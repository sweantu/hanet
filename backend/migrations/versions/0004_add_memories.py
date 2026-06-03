"""add memories table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03
"""

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            type TEXT NOT NULL CHECK (type IN ('hot', 'cold')),
            content TEXT NOT NULL,
            keywords TEXT[] NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ON memories (type)")
    op.execute("CREATE INDEX ON memories USING GIN (keywords)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memories")
