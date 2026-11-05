"""The jailed Claude seat's transport seam (IF-0-CLAUDE-1, SEATS CLAUDE, agent-harness#1820).

The jailed Claude seat reads ``PHASE_LOOP_PANEL_CLAUDE_ROUTE`` and launches one transport,
``tui``, ``print`` or ``sdk``, inside the same jail, staged clone, tool set and teardown
(``panel_invoker._JailedSeat``). This module decides which one, and only that:

* :func:`resolve_jailed_claude_transport` -- the selector. Unset or blank is the shipped
  default (:data:`JAILED_CLAUDE_DEFAULT`); an unknown value refuses
  ``panel_claude_route_invalid``; a known value whose module is not admitted refuses
  ``panel_claude_transport_not_admitted``. A refusal launches nothing and never falls back.
* admission -- ``tui`` is always admitted. ``print`` and ``sdk`` are admitted only when their
  module (``claude_seat_print``, ``claude_seat_sdk``) imports and exports ``ADMITTED = True``,
  ``ACTIVATION`` (a :class:`RecordCitation`) and ``run_jailed(seat, **kwargs)``.
* :data:`CODES` -- the typed codes these transports add, each with its OD-10 class and a
  fix line. The mode line accepts ``seat_jail.NOTICE_CODES | CODES``.
* :func:`launch_jailed` -- the dispatch: the login proof (IF-0-CLAUDE-4) on every
  transport, then exactly one transport. No refusal or terminal code launches another;
  "TUI last" is operator selection only.
* :func:`audit_order` and ``python -m phase_loop_runtime.claude_seat_transport audit-order``
  -- the ratification-order audit (EC-CLAUDE-4), by content on the landing's base tree.

The module imports only the standard library at load time, so the audit runs from a bare
checkout. ``panel_invoker`` helpers are late-bound through the package facade
(PANELSPLIT-compatible), and nothing here changes them.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable, Literal, Mapping, Sequence

ClaudeTransport = Literal["tui", "print", "sdk"]

TRANSPORTS: tuple[str, ...] = ("tui", "print", "sdk")
ROUTE_ENV = "PHASE_LOOP_PANEL_CLAUDE_ROUTE"
ROUTE_INVALID = "panel_claude_route_invalid"
NOT_ADMITTED = "panel_claude_transport_not_admitted"
REFUSAL_CODES: frozenset[str] = frozenset({ROUTE_INVALID, NOT_ADMITTED})

#: The decision record every admission and default cites.
DECISION_RECORD = "plans/decision-claude-print-subscription-route-20261008.md"


@dataclass(frozen=True)
class RecordCitation:
    """Where a transport's admission, or the shipped default, is ratified: the decision
    record's path, the section id (``4a``, ``4b``, ...), the sha256 of that section's bytes
    (its ``## `` heading line through the line before the next ``## `` heading) and the
    merged PR that landed it (``agent-harness#N``)."""

    record: str
    section: str
    section_sha256: str
    pr: str


#: The section each purpose must cite. ``print`` cites §4a; ``sdk`` cites the OD-3a
#: amendment, ``## 4b. OD-3a``; the default cites an OD-3b section, ``## 4c. OD-3b`` and
#: later switches the next free letter, every one carrying ``OD-3b`` in its heading.
SECTION_FOR: Mapping[str, str] = {"print": "4a", "sdk": "4b", "default": "4c"}
_SECTION_HEADING_RULE: Mapping[str, re.Pattern[str]] = {
    "print": re.compile(r"## 4a\. "),
    "sdk": re.compile(r"## 4b\. OD-3a\b"),
    "default": re.compile(r"## 4[c-z]\. .*\bOD-3b\b"),
}

#: The shipped default for the jailed seat (§4a item 2). It changes only in a switch PR that
#: edits this value and :data:`JAILED_DEFAULT_AUTHORITY` and nothing in the decision record
#: (EC-CLAUDE-4); ``tui`` may also cite an OD-3b section.
JAILED_CLAUDE_DEFAULT: ClaudeTransport = "tui"
JAILED_DEFAULT_AUTHORITY: RecordCitation | None = None

# --------------------------------------------------------------------------------------
# The typed codes (OD-10 class, what, why, fix). None is on the closed descend list, and no
# fix line names a key-based credential. JAILCORE takes this table as input.
# --------------------------------------------------------------------------------------

SECURITY = "security"
ORDINARY = "ordinary"
OD10_CLASSES = (SECURITY, ORDINARY)

CODES: Mapping[str, tuple[str, str, str, str]] = {
    "claude_seat_token_in_output": (
        SECURITY, "leg rejected", "seat tried to publish its credential", "revoke the token"),
    "claude_seat_api_key_source": (
        SECURITY, "leg rejected",
        "the seat's CLI reported a credential source other than its subscription login",
        "run `claude auth login` in the launching session, then re-run; report the "
        "outcome privately"),
    "claude_sdk_closure_refused": (
        SECURITY, "leg refused",
        "the sdk transport's projected closure did not verify against its declared authority",
        "rebuild the closure with `python -m phase_loop_runtime.claude_seat_sdk "
        "build-closure`, supply its authority digest, then re-run; report the outcome "
        "privately"),
    "claude_seat_login_unproven": (
        ORDINARY, "leg refused",
        "the seat's login is not a proven subscription login on the credential it would use",
        "run `claude auth login` in the launching session, then re-run"),
    "claude_seat_result_unproven": (
        ORDINARY, "leg ended",
        "the seat's stream did not end in exactly one admitted result",
        "re-run the seat; to compare, select `tui` explicitly"),
    "claude_seat_stream_unsafe": (
        ORDINARY, "leg rejected",
        "the seat's output stream broke a parser bound and was not read further",
        "re-run the seat; to compare, select `tui` explicitly"),
    "claude_sdk_dependency_unavailable": (
        ORDINARY, "leg refused",
        "the sdk transport needs an admitted dependency session that carries its closure",
        "start the board in a dependency session that declares the sdk closure, or select "
        "`print` or `tui`"),
}


#: The selector's own refusals, for a republished seat-mode row (what, why, fix). They are
#: leg details, not mode-line codes.
REFUSAL_TEXT: Mapping[str, tuple[str, str, str]] = {
    ROUTE_INVALID: (
        "leg refused", "PHASE_LOOP_PANEL_CLAUDE_ROUTE names no Claude transport",
        "set PHASE_LOOP_PANEL_CLAUDE_ROUTE to tui, print or sdk, or unset it"),
    NOT_ADMITTED: (
        "leg refused", "the selected jailed Claude transport is not admitted on this runtime",
        "unset PHASE_LOOP_PANEL_CLAUDE_ROUTE, or select an admitted transport"),
}


def notice_text(code: str) -> tuple[str, str, str]:
    """``(what, why, fix)`` for a :data:`CODES` entry or a selector refusal."""
    if code in CODES:
        return CODES[code][1:]
    return REFUSAL_TEXT[code]


def od10_class(code: str) -> str | None:
    entry = CODES.get(code)
    return entry[0] if entry is not None else None


def mode_line_codes() -> frozenset[str]:
    """Every code the mode line accepts: ``seat_jail.NOTICE_CODES | CODES``."""
    from . import seat_jail

    return frozenset(seat_jail.NOTICE_CODES) | frozenset(CODES)


def render_notice(code: object, seat_key: object):
    """A ``seat_jail.Notice`` for a :data:`CODES` entry, rendered from literals only, with
    its OD-10 class in ``what``; ``seat_jail.render_notice`` for every other code."""
    from . import seat_jail

    if type(code) is not str or code not in CODES:
        return seat_jail.render_notice(code, seat_key)
    klass, what, why, fix = CODES[code]
    key = seat_key if type(seat_key) is str else ""
    return seat_jail.Notice(code=code, seat_key=key, what=f"{what} (OD-10 {klass})", why=why,
                            fix=fix)


class TransportRefused(RuntimeError):
    """A jailed transport refused before or after its launch. ``code`` is one of
    :data:`CODES` or :data:`REFUSAL_CODES`; ``also`` are sibling notice codes."""

    def __init__(self, code: str, message: str = "", also: tuple[str, ...] = ()) -> None:
        if code not in CODES and code not in REFUSAL_CODES:
            raise ValueError(f"unknown jailed transport code {code!r}")
        super().__init__(message or code)
        self.code = code
        self.also = tuple(also)


# --------------------------------------------------------------------------------------
# Admission and resolution.
# --------------------------------------------------------------------------------------

_TRANSPORT_MODULES: Mapping[str, str] = {"print": "claude_seat_print", "sdk": "claude_seat_sdk"}


def transport_module(transport: str) -> ModuleType | None:
    """The admitted module for ``print`` or ``sdk``, or ``None``. A module that does not
    import, or exports anything short of ``ADMITTED is True``, a :class:`RecordCitation`
    ``ACTIVATION`` and a callable ``run_jailed``, is not admitted."""
    name = _TRANSPORT_MODULES.get(transport)
    if name is None:
        return None
    try:
        module = importlib.import_module(f"{__package__}.{name}")
    except ImportError:
        return None
    if getattr(module, "ADMITTED", False) is not True:
        return None
    if not isinstance(getattr(module, "ACTIVATION", None), RecordCitation):
        return None
    if not callable(getattr(module, "run_jailed", None)):
        return None
    return module


def is_admitted(transport: str) -> bool:
    if transport == "tui":
        return True
    return transport_module(transport) is not None


def resolve_jailed_claude_transport(
    env: Mapping[str, str] | None = None,
) -> tuple[ClaudeTransport | None, str | None]:
    """``(transport, None)`` for an admitted selection, else ``(None, refusal)``."""
    env = os.environ if env is None else env
    raw = env.get(ROUTE_ENV)
    value = JAILED_CLAUDE_DEFAULT if raw is None or not raw.strip() else raw.strip().lower()
    if value not in TRANSPORTS:
        return None, ROUTE_INVALID
    if not is_admitted(value):
        return None, NOT_ADMITTED
    return value, None  # type: ignore[return-value]


def _panel_invoker() -> ModuleType:
    return importlib.import_module(f"{__package__}.panel_invoker")


def launch_jailed(
    transport: str,
    seat: object,
    *,
    prove_login: Callable[[], object],
    **kwargs: object,
) -> tuple[str, str]:
    """Launch the ONE selected transport on a prepared seat.

    ``prove_login`` is the jailed login proof (IF-0-CLAUDE-4); it runs first on every
    transport and raises on failure. A refusal here, from the proof or from admission, tears
    the prepared seat down and launches nothing; whatever the selected transport returns or
    raises is the outcome, and no other transport is tried."""
    pi = _panel_invoker()
    module = None
    try:
        if transport not in TRANSPORTS:
            raise TransportRefused(ROUTE_INVALID)
        if transport != "tui":
            module = transport_module(transport)
            if module is None:
                raise TransportRefused(NOT_ADMITTED)
        proof = prove_login()
    except BaseException as exc:
        pi._cleanup_jailed_seat(seat, primary=exc)
        raise
    evidence = kwargs.get("broker_evidence")
    if isinstance(evidence, dict):
        evidence["claude_transport"] = transport
        as_evidence = getattr(proof, "as_evidence", None)
        if callable(as_evidence):
            evidence.update(as_evidence())
    if module is None:
        return pi._exec_jailed_claude_leg(seat, **kwargs)
    return module.run_jailed(seat, **kwargs)


# --------------------------------------------------------------------------------------
# EC-CLAUDE-4: the ratification-order audit, by content on the landing's base tree.
# --------------------------------------------------------------------------------------

RUNTIME_DIR = "phase-loop-runtime/src/phase_loop_runtime"
TRANSPORT_SOURCE = f"{RUNTIME_DIR}/claude_seat_transport.py"
MODULE_SOURCES: Mapping[str, str] = {
    transport: f"{RUNTIME_DIR}/{name}.py" for transport, name in _TRANSPORT_MODULES.items()
}
CARD = "docs/advisor-board-capabilities-card.md"
DEFAULT_LINE = re.compile(
    r"^\*\*Jailed Claude default:\*\* (?:`(?P<value>tui|print|sdk)`|(?P<none>none admitted))\s*$")
CARD_MARKER = "**Jailed Claude default:**"
_PR_RE = re.compile(r"^(?:Consiliency/)?agent-harness#(?P<n>[1-9][0-9]*)$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AuditError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> bytes | None:
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _commit(repo: Path, rev: str | None) -> str | None:
    if not rev or rev.startswith("-"):
        return None
    out = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return out.decode().strip() if out else None


def _blob(repo: Path, commit: str, path: str) -> bytes | None:
    return _git(repo, "show", f"{commit}:{path}")


def record_sections(raw: bytes) -> dict[str, tuple[str, str]]:
    """``{section id: (heading line, sha256 of the section's bytes)}``. A section runs from
    its ``## `` heading line through the line before the next ``## `` heading."""
    lines = raw.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith(b"## ")]
    sections: dict[str, tuple[str, str]] = {}
    for at, start in enumerate(starts):
        end = starts[at + 1] if at + 1 < len(starts) else len(lines)
        heading = lines[start].decode("utf-8", errors="replace").rstrip("\r\n")
        match = re.match(r"## (\d+[a-z]?)\. ", heading)
        if match is None:
            continue
        body = b"".join(lines[start:end])
        sections.setdefault(match.group(1), (heading, hashlib.sha256(body).hexdigest()))
    return sections


def section_bytes(raw: bytes, section: str) -> bytes | None:
    lines = raw.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith(b"## ")]
    for at, start in enumerate(starts):
        if lines[start].startswith(f"## {section}. ".encode()):
            end = starts[at + 1] if at + 1 < len(starts) else len(lines)
            return b"".join(lines[start:end])
    return None


def _literal_citation(node: ast.expr) -> RecordCitation | None:
    """A ``RecordCitation(...)`` call whose four arguments are string literals."""
    if not isinstance(node, ast.Call):
        raise AuditError("a citation is not a RecordCitation call")
    name = node.func.id if isinstance(node.func, ast.Name) else (
        node.func.attr if isinstance(node.func, ast.Attribute) else "")
    if name != "RecordCitation":
        raise AuditError("a citation is not a RecordCitation call")
    fields = ("record", "section", "section_sha256", "pr")
    values: dict[str, str] = {}
    if len(node.args) > len(fields):
        raise AuditError("a citation has extra arguments")
    for field_name, arg in zip(fields, node.args):
        values[field_name] = arg
    for keyword in node.keywords:
        if keyword.arg not in fields or keyword.arg in values:
            raise AuditError("a citation has an unknown or repeated argument")
        values[keyword.arg] = keyword.value
    if set(values) != set(fields):
        raise AuditError("a citation is missing an argument")
    out: dict[str, str] = {}
    for field_name, value in values.items():
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            raise AuditError("a citation argument is not a string literal")
        out[field_name] = value.value
    return RecordCitation(**out)


#: Every name the admission and the default are read from, in any audited module.
AUDITED_NAMES: tuple[str, ...] = (
    "ADMITTED", "ACTIVATION", "JAILED_CLAUDE_DEFAULT", "JAILED_DEFAULT_AUTHORITY")
#: Constructs that can set a module attribute without a visible assignment. An audited
#: module that uses one fails, whatever it does with it.
_DYNAMIC_NAMES = frozenset({"globals", "locals", "vars", "setattr", "delattr", "exec", "eval",
                            "__import__", "compile"})
_DYNAMIC_ATTRIBUTES = frozenset({"__dict__", "__setattr__", "__delattr__", "modules",
                                 "meta_path", "path_hooks", "__getattr__"})


def _bound_names(node: ast.AST) -> list[str]:
    """The names ``node`` binds in its scope, whatever the binding form."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return [node.id]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.alias):
        return [node.asname or node.name.split(".")[0]]
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.ExceptHandler) and node.name:
        return [node.name]
    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
        return [node.name]
    if isinstance(node, ast.MatchMapping) and node.rest:
        return [node.rest]
    return []


def _module_facts(source: bytes | None, names: Sequence[str]) -> dict[str, object]:
    """The literal values of ``names`` in one audited module, read with ``ast`` (never
    executed).

    Fails closed on anything but the one shape the audit can read: each name is bound at
    most once in the whole module, by a module-level ``NAME = literal`` (or annotated)
    assignment with that name as its only target. A nested, tuple, augmented, imported,
    deleted or otherwise bound name fails, as does a module-level ``__getattr__``, a star
    import, or any construct that sets attributes without a visible assignment."""
    if source is None:
        return {}
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise AuditError("a transport module does not parse") from exc
    readable: dict[int, tuple[str, ast.expr]] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in names:
            readable[id(target)] = (target.id, value)
    bound: dict[str, int] = {}
    facts: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            raise AuditError("an audited module uses a star import")
        if isinstance(node, ast.Name) and node.id in _DYNAMIC_NAMES:
            raise AuditError(f"an audited module uses {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in _DYNAMIC_ATTRIBUTES:
            raise AuditError(f"an audited module uses .{node.attr}")
        for name in _bound_names(node):
            if name == "__getattr__" and (any(node is s for s in tree.body)
                                          or isinstance(node, (ast.Name, ast.alias))):
                raise AuditError("an audited module defines a module-level __getattr__")
            if name not in names:
                continue
            bound[name] = bound.get(name, 0) + 1
            if bound[name] > 1:
                raise AuditError(f"{name} is bound more than once")
            if id(node) not in readable:
                raise AuditError(f"{name} is bound other than by one module-level literal "
                                 "assignment")
            value = readable[id(node)][1]
            if isinstance(value, ast.Constant) and (value.value is None
                                                    or isinstance(value.value, (bool, str))):
                facts[name] = value.value
            else:
                facts[name] = _literal_citation(value)
    return facts


def _tree_entries(repo: Path, commit: str, path: str, *, recursive: bool) -> list[tuple[str, str, str]]:
    """``(mode, object, path)`` for each entry under ``path`` at ``commit``."""
    out = _git(repo, "ls-tree", "-z", *(("-r",) if recursive else ()), commit, "--", path)
    if out is None:
        raise AuditError("the tree cannot be listed")
    entries = []
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _tab, name = record.partition(b"\t")
        mode, _kind, obj = meta.decode().split(" ")
        entries.append((mode, obj, name.decode("utf-8", "surrogateescape")))
    return entries


def module_form_failures(repo: Path, commit: str) -> list[str]:
    """Each audited module is one regular ``<name>.py`` file or absent: no package, symlink,
    compiled or other importable form of the same module name."""
    problems = []
    entries = _tree_entries(repo, commit, f"{RUNTIME_DIR}/", recursive=False)
    for name in (Path(TRANSPORT_SOURCE).stem, *_TRANSPORT_MODULES.values()):
        for mode, _obj, path in entries:
            base = path.rsplit("/", 1)[-1]
            if base != name and not base.startswith(name + "."):
                continue
            if base != f"{name}.py" or mode != "100644":
                problems.append(f"{name}: an importable form other than one regular "
                                f"{name}.py file ({base}, mode {mode})")
    return problems


def _blobs(repo: Path, objects: Sequence[str]) -> list[bytes]:
    try:
        done = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"],
                              input=b"".join(o.encode() + b"\n" for o in objects),
                              capture_output=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuditError("the runtime sources cannot be read") from exc
    if done.returncode != 0:
        raise AuditError("the runtime sources cannot be read")
    data, blobs, at = done.stdout, [], 0
    try:
        for _obj in objects:
            end = data.index(b"\n", at)
            size = int(data[at:end].split(b" ")[2])
            blobs.append(data[end + 1:end + 1 + size])
            at = end + 1 + size + 1
    except (ValueError, IndexError) as exc:
        raise AuditError("the runtime sources cannot be read") from exc
    return blobs


def cross_module_failures(repo: Path, commit: str) -> list[str]:
    """No runtime module sets an audited name on another module: no attribute assignment
    or deletion of one, and no ``setattr``/``delattr`` naming one."""
    sources = [(path, obj) for mode, obj, path in
               _tree_entries(repo, commit, f"{RUNTIME_DIR}/", recursive=True)
               if path.endswith(".py") and mode.startswith("100")]
    problems = []
    for (path, _obj), source in zip(sources, _blobs(repo, [obj for _p, obj in sources])):
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            problems.append(f"{path}: a runtime module does not parse")
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr in AUDITED_NAMES
                    and isinstance(node.ctx, (ast.Store, ast.Del))):
                problems.append(f"{path}: sets {node.attr} on another object")
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("setattr", "delattr") and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in AUDITED_NAMES):
                problems.append(f"{path}: sets {node.args[1].value} through {node.func.id}")
    return problems


@dataclass(frozen=True)
class _TreeFacts:
    admissions: Mapping[str, RecordCitation | None]  # admitted transport -> its citation
    default: object
    authority: object


def _tree_facts(repo: Path, commit: str) -> _TreeFacts:
    admissions: dict[str, RecordCitation | None] = {}
    for transport, path in MODULE_SOURCES.items():
        facts = _module_facts(_blob(repo, commit, path), ("ADMITTED", "ACTIVATION"))
        if facts.get("ADMITTED") is True:
            activation = facts.get("ACTIVATION")
            admissions[transport] = activation if isinstance(activation, RecordCitation) else None
        elif "ADMITTED" in facts and facts["ADMITTED"] is not False:
            raise AuditError(f"{transport}: ADMITTED is not a boolean literal")
    transport_source = _blob(repo, commit, TRANSPORT_SOURCE)
    facts = _module_facts(transport_source, ("JAILED_CLAUDE_DEFAULT", "JAILED_DEFAULT_AUTHORITY"))
    if transport_source is None:
        # Before the seam existed, the jailed seat ran the TUI (§4a item 2).
        return _TreeFacts(admissions, "tui", None)
    if "JAILED_CLAUDE_DEFAULT" not in facts:
        raise AuditError("the shipped default is not a module-level literal")
    return _TreeFacts(admissions, facts.get("JAILED_CLAUDE_DEFAULT"),
                      facts.get("JAILED_DEFAULT_AUTHORITY"))


def _od3b_value(raw: bytes, section: str) -> str | None:
    body = section_bytes(raw, section)
    if body is None:
        return None
    found = [DEFAULT_LINE.match(line) for line in body.decode("utf-8", "replace").splitlines()]
    found = [m for m in found if m is not None]
    if len(found) != 1:
        return None
    return "tui" if found[0].group("none") else found[0].group("value")


def default_rule_failures(default: object, authority: object, record: bytes | None,
                          admitted: Sequence[str]) -> list[str]:
    """The default is ``tui`` (which may cite an OD-3b section), or the latest OD-3b value
    with an authority citing that section. A recorded but unshipped OD-3b value is legal."""
    if default not in TRANSPORTS:
        return [f"the shipped default {default!r} is not a transport"]
    sections = record_sections(record) if record is not None else {}
    od3b = sorted(sid for sid, (heading, _d) in sections.items()
                  if _SECTION_HEADING_RULE["default"].match(heading))
    if default == "tui":
        if authority is None:
            return []
        if not isinstance(authority, RecordCitation) or authority.section not in od3b:
            return ["a `tui` default may cite only an OD-3b section"]
        return []
    if not isinstance(authority, RecordCitation):
        return [f"the shipped default `{default}` has no authority"]
    if not od3b or authority.section != od3b[-1]:
        return [f"the shipped default `{default}` does not cite the latest OD-3b section"]
    value = _od3b_value(record or b"", authority.section)
    if value != default:
        return [f"the shipped default `{default}` is not the latest OD-3b value ({value})"]
    if default not in admitted:
        return [f"the shipped default `{default}` is not an admitted transport"]
    return []


def card_failures(default: object, card: bytes | None) -> list[str]:
    """EC-CLAUDE-6: a chosen (non-``tui``) default is stated on the capabilities card with
    the default, open egress and its row window."""
    if default == "tui":
        return []
    lines = [line for line in (card or b"").decode("utf-8", "replace").splitlines()
             if CARD_MARKER in line]
    if not lines:
        return ["the capabilities card has no jailed Claude default statement"]
    problems = []
    for line in lines:
        lower = line.lower()
        if f"`{default}`" not in line:
            problems.append("the card's default statement omits the default")
        if "open egress" not in lower:
            problems.append("the card's default statement omits open egress")
        if "row window" not in lower:
            problems.append("the card's default statement omits the row window")
    return problems


def _citation_failures(purpose: str, citation: object, record: bytes | None, pr: int | None,
                       pr_merged: Callable[[int], bool]) -> list[str]:
    if not isinstance(citation, RecordCitation):
        return [f"{purpose}: the citation is not a literal RecordCitation"]
    problems: list[str] = []
    if citation.record != DECISION_RECORD:
        problems.append(f"{purpose}: the citation names another record")
    if citation.section != SECTION_FOR.get(purpose) and not (
            purpose == "default" and re.fullmatch(r"4[c-z]", citation.section)):
        problems.append(f"{purpose}: the cited section is not this purpose's own")
    sections = record_sections(record) if record is not None else {}
    found = sections.get(citation.section)
    if found is None:
        problems.append(f"{purpose}: the cited section is absent from the base tree")
    else:
        heading, digest = found
        if not _SECTION_HEADING_RULE[purpose].match(heading):
            problems.append(f"{purpose}: the cited section is not this purpose's own")
        if not _HEX64.match(citation.section_sha256) or digest != citation.section_sha256:
            problems.append(f"{purpose}: the cited section's digest differs on the base tree")
    match = _PR_RE.match(citation.pr)
    if match is None:
        problems.append(f"{purpose}: the cited PR is not an agent-harness PR")
    else:
        number = int(match.group("n"))
        if pr is not None and number == pr:
            problems.append(f"{purpose}: the citation names the PR under check")
        else:
            try:
                merged = bool(pr_merged(number))
            except Exception:  # an unverifiable merge state is a failure, never a pass
                merged = False
            if not merged:
                problems.append(f"{purpose}: the cited PR is not merged")
    return problems


def append_only_failures(base_record: bytes | None, head_record: bytes | None) -> list[str]:
    """Sections are append-only, for every section and the preamble, cited yet or not: the
    base record's bytes are a prefix of the head's, and anything added starts a new
    ``## `` section, so no section on the base changes its bytes or digest."""
    if base_record is None or head_record == base_record:
        return []
    if head_record is None:
        return ["a landing removes the decision record"]
    added = head_record[len(base_record):]
    if (not head_record.startswith(base_record) or not base_record.endswith(b"\n")
            or not added.startswith(b"## ")):
        return ["a landing edits the decision record's existing bytes (sections are "
                "append-only)"]
    return []


def audit_order(
    base: str | None, head: str | None, pr: int | None, *,
    repo: Path | str = ".",
    event_base: str | None = None,
    pr_merged: Callable[[int], bool] | None = None,
) -> tuple[str, ...]:
    """Every failure of the ratification order for a landing of ``head`` onto ``base``
    (empty when it holds). ``event_base`` is the event's ``pull_request.base.sha``: when
    given, ``base`` must be that commit. ``pr`` is the PR under check."""
    repo = Path(repo)
    pr_merged = pr_merged or github_pr_merged
    base_commit = _commit(repo, base)
    if base_commit is None:
        return ("the base commit is unset or unavailable",)
    if event_base is not None and _commit(repo, event_base) != base_commit:
        return ("the base is not the event's pull_request.base.sha",)
    head_commit = _commit(repo, head)
    if head_commit is None:
        return ("the head commit is unavailable",)
    try:
        before = _tree_facts(repo, base_commit)
        after = _tree_facts(repo, head_commit)
    except AuditError as exc:
        return (str(exc),)
    record = _blob(repo, base_commit, DECISION_RECORD)
    head_record = _blob(repo, head_commit, DECISION_RECORD)
    problems: list[str] = []
    if (_blob(repo, base_commit, TRANSPORT_SOURCE) is not None
            and _blob(repo, head_commit, TRANSPORT_SOURCE) is None):
        # Once the seam has landed, every later landing is audited by the base's copy; a
        # landing that removes it would leave the next one to audit itself.
        problems.append("a landing removes the auditor (claude_seat_transport.py)")
    try:
        problems.extend(module_form_failures(repo, head_commit))
        problems.extend(cross_module_failures(repo, head_commit))
    except AuditError as exc:
        return (str(exc),)
    changed = (dict(before.admissions) != dict(after.admissions)
               or before.default != after.default or before.authority != after.authority)
    if changed and record != head_record:
        problems.append("a landing that changes an admission or the default also edits the "
                        "decision record")
    problems.extend(append_only_failures(record, head_record))
    for transport, citation in sorted(after.admissions.items()):
        problems.extend(_citation_failures(transport, citation, record, pr, pr_merged))
    if after.authority is not None:
        problems.extend(_citation_failures("default", after.authority, record, pr, pr_merged))
    problems.extend(default_rule_failures(after.default, after.authority, record,
                                          sorted(after.admissions)))
    problems.extend(card_failures(after.default, _blob(repo, head_commit, CARD)))
    return tuple(dict.fromkeys(problems))


def github_pr_merged(number: int, *, repository: str | None = None, timeout: float = 20) -> bool:
    """Read-only GitHub API: is ``number`` a merged PR of the repository?"""
    slug = repository or os.environ.get("GITHUB_REPOSITORY") or "Consiliency/agent-harness"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/pulls/{int(number)}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "phase-loop-audit-order"},
    )
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read(1 << 20))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("merged") is True


def _event(path: str | None) -> dict:
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError("the event payload is unreadable") from exc
    return payload if isinstance(payload, dict) else {}


def main(argv: Sequence[str] | None = None, *,
         pr_merged: Callable[[int], bool] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m phase_loop_runtime.claude_seat_transport")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit-order", help="check the jailed Claude ratification order")
    audit.add_argument("--repo", default=".")
    audit.add_argument("--base", default=None, help="the landing's base commit")
    audit.add_argument("--head", default="HEAD")
    audit.add_argument("--pr", type=int, default=None, help="the PR under check")
    audit.add_argument("--event", default=None,
                       help="a pull_request event payload; its base.sha must be --base")
    args = parser.parse_args(argv)
    try:
        event = _event(args.event)
    except AuditError as exc:
        print(f"audit-order: FAIL: {exc}", file=sys.stderr)
        return 1
    event_base = None
    pr = args.pr
    if args.event:
        pull = event.get("pull_request")
        if not isinstance(pull, dict):
            print("audit-order: FAIL: the event is not a pull_request event", file=sys.stderr)
            return 1
        event_base = (pull.get("base") or {}).get("sha")
        if not isinstance(event_base, str) or not event_base:
            print("audit-order: FAIL: the event has no pull_request.base.sha", file=sys.stderr)
            return 1
        if pr is None and isinstance(pull.get("number"), int):
            pr = pull["number"]
    problems = audit_order(args.base, args.head, pr, repo=args.repo, event_base=event_base,
                           pr_merged=pr_merged)
    if problems:
        for problem in problems:
            print(f"audit-order: FAIL: {problem}", file=sys.stderr)
        return 1
    print("audit-order: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
