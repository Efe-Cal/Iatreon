"""add diagnosis sessions

Revision ID: 7dc4a6d8582f
Revises: c84f6e2b9a73
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7dc4a6d8582f'
down_revision: Union[str, Sequence[str], None] = 'c84f6e2b9a73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'diagnosis_sessions',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('encrypted_payload', sa.Text(), nullable=True),
        sa.Column('intake_session_id', sa.Uuid(), nullable=False),
        sa.Column('chat_session_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['chat_session_id'], ['chat_sessions.id']),
        sa.ForeignKeyConstraint(['intake_session_id'], ['intake_sessions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('diagnosis_sessions')
