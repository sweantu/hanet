import json
import re

from models import MessagePair
from llm import llm, embeddings_model
from sql import HYBRID_SEARCH_ASSISTANT_SQL


async def rag_retrieve(query: str, limit: int, db) -> MessagePair | None:
    hyde_response = await llm.ainvoke(
        [{"role": "user", "content": f"Write a concise answer to the following question:\n\n{query}"}]
    )
    query_embedding = await embeddings_model.aembed_query(hyde_response.content)
    rows = await db.fetch(HYBRID_SEARCH_ASSISTANT_SQL, query_embedding, query, limit)
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

    asst_row = await db.fetchrow("SELECT content FROM messages WHERE id = $1::uuid", msg_id)
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
