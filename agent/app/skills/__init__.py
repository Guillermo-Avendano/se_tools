"""Skill-based agent architecture.

Each skill is a self-contained module that provides:
- Tools (LangChain tools for the ReAct agent)
- A prompt fragment (injected into the system prompt)
- Lifecycle hooks (setup/teardown)
"""

from app.skills.base import SkillBase, SkillContext
from app.skills.registry import SkillRegistry

__all__ = ["SkillBase", "SkillContext", "SkillRegistry"]
