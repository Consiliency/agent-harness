"""#36 — input-scaled leg timeout + argv assertions for ``panel_invoker._exec_leg``.

The previously-fixed 600s timeout silently timed out large-artifact frontier reviews,
degrading the panel to fewer legs (the failure that stayed hidden through the cross-repo
work because every test stubs the spawn boundary and none asserted the command / timeout).
These tests pin the input-scaling and the exact command construction (read-only sandbox +
``--output-last-message`` for codex; ``--add-dir`` + scaled ``--print-timeout`` for gemini).
"""

from __future__ import annotations

import json
import os
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_canary_evidence as evidence
from phase_loop_runtime import panel_invoker as pi


def _mock_canonical_bwrap(monkeypatch) -> None:
    monkeypatch.setattr(evidence, "_canonical_bwrap", lambda: Path("/usr/bin/bwrap"))


def _cleanup_tombstone_for(authority) -> Path:
    matches = []
    for path in Path("/tmp").glob(
        f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}*"
    ):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) == (authority.device, authority.inode):
            matches.append(path)
    assert len(matches) == 1
    return matches[0]


def _cleanup_descendant_tombstones_for(authority) -> list[Path]:
    return sorted(Path("/tmp").glob(
        f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}entry-"
        f"{authority.quarantine_token}-*"
    ))


def test_leg_timeout_scales_with_review_size():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # empty → base floor
        assert pi._leg_timeout_for(d) == pi._LEG_TIMEOUT_BASE_S
        # ~50 KB artifact → base + 50 * per-KB (below the cap), clearing codex-xhigh ~900s
        (d / "big.txt").write_text("x" * (50 * 1024))
        scaled = pi._leg_timeout_for(d)
        assert scaled == pi._LEG_TIMEOUT_BASE_S + 50 * pi._LEG_TIMEOUT_PER_KB_S
        assert scaled > pi._LEG_TIMEOUT_BASE_S
        assert scaled >= 900


def test_leg_timeout_is_capped():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "huge.txt").write_text("x" * (4 * 1024 * 1024))  # 4 MB → well over cap
        assert pi._leg_timeout_for(d) == pi._LEG_TIMEOUT_MAX_S


def _capture_run(monkeypatch, stdout: str = ""):
    """Capture the leg's ``_run_leg_with_liveness`` call.

    The leg exec no longer calls ``subprocess.run`` — it goes through the stall-aware
    ``_run_leg_with_liveness`` seam. We capture the ``cmd`` plus the ``deadline_s`` /
    ``stall_threshold_s`` / ``input_text`` kwargs. The codex auth preflight still uses
    ``subprocess.run``, so bypass it (fail-open logged-in) to reach the leg exec.
    """
    captured: dict = {}

    def fake_liveness(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["deadline_s"] = kwargs.get("deadline_s")
        captured["stall_threshold_s"] = kwargs.get("stall_threshold_s")
        captured["input_text"] = kwargs.get("input_text")
        return pi._LegRun(0, stdout, "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    return captured


def test_codex_leg_argv_is_read_only_with_output_last_message(monkeypatch):
    captured = _capture_run(monkeypatch)
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        pi._exec_leg("codex", Path(rd), Path(od))
    cmd = captured["cmd"]
    assert cmd[:2] == ["codex", "exec"]
    assert "--sandbox" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--output-last-message" in cmd
    # never the executor default that build_codex_command emits
    assert "danger-full-access" not in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    # Leg-liveness: the hard-kill is DECOUPLED from the input-scaled timeout and raised
    # to the _MAX_LEG_TIMEOUT_S backstop (a slow-but-streaming leg is no longer killed
    # at the 600s floor); stall detection uses the seam's _LEG_STALL_THRESHOLD_S default
    # (never overridden by the leg, so it is absent from the call kwargs).
    assert captured["deadline_s"] == pi._MAX_LEG_TIMEOUT_S
    assert captured["stall_threshold_s"] is None


def test_grok_leg_argv_is_headless_plain_with_reasoning_effort(monkeypatch):
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        rdp = Path(rd)
        pi._exec_leg("grok", rdp, Path(od))  # effort-absent → grok's max reasoning
    cmd = captured["cmd"]
    assert cmd[0] == "grok"
    assert "-p" in cmd  # single-turn headless prompt
    # plain headless output (stdout IS the review; no --output-last-message file)
    assert cmd[cmd.index("--output-format") + 1] == "plain"
    # runs the grok-4.5 default model at grok's MAX reasoning. The effort-absent default
    # renders through the SAME map as an explicit seat effort (ah#222): canonical ``max``
    # CLAMPS to grok's ``high`` ceiling (grok has no ``max``/``xhigh``), so the token the
    # CLI receives is a valid ``high`` — NOT the literal ``max`` that the grok CLI rejects
    # ("unknown effort level 'max'"), which used to ERROR the grok leg on every default run.
    assert cmd[cmd.index("-m") + 1] == "grok-4.5"
    assert cmd[cmd.index("--reasoning-effort") + 1] == "high"
    # regression guard: the invalid literal must never reach the CLI on the default path.
    assert "max" not in cmd
    # HARD READ-ONLY (GROKEXEC, agent-harness#147): headless `grok -p` auto-approves
    # writes, so the panel/CR reviewer leg is constrained by a `--tools` ALLOW-LIST of
    # read/search built-ins only. Assert EXACT equality with the shared allow-list —
    # because `--tools` is an allow-list, anything not named is excluded, so equality
    # is the airtight guard a regression cannot silently defeat.
    tools_value = cmd[cmd.index("--tools") + 1]
    assert tools_value == pi.GROK_REVIEW_READONLY_TOOLS == "read_file,grep,list_dir,search_tool"
    # Belt-and-suspenders: no write / privileged tool can appear in the allow-list.
    for forbidden in ("write", "search_replace", "run_terminal_command", "scheduler", "spawn_subagent", "memory", "image"):
        assert forbidden not in tools_value.split(","), f"{forbidden!r} must not be a grok reviewer tool"
    # The allow-list (not `--disable-web-search`) is the read-only lever, so that flag
    # is intentionally left off; assert it is not what enforces read-only here.
    assert "--disable-web-search" not in cmd
    # grok is a SLOW leg: the hard-kill is the raised _MAX_LEG_TIMEOUT_S backstop (no
    # longer a short input-scaled wall-clock); liveness rides the 180s stall default.
    assert captured["deadline_s"] == pi._MAX_LEG_TIMEOUT_S
    assert captured["stall_threshold_s"] is None


def test_grok_leg_renders_seat_effort_through_the_map(monkeypatch):
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        # a board seat's canonical effort reaches the CLI as --reasoning-effort <token>.
        pi._exec_leg("grok", Path(rd), Path(od), effort="high", model="grok-4.5")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--reasoning-effort") + 1] == "high"


def test_gemini_leg_argv_uses_add_dir_and_scaled_print_timeout(monkeypatch):
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        rdp = Path(rd)
        (rdp / "artifact.py").write_text("x" * (30 * 1024))
        pi._exec_leg("gemini", rdp, Path(od))
        expected_timeout = pi._leg_timeout_for(rdp)
    cmd = captured["cmd"]
    assert cmd[0] == "agy"
    assert "--add-dir" in cmd
    assert "--print-timeout" in cmd
    # --print-timeout is still the input-scaled timeout_s (agy's own internal budget)
    assert cmd[cmd.index("--print-timeout") + 1] == f"{expected_timeout}s"
    # ...but the process hard-kill is the raised _MAX_LEG_TIMEOUT_S backstop, decoupled
    # from that scaled value; liveness rides the 180s stall default (not overridden).
    assert captured["deadline_s"] == pi._MAX_LEG_TIMEOUT_S
    assert captured["stall_threshold_s"] is None


def test_gemini_leg_passes_headless_permission_flag(monkeypatch):
    """ah#525: without ``--dangerously-skip-permissions`` this leg cannot review at all.

    agy's permission check has no headless approver, so the FIRST tool call the model
    makes is auto-denied (``permission check failed for command ...: user denied
    permission``) and the run dies in 8-13s with an empty body. Measured directly:
    identical staged bundle, flag absent -> denial; flag present -> a full review.

    Without it the leg cannot review at all: agy's permission check has no headless
    approver, the first tool call is auto-denied, and the run dies in 8-13s empty --
    which is why this seat delivered zero usable reviews across four boards.

    THIS TEST ASSERTS ARGV, NOT A SECURITY PROPERTY. An earlier docstring here
    concluded that the staged `--add-dir` made the repository unreachable. That was
    false: the flag auto-approves every tool permission (shell, network, spawn), and
    `--add-dir` selects workspace context, not containment -- verified against live
    agy, where shell ran and a file was written outside `--add-dir`.

    Running unconfined is a standing operator decision for this fleet (executors
    already run --yolo, and the repo takes no third-party submissions), so this leg
    matches the existing posture rather than introducing a new exposure. Confinement
    is wanted eventually and tracked on ah#525.

    Nothing here exercises real agy, so a green run is scope-green, not property-green.
    Do not read the flag's presence as evidence about isolation in either direction.

    Mutation that must kill this: drop the flag from the gemini cmd.
    """
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        rdp = Path(rd)
        (rdp / "artifact.py").write_text("some code to review")
        pi._exec_leg("gemini", rdp, Path(od), artifact="REVIEW THIS", mode="review")
    cmd = captured["cmd"]
    assert cmd[0] == "agy"
    assert "--dangerously-skip-permissions" in cmd, (
        "the gemini leg cannot complete a headless review without this flag; every "
        "tool call is auto-denied and the leg returns EMPTY/ERROR (ah#525)"
    )
    # The workspace agy is granted must remain the STAGED dir, never a repo path. This
    # is worth pinning on its own merits -- but it is NOT containment: it bounds where
    # the leg is pointed, not what an auto-approved tool call can reach.
    assert cmd[cmd.index("--add-dir") + 1] == str(rdp)


def test_gemini_leg_passes_prompt_inline_on_argv_not_stdin(monkeypatch):
    """Regression: ``agy -p -`` IGNORES stdin and runs an EMPTY prompt (it prints its
    "How can I help you today?" greeting), so the gemini leg silently returned a
    non-review on every run. The prompt MUST be the inline ``-p`` argv value, and the
    leg MUST NOT feed stdin. Mirrors the grok leg's inline-prompt convention."""
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        rdp = Path(rd)
        (rdp / "artifact.py").write_text("some code to review")
        pi._exec_leg("gemini", rdp, Path(od), artifact="REVIEW THIS ARTIFACT", mode="review")
    cmd = captured["cmd"]
    # the arg right after -p is the composed leg prompt (the staged-bundle pointer),
    # never the stdin sentinel "-" that made agy run an empty prompt.
    prompt_arg = cmd[cmd.index("-p") + 1]
    assert prompt_arg != "-"
    assert "review-bundle.md" in prompt_arg  # the real staged-bundle pointer prompt
    # and nothing is fed on stdin (feeding stdin was the empty-prompt bug): the gemini
    # leg passes NO input_text to the liveness seam, which then wires the child to DEVNULL.
    assert captured["input_text"] is None


def test_capture_enabled_gemini_translates_host_stage_in_prompt_and_argv(monkeypatch, tmp_path):
    """The production command exposes the host stage only as bwrap's bind source."""
    _mock_canonical_bwrap(monkeypatch)
    source = tmp_path / "trusted-agy"
    source.write_bytes(b"trusted-agy")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedAgyRuntime(
        source, info.st_dev, info.st_ino, info.st_mode & 0o7777,
        evidence._sha256(source.read_bytes()),
    )
    monkeypatch.setattr(evidence, "_trusted_agy_runtime", lambda: runtime)
    root = Path("/tmp") / f"phase-loop-agy-panel-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    try:
        review_dir = tmp_path / "host-stage"
        review_dir.mkdir()
        instructions = review_dir / "review-instructions.md"
        bundle = review_dir / "review-bundle.md"
        instructions.write_text("read instructions\n")
        bundle.write_text("read bundle\n")
        instructions.chmod(0o600)
        bundle.chmod(0o600)
        staged = {
            "review-bundle.md": {"retained": "staged-review-bundle.md", "bytes": 12, "sha256": "0" * 64},
            "review-instructions.md": {"retained": "staged-review-instructions.md", "bytes": 18, "sha256": "0" * 64},
        }
        home = tmp_path / "minimal-home"
        home.mkdir(mode=0o700)
        namespace = evidence.AgyCanaryNamespace(
            stage=review_dir,
            minimal_home=home,
            evidence_root=root,
            provider_hostname="example.invalid",
        )
        captured: dict[str, object] = {}
        stream = "\n".join(json.dumps(event) for event in [
            {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
            {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "read instructions\n"},
            {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
            {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "read bundle\n"},
            {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
        ])

        def fake_liveness(cmd, **_kwargs):
            captured["cmd"] = list(cmd)
            return pi._LegRun(0, stream, "")

        monkeypatch.setattr(pi, "_leg_auth_ok", lambda *args, **kwargs: (True, ""))
        monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
        monkeypatch.setattr(pi, "record_launch", lambda **_kwargs: None)
        out_dir = tmp_path / "out"
        out_dir.mkdir(mode=0o700)
        class TestAuthority:
            def __init__(self):
                self.preflights: list[list[str]] = []
                self.self_tests: list[list[str]] = []
                self.output_reads: list[str] = []
                self.output_writes: list[str] = []
                self.auth_proofs = 0

            def preflight(self, argv):
                self.preflights.append(list(argv))
                self.self_tests.append(list(argv))
                return namespace.agy_command(list(argv))

            def outer_environment(self):
                return namespace.outer_environment()

            def rewrite_provider_output_path(self, path):
                return namespace.rewrite_provider_output_path(path)

            def read_expected_output(self, name):
                self.output_reads.append(name)
                return (out_dir / name).read_bytes()

            def write_expected_output(self, name, data):
                self.output_writes.append(name)
                (out_dir / name).write_bytes(data)
                return self.read_expected_output(name)

            def projected_auth_proof(self):
                self.auth_proofs += 1
                return {"schema": "projected_auth.v1", "provider": "gemini", "records": []}

        authority = TestAuthority()
        rc, review, _log = pi._exec_leg(
            "gemini", review_dir, out_dir, artifact="artifact",
            agy_capture=capture, capture_staged=staged, seat_key="gemini-primary",
            provider_authority=authority,
        )
        command = captured["cmd"]
        assert rc == 0 and review == "AGREE"
        assert isinstance(command, list)
        assert command[0] == "/usr/bin/bwrap"
        add_dir = command.index("--add-dir")
        assert command[add_dir + 1] == "/run/phase-loop-review"
        prompt = command[-1]
        assert "/run/phase-loop-review" in prompt
        assert str(review_dir) not in prompt
        # The host path is present exactly once: bwrap's explicit source side.
        assert command.count(str(review_dir)) == 1
        bind = next(
            index for index, token in enumerate(command)
            if token == "--ro-bind" and command[index + 1] == str(review_dir)
        )
        assert command[bind + 1] == str(review_dir)
        assert command[bind + 2] == "/run/phase-loop-review"
        assert authority.preflights and authority.self_tests
        assert authority.preflights[0][0] == "agy"
        assert authority.output_reads == ["panel-gemini.txt"]
        assert authority.output_writes == ["panel-gemini.txt"]
        assert authority.auth_proofs == 1
    finally:
        capture.close()
        shutil.rmtree(root)


def test_capture_retry_revalidates_sealed_runtime_before_each_attempt(monkeypatch, tmp_path):
    """A transient Gemini retry must not launch a runtime replaced after attempt one."""
    root = Path("/tmp") / f"phase-loop-retry-root-{os.getpid()}-{tmp_path.name}"
    output = Path("/tmp") / f"phase-loop-retry-output-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    source = tmp_path / "agy"
    source.write_bytes(b"sealed-agy")
    source.chmod(0o700)
    info = source.stat()
    runtime = evidence._TrustedProviderRuntime(
        "gemini", source, info.st_dev, info.st_ino, info.st_mode & 0o7777,
        evidence._sha256(source.read_bytes()),
    )
    review_dir = tmp_path / "review"
    home = tmp_path / "home"
    review_dir.mkdir()
    home.mkdir(mode=0o700)
    customization_sources = {
        "inventory": evidence.freeze_customization_inventory(
            home=home, project_dir=review_dir, env={},
        ),
        "home": str(home.resolve(strict=True)),
        "project": str(review_dir.resolve(strict=True)),
    }
    minimal_customizations = evidence.freeze_customization_inventory(
        home=home, project_dir=review_dir, env={},
    )

    def authority_for(runtime):
        return evidence.ProviderLaunchAuthority(
            provider="gemini", runtime=runtime,
            namespace=evidence.AgyCanaryNamespace(
                review_dir, home, root, "example.invalid", provider_output=output
            ),
            auth_records=(),
            auth_records_sha256=evidence._sha256(evidence._canonical_json(())),
            customization_sources=customization_sources,
            customization_sources_sha256=evidence._sha256(
                evidence._canonical_json(customization_sources)
            ),
            minimal_customizations=minimal_customizations,
            minimal_customizations_sha256=evidence._sha256(
                evidence._canonical_json(minimal_customizations)
            ),
            auth_placeholders=(),
            auth_placeholders_sha256=evidence._sha256(
                evidence._canonical_json(())
            ),
        )

    def fake_preflight(self, argv):
        command = list(argv)
        launch = evidence._provider_launch_identity(
            command, provider=self.provider,
        )
        object.__setattr__(self, "review_launch", launch)
        return command

    monkeypatch.setattr(evidence.ProviderLaunchAuthority, "preflight", fake_preflight)
    monkeypatch.setattr(pi, "record_launch", lambda **_kwargs: None)
    try:
        authority = authority_for(runtime)
        launched = 0
        transient_stream = (
            '{"sequence": 0, "session_id": "s", "type": "terminal", "text": "retry"}'
        )

        def mutate_after_first_attempt(_command, **_kwargs):
            nonlocal launched
            launched += 1
            source.write_bytes(b"replaced-agy")
            return pi._LegRun(0, transient_stream, "timeout waiting for response")

        monkeypatch.setattr(pi, "_run_leg_with_liveness", mutate_after_first_attempt)
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="executable drifted"):
            pi._exec_leg(
                "gemini", review_dir, output, artifact="artifact",
                agy_capture=capture, capture_staged={}, seat_key="gemini-primary",
                provider_authority=authority,
            )
        assert launched == 1

        source.write_bytes(b"sealed-agy-again")
        info = source.stat()
        clean_runtime = evidence._TrustedProviderRuntime(
            "gemini", source, info.st_dev, info.st_ino, info.st_mode & 0o7777,
            evidence._sha256(source.read_bytes()),
        )
        attempts = 0

        def transient_then_success(_command, **_kwargs):
            nonlocal attempts
            attempts += 1
            return pi._LegRun(
                0,
                transient_stream if attempts == 1 else '{"sequence": 0, "session_id": "s", "type": "terminal", "text": "AGREE"}',
                "timeout waiting for response" if attempts == 1 else "",
        )

        monkeypatch.setattr(pi, "_run_leg_with_liveness", transient_then_success)
        clean_authority = authority_for(clean_runtime)
        rc, review, _log = pi._exec_leg(
            "gemini", review_dir, output, artifact="artifact",
            agy_capture=capture, capture_staged={}, seat_key="gemini-primary",
            provider_authority=clean_authority,
        )
        assert (rc, review, attempts) == (0, "AGREE", 2)
        assert len(clean_authority.review_attempts) == 2
    finally:
        capture.close()
        shutil.rmtree(root)
        shutil.rmtree(output)


@pytest.mark.parametrize(
    ("provider", "mutation", "message"),
    [
        ("codex", "support", "package drifted"),
        ("grok", "source", "executable drifted"),
        ("grok", "node", "node runtime drifted"),
    ],
)
def test_capture_retry_full_hashes_support_launcher_and_node_assets(
    monkeypatch, tmp_path, provider, mutation, message,
):
    root = Path("/tmp") / f"phase-loop-asset-root-{os.getpid()}-{tmp_path.name}"
    output = Path("/tmp") / f"phase-loop-asset-output-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    review_dir = tmp_path / "review"
    home = tmp_path / "home"
    review_dir.mkdir()
    home.mkdir(mode=0o700)

    support = None
    node = None
    launcher = None
    if mutation == "support":
        support = tmp_path / "provider-support"
        source = support / "bin" / "codex"
        asset = support / "asset.dat"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"sealed-entry")
        source.chmod(0o700)
        asset.write_bytes(b"sealed-asset")
        mutation_target = asset
    else:
        source = tmp_path / "grok-target"
        source.write_bytes(b"sealed-entry")
        source.chmod(0o700)
        node = tmp_path / "node"
        node.write_bytes(b"sealed-node")
        node.chmod(0o700)
        launcher = tmp_path / "grok"
        launcher.symlink_to(source.name)
        mutation_target = source if mutation == "source" else node

    source_info = source.stat()
    support_info = support.stat() if support is not None else None
    node_info = node.stat() if node is not None else None
    runtime = evidence._TrustedProviderRuntime(
        provider=provider,
        source=source,
        device=source_info.st_dev,
        inode=source_info.st_ino,
        mode=source_info.st_mode & 0o7777,
        sha256=evidence._sha256(source.read_bytes()),
        support_source=support,
        support_device=support_info.st_dev if support_info is not None else None,
        support_inode=support_info.st_ino if support_info is not None else None,
        support_mode=(support_info.st_mode & 0o7777) if support_info is not None else None,
        support_sha256=(
            evidence._runtime_tree_sha256(support) if support is not None else None
        ),
        entry_relative="bin/codex" if support is not None else "",
        node_source=node,
        node_device=node_info.st_dev if node_info is not None else None,
        node_inode=node_info.st_ino if node_info is not None else None,
        node_mode=(node_info.st_mode & 0o7777) if node_info is not None else None,
        node_sha256=evidence._sha256(node.read_bytes()) if node is not None else None,
        launcher=launcher,
        launcher_target=source.name if launcher is not None else None,
    )
    customization_sources = {
        "inventory": evidence.freeze_customization_inventory(
            home=home, project_dir=review_dir, env={},
        ),
        "home": str(home.resolve(strict=True)),
        "project": str(review_dir.resolve(strict=True)),
    }
    minimal_customizations = evidence.freeze_customization_inventory(
        home=home, project_dir=review_dir, env={},
    )
    authority = evidence.ProviderLaunchAuthority(
        provider=provider,
        runtime=runtime,
        namespace=evidence.AgyCanaryNamespace(
            review_dir, home, root, "example.invalid", provider_output=output,
        ),
        auth_records=(),
        auth_records_sha256=evidence._sha256(evidence._canonical_json(())),
        customization_sources=customization_sources,
        customization_sources_sha256=evidence._sha256(
            evidence._canonical_json(customization_sources)
        ),
        minimal_customizations=minimal_customizations,
        minimal_customizations_sha256=evidence._sha256(
            evidence._canonical_json(minimal_customizations)
        ),
        auth_placeholders=(),
        auth_placeholders_sha256=evidence._sha256(evidence._canonical_json(())),
    )

    def fake_preflight(self, argv):
        command = list(argv)
        object.__setattr__(
            self, "review_launch",
            evidence._provider_launch_identity(command, provider=self.provider),
        )
        return command

    launched = 0
    original_inode = mutation_target.stat().st_ino
    original_bytes = mutation_target.read_bytes()

    def mutate_after_first_attempt(_command, **_kwargs):
        nonlocal launched
        launched += 1
        mutation_target.write_bytes(b"same-inode-mutation")
        assert mutation_target.stat().st_ino == original_inode
        return pi._LegRun(0, "", "timeout waiting for response")

    monkeypatch.setattr(evidence.ProviderLaunchAuthority, "preflight", fake_preflight)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", mutate_after_first_attempt)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError, match=message):
            pi._exec_leg(
                provider, review_dir, output, artifact="artifact",
                agy_capture=capture, provider_authority=authority,
            )
        assert launched == 1
        assert len(authority.review_attempts) == 1
        mutation_target.write_bytes(original_bytes)
        clean_authority = evidence.ProviderLaunchAuthority(
            provider=provider,
            runtime=runtime,
            namespace=authority.namespace,
            auth_records=authority.auth_records,
            auth_records_sha256=authority.auth_records_sha256,
            customization_sources=authority.customization_sources,
            customization_sources_sha256=authority.customization_sources_sha256,
            minimal_customizations=authority.minimal_customizations,
            minimal_customizations_sha256=authority.minimal_customizations_sha256,
            auth_placeholders=authority.auth_placeholders,
            auth_placeholders_sha256=authority.auth_placeholders_sha256,
        )
        clean_attempts = 0

        def transient_then_success(_command, **_kwargs):
            nonlocal clean_attempts
            clean_attempts += 1
            if provider == "codex" and clean_attempts == 2:
                (output / "panel-codex.txt").write_text("AGREE")
            return pi._LegRun(
                0, "AGREE" if provider == "grok" and clean_attempts == 2 else "",
                "timeout waiting for response" if clean_attempts == 1 else "",
            )

        monkeypatch.setattr(
            pi, "_run_leg_with_liveness", transient_then_success,
        )
        rc, review, _log = pi._exec_leg(
            provider, review_dir, output, artifact="artifact",
            agy_capture=capture, provider_authority=clean_authority,
        )
        assert (rc, review, clean_attempts) == (0, "AGREE", 2)
        assert len(clean_authority.review_attempts) == 2
    finally:
        capture.close()
        shutil.rmtree(root)
        shutil.rmtree(output)


def _sibling_namespace(tmp_path: Path):
    """Build a real bwrap namespace without preparing a Gemini ledger entry."""
    root = Path("/tmp") / f"phase-loop-sibling-root-{os.getpid()}-{tmp_path.name}"
    output = Path("/tmp") / f"phase-loop-sibling-output-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    stage = tmp_path / "host-stage"
    home = tmp_path / "minimal-home"
    stage.mkdir()
    home.mkdir(mode=0o700)
    namespace = evidence.AgyCanaryNamespace(
        stage=stage,
        minimal_home=home,
        evidence_root=root,
        provider_hostname="example.invalid",
        provider_output=output,
    )
    class TestAuthority:
        def __init__(self):
            self.namespace = namespace
            self.preflights: list[list[str]] = []
            self.self_tests: list[list[str]] = []
            self.output_reads: list[str] = []
            self.output_writes: list[str] = []
            self.auth_proofs = 0

        def preflight(self, argv):
            self.preflights.append(list(argv))
            self.self_tests.append(list(argv))
            return namespace.command(list(argv))

        def outer_environment(self):
            return namespace.outer_environment()

        def rewrite_provider_output_path(self, path):
            return namespace.rewrite_provider_output_path(path)

        def read_expected_output(self, name):
            self.output_reads.append(name)
            entries = sorted(output.iterdir())
            if entries != [output / name] or (output / name).is_symlink():
                raise evidence.AgyCanaryEvidenceError("unsafe captured output set")
            return (output / name).read_bytes()

        def write_expected_output(self, name, data):
            if list(output.iterdir()):
                raise evidence.AgyCanaryEvidenceError("unsafe captured output set")
            self.output_writes.append(name)
            (output / name).write_bytes(data)
            return self.read_expected_output(name)

        def projected_auth_proof(self):
            self.auth_proofs += 1
            return {"schema": "projected_auth.v1", "provider": "test", "records": []}

    return capture, TestAuthority(), stage, root, output


def _assert_sibling_command_is_private(command, env, prompt, *, stage, root, output):
    assert command[0] == "/usr/bin/bwrap"
    assert "--unshare-pid" in command
    assert command.index("--unshare-pid") < command.index("--clearenv")
    assert "/run/phase-loop-review" in command
    assert "/run/phase-loop-output" in command
    assert str(root) not in command
    assert str(root) not in prompt
    assert str(root) not in "\n".join(f"{key}={value}" for key, value in env.items())
    assert command.count(str(stage)) == 1
    assert command.count(str(output)) == 1
    assert str(stage) not in prompt
    assert str(output) not in prompt
    assert env["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    assert "HOME" not in env
    assert not any(key.startswith(("AGY_", "ANTIGRAVITY_", "GEMINI_", "XDG_")) for key in env)


def test_capture_enabled_codex_uses_sibling_namespace_and_output_mapping(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    capture, authority, stage, root, output = _sibling_namespace(tmp_path)
    captured: dict[str, object] = {}
    try:
        def fake_liveness(command, **kwargs):
            captured["command"] = list(command)
            captured["env"] = dict(kwargs["env"])
            captured["prompt"] = str(kwargs["input_text"])
            (output / "panel-codex.txt").write_text("AGREE\n")
            return pi._LegRun(0, "", "")

        monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
        rc, review, _log = pi._exec_leg(
            "codex",
            stage,
            output,
            artifact="artifact",
            env={"HOME": "/host-home", "AGY_SENTINEL": "leak"},
            agy_capture=capture,
            provider_authority=authority,
        )
        assert rc == 0 and review == "AGREE\n"
        assert authority.preflights and authority.self_tests
        assert authority.preflights[0][0] == "codex"
        assert authority.output_reads == ["panel-codex.txt"] * 2
        command = captured["command"]
        assert isinstance(command, list)
        assert "/run/phase-loop-output/panel-codex.txt" in command
        _assert_sibling_command_is_private(
            command, captured["env"], captured["prompt"],
            stage=stage, root=root, output=output,
        )
    finally:
        capture.close()
        shutil.rmtree(root)
        shutil.rmtree(output)


def test_capture_enabled_grok_uses_sibling_namespace_without_ledger_launch(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    capture, authority, stage, root, output = _sibling_namespace(tmp_path)
    captured: dict[str, object] = {}
    try:
        def fake_liveness(command, **kwargs):
            captured["command"] = list(command)
            captured["env"] = dict(kwargs["env"])
            return pi._LegRun(0, "AGREE\n", "")

        monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
        rc, review, _log = pi._exec_leg(
            "grok", stage, output, artifact="artifact",
            env={"HOME": "/host-home", "XDG_CONFIG_HOME": "/host-config"},
            agy_capture=capture, provider_authority=authority,
        )
        assert rc == 0 and review == "AGREE\n"
        assert authority.preflights and authority.self_tests
        assert authority.preflights[0][0] == "grok"
        assert authority.output_reads == ["panel-grok.txt"]
        assert authority.output_writes == ["panel-grok.txt"]
        assert authority.auth_proofs == 1
        command = captured["command"]
        assert isinstance(command, list)
        prompt = command[command.index("-p") + 1]
        assert "grok" in command
        _assert_sibling_command_is_private(
            command, captured["env"], prompt,
            stage=stage, root=root, output=output,
        )
    finally:
        capture.close()
        shutil.rmtree(root)
        shutil.rmtree(output)


def test_capture_materializes_all_provider_authorities_from_one_bound_stage(monkeypatch, tmp_path):
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    expected_capture = object()
    bindings: list[tuple[bytes, bytes]] = []
    prepared: dict[str, tuple[object, Path, tuple[bytes, bytes]]] = {}
    spawned: list[str] = []
    sealed_results: list[str] = []

    def bind_stage(**kwargs):
        assert kwargs["capture"] is expected_capture
        if bindings:
            raise evidence.AgyCanaryEvidenceError("stage binding must be exclusive")
        pair = (kwargs["bundle_bytes"], kwargs["instruction_bytes"])
        assert (kwargs["review_dir"] / "review-bundle.md").read_bytes() == pair[0]
        assert (kwargs["review_dir"] / "review-instructions.md").read_bytes() == pair[1]
        bindings.append(pair)

    def prepare_authority(*, capture: object, stage: Path, providers: tuple[str, ...]):
        assert capture is expected_capture
        assert len(providers) == 1
        provider = providers[0]
        output = Path(tempfile.mkdtemp(
            prefix=f"phase-loop-provider-output-{provider}-",
        ))
        output.chmod(0o700)
        authority = SimpleNamespace(
            namespace=SimpleNamespace(
                provider_output=output,
                provider_output_cleanup=evidence._seal_owned_cleanup_root(
                    output, kind="provider_output",
                ),
            ),
        )
        prepared[provider] = (
            authority,
            stage,
            ((stage / "review-bundle.md").read_bytes(),
             (stage / "review-instructions.md").read_bytes()),
        )
        return {provider: authority}

    def spawn_provider(leg, _artifact, **kwargs):
        authority, stage, _bytes = prepared[leg]
        assert kwargs["provider_authority"] is authority
        assert kwargs["capture_stage"] == stage
        assert kwargs["capture_scratch"].is_dir()
        assert stage.is_dir()
        assert authority.namespace.provider_output.is_dir()
        spawned.append(leg)
        return "OK", "AGREE"

    def seal_result(*, provider, authority, **_kwargs):
        _prepared_authority, stage, _bytes = prepared[provider]
        assert authority is _prepared_authority
        assert stage.is_dir()
        assert authority.namespace.provider_output.is_dir()
        sealed_results.append(provider)
        return {"synthetic": True}

    monkeypatch.setattr(pi, "bind_staged_review_inputs", bind_stage)
    monkeypatch.setattr(pi, "prepare_provider_launch_authorities", prepare_authority)
    monkeypatch.setattr(pi, "seal_provider_launches", lambda **_kwargs: {"synthetic": True})
    monkeypatch.setattr(pi, "record_provider_result", seal_result)
    monkeypatch.setattr(pi, "_default_spawn_via_provider", spawn_provider)
    monkeypatch.setattr(pi, "capture_summary", lambda _capture: {"synthetic": True})

    result = pi.invoke_board(
        DEFAULT_BOARD,
        "review",
        agy_canary_capture=expected_capture,
        base_env={},
        max_concurrency=1,
    )

    assert [leg.leg for leg in result.legs] == ["codex", "gemini", "claude", "grok"]
    assert set(prepared) == {"codex", "gemini", "claude", "grok"}
    assert spawned == ["codex", "gemini", "claude", "grok"]
    assert sealed_results == ["codex", "gemini", "claude", "grok"]
    assert len(bindings) == 1
    assert all(
        staged_bytes == bindings[0]
        for _authority, _stage, staged_bytes in prepared.values()
    )
    assert all(not stage.parent.exists() for _authority, stage, _bytes in prepared.values())
    assert all(
        not authority.namespace.provider_output.exists()
        for authority, _stage, _bytes in prepared.values()
    )


def test_capture_result_seals_before_coordinator_reclaims_scratch(monkeypatch, tmp_path):
    root = Path("/tmp") / f"phase-loop-result-root-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    providers = ("codex", "gemini", "claude", "grok")
    launches = {}
    registry_entries = []

    class Authority:
        def __init__(self, provider, output, runtime, placeholders, projection):
            self.provider = provider
            self.namespace = SimpleNamespace(
                provider_output=output,
                provider_output_cleanup=evidence._seal_owned_cleanup_root(
                    output, kind="provider_output",
                ),
            )
            self._runtime = runtime
            self._placeholders = placeholders
            self._projection = projection

        def runtime_authority(self):
            return self._runtime

        def auth_placeholder_proof(self):
            return self._placeholders

        def projected_auth_proof(self):
            return self._projection

        def review_attempt_proof(self):
            return {"launch": None, "attempts": [], "terminal_attempt": None}

    try:
        for provider in providers:
            seat_key = f"{provider}-seat"
            scratch = Path(tempfile.mkdtemp(prefix=f"pl-panel-capture-{provider}-"))
            stage = scratch / "review"
            stage.mkdir(mode=0o700)
            for name in ("review-bundle.md", "review-instructions.md"):
                (stage / name).write_text(name)
            output = Path("/tmp") / (
                f"phase-loop-provider-output-{provider}-{os.getpid()}-{tmp_path.name}"
            )
            output.mkdir(mode=0o700)
            runtime = {"provider": provider, "sha256": provider[0] * 64}
            placeholders = []
            projection = {"provider": provider, "records": []}
            authority = Authority(
                provider, output, runtime, placeholders, projection,
            )
            launches[seat_key] = (
                authority, stage, scratch,
                evidence._seal_owned_cleanup_root(scratch, kind="scratch"),
            )
            names = evidence._provider_names(provider, seat_key)
            launch = {
                "schema": "agy_provider_launch.v1",
                "provider": provider,
                "seat_key": seat_key,
                "runtime": runtime,
                "auth_placeholders": placeholders,
                "projected_auth": projection,
            }
            launch_bytes = evidence._canonical_json(launch)
            evidence._exclusive_write_at(
                capture.root_fd, names["authority"], launch_bytes, 0o600,
            )
            registry_entries.append({
                "provider": provider,
                "seat_key": seat_key,
                "authority": {
                    "name": names["authority"],
                    "bytes": len(launch_bytes),
                    "sha256": evidence._sha256(launch_bytes),
                },
                "result_name": names["result"],
            })
        registry = {
            "schema": "agy_provider_launch_registry.v1",
            "launch_authority_sha256": "a" * 64,
            "stage_binding_sha256": "b" * 64,
            "entries": registry_entries,
        }
        evidence._exclusive_write_at(
            capture.root_fd, evidence._PROVIDER_REGISTRY_NAME,
            evidence._canonical_json(registry), 0o600,
        )
        seat_key = "codex-seat"
        authority, stage, scratch, _scratch_cleanup = launches[seat_key]
        monkeypatch.setattr(pi, "_exec_leg", lambda *_args, **_kwargs: (0, "", ""))
        assert pi._default_spawn(
            "codex", "review", agy_capture=capture, seat_key=seat_key,
            provider_authority=authority, capture_stage=stage,
            capture_scratch=scratch,
        ) == ("EMPTY", "")
        assert scratch.is_dir() and stage.is_dir()
        assert authority.namespace.provider_output.is_dir()
        result = evidence.record_provider_result(
            capture=capture, provider="codex", seat_key=seat_key,
            authority=authority, status="EMPTY", text="", detail=None,
        )
        assert result["schema"] == "agy_provider_result.v1"
        assert (root / evidence._provider_names("codex", seat_key)["result"]).is_file()
        pi._cleanup_capture_launches(launches)
        assert all(
            not scratch_path.exists() and
            not launch_authority.namespace.provider_output.exists()
            for launch_authority, _stage, scratch_path, _cleanup in launches.values()
        )
    finally:
        capture.close()
        pi._cleanup_capture_launches(launches)
        shutil.rmtree(root)


def test_capture_cleanup_repairs_owned_mode_zero_tree():
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-mode-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    nested = root / "nested"
    nested.mkdir(mode=0o700)
    (nested / "result.json").write_text("{}\n")
    nested.chmod(0o000)
    evidence._cleanup_owned_roots([authority])
    assert not root.exists()
    tombstone = _cleanup_tombstone_for(authority)
    assert tombstone.is_dir() and list(tombstone.iterdir()) == []
    descendants = _cleanup_descendant_tombstones_for(authority)
    assert len(descendants) == 2
    assert sorted(
        ("directory", 0) if path.is_dir() else ("file", path.stat().st_size)
        for path in descendants
    ) == [("directory", 0), ("file", 0)]
    tombstone.rmdir()
    for descendant in descendants:
        descendant.rmdir() if descendant.is_dir() else descendant.unlink()


@pytest.mark.parametrize("failure", ["chmod", "seal"])
def test_capture_root_creation_failure_reclaims_provisional_root(
    monkeypatch, failure,
):
    created: list[Path] = []
    authorities: dict[tuple[int, int], object] = {}
    real_mkdtemp = tempfile.mkdtemp
    real_chmod = Path.chmod
    real_seal = evidence._seal_owned_cleanup_root
    real_authority = evidence._owned_cleanup_root_authority

    def capture_mkdtemp(*, prefix, dir):
        path = Path(real_mkdtemp(prefix=prefix, dir=dir))
        created.append(path)
        return str(path)

    def fail_chmod(path, mode):
        real_chmod(path, mode)
        if failure == "chmod" and path in created:
            raise OSError("injected chmod failure")

    def fail_seal(path, *, kind, quarantine_token=None):
        if failure == "seal":
            raise evidence.AgyCanaryEvidenceError("injected seal failure")
        return real_seal(
            path, kind=kind, quarantine_token=quarantine_token,
        )

    def capture_authority(path, *, kind, quarantine_token=None):
        authority = real_authority(
            path, kind=kind, quarantine_token=quarantine_token,
        )
        authorities[(authority.device, authority.inode)] = authority
        return authority

    monkeypatch.setattr(evidence.tempfile, "mkdtemp", capture_mkdtemp)
    monkeypatch.setattr(Path, "chmod", fail_chmod)
    monkeypatch.setattr(
        evidence, "_owned_cleanup_root_authority", capture_authority,
    )
    monkeypatch.setattr(evidence, "_seal_owned_cleanup_root", fail_seal)
    with pytest.raises((OSError, evidence.AgyCanaryEvidenceError)):
        evidence._create_owned_cleanup_root(kind="scratch")
    assert len(created) == 1
    assert not created[0].exists()
    assert len(authorities) == 1
    tombstone = _cleanup_tombstone_for(next(iter(authorities.values())))
    assert list(tombstone.iterdir()) == []
    tombstone.rmdir()


def test_capture_cleanup_attempts_all_roots_and_reports_incomplete(monkeypatch):
    first = Path(tempfile.mkdtemp(prefix="pl-panel-capture-fail-", dir="/tmp"))
    second = Path(tempfile.mkdtemp(prefix="pl-panel-capture-next-", dir="/tmp"))
    first.chmod(0o700)
    second.chmod(0o700)
    authorities = [
        evidence._seal_owned_cleanup_root(first, kind="scratch"),
        evidence._seal_owned_cleanup_root(second, kind="scratch"),
    ]
    (first / "undeletable").write_text("retain\n")
    (second / "removable").write_text("remove\n")
    real_rename_noreplace = evidence._rename_noreplace

    def injected_failure(source_fd, source, destination_fd, destination):
        if source == "undeletable":
            raise PermissionError("injected undeletable root")
        return real_rename_noreplace(
            source_fd, source, destination_fd, destination,
        )

    monkeypatch.setattr(evidence, "_rename_noreplace", injected_failure)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots(authorities)
        first_tombstone = _cleanup_tombstone_for(authorities[0])
        second_tombstone = _cleanup_tombstone_for(authorities[1])
        assert (first_tombstone / "undeletable").is_file()
        assert (first_tombstone / "undeletable").read_bytes() == b""
        assert not second.exists()
        assert list(second_tombstone.iterdir()) == []
    finally:
        monkeypatch.setattr(
            evidence, "_rename_noreplace", real_rename_noreplace,
        )
        for authority in authorities:
            shutil.rmtree(_cleanup_tombstone_for(authority), ignore_errors=True)


def test_capture_cleanup_refuses_substituted_root_and_unrelated_deletion():
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-swap-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    original = root.with_name(root.name + "-original")
    root.rename(original)
    root.mkdir(mode=0o700)
    marker = root / "unrelated"
    marker.write_text("retain\n")
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        assert marker.read_text() == "retain\n"
        assert original.is_dir()
    finally:
        shutil.rmtree(root)
        shutil.rmtree(original)


def test_capture_cleanup_quarantine_swap_retains_unrelated_data(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-race-", dir="/tmp"))
    unrelated = Path(tempfile.mkdtemp(
        prefix="pl-panel-capture-unrelated-", dir="/tmp",
    ))
    root.chmod(0o700)
    unrelated.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    marker = unrelated / "unrelated-marker"
    marker.write_text("retain\n")
    original = root.with_name(root.name + "-original")
    real_rename_noreplace = evidence._rename_noreplace
    moved_names: list[str] = []

    def swap_inside_rename(source_fd, source, destination_fd, destination):
        if source == root.name:
            root.rename(original)
            unrelated.rename(root)
            moved_names.append(destination)
        return real_rename_noreplace(
            source_fd, source, destination_fd, destination,
        )

    monkeypatch.setattr(evidence, "_rename_noreplace", swap_inside_rename)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        assert len(moved_names) == 1
        moved = Path("/tmp") / moved_names[0]
        assert (moved / "unrelated-marker").read_text() == "retain\n"
        assert original.is_dir()
    finally:
        monkeypatch.setattr(
            evidence, "_rename_noreplace", real_rename_noreplace,
        )
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(original, ignore_errors=True)
        for name in moved_names:
            shutil.rmtree(Path("/tmp") / name, ignore_errors=True)


def test_capture_cleanup_regular_swap_at_quarantine_preserves_replacement(
    monkeypatch,
):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-file-swap-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    (root / "victim").write_text("authorized\n")
    real_rename_noreplace = evidence._rename_noreplace
    moved_names: list[str] = []

    def swap_inside_rename(source_fd, source, destination_fd, destination):
        if source == "victim":
            os.rename(
                "victim", "authorized-original",
                src_dir_fd=source_fd, dst_dir_fd=source_fd,
            )
            replacement_fd = os.open(
                "victim", os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600, dir_fd=source_fd,
            )
            try:
                os.write(replacement_fd, b"unrelated-marker\n")
            finally:
                os.close(replacement_fd)
            moved_names.append(destination)
        return real_rename_noreplace(
            source_fd, source, destination_fd, destination,
        )

    monkeypatch.setattr(evidence, "_rename_noreplace", swap_inside_rename)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        root_tombstone = _cleanup_tombstone_for(authority)
        assert (root_tombstone / "authorized-original").read_bytes() == b""
        assert len(moved_names) == 1
        assert (Path("/tmp") / moved_names[0]).read_bytes() == b"unrelated-marker\n"
    finally:
        monkeypatch.setattr(
            evidence, "_rename_noreplace", real_rename_noreplace,
        )
        shutil.rmtree(_cleanup_tombstone_for(authority), ignore_errors=True)
        for name in moved_names:
            (Path("/tmp") / name).unlink(missing_ok=True)


def test_capture_cleanup_directory_swap_at_quarantine_preserves_replacement(
    monkeypatch,
):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-dir-swap-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    nested = root / "nested"
    nested.mkdir(mode=0o700)
    (nested / "authorized").write_text("retain\n")
    real_rename_noreplace = evidence._rename_noreplace
    moved_names: list[str] = []

    def swap_inside_rename(source_fd, source, destination_fd, destination):
        if source == "nested":
            os.rename(
                "nested", "authorized-original",
                src_dir_fd=source_fd, dst_dir_fd=source_fd,
            )
            os.mkdir("nested", mode=0o700, dir_fd=source_fd)
            replacement_fd = os.open(
                "nested", os.O_RDONLY | os.O_DIRECTORY,
                dir_fd=source_fd,
            )
            try:
                marker_fd = os.open(
                    "unrelated-marker", os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600, dir_fd=replacement_fd,
                )
                os.close(marker_fd)
            finally:
                os.close(replacement_fd)
            moved_names.append(destination)
        return real_rename_noreplace(
            source_fd, source, destination_fd, destination,
        )

    monkeypatch.setattr(evidence, "_rename_noreplace", swap_inside_rename)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        root_tombstone = _cleanup_tombstone_for(authority)
        assert (root_tombstone / "authorized-original" / "authorized").read_text() == "retain\n"
        assert len(moved_names) == 1
        assert (Path("/tmp") / moved_names[0] / "unrelated-marker").is_file()
    finally:
        monkeypatch.setattr(
            evidence, "_rename_noreplace", real_rename_noreplace,
        )
        shutil.rmtree(_cleanup_tombstone_for(authority), ignore_errors=True)
        for name in moved_names:
            shutil.rmtree(Path("/tmp") / name, ignore_errors=True)


def test_capture_cleanup_never_name_deletes_public_root(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-final-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    (root / "result").write_text("remove\n")
    real_rmdir = evidence.os.rmdir

    def reject_public_rmdir(name, *args, **kwargs):
        if name == root.name:
            raise AssertionError("public cleanup root must never be name-deleted")
        return real_rmdir(name, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "rmdir", reject_public_rmdir)
    evidence._cleanup_owned_roots([authority])
    assert not root.exists()
    _cleanup_tombstone_for(authority).rmdir()


def test_capture_cleanup_rejects_hostile_held_root_with_secret():
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-held-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    secret = root / "secret"
    secret.write_text("retain\n")
    held = Path("/tmp") / (
        f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}scratch-"
        f"{authority.quarantine_token}"
    )
    root.rename(held)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        assert (held / "secret").read_text() == "retain\n"
    finally:
        shutil.rmtree(held)


def test_capture_cleanup_repeat_accepts_exact_empty_tombstone():
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-repeat-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    (root / "result").write_text("remove\n")
    evidence._cleanup_owned_roots([authority])
    tombstone = _cleanup_tombstone_for(authority)
    evidence._cleanup_owned_roots([authority])
    assert tombstone.is_dir() and list(tombstone.iterdir()) == []
    descendants = _cleanup_descendant_tombstones_for(authority)
    assert len(descendants) == 1
    assert descendants[0].is_file() and descendants[0].stat().st_size == 0
    tombstone.rmdir()
    descendants[0].unlink()


@pytest.mark.parametrize("repeat", [False, True])
def test_capture_cleanup_revalidates_root_after_descendants(monkeypatch, repeat):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-root-final-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    if repeat:
        evidence._cleanup_owned_roots([authority])
    tombstone = _cleanup_tombstone_for(authority) if repeat else Path("/tmp") / (
        f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}scratch-"
        f"{authority.quarantine_token}"
    )
    real_validate = evidence._validate_owned_cleanup_descendant_tombstones
    injected = False

    def inject_after_descendants(*, tmp_fd, authority):
        nonlocal injected
        result = real_validate(tmp_fd=tmp_fd, authority=authority)
        if not injected:
            injected = True
            (tombstone / "late-secret").write_text("retain\n")
        return result

    monkeypatch.setattr(
        evidence, "_validate_owned_cleanup_descendant_tombstones",
        inject_after_descendants,
    )
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        assert injected
        assert (tombstone / "late-secret").read_text() == "retain\n"
    finally:
        monkeypatch.setattr(
            evidence, "_validate_owned_cleanup_descendant_tombstones",
            real_validate,
        )
        shutil.rmtree(tombstone)


def test_capture_cleanup_rejects_early_descendant_replacement_during_later_check(
    monkeypatch,
):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-desc-final-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    (root / "first").write_text("remove\n")
    (root / "second").write_text("remove\n")
    evidence._cleanup_owned_roots([authority])
    tombstone = _cleanup_tombstone_for(authority)
    descendants = _cleanup_descendant_tombstones_for(authority)
    assert len(descendants) == 2
    early, later = descendants
    original = early.with_name(early.name + "-original")
    real_open = evidence.os.open
    injected = False

    def replace_early_when_later_opens(path, flags, *args, **kwargs):
        nonlocal injected
        if (not injected and path == later.name and
                kwargs.get("dir_fd") is not None):
            injected = True
            early.rename(original)
            early.touch(mode=0o600)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "open", replace_early_when_later_opens)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        assert injected
        assert early.is_file() and early.stat().st_size == 0
        assert original.is_file() and original.stat().st_size == 0
    finally:
        monkeypatch.setattr(evidence.os, "open", real_open)
        tombstone.rmdir()
        early.unlink(missing_ok=True)
        later.unlink(missing_ok=True)
        original.unlink(missing_ok=True)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_capture_cleanup_repeat_rejects_nonempty_descendant_tombstone(kind):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-desc-repeat-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    if kind == "file":
        (root / "result").write_text("remove\n")
    else:
        (root / "nested").mkdir(mode=0o700)
    evidence._cleanup_owned_roots([authority])
    tombstone = _cleanup_tombstone_for(authority)
    descendants = _cleanup_descendant_tombstones_for(authority)
    assert len(descendants) == 1
    if kind == "file":
        descendants[0].write_text("late-secret\n")
    else:
        (descendants[0] / "late-secret").write_text("retain\n")
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        if kind == "file":
            assert descendants[0].read_text() == "late-secret\n"
        else:
            assert (descendants[0] / "late-secret").read_text() == "retain\n"
    finally:
        tombstone.rmdir()
        if kind == "file":
            descendants[0].unlink()
        else:
            shutil.rmtree(descendants[0])


def test_capture_cleanup_repeat_rejects_late_tombstone_secret(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-late-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    evidence._cleanup_owned_roots([authority])
    tombstone = _cleanup_tombstone_for(authority)
    real_stat = evidence.os.stat
    calls = 0

    def inject_secret(path, *args, **kwargs):
        nonlocal calls
        if path == tombstone.name and kwargs.get("dir_fd") is not None:
            calls += 1
            if calls == 3:
                (tombstone / "late-secret").write_text("retain\n")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "stat", inject_secret)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        assert calls >= 3
        assert (tombstone / "late-secret").read_text() == "retain\n"
    finally:
        monkeypatch.setattr(evidence.os, "stat", real_stat)
        shutil.rmtree(tombstone)


def test_capture_cleanup_repeat_rejects_public_recreation_at_final_stat(
    monkeypatch,
):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-recreate-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    evidence._cleanup_owned_roots([authority])
    tombstone = _cleanup_tombstone_for(authority)
    real_stat = evidence.os.stat
    calls = 0

    def recreate_public(path, *args, **kwargs):
        nonlocal calls
        if path == tombstone.name and kwargs.get("dir_fd") is not None:
            calls += 1
            if calls == 4:
                root.mkdir(mode=0o700)
                (root / "unrelated-marker").write_text("retain\n")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "stat", recreate_public)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        assert calls >= 4
        assert (root / "unrelated-marker").read_text() == "retain\n"
        assert list(tombstone.iterdir()) == []
    finally:
        monkeypatch.setattr(evidence.os, "stat", real_stat)
        shutil.rmtree(root)
        tombstone.rmdir()


def test_capture_cleanup_rejects_missing_tombstone_for_absent_root():
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-zero-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    root.rmdir()
    with pytest.raises(
        evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
    ):
        evidence._cleanup_owned_roots([authority])


@pytest.mark.parametrize("mutation", ["malformed", "wrong-kind", "mode"])
def test_capture_cleanup_rejects_malformed_tombstone(
    mutation,
):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-malformed-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    token = authority.quarantine_token
    if mutation == "malformed":
        name = f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}scratch-not-hex"
    elif mutation == "wrong-kind":
        name = f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}provider_output-{token}"
    else:
        name = f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}scratch-{token}"
    tombstone = Path("/tmp") / name
    root.rename(tombstone)
    if mutation == "mode":
        tombstone.chmod(0o755)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
    finally:
        tombstone.chmod(0o700)
        tombstone.rmdir()


def test_capture_cleanup_rejects_wrong_identity_tombstone():
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-identity-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    tombstone = Path(tempfile.mkdtemp(
        prefix=f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}scratch-",
        dir="/tmp",
    ))
    replacement = tombstone.with_name(
        f"{evidence._OWNED_CLEANUP_QUARANTINE_PREFIX}scratch-"
        f"{authority.quarantine_token}"
    )
    tombstone.rename(replacement)
    root.rmdir()
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
    finally:
        replacement.rmdir()


def test_capture_cleanup_rejects_duplicate_tombstone_scan(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-cardinality-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    evidence._cleanup_owned_roots([authority])
    tombstone = _cleanup_tombstone_for(authority)
    tmp_info = Path("/tmp").stat()
    real_listdir = evidence.os.listdir

    def duplicate_tombstone(path):
        names = real_listdir(path)
        if (isinstance(path, int) and
                (os.fstat(path).st_dev, os.fstat(path).st_ino) ==
                (tmp_info.st_dev, tmp_info.st_ino)):
            return [*names, tombstone.name]
        return names

    monkeypatch.setattr(evidence.os, "listdir", duplicate_tombstone)
    with pytest.raises(
        evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
    ):
        evidence._cleanup_owned_roots([authority])
    tombstone.rmdir()


def test_capture_cleanup_rejects_hardlink_without_chmod(tmp_path):
    root = Path(tempfile.mkdtemp(prefix="pl-panel-capture-hardlink-", dir="/tmp"))
    root.chmod(0o700)
    authority = evidence._seal_owned_cleanup_root(root, kind="scratch")
    outside = tmp_path / "outside-hardlink"
    outside.write_text("retain\n")
    outside.chmod(0o400)
    linked = root / "linked"
    os.link(outside, linked)
    mode = stat.S_IMODE(outside.stat().st_mode)
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([authority])
        tombstone = _cleanup_tombstone_for(authority)
        assert (tombstone / "linked").is_file()
        assert outside.read_text() == "retain\n"
        assert stat.S_IMODE(outside.stat().st_mode) == mode == 0o400
    finally:
        shutil.rmtree(_cleanup_tombstone_for(authority), ignore_errors=True)


def test_capture_cleanup_rejects_invalid_kind_and_prefix():
    invalid = Path(tempfile.mkdtemp(prefix="invalid-cleanup-", dir="/tmp"))
    valid = Path(tempfile.mkdtemp(prefix="pl-panel-capture-valid-", dir="/tmp"))
    invalid.chmod(0o700)
    valid.chmod(0o700)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError):
            evidence._seal_owned_cleanup_root(invalid, kind="scratch")
        with pytest.raises(evidence.AgyCanaryEvidenceError):
            evidence._seal_owned_cleanup_root(valid, kind="provider_output")
        authority = evidence._seal_owned_cleanup_root(valid, kind="scratch")
        forged = evidence._OwnedCleanupRoot(
            path=authority.path, kind="unknown", prefix=authority.prefix,
            device=authority.device, inode=authority.inode,
            uid=authority.uid, gid=authority.gid,
            quarantine_token=authority.quarantine_token,
        )
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ):
            evidence._cleanup_owned_roots([forged])
        assert valid.is_dir()
    finally:
        shutil.rmtree(invalid)
        shutil.rmtree(valid)


def test_capture_cleanup_failure_preserves_primary_exception_context(tmp_path):
    scratch = Path(tempfile.mkdtemp(prefix="pl-panel-capture-context-", dir="/tmp"))
    output = Path(tempfile.mkdtemp(
        prefix="phase-loop-provider-output-context-", dir="/tmp",
    ))
    scratch.chmod(0o700)
    output.chmod(0o700)
    outside = tmp_path / "outside-context-hardlink"
    outside.write_text("retain\n")
    os.link(outside, output / "linked")
    authority = SimpleNamespace(namespace=SimpleNamespace(
        provider_output=output,
        provider_output_cleanup=evidence._seal_owned_cleanup_root(
            output, kind="provider_output",
        ),
    ))
    scratch_cleanup = evidence._seal_owned_cleanup_root(scratch, kind="scratch")
    launches = {"seat": (authority, scratch, scratch, scratch_cleanup)}
    try:
        with pytest.raises(
            evidence.AgyCanaryEvidenceError, match="cleanup was incomplete",
        ) as caught:
            try:
                raise evidence.AgyCanaryEvidenceError("primary result failure")
            finally:
                pi._cleanup_capture_launches(launches)
        assert isinstance(caught.value.__context__, evidence.AgyCanaryEvidenceError)
        assert str(caught.value.__context__) == "primary result failure"
        assert _cleanup_tombstone_for(
            authority.namespace.provider_output_cleanup
        ).is_dir()
        assert not scratch.exists()
    finally:
        shutil.rmtree(
            _cleanup_tombstone_for(authority.namespace.provider_output_cleanup),
            ignore_errors=True,
        )
        _cleanup_tombstone_for(scratch_cleanup).rmdir()


def _private_tree_snapshot(path: Path) -> tuple[object, ...]:
    root = path.lstat()
    entries: list[object] = [
        (".", root.st_dev, root.st_ino, stat.S_IMODE(root.st_mode), root.st_uid,
         root.st_gid),
    ]
    for entry in sorted(path.rglob("*")):
        info = entry.lstat()
        relative = entry.relative_to(path).as_posix()
        entries.append((
            relative,
            info.st_dev,
            info.st_ino,
            stat.S_IMODE(info.st_mode),
            info.st_uid,
            info.st_gid,
            entry.read_bytes() if stat.S_ISREG(info.st_mode) else None,
        ))
    return tuple(entries)


def test_default_spawn_preserves_fatal_quiescence_authority(monkeypatch, tmp_path):
    def fatal_exec(*_args, **_kwargs):
        raise pi.ProviderProcessGroupQuiescenceError(
            "provider process group did not terminate"
        )

    monkeypatch.setattr(pi, "_exec_leg", fatal_exec)
    with pytest.raises(
        pi.ProviderProcessGroupQuiescenceError,
        match="provider process group did not terminate",
    ):
        pi._default_spawn("codex", "review", repo_dir=tmp_path)

    def ordinary_failure(*_args, **_kwargs):
        raise OSError("ordinary provider failure")

    monkeypatch.setattr(pi, "_exec_leg", ordinary_failure)
    assert pi._default_spawn("codex", "review", repo_dir=tmp_path) == (
        "DEGRADED",
        "ordinary provider failure",
    )


@pytest.mark.parametrize("mutation_kind", ["ledger", "output"])
def test_capture_mutation_gate_rejects_parent_write_after_trip(
    monkeypatch, tmp_path, mutation_kind,
):
    latch = pi._ProviderQuiescenceLatch()
    primary = pi.ProviderProcessGroupQuiescenceError("fatal quiescence")
    checked = threading.Event()
    resume = threading.Event()
    mutations: list[str] = []
    errors: list[BaseException] = []
    output = tmp_path / "parent-output"
    authority = object.__new__(evidence.ProviderLaunchAuthority)

    monkeypatch.setattr(
        evidence.ProviderLaunchAuthority,
        "record_review_attempt",
        lambda _self, _command, **_kwargs: mutations.append("ledger"),
    )

    def worker() -> None:
        try:
            # Reproduce the old check-then-mutate window: this check succeeds,
            # then a sibling trips the fatal latch before the mutation resumes.
            latch.raise_if_set()
            checked.set()
            assert resume.wait(5)
            if mutation_kind == "ledger":
                pi._record_capture_review_attempt(
                    authority, ["codex"], quiescence_latch=latch,
                )
            else:
                pi._capture_mutation(
                    latch, lambda: output.write_text("parent mutation"),
                )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert checked.wait(5)
    assert latch.trip(primary) is primary
    resume.set()
    thread.join(5)

    assert not thread.is_alive()
    assert errors == [primary]
    assert mutations == []
    assert not output.exists()


def test_capture_grok_preflight_publish_rejects_after_trip(tmp_path):
    latch = pi._ProviderQuiescenceLatch()
    primary = pi.ProviderProcessGroupQuiescenceError("fatal preflight")
    precommit = threading.Event()
    resume = threading.Event()
    errors: list[BaseException] = []

    class PausedGrokAuthority:
        review_launch = None

        def preflight(self, command, *, probe_runner, publish):
            assert callable(probe_runner)
            precommit.set()
            assert resume.wait(5)
            publish(lambda: setattr(self, "review_launch", tuple(command)))
            return command

    authority = PausedGrokAuthority()

    def worker() -> None:
        try:
            pi._capture_provider_preflight(authority, ["grok"], latch)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert precommit.wait(5)
    assert latch.trip(primary) is primary
    resume.set()
    thread.join(5)

    assert not thread.is_alive()
    assert errors == [primary]
    assert authority.review_launch is None


@pytest.mark.skipif(os.name == "nt", reason="preflight registry needs POSIX groups")
def test_capture_preflight_probe_is_swept_by_fatal_latch(tmp_path):
    latch = pi._ProviderQuiescenceLatch()
    primary = pi.ProviderProcessGroupQuiescenceError("fatal preflight")
    pid_marker = tmp_path / "preflight.pid"
    errors: list[BaseException] = []

    class BlockingGrokAuthority:
        review_launch = None

        def preflight(self, command, *, probe_runner, publish):
            returncode = probe_runner(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os, signal, sys, time; "
                        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                        "import os as _o; _t=sys.argv[1]+'.partial'; open(_t,'w').write(str(os.getpid())); _o.replace(_t, sys.argv[1]); "
                        "time.sleep(600)"
                    ),
                    str(pid_marker),
                ],
                os.environ,
                30,
            )
            assert returncode == 0
            publish(lambda: setattr(self, "review_launch", tuple(command)))
            return command

    authority = BlockingGrokAuthority()

    def worker() -> None:
        try:
            pi._capture_provider_preflight(authority, ["grok"], latch)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 5
    while not pid_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_marker.exists()
    pid = int(pid_marker.read_text())
    assert latch.trip(primary) is primary
    thread.join(5)

    assert not thread.is_alive()
    assert errors == [primary]
    assert authority.review_launch is None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not pi._process_group_exists(pid)


@pytest.mark.parametrize("publication_kind", ["stream-file", "callback"])
def test_capture_stream_publication_rejects_after_paused_gate_trip(
    monkeypatch, tmp_path, publication_kind,
):
    latch = pi._ProviderQuiescenceLatch()
    primary = pi.ProviderProcessGroupQuiescenceError("fatal stream publication")
    gate_entered = threading.Event()
    resume = threading.Event()
    callbacks: list[str] = []
    errors: list[BaseException] = []
    real_gate = pi._capture_mutation

    def paused_gate(gate_latch, mutation):
        if gate_latch is latch:
            gate_entered.set()
            assert resume.wait(5)
        return real_gate(gate_latch, mutation)

    monkeypatch.setattr(pi, "_capture_mutation", paused_gate)
    result = pi.PanelLegResult("codex", "OK", "AGREE")
    stream_dir = tmp_path / "stream"

    def run() -> None:
        try:
            pi._run_legs_ordered(
                [object()],
                lambda _item: result,
                max_concurrency=1,
                on_leg_complete=(
                    callbacks.append if publication_kind == "callback" else None
                ),
                review_dir=(
                    stream_dir if publication_kind == "stream-file" else None
                ),
                fatal_latch=latch,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert gate_entered.wait(5)
    assert latch.trip(primary) is primary
    resume.set()
    thread.join(5)

    assert not thread.is_alive()
    assert errors == [primary]
    assert callbacks == []
    assert not stream_dir.exists()


@pytest.mark.parametrize(
    "max_concurrency", [1, 4], ids=["queued-sequential", "running-parallel-barrier"],
)
def test_capture_quiescence_failure_stops_siblings_and_retains_private_roots(
    monkeypatch, tmp_path, max_concurrency,
):
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    expected_capture = object()
    roots: list[Path] = []
    outputs: dict[str, Path] = {}
    spawned: list[str] = []
    group_pids: dict[str, int] = {}
    cleanup_calls = 0
    result_seals = 0
    summary_calls = 0
    primary_error = pi.ProviderProcessGroupQuiescenceError(
        "provider process group did not terminate"
    )

    def prepare_authority(*, stage: Path, providers: tuple[str, ...], **_kwargs):
        provider = providers[0]
        output, output_cleanup = evidence._create_owned_cleanup_root(
            kind="provider_output",
        )
        (output / "sentinel").write_bytes(f"{provider}-sealed".encode())
        roots.extend((stage.parent, output))
        outputs[provider] = output
        authority = SimpleNamespace(namespace=SimpleNamespace(
            provider_output=output,
            provider_output_cleanup=output_cleanup,
        ))
        return {provider: authority}

    def fatal_spawn(leg, *_args, quiescence_latch=None, **_kwargs):
        spawned.append(leg)
        if leg == "codex":
            if max_concurrency == 4:
                deadline = time.monotonic() + 5
                sibling_markers = [
                    tmp_path / f"{provider}.pid"
                    for provider in ("gemini", "claude", "grok")
                ]
                while (not all(path.exists() for path in sibling_markers) and
                       time.monotonic() < deadline):
                    time.sleep(0.02)
                assert all(path.exists() for path in sibling_markers)
                group_pids.update({
                    path.stem: int(path.read_text()) for path in sibling_markers
                })
            raise primary_error
        (outputs[leg] / "pre-fatal-partial-output").write_text("retained")
        pid_marker = tmp_path / f"{leg}.pid"
        sigterm_marker = outputs[leg] / "sigterm-partial-output"
        pi._run_leg_with_liveness(
            [
                sys.executable,
                "-c",
                (
                    "import os, signal, sys, time\n"
                    "def on_term(_signum, _frame):\n"
                    "    with open(sys.argv[2], 'w') as marker:\n"
                    "        marker.write('truthful post-trip private output')\n"
                    "signal.signal(signal.SIGTERM, on_term)\n"
                    "_t = sys.argv[1] + '.partial'\n"
                    "with open(_t, 'w') as marker:\n"
                    "    marker.write(str(os.getpid()))\n"
                    "os.replace(_t, sys.argv[1])\n"
                    "while True:\n"
                    "    time.sleep(1)\n"
                ),
                str(pid_marker),
                str(sigterm_marker),
            ],
            cwd=tmp_path,
            env=os.environ,
            deadline_s=30,
            stall_threshold_s=30,
            quiescence_latch=quiescence_latch,
        )
        (outputs[leg] / "parent-after-quiescence-marker").write_text("must-not-run")
        return "OK", "AGREE"

    def seal_result(**_kwargs):
        nonlocal result_seals
        result_seals += 1

    def cleanup_spy(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1

    def summary_spy(_capture):
        nonlocal summary_calls
        summary_calls += 1
        return {"synthetic": True}

    monkeypatch.setattr(pi, "bind_staged_review_inputs", lambda **_kwargs: None)
    monkeypatch.setattr(pi, "prepare_provider_launch_authorities", prepare_authority)
    monkeypatch.setattr(pi, "seal_provider_launches", lambda **_kwargs: None)
    monkeypatch.setattr(pi, "record_provider_result", seal_result)
    monkeypatch.setattr(pi, "capture_summary", summary_spy)
    monkeypatch.setattr(pi, "_default_spawn", fatal_spawn)
    monkeypatch.setattr(pi, "_cleanup_capture_launches", cleanup_spy)

    try:
        with pytest.raises(
            pi.ProviderProcessGroupQuiescenceError,
            match="provider process group did not terminate",
        ) as caught:
            pi.invoke_board(
                DEFAULT_BOARD,
                "review",
                agy_canary_capture=expected_capture,
                base_env={},
                max_concurrency=max_concurrency,
            )
        assert cleanup_calls == 0
        assert result_seals == 0
        assert summary_calls == 0
        assert caught.value is primary_error
        if max_concurrency == 1:
            assert spawned == ["codex"]
        else:
            assert len(spawned) == 4
            assert set(spawned) == {"codex", "gemini", "claude", "grok"}
            assert set(group_pids) == {"gemini", "claude", "grok"}
            for pid in group_pids.values():
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
                assert not pi._process_group_exists(pid)
            assert all(
                (outputs[provider] / "pre-fatal-partial-output").read_text()
                == "retained"
                for provider in ("gemini", "claude", "grok")
            )
            assert all(
                (outputs[provider] / "sigterm-partial-output").read_text()
                == "truthful post-trip private output"
                for provider in ("gemini", "claude", "grok")
            )
            assert all(
                not (outputs[provider] / "parent-after-quiescence-marker").exists()
                for provider in ("gemini", "claude", "grok")
            )
        assert len(roots) == 8
        assert all(root.is_dir() for root in roots)
        assert all(stat.S_IMODE(root.lstat().st_mode) == 0o700 for root in roots)
        retained = {root: _private_tree_snapshot(root) for root in roots}
        time.sleep(0.1)
        assert all(_private_tree_snapshot(root) == snapshot
                   for root, snapshot in retained.items())
    finally:
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)


def _terminate_real_descendant_group_before_capture_cleanup(
    monkeypatch, marker: Path,
) -> tuple[int, int]:
    child_code = (
        "import os, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "import os as _o; _t=sys.argv[1]+'.partial'; open(_t,'w').write(str(os.getpid())); _o.replace(_t, sys.argv[1]); "
        "time.sleep(600)"
    )
    leader_code = (
        "import signal, subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]]); "
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
        "time.sleep(600)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", leader_code, str(marker), child_code],
        start_new_session=True,
    )
    pi._anchor_process_group(proc)
    monkeypatch.setattr(pi, "_PROCESS_GROUP_TERM_GRACE_S", 0.2)
    monkeypatch.setattr(pi, "_PROCESS_GROUP_KILL_GRACE_S", 3.0)
    monkeypatch.setattr(pi, "_PROCESS_GROUP_POLL_S", 0.02)
    deadline = time.monotonic() + 5
    try:
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        descendant_pid = int(marker.read_text())
        pi._terminate_process_group(proc)
        return proc.pid, descendant_pid
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2)
        raise


@pytest.mark.parametrize(
    "failure", ["write", "bind", "prepare", "seal", "result", None],
)
def test_capture_setup_always_reclaims_scratch_and_provider_outputs(monkeypatch, tmp_path, failure):
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    outputs: list[Path] = []
    scratches: list[Path] = []
    cleanup_authorities: list[object] = []
    worker_threads: list[threading.Thread] = []
    cleanup_worker_states: list[tuple[bool, ...]] = []
    terminated_groups: list[tuple[int, int]] = []
    calls = 0

    real_write_bytes = Path.write_bytes
    real_mkdtemp = tempfile.mkdtemp
    real_cleanup = pi._cleanup_capture_launches

    def capture_mkdtemp(*, prefix, dir="/tmp"):
        scratch = Path(real_mkdtemp(prefix=prefix, dir=dir))
        scratch.chmod(0o700)
        scratches.append(scratch)
        cleanup_authorities.append(
            evidence._seal_owned_cleanup_root(scratch, kind="scratch")
        )
        return str(scratch)

    def write_bytes(path, data):
        if failure == "write" and path.name == "review-bundle.md":
            raise OSError("stage write failed")
        return real_write_bytes(path, data)

    def bind_stage(**_kwargs):
        if failure == "bind":
            raise evidence.AgyCanaryEvidenceError("stage bind failed")

    def prepare_authority(*, stage: Path, providers: tuple[str, ...], **_kwargs):
        nonlocal calls
        calls += 1
        if failure == "prepare" and calls == 2:
            raise evidence.AgyCanaryEvidenceError("second authority failed")
        output = Path(real_mkdtemp(
            prefix=f"phase-loop-provider-output-{providers[0]}-", dir="/tmp",
        ))
        output.chmod(0o700)
        outputs.append(output)
        output_cleanup = evidence._seal_owned_cleanup_root(
            output, kind="provider_output",
        )
        cleanup_authorities.append(output_cleanup)
        return {providers[0]: SimpleNamespace(namespace=SimpleNamespace(
            provider_output=output,
            provider_output_cleanup=output_cleanup,
        ))}

    def spawn_provider(*_args, **_kwargs):
        worker_threads.append(threading.current_thread())
        if failure in {"result", None} and not terminated_groups:
            terminated_groups.append(
                _terminate_real_descendant_group_before_capture_cleanup(
                    monkeypatch, tmp_path / "capture-descendant.pid",
                )
            )
        return "OK", "AGREE"

    def observe_cleanup(*args, **kwargs):
        if worker_threads:
            cleanup_worker_states.append(tuple(
                thread.is_alive() for thread in worker_threads
            ))
        for pgid, descendant_pid in terminated_groups:
            with pytest.raises(ProcessLookupError):
                os.kill(descendant_pid, 0)
            assert not pi._process_group_exists(pgid)
        return real_cleanup(*args, **kwargs)

    monkeypatch.setattr(pi.tempfile, "mkdtemp", capture_mkdtemp)
    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    monkeypatch.setattr(pi, "bind_staged_review_inputs", bind_stage)
    monkeypatch.setattr(pi, "prepare_provider_launch_authorities", prepare_authority)
    monkeypatch.setattr(
        pi, "seal_provider_launches",
        (lambda **_kwargs: (_ for _ in ()).throw(evidence.AgyCanaryEvidenceError("seal failed")))
        if failure == "seal" else lambda **_kwargs: {"synthetic": True},
    )
    monkeypatch.setattr(
        pi, "record_provider_result",
        (lambda **_kwargs: (_ for _ in ()).throw(
            evidence.AgyCanaryEvidenceError("result seal failed")
        )) if failure == "result" else lambda **_kwargs: {"synthetic": True},
    )
    monkeypatch.setattr(pi, "capture_summary", lambda _capture: {"synthetic": True})
    monkeypatch.setattr(pi, "_default_spawn_via_provider", spawn_provider)
    monkeypatch.setattr(pi, "_cleanup_capture_launches", observe_cleanup)

    if failure is None:
        pi.invoke_board(DEFAULT_BOARD, "review", agy_canary_capture=object(), base_env={}, max_concurrency=1)
    else:
        with pytest.raises((evidence.AgyCanaryEvidenceError, OSError)):
            pi.invoke_board(DEFAULT_BOARD, "review", agy_canary_capture=object(), base_env={}, max_concurrency=1)
    assert scratches
    if failure not in {"write", "bind"}:
        assert outputs
    if failure in {"result", None}:
        assert worker_threads
        assert cleanup_worker_states
        assert all(not alive for states in cleanup_worker_states for alive in states)
    assert all(not path.exists() for path in outputs)
    assert all(not path.exists() for path in scratches)
    tombstones = {
        _cleanup_tombstone_for(authority)
        for authority in cleanup_authorities
    }
    assert tombstones
    assert all(list(path.iterdir()) == [] for path in tombstones)
    for path in tombstones:
        path.rmdir()


def test_capture_enabled_claude_uses_sibling_namespace_and_mapped_output(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    capture, authority, stage, root, output = _sibling_namespace(tmp_path)
    captured: dict[str, object] = {}
    try:
        def fake_tui(*, command, cwd, prompt, output_file, timeout_s, env, capture_output_reader, **_kwargs):
            captured["command"] = list(command)
            captured["cwd"] = cwd
            captured["prompt"] = prompt
            captured["output_file"] = output_file
            captured["env"] = dict(env)
            assert capture_output_reader() == ""
            output_file.write_text("AGREE\n", encoding="utf-8")
            assert capture_output_reader() == "AGREE\n"
            return 0, "AGREE\n", "claude_tui_file_output", ""

        monkeypatch.setattr(pi, "_under_claude_code", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(pi, "_run_claude_tui_session", fake_tui)
        monkeypatch.setattr(
            pi,
            "_claude_code_support_status",
            lambda: (_ for _ in ()).throw(AssertionError("capture must not probe Claude")),
        )
        monkeypatch.setattr(
            pi,
            "_claude_subscription_auth_ok",
            lambda *_args: (_ for _ in ()).throw(AssertionError("capture must not probe Claude auth")),
        )
        status, review = pi._exec_claude_tui_leg(
            stage,
            output,
            30,
            "artifact",
            repo_dir=tmp_path / "host-repo",
            env={"HOME": "/host-home", "XDG_CONFIG_HOME": "/host-config"},
            agy_capture=capture,
            provider_authority=authority,
        )
        assert status == "OK" and review == "AGREE\n"
        assert authority.preflights and authority.self_tests
        assert authority.preflights[0][0] == "claude"
        # Every capture read, including the TUI liveness checks, uses the authority.
        assert authority.output_reads == ["panel-claude.txt"] * 3
        command = captured["command"]
        assert isinstance(command, list)
        assert "/run/phase-loop-output/panel-claude.txt" in captured["prompt"]
        assert str(output / "panel-claude.txt") not in captured["prompt"]
        _assert_sibling_command_is_private(
            command, captured["env"], captured["prompt"],
            stage=stage, root=root, output=output,
        )
        assert captured["cwd"] == output
        assert captured["output_file"] == output / "panel-claude.txt"
    finally:
        capture.close()
        shutil.rmtree(root)
        shutil.rmtree(output)


def test_capture_claude_liveness_rejects_extra_output_without_unsafe_fallback(monkeypatch, tmp_path):
    _mock_canonical_bwrap(monkeypatch)
    capture, authority, stage, root, output = _sibling_namespace(tmp_path)
    try:
        def fake_tui(*, output_file, capture_output_reader, **_kwargs):
            output_file.write_text("UNSAFE\n", encoding="utf-8")
            (output / "forged.log").write_text("forged\n", encoding="utf-8")
            capture_output_reader()
            raise AssertionError("unsafe capture output must not be accepted")

        monkeypatch.setattr(pi, "_under_claude_code", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(pi, "_run_claude_tui_session", fake_tui)
        monkeypatch.setattr(
            pi,
            "_read_review_output",
            lambda *_args, **_kwargs: pytest.fail("capture liveness must use authority output reader"),
        )
        with pytest.raises(evidence.AgyCanaryEvidenceError, match="unsafe captured output set"):
            pi._exec_claude_tui_leg(
                stage, output, 30, "artifact", agy_capture=capture,
                provider_authority=authority,
            )
        assert authority.output_reads == ["panel-claude.txt"]
    finally:
        capture.close()
        shutil.rmtree(root)
        shutil.rmtree(output)
