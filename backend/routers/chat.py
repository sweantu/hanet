import json

from db import get_hot_memories, save_chunks
from dependencies import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Command
from models import ChatRequest, ResumeRequest

router = APIRouter(tags=["chat"])


async def _stream_graph(graph, input_data, config, results: list):
    """
    Async generator that yields SSE data strings for a graph run.
    Appends (full_response_str, interrupt_payload | None) to `results` before the final [DONE].
    """
    full_response = []
    async for event in graph.astream_events(input_data, config=config, version="v2"):
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

    state = await graph.aget_state(config)
    interrupt_payload = None
    if state.next and state.tasks and state.tasks[0].interrupts:
        interrupt_payload = state.tasks[0].interrupts[0].value
        yield f"data: {json.dumps({'interrupt': interrupt_payload})}\n\n"

    results.append(("".join(full_response), interrupt_payload))
    yield "data: [DONE]\n\n"


@router.get("/conversations/{conversation_id}/pending-interrupt")
async def get_pending_interrupt(conversation_id: str, request: Request):
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": conversation_id}}
    state = await graph.aget_state(config)
    if state.next and state.tasks and state.tasks[0].interrupts:
        return {"interrupt": state.tasks[0].interrupts[0].value}
    return {"interrupt": None}


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, db=Depends(get_db)):
    graph = request.app.state.graph
    conv_id = body.conversation_id
    config = {"configurable": {"thread_id": conv_id, "db": db}}

    state = await graph.aget_state(config)
    if state.next:
        raise HTTPException(
            status_code=409,
            detail="Resolve the pending interrupt before sending a new message.",
        )

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
        system_content += "\n\nThings to always remember:\n" + "\n".join(
            f"- {m}" for m in hot_memories
        )

    lc_messages = [SystemMessage(content=system_content)]
    lc_messages += [
        HumanMessage(content=r["content"])
        if r["role"] == "user"
        else AIMessage(content=r["content"])
        for r in ctx_rows
    ]

    async def generate():
        results = []
        async for sse_line in _stream_graph(graph, {"messages": lc_messages}, config, results):
            yield sse_line

        full_response, interrupt_payload = results[0]
        if interrupt_payload or not full_response:
            return

        asst_msg_id = await db.fetchval(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
            conv_id,
            "assistant",
            full_response,
        )
        await db.execute(
            "UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid", conv_id
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
            full_response,
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


@router.post("/chat/resume")
async def resume_chat(body: ResumeRequest, request: Request, db=Depends(get_db)):
    graph = request.app.state.graph
    conv_id = body.conversation_id
    config = {"configurable": {"thread_id": conv_id, "db": db}}

    # Persist replan message before streaming (durable even on client disconnect)
    replan_msg_id = None
    if body.action == "replan":
        replan_msg_id = await db.fetchval(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
            conv_id,
            "user",
            body.message,
        )

    resume_payload: bool | dict = {"action": body.action}
    if body.action == "replan":
        resume_payload["message"] = body.message

    async def generate():
        results = []
        async for sse_line in _stream_graph(
            graph, Command(resume=resume_payload), config, results
        ):
            yield sse_line

        full_response, interrupt_payload = results[0]
        if interrupt_payload or not full_response:
            return

        asst_msg_id = await db.fetchval(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
            conv_id,
            "assistant",
            full_response,
        )
        await db.execute(
            "UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid", conv_id
        )

        conv_row = await db.fetchrow(
            "SELECT title FROM conversations WHERE id = $1::uuid", conv_id
        )
        conv_title = conv_row["title"] if conv_row else ""

        if body.action == "replan" and replan_msg_id:
            await save_chunks(
                db,
                "message",
                body.message,
                {
                    "message_id": str(replan_msg_id),
                    "conversation_id": conv_id,
                    "conversation_title": conv_title,
                    "role": "user",
                },
            )

        await save_chunks(
            db,
            "message",
            full_response,
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
