import json
import os
from contextlib import asynccontextmanager

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(
        os.environ["DATABASE_URL"].replace("+asyncpg", "")
    )
    yield
    await app.state.db.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

llm = ChatOpenAI(model="gpt-4o-mini", streaming=True)


def call_model(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


builder = StateGraph(MessagesState)
builder.add_node("agent", call_model)
builder.add_edge(START, "agent")
builder.add_edge("agent", END)
graph = builder.compile()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    conversation_id: str | None = None


class ConversationCreate(BaseModel):
    title: str = "New Chat"


# ── Conversation endpoints ────────────────────────────────────────────────────

@app.get("/conversations")
async def list_conversations():
    rows = await app.state.db.fetch(
        "SELECT id, title, created_at FROM conversations ORDER BY updated_at DESC"
    )
    return [{"id": str(r["id"]), "title": r["title"], "created_at": r["created_at"].isoformat()} for r in rows]


@app.post("/conversations")
async def create_conversation(body: ConversationCreate = ConversationCreate()):
    row = await app.state.db.fetchrow(
        "INSERT INTO conversations (title) VALUES ($1) RETURNING id, title, created_at",
        body.title,
    )
    return {"id": str(row["id"]), "title": row["title"], "created_at": row["created_at"].isoformat()}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    result = await app.state.db.execute(
        "DELETE FROM conversations WHERE id = $1::uuid", conversation_id
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@app.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str):
    rows = await app.state.db.fetch(
        "SELECT role, content FROM messages WHERE conversation_id = $1::uuid ORDER BY created_at ASC",
        conversation_id,
    )
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(body: ChatRequest):
    conv_id = body.conversation_id

    if conv_id:
        user_msg = body.messages[-1]
        await app.state.db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3)",
            conv_id, user_msg.role, user_msg.content,
        )

        row = await app.state.db.fetchrow(
            "SELECT title FROM conversations WHERE id = $1::uuid", conv_id
        )
        if row and row["title"] == "New Chat":
            new_title = user_msg.content[:60].strip()
            await app.state.db.execute(
                "UPDATE conversations SET title = $1 WHERE id = $2::uuid",
                new_title, conv_id,
            )

    messages = [SystemMessage(content="You are a helpful assistant.")] + [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in body.messages
    ]

    async def generate():
        full_response: list[str] = []
        async for event in graph.astream_events({"messages": messages}, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    full_response.append(chunk.content)
                    yield f"data: {json.dumps({'text': chunk.content})}\n\n"
        yield "data: [DONE]\n\n"

        if conv_id and full_response:
            assistant_content = "".join(full_response)
            await app.state.db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3)",
                conv_id, "assistant", assistant_content,
            )
            await app.state.db.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid", conv_id
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
