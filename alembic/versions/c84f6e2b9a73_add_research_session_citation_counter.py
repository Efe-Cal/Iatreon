"""add research session citation counter

Revision ID: c84f6e2b9a73
Revises: b7a1d3c9e2f0
Create Date: 2026-06-28 23:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c84f6e2b9a73'
down_revision: Union[str, Sequence[str], None] = 'b7a1d3c9e2f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'research_sessions',
        sa.Column('next_citation_num', sa.Integer(), server_default='1', nullable=False),
    )
    op.alter_column('research_sessions', 'next_citation_num', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('research_sessions', 'next_citation_num')
