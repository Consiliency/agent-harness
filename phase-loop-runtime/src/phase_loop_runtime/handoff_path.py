"""Resolve a skill's latest handoff under a repository's .dev-skills/handoffs.
"""

from __future__ import annotations

from pathlib import Path


def resolve_handoff_path(repo: str | Path, skill_name: str) -> Path:
    return Path(repo).expanduser().resolve() / ".dev-skills" / "handoffs" / skill_name / "latest.md"
