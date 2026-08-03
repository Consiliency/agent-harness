from __future__ import annotations

import json
import os
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
