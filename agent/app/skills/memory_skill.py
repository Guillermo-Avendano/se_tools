"""Memory skill — save and recall agent learnings from user corrections.

Learnings are persisted as markdown files under workspace/knowledge/
and indexed into Qdrant so the agent can recall them via semantic search.

File structure:
  workspace/knowledge/
  ├── corrections/   # User corrections ("no, that's wrong, do X instead")
  ├── procedures/    # Learned multi-step procedures
  └── preferences/   # User preferences and style notes

If Qdrant is lost, restart the app → file_loader re-indexes everything.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import structlog
from langchain_core.tools import tool

from app.config import settings
from app.memory.qdrant_store import (
    get_qdrant_client,
    get_embeddings,
    ensure_collection,
    upsert_texts,
    search_similar,
)
from app.skills.base import SkillBase, SkillContext, WORKSPACE_ROOT

logger = structlog.get_logger(__name__)

_WORKSPACE = WORKSPACE_ROOT
_KNOWLEDGE_DIR = _WORKSPACE / "knowledge"

# Valid categories map to subdirectories
_CATEGORIES = {
    "correction": "corrections",
    "procedure": "procedures",
    "preference": "preferences",
}


def _safe_filename(text: str) -> str:
    """Generate a filesystem-safe filename from text."""
    slug = re.sub(r"[^\w\s-]", "", text[:60]).strip().lower()
    slug = re.sub(r"[\s]+", "_", slug)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{slug}.md"


def _index_single_learning(text: str, category: str, filename: str) -> None:
    """Index a single learning into Qdrant immediately (don't wait for restart)."""
    try:
        client = get_qdrant_client()
        embeddings = get_embeddings()
        collection = settings.qdrant_collection
        ensure_collection(client, collection, embeddings)
        upsert_texts(
            client, embeddings, collection,
            texts=[text],
            metadatas=[{
                "source": filename,
                "type": "knowledge",
                "category": category,
            }],
        )
        logger.info("memory.indexed", file=filename, category=category)
    except Exception as e:
        logger.warning("memory.index_error", error=str(e))


# ── Tools ────────────────────────────────────────────────────

@tool
def save_learning(content: str, category: str = "correction", title: str = "") -> str:
    """Save a learning, correction, or procedure to the agent's persistent memory.

    Call this when the user corrects you, teaches you a procedure, or states a preference.
    The learning is saved as a file AND indexed in Qdrant for future recall.

    Args:
        content: The full text of what was learned. Be specific and include context.
                 Example: "When searching for customer loans, always use contentedge_search
                 with index CUST_NAME before calling smart_chat, not the other way around."
        category: One of "correction", "procedure", or "preference".
                  - correction: User corrected an error in agent behavior.
                  - procedure: A multi-step workflow the agent should follow.
                  - preference: User preference (language, format, style).
        title: Short descriptive title. If empty, derived from content.
    """
    logger.info("memory.save_learning", category=category, title=title[:60])

    cat_key = category.lower().strip()
    if cat_key not in _CATEGORIES:
        return f"Error: category must be one of: {', '.join(_CATEGORIES.keys())}"

    subdir = _KNOWLEDGE_DIR / _CATEGORIES[cat_key]
    subdir.mkdir(parents=True, exist_ok=True)

    label = title or content[:60]
    filename = _safe_filename(label)
    filepath = subdir / filename

    # Build markdown content
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    md = f"""# {label}

- **Category**: {cat_key}
- **Date**: {now}

## Content

{content}
"""
    filepath.write_text(md, encoding="utf-8")
    logger.info("memory.saved_file", path=str(filepath))

    # Index immediately into Qdrant so it's available in this session
    _index_single_learning(content, cat_key, filename)

    return f"Learning saved: [{cat_key}] {label} → {filename}"


@tool
def recall_learnings(query: str, category: str = "", top_k: int = 5) -> str:
    """Search the agent's memory for relevant past learnings, corrections, or procedures.

    Call this before starting a task to check if there are relevant learnings
    from previous interactions.

    Args:
        query: What to search for. Describe the task or topic.
        category: Optional filter — "correction", "procedure", or "preference".
                  Leave empty to search all categories.
        top_k: Maximum number of results to return (default 5).
    """
    logger.info("memory.recall", query=query[:100], category=category)

    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = get_qdrant_client()
        embeddings = get_embeddings()
        collection = settings.qdrant_collection

        query_vector = embeddings.embed_query(query)

        # Build filter
        conditions = [FieldCondition(key="type", match=MatchValue(value="knowledge"))]
        if category and category.lower().strip() in _CATEGORIES:
            conditions.append(
                FieldCondition(key="category", match=MatchValue(value=category.lower().strip()))
            )

        results = client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=Filter(must=conditions),
            limit=top_k,
            with_payload=True,
        )

        if not results.points:
            return "No relevant learnings found in memory."

        output = []
        for i, hit in enumerate(results.points, 1):
            score = hit.score
            if score < 0.3:
                continue
            cat = hit.payload.get("category", "unknown")
            source = hit.payload.get("source", "")
            text = hit.payload.get("text", "")
            output.append(f"**{i}. [{cat}]** (relevance: {score:.2f}) — {source}\n{text}")

        if not output:
            return "No relevant learnings found in memory (low relevance scores)."

        return "## Relevant Learnings from Memory\n\n" + "\n\n".join(output)

    except Exception as e:
        logger.error("memory.recall_error", error=str(e))
        return f"Error searching memory: {e}"


@tool
def list_learnings(category: str = "") -> str:
    """List all saved learnings in the agent's knowledge base.

    Args:
        category: Optional filter — "correction", "procedure", or "preference".
                  Leave empty to list all.
    """
    logger.info("memory.list", category=category)

    dirs_to_scan = []
    if category and category.lower().strip() in _CATEGORIES:
        dirs_to_scan.append((_KNOWLEDGE_DIR / _CATEGORIES[category.lower().strip()], category.lower().strip()))
    else:
        for cat_key, subdir_name in _CATEGORIES.items():
            dirs_to_scan.append((_KNOWLEDGE_DIR / subdir_name, cat_key))

    entries = []
    for dirpath, cat in dirs_to_scan:
        if not dirpath.exists():
            continue
        for f in sorted(dirpath.iterdir()):
            if f.suffix == ".md" and f.is_file():
                entries.append(f"- [{cat}] {f.name}")

    if not entries:
        return "No learnings saved yet."

    return f"## Knowledge Base ({len(entries)} entries)\n\n" + "\n".join(entries)


# ── Skill guide tools ────────────────────────────────────────

_PROMPTS_DIR = _WORKSPACE / "prompts"


@tool
def list_skill_guides() -> str:
    """List all available skill guides that explain what the agent can do and how to use each capability.

    Call this when the user asks "what can you do?", "how do I use you?",
    "show me your capabilities", or any equivalent.
    """
    logger.info("memory.list_guides")
    if not _PROMPTS_DIR.exists():
        return "No skill guides available."

    guides = sorted(f for f in _PROMPTS_DIR.iterdir() if f.suffix == ".md" and f.is_file())
    if not guides:
        return "No skill guides available."

    lines = ["## Available Skill Guides\n"]
    for g in guides:
        name = g.stem.replace("_", " ").title()
        # Read first non-empty line as description
        try:
            first_line = ""
            for line in g.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    first_line = stripped
                    break
            lines.append(f"- **{name}** (`{g.name}`) — {first_line}")
        except Exception:
            lines.append(f"- **{name}** (`{g.name}`)")

    lines.append("\nUse `show_skill_guide(skill_name)` to see the full guide for any skill.")
    return "\n".join(lines)


@tool
def show_skill_guide(skill_name: str) -> str:
    """Show the full usage guide for a specific skill.

    Call this when the user asks "how do I use ContentEdge?", "how does SQL work?",
    "show me the memory guide", etc.

    Args:
        skill_name: Name of the skill guide to show (e.g. "sql", "contentedge",
                    "web_search", "filesystem", "shell", "memory").
    """
    logger.info("memory.show_guide", skill=skill_name)

    clean = skill_name.lower().strip().replace(" ", "_")
    path = _PROMPTS_DIR / f"{clean}.md"

    if not path.exists():
        # Try fuzzy match
        available = [f.stem for f in _PROMPTS_DIR.iterdir() if f.suffix == ".md"]
        for name in available:
            if clean in name or name in clean:
                path = _PROMPTS_DIR / f"{name}.md"
                break

    if not path.exists():
        available = [f.stem for f in _PROMPTS_DIR.iterdir() if f.suffix == ".md"]
        return f"Guide '{skill_name}' not found. Available: {', '.join(sorted(available))}"

    try:
        content = path.read_text(encoding="utf-8")
        title = path.stem.replace("_", " ").title()
        return f"## {title} — Skill Guide\n\n{content}"
    except Exception as e:
        return f"Error reading guide: {e}"


# ── Skill class ──────────────────────────────────────────────

class MemorySkill(SkillBase):
    name = "Memory & Knowledge"
    description = "Save/recall agent learnings, and show skill usage guides."
    version = "1.1.0"
    prompt_file = "memory.md"

    def get_tools(self) -> list:
        return [save_learning, recall_learnings]

    def get_routing_hint(self) -> str:
        return (
            "If the user corrects you or teaches a procedure → use `save_learning`; "
            "before complex tasks, use `recall_learnings` to check for relevant past learnings"
        )
