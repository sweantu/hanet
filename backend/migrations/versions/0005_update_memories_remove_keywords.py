"""remove keywords from memories, truncate stale data

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-03
"""

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("TRUNCATE TABLE memories")
    op.execute("DELETE FROM documents WHERE collection = 'memory'")
    # DROP COLUMN automatically removes associated indexes (GIN on keywords, btree on type survives)
    op.execute("ALTER TABLE memories DROP COLUMN keywords")


def downgrade() -> None:
    op.execute("ALTER TABLE memories ADD COLUMN keywords TEXT[] NOT NULL DEFAULT '{}'")
    op.execute("CREATE INDEX ON memories USING GIN (keywords)")
