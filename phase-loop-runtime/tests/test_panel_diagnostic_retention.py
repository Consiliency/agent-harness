"""Diagnostic delivery regressions for agent-harness#369 and agent-harness#525."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import os
import stat
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi


@pytest.fixture
def broker_control(monkeypatch, tmp_path):
    """Exercise the parent/provider chain without auth, namespace or provider effects."""
    calls = []

    class Broker:
        def __init__(self, *args, **kwargs):
            self.evidence = {"stage_bundle_sha256": sha256(b"artifact").hexdigest()}

        def run_credentialless_client(self, adapter, **kwargs):
            result = adapter.invoke()
            assert len(result) == 2, "the frozen broker wire must remain a pair"
            return {"schema": "parent_unix_broker_v1", "status": result[0], "text": result[1]}, self.evidence

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(pi, "ParentUnixBroker", Broker)
    monkeypatch.setattr(pi, "_has_injected_review_execution_seam", lambda **kw: False)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda value: tmp_path)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **kw: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization", lambda *a, **kw: object())
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda env=None: (True, ""))
    return calls, dict(review_authorization=object(), canonical_repo_authority=tmp_path, env={})


def test_brokered_gemini_reason_survives_provider_pair(monkeypatch, broker_control):
    calls, kwargs = broker_control

    def rejected(*args, **kwargs):
        calls.append("provider")
        kwargs["broker_evidence"]["provider_stream_outcome"] = "acknowledgement_mismatch"
        return 1, "", "Gemini broker stream has a malformed chunk acknowledgement; token=PLANTED_SECRET"

    monkeypatch.setattr(pi, "_exec_leg", rejected)
    result = pi._default_spawn_via_provider("gemini", "artifact", **kwargs)
    assert result[:2] == ("ERROR", "")
    assert len(result) == 3
    assert "malformed chunk acknowledgement" in result[2]
    assert "returncode=1" in result[2]
    assert "PLANTED_SECRET" not in result[2]
    assert result.harden_isolation_evidence["provider_stream_outcome"] == "acknowledgement_mismatch"
    assert calls == ["provider", "closed"]


def test_brokered_claude_tail_survives_without_changing_pair(monkeypatch, broker_control):
    calls, kwargs = broker_control

    def stalled(**kwargs):
        calls.append("provider")
        return 1, "", "claude_tui_stalled", "elapsed_s=290.4 last_progress_age_s=274.3 child_running=true"

    monkeypatch.setattr(pi, "_run_claude_tui_session", stalled)
    original = pi._exec_claude_tui_leg

    def pair_checked(*args, **kwargs):
        result = original(*args, **kwargs)
        assert len(result) == 2
        return result

    monkeypatch.setattr(pi, "_exec_claude_tui_leg", pair_checked)
    result = pi._default_spawn_via_provider("claude", "artifact", **kwargs)
    assert result[:2] == ("DEGRADED", "")
    assert len(result) == 3
    assert "claude_tui_stalled" in result[2]
    assert "last_progress_age_s=274.3" in result[2]
    assert calls == ["provider", "closed"]


def _leg():
    result = pi.PanelLegResult(leg="gemini", status="ERROR", text="", detail="stream rejected", seat_key="gemini:test:high:review")
    pi.attach_harden_isolation_evidence(result, {
        "stage_bundle_sha256": "a" * 64,
        "provider_input_sha256": "b" * 64,
        "provider_stream_outcome": "acknowledgement_mismatch",
        "provider_stream_result_count": 3,
        "provider_stream_output_bytes": 321,
        "provider_agy_home_cleanup_verified": True,
        "provider_argv_shape": ["PLANTED_SECRET"],
        "unknown_key": "PRIVATE_SESSION_CONTENT",
    })
    return result


def _verdict_identity(path):
    info = path.stat()
    return {key: getattr(info, key) for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}


def test_stream_retains_separate_bound_diagnostic(tmp_path):
    leg = _leg()
    before = asdict(leg)
    pi._write_incremental_verdict(tmp_path, 2, leg)
    verdict = next(tmp_path.glob("*.verdict.json"))
    sidecar = next(tmp_path.glob("*.diagnostic.json"))
    payload = json.loads(sidecar.read_text())
    assert payload["schema"] == "advisor_leg_diagnostic.v1"
    assert payload["verdict_sha256"] == sha256(verdict.read_bytes()).hexdigest()
    assert payload["verdict_file_identity"] == _verdict_identity(verdict)
    assert payload["index"] == 2
    assert payload["evidence"]["stage_bundle_sha256"] == "a" * 64
    assert payload["evidence"]["provider_stream_outcome"] == "acknowledgement_mismatch"
    assert "PLANTED_SECRET" not in sidecar.read_text()
    assert "PRIVATE_SESSION_CONTENT" not in sidecar.read_text()
    assert set(json.loads(verdict.read_text())) == {"index", "leg", "seat_key", "status", "usable", "text", "detail"}
    assert asdict(leg) == before
    assert sidecar.stat().st_mode & 0o777 == 0o600
    assert sidecar.stat().st_uid == os.getuid()
    assert sidecar.stat().st_nlink == 1
    assert leg.diagnostic_retention["status"] == "saved"
    assert leg.diagnostic_retention["sha256"] == sha256(sidecar.read_bytes()).hexdigest()


def test_diagnostic_failure_is_observable_without_altering_verdict(tmp_path, monkeypatch, caplog):
    leg = _leg()

    def fail(*args, **kwargs):
        raise OSError("PLANTED_SECRET")

    monkeypatch.setattr(os, "fsync", fail)
    pi._write_incremental_verdict(tmp_path, 0, leg)
    assert leg.status == "ERROR" and not leg.text
    assert leg.diagnostic_retention["status"] == "failed"
    assert not list(tmp_path.glob("*.diagnostic.json"))
    assert list(tmp_path.glob("*.verdict.json"))
    assert "PLANTED_SECRET" not in caplog.text


def test_diagnostic_files_do_not_overwrite_earlier_inputs(tmp_path):
    first = _leg()
    pi._write_incremental_verdict(tmp_path, 0, first)
    original = {p.name: p.read_bytes() for p in tmp_path.glob("*.diagnostic.json")}
    second = _leg()
    pi.attach_harden_isolation_evidence(second, {"stage_bundle_sha256": "c" * 64})
    pi._write_incremental_verdict(tmp_path, 0, second)
    assert len(list(tmp_path.glob("*.diagnostic.json"))) == 2
    for name, content in original.items():
        assert (tmp_path / name).read_bytes() == content
    verdict = next(tmp_path.glob("*.verdict.json"))
    matching = [
        json.loads(p.read_text()) for p in tmp_path.glob("*.diagnostic.json")
        if json.loads(p.read_text())["verdict_file_identity"] == _verdict_identity(verdict)
    ]
    assert len(matching) == 1
    assert matching[0]["evidence"]["stage_bundle_sha256"] == "c" * 64
    assert {json.loads(p.read_text())["verdict_sha256"] for p in tmp_path.glob("*.diagnostic.json")} == {
        sha256(verdict.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize("raw", [
    b"Authorization: Bearer PLANTED_SECRET end",
    b'{"token": "PLANTED_SECRET", "reason": "failed"}',
    b"Bearer PLANTED_SECRET end",
])
def test_detail_redaction_covers_header_and_json_values(raw):
    assert "PLANTED_SECRET" not in pi._sanitized_pty_tail(raw, max_chars=1024)


@pytest.mark.parametrize("raw", [
    "https://user:PLANTED_SECRET@example.invalid/",
    "github_pat_" + "A" * 24 + "PLANTED_SECRET",
    "-----BEGIN PRIVATE KEY-----\nPLANTED_SECRET\n-----END PRIVATE KEY-----",  # gitleaks:allow -- invalid synthetic PEM redaction fixture
    r'{"to\u006ben": "PLANTED_SECRET"}',
    json.dumps(json.dumps({"token": "PLANTED_SECRET"})),
    json.dumps({"token": 'prefix" PLANTED_SECRET'}),
])
def test_broker_diagnostics_are_redacted_before_public_streaming(
    monkeypatch, broker_control, tmp_path, raw,
):
    calls, kwargs = broker_control

    def failed(*args, **kw):
        calls.append("provider")
        return 1, "", raw + "\nGemini stream rejected"

    monkeypatch.setattr(pi, "_exec_leg", failed)
    panel = pi.invoke_panel(
        "artifact", ["gemini"],
        spawn=lambda leg, artifact: pi._default_spawn_via_provider(leg, artifact, **kwargs),
        stream_dir=tmp_path,
    )
    leg = panel.legs[0]
    assert leg.status == "ERROR" and leg.text == ""
    assert "Gemini stream rejected" in leg.detail
    assert "PLANTED_SECRET" not in leg.detail
    assert leg.diagnostic_retention["status"] == "saved"
    for path in tmp_path.glob("*.json"):
        assert "PLANTED_SECRET" not in path.read_text()
    assert calls == ["provider", "closed"]


@pytest.mark.parametrize("ancestor", [False, True])
def test_diagnostic_writer_refuses_symlinked_directories(tmp_path, ancestor):
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    root = alias
    if ancestor:
        (outside / "child").mkdir()
        root = alias / "child"
    leg = _leg()
    pi._write_incremental_diagnostic(root, 0, leg, "d" * 64)
    assert leg.diagnostic_retention["status"] == "failed"
    assert not list(outside.rglob("*.diagnostic.json"))


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "conflict", "mode"])
def test_existing_diagnostic_cannot_be_redirected_or_overwritten(tmp_path, kind):
    leg = _leg()
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)
    destination = tmp_path / leg.diagnostic_retention["file"]
    if kind == "symlink":
        original = tmp_path / "original"
        destination.rename(original)
        destination.symlink_to(original)
    elif kind == "hardlink":
        os.link(destination, tmp_path / "linked")
    elif kind == "conflict":
        destination.write_bytes(b"original conflicting data")
    else:
        destination.chmod(0o644)
    before = destination.read_bytes()
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)
    assert leg.diagnostic_retention["status"] == "failed"
    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(".diagnostic-*.tmp"))


def test_unchanged_diagnostic_reuse_preserves_the_saved_artifact(tmp_path):
    leg = _leg()
    before = asdict(leg)
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)
    receipt = dict(leg.diagnostic_retention)
    destination = tmp_path / receipt["file"]
    content = destination.read_bytes()
    identity = pi._capture_file_identity(destination.stat())

    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)

    assert leg.diagnostic_retention == receipt
    assert receipt["status"] == "saved"
    assert receipt["sha256"] == sha256(content).hexdigest()
    assert destination.read_bytes() == content
    assert pi._capture_file_identity(destination.stat()) == identity
    assert asdict(leg) == before
    assert len(list(tmp_path.glob("*.diagnostic.json"))) == 1
    assert not list(tmp_path.glob(".diagnostic-*.tmp"))


@pytest.mark.parametrize("kind", [
    "source_swap", "source_identical", "destination_replace", "destination_identical",
    "mode", "content", "hardlink", "symlink",
])
def test_diagnostic_publication_races_are_not_reported_saved(tmp_path, monkeypatch, kind):
    real_link = os.link
    changed = []

    def change_at_link(source, destination, **kwargs):
        source_path = tmp_path / source
        destination_path = tmp_path / destination
        replacement = tmp_path / "replacement"
        if kind.startswith("source_"):
            content = source_path.read_bytes() if kind == "source_identical" else b"replaced temporary diagnostic"
            replacement.write_bytes(content)
            replacement.chmod(0o600)
            os.replace(replacement, source_path)
        real_link(source, destination, **kwargs)
        if kind.startswith("destination_"):
            content = source_path.read_bytes() if kind == "destination_identical" else b"replaced published diagnostic"
            replacement.write_bytes(content)
            replacement.chmod(0o600)
            os.replace(replacement, destination_path)
        elif kind == "mode":
            destination_path.chmod(0o644)
        elif kind == "content":
            destination_path.write_bytes(b"mutated published diagnostic")
        elif kind == "hardlink":
            real_link(destination_path, tmp_path / "extra-link")
        elif kind == "symlink":
            replacement.write_bytes(b"symlink replacement diagnostic")
            replacement.chmod(0o600)
            destination_path.unlink()
            destination_path.symlink_to(replacement)
        changed.append(kind)

    monkeypatch.setattr(os, "link", change_at_link)
    leg = _leg()
    before = asdict(leg)
    pi._write_incremental_verdict(tmp_path, 0, leg)

    assert changed == [kind]
    assert leg.diagnostic_retention == {"status": "failed"}
    assert asdict(leg) == before
    assert next(tmp_path.glob("*.verdict.json")).is_file()
    assert list(tmp_path.glob("*.diagnostic.json"))
    assert not list(tmp_path.glob(".diagnostic-*.tmp"))


def test_existing_diagnostic_changed_during_directory_sync_is_not_reported_saved(tmp_path, monkeypatch):
    leg = _leg()
    before = asdict(leg)
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)
    destination = tmp_path / leg.diagnostic_retention["file"]
    real_fsync = os.fsync
    changed = []

    def change_during_sync(fd):
        real_fsync(fd)
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            destination.chmod(0o644)
            changed.append(True)

    monkeypatch.setattr(os, "fsync", change_during_sync)
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)

    assert changed == [True]
    assert leg.diagnostic_retention == {"status": "failed"}
    assert asdict(leg) == before
    assert not list(tmp_path.glob(".diagnostic-*.tmp"))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("kind", ["content_preserved_mtime", "identical_replacement"])
def test_diagnostic_change_during_final_read_is_not_reported_saved(tmp_path, monkeypatch, existing, kind):
    leg = _leg()
    before = asdict(leg)
    if existing:
        pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)
    real_read, real_fsync = os.read, os.fsync
    synced, changed = [], []

    def record_sync(fd):
        real_fsync(fd)
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            synced.append(True)

    def change_after_read(fd, count):
        content = real_read(fd, count)
        if synced and not changed:
            destination = next(tmp_path.glob("*.diagnostic.json"))
            info = destination.stat()
            if info.st_ino == os.fstat(fd).st_ino:
                if kind == "content_preserved_mtime":
                    destination.write_bytes(b"x" + content[1:])
                    os.utime(destination, ns=(info.st_atime_ns, info.st_mtime_ns))
                else:
                    replacement = tmp_path / "replacement"
                    replacement.write_bytes(content)
                    replacement.chmod(0o600)
                    os.replace(replacement, destination)
                changed.append(True)
        return content

    monkeypatch.setattr(os, "fsync", record_sync)
    monkeypatch.setattr(os, "read", change_after_read)
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)

    assert changed == [True]
    assert leg.diagnostic_retention == {"status": "failed"}
    assert asdict(leg) == before
    assert not list(tmp_path.glob(".diagnostic-*.tmp"))


def test_publish_failure_is_fail_open_and_leaves_no_partial_sidecar(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("link failed")

    monkeypatch.setattr(os, "link", fail)
    leg = _leg()
    pi._write_incremental_verdict(tmp_path, 0, leg)
    assert leg.diagnostic_retention["status"] == "failed"
    assert not list(tmp_path.glob("*.diagnostic.json"))
    assert not list(tmp_path.glob(".diagnostic-*.tmp"))
    assert next(tmp_path.glob("*.verdict.json")).is_file()


def test_directory_sync_failure_does_not_claim_durability(tmp_path, monkeypatch):
    original = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory sync failed")
        original(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    leg = _leg()
    pi._write_incremental_verdict(tmp_path, 0, leg)
    assert leg.diagnostic_retention["status"] == "failed"
    # Publication was atomic, but directory persistence was not established.
    assert json.loads(next(tmp_path.glob("*.diagnostic.json")).read_text())


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("stage", ["directory_sync", "final_read"])
@pytest.mark.parametrize("change", ["stable", "mode", "owner", "replacement", "ancestor_symlink"])
def test_diagnostic_publication_rechecks_directory_authority(tmp_path, monkeypatch, existing, stage, change):
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir(mode=0o700)
    root = ancestor / "review"
    root.mkdir(mode=0o700)
    original = root.stat()
    root_identity = (original.st_dev, original.st_ino)
    leg = _leg()
    before = asdict(leg)
    if existing:
        pi._write_incremental_diagnostic(root, 0, leg, "d" * 64)
        assert leg.diagnostic_retention["status"] == "saved"
    real_fsync, real_fstat, real_read = os.fsync, os.fstat, os.read
    synced, changed, owner_observed = [], [], []

    def change_root():
        if change == "mode":
            root.chmod(0o777)
        elif change == "replacement":
            root.rename(ancestor / "displaced-review")
            root.mkdir(mode=0o700)
        elif change == "ancestor_symlink":
            displaced = tmp_path / "displaced-ancestor"
            ancestor.rename(displaced)
            ancestor.symlink_to(displaced, target_is_directory=True)
        changed.append(True)

    def observe_owner(fd):
        info = real_fstat(fd)
        if (change == "owner" and changed
                and (info.st_dev, info.st_ino) == root_identity):
            values = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
            values["st_uid"] = info.st_uid + 1
            owner_observed.append(True)
            return SimpleNamespace(**values)
        return info

    def change_at_sync(fd):
        real_fsync(fd)
        info = real_fstat(fd)
        if (info.st_dev, info.st_ino) == root_identity:
            synced.append(True)
            if stage == "directory_sync" and not changed:
                change_root()

    def change_after_read(fd, count):
        content = real_read(fd, count)
        if stage == "final_read" and synced and not changed:
            change_root()
        return content

    monkeypatch.setattr(os, "fsync", change_at_sync)
    monkeypatch.setattr(os, "fstat", observe_owner)
    monkeypatch.setattr(os, "read", change_after_read)
    pi._write_incremental_diagnostic(root, 0, leg, "d" * 64)

    assert changed == [True]
    assert asdict(leg) == before
    if change == "stable":
        assert leg.diagnostic_retention["status"] == "saved"
        sidecar = root / leg.diagnostic_retention["file"]
        assert leg.diagnostic_retention["sha256"] == sha256(sidecar.read_bytes()).hexdigest()
        assert sidecar.stat().st_mode & 0o777 == 0o600
        assert len(list(root.glob("*.diagnostic.json"))) == 1
    else:
        assert leg.diagnostic_retention == {"status": "failed"}
    if change == "owner":
        assert owner_observed
    assert not list(tmp_path.rglob(".diagnostic-*.tmp"))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("change", ["content", "identical_replacement"])
def test_diagnostic_change_during_directory_reopen_is_not_reported_saved(tmp_path, monkeypatch, existing, change):
    leg = _leg()
    before = asdict(leg)
    if existing:
        pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)
        assert leg.diagnostic_retention["status"] == "saved"
    real_open = pi._open_capture_directory
    changed = []

    def change_after_reopen(path):
        fd = real_open(path)
        if path == tmp_path and not changed:
            sidecar = next(tmp_path.glob("*.diagnostic.json"))
            content = sidecar.read_bytes()
            if change == "content":
                sidecar.write_bytes(b"x" + content[1:])
            else:
                replacement = tmp_path / "replacement"
                replacement.write_bytes(content)
                replacement.chmod(0o600)
                os.replace(replacement, sidecar)
            changed.append(True)
        return fd

    monkeypatch.setattr(pi, "_open_capture_directory", change_after_reopen)
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)

    assert changed == [True]
    assert leg.diagnostic_retention == {"status": "failed"}
    assert asdict(leg) == before
    assert not list(tmp_path.glob(".diagnostic-*.tmp"))


def test_failed_diagnostic_after_identical_verdict_does_not_match_old_sidecar(tmp_path, monkeypatch):
    first = _leg()
    pi._write_incremental_verdict(tmp_path, 0, first)
    sidecar = json.loads(next(tmp_path.glob("*.diagnostic.json")).read_text())

    def fail(*args, **kwargs):
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", fail)
    second = _leg()
    pi._write_incremental_verdict(tmp_path, 0, second)
    verdict = next(tmp_path.glob("*.verdict.json"))
    assert second.diagnostic_retention["status"] == "failed"
    assert sidecar["verdict_sha256"] == sha256(verdict.read_bytes()).hexdigest()
    assert sidecar["verdict_file_identity"] != _verdict_identity(verdict)


def test_failed_verdict_replace_leaves_history_not_a_new_capture(tmp_path, monkeypatch):
    first = _leg()
    pi._write_incremental_verdict(tmp_path, 0, first)
    original = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}

    def fail(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail)
    second = _leg()
    pi._write_incremental_verdict(tmp_path, 0, second)
    assert second.diagnostic_retention["status"] == "failed"
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == original
    assert not list(tmp_path.glob("*.tmp"))


def test_in_place_restore_with_preserved_mtime_invalidates_identity(tmp_path):
    leg = _leg()
    pi._write_incremental_verdict(tmp_path, 0, leg)
    verdict = next(tmp_path.glob("*.verdict.json"))
    sidecar = json.loads(next(tmp_path.glob("*.diagnostic.json")).read_text())
    original = verdict.stat()
    verdict.write_bytes(verdict.read_bytes())
    os.utime(verdict, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert sidecar["verdict_sha256"] == sha256(verdict.read_bytes()).hexdigest()
    assert verdict.stat().st_mtime_ns == original.st_mtime_ns
    assert sidecar["verdict_file_identity"] != _verdict_identity(verdict)


def test_verdict_replaced_during_diagnostic_publication_is_not_reported_saved(tmp_path, monkeypatch):
    original = os.link

    def replace_verdict(*args, **kwargs):
        original(*args, **kwargs)
        verdict = next(tmp_path.glob("*.verdict.json"))
        replacement = tmp_path / "replacement"
        replacement.write_bytes(verdict.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, verdict)

    monkeypatch.setattr(os, "link", replace_verdict)
    leg = _leg()
    pi._write_incremental_verdict(tmp_path, 0, leg)
    assert leg.diagnostic_retention["status"] == "failed"
    sidecar = json.loads(next(tmp_path.glob("*.diagnostic.json")).read_text())
    assert sidecar["verdict_file_identity"] != _verdict_identity(next(tmp_path.glob("*.verdict.json")))


def test_failed_verdict_write_cannot_reuse_an_old_retention_receipt(tmp_path):
    leg = _leg()
    pi._write_incremental_verdict(tmp_path, 0, leg)
    assert leg.diagnostic_retention["status"] == "saved"
    non_directory = tmp_path / "file"
    non_directory.write_text("unchanged")
    pi._write_incremental_verdict(non_directory / "child", 0, leg)
    assert leg.diagnostic_retention["status"] == "failed"
    assert non_directory.read_text() == "unchanged"


def test_disabled_streaming_leaves_no_diagnostic_receipt(tmp_path):
    leg = _leg()
    before = set(tmp_path.iterdir())
    result = pi._run_legs_ordered([leg], lambda item: item, max_concurrency=1)
    assert result == [leg]
    assert leg.diagnostic_retention is None
    assert set(tmp_path.iterdir()) == before


def test_missing_posix_capture_support_does_not_disable_legacy_streaming(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "O_NOFOLLOW")
    leg = _leg()
    pi._write_incremental_verdict(tmp_path, 0, leg)
    verdict = json.loads(next(tmp_path.glob("*.verdict.json")).read_text())
    assert verdict["status"] == "ERROR" and verdict["text"] == ""
    assert leg.diagnostic_retention["status"] == "failed"
    assert not list(tmp_path.glob("*.diagnostic.json"))


def test_same_label_seats_have_distinct_bound_sidecars(tmp_path):
    legs = [_leg(), _leg()]
    results = pi._run_legs_ordered(legs, lambda item: item, max_concurrency=2, review_dir=tmp_path)
    assert results == legs
    sidecars = [json.loads(p.read_text()) for p in tmp_path.glob("*.diagnostic.json")]
    assert {entry["index"] for entry in sidecars} == {0, 1}
    assert len({entry["verdict_sha256"] for entry in sidecars}) == 2


def test_malformed_metadata_is_not_serialized_as_provider_diagnostics(tmp_path):
    leg = _leg()
    pi.attach_harden_isolation_evidence(leg, {
        "provider_input_sha256": "PRIVATE_CONTENT",
        "provider_stream_result_count": True,
        "provider_liveness_stall_threshold_s": float("nan"),
        "provider_stream_outcome": "UNKNOWN_PRIVATE_MESSAGE",
        "provider_agy_home_cleanup_verified": "true",
    })
    pi._write_incremental_diagnostic(tmp_path, 0, leg, "d" * 64)
    sidecar = json.loads(next(tmp_path.glob("*.diagnostic.json")).read_text())
    assert sidecar["evidence"] == {}
