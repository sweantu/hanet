# Hanet — Agent Chat App

## Current state
Basic streaming chat: user sends a message, AI replies word-by-word via SSE. No database yet. UI is dark mode (gray-900 background, Tailwind utility classes in `page.tsx`).

## Stack
- **Frontend:** Next.js 15, TypeScript, Tailwind CSS (`frontend/`)
- **Backend:** FastAPI, Python (`backend/`)
- **LLM:** OpenAI `gpt-4o-mini` (swap to LangGraph later)

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
- `POST /chat` receives `{ messages: [...] }` (full history), streams SSE tokens back
- Frontend holds conversation history in React state; sends entire history each request
- SSE format: `data: {"text": "..."}` lines, terminated by `data: [DONE]`

## Planned next steps
- Add LangGraph for agent/tool-use logic in the backend
- Add PostgreSQL to persist conversation history
- Add conversation list sidebar
