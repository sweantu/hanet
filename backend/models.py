from datetime import datetime
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, model_validator


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


class Memory(BaseModel):
    type: str  # 'hot' | 'cold'
    content: str
    keywords: list[str] = []
    created_at: datetime


class ResumeRequest(BaseModel):
    conversation_id: str
    action: Literal["approve", "deny", "replan"]
    message: Optional[str] = None

    @model_validator(mode="after")
    def replan_requires_message(self) -> "ResumeRequest":
        if self.action == "replan" and not (self.message and self.message.strip()):
            raise ValueError("message is required when action is 'replan'")
        return self

