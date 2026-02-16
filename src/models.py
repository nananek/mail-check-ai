from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship

Base = declarative_base()


class Customer(Base):
    """顧客情報テーブル"""
    __tablename__ = 'customers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    repo_url = Column(Text, nullable=False, comment='Gitea リポジトリURL')
    gitea_token = Column(String(255), nullable=False, comment='Gitea API トークン')
    discord_webhook = Column(Text, nullable=True, comment='顧客専用Discord Webhook URL（オプション）')
    created_at = Column(DateTime, default=datetime.utcnow)

    # リレーションシップ
    email_addresses = relationship('EmailAddress', back_populates='customer', cascade='all, delete-orphan')
    threads = relationship('ConversationThread', back_populates='customer', cascade='all, delete-orphan')


class EmailAddress(Base):
    """顧客メールアドレス（ホワイトリスト）テーブル"""
    __tablename__ = 'email_addresses'

    email = Column(String(255), primary_key=True, comment='メールアドレス（正規化済み）')
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    salutation = Column(String(500), nullable=True, comment='標準の宛名（例: 株式会社ABC 伊呂波社長様）')
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # リレーションシップ
    customer = relationship('Customer', back_populates='email_addresses')

    __table_args__ = (
        Index('idx_email_customer', 'email', 'customer_id'),
    )

    @classmethod
    def resolve(cls, db: Session, email_addr: str) -> Optional["EmailAddress"]:
        """メールアドレスを解決する（フルアドレス優先、次にドメイン一致）"""
        email_addr = email_addr.lower().strip()
        # フルアドレス完全一致
        record = db.query(cls).filter_by(email=email_addr).first()
        if record:
            return record
        # ドメイン一致（@domain.com 形式のエントリ）
        domain = email_addr.split("@", 1)[-1] if "@" in email_addr else None
        if domain:
            record = db.query(cls).filter_by(email=f"@{domain}").first()
        return record


class MailAccount(Base):
    """POP3メールアカウント設定テーブル"""
    __tablename__ = 'mail_accounts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=110)
    username = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)
    use_ssl = Column(Boolean, default=False, comment='SSL/TLS使用フラグ')
    enabled = Column(Boolean, default=True, comment='有効/無効フラグ')
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_enabled', 'enabled'),
    )


class ProcessedEmail(Base):
    """処理済みメールID（重複排除）テーブル"""
    __tablename__ = 'processed_emails'

    message_id = Column(String(512), primary_key=True, comment='Message-ID ヘッダー')
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='SET NULL'), nullable=True)
    from_address = Column(String(255), nullable=True)
    subject = Column(Text, nullable=True)
    direction = Column(String(10), default='incoming', comment='incoming / outgoing')
    to_addresses = Column(Text, nullable=True, comment='宛先アドレス')
    thread_id = Column(Integer, ForeignKey('conversation_threads.id', ondelete='SET NULL'), nullable=True)
    processed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_processed_at', 'processed_at'),
    )


class SystemSetting(Base):
    """システム設定テーブル"""
    __tablename__ = 'system_settings'

    key = Column(String(255), primary_key=True, comment='設定キー')
    value = Column(Text, nullable=True, comment='設定値')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationThread(Base):
    """会話スレッドテーブル"""
    __tablename__ = 'conversation_threads'

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    subject = Column(Text, nullable=True, comment='正規化された件名 (Re:/Fwd: 除去)')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship('Customer', back_populates='threads')
    emails = relationship('ThreadEmail', back_populates='thread',
                          order_by='ThreadEmail.date', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_thread_customer', 'customer_id'),
        Index('idx_thread_updated', 'updated_at'),
    )


class ThreadEmail(Base):
    """スレッド内メールテーブル"""
    __tablename__ = 'thread_emails'

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(Integer, ForeignKey('conversation_threads.id', ondelete='CASCADE'), nullable=False)
    message_id = Column(String(512), nullable=False, unique=True, comment='Message-ID ヘッダー')
    in_reply_to = Column(String(512), nullable=True, comment='In-Reply-To ヘッダー')
    references = Column(Text, nullable=True, comment='References ヘッダー (space-separated)')
    direction = Column(String(10), nullable=False, comment='incoming / outgoing')
    from_address = Column(String(255), nullable=False)
    to_addresses = Column(Text, nullable=False, comment='カンマ区切りの宛先')
    cc_addresses = Column(Text, nullable=True, comment='カンマ区切りのCC')
    subject = Column(Text, nullable=True)
    body_preview = Column(Text, nullable=True, comment='本文の先頭500文字')
    summary = Column(Text, nullable=True, comment='AI生成要約')
    date = Column(DateTime, nullable=False, comment='メールのDateヘッダー')
    processed_at = Column(DateTime, default=datetime.utcnow)

    thread = relationship('ConversationThread', back_populates='emails')

    __table_args__ = (
        Index('idx_thread_email_message_id', 'message_id'),
        Index('idx_thread_email_thread', 'thread_id'),
        Index('idx_thread_email_in_reply_to', 'in_reply_to'),
        Index('idx_thread_email_direction', 'direction'),
    )


class PendingDiscordNotification(Base):
    """業務時間外に保留されたDiscord通知"""
    __tablename__ = 'pending_discord_notifications'

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_url = Column(Text, nullable=False, comment='Discord Webhook URL')
    payload = Column(Text, nullable=False, comment='通知ペイロード (JSON)')
    created_at = Column(DateTime, default=datetime.utcnow)


class ThreadIssue(Base):
    """スレッドに紐づくGitea Issue"""
    __tablename__ = 'thread_issues'

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(Integer, ForeignKey('conversation_threads.id', ondelete='CASCADE'), nullable=False)
    issue_url = Column(Text, nullable=False, comment='Gitea Issue URL')
    issue_number = Column(Integer, nullable=False, comment='Issue番号（APIコール用）')
    created_at = Column(DateTime, default=datetime.utcnow)

    thread = relationship('ConversationThread', backref='issues')

    __table_args__ = (
        Index('idx_thread_issue_thread', 'thread_id'),
    )


class SmtpRelayConfig(Base):
    """SMTP中継設定テーブル"""
    __tablename__ = 'smtp_relay_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, comment='設定名')
    relay_username = Column(String(255), nullable=False, unique=True, comment='メールクライアントのログインユーザー名（メールアドレス）')
    host = Column(String(255), nullable=False, comment='転送先SMTPホスト')
    port = Column(Integer, nullable=False, default=587, comment='転送先SMTPポート')
    username = Column(String(255), nullable=True, comment='転送先SMTP認証ユーザー名（省略時はrelay_usernameを使用）')
    use_tls = Column(Boolean, default=True, comment='STARTTLS使用フラグ')
    use_ssl = Column(Boolean, default=False, comment='SSL/TLS使用フラグ')
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_smtp_relay_enabled', 'enabled'),
    )
