"""Initial migration - create all tables

Revision ID: 001
Revises: 
Create Date: 2026-02-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create customers table
    op.create_table(
        'customers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('repo_url', sa.Text(), nullable=False),
        sa.Column('gitea_token', sa.String(length=255), nullable=False),
        sa.Column('discord_webhook', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Create email_addresses table
    op.create_table(
        'email_addresses',
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('email')
    )
    op.create_index('idx_email_customer', 'email_addresses', ['email', 'customer_id'], unique=False)

    # Create mail_accounts table
    op.create_table(
        'mail_accounts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('password', sa.String(length=255), nullable=False),
        sa.Column('use_ssl', sa.Boolean(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_enabled', 'mail_accounts', ['enabled'], unique=False)

    # Create processed_emails table
    op.create_table(
        'processed_emails',
        sa.Column('message_id', sa.String(length=512), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('from_address', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('message_id')
    )
    op.create_index('idx_processed_at', 'processed_emails', ['processed_at'], unique=False)

    # Create draft_queue table
    op.create_table(
        'draft_queue',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(length=512), nullable=False),
        sa.Column('reply_draft', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('issue_title', sa.String(length=500), nullable=True),
        sa.Column('issue_url', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_customer_status', 'draft_queue', ['customer_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_customer_status', table_name='draft_queue')
    op.drop_table('draft_queue')
    op.drop_index('idx_processed_at', table_name='processed_emails')
    op.drop_table('processed_emails')
    op.drop_index('idx_enabled', table_name='mail_accounts')
    op.drop_table('mail_accounts')
    op.drop_index('idx_email_customer', table_name='email_addresses')
    op.drop_table('email_addresses')
    op.drop_table('customers')
