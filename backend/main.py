import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pgvector.asyncpg import register_vector

from graph import build_graph
from routers import chat, conversations, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(
        os.environ["DATABASE_URL"].replace("+asyncpg", ""),
        init=register_vector,
    )

    pg_conn_string = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    async with AsyncPostgresSaver.from_conn_string(pg_conn_string) as checkpointer:
        await checkpointer.setup()
        app.state.graph = build_graph(checkpointer)
        yield

    await app.state.db.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(search.router)
