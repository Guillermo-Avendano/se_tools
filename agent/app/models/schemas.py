"""Pydantic request/response models for the API."""

from typing import Literal

from pydantic import BaseModel, Field
from app.config import settings


class ChatMessage(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=10000)


class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The user's question.",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session ID. When provided, conversation history is stored/retrieved from Redis.",
    )
    context_hint: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional structured context injected ahead of the question.",
    )
    chat_history: list[ChatMessage] = Field(
        default_factory=list,
        max_length=50,
        description="Previous messages for context (used when session_id is not set).",
    )


class AskResponse(BaseModel):
    answer: str


class HealthResponse(BaseModel):
    status: str
    qdrant: str
    ollama: str
    redis: str


class OpenAITextContentBlock(BaseModel):
    type: Literal["text"]
    text: str = Field(default="")


class OpenAIImageURLBlockData(BaseModel):
    url: str


class OpenAIImageContentBlock(BaseModel):
    type: Literal["image_url"]
    image_url: OpenAIImageURLBlockData


OpenAIContentBlock = OpenAITextContentBlock | OpenAIImageContentBlock


# ─── OpenAI-compatible models (for AnythingLLM) ─────────────
class OpenAIChatMessage(BaseModel):
    role: str = Field(..., pattern=r"^(system|user|assistant)$")

    # OpenAI-compatible multimodal content blocks.
    # Supports:
    # - plain text string
    # - [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}]
    content: str | list[OpenAIContentBlock]


class OpenAIChatRequest(BaseModel):
    model: str = Field(default_factory=lambda: settings.agent_name)
    messages: list[OpenAIChatMessage] = Field(..., min_length=1)
    temperature: float = Field(default=0.0)
    max_tokens: int | None = Field(default=None)
    stream: bool = Field(default=False)


class OpenAIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatChoice(BaseModel):
    index: int = 0
    message: OpenAIChatMessage
    finish_reason: str = "stop"


class OpenAIChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str = Field(default_factory=lambda: settings.agent_name)
    choices: list[OpenAIChatChoice]
    usage: OpenAIUsage = OpenAIUsage()


class OpenAIModel(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = Field(default_factory=lambda: settings.agent_name)


class OpenAIModelList(BaseModel):
    object: str = "list"
    data: list[OpenAIModel]
