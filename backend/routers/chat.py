import json

from db import get_hot_memories, save_chunks
from dependencies import get_db
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from graph import graph
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from models import ChatRequest

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest, db=Depends(get_db)):
    conv_id = body.conversation_id

    user_msg_id = await db.fetchval(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
        conv_id,
        "user",
        body.message,
    )

    row = await db.fetchrow(
        "SELECT title FROM conversations WHERE id = $1::uuid", conv_id
    )
    if row and row["title"] == "New Chat":
        await db.execute(
            "UPDATE conversations SET title = $1 WHERE id = $2::uuid",
            body.message[:60].strip(),
            conv_id,
        )

    ctx_rows = await db.fetch(
        """SELECT id, role, content FROM messages
           WHERE conversation_id = $1::uuid
           ORDER BY created_at DESC LIMIT 10""",
        conv_id,
    )
    ctx_rows = list(reversed(ctx_rows))

    hot_memories = await get_hot_memories(db)
    system_content = "You are a helpful assistant."
    if hot_memories:
        system_content += "\n\nThings to always remember:\n" + "\n".join(f"- {m}" for m in hot_memories)

    lc_messages = [SystemMessage(content=system_content)]
    lc_messages += [
        HumanMessage(content=r["content"])
        if r["role"] == "user"
        else AIMessage(content=r["content"])
        for r in ctx_rows
    ]

    async def generate():
        full_response: list[str] = []
        async for event in graph.astream_events(
            {"messages": lc_messages, "db": db},
            version="v2",
        ):
            if event["event"] == "on_tool_start":
                print(f"[tool] {event['name']} <- {event['data'].get('input')}")
            elif event["event"] == "on_tool_end":
                print(f"[tool] {event['name']} -> {event['data'].get('output')}")
            elif (
                event["event"] == "on_chat_model_stream"
                and event.get("metadata", {}).get("langgraph_node") == "agent"
            ):
                chunk = event["data"]["chunk"]
                if chunk.content:
                    full_response.append(chunk.content)
                    yield f"data: {json.dumps({'text': chunk.content})}\n\n"
        yield "data: [DONE]\n\n"

        if full_response:
            assistant_content = "".join(full_response)
            asst_msg_id = await db.fetchval(
                "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
                conv_id,
                "assistant",
                assistant_content,
            )
            await db.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid",
                conv_id,
            )

            conv_row = await db.fetchrow(
                "SELECT title FROM conversations WHERE id = $1::uuid", conv_id
            )
            conv_title = conv_row["title"] if conv_row else ""

            await save_chunks(
                db,
                "message",
                body.message,
                {
                    "message_id": str(user_msg_id),
                    "conversation_id": conv_id,
                    "conversation_title": conv_title,
                    "role": "user",
                },
            )
            await save_chunks(
                db,
                "message",
                assistant_content,
                {
                    "message_id": str(asst_msg_id),
                    "conversation_id": conv_id,
                    "conversation_title": conv_title,
                    "role": "assistant",
                },
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
