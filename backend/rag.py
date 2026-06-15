import json

from llm import embeddings_model, llm
from pydantic import BaseModel as PydanticBaseModel
from sql import HYBRID_SEARCH_ASSISTANT_SQL, HYBRID_SEARCH_MEMORIES_SQL


class _Scores(PydanticBaseModel):
    scores: list[float]


_scoring_llm = llm.with_structured_output(_Scores)


async def _llm_score(query: str, rows: list) -> list[float]:
    if not rows:
        return []
    chunks_text = "\n\n".join(f"[{i + 1}] {r['content']}" for i, r in enumerate(rows))
    try:
        content = (
            f"Query: {query}\n\n"
            f"Score each passage 0–10 for relevance to the query.\n"
            f"- 9–10: directly answers the query (exact item or category asked about)\n"
            f"- 7–8: clearly relevant — same topic, category, or concept\n"
            f"- 4–6: tangentially related or partially relevant\n"
            f"- 1–3: mostly unrelated, only superficial connection\n"
            f"- 0: completely irrelevant\n\n"
            f"Consider semantic relationships: e.g. 'coffee', 'tea', 'juice' are drinks; "
            f"'rice', 'noodles', 'buns' are food; 'taxi', 'grab', 'bus' are transport.\n\n"
            f"Return one score per passage in the same order.\n\n"
            f"{chunks_text}"
        )
        print(f"[content]: {content}")
        result = await _scoring_llm.ainvoke(
            [
                {
                    "role": "user",
                    "content": content,
                }
            ]
        )
        if len(result.scores) != len(rows):
            raise ValueError("score count mismatch")
        print(f"[scores]: {result.scores}")
        return result.scores
    except Exception:
        return [float(r["rrf_score"]) for r in rows]


async def search_database_impl(query: str, limit: int, db) -> list[str]:
    query_embedding = await embeddings_model.aembed_query(query)
    rows = await db.fetch(HYBRID_SEARCH_ASSISTANT_SQL, query_embedding, query, limit)
    if not rows:
        return []

    scores = await _llm_score(query, rows)
    ranked = sorted(zip(rows, scores), key=lambda x: x[1], reverse=True)

    qualifying: list[tuple] = []
    for row, score in ranked:
        if score < 7:
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


async def search_memories_impl(query: str, limit: int, db) -> list[str]:
    query_embedding = await embeddings_model.aembed_query(query)
    rows = await db.fetch(HYBRID_SEARCH_MEMORIES_SQL, query_embedding, query, limit)
    if not rows:
        return []
    scores = await _llm_score(query, rows)
    return [r["content"] for r, s in zip(rows, scores) if s >= 7]


async def search_memories_with_ids_impl(query: str, limit: int, db) -> list[dict]:
    query_embedding = await embeddings_model.aembed_query(query)
    rows = await db.fetch(HYBRID_SEARCH_MEMORIES_SQL, query_embedding, query, limit)
    if not rows:
        return []
    scores = await _llm_score(query, rows)
    result = []
    for r, s in zip(rows, scores):
        if s < 5:
            continue
        meta = (
            r["metadata"]
            if isinstance(r["metadata"], dict)
            else json.loads(r["metadata"])
        )
        result.append({"memory_id": meta["memory_id"], "content": r["content"]})
    return result
