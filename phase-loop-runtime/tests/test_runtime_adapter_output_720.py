"""Exercise real bounded adapter streams and cleanup (agent-harness#720)."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from phase_loop_runtime.convergence.adapters import base
from phase_loop_runtime.convergence.contracts import AdmissionRequest


_LIMIT = 65536


def _identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return None
    return fields[0], fields[19]


def _alive(pid, start):
    observed = _identity(pid)
    return observed is not None and observed[1] == start and observed[0] != "Z"


def _kill_owned(pid, start):
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        if _alive(pid, start):
            signal.pidfd_send_signal(fd, signal.SIGKILL)
    finally:
        os.close(fd)


@pytest.fixture
def observed(tmp_path, monkeypatch):
    data = {"processes": [], "streams": {}, "reads": [], "kills": [], "waits": [], "fail_wait": False}
    real_popen, real_read, real_killpg = subprocess.Popen, os.read, os.killpg
    data["spawn_unobserved"] = real_popen

    def spawn(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        identity = _identity(process.pid)
        assert identity is not None
        data["processes"].append((process, identity[1]))
        data["streams"].update({process.stdout.fileno(): "stdout", process.stderr.fileno(): "stderr"})
        if data["fail_wait"]:
            real_wait = process.wait

            def refuse_reap(timeout=None):
                data["waits"].append(timeout)
                # Actually reap a signaled fixture before reporting the injected
                # failure, so even this negative control leaves no live leader.
                if data["kills"]:
                    real_wait(timeout=1)
                raise subprocess.TimeoutExpired(process.args, timeout or 0)

            process.wait = refuse_reap
        return process

    def read(fd, size):
        chunk = real_read(fd, size)
        if fd in data["streams"]:
            data["reads"].append((data["streams"][fd], size, len(chunk)))
        return chunk

    def killpg(pgid, signum):
        data["kills"].append((pgid, signum))
        return real_killpg(pgid, signum)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(os, "read", read)
    monkeypatch.setattr(os, "killpg", killpg)
    data["read"] = read
    try:
        yield data
    finally:
        marker = tmp_path / "owned-child.json"
        if marker.exists():
            child = json.loads(marker.read_text())
            _kill_owned(child["pid"], child["start"])
        for process, start in data["processes"]:
            _kill_owned(process.pid, start)
            # Call the original method, bypassing any deliberate wait failure.
            real_popen.wait(process, timeout=2)


def _request(tmp_path, body, timeout=2):
    script = tmp_path / "codex"
    script.write_text(f"#!{sys.executable}\nimport os, time, json, threading\nfrom pathlib import Path\n" + body + "\n")
    script.chmod(0o755)
    return base.AdapterExecutionRequest(
        attempt_id="attempt",
        admission=AdmissionRequest("attempt", 1, "fence", "approval", "head==base", "repo", "key"),
        argv=(str(script),), cwd=tmp_path, timeout_seconds=timeout, allowed_action="execute",
    )


def _output_body(stdout, stderr=b"", linger=False):
    return f'''
def emit(fd, raw):
    while raw:
        raw = raw[os.write(fd, raw):]
threads = [threading.Thread(target=emit, args=(1, {stdout!r})),
           threading.Thread(target=emit, args=(2, {stderr!r}))]
for thread in threads: thread.start()
for thread in threads: thread.join()
{'time.sleep(5)' if linger else ''}
'''


def _payload(size, multibyte=False):
    prefix, suffix = b'{"status":"completed","padding":"', b'"}'
    room = size - len(prefix) - len(suffix)
    fill = b"\xc3\xa9" * (room // 2) + b" " * (room % 2) if multibyte else b"x" * room
    value = prefix + fill + suffix
    assert len(value) == size
    return value


def _assert_quiescent(tmp_path, observed):
    assert observed["processes"], "a real adapter subprocess must have entered"
    assert {pgid for pgid, _signum in observed["kills"]} <= {
        process.pid for process, _start in observed["processes"]
    }, "only the adapter's owned process groups may be signaled"
    for process, start in observed["processes"]:
        assert not _alive(process.pid, start), "adapter returned with its leader alive"
    marker = tmp_path / "owned-child.json"
    if marker.exists():
        child = json.loads(marker.read_text())
        deadline = time.monotonic() + 1
        while _alive(child["pid"], child["start"]) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not _alive(child["pid"], child["start"]), "adapter left its same-group descendant alive"


def _assert_bounded_reads(observed):
    assert observed["reads"], "the real output read path must be observed"
    for stream in ("stdout", "stderr"):
        total = 0
        for name, requested, received in observed["reads"]:
            if name != stream:
                continue
            assert 0 < requested <= _LIMIT + 1 - total, (stream, requested, total)
            total += received
        assert total <= _LIMIT + 1, (stream, total)


@pytest.mark.parametrize("stream", ["stdout", "stderr", "both"])
def test_overflow_is_blocked_before_unbounded_capture(tmp_path, observed, stream):
    success = b'{"status":"completed"}'
    large = success + b" " * (4 * _LIMIT - len(success))
    stdout = large if stream in ("stdout", "both") else success
    stderr = b"E" * (4 * _LIMIT) if stream in ("stderr", "both") else b""
    request = _request(tmp_path, _output_body(stdout, stderr))
    result = base.run_bounded(request, provider="codex")
    assert result.status.value == "blocked"
    assert result.attempt_id == request.attempt_id
    _assert_bounded_reads(observed)
    _assert_quiescent(tmp_path, observed)


@pytest.mark.parametrize("extra", [0, 1])
@pytest.mark.parametrize("multibyte", [False, True])
def test_limit_counts_bytes_and_rejects_valid_oversized_json(tmp_path, observed, extra, multibyte):
    request = _request(tmp_path, _output_body(_payload(_LIMIT + extra, multibyte)))
    result = base.run_bounded(request, provider="codex")
    assert result.status.value == ("blocked" if extra else "completed")
    _assert_bounded_reads(observed)
    _assert_quiescent(tmp_path, observed)


def test_stderr_at_exact_budget_still_allows_success(tmp_path, observed):
    request = _request(tmp_path, _output_body(b'{"status":"completed"}', b"E" * _LIMIT))
    result = base.run_bounded(request, provider="codex")
    assert result.status.value == "completed"
    _assert_bounded_reads(observed)
    _assert_quiescent(tmp_path, observed)


@pytest.mark.parametrize("raw", [b"not-json", b"\xff", b'{"status":"unknown"}', b"[]"])
def test_malformed_bounded_output_is_metadata_only(tmp_path, observed, raw):
    request = _request(tmp_path, _output_body(raw))
    result = base.run_bounded(request, provider="codex")
    assert result.status.value == "blocked"
    assert result.attempt_id == request.attempt_id
    assert result.detail and raw.decode(errors="replace") not in result.detail
    _assert_bounded_reads(observed)
    _assert_quiescent(tmp_path, observed)


def _fork_body(exit_code, *, leader_lingers=False):
    return f'''
child = os.fork()
if child == 0:
    time.sleep(5)
    os._exit(0)
fields = Path(f"/proc/{{child}}/stat").read_text().rsplit(")", 1)[1].split()
Path("owned-child.json").write_text(json.dumps({{"pid": child, "start": fields[19]}}))
os.write(1, b'{{"status":"completed"}}')
{'time.sleep(5)' if leader_lingers else ''}
os._exit({exit_code})
'''


@pytest.mark.parametrize("descendant", [False, True])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_original_leader_status_survives_descendant_held_pipes(tmp_path, observed, descendant, exit_code):
    body = _fork_body(exit_code) if descendant else f"os.write(1, b'{{\"status\":\"completed\"}}')\nos._exit({exit_code})"
    request = _request(tmp_path, body, timeout=2)
    started = time.monotonic()
    result = base.run_bounded(request, provider="codex")
    elapsed = time.monotonic() - started
    assert result.status.value == ("failed" if exit_code else "completed")
    assert elapsed < 1.5, "leader exit must not wait for descendant-held EOF or the request deadline"
    if descendant:
        assert observed["kills"], "remaining owned group must be reclaimed"
    _assert_bounded_reads(observed)
    _assert_quiescent(tmp_path, observed)


def test_timeout_reclaims_real_leader_and_descendant(tmp_path, observed):
    request = _request(tmp_path, _fork_body(0, leader_lingers=True), timeout=0.3)
    started = time.monotonic()
    result = base.run_bounded(request, provider="codex")
    assert result.status.value == "degraded"
    assert time.monotonic() - started < 2
    assert observed["kills"]
    _assert_quiescent(tmp_path, observed)


def test_cleanup_leaves_an_unrelated_process_running(tmp_path, observed):
    unrelated = observed["spawn_unobserved"](
        [sys.executable, "-c", "import time; time.sleep(5)"],
        start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        request = _request(tmp_path, _fork_body(0, leader_lingers=True), timeout=0.3)
        result = base.run_bounded(request, provider="codex")
        assert result.status.value == "degraded"
        assert unrelated.poll() is None, "adapter cleanup must preserve unrelated processes"
        _assert_quiescent(tmp_path, observed)
    finally:
        unrelated.kill()
        unrelated.wait(timeout=2)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, OSError])
@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_read_exception_survives_group_cleanup_even_if_wait_fails(tmp_path, observed, monkeypatch, error_type, cleanup_failure):
    observed["fail_wait"] = cleanup_failure
    failure = error_type("injected adapter read failure")
    entered = []

    def fail_read(fd, size):
        if fd in observed["streams"] and not entered:
            entered.append(True)
            raise failure
        return observed["read"](fd, size)

    monkeypatch.setattr(os, "read", fail_read)
    request = _request(tmp_path, _fork_body(0, leader_lingers=True))
    with pytest.raises(error_type) as caught:
        base.run_bounded(request, provider="codex")
    assert caught.value is failure
    assert entered
    assert observed["kills"]
    if cleanup_failure:
        assert observed["waits"] and all(t is not None and 0 < t <= 1 for t in observed["waits"])
    _assert_quiescent(tmp_path, observed)


def test_cleanup_failure_overrides_observed_overflow(tmp_path, observed):
    observed["fail_wait"] = True
    request = _request(tmp_path, _output_body(_payload(_LIMIT + 1), linger=True), timeout=0.4)
    started = time.monotonic()
    result = base.run_bounded(request, provider="codex")
    assert result.status.value == "degraded"
    assert result.detail and "cleanup" in result.detail.lower()
    assert time.monotonic() - started < 2
    assert observed["waits"] and all(t is not None and 0 < t <= 1 for t in observed["waits"])
    assert any(n == "stdout" for n, _requested, _received in observed["reads"])
    assert sum(received for name, _requested, received in observed["reads"] if name == "stdout") == _LIMIT + 1
    _assert_bounded_reads(observed)
    _assert_quiescent(tmp_path, observed)
