"""Simplify SMTP relay credentials - passthrough client auth

Revision ID: 007
Revises: 006
Create Date: 2026-02-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('smtp_relay_config', 'relay_password')
    op.drop_column('smtp_relay_config', 'password')
    op.alter_column('smtp_relay_config', 'username', nullable=True)


def downgrade() -> None:
    op.alter_column('smtp_relay_config', 'username', nullable=False)
    op.add_column('smtp_relay_config', sa.Column('password', sa.String(255), nullable=False, server_default='changeme'))
    op.add_column('smtp_relay_config', sa.Column('relay_password', sa.String(255), nullable=False, server_default='changeme'))
