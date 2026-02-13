"""会話スレッド管理モジュール

Message-ID / In-Reply-To / References ヘッダーに基づいて
受信・送信メールを会話スレッドに紐づける。
"""
import re
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from src.models import ConversationThread, ThreadEmail

logger = logging.getLogger(__name__)


class ThreadManager:
    """会話スレッド管理クラス"""

    # Re:/Fwd: 等のプレフィクスパターン
    SUBJECT_PREFIX_RE = re.compile(
        r'^(Re|RE|Fwd|FWD|Fw|FW|返信|転送)\s*[:：]\s*', re.IGNORECASE
    )

    @staticmethod
    def normalize_subject(subject: str) -> str:
        """件名からRe:/Fwd:等のプレフィクスを除去して正規化"""
        if not subject:
            return ""
        normalized = subject.strip()
        while True:
            new = ThreadManager.SUBJECT_PREFIX_RE.sub('', normalized).strip()
            if new == normalized:
                break
            normalized = new
        return normalized

    @staticmethod
    def find_thread(
        db: Session,
        customer_id: int,
        message_id: str,
        in_reply_to: Optional[str],
        references: Optional[str],
        subject: str
    ) -> Optional[ConversationThread]:
        """
        既存スレッドを検索する（3段階）:
        1. In-Reply-To → ThreadEmail.message_id マッチ
        2. References内の各ID → ThreadEmail.message_id マッチ
        3. 正規化subject + customer_id のフォールバック
        """
        # 1. In-Reply-To
        if in_reply_to:
            existing = db.query(ThreadEmail).filter_by(message_id=in_reply_to.strip()).first()
            if existing:
                logger.info(f"Thread found via In-Reply-To: thread_id={existing.thread_id}")
                return existing.thread

        # 2. References
        if references:
            ref_ids = references.strip().split()
            for ref_id in ref_ids:
                existing = db.query(ThreadEmail).filter_by(message_id=ref_id.strip()).first()
                if existing:
                    logger.info(f"Thread found via References: thread_id={existing.thread_id}")
                    return existing.thread

        # 3. Subject フォールバック
        normalized = ThreadManager.normalize_subject(subject)
        if normalized:
            thread = db.query(ConversationThread).filter_by(
                customer_id=customer_id,
                subject=normalized
            ).order_by(ConversationThread.updated_at.desc()).first()
            if thread:
                logger.info(f"Thread found via subject match: thread_id={thread.id}")
                return thread

        return None

    @staticmethod
    def get_or_create_thread(
        db: Session,
        customer_id: int,
        message_id: str,
        in_reply_to: Optional[str],
        references: Optional[str],
        subject: str
    ) -> ConversationThread:
        """既存スレッドを検索し、なければ新規作成"""
        thread = ThreadManager.find_thread(
            db, customer_id, message_id, in_reply_to, references, subject
        )

        if thread:
            thread.updated_at = datetime.utcnow()
            return thread

        normalized_subject = ThreadManager.normalize_subject(subject)
        thread = ConversationThread(
            customer_id=customer_id,
            subject=normalized_subject,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(thread)
        db.flush()
        logger.info(f"Created new thread: id={thread.id}, subject='{normalized_subject}'")
        return thread

    @staticmethod
    def add_email_to_thread(
        db: Session,
        thread: ConversationThread,
        message_id: str,
        in_reply_to: Optional[str],
        references: Optional[str],
        direction: str,
        from_address: str,
        to_addresses: str,
        cc_addresses: Optional[str],
        subject: str,
        body_preview: str,
        summary: Optional[str],
        date: datetime
    ) -> ThreadEmail:
        """メールをスレッドに追加"""
        existing = db.query(ThreadEmail).filter_by(message_id=message_id).first()
        if existing:
            logger.debug(f"Email already in thread: {message_id}")
            return existing

        thread_email = ThreadEmail(
            thread_id=thread.id,
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
            direction=direction,
            from_address=from_address,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            subject=subject,
            body_preview=body_preview[:500] if body_preview else None,
            summary=summary,
            date=date,
            processed_at=datetime.utcnow()
        )
        db.add(thread_email)
        thread.updated_at = datetime.utcnow()
        logger.info(f"Added {direction} email to thread {thread.id}: {message_id}")
        return thread_email

    @staticmethod
    def get_thread_context(db: Session, thread_id: int, max_emails: int = 10) -> List[Dict[str, Any]]:
        """AI分析用の会話コンテキストを取得（最新max_emails件を時系列順で返す）"""
        emails = db.query(ThreadEmail).filter_by(
            thread_id=thread_id
        ).order_by(ThreadEmail.date.desc()).limit(max_emails).all()

        emails.reverse()

        context = []
        for e in emails:
            context.append({
                'direction': e.direction,
                'from': e.from_address,
                'to': e.to_addresses,
                'subject': e.subject,
                'date': e.date.isoformat() if e.date else '',
                'body_preview': e.body_preview or '',
                'summary': e.summary or ''
            })
        return context
