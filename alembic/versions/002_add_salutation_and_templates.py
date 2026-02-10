"""Add salutation to email_addresses and greeting/signature settings

Revision ID: 002
Revises: 001
Create Date: 2026-02-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add salutation column to email_addresses table
    op.add_column(
        'email_addresses',
        sa.Column('salutation', sa.String(length=500), nullable=True, comment='標準の宛名')
    )
    
    # Insert default greeting and signature settings into system_settings
    op.execute("""
        INSERT INTO system_settings (key, value, updated_at)
        VALUES 
            ('greeting_template', 'いつもお世話になっております。', CURRENT_TIMESTAMP),
            ('signature_template', '', CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Remove salutation column from email_addresses
    op.drop_column('email_addresses', 'salutation')
    
    # Remove greeting and signature settings
    op.execute("""
        DELETE FROM system_settings 
        WHERE key IN ('greeting_template', 'signature_template')
    """)
