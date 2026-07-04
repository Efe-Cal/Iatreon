"""add jwt auth sessions

Revision ID: 9f8e7d6c5b4a
Revises: 7dc4a6d8582f
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9f8e7d6c5b4a'
down_revision: Union[str, Sequence[str], None] = '7dc4a6d8582f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_hash', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('session_key_salt', sa.String(), nullable=True))
    op.alter_column('users', 'ssh_key', existing_type=sa.Text(), nullable=True)
    op.execute("UPDATE users SET ssh_key = NULL WHERE ssh_key = ''")
    op.create_table(
        'auth_sessions',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('refresh_token_hash', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_auth_sessions_user_id', table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.execute("UPDATE users SET ssh_key = id::text WHERE ssh_key IS NULL")
    op.alter_column('users', 'ssh_key', existing_type=sa.Text(), nullable=False)
    op.drop_column('users', 'session_key_salt')
    op.drop_column('users', 'password_hash')
