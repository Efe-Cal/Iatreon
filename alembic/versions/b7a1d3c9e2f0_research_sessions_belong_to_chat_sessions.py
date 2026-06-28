"""research sessions belong to chat sessions

Revision ID: b7a1d3c9e2f0
Revises: e929d8b95384
Create Date: 2026-06-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7a1d3c9e2f0'
down_revision: Union[str, Sequence[str], None] = 'e929d8b95384'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('research_sessions', sa.Column('chat_session_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'research_sessions_chat_session_id_fkey',
        'research_sessions',
        'chat_sessions',
        ['chat_session_id'],
        ['id'],
    )
    op.execute("""
        UPDATE research_sessions AS rs
        SET chat_session_id = cs.id
        FROM chat_sessions AS cs
        WHERE cs.research_session_id = rs.id
    """)
    op.drop_constraint('chat_sessions_research_session_id_fkey', 'chat_sessions', type_='foreignkey')
    op.drop_column('chat_sessions', 'research_session_id')
    op.drop_constraint('research_sessions_intake_session_id_fkey', 'research_sessions', type_='foreignkey')
    op.drop_column('research_sessions', 'intake_session_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('research_sessions', sa.Column('intake_session_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'research_sessions_intake_session_id_fkey',
        'research_sessions',
        'intake_sessions',
        ['intake_session_id'],
        ['id'],
    )
    op.add_column('chat_sessions', sa.Column('research_session_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'chat_sessions_research_session_id_fkey',
        'chat_sessions',
        'research_sessions',
        ['research_session_id'],
        ['id'],
    )
    op.execute("""
        UPDATE research_sessions AS rs
        SET intake_session_id = cs.intake_session_id
        FROM chat_sessions AS cs
        WHERE rs.chat_session_id = cs.id
    """)
    op.execute("""
        UPDATE chat_sessions AS cs
        SET research_session_id = latest.id
        FROM (
            SELECT DISTINCT ON (chat_session_id) id, chat_session_id
            FROM research_sessions
            WHERE chat_session_id IS NOT NULL
            ORDER BY chat_session_id, created_at DESC
        ) AS latest
        WHERE latest.chat_session_id = cs.id
    """)
    op.drop_constraint('research_sessions_chat_session_id_fkey', 'research_sessions', type_='foreignkey')
    op.drop_column('research_sessions', 'chat_session_id')
