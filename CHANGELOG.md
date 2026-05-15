# Project History

## 2026-05-14/15 (session 3)

Added hybrid search backend. Introduced a generic `documents` table (`collection text`, `content text`, `metadata jsonb`, `embedding vector(1536)`, generated `fts tsvector`) via Alembic migration `0002_add_documents`. Switched Docker image from `postgres:16-alpine` to `pgvector/pgvector:pg16` to enable the `vector` extension. Added `pgvector` and `tiktoken` to requirements. Implemented `chunk_text` (512-token window, 64-token overlap, `cl100k_base` encoder) and `save_chunks` helper. Modified `POST /chat` to chunk and embed both user and assistant messages into `documents` after each streaming round-trip (using `text-embedding-3-small`). Added three search endpoints: `POST /search` (hybrid RRF fusion), `POST /search/semantic` (pgvector cosine similarity with optional `threshold` param), `POST /search/keyword` (tsvector `ts_rank`). Added `backfill_embeddings.py` one-time script to chunk and embed existing messages.

## 2026-05-13 (session 2)

Added persistent chat history with sidebar. Introduced Docker Compose + PostgreSQL 16. Set up Alembic migrations (`0001_create_conversations_messages`). Added `asyncpg` pool to FastAPI via `lifespan`. New endpoints: `GET/POST /conversations`, `DELETE /conversations/{id}`, `GET /conversations/{id}/messages`. Modified `POST /chat` to accept `conversation_id`, persist both user and assistant messages, auto-title conversation from first user message. Redesigned frontend: sidebar (256px) with conversation list, "+ New Chat" button, delete-on-hover. Clicking a conversation loads its history; first send auto-creates a conversation.

## 2026-05-13 (session 1)

Switched the backend from direct OpenAI to LangGraph while keeping gpt-4o-mini, then updated CLAUDE.md with backend and frontend structure, architecture, and key symbols for faster future sessions. No code changes pending.
