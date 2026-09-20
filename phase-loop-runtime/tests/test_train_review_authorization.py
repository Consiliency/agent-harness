"""agent-harness#906: the coordinator's train review runs through the broker-AUTHORIZED
board, per-leg refusal diagnostics survive a hold, and `--review-only` reviews the admitted
heads and stops before any merge.

The defect these pin: `_default_train_review` reached the review-mode launch boundary via
`governed_planning_gate` -> `invoke_panel` with no `ReviewIsolationAuthorization`; every leg
refused with "missing HARDEN review authorization" and the loop reported only
`no_usable_review` (plan: plans/detailed-train-review-authorization-906-20260920-0640.md).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import train_runner as tr
from phase_loop_runtime.advisor_board import backing as backing_mod
from phase_loop_runtime.advisor_board import composition as composition_mod
from phase_loop_runtime.advisor_board.schema import Board, Seat
from phase_loop_runtime.closeout_validators import ReviewFinding
from phase_loop_runtime.governed_premerge import (
    REVIEW_POLICY_VERSION,
    LoopResult,
    run_governed_premerge_loop,
)
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult
from phase_loop_runtime.train_ledger import LedgerRecord, append_record, read_ledger
from phase_loop_runtime.train_roadmap import parse_train_roadmap
from phase_loop_runtime.train_runner import _default_train_review, run_train

from test_train_merge import (  # noqa: E402
    _approval_review_fn,
    _preflight_pass,
    _pr_is_open_false,
    _pr_is_open_true,
    _rejection_review_fn,
)
from test_train_prebuilt import PREBUILT_1NODE_MD, _make_prebuilt_publish_stub  # noqa: E402

ADMITTED = "sha-admitted-a"
NODE = "repo-a/specs/plan-a.md"


def _approval_with_panel_review_fn(artifact: str, run_mode: str) -> LoopResult:
    """An approval carrying a REAL two-leg panel, the shape the production gate returns,
    so the coordinator stamps ``usable_reviewers`` from ``panel.usable_legs``."""
    panel = PanelResult(legs=[
        PanelLegResult(leg="codex", status="OK", text="Reviewed.\nAGREE"),
        PanelLegResult(leg="gemini", status="OK", text="Reviewed.\nAGREE"),
    ])
    return LoopResult(mergeable=True, ran=True, rounds=1, panel=panel)


def _rejection_with_findings_review_fn(artifact: str, run_mode: str) -> LoopResult:
    """A rejection carrying the per-leg finding the production gate attaches (D3)."""
    base = _rejection_review_fn(artifact, run_mode)
    return LoopResult(
        mergeable=False, ran=True, rounds=1, reason=base.reason,
        terminal_blocker=base.terminal_blocker,
        findings=(ReviewFinding(code="panel_block", reason="leg codex: DISAGREE",
                                severity="block", blocker_class="review_gate_block",
                                body="The merge order is wrong.\nDISAGREE"),),
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _canonical_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("fixture\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    return repo.resolve()


def _seat(harness: str) -> Seat:
    # The fleet-default seat for the lane: its route is HARDEN-supported by construction
    # (routes are derived from these seats, never pinned).
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
    return next(s for s in DEFAULT_SEATS if str(s.harness).lower() == harness)


def _board(*harnesses: str) -> Board:
    return Board(name="train-review", purpose="code-review", seats=tuple(_seat(h) for h in harnesses))


def _legs(board: Board, status: str = "OK", text: str = "Reviewed.\nAGREE", detail: str | None = None):
    return PanelResult(legs=[
        PanelLegResult(leg=seat.harness, status=status, text=text, detail=detail)
        for seat in board.seats
    ])


# ---------------------------------------------------------------------------
# (a) the gate performs the advisor-board CLI's authorization sequence, in order


class TestAuthorizedGateSequence:
    def _run(self, tmp_path, monkeypatch, *, board=None, invoke=None, spawn=None, brief_ref=None,
             raise_in_invoke: Exception | None = None):
        repo = _canonical_repo(tmp_path)
        board = board or _board("codex", "gemini", "grok")
        events: list[str] = []
        sentinel = object()
        digest_token = object()
        observed: dict = {}

        monkeypatch.setattr(backing_mod, "prepare_review_composition_authorization",
                            lambda: events.append("composition_authority"))
        monkeypatch.setattr(backing_mod, "clear_review_composition_authorization",
                            lambda: events.append("clear"))

        def _set_digest(text):
            events.append("digest")
            observed["digest_text"] = text
            return digest_token

        def _reset_digest(token):
            assert token is digest_token
            events.append("reset")

        monkeypatch.setattr(backing_mod, "set_review_instruction_digest", _set_digest)
        monkeypatch.setattr(backing_mod, "reset_review_instruction_digest", _reset_digest)

        def _mint(board_, artifact_, *, mode, canonical_repo_authority):
            events.append("mint")
            observed["minted_artifact"] = artifact_
            observed["minted_mode"] = mode
            observed["minted_authority"] = Path(canonical_repo_authority).resolve()
            return sentinel

        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", _mint)

        def _compose():
            events.append("compose")
            return board

        def _invoke(board_, artifact_, **kw):
            events.append("invoke")
            observed["invoke_board"] = board_
            observed["invoke_kwargs"] = kw
            observed["staged_bytes"] = Path(kw["artifact_ref"]).read_text(encoding="utf-8")
            if raise_in_invoke is not None:
                raise raise_in_invoke
            return (invoke or (lambda b, a, **k: _legs(b)))(board_, artifact_, **kw)

        gate = gr.governed_board_gate(
            artifact="# Train-level bundle review\n\nbundle\n",
            author_executor="train-coordinator",
            run_mode="governed",
            available_legs=("codex", "gemini", "grok"),
            spawn=spawn,
            canonical_repo_authority=repo,
            brief_ref=brief_ref,
            compose=_compose,
            invoke=_invoke,
        )
        return gate, events, observed, sentinel, repo

    def test_cli_order_and_object_identity(self, tmp_path, monkeypatch):
        gate, events, obs, sentinel, repo = self._run(tmp_path, monkeypatch, spawn=None)
        assert events == ["composition_authority", "compose", "clear", "digest", "mint", "invoke", "reset"]
        kw = obs["invoke_kwargs"]
        assert kw["review_authorization"] is sentinel, "the invoker gets the minted object itself"
        assert Path(kw["canonical_repo_authority"]).resolve() == repo
        assert Path(kw["repo_dir"]).resolve() != repo, "provider scratch is never the canonical repo"
        assert obs["minted_authority"] == repo and obs["minted_mode"] == "review"
        assert obs["staged_bytes"] == obs["minted_artifact"], "authorization binds the staged bytes"
        assert obs["digest_text"] == pi._resolve_brief("review", None)
        for forbidden in ("landing_tier", "mode", "president_invoke", "review_policy"):
            assert forbidden not in kw, f"tierless, mode-less call: {forbidden} must not be passed"
        assert "spawn" in kw and kw["spawn"] is None
        assert gate.ran and gate.promoted and gate.panel is not None

    def test_spawn_is_forwarded_as_received(self, tmp_path, monkeypatch):
        marker = object()
        _, _, obs, _, _ = self._run(tmp_path, monkeypatch, spawn=marker)
        assert obs["invoke_kwargs"]["spawn"] is marker

    def test_minted_text_is_the_staged_text_even_with_carriage_returns(self, tmp_path, monkeypatch):
        """Board r1 (claude): ``invoke_board`` resolves ``artifact_ref`` through
        ``read_text`` (universal newlines). The authorization must be minted over THAT
        text, as the CLI does — a CR in the bundle (a roadmap title is free text) must
        not diverge mint from stage and fail the review closed for no reason."""
        repo = _canonical_repo(tmp_path)
        board = _board("codex", "gemini", "grok")
        minted: dict = {}
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                            lambda b, art, **k: minted.setdefault("artifact", art) or object())
        seen: dict = {}

        def _invoke(board_, artifact_, **kw):
            seen["resolved"] = pi._resolve_artifact(None, kw["artifact_ref"])
            seen["passed"] = artifact_
            return _legs(board_)

        bundle = "# Train\r\n\r\ntitle with CR\r\nbundle\r\n"
        gate = gr.governed_board_gate(
            artifact=bundle, author_executor="train-coordinator", run_mode="governed",
            canonical_repo_authority=repo, compose=lambda: board, invoke=_invoke,
        )
        assert gate.promoted
        assert "\r" not in seen["resolved"], "read_text translates CRLF; the staged view is LF"
        assert minted["artifact"] == seen["resolved"] == seen["passed"]

    def test_custom_brief_binds_its_digest_and_is_forwarded(self, tmp_path, monkeypatch):
        brief = tmp_path / "brief.md"
        brief.write_text("custom brief\n")
        _, _, obs, _, _ = self._run(tmp_path, monkeypatch, brief_ref=str(brief))
        assert obs["digest_text"] == "custom brief\n"
        assert obs["invoke_kwargs"]["brief_ref"] == str(brief)

    def test_digest_is_reset_when_the_invoker_raises(self, tmp_path, monkeypatch):
        gate, events, _, _, _ = self._run(tmp_path, monkeypatch, raise_in_invoke=ValueError("boom"))
        assert events[-1] == "reset"
        assert gate.ran and not gate.promoted and gate.reason == "review_isolation_unavailable"

    def test_loop_forwarded_keywords_are_accepted(self, tmp_path, monkeypatch):
        """run_governed_premerge_loop passes available_legs/spawn/repo_dir/max_concurrency."""
        repo = _canonical_repo(tmp_path)
        board = _board("codex", "gemini", "grok")
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                            lambda *a, **k: object())
        seen: dict = {}

        def _invoke(board_, artifact_, **kw):
            seen.update(kw)
            return _legs(board_)

        import functools
        result = run_governed_premerge_loop(
            artifact="bundle", author_executor="train-coordinator", run_mode="governed",
            max_rounds=1, max_concurrency=2,
            invoke=functools.partial(gr.governed_board_gate, canonical_repo_authority=repo,
                                     compose=lambda: board, invoke=_invoke),
        )
        assert result.mergeable is True and seen["max_concurrency"] == 2

    def test_author_vendor_seats_are_excluded(self, tmp_path, monkeypatch):
        repo = _canonical_repo(tmp_path)
        board = _board("codex", "gemini", "grok", "claude")
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                            lambda *a, **k: object())
        seen: dict = {}

        def _invoke(board_, artifact_, **kw):
            seen["harnesses"] = [s.harness for s in board_.seats]
            return _legs(board_)

        gate = gr.governed_board_gate(
            artifact="bundle", author_vendors=("claude",), run_mode="governed",
            canonical_repo_authority=repo, compose=lambda: board, invoke=_invoke,
        )
        assert gate.promoted and seen["harnesses"] == ["codex", "gemini", "grok"]


# ---------------------------------------------------------------------------
# (b) PRODUCTION wiring: the real invoke_board + the real authorization, hermetic


class TestProductionWiring:
    def test_default_train_review_passes_the_launch_boundary_with_a_real_authorization(self, tmp_path, monkeypatch):
        """Enter through `_default_train_review` with the REAL `invoke_board` and the REAL
        `prepare_review_isolation_authorization`, under the sanctioned factory-replacement
        seam (the replacement returns the IDENTICAL minted object on the invoker's own
        lookup) and a hermetic spawn injected through the loop's `spawn` seam. Every leg
        must pass the boundary that refused the coordinator; `invoke_panel` is never called.
        """
        from harden_tdd_guard import harden_require
        harden_require("review-leg-isolation")
        from phase_loop_runtime import governed_premerge as gp_mod
        from phase_loop_runtime.advisor_board.matrix import default_matrix

        repo = _canonical_repo(tmp_path)
        board = _board("codex", "gemini", "grok")
        monkeypatch.setattr(composition_mod, "compose_review_board", lambda: board)

        production_factory = backing_mod.prepare_review_isolation_authorization
        minted: dict = {}

        def identity_stable_factory(board_, artifact_, *, mode, canonical_repo_authority):
            if "auth" not in minted:
                minted["auth"] = production_factory(
                    board_, artifact_, mode=mode, canonical_repo_authority=canonical_repo_authority
                )
            return minted["auth"]

        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", identity_stable_factory)

        revalidated: list[Path] = []
        real_revalidate = pi.revalidate_review_isolation_authorization

        def revalidate(auth, review_board, review_artifact, **kwargs):
            assert auth is minted["auth"], "the invoker validates the object the gate minted"
            revalidated.append(Path(kwargs["canonical_repo_authority"]).resolve())
            return real_revalidate(auth, review_board, review_artifact, **kwargs)

        monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", revalidate)

        spawned: list[str] = []

        def hermetic_spawn(*_args, **_kwargs):
            assert revalidated, "authorization is revalidated before any launch"
            spawned.append("spawn")
            return "OK", "hermetic control\nAGREE"

        real_loop = gp_mod.run_governed_premerge_loop

        def loop_with_spawn(**kw):
            return real_loop(spawn=hermetic_spawn, **kw)

        monkeypatch.setattr(gp_mod, "run_governed_premerge_loop", loop_with_spawn)

        real_invoke = pi.invoke_board

        def invoke_with_static_matrix(board_, artifact_, **kw):
            return real_invoke(
                board_, artifact_, matrix=default_matrix(env={}, probe=lambda _v: True),
                base_env={}, max_concurrency=1, **kw,
            )

        monkeypatch.setattr(pi, "invoke_board", invoke_with_static_matrix)

        def never(*_a, **_k):
            raise AssertionError("invoke_panel must not be on the coordinator's review path")

        monkeypatch.setattr(pi, "invoke_panel", never)
        monkeypatch.setattr(gr, "invoke_panel", never)

        result = _default_train_review(
            "# Train-level bundle review\n\nbundle\n", "governed", canonical_repo_authority=repo
        )
        assert result.mergeable is True, result
        assert result.panel is not None
        statuses = [leg.status for leg in result.panel.legs]
        assert statuses == ["OK", "OK", "OK"], statuses
        assert not any("missing HARDEN review authorization" in (leg.detail or "") for leg in result.panel.legs)
        assert len(spawned) == 3 and revalidated and all(r == repo for r in revalidated)

    def test_negative_control_the_old_route_still_refuses_every_leg(self):
        """Without any seam, the legacy panel route refuses at the boundary — and the
        refusal text now reaches the loop's findings (D3)."""
        result = run_governed_premerge_loop(
            artifact="bundle", author_executor="train-coordinator", run_mode="governed",
            max_rounds=1, available_legs=("codex", "gemini", "grok"),
        )
        assert result.mergeable is False and result.reason == "no_usable_review"
        # The legacy route puts the refusal in the leg TEXT, which `_findings_from_panel`
        # classifies as a non-conforming review (block) carrying that text as body.
        carriers = [
            f for f in result.findings
            if "missing HARDEN review authorization" in (f.reason or "") + (f.body or "")
        ]
        assert len(carriers) == 3, [(f.code, f.reason) for f in result.findings]


# ---------------------------------------------------------------------------
# (c) unavailable / rejected reviewers   (d) per-leg diagnostics survive the hold


class TestHoldsAndDiagnostics:
    def test_below_composition_floor_refuses_before_any_invoke(self, tmp_path, monkeypatch):
        repo = _canonical_repo(tmp_path)
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not mint")))
        gate = gr.governed_board_gate(
            artifact="bundle", author_executor="train-coordinator", run_mode="governed",
            canonical_repo_authority=repo, compose=lambda: _board("codex", "gemini"),
            invoke=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not invoke")),
        )
        assert not gate.promoted and gate.reason == "below_reviewer_floor"
        assert "codex" in gate.findings[0].reason and "gemini" in gate.findings[0].reason

    def test_a_disagreeing_reviewer_holds_with_its_body(self, tmp_path, monkeypatch):
        repo = _canonical_repo(tmp_path)
        board = _board("codex", "gemini", "grok")
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", lambda *a, **k: object())

        def _invoke(board_, artifact_, **kw):
            legs = [PanelLegResult(leg=s.harness, status="OK", text="fine\nAGREE") for s in board_.seats]
            legs[1] = PanelLegResult(leg="gemini", status="OK", text="the digest is unbound\nDISAGREE")
            return PanelResult(legs=legs)

        gate = gr.governed_board_gate(
            artifact="bundle", author_executor="train-coordinator", run_mode="governed",
            canonical_repo_authority=repo, compose=lambda: board, invoke=_invoke,
        )
        assert gate.ran and not gate.promoted
        blocks = [f for f in gate.findings if f.severity == "block"]
        assert blocks and "the digest is unbound" in (blocks[0].body or "")

    def test_zero_usable_hold_keeps_every_legs_status_and_detail_and_the_reason(self, tmp_path, monkeypatch):
        repo = _canonical_repo(tmp_path)
        board = _board("codex", "gemini", "grok")
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", lambda *a, **k: object())

        def _invoke(board_, artifact_, **kw):
            return _legs(board_, status="UNAVAILABLE", text="", detail="missing HARDEN review authorization")

        gate = gr.governed_board_gate(
            artifact="bundle", author_executor="train-coordinator", run_mode="governed",
            canonical_repo_authority=repo, compose=lambda: board, invoke=_invoke,
        )
        assert gate.reason == "no_usable_review" and gate.panel is None, (
            "panel stays None on the zero-usable hold so the reviewer-floor guard is unreached"
        )
        per_leg = [f for f in gate.findings if f.code == "panel_leg_degraded"]
        assert [f.reason for f in per_leg] == [
            f"panel leg {h} unusable (UNAVAILABLE: missing HARDEN review authorization)"
            for h in ("codex", "gemini", "grok")
        ]
        import functools
        loop = run_governed_premerge_loop(
            artifact="bundle", author_executor="train-coordinator", run_mode="governed", max_rounds=1,
            invoke=functools.partial(gr.governed_board_gate, canonical_repo_authority=repo,
                                     compose=lambda: board, invoke=_invoke),
        )
        assert loop.reason == "no_usable_review", "not relabelled below_reviewer_floor"
        assert any("missing HARDEN review authorization" in f.reason for f in loop.findings)


# ---------------------------------------------------------------------------
# (e) stale head   (f) review-only


def _prep_gate(tmp_path, monkeypatch, *, invoke=None):
    """A gate call whose composition succeeds; the caller breaks ONE preparation step."""
    repo = _canonical_repo(tmp_path)
    board = _board("codex", "gemini", "grok")
    minted = []
    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization",
                        lambda *a, **k: minted.append(1) or object())
    invoke_fn = invoke if invoke is not None else (lambda b, a, **k: _legs(b))
    return lambda: gr.governed_board_gate(
        artifact="bundle", author_executor="train-coordinator", run_mode="governed",
        canonical_repo_authority=repo, compose=lambda: board, invoke=invoke_fn,
    ), minted


class _ScratchSpy:
    """Records every scratch the gate allocates so a test can assert its removal."""

    def __init__(self, monkeypatch):
        import tempfile
        self.paths: list[Path] = []
        real = tempfile.mkdtemp

        def _mkdtemp(*a, **k):
            path = real(*a, **k)
            self.paths.append(Path(path))
            return path

        monkeypatch.setattr(tempfile, "mkdtemp", _mkdtemp)


class TestPreparationFailuresHold:
    """Board r1 (agent-harness#914, codex): brief resolution, scratch allocation and the
    digest binding are preparation steps INSIDE the guarded scope — each failure holds
    as ``review_isolation_unavailable`` and leaves neither a bound digest nor a scratch."""

    def test_unreadable_brief_holds_without_binding_a_digest(self, tmp_path, monkeypatch):
        run, minted = _prep_gate(tmp_path, monkeypatch)
        monkeypatch.setattr(pi, "_resolve_brief",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("brief unreadable")))
        monkeypatch.setattr(backing_mod, "set_review_instruction_digest", _Never("set digest"))
        monkeypatch.setattr(backing_mod, "reset_review_instruction_digest", _Never("reset digest"))
        spy = _ScratchSpy(monkeypatch)
        gate = run()
        assert not gate.promoted and gate.reason == "review_isolation_unavailable"
        assert "brief unreadable" in gate.findings[0].reason
        assert spy.paths == [] and minted == []

    def test_scratch_allocation_failure_holds(self, tmp_path, monkeypatch):
        import tempfile
        run, minted = _prep_gate(tmp_path, monkeypatch)
        monkeypatch.setattr(tempfile, "mkdtemp",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("tmp full")))
        monkeypatch.setattr(backing_mod, "reset_review_instruction_digest", _Never("reset digest"))
        gate = run()
        assert not gate.promoted and gate.reason == "review_isolation_unavailable"
        assert "tmp full" in gate.findings[0].reason and minted == []

    def test_digest_refusal_after_scratch_removes_the_scratch(self, tmp_path, monkeypatch):
        run, minted = _prep_gate(tmp_path, monkeypatch)
        spy = _ScratchSpy(monkeypatch)
        monkeypatch.setattr(backing_mod, "set_review_instruction_digest",
                            lambda text: (_ for _ in ()).throw(ValueError("digest refused")))
        monkeypatch.setattr(backing_mod, "reset_review_instruction_digest", _Never("reset digest"))
        gate = run()
        assert not gate.promoted and gate.reason == "review_isolation_unavailable"
        assert "digest refused" in gate.findings[0].reason and minted == []
        assert len(spy.paths) == 1 and not spy.paths[0].exists()

    @pytest.mark.parametrize("exc", [
        subprocess.TimeoutExpired(cmd=["codex"], timeout=1),
        subprocess.CalledProcessError(1, ["codex"]),
    ])
    def test_subprocess_failure_during_invocation_holds(self, tmp_path, monkeypatch, exc):
        run, _ = _prep_gate(tmp_path, monkeypatch,
                            invoke=lambda *a, **k: (_ for _ in ()).throw(exc))
        spy = _ScratchSpy(monkeypatch)
        gate = run()
        assert not gate.promoted and gate.reason == "review_isolation_unavailable"
        assert gate.findings[0].code == "governed_board_isolation_unavailable"
        assert len(spy.paths) == 1 and not spy.paths[0].exists()

    def test_subprocess_failure_during_composition_holds(self, tmp_path, monkeypatch):
        repo = _canonical_repo(tmp_path)
        gate = gr.governed_board_gate(
            artifact="bundle", author_executor="train-coordinator", run_mode="governed",
            canonical_repo_authority=repo,
            compose=lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["agy"], timeout=1)),
            invoke=_Never("invoke"),
        )
        assert not gate.promoted and gate.reason == "review_isolation_unavailable"
        assert gate.findings[0].code == "governed_board_composition_unavailable"

    def test_successful_review_removes_its_scratch(self, tmp_path, monkeypatch):
        run, minted = _prep_gate(tmp_path, monkeypatch)
        spy = _ScratchSpy(monkeypatch)
        gate = run()
        assert gate.promoted and minted == [1]
        assert len(spy.paths) == 1 and not spy.paths[0].exists()


def _ledger(tmp_path: Path, *, approved: int | None = None) -> Path:
    ledger = tmp_path / "ledger" / "train.ledger.jsonl"
    append_record(ledger, LedgerRecord(
        node_id=NODE, status="pr_open", branch="feat/train-repo-a",
        head_sha=ADMITTED, pr_url="https://gh.com/repo-a/pr/1", merge_order=0,
    ))
    if approved is not None:
        append_record(ledger, LedgerRecord(
            node_id=tr._TRAIN_REVIEW_NODE_ID, status="approved",
            usable_reviewers=approved, review_policy_version="test",
        ))
    return ledger


class _Never:
    def __init__(self, what):
        self.what = what
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError(f"{self.what} must not be called")


def _run_review(tmp_path, ledger, *, review_only, review_fn=_approval_review_fn, live=ADMITTED,
                head=ADMITTED, pr_open=_pr_is_open_true, merge_pr=None, publish=None):
    roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
    ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
    merged: list = []

    def _merge(workspace, branch, base="main", head_sha=None):
        merged.append((workspace.name, head_sha))
        return f"sha-merged-{workspace.name}"

    result = run_train(
        roadmap, ledger, run_mode="governed",
        resolve_workspace=lambda n: ws_map[n.node_id],
        _run_loop=lambda *a, **kw: (None, []),
        _publish=publish or _make_prebuilt_publish_stub({}),
        _set_upstream_ref_fn=lambda *a, **kw: [],
        _preflight_fn=_preflight_pass,
        _pr_is_open=pr_open,
        _live_pr_head_sha_fn=lambda ws, br: live,
        _workspace_head_fn=lambda ws: head,
        _is_ancestor_fn=lambda ws, a, b: True,
        _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"],
        _merge_phase_enabled=True,
        review_only=review_only,
        _train_review_fn=review_fn,
        _merge_pr_fn=merge_pr or _merge,
        _reverify_fn=lambda *a, **k: True,
        _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
    )
    return result, merged


class TestReviewOnly:
    def test_approved_records_and_stops_before_any_merge_or_publish(self, tmp_path):
        ledger = _ledger(tmp_path)
        publish = _Never("publish_fn")
        merge = _Never("merge_pr_fn")
        result, _ = _run_review(tmp_path, ledger, review_only=True, publish=publish, merge_pr=merge)
        assert result["status"] == "review_approved", result
        assert publish.calls == 0 and merge.calls == 0
        rec = read_ledger(ledger)[tr._TRAIN_REVIEW_NODE_ID]
        assert rec.status == "approved"

    def test_review_only_approval_then_governed_run_merges_without_re_board(self, tmp_path):
        """Two real invocations over ONE ledger (board r1, codex): the review-only run
        records the usable-reviewer floor evidence from its panel; the later governed
        run honours it and merges the ADMITTED head without spending a second board."""
        ledger = _ledger(tmp_path)
        first, merged_first = _run_review(tmp_path, ledger, review_only=True,
                                          review_fn=_approval_with_panel_review_fn)
        assert first["status"] == "review_approved" and merged_first == []
        assert first["usable_reviewers"] == 2
        rec = read_ledger(ledger)[tr._TRAIN_REVIEW_NODE_ID]
        assert rec.usable_reviewers == 2 and rec.review_policy_version == REVIEW_POLICY_VERSION
        second, merged_second = _run_review(tmp_path, ledger, review_only=False,
                                            review_fn=_Never("train_review_fn"))
        assert second["status"] == "merged", second
        assert merged_second == [("repo-a", ADMITTED)]

    def test_later_governed_run_merges_without_re_review(self, tmp_path):
        ledger = _ledger(tmp_path, approved=3)
        result, merged = _run_review(tmp_path, ledger, review_only=False, review_fn=_Never("train_review_fn"))
        assert result["status"] == "merged", result
        assert merged == [("repo-a", ADMITTED)], "merge pinned to the admitted head, no re-board"

    def test_review_only_on_an_approved_train_returns_without_re_board(self, tmp_path):
        ledger = _ledger(tmp_path, approved=3)
        result, merged = _run_review(tmp_path, ledger, review_only=True, review_fn=_Never("train_review_fn"))
        assert result["status"] == "review_approved" and result["usable_reviewers"] == 3
        assert merged == []

    def test_rejected_review_halts_with_zero_merges_and_carries_findings(self, tmp_path):
        ledger = _ledger(tmp_path)
        result, merged = _run_review(tmp_path, ledger, review_only=True,
                                     review_fn=_rejection_with_findings_review_fn)
        assert result["status"] == "review_halted" and merged == []
        assert result["findings"], "the per-leg diagnostics must reach the caller"
        assert result["findings"][0] == {
            "code": "panel_block", "reason": "leg codex: DISAGREE", "severity": "block",
            "body": "The merge order is wrong.\nDISAGREE",
        }
        assert result["terminal_blocker"]["blocker_class"] == "review_gate_block"

    def test_node_without_admitted_pr_is_refused_before_publication(self, tmp_path):
        ledger = _ledger(tmp_path)
        publish = _Never("publish_fn")
        result, _ = _run_review(tmp_path, ledger, review_only=True, pr_open=_pr_is_open_false,
                                publish=publish, review_fn=_Never("train_review_fn"))
        assert result["status"] == "review_only_requires_admitted_prs", result
        assert result["detail"]["reason"] == "nodes_without_admitted_pr"
        assert publish.calls == 0

    def test_advanced_local_candidate_is_refused_not_published(self, tmp_path):
        """The agent-harness#909 refresh shape: an admitted open PR and a fast-forwarded
        workspace publish on a normal run; under review-only they must refuse."""
        ledger = _ledger(tmp_path)
        publish = _Never("publish_fn")
        result, _ = _run_review(tmp_path, ledger, review_only=True, head="sha-new-a",
                                publish=publish, review_fn=_Never("train_review_fn"))
        assert result["status"] == "review_only_requires_admitted_prs", result
        assert result["detail"]["reason"] == "local_candidate_not_admitted"
        assert result["detail"]["workspace_head"] == "sha-new-a"
        assert publish.calls == 0

    def test_unreadable_workspace_head_is_refused_not_approved(self, tmp_path):
        """Board r1 (claude): the refresh arm refuses an unreadable HEAD by type; the
        review-only guard must not be looser than the arm it protects."""
        ledger = _ledger(tmp_path)
        publish = _Never("publish_fn")
        result, merged = _run_review(tmp_path, ledger, review_only=True, head=None,
                                     publish=publish, review_fn=_Never("train_review_fn"))
        assert result["status"] == "review_only_requires_admitted_prs", result
        assert result["detail"]["reason"] == "workspace_head_unreadable"
        assert result["detail"]["node_id"] == NODE and merged == [] and publish.calls == 0
        assert tr._TRAIN_REVIEW_NODE_ID not in read_ledger(ledger)

    def test_stale_live_head_halts_before_any_board_even_when_approved(self, tmp_path):
        for approved in (None, 3):
            ledger = _ledger(tmp_path / f"case-{approved}", approved=approved)
            result, merged = _run_review(tmp_path / f"case-{approved}", ledger, review_only=True,
                                         live="sha-oob-a", review_fn=_Never("train_review_fn"))
            assert result["status"] == "review_halted" and result["reason"] == "stale_head", result
            assert result["detail"]["stale"][0]["node_id"] == NODE
            assert merged == []

    def test_cli_review_only_requires_governed(self, tmp_path):
        from phase_loop_runtime import cli
        train = tmp_path / "train.md"
        train.write_text(PREBUILT_1NODE_MD)
        with pytest.raises(SystemExit) as exc:
            cli.main(["run-train", "--train", str(train), "--review-only"])
        assert exc.value.code == 2


class TestCanonicalRepoAuthorityResolution:
    """agent-harness#906 D2 (board r1, gemini): the authority the coordinator binds the
    isolation authorization to — cwd git toplevel, else the first node's workspace,
    else no authority (the gate then refuses ``review_isolation_unavailable``)."""

    @staticmethod
    def _topo():
        return parse_train_roadmap(PREBUILT_1NODE_MD).topo_order()

    def test_cwd_git_toplevel_wins_over_node_workspaces(self, tmp_path, monkeypatch):
        repo = _canonical_repo(tmp_path)
        other = tmp_path / "node-ws"
        other.mkdir()
        monkeypatch.chdir(repo)
        got = tr._train_canonical_repo_authority(self._topo(), lambda node: other)
        assert got == repo.resolve()

    def test_non_git_cwd_falls_back_to_first_node_workspace(self, tmp_path, monkeypatch):
        plain = tmp_path / "plain"
        plain.mkdir()
        ws = tmp_path / "node-ws"
        ws.mkdir()
        monkeypatch.chdir(plain)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        got = tr._train_canonical_repo_authority(self._topo(), lambda node: ws)
        assert got == ws.resolve()

    @pytest.mark.parametrize("exc", [
        FileNotFoundError("git"), subprocess.TimeoutExpired(cmd=["git"], timeout=15),
    ])
    def test_git_failure_falls_back_to_first_node_workspace(self, tmp_path, monkeypatch, exc):
        ws = tmp_path / "node-ws"
        ws.mkdir()
        monkeypatch.setattr(tr.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(exc))
        got = tr._train_canonical_repo_authority(self._topo(), lambda node: ws)
        assert got == ws.resolve()

    def test_no_git_and_no_workspace_yields_no_authority(self, tmp_path, monkeypatch):
        plain = tmp_path / "plain"
        plain.mkdir()
        monkeypatch.chdir(plain)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

        def _no_ws(node):
            raise KeyError(node.node_id)

        assert tr._train_canonical_repo_authority(self._topo(), _no_ws) is None
