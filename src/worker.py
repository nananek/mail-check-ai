import poplib
import email
from email.header import decode_header
from email.utils import parseaddr
import time
import logging
from datetime import datetime
from typing import List, Tuple, Optional
import requests

from sqlalchemy.orm import Session
from src.database import SessionLocal
from src.models import MailAccount, EmailAddress, ProcessedEmail, Customer, DraftQueue
from src.utils.git_handler import GitHandler
from src.utils.pdf_parser import PDFParser
from src.utils.openai_client import OpenAIClient
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmailWorker:
    """POP3メール監視・処理ワーカー"""
    
    def __init__(self):
        self.openai_client = OpenAIClient()
    
    def decode_mime_words(self, s: str) -> str:
        """MIMEエンコードされた文字列をデコード"""
        if not s:
            return ""
        decoded_parts = []
        for word, encoding in decode_header(s):
            if isinstance(word, bytes):
                decoded_parts.append(word.decode(encoding or 'utf-8', errors='ignore'))
            else:
                decoded_parts.append(word)
        return ''.join(decoded_parts)
    
    def extract_email_body(self, msg: email.message.Message) -> str:
        """メール本文を抽出"""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    charset = part.get_content_charset() or 'utf-8'
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode(charset, errors='ignore') + "\n"
        else:
            charset = msg.get_content_charset() or 'utf-8'
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(charset, errors='ignore')
        return body.strip()
    
    def extract_attachments(self, msg: email.message.Message) -> List[Tuple[str, bytes]]:
        """添付ファイルを抽出"""
        attachments = []
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue
            
            filename = part.get_filename()
            if filename:
                filename = self.decode_mime_words(filename)
                data = part.get_payload(decode=True)
                if data:
                    attachments.append((filename, data))
        return attachments
    
    def check_mail_account(self, db: Session, account: MailAccount) -> None:
        """単一のPOP3アカウントをチェック"""
        logger.info(f"Checking account: {account.username}@{account.host}")
        
        try:
            # POP3接続
            if account.use_ssl:
                pop = poplib.POP3_SSL(account.host, account.port)
            else:
                pop = poplib.POP3(account.host, account.port)
            
            pop.user(account.username)
            pop.pass_(account.password)
            
            # メール数を取得
            num_messages = len(pop.list()[1])
            logger.info(f"Found {num_messages} messages")
            
            for i in range(1, num_messages + 1):
                # メッセージを取得（サーバーからは削除しない）
                response, lines, octets = pop.retr(i)
                raw_email = b'\n'.join(lines)
                msg = email.message_from_bytes(raw_email)
                
                # Message-IDを取得
                message_id = msg.get('Message-ID', f'<generated-{i}@{account.host}>')
                
                # 重複チェック
                if db.query(ProcessedEmail).filter_by(message_id=message_id).first():
                    logger.debug(f"Already processed: {message_id}")
                    continue
                
                # 送信元アドレスを取得
                from_header = msg.get('From', '')
                from_name, from_address = parseaddr(from_header)
                from_address = from_address.lower()
                
                # ★ ホワイトリストチェック（未登録は完全無視）
                email_record = db.query(EmailAddress).filter_by(email=from_address).first()
                if not email_record:
                    logger.info(f"Ignoring email from unregistered address: {from_address}")
                    # 処理済みとしてマークして次回スキップ
                    db.add(ProcessedEmail(
                        message_id=message_id,
                        from_address=from_address,
                        subject=self.decode_mime_words(msg.get('Subject', '')),
                        processed_at=datetime.utcnow()
                    ))
                    db.commit()
                    continue
                
                # 顧客情報を取得
                customer = email_record.customer
                logger.info(f"Processing email for customer: {customer.name}")
                
                # メール情報を抽出
                subject = self.decode_mime_words(msg.get('Subject', ''))
                body = self.extract_email_body(msg)
                attachments = self.extract_attachments(msg)
                received_date = msg.get('Date', datetime.utcnow().isoformat())
                
                # PDFファイルからテキスト抽出
                pdf_files = [(name, data) for name, data in attachments if name.lower().endswith('.pdf')]
                pdf_texts = PDFParser.extract_text_from_multiple(pdf_files)
                
                # Gitへ保存
                try:
                    git_handler = GitHandler(customer.repo_url, customer.gitea_token, customer.name)
                    commit_hash = git_handler.save_email_archive(
                        message_id=message_id,
                        email_content=body,
                        attachments=attachments,
                        subject=subject,
                        from_address=from_address,
                        received_date=received_date
                    )
                    logger.info(f"Saved to Git: {commit_hash}")
                except Exception as e:
                    logger.error(f"Failed to save to Git: {e}")
                    # Git保存失敗時でも続行（処理済みとしてマーク）
                
                # AI解析
                try:
                    analysis = self.openai_client.analyze_email(
                        email_body=body,
                        subject=subject,
                        from_address=from_address,
                        attachments_text=pdf_texts,
                        customer_name=customer.name
                    )
                    
                    # Discordへ通知
                    webhook_url = customer.discord_webhook or settings.DISCORD_WEBHOOK_URL
                    if webhook_url:
                        self.send_discord_notification(
                            webhook_url=webhook_url,
                            customer_name=customer.name,
                            from_address=from_address,
                            subject=subject,
                            summary=analysis['summary']
                        )
                    
                    # Gitea Issueを作成
                    issue_url = self.create_gitea_issue(
                        repo_url=customer.repo_url,
                        token=customer.gitea_token,
                        title=analysis['issue_title'],
                        body=analysis['issue_body']
                    )
                    
                    # 下書きキューに保存
                    draft = DraftQueue(
                        customer_id=customer.id,
                        message_id=message_id,
                        reply_draft=analysis['reply_draft'],
                        summary=analysis['summary'],
                        issue_title=analysis['issue_title'],
                        issue_url=issue_url,
                        status='pending'
                    )
                    db.add(draft)
                    
                except Exception as e:
                    logger.error(f"Failed to analyze email: {e}")
                
                # 処理済みとしてマーク
                db.add(ProcessedEmail(
                    message_id=message_id,
                    customer_id=customer.id,
                    from_address=from_address,
                    subject=subject,
                    processed_at=datetime.utcnow()
                ))
                db.commit()
                logger.info(f"Successfully processed: {message_id}")
            
            pop.quit()
        
        except Exception as e:
            logger.error(f"Error checking account {account.username}@{account.host}: {e}")
            db.rollback()
    
    def send_discord_notification(
        self,
        webhook_url: str,
        customer_name: str,
        from_address: str,
        subject: str,
        summary: str
    ) -> None:
        """Discordへ通知"""
        try:
            payload = {
                "embeds": [{
                    "title": f"📧 新着メール: {customer_name}",
                    "color": 3447003,
                    "fields": [
                        {"name": "送信者", "value": from_address, "inline": False},
                        {"name": "件名", "value": subject, "inline": False},
                        {"name": "要約", "value": summary, "inline": False}
                    ],
                    "timestamp": datetime.utcnow().isoformat()
                }]
            }
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Discord notification sent")
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
    
    def create_gitea_issue(
        self,
        repo_url: str,
        token: str,
        title: str,
        body: str
    ) -> Optional[str]:
        """Gitea Issueを作成"""
        try:
            # repo_url例: https://gitea.example.com/owner/repo.git
            # API URL: https://gitea.example.com/api/v1/repos/owner/repo/issues
            
            if repo_url.endswith('.git'):
                repo_url = repo_url[:-4]
            
            parts = repo_url.replace('https://', '').replace('http://', '').split('/')
            base_url = f"https://{parts[0]}"
            owner = parts[1]
            repo = parts[2]
            
            api_url = f"{base_url}/api/v1/repos/{owner}/{repo}/issues"
            
            headers = {
                "Authorization": f"token {token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "title": title,
                "body": body
            }
            
            response = requests.post(api_url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            issue_data = response.json()
            issue_url = issue_data.get('html_url')
            logger.info(f"Created Gitea issue: {issue_url}")
            return issue_url
        
        except Exception as e:
            logger.error(f"Failed to create Gitea issue: {e}")
            return None
    
    def run(self) -> None:
        """メインループ"""
        logger.info("Email Worker started")
        
        while True:
            try:
                db = SessionLocal()
                
                # 有効なメールアカウントを取得
                accounts = db.query(MailAccount).filter_by(enabled=True).all()
                
                if not accounts:
                    logger.warning("No enabled mail accounts found")
                else:
                    for account in accounts:
                        self.check_mail_account(db, account)
                
                db.close()
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
            
            logger.info(f"Sleeping for {settings.POLL_INTERVAL} seconds...")
            time.sleep(settings.POLL_INTERVAL)


if __name__ == "__main__":
    worker = EmailWorker()
    worker.run()
