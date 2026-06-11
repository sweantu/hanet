import base64
import json
import uuid

import tiktoken
from llm import embeddings_model

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


async def save_chunks(db, collection: str, content: str, metadata: dict, keywords: list[str] = []) -> None:
    chunks = chunk_text(content)
    embeddings = await embeddings_model.aembed_documents(chunks)
    await db.executemany(
        "INSERT INTO documents (collection, content, metadata, embedding, fts, keywords) "
        "VALUES ($1, $2, $3::jsonb, $4::vector, to_tsvector('english', $2), $5::text[])",
        [
            (collection, chunk, json.dumps({**metadata, "chunk_index": i}), emb, keywords)
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ],
    )


async def save_memory(db, type: str, content: str) -> str:
    return await db.fetchval(
        "INSERT INTO memories (type, content) VALUES ($1, $2) RETURNING id::text",
        type,
        content,
    )


async def get_hot_memories(db) -> list[str]:
    rows = await db.fetch(
        "SELECT content FROM memories WHERE type = 'hot' ORDER BY created_at"
    )
    return [r["content"] for r in rows]


async def save_memory_embedding(db, memory_id: str, type: str, content: str, keywords: list[str]) -> None:
    embedding = await embeddings_model.aembed_query(content)
    fts_input = " ".join(keywords) if keywords else content
    await db.execute(
        "INSERT INTO documents (collection, content, metadata, embedding, fts, keywords) "
        "VALUES ($1, $2, $3::jsonb, $4::vector, to_tsvector('english', $5), $6::text[])",
        "memory",
        content,
        json.dumps({"memory_id": memory_id, "type": type}),
        embedding,
        fts_input,
        keywords,
    )


async def delete_memories(db, memory_ids: list[str]) -> int:
    await db.execute(
        "DELETE FROM documents WHERE collection = 'memory' AND metadata->>'memory_id' = ANY($1::text[])",
        memory_ids,
    )
    result = await db.execute(
        "DELETE FROM memories WHERE id = ANY($1::uuid[])",
        [uuid.UUID(mid) for mid in memory_ids],
    )
    return int(result.split()[-1])


async def update_memory(db, memory_id: str, new_content: str, keywords: list[str]) -> None:
    embedding = await embeddings_model.aembed_query(new_content)
    fts_input = " ".join(keywords) if keywords else new_content
    await db.execute(
        "UPDATE memories SET content=$2 WHERE id=$1::uuid",
        memory_id,
        new_content,
    )
    await db.execute(
        "UPDATE documents SET content=$2, embedding=$3::vector, "
        "fts=to_tsvector('english', $4), keywords=$5::text[] "
        "WHERE collection='memory' AND metadata->>'memory_id'=$1",
        memory_id,
        new_content,
        embedding,
        fts_input,
        keywords,
    )
    print(f"{memory_id} and {new_content}")


def encode_cursor(*parts: str) -> str:
    return base64.urlsafe_b64encode("|".join(parts).encode()).decode()


def decode_cursor(cursor: str) -> list[str]:
    return base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
