"""add chat session fk columns

Revision ID: a1b2c3d4e5f6
Revises: 2cb3fba87cc2
Create Date: 2026-06-17 00:00:00.000000

Note: ``user_sessions`` is created out-of-band (by the application on startup,
not by alembic). This migration is written so it succeeds whether or not the
table already exists: when missing, the steps are no-ops, and the next app
startup will create the table with all expected columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '2cb3fba87cc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def _constraint_exists(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        fk["name"] == constraint_name
        for fk in inspector.get_foreign_keys(table_name)
    )


def upgrade() -> None:
    if not _table_exists("user_sessions"):
        # ``user_sessions`` is created by the app on startup. Nothing to do
        # here; when the app boots it will create the table and SQLAlchemy
        # will pick up the new columns via the mapped model.
        return

    if not _column_exists("user_sessions", "intake_session_id"):
        op.add_column(
            "user_sessions",
            sa.Column("intake_session_id", sa.Uuid(), nullable=True),
        )

    if not _column_exists("user_sessions", "research_session_id"):
        op.add_column(
            "user_sessions",
            sa.Column("research_session_id", sa.Uuid(), nullable=True),
        )

    if not _constraint_exists("user_sessions", "fk_user_sessions_intake_session_id"):
        op.create_foreign_key(
            "fk_user_sessions_intake_session_id",
            "user_sessions", "intake_sessions",
            ["intake_session_id"], ["id"],
        )

    if not _constraint_exists("user_sessions", "fk_user_sessions_research_session_id"):
        op.create_foreign_key(
            "fk_user_sessions_research_session_id",
            "user_sessions", "research_sessions",
            ["research_session_id"], ["id"],
        )


def downgrade() -> None:
    if not _table_exists("user_sessions"):
        return

    if _constraint_exists("user_sessions", "fk_user_sessions_research_session_id"):
        op.drop_constraint(
            "fk_user_sessions_research_session_id",
            "user_sessions",
            type_="foreignkey",
        )
    if _constraint_exists("user_sessions", "fk_user_sessions_intake_session_id"):
        op.drop_constraint(
            "fk_user_sessions_intake_session_id",
            "user_sessions",
            type_="foreignkey",
        )

    if _column_exists("user_sessions", "research_session_id"):
        op.drop_column("user_sessions", "research_session_id")
    if _column_exists("user_sessions", "intake_session_id"):
        op.drop_column("user_sessions", "intake_session_id")
