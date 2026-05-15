"""One-time script to chunk and embed existing messages into the documents table."""
import asyncio
import json
import os

import asyncpg
import tiktoken
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from pgvector.asyncpg import register_vector

load_dotenv()

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


async def main():
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"].replace("+asyncpg", ""),
        init=register_vector,
    )
    model = OpenAIEmbeddings(model="text-embedding-3-small")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT m.id, m.conversation_id, m.role, m.content, c.title
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE NOT EXISTS (
                   SELECT 1 FROM documents d
                   WHERE d.metadata->>'message_id' = m.id::text
               )
               ORDER BY m.created_at"""
        )

    print(f"Backfilling {len(rows)} messages...")
    for i, row in enumerate(rows):
        chunks = chunk_text(row["content"])
        embeddings = await model.aembed_documents(chunks)
        records = [
            (
                chunk,
                json.dumps({
                    "message_id": str(row["id"]),
                    "conversation_id": str(row["conversation_id"]),
                    "conversation_title": row["title"],
                    "role": row["role"],
                    "chunk_index": j,
                }),
                emb,
            )
            for j, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO documents (collection, content, metadata, embedding) "
                "VALUES ('message', $1, $2::jsonb, $3::vector)",
                records,
            )
        if (i + 1) % 10 == 0 or i + 1 == len(rows):
            print(f"  {i + 1}/{len(rows)}")

    await pool.close()
    print("Done.")


asyncio.run(main())
