from __future__ import annotations

import argparse
import json
import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import agy_canary_evidence as evidence
from phase_loop_runtime import cli
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


def _source_inventory(tmp_path: Path) -> dict[str, object]:
    return evidence.freeze_customization_inventory(home=tmp_path, project_dir=tmp_path, env={})


def _git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)


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
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary", source_inventory=_source_inventory(tmp_path))
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
                {"sequence": 1, "session_id": "s1", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "read this first\n"},
                {"sequence": 2, "session_id": "s1", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
                {"sequence": 3, "session_id": "s1", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "review this\n"},
                {"sequence": 4, "session_id": "s1", "type": "terminal", "text": "Looks good\nAGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret prompt"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
            evidence.write_private_board(
                capture=capture,
                basename="board.json",
                payload={"agy_canary_capture": evidence.capture_summary(capture)},
            )
        finally:
            capture.close()
        proof = evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
        assert proof["attempt_ids"] == ["gemini-1"]
        assert proof["attempts"][0]["counts"] == {"command": 0, "unsandboxed": 0, "non_read_tool": 0, "out_of_stage_read": 0}
    finally:
        shutil.rmtree(root)


def test_capture_reducer_rejects_missing_or_swapped_private_board(tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary", source_inventory=_source_inventory(tmp_path))
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
                {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "review-instructions.md"},
                {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
                {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "review-bundle.md"},
                {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
            evidence.write_private_board(capture=capture, basename="board.json", payload={"agy_canary_capture": evidence.capture_summary(capture)})
            (root / "board.json").write_text('{"agy_canary_capture":"swapped"}')
        finally:
            capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="private board payload bytes drifted"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize(
    "events",
    [
        [
            {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
            {"sequence": 1, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
        ],
        [
            {"sequence": 0, "session_id": "s", "type": "terminal", "text": "AGREE"},
            {"sequence": 1, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
        ],
    ],
)
def test_stream_rejects_interleaved_or_post_terminal_events(events):
    with pytest.raises(evidence.AgyCanaryEvidenceError):
        evidence._parse_stream("\n".join(json.dumps(event) for event in events).encode())


def test_stream_rejects_duplicate_staged_read_even_when_one_copy_has_right_content():
    events = [
        {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
        {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "wrong"},
        {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
        {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "right"},
        {"sequence": 4, "session_id": "s", "type": "tool_call", "call_id": "c", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
        {"sequence": 5, "session_id": "s", "type": "tool_result", "call_id": "c", "outcome": "success", "content": "bundle"},
        {"sequence": 6, "session_id": "s", "type": "terminal", "text": "AGREE"},
    ]
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="exactly two staged reads"):
        evidence._parse_stream("\n".join(json.dumps(event) for event in events).encode(), require_staged_reads=True)


def test_capture_namespace_reopens_auth_and_resolver_for_child_paths(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    try:
        settings = _settings(tmp_path, [])
        evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary", source_inventory=_source_inventory(tmp_path))
        auth = tmp_path / "auth.json"
        auth.write_text('{"credential":"private"}')
        auth.chmod(0o600)
        home, binds = evidence.build_minimal_home(
            evidence_root=root, settings_path=settings, auth_paths=(auth,)
        )
        ledger = evidence._read_json_at(capture.root_fd, "agy-launch-ledger.json")
        ledger["minimal_home"] = str(home)
        ledger["auth_binds"] = [{"source": str(auth), "destination": binds[0][1], "source_sha256": evidence._sha256(auth.read_bytes())}]
        evidence._write_replace_at(capture.root_fd, "agy-launch-ledger.json", ledger)
        evidence._exclusive_write_at(capture.root_fd, "agy_canary_prepare.json", evidence._canonical_json({"schema": "agy_canary_prepare.v1", "seat_key": ledger["seat_key"], "ledger_sha256": evidence._sha256(evidence._canonical_json(ledger))}), 0o600)
        resolver = tmp_path / "resolv.conf"
        resolver.write_text("nameserver 127.0.0.1\n")
        monkeypatch.setattr(evidence, "_resolver_snapshot", lambda: (resolver, evidence._sha256(resolver.read_bytes())))
        stage = tmp_path / "stage"
        stage.mkdir()
        namespace = evidence.capture_namespace(capture=capture, stage=stage)
        command = namespace.command(["agy", "--version"])
        assert binds[0][1] in command
        assert str(auth) in command
        assert str(resolver) in command
    finally:
        capture.close()
        shutil.rmtree(root)


def test_bwrap_auth_bind_is_visible_only_at_child_lookup_path(tmp_path):
    if not Path("/usr/bin/bwrap").is_file():
        pytest.skip("bwrap is unavailable")
    root = _private_root(tmp_path)
    try:
        stage = tmp_path / "stage"
        stage.mkdir()
        home = tmp_path / "home"
        (home / ".gemini" / "antigravity-cli" / "auth").mkdir(parents=True)
        home.chmod(0o700)
        placeholder = home / ".gemini" / "antigravity-cli" / "auth" / "auth.json"
        placeholder.write_bytes(b"")
        placeholder.chmod(0o600)
        auth = tmp_path / "auth.json"
        auth.write_text("dummy-private-auth")
        auth.chmod(0o600)
        destination = "/home/phase-loop/.gemini/antigravity-cli/auth/auth.json"
        namespace = evidence.AgyCanaryNamespace(
            stage=stage, minimal_home=home, evidence_root=root,
            provider_hostname="example.invalid", auth_binds=((auth, destination),),
        )
        proc = evidence.subprocess.run(
            namespace.command(["/bin/sh", "-c", f"test \"$(cat {destination})\" = dummy-private-auth"]),
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr
    finally:
        shutil.rmtree(root)


def test_capture_reducer_rejects_unpaired_tool_evidence(tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary", source_inventory=_source_inventory(tmp_path))
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
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary", source_inventory=_source_inventory(tmp_path))
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/not-stage/review-instructions.md"},
                {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "review-instructions.md"},
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


def test_capture_reducer_derives_staged_proof_from_content_not_reported_digest(tmp_path):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary", source_inventory=_source_inventory(tmp_path))
            review = tmp_path / "review"
            review.mkdir()
            for name in ("review-instructions.md", "review-bundle.md"):
                path = review / name
                path.write_text(name)
                path.chmod(0o600)
            staged = evidence.retain_staged_files(capture=capture, review_dir=review)
            events = [
                {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
                {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "forged", "sha256": staged["review-instructions.md"]["sha256"], "bytes": staged["review-instructions.md"]["bytes"]},
                {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
                {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "review-bundle.md"},
                {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
            ]
            evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(event) for event in events), stderr="", staged=staged)
        finally:
            capture.close()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="schema"):
            evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


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
        command = namespace.command(["agy", "--version"])
        assert "--tmpfs" in command
        assert "/run/phase-loop-review" in command
        assert str(root) not in command
    finally:
        root.rmdir()


def test_namespace_uses_private_fixed_provider_output_mapping_and_pid_namespace(tmp_path):
    root = _private_root(tmp_path)
    output = Path("/tmp") / f"phase-loop-provider-output.test-{os.getpid()}-{tmp_path.name}"
    output.mkdir(mode=0o700)
    try:
        namespace = evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid", provider_output=output)
        command = namespace.command(["agent", "--result", namespace.rewrite_provider_output_path(output / "result.json")])
        assert "--unshare-pid" in command
        assert command.index("--unshare-pid") < command.index("--clearenv")
        output_dir = command.index("/run/phase-loop-output")
        assert command[output_dir - 1] == "--dir"
        assert command[output_dir + 1:output_dir + 4] == ["--bind", str(output), "/run/phase-loop-output"]
        assert str(root) not in command
        assert command[-1] == "/run/phase-loop-output/result.json"
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="escapes"):
            namespace.rewrite_provider_output_path(tmp_path / "outside.json")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="distinct"):
            evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid", provider_output=root).command(["agent"])
    finally:
        shutil.rmtree(output)
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
        assert binds == ((auth, "/home/phase-loop/.gemini/antigravity-cli/auth/auth.json"),)
        assert (home / ".gemini" / "antigravity-cli" / "settings.json").is_file()
        assert (home / ".gemini" / "antigravity-cli" / "auth" / "auth.json").read_bytes() == b""
    finally:
        if home is not None:
            shutil.rmtree(home)
        root.rmdir()


def _capability_stream(class_name: str, mutation: str | None = None) -> str:
    capability = next(item for item in evidence._CAPABILITY_CLASSES if item[0] == class_name)
    _name, tool, target, outcome = capability
    calls = [("read-a", tool, "/run/phase-loop-review/review-instructions.md", "review-instructions.md")]
    if class_name == "allowed_read":
        calls.append(("read-b", tool, "/run/phase-loop-review/review-bundle.md", "review-bundle.md"))
    else:
        calls[0] = ("call", tool, target, "READY")
    events = []
    for call_id, call_tool, call_target, content in calls:
        events.extend([
            {"sequence": len(events), "session_id": class_name, "type": "tool_call", "call_id": call_id, "tool": call_tool, "target": call_target, "attempt": True},
            {"sequence": len(events) + 1, "session_id": class_name, "type": "tool_result", "call_id": call_id, "outcome": outcome, "content": content, "execution": True},
        ])
    if mutation == "omit":
        events = []
    elif mutation == "alias":
        events[2 if class_name == "allowed_read" else 0]["target"] = "/run/phase-loop-review/review-instructions.md"
    elif mutation == "unpair":
        events[1]["call_id"] = "other"
    elif mutation == "wrong_target":
        events[0]["target"] = "/wrong-target"
    elif mutation == "wrong_outcome":
        events[1] = {"sequence": 1, "session_id": class_name, "type": "tool_result", "call_id": events[0]["call_id"], "outcome": "denied", "execution": True}
    events.append({"sequence": len(events), "session_id": class_name, "type": "terminal", "text": "READY"})
    return "\n".join(json.dumps(item) for item in events)


def _probe_namespace(tmp_path: Path, root: Path) -> evidence.AgyCanaryNamespace:
    stage = tmp_path / "stage"
    stage.mkdir()
    for name in ("review-instructions.md", "review-bundle.md"):
        path = stage / name
        path.write_text(name)
        path.chmod(0o600)
    home = tmp_path / "home"
    home.mkdir()
    return evidence.AgyCanaryNamespace(stage, home, root, "example.invalid")


def _install_capability_process(monkeypatch, mutation: tuple[str, str] | None = None):
    calls = []
    source = Path("/bin/true").resolve(strict=True)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(
        source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)

    class Proc:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, **kwargs):
        calls.append((command, kwargs.get("env")))
        if command[-1:] == ["--version"]:
            return Proc("1.1.13\n")
        if command[-1:] == ["--help"]:
            return Proc("--output-format text, json, stream-json")
        prompt = command[-1] if command else ""
        class_name = next((name for name, *_rest in evidence._CAPABILITY_CLASSES if prompt == evidence._capability_prompt(name)), None)
        return Proc(_capability_stream(class_name, mutation[1] if mutation and mutation[0] == class_name else None) if class_name else "")

    monkeypatch.setattr(evidence.subprocess, "run", fake_run)
    return calls


def test_probe_selects_1_1_13_stream_json_only_after_complete_capability_matrix(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        calls = _install_capability_process(monkeypatch)
        result = evidence.probe_capability(evidence_root=root, namespace=_probe_namespace(tmp_path, root))
        assert result["complete"] is True
        assert result["mode"] == "stream_json"
        assert result["schema"] == "agy_capability_probe.v2"
        assert [row["class"] for row in result["classes"]] == [item[0] for item in evidence._CAPABILITY_CLASSES]
        assert all(row["attempt"] and row["execution"] and row["result"] == "text" for row in result["classes"])
        assert any("--output-format" in command for command, _env in calls)
        assert all(env is not None and not any(name.startswith(("LD_", "DYLD_", "PYTHON")) for name in env) for _command, env in calls)
    finally:
        shutil.rmtree(root)


def test_probe_rejects_each_missing_aliased_unpaired_or_wrong_capability_class(monkeypatch, tmp_path):
    for class_name, *_rest in evidence._CAPABILITY_CLASSES:
        for mutation in ("omit", "alias", "unpair", "wrong_target", "wrong_outcome"):
            root = _private_root(tmp_path)
            try:
                _install_capability_process(monkeypatch, (class_name, mutation))
                result = evidence.probe_capability(evidence_root=root, namespace=_probe_namespace(tmp_path, root))
                assert result["complete"] is False
                assert result["mode"] is None
                assert result["reason"].startswith(f"stream_json_capability_unproven:{class_name}:")
            finally:
                shutil.rmtree(root)
                shutil.rmtree(tmp_path / "stage")
                shutil.rmtree(tmp_path / "home")


def test_prepare_requires_bootstrap_and_binds_selected_mode(tmp_path, monkeypatch):
    root = _private_root(tmp_path)
    try:
        settings = _settings(tmp_path, [])
        evidence.clean_settings(
            evidence_root=root,
            settings_path=settings,
            maintenance_lock=tmp_path / "maintenance.lock",
        )
        rows = []
        staged = {}
        for name in ("review-instructions.md", "review-bundle.md"):
            retained = f"agy-capability-stage-{name}"
            raw_stage = name.encode()
            (root / retained).write_bytes(raw_stage)
            staged[name] = {"name": retained, "bytes": len(raw_stage), "sha256": evidence._sha256(raw_stage)}
        for class_name, tool, target, outcome in evidence._CAPABILITY_CLASSES:
            name = f"agy-capability-{class_name}.jsonl"
            raw = _capability_stream(class_name).encode()
            (root / name).write_bytes(raw)
            rows.append({
                "class": class_name, "tool": tool, "target": target,
                "attempt": True, "execution": True, "result": "text", "outcome": outcome,
                "stream": {"name": name, "bytes": len(raw), "sha256": evidence._sha256(raw)},
            })
        (root / "agy_capability_probe.json").write_text(json.dumps({
            "schema": "agy_capability_probe.v2", "agy_version": "1.1.13",
            "help_sha256": "a" * 64, "mode": "stream_json", "complete": True, "classes": rows,
            "staged": staged,
        }))
        installation = {
            "console_script": "/tool/phase-loop", "interpreter": "/tool/python", "version": "0.7.14",
            "distribution_root": "/tool/site-packages", "module_origin": "/tool/site-packages/phase_loop_runtime/__init__.py",
            "direct_url_sha256": "a" * 64, "archive_hash": "sha256=" + "b" * 64,
            "archive_url_sha256": "c" * 64,
        }
        monkeypatch.setattr(evidence, "_installed_phase_loop_identity", lambda: installation)
        (root / "agy_canary_bootstrap_attestation.json").write_text(json.dumps({"bootstrap": {"returncode": 0, "installation": installation}, "targets": {"plan": "plans/canary.md", "manifest": "plans/manifest.json"}, "blobs": {"plans/canary.md": "a", "plans/manifest.json": "b"}}))
        release = {"version": "0.7.14", "artifacts": [{"filename": "phase_loop_runtime.whl", "sha256": "b" * 64, "url_sha256": "c" * 64}]}
        monkeypatch.setattr(evidence, "_reconcile_release_lineage", lambda **_kwargs: release)
        harness = tmp_path / "agent-harness"
        harness.mkdir()
        prepared = evidence.prepare_canary(
            evidence_root=root, settings_path=settings, seat_key="gemini-primary",
            agent_harness_repo=harness, handoff_commit="d" * 40,
            customization_home=tmp_path, project_dir=tmp_path, source_env={},
        )
        assert prepared["seat_key"] == "gemini-primary"
        ledger = json.loads((root / "agy-launch-ledger.json").read_text())
        assert ledger["capture_mode"] == "stream_json"
    finally:
        shutil.rmtree(root)


def test_bootstrap_attest_rejects_caller_selected_child_command(tmp_path):
    root = _private_root(tmp_path)
    try:
        with pytest.raises(TypeError):
            evidence.bootstrap_attest(
                evidence_root=root,
                dotfiles_repo=tmp_path,
                bootstrap_command=("sh", "-c", "false"),  # type: ignore[call-arg]
            )
    finally:
        root.rmdir()


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
        (repo / "bootstrap.sh").write_text("#!/bin/sh\n")
        (repo / "shared").mkdir()
        (repo / "shared" / "agent-harness.pin").write_text("v0.7.14\n")
        _git_repo(repo)
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        blobs = {
            name: subprocess.check_output(["git", "-C", str(repo), "rev-parse", f"HEAD:{name}"], text=True).strip()
            for name in ("bootstrap.sh", "shared/agent-harness.pin", "plans/canary.md", "plans/manifest.json")
        }
        (root / "agy_canary_bootstrap_attestation.json").write_text(json.dumps({
            "repo_head": head, "blobs": blobs,
            "input_sha256": {
                name: evidence._sha256((repo / name).read_bytes())
                for name in ("bootstrap.sh", "shared/agent-harness.pin", "plans/canary.md", "plans/manifest.json")
            },
            "targets": {"plan": "plans/canary.md", "manifest": "plans/manifest.json"},
        }))
        release = {
            "version": "0.7.14", "handoff_commit": "a" * 40, "release_commit": "b" * 40,
            "tag_object": "c" * 40, "tag_peel": "b" * 40,
            "artifacts": [
                {"filename": "phase-loop-runtime-0.7.14-py3-none-any.whl", "packagetype": "bdist_wheel", "sha256": "d" * 64, "url_sha256": "e" * 64},
                {"filename": "phase-loop-runtime-0.7.14.tar.gz", "packagetype": "sdist", "sha256": "f" * 64, "url_sha256": "0" * 64},
            ],
        }
        (root / "agy_canary_prepare.json").write_text(json.dumps({
            "release": release, "release_sha256": evidence._sha256(evidence._canonical_json(release)), "seat_key": "gemini-primary",
        }))
        proof = {"schema": evidence.SCHEMA_VERSION, "seat_key": "gemini-primary", "attempt_ids": ["gemini-1"], "capture_mode": "stream_json", "attempts": [{"attempt_id": "gemini-1", "counts": {"command": 0, "unsandboxed": 0, "non_read_tool": 0, "out_of_stage_read": 0}, "terminal_sha256": "1" * 64}], "accepted_review_sha256": "2" * 64, "private_board_sha256": "3" * 64}
        (root / "agy_canary_proof.json").write_bytes(evidence._canonical_json(proof))
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
        checked = evidence.check_private_final(
            evidence_root=root, expected_seat_key="gemini-primary", dotfiles_repo=repo,
            plan_path=Path("plans/canary.md"), manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
        )
        assert checked["inputs_sha256"] == result["inputs_sha256"]
        subprocess.run(["git", "-C", str(repo), "add", "plans/canary.md", "plans/manifest.json"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "finalize"], check=True)
        committed = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        monkeypatch.setattr(evidence, "_reconcile_release_lineage", lambda **_kwargs: release)
        assert evidence.check_committed_final(
            dotfiles_repo=repo, commit=committed, plan_path=Path("plans/canary.md"),
            manifest_path=Path("plans/manifest.json"), plan_slug="agy-canary",
            agent_harness_repo=repo, handoff_commit=release["handoff_commit"],
        )["commit"] == committed
        bootstrap = json.loads((root / "agy_canary_bootstrap_attestation.json").read_text())
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="release"):
            evidence._validate_committed_attestation(
                repo=repo,
                attestation={
                    "bootstrap": {name: bootstrap[name] for name in ("repo_head", "blobs", "input_sha256")},
                    "release": {"version": "0.7.14", "release_commit": "b" * 40, "artifacts": []},
                    "release_sha256": evidence._sha256(evidence._canonical_json({"version": "0.7.14", "release_commit": "b" * 40, "artifacts": []})),
                    "proof": evidence._proof_identity(proof),
                    "reducer_proof_sha256": evidence._sha256(evidence._canonical_json(proof)),
                },
                plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", "HEAD^:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", "HEAD^:plans/manifest.json"]),
            )
        _prefix, payload = evidence._parse_final_payload(plan.read_bytes())
        tampered = json.loads(json.dumps(payload["attestation"]))
        tampered["bootstrap"]["input_sha256"]["bootstrap.sh"] = "0" * 64
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="bootstrap blob"):
            evidence._validate_committed_attestation(
                repo=repo, attestation=tampered, plan_relative="plans/canary.md", manifest_relative="plans/manifest.json",
                plan_before=subprocess.check_output(["git", "-C", str(repo), "show", "HEAD^:plans/canary.md"]),
                manifest_before=subprocess.check_output(["git", "-C", str(repo), "show", "HEAD^:plans/manifest.json"]),
            )
    finally:
        shutil.rmtree(root)


def test_real_source_inventory_rejects_environment_override_and_generated_capture_never_claims_complete(tmp_path):
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="customization source"):
        evidence.freeze_customization_inventory(
            home=tmp_path, project_dir=tmp_path, env={"AGY_PLUGIN_PATH": "ignored"}
        )
    root = _private_root(tmp_path)
    try:
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            ledger = evidence.create_capture(capture=capture, settings_path=_settings(tmp_path, []), seat_key="gemini-primary")
            assert ledger["policy"]["sources_complete"] is False
        finally:
            capture.close()
    finally:
        shutil.rmtree(root)


def test_namespace_masks_all_xdg_sources_and_finalizer_requires_tracked_repo(tmp_path):
    root = _private_root(tmp_path)
    try:
        namespace = evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid")
        command = namespace.command(["agy", "--version"])
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_DIRS", "XDG_RUNTIME_DIR"):
            assert name in command
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="customization source"):
            evidence.freeze_customization_inventory(home=tmp_path, project_dir=tmp_path, env={"XDG_CONFIG_HOME": "/tmp/host-config"})
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="bootstrap-attested dotfiles repository"):
            evidence.finalize_canary(evidence_root=root, expected_seat_key="gemini-primary")
    finally:
        shutil.rmtree(root)


def test_namespace_binds_trusted_home_agi_at_fixed_path_without_exposing_home(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    try:
        source = tmp_path / "agy"
        source.write_bytes(b"trusted-agy")
        source.chmod(0o700)
        info = source.stat()
        runtime = evidence._TrustedAgyRuntime(source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), evidence._sha256(source.read_bytes()))
        monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)
        command = evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid").agy_command(["agy", "--version"])
        assert "--tmpfs" in command and "/home" in command
        assert str(source) in command and runtime.destination in command
        assert command[-3:] == ["--", runtime.destination, "--version"]
        source.write_bytes(b"replaced")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted"):
            evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid").agy_command(["agy", "--version"])
    finally:
        shutil.rmtree(root)


def test_probe_revalidates_trusted_executable_before_host_exec(monkeypatch, tmp_path):
    root = _private_root(tmp_path)
    source = tmp_path / "agy"
    source.write_bytes(b"trusted")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), evidence._sha256(source.read_bytes()))
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)
    monkeypatch.setattr(evidence._TrustedAgyRuntime, "revalidate", lambda _self: (_ for _ in ()).throw(evidence.AgyCanaryEvidenceError("drift")))
    monkeypatch.setattr(evidence.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("host agy must not execute after drift"))
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="drift"):
        evidence.probe_capability(evidence_root=root)
    shutil.rmtree(root)


def test_provider_launch_authority_revalidates_runtime_and_exactly_ingests_output(tmp_path):
    root = _private_root(tmp_path)
    output = Path("/tmp") / f"phase-loop-provider-output.test-{os.getpid()}-{tmp_path.name}"
    output.mkdir(mode=0o700)
    source = tmp_path / "codex"
    source.write_bytes(b"trusted-codex")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedProviderRuntime(
        "codex", source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    try:
        authority = evidence.ProviderLaunchAuthority(
            "codex", runtime,
            evidence.AgyCanaryNamespace(tmp_path, tmp_path, root, "example.invalid", provider_output=output),
            (),
        )
        command = authority.command(["codex", "exec", "review"])
        assert "/run/phase-loop-bin/codex" in command
        (output / "result.json").write_bytes(b"accepted")
        assert authority.read_expected_output("result.json") == b"accepted"
        (output / "extra.log").write_bytes(b"forged")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="output set"):
            authority.read_expected_output("result.json")
        (output / "extra.log").unlink()
        source.write_bytes(b"replaced")
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted"):
            authority.command(["codex", "exec", "review"])
    finally:
        shutil.rmtree(output)
        shutil.rmtree(root)


def test_provider_launch_authority_rejects_legacy_prepare_without_immutable_authority(tmp_path):
    root = _private_root(tmp_path)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    home = None
    try:
        ledger = evidence.create_capture(
            capture=capture, settings_path=_settings(tmp_path, []), seat_key="gemini-primary",
            source_inventory=_source_inventory(tmp_path),
        )
        home, _binds = evidence.build_minimal_home(
            evidence_root=root, settings_path=_settings(tmp_path, [])
        )
        ledger.update({"minimal_home": str(home), "auth_binds": []})
        evidence._write_replace_at(capture.root_fd, "agy-launch-ledger.json", ledger)
        stage = tmp_path / "legacy-stage"
        stage.mkdir()
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="invalid private evidence record"):
            evidence.prepare_provider_launch_authorities(
                capture=capture, stage=stage, providers=("gemini",)
            )
    finally:
        capture.close()
        if home is not None:
            shutil.rmtree(home)
        shutil.rmtree(root)


def test_advisor_board_cli_seals_and_verifies_capture_summary(monkeypatch, tmp_path):
    """The public command, not its sink helper, must bind the private payload."""
    from phase_loop_runtime.advisor_board.schema import Board, Seat
    from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult
    from phase_loop_runtime.advisor_board import composition
    from phase_loop_runtime import panel_invoker

    root = _private_root(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    contents = {"review-instructions.md": "instructions", "review-bundle.md": "bundle"}
    for name, value in contents.items():
        path = stage / name
        path.write_text(value)
        path.chmod(0o600)
    settings = _settings(tmp_path, [])
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    try:
        evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary", source_inventory=_source_inventory(tmp_path))
        staged = evidence.retain_staged_files(capture=capture, review_dir=stage)
        events = [
            {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
            {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": contents["review-instructions.md"]},
            {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
            {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": contents["review-bundle.md"]},
            {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
        ]
        evidence.record_launch(capture=capture, seat_key="gemini-primary", attempt_id="gemini-1", argv=["agy", "-p", "secret"], returncode=0, stdout="\n".join(json.dumps(item) for item in events), stderr="", staged=staged)
        expected = evidence.capture_summary(capture)
    finally:
        capture.close()
    board = Board("synthetic", "test", (
        Seat("gemini-3.6-flash", "high", harness="gemini"), Seat("gpt-5.6-sol", "high", harness="codex"), Seat("grok-4.5", "high", harness="grok"),
    ))
    result = PanelResult(tuple(PanelLegResult(leg=seat.harness or "x", seat_key="gemini-primary" if seat.harness == "gemini" else seat.harness, status="OK", text="AGREE") for seat in board.seats))
    object.__setattr__(result, "_agy_canary_capture", expected)
    monkeypatch.setattr(composition, "compose_review_board", lambda: board)
    monkeypatch.setattr(panel_invoker, "invoke_board", lambda *_args, **_kwargs: result)
    artifact = tmp_path / "review.md"
    artifact.write_text("review")
    monkeypatch.setenv("PHASE_LOOP_AGY_CANARY_EVIDENCE_DIR", str(root))
    args = argparse.Namespace(artifact=str(artifact), json=True, agy_canary_private_board_name="board.json")
    assert cli._advisor_board_command(args=args) == 0
    ledger = json.loads((root / "agy-launch-ledger.json").read_text())
    board_bytes = (root / "board.json").read_bytes()
    assert ledger["private_board"]["sha256"] == evidence._sha256(board_bytes)
    assert json.loads(board_bytes)["agy_canary_capture"] == ledger["private_board"]["capture"]
    assert evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary", seal=False)["attempt_ids"] == ["gemini-1"]
    retained = root / "staged-review-instructions.md"
    retained.write_text("forged")
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="retained input bytes drifted"):
        evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary", seal=False)
    retained.write_text(contents["review-instructions.md"])
    (root / "board.json").write_text("{}")
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="drifted"):
        evidence.verify_capture(evidence_root=root, expected_seat_key="gemini-primary", seal=False)
    shutil.rmtree(root)


def test_advisor_board_cli_real_invoker_capture_path(monkeypatch, tmp_path):
    from phase_loop_runtime.advisor_board.schema import Board, Seat
    from phase_loop_runtime.advisor_board import composition
    from phase_loop_runtime import panel_invoker
    root = _private_root(tmp_path)
    home = tmp_path / "minimal-home"; home.mkdir(mode=0o700)
    (home / ".gemini" / "antigravity-cli").mkdir(parents=True, mode=0o700)
    settings = home / ".gemini" / "antigravity-cli" / "settings.json"
    settings.write_bytes(_settings(tmp_path, []).read_bytes())
    settings.chmod(0o600)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    try:
        ledger = evidence.create_capture(capture=capture, settings_path=_settings(tmp_path, []), seat_key="gemini:gemini-3.6-flash:high", source_inventory=_source_inventory(tmp_path))
        ledger.update({"minimal_home": str(home), "auth_binds": []})
        evidence._write_replace_at(capture.root_fd, "agy-launch-ledger.json", ledger)
        evidence._exclusive_write_at(capture.root_fd, "agy_canary_prepare.json", evidence._canonical_json({"schema": "agy_canary_prepare.v1", "seat_key": ledger["seat_key"], "ledger_sha256": evidence._sha256(evidence._canonical_json(ledger))}), 0o600)
    finally:
        capture.close()
    source = tmp_path / "agy"; source.write_bytes(b"agy"); source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), evidence._sha256(source.read_bytes()))
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)
    provider_runtime = evidence._TrustedProviderRuntime(
        "gemini", source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
        evidence._sha256(source.read_bytes()),
    )
    monkeypatch.setattr(evidence, "_trusted_provider_runtime", lambda provider: provider_runtime)
    self_tests = []
    monkeypatch.setattr(
        evidence,
        "namespace_self_test",
        lambda **kwargs: self_tests.append(kwargs["namespace"]) or {"synthetic": True},
    )
    monkeypatch.setattr(composition, "compose_review_board", lambda: Board("one", "review", (Seat("gemini-3.6-flash", "high", harness="gemini"),)))
    seen = []
    def fake_liveness(command, *, cwd, **_kwargs):
        seen.append(command)
        review = Path(cwd)
        events = []
        for index, name in enumerate(("review-instructions.md", "review-bundle.md")):
            events += [{"sequence": index * 2, "session_id": "s", "type": "tool_call", "call_id": str(index), "tool": "read_file", "target": f"/run/phase-loop-review/{name}"}, {"sequence": index * 2 + 1, "session_id": "s", "type": "tool_result", "call_id": str(index), "outcome": "success", "content": (review / name).read_text()}]
        events.append({"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"})
        return panel_invoker._LegRun(0, "\n".join(json.dumps(item) for item in events), "")
    monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", fake_liveness)
    artifact = tmp_path / "artifact.md"; artifact.write_text("review")
    monkeypatch.setenv("PHASE_LOOP_AGY_CANARY_EVIDENCE_DIR", str(root))
    assert cli._advisor_board_command(args=argparse.Namespace(artifact=str(artifact), json=True, agy_canary_private_board_name="real.json")) == 1
    ledger = json.loads((root / "agy-launch-ledger.json").read_text())
    assert len(ledger["attempts"]) == 1 and self_tests and seen[0][0] == "/usr/bin/bwrap" and "--clearenv" in seen[0] and "/run/phase-loop-bin/agy" in seen[0]
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="usable independence floor"):
        evidence.verify_capture(evidence_root=root, expected_seat_key="gemini:gemini-3.6-flash:high", seal=False)
    shutil.rmtree(root)


def test_bootstrap_environment_never_uses_attacker_path_or_home(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/tmp/fake-bin:/usr/bin")
    account_home = evidence._account_home()
    monkeypatch.setenv("HOME", str(account_home))
    environment = evidence._bootstrap_environment(nonce="n", uv_executable=Path("/trusted/uv"), account_home=account_home)
    assert environment["PATH"].startswith("/trusted:")
    assert "/tmp/fake-bin" not in environment["PATH"]
    assert evidence._canonical_bash() != Path("/tmp/fake-bin/bash")
    assert evidence._canonical_uv() != Path("/tmp/fake-bin/uv")
    fake_home = tmp_path / "attacker-home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    (fake_home / ".local" / "bin" / "uv").write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("HOME", str(fake_home))
    assert evidence._canonical_uv() != fake_home / ".local" / "bin" / "uv"
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="HOME drift"):
        evidence._bootstrap_environment(nonce="n", uv_executable=Path("/trusted/uv"), account_home=account_home)


def test_release_lineage_uses_merged_handoff_and_rehashes_downloads(tmp_path, monkeypatch):
    repo = tmp_path / "agent-harness"
    (repo / "docs" / "releases").mkdir(parents=True)
    handoff = repo / "docs" / "releases" / "outside-agent-release-handoff.md"
    handoff.write_text("pending\n")
    _git_repo(repo)
    release_commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(repo), "tag", "-am", "release", "v0.7.14", release_commit], check=True)
    tag_object = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "refs/tags/v0.7.14"], text=True).strip()
    wheel, sdist = b"synthetic wheel", b"synthetic sdist"
    rows = [
        {"filename": "phase_loop_runtime-0.7.14-py3-none-any.whl", "packagetype": "bdist_wheel", "url": "https://example.invalid/wheel", "digests": {"sha256": hashlib.sha256(wheel).hexdigest()}},
        {"filename": "phase_loop_runtime-0.7.14.tar.gz", "packagetype": "sdist", "url": "https://example.invalid/sdist", "digests": {"sha256": hashlib.sha256(sdist).hexdigest()}},
    ]
    record = {
        "schema": "release_evidence.v1", "version": "0.7.14", "release_commit": release_commit,
        "tag_object": tag_object, "tag_peel": release_commit,
        "release_url": "https://example.invalid/release", "workflow_url": "https://example.invalid/workflow",
        "pypi_metadata_url": "https://pypi.org/pypi/phase-loop-runtime/0.7.14/json",
        "artifacts": [{key: row[key] for key in ("filename", "packagetype", "url")} | {"sha256": row["digests"]["sha256"]} for row in rows],
    }
    handoff.write_bytes(b"<!-- release_evidence.v1:start -->" + evidence._canonical_json(record) + b"<!-- release_evidence.v1:end -->")
    subprocess.run(["git", "-C", str(repo), "add", "docs/releases/outside-agent-release-handoff.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "handoff"], check=True)
    handoff_commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", handoff_commit], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/Consiliency/agent-harness.git"], check=True)
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/phase-loop/canonical-main", handoff_commit], check=True)
    real_run = evidence.subprocess.run

    def fake_run(argv, **kwargs):
        if argv[:3] == ["git", "-C", str(repo)] and argv[3:5] == ["fetch", "--quiet"]:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if argv[:3] == ["git", "-C", str(repo)] and argv[3:5] == ["verify-tag", "--raw"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:3] == ["gh", "release", "view"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"tagName": "v0.7.14", "url": record["release_url"]}), "")
        if argv[:3] == ["gh", "run", "list"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"headSha": release_commit, "conclusion": "success", "event": "push", "url": record["workflow_url"]}]), "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(evidence.subprocess, "run", fake_run)
    blobs = {row["url"]: wheel if row["url"].endswith("wheel") else sdist for row in rows}
    result = evidence._reconcile_release_lineage(
        repo=repo, handoff_commit=handoff_commit,
        fetch_json=lambda _url: {"urls": rows}, download=lambda url: blobs[url],
    )
    assert result["release_commit"] == release_commit
    with pytest.raises(evidence.AgyCanaryEvidenceError, match="downloaded release artifact digest mismatch"):
        evidence._reconcile_release_lineage(
            repo=repo, handoff_commit=handoff_commit,
            fetch_json=lambda _url: {"urls": rows}, download=lambda _url: b"forged",
        )


@pytest.mark.parametrize("mutate", [
    lambda record: record | {"extra": True},
    lambda record: {key: value for key, value in record.items() if key != "workflow_url"},
    lambda record: record | {"artifacts": record["artifacts"] * 2},
])
def test_release_handoff_parser_rejects_noncanonical_schema_and_duplicate_artifacts(mutate):
    record = {
        "schema": "release_evidence.v1", "version": "0.7.14", "release_commit": "a" * 40,
        "tag_object": "b" * 40, "tag_peel": "a" * 40,
        "release_url": "https://example.invalid/release", "workflow_url": "https://example.invalid/workflow",
        "pypi_metadata_url": "https://pypi.org/pypi/phase-loop-runtime/0.7.14/json",
        "artifacts": [{"filename": "x.whl", "packagetype": "bdist_wheel", "url": "https://example.invalid/x", "sha256": "c" * 64}],
    }
    bad = mutate(record)
    with pytest.raises(evidence.AgyCanaryEvidenceError):
        evidence._release_handoff_record(b"<!-- release_evidence.v1:start -->" + evidence._canonical_json(bad) + b"<!-- release_evidence.v1:end -->")
