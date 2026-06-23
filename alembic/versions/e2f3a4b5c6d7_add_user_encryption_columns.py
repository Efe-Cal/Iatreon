"""add user encryption columns

Revision ID: e2f3a4b5c6d7
Revises: d8aebad3454a
Create Date: 2026-06-22 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd8aebad3454a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('encrypted_data_key', sa.Text(), nullable=True))
    op.add_column('user_profile', sa.Column('encrypted_payload', sa.Text(), nullable=True))
    op.add_column('intake_sessions', sa.Column('encrypted_payload', sa.Text(), nullable=True))
    op.add_column('research_sessions', sa.Column('encrypted_payload', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('research_sessions', 'encrypted_payload')
    op.drop_column('intake_sessions', 'encrypted_payload')
    op.drop_column('user_profile', 'encrypted_payload')
    op.drop_column('users', 'encrypted_data_key')
