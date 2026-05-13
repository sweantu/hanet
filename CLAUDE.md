# Hanet — Agent Chat App

## Current state
Basic streaming chat: user sends a message, AI replies word-by-word via SSE. No database yet. UI is dark mode (gray-900 background, Tailwind utility classes in `page.tsx`).

## Last session recap — 2026-05-13
Switched the backend from direct OpenAI to LangGraph while keeping gpt-4o-mini, then updated CLAUDE.md with backend and frontend structure, architecture, and key symbols for faster future sessions. No code changes pending.

## Stack
- **Frontend:** Next.js 15, TypeScript, Tailwind CSS (`frontend/`)
- **Backend:** FastAPI, Python (`backend/`)
- **LLM:** LangGraph + `langchain-openai`, model `gpt-4o-mini`

## How to run
```bash
# Backend
cd backend && pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY
uvicorn main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

## Architecture

**Backend**
- `POST /chat` receives `{ messages: [...] }` (full history), streams SSE tokens back
- LangGraph graph: `START → agent → END`; single node calls `llm.invoke`
- SSE format: `data: {"text": "..."}` lines, terminated by `data: [DONE]`

**Frontend**
- No routing — single page app (`page.tsx` is the whole UI)
- State: `messages[]` holds full history; sent as-is on every request
- On send: appends user message → appends empty assistant message → fills it token-by-token via SSE
- SSE parsing: reads `res.body` with `ReadableStream` + `TextDecoder`; splits on `\n`, strips `data: ` prefix, parses JSON `{text}`
- Streaming cursor: pulsing `<span>` appended to last assistant message while `isStreaming`
- Enter sends, Shift+Enter newlines; textarea auto-resizes up to 160px

## Backend structure

```
backend/
  main.py          — FastAPI app; LangGraph StateGraph (START→agent→END); POST /chat streams SSE
  requirements.txt — langgraph, langchain-openai, fastapi, uvicorn[standard], python-dotenv
  .env             — OPENAI_API_KEY
```

Key symbols in `backend/main.py`:
- `llm` — `ChatOpenAI(model="gpt-4o-mini", streaming=True)`
- `agent` — graph node
- `Message` — Pydantic model
- `ChatRequest` — Pydantic model
- `POST /chat` — endpoint
- streams via `astream_events(..., version="v2")`

## Frontend structure

```
frontend/src/app/
  page.tsx    — single "use client" page; all chat UI and SSE streaming logic
  layout.tsx  — root layout; sets <title>Hanet Chat</title>
  globals.css — Tailwind base styles
```

Key symbols in `frontend/src/app/page.tsx`:
- `Message` — interface `{ role: "user" | "assistant", content: string }`
- `API_URL` — `"http://localhost:8000"`
- `ChatPage` — default export; owns all state
- `messages` — `useState<Message[]>` — full conversation history
- `input` — `useState<string>` — current textarea value
- `isStreaming` — `useState<boolean>` — disables input while streaming
- `bottomRef` — auto-scroll anchor
- `textareaRef` — auto-resize textarea
- `sendMessage()` — posts full history to `POST /chat`, reads SSE stream, appends tokens to last message
- `handleKeyDown()` — Enter sends, Shift+Enter newline

## Planned next steps
- Add tools/agents to the LangGraph graph
- Add PostgreSQL to persist conversation history
- Add conversation list sidebar
