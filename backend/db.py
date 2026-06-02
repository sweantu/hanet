import base64
import json

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


def encode_cursor(*parts: str) -> str:
    return base64.urlsafe_b64encode("|".join(parts).encode()).decode()


def decode_cursor(cursor: str) -> list[str]:
    return base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
