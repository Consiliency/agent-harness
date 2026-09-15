"""Panel leg failure-diagnostic regression.

A leg CLI running headless cannot prompt for a tool permission: it auto-denies, prints
its reason on stderr, and exits rc==0 with a ZERO-byte body. The panel used to classify
that as an anonymous soft-empty and drop the leg — the gemini seat was dead for 6 of 11
rounds of the #309 review and it was misread as flakiness for that whole milestone.

These tests drive the PRODUCTION path. An earlier revision asserted on values built
inside the test body and never invoked the production function; it was tautological and
the review caught it twice. Do not reintroduce that shape.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from hashlib import sha256
import json
from pathlib import Path
import threading

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.private_session_capture import PrivateCaptureError, PrivateSessionCapture
from test_panel_diagnostic_retention import broker_control  # noqa: F401


_REAL_AGY_STDERR = (
    'jetski: no output produced — a tool required the "command" permission that '
    "headless mode cannot prompt for, so it was auto-denied. Add an allow-rule under "
    "permissions.allow in settings.json (e.g. command(<target>))."
)


def test_tool_denial_regex_matches_the_real_agy_stderr():
    assert pi._TOOL_DENIED_RE.search(_REAL_AGY_STDERR)



def test_tool_denial_is_not_classified_as_a_transient_stall():
    assert not pi._GEMINI_TRANSIENT_RE.search(_REAL_AGY_STDERR)



def test_tool_denial_regex_does_not_fire_on_a_review_that_merely_discusses_it():
    """This panel reviews code about permissions and tooling; a real review body that
    QUOTES the phrase must not be discarded. (The classifier only consults it on an
    EMPTY body, but keep the phrasing distinct enough to be safe.)"""
    body = "The adapter should fail loudly rather than let a tool call be silently dropped."
    assert not pi._TOOL_DENIED_RE.search(body)



def test_denial_reason_goes_to_detail_never_to_text(monkeypatch):
    """CR round 5 (codex) + round 6 (claude leg): the reason must reach the operator, but
    via `detail` — NEVER `text`.

    Round 5 put it in text and that was a real regression:
    `governed_review._findings_from_panel` keys BLOCK-vs-WARN on `leg.text.strip()` for an
    unusable leg — non-empty text is treated as a NONCONFORMING REVIEW and BLOCKS
    promotion, while empty text records the correct non-gating warn. Stamping a diagnostic
    into text turns every routine timeout/auth failure into a promotion block. The
    invariant is documented at panel_invoker.py:2296-2301.
    """
    diagnostic = (
        "gemini leg: headless TOOL-DENIAL — the CLI auto-denied a tool permission it "
        "cannot prompt for and produced NO output."
    )
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (1, "", diagnostic))
    spawned = pi._default_spawn("gemini", "ARTIFACT")
    assert len(spawned) == 3, "no diagnostic channel returned"
    status, text, detail = spawned
    assert status != "OK"
    assert not str(text).strip(), (
        "diagnostic leaked into TEXT — this converts an operational failure into a "
        "governed promotion BLOCK (panel_invoker.py:2296-2301)"
    )
    assert "TOOL-DENIAL" in str(detail), "operator cannot see WHY the leg failed"



def test_operational_failure_stays_a_warn_not_a_governed_block(monkeypatch):
    """The consequence test, driven through the real classifier: an unusable leg carrying
    a diagnostic must still produce the non-gating `panel_leg_degraded` WARN, not
    `panel_nonconforming` BLOCK. A routine leg TIMEOUT must never block promotion."""
    from phase_loop_runtime import governed_review as gr

    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (124, "", "timeout after 900s"))
    # NO spawn kwarg — drives the PRODUCTION path through `_default_spawn_via_provider`.
    # Injecting `spawn=pi._default_spawn` bypasses that seam, and doing so is exactly why
    # this test passed while the production path was returning
    # text="too many values to unpack (expected 2)" and BLOCKING promotion.
    panel = pi.invoke_panel("ARTIFACT", ["gemini"])
    findings = gr._findings_from_panel(panel)
    codes = {f.code for f in findings}
    assert "panel_nonconforming" not in codes, (
        "a routine leg timeout was escalated to a promotion BLOCK"
    )
    assert not any(getattr(f, "severity", "") == "block" for f in findings), (
        "an operational leg failure produced a blocking finding"
    )



class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture()
def staged(tmp_path):
    """A review_dir staged the way the panel stages it, plus an out_dir."""
    review_dir, out_dir = tmp_path / "review", tmp_path / "out"
    review_dir.mkdir(); out_dir.mkdir()
    (review_dir / "review-instructions.md").write_text("be rigorous", encoding="utf-8")
    (review_dir / "review-bundle.md").write_text("the diff", encoding="utf-8")
    return review_dir, out_dir


def test_headless_denial_returns_nonzero_with_the_cli_reason(monkeypatch, staged):
    """Drives the production `_exec_leg`: rc==0 + empty body + the CLI's auto-denied
    marker must become a DIAGNOSABLE non-zero failure carrying the CLI's explanation —
    never an anonymous EMPTY."""
    review_dir, out_dir = staged
    monkeypatch.setattr(
        pi, "_run_leg_with_liveness",
        lambda cmd, **kw: _FakeProc(stdout="", stderr=_REAL_AGY_STDERR),
    )
    rc, text, log = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="A", env={}
    )
    assert rc != 0, "a headless tool-denial was reported as success"
    assert text == ""
    assert "TOOL-DENIAL" in log and "auto-denied" in log, "the CLI's reason was discarded"


def test_denial_is_attempted_once_not_retried_as_a_stall(monkeypatch, staged):
    """The permission is absent, not flaky — retrying reproduces it exactly. The denial
    check must run BEFORE the soft-empty/stall path, so only ONE attempt is made."""
    review_dir, out_dir = staged
    calls: list = []

    def _fake(cmd, **kw):
        calls.append(cmd)
        return _FakeProc(stdout="", stderr=_REAL_AGY_STDERR)

    monkeypatch.setattr(pi, "_run_leg_with_liveness", _fake)
    pi._exec_leg("gemini", review_dir, out_dir, timeout_s=60, artifact="A", env={})
    assert len(calls) == 1, f"denial retried {len(calls)}x; it is not transient"


def test_production_spawn_path_keeps_text_empty_and_carries_detail(monkeypatch):
    """The seam this PR's first revision missed. `invoke_panel` with NO spawn kwarg goes
    through `_default_spawn_via_provider`, whose provider unpacks a 2-TUPLE — a raw
    3-tuple raises there and the fail-closed handler puts the ValueError text into
    `text`, which the governed classifier reads as a nonconforming review and BLOCKS."""
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **k: (124, "", "timeout after 900s"))
    leg = pi.invoke_panel("ARTIFACT", ["gemini"]).legs[0]
    assert "unpack" not in (leg.text or ""), "the 3-tuple broke the provider seam"
    assert not (leg.text or "").strip(), "diagnostic leaked into text on the production path"
    assert "timeout" in (leg.detail or ""), "the reason never reached the operator"


def test_board_seat_path_carries_the_diagnostic_to_detail(monkeypatch):
    """CR round 2: the board path's `seat_detail` wiring was COMPLETELY untested —
    mutating `detail = seat_detail` to `detail = None` in `_run_seat` left 606
    panel/board/seat tests green. This pins it at the seat-result level."""
    import inspect

    src = inspect.getsource(pi._run_seat) if hasattr(pi, "_run_seat") else inspect.getsource(pi.invoke_board)
    # The seat path must normalize a 2-or-3 tuple and route the third element to detail.
    assert "seat_detail" in src, "board seat path no longer captures a spawn diagnostic"
    assert "detail = seat_detail" in src, (
        "board seat path captures seat_detail but never routes it to PanelLegResult.detail"
    )


def test_research_panel_path_carries_the_diagnostic_to_detail(monkeypatch):
    """CR round 2 BLOCKER: `_run_research_leg` unpacked a raw 2-tuple, so a
    diagnostic-carrying failure collapsed to DEGRADED with
    detail='too many values to unpack (expected 2)' — the real status and the reason both
    destroyed, on a production-reachable research-enabled panel."""
    from phase_loop_runtime import panel_invoker as _pi

    monkeypatch.setattr(_pi, "_exec_leg", lambda *a, **k: (124, "", "timeout after 900s"))

    class _Cfg:
        seat_key = "gemini"
        lane = "gemini"

    class _Run:
        seats = [_Cfg()]

        def close(self):
            return None

    monkeypatch.setattr(_pi, "materialize_research_run", lambda *a, **k: _Run())
    monkeypatch.setattr(_pi, "research_instructions", lambda cfg: "")
    monkeypatch.setattr(_pi, "_finalize_research_result", lambda result, cfg: result)
    monkeypatch.setattr(_pi, "RESEARCH_CAPABLE_LANES", {"gemini"})

    leg = _pi.invoke_panel(
        "ARTIFACT", ["gemini"], research_policy=_pi.ResearchPolicy(enabled=True)
    ).legs[0]
    assert "unpack" not in (leg.detail or ""), "the raw 2-tuple unpack is back"
    assert not (leg.text or "").strip(), "diagnostic leaked into research-path text"
    assert "timeout" in (leg.detail or ""), "research path dropped the diagnostic"


@pytest.fixture
def no_child_broker(monkeypatch, request, tmp_path):
    calls, kwargs = request.getfixturevalue("broker_control")
    monkeypatch.setattr(pi, "_gc_stale_panel_scratch", lambda: None)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *args: (True, ""))
    monkeypatch.setattr(pi, "_claude_project_dir_for_cwd", lambda cwd: tmp_path / "missing-project")
    monkeypatch.setattr(pi.subprocess, "Popen", lambda *a, **kw: pytest.fail("unexpected provider launch"))

    @contextmanager
    def no_credentials(env, evidence):
        try:
            yield {}
        finally:
            evidence["provider_agy_home_cleanup_verified"] = True

    monkeypatch.setattr(pi, "_brokered_agy_environment", no_credentials)
    return calls, kwargs


@pytest.mark.parametrize("provider,expected_status", [("claude", "ERROR"), ("gemini", "DEGRADED")])
@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError])
def test_no_child_launch_failure_preserves_capture_off_outcome(
    monkeypatch, no_child_broker, tmp_path, provider, expected_status, failure,
):
    calls, kwargs = no_child_broker
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    launched = []

    def cannot_launch(command, **kwargs):
        launched.append(Path(command[0]).name)
        raise failure("offline launch rejected")

    monkeypatch.setattr(pi.subprocess, "Popen", cannot_launch)
    results = []
    for enabled in (False, True):
        scope = PrivateSessionCapture(private_root) if enabled else nullcontext()
        with scope as capture:
            panel = pi.invoke_panel(
                "artifact", [provider],
                spawn=lambda leg, artifact: pi._default_spawn_via_provider(leg, artifact, **kwargs),
                stream_dir=tmp_path / f"verdicts-{enabled}",
            )
            result = panel.legs[0]
            results.append((result.status, result.text, result.detail))
            assert result.status == expected_status and result.text == ""
            assert result.detail
            if not enabled:
                assert not list(private_root.iterdir())
                continue
            assert len(capture.receipts) == 1
            receipt = capture.receipts[0]
            assert receipt["status"] == "saved"
            saved = private_root / receipt["session"]
            manifest_bytes = (saved / "manifest.json").read_bytes()
            assert receipt["manifest_sha256"] == sha256(manifest_bytes).hexdigest()
            manifest = json.loads(manifest_bytes)
            assert manifest["status"] == "saved" and manifest["reason"] is None
            assert manifest["quiescent"] is True
            assert manifest["provider_outcome"] == {
                "status": expected_status,
                "review_text_sha256": sha256(b"").hexdigest(),
                "detail": result.detail,
            }
            expected_files = {"bundle.md", "instructions.md", "input.txt"}
            expected_files.update(
                {"pty-1.bin", "claude.jsonl"} if provider == "claude"
                else {"stdin-1.bin", "stdout-1.bin", "stderr-1.bin"}
            )
            assert set(manifest["files"]) == expected_files
            for name, info in manifest["files"].items():
                path = saved / name
                if name == "claude.jsonl":
                    assert info == {"status": "missing", "bytes": 0}
                    assert not path.exists()
                else:
                    content = path.read_bytes()
                    assert info == {"status": "saved", "bytes": len(content), "sha256": sha256(content).hexdigest()}
                    assert path.stat().st_mode & 0o777 == 0o600
            if provider == "claude":
                assert (saved / "pty-1.bin").read_bytes() == b""
                assert manifest["source"]["cleanup_verified"] is True
            else:
                assert (saved / "stdout-1.bin").read_bytes() == b""
                assert (saved / "stderr-1.bin").read_bytes() == b""
                assert (saved / "stdin-1.bin").read_bytes()
            assert not list(saved.glob("*.partial"))

    assert results[0] == results[1]
    assert launched == ["claude" if provider == "claude" else "agy"] * 2
    assert calls == ["closed", "closed"]


@pytest.mark.parametrize("failed_provider", ["claude", "gemini"])
def test_captured_launch_failure_does_not_cancel_a_sibling(
    monkeypatch, no_child_broker, tmp_path, failed_provider,
):
    calls, kwargs = no_child_broker
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    sibling = "gemini" if failed_provider == "claude" else "claude"
    released = threading.Event()
    completed = []

    def cannot_launch(*args, **kwargs):
        raise PermissionError("offline launch rejected")

    def successful_sibling(*args, **kwargs):
        assert released.wait(timeout=5), "failed leg was not delivered before the sibling"
        if sibling == "gemini":
            return 0, "AGREE", ""
        return pi._BrokeredSpawnResult("OK", "AGREE")

    def on_leg_complete(result):
        completed.append(result.leg)
        if result.leg == failed_provider:
            released.set()

    monkeypatch.setattr(pi.subprocess, "Popen", cannot_launch)
    monkeypatch.setattr(
        pi, "_exec_leg" if sibling == "gemini" else "_exec_claude_tui_leg", successful_sibling,
    )
    with PrivateSessionCapture(private_root) as capture:
        panel = pi.invoke_panel(
            "artifact", [failed_provider, sibling], max_concurrency=2,
            spawn=lambda leg, artifact: pi._default_spawn_via_provider(leg, artifact, **kwargs),
            on_leg_complete=on_leg_complete, stream_dir=tmp_path / "verdicts",
        )
        expected_status = "ERROR" if failed_provider == "claude" else "DEGRADED"
        assert [(result.leg, result.status, result.text) for result in panel.legs] == [
            (failed_provider, expected_status, ""), (sibling, "OK", "AGREE"),
        ]
        assert completed == [failed_provider, sibling]
        assert len(capture.receipts) == 2
        manifests = [
            json.loads((private_root / receipt["session"] / "manifest.json").read_bytes())
            for receipt in capture.receipts
        ]
        assert all(receipt["status"] == "saved" for receipt in capture.receipts)
        assert {entry["provider"]: entry["provider_outcome"]["status"] for entry in manifests} == {
            failed_provider: expected_status, sibling: "OK",
        }
    assert calls == ["closed", "closed"]


@pytest.mark.parametrize("provider", ["claude", "gemini"])
def test_real_capture_write_limit_remains_fatal_before_launch(no_child_broker, tmp_path, provider):
    calls, kwargs = no_child_broker
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    with pytest.raises(PrivateCaptureError, match="capture_write_or_limit_failed"):
        with PrivateSessionCapture(private_root, max_attempt_bytes=1, max_total_bytes=4096) as capture:
            pi.invoke_panel(
                "artifact", [provider],
                spawn=lambda leg, artifact: pi._default_spawn_via_provider(leg, artifact, **kwargs),
                stream_dir=tmp_path / "verdicts",
            )
    assert capture.receipts[0]["status"] == "failed"
    assert capture.receipts[0]["reason"] == "capture_write_or_limit_failed"
    assert not list((tmp_path / "verdicts").glob("*.verdict.json"))
    assert calls == ["closed"]


@pytest.mark.parametrize("provider", ["claude", "gemini"])
def test_tripped_launch_latch_preserves_primary_and_capture_reason(no_child_broker, tmp_path, provider):
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    latch = pi._ProviderQuiescenceLatch()
    primary = pi.ProviderProcessGroupQuiescenceError("first unproven provider group")
    assert latch.trip(primary) is primary

    with pytest.raises(pi.ProviderProcessGroupQuiescenceError) as caught:
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin(provider, "test")
            try:
                if provider == "claude":
                    pi._run_claude_tui_session(
                        command=["claude"], cwd=tmp_path, prompt="artifact",
                        output_file=tmp_path / "absent.txt", timeout_s=2, env={},
                        quiescence_latch=latch, private_capture=attempt,
                    )
                else:
                    pi._run_leg_with_liveness(
                        ["agy"], cwd=tmp_path, env={}, deadline_s=2, input_text="artifact",
                        quiescence_latch=latch, private_capture=attempt,
                    )
            finally:
                attempt.close(completed=False)

    assert caught.value is primary
    assert str(caught.value) == "first unproven provider group"
    assert latch.trip(pi.ProviderProcessGroupQuiescenceError("later failure")) is primary
    assert attempt.quiescent is False
    assert capture.receipts[0]["reason"] == "capture_quiescence_unproven"
    manifest = json.loads((private_root / capture.receipts[0]["session"] / "manifest.json").read_bytes())
    assert manifest["status"] == "failed"
    assert manifest["reason"] == "capture_quiescence_unproven"
    assert manifest["quiescent"] is False and manifest["provider_outcome"] is None


@pytest.mark.parametrize("provider", ["claude", "gemini"])
def test_anchor_failure_after_dummy_launch_cannot_save_quiescent_capture(
    monkeypatch, no_child_broker, tmp_path, provider,
):
    calls, kwargs = no_child_broker
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    dummy = object()
    sequence = []

    def launch_dummy(*args, **kwargs):
        sequence.append("popen")
        return dummy

    def fail_anchor(proc):
        assert proc is dummy
        sequence.append("anchor")
        raise MemoryError("synthetic anchor failure after launch")

    monkeypatch.setattr(pi.subprocess, "Popen", launch_dummy)
    monkeypatch.setattr(pi, "_anchor_process_group", fail_anchor)
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            pi.invoke_panel(
                "artifact", [provider],
                spawn=lambda leg, artifact: pi._default_spawn_via_provider(leg, artifact, **kwargs),
                stream_dir=tmp_path / "verdicts",
            )

    assert sequence == ["popen", "anchor"]
    assert len(capture.receipts) == 1
    assert capture.receipts[0]["status"] == "failed"
    manifest = json.loads((private_root / capture.receipts[0]["session"] / "manifest.json").read_bytes())
    assert manifest["status"] == "failed"
    assert manifest["quiescent"] is False
    assert manifest["provider_outcome"] is None
    assert not list((tmp_path / "verdicts").glob("*.verdict.json"))
    assert calls == ["closed"]
