from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from db import decode_cursor, encode_cursor
from dependencies import get_db
from models import ConversationCreate

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(cursor: str | None = None, limit: int = 10, db=Depends(get_db)):
    fetch_limit = limit + 1
    if cursor:
        pivot_ts, pivot_id = decode_cursor(cursor)
        pivot_dt = datetime.fromisoformat(pivot_ts)
        rows = await db.fetch(
            """SELECT id, title, created_at, updated_at FROM conversations
               WHERE updated_at < $1 OR (updated_at = $1 AND id::text < $2)
               ORDER BY updated_at DESC, id DESC LIMIT $3""",
            pivot_dt, pivot_id, fetch_limit,
        )
    else:
        rows = await db.fetch(
            """SELECT id, title, created_at, updated_at FROM conversations
               ORDER BY updated_at DESC, id DESC LIMIT $1""",
            fetch_limit,
        )
    has_more = len(rows) > limit
    items = list(rows[:limit])
    next_cursor = None
    if has_more:
        last = items[-1]
        next_cursor = encode_cursor(last["updated_at"].isoformat(), str(last["id"]))
    return {
        "items": [
            {"id": str(r["id"]), "title": r["title"], "created_at": r["created_at"].isoformat()}
            for r in items
        ],
        "next_cursor": next_cursor,
    }


@router.post("")
async def create_conversation(body: ConversationCreate = ConversationCreate(), db=Depends(get_db)):
    row = await db.fetchrow(
        "INSERT INTO conversations (title) VALUES ($1) RETURNING id, title, created_at",
        body.title,
    )
    return {"id": str(row["id"]), "title": row["title"], "created_at": row["created_at"].isoformat()}


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, db=Depends(get_db)):
    result = await db.execute("DELETE FROM conversations WHERE id = $1::uuid", conversation_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@router.get("/{conversation_id}/messages")
async def get_messages(conversation_id: str, cursor: str | None = None, limit: int = 10, db=Depends(get_db)):
    if limit == 0:
        rows = await db.fetch(
            "SELECT id, role, content FROM messages WHERE conversation_id = $1::uuid ORDER BY created_at ASC",
            conversation_id,
        )
        return {
            "items": [{"id": str(r["id"]), "role": r["role"], "content": r["content"]} for r in rows],
            "prev_cursor": None,
        }

    fetch_limit = limit + 1
    if cursor:
        pivot_ts, pivot_id = decode_cursor(cursor)
        pivot_dt = datetime.fromisoformat(pivot_ts)
        rows = await db.fetch(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = $1::uuid
                 AND (created_at < $2 OR (created_at = $2 AND id::text < $3))
               ORDER BY created_at DESC LIMIT $4""",
            conversation_id, pivot_dt, pivot_id, fetch_limit,
        )
    else:
        rows = await db.fetch(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = $1::uuid
               ORDER BY created_at DESC LIMIT $2""",
            conversation_id, fetch_limit,
        )
    has_more = len(rows) > fetch_limit - 1
    page = list(rows[:limit])
    prev_cursor = None
    if has_more:
        oldest = page[-1]
        prev_cursor = encode_cursor(oldest["created_at"].isoformat(), str(oldest["id"]))
    page.reverse()
    return {
        "items": [{"id": str(r["id"]), "role": r["role"], "content": r["content"]} for r in page],
        "prev_cursor": prev_cursor,
    }
