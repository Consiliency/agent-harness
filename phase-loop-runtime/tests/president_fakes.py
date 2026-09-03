"""Test-side president seams for ``invoke_board(..., president_invoke=...)`` (ah#736).

A president-requiring tier now refuses to run without a seam; these fakes give
existing board tests a deterministic ruling so they keep exercising the seat
transport they were written for, and give the wiring tests a scriptable
ladder.
"""
from __future__ import annotations

import re
from typing import Callable, Mapping

_FINDING_ID_RE = re.compile(r"^(F\d{3}):", re.MULTILINE)


def finding_ids_in_prompt(prompt: str) -> list[str]:
    return _FINDING_ID_RE.findall(prompt)


def ruling_text(prompt: str, *, disposition: str = "DEFERRED", decision: str = "LAND") -> str:
    lines = [
        f"FINDING {finding_id}: {disposition} — ruled by test president"
        for finding_id in finding_ids_in_prompt(prompt)
    ]
    lines.append(f"FORCING DECISION: {decision}")
    return "\n".join(lines)


def deferring_president(model: str, prompt: str) -> Mapping[str, str]:
    """Every rung answers; every finding is DEFERRED; decision LAND."""
    return {"status": "ok", "text": ruling_text(prompt)}


def blocking_president(model: str, prompt: str) -> Mapping[str, str]:
    return {"status": "ok", "text": ruling_text(prompt, disposition="BLOCKING", decision="REJECT")}


class ScriptedPresident:
    """Replay a per-call script of responses; records every (rung, prompt)."""

    def __init__(self, script: list[Mapping[str, str] | Callable[[str, str], Mapping[str, str]]]) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model: str, prompt: str) -> Mapping[str, str]:
        self.calls.append((model, prompt))
        if not self.script:
            raise AssertionError("president invoked more times than scripted")
        step = self.script.pop(0)
        return step(model, prompt) if callable(step) else step
