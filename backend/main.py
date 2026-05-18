import base64
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime

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


def _encode_cursor(*parts: str) -> str:
    return base64.urlsafe_b64encode("|".join(parts).encode()).decode()


def _decode_cursor(cursor: str) -> list[str]:
    return base64.urlsafe_b64decode(cursor.encode()).decode().split("|")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: str


class ConversationCreate(BaseModel):
    title: str = "New Chat"


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    threshold: float | None = None  # min cosine similarity (0–1), semantic only


class RagSearchRequest(BaseModel):
    query: str
    limit: int = 10


class RankedChunk(BaseModel):
    id: str
    content: str
    conversation_title: str
    conversation_created_at: str
    metadata: dict
    rrf_score: float
    relevance_score: float


class RagSearchResponse(BaseModel):
    hypothetical_answer: str
    chunks: list[RankedChunk]


class MessagePair(BaseModel):
    message_id: str
    user_message: str | None
    assistant_message: str
    relevance_score: float
    conversation_title: str
    conversation_created_at: str


_HYBRID_SEARCH_SQL = """
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
        c.created_at AS conversation_created_at,
        f.rrf_score
    FROM fused f
    JOIN documents d ON d.id = f.id
    JOIN conversations c ON c.id = (d.metadata->>'conversation_id')::uuid
    ORDER BY f.rrf_score DESC
    LIMIT $3
"""

_HYBRID_SEARCH_ASSISTANT_SQL = """
    WITH semantic AS (
        SELECT d.id,
               ROW_NUMBER() OVER (ORDER BY d.embedding <=> $1::vector) AS rank
        FROM documents d
        WHERE d.embedding IS NOT NULL
          AND d.collection = 'message'
          AND d.metadata->>'role' = 'assistant'
        ORDER BY d.embedding <=> $1::vector
        LIMIT 50
    ),
    keyword AS (
        SELECT d.id,
               ROW_NUMBER() OVER (ORDER BY ts_rank(d.fts, query) DESC) AS rank
        FROM documents d, plainto_tsquery('english', $2) query
        WHERE d.fts @@ query
          AND d.collection = 'message'
          AND d.metadata->>'role' = 'assistant'
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
        c.created_at AS conversation_created_at,
        f.rrf_score
    FROM fused f
    JOIN documents d ON d.id = f.id
    JOIN conversations c ON c.id = (d.metadata->>'conversation_id')::uuid
    ORDER BY f.rrf_score DESC
    LIMIT $3
"""


async def _rag_retrieve(query: str, limit: int, db) -> MessagePair | None:
    hyde_response = await llm.ainvoke(
        [
            {
                "role": "user",
                "content": f"Write a concise answer to the following question:\n\n{query}",
            }
        ]
    )
    query_embedding = await embeddings_model.aembed_query(hyde_response.content)
    rows = await db.fetch(_HYBRID_SEARCH_ASSISTANT_SQL, query_embedding, query, limit)
    if not rows:
        return None

    chunks_text = "\n\n".join(f"[{i + 1}] {r['content']}" for i, r in enumerate(rows))
    rerank_response = await llm.ainvoke(
        [
            {
                "role": "user",
                "content": (
                    f"Query: {query}\n\n"
                    f"Rate each passage 0–10 for relevance to the query. "
                    f"Reply ONLY with a JSON array of numbers, one per passage, in the same order.\n\n"
                    f"{chunks_text}"
                ),
            }
        ]
    )
    try:
        match = re.search(r"\[[\d\s.,]+\]", rerank_response.content)
        if not match:
            raise ValueError("no JSON array")
        scores = [float(s) for s in json.loads(match.group())]
        if len(scores) != len(rows):
            raise ValueError("score count mismatch")
    except (json.JSONDecodeError, ValueError):
        scores = [float(r["rrf_score"]) for r in rows]

    ranked = sorted(zip(rows, scores), key=lambda x: x[1], reverse=True)
    best_row, best_score = ranked[0]
    if best_score < 8:
        return None

    meta = (
        best_row["metadata"]
        if isinstance(best_row["metadata"], dict)
        else json.loads(best_row["metadata"])
    )
    msg_id = meta.get("message_id")
    conv_id = meta.get("conversation_id")

    asst_row = await db.fetchrow(
        "SELECT content FROM messages WHERE id = $1::uuid", msg_id
    )
    asst_content = asst_row["content"] if asst_row else best_row["content"]

    user_row = await db.fetchrow(
        """SELECT content FROM messages
           WHERE conversation_id = $1::uuid AND role = 'user'
             AND created_at < (SELECT created_at FROM messages WHERE id = $2::uuid)
           ORDER BY created_at DESC LIMIT 1""",
        conv_id,
        msg_id,
    )
    return MessagePair(
        message_id=msg_id,
        user_message=user_row["content"] if user_row else None,
        assistant_message=asst_content,
        relevance_score=best_score,
        conversation_title=best_row["conversation_title"],
        conversation_created_at=best_row["conversation_created_at"].isoformat(),
    )


# ── Conversation endpoints ────────────────────────────────────────────────────

@app.get("/conversations")
async def list_conversations(cursor: str | None = None, limit: int = 10):
    fetch_limit = limit + 1
    if cursor:
        pivot_ts, pivot_id = _decode_cursor(cursor)
        pivot_dt = datetime.fromisoformat(pivot_ts)
        rows = await app.state.db.fetch(
            """SELECT id, title, created_at, updated_at FROM conversations
               WHERE updated_at < $1 OR (updated_at = $1 AND id::text < $2)
               ORDER BY updated_at DESC, id DESC LIMIT $3""",
            pivot_dt, pivot_id, fetch_limit,
        )
    else:
        rows = await app.state.db.fetch(
            """SELECT id, title, created_at, updated_at FROM conversations
               ORDER BY updated_at DESC, id DESC LIMIT $1""",
            fetch_limit,
        )
    has_more = len(rows) > limit
    items = list(rows[:limit])
    next_cursor = None
    if has_more:
        last = items[-1]
        next_cursor = _encode_cursor(last["updated_at"].isoformat(), str(last["id"]))
    return {
        "items": [{"id": str(r["id"]), "title": r["title"], "created_at": r["created_at"].isoformat()} for r in items],
        "next_cursor": next_cursor,
    }


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
async def get_messages(conversation_id: str, cursor: str | None = None, limit: int = 10):
    if limit == 0:
        rows = await app.state.db.fetch(
            "SELECT id, role, content FROM messages WHERE conversation_id = $1::uuid ORDER BY created_at ASC",
            conversation_id,
        )
        return {
            "items": [{"id": str(r["id"]), "role": r["role"], "content": r["content"]} for r in rows],
            "prev_cursor": None,
        }

    fetch_limit = limit + 1
    if cursor:
        pivot_ts, pivot_id = _decode_cursor(cursor)
        pivot_dt = datetime.fromisoformat(pivot_ts)
        rows = await app.state.db.fetch(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = $1::uuid
                 AND (created_at < $2 OR (created_at = $2 AND id::text < $3))
               ORDER BY created_at DESC LIMIT $4""",
            conversation_id, pivot_dt, pivot_id, fetch_limit,
        )
    else:
        rows = await app.state.db.fetch(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = $1::uuid
               ORDER BY created_at DESC LIMIT $2""",
            conversation_id, fetch_limit,
        )
    has_more = len(rows) > limit
    page = list(rows[:limit])
    prev_cursor = None
    if has_more:
        oldest = page[-1]  # last in DESC order = oldest in this page
        prev_cursor = _encode_cursor(oldest["created_at"].isoformat(), str(oldest["id"]))
    page.reverse()  # return oldest-first for the UI
    return {
        "items": [{"id": str(r["id"]), "role": r["role"], "content": r["content"]} for r in page],
        "prev_cursor": prev_cursor,
    }


# ── Search endpoints ──────────────────────────────────────────────────────────


@app.post("/search/rag", response_model=RagSearchResponse)
async def rag_search(body: RagSearchRequest):
    if not body.query.strip():
        return RagSearchResponse(hypothetical_answer="", chunks=[])

    hyde_response = await llm.ainvoke(
        [
            {
                "role": "user",
                "content": f"Write a concise answer to the following question:\n\n{body.query}",
            }
        ]
    )
    hypothetical_answer = hyde_response.content

    query_embedding = await embeddings_model.aembed_query(hypothetical_answer)
    rows = await app.state.db.fetch(
        _HYBRID_SEARCH_ASSISTANT_SQL, query_embedding, body.query, body.limit
    )

    if not rows:
        return RagSearchResponse(hypothetical_answer=hypothetical_answer, chunks=[])

    chunks_text = "\n\n".join(f"[{i + 1}] {r['content']}" for i, r in enumerate(rows))
    rerank_response = await llm.ainvoke(
        [
            {
                "role": "user",
                "content": (
                    f"Query: {body.query}\n\n"
                    f"Rate each passage 0–10 for relevance to the query. "
                    f"Reply ONLY with a JSON array of numbers, one per passage, in the same order.\n\n"
                    f"{chunks_text}"
                ),
            }
        ]
    )

    try:
        print("rerank response", rerank_response.content)
        match = re.search(r"\[[\d\s.,]+\]", rerank_response.content)
        if not match:
            raise ValueError("no JSON array in rerank response")
        scores = json.loads(match.group())
        if not isinstance(scores, list) or len(scores) != len(rows):
            raise ValueError("score count mismatch")
        scores = [float(s) for s in scores]
    except (json.JSONDecodeError, ValueError):
        scores = [float(r["rrf_score"]) for r in rows]

    ranked = sorted(zip(rows, scores), key=lambda x: x[1], reverse=True)

    return RagSearchResponse(
        hypothetical_answer=hypothetical_answer,
        chunks=[
            RankedChunk(
                id=str(r["id"]),
                content=r["content"],
                conversation_title=r["conversation_title"],
                conversation_created_at=r["conversation_created_at"].isoformat(),
                metadata=json.loads(r["metadata"])
                if isinstance(r["metadata"], str)
                else dict(r["metadata"]),
                rrf_score=float(r["rrf_score"]),
                relevance_score=score,
            )
            for r, score in ranked
        ],
    )


@app.post("/search/rag/messages")
async def rag_search_messages(body: RagSearchRequest) -> MessagePair | None:
    if not body.query.strip():
        return None
    return await _rag_retrieve(body.query, body.limit, app.state.db)


@app.post("/search")
async def search(body: SearchRequest):
    if not body.query.strip():
        return []

    query_embedding = await embeddings_model.aembed_query(body.query)

    rows = await app.state.db.fetch(
        _HYBRID_SEARCH_SQL, query_embedding, body.query, body.limit
    )

    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
            "conversation_title": r["conversation_title"],
            "conversation_created_at": r["conversation_created_at"].isoformat(),
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
               c.created_at AS conversation_created_at,
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
            "conversation_created_at": r["conversation_created_at"].isoformat(),
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
               c.created_at AS conversation_created_at,
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
            "conversation_created_at": r["conversation_created_at"].isoformat(),
            "score": float(r["rank"]),
        }
        for r in rows
    ]


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(body: ChatRequest):
    conv_id = body.conversation_id

    user_msg_id = await app.state.db.fetchval(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id",
        conv_id, "user", body.message,
    )

    row = await app.state.db.fetchrow(
        "SELECT title FROM conversations WHERE id = $1::uuid", conv_id
    )
    if row and row["title"] == "New Chat":
        await app.state.db.execute(
            "UPDATE conversations SET title = $1 WHERE id = $2::uuid",
            body.message[:60].strip(), conv_id,
        )

    # Build context from the 10 most recent messages in the DB (includes the user message just saved)
    ctx_rows = await app.state.db.fetch(
        """SELECT id, role, content FROM messages
           WHERE conversation_id = $1::uuid
           ORDER BY created_at DESC LIMIT 10""",
        conv_id,
    )
    ctx_rows = list(reversed(ctx_rows))

    rag_pair = await _rag_retrieve(body.message, 5, app.state.db)

    ctx_ids = {str(r["id"]) for r in ctx_rows}
    inject_rag = (
        rag_pair and rag_pair.user_message and rag_pair.message_id not in ctx_ids
    )

    lc_messages = [SystemMessage(content="You are a helpful assistant.")]
    if inject_rag:
        lc_messages.append(HumanMessage(content=rag_pair.user_message))
        lc_messages.append(AIMessage(content=rag_pair.assistant_message))
    lc_messages += [
        HumanMessage(content=r["content"])
        if r["role"] == "user"
        else AIMessage(content=r["content"])
        for r in ctx_rows
    ]

    async def generate():
        full_response: list[str] = []
        async for event in graph.astream_events({"messages": lc_messages}, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    full_response.append(chunk.content)
                    yield f"data: {json.dumps({'text': chunk.content})}\n\n"
        yield "data: [DONE]\n\n"

        if full_response:
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

            await save_chunks(app.state.db, "message", body.message, {
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
