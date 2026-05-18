import json

from fastapi import APIRouter, Depends

from dependencies import get_db
from llm import embeddings_model, llm
from models import MessagePair, RagSearchRequest, RagSearchResponse, RankedChunk, SearchRequest
from rag import rag_retrieve
from sql import HYBRID_SEARCH_ASSISTANT_SQL, HYBRID_SEARCH_SQL

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/rag", response_model=RagSearchResponse)
async def rag_search(body: RagSearchRequest, db=Depends(get_db)):
    if not body.query.strip():
        return RagSearchResponse(hypothetical_answer="", chunks=[])

    hyde_response = await llm.ainvoke(
        [{"role": "user", "content": f"Write a concise answer to the following question:\n\n{body.query}"}]
    )
    hypothetical_answer = hyde_response.content
    query_embedding = await embeddings_model.aembed_query(hypothetical_answer)
    rows = await db.fetch(HYBRID_SEARCH_ASSISTANT_SQL, query_embedding, body.query, body.limit)

    if not rows:
        return RagSearchResponse(hypothetical_answer=hypothetical_answer, chunks=[])

    import re
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
                metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else dict(r["metadata"]),
                rrf_score=float(r["rrf_score"]),
                relevance_score=score,
            )
            for r, score in ranked
        ],
    )


@router.post("/rag/messages")
async def rag_search_messages(body: RagSearchRequest, db=Depends(get_db)) -> MessagePair | None:
    if not body.query.strip():
        return None
    return await rag_retrieve(body.query, body.limit, db)


@router.post("")
async def search(body: SearchRequest, db=Depends(get_db)):
    if not body.query.strip():
        return []
    query_embedding = await embeddings_model.aembed_query(body.query)
    rows = await db.fetch(HYBRID_SEARCH_SQL, query_embedding, body.query, body.limit)
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


@router.post("/semantic")
async def search_semantic(body: SearchRequest, db=Depends(get_db)):
    if not body.query.strip():
        return []
    query_embedding = await embeddings_model.aembed_query(body.query)
    rows = await db.fetch(
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
            "score": round(1 - float(r["distance"]), 4),
        }
        for r in rows
    ]


@router.post("/keyword")
async def search_keyword(body: SearchRequest, db=Depends(get_db)):
    if not body.query.strip():
        return []
    rows = await db.fetch(
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
