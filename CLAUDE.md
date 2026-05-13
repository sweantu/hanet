# Hanet — Agent Chat App

## Current state
Streaming chat with persistent conversation history. PostgreSQL stores conversations and messages. Sidebar lists past conversations; clicking one loads its history. UI is dark mode (gray-900 background, Tailwind utility classes in `page.tsx`).

## Last session recap — 2026-05-13
Added PostgreSQL persistence via Docker Compose + asyncpg. Set up Alembic migrations. Added four conversation CRUD endpoints. Modified `/chat` to save user + assistant messages and auto-title the conversation from the first message. Redesigned frontend layout to include a sidebar with conversation list, new chat button, and delete-on-hover.

## Stack
- **Frontend:** Next.js 15, TypeScript, Tailwind CSS (`frontend/`)
- **Backend:** FastAPI, Python (`backend/`)
- **LLM:** LangGraph + `langchain-openai`, model `gpt-4o-mini`
- **Database:** PostgreSQL 16 (Docker), accessed via `asyncpg`
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
- After stream completes, persists assistant reply and updates `conversations.updated_at`
- LangGraph graph: `START → agent → END`; single node calls `llm.invoke`
- SSE format: `data: {"text": "..."}` lines, terminated by `data: [DONE]`
- DB pool created on startup via `asyncpg.create_pool()` (FastAPI `lifespan`)

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
  main.py          — FastAPI app + asyncpg pool; LangGraph graph; all endpoints
  requirements.txt — langgraph, langchain-openai, fastapi, uvicorn, asyncpg, alembic, sqlalchemy, greenlet
  .env             — OPENAI_API_KEY, DATABASE_URL
  alembic.ini      — Alembic config (script_location = migrations/)
  migrations/
    env.py                               — async env; reads DATABASE_URL from env
    versions/
      0001_create_conversations_messages.py
```

Key symbols in `backend/main.py`:
- `llm` — `ChatOpenAI(model="gpt-4o-mini", streaming=True)`
- `agent` / `graph` — LangGraph node + compiled graph
- `Message` — Pydantic model `{ role, content }`
- `ChatRequest` — Pydantic model `{ messages, conversation_id? }`
- `ConversationCreate` — Pydantic model `{ title? }`
- `GET /conversations` — list all, newest first
- `POST /conversations` — create blank conversation
- `DELETE /conversations/{id}` — cascade delete
- `GET /conversations/{id}/messages` — fetch message history
- `POST /chat` — stream SSE; persist messages; auto-title on first send
- `lifespan` — opens/closes asyncpg pool

## Frontend structure

```
frontend/src/app/
  page.tsx    — single "use client" page; sidebar + chat UI + SSE streaming
  layout.tsx  — root layout; sets <title>Hanet Chat</title>
  globals.css — Tailwind base styles
```

Key symbols in `frontend/src/app/page.tsx`:
- `Message` — interface `{ role: "user" | "assistant", content: string }`
- `Conversation` — interface `{ id, title, created_at }`
- `API_URL` — `"http://localhost:8000"`
- `ChatPage` — default export; owns all state
- `messages` — `useState<Message[]>` — active conversation messages
- `conversations` — `useState<Conversation[]>` — sidebar list
- `activeId` — `useState<string | null>` — selected conversation id
- `hoveredId` — `useState<string | null>` — controls delete button visibility
- `fetchConversations()` — refreshes sidebar from `GET /conversations`
- `selectConversation(id)` — loads messages for a conversation
- `newChat()` — clears state, no active conversation
- `deleteConversation(e, id)` — deletes and refreshes sidebar
- `sendMessage()` — creates conversation if needed, posts to `/chat`, reads SSE
- `handleKeyDown()` — Enter sends, Shift+Enter newline

## Changelog
See `CHANGELOG.md` for full session-by-session history.

## Planned next steps
- Add tools/agents to the LangGraph graph
- Rename conversations from the sidebar
