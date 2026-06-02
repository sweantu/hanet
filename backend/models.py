from typing import TypedDict

from pydantic import BaseModel


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

