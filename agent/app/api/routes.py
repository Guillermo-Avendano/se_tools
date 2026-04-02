"""API routes for the SE-Content-Agent."""

import re
import httpx
import structlog
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.schemas import (
    AskRequest,
    AskResponse,
    HealthResponse,
)
from app.agent.core import ask_agent, get_skill_registry
from app.memory.qdrant_store import get_qdrant_client
from app.memory.chat_history import ping_redis, get_history, append_messages, clear_history

logger = structlog.get_logger(__name__)

router = APIRouter()

# Phrases that trigger a chat-history reset (matched at the start of a message).
_RESET_PHRASES = [
    "nuevo tema", "new topic", "reset", "nueva conversación",
    "nueva conversacion", "olvida lo anterior", "forget previous",
    "limpiar historial", "clear history", "empezar de nuevo", "start over",
]
_RESET_PATTERN = re.compile(
    r"^\s*(?:" + "|".join(re.escape(p) for p in _RESET_PHRASES) + r")\b[.:,;!\s]*",
    re.IGNORECASE,
)


def _parse_context_hint(context_hint: str | None) -> dict[str, str]:
    """Parse pipe-delimited key=value UI context into a structured dict for logs."""
    if not context_hint:
        return {}

    parsed: dict[str, str] = {}
    for segment in context_hint.split("|"):
        item = segment.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            parsed[key] = value
    return parsed


def _merge_context_hint(question: str, context_hint: str | None) -> str:
    """Prepend structured UI context so the agent can use it without the user repeating it."""
    if not context_hint:
        return question

    cleaned_hint = context_hint.strip()
    if not cleaned_hint:
        return question

    return (
        "SE Tools context for this turn:\n"
        f"{cleaned_hint}\n\n"
        "Use this context when it is relevant to the user's question. "
        "Do not claim hidden state beyond what is provided here.\n\n"
        f"User question:\n{question}"
    )


# ─── Health Check ────────────────────────────────────────────
@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check():
    """Check connectivity to all services."""
    # Qdrant
    qdrant_status = "ok"
    try:
        client = get_qdrant_client()
        client.get_collections()
    except Exception as e:
        qdrant_status = f"error: {e}"

    # Ollama
    ollama_status = "ok"
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            resp = await http.get(f"{settings.ollama_base_url}/")
            if resp.status_code != 200:
                ollama_status = f"http {resp.status_code}"
    except Exception as e:
        ollama_status = f"error: {e}"

    # Redis
    redis_status = await ping_redis()

    overall = "healthy" if all(
        s == "ok" for s in [qdrant_status, ollama_status, redis_status]
    ) else "degraded"

    return HealthResponse(
        status=overall,
        qdrant=qdrant_status,
        ollama=ollama_status,
        redis=redis_status,
    )


# ─── Ask the Agent ───────────────────────────────────────────
@router.post("/ask", response_model=AskResponse, tags=["agent"])
async def ask(request: AskRequest):
    """Send a natural-language question to the AI agent."""
    logger.info("api.ask", question=request.question[:100],
                session_id=request.session_id)
    try:
        # Detect reset phrases at the start of the message
        question = request.question
        history_reset = False
        reset_match = _RESET_PATTERN.match(question)
        if reset_match:
            history_reset = True
            # Strip the reset phrase — keep the rest as the actual question
            question = question[reset_match.end():].strip()

        # Clear Redis history if reset was requested
        if history_reset and request.session_id:
            logger.info("api.ask.reset_history", session_id=request.session_id)
            await clear_history(request.session_id)

        # Build chat history: Redis-backed if session_id given, else from request
        if request.session_id:
            chat_history = await get_history(
                request.session_id, max_turns=settings.redis_max_turns
            ) if not history_reset else []
        else:
            chat_history = [] if history_reset else [msg.model_dump() for msg in request.chat_history]

        # If the reset phrase consumed the entire message, use a neutral prompt
        if not question:
            question = request.question

        effective_question = _merge_context_hint(question, request.context_hint)
        effective_context = _parse_context_hint(request.context_hint)

        if effective_context:
            logger.info(
                "api.ask.context_effective",
                session_id=request.session_id,
                history_reset=history_reset,
                context=effective_context,
                original_question=question[:200],
                effective_question=effective_question[:500],
            )

        result = await ask_agent(
            question=effective_question,
            chat_history=chat_history if chat_history else None,
        )

        # Persist the turn in Redis if session_id was provided
        if request.session_id:
            await append_messages(
                request.session_id, request.question, result["answer"]
            )

        return AskResponse(**result)
    except Exception as e:
        logger.error("api.ask.error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")


# ─── Clear Conversation History ──────────────────────────────
@router.delete("/chat/{session_id}", tags=["agent"])
async def delete_chat_history(session_id: str):
    """Clear conversation history for a given session."""
    await clear_history(session_id)
    return {"status": "cleared", "session_id": session_id}


# ─── Skills Introspection ────────────────────────────────────
@router.get("/skills", tags=["system"])
async def list_skills():
    """List all registered skills and their status."""
    registry = get_skill_registry()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "enabled": s.enabled,
                "tools": [t.name for t in s.get_tools()],
            }
            for s in registry.all_skills
        ]
    }


@router.post("/reindex", tags=["system"])
async def reindex_knowledge():
    """
    Force reindexing of knowledge base and files in Qdrant.
    Detects changes automatically via fingerprinting.
    Useful when new files are added to workspace/knowledge/ without container restart.
    """
    try:
        from app.memory.file_loader import load_files_for_memory, load_knowledge_for_memory
        
        logger.info("reindex.started")
        
        files_chunks = load_files_for_memory(force_reindex=True)
        knowledge_chunks = load_knowledge_for_memory(force_reindex=True)
        
        logger.info("reindex.completed", files_chunks=files_chunks, knowledge_chunks=knowledge_chunks)
        
        return {
            "success": True,
            "message": "Reindexing completed successfully",
            "files_chunks": files_chunks,
            "knowledge_chunks": knowledge_chunks,
            "total_chunks": files_chunks + knowledge_chunks,
        }
    except Exception as e:
        logger.error("reindex.error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Reindexing failed: {str(e)}")
