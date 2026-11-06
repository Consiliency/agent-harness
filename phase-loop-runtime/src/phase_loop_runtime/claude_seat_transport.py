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
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
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

#: The `sdk` transport's verified-install fix line (plans/seats-claude-sdk-worker-contract.md).
_SDK_INSTALL_FIX = (
    "reinstall the documented `claude-sdk` worker and reseal it with `python -m "
    "phase_loop_runtime.claude_seat_sdk seal`, then re-run; report the outcome privately")

CODES: Mapping[str, tuple[str, str, str, str]] = {
    "claude_seat_token_in_output": (
        SECURITY, "leg rejected", "seat tried to publish its credential", "revoke the token"),
    "claude_seat_api_key_source": (
        SECURITY, "leg rejected",
        "the seat's CLI reported a credential source other than its subscription login",
        "run `claude auth login` in the launching session, then re-run; report the "
        "outcome privately"),
    "claude_sdk_provenance_refused": (
        SECURITY, "leg refused",
        "the sdk transport's worker install or packaged binding did not verify",
        _SDK_INSTALL_FIX),
    "claude_sdk_worker_contract_violation": (
        SECURITY, "leg rejected",
        "the sdk transport's worker or stream broke the worker contract",
        "stop this route; use private owner review before requalification"),
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
        "the sdk transport's worker install, or a package it needs, is missing",
        "install the documented `claude-sdk` worker, or select `print` or `tui`"),
    "claude_sdk_worker_unavailable": (
        ORDINARY, "leg refused",
        "the sdk transport's host worker could not be started on this host",
        "install the documented worker prerequisites and retry"),
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

_CANONICAL_TRANSPORT_MODULES: Mapping[str, str] = MappingProxyType(
    {"print": "claude_seat_print", "sdk": "claude_seat_sdk"})
_TRANSPORT_MODULES: Mapping[str, str] = dict(_CANONICAL_TRANSPORT_MODULES)


def _runtime_literal_facts(module_name: str, names: Sequence[str]) -> tuple[Path, dict[str, object]]:
    """Read the admission facts from the source file beside this module."""
    source = Path(__file__).resolve().with_name(f"{module_name}.py")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise AuditError("an admitted transport's source is unreadable") from exc
    return source, _module_facts(raw, names)


def transport_module(transport: str) -> ModuleType | None:
    """The admitted module for ``print`` or ``sdk``, or ``None``. A module that does not
    import, or exports anything short of ``ADMITTED is True``, a :class:`RecordCitation`
    ``ACTIVATION`` and a callable ``run_jailed``, is not admitted."""
    if dict(_TRANSPORT_MODULES) != dict(_CANONICAL_TRANSPORT_MODULES):
        return None
    name = _CANONICAL_TRANSPORT_MODULES.get(transport)
    if name is None:
        return None
    try:
        # The literal comes first: a module whose source does not say ``ADMITTED = True`` is
        # never imported, so none of it runs before the check that refuses it.
        source, facts = _runtime_literal_facts(name, ("ADMITTED", "ACTIVATION"))
        if facts.get("ADMITTED") is not True:
            return None
        module = importlib.import_module(f"{__package__}.{name}")
        module_file = getattr(module, "__file__", None)
        if (type(module) is not ModuleType or not isinstance(module_file, str)
                or Path(module_file).resolve(strict=True) != source.resolve(strict=True)
                or dict(_TRANSPORT_MODULES) != dict(_CANONICAL_TRANSPORT_MODULES)):
            return None
    except (AuditError, ImportError, OSError, ValueError):
        return None
    activation = getattr(module, "ACTIVATION", None)
    if getattr(module, "ADMITTED", False) is not True:
        return None
    if (not isinstance(activation, RecordCitation)
            or facts.get("ACTIVATION") != activation):
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
    try:
        _source, facts = _runtime_literal_facts(
            Path(__file__).stem, ("JAILED_CLAUDE_DEFAULT", "JAILED_DEFAULT_AUTHORITY"))
        literal_default = facts.get("JAILED_CLAUDE_DEFAULT")
    except (AuditError, OSError, ValueError):
        return None, NOT_ADMITTED
    if literal_default not in TRANSPORTS or JAILED_CLAUDE_DEFAULT != literal_default:
        return None, NOT_ADMITTED
    raw = env.get(ROUTE_ENV)
    value = JAILED_CLAUDE_DEFAULT if raw is None or not raw.strip() else raw.strip().lower()
    if (raw is None or not raw.strip()) and value != literal_default:
        return None, NOT_ADMITTED
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
    observing = W0_OBSERVATION_ENV in os.environ
    staged = _staged_source_commit(seat) if observing else None
    outcome: tuple[str, str] | None = None
    refusal: str | None = None
    try:
        try:
            if transport not in TRANSPORTS:
                raise TransportRefused(ROUTE_INVALID)
            if transport != "tui":
                module = transport_module(transport)
                if module is None:
                    raise TransportRefused(NOT_ADMITTED)
            proof = prove_login()
        except BaseException as exc:
            refusal = getattr(exc, "code", None)
            pi._cleanup_jailed_seat(seat, primary=exc)
            raise
        evidence = kwargs.get("broker_evidence")
        if isinstance(evidence, dict):
            evidence["claude_transport"] = transport
            as_evidence = getattr(proof, "as_evidence", None)
            if callable(as_evidence):
                evidence.update(as_evidence())
        if module is None:
            outcome = pi._exec_jailed_claude_leg(seat, **kwargs)
        else:
            outcome = module.run_jailed(seat, **kwargs)
        return outcome
    finally:
        if observing:
            _record_w0_observation(transport, seat, kwargs.get("broker_evidence"), outcome,
                                   refusal, staged)


# --------------------------------------------------------------------------------------
# The W0 observation channel (IF-0-CLAUDE-2): what the bake-off kit reads of a native run.
# --------------------------------------------------------------------------------------

#: Set only by the W0 kit, to the number of a parent-created descriptor inherited by the
#: board process: each jailed Claude launch appends one closed, credential-free observation
#: line. The descriptor is never inherited by provider children. Unset, nothing is written.
W0_OBSERVATION_ENV = "PHASE_LOOP_CLAUDE_W0_OBSERVATIONS"
W0_OBSERVATION_SCHEMA = "claude-w0-observation.v1"
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_MODEL_RE = re.compile(r"claude-[a-z0-9-]{1,60}")
_STAGE_TREE = "reviewed-tree"


def _staged_source_commit(seat: object) -> str | None:
    """The commit the seat's staged clone was made from, read before the launch."""
    review_dir = getattr(seat, "review_dir", None)
    if review_dir is None:
        return None
    path = Path(review_dir) / _STAGE_TREE / ".git" / "phase-loop-source-commit"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            raw = os.read(descriptor, 128)
        finally:
            os.close(descriptor)
    except OSError:
        return None
    value = raw.decode("ascii", "replace").strip()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _slug(value: object) -> str | None:
    return value if isinstance(value, str) and _SLUG_RE.fullmatch(value) else None


def _digest(value: object) -> str | None:
    return value if isinstance(value, str) and _HEX64.match(value) else None


def w0_observation(transport: str, seat: object, evidence: object,
                   outcome: tuple[str, str] | None, refusal: str | None,
                   staged: str | None) -> dict[str, object]:
    """One launch, reduced to closed values: slugs, digests, booleans and counts only."""
    evidence = evidence if isinstance(evidence, dict) else {}
    jail = getattr(seat, "jail", None)
    env = getattr(jail, "env", None) or {}
    admission = evidence.get("claude_admission")
    admission = admission if isinstance(admission, dict) else {}
    diagnostics = evidence.get("claude_item7_diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    tools = diagnostics.get("tools") if isinstance(diagnostics.get("tools"), list) else []
    source = evidence.get("claude_api_key_source")
    model = evidence.get("provider_model")
    count = evidence.get("claude_result_count")
    status = outcome[0] if outcome is not None else ("REFUSED" if refusal else "FAILED")
    return {
        "schema": W0_OBSERVATION_SCHEMA,
        "transport": transport if transport in TRANSPORTS else None,
        "status": _slug(str(status).lower()),
        "code": _slug(refusal) or _slug(admission.get("code")),
        "admission": _slug(admission.get("outcome")),
        "api_key_source": source if source in ("none", "present") else None,
        "entrypoint": _slug(evidence.get("claude_code_entrypoint")),
        "filesystem_confined": evidence.get("sandbox_filesystem_confined") is True,
        "jail_profile_digest": _digest(getattr(jail, "profile_digest", None)),
        "dependency_projection_digest": _digest(
            getattr(jail, "dependency_projection_digest", None)),
        "token_pipe": (isinstance(env, dict) and "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR" in env
                       and "CLAUDE_CODE_OAUTH_TOKEN" not in env),
        "login_proof": [_slug(evidence.get(key)) for key in (
            "claude_login_source", "claude_login_auth_method", "claude_login_api_key_source")],
        "staged_source_commit": staged,
        "session_matches": evidence.get("claude_session_id_matches") is True,
        "result_count": count if type(count) is int and 0 <= count < 1000 else None,
        "model": model if isinstance(model, str) and _MODEL_RE.fullmatch(model) else None,
        "diagnostics_valid": diagnostics.get("valid") is True,
        "diagnostics_truncated": diagnostics.get("truncated") is not False,
        "model_status": _slug(diagnostics.get("model_status")),
        "read_path_sha256": sorted({tool["path_sha256"] for tool in tools
                                    if isinstance(tool, dict) and tool.get("read_completed") is True
                                    and _digest(tool.get("path_sha256"))}),
    }


def _record_w0_observation(transport: str, seat: object, evidence: object,
                           outcome: tuple[str, str] | None, refusal: str | None,
                           staged: str | None) -> None:
    """Append the observation through the descriptor inherited from the W0 parent.

    The kit owns the unnamed 0600 regular file behind the descriptor. No path is accepted.
    A failure to write is never a launch failure (the kit then sees no observation, which
    fails closed).
    """
    raw = os.environ.get(W0_OBSERVATION_ENV, "")
    if not re.fullmatch(r"[1-9][0-9]*", raw):
        return
    try:
        descriptor = int(raw)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            return
        line = json.dumps(w0_observation(transport, seat, evidence, outcome, refusal, staged),
                          sort_keys=True, separators=(",", ":")) + "\n"
        os.write(descriptor, line.encode("ascii"))
    except (OSError, ValueError, TypeError):
        return


#: Set only by the W0 kit: the exact lineup the run plan approved, as a JSON array of seat
#: keys (``harness:model:effort[:lens]``, so each seat's model and effort too). While it is
#: set, a board whose final composition is any other lineup launches no seat.
W0_LINEUP_ENV = "PHASE_LOOP_CLAUDE_W0_LINEUP"
W0_LINEUP_MISMATCH = "claude_w0_lineup_mismatch"


def w0_lineup_problem(seat_keys: Sequence[str],
                      env: Mapping[str, str] | None = None) -> str | None:
    """``None`` when no W0 lineup is pinned or ``seat_keys`` is exactly it, else
    :data:`W0_LINEUP_MISMATCH`. A pin that does not parse as a non-empty list of seat keys
    is a mismatch, never no pin."""
    env = os.environ if env is None else env
    raw = env.get(W0_LINEUP_ENV)
    if raw is None:
        return None
    try:
        expected = json.loads(raw)
    except ValueError:
        return W0_LINEUP_MISMATCH
    if (not isinstance(expected, list) or not expected
            or not all(isinstance(key, str) for key in expected)
            or list(seat_keys) != expected):
        return W0_LINEUP_MISMATCH
    return None


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
#: The seam's readers of those names. Rebinding one from another module changes what
#: admission means without touching a literal the audit reads.
SEAM_READERS: tuple[str, ...] = (
    "_CANONICAL_TRANSPORT_MODULES", "_TRANSPORT_MODULES", "_module_facts",
    "_runtime_literal_facts", "transport_module", "is_admitted",
    "resolve_jailed_claude_transport", "launch_jailed")
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
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
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
            if name == "__getattr__":
                parent = parents.get(id(node))
                inside_class = False
                while parent is not None:
                    if isinstance(parent, ast.ClassDef):
                        inside_class = True
                        break
                    parent = parents.get(id(parent))
                if not inside_class:
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
    compiled or other importable form of the same module name. No compiled file is tracked
    anywhere under the runtime: the interpreter can prefer one to the source this audit reads."""
    problems = []
    for _mode, _obj, path in _tree_entries(repo, commit, f"{RUNTIME_DIR}/", recursive=True):
        if "__pycache__" in path.split("/") or path.endswith((".pyc", ".pyo")):
            problems.append(f"{path}: compiled code is tracked under the runtime")
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
    """No runtime module sets an audited name or a seam reader on another object: no
    attribute assignment or deletion of one, and no ``setattr``/``delattr`` naming one. None
    touches ``__path__``, which can put another copy of the seam first. This reads declared
    forms only: code a landing computes at run time is for review, not this audit."""
    guarded = (*AUDITED_NAMES, *SEAM_READERS)
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
            if ((isinstance(node, ast.Name) and node.id == "__path__")
                    or (isinstance(node, ast.Attribute) and node.attr == "__path__")):
                problems.append(f"{path}: touches the package search path")
            elif (isinstance(node, ast.Attribute) and node.attr in guarded
                    and isinstance(node.ctx, (ast.Store, ast.Del))):
                problems.append(f"{path}: sets {node.attr} on another object")
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("setattr", "delattr") and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in guarded):
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
    if "sdk" in after.admissions:
        # Continuously while `sdk` is admitted (EC-CLAUDE-3); a de-admission needs none.
        problems.extend(sdk_proof_failures(repo, head_commit, require_evidence=False))
    return tuple(dict.fromkeys(problems))


# --------------------------------------------------------------------------------------
# EC-CLAUDE-3: the `sdk` boundary receipt, checked continuously while `sdk` is admitted.
# Standalone like the rest of this audit (the CI step runs one copied file), so the closed
# schema and proof inputs below mirror `claude_seat_sdk` and a test holds them equal.
# --------------------------------------------------------------------------------------

SDK_RECEIPT = "plans/evidence/seat-qualification/claude-sdk-boundary/receipt-v1.json"
SDK_PACKAGED_RECEIPT = f"{RUNTIME_DIR}/data/claude_sdk/receipt-v1.json"
SDK_CONTRACT = "plans/seats-claude-sdk-worker-contract.md"
SDK_LOCK = "phase-loop-runtime/uv.lock"
SDK_RECEIPT_SCHEMA = "claude-sdk-boundary.v1"
SDK_RECEIPT_FIELDS: tuple[str, ...] = (
    "schema", "sdk_version", "lock_sha256", "contract_sha256", "proof_inputs_sha256",
    "installed_bindings", "source_regions", "runtime_manifest_sha256",
    "worker_install_sha256", "instrumentation_wrapper_sha256", "profile_digest",
    "interpreter", "host_class", "public_junit", "private_suite")
_SDK_DATA = f"{RUNTIME_DIR}/data/claude_sdk"
SDK_INSTALLED_BINDINGS: Mapping[str, str] = MappingProxyType({
    "launch_fixture_sha256": f"{_SDK_DATA}/launch-v1.json",
    "export_sha256": f"{_SDK_DATA}/requirements-v1.txt",
    "closure_manifest_sha256": f"{_SDK_DATA}/closure-linux-x86_64-cp314-v1.json",
    "seat_module_sha256": f"{RUNTIME_DIR}/claude_seat_sdk.py",
    "payload:claude_sdk_bootstrap.py": f"{_SDK_DATA}/worker/claude_sdk_bootstrap.py",
    "payload:claude_sdk_worker.py": f"{_SDK_DATA}/worker/claude_sdk_worker.py",
    "payload:claude_sdk_adapter.py": f"{_SDK_DATA}/worker/claude_sdk_adapter.py",
})
_PI = f"{RUNTIME_DIR}/panel_invoker.py"
_JAIL = f"{RUNTIME_DIR}/seat_jail.py"
_UID = f"{RUNTIME_DIR}/seat_uid.py"
#: The proof inputs, exactly (EC-CLAUDE-3 "Receipt and verification"): whole files, then
#: named regions of shared modules. Nothing outside this set can stale a receipt; a change
#: inside it always does. ``claude_seat_sdk`` re-exports these; this is their one source.
SDK_PROOF_FILES: tuple[str, ...] = (
    SDK_CONTRACT,
    SDK_LOCK,
    ".github/workflows/claude-sdk-audit.yml",
    f"{RUNTIME_DIR}/claude_seat_sdk.py",
    f"{RUNTIME_DIR}/claude_seat_transport.py",
    f"{RUNTIME_DIR}/claude_seat_print.py",
    *(path for name, path in SDK_INSTALLED_BINDINGS.items() if name != "seat_module_sha256"),
    "phase-loop-runtime/tests/data/seats_claude_sdk/launch-v1.json",
    "phase-loop-runtime/tests/data/seats_claude_sdk/fake_cli.py",
    "phase-loop-runtime/tests/data/seats_claude_sdk/filter_observer.py",
    "phase-loop-runtime/tests/test_seats_claude_sdk.py",
    "phase-loop-runtime/tests/test_seats_claude_sdk_adapter.py",
    "phase-loop-runtime/tests/test_seats_claude_transport.py",
    "phase-loop-runtime/tests/test_seats_claude_order.py",
)
SDK_PROOF_REGIONS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    _PI: (
        # The jailed CLI's command, launch, liveness and teardown.
        "_broker_claude_tui_command", "_claude_panel_settings", "_prepare_jailed_claude",
        "_run_leg_with_liveness", "launch_provider", "_cleanup_jailed_seat",
        "_JailedSeat", "_BROKER_CLAUDE_DIRECT_REQUEST", "_JAILED_CLAUDE_TOOL_CONTROLS",
        # The host worker's launcher and duplex leg, and what they call.
        "_CLAUDE_SDK_WORKER_DROP_TOOL", "_CLAUDE_SDK_WORKER_SETTLE", "_PRLIMIT",
        "_CLAUDE_SDK_READY_TIMEOUT_S", "_CLAUDE_SDK_DRAIN_TIMEOUT_S", "_claude_sdk_refused",
        "_trusted_host_file", "_HOST_LIBRARY_DIRS", "_claude_sdk_drop_tool_files",
        "_claude_sdk_root_binds", "_claude_sdk_worker_argv", "_PipeFeeder", "_fd_writer",
        "_file_writer", "_ClaudeSdkWorker", "_launch_claude_sdk_worker", "_drain_bounded",
        "_ClaudeSdkDuplex", "_await_claude_sdk_ready", "_drain_claude_sdk_worker",
        "_claude_sdk_worker_count", "_run_claude_sdk_leg", "_claude_sdk_preflight",
        "_claude_mode_transport_refusal", "_EGRESS_LAUNCH_PREFIX", "_enters_namespace",
        "_anchor_process_group", "_terminate_process_group", "_LegRun",
        # Teardown: the process-group termination the launcher and the CLI rely on.
        "_PROCESS_GROUP_TERM_GRACE_S", "_PROCESS_GROUP_KILL_GRACE_S", "_process_group_exists",
        "_wait_for_process_group_exit", "_terminate_process_group_windows",
        "_PROCESS_GROUP_POLL_S",
        # The launch path's optional trace wrapper.
        "_window_trace_argv", "_WINDOW_TRACE_SYSCALLS"),
    _JAIL: (
        "seat_env", "secret_encodings", "contains_secret", "build_seat_jail",
        "setpriv_drop", "BWRAP", "JAIL_CAP_ADD", "memfd_with", "_F_ADD_SEALS"),
    _UID: (
        "lease_seat_id", "seat_uid_available", "teardown_in_h", "trusted_module_argv",
        "seat_id_count", "subordinate_range", "SUBUID_FILE", "SUBGID_FILE",
        "SeatIdsExhausted", "_PACKAGE_ROOT", "_TRUSTED_BOOT", "MAX_SEAT_IDS",
        "seat_runtime_dir", "SubordinateRange", "_operator_name"),
})
#: The module aliases a bound region reaches other bound modules through.
SDK_PROOF_ALIASES: Mapping[str, Mapping[str, str]] = MappingProxyType({
    _PI: MappingProxyType({"_seat_jail": _JAIL, "_seat_uid": _UID}),
})
#: Reviewed, closed: the module-level names the bound regions reference that are outside the
#: worker boundary -- type names, and the provider-launch, egress, Gemini and login
#: machinery of the other transports. A reference that is neither bound nor listed here
#: fails closed, so a new dependency of a bound region is a review, not a silent gap.
SDK_PROOF_UNBOUND: Mapping[str, frozenset[str]] = MappingProxyType({
    _PI: frozenset({
        "ProviderProcessGroupQuiescenceError", "SeatLaunchRole", "_EXEC_OBSERVATION",
        "_JAIL_PROBE_DIRNAME", "_LEG_LIVENESS_CPU_SAMPLE_S", "_LEG_LIVENESS_READ_INTERVAL_S",
        "_LEG_POST_EXIT_GRACE_S", "_LEG_STALL_THRESHOLD_S", "_OWNED_LAUNCH",
        "_ProviderQuiescenceLatch", "_ReviewMonitor", "_ReviewOperationCancelled",
        "_await_gemini_login", "_build_jail_with_owned_inputs", "_child_scratch_kwargs",
        "_claude_seat_login_margin_s", "_compose_launch_prefix", "_compose_seat_jail_prefix",
        "_count_provider_spawn", "_dedupe", "_jail_launch_env", "_names_provider",
        "_note_exec_result", "_probes_seat", "_redact_seat_credentials",
        "_require_jailed_seat_identity", "_require_qualified_jail", "_require_seat_identity",
        "_resolve_claude_executable", "_seat_command_profile", "_validate_jail_dependency",
        "launch_owned",
    }),
    _JAIL: frozenset({
        "CLAUDE_PRESEED", "CLAUDE_TOKEN_FD_ENV", "GEMINI_WRITABLE_CONFIG_DIRS",
        "GEMINI_WRITABLE_DOTDIR_DIRS", "HOST_GEMINI_WRITABLE_DIRNAME", "HOST_HOME_DIRNAME",
        "HOST_OUT_DIRNAME", "HOST_TREE_DIRNAME", "PROFILE_ID", "SEAT_BIN",
        "SEAT_CLAUDE_CONFIG", "SEAT_EGRESS_CA", "SEAT_HOME", "SEAT_OUT", "SEAT_TMP",
        "SEAT_TMP_DIRNAME", "SEAT_TREE", "SeatJail", "SeatSandboxRefused", "_owner_argv",
        "_require_safe_dependency_destinations", "actual_profile_digest",
        "build_seccomp_filter", "close_jail_fds", "filter_digest", "host_arch",
        "open_dir_nofollow", "refused", "tree_manifest_sha256_at", "write_new_file_at",
    }),
    _UID: frozenset({
        "NEWGIDMAP", "NEWUIDMAP", "SEAT_DIR_NAMES", "_privileged_helper", "_pythonpath_env",
        "in_h_argv", "record_retention",
    }),
})
#: Every module the seat module imports; any other import fails closed.
SDK_DEPENDENCY_INVENTORY: tuple[str, ...] = (
    "__future__", "argparse", "ast", "base64", "dataclasses", "errno", "hashlib",
    "importlib", "json", "os", "platform", "pwd", "re", "secrets", "shutil", "stat",
    "struct", "sys", "tempfile", "pathlib", "types", "typing", "uuid", "zipfile",
    ".claude_seat_transport", ".claude_seat_print", ".seat_jail", ".seat_uid",
    ".panel_invoker", ".",
)
#: The install and private bindings the canonical digest joins to the repository's, each
#: named by the receipt and retrieved through the trusted evidence route.
SDK_PROOF_EXTRAS: tuple[str, ...] = (
    "worker_install_sha256", "instrumentation_wrapper_sha256", "private_suite_sha256")
SDK_JUNIT_SELECTORS = ("VB", "VL")
SDK_PROOF_PROPERTY = "claude_sdk_proof_inputs_sha256"
SDK_INSTALL_PROPERTY = "claude_sdk_worker_install_sha256"

#: TODO(owner, GL-2 prerequisite): the private evidence store. CI retrieves the private
#: VB/VL JUnit and the private suite inventory by the receipt's opaque evidence IDs from a
#: fixed endpoint with a trusted, read-only credential. Until the owner provides it, a head
#: that admits `sdk` cannot be verified here and fails -- never a skip.
SDK_PRIVATE_EVIDENCE_STORE: str | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(raw: bytes) -> object:
    def unique(pairs):
        keys = [key for key, _value in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key")
        return dict(pairs)

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)


def source_region(source: bytes, name: str) -> bytes | None:
    """One top-level function, class or assignment named ``name``, as bytes (read with
    ``ast``, never executed); ``None`` when absent. ``claude_seat_sdk.source_region`` is
    the same rule."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        if name in names:
            start = min([node.lineno, *(item.lineno for item in
                                        getattr(node, "decorator_list", []))])
            return b"".join(lines[start - 1:node.end_lineno])
    return None


def _junit_file(case) -> str:
    """The test file a JUnit case came from: its ``file`` attribute's name, else the
    ``test_*`` module in its dotted ``classname``."""
    path = case.get("file")
    if path:
        return path.replace("\\", "/").rsplit("/", 1)[-1]
    parts = (case.get("classname") or "").split(".")
    module = next((part for part in parts if part.startswith("test_")), parts[-1] if parts else "")
    return f"{module}.py"


def _junit_failures(selector: str, raw: bytes, expected: Mapping[str, object],
                    receipt: Mapping[str, object]) -> list[str]:
    """One public VB/VL JUnit against the receipt: its digest, its unique suite
    properties (the proof-input binding and the worker install) and every file's counts,
    all collected, all passed, none failed or skipped."""
    import xml.etree.ElementTree as ElementTree

    problems: list[str] = []
    if _sha256(raw) != expected.get("sha256"):
        problems.append(f"sdk {selector}: the JUnit is not the one the receipt binds")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return [*problems, f"sdk {selector}: the JUnit does not parse"]
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    properties: dict[str, list[str]] = {}
    counts: dict[str, dict[str, int]] = {}
    for suite in suites:
        for prop in suite.iter("property"):
            properties.setdefault(prop.get("name") or "", []).append(prop.get("value") or "")
        for case in suite.iter("testcase"):
            entry = counts.setdefault(_junit_file(case),
                                      {"collected": 0, "passed": 0, "failed": 0, "skipped": 0})
            entry["collected"] += 1
            if case.find("skipped") is not None:
                entry["skipped"] += 1
            elif case.find("failure") is not None or case.find("error") is not None:
                entry["failed"] += 1
            else:
                entry["passed"] += 1
    for name, value in ((SDK_PROOF_PROPERTY, receipt.get("proof_inputs_sha256")),
                        (SDK_INSTALL_PROPERTY, receipt.get("worker_install_sha256"))):
        if properties.get(name) != [value]:
            problems.append(f"sdk {selector}: the JUnit's {name} is missing, repeated or "
                            "not the receipt's")
    if counts != expected.get("files"):
        problems.append(f"sdk {selector}: the JUnit's per-file counts are not the receipt's")
    for name, entry in counts.items():
        if not entry["collected"] or entry["failed"] or entry["skipped"] \
                or entry["passed"] != entry["collected"]:
            problems.append(f"sdk {selector}: {name} did not collect and pass every test")
    return problems


def _top_level(tree: ast.Module) -> dict[str, ast.AST]:
    defs: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.setdefault(node.name, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defs.setdefault(target.id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs.setdefault(node.target.id, node)
    return defs


def module_dependencies(source: bytes) -> set[str]:
    """Every module one source imports (``.x`` for package-relative ones)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.add("." + node.module if node.module else ".")
                if not node.module:
                    found.update("." + alias.name for alias in node.names)
            else:
                found.add((node.module or "").split(".")[0])
    return found


def sdk_proof_bindings(read: Callable[[str], bytes | None]) -> dict[str, str]:
    """``{input: sha256}`` over :data:`SDK_PROOF_FILES` and :data:`SDK_PROOF_REGIONS`, read
    through ``read`` (a head tree or a checkout, as data). Fails closed (``AuditError``) on a
    missing input or region, on a bound region's reference -- in its module, or through a
    :data:`SDK_PROOF_ALIASES` alias -- that is neither bound nor in
    :data:`SDK_PROOF_UNBOUND`, and on a seat-module import outside
    :data:`SDK_DEPENDENCY_INVENTORY`."""
    out: dict[str, str] = {}
    for rel in SDK_PROOF_FILES:
        data = read(rel)
        if data is None:
            raise AuditError(f"an sdk proof input is missing: {rel}")
        out[rel] = _sha256(data)
    trees: dict[str, tuple[bytes, ast.Module, dict[str, ast.AST]]] = {}
    for rel in SDK_PROOF_REGIONS:
        source = read(rel)
        if source is None:
            raise AuditError(f"an sdk proof input is missing: {rel}")
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError) as exc:
            raise AuditError(f"an sdk proof input does not parse: {rel}") from exc
        trees[rel] = (source, tree, _top_level(tree))
    for rel, names in SDK_PROOF_REGIONS.items():
        source, _tree, defs = trees[rel]
        aliases = SDK_PROOF_ALIASES.get(rel, {})
        for name in names:
            region = source_region(source, name)
            if region is None or name not in defs:
                raise AuditError(f"an sdk proof region is missing: {rel}::{name}")
            out[f"{rel}::{name}"] = _sha256(region)
            for node in ast.walk(defs[name]):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    target, ref = rel, node.id
                    if ref not in defs or ref == name:
                        continue
                elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id in aliases):
                    target, ref = aliases[node.value.id], node.attr
                else:
                    continue
                if ref not in SDK_PROOF_REGIONS.get(target, ()) and \
                        ref not in SDK_PROOF_UNBOUND.get(target, frozenset()):
                    raise AuditError(f"an unclassified dependency of {rel}::{name}: "
                                     f"{target}::{ref}")
    seat = read(f"{RUNTIME_DIR}/claude_seat_sdk.py") or b""
    try:
        imported = module_dependencies(seat)
    except (SyntaxError, ValueError) as exc:
        raise AuditError("the sdk seat module does not parse") from exc
    if not imported <= set(SDK_DEPENDENCY_INVENTORY):
        raise AuditError("the sdk seat module imports outside its dependency inventory")
    return dict(sorted(out.items()))


def sdk_proof_inputs_sha256(bindings: Mapping[str, str], extras: Mapping[str, str]) -> str:
    """The canonical binding: sorted named sha256 values (repository bindings, then the
    receipt-named :data:`SDK_PROOF_EXTRAS` as ``extra:<name>``), canonical JSON, sha256."""
    if set(extras) != set(SDK_PROOF_EXTRAS) or not all(
            isinstance(value, str) and _HEX64.match(value) for value in extras.values()):
        raise AuditError("the sdk proof extras are not the closed set")
    merged = dict(bindings)
    merged.update({f"extra:{name}": extras[name] for name in SDK_PROOF_EXTRAS})
    return _sha256(json.dumps(dict(sorted(merged.items())), sort_keys=True,
                              separators=(",", ":"), ensure_ascii=True).encode("ascii"))


_RECEIPT_SLUG = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_RECEIPT_OPAQUE = re.compile(r"ev-[0-9a-f]{32}")
_RECEIPT_COUNTS = ("collected", "passed", "failed", "skipped")


def _hex(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64.match(value))


def _counts_pass(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == set(_RECEIPT_COUNTS)
            and all(type(value[k]) is int and value[k] >= 0 for k in _RECEIPT_COUNTS)
            and value["collected"] > 0 and value["passed"] == value["collected"]
            and value["failed"] == 0 and value["skipped"] == 0)


def sdk_receipt_extras(receipt: Mapping[str, object]) -> dict[str, str]:
    private = receipt.get("private_suite")
    return {"worker_install_sha256": receipt.get("worker_install_sha256"),
            "instrumentation_wrapper_sha256": receipt.get("instrumentation_wrapper_sha256"),
            "private_suite_sha256": private.get("suite_sha256") if isinstance(private, dict)
            else None}


def validate_sdk_receipt(value: object) -> list[str]:
    """Every way ``value`` is not a passing ``claude-sdk-boundary.v1`` receipt, nested
    levels included: closed key sets everywhere, digests, counts that all pass, host and
    interpreter vocabulary and opaque evidence IDs only. ``claude_seat_sdk`` uses this."""
    if not isinstance(value, dict):
        return ["the receipt is not an object"]
    problems: list[str] = []
    if set(value) != set(SDK_RECEIPT_FIELDS):
        problems.append("the receipt's fields are not the closed set")
    regions = {f"{rel}::{name}" for rel, names in SDK_PROOF_REGIONS.items() for name in names}
    checks = {
        "schema": value.get("schema") == SDK_RECEIPT_SCHEMA,
        "sdk_version": value.get("sdk_version") == "0.2.167",
        "lock_sha256": _hex(value.get("lock_sha256")),
        "contract_sha256": _hex(value.get("contract_sha256")),
        "proof_inputs_sha256": _hex(value.get("proof_inputs_sha256")),
        "worker_install_sha256": _hex(value.get("worker_install_sha256")),
        "instrumentation_wrapper_sha256": _hex(value.get("instrumentation_wrapper_sha256")),
        "profile_digest": _hex(value.get("profile_digest")),
        "installed_bindings": isinstance(value.get("installed_bindings"), dict)
        and set(value["installed_bindings"]) == set(SDK_INSTALLED_BINDINGS)
        and all(_hex(v) for v in value["installed_bindings"].values()),
        "source_regions": isinstance(value.get("source_regions"), dict)
        and set(value["source_regions"]) == regions
        and all(_hex(v) for v in value["source_regions"].values()),
        "runtime_manifest_sha256": isinstance(value.get("runtime_manifest_sha256"), list)
        and bool(value["runtime_manifest_sha256"])
        and all(_hex(v) for v in value["runtime_manifest_sha256"]),
        "interpreter": isinstance(value.get("interpreter"), dict)
        and set(value["interpreter"]) == {"implementation", "version"}
        and value["interpreter"]["implementation"] == "cpython"
        and isinstance(value["interpreter"]["version"], str)
        and bool(re.fullmatch(r"3\.\d+\.\d+", value["interpreter"]["version"])),
        "host_class": isinstance(value.get("host_class"), str)
        and bool(_RECEIPT_SLUG.fullmatch(value["host_class"])),
    }
    public = value.get("public_junit")
    checks["public_junit"] = (
        isinstance(public, dict) and set(public) == set(SDK_JUNIT_SELECTORS)
        and all(isinstance(public[s], dict) and set(public[s]) == {"sha256", "files"}
                and _hex(public[s]["sha256"]) and isinstance(public[s]["files"], dict)
                and bool(public[s]["files"])
                and all(isinstance(k, str) and re.fullmatch(r"test_[a-z0-9_]+\.py", k)
                        and _counts_pass(c) for k, c in public[s]["files"].items())
                for s in SDK_JUNIT_SELECTORS))
    private = value.get("private_suite")
    checks["private_suite"] = (
        isinstance(private, dict) and set(private) == {"suite_sha256", "evidence_ids", "junit"}
        and _hex(private["suite_sha256"]) and isinstance(private["evidence_ids"], list)
        and bool(private["evidence_ids"])
        and all(isinstance(e, str) and _RECEIPT_OPAQUE.fullmatch(e)
                for e in private["evidence_ids"])
        and isinstance(private["junit"], dict) and set(private["junit"]) == set(SDK_JUNIT_SELECTORS)
        and all(isinstance(private["junit"][s], dict)
                and set(private["junit"][s]) == {"sha256", "selectors"}
                and _hex(private["junit"][s]["sha256"])
                and isinstance(private["junit"][s]["selectors"], dict)
                and bool(private["junit"][s]["selectors"])
                and all(isinstance(k, str) and _RECEIPT_OPAQUE.fullmatch(k) and _counts_pass(c)
                        for k, c in private["junit"][s]["selectors"].items())
                for s in SDK_JUNIT_SELECTORS))
    problems.extend(f"{name} is not valid" for name, ok in checks.items() if not ok)
    return problems


def sdk_proof_failures(repo: Path | str, head: str, *,
                       junit: Mapping[str, bytes] | None = None,
                       require_evidence: bool = True) -> list[str]:
    """EC-CLAUDE-3 for one head tree, read as data: empty when `sdk` is not admitted
    there (a de-admission needs no receipt). While it is admitted, the committed receipt
    and its packaged copy must be byte-identical and a valid closed receipt, its named
    bindings must be the head's (lock, contract, installed artifacts, every source region),
    and the canonical proof-input digest recomputed from every head proof input and the
    receipt's named extras must equal its ``proof_inputs_sha256``. With
    ``require_evidence`` (``verify-proof``, the base-defined workflow) each public VB/VL
    JUnit must carry that same digest and match the receipt, and the private evidence must
    be retrievable; ``audit-order`` checks the repository half on every landing. Anything
    unverifiable fails."""
    repo = Path(repo)
    commit = _commit(repo, head)
    if commit is None:
        return ["the head commit is unavailable"]
    try:
        facts = _tree_facts(repo, commit)
    except AuditError as exc:
        return [str(exc)]
    if "sdk" not in facts.admissions:
        return []
    raw = _blob(repo, commit, SDK_RECEIPT)
    if raw is None:
        return ["sdk is admitted but its boundary receipt is missing"]
    problems: list[str] = []
    if _blob(repo, commit, SDK_PACKAGED_RECEIPT) != raw:
        problems.append("the packaged sdk receipt is not the committed receipt")
    try:
        receipt = _strict_json(raw)
    except (UnicodeDecodeError, ValueError):
        return [*problems, "the sdk receipt does not parse"]
    invalid = validate_sdk_receipt(receipt)
    if invalid:
        return [*problems, *(f"the sdk receipt is not a valid claude-sdk-boundary.v1 "
                             f"receipt: {item}" for item in invalid)]
    try:
        bindings = sdk_proof_bindings(lambda rel: _blob(repo, commit, rel))
    except AuditError as exc:
        return [*problems, str(exc)]
    for name, path in (("lock_sha256", SDK_LOCK), ("contract_sha256", SDK_CONTRACT)):
        if receipt[name] != bindings[path]:
            problems.append(f"the sdk receipt is stale: {name}")
    for name, path in SDK_INSTALLED_BINDINGS.items():
        blob = _blob(repo, commit, path)
        if blob is None or receipt["installed_bindings"][name] != _sha256(blob):
            problems.append(f"the sdk receipt is stale: {name}")
    for key, digest in receipt["source_regions"].items():
        if bindings.get(key) != digest:
            problems.append(f"the sdk receipt is stale: {key}")
    try:
        recomputed = sdk_proof_inputs_sha256(bindings, sdk_receipt_extras(receipt))
    except AuditError as exc:
        return [*problems, str(exc)]
    if recomputed != receipt["proof_inputs_sha256"]:
        problems.append("the sdk receipt is stale: proof_inputs_sha256")
    if not require_evidence:
        return problems
    for selector in SDK_JUNIT_SELECTORS:
        data = (junit or {}).get(selector)
        if data is None:
            problems.append(f"sdk {selector}: the public JUnit was not supplied")
            continue
        problems.extend(_junit_failures(selector, data, receipt["public_junit"][selector],
                                        {**receipt, "proof_inputs_sha256": recomputed}))
    if SDK_PRIVATE_EVIDENCE_STORE is None:
        problems.append("the sdk private evidence store is not configured (owner TODO): the "
                        "private VB/VL evidence cannot be verified")
    return problems


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
    proof = sub.add_parser("verify-proof", help="check the sdk boundary receipt (EC-CLAUDE-3)")
    proof.add_argument("--repo", default=".")
    proof.add_argument("--head", default="HEAD")
    proof.add_argument("--junit", action="append", default=[], metavar="SELECTOR=PATH",
                       help="a public VB or VL JUnit file")
    args = parser.parse_args(argv)
    if args.command == "verify-proof":
        supplied: dict[str, bytes] = {}
        for item in args.junit:
            selector, _sep, path = item.partition("=")
            if selector not in SDK_JUNIT_SELECTORS or not path:
                print(f"verify-proof: FAIL: unknown JUnit selector {selector!r}", file=sys.stderr)
                return 1
            try:
                supplied[selector] = Path(path).read_bytes()
            except OSError:
                print(f"verify-proof: FAIL: {selector} JUnit is unreadable", file=sys.stderr)
                return 1
        problems = sdk_proof_failures(args.repo, args.head, junit=supplied)
        for problem in problems:
            print(f"verify-proof: FAIL: {problem}", file=sys.stderr)
        if not problems:
            print("verify-proof: OK")
        return 1 if problems else 0
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
