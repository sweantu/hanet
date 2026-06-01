# Hanet — Agent Chat App

## Current state
Streaming chat with persistent conversation history, hybrid search, and search-to-message navigation. PostgreSQL stores conversations, messages, and document chunks with embeddings. Sidebar lists past conversations. UI is dark mode (gray-900 background, Tailwind CSS). Both backend and frontend are separated by feature into focused modules.

## Last session recap — 2026-06-01
Added LangGraph RAG router to the chat pipeline. `llm.py` stripped to primitives only (`llm`, `embeddings_model`). New `graph.py` extends the LangGraph graph to three nodes: `route_intent` (LLM structured-output classifier — returns `should_retrieve: bool`), `retrieve_rag` (calls `rag_retrieve` only when needed), `agent` (injects retrieved context into system prompt then calls LLM). Conditional edge: `route_intent → retrieve_rag → agent` or `route_intent → agent`. RAG retrieval simplified: HyDE removed (user query embedded directly); `rag_retrieve` now returns `list[str]` (top assistant messages scoring ≥ 8) instead of a single `MessagePair`; qualifying messages batch-fetched in one query. Retrieved context injected as additional system prompt text, not as fake conversation turns. `MessagePair` model deleted.

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
- LangGraph graph: `START → route_intent → [conditional] → retrieve_rag → agent → END` or `→ agent → END`; `route_intent` classifies user intent with structured output; `retrieve_rag` runs only on retrieval intent; `agent` optionally injects RAG context into system prompt
- SSE format: `data: {"text": "..."}` lines, terminated by `data: [DONE]`
- DB pool created on startup via `asyncpg.create_pool(init=register_vector)` (FastAPI `lifespan`)
- Chunking: `tiktoken` with `cl100k_base` encoder, 512-token window, 64-token overlap (`chunk_text`)
- `save_chunks(db, collection, content, metadata)` — chunks text, embeds, bulk-inserts into `documents`

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
  graph.py              — LangGraph ChatState + route_intent / retrieve_rag / agent nodes; exports graph
  models.py             — all Pydantic models
  sql.py                — HYBRID_SEARCH_SQL, HYBRID_SEARCH_ASSISTANT_SQL constants
  db.py                 — chunk_text, save_chunks, encode_cursor, decode_cursor
  rag.py                — rag_retrieve(query, limit, db) → list[str]
  dependencies.py       — get_db(request) FastAPI dependency
  requirements.txt      — langgraph, langchain-openai, fastapi, uvicorn, asyncpg, alembic,
                          sqlalchemy, greenlet, pgvector, tiktoken
  backfill_embeddings.py — one-time script to chunk + embed existing messages
  .env                  — OPENAI_API_KEY, DATABASE_URL
  alembic.ini           — Alembic config (script_location = migrations/)
  migrations/
    env.py                               — async env; reads DATABASE_URL from env
    versions/
      0001_create_conversations_messages.py
      0002_add_documents.py              — documents table + ivfflat/GIN/btree indexes
  routers/
    conversations.py    — GET/POST/DELETE /conversations; GET /conversations/{id}/messages
    chat.py             — POST /chat
    search.py           — POST /search, /search/semantic, /search/keyword, /search/rag, /search/rag/messages
```

Key symbols:
- `llm.py`: `llm`, `embeddings_model`
- `graph.py`: `graph` (compiled LangGraph); `ChatState` (messages, db, rag_messages, should_retrieve); `RAGRouterDecision` TypedDict
- `db.py`: `chunk_text(text)`, `save_chunks(db, collection, content, metadata)`, `encode_cursor(*parts)`, `decode_cursor(cursor)`
- `rag.py`: `rag_retrieve(query, limit, db)` — embed query → hybrid search (assistant only) → LLM rerank → batch-fetch full messages; returns `list[str]` (threshold: score ≥ 8)
- `models.py`: `Message`, `ChatRequest`, `ConversationCreate`, `SearchRequest`, `RagSearchRequest`, `RankedChunk`, `RagSearchResponse`, `RAGRouterDecision`
- `sql.py`: `HYBRID_SEARCH_SQL`, `HYBRID_SEARCH_ASSISTANT_SQL` — RRF fusion; assistant variant filters `metadata->>'role' = 'assistant'`
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
- Add tools/agents to the LangGraph graph
- Rename conversations from the sidebar

