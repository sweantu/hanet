# Project History

## 2026-05-13 (session 2)

Added persistent chat history with sidebar. Introduced Docker Compose + PostgreSQL 16. Set up Alembic migrations (`0001_create_conversations_messages`). Added `asyncpg` pool to FastAPI via `lifespan`. New endpoints: `GET/POST /conversations`, `DELETE /conversations/{id}`, `GET /conversations/{id}/messages`. Modified `POST /chat` to accept `conversation_id`, persist both user and assistant messages, auto-title conversation from first user message. Redesigned frontend: sidebar (256px) with conversation list, "+ New Chat" button, delete-on-hover. Clicking a conversation loads its history; first send auto-creates a conversation.

## 2026-05-13 (session 1)

Switched the backend from direct OpenAI to LangGraph while keeping gpt-4o-mini, then updated CLAUDE.md with backend and frontend structure, architecture, and key symbols for faster future sessions. No code changes pending.
