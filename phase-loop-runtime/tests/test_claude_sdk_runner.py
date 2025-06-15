from dataclasses import replace
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import threading
import time
from unittest.mock import patch

import pytest

from phase_loop_runtime import claude_sdk_adapter as sdk, launcher
from phase_loop_runtime.claude_channel_sidecar import ClaudeRouteResult
from phase_loop_runtime.launcher import (
    build_launch_spec, launch_with_spec, run_auth_preflight, resolve_claude_route,
    _extract_claude_stream_json_text, _claude_permission_mode,
)
from phase_loop_runtime.models import LaunchRequest, PromptBundle, InjectionMetadata, PermissionPolicy
from phase_loop_runtime.profiles import resolve_profile_for_executor


FAKE_CLI = r'''
import json, os, sys, time, subprocess
from pathlib import Path
args = sys.argv[1:]
mode = "version" if "-v" in args or "--version" in args else "auth" if "auth" in args and "status" in args else "help" if "-h" in args or "--help" in args else "inference"
config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path(os.environ["HOME"]) / ".claude")))
settings_path = Path(args[args.index("--settings")+1]) if "--settings" in args else config / "settings.json"
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
record = {"mode": mode, "blocked_present": any(k in os.environ for k in ("XAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")),
          "memory_disabled": os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") == "1",
          "readonly": bool(os.statvfs(config).f_flag & os.ST_RDONLY),
          "strict_mcp": "--strict-mcp-config" in args, "no_persistence": "--no-session-persistence" in args,
          "allowed_tools": "--allowedTools" in args, "permission_mode": args[args.index("--permission-mode")+1] if "--permission-mode" in args else None,
          "snapshot_readonly": bool(os.statvfs(settings_path).f_flag & os.ST_RDONLY),
          "setting_sources_empty": "--setting-sources=" in args or ("--setting-sources" in args and args[args.index("--setting-sources")+1] == ""),
          "bare_sdk_version_probe": args == ["-v"],
          "probe_cwd_bound": str(Path.cwd()) == "/etc/phase-loop-sdk-probe" and bool(os.statvfs(Path.cwd()).f_flag & os.ST_RDONLY),
          "approved_settings": settings.get("env", {}).get("SDK_CONFIGURATION_MARKER") == "approved",
          "approved_project_deny": "Bash(SDK_APPROVED)" in settings.get("permissions", {}).get("deny", [])}
with open(os.environ["SDK_FAKE_RECORD"], "a") as handle:
    handle.write(json.dumps(record) + "\n")
if mode == "help":
    print("--settings --setting-sources --strict-mcp-config --no-session-persistence --permission-mode --tools --disallowedTools --json-schema --effort")
    raise SystemExit(0)
if mode == "auth":
    print(json.dumps(dict(loggedIn=True, authMethod="claude.ai", apiProvider="firstParty", subscriptionType="max")))
    raise SystemExit(0)
if mode == "version":
    print("2.1.301 (Claude Code)")
    raise SystemExit(0)
def emit(data):
    print(json.dumps(data), flush=True)
case = os.environ.get("SDK_FAKE_CASE", "success")
def value(schema, root):
    if "$ref" in schema:
        node = root
        for key in schema["$ref"].split("/")[1:]: node = node[key]
        return value(node, root)
    if "const" in schema: return schema["const"]
    if "enum" in schema: return "done" if "done" in schema["enum"] else schema["enum"][0]
    if "anyOf" in schema: return value(schema["anyOf"][0], root)
    kind = schema.get("type", "object")
    if isinstance(kind, list): kind = kind[0]
    if kind == "object": return {k: value(schema.get("properties", {}).get(k, {}), root) for k in schema.get("required", [])}
    return {"array": [], "string": "fixture", "boolean": False, "integer": 1, "number": 1, "null": None}.get(kind)
for line in sys.stdin:
    message = json.loads(line)
    if message.get("type") == "control_request":
        emit({"type": "control_response", "response": {"subtype": "success", "request_id": message["request_id"], "response": {}}})
    if message.get("type") != "user": continue
    if case != "missing_init": emit({"type": "system", "subtype": "init", "apiKeySource": "api_key" if case == "conflicting_init" else "none"})
    if case == "drift": emit({"type": "system", "subtype": "api_retry", "error": {"type": "billing_error"}})
    if case == "nested_drift": emit({"type": "system", "subtype": "api_retry", "error": {"error": {"type": "authentication_failed"}}})
    if case == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        Path(os.environ["SDK_FAKE_PID"]).write_text(str(child.pid))
        time.sleep(300)
    if case == "workspace_write":
        Path("sdk-project-artifact.txt").write_text("project remains writable")
        try:
            Path("context.md").write_text("must stay frozen")
        except OSError:
            pass
        else:
            raise AssertionError("context snapshot must be read-only")
    if case == "assistant_only":
        emit({"type":"assistant", "message":{"role":"assistant", "content":[{"type":"text", "text":"not terminal"}]}})
        raise SystemExit(0)
    if case == "process_error":
        sys.stderr.write("synthetic-private-stderr")
        raise SystemExit(7)
    schema = json.loads(args[args.index("--json-schema")+1]) if "--json-schema" in args else None
    structured = value(schema, schema) if schema else None
    if case == "invalid_closeout": structured = "invalid"
    emit({"type":"result", "subtype":"success", "is_error":case in {"rate_limit", "terminal_auth"}, "duration_ms":1, "duration_api_ms":1,
          "num_turns":1, "session_id":"synthetic", "result":"completed", "structured_output":structured,
          "errors":["oauth_org_not_allowed"] if case == "terminal_auth" else None,
          "api_error_status":429 if case == "rate_limit" else None})
'''


def request(repo, action="execute", mode="solo"):
    return LaunchRequest(
        executor="claude", action=action, repo=repo, roadmap=repo / "roadmap.md", phase=None, plan=None,
        model_selection=resolve_profile_for_executor(action=action, executor="claude"),
        prompt_bundle=PromptBundle(workflow_command="fixture", body="private fixture prompt", injection_mode="inline", product_action=action),
        injection_metadata=InjectionMetadata(harness_target="claude", injection_mode="inline"),
        permission_policy=PermissionPolicy(sandbox_mode="workspace-write"), claude_execution_mode=mode,
    )


@pytest.fixture
def context(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config = home / ".claude"
    config.mkdir(parents=True)
    store = config / ".credentials.json"
    store.write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic-fixture",
        "scopes": ["user:inference"], "subscriptionType": "max", "expiresAt": (time.time()+7200)*1000}}))
    store.chmod(0o600)
    binary = tmp_path / "bin"
    binary.mkdir()
    cli = binary / "claude"
    cli.write_text("#!" + sys.executable + "\n" + FAKE_CLI)
    cli.chmod(0o700)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name in tuple(os.environ):
        if name.startswith("ANTHROPIC_") or name.startswith("CLAUDE_CODE_OAUTH") or name == "CLAUDE_CONFIG_DIR":
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("PHASE_LOOP_CLAUDE_ROUTE", "sdk")
    monkeypatch.setenv("SDK_FAKE_RECORD", str(tmp_path / "observations.jsonl"))
    return repo, config, tmp_path / "observations.jsonl"


def binding_available():
    if sys.platform != "linux" or not Path("/usr/bin/bwrap").exists():
        pytest.skip("Linux mount binding unavailable")
    result = subprocess.run(["/usr/bin/bwrap", "--ro-bind", "/", "/", "--unshare-user", "--", "/usr/bin/true"], capture_output=True)
    if result.returncode:
        pytest.skip("Unprivileged mount binding unavailable")
    if not sdk.sdk_available():
        pytest.skip("Install the pinned claude-sdk extra to exercise the real transport")


def test_explicit_aliases_and_defaults():
    for alias in ("sdk", "claude_sdk", "claude-sdk"):
        route = resolve_claude_route(alias, env={})
        assert (route.route, route.reason, route.warnings) == ("claude_sdk", "explicit_sdk", ())
    assert resolve_claude_route(None, env={}).route == "claude_channel"
    assert resolve_claude_route(None, env={"CI": "true"}).error
    assert resolve_claude_route("print", env={}).warnings


@pytest.mark.parametrize("action,mode", [("review", "solo"), ("execute", "subagent"), ("plan", "agent_team"), ("plan", "subagent")])
def test_requested_scope_rejected_before_degrade(context, action, mode):
    repo, _, record = context
    spec = build_launch_spec(request(repo, action, mode))
    assert not spec.available
    assert spec.reason == "sdk_solo_runner_only"
    assert not record.exists()


def test_dry_run_offline_and_no_prompt_in_helper_argv(context):
    repo, _, record = context
    spec = build_launch_spec(request(repo))
    assert "private fixture prompt" not in " ".join(spec.command)
    with patch.object(sdk, "bound_command", side_effect=AssertionError("must be offline")):
        result = launch_with_spec(spec, dry_run=True)
    assert result.dry_run
    assert spec.to_json()["claude_billing_posture"] == "unknown"
    assert not record.exists()


def test_helper_uses_the_trusted_installation_from_any_cwd(context, monkeypatch):
    binding_available()
    repo, _, record = context
    marker = repo / "cwd-package-ran"
    package = repo / "phase_loop_runtime"
    package.mkdir()
    (package / "__init__.py").write_text(f"from pathlib import Path; Path({str(marker)!r}).touch()\n")
    (package / "claude_sdk_adapter.py").write_text("raise SystemExit(7)\n")
    monkeypatch.setenv("PYTHONPATH", str(repo))
    spec = build_launch_spec(request(repo))
    assert run_auth_preflight(spec).ok
    result = launch_with_spec(spec)
    assert not result.failed, result.claude_route_result or result.output
    assert not marker.exists()
    assert any(json.loads(line)["mode"] == "inference" for line in record.read_text().splitlines())


@pytest.mark.parametrize("kind", ["team", "enterprise", "", None, {}, []])
def test_offline_context_class_before_any_probe(context, kind):
    repo, config, record = context
    path = config / ".credentials.json"
    raw = json.loads(path.read_text())
    raw["claudeAiOauth"]["subscriptionType"] = kind
    path.write_text(json.dumps(raw))
    with patch.object(sdk, "_probe", side_effect=AssertionError("no probe")):
        assert not run_auth_preflight(build_launch_spec(request(repo))).ok
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["billing_posture"] == "unknown"
    assert not record.exists()


@pytest.mark.parametrize("location,document", [
    ("user", {"env": {"ANTHROPIC_BASE_URL": "synthetic"}}),
    ("global", {"apiKeyHelper": "synthetic"}),
    ("project", {"env": {"ANTHROPIC_API_KEY": "synthetic"}}),
    ("global", {"profiles": {"example": {"type": "user_oauth"}}}),
    ("user", {"env": {"CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR": "9"}}),
    ("user", {"env": {"CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "synthetic"}}),
    ("user", {"env": {"ANTHROPIC_UNRECOGNIZED_OVERRIDE": "synthetic"}}),
    ("user", {"env": ["invalid"]}),
    ("user", {"env": {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}}),
    ("global", {"env": {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}}),
])
def test_settings_refused_before_probe(context, location, document):
    repo, config, record = context
    path = {"user": config / "settings.json", "global": config.parent / ".claude.json", "project": repo / ".claude/settings.json"}[location]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert not record.exists()


def test_caller_credential_rejection_precedes_scrub(context, monkeypatch):
    repo, _, record = context
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_caller_credential_refused"
    assert not record.exists()


def test_actual_sdk_probe_and_inference_env(context, monkeypatch):
    binding_available()
    repo, _, record = context
    monkeypatch.setenv("XAI_API_KEY", "synthetic-scrub-control")
    before = dict(os.environ)
    spec = build_launch_spec(request(repo))
    result = launch_with_spec(spec)
    assert not result.failed, result.claude_route_result or result.output
    assert result.claude_route_result["billing_posture"] == "subscription_included"
    assert _extract_claude_stream_json_text(result.output)
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    assert {row["mode"] for row in rows} == {"help", "auth", "version", "inference"}
    assert any(row["bare_sdk_version_probe"] for row in rows)
    assert all(not row["blocked_present"] and row["memory_disabled"] and row["readonly"] for row in rows)
    inference = next(row for row in rows if row["mode"] == "inference")
    assert inference["strict_mcp"] and inference["no_persistence"]
    assert inference["setting_sources_empty"]
    assert inference["snapshot_readonly"]
    assert not inference["allowed_tools"]
    assert inference["permission_mode"] == _claude_permission_mode("execute", False)
    versions = [json.loads(line) for line in result.output.splitlines() if line.startswith('{"type":"sdk_version"')]
    assert versions[0]["adapter_sha256"] == hashlib.sha256(Path(sdk.__file__).read_bytes()).hexdigest()
    assert dict(os.environ) == before
    assert "synthetic-fixture" not in result.output
    assert "private fixture prompt" not in " ".join(result.command)
    assert "/usr/bin/bwrap" not in result.command
    assert not any(part == str(Path(os.environ["HOME"]) / "bin") for part in result.command)


def test_scrub_removal_negative_control(context, monkeypatch):
    binding_available()
    repo, _, _ = context
    monkeypatch.setenv("XAI_API_KEY", "synthetic-scrub-control")
    with patch.object(sdk, "scrub_subscription_env", side_effect=lambda env: dict(env)):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed


@pytest.mark.parametrize("case", ["missing_init", "conflicting_init", "drift", "nested_drift", "terminal_auth", "rate_limit", "assistant_only", "invalid_closeout", "process_error"])
def test_terminal_and_init_failures(context, monkeypatch, case):
    binding_available()
    repo, _, _ = context
    monkeypatch.setenv("SDK_FAKE_CASE", case)
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["status"] != "done"
    assert result.claude_route_result["billing_posture"] == "unknown"
    assert "synthetic-private-stderr" not in result.output
    if case == "rate_limit":
        assert result.claude_route_result["event_id"] == "sdk_provider_rate_limited"
    if case == "terminal_auth":
        assert result.claude_route_result["event_id"] == "sdk_auth_drift"


def test_dependency_missing_and_no_cli_are_clean_refusals(context):
    repo, _, record = context
    with patch.object(sdk, "sdk_available", return_value=False):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.claude_route_result["event_id"] == "sdk_dependency_missing"
    with patch.object(sdk, "sdk_available", return_value=True), patch.object(sdk.shutil, "which", return_value=None):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.claude_route_result["event_id"] == "sdk_cli_missing"
    assert not record.exists()


def test_route_receipt_roundtrip():
    receipt = sdk._receipt("done", "sdk_completed", proven=True)
    assert ClaudeRouteResult(**{**receipt, "artifacts": tuple(receipt["artifacts"]),
                               "warnings": tuple(receipt["warnings"]), "evidence_refs": tuple(receipt["evidence_refs"])}).to_json() == receipt
    assert receipt["text"] == ""


@pytest.mark.parametrize("action", ["plan", "execute", "repair"])
def test_permission_mode_parity(context, action):
    binding_available()
    repo, _, record = context
    result = launch_with_spec(build_launch_spec(request(repo, action)))
    assert not result.failed, result.claude_route_result or result.output
    row = next(json.loads(line) for line in record.read_text().splitlines() if json.loads(line)["mode"] == "inference")
    assert row["permission_mode"] == _claude_permission_mode(action, False)
    assert not row["allowed_tools"]


def test_private_snapshot_survives_source_changes(context):
    binding_available()
    repo, config, _ = context
    original = config.parent / ".claude.json"
    original.write_text("{}")
    with sdk.bound_command([sys.executable, "-c", "import json,os; from pathlib import Path; print(json.dumps(json.loads((Path(os.environ[\"HOME\"])/\".claude.json\").read_text())))"], repo, os.environ) as (command, env):
        # The added helper flags are not Python flags for this observation.
        command = command[:-4]
        original.write_text(json.dumps({"apiKeyHelper": "synthetic"}))
        result = subprocess.run(command, env=env, cwd=repo, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {}


def test_snapshot_under_home_remains_readonly(context, monkeypatch):
    binding_available()
    repo, config, record = context
    scratch = config.parent / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(sdk.tempfile, "tempdir", str(scratch))
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output
    row = next(json.loads(line) for line in record.read_text().splitlines() if json.loads(line)["mode"] == "inference")
    assert row["snapshot_readonly"]


@pytest.mark.parametrize("action", ["plan", "execute"])
@pytest.mark.parametrize("log_location", ["none", "repo"])
def test_context_file_bundle_without_log(context, action, log_location, monkeypatch):
    binding_available()
    repo, _, _ = context
    launch_request = request(repo, action)
    launch_request = replace(launch_request, prompt_bundle=replace(launch_request.prompt_bundle,
        fallback_mode="context_file", expected_skill_pack=("claude-execute-phase",)))
    spec = build_launch_spec(launch_request)
    assert spec.delivery_mode == "context_file"
    skill = repo / "fixture-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: claude-execute-phase\n---\nFollow the fixture workflow.\n")
    log_path = None if log_location == "none" else repo / "output.log"
    if log_path:
        monkeypatch.setenv("SDK_FAKE_CASE", "workspace_write")
    with patch("phase_loop_runtime.injection.resolve_source_skill_dir", return_value=skill):
        result = launch_with_spec(spec, log_path=log_path)
    assert not result.failed, result.claude_route_result or result.output
    assert not any("__PHASE_LOOP_" in part for part in result.command)
    assert "--context-prompt" not in result.command
    assert result.log_path == (str(log_path) if log_path else None)
    assert "--context-dir" in result.command
    if log_path:
        assert (repo / "sdk-project-artifact.txt").read_text() == "project remains writable"


@pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
def test_project_allow_rules_require_bound_trust(context, name):
    binding_available()
    repo, config, record = context
    settings = repo / ".claude" / name
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Read"]}}))
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.claude_route_result["event_id"] == "sdk_project_trust_unproven"
    assert not record.exists()
    (config.parent / ".claude.json").write_text(json.dumps({"projects": {str(repo.resolve()): {"hasTrustDialogAccepted": True}}}))
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output


def test_project_permission_modes_are_not_elevated(context):
    binding_available()
    repo, _, record = context
    settings = repo / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.claude_route_result["event_id"] == "sdk_project_settings_scope_unsupported"
    assert not record.exists()


def test_all_probes_and_inference_share_frozen_settings(context):
    binding_available()
    repo, config, record = context
    settings = repo / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"deny": ["Bash(SDK_APPROVED)"]}}))
    user = config / "settings.json"
    user.write_text(json.dumps({"env": {"SDK_CONFIGURATION_MARKER": "approved", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}}))
    original = sdk.bound_command

    @contextlib.contextmanager
    def change_sources(*args, **kwargs):
        with original(*args, **kwargs) as bound:
            settings.write_text(json.dumps({"env": {"ANTHROPIC_API_KEY": "synthetic"}}))
            user.write_text(json.dumps({"env": {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}}))
            yield bound

    with patch.object(sdk, "bound_command", side_effect=change_sources):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    assert any(row["mode"] == "auth" for row in rows)
    assert any(row["bare_sdk_version_probe"] for row in rows)
    assert all(row["approved_settings"] and row["approved_project_deny"] and row["snapshot_readonly"] for row in rows)
    assert all(row["probe_cwd_bound"] for row in rows if row["mode"] != "inference")


def test_home_symlinks_preserve_bound_targets(context):
    binding_available()
    repo, config, _ = context
    home = config.parent
    (home / "dangling").symlink_to("missing")
    (home / "credential-alias").symlink_to(".claude.json")
    (home / ".claude.json").write_text("{}")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output
    assert not any("credential-alias" in part or "dangling" in part for part in result.command)
    with sdk.bound_command([sys.executable, "-c", "import os; from pathlib import Path; p=Path(os.environ['HOME']); print((p/'credential-alias').read_text()); assert (p/'dangling').is_symlink()"], repo, os.environ) as (command, env):
        (home / ".claude.json").write_text(json.dumps({"apiKeyHelper": "synthetic"}))
        observed = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    assert observed.stdout.strip() == "{}"


@pytest.mark.parametrize("layout", ["import", "nested_rule", "scoped_rule", "symlink", "encoding"])
def test_instruction_layouts_fail_before_probes(context, layout):
    binding_available()
    repo, _, record = context
    instruction = repo / "CLAUDE.md"
    if layout == "import":
        instruction.write_text("See @instructions.md\n")
    elif layout == "nested_rule":
        path = repo / ".claude/rules/nested/rule.md"
        path.parent.mkdir(parents=True)
        path.write_text("Nested rule\n")
    elif layout == "scoped_rule":
        path = repo / ".claude/rules/rule.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\npaths: ['src/**']\n---\nScoped rule\n")
    elif layout == "symlink":
        secret = repo.parent / "synthetic-private-input"
        secret.write_text("synthetic-credential-marker")
        instruction.symlink_to(secret)
    else:
        instruction.write_bytes(b"\xff")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed and result.claude_route_result["status"] == "blocked"
    assert result.claude_route_result["event_id"] == ("sdk_context_uninspectable" if layout == "encoding" else "sdk_instruction_layout_unsupported")
    assert not record.exists()
    assert "synthetic-credential-marker" not in " ".join(result.command) + result.output


def test_user_instructions_under_home_are_not_duplicated(context):
    _, config, _ = context
    repo = config.parent / "project"
    repo.mkdir()
    (config / "CLAUDE.md").write_text("USER_INSTRUCTION\n")
    rules = config / "rules"
    rules.mkdir()
    (rules / "a.md").write_text("USER_RULE\n")
    text = sdk._instructions(config, repo)
    assert text.count("USER_INSTRUCTION") == text.count("USER_RULE") == 1


@pytest.mark.parametrize("name", ["CLAUDE.md", ".claude/CLAUDE.md"])
def test_plain_instruction_syntax_is_preserved(context, name):
    binding_available()
    repo, config, _ = context
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "---\nPLAIN_ONCE security@example.com\n`@README` and ``@other``\n```python\n@decorator\n```\n~~~text\n@literal\n~~~\n"
    path.write_text(text)
    assert sdk._instructions(config, repo).count(text) == 1
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output


def test_unconditional_rule_frontmatter_is_removed(context):
    binding_available()
    repo, config, _ = context
    path = repo / ".claude/rules/plain.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: unused metadata\n---\nUNCONDITIONAL_RULE\n")
    text = sdk._instructions(config, repo)
    assert text.count("UNCONDITIONAL_RULE") == 1
    assert "description:" not in text
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output


@pytest.mark.parametrize("name", ["AGENTS.md", "src/AGENTS.md", "src/CLAUDE.md", "src/CLAUDE.local.md",
                                  "src/.claude/CLAUDE.md", "src/.claude/rules/a.md", "src/.claude/rules/deeper/a.md"])
def test_dynamic_instruction_sources_refuse_before_probes(context, name):
    binding_available()
    repo, _, record = context
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Dynamically discovered instruction\n")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert result.failed and not record.exists()


@pytest.mark.parametrize("name", ["AGENTS.md", ".claude/AGENTS.md"])
def test_ancestor_agents_refuse_before_probes(context, name):
    binding_available()
    repo, _, record = context
    path = repo.parent / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Ancestor project instruction\n")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert result.failed and not record.exists()


def test_config_agents_outside_project_ancestry_does_not_refuse(context):
    binding_available()
    repo, config, record = context
    (config / "AGENTS.md").write_text("Unrelated config file\n")
    text = "---\nsecurity@example.com\n```python\n@decorator\n```\n"
    (repo / "CLAUDE.md").write_text(text)
    assert sdk._instructions(config, repo) == text
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output
    assert any(json.loads(line)["mode"] == "inference" for line in record.read_text().splitlines())


def test_config_agents_refuses_when_home_is_project_ancestor(context):
    binding_available()
    _, config, record = context
    repo = config.parent / "project"
    repo.mkdir()
    (config / "AGENTS.md").write_text("Ancestor project instruction\n")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert result.failed and not record.exists()


def test_managed_memory_control_conflict_refuses(context):
    _, config, _ = context
    managed = config.parent / "managed-fixture"
    managed.mkdir()
    (managed / "managed-settings.json").write_text(json.dumps({"env": {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}}))
    with patch.object(sdk, "Path", side_effect=lambda value: managed if value == "/etc/claude-code" else Path(value)):
        with pytest.raises(sdk.SDKRefused, match="sdk_settings_refused"):
            sdk._managed_settings()


def test_unbound_direct_helper_refuses(context):
    repo, config, _ = context
    completed = subprocess.run([sys.executable, "-m", "phase_loop_runtime.claude_sdk_adapter", "--auth-only",
        "--cli-path", str(repo.parent / "bin/claude"), "--cwd", str(repo), "--instructions-file", str(config / "unused")],
        cwd=repo, capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert "sdk_context_unbound" in completed.stdout


class Lease:
    generation = "sdk-qualification"

    def __init__(self, fd):
        self.fd = fd

    def fileno(self):
        return self.fd


def cancelled_launch(spec, root, *, wait_for=None):
    """Terminate the real lease supervisor after its SDK descendant is ready."""
    fd = os.open(root / "lease.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    spawned = []
    outcome = {}
    popen = launcher.subprocess.Popen

    def capture(*args, **kwargs):
        child = popen(*args, **kwargs)
        if any("lease_supervisor.py" in str(part) for part in args[0]):
            spawned.append(child)
        return child

    def run():
        try:
            outcome["result"] = launch_with_spec(spec, lease_authority=Lease(fd),
                log_path=root / "cancel.log", heartbeat_interval_seconds=1)
        except BaseException as exc:
            outcome["error"] = type(exc).__name__

    thread = threading.Thread(target=run, daemon=True)
    try:
        with patch.object(launcher.subprocess, "Popen", side_effect=capture):
            thread.start()
            deadline = time.monotonic() + 90
            while thread.is_alive():
                ready = wait_for.exists() if wait_for is not None else (
                    (root / "cancel.log").exists() and '"sdk_progress"' in (root / "cancel.log").read_text())
                if ready and spawned:
                    break
                assert time.monotonic() < deadline, "SDK did not reach the cancellation boundary"
                time.sleep(0.05)
            assert thread.is_alive() and spawned, outcome
            os.kill(spawned[0].pid, signal.SIGTERM)
            thread.join(20)
            assert not thread.is_alive(), "SDK supervisor did not finish cleanup"
        assert "error" not in outcome, outcome
        result = outcome["result"]
        assert result.failed
        assert result.supervisor_receipt is not None
        assert result.supervisor_receipt["terminal_status"] == "blocked"
        assert spawned[0].poll() is not None
        return result
    finally:
        if thread.is_alive() and spawned and spawned[0].poll() is None:
            spawned[0].terminate()
            thread.join(20)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_supervised_cancellation_and_lease_cleanup(context, monkeypatch):
    binding_available()
    repo, _, _ = context
    marker = repo / "descendant.pid"
    monkeypatch.setenv("SDK_FAKE_CASE", "hang")
    monkeypatch.setenv("SDK_FAKE_PID", str(marker))
    result = cancelled_launch(build_launch_spec(request(repo)), repo, wait_for=marker)
    assert result.claude_route_result["status"] != "done"


def test_no_log_stall_and_descendant_cleanup(context, monkeypatch):
    binding_available()
    repo, _, _ = context
    marker = repo / "descendant.pid"
    monkeypatch.setenv("SDK_FAKE_CASE", "hang")
    monkeypatch.setenv("SDK_FAKE_PID", str(marker))
    idle = lambda *args, **kwargs: 0.0 if marker.exists() else 100.0
    with patch("phase_loop_runtime.observability._process_cpu_percent", side_effect=idle), \
         patch("phase_loop_runtime.observability._process_group_cpu_percent", side_effect=idle):
        result = launch_with_spec(replace(build_launch_spec(request(repo)), launch_timeout_seconds=20),
            log_path=None, heartbeat_interval_seconds=0, quiet_warning_seconds=0, quiet_blocker_seconds=0)
    assert marker.exists()
    assert result.stalled
    assert result.cleanup_evidence
    assert result.log_path is None


@pytest.mark.host_seat_credentials
def test_live_subscription_qualification(tmp_path, monkeypatch):
    if os.environ.get("PHASE_LOOP_SDK_LIVE_PROOF") != "1":
        pytest.skip("Explicit disposable live proof is opt-in")
    monkeypatch.setenv("PHASE_LOOP_CLAUDE_ROUTE", "sdk")
    binding_available()
    if not sdk.sdk_available():
        pytest.skip("SDK extra unavailable")
    try:
        sdk.admit_context(os.environ, tmp_path)
    except sdk.SDKRefused:
        pytest.skip("Supported personal subscription context unavailable")
    repo = tmp_path / "live-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    # Only metadata leaves this test; provider output stays in the disposable repo.
    results = []
    for action in ("plan", "execute"):
        launch_request = request(repo, action)
        bundle = replace(launch_request.prompt_bundle,
                         body="Write a small SDK qualification artifact in this disposable repository, then return a valid schema closeout. No delegation or external messages.")
        spec = build_launch_spec(replace(launch_request, prompt_bundle=bundle, launch_timeout_seconds=180))
        assert spec.claude_route == "claude_sdk" and spec.available
        result = launch_with_spec(spec, log_path=repo / action / "output.log")
        assert not result.failed, "live SDK qualification failed (inspect private disposable output)"
        versions = [json.loads(line) for line in result.output.splitlines() if line.startswith('{"type":"sdk_version"')]
        results.append({"action": action, "versions": versions, "route": result.claude_route_result,
                        "model": spec.selected_model, "effort": spec.selected_effort,
                        "terminal_success": not result.failed, "cleanup": result.cleanup_evidence})
    cancellation_request = request(repo)
    cancellation_request = replace(cancellation_request,
        prompt_bundle=replace(cancellation_request.prompt_bundle,
            body="Use Bash to sleep for 120 seconds before writing a tiny qualification artifact. This disposable run tests cancellation. No delegation or external messages."),
        launch_timeout_seconds=180)
    cancellation_spec = build_launch_spec(cancellation_request)
    assert cancellation_spec.claude_route == "claude_sdk" and cancellation_spec.available
    cancellation = cancelled_launch(cancellation_spec, repo)
    target = Path(__file__).resolve().parents[2] / "plans/evidence/claude-sdk-stage3/qualification.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"status": "passed", "turns": results,
        "cancellation": {"terminal_status": cancellation.supervisor_receipt["terminal_status"],
                         "supervisor_reaped": True}}, indent=2) + "\n")
