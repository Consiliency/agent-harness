"""Offline process and broker controls for private capture before cleanup."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.advisor_board import Board, Seat
from phase_loop_runtime.private_session_capture import PrivateCaptureError, PrivateSessionCapture
from harden_tdd_guard import invoke_sanctioned_board_control
from test_panel_diagnostic_retention import broker_control  # noqa: F401


@pytest.fixture
def private_root(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return root


def _attempt_path(root, capture):
    return root / capture.receipts[-1]["session"]


@pytest.mark.parametrize("returncode", [0, 3])
def test_pipe_capture_preserves_raw_bytes_and_provider_result(tmp_path, private_root, returncode):
    out, err = b"raw-stdout:\xff\n", b"raw-stderr:\xfe\n"
    script = f"import os,sys; sys.stdin.buffer.read(); os.write(1,{out!r}); os.write(2,{err!r}); sys.exit({returncode})"
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("gemini", "test")
        result = pi._run_leg_with_liveness(
            [sys.executable, "-c", script], cwd=tmp_path, env={}, deadline_s=5,
            input_text="exact input\n", private_capture=attempt,
        )
        assert result.returncode == returncode
        assert attempt.quiescent
        attempt.close(completed=True)
        saved = _attempt_path(private_root, capture)
        assert (saved / "stdout-1.bin").read_bytes() == out
        assert (saved / "stderr-1.bin").read_bytes() == err
        assert (saved / "stdin-1.bin").read_bytes() == b"exact input\n"
        assert capture.receipts[0]["status"] == "saved"


def test_timeout_capture_drains_shutdown_bytes(tmp_path, private_root, monkeypatch):
    monkeypatch.setattr(pi, "_LEG_LIVENESS_READ_INTERVAL_S", 0.01)
    script = (
        "import os,signal,time,sys; "
        "signal.signal(signal.SIGTERM,lambda *a:(os.write(1,b'late-shutdown'),sys.exit(0))); "
        "os.write(1,b'ready:'); time.sleep(10)"
    )
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("gemini", "test")
        with pytest.raises(subprocess.TimeoutExpired):
            pi._run_leg_with_liveness(
                [sys.executable, "-c", script], cwd=tmp_path, env={},
                deadline_s=0.4, private_capture=attempt,
            )
        assert attempt.quiescent
        attempt.close(completed=True)
        assert (_attempt_path(private_root, capture) / "stdout-1.bin").read_bytes() == b"ready:late-shutdown"


def test_real_offline_pty_capture_preserves_original_bytes(tmp_path, private_root):
    raw = b"terminal-output:\xff"
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("claude", "test")
        result = pi._run_claude_tui_session(
            command=[sys.executable, "-c", f"import os; os.write(1,{raw!r})"],
            cwd=tmp_path, prompt="unused offline input", output_file=tmp_path / "absent.txt",
            timeout_s=2, backstop_s=2, env={}, private_capture=attempt,
        )
        assert result[0] != 0 and not result[1]
        assert attempt.quiescent
        attempt.close(completed=True)
        assert (_attempt_path(private_root, capture) / "pty-1.bin").read_bytes() == raw


def test_final_pipe_read_failure_cannot_claim_complete_capture(tmp_path, private_root, monkeypatch):
    actual = os.set_blocking
    failing = set()
    read = os.read

    def nonblocking(fd, enabled):
        actual(fd, enabled)
        if not enabled:
            failing.add(fd)

    def fail_final(fd, count):
        if fd in failing:
            raise OSError(errno.EBADF, "PLANTED_SECRET")
        return read(fd, count)

    monkeypatch.setattr(os, "set_blocking", nonblocking)
    monkeypatch.setattr(os, "read", fail_final)
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("gemini", "test")
            result = pi._run_leg_with_liveness(
                [sys.executable, "-c", "print('finished')"], cwd=tmp_path,
                env={}, deadline_s=5, private_capture=attempt,
            )
            assert result.returncode == 0
            assert attempt.quiescent
            attempt.close(completed=True)
            assert capture.receipts[0]["status"] == "failed"
            assert "PLANTED_SECRET" not in str(capture.receipts)


def test_verified_transcript_survives_native_cleanup(tmp_path, private_root):
    transcript = tmp_path / "exact-session.jsonl"
    original = b'{"type":"assistant","content":"original"}\n\xff'
    transcript.write_bytes(original)
    unrelated = tmp_path / "unrelated.jsonl"
    unrelated.write_bytes(b"DO_NOT_READ")
    evidence = {}
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("claude", "test")
        assert pi._cleanup_broker_claude_transcript(transcript, evidence, private_capture=attempt)
        attempt.close(completed=True)
        assert not transcript.exists()
        assert unrelated.read_bytes() == b"DO_NOT_READ"
        saved = _attempt_path(private_root, capture)
        assert (saved / "claude.jsonl").read_bytes() == original
        assert evidence["claude_transcript_sha256"] == sha256(original).hexdigest()
        assert evidence["claude_transcript_cleanup_verified"]
        assert capture.receipts[0]["source"] == {
            "path": str(transcript), "cleanup_verified": True,
        }
        assert not list(tmp_path.glob(".phase-loop-retained-*"))


def test_capture_failure_preserves_exact_original_transcript(tmp_path, private_root, monkeypatch):
    transcript = tmp_path / "exact.jsonl"
    transcript.write_bytes(b"ORIGINAL")
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")

            def no_sync(fd):
                raise OSError("PLANTED_SECRET")

            monkeypatch.setattr(os, "fsync", no_sync)
            try:
                pi._cleanup_broker_claude_transcript(transcript, {}, private_capture=attempt)
            finally:
                attempt.close(completed=False)
    assert transcript.read_bytes() == b"ORIGINAL"


def test_transcript_created_after_missing_observation_is_not_deleted(tmp_path, private_root, monkeypatch):
    transcript = tmp_path / "exact.jsonl"
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")
            original = attempt.copy_transcript

            def appeared(path, **kwargs):
                result = original(path, **kwargs)
                path.write_bytes(b"NEW_UNCAPTURED")
                return result

            monkeypatch.setattr(attempt, "copy_transcript", appeared)
            try:
                pi._cleanup_broker_claude_transcript(transcript, {}, private_capture=attempt)
            finally:
                attempt.close(completed=False)
    assert transcript.read_bytes() == b"NEW_UNCAPTURED"


def test_replacement_at_retirement_is_restored_not_deleted(tmp_path, private_root, monkeypatch):
    transcript = tmp_path / "exact.jsonl"
    transcript.write_bytes(b"ORIGINAL")
    original = pi._rename_noreplace
    replaced = []

    def race(source_fd, source, destination_fd, destination):
        if source == transcript.name and not replaced:
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"NEW_UNCAPTURED")
            os.replace(replacement, transcript)
            replaced.append(True)
        original(source_fd, source, destination_fd, destination)

    monkeypatch.setattr(pi, "_rename_noreplace", race)
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")
            try:
                pi._cleanup_broker_claude_transcript(transcript, {}, private_capture=attempt)
            finally:
                attempt.close(completed=False)
    assert transcript.read_bytes() == b"NEW_UNCAPTURED"
    assert next(private_root.glob("session-*/claude.jsonl")).read_bytes() == b"ORIGINAL"


@pytest.mark.parametrize("initial_source", ["present", "empty_parent", "missing_parent"])
def test_source_parent_change_after_open_cannot_verify_cleanup(
    tmp_path, private_root, monkeypatch, initial_source,
):
    project = tmp_path / "project"
    displaced = tmp_path / "displaced"
    transcript = project / "exact.jsonl"
    if initial_source != "missing_parent":
        project.mkdir(mode=0o700)
    if initial_source == "present":
        transcript.write_bytes(b"ORIGINAL")
    actual_open = pi._open_capture_directory
    changed = False

    def replace_parent(path):
        nonlocal changed
        try:
            return actual_open(path)
        finally:
            if path == project and not changed:
                changed = True
                if project.exists():
                    project.rename(displaced)
                project.mkdir(mode=0o700)
                transcript.write_bytes(b"NEW_UNCAPTURED")

    monkeypatch.setattr(pi, "_open_capture_directory", replace_parent)
    evidence = {}
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")
            try:
                pi._cleanup_broker_claude_transcript(transcript, evidence, private_capture=attempt)
            finally:
                attempt.close(completed=True)
    assert transcript.read_bytes() == b"NEW_UNCAPTURED"
    assert capture.receipts[0]["status"] == "failed"
    assert capture.receipts[0]["source"]["cleanup_verified"] is False
    assert evidence["claude_transcript_cleanup_verified"] is False
    if initial_source == "present":
        assert (displaced / transcript.name).read_bytes() == b"ORIGINAL"
        assert next(private_root.glob("session-*/claude.jsonl")).read_bytes() == b"ORIGINAL"


@pytest.mark.parametrize("restore_collision", [False, True])
def test_source_parent_change_after_move_preserves_source_and_honest_locator(
    tmp_path, private_root, monkeypatch, restore_collision,
):
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    displaced = tmp_path / "displaced"
    transcript = project / "exact.jsonl"
    transcript.write_bytes(b"ORIGINAL")
    actual_rename = pi._rename_noreplace
    changed = False

    def replace_parent(source_fd, source, destination_fd, destination):
        nonlocal changed
        actual_rename(source_fd, source, destination_fd, destination)
        if source == transcript.name and not changed:
            changed = True
            project.rename(displaced)
            project.mkdir(mode=0o700)
            transcript.write_bytes(b"NEW_UNCAPTURED")
            if restore_collision:
                (displaced / transcript.name).write_bytes(b"BLOCK_RESTORE")

    monkeypatch.setattr(pi, "_rename_noreplace", replace_parent)
    evidence = {}
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")
            try:
                pi._cleanup_broker_claude_transcript(transcript, evidence, private_capture=attempt)
            finally:
                attempt.close(completed=True)
    assert transcript.read_bytes() == b"NEW_UNCAPTURED"
    assert next(private_root.glob("session-*/claude.jsonl")).read_bytes() == b"ORIGINAL"
    if restore_collision:
        assert (displaced / transcript.name).read_bytes() == b"BLOCK_RESTORE"
        retained = next(displaced.glob(".phase-loop-retained-*/transcript.jsonl"))
        assert capture.receipts[0]["source_preservation"] == "quarantined"
    else:
        retained = displaced / transcript.name
    assert retained.read_bytes() == b"ORIGINAL"
    source = capture.receipts[0]["source"]
    assert source["cleanup_verified"] is False
    assert evidence["claude_transcript_cleanup_verified"] is False
    assert capture.receipts[0]["status"] == "failed"
    assert "quarantine_path" not in source
    locator = source["recovery_locator"]
    assert locator["status"] == "unresolved"
    assert "path" not in locator
    assert locator["directory_device"] == retained.parent.stat().st_dev
    assert locator["directory_inode"] == retained.parent.stat().st_ino
    assert locator["name"] == retained.name
    manifest = json.loads(next(private_root.glob("session-*/manifest.json")).read_bytes())
    assert manifest["source"]["recovery_locator"] == locator


def test_restore_collision_records_verified_quarantine_locator(
    tmp_path, private_root, monkeypatch,
):
    transcript = tmp_path / "exact.jsonl"
    transcript.write_bytes(b"ORIGINAL")
    actual_rename = pi._rename_noreplace

    def replace_and_block_restore(source_fd, source, destination_fd, destination):
        if source == transcript.name:
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"NEW_UNCAPTURED")
            os.replace(replacement, transcript)
        actual_rename(source_fd, source, destination_fd, destination)
        if source == transcript.name:
            transcript.write_bytes(b"BLOCK_RESTORE")

    monkeypatch.setattr(pi, "_rename_noreplace", replace_and_block_restore)
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")
            try:
                pi._cleanup_broker_claude_transcript(transcript, {}, private_capture=attempt)
            finally:
                attempt.close(completed=True)
    assert transcript.read_bytes() == b"BLOCK_RESTORE"
    source = capture.receipts[0]["source"]
    retained = Path(source["quarantine_path"])
    assert retained.read_bytes() == b"NEW_UNCAPTURED"
    assert source["recovery_locator"]["status"] == "verified"
    assert source["recovery_locator"]["path"] == str(retained)
    assert next(private_root.glob("session-*/claude.jsonl")).read_bytes() == b"ORIGINAL"


@pytest.mark.parametrize("last_operation", ["unlink", "rmdir"])
def test_source_parent_change_during_final_cleanup_cannot_report_success(
    tmp_path, private_root, monkeypatch, last_operation,
):
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    transcript = project / "exact.jsonl"
    transcript.write_bytes(b"ORIGINAL")
    actual = getattr(os, last_operation)
    changed = False

    def replace_parent(name, *args, **kwargs):
        nonlocal changed
        result = actual(name, *args, **kwargs)
        is_retirement = (name == "transcript.jsonl" if last_operation == "unlink"
                         else str(name).startswith(".phase-loop-retained-"))
        if is_retirement and kwargs.get("dir_fd") is not None and not changed:
            changed = True
            project.rename(tmp_path / "displaced")
            project.mkdir(mode=0o700)
            transcript.write_bytes(b"NEW_UNCAPTURED")
        return result

    monkeypatch.setattr(os, last_operation, replace_parent)
    evidence = {}
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")
            try:
                pi._cleanup_broker_claude_transcript(transcript, evidence, private_capture=attempt)
            finally:
                attempt.close(completed=True)
    assert changed
    assert transcript.read_bytes() == b"NEW_UNCAPTURED"
    assert next(private_root.glob("session-*/claude.jsonl")).read_bytes() == b"ORIGINAL"
    assert capture.receipts[0]["status"] == "failed"
    assert capture.receipts[0]["source"]["cleanup_verified"] is False
    assert evidence["claude_transcript_cleanup_verified"] is False


def test_parent_change_after_restoration_leaves_recovery_locator_unresolved(
    tmp_path, private_root, monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    displaced = tmp_path / "displaced"
    transcript = project / "exact.jsonl"
    transcript.write_bytes(b"ORIGINAL")
    actual_rename = pi._rename_noreplace
    actual_rmdir = os.rmdir

    def replace_before_move(source_fd, source, destination_fd, destination):
        if source == transcript.name:
            replacement = project / "replacement"
            replacement.write_bytes(b"NEW_UNCAPTURED")
            os.replace(replacement, transcript)
        actual_rename(source_fd, source, destination_fd, destination)

    def replace_after_restore(name, *args, **kwargs):
        result = actual_rmdir(name, *args, **kwargs)
        if str(name).startswith(".phase-loop-retained-"):
            project.rename(displaced)
            project.mkdir(mode=0o700)
            transcript.write_bytes(b"RECREATED_SOURCE")
        return result

    monkeypatch.setattr(pi, "_rename_noreplace", replace_before_move)
    monkeypatch.setattr(os, "rmdir", replace_after_restore)
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root) as capture:
            attempt = capture.begin("claude", "test")
            try:
                pi._cleanup_broker_claude_transcript(transcript, {}, private_capture=attempt)
            finally:
                attempt.close(completed=True)
    assert transcript.read_bytes() == b"RECREATED_SOURCE"
    assert (displaced / transcript.name).read_bytes() == b"NEW_UNCAPTURED"
    locator = capture.receipts[0]["source"]["recovery_locator"]
    assert locator["status"] == "unresolved"
    assert "path" not in locator
    assert locator["directory_inode"] == displaced.stat().st_ino


@pytest.fixture
def threaded_broker(monkeypatch, request):
    calls, kwargs = request.getfixturevalue("broker_control")
    original = pi.ParentUnixBroker

    class ThreadedBroker(original):
        def run_credentialless_client(self, adapter, **kw):
            with ThreadPoolExecutor(max_workers=1) as pool:
                try:
                    return pool.submit(super().run_credentialless_client, adapter, **kw).result()
                except Exception as exc:
                    raise ValueError("synthetic broker exception wrapper") from exc

    monkeypatch.setattr(pi, "ParentUnixBroker", ThreadedBroker)
    monkeypatch.setattr(pi, "_gc_stale_panel_scratch", lambda *a, **kw: None)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a: (True, ""))

    @contextmanager
    def no_credentials(env, evidence):
        yield {}
        evidence["provider_agy_home_cleanup_verified"] = True

    monkeypatch.setattr(pi, "_brokered_agy_environment", no_credentials)
    return calls, kwargs


def test_raw_gemini_error_survives_both_threads_and_public_streaming(
    monkeypatch, threaded_broker, private_root, tmp_path,
):
    calls, kwargs = threaded_broker
    raw = b'{"type":"result","status":"ERROR","response":"rejected"}\n\xff'
    real_run = pi._run_leg_with_liveness

    def offline(cmd, **run_kwargs):
        assert cmd[0] == "agy"
        calls.append("provider")
        script = f"import os,sys; sys.stdin.buffer.read(); os.write(1,{raw!r}); os.write(2,b'raw-stderr')"
        return real_run([sys.executable, "-c", script], **run_kwargs)

    monkeypatch.setattr(pi, "_run_leg_with_liveness", offline)
    with PrivateSessionCapture(private_root) as capture:
        panel = pi.invoke_panel(
            "artifact", ["gemini"],
            spawn=lambda leg, artifact: pi._default_spawn_via_provider(leg, artifact, **kwargs),
            stream_dir=tmp_path / "verdicts",
        )
        assert panel.legs[0].status == "ERROR" and not panel.legs[0].text
        saved = _attempt_path(private_root, capture)
        assert (saved / "stdout-1.bin").read_bytes() == raw
        assert (saved / "stderr-1.bin").read_bytes() == b"raw-stderr"
        assert b"artifact" in (saved / "input.txt").read_bytes()
        assert capture.receipts[0]["status"] == "saved"
        assert calls == ["provider", "closed"]
        manifest = json.loads((saved / "manifest.json").read_bytes())
        assert manifest["status"] == "saved"
        assert manifest["provider_outcome"]["status"] == "ERROR"
        assert manifest["provider_outcome"]["review_text_sha256"] == sha256(b"").hexdigest()


def test_retention_error_crosses_broker_provider_and_public_wrappers(
    monkeypatch, threaded_broker, private_root, tmp_path,
):
    calls, kwargs = threaded_broker
    monkeypatch.setattr(pi, "_exec_leg", lambda *a, **kw: pytest.fail("provider must not start"))
    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root, max_attempt_bytes=1, max_total_bytes=2048):
            pi.invoke_panel(
                "artifact", ["gemini"],
                spawn=lambda leg, artifact: pi._default_spawn_via_provider(leg, artifact, **kwargs),
                stream_dir=tmp_path / "verdicts",
            )
    assert calls == ["closed"]
    assert not list((tmp_path / "verdicts").glob("*.verdict.json"))


@pytest.mark.parametrize("quiescent", [False, True])
def test_unproven_quiescence_stays_primary_and_leaves_transcript(
    monkeypatch, threaded_broker, private_root, tmp_path, quiescent,
):
    _calls, kwargs = threaded_broker
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    monkeypatch.setattr(pi, "_claude_project_dir_for_cwd", lambda cwd: project)

    def unsafe(**params):
        Path(params["broker_transcript_path"]).write_bytes(b"KEEP_UNQUIESCENT")
        params["private_capture"].quiescent = quiescent
        params["private_capture"].fail("synthetic_capture_failure")
        raise pi.ProviderProcessGroupQuiescenceError("synthetic unproven process group")

    monkeypatch.setattr(pi, "_run_claude_tui_session", unsafe)
    with pytest.raises(pi.ProviderProcessGroupQuiescenceError):
        with PrivateSessionCapture(private_root) as capture:
            pi._default_spawn_via_provider("claude", "artifact", **kwargs)
    transcript = next(project.glob("*.jsonl"))
    assert transcript.read_bytes() == b"KEEP_UNQUIESCENT"
    assert capture.receipts[0]["source"] == {
        "path": str(transcript), "cleanup_verified": False,
    }


def test_absent_project_directory_is_missing_transcript_not_capture_failure(tmp_path, private_root):
    transcript = tmp_path / "uncreated-project" / "exact-session.jsonl"
    evidence = {}
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("claude", "test")
        assert pi._cleanup_broker_claude_transcript(transcript, evidence, private_capture=attempt)
        assert attempt.files["claude.jsonl"]["status"] == "missing"
        assert evidence["claude_transcript_existed"] is False
        assert evidence["claude_transcript_cleanup_verified"] is True
        attempt.close(completed=True)


@pytest.mark.parametrize("status,returncode,text,log", [
    ("OK", 0, "AGREE", ""), ("DEGRADED", 1, "", "claude_tui_stalled"),
])
def test_claude_adapter_retains_success_and_failure_before_cleanup(
    monkeypatch, threaded_broker, private_root, tmp_path, status, returncode, text, log,
):
    calls, kwargs = threaded_broker
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    monkeypatch.setattr(pi, "_claude_project_dir_for_cwd", lambda cwd: project)
    raw, terminal = b'{"type":"assistant","raw":"exact"}\n\xff', b"PTY:\xfe"

    def offline(**params):
        calls.append("provider")
        Path(params["broker_transcript_path"]).write_bytes(raw)
        params["private_capture"].save("pty-1.bin", terminal)
        return returncode, text, log, "synthetic terminal tail"

    monkeypatch.setattr(pi, "_run_claude_tui_session", offline)
    with PrivateSessionCapture(private_root) as capture:
        result = pi._default_spawn_via_provider("claude", "artifact", **kwargs)
        assert result[:2] == (status, text)
        saved = _attempt_path(private_root, capture)
        assert (saved / "claude.jsonl").read_bytes() == raw
        assert (saved / "pty-1.bin").read_bytes() == terminal
        manifest = json.loads((saved / "manifest.json").read_bytes())
        assert manifest["provider_outcome"]["status"] == status
        assert manifest["provider_outcome"]["review_text_sha256"] == sha256(text.encode()).hexdigest()
        assert manifest["status"] == "saved"
        assert calls == ["provider", "closed"]
    assert not list(project.iterdir())


def test_preflight_rejection_records_outcome_without_claiming_provider_output(
    monkeypatch, threaded_broker, private_root,
):
    _, kwargs = threaded_broker
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (False, "synthetic_unavailable"))
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **kw: pytest.fail("no process expected"))
    with PrivateSessionCapture(private_root) as capture:
        result = pi._default_spawn_via_provider("claude", "artifact", **kwargs)
        assert result[:2] == ("UNAVAILABLE", "")
        assert result[2] == "synthetic_unavailable"
        saved = _attempt_path(private_root, capture)
        manifest = json.loads((saved / "manifest.json").read_bytes())
        assert manifest["provider_outcome"]["status"] == "UNAVAILABLE"
        assert manifest["provider_outcome"]["detail"] == "synthetic_unavailable"
        assert set(manifest["files"]) == {"input.txt", "instructions.md", "bundle.md"}


def test_public_board_does_not_turn_retention_failure_into_a_verdict(private_root, tmp_path):
    board = Board(name="capture-control", purpose="general", seats=(
        Seat(model="gemini-3.8-flash", effort="high", harness="gemini"),
    ))

    def failed(*args, **kwargs):
        raise PrivateCaptureError("synthetic_capture_failure")

    with pytest.raises(PrivateCaptureError):
        with PrivateSessionCapture(private_root):
            invoke_sanctioned_board_control(
                board, "artifact", spawn=failed, stream_dir=tmp_path / "verdicts",
            )
    assert not list((tmp_path / "verdicts").glob("*.verdict.json"))


@pytest.mark.parametrize("streaming", [False, True])
def test_sibling_quiescence_error_wins_over_earlier_capture_error(monkeypatch, streaming):
    second_started, shutdown_started = threading.Event(), threading.Event()
    actual_shutdown = ThreadPoolExecutor.shutdown
    primary = pi.ProviderProcessGroupQuiescenceError("synthetic sibling process still unproven")

    def shutdown(pool, *args, **kwargs):
        shutdown_started.set()
        return actual_shutdown(pool, *args, **kwargs)

    def run_one(item):
        if item == 0:
            assert second_started.wait(2)
            raise PrivateCaptureError("synthetic_capture_failure")
        second_started.set()
        assert shutdown_started.wait(2)
        raise primary

    monkeypatch.setattr(ThreadPoolExecutor, "shutdown", shutdown)
    with pytest.raises(pi.ProviderProcessGroupQuiescenceError) as raised:
        pi._run_legs_ordered(
            [0, 1], run_one, max_concurrency=2,
            on_leg_complete=(lambda result: pytest.fail("no verdict")) if streaming else None,
        )
    assert raised.value is primary
