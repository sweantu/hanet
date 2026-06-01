import json
import re

from llm import embeddings_model, llm
from sql import HYBRID_SEARCH_ASSISTANT_SQL


async def rag_retrieve(query: str, limit: int, db) -> list[str]:
    query_embedding = await embeddings_model.aembed_query(query)
    rows = await db.fetch(HYBRID_SEARCH_ASSISTANT_SQL, query_embedding, query, limit)
    if not rows:
        return []

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

    qualifying: list[tuple] = []
    for row, score in ranked:
        if score < 8:
            continue
        meta = (
            row["metadata"]
            if isinstance(row["metadata"], dict)
            else json.loads(row["metadata"])
        )
        qualifying.append((meta.get("message_id"), row["content"]))

    if not qualifying:
        return []

    msg_ids = [q[0] for q in qualifying]
    fallbacks = {q[0]: q[1] for q in qualifying}

    fetched = await db.fetch(
        "SELECT id::text, content FROM messages WHERE id = ANY($1::uuid[])", msg_ids
    )
    content_by_id = {r["id"]: r["content"] for r in fetched}

    return [content_by_id.get(msg_id, fallbacks[msg_id]) for msg_id in msg_ids]
