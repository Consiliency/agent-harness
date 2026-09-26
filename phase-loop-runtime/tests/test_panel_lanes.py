"""PANEL SL-0 frozen corpus: EC-PANEL-1..5, the entry points, and the slice-1 lens hook.

Frozen byte-equal from SL-0's landing until the phase merges (``content_tdd_receipt.v1``;
see ``panel_content_tdd_adapter.py``). SL-1, SL-2 and SL-3 turn these nodes green WITHOUT
editing this file; a later correction restarts SL-0. Plan: ``plans/phase-plan-v10-PANEL.md``;
roadmap: ``specs/phase-plans-v10.md`` Phase 18 (the EC-PANEL-N criteria are referenced by
id, never restated here).

Node groups (one per EC-PANEL-N falsifier)
------------------------------------------
* ``test_ec1_*``  EC-PANEL-1 lane tables, sources, validity, base-revision read, golden.
* ``test_ec2_*``  EC-PANEL-2 lane fallback over an availability x auth x preflight matrix.
* ``test_ec3_*``  EC-PANEL-3 one composition for every monitoring policy and entry point.
* ``test_ec4_*``  EC-PANEL-4 the landing minimum, the floor, explicit-profile seats.
* ``test_ec5_*``  EC-PANEL-5 labels on the result.
* ``test_ec3e_*`` every landing entry point driven through the entry point itself
  (``runner._run_legible_panel`` at ``production_code``; ``governed_board_gate`` at
  ``plan``; ``run-train`` at ``plan`` -- its review IS the governed gate, president
  follow-up F018; ``advisor-board`` at ``plan`` and ``tests_only``).
* ``test_ec6h_*`` the slice-1 lens hook with ``lens_frame`` stubbed in ``sys.modules``,
  on the brokered, TUI and native-fill routes (F023), each delivery bound to its seat by
  the identity production supplies (``deliver_seat_prompt``'s ``seat_key``; a native
  request's ``seat_key``), with lens-swap falsifiers.

Readiness (see the adapter): ``ec1``-``ec5`` and ``ec3e`` run once
``advisor_board.config.resolve_panel_table`` exists; ``ec6h`` once BOTH
``panel_invoker._seat_instructions`` and ``panel_invoker.deliver_seat_prompt`` exist. With ``PHASE_LOOP_TDD_EXPECT_PANEL=1``
nothing skips.

Names SL-0 fixes that IF-0-PANEL-1 left open (the contract; reported on the SL-0 PR)
------------------------------------------------------------------------------------
* ``ResolvedPanelTable.table`` / ``.source`` / ``.provenance``; ``PanelTable.lanes`` /
  ``.lenses`` (name -> text) / ``.min_distinct_vendors`` (``None`` when omitted);
  ``PanelLane.lens`` (a lens NAME) / ``.vendors``; ``ResolvedLens.kind`` in
  ``{"built-in", "declared"}``.
* ``resolve_panel_table(..., user_path=None, repo_dir=None, base_revision=None)`` is the
  built-in table; ``user_path`` is the user file; the repository file is read with
  ``git show <base_revision>:.agent-harness/advisor-boards.toml``.
* ``compose_panel_board``'s ``is_available``, ``auth_ok`` and ``preflight`` are each
  ``(vendor) -> bool``; ``seat_lenses`` is keyed by ``Seat.seat_key``; a seat's vendor is
  ``Seat.vendor_family`` and its ``Seat.lens`` is its lane's lens name;
  ``fallback_lanes`` / ``unfilled_lanes`` hold lens names (or ``PanelLane``); a lane is
  "filled by fallback" when its seated vendor is not the lane's FIRST listed vendor.
* ``BoardConfigError`` is the typed refusal of the loader, of ``validate_panel_change``
  and of an unreadable base revision; its message names the offending token.
* ``LandingDecision.admitted: bool``; ``PanelResult.panel_labels`` and
  ``PanelResult.landing_decision``; ``PanelLabels`` is a dataclass (or exposes
  ``to_dict()``) with the fields in :data:`LABEL_FIELDS`; ``minimum_source`` /
  ``table_source`` carry ``kind`` (``built-in`` / ``user`` / ``repository`` / the
  replaced label), ``path``, ``digest`` (sha256 hex of the whole user file) and
  ``base_revision``; each ``seats`` entry carries ``seat_key``, ``vendor``, ``lens``,
  ``lens_kind`` and ``lens_delivery`` (``prompt`` / ``metadata-only``).
* The ``advisor-board`` JSON and the runner's ``implementation-panel.json`` carry the
  labels under ``"panel_labels"``; ``governed_board_gate`` carries them on
  ``GateResult.panel.panel_labels``; ``run_train``'s result dict under ``"panel_labels"``.
* An entry point's target branch is ``origin``'s default branch (``main``), fetched at
  gate time. Its "change under review" is: the runner's ``expected_head``; the governed
  gate's ``reviewed_sha``; the ``advisor-board`` checkout's ``HEAD``; the train node's
  ledger ``head_sha``.
* The repository governance profile is ``.phase-loop/governance.toml`` (EC-GOVSETUP-1)
  and its per-tier ``panel`` list is written ``[tiers.<tier>] panel = [...]`` here
  (F027 asks SL-1 to name it; see the PR's insufficiency list).
* The ec3e harness observes ``snapshot_panel_run``, ``build_panel_context``,
  ``compose_panel_board`` and ``invoke_board`` at the call boundary: on their defining
  modules AND on any same-named module-level alias in ``runner``, ``governed_review``,
  ``cli`` and ``train_runner``. It forwards the entry's own ``invoke_board`` keywords
  unchanged (only transport-authority keys are stripped; ``spawn`` and
  ``president_invoke`` are injected), so the landing is decided on the ENTRY's policy.
* Orchestrator ruling (agent-harness#1092 r1): a supplied ``review_policy`` is accepted
  only if it equals ``panel_landing_policy(tier, context=panel_context)`` by value; the
  named-seat relaxation applies only when the context's resolved table sets the minimum
  from the user or repository file; any other supplied policy is a typed
  ``PresidentPolicyError`` raised inside ``_validate_review_board_policy``.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import inspect
import io
import json
import os
import re
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pytest

from harden_tdd_guard import invoke_sanctioned_review_transport
from panel_content_tdd_adapter import (
    HOOK,
    SLICE1,
    board_record,
    load_golden,
    require_ready,
    seat_record,
)
from president_fakes import deferring_president
from test_train_review_packet import synthetic_train_packet  # noqa: F401  (fixture by name)

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.panel_invoker import PanelLegResult, PresidentPolicyError, PresidentRuling

_FIXTURES = (synthetic_train_packet,)  # requested by name in the run-train ec3e nodes
BOARD_VENDORS: tuple[str, ...] = ("grok", "claude", "codex", "gemini")
PRESIDENT_TIERS: tuple[str, ...] = ("plan", "production_code")
CR_LENSES: tuple[str, ...] = ("adversarial", "correctness", "red-team", "alternative-approach")
REPO_REL = ".agent-harness/advisor-boards.toml"
GOVERNANCE_REL = ".phase-loop/governance.toml"
REPLACED_LABEL = "repository table invalid at base, replaced"
LENS_FRAME = "phase_loop_runtime.advisor_board.lens_frame"
LABEL_FIELDS: tuple[str, ...] = (
    "usable_distinct_vendors",
    "composed_seats",
    "usable_seats",
    "seats",
    "fallback_lanes",
    "unfilled_lanes",
    "effective_minimum",
    "minimum_source",
    "table_source",
    "explicit_profile",
    "minimum_met",
)
SEAT_LABEL_FIELDS: tuple[str, ...] = ("seat_key", "vendor", "lens", "lens_kind", "lens_delivery")
USER_BODY = '[president]\nladder = ["fable", "sol", "grok", "gemini"]\n'


# ---------------------------------------------------------------------------------------
# Readiness + IF-0-PANEL-1 names (looked up only AFTER the gate, never at import time)


def _names() -> types.SimpleNamespace:
    from phase_loop_runtime.advisor_board import composition, config, presets

    return types.SimpleNamespace(
        config=config,
        composition=composition,
        resolve=config.resolve_panel_table,
        validate=config.validate_panel_change,
        regate=config.panel_regate_required,
        snapshot=config.snapshot_panel_run,
        build=config.build_panel_context,
        ResolvedLens=config.ResolvedLens,
        ExplicitProfileSeats=config.ExplicitProfileSeats,
        BoardConfigError=config.BoardConfigError,
        compose=composition.compose_panel_board,
        lens_text=presets.BUILTIN_LENS_TEXT,
        landing_policy=pi.panel_landing_policy,
        evaluate=pi.evaluate_landing,
        PanelContext=config.PanelContext,
    )


def slice1() -> types.SimpleNamespace:
    require_ready(SLICE1)
    return _names()


def hook() -> types.SimpleNamespace:
    require_ready(HOOK)
    names = _names()
    names.seat_instructions = pi._seat_instructions
    return names


# ---------------------------------------------------------------------------------------
# Small helpers


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_GIT_C = (
    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "core.hooksPath=/dev/null",
    "-c", "user.name=panel", "-c", "user.email=panel@example.com",
    "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-c", "init.defaultBranch=main",
)


def _git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    done = subprocess.run(
        ["git", *_GIT_C, "-C", str(repo), *args], capture_output=True, text=True, env=env
    )
    if done.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _write(root: Path, files: Mapping[str, str | None]) -> None:
    for rel, text in files.items():
        path = root / rel
        if text is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _commit(repo: Path, files: Mapping[str, str | None], message: str) -> str:
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path, files: Mapping[str, str | None] | None = None, name: str = "fixture") -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    return repo, _commit(repo, {"README.md": "fixture\n", **(files or {})}, "base")


def _panel_toml(
    task: str,
    lanes: Iterable[tuple[str, Iterable[str]]],
    *,
    lenses: Mapping[str, str] | None = None,
    minimum: str | int | None = None,
    extra: str = "",
) -> str:
    lines = [f"[panel.{task}]"]
    if minimum is not None:
        lines.append(f"min_distinct_vendors = {minimum}")
    lines.append("lanes = [")
    for lens, vendors in lanes:
        lines.append(f"  {{ lens = {json.dumps(lens)}, vendors = {json.dumps(list(vendors))} }},")
    lines.append("]")
    if extra:
        lines.append(extra)
    if lenses:
        lines.append(f"[panel.{task}.lenses]")
        lines.extend(f"{json.dumps(name)} = {json.dumps(text)}" for name, text in lenses.items())
    return "\n".join(lines) + "\n"


def _cr_table(order: Iterable[str] = BOARD_VENDORS, *, minimum: str | int | None = None, **kw) -> str:
    """A code-review table whose every lane lists ``order``."""
    order = tuple(order)
    return _panel_toml("code-review", [(lens, order) for lens in CR_LENSES], minimum=minimum, **kw)


def _rotated_cr_table(*, minimum: str | int | None = None) -> str:
    """Lane ``i`` lists the board vendors rotated by ``i`` (today's vendor->lens pairing
    first), so the first ``k`` available vendors seat exactly ``k`` distinct vendors."""
    lanes = [(lens, BOARD_VENDORS[i:] + BOARD_VENDORS[:i]) for i, lens in enumerate(CR_LENSES)]
    return _panel_toml("code-review", lanes, minimum=minimum)


def _lane_names(items: Iterable[object]) -> list[str]:
    return sorted(str(getattr(item, "lens", item)) for item in items)


def _norm(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _norm(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    return value


def _labels(obj: object) -> dict:
    """``PanelLabels`` (or its JSON form) as a plain dict carrying every pinned field."""
    if obj is None:
        raise AssertionError("no panel labels were carried")
    if not (dataclasses.is_dataclass(obj) or isinstance(obj, Mapping)):
        to_dict = getattr(obj, "to_dict", None)
        if to_dict is None:
            raise AssertionError(f"panel labels {type(obj).__name__} are neither a dataclass nor a mapping")
        obj = to_dict()
    labels = _norm(obj)
    assert isinstance(labels, dict)
    missing = [name for name in LABEL_FIELDS if name not in labels]
    assert not missing, f"panel labels lack {missing}"
    for seat in labels["seats"]:
        absent = [name for name in SEAT_LABEL_FIELDS if name not in seat]
        assert not absent, f"seat label lacks {absent}"
    return labels


def _mark(spy, original):
    """Tag a test spy with what it wraps, so a second harness in one test wraps the
    ORIGINAL, never the first harness's spy."""
    spy.__panel_original__ = original
    return spy


def _unwrapped(fn):
    while hasattr(fn, "__panel_original__"):
        fn = fn.__panel_original__
    return fn


def _probes(ok: Iterable[str] = BOARD_VENDORS, *, unavailable=(), unauthed=(), preflight_fail=()):
    ok = set(ok)
    return {
        "is_available": lambda v: v in ok and v not in unavailable,
        "auth_ok": lambda v: v in ok and v not in unauthed,
        "preflight": lambda v: v in ok and v not in preflight_fail,
    }


class _ForcedProbes:
    """Route every ``compose_panel_board`` call (however an entry reaches it) through
    injected probes, so availability is the test's, never the host's."""

    def __init__(self, s, monkeypatch, available: Iterable[str] = BOARD_VENDORS) -> None:
        self.available = set(available)
        self.unauthed: set[str] = set()
        self.preflight_fail: set[str] = set()
        real = _unwrapped(s.composition.compose_panel_board)

        def forced(table, **_ignored):
            return real(
                table,
                is_available=lambda v: v in self.available,
                auth_ok=lambda v: v not in self.unauthed,
                preflight=lambda v: v not in self.preflight_fail,
            )

        _mark(forced, real)
        self.forced = forced
        monkeypatch.setattr(s.composition, "compose_panel_board", forced)
        if hasattr(s.config, "compose_panel_board"):
            monkeypatch.setattr(s.config, "compose_panel_board", forced)


def _unwrapped_forced(s):
    """The currently installed forced composer (set by ``_ForcedProbes``), or None."""
    current = s.composition.compose_panel_board
    return current if hasattr(current, "__panel_original__") else None


def _user_file(tmp_path: Path, monkeypatch, body: str | None = None) -> Path:
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    path = xdg / "agent-harness" / "advisor-boards.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is not None:
        path.write_text(body, encoding="utf-8")
    return path


_CONTEXT_REPOS: dict[int, Path] = {}


def _context(s, tmp_path, monkeypatch, *, user: str | None = None, repo_files=None,
             available=BOARD_VENDORS, policy="bounded", head_files=None, repository_profile=None,
             user_profile=None, task="code-review"):
    """Snapshot + gate-time context over a fixture repository (base = its HEAD)."""
    user_path = _user_file(tmp_path, monkeypatch, user)
    probes = _ForcedProbes(s, monkeypatch, available)
    repo, base = _repo(tmp_path, repo_files, name=f"ctx-{task}")
    head = None
    if head_files is not None:
        _git(repo, "checkout", "-q", "-b", "change")
        head = _commit(repo, head_files, "change")
        _git(repo, "checkout", "-q", "main")
    if callable(repository_profile):  # a profile labelled with the base revision it was read at
        repository_profile = repository_profile(base)
    snap = s.snapshot(user_profile=user_profile)
    ctx = s.build(task, snap, repo_dir=repo, base_revision=base, head_revision=head,
                  monitoring_policy=policy, repository_profile=repository_profile)
    _CONTEXT_REPOS[id(ctx)] = repo
    return types.SimpleNamespace(ctx=ctx, snap=snap, repo=repo, base=base, head=head,
                                 user_path=user_path, probes=probes)


def _legs(board, unusable: Callable[[object], bool] = lambda seat: False) -> list[PanelLegResult]:
    return [
        PanelLegResult(
            leg=str(seat.harness), status="DEGRADED" if unusable(seat) else "OK",
            text="" if unusable(seat) else f"{seat.harness} reviewed\nAGREE", seat_key=seat.seat_key,
        )
        for seat in board.seats
    ]


RULING = PresidentRuling(model="fable", text="FORCING DECISION: LAND", substantive_rounds=1, format_reasks=0)


def _decide(s, ctx, tier, legs, *, president=RULING, digest=None) -> bool:
    policy = s.landing_policy(tier, context=ctx)
    decision = s.evaluate(
        policy,
        usable_legs=tuple(leg for leg in legs if leg.usable),
        president_ruling=president,
        context=ctx,
        user_digest_now=ctx.snapshot.user_digest if digest is None else digest,
    )
    assert isinstance(decision.admitted, bool)
    return decision.admitted


def _ok_spawn(unusable: Iterable[str] = ()):
    unusable = set(unusable)

    def spawn(leg: str, _artifact: str):
        return ("DEGRADED", "") if leg in unusable else ("OK", f"{leg} reviewed\nAGREE")

    return spawn


def _landing_kwargs(ctx, tier) -> dict[str, object]:
    """``landing_tier`` + the context, and the context's own landing policy passed as
    ``review_policy``: the sanctioned hermetic control (``harden_tdd_guard``) requires
    the policy ``invoke_board`` validates to BE a supplied ``review_policy`` (identity) or
    ``review_policy_for_tier(tier)``, so the panel policy is supplied explicitly and
    ``invoke_board`` must validate and evaluate exactly that object."""
    tier_value = getattr(tier, "value", tier)
    kwargs: dict[str, object] = {"landing_tier": tier, "panel_context": ctx}
    if ctx is not None:
        kwargs["review_policy"] = pi.panel_landing_policy(tier_value, context=ctx)
    if tier_value in PRESIDENT_TIERS:
        kwargs["president_invoke"] = deferring_president
    return kwargs


def _invoke(ctx, tier: str | None, *, spawn=None, **extra):
    kwargs: dict[str, object] = {"panel_context": ctx}
    if tier is not None:
        kwargs.update(_landing_kwargs(ctx, tier))
    kwargs.update(extra)
    return invoke_sanctioned_review_transport(ctx.composed.board, "artifact", spawn=spawn or _ok_spawn(), **kwargs)


def _multiset(seats) -> Counter:
    return Counter(json.dumps(seat_record(seat), sort_keys=True) for seat in seats)


def _golden_multiset(board: Mapping) -> Counter:
    return Counter(json.dumps(seat, sort_keys=True) for seat in board["seats"])


# =======================================================================================
# EC-PANEL-1 -- lane tables and lenses
# =======================================================================================

# (id, table body, token the typed reason must name). Each is a malformed or unknown
# ``[panel.*]`` value; every one must be refused with a typed reason, never coerced.
MALFORMED = [
    ("unknown-key", _cr_table(extra="bogus_key = 1"), "bogus_key"),
    ("unknown-task", _panel_toml("no-such-task", [("correctness", BOARD_VENDORS)]), "no-such-task"),
    ("unknown-vendor", _panel_toml("code-review", [("correctness", ("claude", "mistral"))]), "mistral"),
    ("unknown-lens", _panel_toml("code-review", [("no-such-lens", BOARD_VENDORS)]), "no-such-lens"),
    ("lanes-not-a-list", '[panel.code-review]\nlanes = "correctness"\n', "lanes"),
    ("vendors-not-a-list", '[panel.code-review]\nlanes = [{ lens = "correctness", vendors = "claude" }]\n', "vendors"),
    ("vendors-empty", _panel_toml("code-review", [("correctness", ())]), "vendors"),
    ("vendors-duplicate", _panel_toml("code-review", [("correctness", ("claude", "codex", "claude"))]), "vendors"),
    ("lane-missing-vendors", '[panel.code-review]\nlanes = [{ lens = "correctness" }]\n', "vendors"),
    ("lane-unknown-key", '[panel.code-review]\nlanes = [{ lens = "correctness", vendors = ["claude"], weight = 2 }]\n', "weight"),
    ("lens-not-a-string", '[panel.code-review]\nlanes = [{ lens = 7, vendors = ["claude"] }]\n', "lens"),
    ("lens-text-empty", _panel_toml("code-review", [("my-lens", BOARD_VENDORS)], lenses={"my-lens": ""}), "my-lens"),
    ("lane-missing-lens", '[panel.code-review]\nlanes = [{ vendors = ["claude"] }]\n', "lens"),
    ("lens-text-not-a-string",
     '[panel.code-review]\nlanes = [{ lens = "my-lens", vendors = ["claude"] }]\n'
     '[panel.code-review.lenses]\n"my-lens" = 7\n', "my-lens"),
    ("lane-not-a-table", '[panel.code-review]\nlanes = ["correctness"]\n', "lanes"),
    ("lanes-empty", '[panel.code-review]\nlanes = []\n', "lanes"),
    ("lenses-not-a-table", '[panel.code-review]\nlenses = ["x"]\nlanes = [{ lens = "correctness", vendors = ["claude"] }]\n', "lenses"),
]


@pytest.mark.parametrize("case_id,body,token", MALFORMED, ids=[c[0] for c in MALFORMED])
def test_ec1_malformed_or_unknown_user_table_is_refused_with_a_typed_reason(tmp_path, monkeypatch, case_id, body, token):
    s = slice1()
    user = _user_file(tmp_path, monkeypatch, body)
    with pytest.raises(s.BoardConfigError) as excinfo:
        s.resolve("code-review", user_path=user, repo_dir=None, base_revision=None)
    assert token in str(excinfo.value), f"{case_id}: the reason does not name {token!r}: {excinfo.value}"


@pytest.mark.parametrize("case_id,body,token", MALFORMED, ids=[c[0] for c in MALFORMED])
def test_ec1_change_adding_a_malformed_repository_table_is_refused(tmp_path, case_id, body, token):
    s = slice1()
    repo, base = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "change")
    head = _commit(repo, {REPO_REL: body}, "add table")
    with pytest.raises(s.BoardConfigError) as excinfo:
        s.validate(repo, base_revision=base, head_revision=head)
    assert token in str(excinfo.value), f"{case_id}: the reason does not name {token!r}: {excinfo.value}"
    # The same change with a valid table is not refused (the refusal is about validity).
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "valid-change")
    valid = _commit(repo, {REPO_REL: _cr_table()}, "add valid table")
    s.validate(repo, base_revision=base, head_revision=valid)


@pytest.mark.parametrize("source", ["user", "repository"])
def test_ec1_declared_custom_lens_is_accepted_and_composed_as_declared(tmp_path, monkeypatch, source):
    s = slice1()
    body = _panel_toml(
        "code-review",
        [("supply-chain", BOARD_VENDORS), ("correctness", BOARD_VENDORS)],
        lenses={"supply-chain": "Check every new dependency's provenance and pinning."},
    )
    user = _user_file(tmp_path, monkeypatch, body if source == "user" else None)
    repo, base = _repo(tmp_path, {REPO_REL: body} if source == "repository" else None)
    resolved = s.resolve("code-review", user_path=user, repo_dir=repo, base_revision=base)
    assert [lane.lens for lane in resolved.table.lanes] == ["supply-chain", "correctness"]
    composed = s.compose(resolved.table, **_probes())
    lenses = {lens.name: lens for lens in composed.seat_lenses.values()}
    assert lenses["supply-chain"].kind == "declared"
    assert lenses["supply-chain"].text == "Check every new dependency's provenance and pinning."
    assert lenses["correctness"].kind == "built-in"
    assert lenses["correctness"].text == s.lens_text["correctness"]


@pytest.mark.parametrize("source", ["user", "repository-change"])
def test_ec1_declared_lens_reusing_a_builtin_name_is_refused(tmp_path, monkeypatch, source):
    s = slice1()
    body = _panel_toml("code-review", [("correctness", BOARD_VENDORS)], lenses={"correctness": "My own text."})
    if source == "user":
        user = _user_file(tmp_path, monkeypatch, body)
        with pytest.raises(s.BoardConfigError) as excinfo:
            s.resolve("code-review", user_path=user, repo_dir=None, base_revision=None)
    else:
        repo, base = _repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "change")
        head = _commit(repo, {REPO_REL: body}, "reuse")
        with pytest.raises(s.BoardConfigError) as excinfo:
            s.validate(repo, base_revision=base, head_revision=head)
    assert "correctness" in str(excinfo.value)


def test_ec1_builtin_lens_names_include_todays_code_review_lenses():
    s = slice1()
    for lens in CR_LENSES:
        assert s.lens_text.get(lens), f"built-in lens {lens!r} has no text"


def test_ec1_landing_is_refused_when_the_user_file_changed_during_the_run(tmp_path, monkeypatch):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=USER_BODY)
    assert c.snap.user_digest == _sha256(c.user_path), "the run-start digest is the whole user file's sha256"
    legs = _legs(c.ctx.composed.board)
    assert _decide(s, c.ctx, "plan", legs) is True  # control: unchanged file lands
    c.user_path.write_text(USER_BODY + "# edited mid-run\n", encoding="utf-8")
    assert _decide(s, c.ctx, "plan", legs, digest=_sha256(c.user_path)) is False


def test_ec1_repository_table_is_read_at_the_given_base_revision_only(tmp_path, monkeypatch):
    s = slice1()
    user = _user_file(tmp_path, monkeypatch)
    repo, base = _repo(tmp_path, {REPO_REL: _cr_table(minimum=1)})
    _git(repo, "checkout", "-q", "-b", "change")
    head = _commit(repo, {REPO_REL: _cr_table(minimum=2)}, "edit in the change")
    (repo / REPO_REL).write_text(_cr_table(minimum=3), encoding="utf-8")  # uncommitted working tree
    at_base = s.resolve("code-review", user_path=user, repo_dir=repo, base_revision=base)
    at_head = s.resolve("code-review", user_path=user, repo_dir=repo, base_revision=head)
    assert at_base.table.min_distinct_vendors == 1
    assert at_head.table.min_distinct_vendors == 2
    assert base in str(at_base.provenance) and head in str(at_head.provenance)


def test_ec1_loader_reads_only_panel_tables_from_the_repository_file(tmp_path, monkeypatch):
    s = slice1()
    user = _user_file(tmp_path, monkeypatch)
    # Keys outside [panel.*] -- even ones another loader would refuse -- are not PANEL's.
    body = (
        '[president]\nladder = ["nobody"]\n'
        '[[boards]]\nname = "x"\n'
        '[unrelated]\nanything = true\n'
        + _cr_table(minimum=2)
    )
    repo, base = _repo(tmp_path, {REPO_REL: body})
    resolved = s.resolve("code-review", user_path=user, repo_dir=repo, base_revision=base)
    assert resolved.table.min_distinct_vendors == 2
    # A user file's non-panel keys are likewise not refused by PANEL's loader.
    user.write_text('default_board = "code-review"\n' + USER_BODY + _cr_table(minimum=3), encoding="utf-8")
    assert s.resolve("code-review", user_path=user, repo_dir=None, base_revision=None).table.min_distinct_vendors == 3


def test_ec1_existing_loaders_tolerate_a_sibling_panel_table(tmp_path, monkeypatch):
    s = slice1()
    from phase_loop_runtime.advisor_board.config import load_boards, load_president_ladder

    user = _user_file(tmp_path, monkeypatch, USER_BODY + _cr_table(minimum=2))
    load_boards(user, validate=False, is_available=lambda _v: True, auth_ok=lambda _v: True)
    repo, _base = _repo(tmp_path, {REPO_REL: '[president]\nladder = ["sol"]\n' + _cr_table(minimum=2)})
    assert load_president_ladder(repo, path=user) == ("sol",)
    assert s.resolve("code-review", user_path=user, repo_dir=None, base_revision=None).table.min_distinct_vendors == 2


def test_ec1_target_head_panel_change_requires_a_regate(tmp_path):
    s = slice1()
    repo, gated = _repo(tmp_path, {REPO_REL: USER_BODY + _cr_table(minimum=1)})
    assert s.regate(repo, gated_revision=gated, target_head=gated) is False
    unrelated = _commit(repo, {"README.md": "changed\n"}, "unrelated")
    assert s.regate(repo, gated_revision=gated, target_head=unrelated) is False
    president_only = _commit(repo, {REPO_REL: '[president]\nladder = ["sol"]\n' + _cr_table(minimum=1)}, "president")
    assert s.regate(repo, gated_revision=gated, target_head=president_only) is False
    panel = _commit(repo, {REPO_REL: '[president]\nladder = ["sol"]\n' + _cr_table(minimum=2)}, "panel")
    assert s.regate(repo, gated_revision=president_only, target_head=panel) is True
    assert s.regate(repo, gated_revision=gated, target_head=panel) is True
    profile = _commit(repo, {GOVERNANCE_REL: '[tiers.plan]\npanel = ["fable", "sol", "gemini", "grok"]\n'}, "profile")
    assert s.regate(repo, gated_revision=panel, target_head=profile) is True
    profile2 = _commit(repo, {GOVERNANCE_REL: '[tiers.plan]\npanel = ["fable", "sol", "gemini", "grok", "fable"]\n'}, "profile 2")
    assert s.regate(repo, gated_revision=profile, target_head=profile2) is True


def _divergent_table(*, supply_lane: bool, declared: bool, minimum: int | None = None) -> str:
    """A code-review table laid out so each divergent edit touches its own, separated hunk."""
    vendors = json.dumps(list(BOARD_VENDORS))
    lines = ["[panel.code-review]"]
    lines += ["# minimum"] + ([f"min_distinct_vendors = {minimum}"] if minimum is not None else []) + ["#", "#"]
    lines += ["lanes = [", f'  {{ lens = "correctness", vendors = {vendors} }},']
    if supply_lane:
        lines.append(f'  {{ lens = "supply-chain", vendors = {vendors} }},')
    lines += ["]", "#", "#", "#"]
    if declared:
        lines += ["[panel.code-review.lenses]", '"supply-chain" = "Check dependency provenance."']
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("variant", ["removes-the-declaration", "control-raises-the-minimum"])
def test_ec1_a_change_is_validated_as_applied_onto_a_divergent_target_head(tmp_path, variant):
    """EC-PANEL-1 "valid once applied onto the target head": the common base declares an
    unused custom lens; the TARGET then adds a lane using it; the change (branched from the
    common base, not from the target) removes the declaration. Each tip is valid alone, the
    combination is not -> refused. The control change edits only the minimum -> accepted."""
    s = slice1()
    repo, _common = _repo(tmp_path, {REPO_REL: _divergent_table(supply_lane=False, declared=True)})
    _git(repo, "checkout", "-q", "-b", "change")
    if variant == "removes-the-declaration":
        head = _commit(repo, {REPO_REL: _divergent_table(supply_lane=False, declared=False)}, "drop unused lens")
    else:
        head = _commit(repo, {REPO_REL: _divergent_table(supply_lane=False, declared=True, minimum=2)}, "minimum")
    _git(repo, "checkout", "-q", "main")
    target = _commit(repo, {REPO_REL: _divergent_table(supply_lane=True, declared=True)}, "use the lens")
    for tip in (target, head):  # each tip is valid on its own
        resolved = s.resolve("code-review", user_path=None, repo_dir=repo, base_revision=tip)
        assert REPLACED_LABEL not in str(resolved.source), f"tip {tip} is not valid alone"
    if variant == "removes-the-declaration":
        with pytest.raises(s.BoardConfigError) as excinfo:
            s.validate(repo, base_revision=target, head_revision=head)
        assert "supply-chain" in str(excinfo.value)
    else:
        s.validate(repo, base_revision=target, head_revision=head)


def test_ec1_invalid_change_refused_and_valid_repair_of_an_invalid_base_accepted(tmp_path):
    s = slice1()
    repo, valid_base = _repo(tmp_path, {REPO_REL: _cr_table(minimum=2)})
    _git(repo, "checkout", "-q", "-b", "edit")
    bad_edit = _commit(repo, {REPO_REL: _cr_table(("claude", "mistral"))}, "bad edit")
    with pytest.raises(s.BoardConfigError):
        s.validate(repo, base_revision=valid_base, head_revision=bad_edit)
    _git(repo, "checkout", "-q", "main")
    invalid_base = _commit(repo, {REPO_REL: _cr_table(extra="bogus_key = 1")}, "base goes invalid")
    _git(repo, "checkout", "-q", "-b", "repair")
    repair = _commit(repo, {REPO_REL: _cr_table(minimum=2)}, "repair")
    s.validate(repo, base_revision=invalid_base, head_revision=repair)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "code-only")
    code_only = _commit(repo, {"src.py": "x = 1\n"}, "code only")
    s.validate(repo, base_revision=invalid_base, head_revision=code_only)


INVALID_BASES = [
    ("parse-error", "[panel.code-review\nlanes = \n"),
    ("unknown-key", _cr_table(extra="bogus_key = 1")),
    ("unknown-vendor", _cr_table(("claude", "mistral"))),
]


@pytest.mark.parametrize("case_id,body", INVALID_BASES, ids=[c[0] for c in INVALID_BASES])
def test_ec1_invalid_base_table_is_replaced_by_its_builtin_and_labelled(tmp_path, monkeypatch, case_id, body):
    s = slice1()
    user = _user_file(tmp_path, monkeypatch)
    builtin = s.resolve("code-review", user_path=None, repo_dir=None, base_revision=None)
    repo, base = _repo(tmp_path, {REPO_REL: body})
    resolved = s.resolve("code-review", user_path=user, repo_dir=repo, base_revision=base)
    assert resolved.table == builtin.table, case_id
    assert REPLACED_LABEL in str(resolved.source)
    # Its invalidity does not block a landing the built-in table admits.
    c = _context(s, tmp_path / "ctx", monkeypatch, repo_files={REPO_REL: body})
    assert REPLACED_LABEL in str(c.ctx.resolved_table.source)
    assert _decide(s, c.ctx, "plan", _legs(c.ctx.composed.board)) is True


def test_ec1_a_repository_table_omitting_the_minimum_replaces_a_lowering_user_table(tmp_path, monkeypatch):
    """Table-by-table precedence replaces the WHOLE table: a repository code-review table
    without ``min_distinct_vendors`` does not inherit the user table's lowered minimum."""
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=1),
                 repo_files={REPO_REL: _rotated_cr_table()}, available=("claude",))
    assert c.ctx.resolved_table.table.min_distinct_vendors is None
    assert "repository" in str(c.ctx.resolved_table.source)
    assert s.landing_policy("plan", context=c.ctx).min_distinct_vendors is None
    assert _decide(s, c.ctx, "plan", _legs(c.ctx.composed.board)) is False


@pytest.mark.parametrize("case_id,body", INVALID_BASES, ids=[c[0] for c in INVALID_BASES])
def test_ec1_an_invalid_base_table_is_not_replaced_by_a_lowering_user_table(tmp_path, monkeypatch, case_id, body):
    """An invalid base table is replaced by its BUILT-IN table (the strictest), never by the
    user table below it: with a user minimum of 1 and one vendor up, the landing is refused."""
    s = slice1()
    builtin = s.resolve("code-review", user_path=None, repo_dir=None, base_revision=None)
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=1),
                 repo_files={REPO_REL: body}, available=("claude",))
    assert c.ctx.resolved_table.table == builtin.table, case_id
    assert REPLACED_LABEL in str(c.ctx.resolved_table.source)
    assert s.landing_policy("plan", context=c.ctx).min_distinct_vendors is None
    assert _decide(s, c.ctx, "plan", _legs(c.ctx.composed.board)) is False


def test_ec1_an_invalid_base_table_labels_replaced_sources_for_table_and_minimum(tmp_path, monkeypatch):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=1),
                 repo_files={REPO_REL: _cr_table(extra="bogus_key = 1")})
    labels = _labels(_invoke(c.ctx, "plan").panel_labels)
    assert REPLACED_LABEL in json.dumps(labels["table_source"])
    assert labels["effective_minimum"] == 4
    assert labels["minimum_source"]["kind"] == "built-in"


def test_ec1_a_change_repairing_an_invalid_base_does_not_govern_itself(tmp_path, monkeypatch):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=1),
                 repo_files={REPO_REL: _cr_table(extra="bogus_key = 1")},
                 head_files={REPO_REL: _rotated_cr_table(minimum=1)}, available=("claude",))
    assert c.ctx.gated_revision == c.base
    assert REPLACED_LABEL in str(c.ctx.resolved_table.source)
    assert c.ctx.resolved_table.table == s.resolve("code-review", user_path=None, repo_dir=None,
                                                    base_revision=None).table
    assert _decide(s, c.ctx, "plan", _legs(c.ctx.composed.board)) is False


def test_ec1_unreadable_base_revision_fails_closed(tmp_path, monkeypatch):
    s = slice1()
    user = _user_file(tmp_path, monkeypatch)
    repo, _base = _repo(tmp_path, {REPO_REL: _cr_table(minimum=2)})
    with pytest.raises(s.BoardConfigError):
        s.resolve("code-review", user_path=user, repo_dir=repo, base_revision="0" * 40)
    with pytest.raises(s.BoardConfigError):
        s.resolve("code-review", user_path=user, repo_dir=tmp_path / "not-a-repo", base_revision="HEAD")


def _preset_names() -> list[str]:
    from phase_loop_runtime.advisor_board.presets import PRESET_NAMES

    return list(PRESET_NAMES)


@pytest.mark.parametrize("task", _preset_names())
def test_ec1_every_builtin_task_has_a_table_composing_todays_seats(task):
    s = slice1()
    golden = load_golden()
    resolved = s.resolve(task, user_path=None, repo_dir=None, base_revision=None)
    composed = s.compose(resolved.table, **_probes())
    # For code review, "today" is the landing path's DEFAULT_BOARD (EC-PANEL-1).
    expected = golden["import_time"]["fixtures.DEFAULT_BOARD"] if task == "code-review" else golden["preset_tasks"][task]
    assert _multiset(composed.board.seats) == _golden_multiset(expected)
    assert not list(composed.unfilled_lanes) and not list(composed.fallback_lanes)


def test_ec1_import_time_snapshots_equal_the_base_golden():
    slice1()
    golden = load_golden()["import_time"]
    from phase_loop_runtime.advisor_board import resolver
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from phase_loop_runtime.advisor_board.presets import CODE_REVIEW_BOARD

    assert board_record(CODE_REVIEW_BOARD) == golden["presets.CODE_REVIEW_BOARD"]
    assert board_record(resolver._STANDIN_CODE_REVIEW) == golden["resolver._STANDIN_CODE_REVIEW"]
    assert board_record(DEFAULT_BOARD) == golden["fixtures.DEFAULT_BOARD"]


def test_ec1_precedence_is_builtin_then_user_then_repository_table_by_table(tmp_path, monkeypatch):
    s = slice1()
    user = _user_file(
        tmp_path, monkeypatch,
        _cr_table(minimum=2) + _panel_toml("brainstorm", [("adversarial", ("claude", "codex"))]),
    )
    repo, base = _repo(tmp_path, {REPO_REL: _cr_table(minimum=3)})
    cr = s.resolve("code-review", user_path=user, repo_dir=repo, base_revision=base)
    assert cr.table.min_distinct_vendors == 3 and "repository" in str(cr.source)
    brainstorm = s.resolve("brainstorm", user_path=user, repo_dir=repo, base_revision=base)
    assert [(lane.lens, tuple(lane.vendors)) for lane in brainstorm.table.lanes] == [("adversarial", ("claude", "codex"))]
    assert "user" in str(brainstorm.source)
    user_only = s.resolve("code-review", user_path=user, repo_dir=None, base_revision=None)
    assert user_only.table.min_distinct_vendors == 2 and "user" in str(user_only.source)
    doc_edit = s.resolve("doc-edit", user_path=user, repo_dir=repo, base_revision=base)
    assert doc_edit.table == s.resolve("doc-edit", user_path=None, repo_dir=None, base_revision=None).table
    assert "built-in" in str(doc_edit.source)


def test_ec1_a_change_editing_the_repository_table_is_not_governed_by_its_own_edit(tmp_path, monkeypatch):
    s = slice1()
    c = _context(
        s, tmp_path, monkeypatch, repo_files={REPO_REL: _cr_table(minimum=3)},
        head_files={REPO_REL: _cr_table(minimum=1)}, available=("claude",),
    )
    assert c.ctx.resolved_table.table.min_distinct_vendors == 3
    assert c.ctx.gated_revision == c.base
    assert _decide(s, c.ctx, "plan", _legs(c.ctx.composed.board)) is False


# =======================================================================================
# EC-PANEL-2 -- lane fallback for any subset of vendors
# =======================================================================================

STATES = ("ok", "unavailable", "unauthed", "preflight")


def _state_matrix():
    for a in STATES:
        for b in STATES:
            for c in STATES:
                for d in STATES:
                    yield dict(zip(BOARD_VENDORS, (a, b, c, d)))


def _check_composition(s, table, states: Mapping[str, str]) -> None:
    composed = s.compose(
        table,
        is_available=lambda v: states.get(v, "ok") != "unavailable",
        auth_ok=lambda v: states.get(v, "ok") != "unauthed",
        preflight=lambda v: states.get(v, "ok") != "preflight",
    )
    lanes = list(table.lanes)
    seats_by_lens: dict[str, list] = {}
    for seat in composed.board.seats:
        seats_by_lens.setdefault(str(seat.lens), []).append(seat)
    lane_lenses = {lane.lens for lane in lanes}
    assert set(seats_by_lens) <= lane_lenses, f"a seat carries a lens outside the lanes: {set(seats_by_lens) - lane_lenses}"
    expected_unfilled, expected_fallback = [], []
    for lane in lanes:
        eligible = [v for v in lane.vendors if states.get(v, "ok") == "ok"]
        seated = seats_by_lens.get(lane.lens, [])
        if not eligible:
            assert not seated, f"lane {lane.lens} seated {seated} though no listed vendor is eligible ({states})"
            expected_unfilled.append(lane.lens)
            continue
        assert len(seated) == 1, f"lane {lane.lens} seated {len(seated)} seats ({states})"
        assert seated[0].vendor_family == eligible[0], (
            f"lane {lane.lens} seated {seated[0].vendor_family}, first eligible is {eligible[0]} ({states})"
        )
        assert composed.seat_lenses[seated[0].seat_key].name == lane.lens
        if eligible[0] != lane.vendors[0]:
            expected_fallback.append(lane.lens)
    assert _lane_names(composed.unfilled_lanes) == sorted(expected_unfilled), states
    assert _lane_names(composed.fallback_lanes) == sorted(expected_fallback), states
    assert set(composed.seat_lenses) == {seat.seat_key for seat in composed.board.seats}


@pytest.mark.parametrize("task", _preset_names())
def test_ec2_builtin_lane_seats_first_eligible_vendor_across_the_matrix(task):
    s = slice1()
    table = s.resolve(task, user_path=None, repo_dir=None, base_revision=None).table
    for states in _state_matrix():
        _check_composition(s, table, states)


def test_ec2_configured_lanes_seat_first_eligible_vendor_and_record_unfilled(tmp_path, monkeypatch):
    s = slice1()
    body = _panel_toml(
        "code-review",
        [
            ("correctness", ("codex", "claude")),
            ("adversarial", ("grok",)),
            ("supply-chain", ("gemini", "grok", "codex")),
        ],
        lenses={"supply-chain": "Check dependency provenance."},
    )
    user = _user_file(tmp_path, monkeypatch, body)
    table = s.resolve("code-review", user_path=user, repo_dir=None, base_revision=None).table
    for states in _state_matrix():
        _check_composition(s, table, states)


@pytest.mark.parametrize("task", _preset_names())
def test_ec2_every_builtin_lane_lists_every_board_vendor(task):
    s = slice1()
    table = s.resolve(task, user_path=None, repo_dir=None, base_revision=None).table
    assert table.lanes, f"built-in task {task} has no lanes"
    for lane in table.lanes:
        assert sorted(lane.vendors) == sorted(BOARD_VENDORS), (task, lane.lens, lane.vendors)


@pytest.mark.parametrize("vendor", BOARD_VENDORS)
@pytest.mark.parametrize("task", _preset_names())
def test_ec2_any_single_eligible_vendor_fills_every_builtin_lane(task, vendor):
    s = slice1()
    table = s.resolve(task, user_path=None, repo_dir=None, base_revision=None).table
    composed = s.compose(table, **_probes((vendor,)))
    assert not list(composed.unfilled_lanes), (task, vendor, composed.unfilled_lanes)
    assert len(composed.board.seats) == len(table.lanes)
    assert {seat.vendor_family for seat in composed.board.seats} == {vendor}


# =======================================================================================
# EC-PANEL-3 -- one composition for every monitoring policy
# =======================================================================================


def test_ec3_heartbeat_only_composes_through_the_lane_fallback(tmp_path, monkeypatch):
    s = slice1()
    available = ("claude", "codex", "gemini")  # grok down
    c = _context(s, tmp_path, monkeypatch, available=available, policy="heartbeat_only")
    board = c.ctx.composed.board
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    assert board != DEFAULT_BOARD, "heartbeat_only still seats the frozen default board"
    assert {seat.vendor_family for seat in board.seats} <= set(available)
    assert not list(c.ctx.composed.unfilled_lanes), "a listed fallback vendor could fill every lane"
    assert sorted(str(seat.lens) for seat in board.seats) == sorted(CR_LENSES)
    assert "adversarial" in _lane_names(c.ctx.composed.fallback_lanes)


@pytest.mark.parametrize("hosts", ["all-hosts-ok", "grok-cli-missing-codex-unauthed"])
@pytest.mark.parametrize("agy_capable", [False, True], ids=["agy-incapable", "agy-capable"])
@pytest.mark.parametrize("policy", ["bounded", "heartbeat_only"])
def test_ec3_the_builder_applies_its_own_probes_per_policy(tmp_path, monkeypatch, policy, agy_capable, hosts):
    """No ``_ForcedProbes``: ``build_panel_context`` composes with its OWN availability, auth
    and route-preflight probes. Only the lowest host leaves are faked:

    * CLI presence -- ``DEFAULT_HARNESS_REGISTRY.probe`` (``[grok-cli-missing-…]``: grok's CLI
      is absent);
    * auth -- ``executor_availability._probes_pass`` (``[…-codex-unauthed]``: codex fails);
    * the agy capability -- ``gemini_heartbeat.require_capability``.

    Under BOTH policies every lane is seated by the first listed vendor that is present,
    authenticated and (under ``heartbeat_only`` only) route-preflight capable; a lane
    whose first vendor is not eligible falls back to the next eligible one."""
    s = slice1()
    from phase_loop_runtime import executor_availability, gemini_heartbeat
    from phase_loop_runtime.advisor_board import registries

    missing_cli = {"grok"} if hosts != "all-hosts-ok" else set()
    unauthed = {"codex"} if hosts != "all-hosts-ok" else set()
    clis = {registries.DEFAULT_HARNESS_REGISTRY.get(v).cli: v for v in BOARD_VENDORS}

    def capability(env):
        if not agy_capable:
            raise ValueError("gemini_heartbeat_capability_unavailable")
        return Path("/usr/bin/agy")

    monkeypatch.setattr(registries.DEFAULT_HARNESS_REGISTRY, "probe", lambda cli: clis.get(cli) not in missing_cli)
    monkeypatch.setattr(executor_availability, "_probes_pass",
                        lambda executor, *a, **k: executor not in unauthed)
    executor_availability.clear_auth_cache()
    monkeypatch.setattr(gemini_heartbeat, "require_capability", capability)
    _user_file(tmp_path, monkeypatch)
    repo, base = _repo(tmp_path)
    try:
        ctx = s.build("code-review", s.snapshot(), repo_dir=repo, base_revision=base, head_revision=None,
                      monitoring_policy=policy)
    finally:
        executor_availability.clear_auth_cache()
    down = missing_cli | unauthed
    if policy == "heartbeat_only" and not agy_capable:
        down = down | {"gemini"}
    seated = {str(seat.lens): seat.vendor_family for seat in ctx.composed.board.seats}
    expected_fallback = []
    for lane in ctx.resolved_table.table.lanes:
        eligible = [v for v in lane.vendors if v not in down]
        assert seated.get(lane.lens) == eligible[0], (policy, hosts, lane.lens, seated.get(lane.lens), eligible)
        if eligible[0] != lane.vendors[0]:
            expected_fallback.append(lane.lens)
    assert _lane_names(ctx.composed.fallback_lanes) == sorted(expected_fallback)
    assert not list(ctx.composed.unfilled_lanes)
    assert not ({seat.vendor_family for seat in ctx.composed.board.seats} & down)
    # Independent of the object under test: the built-in code-review lanes are today's four.
    assert sorted(str(seat.lens) for seat in ctx.composed.board.seats) == sorted(CR_LENSES)


@pytest.mark.parametrize("available", [BOARD_VENDORS, ("claude",), ("codex", "gemini")], ids=["all", "claude", "codex-gemini"])
def test_ec3_bounded_and_heartbeat_only_compose_the_same_board(tmp_path, monkeypatch, available):
    s = slice1()
    bounded = _context(s, tmp_path / "b", monkeypatch, available=available, policy="bounded")
    heartbeat = _context(s, tmp_path / "h", monkeypatch, available=available, policy="heartbeat_only")
    assert [seat_record(x) for x in bounded.ctx.composed.board.seats] == [
        seat_record(x) for x in heartbeat.ctx.composed.board.seats
    ]


# =======================================================================================
# EC-PANEL-4 -- the landing minimum
# =======================================================================================

ALL_TIERS = ("plan", "production_code", "tests_only", "docs_only")


@pytest.mark.parametrize("tier", ALL_TIERS)
def test_ec4_no_config_landing_policy_is_todays_for_every_tier(tmp_path, monkeypatch, tier):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch)
    policy = s.landing_policy(tier, context=c.ctx)
    today = pi.review_policy_for_tier(tier)
    assert policy.required_seats == today.required_seats
    assert policy.requires_president == today.requires_president
    assert policy.min_distinct_vendors is None
    assert policy.min_usable_seats == (2 if tier in PRESIDENT_TIERS else 0)
    # The dataclass defaults keep today's rule wherever the seam is not used.
    assert today.min_distinct_vendors is None and today.min_usable_seats == 0


@pytest.mark.parametrize("minimum", [1, 2, 3, 4])
@pytest.mark.parametrize("vendors", [1, 2, 3, 4])
@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_configured_minimum_admits_exactly_at_or_above_it(tmp_path, monkeypatch, tier, vendors, minimum):
    s = slice1()
    available = BOARD_VENDORS[:vendors]
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=minimum), available=available)
    policy = s.landing_policy(tier, context=c.ctx)
    assert policy.min_distinct_vendors == minimum and policy.min_usable_seats == 2
    board = c.ctx.composed.board
    assert len(board.seats) >= 2 and {seat.vendor_family for seat in board.seats} == set(available)
    assert _decide(s, c.ctx, tier, _legs(board)) is (vendors >= minimum)


@pytest.mark.parametrize("minimum", [1, 2, 3, 4])
@pytest.mark.parametrize("vendors", [1, 2, 3, 4])
def test_ec4_invoke_board_enforces_the_configured_minimum(tmp_path, monkeypatch, vendors, minimum):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=minimum), available=BOARD_VENDORS[:vendors])
    result = _invoke(c.ctx, "plan")
    labels = _labels(result.panel_labels)
    assert labels["effective_minimum"] == minimum
    assert labels["usable_distinct_vendors"] == vendors
    assert labels["minimum_met"] is (vendors >= minimum)
    assert result.landing_decision.admitted is (vendors >= minimum)


@pytest.mark.parametrize("minimum", [1, 2])
def test_ec4_fewer_than_two_usable_seats_or_no_president_is_refused(tmp_path, monkeypatch, minimum):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=minimum), available=("claude", "codex"))
    board = c.ctx.composed.board
    first = board.seats[0].seat_key
    two_vendors = {board.seats[0].seat_key}
    two_vendors.add(next(seat.seat_key for seat in board.seats if seat.vendor_family != board.seats[0].vendor_family))
    assert _decide(s, c.ctx, "plan", _legs(board, lambda seat: seat.seat_key not in two_vendors)) is True
    assert _decide(s, c.ctx, "plan", _legs(board, lambda seat: seat.seat_key != first)) is False
    assert _decide(s, c.ctx, "plan", _legs(board), president=None) is False


def _other_tasks() -> list[str]:
    return [task for task in _preset_names() if task != "code-review"]


@pytest.mark.parametrize("task", _other_tasks())
def test_ec4_minimum_is_refused_outside_the_code_review_table(tmp_path, monkeypatch, task):
    s = slice1()
    body = _panel_toml(task, [("adversarial", BOARD_VENDORS)], minimum=1)
    user = _user_file(tmp_path, monkeypatch, body)
    with pytest.raises(s.BoardConfigError) as excinfo:
        s.resolve(task, user_path=user, repo_dir=None, base_revision=None)
    assert "min_distinct_vendors" in str(excinfo.value)
    repo, base = _repo(tmp_path / "r")
    _git(repo, "checkout", "-q", "-b", "change")
    head = _commit(repo, {REPO_REL: body}, "minimum outside code-review")
    with pytest.raises(s.BoardConfigError) as excinfo:
        s.validate(repo, base_revision=base, head_revision=head)
    assert "min_distinct_vendors" in str(excinfo.value)


BAD_MINIMA = [("zero", "0"), ("five", "5"), ("negative", "-1"), ("float", "2.5"), ("bool", "true"), ("string", '"2"')]


@pytest.mark.parametrize("case_id,raw", BAD_MINIMA, ids=[c[0] for c in BAD_MINIMA])
def test_ec4_minimum_must_be_an_integer_from_one_to_the_vendor_count(tmp_path, monkeypatch, case_id, raw):
    s = slice1()
    user = _user_file(tmp_path, monkeypatch, _cr_table(minimum=raw))
    with pytest.raises(s.BoardConfigError) as excinfo:
        s.resolve("code-review", user_path=user, repo_dir=None, base_revision=None)
    assert "min_distinct_vendors" in str(excinfo.value), case_id
    repo, base = _repo(tmp_path / "r")
    _git(repo, "checkout", "-q", "-b", "change")
    head = _commit(repo, {REPO_REL: _cr_table(minimum=raw)}, "bad minimum")
    with pytest.raises(s.BoardConfigError):
        s.validate(repo, base_revision=base, head_revision=head)


@pytest.mark.parametrize("via", ["repository_profile", "user_profile"])
def test_ec4_a_governance_profile_cannot_lower_the_minimum(tmp_path, monkeypatch, via):
    s = slice1()
    profile = s.ExplicitProfileSeats(seats=("fable",), path=".phase-loop/governance.toml", provenance="base")
    kwargs = {via: profile}
    c = _context(s, tmp_path, monkeypatch, available=("claude",), **kwargs)
    # No [panel.*] minimum anywhere: the landing is today's four named seats, whatever
    # the profile names. A one-vendor Claude board is refused.
    assert _decide(s, c.ctx, "plan", _legs(c.ctx.composed.board)) is False
    assert s.landing_policy("plan", context=c.ctx).min_distinct_vendors is None


@pytest.mark.parametrize("source", ["user", "repository"])
def test_ec4_configured_table_without_a_minimum_keeps_todays_rule_and_is_labelled_builtin(tmp_path, monkeypatch, source):
    s = slice1()
    body = _rotated_cr_table()  # a configured code-review table that omits min_distinct_vendors
    c = _context(s, tmp_path, monkeypatch, user=body if source == "user" else USER_BODY,
                 repo_files={REPO_REL: body} if source == "repository" else None)
    assert c.ctx.resolved_table.table.min_distinct_vendors is None
    policy = s.landing_policy("plan", context=c.ctx)
    assert policy.min_distinct_vendors is None
    assert policy.required_seats == pi.review_policy_for_tier("plan").required_seats
    board = c.ctx.composed.board
    two = {seat.seat_key for seat in board.seats[:2]}
    assert _decide(s, c.ctx, "plan", _legs(board, lambda seat: seat.seat_key not in two)) is True
    result = _invoke(c.ctx, "plan", spawn=_ok_spawn({"grok", "gemini"}))
    assert result.landing_decision.admitted is True
    labels = _labels(result.panel_labels)
    assert labels["effective_minimum"] == 4
    assert labels["minimum_source"]["kind"] == "built-in"
    table_source = labels["table_source"]
    assert table_source["kind"] == source
    if source == "user":
        assert table_source["digest"] == _sha256(c.user_path)
    else:
        assert table_source["base_revision"] == c.base


@pytest.mark.parametrize("config", ["minimum-1", "no-config"])
@pytest.mark.parametrize("via", ["repository_profile", "user_profile"])
def test_ec4_every_seat_an_explicit_profile_names_is_required(tmp_path, monkeypatch, via, config):
    s = slice1()
    profile = s.ExplicitProfileSeats(seats=("grok",), path=".phase-loop/governance.toml", provenance="base")
    user = _rotated_cr_table(minimum=1) if config == "minimum-1" else None
    c = _context(s, tmp_path, monkeypatch, user=user, available=BOARD_VENDORS, **{via: profile})
    assert c.ctx.explicit_profile is not None and tuple(c.ctx.explicit_profile.seats) == ("grok",)
    board = c.ctx.composed.board
    assert _decide(s, c.ctx, "plan", _legs(board)) is True
    assert _decide(s, c.ctx, "plan", _legs(board, lambda seat: seat.vendor_family == "grok")) is False


def test_ec4_repository_profile_takes_precedence_over_the_user_profile(tmp_path, monkeypatch):
    s = slice1()
    user_profile = s.ExplicitProfileSeats(seats=("gemini",), path="user/governance.toml", provenance="digest")
    repo_profile = s.ExplicitProfileSeats(seats=("grok",), path=".phase-loop/governance.toml", provenance="base")
    c = _context(s, tmp_path, monkeypatch, user=_cr_table(minimum=1),
                 repository_profile=repo_profile, user_profile=user_profile)
    assert tuple(c.ctx.explicit_profile.seats) == ("grok",)


def test_ec4_no_config_fallback_seat_never_satisfies_a_named_seat(tmp_path, monkeypatch):
    s = slice1()
    full = _context(s, tmp_path / "full", monkeypatch)
    assert _decide(s, full.ctx, "plan", _legs(full.ctx.composed.board)) is True
    degraded = _context(s, tmp_path / "degraded", monkeypatch, available=("claude", "codex", "gemini"))
    assert "adversarial" in _lane_names(degraded.ctx.composed.fallback_lanes)
    assert _decide(s, degraded.ctx, "plan", _legs(degraded.ctx.composed.board)) is False


@pytest.mark.parametrize("scenario,expected", [
    ("four-named-all-usable", True),
    ("four-named-two-usable", True),
    ("four-named-one-usable", False),
    ("four-named-no-president", False),
])
def test_ec4_no_config_outcome_is_todays_plus_the_floor(tmp_path, monkeypatch, scenario, expected):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch)
    board = c.ctx.composed.board
    keep = {
        "four-named-all-usable": len(board.seats),
        "four-named-two-usable": 2,
        "four-named-one-usable": 1,
        "four-named-no-president": len(board.seats),
    }[scenario]
    usable = {seat.seat_key for seat in board.seats[:keep]}
    president = None if scenario == "four-named-no-president" else RULING
    assert _decide(s, c.ctx, "production_code", _legs(board, lambda seat: seat.seat_key not in usable),
                   president=president) is expected


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_a_president_tier_landing_without_a_context_is_refused(tmp_path, monkeypatch, tier):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch)
    assert _invoke(c.ctx, tier).landing_decision.admitted is True  # control
    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_sanctioned_review_transport(
            c.ctx.composed.board, "artifact", spawn=_ok_spawn(), landing_tier=tier,
            president_invoke=deferring_president,
        )
    assert excinfo.value.code == "panel_context_required"


def _no_ruling_president(model: str, prompt: str):
    """A president that never rules: every rung reports itself unavailable."""
    return {"status": "unavailable", "code": "president_unavailable"}


def _not_admitted(run) -> bool:
    """True when ``invoke_board`` refused the landing -- a typed refusal or a result whose
    landing decision is not admitted."""
    try:
        result = run()
    except PresidentPolicyError:
        return True
    return result.landing_decision.admitted is False


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_invoke_board_refuses_one_usable_seat_on_a_configured_minimum_of_one(tmp_path, monkeypatch, tier):
    """The two-usable-seat floor at the LANDING PATH, not only in ``evaluate_landing``:
    claude fills one lane, grok three; every grok seat is unusable -> one usable seat."""
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=1), available=("grok", "claude"))
    assert _invoke(c.ctx, tier).landing_decision.admitted is True  # control: all four usable
    result = _invoke(c.ctx, tier, spawn=_ok_spawn({"grok"}))
    labels = _labels(result.panel_labels)
    assert labels["usable_seats"] == 1
    assert result.landing_decision.admitted is False


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_invoke_board_refuses_one_usable_seat_without_configuration(tmp_path, monkeypatch, tier):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch)
    assert _invoke(c.ctx, tier, spawn=_ok_spawn({"grok", "codex"})).landing_decision.admitted is True  # two usable
    assert _not_admitted(lambda: _invoke(c.ctx, tier, spawn=_ok_spawn({"grok", "codex", "gemini"})))


@pytest.mark.parametrize("config", ["minimum-1", "no-config"])
@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_invoke_board_refuses_a_landing_without_a_president_ruling(tmp_path, monkeypatch, tier, config):
    s = slice1()
    user = _rotated_cr_table(minimum=1) if config == "minimum-1" else None
    c = _context(s, tmp_path, monkeypatch, user=user)
    assert _invoke(c.ctx, tier).landing_decision.admitted is True  # control: the president rules
    assert _not_admitted(lambda: _invoke(c.ctx, tier, president_invoke=_no_ruling_president))


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_a_supplied_policy_without_a_context_is_refused(tmp_path, monkeypatch, tier):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=_rotated_cr_table(minimum=1))
    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_sanctioned_review_transport(
            c.ctx.composed.board, "artifact", spawn=_ok_spawn(), landing_tier=tier,
            review_policy=s.landing_policy(tier, context=c.ctx), president_invoke=deferring_president,
        )
    assert excinfo.value.code == "panel_context_required"


def _perturbations(value: object) -> list[object]:
    """Every different value the every-field node tries: for an integer both a HIGHER and
    every LOWER value down to 0 (a lowered floor is the dangerous direction)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return [value + 1, *range(0, value)]
    return [_perturbed(value)]


def _perturbed(value: object) -> object:
    """A different value of the same kind (for the every-field node)."""
    if isinstance(value, bool):
        return not value
    if value is None:
        return 1
    if isinstance(value, int):
        return value + 1 if value < 4 else value - 1
    if isinstance(value, tuple):
        return value[:-1] if value else ("extra",)
    if isinstance(value, str):
        return value + "-other"
    raise AssertionError(f"no perturbation for a policy field of type {type(value).__name__}")


def _policy_mismatches():
    """(id, user table, available, policy factory(s, ctx, tier)) -- each a SUPPLIED policy
    that is not ``panel_landing_policy(tier, context=ctx)`` by value, so it must be refused."""
    canonical = lambda s, ctx, tier: s.landing_policy(tier, context=ctx)  # noqa: E731
    return [
        ("no-config-lowered", None, ("claude",),
         lambda s, ctx, tier: dataclasses.replace(pi.review_policy_for_tier(tier), min_distinct_vendors=1,
                                                  min_usable_seats=2)),
        ("configured-lowered", _rotated_cr_table(minimum=3), BOARD_VENDORS,
         lambda s, ctx, tier: dataclasses.replace(canonical(s, ctx, tier), min_distinct_vendors=1)),
        ("floor-dropped", _rotated_cr_table(minimum=1), BOARD_VENDORS,
         lambda s, ctx, tier: dataclasses.replace(canonical(s, ctx, tier), min_usable_seats=0)),
        ("president-dropped", _rotated_cr_table(minimum=1), BOARD_VENDORS,
         lambda s, ctx, tier: dataclasses.replace(canonical(s, ctx, tier), requires_president=False)),
        # Configured, so the named-seat check is relaxed: only equality can refuse this. The
        # change is made with ``_perturbed`` so no encoding of the configured policy's
        # ``required_seats`` (e.g. empty vs. the four aliases) is assumed.
        ("required-seats-changed", _rotated_cr_table(minimum=1), BOARD_VENDORS,
         lambda s, ctx, tier: dataclasses.replace(
             canonical(s, ctx, tier), required_seats=_perturbed(tuple(canonical(s, ctx, tier).required_seats)))),
        # No configuration anywhere, all four vendors up: today's policy passes today's named
        # check, but its floor is 0 -- a "backward-compatible" acceptance lowers the landing.
        ("todays-policy-for-an-unconfigured-context", None, BOARD_VENDORS,
         lambda s, ctx, tier: pi.review_policy_for_tier(tier)),
        # All four vendors up, so today's named-seat check alone would ACCEPT this board: only
        # the equality rule can refuse it.
        ("todays-policy-for-a-configured-context", _rotated_cr_table(minimum=1), BOARD_VENDORS,
         lambda s, ctx, tier: pi.review_policy_for_tier(tier)),
    ]


def _supply(c, tier, supplied, monkeypatch):
    """Invoke through the sanctioned control with ``supplied`` as ``review_policy``; return
    ``(calls, launched, outcome)`` where ``calls`` records the policy validation and
    ``outcome`` is the result or the raised ``PresidentPolicyError``."""
    real_validate = _unwrapped(pi._validate_review_board_policy)
    calls: list[str] = []

    def validate_spy(*args, **kwargs):
        calls.append("enter")
        try:
            return real_validate(*args, **kwargs)
        except PresidentPolicyError:
            calls.append("refused")
            raise

    monkeypatch.setattr(pi, "_validate_review_board_policy", _mark(validate_spy, real_validate))
    launched: list[str] = []

    def spawn(leg, artifact):
        launched.append(leg)
        return _ok_spawn()(leg, artifact)

    try:
        outcome: object = invoke_sanctioned_review_transport(
            c.ctx.composed.board, "artifact", spawn=spawn, landing_tier=tier, panel_context=c.ctx,
            review_policy=supplied, president_invoke=deferring_president,
        )
    except PresidentPolicyError as exc:
        outcome = exc
    return calls, launched, outcome


def _assert_refused_inside_validation(case_id, calls, launched, outcome) -> None:
    assert isinstance(outcome, PresidentPolicyError), f"{case_id}: a supplied non-context policy was accepted"
    assert outcome.code and outcome.code != "panel_context_required", case_id
    assert calls == ["enter", "refused"], f"{case_id}: not refused inside the one policy validation"
    assert launched == [], f"{case_id}: a seat launched under a refused policy"


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
@pytest.mark.parametrize("case_id,user,available,make", _policy_mismatches(), ids=[c[0] for c in _policy_mismatches()])
def test_ec4_a_supplied_policy_that_is_not_the_contexts_is_refused_inside_validation(
        tmp_path, monkeypatch, tier, case_id, user, available, make):
    """Orchestrator ruling (agent-harness#1092 r1): a supplied ``review_policy`` is accepted
    only if it EQUALS ``panel_landing_policy(tier, context=panel_context)``; the named-seat
    relaxation applies only when the context's resolved table sets the minimum from the user
    or repository file. Anything else is a typed refusal raised INSIDE
    ``_validate_review_board_policy`` (so the sanctioned control sees one validation), and
    no seat launches."""
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, user=user, available=available)
    try:
        supplied = make(s, c.ctx, tier)
    except (ValueError, TypeError):
        return  # the policy cannot even be constructed: refused at construction
    # IF assumption (listed on agent-harness#1092): ``review_policy_for_tier`` stays
    # floor-less, so today's policy never equals a context's panel policy.
    assert supplied != s.landing_policy(tier, context=c.ctx), (
        f"{case_id}: IF assumption broken -- the supplied policy equals the context's policy")
    _assert_refused_inside_validation(case_id, *_supply(c, tier, supplied, monkeypatch))


@pytest.mark.parametrize("config", ["minimum-1", "no-config"])
@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_every_policy_field_is_compared(tmp_path, monkeypatch, tier, config):
    """Value equality means EVERY field: perturbing any single field of the canonical policy
    (whatever fields ``ReviewLandingPolicy`` carries) is refused inside validation."""
    s = slice1()
    user = _rotated_cr_table(minimum=1) if config == "minimum-1" else None
    c = _context(s, tmp_path, monkeypatch, user=user)
    canonical = s.landing_policy(tier, context=c.ctx)
    fields = dataclasses.fields(canonical)
    assert {f.name for f in fields} >= {"required_seats", "requires_president", "min_distinct_vendors", "min_usable_seats"}
    for field in fields:
        for value in _perturbations(getattr(canonical, field.name)):
            try:
                supplied = dataclasses.replace(canonical, **{field.name: value})
            except (ValueError, TypeError):
                continue  # refused at construction (e.g. min_distinct_vendors=0)
            assert supplied != canonical
            _assert_refused_inside_validation(f"{config}:{field.name}={value!r}", *_supply(c, tier, supplied, monkeypatch))


@pytest.mark.parametrize("config", ["minimum-1", "no-config"])
@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_ec4_an_independently_constructed_equal_policy_is_accepted(tmp_path, monkeypatch, tier, config):
    """The acceptance control: a policy EQUAL to the context's but a distinct object (so an
    identity-only or cached-object validator fails) is validated once and lands."""
    s = slice1()
    user = _rotated_cr_table(minimum=1) if config == "minimum-1" else None
    c = _context(s, tmp_path, monkeypatch, user=user)
    canonical = s.landing_policy(tier, context=c.ctx)
    supplied = dataclasses.replace(canonical)
    assert supplied == canonical and supplied is not canonical
    calls, launched, outcome = _supply(c, tier, supplied, monkeypatch)
    assert not isinstance(outcome, BaseException), f"an equal policy was refused: {outcome}"
    assert calls == ["enter"], "the equal policy was not validated exactly once"
    assert launched, "no seat launched under an accepted policy"
    assert outcome.landing_decision.admitted is True


# =======================================================================================
# EC-PANEL-5 -- every result is labelled, and the labels are right
# =======================================================================================


def _expected_delivery() -> str:
    """Slice 1 alone delivers lenses as metadata; once ``lens_frame`` exists, as prompt."""
    try:
        module = __import__(LENS_FRAME, fromlist=["render_lens_section"])
    except ModuleNotFoundError:
        return "metadata-only"
    return "prompt" if hasattr(module, "render_lens_section") else "metadata-only"


@pytest.mark.parametrize("source", ["built-in", "user", "repository"])
def test_ec5_result_labels_match_the_resolved_configuration_and_seat_outcomes(tmp_path, monkeypatch, source):
    s = slice1()
    body = _panel_toml(
        "code-review",
        [
            ("correctness", ("claude", "codex")),
            ("adversarial", ("grok", "claude")),
            ("supply-chain", ("codex", "claude")),
            ("red-team", ("grok",)),
        ],
        lenses={"supply-chain": "Check dependency provenance."},
        minimum=2,
    )
    # No config keeps today's named-seat landing path, so the built-in case seats every
    # vendor (a fallback seat would be refused before launch); the configured cases lose grok.
    available = BOARD_VENDORS if source == "built-in" else ("claude", "codex", "gemini")
    c = _context(
        s, tmp_path, monkeypatch, available=available,
        user=body if source == "user" else USER_BODY,
        repo_files={REPO_REL: body} if source == "repository" else None,
    )
    board = c.ctx.composed.board
    result = _invoke(c.ctx, "plan", spawn=_ok_spawn({"codex"}))
    labels = _labels(result.panel_labels)
    usable = [leg for leg in result.legs if leg.usable]
    assert labels["composed_seats"] == len(board.seats)
    assert labels["usable_seats"] == len(usable)
    assert labels["usable_distinct_vendors"] == len({leg.leg for leg in usable})
    delivery = _expected_delivery()
    by_key = {seat["seat_key"]: seat for seat in labels["seats"]}
    assert set(by_key) == {seat.seat_key for seat in board.seats}
    for seat in board.seats:
        lens = c.ctx.composed.seat_lenses[seat.seat_key]
        assert by_key[seat.seat_key]["lens"] == lens.name
        assert by_key[seat.seat_key]["lens_kind"] == lens.kind
        assert by_key[seat.seat_key]["vendor"] == seat.vendor_family
        assert by_key[seat.seat_key]["lens_delivery"] == delivery
    assert sorted(labels["fallback_lanes"]) == _lane_names(c.ctx.composed.fallback_lanes)
    assert sorted(labels["unfilled_lanes"]) == _lane_names(c.ctx.composed.unfilled_lanes)
    assert labels["explicit_profile"] is None
    minimum_source, table_source = labels["minimum_source"], labels["table_source"]
    if source == "built-in":
        assert labels["effective_minimum"] == 4
        assert minimum_source["kind"] == "built-in" and table_source["kind"] == "built-in"
    elif source == "user":
        assert "red-team" in labels["unfilled_lanes"] and "adversarial" in labels["fallback_lanes"]
        assert labels["effective_minimum"] == 2
        for record in (minimum_source, table_source):
            assert record["kind"] == "user"
            assert record["path"] == str(c.user_path)
            assert record["digest"] == _sha256(c.user_path)
    else:
        assert labels["effective_minimum"] == 2
        for record in (minimum_source, table_source):
            assert record["kind"] == "repository"
            assert str(record["path"]).endswith(REPO_REL)
            assert record["base_revision"] == c.base
    if source != "built-in":
        assert labels["usable_distinct_vendors"] == 1, "only the Claude seats were usable"
    assert labels["minimum_met"] is False  # at most three usable vendors (codex unusable)
    if source != "built-in":
        assert result.landing_decision.admitted is False


def test_ec5_labels_carry_the_explicit_profile_and_its_provenance(tmp_path, monkeypatch):
    s = slice1()
    c = _context(
        s, tmp_path, monkeypatch, user=_cr_table(minimum=1),
        repository_profile=lambda base: s.ExplicitProfileSeats(
            seats=("grok", "fable"), path=".phase-loop/governance.toml", provenance=base),
    )
    labels = _labels(_invoke(c.ctx, "plan").panel_labels)
    assert labels["explicit_profile"] is not None
    assert list(labels["explicit_profile"]["seats"]) == ["grok", "fable"]
    assert labels["explicit_profile"]["path"] == ".phase-loop/governance.toml"
    # IF-0-PANEL-1: the repository profile is read at, and labelled with, the context's
    # gated_revision -- the actual base revision.
    assert c.ctx.gated_revision == c.base
    assert c.base in json.dumps(labels["explicit_profile"]), "the profile label does not carry gated_revision"


def test_ec5_labels_carry_a_user_profile_path_and_digest_not_the_base(tmp_path, monkeypatch):
    """A USER profile is labelled with the user file's path and content digest -- never with
    the base revision a repository profile carries."""
    s = slice1()
    path = tmp_path / "xdg" / "agent-harness" / "governance.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[tiers.plan]\npanel = ["grok"]\n', encoding="utf-8")
    digest = _sha256(path)
    profile = s.ExplicitProfileSeats(seats=("grok",), path=str(path), provenance=digest)
    c = _context(s, tmp_path, monkeypatch, user=_cr_table(minimum=1), user_profile=profile)
    labels = _labels(_invoke(c.ctx, "plan").panel_labels)
    record = json.dumps(labels["explicit_profile"])
    assert str(path) in record and digest in record
    assert c.base not in record, "a user profile was labelled with the base revision"


def test_ec5_labels_record_an_invalid_base_table_replacement(tmp_path, monkeypatch):
    s = slice1()
    c = _context(s, tmp_path, monkeypatch, repo_files={REPO_REL: _cr_table(extra="bogus_key = 1")})
    labels = _labels(_invoke(c.ctx, "plan").panel_labels)
    assert REPLACED_LABEL in json.dumps(labels["table_source"])
    assert labels["effective_minimum"] == 4


# =======================================================================================
# ec3e -- every landing entry point, driven through the entry point itself
# =======================================================================================


class _TargetRepo:
    """``origin`` (bare, default branch ``main``) + the entry's checkout + an upstream
    clone that moves the target head without touching the checkout."""

    def __init__(self, tmp_path: Path, name: str, files: Mapping[str, str | None]) -> None:
        self.origin = tmp_path / f"{name}.origin.git"
        self.path = tmp_path / name
        self.upstream = tmp_path / f"{name}.upstream"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True,
                       capture_output=True)
        self.upstream.mkdir()
        _git(self.upstream, "init", "-q", "-b", "main")
        _git(self.upstream, "remote", "add", "origin", str(self.origin))
        self.base = _commit(self.upstream, {"README.md": "target\n", **files}, "base")
        _git(self.upstream, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.path)], check=True, capture_output=True)
        _git(self.path, "checkout", "-q", "-b", "change")
        self.change_head = _commit(self.path, {"src.py": "change = 1\n"}, "the change under review")

    def push_target(self, files: Mapping[str, str | None], message: str) -> str:
        sha = _commit(self.upstream, files, message)
        _git(self.upstream, "push", "-q", "origin", "main")
        return sha

    def change(self, files: Mapping[str, str | None], message: str) -> str:
        self.change_head = _commit(self.path, files, message)
        return self.change_head


_GOVLEAN_SWITCH = json.dumps({
    "schema_version": 1,
    "plans": [{
        "slug": "v10-GOVLEAN",
        "lifecycle": [{
            "transition": "authority_switch", "by": "codex-execute-phase",
            "at": "2026-08-15T00:00:00Z", "metadata": {"verification_status": "passed"},
        }],
    }],
}) + "\n"


@dataclasses.dataclass
class _Outcome:
    landed: bool
    labels: object
    detail: str = ""


class _Harness:
    """Drives one entry point hermetically: a real git target, a real user file, injected
    probes, fake seats and a fake president; the gate, the context and the landing
    decision are the entry point's own."""

    def __init__(self, s, tmp_path: Path, monkeypatch, *, repo_files=None, user: str | None = USER_BODY,
                 available: Iterable[str] = BOARD_VENDORS, policy: str = "bounded") -> None:
        from phase_loop_runtime import cli, governed_review, runner, train_runner
        from phase_loop_runtime.advisor_board import backing

        self.s, self.tmp, self.mp, self.policy = s, tmp_path, monkeypatch, policy
        self.user = _user_file(tmp_path, monkeypatch, user)
        self.repo = _TargetRepo(tmp_path, "repo-a", {"plans/manifest.json": _GOVLEAN_SWITCH, **(repo_files or {})})
        self.probes = _ForcedProbes(s, monkeypatch, available)
        self.unusable: set[str] = set()
        self.after_snapshot: list[Callable[[], None]] = []
        self.after_first_gate: list[Callable[[], None]] = []
        self.during_seats: list[Callable[[], None]] = []
        self.seat_hooks_fired = 0
        self.snapshots: list[object] = []
        self.contexts: list[object] = []
        self.build_calls: list[dict] = []
        self.invocations: list[dict] = []
        self._reals = {
            (module, name): _unwrapped(getattr(module, name))
            for module, name in (
                (pi, "invoke_board"),
                (backing, "prepare_review_isolation_authorization"),
                (backing, "set_review_instruction_digest"),
                (backing, "reset_review_instruction_digest"),
            )
        }
        real_snapshot = _unwrapped(s.config.snapshot_panel_run)
        real_build = _unwrapped(s.config.build_panel_context)

        def snapshot_spy(*args, **kwargs):
            snap = real_snapshot(*args, **kwargs)
            self.snapshots.append(snap)
            hooks, self.after_snapshot[:] = list(self.after_snapshot), []
            for fn in hooks:
                fn()
            return snap

        build_signature = inspect.signature(real_build)

        def build_spy(*args, **kwargs):
            # Bind as the builder sees them, so a positional or defaulted
            # ``monitoring_policy`` is recorded correctly.
            bound = build_signature.bind(*args, **kwargs)
            bound.apply_defaults()
            self.build_calls.append(dict(bound.arguments))
            ctx = real_build(*args, **kwargs)
            self.contexts.append(ctx)
            if len(self.contexts) == 1:
                for fn in list(self.after_first_gate):
                    fn()
            return ctx

        def invoke(board, artifact, **kwargs):
            return self._invoke(board, artifact, **kwargs)

        # Entry-level ISOLATION authority minting and digest binding are stubbed; composition
        # authority stays REAL (a builder that prepares and revalidates it, as ``load_boards``
        # does, must work unchanged). The delegate
        # re-runs the REAL invoke_board through the sanctioned hermetic seam with the
        # real backing restored, so the landing decision is production's own.
        stubs = {
            (s.config, "snapshot_panel_run"): snapshot_spy,
            (s.config, "build_panel_context"): build_spy,
            (pi, "invoke_board"): invoke,
            (backing, "prepare_review_isolation_authorization"): lambda *a, **k: "authorization",
            (backing, "set_review_instruction_digest"): lambda *a, **k: object(),
            (backing, "reset_review_instruction_digest"): lambda *a, **k: None,
        }
        for (module, name), spy in stubs.items():
            monkeypatch.setattr(module, name, _mark(spy, _unwrapped(getattr(module, name))))
        # Observation at the CALL BOUNDARY, whichever way an entry imported the name: an
        # entry module that binds one of these names at module level gets the same spy.
        # (``runner._PRODUCTION_INVOKE_BOARD`` is its identity sentinel, deliberately untouched.)
        aliased = {
            "invoke_board": invoke,
            "snapshot_panel_run": snapshot_spy,
            "build_panel_context": build_spy,
            "compose_panel_board": _unwrapped_forced(s),
        }
        for module in (runner, governed_review, cli, train_runner):
            for name, spy in aliased.items():
                if spy is not None and hasattr(module, name):
                    monkeypatch.setattr(module, name, spy)
        if policy == "heartbeat_only":
            # The agy capability probe is host state; the policy's own route checks stay real.
            monkeypatch.setattr(pi, "_preflight_gemini_heartbeat", lambda *a, **k: None)

    @contextlib.contextmanager
    def _production(self):
        saved = {key: getattr(*key) for key in self._reals}
        for (module, name), fn in self._reals.items():
            setattr(module, name, fn)
        try:
            yield
        finally:
            for (module, name), fn in saved.items():
                setattr(module, name, fn)

    # Transport keys the sanctioned hermetic control owns or cannot accept (it mints its own
    # authority, scratch and artifact binding, under the bounded policy). Every OTHER keyword
    # the entry passed -- ``landing_tier``, ``review_policy``, ``panel_context``, aliases and
    # anything new -- is forwarded UNCHANGED, so the landing decision is made on the entry's
    # own policy object. Only ``spawn`` and ``president_invoke`` are injected.
    _TRANSPORT_KEYS = frozenset({
        "review_authorization", "canonical_repo_authority", "repo_dir", "artifact_ref", "stream_dir",
        "brief_ref", "agy_canary_capture", "native_leg_fills", "native_president_fill",
        "monitoring_policy", "spawn", "president_invoke", "max_concurrency",
    })

    def _invoke(self, board, _artifact, **kwargs):
        self.invocations.append({"board": board, **kwargs})
        forwarded = {k: v for k, v in kwargs.items() if k not in self._TRANSPORT_KEYS}
        tier = getattr(kwargs.get("landing_tier"), "value", kwargs.get("landing_tier"))
        if tier in PRESIDENT_TIERS:
            forwarded["president_invoke"] = deferring_president
        seat_spawn = _ok_spawn(self.unusable)
        fired: list[bool] = []

        def spawn(leg: str, artifact: str):
            # Hooks run INSIDE real seat execution (the first seat launch), after the entry's
            # gate and before any landing decision.
            if not fired:
                fired.append(True)
                self.seat_hooks_fired += 1
                for fn in list(self.during_seats):
                    fn()
            return seat_spawn(leg, artifact)

        with self._production():
            return invoke_sanctioned_review_transport(board, "artifact", spawn=spawn, **forwarded)

    def edit_user_file(self) -> None:
        self.user.write_text(self.user.read_text(encoding="utf-8") + "# edited mid-run\n", encoding="utf-8")


def _typed_refusals() -> tuple[type[BaseException], ...]:
    from phase_loop_runtime import legible_evidence
    from phase_loop_runtime.advisor_board.config import BoardConfigError

    return (PresidentPolicyError, legible_evidence.LegibleProcessBootstrapError, BoardConfigError)


def _run_runner(h: _Harness, tier: str) -> _Outcome:
    from phase_loop_runtime import runner

    assert tier == "production_code"
    run_dir = h.repo.path / ".phase-loop" / "runs" / "panel"
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in run_dir.glob("implementation-panel*.json"):
        stale.unlink()
    bundle = run_dir / "bundle.md"
    bundle.write_text("staged transition evidence\n", encoding="utf-8")
    try:
        runner._run_legible_panel(h.repo.path, run_dir, h.repo.change_head, bundle)
    except _typed_refusals() as exc:
        return _Outcome(False, None, f"{type(exc).__name__}: {exc}")
    record = run_dir / "implementation-panel.json"
    if not record.exists():
        return _Outcome(False, None, "no landing record")
    return _Outcome(True, json.loads(record.read_text(encoding="utf-8")).get("panel_labels"))


def _run_gate(h: _Harness, tier: str) -> _Outcome:
    from phase_loop_runtime import governed_review

    assert tier == "plan"
    gate = governed_review.governed_board_gate(
        artifact="# Train-level bundle review\n\nbundle\n", author_executor="train-coordinator",
        run_mode="governed", canonical_repo_authority=h.repo.path, reviewed_sha=h.repo.change_head,
        **({"monitoring_policy": h.policy} if h.policy != "bounded" else {}),
    )
    panel = getattr(gate, "panel", None)
    labels = getattr(panel, "panel_labels", None) if panel is not None else None
    return _Outcome(bool(gate.ran and gate.promoted), labels, str(gate.reason or ""))


def _run_train(h: _Harness, tier: str) -> _Outcome:
    from test_train_review_authorization import NODE, _run_review

    from phase_loop_runtime.train_ledger import LedgerRecord, append_record

    assert tier == "plan"
    h.mp.chdir(h.repo.path)
    ledger = h.tmp / f"ledger-{len(h.invocations)}-{len(h.contexts)}" / "train.ledger.jsonl"
    append_record(ledger, LedgerRecord(
        node_id=NODE, status="pr_open", branch="change", head_sha=h.repo.change_head,
        pr_url="https://gh.com/repo-a/pr/1", merge_order=0,
    ))
    result, merged = _run_review(h.tmp, ledger, review_only=False, review_fn=None,
                                 live=h.repo.change_head, head=h.repo.change_head,
                                 **({"review_monitoring_policy": h.policy} if h.policy != "bounded" else {}))
    landed = result.get("status") == "merged" and bool(merged)
    return _Outcome(landed, result.get("panel_labels"), str(result.get("reason") or result.get("status")))


def _run_cli(h: _Harness, tier: str | None) -> _Outcome:
    """``advisor-board --json``; ``tier=None`` is the non-landing (advisory) run."""
    from phase_loop_runtime import cli

    h.mp.chdir(h.repo.path)
    artifact = h.tmp / "artifact.md"
    artifact.write_text("# artifact\n", encoding="utf-8")
    argv = ["advisor-board", str(artifact), "--native-fill-dir", str(h.tmp / "native-fill"), "--json"]
    if tier is not None:
        argv += ["--landing-tier", tier]
    if h.policy != "bounded":
        argv += ["--monitoring-policy", h.policy]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cli.main(argv)
    try:
        payload = json.loads(out.getvalue())
    except ValueError:
        payload = {}
    return _Outcome(rc == 0, payload.get("panel_labels"), f"rc={rc}")


ENTRIES: dict[str, tuple[Callable[[_Harness, str], _Outcome], tuple[str, ...]]] = {
    "runner": (_run_runner, ("production_code",)),
    "governed_gate": (_run_gate, ("plan",)),
    "run_train": (_run_train, ("plan",)),
    "advisor_board": (_run_cli, ("plan", "tests_only")),
}
LANDING_CASES = [(entry, tier) for entry, (_fn, tiers) in ENTRIES.items() for tier in tiers if tier in PRESIDENT_TIERS]
GATE_CASES = [(entry, tier) for entry, (_fn, tiers) in ENTRIES.items() for tier in tiers]
# Entries with a heartbeat_only review today (the runner's exact-head board has none).
HEARTBEAT_CASES = [(entry, tier) for entry, tier in LANDING_CASES if entry != "runner"]
POLICY_GATE_CASES = [(entry, tier, "bounded") for entry, tier in GATE_CASES] + [
    (entry, tier, "heartbeat_only") for entry, tier in HEARTBEAT_CASES
]


def _ids(cases):
    return [f"{entry}-{tier}" for entry, tier in cases]


def _harness(tmp_path, monkeypatch, request, **kwargs) -> _Harness:
    s = slice1()
    if "run_train" in request.node.name:
        request.getfixturevalue("synthetic_train_packet")
    return _Harness(s, tmp_path, monkeypatch, **kwargs)


def _drive(h: _Harness, entry: str, tier: str) -> _Outcome:
    return ENTRIES[entry][0](h, tier)


@pytest.mark.parametrize("minimum", [1, 2])
@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_configured_minimum_is_enforced_both_ways(tmp_path, monkeypatch, request, entry, tier, minimum):
    h = _harness(tmp_path, monkeypatch, request, repo_files={REPO_REL: _cr_table(minimum=minimum)},
                 available=("claude",))
    outcome = _drive(h, entry, tier)
    assert outcome.landed is (minimum == 1), outcome.detail
    assert h.contexts and h.contexts[0].gated_revision == h.repo.base
    if outcome.landed:
        labels = _labels(outcome.labels)
        assert labels["effective_minimum"] == 1 and labels["minimum_met"] is True
        assert labels["usable_distinct_vendors"] == 1
        assert labels["minimum_source"]["kind"] == "repository"
        assert labels["minimum_source"]["base_revision"] == h.repo.base


@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_user_file_edit_before_the_gate_is_refused(tmp_path, monkeypatch, request, entry, tier):
    control = _harness(tmp_path / "control", monkeypatch, request)
    assert _drive(control, entry, tier).landed is True
    h = _harness(tmp_path / "edited", monkeypatch, request)
    h.after_snapshot.append(h.edit_user_file)
    outcome = _drive(h, entry, tier)
    assert h.snapshots, "the entry point took no run-start snapshot"
    assert outcome.landed is False, outcome.detail


@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_user_file_edit_after_the_gate_is_refused(tmp_path, monkeypatch, request, entry, tier):
    control = _harness(tmp_path / "control", monkeypatch, request)
    assert _drive(control, entry, tier).landed is True
    h = _harness(tmp_path / "edited", monkeypatch, request)
    h.during_seats.append(h.edit_user_file)
    outcome = _drive(h, entry, tier)
    assert h.contexts and h.invocations and h.seat_hooks_fired, "the edit did not happen during seat execution"
    assert outcome.landed is False, outcome.detail


@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_target_head_panel_change_before_the_first_gate_is_enforced(tmp_path, monkeypatch, request, entry, tier):
    control = _harness(tmp_path / "control", monkeypatch, request, repo_files={REPO_REL: _cr_table(minimum=1)},
                       available=("claude",))
    assert _drive(control, entry, tier).landed is True
    h = _harness(tmp_path / "moved", monkeypatch, request, repo_files={REPO_REL: _cr_table(minimum=1)},
                 available=("claude",))
    moved: list[str] = []
    h.after_snapshot.append(lambda: moved.append(h.repo.push_target({REPO_REL: _cr_table(minimum=2)}, "raise")))
    outcome = _drive(h, entry, tier)
    assert moved and h.contexts[0].gated_revision == moved[0], "the gate did not read the target head at gate time"
    assert outcome.landed is False, outcome.detail


@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_target_head_panel_change_after_the_gate_forces_a_regate(tmp_path, monkeypatch, request, entry, tier):
    control = _harness(tmp_path / "control", monkeypatch, request, repo_files={REPO_REL: _cr_table(minimum=1)},
                       available=("claude",))
    control.during_seats.append(lambda: control.repo.push_target({"README.md": "unrelated\n"}, "unrelated"))
    assert _drive(control, entry, tier).landed is True
    h = _harness(tmp_path / "moved", monkeypatch, request, repo_files={REPO_REL: _cr_table(minimum=1)},
                 available=("claude",))
    moved: list[str] = []
    h.during_seats.append(lambda: moved.append(h.repo.push_target({REPO_REL: _cr_table(minimum=2)}, "raise")))
    outcome = _drive(h, entry, tier)
    assert moved, "the target head never moved during seat execution"
    assert len(h.contexts) >= 2 and h.contexts[-1].gated_revision == moved[0], "no re-gate at the new target head"
    assert outcome.landed is False, outcome.detail


@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_target_head_profile_panel_list_change_after_the_gate_forces_a_regate(tmp_path, monkeypatch, request, entry, tier):
    control = _harness(tmp_path / "control", monkeypatch, request, repo_files={REPO_REL: _cr_table(minimum=1)},
                       available=("claude",))
    assert _drive(control, entry, tier).landed is True
    h = _harness(tmp_path / "moved", monkeypatch, request, repo_files={REPO_REL: _cr_table(minimum=1)},
                 available=("claude",))
    moved: list[str] = []
    required = ("fable", "sol", "gemini", "grok")
    h.during_seats.append(lambda: moved.append(h.repo.push_target(
        {GOVERNANCE_REL: f"[tiers.{tier}]\npanel = {json.dumps(list(required))}\n"}, "profile panel list")))
    outcome = _drive(h, entry, tier)
    assert moved, "the target head never moved during seat execution"
    assert len(h.contexts) >= 2 and h.contexts[-1].gated_revision == moved[0], "no re-gate at the new target head"
    profile = h.contexts[-1].explicit_profile
    assert profile is not None and tuple(profile.seats) == required, "the re-gate did not load the profile's seats"
    assert outcome.landed is False, outcome.detail


@pytest.mark.parametrize("where", ["repository", "user"])
@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_a_profile_document_cannot_lower_the_minimum(tmp_path, monkeypatch, request, entry, tier, where):
    """EC-PANEL-4: only the user or base-revision ``advisor-boards.toml`` may lower the
    minimum. A governance profile DOCUMENT that tries to (a ``min_distinct_vendors`` key
    beside its ``panel`` list) is refused or ignored; either way a one-vendor landing with
    no ``[panel.*]`` configuration keeps today's four named seats and is refused."""
    # Control: the SAME one-vendor landing lands when the minimum is lowered by the only
    # permitted route (the base-revision advisor-boards.toml), so the refusal below is not
    # the entry refusing everything.
    control = _harness(tmp_path / "control", monkeypatch, request,
                       repo_files={REPO_REL: _cr_table(minimum=1)}, available=("claude",))
    assert _drive(control, entry, tier).landed is True, "the permitted lowering route does not land"
    tmp_path = tmp_path / "lowering"
    lowering = f"[tiers.{tier}]\npanel = [\"fable\"]\nmin_distinct_vendors = 1\n"
    repo_files = {GOVERNANCE_REL: lowering} if where == "repository" else None
    h = _harness(tmp_path, monkeypatch, request, repo_files=repo_files, available=("claude",))
    if where == "user":
        (h.user.parent / "governance.toml").write_text(lowering, encoding="utf-8")
    outcome = _drive(h, entry, tier)
    assert outcome.landed is False, outcome.detail
    for ctx in h.contexts:
        assert h.s.landing_policy(tier, context=ctx).min_distinct_vendors is None


@pytest.mark.parametrize("source", ["repository", "user"])
@pytest.mark.parametrize("entry,tier", LANDING_CASES, ids=_ids(LANDING_CASES))
def test_ec3e_landing_labels_match_the_configuration_and_seat_outcomes(tmp_path, monkeypatch, request, entry, tier, source):
    """EC-PANEL-5 at each entry's SERIALIZED record (the runner's implementation-panel.json,
    the advisor-board JSON, the run-train result, the gate's panel), checked against the
    independently established fixture: path + base revision for a repository table, path +
    content digest for a user table -- for both the minimum's and the table's source."""
    if source == "repository":
        h = _harness(tmp_path, monkeypatch, request, repo_files={REPO_REL: _rotated_cr_table(minimum=1)},
                     available=("claude", "codex"))
    else:
        h = _harness(tmp_path, monkeypatch, request, user=USER_BODY + _rotated_cr_table(minimum=1),
                     available=("claude", "codex"))
    outcome = _drive(h, entry, tier)
    assert outcome.landed is True, outcome.detail
    assert h.contexts, "the entry built no gate context"
    ctx = h.contexts[-1]
    labels = _labels(outcome.labels)
    board = ctx.composed.board
    assert labels["composed_seats"] == len(board.seats) == len(CR_LENSES)
    assert labels["usable_seats"] == len(board.seats)
    assert labels["usable_distinct_vendors"] == 2
    assert sorted(labels["fallback_lanes"]) == _lane_names(ctx.composed.fallback_lanes)
    # grok (adversarial) and gemini (alternative-approach) are down: both lanes fall back.
    assert sorted(labels["fallback_lanes"]) == ["adversarial", "alternative-approach"]
    assert list(labels["unfilled_lanes"]) == []
    assert labels["effective_minimum"] == 1 and labels["minimum_met"] is True
    for name in ("minimum_source", "table_source"):
        record = labels[name]
        assert record.get("kind") == source, (name, record)
        if source == "repository":
            assert str(record.get("path", "")).endswith(REPO_REL), (name, record)
            assert record.get("base_revision") == h.repo.base == ctx.gated_revision, (name, record)
        else:
            assert record.get("path") == str(h.user), (name, record)
            assert record.get("digest") == _sha256(h.user), (name, record)
    assert labels["explicit_profile"] is None
    assert sorted(seat["lens"] for seat in labels["seats"]) == sorted(CR_LENSES)
    assert {seat["vendor"] for seat in labels["seats"]} == {"claude", "codex"}


@pytest.mark.parametrize("entry,tier", GATE_CASES, ids=_ids(GATE_CASES))
def test_ec3e_an_invalid_panel_change_is_refused_before_any_seat(tmp_path, monkeypatch, request, entry, tier):
    control = _harness(tmp_path / "control", monkeypatch, request)
    control.repo.change({REPO_REL: _cr_table(minimum=2)}, "valid panel edit")
    with contextlib.suppress(Exception):  # the control asserts only that the board was reached
        _drive(control, entry, tier)
    assert control.invocations, "a valid [panel.*] change never reached the board"
    h = _harness(tmp_path / "invalid", monkeypatch, request)
    h.repo.change({REPO_REL: _cr_table(("claude", "mistral"))}, "invalid panel edit")
    outcome = _drive(h, entry, tier)
    assert outcome.landed is False
    assert h.invocations == [], "an invalid [panel.*] change reached the board"


@pytest.mark.parametrize("entry,tier,policy", POLICY_GATE_CASES,
                         ids=[f"{e}-{t}-{p}" for e, t, p in POLICY_GATE_CASES])
def test_ec3e_the_entry_passes_its_gate_context_and_tier_to_invoke_board(tmp_path, monkeypatch, request, entry, tier, policy):
    available = ("claude", "codex", "gemini") if policy == "heartbeat_only" else BOARD_VENDORS
    h = _harness(tmp_path, monkeypatch, request, user=_rotated_cr_table(minimum=1), available=available, policy=policy)
    with contextlib.suppress(Exception):  # only what reached invoke_board is asserted here
        _drive(h, entry, tier)
    assert h.snapshots and h.contexts and h.invocations
    call = h.invocations[-1]
    assert isinstance(call.get("panel_context"), h.s.PanelContext), "invoke_board received no PanelContext"
    assert call["panel_context"] is h.contexts[-1]
    assert call["board"] == h.contexts[-1].composed.board
    assert getattr(call.get("landing_tier"), "value", call.get("landing_tier")) == tier
    assert any(call["panel_context"].snapshot is snap for snap in h.snapshots)
    # The entry itself supplies the context's own policy (IF-0-PANEL-1 names no default for
    # a context without a policy, so the entry is what is pinned here).
    assert call.get("review_policy") == h.s.landing_policy(tier, context=call["panel_context"])
    sent = call["board"]
    assert h.build_calls and all(k.get("monitoring_policy") == policy for k in h.build_calls), (
        f"the entry built its context under {[k.get('monitoring_policy') for k in h.build_calls]}, not {policy}")
    if policy == "heartbeat_only":
        from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

        assert sent != DEFAULT_BOARD, "heartbeat_only still sent the frozen default board"
        assert {seat.vendor_family for seat in sent.seats} <= set(available)
        assert sorted(str(seat.lens) for seat in sent.seats) == sorted(CR_LENSES)


@pytest.mark.parametrize("entry,tier", HEARTBEAT_CASES, ids=_ids(HEARTBEAT_CASES))
def test_ec3e_heartbeat_only_lands_on_the_lane_fallback_board(tmp_path, monkeypatch, request, entry, tier):
    available = ("claude", "codex", "gemini")  # grok down
    h = _harness(tmp_path, monkeypatch, request, repo_files={REPO_REL: _rotated_cr_table(minimum=3)},
                 available=available, policy="heartbeat_only")
    outcome = _drive(h, entry, tier)
    assert outcome.landed is True, outcome.detail
    assert h.build_calls and all(k.get("monitoring_policy") == "heartbeat_only" for k in h.build_calls)
    sent = h.invocations[-1]["board"]
    assert len(sent.seats) == len(CR_LENSES) and {seat.vendor_family for seat in sent.seats} == set(available)
    labels = _labels(outcome.labels)
    assert labels["usable_distinct_vendors"] == 3 and labels["minimum_met"] is True
    assert sorted(labels["fallback_lanes"]) == ["adversarial"]


def test_ec3e_non_landing_advisor_board_seats_only_its_task_lanes_and_labels_them(tmp_path, monkeypatch):
    """A non-landing ``advisor-board --json`` run (no ``--landing-tier``) composes the
    code-review lanes, never today's LENS_CYCLE backfill, and its JSON carries the labels.
    With only Claude up, backfill would add a lens outside the lanes."""
    s = slice1()
    h = _Harness(s, tmp_path, monkeypatch, available=("claude",))
    outcome = _run_cli(h, None)
    assert h.contexts and h.invocations, "the non-landing run built no context"
    sent = h.invocations[-1]["board"]
    assert sorted(str(seat.lens) for seat in sent.seats) == sorted(CR_LENSES)
    assert {seat.vendor_family for seat in sent.seats} == {"claude"}
    labels = _labels(outcome.labels)
    assert sorted(seat["lens"] for seat in labels["seats"]) == sorted(CR_LENSES)
    assert labels["usable_distinct_vendors"] == 1


@pytest.mark.parametrize("available", [("claude", "gemini"), BOARD_VENDORS], ids=["claude-gemini", "all"])
def test_ec3_every_entry_point_composes_the_same_board(tmp_path, monkeypatch, request, available):
    boards = {}
    for entry, tier in LANDING_CASES:
        h = _harness(tmp_path / entry, monkeypatch, request, user=_cr_table(minimum=1), available=available)
        if entry == "run_train":
            request.getfixturevalue("synthetic_train_packet")
        with contextlib.suppress(Exception):  # the board each entry SENT is what is compared
            _drive(h, entry, tier)
        assert h.invocations, f"{entry} never reached invoke_board"
        boards[entry] = [seat_record(seat) for seat in h.invocations[-1]["board"].seats]
    first = next(iter(boards.values()))
    assert all(board == first for board in boards.values()), boards


# =======================================================================================
# ec6h -- the slice-1 lens hook, with lens_frame stubbed in sys.modules (F023)
# =======================================================================================


def _stub_lens_frame(monkeypatch, render: Callable[[object], str] | None) -> None:
    if render is None:
        monkeypatch.setitem(sys.modules, LENS_FRAME, None)
        return
    module = types.ModuleType(LENS_FRAME)
    if render is not False:
        module.render_lens_section = render
    monkeypatch.setitem(sys.modules, LENS_FRAME, module)


def _stub(tag: str) -> Callable[[object], str]:
    return lambda lens: f"\n[{tag} LENS {lens.name}]\n{lens.text}\n"


def _a_lens(s) -> object:
    return s.ResolvedLens(name="correctness", text=s.lens_text["correctness"], kind="built-in")


def test_ec6h_a_stubbed_frame_is_appended_and_labelled_prompt(monkeypatch):
    s = hook()
    _stub_lens_frame(monkeypatch, _stub("STUB"))
    base = pi._resolve_brief("review", None)
    text, label = s.seat_instructions(base, _a_lens(s))
    assert text.startswith(base) and text != base
    assert _stub("STUB")(_a_lens(s)) in text[len(base):]
    assert label == "prompt"


def test_ec6h_an_absent_lens_frame_leaves_the_instructions_metadata_only(monkeypatch):
    s = hook()
    _stub_lens_frame(monkeypatch, None)
    base = pi._resolve_brief("review", None)
    assert s.seat_instructions(base, _a_lens(s)) == (base, "metadata-only")


def test_ec6h_an_empty_section_is_not_labelled_prompt(monkeypatch):
    s = hook()
    _stub_lens_frame(monkeypatch, lambda _lens: "")
    base = pi._resolve_brief("review", None)
    assert s.seat_instructions(base, _a_lens(s)) == (base, "metadata-only")


def test_ec6h_a_present_module_without_the_symbol_propagates(monkeypatch):
    s = hook()
    _stub_lens_frame(monkeypatch, False)  # module exists, attribute absent -> ImportError
    base = pi._resolve_brief("review", None)
    with pytest.raises(ImportError) as excinfo:
        s.seat_instructions(base, _a_lens(s))
    assert not isinstance(excinfo.value, ModuleNotFoundError)


ROUTES = ("brokered", "tui", "native_fill")


def _bound_frame(prompt: str, label: str) -> str:
    """The body of ``prompt``'s digest-bound ``label`` frame, after checking that the frame's
    BEGIN/END delimiters and its metadata line all bind the body's actual sha256 and length."""
    begin = re.search(rf"<<<HARDEN-FRAME {label} BEGIN sha256=([0-9a-f]{{64}}) bytes=([0-9]+)>>>\n", prompt)
    assert begin, f"no digest-bound {label} frame in the outgoing prompt"
    digest, size = begin.group(1), int(begin.group(2))
    end_marker = f"\n<<<HARDEN-FRAME {label} END sha256={digest} bytes={size}>>>"
    stop = prompt.find(end_marker, begin.end())
    assert stop >= 0, f"the {label} frame's END delimiter does not bind the same digest"
    body = prompt[begin.end():stop]
    raw = body.encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == digest, f"the {label} frame's bound digest is not its bytes' digest"
    assert len(raw) == size, f"the {label} frame's bound length is not its byte length"
    assert f"{label} sha256={digest} bytes={size}" in prompt, f"the {label} metadata line binds other bytes"
    return body


def _lane_route(seat) -> str:
    """The route the FIXTURE sends a seat on outside Claude Code: the Claude lane is the
    brokered Claude TUI, every other lane is brokered."""
    return "tui" if str(seat.harness) == "claude" else "brokered"


def seat_deliveries(ctx, recorded) -> dict[str, tuple[str, str]]:
    """Bind each recorded ``deliver_seat_prompt`` call to its seat by the ``seat_key``
    PRODUCTION passed (IF-0-PANEL-1): exactly one delivery per seat of the board, each on
    its lane's route; return ``{seat_key: (instructions frame body, bundle frame body)}``
    with both frames' bound digests checked."""
    board = ctx.composed.board
    keys = [seat.seat_key for seat in board.seats]
    assert len(set(keys)) == len(keys), "fixture precondition: every seat has a distinct seat_key"
    counts = Counter(key for key, _route, _prompt in recorded)
    assert set(counts) == set(keys), f"deliveries for {sorted(counts)}, seats {sorted(keys)}"
    assert all(n == 1 for n in counts.values()), f"a seat was delivered more than once: {counts}"
    routes = {seat.seat_key: _lane_route(seat) for seat in board.seats}
    frames: dict[str, tuple[str, str]] = {}
    for key, route, prompt in recorded:
        assert route == routes[key], f"seat {key} delivered on {route!r}, its lane's route is {routes[key]!r}"
        frames[key] = (_bound_frame(prompt, "AUTHORITATIVE-INSTRUCTIONS"), _bound_frame(prompt, "UNTRUSTED-REVIEW-BUNDLE"))
    return frames


def native_requests(ctx, result) -> dict[str, str]:
    """Bind native fill requests to seats by the request's own ``seat_key``: exactly one
    request per seat the FIXTURE routes to native fill (the Claude lane under Claude Code),
    that seat_key being the ``Seat.seat_key`` keying ``context.composed.seat_lenses``;
    return ``{seat_key: instructions}`` (the instruction channel, never the ``lens`` field)."""
    expected = [seat.seat_key for seat in ctx.composed.board.seats if str(seat.harness) == "claude"]
    assert expected, "fixture precondition: at least one seat is routed to native fill"
    requests = [leg.needs_native_agent for leg in result.legs if leg.needs_native_agent is not None]
    counts = Counter(str(request.seat_key) for request in requests)
    assert counts == Counter(expected), f"native requests for {dict(counts)}, fixture routes {expected}"
    return {str(request.seat_key): request.instructions for request in requests}


def assert_own_lens(ctx, instructions_by_seat: Mapping[str, str], section_of: Callable[[object], str]) -> None:
    """Each seat's OWN lens (``seat_lenses[seat_key]``) is inside ITS OWN instructions: a
    swap of two seats' lenses fails here."""
    for key, instructions in instructions_by_seat.items():
        section = section_of(ctx.composed.seat_lenses[key])
        assert section and section in instructions, f"seat {key}: its own lens section is not in its own instructions"


def route_instructions(ctx, route: str, tmp_path: Path, monkeypatch):
    """Run ``invoke_board`` over ``ctx``; return ``(result, {seat_key: instructions},
    {seat_key: reviewed payload})`` for the seats of ``route``.

    * brokered -- the non-Claude seats; TUI -- the Claude seat(s) outside Claude Code.
      ``invoke_board`` runs its REAL review path. ``panel_invoker.deliver_seat_prompt``
      (IF-0-PANEL-1) is replaced by a recorder: it records ``(seat_key, route, prompt)`` --
      the exact prompt production hands to that seat's transport -- and returns a normal
      verdict WITHOUT calling ``send`` (no transport, no injected exception). Production
      completes and returns a real ``PanelResult``. Deliveries are bound to seats by the
      ``seat_key`` production passes (``seat_deliveries``); the returned instructions and
      payload are the prompt's digest-bound frame bodies.
    * native_fill -- the Claude seat(s) under Claude Code, through the sanctioned hermetic
      control: each ``NativeAgentLegRequest``'s ``seat_key`` binds it to its seat and its
      ``instructions`` is the instruction channel (``native_requests``). The "payload" on
      this route is the artifact file itself.
    """
    board = ctx.composed.board
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    artifact = tmp_path / f"bundle-{route}.md"
    artifact.write_text("the reviewed payload\n", encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", "")}
    if route == "native_fill":
        def no_nested_tui(**_kw):
            raise AssertionError("a Claude TUI was launched under Claude Code")

        monkeypatch.setattr(pi, "_run_claude_tui_session", no_nested_tui)
        scratch = tmp_path / f"scratch-{route}"
        scratch.mkdir()
        env["CLAUDECODE"] = "1"
        result = invoke_sanctioned_review_transport(
            board, "", artifact_ref=str(artifact.resolve()), repo_dir=str(scratch), base_env=env, panel_context=ctx,
        )
        native = native_requests(ctx, result)
        return result, native, {key: artifact.read_text(encoding="utf-8") for key in native}

    recorded: list[tuple[str, str, str]] = []

    def recorder(seat_key, seat_route, prompt, send):
        recorded.append((str(seat_key), str(seat_route), prompt))
        return "OK", f"{seat_key} reviewed\nAGREE"

    monkeypatch.setattr(pi, "deliver_seat_prompt", recorder)
    monkeypatch.chdir(ctx_repo(ctx))  # the review authority is the fixture repository
    result = pi.invoke_board(
        board, artifact.read_text(encoding="utf-8"), repo_dir=ctx_repo(ctx), gateway_available=False,
        base_env=env, panel_context=ctx,
    )
    frames = seat_deliveries(ctx, recorded)
    wanted = {seat.seat_key for seat in board.seats if _lane_route(seat) == route}
    return (result, {key: frames[key][0] for key in wanted}, {key: frames[key][1] for key in wanted})


def route_labels(result) -> dict:
    return {seat["seat_key"]: seat for seat in _labels(result.panel_labels)["seats"]}


def ctx_repo(ctx) -> Path:
    """The fixture repository a ``_context`` context was gated on (set by ``_context``)."""
    repo = _CONTEXT_REPOS.get(id(ctx))
    assert repo is not None, "route observation needs a context built by _context"
    return repo


@pytest.mark.parametrize("route", ROUTES)
def test_ec6h_every_route_carries_the_hook_output_and_label(tmp_path, monkeypatch, route):
    s = hook()
    c = _context(s, tmp_path, monkeypatch)
    _stub_lens_frame(monkeypatch, _stub("STUB"))
    base = pi._resolve_brief("review", None)
    result, seen, _payloads = route_instructions(c.ctx, route, tmp_path, monkeypatch)
    assert_own_lens(c.ctx, seen, _stub("STUB"))
    labels = route_labels(result)
    for key, text in seen.items():
        lens = c.ctx.composed.seat_lenses[key]
        assert text == s.seat_instructions(base, lens)[0]
        assert f"[STUB LENS {lens.name}]" in text
        assert labels[key]["lens_delivery"] == "prompt"


def _swap_fixture(s, harnesses: tuple[str, str]):
    """A context-shaped fixture of two seats with distinct built-in lenses."""
    from phase_loop_runtime.advisor_board.schema import Board, Seat

    lenses = ("adversarial", "red-team")
    seats = tuple(Seat(model="m", effort="high", harness=h, lens=lens) for h, lens in zip(harnesses, lenses))
    seat_lenses = {seat.seat_key: s.ResolvedLens(name=lens, text=s.lens_text[lens], kind="built-in")
                   for seat, lens in zip(seats, lenses)}
    board = Board(name="code-review", purpose="code-review", seats=seats)
    return types.SimpleNamespace(composed=types.SimpleNamespace(board=board, seat_lenses=seat_lenses)), seats


@pytest.mark.parametrize("swapped", [False, True], ids=["own-lenses", "SWAPPED"])
def test_ec6h_the_seat_binding_refuses_a_brokered_lens_swap(swapped):
    """A falsifier for the falsifier: grok's lens in codex's delivered frame and codex's in
    grok's -- each frame still carries SOME seat's section -- fails the per-seat binding."""
    s = hook()
    ctx, (grok, codex) = _swap_fixture(s, ("grok", "codex"))
    base = pi._resolve_brief("review", None)
    render = _stub("STUB")
    lens_of = {seat.seat_key: ctx.composed.seat_lenses[seat.seat_key] for seat in (grok, codex)}
    sent_lens = {grok.seat_key: lens_of[codex.seat_key if swapped else grok.seat_key],
                 codex.seat_key: lens_of[grok.seat_key if swapped else codex.seat_key]}
    recorded = [
        (key, "brokered", pi._render_broker_inline_prompt("payload\n", base + render(sent_lens[key]), "review"))
        for key in (grok.seat_key, codex.seat_key)
    ]
    frames = seat_deliveries(ctx, recorded)
    instructions = {key: body for key, (body, _payload) in frames.items()}
    if swapped:
        with pytest.raises(AssertionError):
            assert_own_lens(ctx, instructions, render)
    else:
        assert_own_lens(ctx, instructions, render)


@pytest.mark.parametrize("swapped", [False, True], ids=["own-lenses", "SWAPPED"])
def test_ec6h_the_native_binding_refuses_a_lens_swap_between_two_native_seats(swapped):
    """The same on native fill: two Claude seats' requests swap their instructions."""
    s = hook()
    ctx, (first, second) = _swap_fixture(s, ("claude", "claude"))
    render = _stub("STUB")
    base = pi._resolve_brief("review", None)
    lens_of = {seat.seat_key: ctx.composed.seat_lenses[seat.seat_key] for seat in (first, second)}
    other = {first.seat_key: second.seat_key, second.seat_key: first.seat_key}
    legs = tuple(
        types.SimpleNamespace(needs_native_agent=types.SimpleNamespace(
            seat_key=key, instructions=base + render(lens_of[other[key] if swapped else key]),
            lens=lens_of[key].name,  # the metadata field is right either way; it is never read
        ))
        for key in (first.seat_key, second.seat_key)
    )
    instructions = native_requests(ctx, types.SimpleNamespace(legs=legs))
    if swapped:
        with pytest.raises(AssertionError):
            assert_own_lens(ctx, instructions, render)
    else:
        assert_own_lens(ctx, instructions, render)


@pytest.mark.parametrize("route", ROUTES)
def test_ec6h_every_route_is_unchanged_and_metadata_only_without_lens_frame(tmp_path, monkeypatch, route):
    s = hook()
    c = _context(s, tmp_path, monkeypatch)
    _stub_lens_frame(monkeypatch, None)
    base = pi._resolve_brief("review", None)
    result, seen, _payloads = route_instructions(c.ctx, route, tmp_path, monkeypatch)
    labels = route_labels(result)
    for key, text in seen.items():
        assert text == base
        assert labels[key]["lens_delivery"] == "metadata-only"
