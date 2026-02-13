import poplib
import email
from email.header import decode_header
from email.utils import parseaddr
import time
import logging
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
import requests

from sqlalchemy.orm import Session
from src.database import SessionLocal
from src.models import MailAccount, EmailAddress, ProcessedEmail, Customer, DraftQueue, SystemSetting
from src.utils.git_handler import GitHandler
from src.utils.attachment_parser import AttachmentParser
from src.utils.openai_client import OpenAIClient
from src.utils.thread_manager import ThreadManager
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

                # スレッド用ヘッダ抽出
                in_reply_to = msg.get('In-Reply-To')
                references_header = msg.get('References')
                to_header = msg.get('To', '')
                cc_header = msg.get('Cc', '')

                # スレッド管理
                thread = ThreadManager.get_or_create_thread(
                    db, customer.id, message_id, in_reply_to, references_header, subject
                )
                thread_context = ThreadManager.get_thread_context(db, thread.id)

                # 全添付ファイルからテキスト抽出
                attachment_texts = AttachmentParser.extract_from_multiple(attachments)

                # Gitへ保存
                commit_hash = None
                archive_path = None
                try:
                    git_handler = GitHandler(customer.repo_url, customer.gitea_token, customer.name)
                    commit_hash, archive_path = git_handler.save_email_archive(
                        message_id=message_id,
                        email_content=body,
                        attachments=attachments,
                        subject=subject,
                        from_address=from_address,
                        received_date=received_date,
                        direction="received"
                    )
                    logger.info(f"Saved to Git: {commit_hash} at {archive_path}")
                except Exception as e:
                    logger.error(f"Failed to save to Git: {e}")

                # AI解析
                try:
                    # 書き出し文と署名を取得
                    greeting_setting = db.query(SystemSetting).filter_by(key='greeting_template').first()
                    greeting_template = greeting_setting.value if greeting_setting and greeting_setting.value else 'いつもお世話になっております。'

                    signature_setting = db.query(SystemSetting).filter_by(key='signature_template').first()
                    signature_template = signature_setting.value if signature_setting and signature_setting.value else ''

                    analysis = self.openai_client.analyze_email(
                        email_body=body,
                        subject=subject,
                        from_address=from_address,
                        attachments_text=attachment_texts,
                        customer_name=customer.name,
                        salutation=email_record.salutation,
                        greeting_template=greeting_template,
                        signature_template=signature_template,
                        thread_context=thread_context
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
                    
                    # 既存のissueを取得
                    existing_issues = self.get_existing_issues(
                        repo_url=customer.repo_url,
                        token=customer.gitea_token
                    )
                    
                    # 各トピックに対してIssueを作成
                    topics = analysis.get('topics', [])
                    issue_urls = []
                    
                    for topic in topics:
                        topic_title = topic.get('title', '')
                        topic_body = topic.get('body', '')
                        
                        # 関連issueを検索
                        related_issues = self.find_related_issues(
                            topic_title=topic_title,
                            topic_body=topic_body,
                            existing_issues=existing_issues
                        )
                        
                        # Gitea Issueを作成
                        issue_url = self.create_gitea_issue(
                            repo_url=customer.repo_url,
                            token=customer.gitea_token,
                            title=topic_title,
                            body=topic_body,
                            commit_hash=commit_hash,
                            archive_path=archive_path,
                            related_issues=related_issues
                        )
                        
                        if issue_url:
                            issue_urls.append(issue_url)
                    
                    # 下書きキューに保存
                    draft = DraftQueue(
                        customer_id=customer.id,
                        message_id=message_id,
                        reply_draft=analysis['reply_draft'],
                        summary=analysis['summary'],
                        issue_title=f"{len(topics)}件のトピック処理完了" if len(topics) > 1 else topics[0].get('title', ''),
                        issue_url=', '.join(issue_urls) if issue_urls else None,
                        status='pending'
                    )
                    db.add(draft)
                    
                    # スレッドにメール追加
                    try:
                        from email.utils import parsedate_to_datetime
                        email_date = parsedate_to_datetime(received_date)
                    except:
                        email_date = datetime.utcnow()

                    ThreadManager.add_email_to_thread(
                        db, thread, message_id, in_reply_to, references_header,
                        direction='incoming',
                        from_address=from_address,
                        to_addresses=to_header,
                        cc_addresses=cc_header,
                        subject=subject,
                        body_preview=body,
                        summary=analysis.get('summary', ''),
                        date=email_date
                    )

                except Exception as e:
                    logger.error(f"Failed to analyze email: {e}")

                # 処理済みとしてマーク
                db.add(ProcessedEmail(
                    message_id=message_id,
                    customer_id=customer.id,
                    from_address=from_address,
                    subject=subject,
                    direction='incoming',
                    to_addresses=to_header,
                    thread_id=thread.id,
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
    
    def get_existing_issues(
        self,
        repo_url: str,
        token: str
    ) -> List[Dict[str, Any]]:
        """リポジトリの既存Issueを取得"""
        try:
            if repo_url.endswith('.git'):
                repo_url = repo_url[:-4]
            
            parts = repo_url.replace('https://', '').replace('http://', '').split('/')
            base_url = f"https://{parts[0]}"
            owner = parts[1]
            repo = parts[2]
            
            # オープンなissueを取得（最大100件）
            api_url = f"{base_url}/api/v1/repos/{owner}/{repo}/issues"
            
            headers = {
                "Authorization": f"token {token}",
                "Content-Type": "application/json"
            }
            
            params = {
                "state": "open",
                "page": 1,
                "limit": 100
            }
            
            response = requests.get(api_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            issues = response.json()
            logger.info(f"Retrieved {len(issues)} existing issues")
            return issues
        
        except Exception as e:
            logger.error(f"Failed to get existing issues: {e}")
            return []
    
    def find_related_issues(
        self,
        topic_title: str,
        topic_body: str,
        existing_issues: List[Dict[str, Any]]
    ) -> List[str]:
        """関連するissueを見つける（簡易的なキーワードマッチング）"""
        related = []
        
        # トピックから重要なキーワードを抽出（簡易版）
        keywords = set()
        for word in topic_title.split():
            if len(word) > 2:  # 3文字以上
                keywords.add(word.lower())
        
        for issue in existing_issues:
            issue_title = issue.get('title', '').lower()
            issue_body = issue.get('body', '').lower()
            
            # キーワードがissueのタイトルまたは本文に含まれるかチェック
            matches = sum(1 for kw in keywords if kw in issue_title or kw in issue_body)
            
            # 3つ以上のキーワードが一致したら関連とみなす
            if matches >= min(3, len(keywords)):
                related.append(issue.get('html_url', ''))
        
        return related[:5]  # 最大5件
    
    def create_gitea_issue(
        self,
        repo_url: str,
        token: str,
        title: str,
        body: str,
        commit_hash: Optional[str] = None,
        archive_path: Optional[str] = None,
        related_issues: Optional[List[str]] = None
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
            
            # Issue本文にcommitリンクと関連issueを追加
            enhanced_body = body
            
            if commit_hash and archive_path:
                commit_url = f"{repo_url}/commit/{commit_hash}"
                archive_url = f"{repo_url}/src/commit/{commit_hash}/{archive_path}"
                enhanced_body += f"\n\n---\n\n**📎 メールアーカイブ:**\n"
                enhanced_body += f"- [コミット]({commit_url})\n"
                enhanced_body += f"- [アーカイブフォルダ]({archive_url})\n"
            
            if related_issues:
                enhanced_body += f"\n\n**🔗 関連Issue:**\n"
                for issue_url in related_issues:
                    enhanced_body += f"- {issue_url}\n"
            
            api_url = f"{base_url}/api/v1/repos/{owner}/{repo}/issues"
            
            headers = {
                "Authorization": f"token {token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "title": title,
                "body": enhanced_body
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
