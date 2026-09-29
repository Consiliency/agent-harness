"""PANEL SL-1 falsifiers (plans/phase-plan-v10-PANEL.md, "SL-1 falsifiers").

Written red in SL-1.1 before any SL-1 production edit; the ``ec<N>`` in each name is the
EC-PANEL goal whose acceptance command selects it. Every name SL-1 introduces is looked up
inside the node, never at import time, so an absent name fails its own node instead of
erroring the whole file.

The ``invoke_board`` nodes go through ``harden_tdd_guard.invoke_sanctioned_review_transport``
(the frozen corpus's sanctioned control). ``harden_tdd_guard.py`` is HARDEN-frozen and is not
edited, so the policy-alignment rule lives in :func:`_strict_landing` here: it coerces the tier
first, and for a valid tier with a context and no ``review_policy`` it expects
``panel_review_policy_required`` with no policy validation and no spawn -- never a
``review_policy_for_tier`` expectation.
"""
from __future__ import annotations

import ast
import contextlib
import dataclasses
import json
import os
import re
import shlex
import subprocess
import tempfile
import textwrap
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from unittest import mock

import pytest

from harden_tdd_guard import invoke_sanctioned_review_transport
from president_fakes import deferring_president
import test_panel_lanes as lanes
from test_panel_lanes import (
    BOARD_VENDORS,
    GOVERNANCE_REL,
    REPO_REL,
    RULING,
    USER_BODY,
    _commit,
    _context,
    _cr_table,
    _git,
    _legs,
    _ok_spawn,
    _repo,
    _rotated_cr_table,
    _stub,
    _stub_lens_frame,
    _user_file,
)

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.panel_invoker import PresidentPolicyError

PRESIDENT_TIERS = ("plan", "production_code")
ALL_TIERS = ("plan", "production_code", "tests_only", "docs_only")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _names() -> types.SimpleNamespace:
    """The SL-1 names, resolved inside each node (a missing one fails only its node)."""
    from phase_loop_runtime.advisor_board import composition, config, presets

    return types.SimpleNamespace(
        config=config,
        composition=composition,
        presets=presets,
        resolve=config.resolve_panel_table,
        snapshot=config.snapshot_panel_run,
        build=config.build_panel_context,
        PanelProbes=config.PanelProbes,
        PanelContext=config.PanelContext,
        PanelRunSnapshot=config.PanelRunSnapshot,
        ExplicitProfileSeats=config.ExplicitProfileSeats,
        BoardConfigError=config.BoardConfigError,
        load_repository_profile=config.load_repository_profile,
        load_user_profile=config.load_user_profile,
        compose=composition.compose_panel_board,
        landing_policy=pi.panel_landing_policy,
        evaluate=pi.evaluate_landing,
    )


# ---------------------------------------------------------------------------------------
# The strict SL-1 wrapper around the sanctioned control (items 6 and 11)


class _Spy:
    """Counts ``_validate_review_board_policy`` calls and seat spawns."""

    def __init__(self, monkeypatch) -> None:
        self.validations = 0
        self.spawns: list[str] = []
        real = lanes._unwrapped(pi._validate_review_board_policy)

        def validate(*args, **kwargs):
            self.validations += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(pi, "_validate_review_board_policy", lanes._mark(validate, real))

    def spawn(self, leg: str, artifact: str):
        self.spawns.append(leg)
        return _ok_spawn()(leg, artifact)


def _strict_landing(board, ctx, tier, spy: _Spy, *, review_policy=None, **extra):
    """Invoke a landing through the sanctioned control, enforcing the SL-1 alignment.

    Returns the result, or the ``PresidentPolicyError`` raised. The tier is coerced FIRST:
    an unknown or falsy tier must be ``review_landing_tier_unknown``; a valid tier with a
    context and no policy must be ``panel_review_policy_required``. Either refusal must come
    with zero policy validations and zero spawns."""
    try:
        coerced = pi._coerce_review_landing_tier(tier)
    except PresidentPolicyError as exc:
        expected = "review_landing_tier_unknown"
        assert exc.code == expected
        coerced = None
    kwargs = {"landing_tier": tier, "panel_context": ctx, **extra}
    if review_policy is not None:
        kwargs["review_policy"] = review_policy
    if coerced is not None and coerced.value in PRESIDENT_TIERS:
        kwargs.setdefault("president_invoke", deferring_president)
    try:
        return invoke_sanctioned_review_transport(board, "artifact", spawn=spy.spawn, **kwargs)
    except PresidentPolicyError as exc:
        if coerced is None:
            assert exc.code == "review_landing_tier_unknown", exc.code
        elif ctx is not None and review_policy is None:
            assert exc.code == "panel_review_policy_required", exc.code
        if exc.code in ("review_landing_tier_unknown", "panel_review_policy_required"):
            assert spy.validations == 0, "a refused landing reached policy validation"
            assert spy.spawns == [], "a refused landing launched a seat"
        return exc


# =======================================================================================
# EC-PANEL-4 -- the landing rules at invoke_board
# =======================================================================================


@pytest.mark.parametrize("tier", ALL_TIERS)
def test_sl1_ec4_invoke_board_refuses_a_context_without_a_policy(tmp_path, monkeypatch, tier):
    s = _names()
    c = _context(s, tmp_path, monkeypatch)
    spy = _Spy(monkeypatch)
    outcome = _strict_landing(c.ctx.composed.board, c.ctx, tier, spy)
    assert isinstance(outcome, PresidentPolicyError), f"{tier}: a context without a policy was accepted"
    assert outcome.code == "panel_review_policy_required"
    assert spy.validations == 0 and spy.spawns == []
    # Direct call (no sanctioned control): the same typed refusal, before anything else.
    with pytest.raises(PresidentPolicyError) as excinfo:
        pi.invoke_board(c.ctx.composed.board, "artifact", landing_tier=tier, panel_context=c.ctx,
                        spawn=spy.spawn)
    assert excinfo.value.code == "panel_review_policy_required"
    assert spy.validations == 0 and spy.spawns == []


@pytest.mark.parametrize("tier", ["", 0, False], ids=["empty", "zero", "false"])
def test_sl1_ec4_a_falsy_landing_tier_is_rejected_not_treated_as_non_landing(tmp_path, monkeypatch, tier):
    s = _names()
    c = _context(s, tmp_path, monkeypatch)
    spy = _Spy(monkeypatch)
    outcome = _strict_landing(c.ctx.composed.board, c.ctx, tier, spy)
    assert isinstance(outcome, PresidentPolicyError) and outcome.code == "review_landing_tier_unknown"
    with pytest.raises(PresidentPolicyError) as excinfo:
        pi.invoke_board(c.ctx.composed.board, "artifact", landing_tier=tier, panel_context=c.ctx,
                        spawn=spy.spawn)
    assert excinfo.value.code == "review_landing_tier_unknown"
    assert spy.validations == 0 and spy.spawns == []


def _lowered(s, table):
    return dataclasses.replace(table, min_distinct_vendors=1)


UNTRUSTED = ["hand-built", "replaced-copy", "mutated-in-place", "hand-built-snapshot", "mutated-snapshot"]


@pytest.mark.parametrize("case", UNTRUSTED)
@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_sl1_ec4_an_untrusted_context_is_refused(tmp_path, monkeypatch, tier, case):
    s = _names()
    c = _context(s, tmp_path, monkeypatch, available=("claude",))
    spy = _Spy(monkeypatch)
    ctx = c.ctx
    if case in ("hand-built-snapshot", "mutated-snapshot"):
        lowered_table = dataclasses.replace(ctx.resolved_table.table, min_distinct_vendors=1)
        if case == "hand-built-snapshot":
            forged = s.PanelRunSnapshot(user_table={"code-review": lowered_table},
                                        user_digest=c.snap.user_digest, user_profile=None)
        else:
            forged = s.snapshot()
            object.__setattr__(forged, "user_table", {"code-review": lowered_table})
        with pytest.raises(s.BoardConfigError):
            s.build("code-review", forged, repo_dir=c.repo, base_revision=c.base, head_revision=None,
                    monitoring_policy="bounded")
        assert spy.spawns == []
        return
    lowered = dataclasses.replace(ctx.resolved_table, table=_lowered(s, ctx.resolved_table.table))
    if case == "hand-built":
        untrusted = s.PanelContext(snapshot=ctx.snapshot, resolved_table=lowered,
                                   explicit_profile=ctx.explicit_profile, composed=ctx.composed,
                                   gated_revision=ctx.gated_revision)
    elif case == "replaced-copy":
        untrusted = dataclasses.replace(ctx, resolved_table=lowered)
    else:
        untrusted = ctx
        object.__setattr__(untrusted, "resolved_table", lowered)
    policy = s.landing_policy(tier, context=untrusted)
    outcome = _strict_landing(untrusted.composed.board, untrusted, tier, spy, review_policy=policy)
    assert isinstance(outcome, PresidentPolicyError), f"{case}: an untrusted context was accepted"
    assert outcome.code == "panel_context_unverified", (case, outcome.code)
    assert spy.spawns == [], f"{case}: a seat launched under an untrusted context"


def test_sl1_ec4_a_trusted_pass_through_context_is_accepted(tmp_path, monkeypatch):
    """Control for the untrusted-context node: the builder's own object, forwarded through
    a pass-through wrapper, lands."""
    s = _names()
    c = _context(s, tmp_path, monkeypatch)
    spy = _Spy(monkeypatch)

    def passthrough(ctx):
        return ctx

    ctx = passthrough(c.ctx)
    result = _strict_landing(ctx.composed.board, ctx, "plan", spy,
                             review_policy=s.landing_policy("plan", context=ctx))
    assert not isinstance(result, BaseException), result
    assert result.landing_decision.admitted is True
    assert spy.validations == 1


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_sl1_ec4_evaluate_landing_refuses_a_policy_that_is_not_the_contexts(tmp_path, monkeypatch, tier):
    s = _names()
    c = _context(s, tmp_path, monkeypatch)
    legs = tuple(leg for leg in _legs(c.ctx.composed.board) if leg.usable)
    todays = pi.review_policy_for_tier(tier)
    decision = s.evaluate(todays, usable_legs=legs, president_ruling=RULING, context=c.ctx,
                          user_digest_now=c.snap.user_digest)
    assert decision.admitted is False, "today's floor-0 policy was admitted against a context"
    control = s.evaluate(s.landing_policy(tier, context=c.ctx), usable_legs=legs, president_ruling=RULING,
                         context=c.ctx, user_digest_now=c.snap.user_digest)
    assert control.admitted is True


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_sl1_ec4_injected_probes_are_refused_on_a_landing(tmp_path, monkeypatch, tier):
    s = _names()
    _user_file(tmp_path, monkeypatch)
    repo, base = _repo(tmp_path)
    probes = s.PanelProbes(is_available=lambda v: True, auth_ok=lambda v: True, preflight=lambda v: True)
    ctx = s.build("code-review", s.snapshot(), repo_dir=repo, base_revision=base, head_revision=None,
                  monitoring_policy="bounded", probes=probes)
    spy = _Spy(monkeypatch)
    outcome = _strict_landing(ctx.composed.board, ctx, tier, spy,
                              review_policy=s.landing_policy(tier, context=ctx))
    assert isinstance(outcome, PresidentPolicyError) and outcome.code == "panel_probes_injected"
    assert spy.spawns == []
    # A non-landing run with injected probes is allowed.
    result = invoke_sanctioned_review_transport(ctx.composed.board, "artifact", spawn=spy.spawn,
                                                panel_context=ctx)
    assert spy.spawns, "a non-landing run with injected probes launched nothing"
    assert result.landing_decision is None


PROFILE_CASES = [
    ("repository", "parse-error", "[tiers.plan\npanel = \n", "error"),
    ("repository", "not-a-list", '[tiers.plan]\npanel = 7\n', "error"),
    ("repository", "unknown-alias", '[tiers.plan]\npanel = ["fable", "nobody"]\n', "error"),
    ("user", "parse-error", "[tiers.plan\npanel = \n", "error"),
    ("user", "unknown-alias", '[tiers.plan]\npanel = ["nobody"]\n', "error"),
    ("user", "unreadable", None, "error"),
]


@pytest.mark.parametrize("where,case_id,body,expected", PROFILE_CASES, ids=[f"{w}-{c}" for w, c, _b, _e in PROFILE_CASES])
def test_sl1_ec4_a_malformed_or_none_profile_fails_closed(tmp_path, monkeypatch, where, case_id, body, expected):
    s = _names()
    user = _user_file(tmp_path, monkeypatch)
    profile_path = user.parent / "governance.toml"
    if where == "repository":
        repo, base = _repo(tmp_path, {GOVERNANCE_REL: body})
        with pytest.raises(s.BoardConfigError):
            s.load_repository_profile(repo, base_revision=base, tier="plan")
    else:
        if body is None:
            profile_path.mkdir()  # a directory where the file should be: unreadable
        else:
            profile_path.write_text(body, encoding="utf-8")
        with pytest.raises(s.BoardConfigError):
            s.load_user_profile(tier="plan")


@pytest.mark.parametrize("tier", ALL_TIERS)
def test_sl1_ec4_a_none_profile_is_refused_where_seats_are_required(tmp_path, monkeypatch, tier):
    s = _names()
    user = _user_file(tmp_path, monkeypatch)
    body = f'[tiers.{tier}]\npanel = "none"\n'
    repo, base = _repo(tmp_path, {GOVERNANCE_REL: body})
    (user.parent / "governance.toml").write_text(body, encoding="utf-8")
    if tier in PRESIDENT_TIERS:
        with pytest.raises(s.BoardConfigError):
            s.load_repository_profile(repo, base_revision=base, tier=tier)
        with pytest.raises(s.BoardConfigError):
            s.load_user_profile(tier=tier)
    else:
        assert s.load_repository_profile(repo, base_revision=base, tier=tier) is None
        assert s.load_user_profile(tier=tier) is None


def test_sl1_ec4_an_absent_profile_means_no_explicit_seats(tmp_path, monkeypatch):
    s = _names()
    _user_file(tmp_path, monkeypatch)
    repo, base = _repo(tmp_path)
    assert s.load_repository_profile(repo, base_revision=base, tier="plan") is None
    assert s.load_user_profile(tier="plan") is None
    good_repo, good_base = _repo(tmp_path / "g", {GOVERNANCE_REL: '[tiers.plan]\npanel = ["fable", "grok"]\n'})
    profile = s.load_repository_profile(good_repo, base_revision=good_base, tier="plan")
    assert tuple(profile.seats) == ("fable", "grok")
    assert profile.path == GOVERNANCE_REL and profile.provenance == good_base


# =======================================================================================
# EC-PANEL-1 -- a user-file edit during the run is refused (B-A)
# =======================================================================================


def _edit(path: Path) -> None:
    path.write_text(path.read_text(encoding="utf-8") + "# edited mid-run\n", encoding="utf-8")


def _not_admitted(run) -> bool:
    try:
        result = run()
    except PresidentPolicyError:
        return True
    decision = getattr(result, "landing_decision", None)
    return decision is None or decision.admitted is False


@pytest.mark.parametrize("timing", ["first-seat", "president"])
def test_sl1_ec1_a_user_file_edit_during_the_run_is_refused_at_invoke_board(tmp_path, monkeypatch, timing):
    s = _names()
    c = _context(s, tmp_path, monkeypatch, user=USER_BODY)
    policy = s.landing_policy("plan", context=c.ctx)
    edited: list[bool] = []

    def spawn(leg, artifact):
        if timing == "first-seat" and not edited:
            edited.append(True)
            _edit(c.user_path)
        return _ok_spawn()(leg, artifact)

    def president(model, prompt):
        if timing == "president" and not edited:
            edited.append(True)
            _edit(c.user_path)
        return deferring_president(model, prompt)

    control = invoke_sanctioned_review_transport(
        c.ctx.composed.board, "artifact", spawn=_ok_spawn(), landing_tier="plan", panel_context=c.ctx,
        review_policy=policy, president_invoke=deferring_president)
    assert control.landing_decision.admitted is True
    assert _not_admitted(lambda: invoke_sanctioned_review_transport(
        c.ctx.composed.board, "artifact", spawn=spawn, landing_tier="plan", panel_context=c.ctx,
        review_policy=policy, president_invoke=president))
    assert edited, "the edit never happened"


ENTRY_TIMINGS = [(entry, timing) for entry in ("governed_gate", "advisor_board") for timing in ("first-seat", "president")]


@pytest.mark.parametrize("entry,timing", ENTRY_TIMINGS, ids=[f"{e}-{t}" for e, t in ENTRY_TIMINGS])
def test_sl1_ec1_a_user_file_edit_during_the_run_is_refused_at_the_non_merging_entries(
        tmp_path, monkeypatch, request, entry, timing):
    control = lanes._Harness(lanes._names(), tmp_path / "control", monkeypatch)
    assert lanes._drive(control, entry, "plan").landed is True
    h = lanes._Harness(lanes._names(), tmp_path / "edited", monkeypatch)
    if timing == "first-seat":
        h.during_seats.append(h.edit_user_file)
    else:
        fired: list[bool] = []

        def president(model, prompt):
            if not fired:
                fired.append(True)
                h.edit_user_file()
            return deferring_president(model, prompt)

        monkeypatch.setattr(lanes, "deferring_president", president)
    outcome = lanes._drive(h, entry, "plan")
    assert outcome.landed is False, outcome.detail


# =======================================================================================
# EC-PANEL-3 -- the builder's probe seam
# =======================================================================================


def test_sl1_ec3_build_panel_context_uses_the_injected_probes(tmp_path, monkeypatch):
    s = _names()
    from phase_loop_runtime import executor_availability, gemini_heartbeat
    from phase_loop_runtime.advisor_board import registries

    def untouched(*_a, **_k):
        raise AssertionError("a host probe leaf was touched although probes were injected")

    monkeypatch.setattr(registries.DEFAULT_HARNESS_REGISTRY, "probe", untouched)
    monkeypatch.setattr(executor_availability, "_probes_pass", untouched)
    monkeypatch.setattr(gemini_heartbeat, "require_capability", untouched)
    _user_file(tmp_path, monkeypatch, _rotated_cr_table(minimum=1))
    repo, base = _repo(tmp_path)
    up = {"codex", "gemini"}
    probes = s.PanelProbes(is_available=lambda v: v in up, auth_ok=lambda v: v != "gemini",
                           preflight=lambda v: True)
    for policy in ("bounded", "heartbeat_only"):
        ctx = s.build("code-review", s.snapshot(), repo_dir=repo, base_revision=base, head_revision=None,
                      monitoring_policy=policy, probes=probes)
        assert {seat.vendor_family for seat in ctx.composed.board.seats} == {"codex"}, policy
        assert len(ctx.composed.board.seats) == 4


# =======================================================================================
# EC-PANEL-6 (item 4) -- each seat bound to its own instruction digest
# =======================================================================================


def _authorized_board(s, tmp_path, harnesses):
    from phase_loop_runtime.advisor_board import backing
    from phase_loop_runtime.advisor_board.schema import Board, Seat

    lens_names = ("adversarial", "red-team")
    models = {"grok": "grok-4.7", "codex": "gpt-6-astra", "claude": "claude-opus-5-5", "gemini": "gemini-3.8-flash"}
    seats = tuple(Seat(model=models[h], effort="max" if h != "gemini" else "high", harness=h, lens=lens)
                  for h, lens in zip(harnesses, lens_names))
    board = Board(name="code-review", purpose="code-review", seats=seats)
    base = pi._resolve_brief("review", None)
    lens_text = s.presets.BUILTIN_LENS_TEXT
    instructions = {
        seat.seat_key: pi._seat_instructions(base, s.config.ResolvedLens(name=seat.lens, text=lens_text[seat.lens],
                                                                         kind="built-in"))[0]
        for seat in seats
    }
    repo, _base_rev = _repo(tmp_path)
    token = backing.set_review_instruction_digest(base)
    try:
        parent = backing.prepare_review_isolation_authorization(board, "artifact", mode="review",
                                                                canonical_repo_authority=repo,
                                                                stage_review_tree=False)
    finally:
        backing.reset_review_instruction_digest(token)
    children = backing.derive_seat_instruction_authorizations(parent, instructions)
    return backing, board, seats, instructions, children, repo


def _staged(tmp_path: Path, name: str, instructions: str) -> Path:
    stage = tmp_path / name
    stage.mkdir()
    (stage / "review-bundle.md").write_text("artifact", encoding="utf-8")
    (stage / "review-instructions.md").write_text(instructions, encoding="utf-8")
    for f in stage.iterdir():
        f.chmod(0o400)
    return stage


@pytest.mark.parametrize("harnesses", [("grok", "codex"), ("codex", "codex")], ids=["two-vendors", "same-harness"])
def test_sl1_ec6_each_seat_is_bound_to_its_own_instruction_digest(tmp_path, monkeypatch, harnesses):
    s = _names()
    _stub_lens_frame(monkeypatch, _stub("STUB"))
    backing, board, seats, instructions, children, repo = _authorized_board(s, tmp_path, harnesses)
    first, second = seats
    assert instructions[first.seat_key] != instructions[second.seat_key], "fixture: distinct lens instructions"
    for seat in seats:
        auth = children[seat.seat_key]
        stage = _staged(tmp_path, f"own-{seat.lens}", instructions[seat.seat_key])
        backing.revalidate_review_isolation_authorization(auth, None, "artifact", mode="review",
                                                          canonical_repo_authority=repo, staged_dir=stage)
    # A swap: each seat's authorization against the OTHER seat's staged instructions.
    for seat, other in ((first, second), (second, first)):
        stage = _staged(tmp_path, f"swap-{seat.lens}", instructions[other.seat_key])
        with pytest.raises(ValueError):
            backing.revalidate_review_isolation_authorization(
                children[seat.seat_key], None, "artifact", mode="review",
                canonical_repo_authority=repo, staged_dir=stage)
    # A seat cannot derive its leg from another seat's authorization.
    with pytest.raises(ValueError):
        backing.check_seat_instruction_binding(children[first.seat_key], second.seat_key)
    backing.check_seat_instruction_binding(children[first.seat_key], first.seat_key)


def test_sl1_ec6_a_single_instruction_set_keeps_one_authorization(tmp_path, monkeypatch):
    """Slice 1 without lens_frame: every seat shares the base brief, so no child is derived
    and the parent authorization is used unchanged (the HARDEN guard's one factory call)."""
    s = _names()
    _stub_lens_frame(monkeypatch, None)
    backing, board, seats, instructions, children, repo = _authorized_board(s, tmp_path, ("grok", "codex"))
    assert len(set(instructions.values())) == 1
    assert len({id(a) for a in children.values()}) == 1


# =======================================================================================
# EC-PANEL-1 -- merge_guard (item 7); see the merge_guard section below
# =======================================================================================

import copy


def _mg():
    from phase_loop_runtime import merge_guard

    return merge_guard


_SLUG = "github.com/o/r"


class _FakeGitHub:
    """A fake ``gh`` behind ``merge_guard._spawn``; ``git`` runs for real (and is recorded).

    The PR is #1 with head ``branch``. ``merge_mode`` decides what ``gh pr merge`` does:
    ``merge`` (a real merge commit pushed to origin main), ``enqueue`` (stays OPEN, queued),
    ``enqueue-late`` (stays OPEN; the queue entry becomes visible only on a later read),
    ``reject`` (exit 1, stays OPEN), ``merge-then-error`` (merged, exit 1), ``retarget``
    (merged into ``release``), ``base-moved`` (origin main advances first, then merges),
    ``unreadable-merge`` (MERGED with no readable merge commit)."""

    def __init__(self, t, *, branch: str = "change") -> None:
        self.t = t
        self.branch = branch
        self.calls: list[list[str]] = []
        self.base_ref = "main"
        self.head_override: str | None = None
        self.state = "OPEN"
        self.merge_commit: str | None = None
        self.merge_mode = "merge"
        self.rulesets: list | None = []  # None -> unreadable
        self.classic: dict | None = None  # None -> 404 (unprotected); {"__error__": 1} -> unreadable
        self.queued = False
        self.late_queue_reads = 0
        self.auto_merge = False
        self.dequeue_fails = False
        self.open_prs_by_head: dict[str, dict] = {}
        self.before_push: Callable[[], None] | None = None

    # -- helpers ------------------------------------------------------------------------
    def head(self) -> str:
        return self.head_override or self.t.change_head

    def _done(self, rc=0, out="", err=""):
        return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)

    def _real_merge(self, base_branch: str = "main") -> str:
        up = self.t.upstream
        _git(up, "fetch", "-q", "origin")
        _git(up, "checkout", "-q", "-B", base_branch, f"origin/{base_branch}")
        _git(up, "merge", "-q", "--no-ff", "-m", "merge pr 1", f"origin/{self.branch}")
        _git(up, "push", "-q", "origin", f"HEAD:refs/heads/{base_branch}")
        return _git(up, "rev-parse", "HEAD")

    # -- the fake -----------------------------------------------------------------------
    def __call__(self, argv, **kwargs):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if os.path.basename(argv[0]) != "gh":
            if "push" in argv and self.before_push is not None:
                hook, self.before_push = self.before_push, None
                hook()
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            env.update(kwargs.get("env") or {})
            done = subprocess.run(argv, cwd=kwargs.get("cwd"), capture_output=True, text=True, env=env,
                                  input=kwargs.get("input"))
            return done
        rest = argv[1:]
        joined = " ".join(rest)
        if rest[:2] == ["repo", "view"]:
            return self._done(0, json.dumps({"defaultBranchRef": {"name": "main"}, "nameWithOwner": "o/r"}))
        if rest[:1] == ["api"]:
            if "graphql" in rest:
                if "dequeuePullRequest" in joined:
                    if self.dequeue_fails:
                        return self._done(0, json.dumps({"errors": [{"message": "no"}]}))
                    self.queued = False
                    return self._done(0, json.dumps({"data": {"dequeuePullRequest": {"clientMutationId": None}}}))
                if "isInMergeQueue" in joined:
                    if self.merge_mode == "enqueue-late" and self.late_queue_reads == 0:
                        self.late_queue_reads += 1
                        return self._done(0, json.dumps({"data": {"repository": {"pullRequest": {"isInMergeQueue": False}}}}))
                    return self._done(0, json.dumps({"data": {"repository": {"pullRequest": {"isInMergeQueue": self.queued}}}}))
                return self._done(1, "", "unknown graphql")
            if "rules/branches" in joined:
                if self.rulesets is None:
                    return self._done(1, "", "HTTP 500")
                return self._done(0, json.dumps(self.rulesets))
            if "/protection" in joined:
                if self.classic is None:
                    return self._done(1, "", "gh: Branch not protected (HTTP 404)")
                if "__error__" in self.classic:
                    return self._done(1, "", "HTTP 500")
                return self._done(0, json.dumps(self.classic))
            return self._done(1, "", "unexpected api call")
        if rest[:2] == ["pr", "view"]:
            data = {
                "id": "PR_node_1", "number": 1, "baseRefName": self.base_ref, "headRefOid": self.head(),
                "headRefName": self.branch, "headRepository": {"name": "r", "owner": {"login": "o"}},
                "headRepositoryOwner": {"login": "o"}, "url": "https://github.com/o/r/pull/1",
                "state": self.state, "isDraft": False,
                "mergeCommit": {"oid": self.merge_commit} if self.merge_commit else None,
                "autoMergeRequest": {"enabledAt": "t"} if self.auto_merge else None,
            }
            return self._done(0, json.dumps(data))
        if rest[:2] == ["pr", "list"]:
            head = rest[rest.index("--head") + 1] if "--head" in rest else None
            prs = [pr for name, pr in self.open_prs_by_head.items() if head in (None, name)]
            return self._done(0, json.dumps(prs))
        if rest[:2] == ["pr", "merge"]:
            if "--disable-auto" in rest:
                self.auto_merge = False
                return self._done(0)
            mode = self.merge_mode
            if mode in ("enqueue", "enqueue-late"):
                self.queued = True
                return self._done(0)
            if mode == "reject":
                return self._done(1, "", "Head branch was modified")
            if mode == "base-moved":
                self.t.push_target({"other.txt": "moved\n"}, "moved base")
            if mode == "retarget":
                _git(self.t.upstream, "fetch", "-q", "origin")
                _git(self.t.upstream, "push", "-q", "origin", "origin/main:refs/heads/release")
                self.base_ref = "release"
                self.merge_commit = self._real_merge("release")
            else:
                self.merge_commit = self._real_merge()
            self.state = "MERGED"
            if mode == "unreadable-merge":
                self.merge_commit = None
            return self._done(1 if mode == "merge-then-error" else 0, "", "error" if mode == "merge-then-error" else "")
        if rest[:2] in (["pr", "create"], ["pr", "comment"], ["pr", "edit"], ["pr", "ready"],
                        ["issue", "create"], ["issue", "comment"]):
            return self._done(0, "https://github.com/o/r/pull/2\n")
        return self._done(1, "", f"fake gh: unhandled {joined}")

    # -- classification -----------------------------------------------------------------
    def primitives(self) -> list[list[str]]:
        return [c for c in self.calls if _mutation_kind(c) is not None or c[1:3] == ["pr", "ready"]]

    def guarded_io(self) -> list[list[str]]:
        return [c for c in self.calls if "fetch" in c or any("rules/branches" in a or "/protection" in a for a in c)]


class _Landing:
    """A decided governed landing over a real origin: context gated at origin main, a
    decision from invoke_board (sanctioned control), and the fake GitHub installed."""

    def __init__(self, tmp_path: Path, monkeypatch, *, pr: bool = True, head_revision: object = "change",
                 reviewed_head: object = "change", land: bool = True, cross_checks: bool = True) -> None:
        self.s = _names()
        self.mg = _mg()
        self.mp = monkeypatch
        self.tmp = tmp_path
        self.user = _user_file(tmp_path, monkeypatch, USER_BODY)
        self.t = lanes._TargetRepo(tmp_path, "mg", {})
        _git(self.t.path, "push", "-q", "origin", "change")
        self.gh = _FakeGitHub(self.t)
        monkeypatch.setattr(self.mg, "_spawn", self.gh)
        monkeypatch.setattr(self.mg, "_repo_slug", lambda repo_dir: _SLUG)
        monkeypatch.delenv("PHASE_LOOP_RUN_MODE", raising=False)
        lanes._ForcedProbes(self.s, monkeypatch)
        _git(self.t.path, "fetch", "-q", "origin")
        self.b0 = _git(self.t.path, "rev-parse", "origin/main")
        self.snap = self.s.snapshot()
        head = self.t.change_head if head_revision == "change" else head_revision
        self.ctx = self.s.build("code-review", self.snap, repo_dir=self.t.path, base_revision=self.b0,
                                head_revision=head, monitoring_policy="bounded")
        self.pr = pr
        self.decision = None
        self.result = None
        if land:
            self.decide(reviewed_head=self.t.change_head if reviewed_head == "change" else reviewed_head,
                        cross_checks=cross_checks)

    def decide(self, *, reviewed_head, cross_checks=True, ctx=None):
        ctx = ctx or self.ctx
        extra = {}
        if cross_checks:
            extra = {"target_branch": "main", "reviewed_head": reviewed_head}
            if self.pr:
                extra["reviewed_pr"] = 1
        self.result = invoke_sanctioned_review_transport(
            ctx.composed.board, "artifact", spawn=_ok_spawn(), landing_tier="plan", panel_context=ctx,
            review_policy=self.s.landing_policy("plan", context=ctx), president_invoke=deferring_president,
            repo_dir=str(self.t.path), **extra)
        self.decision = self.result.landing_decision
        return self.decision

    def action(self, **over):
        if self.pr:
            fields = {"repo_slug": _SLUG, "pr_number": 1, "head_sha": self.t.change_head,
                      "target_branch": "main", "context": self.ctx}
            fields.update(over)
            return self.mg.GhPrMerge(**fields)
        fields = {"remote": str(self.t.origin), "target_branch": "main", "commit": self.t.change_head,
                  "context": self.ctx}
        fields.update(over)
        return self.mg.GitPush(**fields)

    def merge(self, authority=..., action=None, repo_dir=None):
        return self.mg.guarded_merge(Path(repo_dir or self.t.path),
                                     authority=self.decision if authority is ... else authority,
                                     action=action or self.action())


def _refused_before_any_attempt(land: _Landing, run, *, before_guarded_io: bool = False):
    mg = land.mg
    land.gh.calls.clear()
    with pytest.raises((mg.MergeGuardRefusal, mg.MergeGuardEscalation)) as excinfo:
        run()
    assert land.gh.primitives() == [], f"a primitive was attempted: {land.gh.primitives()}"
    if before_guarded_io:
        assert land.gh.guarded_io() == [], f"guarded I/O ran before the authority check: {land.gh.guarded_io()}"
    return excinfo.value


SITES = ["pr-merge", "push"]


def _site(tmp_path, monkeypatch, site, **kw) -> _Landing:
    return _Landing(tmp_path, monkeypatch, pr=(site == "pr-merge"), **kw)


@pytest.mark.parametrize("site", SITES)
def test_sl1_ec1_a_decided_landing_merges_once(tmp_path, monkeypatch, site):
    """Control for every refusal below: a registered, bound decision merges exactly once."""
    land = _site(tmp_path, monkeypatch, site)
    assert land.decision is not None and land.decision.admitted is True
    sha = land.merge()
    assert sha
    assert len(land.gh.primitives()) == 1
    if site == "push":
        assert _git(land.t.upstream, "ls-remote", str(land.t.origin), "refs/heads/main").split()[0] == land.t.change_head
    # A consumed decision cannot merge again.
    _refused_before_any_attempt(land, lambda: land.merge())


REFUSAL_CASES = [
    "decision-absent", "bare-context", "context-mutated-after-decision", "context-rebuilt",
    "refused-landing-decision", "non-landing-call", "no-bindings", "fresh-process-resume",
    "head-substitution", "repo-substitution", "target-substitution", "direct-evaluate",
    "hand-built-decision", "replaced-decision", "retired-retry", "context-for-other-head",
    "context-head-none", "regate-panel-change", "regate-profile-change", "regate-retry",
    "regate-raises", "gated-not-ancestor", "fetch-failed", "user-file-changed",
    "queue-ruleset", "queue-classic", "rules-unreadable", "classic-unreadable",
]
PR_ONLY_CASES = ["pr-retargeted", "pr-substitution", "cross-check-mismatch", "pr-head-advanced-before-decision"]
AUTHORITY_CASES = {"decision-absent", "bare-context", "refused-landing-decision", "non-landing-call",
                   "fresh-process-resume", "direct-evaluate", "hand-built-decision", "replaced-decision"}


def _refusal_case(land: _Landing, case: str):
    """Returns the zero-argument call that must be refused."""
    s, mg, t = land.s, land.mg, land.t
    if case == "decision-absent":
        return lambda: land.merge(authority=None)
    if case == "bare-context":
        return lambda: land.merge(authority=land.ctx)
    if case == "context-mutated-after-decision":
        object.__setattr__(land.ctx, "gated_revision", "0" * 40)
        return lambda: land.merge()
    if case == "context-rebuilt":
        rebuilt = s.build("code-review", land.snap, repo_dir=t.path, base_revision=land.b0,
                          head_revision=t.change_head, monitoring_policy="bounded")
        return lambda: land.merge(action=land.action(context=rebuilt))
    if case == "refused-landing-decision":
        refused = invoke_sanctioned_review_transport(
            land.ctx.composed.board, "artifact", spawn=_ok_spawn(set(BOARD_VENDORS)), landing_tier="plan",
            panel_context=land.ctx, review_policy=s.landing_policy("plan", context=land.ctx),
            president_invoke=deferring_president, repo_dir=str(t.path), target_branch="main",
            reviewed_head=t.change_head, **({"reviewed_pr": 1} if land.pr else {}))
        assert refused.landing_decision.admitted is False
        return lambda: land.merge(authority=refused.landing_decision)
    if case == "non-landing-call":
        result = invoke_sanctioned_review_transport(land.ctx.composed.board, "artifact", spawn=_ok_spawn(),
                                                    panel_context=land.ctx)
        return lambda: land.merge(authority=result.landing_decision)
    if case == "no-bindings":
        land.decide(reviewed_head=t.change_head, cross_checks=False)
        assert land.decision.admitted is True
        return lambda: land.merge()
    if case == "fresh-process-resume":
        return lambda: land.merge(authority=copy.deepcopy(land.decision))
    if case == "head-substitution":
        h2 = land.t.change({"src.py": "change = 2\n"}, "H2 descends from B0")
        _git(t.path, "push", "-q", "-f", "origin", "change")
        return lambda: land.merge(action=land.action(**({"head_sha": h2} if land.pr else {"commit": h2})))
    if case == "repo-substitution":
        other = lanes._TargetRepo(land.tmp / "other", "mg", {})
        return lambda: land.merge(repo_dir=other.path)
    if case == "target-substitution":
        return lambda: land.merge(action=land.action(target_branch="release"))
    if case == "direct-evaluate":
        legs = tuple(leg for leg in _legs(land.ctx.composed.board) if leg.usable)
        direct = s.evaluate(s.landing_policy("plan", context=land.ctx), usable_legs=legs, president_ruling=RULING,
                            context=land.ctx, user_digest_now=land.snap.user_digest)
        assert direct.admitted is True
        return lambda: land.merge(authority=direct)
    if case == "hand-built-decision":
        forged = dataclasses.replace(land.decision)
        return lambda: land.merge(authority=type(land.decision)(**{f.name: getattr(forged, f.name)
                                                                   for f in dataclasses.fields(forged)}))
    if case == "replaced-decision":
        return lambda: land.merge(authority=dataclasses.replace(land.decision))
    if case == "retired-retry":
        land.gh.rulesets = None  # the first attempt is refused (rules unreadable) and retires it
        with pytest.raises(mg.MergeGuardRefusal):
            land.merge()
        land.gh.rulesets = []
        return lambda: land.merge()
    if case == "context-for-other-head":
        reviewed = t.change_head
        other_head = _commit(t.path, {"src.py": "change = 3\n"}, "another head")
        _git(t.path, "reset", "-q", "--hard", reviewed)
        ctx = s.build("code-review", land.snap, repo_dir=t.path, base_revision=land.b0,
                      head_revision=other_head, monitoring_policy="bounded")
        land.ctx = ctx
        land.decide(reviewed_head=reviewed, ctx=ctx)
        return lambda: land.merge()
    if case == "context-head-none":
        ctx = s.build("code-review", land.snap, repo_dir=t.path, base_revision=land.b0, head_revision=None,
                      monitoring_policy="bounded")
        land.ctx = ctx
        land.decide(reviewed_head=t.change_head, ctx=ctx)
        return lambda: land.merge()
    if case in ("regate-panel-change", "regate-retry"):
        t.push_target({REPO_REL: _cr_table(minimum=2)}, "a [panel.*] change after the gate")
        if case == "regate-retry":
            with pytest.raises(mg.MergeGuardRefusal):
                land.merge()
        return lambda: land.merge()
    if case == "regate-profile-change":
        t.push_target({GOVERNANCE_REL: '[tiers.plan]\npanel = ["fable", "sol", "gemini", "grok"]\n'}, "profile")
        return lambda: land.merge()
    if case == "regate-raises":
        def boom(*a, **k):
            raise s.BoardConfigError("regate unreadable")

        land.mp.setattr(s.config, "panel_regate_required", boom)
        return lambda: land.merge()
    if case == "gated-not-ancestor":
        _git(t.upstream, "checkout", "-q", "--orphan", "rewrite")
        _commit(t.upstream, {"README.md": "rewritten\n"}, "unrelated history")
        _git(t.upstream, "push", "-q", "-f", "origin", "HEAD:refs/heads/main")
        return lambda: land.merge()
    if case == "fetch-failed":
        t.origin.rename(t.origin.with_name("moved.git"))
        return lambda: land.merge()
    if case == "user-file-changed":
        _edit(land.user)
        return lambda: land.merge()
    if case == "queue-ruleset":
        land.gh.rulesets = [{"type": "merge_queue"}]
        return lambda: land.merge()
    if case == "queue-classic":
        land.gh.classic = {"required_merge_queue": {"enabled": True}}
        return lambda: land.merge()
    if case == "rules-unreadable":
        land.gh.rulesets = None
        return lambda: land.merge()
    if case == "classic-unreadable":
        land.gh.classic = {"__error__": 1}
        return lambda: land.merge()
    if case == "pr-retargeted":
        land.gh.base_ref = "release"
        return lambda: land.merge()
    if case == "pr-substitution":
        return lambda: land.merge(action=land.action(pr_number=2))
    if case in ("cross-check-mismatch", "pr-head-advanced-before-decision"):
        land.gh.head_override = "f" * 40  # the live PR head is not the review packet's head
        land.decide(reviewed_head=t.change_head)
        land.gh.head_override = None
        return lambda: land.merge()
    raise AssertionError(case)


EVERY_REFUSAL = [(site, case) for site in SITES for case in REFUSAL_CASES] + [("pr-merge", c) for c in PR_ONLY_CASES]


@pytest.mark.parametrize("site,case", EVERY_REFUSAL, ids=[f"{s}-{c}" for s, c in EVERY_REFUSAL])
def test_sl1_ec1_every_merge_site_refuses_before_any_attempt(tmp_path, monkeypatch, site, case):
    land = _site(tmp_path, monkeypatch, site)
    run = _refusal_case(land, case)
    refusal = _refused_before_any_attempt(land, run, before_guarded_io=case in AUTHORITY_CASES)
    if case.startswith("queue-"):
        assert refusal.code == "panel_merge_queue_target"
    if case in ("rules-unreadable", "classic-unreadable"):
        assert refusal.code == "panel_merge_queue_unknown"
    if case in AUTHORITY_CASES:
        assert refusal.code == "panel_merge_authority_missing", refusal.code


NO_LANDING_CASES = ["governed-run-mode", "unreadable-run-mode", "after-a-landing-call"]


@pytest.mark.parametrize("case", NO_LANDING_CASES)
@pytest.mark.parametrize("site", SITES)
def test_sl1_ec1_a_no_landing_token_is_refused_on_a_landing_path(tmp_path, monkeypatch, site, case):
    land = _site(tmp_path, monkeypatch, site, land=(case == "after-a-landing-call"))
    mg = land.mg
    if case == "governed-run-mode":
        monkeypatch.setenv("PHASE_LOOP_RUN_MODE", "governed")
    elif case == "unreadable-run-mode":
        monkeypatch.setenv("PHASE_LOOP_RUN_MODE", "governd")
    token = mg.mint_no_landing_token()
    refusal = _refused_before_any_attempt(land, lambda: land.merge(authority=token), before_guarded_io=True)
    assert refusal.code == "panel_merge_authority_missing"


def test_sl1_ec1_a_no_landing_token_forged_is_refused(tmp_path, monkeypatch):
    land = _site(tmp_path, monkeypatch, "pr-merge", land=False)
    mg = land.mg
    forged = object.__new__(mg.NoLandingToken)
    _refused_before_any_attempt(land, lambda: land.merge(authority=forged), before_guarded_io=True)


def test_sl1_ec1_the_no_landing_path_keeps_todays_argv_byte_for_byte(tmp_path, monkeypatch):
    """Autonomous run mode, a minted NoLandingToken: the merge argv is today's
    ``train_runner._live_merge_pr`` argv exactly, and the push argv is today's closeout push."""
    land = _site(tmp_path, monkeypatch, "pr-merge", land=False)
    mg = land.mg
    token = mg.mint_no_landing_token()
    land.mg.guarded_merge(land.t.path, authority=token,
                          action=mg.LegacyPrMerge(branch="change", repo_args=("--repo", _SLUG),
                                                  head_sha=land.t.change_head, delete_branch=True,
                                                  cwd=str(land.t.path), env=None))
    merges = [c for c in land.gh.calls if c[1:3] == ["pr", "merge"]]
    assert merges == [["gh", "pr", "merge", "change", "--repo", _SLUG, "--merge", "--delete-branch",
                       "--match-head-commit", land.t.change_head]]
    token2 = mg.mint_no_landing_token()
    land.gh.calls.clear()
    _git(land.t.path, "checkout", "-q", "change")
    mg.guarded_merge(land.t.path, authority=token2,
                     action=mg.LegacyPush(remote="origin", refspec=f"{land.t.change_head}:refs/heads/closeout",
                                          cwd=str(land.t.path)))
    pushes = [c for c in land.gh.calls if "push" in c]
    # Today's remote and refspec exactly; the hook suppression every merge_guard git call
    # carries (plan item 7) is the one addition.
    assert pushes and pushes[0][-4:] == ["push", "--no-verify", "origin", f"{land.t.change_head}:refs/heads/closeout"]
    assert pushes[0][1:3] == ["-c", "core.hooksPath=/dev/null"]


POST_ATTEMPT = ["enqueued", "enqueue-visible-late", "dequeue-failed", "lease-rejected", "match-head-rejected",
                "merged-then-cli-error", "retarget-after-read", "base-moved", "unreadable-merge"]


@pytest.mark.parametrize("case", POST_ATTEMPT)
def test_sl1_ec1_every_merge_site_handles_post_attempt_outcomes(tmp_path, monkeypatch, case):
    if case == "lease-rejected":
        # The commit is two steps past B0 (B1, then the reviewed head); the target will
        # advance to B1, an ancestor of the commit, after B0 was fetched.
        land = _Landing(tmp_path, monkeypatch, pr=False, land=False)
        b1 = land.t.change_head
        head = land.t.change({"src.py": "change = 9\n"}, "second change commit")
        _git(land.t.path, "push", "-q", "-f", "origin", "change")
        land.ctx = land.s.build("code-review", land.snap, repo_dir=land.t.path, base_revision=land.b0,
                                head_revision=head, monitoring_policy="bounded")
        land.decide(reviewed_head=head)
    else:
        land = _site(tmp_path, monkeypatch, "pr-merge")
    mg, gh = land.mg, land.gh
    gh.calls.clear()
    if case == "enqueued":
        gh.merge_mode = "enqueue"
    elif case == "enqueue-visible-late":
        gh.merge_mode = "enqueue-late"
    elif case == "dequeue-failed":
        gh.merge_mode, gh.dequeue_fails = "enqueue", True
    elif case == "match-head-rejected":
        gh.merge_mode = "reject"
    elif case == "merged-then-cli-error":
        gh.merge_mode = "merge-then-error"
    elif case == "retarget-after-read":
        gh.merge_mode = "retarget"
    elif case == "base-moved":
        gh.merge_mode = "base-moved"
    elif case == "unreadable-merge":
        gh.merge_mode = "unreadable-merge"
    elif case == "lease-rejected":
        def advance():
            _git(land.t.path, "push", "-q", "origin", f"{b1}:refs/heads/main")

        gh.before_push = advance
    if case == "merged-then-cli-error":
        assert land.merge()
        assert len([c for c in gh.calls if c[1:3] == ["pr", "merge"]]) == 1
        _refused_before_any_attempt(land, lambda: land.merge())  # consumed
        return
    expected = {
        "enqueued": (mg.MergeGuardRefusal, "panel_merge_enqueued"),
        "enqueue-visible-late": (mg.MergeGuardRefusal, "panel_merge_enqueued"),
        "dequeue-failed": (mg.MergeGuardEscalation, "panel_merge_dequeue_failed"),
        "lease-rejected": (mg.MergeGuardRefusal, None),
        "match-head-rejected": (mg.MergeGuardRefusal, "panel_merge_not_merged"),
        "retarget-after-read": (mg.MergeGuardEscalation, "panel_merge_base_moved"),
        "base-moved": (mg.MergeGuardEscalation, "panel_merge_base_moved"),
        "unreadable-merge": (mg.MergeGuardEscalation, "panel_merge_base_moved"),
    }[case]
    with pytest.raises(expected[0]) as excinfo:
        land.merge()
    if expected[1]:
        assert excinfo.value.code == expected[1]
    attempts = [c for c in gh.calls if c[1:3] == ["pr", "merge"] and "--disable-auto" not in c] + \
               [c for c in gh.calls if "push" in c and os.path.basename(c[0]) == "git"]
    assert len(attempts) == 1, f"{case}: expected exactly one attempt, saw {attempts}"
    if case in ("enqueued", "enqueue-visible-late", "dequeue-failed"):
        assert any("dequeuePullRequest" in " ".join(c) for c in gh.calls), "no dequeue after an enqueue"
        assert any("--disable-auto" in c for c in gh.calls)
    # A refused or escalated decision is retired.
    _refused_before_any_attempt(land, lambda: land.merge())


# --- publish_nontarget ------------------------------------------------------------------


class _Publisher:
    def __init__(self, tmp_path, monkeypatch):
        self.mg = _mg()
        self.t = lanes._TargetRepo(tmp_path, "pub", {})
        self.gh = _FakeGitHub(self.t, branch="feature")
        monkeypatch.setattr(self.mg, "_spawn", self.gh)
        monkeypatch.setattr(self.mg, "_repo_slug", lambda repo_dir: _SLUG)
        self.sha = self.t.change_head
        self.url = str(self.t.origin)

    def push(self, *args, declared_target=None):
        return self.mg.publish_nontarget(self.t.path, "git", list(args), declared_target=declared_target)

    def gh_op(self, *args):
        return self.mg.publish_nontarget(self.t.path, "gh", list(args))


def _refs(t) -> str:
    return _git(t.upstream, "ls-remote", str(t.origin))


PUSH_REFUSALS = [
    ("no-refspec", ["push", "--no-verify"]),
    ("origin-head", ["push", "--no-verify", "origin", "HEAD"]),
    ("matching", ["push", "--no-verify", "{url}", ":"]),
    ("force-matching", ["push", "--no-verify", "{url}", "+:"]),
    ("unqualified", ["push", "--no-verify", "{url}", "main"]),
    ("head-main", ["push", "--no-verify", "{url}", "HEAD:main"]),
    ("force", ["push", "--no-verify", "{url}", "+{sha}:refs/heads/main"]),
    ("delete-refspec", ["push", "--no-verify", "{url}", ":main"]),
    ("delete-flag", ["push", "--no-verify", "--delete", "{url}", "refs/heads/x"]),
    ("mirror", ["push", "--no-verify", "--mirror", "{url}"]),
    ("all", ["push", "--no-verify", "--all", "{url}"]),
    ("tags", ["push", "--no-verify", "--tags", "{url}", "{sha}:refs/heads/x"]),
    ("follow-tags", ["push", "--no-verify", "--follow-tags", "{url}", "{sha}:refs/heads/x"]),
    ("set-upstream", ["push", "--no-verify", "--set-upstream", "{url}", "{sha}:refs/heads/x"]),
    ("push-option", ["push", "--no-verify", "-o", "ci.skip", "{url}", "{sha}:refs/heads/x"]),
    ("no-verify-missing", ["push", "{url}", "{sha}:refs/heads/x"]),
    ("to-main", ["push", "--no-verify", "{url}", "{sha}:refs/heads/main"]),
    ("other-remote", ["push", "--no-verify", "https://github.com/evil/r.git", "{sha}:refs/heads/x"]),
]


@pytest.mark.parametrize("case_id,args", PUSH_REFUSALS, ids=[c[0] for c in PUSH_REFUSALS])
def test_sl1_ec1_publish_nontarget_never_updates_a_protected_branch(tmp_path, monkeypatch, case_id, args):
    p = _Publisher(tmp_path, monkeypatch)
    before = _refs(p.t)
    argv = [a.format(url=p.url, sha=p.sha) for a in args]
    with pytest.raises(p.mg.MergeGuardRefusal):
        p.push(*argv)
    assert not [c for c in p.gh.calls if "push" in c and os.path.basename(c[0]) == "git"], case_id
    assert _refs(p.t) == before


PROTECTION_CASES = ["classic", "ruleset", "lookup-failed", "misdeclared-target"]


@pytest.mark.parametrize("case", PROTECTION_CASES)
def test_sl1_ec1_publish_nontarget_resolves_protection_itself(tmp_path, monkeypatch, case):
    p = _Publisher(tmp_path, monkeypatch)
    declared = None
    if case == "classic":
        p.gh.classic = {"enforce_admins": {"enabled": True}}
    elif case == "ruleset":
        p.gh.rulesets = [{"type": "pull_request"}]
    elif case == "lookup-failed":
        p.gh.rulesets = None
    else:
        declared = "feature-x"  # the caller mis-declares; the refspec writes another branch
        p.gh.classic = {"enforce_admins": {"enabled": True}}
    before = _refs(p.t)
    with pytest.raises(p.mg.MergeGuardRefusal):
        p.push("push", "--no-verify", p.url, f"{p.sha}:refs/heads/feature", declared_target=declared)
    assert not [c for c in p.gh.calls if "push" in c and os.path.basename(c[0]) == "git"]
    assert _refs(p.t) == before


def test_sl1_ec1_publish_nontarget_pushes_a_fresh_unprotected_branch(tmp_path, monkeypatch):
    """Positive control: exactly one push, of the exact SHA, to a fully qualified destination."""
    p = _Publisher(tmp_path, monkeypatch)
    p.push("push", "--no-verify", "--porcelain", p.url, f"{p.sha}:refs/heads/feature")
    pushes = [c for c in p.gh.calls if "push" in c and os.path.basename(c[0]) == "git"]
    assert len(pushes) == 1
    assert "core.hooksPath=/dev/null" in pushes[0]
    assert f"{p.sha}\trefs/heads/feature" in _refs(p.t)


GH_REFUSALS = [
    ("edit-base", ["pr", "edit", "1", "--repo", _SLUG, "--base", "release"]),
    ("edit-other-flag", ["pr", "edit", "1", "--repo", _SLUG, "--milestone", "m"]),
    ("url-selector", ["pr", "comment", "https://github.com/evil/r/pull/1", "--repo", _SLUG, "--body", "x"]),
    ("no-repo", ["pr", "comment", "1", "--body", "x"]),
    ("other-repo", ["pr", "comment", "1", "--repo", "github.com/evil/r", "--body", "x"]),
    ("create-web", ["pr", "create", "--repo", _SLUG, "--web"]),
    ("create-fill", ["pr", "create", "--repo", _SLUG, "--head", "o:feature", "--base", "main", "--fill"]),
    ("create-fork", ["pr", "create", "--repo", _SLUG, "--head", "evil:feature", "--base", "main",
                     "--title", "t", "--body", "b"]),
    ("create-unpublished", ["pr", "create", "--repo", _SLUG, "--head", "o:never-pushed", "--base", "main",
                            "--title", "t", "--body", "b"]),
    ("merge", ["pr", "merge", "1", "--repo", _SLUG, "--merge"]),
    ("api-put", ["api", "-X", "PUT", "repos/o/r/pulls/1/merge"]),
]


@pytest.mark.parametrize("case_id,args", GH_REFUSALS, ids=[c[0] for c in GH_REFUSALS])
def test_sl1_ec1_publish_nontarget_refuses_off_grammar_github_operations(tmp_path, monkeypatch, case_id, args):
    p = _Publisher(tmp_path, monkeypatch)
    with pytest.raises(p.mg.MergeGuardRefusal):
        p.gh_op(*args)
    assert not [c for c in p.gh.calls if os.path.basename(c[0]) == "gh" and _mutation_kind(c)], case_id


def test_sl1_ec1_publish_nontarget_refuses_a_pr_create_ahead_of_its_published_head(tmp_path, monkeypatch):
    p = _Publisher(tmp_path, monkeypatch)
    _git(p.t.path, "push", "-q", "origin", "change:refs/heads/feature")
    p.t.change({"src.py": "ahead = 1\n"}, "local commit not published")
    _git(p.t.path, "checkout", "-q", "-B", "feature")
    with pytest.raises(p.mg.MergeGuardRefusal):
        p.gh_op("pr", "create", "--repo", _SLUG, "--head", "o:feature", "--base", "main", "--title", "t", "--body", "b")
    assert not [c for c in p.gh.calls if c[1:3] == ["pr", "create"]]


PR_HEAD_STATES = ["auto-merge", "queued", "queue-protected-base", "unreadable"]


@pytest.mark.parametrize("state", PR_HEAD_STATES)
@pytest.mark.parametrize("operation", ["ready", "push-to-head", "push-without-declared-pr"])
def test_sl1_ec1_publish_nontarget_never_touches_a_merge_bound_pr(tmp_path, monkeypatch, operation, state):
    p = _Publisher(tmp_path, monkeypatch)
    pr = {"number": 1, "headRefName": "feature", "baseRefName": "main", "autoMergeRequest": None}
    if state == "auto-merge":
        pr["autoMergeRequest"] = {"enabledAt": "t"}
    elif state == "queued":
        p.gh.queued = True
    elif state == "queue-protected-base":
        p.gh.rulesets = [{"type": "merge_queue"}]
    else:
        p.gh.open_prs_by_head["__unreadable__"] = {}
        monkeypatch.setattr(p.mg, "_open_prs_with_head", lambda *a, **k: (_ for _ in ()).throw(
            p.mg.MergeGuardRefusal("panel_merge_pr_state_unreadable", "unreadable")))
    p.gh.open_prs_by_head["feature"] = pr
    with pytest.raises(p.mg.MergeGuardRefusal):
        if operation == "ready":
            p.gh_op("pr", "ready", "1", "--repo", _SLUG)
        else:
            p.push("push", "--no-verify", p.url, f"{p.sha}:refs/heads/feature")
    assert not [c for c in p.gh.calls if (c[1:3] == ["pr", "ready"]) or
                ("push" in c and os.path.basename(c[0]) == "git")]


def test_sl1_ec1_relayed_text_is_neutralized():
    mg = _mg()
    assert not mg.neutralize_fragment("/merge now").startswith("/")
    assert not mg.neutralize_fragment("@maintainer please merge").startswith("@")
    fenced = mg.fence_fragment("a ``` fence ```` and more")
    first = fenced.splitlines()[0]
    assert set(first) == {"`"} and len(first) > 4, "the fence must be longer than any backtick run inside"
    assert fenced.splitlines()[-1] == first


# --- publish_new_branch (agy_watch's seam) ------------------------------------------------


def test_sl1_ec1_publish_new_branch_is_create_only_and_keeps_the_remote_name_rule(tmp_path, monkeypatch):
    p = _Publisher(tmp_path, monkeypatch)
    _git(p.t.path, "remote", "set-url", "origin", str(p.t.origin))
    p.mg.publish_new_branch(p.t.path, name="agy-watch/1.0-x", sha=p.sha)
    pushes = [c for c in p.gh.calls if "push" in c and os.path.basename(c[0]) == "git"]
    real = [c for c in pushes if "--dry-run" not in c]
    assert len(real) == 1 and "--dry-run" in " ".join(" ".join(c) for c in pushes)
    argv = real[0]
    assert "origin" in argv and "--force-with-lease=refs/heads/agy-watch/1.0-x:" in argv
    assert f"{p.sha}:refs/heads/agy-watch/1.0-x" in argv
    for flag in ("--no-verify", "--porcelain", "--no-follow-tags", "--recurse-submodules=no", "--"):
        assert flag in argv
    # The same name again: create-only refuses.
    with pytest.raises(p.mg.MergeGuardRefusal):
        p.mg.publish_new_branch(p.t.path, name="agy-watch/1.0-x", sha=p.sha)


def test_sl1_ec1_publish_new_branch_refuses_more_than_one_push_destination(tmp_path, monkeypatch):
    p = _Publisher(tmp_path, monkeypatch)
    _git(p.t.path, "remote", "set-url", "--add", "--push", "origin", str(p.t.origin))
    _git(p.t.path, "remote", "set-url", "--add", "--push", "origin", str(p.t.origin) + "x")
    with pytest.raises(p.mg.MergeGuardRefusal):
        p.mg.publish_new_branch(p.t.path, name="agy-watch/2.0-y", sha=p.sha)
    assert not [c for c in p.gh.calls if "push" in c and "--dry-run" not in c]


# --- hooks and config-driven redirection -------------------------------------------------


def _install_hooks(repo: Path, record: Path) -> None:
    body = f"#!/bin/sh\necho \"$0\" >> {record}\n"
    for where in (repo / ".git" / "hooks", repo / "rel-hooks"):
        where.mkdir(parents=True, exist_ok=True)
        for name in ("pre-push", "post-commit", "reference-transaction"):
            hook = where / name
            hook.write_text(body, encoding="utf-8")
            hook.chmod(0o755)


@pytest.mark.parametrize("hooks_path", ["default", "relative"])
def test_sl1_ec1_merge_guard_runs_no_hooks(tmp_path, monkeypatch, hooks_path):
    land = _site(tmp_path, monkeypatch, "push")
    record = tmp_path / "hook-record.txt"
    _install_hooks(land.t.path, record)
    if hooks_path == "relative":
        _git(land.t.path, "config", "core.hooksPath", "rel-hooks")
    land.merge()
    p = _Publisher(tmp_path / "pub", monkeypatch)
    _install_hooks(p.t.path, record)
    if hooks_path == "relative":
        _git(p.t.path, "config", "core.hooksPath", "rel-hooks")
    p.push("push", "--no-verify", p.url, f"{p.sha}:refs/heads/feature")
    assert not record.exists() or record.read_text() == "", f"a hook ran: {record.read_text()}"


REDIRECTS = [("pushInsteadOf", "url.https://evil.example/.pushInsteadOf"), ("insteadOf", "url.https://evil.example/.insteadOf"),
             ("sshCommand", "core.sshCommand"), ("credential-helper", "credential.helper"),
             ("pushurl", "remote.origin.pushurl")]


@pytest.mark.parametrize("case_id,key", REDIRECTS, ids=[c[0] for c in REDIRECTS])
def test_sl1_ec1_merge_guard_refuses_config_driven_redirection(tmp_path, monkeypatch, case_id, key):
    land = _site(tmp_path, monkeypatch, "push")
    _git(land.t.path, "config", key, str(land.t.origin))
    _refused_before_any_attempt(land, lambda: land.merge())


# --- dequeue ----------------------------------------------------------------------------


def test_sl1_ec1_dequeue_only_removes(tmp_path, monkeypatch):
    mg = _mg()
    t = lanes._TargetRepo(tmp_path, "dq", {})
    gh = _FakeGitHub(t)
    gh.queued, gh.auto_merge = True, True
    monkeypatch.setattr(mg, "_spawn", gh)
    monkeypatch.setattr(mg, "_repo_slug", lambda repo_dir: _SLUG)
    assert mg.dequeue(t.path, repo_slug=_SLUG, pr_number=1, host="github.com") is True
    gh_calls = [c for c in gh.calls if os.path.basename(c[0]) == "gh"]
    mutations = [c for c in gh_calls if _mutation_kind(c) is not None]
    assert all("dequeuePullRequest" in " ".join(c) or "--disable-auto" in c for c in mutations), mutations
    assert any("dequeuePullRequest" in " ".join(c) for c in mutations)
    assert any("--disable-auto" in c for c in mutations)
    for call in gh_calls:
        if call[1:2] == ["api"]:
            assert "--hostname" in call and call[call.index("--hostname") + 1] == "github.com", call
    assert any("isInMergeQueue" in " ".join(c) for c in gh_calls), "no membership confirmation read"


def test_sl1_ec1_the_rules_read_and_dequeue_carry_the_broker_host(tmp_path, monkeypatch):
    land = _site(tmp_path, monkeypatch, "pr-merge")
    land.gh.merge_mode = "enqueue"
    with pytest.raises(land.mg.MergeGuardRefusal):
        land.merge()
    for call in land.gh.calls:
        if os.path.basename(call[0]) == "gh" and call[1:2] == ["api"]:
            assert "--hostname" in call and call[call.index("--hostname") + 1] == "github.com", call


# =======================================================================================
# EC-PANEL-1 -- the gateway tripwire (item 7; a regression tripwire, agent-harness#1111)
# =======================================================================================


_TW_ROOTS = ("phase-loop-runtime/src", "phase-loop-runtime/scripts", "phase-loop-skills", "skills-src")
_TW_FILES = ("install-agent-harness.sh",)
_TW_TRANSPARENT = {"env", "timeout", "nice", "nohup", "stdbuf", "sudo", "command", "exec", "time", "xargs"}
_TW_SHELLS = {"sh", "bash", "dash", "zsh"}
_TW_EXEC_ENV = re.compile(
    r"^(GIT_SSH_COMMAND|GIT_CONFIG_PARAMETERS|GIT_CONFIG_COUNT|GIT_CONFIG_KEY_\d+|"
    r"GIT_CONFIG_VALUE_\d+|GIT_EXEC_PATH|GIT_ASKPASS|GIT_PROXY_COMMAND)$"
)
_TW_LOCAL_GIT = frozenset("""
rev-parse status diff log show cat-file ls-files ls-tree merge-base config add commit checkout
switch branch tag worktree init reset restore rm mv apply cherry-pick rebase merge for-each-ref
symbolic-ref update-ref hash-object write-tree commit-tree read-tree update-index describe rev-list
blame grep remote fsck gc version check-ignore check-attr show-ref name-rev diff-tree diff-index
archive stash clean mktree count-objects var verify-commit verify-tag notes mktag unpack-objects
pack-objects index-pack range-diff shortlog cherry prune repack maintenance sparse-checkout
submodule format-patch am commit-graph fetch ls-remote clone
""".split())
_TW_INERT_C = re.compile(
    r"^(color\.[A-Za-z.]+|commit\.gpgsign|tag\.gpgsign|user\.name|user\.email|gc\.auto|maintenance\.auto|"
    r"init\.defaultBranch|core\.commitGraph|core\.abbrev|core\.quote[Pp]ath|diff\.algorithm|diff\.renames|"
    r"diff\.relative|diff\.noprefix|diff\.mnemonicPrefix|diff\.indentHeuristic|diff\.submodule|"
    r"diff\.ignoreSubmodules)=[^=]*$"
    r"|^(core\.hooksPath|core\.attributesFile|diff\.orderFile)=/dev/null$"
    r"|^(core\.fsmonitor|core\.useBuiltinFSMonitor)=false$|^core\.pager=cat$|^diff\.external=$|^protocol\.allow=never$"
)
_TW_GH_READ = {("pr", "view"), ("pr", "list"), ("pr", "checks"), ("pr", "diff"), ("issue", "view"),
           ("issue", "list"), ("auth", "status"), ("repo", "view")}
_TW_GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_TW_GIT_GLOBAL_FLAGS = {"--no-pager", "-P", "--no-replace-objects", "--literal-pathspecs", "--no-optional-locks",
                        "--bare", "--version", "--no-lazy-fetch", "--glob-pathspecs", "--noglob-pathspecs",
                        "--icase-pathspecs", "--no-advice"}


class _TW_Expr:
    """A non-literal argv _tw_element; ``text`` is its literal prefix (f-string head) if any."""

    def __init__(self, prefix: str = "", *, int_only: bool = False, starred: bool = False,
                 const: str | None = None) -> None:
        self.prefix, self.int_only, self.starred, self.const = prefix, int_only, starred, const


@dataclass(frozen=True)
class _TW_Finding:
    path: str
    line: int
    verdict: str  # OK / FAIL
    why: str


def _tw_lit(x) -> str | None:
    return x if isinstance(x, str) else None


def _tw_git_verdict(rest: list) -> tuple[str, str]:
    j = 0
    while j < len(rest):
        a = rest[j]
        if isinstance(a, _TW_Expr):
            if a.prefix in ("--git-dir=", "--work-tree=") or (j > 0 and rest[j - 1] in ("-C", "--git-dir", "--work-tree")):
                j += 1
                continue
            return "FAIL", "non-literal git global argument"
        if a == "-c":
            v = rest[j + 1] if j + 1 < len(rest) else None
            if not (isinstance(v, str) and _TW_INERT_C.match(v)):
                return "FAIL", f"git -c {v if isinstance(v, str) else '<expr>'}"
            j += 2
            continue
        if a.startswith("-c") or a.startswith("--exec-path") or a.startswith("--config-env"):
            return "FAIL", f"git {a}"
        if a in _TW_GIT_GLOBAL_WITH_ARG:
            j += 2
            continue
        if a.split("=", 1)[0] in ("--git-dir", "--work-tree", "--namespace"):
            j += 1
            continue
        if a.startswith("-"):
            if a not in _TW_GIT_GLOBAL_FLAGS:
                return "FAIL", f"git unrecognized global option {a}"
            j += 1
            continue
        break
    if j >= len(rest):
        if any(a in ("--version", "--exec-path") for a in rest if isinstance(a, str)) and "--exec-path" not in rest:
            return "OK", "git --version"
        return "FAIL", "git without a literal subcommand"
    sub, args = rest[j], rest[j + 1:]
    if sub not in _TW_LOCAL_GIT:
        return "FAIL", f"git {sub}"
    lits = [a for a in args if isinstance(a, str)]
    if sub == "rebase" and any(x in ("-x", "--exec") or x.startswith("--exec=") for x in lits):
        return "FAIL", "git rebase --exec"
    if sub == "submodule" and "foreach" in lits:
        return "FAIL", "git submodule foreach"
    if sub == "bisect" and "run" in lits:
        return "FAIL", "git bisect run"
    if sub == "grep" and any(x in ("-O",) or x.startswith("--open-files-in-pager") for x in lits):
        return "FAIL", "git grep -O"
    if any(x.split("=")[0] in ("--upload-pack", "--receive-pack", "--extcmd", "--exec") for x in lits):
        return "FAIL", f"git {sub} exec-capable option"
    if sub in ("fetch", "clone", "ls-remote") and "-u" in lits:
        return "FAIL", f"git {sub} -u"
    if any(x.startswith("ext::") for x in lits):
        return "FAIL", "ext:: transport"
    if sub == "fetch":
        for x in lits:
            if ":" in x and not x.startswith("-") and not re.match(r"^\w+://", x):
                dst = x.lstrip("+").split(":", 1)[1]
                if not dst.startswith("refs/remotes/"):
                    return "FAIL", f"git fetch refspec writes {dst}"
    return "OK", f"git {sub}"


def _tw_gh_api_verdict(args: list, *, host_allowlisted: bool) -> tuple[str, str]:
    if args and args[0] == "graphql":
        fields, k, rest = [], 1, args[1:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if isinstance(a, _TW_Expr):
                return "FAIL", "gh api graphql non-literal flag"
            if a in ("-f", "-F", "--raw-field", "--field"):
                if i + 1 >= len(rest):
                    return "FAIL", "gh api field without value"
                fields.append((a, rest[i + 1]))
                i += 2
                continue
            if a in ("-H", "--header", "--jq", "-q"):
                if i + 1 >= len(rest) or not isinstance(rest[i + 1], str):
                    return "FAIL", f"gh api {a} non-literal"
                i += 2
                continue
            if a == "--paginate":
                i += 1
                continue
            if a == "--hostname" or a.startswith("--hostname="):
                val = rest[i + 1] if a == "--hostname" and i + 1 < len(rest) else a.partition("=")[2]
                if val != "github.com" and not host_allowlisted:
                    return "FAIL", "gh api --hostname not the literal github.com"
                i += 2 if a == "--hostname" else 1
                continue
            return "FAIL", f"gh api graphql flag {a if isinstance(a, str) else '<expr>'}"
        queries = []
        for flag, value in fields:
            text = value if isinstance(value, str) else (value.const if value.const is not None else None)
            prefix = value if isinstance(value, str) else value.prefix
            key = prefix.split("=", 1)[0] if "=" in prefix else None
            if key is None:
                return "FAIL", "gh api field key not literal"
            if key == "query":
                if text is None:
                    return "FAIL", "gh api graphql document not a literal or module constant"
                if flag not in ("-f", "--raw-field"):
                    return "FAIL", "gh api graphql query not passed with -f"
                queries.append(text.split("=", 1)[1])
                continue
            if isinstance(value, str):
                if value.split("=", 1)[1].startswith("@"):
                    return "FAIL", "gh api field value reads a file (@)"
                continue
            if flag in ("-F", "--field") and not value.int_only:
                return "FAIL", "gh api -F with a non-literal, non-int value"
        if len(queries) != 1:
            return "FAIL", "gh api graphql needs exactly one query field"
        if re.search(r"\bmutation\b", queries[0]):
            return "FAIL", "gh api graphql mutation"
        return "OK", "gh api graphql read"
    # REST
    if not args:
        return "FAIL", "gh api without endpoint"
    endpoint, rest = args[0], args[1:]
    ep_text = endpoint if isinstance(endpoint, str) else endpoint.prefix
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", ep_text) or ep_text.startswith("//") or \
            (isinstance(endpoint, _TW_Expr) and not endpoint.prefix):
        return "FAIL", "gh api endpoint not relative"
    method_get = False
    i = 0
    while i < len(rest):
        a = rest[i]
        if isinstance(a, _TW_Expr):
            return "FAIL", "gh api non-literal flag"
        if a in ("-X", "--method"):
            if i + 1 < len(rest) and rest[i + 1] == "GET":
                method_get = True
                i += 2
                continue
            return "FAIL", "gh api non-GET method"
        if a in ("-XGET", "--method=GET"):
            method_get = True
            i += 1
            continue
        if a.startswith("-X") or a.startswith("--method"):
            return "FAIL", "gh api non-GET method"
        if a in ("-f", "-F", "--field", "--raw-field", "--input") or a.startswith("--input="):
            return "FAIL", f"gh api {a} on a REST call"
        if a in ("-H", "--header", "--jq", "-q"):
            if i + 1 >= len(rest) or not isinstance(rest[i + 1], str):
                return "FAIL", f"gh api {a} non-literal"
            i += 2
            continue
        if a == "--paginate":
            i += 1
            continue
        if a == "--hostname" or a.startswith("--hostname="):
            val = rest[i + 1] if a == "--hostname" and i + 1 < len(rest) else a.partition("=")[2]
            if val != "github.com":
                return "FAIL", "gh api --hostname not the literal github.com"
            i += 2 if a == "--hostname" else 1
            continue
        return "FAIL", f"gh api flag {a}"
    if not method_get:
        return "FAIL", "gh api REST read without a literal -X GET"
    return "OK", "gh api REST GET"


def _tw_classify(argv: list, *, host_allowlisted: bool = False) -> tuple[str, str]:
    i = 0
    while i < len(argv):
        a = argv[i]
        if isinstance(a, _TW_Expr):
            return "FAIL", "non-literal command position"
        name, eq, _ = a.partition("=")
        if eq and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            if _TW_EXEC_ENV.match(name):
                return "FAIL", f"exec-capable env {name}"
            i += 1
            continue
        if os.path.basename(a) in _TW_TRANSPARENT:
            i += 1
            while i < len(argv) and isinstance(argv[i], str) and (argv[i].startswith("-") or argv[i][:1].isdigit()):
                i += 1
            continue
        break
    if i >= len(argv):
        return "SKIP", ""
    tool, rest = os.path.basename(argv[i]), argv[i + 1:]
    if tool == "git":
        return _tw_git_verdict(rest)
    if tool == "gh":
        if not rest or isinstance(rest[0], _TW_Expr):
            return "FAIL", "gh without a literal subcommand"
        if rest[0] == "api":
            return _tw_gh_api_verdict(rest[1:], host_allowlisted=host_allowlisted)
        if len(rest) < 2 or isinstance(rest[1], _TW_Expr):
            return "FAIL", f"gh {rest[0]} without a literal verb"
        if (rest[0], rest[1]) in _TW_GH_READ:
            return "OK", f"gh {rest[0]} {rest[1]}"
        return "FAIL", f"gh {rest[0]} {rest[1]}"
    if tool in _TW_SHELLS:
        for k, a in enumerate(rest):
            if isinstance(a, str) and re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", a) and k + 1 < len(rest):
                payload = rest[k + 1]
                if isinstance(payload, _TW_Expr):
                    return "SKIP", "runtime-built -c payload (residual)"
                return _tw_shell_verdict(payload)
    return "SKIP", ""


def _tw_shell_commands(text: str) -> list[list[str]]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()`")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError:
        return [text.split()]
    commands, cur = [], []
    for tok in tokens:
        if tok and set(tok) <= set(";&|()`"):
            if cur:
                commands.append(cur)
            cur = []
            continue
        if tok.startswith("$(") or tok == "$":
            if cur:
                commands.append(cur)
            cur = []
            continue
        cur.append(tok)
    if cur:
        commands.append(cur)
    out = []
    for words in commands:
        if words and words[0] == "eval":
            out.extend(_tw_shell_commands(" ".join(words[1:])))
        else:
            out.append(words)
    return out


def _tw_shell_verdict(text: str) -> tuple[str, str]:
    best = ("SKIP", "")
    for words in _tw_shell_commands(text):
        v = _tw_classify(list(words))
        if v[0] == "FAIL":
            return v
        if v[0] == "OK":
            best = v
    return best


class _tw_Module:
    def __init__(self, tree: ast.Module) -> None:
        self.consts: dict[str, str] = {}
        self.tuples: dict[str, list] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, (ast.Tuple, ast.List)) \
                    and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts):
                self.tuples[node.targets[0].id] = [e.value for e in node.value.elts]
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    self.consts[node.targets[0].id] = node.value.value
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and \
                    isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                self.consts[node.target.id] = node.value.value


def _tw_element(node: ast.AST, mod: _tw_Module):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Starred):
        return _TW_Expr(starred=True)
    if isinstance(node, ast.JoinedStr):
        prefix, const_parts, all_const = "", [], True
        for part in node.values:
            if isinstance(part, ast.Constant):
                prefix += part.value if all_const else ""
                const_parts.append(part.value)
            elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name) and part.value.id in mod.consts:
                const_parts.append(mod.consts[part.value.id])
                if all_const:
                    prefix += mod.consts[part.value.id]
            else:
                all_const = False
                const_parts = None if const_parts is None else const_parts
                break
        int_only = (len(node.values) == 2 and isinstance(node.values[1], ast.FormattedValue)
                    and isinstance(node.values[1].value, ast.Call)
                    and getattr(node.values[1].value.func, "id", "") == "int")
        if all_const:
            return "".join(const_parts)
        return _TW_Expr(prefix, int_only=int_only)
    if isinstance(node, ast.Name) and node.id in mod.consts:
        return mod.consts[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _tw_element(node.left, mod)
        if isinstance(left, str):
            right = _tw_element(node.right, mod)
            return left + right if isinstance(right, str) else _TW_Expr(left)
    return _TW_Expr()


def _tw_display_argv(node, mod):
    out = []
    for e in node.elts:
        if isinstance(e, ast.Starred) and isinstance(e.value, ast.Name) and e.value.id in mod.tuples:
            out.extend(mod.tuples[e.value.id])
        else:
            out.append(_tw_element(e, mod))
    return out


def _tw_scan_python(path: Path, rel: str, *, host_allowlist=frozenset(), data_allowlist=frozenset()) -> list[_TW_Finding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [_TW_Finding(rel, 0, "FAIL", f"unparseable: {exc}")]
    mod = _tw_Module(tree)
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent
    out: list[_TW_Finding] = []
    # wrappers: def f(..., *args) whose body spawns ["git"|"gh", <globals>, *args]
    wrappers: dict[str, list] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.args.vararg is None:
            continue
        var = fn.args.vararg.arg
        for node in ast.walk(fn):
            if isinstance(node, (ast.List, ast.Tuple)) and node.elts and _tw_element(node.elts[0], mod) in ("git", "gh"):
                last = node.elts[-1]
                if isinstance(last, ast.Starred) and isinstance(last.value, ast.Name) and last.value.id == var:
                    head = _tw_display_argv(ast.List(elts=node.elts[:-1]), mod)
                    # a non-literal head _tw_element is allowed only as the operand of -C
                    ok = all(isinstance(h, str) or (k > 0 and head[k - 1] in ("-C", "--git-dir", "--work-tree"))
                             or (isinstance(h, _TW_Expr) and h.prefix in ("--git-dir=", "--work-tree=")) for k, h in enumerate(head))
                    wrappers[fn.name] = (head, len(fn.args.posonlyargs) + len(fn.args.args)) if ok else None
    # list-typed parameter wrappers: def f(..., args) spawning ["git", ..., *args]
    list_wrappers: dict[str, tuple] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name in wrappers:
            continue
        params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        for node in ast.walk(fn):
            if isinstance(node, (ast.List, ast.Tuple)) and node.elts and _tw_element(node.elts[0], mod) in ("git", "gh"):
                last = node.elts[-1]
                if isinstance(last, ast.Starred) and isinstance(last.value, ast.Name) and last.value.id in params:
                    head = _tw_display_argv(ast.List(elts=node.elts[:-1]), mod)
                    if all(isinstance(h, str) for h in head):
                        list_wrappers[fn.name] = (head, params.index(last.value.id))
    # transitive: def g(x, *args): return f(x, *args) where f is a wrapper
    changed = True
    while changed:
        changed = False
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.args.vararg is None or fn.name in wrappers:
                continue
            var = fn.args.vararg.arg
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    callee = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if callee in wrappers and wrappers[callee] is not None and node.args and \
                            isinstance(node.args[-1], ast.Starred) and getattr(node.args[-1].value, "id", None) == var:
                        head, nfixed = wrappers[callee]
                        extra = [_tw_element(a, mod) for a in node.args[nfixed:-1]]
                        if all(isinstance(e, str) for e in extra):
                            wrappers[fn.name] = (list(head) + extra, len(fn.args.posonlyargs) + len(fn.args.args))
                            changed = True
                            break
    wrapper_nodes = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and (fn.name in wrappers or fn.name in list_wrappers):
            for node in ast.walk(fn):
                if isinstance(node, (ast.List, ast.Tuple)):
                    wrapper_nodes.add(id(node))
    for fn_name, head in wrappers.items():
        if head is None:
            out.append(_TW_Finding(rel, 0, "FAIL", f"wrapper {fn_name} has a non-literal global argument"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None)
            if fname is None and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id in ("self", "cls"):
                fname = node.func.attr
            encl_fn = _tw_enclosing_fn_node(tree, node)
            if fname in wrappers and wrappers[fname] is not None and encl_fn is not None and encl_fn.args.vararg is not None \
                    and node.args and isinstance(node.args[-1], ast.Starred) \
                    and getattr(node.args[-1].value, "id", None) == encl_fn.args.vararg.arg and encl_fn.name in wrappers:
                continue  # a transitive wrapper forwarding its own *args; its callers are classified
            if fname in wrappers and wrappers[fname] is not None:
                head, nfixed = wrappers[fname]
                if isinstance(node.func, ast.Attribute) and nfixed and _tw_fn_is_method(tree, fname):
                    nfixed -= 1
                var_args = node.args[nfixed:]
                argv = list(head)
                for a in var_args:
                    if isinstance(a, ast.Starred) and isinstance(a.value, ast.Name) and encl_fn is not None:
                        resolved = _tw_local_literal_list(encl_fn, a.value.id, mod)
                        if resolved is None:
                            argv.append(_TW_Expr(starred=True))
                        else:
                            argv.extend(resolved)
                    else:
                        argv.append(_tw_element(a, mod))
                if var_args and isinstance(var_args[0], ast.Starred) and not isinstance(argv[len(head)] if len(argv) > len(head) else None, _TW_Expr):
                    v = _tw_classify(argv, host_allowlisted=(rel, fname) in host_allowlist)
                    if v[0] != "SKIP":
                        out.append(_TW_Finding(rel, node.lineno, *v))
                    continue
                if not var_args or isinstance(_tw_element(var_args[0], mod), _TW_Expr):
                    out.append(_TW_Finding(rel, node.lineno, "FAIL", f"wrapper {fname} called with a non-literal leading argument"))
                    continue
                v = _tw_classify(argv, host_allowlisted=(rel, fname) in host_allowlist)
                if v[0] != "SKIP":
                    out.append(_TW_Finding(rel, node.lineno, *v))
        if isinstance(node, ast.Call):
            lname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if lname in list_wrappers:
                head, idx = list_wrappers[lname]
                if isinstance(node.func, ast.Attribute) and _tw_fn_is_method(tree, lname):
                    idx -= 1
                arg = node.args[idx] if idx < len(node.args) else None
                if isinstance(arg, (ast.List, ast.Tuple)):
                    v = _tw_classify(list(head) + _tw_display_argv(arg, mod))
                    if v[0] != "SKIP":
                        out.append(_TW_Finding(rel, node.lineno, *v))
                else:
                    out.append(_TW_Finding(rel, node.lineno, "FAIL", f"list wrapper {lname} called without a literal list"))
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and id(node) not in wrapper_nodes:
            argv = _tw_display_argv(node, mod)
            first = argv[0]
            if not isinstance(first, str):
                continue
            if not any(isinstance(a, str) and os.path.basename(a.split()[0] if a.split() else a) in ("git", "gh") for a in argv):
                continue
            base = os.path.basename(first)
            if base in ("git", "gh") or base in _TW_TRANSPARENT or base in _TW_SHELLS or ("=" in first and _TW_EXEC_ENV.match(first.partition("=")[0])):
                if (rel, node.lineno) in data_allowlist:
                    continue
                encl = _tw_enclosing_function(tree, node)
                v = _tw_classify(argv, host_allowlisted=(rel, encl) in host_allowlist)
                if v[0] != "SKIP":
                    out.append(_TW_Finding(rel, node.lineno, *v))
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "split" and isinstance(f, ast.Attribute):
                s = None
                if isinstance(f.value, ast.Name) and f.value.id == "shlex" and node.args:
                    s = _tw_element(node.args[0], mod)
                elif isinstance(f.value, ast.Constant):
                    s = f.value.value
                if isinstance(s, str) and s.split()[:1] and os.path.basename(s.split()[0]) in ("git", "gh"):
                    v = _tw_classify(s.split())
                    out.append(_TW_Finding(rel, node.lineno, *v))
            shell_kw = any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)
            if (name in ("system", "popen") or shell_kw) and node.args:
                s = _tw_element(node.args[0], mod)
                if isinstance(s, str):
                    v = _tw_shell_verdict(s)
                    if v[0] != "SKIP":
                        out.append(_TW_Finding(rel, node.lineno, *v))
            for kw in node.keywords:
                if kw.arg == "env" and isinstance(kw.value, ast.Dict):
                    for key in kw.value.keys:
                        k = _tw_element(key, mod) if key is not None else None
                        if isinstance(k, str) and _TW_EXEC_ENV.match(k):
                            out.append(_TW_Finding(rel, node.lineno, "FAIL", f"exec-capable env {k} in env="))
            if name in ("put", "post", "patch", "delete", "request", "Request", "urlopen"):
                urls = [_tw_element(a, mod) for a in list(node.args) + [k.value for k in node.keywords if k.arg == "url"]]
                if any(isinstance(u, str) and "api.github.com" in u for u in urls):
                    method = next((k.value for k in node.keywords if k.arg == "method"), None)
                    if method is None and name == "request" and len(node.args) >= 2:
                        method = node.args[0]
                    if name in ("Request", "urlopen") and method is None:
                        pass  # GET by default
                    elif name in ("Request", "request") and isinstance(method, ast.Constant) and method.value == "GET":
                        pass
                    else:
                        out.append(_TW_Finding(rel, node.lineno, "FAIL", f"HTTP {name} to the GitHub API, method not a literal GET"))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] in ("git", "pygit2", "dulwich", "github", "ghapi", "gidgethub"):
                    out.append(_TW_Finding(rel, node.lineno, "FAIL", f"library import {m}"))
    return out


def _tw_enclosing_fn_node(tree, target):
    node = getattr(target, "_parent", None)
    while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node = getattr(node, "_parent", None)
    return node


def _tw_local_literal_list(fn, name, mod):
    """All literal elements assigned to ``name`` in ``fn`` if every store is a literal list display."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                return None
            vals = _tw_display_argv(node.value, mod)
            out.extend(vals)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                return None
            out.extend(_tw_display_argv(node.value, mod))
    if not out or not isinstance(out[0], str):
        return None
    return out


def _tw_fn_is_method(tree, name):
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef):
            for fn in cls.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                    return True
    return False


def _tw_enclosing_function(tree, target):
    fn = _tw_enclosing_fn_node(tree, target)
    return fn.name if fn is not None else None


def _tw_scan(repo: Path, **kw) -> list[_TW_Finding]:
    files = []
    for root in _TW_ROOTS:
        base = repo / root
        if base.exists():
            files += [p for p in base.rglob("*") if p.is_file() and (p.suffix in (".py", ".sh") or p.name.endswith(".bash"))]
    files += [repo / f for f in _TW_FILES if (repo / f).exists()]
    out: list[_TW_Finding] = []
    for p in sorted(set(files)):
        rel = str(p.relative_to(repo))
        if p.suffix == ".py":
            out += _tw_scan_python(p, rel, **kw)
        else:
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                v = _tw_shell_verdict(line)
                if v[0] != "SKIP":
                    out.append(_TW_Finding(rel, n, *v))
    return out



# --- merge_guard's own structure --------------------------------------------------------

_TW_DATA_ALLOWLIST = frozenset({
    # Tables of names that reach no spawn API (plan: "Data displays", allowlisted by path and line).
    ("phase-loop-runtime/src/phase_loop_runtime/convergence/reconcile.py", "_REQUIRED_DOMAINS"),
    ("phase-loop-runtime/src/phase_loop_runtime/convergence/reconcile.py", "reconcile-domain-tuple"),
    ("phase-loop-runtime/src/phase_loop_runtime/repo_validation.py", "tool-name-table"),
})
# The data displays are identified by their first literal element and module (a line pin
# would be brittle); each is a tuple of names, never an argv.
_TW_DATA_DISPLAYS = {
    "phase-loop-runtime/src/phase_loop_runtime/convergence/reconcile.py": {("git", "github"), ("git", "head_sha")},
    "phase-loop-runtime/src/phase_loop_runtime/repo_validation.py": {("git", "just")},
}
_TW_HOST_ALLOWLIST = frozenset({
    # agent-harness#265: the merge-queue membership read binds the broker-validated host.
    ("phase-loop-runtime/src/phase_loop_runtime/train_runner.py", "_live_pr_queue_status"),
})
_MERGE_GUARD_REL = "phase-loop-runtime/src/phase_loop_runtime/merge_guard.py"
_MG_ALLOWED = {
    "guarded_merge": {"git push", "gh pr merge", "gh pr ready"},
    "publish_nontarget": {"git push", "gh pr create", "gh pr comment", "gh pr edit", "gh pr ready",
                          "gh issue create", "gh issue comment"},
    "publish_new_branch": {"git push", "gh pr create"},
    "dequeue": {"gh api graphql mutation", "gh pr merge"},
}
_TOKEN_SITES = {
    "mint_no_landing_token": {_MERGE_GUARD_REL, "phase-loop-runtime/src/phase_loop_runtime/runner.py",
                              "phase-loop-runtime/src/phase_loop_runtime/train_runner.py"},
    "NoLandingToken": {_MERGE_GUARD_REL},
    "register_landing_decision": {_MERGE_GUARD_REL, "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py"},
}


def _mutation_kind(argv: list) -> str | None:
    lits = [a for a in argv if isinstance(a, str)]
    if not lits:
        return None
    try:
        i = next(k for k, a in enumerate(lits) if os.path.basename(a) in ("git", "gh"))
    except StopIteration:
        return None
    tool, rest = os.path.basename(lits[i]), lits[i + 1:]
    if tool == "git":
        return "git push" if "push" in rest or "send-pack" in rest else None
    if rest[:1] == ["api"]:
        joined = " ".join(rest)
        if re.search(r"\bmutation\b", joined):
            return "gh api graphql mutation"
        if re.search(r"(-X|--method)[ =]?(?!GET)\w", joined):
            return "gh api non-GET"
        return None
    if len(rest) >= 2 and (rest[0], rest[1]) in {("pr", "merge"), ("pr", "create"), ("pr", "comment"), ("pr", "edit"),
                                                  ("pr", "ready"), ("issue", "create"), ("issue", "comment")}:
        return f"gh {rest[0]} {rest[1]}"
    return None


def _merge_guard_violations(path: Path, rel: str = _MERGE_GUARD_REL) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mod = _tw_Module(tree)
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent
    out: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.List, ast.Tuple)) and node.elts):
            continue
        argv = _tw_display_argv(node, mod)
        if not any(isinstance(a, str) and os.path.basename(a) in ("git", "gh") for a in argv):
            continue
        top = node
        while getattr(top, "_parent", None) is not None and not isinstance(top._parent, ast.Module):
            top = top._parent
        fn = top.name if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
        kind = _mutation_kind(argv)
        if kind is not None and kind not in _MG_ALLOWED.get(fn, set()):
            out.append(f"{rel}:{node.lineno}: {kind} outside its one allowed function ({fn})")
        lits = [a for a in argv if isinstance(a, str)]
        if lits and os.path.basename(lits[0]) == "git":
            cs = [lits[k + 1] for k, a in enumerate(lits[:-1]) if a == "-c"]
            if cs != ["core.hooksPath=/dev/null"]:
                out.append(f"{rel}:{node.lineno}: a merge_guard git call must carry exactly -c core.hooksPath=/dev/null")
            if "push" in lits and "--no-verify" not in lits:
                out.append(f"{rel}:{node.lineno}: a merge_guard push without --no-verify")
    return out


def _token_site_violations(repo: Path) -> list[str]:
    out = []
    for root in _TW_ROOTS:
        for path in (repo / root).rglob("*.py"):
            rel = str(path.relative_to(repo))
            text = path.read_text(encoding="utf-8", errors="replace")
            for name, allowed in _TOKEN_SITES.items():
                if re.search(rf"\b{name}\b", text) and rel not in allowed:
                    out.append(f"{rel}: stray reference to {name}")
    pi_text = (repo / "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py").read_text(encoding="utf-8")
    if len(re.findall(r"\bregister_landing_decision\b", pi_text)) != 1:
        out.append("panel_invoker.py must reference register_landing_decision exactly once (in invoke_board)")
    return out


def _tripwire(repo: Path) -> list[str]:
    findings = _tw_scan(repo, host_allowlist=_TW_HOST_ALLOWLIST)
    out = []
    for f in findings:
        if f.verdict != "FAIL":
            continue
        if f.path == _MERGE_GUARD_REL:
            continue  # merge_guard is checked by its own rules below
        displays = _TW_DATA_DISPLAYS.get(f.path, set())
        if any(f.why == f"git {second}" for _first, second in displays):
            continue
        out.append(f"{f.path}:{f.line}: {f.why}")
    mg = repo / _MERGE_GUARD_REL
    if not mg.exists():
        out.append("merge_guard.py is missing")
    else:
        out += _merge_guard_violations(mg)
    out += _token_site_violations(repo)
    return out


def test_sl1_ec1_gateway_tripwire():
    """The scan over the tree: every git/gh spawn is classified, every remote mutation sits in
    its one merge_guard function, and the authority names appear only where allowed."""
    findings = _tripwire(REPO_ROOT)
    assert findings == [], "\n".join(findings)


def _snippet_findings(tmp_path: Path, source: str, *, name: str = "mod.py") -> list[str]:
    root = tmp_path / "phase-loop-runtime" / "src" / "phase_loop_runtime"
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(textwrap.dedent(source), encoding="utf-8")
    rel = f"phase-loop-runtime/src/phase_loop_runtime/{name}"
    if name.endswith(".py"):
        found = [f.why for f in _tw_scan_python(root / name, rel) if f.verdict == "FAIL"]
    else:
        found = [_tw_shell_verdict(line)[1] for line in (root / name).read_text().splitlines()
                 if _tw_shell_verdict(line)[0] == "FAIL"]
    return found


TRIPWIRE_SELF_FALSIFIERS = [
    ("subprocess-run", 'import subprocess\nsubprocess.run(["git", "push", "origin", "x"])\n'),
    ("subprocess-popen", 'import subprocess\nsubprocess.Popen(["gh", "pr", "merge", "1"])\n'),
    ("os-execvp", 'import os\nos.execvp("git", ["git", "push"])\n'),
    ("os-spawnlp", 'import os\nos.spawnvp(os.P_WAIT, "gh", ["gh", "pr", "merge", "1"])\n'),
    ("posix-spawn", 'import os\nos.posix_spawnp("git", ["git", "push"], {})\n'),
    ("os-system", 'import os\nos.system("git push origin main")\n'),
    ("os-popen", 'import os\nos.popen("gh pr merge 1")\n'),
    ("pty-spawn", 'import pty\npty.spawn(["git", "push"])\n'),
    ("asyncio", 'import asyncio\nasyncio.create_subprocess_exec(*["git", "push"])\n'),
    ("gh-api-field", 'import subprocess\nsubprocess.run(["gh", "api", "repos/o/r/pulls", "--field", "x=1"])\n'),
    ("gh-api-method-put", 'import subprocess\nsubprocess.run(["gh", "api", "--method=PUT", "repos/o/r/merge"])\n'),
    ("gh-api-XPUT", 'import subprocess\nsubprocess.run(["gh", "api", "-XPUT", "repos/o/r/merge"])\n'),
    ("gh-api-get-with-f", 'import subprocess\nsubprocess.run(["gh", "api", "-X", "GET", "repos/o/r", "-f", "a=b"])\n'),
    ("graphql-mutation", 'import subprocess\nsubprocess.run(["gh", "api", "graphql", "-f", "query=mutation{x}"])\n'),
    ("graphql-prefix-injection",
     'import subprocess\ndef f(prefix):\n    subprocess.run(["gh", "api", "graphql", "-f", f"query={prefix}query {{x}}"])\n'),
    ("graphql-query-at-file", 'import subprocess\nsubprocess.run(["gh", "api", "graphql", "-F", "query=@-"])\n'),
    ("gh-api-input", 'import subprocess\nsubprocess.run(["gh", "api", "graphql", "--input", "-"])\n'),
    ("gh-api-nonliteral-key",
     'import subprocess\ndef f(k):\n    subprocess.run(["gh", "api", "graphql", "-f", "query=query{x}", "-f", f"{k}=1"])\n'),
    ("gh-api-interpolated-path-with-field",
     'import subprocess\ndef f(r):\n    subprocess.run(["gh", "api", f"repos/{r}/merges", "-f", "base=main"])\n'),
    ("gh-api-string-through-F",
     'import subprocess\ndef f(o):\n    subprocess.run(["gh", "api", "graphql", "-f", "query=query{x}", "-F", f"owner={o}"])\n'),
    ("gh-api-absolute-url", 'import subprocess\nsubprocess.run(["gh", "api", "-X", "GET", "https://evil.example/x"])\n'),
    ("gh-api-hostname", 'import subprocess\nsubprocess.run(["gh", "api", "-X", "GET", "--hostname", "evil.example", "x"])\n'),
    ("git-push", 'import subprocess\nsubprocess.run(["git", "push"])\n'),
    ("git-send-pack", 'import subprocess\nsubprocess.run(["git", "send-pack", "origin"])\n'),
    ("git-c", 'import subprocess\nsubprocess.run(["git", "-c", "core.sshCommand=x", "fetch"])\n'),
    ("git-config-env", 'import subprocess\nsubprocess.run(["git", "--config-env=core.editor=E", "status"])\n'),
    ("git-unknown-global", 'import subprocess\nsubprocess.run(["git", "--exec-magic", "status"])\n'),
    ("git-rebase-x", 'import subprocess\nsubprocess.run(["git", "rebase", "-x", "make", "main"])\n'),
    ("git-submodule-foreach", 'import subprocess\nsubprocess.run(["git", "submodule", "foreach", "echo"])\n'),
    ("git-fetch-upload-pack", 'import subprocess\nsubprocess.run(["git", "fetch", "--upload-pack=x", "origin"])\n'),
    ("git-fetch-refspec", 'import subprocess\nsubprocess.run(["git", "fetch", "origin", "main:refs/heads/main"])\n'),
    ("git-library", "import git\n"),
    ("pygit2", "import pygit2\n"),
    ("github-client", "import github\n"),
    ("ghapi", "from ghapi.all import GhApi\n"),
    ("assigned-display", 'import subprocess\nargv = ["git", "push", "origin", "main"]\nsubprocess.run(argv)\n'),
    ("prefixed-argv", 'import subprocess\nsubprocess.run(["timeout", "600", "gh", "pr", "merge", "1"])\n'),
    ("shlex-split", 'import shlex, subprocess\nsubprocess.run(shlex.split("git push origin main"))\n'),
    ("shell-true-compound", 'import subprocess\nsubprocess.run("cd x && git push origin main", shell=True)\n'),
    ("bash-lc", 'import subprocess\nsubprocess.run(["bash", "-lc", "git push origin main"])\n'),
    ("git-ssh-command-env", 'import subprocess\nsubprocess.run(["env", "GIT_SSH_COMMAND=x", "git", "fetch"])\n'),
    ("env-mapping", 'import subprocess\nsubprocess.run(["git", "status"], env={"GIT_CONFIG_PARAMETERS": "x"})\n'),
    ("requests-put", 'import requests\nrequests.put("https://api.github.com/repos/o/r/pulls/1/merge")\n'),
    ("urllib-patch",
     'import urllib.request\nurllib.request.Request("https://api.github.com/repos/o/r", method="PATCH")\n'),
    ("urllib3-post", 'import urllib3\nurllib3.PoolManager().request("POST", "https://api.github.com/repos/o/r/merges")\n'),
    ("httpx-nonliteral-method",
     'import httpx\ndef f(m):\n    httpx.request(m, "https://api.github.com/repos/o/r/merges")\n'),
    ("rebound-local", 'import subprocess\ndef f(g):\n    sub = "status"\n    sub = g()\n    subprocess.run(["git", sub])\n'),
]


@pytest.mark.parametrize("case_id,source", TRIPWIRE_SELF_FALSIFIERS, ids=[c[0] for c in TRIPWIRE_SELF_FALSIFIERS])
def test_sl1_ec1_gateway_tripwire_catches_each_in_scope_form(tmp_path, case_id, source):
    assert _snippet_findings(tmp_path, source), f"{case_id}: the tripwire missed an in-scope form"


SHELL_SELF_FALSIFIERS = [
    ("assignment-and-chain", 'GH_TOKEN=$t gh pr merge 1\ncd d && git push origin main\n'),
    ("eval", 'eval "git push origin main"\n'),
    ("ssh-command", 'GIT_SSH_COMMAND=x git fetch\n'),
]


@pytest.mark.parametrize("case_id,source", SHELL_SELF_FALSIFIERS, ids=[c[0] for c in SHELL_SELF_FALSIFIERS])
def test_sl1_ec1_gateway_tripwire_catches_shell_script_forms(tmp_path, case_id, source):
    assert _snippet_findings(tmp_path, source, name="script.sh"), f"{case_id}: missed in a shell script"


def test_sl1_ec1_gateway_tripwire_keeps_its_positive_controls(tmp_path):
    """Local forms the plan classifies must NOT fail (fail-closed is not fail-everything)."""
    source = '''
    import subprocess
    _CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "color.ui=false")
    QUERY = "query($o:String!){repository(owner:$o){id}}"
    def _git(repo, *args):
        return subprocess.run(["git", "-C", str(repo), *_CONFIG, *args])
    def _outer(repo, *args):
        return _git(repo, *args)
    def reads(repo, rev, owner):
        _git(repo, "rev-parse", rev)
        _outer(repo, "log", "-1", rev)
        args = ["diff", "--cached"]
        args += ["--quiet"]
        _git(repo, *args)
        subprocess.run(["git", "--version"])
        subprocess.run(["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"o={owner}"])
        subprocess.run(["gh", "api", f"repos/{owner}/x", "-X", "GET"])
        subprocess.run(["gh", "pr", "view", "1", "--json", "state"])
    '''
    assert _snippet_findings(tmp_path, source) == []


def _write_merge_guard(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "merge_guard.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_sl1_ec1_gateway_tripwire_confines_each_mutation_to_its_function(tmp_path):
    good = _write_merge_guard(tmp_path, '''
    import subprocess
    def guarded_merge(repo, *, authority, action):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "push", "--no-verify", "origin", "x:refs/heads/main"])
    ''')
    assert _merge_guard_violations(good) == []
    second = _write_merge_guard(tmp_path, '''
    import subprocess
    def guarded_merge(repo, *, authority, action):
        pass
    def sneaky(repo):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "push", "--no-verify", "origin", "x:refs/heads/main"])
    ''')
    assert _merge_guard_violations(second), "a second function in merge_guard.py pushed"
    no_verify = _write_merge_guard(tmp_path, '''
    import subprocess
    def guarded_merge(repo, *, authority, action):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "push", "origin", "x:refs/heads/main"])
    ''')
    assert _merge_guard_violations(no_verify)
    hooks = _write_merge_guard(tmp_path, '''
    import subprocess
    def guarded_merge(repo, *, authority, action):
        subprocess.run(["git", "fetch", "origin"])
    ''')
    assert _merge_guard_violations(hooks), "a merge_guard git call without core.hooksPath=/dev/null"


def test_sl1_ec1_gateway_tripwire_confines_the_authority_names(tmp_path):
    repo = tmp_path / "repo"
    src = repo / "phase-loop-runtime/src/phase_loop_runtime"
    src.mkdir(parents=True)
    (src / "panel_invoker.py").write_text("from .merge_guard import register_landing_decision\n", encoding="utf-8")
    (src / "merge_guard.py").write_text("def register_landing_decision(): pass\nclass NoLandingToken: pass\n",
                                        encoding="utf-8")
    assert _token_site_violations(repo) == []
    (src / "stray.py").write_text("from .merge_guard import NoLandingToken\n", encoding="utf-8")
    assert _token_site_violations(repo), "a stray NoLandingToken was not caught"
    (src / "stray.py").write_text("from .merge_guard import register_landing_decision\n", encoding="utf-8")
    assert _token_site_violations(repo), "a stray registration reference was not caught"


# =======================================================================================
# Shared fixture for other phases' granted nodes (plan: "Other phases' frozen nodes SL-1
# may change"). Not a test.
# =======================================================================================


_GRANTED_ROOTS: list = []  # removed by each TemporaryDirectory's finalizer


def _granted_context(tier, vendors, task, *, setenv, setattr_, user_body=None):
    from phase_loop_runtime.advisor_board import composition, config

    real = composition.compose_panel_board
    available = set(vendors)

    def forced(table, **_ignored):
        return real(table, is_available=lambda v: v in available, auth_ok=lambda v: True,
                    preflight=lambda v: True)

    root = tempfile.TemporaryDirectory(prefix="panel-granted-")
    _GRANTED_ROOTS.append(root)
    td = Path(root.name)
    setenv("XDG_CONFIG_HOME", str(td / "xdg"))
    if user_body is not None:
        user_file = td / "xdg" / "agent-harness" / "advisor-boards.toml"
        user_file.parent.mkdir(parents=True)
        user_file.write_text(user_body, encoding="utf-8")
    setattr_(composition, "compose_panel_board", forced)
    repo = td / "repo"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                    "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "base"],
                   check=True, capture_output=True, env=env)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()
    snap = config.snapshot_panel_run()
    ctx = config.build_panel_context(task, snap, repo_dir=repo, base_revision=base, head_revision=None,
                                     monitoring_policy="bounded")
    return ctx, {"panel_context": ctx, "review_policy": pi.panel_landing_policy(tier, context=ctx)}


@contextlib.contextmanager
def granted_landing_context(tier: str = "production_code", *, vendors=lanes.BOARD_VENDORS,
                            task: str = "code-review", user_body: str | None = None):
    """A production-built context for a granted HARDEN / PRESROUTE node: built by
    ``build_panel_context`` with every vendor available, so its composed board is the
    lane board, plus its ``panel_landing_policy`` as ``review_policy``. Availability is
    forced at the ``compose_panel_board`` call boundary (the frozen corpus's
    ``_ForcedProbes`` route), never through injected ``probes``, so the context can land;
    the user file is a private ``XDG_CONFIG_HOME`` path. Yields ``(context, kwargs)``;
    the landing must happen inside the block."""
    with contextlib.ExitStack() as stack:
        def setenv(name, value):
            stack.enter_context(mock.patch.dict(os.environ, {name: value}))

        def setattr_(obj, name, value):
            stack.enter_context(mock.patch.object(obj, name, value))

        yield _granted_context(tier, vendors, task, setenv=setenv, setattr_=setattr_, user_body=user_body)


def granted_landing_context_mp(monkeypatch, tier: str = "production_code", *, vendors=lanes.BOARD_VENDORS,
                               task: str = "code-review", user_body: str | None = None):
    """:func:`granted_landing_context` for a pytest node, undone by its ``monkeypatch``.
    ``user_body`` is an optional user ``advisor-boards.toml`` (for a node whose board
    must lack a vendor, a table whose minimum lifts the named-seat rule)."""
    return _granted_context(tier, vendors, task, setenv=monkeypatch.setenv, setattr_=monkeypatch.setattr,
                            user_body=user_body)
