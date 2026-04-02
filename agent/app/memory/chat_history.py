"""Redis-backed conversation history — short-term memory per session."""

import json
import structlog
import redis.asyncio as aioredis

from app.config import settings

logger = structlog.get_logger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return a shared async Redis client (lazy singleton)."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis


def _key(session_id: str) -> str:
    return f"chat:{session_id}"


async def get_history(session_id: str, max_turns: int | None = None) -> list[dict]:
    """Retrieve conversation history for a session.

    Returns list of {"role": "user"|"assistant", "content": "..."}.
    """
    r = get_redis()
    raw = await r.lrange(_key(session_id), 0, -1)
    messages = [json.loads(m) for m in raw]
    if max_turns is not None:
        # Each turn = 1 user + 1 assistant = 2 messages
        messages = messages[-(max_turns * 2):]
    return messages


async def append_messages(
    session_id: str,
    user_msg: str,
    assistant_msg: str,
) -> None:
    """Append a user/assistant turn and refresh the TTL."""
    r = get_redis()
    key = _key(session_id)
    pipe = r.pipeline()
    pipe.rpush(key, json.dumps({"role": "user", "content": user_msg}))
    pipe.rpush(key, json.dumps({"role": "assistant", "content": assistant_msg}))
    pipe.expire(key, settings.redis_chat_ttl)
    await pipe.execute()


async def clear_history(session_id: str) -> None:
    """Delete conversation history for a session."""
    r = get_redis()
    await r.delete(_key(session_id))


async def ping_redis() -> str:
    """Health check — returns 'ok' or error string."""
    try:
        r = get_redis()
        await r.ping()
        return "ok"
    except Exception as e:
        return f"error: {e}"
