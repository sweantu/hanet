# Hanet — Agent Chat App

## Current state
Streaming chat with persistent conversation history, hybrid search, and search-to-message navigation. PostgreSQL stores conversations, messages, and document chunks with embeddings. Sidebar lists past conversations. UI is dark mode (gray-900 background, Tailwind utility classes in `page.tsx`).

## Last session recap — 2026-05-18
Added RAG retrieval pipeline (HyDE + hybrid search + LLM reranking) to the backend. Three new endpoints: `POST /search/rag` returns ranked chunks with `relevance_score`; `POST /search/rag/messages` returns a single best `MessagePair` (assistant message + preceding user message) or `null` when best score < 8; both search only `role='assistant'` chunks. Shared logic lives in `_rag_retrieve(query, limit, db)`. `POST /chat` now calls `_rag_retrieve` before building the LLM context — if a relevant pair is found and its `message_id` is not already in the 10 most recent messages, it is prepended to `lc_messages` as a priming Q&A pair.

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
- LangGraph graph: `START → agent → END`; single node calls `llm.invoke`
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
  main.py               — FastAPI app + asyncpg pool; LangGraph graph; all endpoints
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
```

Key symbols in `backend/main.py`:
- `_encode_cursor(*parts)` / `_decode_cursor(cursor)` — base64url keyset cursor helpers
- `llm` — `ChatOpenAI(model="gpt-4o-mini", streaming=True)`
- `embeddings_model` — `OpenAIEmbeddings(model="text-embedding-3-small")`
- `chunk_text(text)` — splits text into 512-token chunks with 64-token overlap
- `save_chunks(db, collection, content, metadata)` — chunks + embeds + inserts into `documents`
- `agent` / `graph` — LangGraph node + compiled graph
- `Message` — Pydantic model `{ role, content }`
- `ChatRequest` — Pydantic model `{ message: str, conversation_id: str }`
- `ConversationCreate` — Pydantic model `{ title? }`
- `SearchRequest` — Pydantic model `{ query, limit=10, threshold?  }` (`threshold` = min cosine similarity, semantic only)
- `GET /conversations` — paginated list, newest first; params: `cursor`, `limit=10`; returns `{ items, next_cursor }`
- `POST /conversations` — create blank conversation
- `DELETE /conversations/{id}` — cascade delete
- `GET /conversations/{id}/messages` — paginated history; params: `cursor`, `limit=10` (`limit=0` = all); returns `{ items, prev_cursor }`; newest-10 by default, reversed to oldest-first
- `POST /chat` — accepts `{ message, conversation_id }`; saves user msg, fetches 10 latest from DB for context, calls `_rag_retrieve` and prepends RAG pair if relevant and not already in context, streams SSE; persist assistant reply; chunk + embed after `[DONE]`
- `POST /search` — hybrid RRF (semantic + keyword); returns `rrf_score`, `conversation_created_at`
- `POST /search/semantic` — pgvector cosine similarity only; returns `score` (0–1), `conversation_created_at`; supports `threshold`
- `POST /search/keyword` — tsvector `ts_rank` only; returns `score`, `conversation_created_at`
- `POST /search/rag` — HyDE + hybrid search (assistant chunks only) + LLM reranking; returns `{ hypothetical_answer, chunks: RankedChunk[] }`
- `POST /search/rag/messages` — same pipeline; returns single `MessagePair | null` (best score ≥ 8 only)
- `_rag_retrieve(query, limit, db)` — shared helper: HyDE → embed → `_HYBRID_SEARCH_ASSISTANT_SQL` → rerank → fetch full messages; returns `MessagePair | None`
- `_HYBRID_SEARCH_SQL` / `_HYBRID_SEARCH_ASSISTANT_SQL` — RRF SQL constants; assistant variant filters `metadata->>'role' = 'assistant'`
- `RagSearchRequest` — Pydantic model `{ query, limit=10 }`
- `RankedChunk` — Pydantic model `{ id, content, conversation_title, conversation_created_at, metadata, rrf_score, relevance_score }`
- `RagSearchResponse` — Pydantic model `{ hypothetical_answer, chunks }`
- `MessagePair` — Pydantic model `{ message_id, user_message, assistant_message, relevance_score, conversation_title, conversation_created_at }`
- `lifespan` — opens/closes asyncpg pool with `register_vector`

## Frontend structure

```
frontend/src/app/
  page.tsx    — single "use client" page; sidebar + chat UI + SSE streaming
  layout.tsx  — root layout; sets <title>Hanet Chat</title>
  globals.css — Tailwind base styles
```

Key symbols in `frontend/src/app/page.tsx`:
- `Message` — interface `{ id?, role: "user" | "assistant", content: string }`
- `Conversation` — interface `{ id, title, created_at }`
- `SearchResult` — interface `{ id, content, conversation_title, conversation_created_at, metadata: { conversation_id, message_id, role }, rrf_score }`
- `API_URL` — `"http://localhost:8000"`
- `ChatPage` — default export; owns all state
- `messages` — `useState<Message[]>` — active conversation messages (current page + live session)
- `conversations` — `useState<Conversation[]>` — sidebar list (current page)
- `activeId` — `useState<string | null>` — selected conversation id
- `hoveredId` — `useState<string | null>` — controls delete button visibility
- `searchOpen` — `useState<boolean>` — controls search modal visibility
- `searchQuery` / `searchResults` / `searchLoading` — search modal state
- `convNextCursor` / `convHasMore` — cursor pagination state for conversations sidebar
- `msgPrevCursor` / `msgHasOlder` — cursor pagination state for messages (older pages)
- `targetMessageIdRef` — `useRef<string | null>` — message id to scroll to after conversation loads
- `messagesContainerRef` — `useRef<HTMLDivElement>` — ref to scrollable messages div; used to read/restore `scrollHeight` when prepending older messages
- `scrollRestoreRef` — `useRef<number | null>` — captures `scrollHeight` before prepend; consumed by scroll `useEffect` to restore `scrollTop`
- `fetchConversations(cursor?)` — refreshes/appends sidebar; no cursor = reset list
- `selectConversation(id, loadAll?)` — loads paginated messages; `loadAll=true` fetches all (used by search navigation)
- `loadOlderMessages()` — fetches previous page, prepends to `messages`, restores scroll position
- `newChat()` — clears state and cursor state, no active conversation
- `deleteConversation(e, id)` — deletes and refreshes sidebar
- `runSearch()` — POSTs to `/search` with current query, updates `searchResults`
- `goToResult(result)` — closes modal, sets `targetMessageIdRef`, calls `selectConversation(..., true)`
- `sendMessage()` — creates conversation if needed, posts `{ message, conversation_id }` to `/chat`, reads SSE
- `handleKeyDown()` — Enter sends, Shift+Enter newline
- scroll effect — single `useEffect([messages])`: restores scroll after prepend if `scrollRestoreRef` set; else scrolls to `targetMessageIdRef` with highlight; else scrolls to bottom

## Changelog
See `CHANGELOG.md` for full session-by-session history.

## Planned next steps
- Add tools/agents to the LangGraph graph
- Rename conversations from the sidebar
