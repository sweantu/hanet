# Hanet — Agent Chat App

## Current state
Streaming chat with persistent conversation history, hybrid search, search-to-message navigation, and agent memory. PostgreSQL stores conversations, messages, document chunks, and memories. Sidebar lists past conversations. UI is dark mode (gray-900 background, Tailwind CSS). Both backend and frontend are separated by feature into focused modules.

## Last session recap — 2026-06-03
Added persistent memory system. `memories` table: `id`, `type` (hot/cold), `content`, `created_at`. Both types are also indexed in `documents` (`collection='memory'`) with embeddings and keyword-based FTS. `db.py`: `save_memory`, `get_hot_memories`, `save_memory_embedding`. `rag.py`: `search_memories_impl`. `sql.py`: `HYBRID_SEARCH_MEMORIES_SQL`. `graph.py`: `save_memory` tool (LLM-routed, always saves to documents; hot = identity facts, cold = events/activities), `retrieve_memories` tool (searches both types), `_extract_keywords` via `llm.with_structured_output(_Keywords)`. System prompt always injects hot memories. Tool calls logged to stdout.

## Stack
- **Frontend:** Next.js 15, TypeScript, Tailwind CSS (`frontend/`)
- **Backend:** FastAPI, Python (`backend/`)
- **LLM:** LangGraph + `langchain-openai`, model `gpt-4o-mini`
- **Embeddings:** `text-embedding-3-small` via `OpenAIEmbeddings` (langchain-openai)
- **Database:** PostgreSQL 16 + pgvector (Docker image `pgvector/pgvector:pg16`), accessed via `asyncpg`
- **Migrations:** Alembic + SQLAlchemy (async `env.py`)

## How to run
```bash
# Start Postgres
docker compose up -d

# Backend
cd backend && pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY
alembic upgrade head
uvicorn main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

## Architecture

**Backend**
- `POST /chat` receives `{ messages: [...], conversation_id? }`, streams SSE tokens back
- After stream completes, persists assistant reply, updates `conversations.updated_at`, then chunks + embeds both messages into `documents`
- LangGraph graph: ReAct loop — `START → agent → tools_condition → tools → agent` or `→ END`; agent calls `search_database` or `search_web` tools as needed; tool results flow through message history
- SSE format: `data: {"text": "..."}` lines, terminated by `data: [DONE]`
- DB pool created on startup via `asyncpg.create_pool(init=register_vector)` (FastAPI `lifespan`)
- Chunking: `tiktoken` with `cl100k_base` encoder, 512-token window, 64-token overlap (`chunk_text`)
- `save_chunks(db, collection, content, metadata, keywords=[])` — chunks text, embeds, bulk-inserts into `documents`; sets `fts` via `to_tsvector('english', content)` at insert time

**Frontend**
- Layout: sidebar (256px) + chat column (flex-1)
- Sidebar: lists conversations ordered newest-first; "+ New Chat" button; delete on hover
- On conversation click: fetches messages from `GET /conversations/{id}/messages`
- On first send (no active conversation): auto-creates one via `POST /conversations`
- SSE parsing unchanged: `ReadableStream` + `TextDecoder`, splits on `\n`, parses `{text}`
- After stream completes: refreshes sidebar (title may have updated)

## Backend structure

```
backend/
  main.py               — FastAPI app + asyncpg lifespan + CORS + include_router (~30 lines)
  main.py               — FastAPI app + asyncpg lifespan + CORS + include_router (~30 lines)
  llm.py                — llm, embeddings_model primitives; calls load_dotenv()
  graph.py              — LangGraph ChatState + tools (search_database, search_web, save_memory, retrieve_memories) + agent node; exports graph
  models.py             — all Pydantic models
  sql.py                — HYBRID_SEARCH_SQL, HYBRID_SEARCH_ASSISTANT_SQL, HYBRID_SEARCH_MEMORIES_SQL constants
  db.py                 — chunk_text, save_chunks, save_memory, get_hot_memories, save_memory_embedding, encode_cursor, decode_cursor
  rag.py                — search_database_impl(query, limit, db) → list[str]; search_memories_impl(query, limit, db) → list[str]
  dependencies.py       — get_db(request) FastAPI dependency
  requirements.txt      — langgraph, langchain-openai, fastapi, uvicorn, asyncpg, alembic,
                          sqlalchemy, greenlet, pgvector, tiktoken, tavily-python
  backfill_embeddings.py — one-time script to chunk + embed existing messages
  .env                  — OPENAI_API_KEY, DATABASE_URL
  alembic.ini           — Alembic config (script_location = migrations/)
  migrations/
    env.py                               — async env; reads DATABASE_URL from env
    versions/
      0001_create_conversations_messages.py
      0002_add_documents.py              — documents table + ivfflat/GIN/btree indexes
      0003_update_documents.py           — drop generated fts expression; add keywords TEXT[] column
      0004_add_memories.py               — memories table (id, type, content, created_at)
      0005_update_memories_remove_keywords.py — truncate stale data; drop keywords column from memories
  routers/
    conversations.py    — GET/POST/DELETE /conversations; GET /conversations/{id}/messages
    chat.py             — POST /chat
    search.py           — POST /search, /search/semantic, /search/keyword, /search/rag, /search/rag/messages
```

Key symbols:
- `llm.py`: `llm`, `embeddings_model`
- `graph.py`: `graph` (compiled LangGraph); `ChatState` (messages, db); tools: `search_database`, `search_web` (Tavily), `save_memory` (hot/cold, always saves to documents), `retrieve_memories` (hybrid search across both types); `_extract_keywords` via `llm.with_structured_output(_Keywords)`
- `db.py`: `chunk_text(text)`, `save_chunks(db, collection, content, metadata, keywords=[])`, `save_memory(db, type, content) → str`, `get_hot_memories(db) → list[str]`, `save_memory_embedding(db, memory_id, type, content, keywords)`, `encode_cursor(*parts)`, `decode_cursor(cursor)`
- `rag.py`: `search_database_impl(query, limit, db)` — embed → hybrid search (assistant only) → LLM rerank → batch-fetch; returns `list[str]` (score ≥ 8). `search_memories_impl(query, limit, db)` — hybrid search `collection='memory'`, returns content strings
- `models.py`: `Message`, `ChatRequest`, `ConversationCreate`, `SearchRequest`, `RagSearchRequest`, `RankedChunk`, `RagSearchResponse`, `Memory`
- `sql.py`: `HYBRID_SEARCH_SQL`, `HYBRID_SEARCH_ASSISTANT_SQL`, `HYBRID_SEARCH_MEMORIES_SQL` — RRF fusion; memories variant scoped to `collection='memory'`, no conversations join
- Endpoints: same as before — `GET /conversations`, `POST /conversations`, `DELETE /conversations/{id}`, `GET /conversations/{id}/messages`, `POST /chat`, `POST /search`, `POST /search/semantic`, `POST /search/keyword`, `POST /search/rag`, `POST /search/rag/messages`

## Frontend structure

```
frontend/src/
  app/
    page.tsx        — wires hooks + components; owns hoveredId (~80 lines)
    layout.tsx      — root layout; sets <title>Hanet Chat</title>
    globals.css     — Tailwind base styles
  types/
    index.ts        — Message, Conversation, SearchResult interfaces
  lib/
    api.ts          — API_URL constant
  hooks/
    useConversations.ts  — conversations[], convNextCursor/HasMore, fetchConversations, createConversation, deleteConversation
    useMessages.ts       — activeId, messages, msgHasOlder, loadMessages, loadOlderMessages, resetMessages; owns all scroll refs
    useChat.ts           — input, isStreaming, sendMessage, textareaRef; auto-resize effect
    useSearch.ts         — searchOpen, searchQuery, searchResults, searchLoading, runSearch, goToResult; Escape + focus effects
  components/
    Sidebar.tsx      — pure props; renders conversation list, new chat button, search toggle
    SearchModal.tsx  — pure props; renders search overlay
    MessageList.tsx  — pure props; renders messages + load-older button
    ChatInput.tsx    — pure props; renders textarea + send button
```

Key wiring in `page.tsx`:
- `useMessages` owns `activeId`; `selectConversation(id, loadAll?)` calls `loadMessages`
- `useSearch` receives `onGoToResult(conversationId, messageId)` — sets `targetMessageIdRef.current` then calls `selectConversation`
- `useChat` receives `onCreateConversation`, `onSetActiveId`, `onAfterSend` callbacks

## Changelog
See `CHANGELOG.md` for full session-by-session history.

## Planned next steps
- Rename conversations from the sidebar
- Memory management UI (view/delete memories)

