"""drop generated fts expression and add keywords column

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02
"""

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("ALTER TABLE documents ALTER COLUMN fts DROP EXPRESSION")
    op.execute("ALTER TABLE documents ADD COLUMN keywords TEXT[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN keywords")
    op.execute("ALTER TABLE documents DROP COLUMN fts")
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN fts tsvector
            GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_fts ON documents USING GIN (fts)"
    )
