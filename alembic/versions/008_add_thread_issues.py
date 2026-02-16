"""Add thread_issues table for tracking Gitea issues per thread

Revision ID: 008
Revises: 007
Create Date: 2026-02-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'thread_issues',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('thread_id', sa.Integer(), sa.ForeignKey('conversation_threads.id', ondelete='CASCADE'), nullable=False),
        sa.Column('issue_url', sa.Text(), nullable=False),
        sa.Column('issue_number', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_thread_issue_thread', 'thread_issues', ['thread_id'])


def downgrade() -> None:
    op.drop_index('idx_thread_issue_thread', table_name='thread_issues')
    op.drop_table('thread_issues')
