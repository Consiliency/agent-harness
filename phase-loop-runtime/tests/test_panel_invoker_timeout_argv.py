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
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_canary_evidence as evidence
from phase_loop_runtime import panel_invoker as pi


def _mock_canonical_bwrap(monkeypatch) -> None:
    monkeypatch.setattr(evidence, "_canonical_bwrap", lambda: Path("/usr/bin/bwrap"))


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
        output = tmp_path / f"provider-output-{provider}"
        output.mkdir()
        authority = SimpleNamespace(
            namespace=SimpleNamespace(provider_output=output),
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
            self.namespace = SimpleNamespace(provider_output=output)
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
                f"phase-loop-result-output-{provider}-{os.getpid()}-{tmp_path.name}"
            )
            output.mkdir(mode=0o700)
            runtime = {"provider": provider, "sha256": provider[0] * 64}
            placeholders = []
            projection = {"provider": provider, "records": []}
            authority = Authority(
                provider, output, runtime, placeholders, projection,
            )
            launches[seat_key] = (authority, stage, scratch)
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
        authority, stage, scratch = launches[seat_key]
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
            for launch_authority, _stage, scratch_path in launches.values()
        )
    finally:
        capture.close()
        pi._cleanup_capture_launches(launches)
        shutil.rmtree(root)


@pytest.mark.parametrize("failure", ["prepare", "seal", "result", None])
def test_capture_setup_always_reclaims_scratch_and_provider_outputs(monkeypatch, tmp_path, failure):
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    outputs: list[Path] = []
    scratches: list[Path] = []
    calls = 0

    def bind_stage(**_kwargs):
        return None

    def prepare_authority(*, stage: Path, providers: tuple[str, ...], **_kwargs):
        nonlocal calls
        calls += 1
        scratches.append(stage.parent)
        if failure == "prepare" and calls == 2:
            raise evidence.AgyCanaryEvidenceError("second authority failed")
        output = tmp_path / f"output-{providers[0]}"
        output.mkdir()
        outputs.append(output)
        return {providers[0]: SimpleNamespace(namespace=SimpleNamespace(provider_output=output))}

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
    monkeypatch.setattr(pi, "_default_spawn_via_provider", lambda *_args, **_kwargs: ("OK", "AGREE"))

    if failure is None:
        pi.invoke_board(DEFAULT_BOARD, "review", agy_canary_capture=object(), base_env={}, max_concurrency=1)
    else:
        with pytest.raises(evidence.AgyCanaryEvidenceError):
            pi.invoke_board(DEFAULT_BOARD, "review", agy_canary_capture=object(), base_env={}, max_concurrency=1)
    assert outputs and scratches
    assert all(not path.exists() for path in outputs)
    assert all(not path.exists() for path in scratches)


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
