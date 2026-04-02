"""OpenAI-compatible API routes for AnythingLLM integration.

Exposes /v1/chat/completions and /v1/models so AnythingLLM
can treat this agent as a custom LLM provider.
"""

import json
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agent.core import ask_agent
from app.config import settings
from app.memory.chat_history import get_history, append_messages
from app.models.schemas import (
    OpenAIChatRequest,
    OpenAIChatResponse,
    OpenAIChatChoice,
    OpenAIChatMessage,
    OpenAIUsage,
    OpenAIModel,
    OpenAIModelList,
)

logger = structlog.get_logger(__name__)

openai_router = APIRouter(prefix="/v1", tags=["openai-compatible"])


def _truncate(value: str, limit: int = 500) -> str:
    """Return a log-safe preview string."""
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def _normalize_message_content(content: Any) -> tuple[str, list[dict[str, Any]] | None]:
    """Normalize OpenAI message content into (plain_text, multimodal_blocks)."""
    if isinstance(content, str):
        return content, None

    if not isinstance(content, list):
        return str(content), None

    text_parts: list[str] = []
    blocks: list[dict[str, Any]] = []

    for block in content:
        block_dict = block.model_dump() if hasattr(block, "model_dump") else block
        if not isinstance(block_dict, dict):
            continue

        block_type = block_dict.get("type")
        if block_type == "text":
            text = block_dict.get("text", "")
            if text:
                text_parts.append(text)
            blocks.append({"type": "text", "text": text})
        elif block_type == "image_url":
            image_url = block_dict.get("image_url") or {}
            url = image_url.get("url", "") if isinstance(image_url, dict) else ""
            if url:
                blocks.append({"type": "image_url", "image_url": {"url": url}})

    text = "\n".join(part for part in text_parts if part).strip()
    if not text and any(b.get("type") == "image_url" for b in blocks):
        text = "Please analyze the attached image."

    return text, (blocks if blocks else None)


@openai_router.get("/models", response_model=OpenAIModelList)
async def list_models():
    """List available models (AnythingLLM calls this on setup)."""
    return OpenAIModelList(
        data=[
            OpenAIModel(id=settings.agent_name, created=int(time.time())),
        ]
    )


@openai_router.post("/chat/completions")
async def chat_completions(
    request: OpenAIChatRequest,
    raw_request: Request,
):
    """OpenAI-compatible chat completions — routes through the SE-Content-Agent."""

    session_id = raw_request.headers.get("X-Session-ID")

    # Extract the last user message as the question
    question = ""
    question_content_blocks = None
    chat_history = []
    system_messages: list[str] = []

    for msg in request.messages:
        plain_text, blocks = _normalize_message_content(msg.content)

        if msg.role == "system":
            if plain_text:
                system_messages.append(plain_text)
            continue
        elif msg.role == "user":
            if question:
                chat_history.append({"role": "user", "content": question})
            question = plain_text
            question_content_blocks = blocks
        elif msg.role == "assistant":
            # Flush any pending user question BEFORE the assistant reply
            # so the history stays in chronological order.
            if question:
                chat_history.append({"role": "user", "content": question})
                question = ""
                question_content_blocks = None
            chat_history.append({"role": "assistant", "content": plain_text})

    # If session_id provided, merge Redis history with inline history
    if session_id and not chat_history:
        chat_history = await get_history(session_id, max_turns=settings.redis_max_turns)

    if not question:
        answer = "No user message provided."
    else:
        effective_context = {
            "session_id": session_id,
            "history_turns": len(chat_history),
            "system_messages": [_truncate(msg, 300) for msg in system_messages],
            "has_image": bool(
                question_content_blocks
                and any(block.get("type") == "image_url" for block in question_content_blocks)
            ),
            "user_content_types": [
                block.get("type") for block in (question_content_blocks or []) if isinstance(block, dict)
            ],
        }
        logger.info(
            "openai_compat.context_effective",
            question=_truncate(question, 200),
            effective_question=_truncate(question, 500),
            context=effective_context,
        )
        try:
            result = await ask_agent(
                question=question,
                chat_history=chat_history if chat_history else None,
                user_message_content=question_content_blocks,
            )
            answer = result["answer"]

            # Persist the turn in Redis
            if session_id:
                await append_messages(session_id, question, answer)

        except Exception as e:
            logger.error("openai_compat.error", error=str(e))
            answer = f"Error processing your question: {e}"

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    # ── Streaming response (SSE) ─────────────────────────────
    if request.stream:
        async def _stream_sse():
            # Single content chunk with the full answer
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": answer},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

            # Final chunk signaling completion
            done_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(done_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _stream_sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Non-streaming response ───────────────────────────────
    return OpenAIChatResponse(
        id=completion_id,
        created=created,
        model=request.model,
        choices=[
            OpenAIChatChoice(
                message=OpenAIChatMessage(role="assistant", content=answer),
            )
        ],
        usage=OpenAIUsage(),
    )
