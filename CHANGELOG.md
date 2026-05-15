# Project History

## 2026-05-15 (session 4)

Added message search feature. Backend: `GET /conversations/{id}/messages` now returns `id` per message row (needed for DOM anchoring). All three search endpoints (`POST /search`, `/search/semantic`, `/search/keyword`) now join `conversations.created_at` and include it as `conversation_created_at` in every result. Frontend: added `SearchResult` interface; `Message` interface gained optional `id`; message divs rendered with `id={msg.id}` for stable scroll anchors. Added 🔍 button in the sidebar header that opens a centered modal popup (fixed overlay, `z-50`, click-backdrop-to-close, Escape-to-close). Modal contains a search input (auto-focused, Enter to search), scrollable results list (conversation title + date + 3-line content excerpt), and a Search button. Clicking a result calls `goToResult` which sets `targetMessageIdRef.current`, closes the modal, and awaits `selectConversation`. A single merged `useEffect([messages])` handles both scroll cases: if `targetMessageIdRef.current` is set it scrolls to that element with a 2-second indigo ring highlight and returns early; otherwise it scrolls to the bottom. Using a ref (not state) for the target prevents a re-render that would trigger the scroll-to-bottom path.

## 2026-05-14/15 (session 3)

Added hybrid search backend. Introduced a generic `documents` table (`collection text`, `content text`, `metadata jsonb`, `embedding vector(1536)`, generated `fts tsvector`) via Alembic migration `0002_add_documents`. Switched Docker image from `postgres:16-alpine` to `pgvector/pgvector:pg16` to enable the `vector` extension. Added `pgvector` and `tiktoken` to requirements. Implemented `chunk_text` (512-token window, 64-token overlap, `cl100k_base` encoder) and `save_chunks` helper. Modified `POST /chat` to chunk and embed both user and assistant messages into `documents` after each streaming round-trip (using `text-embedding-3-small`). Added three search endpoints: `POST /search` (hybrid RRF fusion), `POST /search/semantic` (pgvector cosine similarity with optional `threshold` param), `POST /search/keyword` (tsvector `ts_rank`). Added `backfill_embeddings.py` one-time script to chunk and embed existing messages.

## 2026-05-13 (session 2)

Added persistent chat history with sidebar. Introduced Docker Compose + PostgreSQL 16. Set up Alembic migrations (`0001_create_conversations_messages`). Added `asyncpg` pool to FastAPI via `lifespan`. New endpoints: `GET/POST /conversations`, `DELETE /conversations/{id}`, `GET /conversations/{id}/messages`. Modified `POST /chat` to accept `conversation_id`, persist both user and assistant messages, auto-title conversation from first user message. Redesigned frontend: sidebar (256px) with conversation list, "+ New Chat" button, delete-on-hover. Clicking a conversation loads its history; first send auto-creates a conversation.

## 2026-05-13 (session 1)

Switched the backend from direct OpenAI to LangGraph while keeping gpt-4o-mini, then updated CLAUDE.md with backend and frontend structure, architecture, and key symbols for faster future sessions. No code changes pending.
