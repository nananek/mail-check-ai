"""SMTP中継サーバー

aiosmtpdを使用してSMTPリレーサーバーを実装。
メールクライアントからの送信メールを受け取り、
AI分析・Gitアーカイブ後に本来のSMTPサーバーへ転送する。
"""
import asyncio
import email
import smtplib
import logging
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime
from typing import Optional, List, Tuple

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from sqlalchemy.orm import Session
from src.database import SessionLocal
from src.models import (
    EmailAddress, Customer, ProcessedEmail, SmtpRelayConfig
)
from src.utils.thread_manager import ThreadManager
from src.utils.git_handler import GitHandler
from src.utils.attachment_parser import AttachmentParser
from src.utils.openai_client import OpenAIClient
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RelayAuthenticator:
    """SMTP中継の認証ハンドラ（DB駆動）

    relay_usernameでDB検索し、設定が存在すれば認証成功。
    パスワードはDB照合せず、転送先SMTPにパススルーする。
    """

    def __call__(self, server, session, envelope, mechanism, auth_data):
        if isinstance(auth_data, LoginPassword):
            username = auth_data.login.decode('utf-8') if isinstance(auth_data.login, bytes) else auth_data.login
            password = auth_data.password.decode('utf-8') if isinstance(auth_data.password, bytes) else auth_data.password
        else:
            return AuthResult(success=False, handled=False)

        # オープン認証モード: DB未登録でも認証を通す（セットアップ・疎通確認用）
        if settings.SMTP_RELAY_OPEN_AUTH:
            logger.info(f"SMTP auth accepted (open auth mode) for user: {username}")
            return AuthResult(success=True, auth_data=(username, password))

        db = SessionLocal()
        try:
            config = db.query(SmtpRelayConfig).filter_by(
                relay_username=username, enabled=True
            ).first()
            if config:
                # usernameとpasswordをセッションに保存（転送時に使用）
                return AuthResult(success=True, auth_data=(username, password))
        finally:
            db.close()

        logger.warning(f"SMTP auth failed for user: {username}")
        return AuthResult(success=False, handled=False)


class RelayHandler:
    """送信メールの受信・処理・転送ハンドラ"""

    def __init__(self):
        self.openai_client = OpenAIClient()

    async def handle_DATA(self, server, session, envelope):
        """送信メールを受信して処理・転送"""
        auth_data = getattr(session, 'auth_data', None)
        relay_username = auth_data[0] if isinstance(auth_data, tuple) else auth_data
        logger.info(f"Received outgoing email from {envelope.mail_from} to {envelope.rcpt_tos} (relay_user={relay_username})")

        try:
            raw_email = envelope.content
            if isinstance(raw_email, bytes):
                msg = email.message_from_bytes(raw_email)
            else:
                msg = email.message_from_string(raw_email)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._process_outgoing_email, msg, envelope
            )

            await loop.run_in_executor(
                None, self._forward_email, envelope, auth_data
            )

            return '250 Message accepted for delivery'

        except Exception as e:
            logger.error(f"Error processing outgoing email: {e}", exc_info=True)
            # 処理失敗でも転送を試みる（メール消失防止）
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._forward_email, envelope, auth_data)
                return '250 Message accepted for delivery'
            except Exception as fwd_err:
                logger.error(f"Failed to forward email: {fwd_err}")
                return '451 Temporary error, please retry'

    def _decode_mime_words(self, s: str) -> str:
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

    def _extract_body(self, msg: email.message.Message) -> str:
        """メール本文を抽出"""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
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

    def _extract_attachments(self, msg: email.message.Message) -> List[Tuple[str, bytes]]:
        """添付ファイルを抽出"""
        attachments = []
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue
            filename = part.get_filename()
            if filename:
                filename = self._decode_mime_words(filename)
                data = part.get_payload(decode=True)
                if data:
                    attachments.append((filename, data))
        return attachments

    def _identify_customer(self, db: Session, to_addresses: list) -> Optional[Tuple[Customer, EmailAddress]]:
        """宛先アドレスからemail_addressesテーブルを照合して顧客を特定（フルアドレス優先、次にドメイン一致）"""
        for addr in to_addresses:
            _, email_addr = parseaddr(addr) if '@' in addr else ('', addr)
            email_record = EmailAddress.resolve(db, email_addr)
            if email_record:
                return email_record.customer, email_record
        return None

    def _process_outgoing_email(self, msg: email.message.Message, envelope) -> None:
        """送信メールを処理: AI分析、Gitアーカイブ、スレッド紐づけ"""
        db = SessionLocal()
        try:
            message_id = msg.get('Message-ID', '')
            in_reply_to = msg.get('In-Reply-To')
            references = msg.get('References')
            subject = self._decode_mime_words(msg.get('Subject', ''))
            from_header = msg.get('From', '')
            _, from_address = parseaddr(from_header)
            to_header = msg.get('To', '')
            cc_header = msg.get('Cc', '')
            date_header = msg.get('Date', '')

            try:
                email_date = parsedate_to_datetime(date_header)
            except:
                email_date = datetime.utcnow()

            # 重複チェック
            if db.query(ProcessedEmail).filter_by(message_id=message_id).first():
                logger.debug(f"Already processed outgoing: {message_id}")
                return

            # 宛先から顧客を特定
            result = self._identify_customer(db, envelope.rcpt_tos)
            if not result:
                logger.info(f"No registered customer found in recipients: {envelope.rcpt_tos}")
                db.add(ProcessedEmail(
                    message_id=message_id,
                    from_address=from_address,
                    to_addresses=to_header,
                    subject=subject,
                    direction='outgoing',
                    processed_at=datetime.utcnow()
                ))
                db.commit()
                return

            customer, email_record = result
            logger.info(f"Outgoing email to customer: {customer.name}")

            # 本文・添付ファイル抽出
            body = self._extract_body(msg)
            attachments = self._extract_attachments(msg)
            attachment_texts = AttachmentParser.extract_from_multiple(attachments)

            # スレッド管理
            thread = ThreadManager.get_or_create_thread(
                db, customer.id, message_id, in_reply_to, references, subject
            )

            # Gitアーカイブ
            commit_hash = None
            archive_path = None
            try:
                git_handler = GitHandler(customer.repo_url, customer.gitea_token, customer.name)
                commit_hash, archive_path = git_handler.save_email_archive(
                    message_id=message_id,
                    email_content=body,
                    attachments=attachments,
                    subject=subject,
                    from_address=to_header,
                    received_date=date_header or datetime.utcnow().isoformat(),
                    direction="sent"
                )
            except Exception as e:
                logger.error(f"Failed to archive outgoing email: {e}")

            # AI分析
            summary = None
            try:
                thread_context = ThreadManager.get_thread_context(db, thread.id)
                analysis = self.openai_client.analyze_outgoing_email(
                    email_body=body,
                    subject=subject,
                    to_address=to_header,
                    attachments_text=attachment_texts,
                    customer_name=customer.name,
                    thread_context=thread_context
                )
                summary = analysis.get('summary', '')
            except Exception as e:
                logger.error(f"Failed to analyze outgoing email: {e}")

            # スレッドにメール追加
            ThreadManager.add_email_to_thread(
                db, thread, message_id, in_reply_to, references,
                direction='outgoing',
                from_address=from_address,
                to_addresses=to_header,
                cc_addresses=cc_header,
                subject=subject,
                body_preview=body,
                summary=summary,
                date=email_date
            )

            # 処理済みとしてマーク
            db.add(ProcessedEmail(
                message_id=message_id,
                customer_id=customer.id,
                from_address=from_address,
                to_addresses=to_header,
                subject=subject,
                direction='outgoing',
                thread_id=thread.id,
                processed_at=datetime.utcnow()
            ))
            db.commit()
            logger.info(f"Successfully processed outgoing email: {message_id}")

        except Exception as e:
            logger.error(f"Error in _process_outgoing_email: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    def _forward_email(self, envelope, auth_data=None) -> None:
        """転送先SMTPサーバーへメールを送信（クライアント認証情報をパススルー）"""
        if not auth_data or not isinstance(auth_data, tuple):
            raise RuntimeError("No authentication data available")

        relay_username, client_password = auth_data

        db = SessionLocal()
        try:
            relay_config = db.query(SmtpRelayConfig).filter_by(
                relay_username=relay_username, enabled=True
            ).first()
            if not relay_config:
                if settings.SMTP_RELAY_OPEN_AUTH:
                    logger.info(f"No relay config for {relay_username}, skipping forward (open auth mode)")
                    return
                logger.error(f"No SMTP relay configuration found for user: {relay_username}")
                raise RuntimeError("No SMTP relay configuration")

            # 転送先ユーザー名: config.usernameがあればそちら、なければクライアントのユーザー名
            smtp_username = relay_config.username or relay_username
            logger.info(f"Forwarding to {relay_config.host}:{relay_config.port} as {smtp_username}")

            if relay_config.use_ssl:
                smtp = smtplib.SMTP_SSL(relay_config.host, relay_config.port, timeout=30)
            else:
                smtp = smtplib.SMTP(relay_config.host, relay_config.port, timeout=30)
                if relay_config.use_tls:
                    smtp.starttls()

            smtp.login(smtp_username, client_password)
            smtp.sendmail(
                envelope.mail_from,
                envelope.rcpt_tos,
                envelope.content
            )
            smtp.quit()
            logger.info("Email forwarded successfully")

        except Exception as e:
            logger.error(f"Failed to forward email: {e}")
            raise
        finally:
            db.close()


def run_smtp_relay():
    """SMTPリレーサーバーを起動"""
    if not settings.SMTP_RELAY_ENABLED:
        logger.info("SMTP relay is disabled. Set SMTP_RELAY_ENABLED=true to enable.")
        return

    handler = RelayHandler()

    controller_kwargs = {
        'handler': handler,
        'hostname': settings.SMTP_RELAY_HOST,
        'port': settings.SMTP_RELAY_PORT,
        'authenticator': RelayAuthenticator(),
        'auth_required': True,
        'auth_require_tls': False,
    }

    # TLS設定
    if settings.SMTP_RELAY_USE_STARTTLS and settings.SMTP_RELAY_TLS_CERT:
        import ssl
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(settings.SMTP_RELAY_TLS_CERT, settings.SMTP_RELAY_TLS_KEY)
        controller_kwargs['tls_context'] = context

    controller = Controller(**controller_kwargs)
    controller.start()
    logger.info(f"SMTP relay server started on {settings.SMTP_RELAY_HOST}:{settings.SMTP_RELAY_PORT}")

    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        controller.stop()
        logger.info("SMTP relay server stopped")


if __name__ == "__main__":
    run_smtp_relay()
