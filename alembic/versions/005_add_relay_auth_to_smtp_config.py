"""Add relay_username and relay_password to smtp_relay_config

Revision ID: 005
Revises: 004
Create Date: 2026-02-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('smtp_relay_config', sa.Column('relay_username', sa.String(255), nullable=True))
    op.add_column('smtp_relay_config', sa.Column('relay_password', sa.String(255), nullable=True))

    # 既存レコードにusernameをコピーしてデフォルト値とする
    op.execute("UPDATE smtp_relay_config SET relay_username = username, relay_password = 'changeme' WHERE relay_username IS NULL")

    op.alter_column('smtp_relay_config', 'relay_username', nullable=False)
    op.alter_column('smtp_relay_config', 'relay_password', nullable=False)
    op.create_index('idx_smtp_relay_username', 'smtp_relay_config', ['relay_username'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_smtp_relay_username', table_name='smtp_relay_config')
    op.drop_column('smtp_relay_config', 'relay_password')
    op.drop_column('smtp_relay_config', 'relay_username')
