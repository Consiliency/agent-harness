"""Registry of the normative rules in shipped skills and what enforces each one.

The harness acts on client repos, so the rules that matter are the ones in the
``SKILL.md`` text we ship, not this repository's ``AGENTS.md``. Each registry row
pins one rule by quoting it, then names either the code that refuses a violation
(``enforced``) or says plainly that nothing does (``unenforced``). An unenforced
row is a ``gap`` (a mechanism could exist; ``tracking`` names the issue) or a
``judgment`` call, where prose is the correct and final level.

``check_registry`` refuses a row whose quoted text no longer appears in every
shipped harness copy of its skill, whose enforcer symbol no longer exists, or
whose negative-control test is gone. That keeps the table from silently claiming
enforcement that rotted away. It does not prove the enforcer covers the whole
rule; the negative-control test is the evidence for that, and it runs in CI.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "rule_enforcement.v1"
HARNESSES = ("claude", "codex", "gemini", "opencode")
STATUSES = ("enforced", "unenforced")
UNENFORCED_REASONS = ("gap", "judgment")
ENFORCER_KINDS = ("module", "skill_script")

_REGISTRY_PATH = Path(__file__).with_name("rule_enforcement.json")
_BUNDLE_ROOT = Path(__file__).with_name("skills_bundle")
_TRACKING_RE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?#\d+$")
_ID_RE = re.compile(r"^[a-z0-9-]+\.[a-z0-9-]+$")


@dataclass(frozen=True)
class Enforcer:
    kind: str
    symbol: str
    module: str = ""
    path: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    skill: str
    quote: str
    status: str
    harness_quotes: dict[str, str] = field(default_factory=dict)
    enforcers: tuple[Enforcer, ...] = ()
    negative_control: str = ""
    unenforced_reason: str = ""
    tracking: str = ""

    def quote_for(self, harness: str) -> str:
        return self.harness_quotes.get(harness, self.quote)


def load_registry(path: Path | None = None) -> list[Rule]:
    data = json.loads((path or _REGISTRY_PATH).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"rule registry schema must be {SCHEMA!r}, got {data.get('schema')!r}")
    return [_rule(row) for row in data.get("rules", [])]


def _rule(row: dict[str, Any]) -> Rule:
    return Rule(
        id=str(row.get("id", "")),
        skill=str(row.get("skill", "")),
        quote=str(row.get("quote", "")),
        status=str(row.get("status", "")),
        harness_quotes=dict(row.get("harness_quotes") or {}),
        enforcers=tuple(
            Enforcer(
                kind=str(item.get("kind", "")),
                symbol=str(item.get("symbol", "")),
                module=str(item.get("module", "")),
                path=str(item.get("path", "")),
            )
            for item in row.get("enforcers") or ()
        ),
        negative_control=str(row.get("negative_control", "")),
        unenforced_reason=str(row.get("unenforced_reason", "")),
        tracking=str(row.get("tracking", "")),
    )


def check_registry(
    rules: list[Rule],
    *,
    bundle_root: Path | None = None,
    tests_root: Path | None = None,
) -> list[str]:
    """Return one problem string per broken row; an empty list means sound.

    ``tests_root`` is the runtime's ``tests/`` parent. Tests do not ship in the
    package, so negative controls are only resolved when it is given.
    """

    bundle_root = bundle_root or _BUNDLE_ROOT
    problems: list[str] = []
    seen: set[str] = set()
    for rule in rules:
        where = rule.id or "<missing id>"
        if not _ID_RE.match(rule.id):
            problems.append(f"{where}: id must look like '<skill>.<slug>'")
        if rule.id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(rule.id)
        problems.extend(f"{where}: {p}" for p in _check_status(rule))
        copies = _skill_copies(bundle_root, rule.skill)
        if not copies:
            problems.append(f"{where}: no shipped copy of skill {rule.skill!r}")
        for harness in sorted(set(rule.harness_quotes) - set(copies)):
            problems.append(f"{where}: harness_quotes names {harness!r}, which ships no {rule.skill!r}")
        for harness, skill_dir in copies.items():
            quote = rule.quote_for(harness)
            if not quote.strip():
                problems.append(f"{where}: empty quote for {harness}")
            elif _normalize(quote) not in _normalize((skill_dir / "SKILL.md").read_text(encoding="utf-8")):
                problems.append(f"{where}: quote not found in {skill_dir.name}/SKILL.md: {quote!r}")
        for enforcer in rule.enforcers:
            problems.extend(f"{where}: {p}" for p in _check_enforcer(enforcer, copies))
        if tests_root is not None and rule.negative_control:
            problem = _check_node_id(tests_root, rule.negative_control)
            if problem:
                problems.append(f"{where}: {problem}")
    return problems


def _check_status(rule: Rule) -> list[str]:
    if rule.status not in STATUSES:
        return [f"status must be one of {STATUSES}, got {rule.status!r}"]
    if rule.status == "enforced":
        problems = []
        if not rule.enforcers:
            problems.append("enforced rule names no enforcer")
        if not rule.negative_control:
            problems.append("enforced rule names no negative_control test showing the enforcer refuse")
        if rule.unenforced_reason or rule.tracking:
            problems.append("enforced rule carries unenforced_reason/tracking")
        return problems
    problems = []
    if rule.enforcers or rule.negative_control:
        problems.append("unenforced rule names an enforcer or negative_control")
    if rule.unenforced_reason not in UNENFORCED_REASONS:
        problems.append(f"unenforced_reason must be one of {UNENFORCED_REASONS}, got {rule.unenforced_reason!r}")
    if rule.unenforced_reason == "gap" and not _TRACKING_RE.match(rule.tracking):
        problems.append(f"gap needs a repo-qualified tracking ref like 'agent-harness#123', got {rule.tracking!r}")
    return problems


def _skill_copies(bundle_root: Path, skill: str) -> dict[str, Path]:
    return {
        harness: bundle_root / f"{harness}-{skill}"
        for harness in HARNESSES
        if (bundle_root / f"{harness}-{skill}" / "SKILL.md").is_file()
    }


def _check_enforcer(enforcer: Enforcer, copies: dict[str, Path]) -> list[str]:
    if enforcer.kind not in ENFORCER_KINDS:
        return [f"enforcer kind must be one of {ENFORCER_KINDS}, got {enforcer.kind!r}"]
    if enforcer.kind == "module":
        spec = importlib.util.find_spec(enforcer.module) if enforcer.module else None
        if spec is None or not spec.origin or not Path(spec.origin).is_file():
            return [f"enforcer module {enforcer.module!r} not found"]
        if enforcer.symbol not in _top_level_names(Path(spec.origin)):
            return [f"enforcer {enforcer.module}:{enforcer.symbol} not defined"]
        return []
    problems = []
    for skill_dir in copies.values():
        script = skill_dir / enforcer.path
        if not enforcer.path or not script.is_file():
            problems.append(f"enforcer script {skill_dir.name}/{enforcer.path} missing")
        elif enforcer.symbol not in _top_level_names(script):
            problems.append(f"enforcer {skill_dir.name}/{enforcer.path}:{enforcer.symbol} not defined")
    return problems


def _check_node_id(tests_root: Path, node_id: str) -> str:
    rel, _, rest = node_id.partition("::")
    path = tests_root / rel
    if not rest or not path.is_file():
        return f"negative_control {node_id!r} does not name a test in an existing file"
    parts = rest.split("::")
    body: list[ast.stmt] = ast.parse(path.read_text(encoding="utf-8")).body
    for part in parts:
        match = next(
            (n for n in body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part),
            None,
        )
        if match is None:
            return f"negative_control {node_id!r} not found"
        body = match.body if isinstance(match, ast.ClassDef) else []
    return ""


def _top_level_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _normalize(text: str) -> str:
    return " ".join(text.split())
