"""Abstract base class for agent skills.

Every skill must subclass SkillBase and implement:
- get_tools()           → list of LangChain tools
- get_prompt_fragment()  → text injected into the system prompt
- get_routing_hint()     → short rule for the "How to decide" section

Prompt fragments are loaded from ``app/skills/prompts/<prompt_file>.md``
so that prompt engineering is decoupled from Python code.

Skills can optionally override setup() / teardown() for lifecycle management.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from app.config import settings

# Canonical workspace root — single source of truth for all skills
WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE", "/app/workspace"))

# Directory containing per-skill prompt markdown files
_PROMPTS_DIR = WORKSPACE_ROOT / "prompts"

# Shared tmp directory for transient inter-skill file exchange
WORKSPACE_TMP = WORKSPACE_ROOT / "tmp"
WORKSPACE_TMP.mkdir(parents=True, exist_ok=True)


@dataclass
class SkillContext:
    """Shared runtime context passed to skills during setup.

    Skills read what they need and ignore the rest.
    """
    db_session: Any | None = None
    config: Any | None = None
    extra: dict = field(default_factory=dict)


def _load_prompt_file(filename: str, variables: dict[str, str] | None = None) -> str:
    """Load a prompt markdown file, preferring a provider-specific variant.

    For example, if ``filename`` is ``contentedge.md`` and
    ``LLM_PROVIDER=llama_cpp``, the function first looks for
    ``contentedge_llama_cpp.md``. If that file does not exist it
    falls back to the base ``contentedge.md``.

    Args:
        filename: Name of the ``.md`` file inside ``workspace/prompts/``.
        variables: Dict of ``{placeholder: value}`` for ``str.format_map``.
    """
    provider = settings.llm_provider.lower().replace("-", "_")
    stem, ext = os.path.splitext(filename)
    provider_path = _PROMPTS_DIR / f"{stem}_{provider}{ext}"
    base_path = _PROMPTS_DIR / filename

    path = provider_path if provider_path.exists() else base_path
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if variables:
        text = text.format_map(variables)
    return text


class SkillBase(ABC):
    """Base class that all skills must inherit from."""

    # ── Metadata (override in subclass) ──────────────────────
    name: str = "unnamed_skill"
    description: str = ""
    version: str = "1.0.0"

    # Name of the prompt file in app/skills/prompts/ (e.g. "sql.md")
    prompt_file: str = ""

    # If True, the skill is enabled by default
    enabled: bool = True

    async def setup(self, context: SkillContext) -> None:
        """Called before each agent invocation. Bind runtime resources."""

    async def teardown(self) -> None:
        """Called after each agent invocation. Release resources."""

    @abstractmethod
    def get_tools(self) -> list[BaseTool]:
        """Return the LangChain tools this skill provides."""

    def get_prompt_fragment(self) -> str:
        """Return markdown text describing this skill's capabilities.

        Default implementation loads from ``app/skills/prompts/{prompt_file}``.
        Override to provide dynamic variables via ``_load_prompt_file()``.
        """
        if self.prompt_file:
            return _load_prompt_file(self.prompt_file)
        return ""

    @abstractmethod
    def get_routing_hint(self) -> str:
        """Return a one-line rule for the 'How to decide' section.

        Example: "If the question is about data in database tables → use `execute_sql`"
        """

    def __repr__(self) -> str:
        return f"<Skill {self.name} v{self.version} enabled={self.enabled}>"
