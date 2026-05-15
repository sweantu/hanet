"""create documents table for hybrid search

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13
"""

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            collection  TEXT NOT NULL DEFAULT 'message',
            content     TEXT NOT NULL,
            metadata    JSONB DEFAULT '{}',
            embedding   vector(1536),
            fts         tsvector
                        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_collection ON documents (collection)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_metadata_conversation_id "
        "ON documents ((metadata->>'conversation_id'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_embedding "
        "ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_fts "
        "ON documents USING GIN (fts)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents")
    # Do NOT drop the vector extension
