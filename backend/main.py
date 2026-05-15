import json
import os
from contextlib import asynccontextmanager

import asyncpg
import tiktoken
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, MessagesState, StateGraph
from pgvector.asyncpg import register_vector
from pydantic import BaseModel

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(
        os.environ["DATABASE_URL"].replace("+asyncpg", ""),
        init=register_vector,
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
embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small")

_enc = tiktoken.encoding_for_model("text-embedding-3-small")
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


def chunk_text(text: str) -> list[str]:
    tokens = _enc.encode(text)
    chunks, start = [], 0
    while start < len(tokens):
        end = start + CHUNK_SIZE
        chunks.append(_enc.decode(tokens[start:end]))
        if end >= len(tokens):
            break
        start = end - CHUNK_OVERLAP
    return chunks


async def save_chunks(db, collection: str, content: str, metadata: dict) -> None:
    chunks = chunk_text(content)
    embeddings = await embeddings_model.aembed_documents(chunks)
    await db.executemany(
        "INSERT INTO documents (collection, content, metadata, embedding) "
        "VALUES ($1, $2, $3::jsonb, $4::vector)",
        [
            (collection, chunk, json.dumps({**metadata, "chunk_index": i}), emb)
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ],
    )


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


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    threshold: float | None = None  # min cosine similarity (0–1), semantic only


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


# ── Search endpoint ───────────────────────────────────────────────────────────

@app.post("/search")
async def search(body: SearchRequest):
    if not body.query.strip():
        return []

    query_embedding = await embeddings_model.aembed_query(body.query)

    rows = await app.state.db.fetch(
        """
        WITH semantic AS (
            SELECT d.id,
                   ROW_NUMBER() OVER (ORDER BY d.embedding <=> $1::vector) AS rank
            FROM documents d
            WHERE d.embedding IS NOT NULL
              AND d.collection = 'message'
            ORDER BY d.embedding <=> $1::vector
            LIMIT 50
        ),
        keyword AS (
            SELECT d.id,
                   ROW_NUMBER() OVER (ORDER BY ts_rank(d.fts, query) DESC) AS rank
            FROM documents d, plainto_tsquery('english', $2) query
            WHERE d.fts @@ query
              AND d.collection = 'message'
            ORDER BY rank
            LIMIT 50
        ),
        fused AS (
            SELECT
                COALESCE(s.id, k.id) AS id,
                COALESCE(1.0 / (60 + s.rank), 0.0) +
                COALESCE(1.0 / (60 + k.rank), 0.0) AS rrf_score
            FROM semantic s
            FULL OUTER JOIN keyword k USING (id)
        )
        SELECT
            f.id,
            d.content,
            d.metadata,
            c.title AS conversation_title,
            f.rrf_score
        FROM fused f
        JOIN documents d ON d.id = f.id
        JOIN conversations c ON c.id = (d.metadata->>'conversation_id')::uuid
        ORDER BY f.rrf_score DESC
        LIMIT $3
        """,
        query_embedding,
        body.query,
        body.limit,
    )

    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
            "conversation_title": r["conversation_title"],
            "rrf_score": float(r["rrf_score"]),
        }
        for r in rows
    ]


@app.post("/search/semantic")
async def search_semantic(body: SearchRequest):
    if not body.query.strip():
        return []

    query_embedding = await embeddings_model.aembed_query(body.query)

    rows = await app.state.db.fetch(
        f"""
        SELECT d.id, d.content, d.metadata,
               c.title AS conversation_title,
               d.embedding <=> $1::vector AS distance
        FROM documents d
        JOIN conversations c ON c.id = (d.metadata->>'conversation_id')::uuid
        WHERE d.embedding IS NOT NULL
          AND d.collection = 'message'
          {"AND d.embedding <=> $1::vector <= $3" if body.threshold is not None else ""}
        ORDER BY distance
        LIMIT $2
        """,
        query_embedding,
        body.limit,
        *([1 - body.threshold] if body.threshold is not None else []),
    )

    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
            "conversation_title": r["conversation_title"],
            "score": round(1 - float(r["distance"]), 4),  # cosine similarity = 1 - distance
        }
        for r in rows
    ]


@app.post("/search/keyword")
async def search_keyword(body: SearchRequest):
    if not body.query.strip():
        return []

    rows = await app.state.db.fetch(
        """
        SELECT d.id, d.content, d.metadata,
               c.title AS conversation_title,
               ts_rank(d.fts, plainto_tsquery('english', $1)) AS rank
        FROM documents d
        JOIN conversations c ON c.id = (d.metadata->>'conversation_id')::uuid
        WHERE d.fts @@ plainto_tsquery('english', $1)
          AND d.collection = 'message'
        ORDER BY rank DESC
        LIMIT $2
        """,
        body.query,
        body.limit,
    )

    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
            "conversation_title": r["conversation_title"],
            "score": float(r["rank"]),
        }
        for r in rows
    ]


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(body: ChatRequest):
    conv_id = body.conversation_id

    if conv_id:
        user_msg = body.messages[-1]
        user_msg_id = await app.state.db.fetchval(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
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
            asst_msg_id = await app.state.db.fetchval(
                "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
                conv_id, "assistant", assistant_content,
            )
            await app.state.db.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid", conv_id
            )

            conv_row = await app.state.db.fetchrow(
                "SELECT title FROM conversations WHERE id = $1::uuid", conv_id
            )
            conv_title = conv_row["title"] if conv_row else ""

            await save_chunks(app.state.db, "message", body.messages[-1].content, {
                "message_id": str(user_msg_id),
                "conversation_id": conv_id,
                "conversation_title": conv_title,
                "role": "user",
            })
            await save_chunks(app.state.db, "message", assistant_content, {
                "message_id": str(asst_msg_id),
                "conversation_id": conv_id,
                "conversation_title": conv_title,
                "role": "assistant",
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
