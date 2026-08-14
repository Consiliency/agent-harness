from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from phase_loop_runtime import agy_canary_evidence as evidence
from phase_loop_runtime.cli import main


def _private_root(tmp_path: Path) -> Path:
    root = Path("/tmp") / f"phase-loop-agy-canary.test-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    return root


def _settings(tmp_path: Path, allow: list[str]) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {"allow": allow, "deny": ["command(rm)"]},
                "toolPermission": "request-review",
                "allowNonWorkspaceAccess": False,
                "unrelated": {"preserved": [1, 2, 3]},
            },
            indent=2,
        )
        + "\n"
    )
    path.chmod(0o600)
    return path


def test_clean_settings_cli_removes_exact_rule_and_preserves_structure(tmp_path, capsys):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, ["command(pwd)"])
        before = json.loads(settings.read_text())
        rc = main(
            [
                "agy-canary-clean-settings",
                "--evidence-root",
                str(root),
                "--settings-path",
                str(settings),
                "--maintenance-lock",
                str(tmp_path / "maintenance.lock"),
            ]
        )
        assert rc == 0
        status = json.loads(capsys.readouterr().out)
        assert status["state"] == "committed"
        assert status["result"] == "removed_exact_rule"
        assert status["structural_delta_valid"] is True
        after = json.loads(settings.read_text())
        before["permissions"]["allow"] = []
        assert after == before
        assert stat.S_IMODE(settings.stat().st_mode) == 0o600
        snapshot = root / "agy-settings.pre.json"
        assert not snapshot.is_symlink()
        assert json.loads(snapshot.read_text())["permissions"]["allow"] == ["command(pwd)"]
        state = json.loads((root / "cleanup-state.json").read_text())
        assert state["state"] == "committed"
        assert state["transitions"] == [
            "prepared",
            "exchanged_unverified",
            "verified",
            "committed",
        ]
        assert not list(tmp_path.glob(".phase-loop-agy-settings.*.tmp"))
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_clean_settings_cli_records_already_absent(tmp_path, capsys):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        original = settings.read_bytes()
        rc = main(
            [
                "agy-canary-clean-settings",
                "--evidence-root",
                str(root),
                "--settings-path",
                str(settings),
                "--maintenance-lock",
                str(tmp_path / "maintenance.lock"),
            ]
        )
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["result"] == "already_absent"
        assert settings.read_bytes() == original
        assert json.loads((root / "cleanup-state.json").read_text())["transitions"] == [
            "prepared",
            "verified",
            "committed",
        ]
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


@pytest.mark.parametrize(
    "payload",
    [
        {"permissions": {"allow": ["command(pwd)", "command(git)"]}},
        {"permissions": {"allow": ["command(pwd)", "command(pwd)"]}},
        {"permissions": {"allow": []}, "toolPermission": "always-proceed"},
        {"permissions": {"allow": []}, "allowNonWorkspaceAccess": True},
    ],
)
def test_clean_settings_fails_closed_without_mutation(tmp_path, payload):
    root = _private_root(tmp_path)
    try:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(payload))
        settings.chmod(0o600)
        original = settings.read_bytes()
        with pytest.raises(evidence.AgyCanaryEvidenceError):
            evidence.clean_settings(
                evidence_root=root,
                settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert settings.read_bytes() == original
        assert not (root / "agy-settings.pre.json").exists()
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_clean_settings_rejects_symlinked_evidence_root(tmp_path):
    target = _private_root(tmp_path)
    link = Path("/tmp") / f"phase-loop-agy-canary.link-{os.getpid()}-{tmp_path.name}"
    link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="real directory"):
            evidence.clean_settings(
                evidence_root=link,
                settings_path=_settings(tmp_path, []),
                maintenance_lock=tmp_path / "maintenance.lock",
            )
    finally:
        link.unlink()
        target.rmdir()


def test_clean_settings_rolls_back_after_exchange_failure(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, ["command(pwd)"])
        original = settings.read_bytes()
        real_reopen = evidence._reopen_at
        calls = 0

        def fail_destination(directory_fd: int, name: str):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise evidence.AgyCanaryEvidenceError("injected post-exchange failure")
            return real_reopen(directory_fd, name)

        monkeypatch.setattr(evidence, "_reopen_at", fail_destination)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="injected"):
            evidence.clean_settings(
                evidence_root=root,
                settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert settings.read_bytes() == original
        state = json.loads((root / "cleanup-state.json").read_text())
        assert state["state"] == "rolled_back"
        assert state["transitions"][-2:] == ["rollback_required", "rolled_back"]
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_clean_settings_blocks_when_agy_process_is_active(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, ["command(pwd)"])

        def blocked(*_args, **_kwargs):
            raise evidence.AgyCanaryEvidenceError("settings tree is not quiescent: pid=123,process=agy")

        monkeypatch.setattr(evidence, "_assert_quiescent", blocked)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="not quiescent"):
            evidence.clean_settings(
                evidence_root=root,
                settings_path=settings,
                maintenance_lock=tmp_path / "maintenance.lock",
            )
        assert json.loads(settings.read_text())["permissions"]["allow"] == ["command(pwd)"]
        assert not (root / "agy-settings.pre.json").exists()
    finally:
        for child in root.iterdir():
            child.unlink()
        root.rmdir()


def test_capture_reducer_requires_complete_sealed_staged_reads(tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary")
            review = tmp_path / "review"
            review.mkdir()
            instructions = review / "review-instructions.md"
            bundle = review / "review-bundle.md"
            instructions.write_text("read this first\n")
            bundle.write_text("review this\n")
            instructions.chmod(0o600)
            bundle.chmod(0o600)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s1", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
                {"sequence": 1, "session_id": "s1", "type": "tool_result", "call_id": "a", "outcome": "success", "sha256": staged["review-instructions.md"]["sha256"], "bytes": staged["review-instructions.md"]["bytes"]},
                {"sequence": 2, "session_id": "s1", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
                {"sequence": 3, "session_id": "s1", "type": "tool_result", "call_id": "b", "outcome": "success", "sha256": staged["review-bundle.md"]["sha256"], "bytes": staged["review-bundle.md"]["bytes"]},
                {"sequence": 4, "session_id": "s1", "type": "terminal", "text": "Looks good\nAGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret prompt"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
        finally:
            capture.close()
        proof = evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
        assert proof["attempt_ids"] == ["gemini-1"]
        assert proof["attempts"][0]["counts"] == {"command": 0, "unsandboxed": 0, "non_read_tool": 0, "out_of_stage_read": 0}
    finally:
        shutil.rmtree(root)


def test_capture_reducer_rejects_unpaired_tool_evidence(tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary")
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            broken = {"sequence": 0, "session_id": "s1", "type": "tool_call", "call_id": "bad", "tool": "command", "target": "true"}
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret prompt"], returncode=0, stdout=json.dumps(broken), stderr="", staged=staged)
        finally:
            capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="complete"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()


def test_capture_reducer_rejects_denied_command_and_alias_stage_read(tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary")
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/not-stage/review-instructions.md"},
                {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "sha256": staged["review-instructions.md"]["sha256"], "bytes": staged["review-instructions.md"]["bytes"]},
                {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "command", "target": "true"},
                {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "denied"},
                {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
        finally:
            capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="prohibited tool attempt"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()


def test_namespace_masks_evidence_root_and_uses_fixed_stage(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        stage = tmp_path / "stage"
        stage.mkdir()
        for name in ("review-instructions.md", "review-bundle.md"):
            (stage / name).write_text(name)
        home = tmp_path / "home"
        home.mkdir()
        namespace = evidence.AgyCanaryNamespace(stage, home, root, "example.invalid")
        monkeypatch.setattr(evidence.shutil, "which", lambda _name: "/usr/bin/bwrap")
        command = namespace.command(["agy", "--version"])
        assert "--tmpfs" in command
        assert "/run/phase-loop-review" in command
        assert str(root) not in command
    finally:
        root.rmdir()


def test_minimal_home_keeps_auth_bytes_outside_evidence_and_binds_read_only(tmp_path):
    root = _private_root(tmp_path)
    home = None
    try:
        auth = tmp_path / "auth.json"
        auth.write_text('{"token":"private"}')
        auth.chmod(0o600)
        home, binds = evidence.build_minimal_home(
            evidence_root=root, settings_path=_settings(tmp_path, []), auth_paths=(auth,)
        )
        assert root not in home.parents
        assert binds == ((auth, str(home / ".gemini" / "antigravity-cli" / "auth" / "auth.json")),)
        assert (home / ".gemini" / "antigravity-cli" / "settings.json").is_file()
        assert Path(binds[0][1]).read_bytes() == b""
    finally:
        if home is not None:
            shutil.rmtree(home)
        root.rmdir()


def test_probe_selects_1_1_13_stream_json_only_after_strict_parse(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        stage = tmp_path / "stage"
        stage.mkdir()
        for name in ("review-instructions.md", "review-bundle.md"):
            (stage / name).write_text(name)
        home = tmp_path / "home"
        home.mkdir()
        namespace = evidence.AgyCanaryNamespace(stage, home, root, "example.invalid")
        events = "\n".join(json.dumps(item) for item in [
            {"sequence": 0, "session_id": "p", "type": "terminal", "text": "READY"},
        ])
        calls = []

        class Proc:
            returncode = 0
            stderr = ""
            def __init__(self, stdout):
                self.stdout = stdout

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command == ["agy", "--version"]:
                return Proc("1.1.13\n")
            if command == ["agy", "--help"]:
                return Proc("--output-format text, json, stream-json")
            return Proc(events if "agy" in command else "")

        monkeypatch.setattr(evidence.subprocess, "run", fake_run)
        monkeypatch.setattr(evidence.shutil, "which", lambda _name: "/usr/bin/bwrap")
        result = evidence.probe_capability(evidence_root=root, namespace=namespace)
        assert result["complete"] is True
        assert result["mode"] == "stream_json"
        assert any("--output-format" in command for command in calls)
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()


def test_prepare_requires_bootstrap_and_binds_selected_mode(tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        (root / "cleanup-state.json").write_text(json.dumps({"state": "committed"}))
        (root / "agy_capability_probe.json").write_text(json.dumps({"complete": True, "mode": "stream_json"}))
        (root / "agy_canary_bootstrap_attestation.json").write_text(json.dumps({"bootstrap": {"returncode": 0}}))
        prepared = evidence.prepare_canary(evidence_root=root, settings_path=settings, seat_key="gemini-primary")
        assert prepared["seat_key"] == "gemini-primary"
        ledger = json.loads((root / "agy-launch-ledger.json").read_text())
        assert ledger["capture_mode"] == "stream_json"
    finally:
        shutil.rmtree(root)


def test_finalizer_only_appends_canonical_proof_and_updates_matching_manifest(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        repo = tmp_path / "dotfiles"
        plans = repo / "plans"
        plans.mkdir(parents=True)
        plan = plans / "canary.md"
        manifest = plans / "manifest.json"
        plan.write_text("# Plan\n")
        manifest.write_text(json.dumps({"plans": [{"slug": "agy-canary", "updated_at": "old"}]}))
        proof = {"schema": evidence.SCHEMA_VERSION, "seat_key": "gemini-primary", "attempt_ids": ["gemini-1"]}
        monkeypatch.setattr(evidence, "verify_capture", lambda **_kwargs: proof)
        result = evidence.finalize_canary(
            evidence_root=root,
            expected_seat_key="gemini-primary",
            dotfiles_repo=repo,
            plan_path=Path("plans/canary.md"),
            manifest_path=Path("plans/manifest.json"),
            plan_slug="agy-canary",
        )
        assert result["inputs_sha256"]
        assert "## Execution evidence" in plan.read_text()
        assert json.loads(manifest.read_text())["plans"][0]["updated_at"] != "old"
        assert (root / "agy_canary_inputs.json").is_file()
    finally:
        shutil.rmtree(root)
