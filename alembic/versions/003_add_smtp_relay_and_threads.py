"""Add SMTP relay and conversation thread support

Revision ID: 003
Revises: 002
Create Date: 2026-02-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create conversation_threads table
    op.create_table(
        'conversation_threads',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_thread_customer', 'conversation_threads', ['customer_id'])
    op.create_index('idx_thread_updated', 'conversation_threads', ['updated_at'])

    # 2. Create thread_emails table
    op.create_table(
        'thread_emails',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('thread_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(512), nullable=False),
        sa.Column('in_reply_to', sa.String(512), nullable=True),
        sa.Column('references', sa.Text(), nullable=True),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('from_address', sa.String(255), nullable=False),
        sa.Column('to_addresses', sa.Text(), nullable=False),
        sa.Column('cc_addresses', sa.Text(), nullable=True),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('body_preview', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['thread_id'], ['conversation_threads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id')
    )
    op.create_index('idx_thread_email_message_id', 'thread_emails', ['message_id'])
    op.create_index('idx_thread_email_thread', 'thread_emails', ['thread_id'])
    op.create_index('idx_thread_email_in_reply_to', 'thread_emails', ['in_reply_to'])
    op.create_index('idx_thread_email_direction', 'thread_emails', ['direction'])

    # 3. Create smtp_relay_config table
    op.create_table(
        'smtp_relay_config',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('host', sa.String(255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(255), nullable=False),
        sa.Column('password', sa.String(255), nullable=False),
        sa.Column('use_tls', sa.Boolean(), nullable=True),
        sa.Column('use_ssl', sa.Boolean(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_smtp_relay_enabled', 'smtp_relay_config', ['enabled'])

    # 4. Add new columns to processed_emails
    op.add_column('processed_emails',
        sa.Column('direction', sa.String(10), nullable=True, server_default='incoming'))
    op.add_column('processed_emails',
        sa.Column('to_addresses', sa.Text(), nullable=True))
    op.add_column('processed_emails',
        sa.Column('thread_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_processed_emails_thread', 'processed_emails', 'conversation_threads',
        ['thread_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_processed_emails_thread', 'processed_emails', type_='foreignkey')
    op.drop_column('processed_emails', 'thread_id')
    op.drop_column('processed_emails', 'to_addresses')
    op.drop_column('processed_emails', 'direction')
    op.drop_index('idx_smtp_relay_enabled', table_name='smtp_relay_config')
    op.drop_table('smtp_relay_config')
    op.drop_index('idx_thread_email_direction', table_name='thread_emails')
    op.drop_index('idx_thread_email_in_reply_to', table_name='thread_emails')
    op.drop_index('idx_thread_email_thread', table_name='thread_emails')
    op.drop_index('idx_thread_email_message_id', table_name='thread_emails')
    op.drop_table('thread_emails')
    op.drop_index('idx_thread_updated', table_name='conversation_threads')
    op.drop_index('idx_thread_customer', table_name='conversation_threads')
    op.drop_table('conversation_threads')
