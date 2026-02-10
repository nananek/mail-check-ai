from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

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
    drafts = relationship('DraftQueue', back_populates='customer', cascade='all, delete-orphan')


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
    processed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_processed_at', 'processed_at'),
    )


class DraftQueue(Base):
    """返信下書きキューテーブル"""
    __tablename__ = 'draft_queue'

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    message_id = Column(String(512), nullable=False, comment='元メールのMessage-ID')
    reply_draft = Column(Text, nullable=False, comment='AI生成の返信案')
    summary = Column(Text, nullable=False, comment='メール要約')
    issue_title = Column(String(500), nullable=True, comment='作成されたIssueのタイトル')
    issue_url = Column(Text, nullable=True, comment='作成されたIssueのURL')
    status = Column(String(50), default='pending', comment='pending / sent / archived')
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # リレーションシップ
    customer = relationship('Customer', back_populates='drafts')

    __table_args__ = (
        Index('idx_customer_status', 'customer_id', 'status'),
    )


class SystemSetting(Base):
    """システム設定テーブル"""
    __tablename__ = 'system_settings'

    key = Column(String(255), primary_key=True, comment='設定キー')
    value = Column(Text, nullable=True, comment='設定値')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
