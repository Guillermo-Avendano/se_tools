"""Skill registry — discovers, manages and aggregates skills.

Usage:
    registry = SkillRegistry()
    registry.register(ContentEdgeSkill())

    # Before each agent invocation:
    await registry.setup_all(context)
    tools = registry.get_all_tools()
    prompt = registry.build_prompt_section()
    # ... run agent ...
    await registry.teardown_all()
"""

from __future__ import annotations

import structlog
from langchain_core.tools import BaseTool

from app.skills.base import SkillBase, SkillContext

logger = structlog.get_logger(__name__)


class SkillRegistry:
    """Central registry for all agent skills."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillBase] = {}

    # ── Registration ─────────────────────────────────────────

    def register(self, skill: SkillBase) -> None:
        """Register a skill. Replaces any existing skill with the same name."""
        self._skills[skill.name] = skill
        logger.info("skill.registered", name=skill.name, version=skill.version,
                     enabled=skill.enabled)

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> SkillBase | None:
        return self._skills.get(name)

    @property
    def enabled_skills(self) -> list[SkillBase]:
        return [s for s in self._skills.values() if s.enabled]

    @property
    def all_skills(self) -> list[SkillBase]:
        return list(self._skills.values())

    # ── Lifecycle ────────────────────────────────────────────

    async def setup_all(self, context: SkillContext) -> None:
        """Call setup() on every enabled skill."""
        for skill in self.enabled_skills:
            try:
                await skill.setup(context)
            except Exception as e:
                logger.error("skill.setup_error", skill=skill.name, error=str(e))

    async def teardown_all(self) -> None:
        """Call teardown() on every enabled skill."""
        for skill in self.enabled_skills:
            try:
                await skill.teardown()
            except Exception as e:
                logger.error("skill.teardown_error", skill=skill.name, error=str(e))

    # ── Aggregation ──────────────────────────────────────────

    def get_all_tools(self) -> list[BaseTool]:
        """Collect tools from every enabled skill."""
        tools: list[BaseTool] = []
        for skill in self.enabled_skills:
            tools.extend(skill.get_tools())
        return tools

    def build_prompt_section(self) -> str:
        """Build the combined skill capabilities section for the system prompt."""
        sections: list[str] = []
        for i, skill in enumerate(self.enabled_skills, 1):
            fragment = skill.get_prompt_fragment()
            if fragment:
                sections.append(f"## Capability {i}: {skill.name}\n{fragment}")
        return "\n\n".join(sections)

    def build_routing_rules(self) -> str:
        """Build the 'How to decide' numbered list from skill routing hints."""
        rules: list[str] = []
        for i, skill in enumerate(self.enabled_skills, 1):
            hint = skill.get_routing_hint()
            if hint:
                rules.append(f"{i}. {hint}")
        return "\n".join(rules)

    def get_tool_names(self) -> list[str]:
        return [t.name for t in self.get_all_tools()]

    def __repr__(self) -> str:
        enabled = len(self.enabled_skills)
        total = len(self._skills)
        return f"<SkillRegistry {enabled}/{total} skills enabled>"
