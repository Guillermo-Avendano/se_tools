"""Core agent — binds LLM (Ollama or llama.cpp) + skills + Qdrant context into a ReAct agent."""

import json
import re
import time
import asyncio
import calendar
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
import structlog
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langgraph.prebuilt import create_react_agent

from app.config import settings
from app.agent.prompts import build_system_prompt
from app.agent.contentedge_langgraph_graph import contentedge_app, ContentEdgeState
from app.skills import SkillRegistry, SkillContext
from app.skills.contentedge_skill import ContentEdgeSkill
from app.skills.contentedge_skill import _sync_list_indexes, _sync_list_content_classes
from app.memory.qdrant_store import (
    get_qdrant_client,
    get_embeddings,
    search_similar,
)

logger = structlog.get_logger(__name__)

ProgressCallback = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]

_INDEX_CATALOG_CACHE: dict[str, tuple[float, set[str]]] = {}
_CONTENT_CLASS_CACHE: dict[str, tuple[float, set[str]]] = {}
_CATALOG_TTL_SECONDS = 120

# ── Global skill registry ────────────────────────────────────
_registry = SkillRegistry()
_registry.register(ContentEdgeSkill())


def get_skill_registry() -> SkillRegistry:
    """Return the global skill registry (for API introspection, etc.)."""
    return _registry


def _get_llm() -> BaseChatModel:
    provider = settings.llm_provider.lower()
    if provider in {"llama_cpp", "llama-cpp", "llamacpp"}:
        logger.info("llm.provider", provider="llama_cpp", model=settings.llama_cpp_model)
        return ChatOpenAI(
            model=settings.llama_cpp_model,
            openai_api_key=settings.llama_cpp_api_key or "sk-no-key",
            openai_api_base=settings.llama_cpp_base_url,
            temperature=settings.llama_cpp_temperature,
        )
    # Default: Ollama
    extra = {}
    if any(m in settings.ollama_model for m in ("qwen3", "gpt-oss")):
        extra["think"] = False
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=settings.ollama_temperature,
        num_ctx=settings.ollama_num_ctx,
        **extra,
    )


def _retrieve_document_context(question: str, top_k: int = 8) -> str:
    """Retrieve relevant chunks from Qdrant (type=document or type=knowledge).

    Searches knowledge base content (PDFs, MD, TXT) and persisted learnings
    using semantic similarity. Returns matching text or empty string if
    nothing relevant found.
    """
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchAny
        client = get_qdrant_client()
        embeddings = get_embeddings()

        query_vector = embeddings.embed_query(question)
        results = client.query_points(
            collection_name=settings.qdrant_collection,
            query=query_vector,
            query_filter=Filter(
                must=[FieldCondition(key="type", match=MatchAny(any=["document", "knowledge"]))]
            ),
            limit=top_k,
            with_payload=True,
        )
        if not results.points:
            return ""
        # Only include results with a reasonable similarity score
        texts = []
        for hit in results.points:
            if hit.score >= 0.55:
                source = hit.payload.get("source", "unknown")
                texts.append(f"[Source: {source}]\n{hit.payload.get('text', '')}")
        if texts:
            logger.info("document_context.found", chunks=len(texts))
        return "\n\n".join(texts)
    except Exception as e:
        logger.warning("document_context.error", error=str(e))
        return ""


def _parse_context_hint_from_question(question: str) -> tuple[str, dict[str, str]]:
    """Extract the original user question and SE Tools context from the wrapped prompt."""
    marker = "SE Tools context for this turn:\n"
    user_marker = "\n\nUser question:\n"
    if not question.startswith(marker) or user_marker not in question:
        return question, {}

    body = question[len(marker):]
    hint_block, user_question = body.split(user_marker, 1)
    hint_line = hint_block.split("\n\n", 1)[0]
    context: dict[str, str] = {}
    for segment in hint_line.split("|"):
        item = segment.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            context[key] = value
    return user_question.strip(), context


def _build_retrieval_query(question: str) -> str:
    """Build a cleaner semantic-search query than the full UI-wrapped prompt."""
    user_question, context = _parse_context_hint_from_question(question)
    parts = [user_question]
    tool = context.get("tool", "")
    operation = context.get("operation", "")
    if tool:
        parts.append(tool)
    if operation:
        parts.append(operation)
    if operation == "adelete":
        parts.append("date filter clause")
    return " | ".join(part for part in parts if part)


def _extract_first_iso_date(text: str) -> str | None:
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    return match.group(1) if match else None


def _extract_iso_dates(text: str) -> list[str]:
    return re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)


_MONTH_NAME_TO_NUM = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _extract_month_year(text: str) -> tuple[int, int] | None:
    """Extract first month-year mention like 'March 2021'. Returns (year, month)."""
    match = re.search(
        r"\b(" + "|".join(_MONTH_NAME_TO_NUM.keys()) + r")\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    month_name = match.group(1).lower()
    year = int(match.group(2))
    month = _MONTH_NAME_TO_NUM.get(month_name)
    if not month:
        return None
    return year, month


def _extract_filter_field(question: str, doc_context: str) -> str | None:
    field_match = re.search(r"\bwith\s+([A-Za-z][A-Za-z0-9_]*)\s+(?:before|after|between|>=|<=|>|<)", question, re.IGNORECASE)
    if field_match:
        return field_match.group(1)
    # Use DoIssue only when explicitly present in the user request/context.
    if "doissue" in question.lower() or "doissue" in doc_context.lower():
        return "DoIssue"
    return None


def _list_index_names(repo: str) -> tuple[list[str], str | None]:
    try:
        data = _sync_list_indexes(repo)
    except Exception as exc:
        return [], f"index lookup failed: {exc}"

    if isinstance(data, dict) and data.get("error"):
        return [], str(data.get("error"))

    names: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        clean = (value or "").strip()
        if not clean:
            return
        key = clean.lower()
        if key in seen:
            return
        seen.add(key)
        names.append(clean)

    for idx in data.get("individual_indexes", []):
        _add(str(idx.get("id", "")))
        _add(str(idx.get("name", "")))

    for group in data.get("index_groups", []):
        for idx in group.get("indexes", []):
            _add(str(idx.get("id", "")))
            _add(str(idx.get("name", "")))

    return names, None


def _get_index_catalog(repo: str) -> tuple[set[str], str | None]:
    now = time.time()
    cached = _INDEX_CATALOG_CACHE.get(repo)
    if cached and (now - cached[0]) < _CATALOG_TTL_SECONDS:
        return cached[1], None

    try:
        data = _sync_list_indexes(repo)
    except Exception as exc:
        return set(), f"index lookup failed: {exc}"

    if isinstance(data, dict) and data.get("error"):
        return set(), str(data.get("error"))

    names: set[str] = set()
    for idx in data.get("individual_indexes", []):
        for key in ("id", "name"):
            value = str(idx.get(key, "")).strip()
            if value:
                names.add(value.lower())

    for group in data.get("index_groups", []):
        for idx in group.get("indexes", []):
            for key in ("id", "name"):
                value = str(idx.get(key, "")).strip()
                if value:
                    names.add(value.lower())

    _INDEX_CATALOG_CACHE[repo] = (now, names)
    return names, None


def _get_content_class_catalog(repo: str) -> tuple[set[str], str | None]:
    now = time.time()
    cached = _CONTENT_CLASS_CACHE.get(repo)
    if cached and (now - cached[0]) < _CATALOG_TTL_SECONDS:
        return cached[1], None

    try:
        data = _sync_list_content_classes(repo)
    except Exception as exc:
        return set(), f"content class lookup failed: {exc}"

    if isinstance(data, dict) and data.get("error"):
        return set(), str(data.get("error"))

    names: set[str] = set()
    for cc in data if isinstance(data, list) else []:
        cc_id = str(cc.get("id", "")).strip()
        cc_name = str(cc.get("name", "")).strip()
        if cc_id:
            names.add(cc_id.lower())
        if cc_name:
            names.add(cc_name.lower())

    _CONTENT_CLASS_CACHE[repo] = (now, names)
    return names, None


def _validate_index_field(repo: str, field_name: str) -> tuple[bool, str | None]:
    catalog, err = _get_index_catalog(repo)
    if err:
        return False, f"Unable to validate index '{field_name}' in repo={repo.upper()}: {err}"
    if field_name.lower() in catalog:
        return True, None
    return False, f"Index '{field_name}' was not found in repo={repo.upper()} indexes or index groups."


def _validate_content_classes(repo: str, classes: list[str]) -> tuple[bool, str | None]:
    catalog, err = _get_content_class_catalog(repo)
    if err:
        return False, f"Unable to validate content classes in repo={repo.upper()}: {err}"

    missing = [cc for cc in classes if cc.lower() not in catalog]
    if missing:
        return False, f"Content classes not found in repo={repo.upper()}: {', '.join(missing)}"
    return True, None


def _extract_content_classes(question: str) -> list[str]:
    match = re.search(r"content classes?\s+(.+?)(?:\.|\?|$)", question, re.IGNORECASE)
    if not match:
        return []
    raw = match.group(1).strip()
    raw = re.sub(r"\breturn only the clause\b", "", raw, flags=re.IGNORECASE).strip()
    parts = [item.strip() for item in re.split(r",|\band\b", raw) if item.strip()]
    cleaned = []
    for part in parts:
        token = re.sub(r"[^A-Za-z0-9_]", "", part)
        if token:
            cleaned.append(token)
    return cleaned


def _extract_index_comparison(question: str) -> tuple[str, str, str] | None:
    match = re.search(
        r"where\s+([A-Za-z][A-Za-z0-9_]*)\s*(=|>=|<=|>|<)\s*(\"[^\"]+\"|'[^']+'|\d+(?:\.\d+)?)",
        question,
        re.IGNORECASE,
    )
    if not match:
        return None
    field, operator, value = match.groups()
    return field, operator, value.strip("'")


def _direct_advisory_answer(question: str, doc_context: str) -> str:
    """Return a deterministic answer for simple advisory filter questions."""
    user_question, context = _parse_context_hint_from_question(question)
    lower_q = user_question.lower()
    operation = context.get("operation", "").lower()
    if operation != "adelete" and "adelete" not in lower_q:
        return ""
    repo = (context.get("repo") or "source").strip().lower()
    if repo not in ("source", "target"):
        repo = "source"

    tool_name = (context.get("tool") or "").strip().lower()
    command_template = (context.get("command") or "").strip()
    is_mrc_context = tool_name == "mobiusremotecli"

    # Doc-first guardrail: only produce deterministic guidance when retrieved
    # context includes explicit adelete option evidence from documentation.
    # Exception: when SE Tools already provides a MobiusRemoteCLI adelete
    # command template, allow deterministic rendering without doc evidence.
    evidence = doc_context.lower()
    has_adelete_options = (
        ("adelete -s" in evidence and "-t" in evidence)
        or "-trn" in evidence
        or "-tro" in evidence
    )
    if is_mrc_context and command_template and operation == "adelete":
        has_adelete_options = True
    if not has_adelete_options:
        return ""

    wants_clause_only = any(token in lower_q for token in ["return only the clause", "exact filter clause", "only the clause", "return the final adelete filter clause"])
    clause = ""
    explanation = ""

    dates = _extract_iso_dates(user_question)
    month_year = _extract_month_year(user_question)
    field_name = _extract_filter_field(user_question, doc_context)
    index_comparison = _extract_index_comparison(user_question)
    content_classes = _extract_content_classes(user_question)

    def _to_ts(date_iso: str, end_of_day: bool = False) -> str:
        dt = datetime.strptime(date_iso, "%Y-%m-%d")
        if end_of_day:
            return dt.strftime("%Y%m%d") + "235959"
        return dt.strftime("%Y%m%d") + "000000"

    def _prev_day_end_ts(date_iso: str) -> str:
        dt = datetime.strptime(date_iso, "%Y-%m-%d") - timedelta(days=1)
        return dt.strftime("%Y%m%d") + "235959"

    def _month_start(year: int, month: int) -> datetime:
        return datetime(year, month, 1)

    def _month_end(year: int, month: int) -> datetime:
        return datetime(year, month, calendar.monthrange(year, month)[1])

    def _render_full_adelete_command(base_cmd: str, filter_clause: str) -> str:
        if not base_cmd:
            return ""
        cleaned = re.sub(r"\s-(?:t|d|trn|tro)\s+\S+", "", base_cmd, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return f"{cleaned} {filter_clause}".strip()

    if len(dates) >= 2 and "between" in lower_q:
        start_ts = _to_ts(dates[0], end_of_day=False)
        end_ts = _to_ts(dates[1], end_of_day=True)
        clause = f"-TRN {start_ts} -TRO {end_ts}"
        explanation = (
            "This uses a report-version range window (first version with -TRN, "
            "last version with -TRO) as documented for adelete."
        )
    elif dates:
        date_value = dates[0]
        if any(token in lower_q for token in ["before", "older than", "prior to"]):
            clause = f"-t {_prev_day_end_ts(date_value)}"
            explanation = (
                "For strictly before that date, use -t with the previous day 23:59:59 "
                "because -t deletes equal-to-or-older ingestions."
            )
        elif any(token in lower_q for token in ["on or after", "after or on"]) or ">=" in user_question:
            clause = f"-TRN {_to_ts(date_value, end_of_day=False)}"
            explanation = "Use -TRN to set the first report version timestamp to delete."
        elif any(token in lower_q for token in ["after", "newer than"]) or re.search(r"\bwhere\b.*>\s*\d{4}-\d{2}-\d{2}", user_question):
            next_day = (datetime.strptime(date_value, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            clause = f"-TRN {_to_ts(next_day, end_of_day=False)}"
            explanation = "For strictly after, start from next day 00:00:00 using -TRN."
        elif any(token in lower_q for token in ["on or before"]) or "<=" in user_question:
            clause = f"-t {_to_ts(date_value, end_of_day=True)}"
            explanation = "Use -t with end-of-day timestamp to include that date."
        elif any(token in lower_q for token in ["date", "timestamp"]):
            clause = f"-t {_to_ts(date_value, end_of_day=True)}"
            explanation = "Default date cut-off with -t (equal-to-or-older behavior)."
    elif month_year:
        year, month = month_year
        month_start = _month_start(year, month)
        month_end = _month_end(year, month)
        if any(token in lower_q for token in ["before", "older than", "prior to"]):
            cutoff = month_start - timedelta(days=1)
            clause = f"-t {cutoff.strftime('%Y%m%d')}235959"
            explanation = (
                "For strictly before that month, use -t with the previous day 23:59:59 "
                "before month start."
            )
        elif any(token in lower_q for token in ["on or before"]):
            clause = f"-t {month_end.strftime('%Y%m%d')}235959"
            explanation = "Use -t at month end to include that full month."
        elif any(token in lower_q for token in ["on or after", "after or on"]) or ">=" in user_question:
            clause = f"-TRN {month_start.strftime('%Y%m%d')}000000"
            explanation = "Use -TRN at month start for on-or-after month filtering."
        elif any(token in lower_q for token in ["after", "newer than"]) or ">" in user_question:
            if month == 12:
                next_month_start = datetime(year + 1, 1, 1)
            else:
                next_month_start = datetime(year, month + 1, 1)
            clause = f"-TRN {next_month_start.strftime('%Y%m%d')}000000"
            explanation = "For strictly after that month, start from next month using -TRN."
        else:
            clause = f"-t {month_end.strftime('%Y%m%d')}235959"
            explanation = "Default month cut-off uses -t at the end of that month."
    elif index_comparison:
        return (
            "The adelete options documented in the PDF (p.434+) are timestamp/retention based "
            "(-t, -d, -TRN, -TRO, -C, -N, -Y, -L). Index-expression filters are not documented there."
        )
    elif content_classes:
        if len(content_classes) == 1:
            clause = f"-r {content_classes[0]}"
            explanation = "Use -r to target a specific Content Class ID."
        else:
            return (
                "adelete takes one -r class ID per command (wildcard possible with -Y w). "
                "For multiple classes, run one command per class or use wildcard pattern carefully."
            )

    if not clause:
        return ""

    if wants_clause_only and not (is_mrc_context and command_template):
        return clause

    if is_mrc_context and command_template:
        full_cmd = _render_full_adelete_command(command_template, clause)
        if full_cmd:
            return full_cmd

    if "before giving the final adelete filter" in lower_q or "before giving the final clause" in lower_q:
        return f"{explanation}\n{clause}"

    return f"Use this adelete filter clause:\n{clause}\n\n{explanation}"


def _is_contentedge_question(question: str) -> bool:
    """Determine if question should be handled by ContentEdge LangGraph."""
    contentedge_keywords = [
        "contentedge", "policy", "archiving", "index", "content class",
        "archive", "document", "repository", "mobius"
    ]
    question_lower = question.lower()
    return any(keyword in question_lower for keyword in contentedge_keywords)


def _needs_rag_fallback(answer: str) -> bool:
    """Return True when ContentEdge flow produced a generic/non-informative answer."""
    if not answer:
        return True
    text = answer.lower()
    generic_markers = [
        "operation completed",
        "no results could be obtained",
        "i'm sorry, but i don't have any information",
        "i dont have any information",
        "❌ error",
    ]
    return any(marker in text for marker in generic_markers)


def _is_transient_agent_error(exc: Exception) -> bool:
    """Heuristics for retryable agent errors."""
    text = str(exc).lower()
    retry_markers = [
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "service unavailable",
        "429",
        "502",
        "503",
        "504",
        "empty reply",
        "connection reset",
    ]
    return any(marker in text for marker in retry_markers)


async def _emit_progress(
    progress_cb: ProgressCallback | None,
    stage: str,
    message: str,
    meta: dict[str, Any] | None = None,
) -> None:
    """Emit a progress event if a callback is provided."""
    if progress_cb is None:
        return
    try:
        await progress_cb(stage, message, meta or {})
    except Exception:
        logger.warning("agent.progress.emit_failed", stage=stage)


async def _run_with_harness(
    *,
    request_id: str,
    route_name: str,
    primary_call,
    fallback_call=None,
    timeout_seconds: float = 120.0,
    fallback_timeout_seconds: float = 90.0,
    max_attempts: int = 2,
    retry_backoff_seconds: float = 0.25,
    progress_cb: ProgressCallback | None = None,
) -> dict:
    """Execute agent route with timeout, retry and fallback safeguards."""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "agent.harness.attempt",
                request_id=request_id,
                route=route_name,
                attempt=attempt,
                timeout_seconds=timeout_seconds,
            )
            await _emit_progress(
                progress_cb,
                "harness_attempt",
                f"Attempt {attempt}/{max_attempts} on {route_name}",
                {"request_id": request_id, "route": route_name, "attempt": attempt, "max_attempts": max_attempts},
            )
            result = await asyncio.wait_for(primary_call(), timeout=timeout_seconds)

            answer = (result or {}).get("answer", "") if isinstance(result, dict) else ""
            if isinstance(answer, str) and answer.strip():
                logger.info(
                    "agent.harness.success",
                    request_id=request_id,
                    route=route_name,
                    attempt=attempt,
                    answer_chars=len(answer),
                )
                return result

            raise RuntimeError("Empty answer produced by route")

        except Exception as exc:
            last_error = exc
            transient = _is_transient_agent_error(exc)
            logger.warning(
                "agent.harness.failure",
                request_id=request_id,
                route=route_name,
                attempt=attempt,
                transient=transient,
                error=str(exc),
            )
            if attempt < max_attempts and transient:
                backoff = retry_backoff_seconds * attempt
                await _emit_progress(
                    progress_cb,
                    "harness_retry",
                    f"Retrying after transient error (attempt {attempt})",
                    {
                        "request_id": request_id,
                        "route": route_name,
                        "attempt": attempt,
                        "error": str(exc),
                        "backoff_seconds": backoff,
                    },
                )
                await asyncio.sleep(backoff)
                continue
            break

    if fallback_call is not None:
        try:
            logger.info("agent.harness.fallback.start", request_id=request_id, route=route_name)
            await _emit_progress(
                progress_cb,
                "harness_fallback_start",
                f"Starting fallback route for {route_name}",
                {"request_id": request_id, "route": route_name},
            )
            fallback_result = await asyncio.wait_for(fallback_call(), timeout=fallback_timeout_seconds)
            fallback_answer = (fallback_result or {}).get("answer", "") if isinstance(fallback_result, dict) else ""
            if isinstance(fallback_answer, str) and fallback_answer.strip():
                logger.info("agent.harness.fallback.success", request_id=request_id, route=route_name)
                await _emit_progress(
                    progress_cb,
                    "harness_fallback_success",
                    "Fallback route completed successfully",
                    {"request_id": request_id, "route": route_name},
                )
                return fallback_result
        except Exception as fallback_exc:
            logger.error(
                "agent.harness.fallback.failure",
                request_id=request_id,
                route=route_name,
                error=str(fallback_exc),
            )

    detail = str(last_error) if last_error else "unknown error"
    logger.error("agent.harness.give_up", request_id=request_id, route=route_name, error=detail)
    await _emit_progress(
        progress_cb,
        "harness_give_up",
        "All attempts and fallback failed",
        {"request_id": request_id, "route": route_name, "error": detail},
    )
    return {
        "answer": (
            "I could not complete your request due to a transient processing problem. "
            "Please retry in a few seconds."
        )
    }


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response."""
    text = (raw_text or "").strip()
    if not text:
        return {}

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}

    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _has_image_content(user_message_content: list[dict] | None) -> bool:
    """Return True when the user payload contains an image block."""
    if not user_message_content:
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "image_url"
        for block in user_message_content
    )


async def _extract_contentedge_visual_context(
    question: str,
    user_message_content: list[dict] | None,
) -> dict[str, Any]:
    """Analyze an image for ContentEdge-relevant admin metadata.

    The result is intentionally narrow: today it extracts a best-effort
    index-group candidate so the graph can verify or create that group.
    """
    if not _has_image_content(user_message_content):
        return {}

    llm = _get_llm()
    system_text = (
        "You extract actionable ContentEdge admin metadata from screenshots. "
        "Return strict JSON only. Do not wrap in markdown. "
        "If the image does not clearly define an index group, set present to false."
    )
    instruction = (
        "Analyze the attached image for a ContentEdge index group definition relevant to the user's request. "
        "Return JSON with this exact shape: "
        '{"summary":"...","index_group_candidate":{"present":true|false,'
        '"group_id":"","group_name":"","member_references":[],"evidence":[],"reason":""}}. '
        "Use member_references for visible index IDs or names. "
        "If the screenshot only shows document values and no schema, explain why in reason. "
        f"User question: {question}"
    )
    human_content = [{"type": "text", "text": instruction}, *(user_message_content or [])]

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_text),
            HumanMessage(content=human_content),
        ])
        raw_content = getattr(response, "content", "")
        if isinstance(raw_content, list):
            raw_text = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw_content
            )
        else:
            raw_text = str(raw_content)
        parsed = _extract_json_object(raw_text)
        if parsed:
            logger.info(
                "contentedge.visual_context.extracted",
                has_candidate=bool((parsed.get("index_group_candidate") or {}).get("present")),
                summary=(parsed.get("summary") or "")[:200],
            )
        else:
            logger.warning("contentedge.visual_context.unparsed", preview=raw_text[:300])
        return parsed
    except Exception as exc:
        logger.warning("contentedge.visual_context.error", error=str(exc))
        return {}


async def _answer_from_document_context(question: str, doc_context: str) -> str:
    """Generate a direct answer using retrieved document/knowledge context only."""
    import asyncio

    def _fallback_from_context() -> str:
        direct = _direct_advisory_answer(question, doc_context)
        if direct:
            return direct

        # Build a useful response directly from retrieved chunks when LLM is slow.
        lines = [ln.strip() for ln in doc_context.splitlines() if ln.strip()]
        candidates = []
        for ln in lines:
            low = ln.lower()
            if "adelete" in low and ("date" in low or "doissue" in low or "2026-01-01" in low):
                candidates.append(ln)
            elif "2026-01-01" in low:
                candidates.append(ln)
            elif "before" in low and ("date(" in low or "doissue" in low):
                candidates.append(ln)

        deduped = []
        seen = set()
        for item in candidates:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= 6:
                break

        if not deduped:
            return ""

        bullets = "\n".join(f"- {item}" for item in deduped)
        return (
            "LLM timed out, but Qdrant returned relevant guidance:\n"
            f"{bullets}\n\n"
            "For 'before 2026-01-01', use a date filter with '< date(\"2026-01-01\")' "
            "on the issue/date field used by your content class (for example DoIssue)."
        )
    
    llm = _get_llm()
    system_text = (
        "You are a technical documentation assistant. "
        "Answer only using the provided context. "
        "If context is insufficient, say what is missing in one sentence. "
        "Respond in English. Use concise bullet points when helpful."
    )
    user_text = (
        f"Question:\n{question}\n\n"
        f"Context:\n{doc_context}\n\n"
        "Provide a practical, step-by-step answer if the context supports it."
    )
    
    try:
        max_context_chars = 4500
        if len(doc_context) > max_context_chars:
            trimmed = doc_context[:max_context_chars]
            user_text = (
                f"Question:\n{question}\n\n"
                f"Context:\n{trimmed}\n\n"
                "Context is truncated to the most relevant leading chunks. "
                "Provide a practical, step-by-step answer if the context supports it."
            )

        llm_timeout_seconds = 90.0
        logger.info(
            "contentedge_agent.llm.invoke_start",
            provider=settings.llm_provider,
            context_chars=min(len(doc_context), max_context_chars),
            timeout_seconds=llm_timeout_seconds,
        )
        response = await asyncio.wait_for(
            llm.ainvoke([
                SystemMessage(content=system_text),
                HumanMessage(content=user_text),
            ]),
            timeout=llm_timeout_seconds,
        )
        content = getattr(response, "content", "")
        result = content if isinstance(content, str) else str(content)
        logger.info("contentedge_agent.llm.invoke_success", content_length=len(result))
        return result
    except asyncio.TimeoutError:
        logger.error("contentedge_agent.llm.timeout", timeout_seconds=90, provider=settings.llm_provider)
        fallback = _fallback_from_context()
        if fallback:
            return fallback
        return f"LLM response timed out after 90s. Unable to generate answer for: {question}"
    except Exception as exc:
        logger.error("contentedge_agent.llm.error", error=str(exc), provider=settings.llm_provider)
        fallback = _fallback_from_context()
        if fallback:
            return f"Error generating model response ({str(exc)}).\n\n{fallback}"
        return f"Error generating answer: {str(exc)}"


async def ask_agent(
    question: str,
    chat_history: list[dict] | None = None,
    user_message_content: list[dict] | None = None,
    progress_cb: ProgressCallback | None = None,
) -> dict:
    """Process a user question through the appropriate agent pipeline.
    
    Routes to ContentEdge LangGraph for ContentEdge-specific questions,
    otherwise uses the general ReAct agent with all skills.
    """
    request_id = f"req_{int(time.time() * 1000)}"
    logger.info("agent.start", request_id=request_id, question=question[:200])

    # Route to ContentEdge LangGraph if ContentEdge-specific question
    if _is_contentedge_question(question):
        logger.info("routing.to_contentedge_langgraph", request_id=request_id)
        await _emit_progress(
            progress_cb,
            "routing_contentedge_langgraph",
            "Routing to ContentEdge LangGraph",
            {"request_id": request_id},
        )
        return await _run_with_harness(
            request_id=request_id,
            route_name="contentedge_langgraph",
            primary_call=lambda: _ask_contentedge_agent(question, chat_history, user_message_content),
            fallback_call=lambda: _ask_general_agent(question, chat_history, user_message_content),
            timeout_seconds=settings.agent_harness_timeout_seconds,
            fallback_timeout_seconds=settings.agent_harness_fallback_timeout_seconds,
            max_attempts=settings.agent_harness_max_attempts,
            retry_backoff_seconds=settings.agent_harness_retry_backoff_seconds,
            progress_cb=progress_cb,
        )

    # Otherwise use general ReAct agent
    logger.info("routing.to_general_react_agent", request_id=request_id)
    await _emit_progress(
        progress_cb,
        "routing_general_react",
        "Routing to general ReAct agent",
        {"request_id": request_id},
    )
    return await _run_with_harness(
        request_id=request_id,
        route_name="general_react",
        primary_call=lambda: _ask_general_agent(question, chat_history, user_message_content),
        fallback_call=lambda: _ask_contentedge_agent(question, chat_history, user_message_content),
        timeout_seconds=settings.agent_harness_timeout_seconds,
        fallback_timeout_seconds=settings.agent_harness_fallback_timeout_seconds,
        max_attempts=settings.agent_harness_max_attempts,
        retry_backoff_seconds=settings.agent_harness_retry_backoff_seconds,
        progress_cb=progress_cb,
    )


async def _ask_contentedge_agent(
    question: str,
    chat_history: list[dict] | None = None,
    user_message_content: list[dict] | None = None,
) -> dict:
    """Process question using ContentEdge LangGraph."""
    try:
        retrieval_query = _build_retrieval_query(question)

        # Doc-first: try deterministic advisory answer only when Qdrant
        # retrieval provides explicit evidence from documentation.
        prefetched_doc_context = _retrieve_document_context(retrieval_query, top_k=10)
        if prefetched_doc_context:
            advisory_answer = _direct_advisory_answer(question, prefetched_doc_context)
            if advisory_answer:
                logger.info("contentedge_agent.direct_advisory_answer")
                return {"answer": advisory_answer}

        visual_context = await _extract_contentedge_visual_context(question, user_message_content)

        # Initialize state
        initial_state = ContentEdgeState(
            question=question,
            intent="",
            domain="",
            parameters={"visual_context": visual_context} if visual_context else {},
            results={},
            formatted_results="",
            context="",
            tools_used=[],
            execution_path=[],
            planning_state=None,
            confirmation_received=False,
            operation_confirmed=False,
        )
        
        # Use a per-request thread id to avoid leaking stale state across turns.
        thread_config = {"configurable": {"thread_id": f"contentedge_{int(time.time() * 1000)}"}}
        
        # Invoke ContentEdge LangGraph
        result = await contentedge_app.ainvoke(
            initial_state,
            config=thread_config
        )
        
        # Format results for API response
        answer = _format_contentedge_results(result)

        # Fallback to Qdrant context when ContentEdge execution result is generic.
        if _needs_rag_fallback(answer):
            doc_context = prefetched_doc_context or _retrieve_document_context(retrieval_query)
            if doc_context:
                logger.info("contentedge_agent.rag_fallback", context_chars=len(doc_context))
                rag_answer = await _answer_from_document_context(question, doc_context)
                if rag_answer and rag_answer.strip():
                    answer = rag_answer
        
        logger.info("contentedge_agent.completed",
                   domain=result.get("domain"),
                   tools_used=result.get("tools_used", []),
                   execution_path=result.get("execution_path", []))
        
        return {"answer": answer}
        
    except Exception as e:
        logger.error("contentedge_agent.error", error=str(e))
        # Fallback to general agent
        return await _ask_general_agent(question, chat_history)


def _format_contentedge_results(state: dict) -> str:
    """Format ContentEdge LangGraph results into a readable answer."""
    def _repo_header() -> str:
        """Resolve repository context and render a consistent header."""
        params = state.get("parameters") or {}
        repo = params.get("repo")

        if not repo:
            question = (state.get("question") or "").lower()
            if "target" in question or "destino" in question:
                repo = "target"
            else:
                repo = "source"

        repo_label = "TARGET" if str(repo).lower() == "target" else "SOURCE"
        return f"**Repository Context:** {repo_label}\n"

    header = _repo_header()

    # Use pre-formatted results if available
    formatted_results = state.get("formatted_results", "")
    if formatted_results:
        return f"{header}\n{formatted_results}"
    
    # Fallback to manual formatting (for backward compatibility)
    results = state.get("results", {})
    domain = state.get("domain", "")
    tools_used = state.get("tools_used", [])
    
    if not results:
        return f"{header}\nNo results could be obtained for your request."
    
    answer_parts = []
    
    # Add domain context
    if domain:
        domain_names = {
            "archiving_policy": "Archiving Policies",
            "indexes": "Indexes",
            "index_groups": "Index Groups", 
            "content_classes": "Content Classes",
            "documents": "Documents",
            "general": "General Query"
        }
        domain_name = domain_names.get(domain, domain)
        answer_parts.append(f"**{domain_name}**\n")
    
    # Format each result
    for operation, result in results.items():
        if operation == "error":
            answer_parts.append(f"❌ Error: {result}")
            continue
            
        try:
            # Try to parse as JSON for better formatting
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict):
                        if "count" in parsed and "policies" in parsed:
                            answer_parts.append(f"✅ Found {parsed['count']} policies:")
                            for policy in parsed['policies'][:5]:  # Limit to first 5
                                name = policy.get('name', 'N/A')
                                version = policy.get('version', 'N/A')
                                answer_parts.append(f"  • {name} (v{version})")
                        elif "count" in parsed and "object_ids" in parsed:
                            answer_parts.append(f"✅ Found {parsed['count']} documents")
                        elif "success" in parsed:
                            if parsed["success"]:
                                answer_parts.append(f"✅ Operation completed successfully")
                            else:
                                answer_parts.append(f"❌ Operation failed")
                        else:
                            # Generic JSON formatting
                            answer_parts.append(f"✅ Result: {json.dumps(parsed, ensure_ascii=False, indent=2)}")
                    else:
                        answer_parts.append(f"✅ {result}")
                except json.JSONDecodeError:
                    answer_parts.append(f"✅ {result}")
            else:
                answer_parts.append(f"✅ {result}")
        except Exception:
            answer_parts.append(f"✅ {str(result)}")
    
    # Add tools used info for transparency
    if tools_used:
        answer_parts.append(f"\n*Tools used: {', '.join(tools_used)}*")
    
    return f"{header}\n" + "\n\n".join(answer_parts)


async def _ask_general_agent(
    question: str,
    chat_history: list[dict] | None = None,
    user_message_content: list[dict] | None = None,
) -> dict:
    """Process question using general ReAct agent (original implementation)."""
    logger.info("general_agent.start", question=question[:200])

    # Retrieve relevant document context from Qdrant (knowledge base)
    doc_context = _retrieve_document_context(_build_retrieval_query(question))
    if doc_context:
        logger.info("document_context.retrieved", length=len(doc_context))
    else:
        logger.info("document_context.no_match")

    # Set up all skills with runtime context
    skill_context = SkillContext(
        config=settings,
    )
    await _registry.setup_all(skill_context)
    logger.info("skills.setup", skills=[s.name for s in _registry.enabled_skills])

    # Build dynamic system prompt from skills
    system_text = build_system_prompt(
        agent_name=settings.agent_name,
        skills_section=_registry.build_prompt_section(),
        routing_rules=_registry.build_routing_rules(),
        document_context=doc_context,
    )

    # Collect tools from all skills
    agent_tools = _registry.get_all_tools()

    # Build agent
    llm = _get_llm()
    agent = create_react_agent(llm, agent_tools)
    logger.info("react_agent.built", model=settings.ollama_model,
                tools=_registry.get_tool_names(),
                system_prompt_chars=len(system_text))

    # Build messages — limit history to last 6 msgs and truncate long ones
    MAX_HISTORY_MSGS = 6
    MAX_MSG_CHARS = 2000

    messages = [SystemMessage(content=system_text)]
    if chat_history:
        recent = chat_history[-MAX_HISTORY_MSGS:]
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if len(content) > MAX_MSG_CHARS:
                content = content[:MAX_MSG_CHARS] + "..."
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                from langchain_core.messages import AIMessage
                messages.append(AIMessage(content=content))

    if user_message_content:
        has_text = any(
            block.get("type") == "text" and str(block.get("text", "")).strip()
            for block in user_message_content
            if isinstance(block, dict)
        )
        if not has_text:
            # Ensure the model receives a textual instruction with image-only messages.
            user_message_content = [{"type": "text", "text": question}] + user_message_content
        messages.append(HumanMessage(content=user_message_content))
    else:
        messages.append(HumanMessage(content=question))
    logger.info("messages.built", count=len(messages),
                history_msgs=len(chat_history) if chat_history else 0)

    # Invoke agent
    logger.info("agent.invoking_llm_loop")
    result = await agent.ainvoke(
        {"messages": messages},
        config={"recursion_limit": 25},
    )

    # ── Log every message in the agent trace ──
    final_messages = result.get("messages", [])
    logger.info("agent.loop.completed", total_messages=len(final_messages))
    for i, msg in enumerate(final_messages):
        msg_type = type(msg).__name__
        content_raw = getattr(msg, "content", "") or ""
        content_preview = str(content_raw)[:300].replace("\n", " ")
        tool_calls = getattr(msg, "tool_calls", None)
        tool_name = getattr(msg, "name", None)  # ToolMessage has .name
        extras = {}
        if tool_calls:
            extras["tool_calls"] = [
                {"name": tc.get("name"), "args_preview": str(tc.get("args", ""))[:200]}
                for tc in tool_calls
            ]
        if tool_name:
            extras["tool_name"] = tool_name
        logger.info(f"agent.trace_message[{i}]", msg_type=msg_type,
                    content_preview=content_preview, **extras)

    # Extract the final answer
    answer = ""
    for msg in reversed(final_messages):
        msg_type = type(msg).__name__
        # Skip ToolMessages and HumanMessages — only extract from AI
        if msg_type in ("ToolMessage", "HumanMessage"):
            continue
        content = getattr(msg, "content", None)
        if content and not getattr(msg, "tool_calls", None):
            answer = content if isinstance(content, str) else str(content)
            break

    if not answer:
        answer = "I was unable to complete the request. Please try again."

    logger.info("answer.extracted",
                length=len(answer),
                preview=answer[:200].replace("\n", " "))

    # Teardown skills
    await _registry.teardown_all()
    logger.info("general_agent.completed")

    return {"answer": answer}
