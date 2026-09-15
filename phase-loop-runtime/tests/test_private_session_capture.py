"""Provider-free contracts for explicitly scoped private session retention."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

import pytest

from phase_loop_runtime import private_session_capture as capture_module
from phase_loop_runtime.private_session_capture import (
    PrivateCaptureError,
    PrivateSessionCapture,
    current_private_capture,
)


@pytest.fixture
def private_root(tmp_path):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    return root


@contextmanager
def failed_capture(root, **limits):
    with pytest.raises(PrivateCaptureError, match="private_session_retention_incomplete"):
        with PrivateSessionCapture(root, **limits) as capture:
            yield capture


def manifest_for(capture, attempt):
    return json.loads((capture.root / attempt.name / "manifest.json").read_bytes())


def capture_fds(root):
    descriptors = set()
    for entry in Path("/proc/self/fd").iterdir():
        try:
            target = os.readlink(entry)
        except FileNotFoundError:
            continue
        if target == str(root) or target.startswith(str(root) + "/"):
            descriptors.add(int(entry.name))
    return descriptors


@pytest.mark.parametrize("provider", ["claude", "gemini"])
def test_saved_capture_has_exact_bytes_hashes_and_private_permissions(private_root, provider):
    payloads = {
        "bundle.md": b"# Synthetic review bundle\n",
        "instructions.md": b"Synthetic instructions\n",
        "input.txt": b"\x00\xffBearer PLANTED_PRIVATE_DATA\n",
        "stdin-1.bin": b"input\r\n\x1b[0m",
        "stderr-1.bin": b"\xff\x00diagnostic\r\n",
        "pty-1.bin": b"\x1b[2Jsynthetic terminal\r\n",
        "stdout-1.bin": bytes(range(256)) * 3,
    }
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin(provider, "synthetic-model")
        for name, payload in payloads.items():
            if name == "stdout-1.bin":
                attempt.open_stream(name)
                attempt.append(name, payload[:127])
                attempt.append(name, payload[127:])
                attempt.finish_stream(name)
            else:
                attempt.save(name, payload)
        attempt.close(completed=True)
        attempt.close(completed=True)
        directory = private_root / attempt.name
        manifest_bytes = (directory / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        assert manifest["schema"] == "private_provider_session.v1"
        assert manifest["provider"] == provider
        assert manifest["model"] == "synthetic-model"
        assert manifest["session"] == attempt.name
        assert manifest["status"] == "saved"
        assert manifest["reason"] is None
        assert manifest["quiescent"] is True
        assert set(manifest["files"]) == set(payloads)
        assert capture.receipts == [{
            "session": attempt.name,
            "status": "saved",
            "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        }]
        for name, payload in payloads.items():
            assert (directory / name).read_bytes() == payload
            assert manifest["files"][name] == {
                "status": "saved", "bytes": len(payload), "sha256": sha256(payload).hexdigest(),
            }
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(private_root.stat().st_mode) == 0o700
        for path in directory.iterdir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert path.stat().st_nlink == 1
            assert not path.name.endswith(".partial")


def test_transcript_copies_only_exact_requested_source(private_root, tmp_path):
    source = tmp_path / "new-session.jsonl"
    payload = b'{"message":"PLANTED PRIVATE SESSION"}\n\x00\xff'
    source.write_bytes(payload)
    adjacent = tmp_path / "other-session.jsonl"
    adjacent.write_bytes(b"SYNTHETIC ADJACENT SESSION MUST NOT BE COPIED")
    before = source.stat()
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        identity = attempt.copy_transcript(source, required=True)
        attempt.close(completed=True)
        directory = private_root / attempt.name
        assert identity[:2] == (before.st_dev, before.st_ino)
        assert (directory / "claude.jsonl").read_bytes() == payload
        assert manifest_for(capture, attempt)["files"]["claude.jsonl"] == {
            "status": "saved", "bytes": len(payload), "sha256": sha256(payload).hexdigest(),
        }
        assert {path.name for path in directory.iterdir()} == {"claude.jsonl", "manifest.json"}
    assert source.read_bytes() == payload
    assert adjacent.read_bytes() == b"SYNTHETIC ADJACENT SESSION MUST NOT BE COPIED"


def test_attempt_limit_never_publishes_a_partial_stream(private_root):
    with failed_capture(private_root, max_attempt_bytes=1024, max_total_bytes=4096) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        attempt.open_stream("stdout-1.bin")
        attempt.append("stdout-1.bin", b"prefix")
        attempt.append("stdout-1.bin", b"x" * 1024)
        with pytest.raises(PrivateCaptureError):
            attempt.check()
        attempt.close(completed=True)
        directory = private_root / attempt.name
        assert not (directory / "stdout-1.bin").exists()
        assert attempt.files["stdout-1.bin"]["status"] == "partial"
        assert attempt.files["stdout-1.bin"]["bytes"] == len(b"prefix")
        assert capture.receipts[0]["status"] == "failed"
        assert manifest_for(capture, attempt)["status"] == "failed"


def test_total_limit_applies_across_separate_attempts(private_root):
    with failed_capture(private_root, max_attempt_bytes=2048, max_total_bytes=3072) as capture:
        first = capture.begin("claude", "synthetic-model")
        first.save("input.txt", b"a" * 1200)
        first.close(completed=True)
        assert first.receipt["status"] == "saved"
        second = capture.begin("gemini", "synthetic-model")
        second.open_stream("stdout-1.bin")
        second.append("stdout-1.bin", b"b" * 1200)
        second.check()
        second.append("stdout-1.bin", b"c" * 800)
        with pytest.raises(PrivateCaptureError):
            second.check()
        second.close(completed=True)
        assert second.receipt["status"] == "failed"
        assert not (private_root / second.name / "stdout-1.bin").exists()
        assert first.receipt["status"] == "saved"
        assert sum(path.stat().st_size for path in private_root.rglob("*") if path.is_file()) <= 3072


def test_manifest_must_fit_within_capture_budget(private_root):
    with failed_capture(private_root, max_attempt_bytes=8, max_total_bytes=8) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        attempt.save("input.txt", b"12345678")
        attempt.close(completed=True)
        assert attempt.receipt["status"] == "failed"
        assert "manifest_sha256" not in attempt.receipt
        assert sum(path.stat().st_size for path in private_root.rglob("*") if path.is_file()) <= 8


@pytest.mark.parametrize("ancestor", [False, True])
def test_symlinked_roots_and_ancestors_are_rejected(private_root, tmp_path, ancestor):
    alias = tmp_path / "alias"
    alias.symlink_to(private_root, target_is_directory=True)
    root = alias
    if ancestor:
        (private_root / "child").mkdir(mode=0o700)
        root = alias / "child"
    with pytest.raises(PrivateCaptureError):
        PrivateSessionCapture(root)
    assert not list(private_root.rglob("session-*"))


@pytest.mark.parametrize("kind", ["missing", "public", "relative", "parent-component"])
def test_root_must_exist_be_private_and_canonical(private_root, tmp_path, monkeypatch, kind):
    root = private_root
    if kind == "missing":
        root = private_root / "missing"
    elif kind == "public":
        root.chmod(0o755)
    elif kind == "relative":
        monkeypatch.chdir(tmp_path)
        root = Path("private")
    else:
        root = private_root / ".." / "private"
    with pytest.raises(PrivateCaptureError):
        PrivateSessionCapture(root)


@pytest.mark.parametrize("target", ["root", "session"])
def test_replaced_capture_directories_cannot_receive_saved_artifacts(private_root, target):
    with failed_capture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        directory = private_root if target == "root" else private_root / attempt.name
        displaced = directory.with_name(directory.name + "-displaced")
        directory.rename(displaced)
        directory.mkdir(mode=0o700)
        with pytest.raises(PrivateCaptureError):
            attempt.save("input.txt", b"synthetic input")
        attempt.close(completed=True)
        assert attempt.receipt["status"] == "failed"
        assert not list(directory.iterdir())


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_unsafe_transcript_sources_are_rejected(private_root, tmp_path, kind):
    source = tmp_path / "new-session.jsonl"
    original = tmp_path / "original"
    original.write_bytes(b"PLANTED PRIVATE SOURCE")
    if kind == "symlink":
        source.symlink_to(original)
    elif kind == "hardlink":
        os.link(original, source)
    else:
        os.mkfifo(source, 0o600)
    with failed_capture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        with pytest.raises(PrivateCaptureError):
            attempt.copy_transcript(source, required=False)
        attempt.close(completed=True)
        assert attempt.receipt["status"] == "failed"
        assert not (private_root / attempt.name / "claude.jsonl").exists()
    assert original.read_bytes() == b"PLANTED PRIVATE SOURCE"


def test_optional_missing_transcript_is_recorded_without_failing(private_root, tmp_path):
    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        assert attempt.copy_transcript(tmp_path / "missing.jsonl", required=False) is None
        attempt.close(completed=True)
        assert manifest_for(capture, attempt)["files"]["claude.jsonl"] == {
            "status": "missing", "bytes": 0,
        }
        assert attempt.receipt["status"] == "saved"


def test_required_missing_transcript_fails_the_receipt(private_root, tmp_path):
    with failed_capture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        with pytest.raises(PrivateCaptureError, match="capture_required_transcript_missing"):
            attempt.copy_transcript(tmp_path / "missing.jsonl", required=True)
        attempt.close(completed=True)
        assert attempt.receipt["status"] == "failed"
        assert manifest_for(capture, attempt)["files"]["claude.jsonl"]["status"] == "missing"


@pytest.mark.parametrize("mutation", ["grow", "rewrite", "truncate", "replace", "unlink"])
def test_source_changes_during_copy_are_not_saved(private_root, tmp_path, monkeypatch, mutation):
    source = tmp_path / "new-session.jsonl"
    source.write_bytes(b"a" * 65540)
    before = source.stat()
    real_read = os.read
    changed = False

    def change_during_read(fd, count):
        nonlocal changed
        chunk = real_read(fd, count)
        info = os.fstat(fd)
        if not changed and (info.st_dev, info.st_ino) == (before.st_dev, before.st_ino):
            changed = True
            if mutation == "grow":
                with source.open("ab") as handle:
                    handle.write(b"appended")
            elif mutation == "rewrite":
                source.write_bytes(b"b" * before.st_size)
                os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            elif mutation == "truncate":
                source.write_bytes(b"")
            elif mutation == "replace":
                source.rename(tmp_path / "moved.jsonl")
                source.write_bytes(b"b" * before.st_size)
            else:
                source.unlink()
        return chunk

    with failed_capture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        monkeypatch.setattr(capture_module.os, "read", change_during_read)
        with pytest.raises(PrivateCaptureError):
            attempt.copy_transcript(source, required=False)
        attempt.close(completed=True)
        assert changed
        assert attempt.receipt["status"] == "failed"
        assert attempt.files["claude.jsonl"]["status"] != "saved"
        assert attempt.files["claude.jsonl"]["status"] != "missing"
        assert not (private_root / attempt.name / "claude.jsonl").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "existing"])
def test_partial_file_redirects_cannot_overwrite_existing_files(private_root, tmp_path, kind):
    outside = tmp_path / "outside"
    outside.write_bytes(b"PRESERVE SYNTHETIC OUTSIDE DATA")
    with failed_capture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        partial = private_root / attempt.name / "stdout-1.bin.partial"
        if kind == "symlink":
            partial.symlink_to(outside)
        elif kind == "hardlink":
            os.link(outside, partial)
        elif kind == "fifo":
            os.mkfifo(partial, 0o600)
        else:
            partial.write_bytes(b"PRESERVE EXISTING PARTIAL")
        with pytest.raises(PrivateCaptureError):
            attempt.open_stream("stdout-1.bin")
        attempt.close(completed=True)
        assert attempt.receipt["status"] == "failed"
        assert not (private_root / attempt.name / "stdout-1.bin").exists()
    assert outside.read_bytes() == b"PRESERVE SYNTHETIC OUTSIDE DATA"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "mode", "content"])
def test_partial_file_tampering_is_detected_before_publication(private_root, tmp_path, kind):
    outside = tmp_path / "outside"
    outside.write_bytes(b"synthetic original")
    with failed_capture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        attempt.open_stream("stdout-1.bin")
        attempt.append("stdout-1.bin", b"synthetic original")
        partial = private_root / attempt.name / "stdout-1.bin.partial"
        if kind in {"symlink", "fifo"}:
            partial.rename(partial.with_name("displaced"))
            if kind == "symlink":
                partial.symlink_to(outside)
            else:
                os.mkfifo(partial, 0o600)
        elif kind == "hardlink":
            os.link(partial, partial.with_name("extra-link"))
        elif kind == "mode":
            partial.chmod(0o644)
        else:
            partial.write_bytes(b"synthetic tampered")
        attempt.finish_stream("stdout-1.bin")
        attempt.close(completed=True)
        assert attempt.receipt["status"] == "failed"
        assert attempt.files["stdout-1.bin"]["status"] != "saved"
        assert not (private_root / attempt.name / "stdout-1.bin").exists()
    assert outside.read_bytes() == b"synthetic original"


@pytest.mark.parametrize("target", ["stdout-1.bin", "manifest.json"])
def test_publication_never_overwrites_existing_destination(private_root, target):
    with failed_capture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        destination = private_root / attempt.name / target
        destination.write_bytes(b"IMMUTABLE EARLIER DATA")
        destination.chmod(0o600)
        if target != "manifest.json":
            with pytest.raises(PrivateCaptureError):
                attempt.save(target, b"new data")
        attempt.close(completed=True)
        assert attempt.receipt["status"] == "failed"
        assert destination.read_bytes() == b"IMMUTABLE EARLIER DATA"


@pytest.mark.parametrize("target", ["stdout-1.bin", "manifest.json"])
@pytest.mark.parametrize("swap", ["source", "destination"])
def test_publication_detects_swaps_inside_link(private_root, monkeypatch, target, swap):
    real_link = os.link
    swapped = False
    with failed_capture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        directory = private_root / attempt.name

        def swap_during_link(source, destination, **kwargs):
            nonlocal swapped
            matches = str(destination) == target and not swapped
            if matches and swap == "source":
                path = directory / source
                body = path.read_bytes()
                path.rename(path.with_name(path.name + ".displaced"))
                path.write_bytes(body)
                path.chmod(0o600)
                swapped = True
            result = real_link(source, destination, **kwargs)
            if matches and swap == "destination":
                path = directory / destination
                body = path.read_bytes()
                path.rename(path.with_name(path.name + ".displaced"))
                path.write_bytes(body)
                path.chmod(0o600)
                swapped = True
            return result

        monkeypatch.setattr(capture_module.os, "link", swap_during_link)
        if target != "manifest.json":
            with pytest.raises(PrivateCaptureError):
                attempt.save(target, b"synthetic output")
        attempt.close(completed=True)
        assert swapped
        assert attempt.receipt["status"] == "failed"
        if target != "manifest.json":
            assert attempt.files[target]["status"] != "saved"
        else:
            assert "manifest_sha256" not in attempt.receipt


def test_positive_short_writes_preserve_all_bytes(private_root, monkeypatch):
    real_write = os.write
    writes = []

    def short_write(fd, data):
        count = real_write(fd, data[:3])
        writes.append(count)
        return count

    with PrivateSessionCapture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        monkeypatch.setattr(capture_module.os, "write", short_write)
        attempt.save("stdout-1.bin", b"synthetic bytes\x00\xff")
        attempt.close(completed=True)
        assert len(writes) > 1
        assert (private_root / attempt.name / "stdout-1.bin").read_bytes() == b"synthetic bytes\x00\xff"
        assert attempt.receipt["status"] == "saved"
        manifest_bytes = (private_root / attempt.name / "manifest.json").read_bytes()
        assert attempt.receipt["manifest_sha256"] == sha256(manifest_bytes).hexdigest()


@pytest.mark.parametrize("fault", ["zero", "disk-full", "prefix-then-disk-full"])
def test_write_failure_retains_failure_and_actual_partial_count(private_root, monkeypatch, fault):
    real_write = os.write
    writes = 0

    def fail_write(fd, data):
        nonlocal writes
        writes += 1
        if fault == "zero":
            return 0
        if fault == "prefix-then-disk-full" and writes == 1:
            return real_write(fd, data[:3])
        raise OSError(errno.ENOSPC, "PLANTED PRIVATE ERROR")

    with failed_capture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        attempt.open_stream("stdout-1.bin")
        with monkeypatch.context() as faults:
            faults.setattr(capture_module.os, "write", fail_write)
            attempt.append("stdout-1.bin", b"synthetic bytes")
        with pytest.raises(PrivateCaptureError) as error:
            attempt.check()
        attempt.close(completed=True)
        assert "PLANTED PRIVATE ERROR" not in str(error.value)
        assert "PLANTED PRIVATE ERROR" not in json.dumps(attempt.receipt)
        assert attempt.files["stdout-1.bin"]["bytes"] == (3 if fault == "prefix-then-disk-full" else 0)
        assert attempt.files["stdout-1.bin"]["status"] == "partial"
        assert not (private_root / attempt.name / "stdout-1.bin").exists()


@pytest.mark.parametrize("target", ["artifact", "manifest"])
@pytest.mark.parametrize("fault", ["open", "file-fsync", "directory-fsync"])
def test_storage_faults_cannot_create_saved_receipts(private_root, monkeypatch, target, fault):
    real_open, real_fsync = os.open, os.fsync
    injected = False
    with failed_capture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        directory_identity = (private_root / attempt.name).stat().st_ino
        filename = "stdout-1.bin" if target == "artifact" else "manifest.json"

        def fail_open(path, flags, *args, **kwargs):
            nonlocal injected
            if str(path) == filename + ".partial" and flags & os.O_CREAT:
                injected = True
                raise OSError(errno.ENOSPC, "PLANTED PRIVATE ERROR")
            return real_open(path, flags, *args, **kwargs)

        def fail_fsync(fd):
            nonlocal injected
            info = os.fstat(fd)
            if ((fault == "file-fsync" and stat.S_ISREG(info.st_mode))
                    or (fault == "directory-fsync" and info.st_ino == directory_identity)):
                injected = True
                raise OSError(errno.EIO, "PLANTED PRIVATE ERROR")
            return real_fsync(fd)

        with monkeypatch.context() as faults:
            if fault == "open":
                faults.setattr(capture_module.os, "open", fail_open)
            else:
                faults.setattr(capture_module.os, "fsync", fail_fsync)
            if target == "artifact":
                with pytest.raises(PrivateCaptureError):
                    attempt.save(filename, b"synthetic output")
            else:
                attempt.close(completed=True)
        attempt.close(completed=True)
        assert injected
        assert attempt.receipt["status"] == "failed"
        assert "PLANTED PRIVATE ERROR" not in json.dumps(attempt.receipt)
        if target == "artifact":
            assert attempt.files.get(filename, {}).get("status") != "saved"
        else:
            assert "manifest_sha256" not in attempt.receipt


@pytest.mark.parametrize("completed,quiescent", [(False, True), (True, False)])
def test_incomplete_attempt_cannot_be_saved(private_root, completed, quiescent):
    with failed_capture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        attempt.open_stream("stdout-1.bin")
        attempt.append("stdout-1.bin", b"unfinished")
        attempt.quiescent = quiescent
        attempt.close(completed=completed)
        assert attempt.receipt["status"] == "failed"
        assert attempt.receipt["reason"] == "capture_attempt_incomplete"
        assert not (private_root / attempt.name / "stdout-1.bin").exists()


def test_first_failure_is_preserved_in_receipt_and_manifest(private_root):
    with failed_capture(private_root) as capture:
        attempt = capture.begin("claude", "synthetic-model")
        attempt.fail("synthetic_first_failure")
        attempt.fail("synthetic_later_failure")
        with pytest.raises(PrivateCaptureError, match="synthetic_first_failure"):
            attempt.check()
        attempt.close(completed=False)
        assert attempt.receipt["reason"] == "synthetic_first_failure"
        assert manifest_for(capture, attempt)["reason"] == "synthetic_first_failure"


def test_nested_different_scopes_restore_context_on_exception(private_root, tmp_path):
    other_root = tmp_path / "other-private"
    other_root.mkdir(mode=0o700)
    assert current_private_capture() is None
    with PrivateSessionCapture(private_root) as outer:
        assert current_private_capture() is outer
        with pytest.raises(ValueError, match="synthetic body failure"):
            with PrivateSessionCapture(other_root) as inner:
                assert current_private_capture() is inner
                assert outer.run(current_private_capture) is outer
                assert current_private_capture() is inner
                raise ValueError("synthetic body failure")
        assert current_private_capture() is outer
    assert current_private_capture() is None


def test_capture_requires_explicit_thread_propagation_and_restores_worker_context(private_root):
    with PrivateSessionCapture(private_root) as capture:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(current_private_capture).result() is None
            assert pool.submit(capture.run, current_private_capture).result() is capture
            assert pool.submit(current_private_capture).result() is None

            def failed_callback():
                assert current_private_capture() is capture
                raise ValueError("synthetic worker failure")

            with pytest.raises(ValueError, match="synthetic worker failure"):
                pool.submit(capture.run, failed_callback).result()
            assert pool.submit(current_private_capture).result() is None
        assert current_private_capture() is capture
    assert current_private_capture() is None


@pytest.mark.parametrize("operation", ["begin", "run", "enter"])
def test_closed_capture_scope_cannot_be_reused(private_root, operation):
    with PrivateSessionCapture(private_root) as capture:
        pass
    with pytest.raises(PrivateCaptureError):
        if operation == "begin":
            capture.begin("claude", "synthetic-model")
        elif operation == "run":
            capture.run(current_private_capture)
        else:
            capture.__enter__()
    assert current_private_capture() is None


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="requires Linux descriptor inspection")
def test_attempt_allocation_failure_closes_all_directory_descriptors(private_root, monkeypatch):
    def fail_fsync(fd):
        raise OSError(errno.EIO, "synthetic allocation failure")

    try:
        with pytest.raises(PrivateCaptureError):
            with PrivateSessionCapture(private_root) as capture:
                monkeypatch.setattr(capture_module.os, "fsync", fail_fsync)
                capture.begin("claude", "synthetic-model")
        leaked = capture_fds(private_root)
    finally:
        for fd in capture_fds(private_root):
            os.close(fd)
    assert not leaked


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="requires Linux descriptor inspection")
@pytest.mark.parametrize("remove_partial", [False, True])
def test_duplicate_stream_open_does_not_leak_or_replace_original_descriptor(
    private_root, monkeypatch, remove_partial,
):
    try:
        with failed_capture(private_root) as capture:
            attempt = capture.begin("gemini", "synthetic-model")
            attempt.open_stream("stdout-1.bin")
            attempt.append("stdout-1.bin", b"original bytes")
            partial = private_root / attempt.name / "stdout-1.bin.partial"
            if remove_partial:
                partial.unlink()
            rejected = False
            try:
                attempt.open_stream("stdout-1.bin")
            except PrivateCaptureError:
                rejected = True
            finally:
                attempt.close(completed=True)
            assert rejected
            assert attempt.receipt["status"] == "failed"
        leaked = capture_fds(private_root)
    finally:
        for fd in capture_fds(private_root):
            os.close(fd)
    assert not leaked


def test_published_stream_name_is_single_use(private_root):
    with failed_capture(private_root) as capture:
        attempt = capture.begin("gemini", "synthetic-model")
        attempt.save("stdout-1.bin", b"immutable original")
        with pytest.raises(PrivateCaptureError):
            attempt.open_stream("stdout-1.bin")
        attempt.close(completed=True)
        assert (private_root / attempt.name / "stdout-1.bin").read_bytes() == b"immutable original"
