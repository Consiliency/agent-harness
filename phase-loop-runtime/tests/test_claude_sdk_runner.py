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
          "linked_instructions": "--append-system-prompt" in args and all(marker in args[args.index("--append-system-prompt")+1] for marker in ("LINKED_PARENT", "LINKED_DEPENDENCY")),
          "changed_instructions": any("CHANGED_INSTRUCTION" in arg for arg in args),
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
    monkeypatch.setattr("phase_loop_runtime.sandbox_policy._MOUNTINFO", Path("/proc/self/mountinfo"))
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


def test_parser_import_failure_refuses_before_probes(context):
    binding_available()
    repo, _, record = context
    with patch.dict(sys.modules, {"markdown_it": None}):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_dependency_missing"
    assert not record.exists()


@pytest.mark.parametrize("parser_version", [None, "3.0.0", "4.2.0"])
def test_sdk_availability_requires_the_pinned_optional_parser(parser_version):
    def version(name):
        if name == "claude-agent-sdk":
            return sdk.SDK_VERSION
        assert name == "markdown-it-py"
        if parser_version is None:
            raise sdk.importlib.metadata.PackageNotFoundError(name)
        return parser_version

    with patch.object(sdk.importlib.metadata, "version", side_effect=version):
        assert sdk.sdk_available() is (parser_version == "4.2.0")


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


@pytest.mark.parametrize("under_home", [False, True])
def test_linked_user_instructions_reach_sdk_as_frozen_content(context, under_home):
    binding_available()
    repo, config, record = context
    if under_home:
        repo = config.parent / "project"
        repo.mkdir()
    source = config.parent / "dotfiles"
    source.mkdir(mode=0o775)
    source.chmod(0o775)
    assert source.stat().st_mode & 0o777 == 0o775
    (source / "CLAUDE.md").write_text("LINKED_PARENT\n@AGENTS.md\n")
    (source / "AGENTS.md").write_text("LINKED_DEPENDENCY\n")
    for name in ("CLAUDE.md", "AGENTS.md"):
        (config / name).symlink_to(source / name)
    assert sdk._instructions(config, repo) == "LINKED_PARENT\n@AGENTS.md\n\n\nLINKED_DEPENDENCY\n"
    original = sdk.bound_command

    @contextlib.contextmanager
    def change_sources(*args, **kwargs):
        with original(*args, **kwargs) as bound:
            (source / "AGENTS.md").write_text("CHANGED_INSTRUCTION\n")
            (config / "CLAUDE.md").unlink()
            (config / "CLAUDE.md").symlink_to(source / "AGENTS.md")
            yield bound

    with patch.object(sdk, "bound_command", side_effect=change_sources):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert not result.failed, result.claude_route_result or result.output
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    assert any(row["mode"] == "auth" for row in rows)
    assert any(row["mode"] == "inference" and row["linked_instructions"] for row in rows)
    assert not any(row["changed_instructions"] for row in rows)
    assert "LINKED_DEPENDENCY" not in result.output + " ".join(result.command)


@pytest.mark.parametrize("fenced_candidate", [False, True])
def test_user_import_order_dedup_and_literals(context, fenced_candidate):
    repo, config, _ = context
    parent = 'PARENT\n@one.md @two.md\nsecurity@example.com `@ignored`\n```\n@ignored\n```\n'
    if not fenced_candidate:
        parent = parent.replace("\n@ignored\n", "\nordinary example\n")
    (config / "CLAUDE.md").write_text(parent)
    (config / "one.md").write_text("ONE\n@shared.md\n")
    (config / "two.md").write_text("TWO\n@shared.md\n")
    (config / "shared.md").write_text("SHARED\n")
    if fenced_candidate:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
    else:
        assert sdk._instructions(config, repo) == "\n\n".join([parent, "ONE\n@shared.md\n", "SHARED\n", "TWO\n@shared.md\n"])


@pytest.mark.parametrize("edges", [4, 5])
def test_user_import_depth_bound(context, edges):
    repo, config, _ = context
    for index in range(edges + 1):
        name = "CLAUDE.md" if index == 0 else f"{index}.md"
        (config / name).write_text(f"@{index + 1}.md\n" if index < edges else "LEAF\n")
    if edges == 4:
        assert "LEAF" in sdk._instructions(config, repo)
    else:
        with pytest.raises(sdk.SDKRefused):
            sdk._instructions(config, repo)


@pytest.mark.parametrize("layout", ["dangling", "cycle", "import_cycle", "directory", "fifo", "encoding", "oversize", "escaped", "quoted_suffix", "ambiguous"])
def test_invalid_user_instruction_dependencies_refuse_before_probes(context, layout):
    binding_available()
    repo, config, record = context
    parent = config / "CLAUDE.md"
    parent.write_text("@dependency.md\n")
    dependency = config / "dependency.md"
    if layout == "dangling":
        dependency.symlink_to("missing")
    elif layout == "cycle":
        dependency.symlink_to("dependency.md")
    elif layout == "import_cycle":
        dependency.write_text("@CLAUDE.md\n")
    elif layout == "directory":
        dependency.mkdir()
    elif layout == "fifo":
        os.mkfifo(dependency)
    elif layout == "encoding":
        dependency.write_bytes(b"\xff")
    elif layout == "oversize":
        with dependency.open("wb") as stream:
            stream.truncate((32 << 20) + 1)
    elif layout in {"escaped", "quoted_suffix"}:
        dependency.write_text("TRUNCATED_IMPORT\n")
        parent.write_text('@dependency.md\\ suffix\n' if layout == "escaped" else '@dependency.md"suffix\n')
    else:
        source = config.parent / "dotfiles"
        source.mkdir()
        (source / "CLAUDE.md").write_text("@dependency.md\n")
        (source / "dependency.md").write_text("CANONICAL_DEPENDENCY\n")
        dependency.write_text("DIFFERENT_LOGICAL_DEPENDENCY\n")
        parent.unlink()
        parent.symlink_to(source / "CLAUDE.md")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed and result.claude_route_result["status"] == "blocked"
    assert result.claude_route_result["event_id"] == ("sdk_context_uninspectable" if layout == "encoding" else "sdk_instruction_layout_unsupported")
    assert not record.exists()


@pytest.mark.parametrize("mutation", ["inplace", "alias", "chain"])
def test_user_instruction_capture_rejects_concurrent_replacement(context, mutation):
    repo, config, _ = context
    source = config / "source.md"
    source.write_text("ORIGINAL\n")
    alias = config / "CLAUDE.md"
    middle = config / "middle.md"
    middle.symlink_to(source)
    alias.symlink_to(middle if mutation == "chain" else source)
    original = os.fstat
    calls = 0

    def replace_during_capture(fd):
        nonlocal calls
        calls += 1
        result = original(fd)
        if calls == 1:
            if mutation == "inplace":
                source.write_text("CHANGED_INSTRUCTION\n")
            else:
                target = middle if mutation == "chain" else alias
                before = target.lstat()
                target.unlink()
                target.symlink_to(source)
                os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 1000), follow_symlinks=False)
        return result

    with patch.object(os, "fstat", side_effect=replace_during_capture):
        with pytest.raises(sdk.SDKRefused):
            sdk._instructions(config, repo)


@pytest.mark.parametrize("side", ["logical", "canonical"])
def test_relative_import_target_remains_bound_until_capture(context, side):
    binding_available()
    repo, config, record = context
    source = config.parent / "dotfiles"
    source.mkdir()
    (source / "CLAUDE.md").write_text("@AGENTS.md\n")
    original_target = source / "original.md"
    replacement = source / "replacement.md"
    original_target.write_text("ORIGINAL\n")
    replacement.write_text("REPLACEMENT\n")
    logical = config / "AGENTS.md"
    canonical = source / "AGENTS.md"
    for path in (logical, canonical):
        path.symlink_to(original_target)
    (config / "CLAUDE.md").symlink_to(source / "CLAUDE.md")
    original_resolve = Path.resolve
    changed = False

    def retarget_after_validation(path, *args, **kwargs):
        nonlocal changed
        resolved = original_resolve(path, *args, **kwargs)
        if path == canonical and not changed:
            changed = True
            target = logical if side == "logical" else canonical
            target.unlink()
            target.symlink_to(replacement)
        return resolved

    with patch.object(Path, "resolve", retarget_after_validation):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert changed and result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("shallow_first", [True, False])
def test_repeated_subtree_depth_is_checked_in_every_order(context, shallow_first):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text("@shared.md @one.md\n" if shallow_first else "@one.md @shared.md\n")
    for name, text in {"one.md": "@two.md\n", "two.md": "@three.md\n", "three.md": "@shared.md\n",
                       "shared.md": "@leaf.md\n", "leaf.md": "LEAF\n"}.items():
        (config / name).write_text(text)
    with pytest.raises(sdk.SDKRefused):
        sdk._instructions(config, repo)


def test_repeated_alias_validates_transitive_relative_imports(context):
    repo, config, _ = context
    source = config / "source"
    other = config / "other"
    source.mkdir()
    other.mkdir()
    (config / "CLAUDE.md").write_text("@source/parent.md @other/parent.md\n")
    (source / "parent.md").write_text("@middle.md\n")
    (source / "middle.md").write_text("@child.md\n")
    (source / "child.md").write_text("ORIGINAL\n")
    (other / "child.md").write_text("DIFFERENT\n")
    for name in ("parent.md", "middle.md"):
        (other / name).symlink_to(source / name)
    with pytest.raises(sdk.SDKRefused):
        sdk._instructions(config, repo)


@pytest.mark.parametrize("repeat", [False, True])
@pytest.mark.parametrize("at_boundary", [False, True])
def test_user_capture_total_read_budget(context, monkeypatch, repeat, at_boundary):
    repo, config, _ = context
    parent = "@a.md @a.md\n" if repeat else "@a.md @b.md\n"
    (config / "CLAUDE.md").write_text(parent)
    for name in ("a.md", "b.md"):
        (config / name).write_text("BODY\n")
    monkeypatch.setattr(sdk, "_INSTRUCTION_CAPTURE_BYTES", len(parent.encode()) + 10 - (not at_boundary))
    if at_boundary:
        assert "BODY" in sdk._instructions(config, repo)
    else:
        with pytest.raises(sdk.SDKRefused):
            sdk._instructions(config, repo)


@pytest.mark.parametrize("repeat", [False, True])
@pytest.mark.parametrize("at_boundary", [False, True])
def test_user_capture_visit_budget(context, monkeypatch, repeat, at_boundary):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text("@a.md @a.md @a.md\n" if repeat else "@a.md @b.md @c.md\n")
    for name in ("a.md", "b.md", "c.md"):
        (config / name).write_text("")
    monkeypatch.setattr(sdk, "_INSTRUCTION_CAPTURE_VISITS", 4 if at_boundary else 3)
    if at_boundary:
        sdk._instructions(config, repo)
    else:
        with pytest.raises(sdk.SDKRefused):
            sdk._instructions(config, repo)


def test_nonregular_user_dependency_does_not_leak_descriptor(context):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text("@directory\n")
    (config / "directory").mkdir()
    before = len(list(Path("/proc/self/fd").iterdir()))
    with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
        sdk._instructions(config, repo)
    assert len(list(Path("/proc/self/fd").iterdir())) == before


def test_wide_graph_stops_resolving_at_capture_budget(context, monkeypatch):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text(" ".join(f"@{index}.md" for index in range(100)))
    for index in range(100):
        (config / f"{index}.md").write_text("")
    monkeypatch.setattr(sdk, "_INSTRUCTION_CAPTURE_VISITS", 3)
    original = Path.resolve
    resolved_dependencies = set()

    def count_dependencies(path, *args, **kwargs):
        if path.parent == config and path.stem.isdecimal():
            resolved_dependencies.add(path)
        return original(path, *args, **kwargs)

    with patch.object(Path, "resolve", count_dependencies):
        with pytest.raises(sdk.SDKRefused):
            sdk._instructions(config, repo)
    assert len(resolved_dependencies) <= 2


def test_proc_dependency_is_refused_without_opening_it(context):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text("@/proc/self/status\n")
    with patch.object(os, "open", wraps=os.open) as opened:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
    assert not any(str(call.args[0]).startswith("/proc/") for call in opened.call_args_list)


def test_quoted_paths_are_literal_nonimports(context):
    repo, config, _ = context
    text = 'PARENT\n@"dependency.md" @\'dependency.md\'\n'
    (config / "CLAUDE.md").write_text(text)
    (config / "dependency.md").write_bytes(b"\xff")
    assert sdk._instructions(config, repo) == text


def test_home_import_uses_the_admitted_target_home(context):
    repo, config, _ = context
    target_home = config.parent / "selected-home"
    target_home.mkdir()
    (config / "CLAUDE.md").write_text("@~/dependency.md\n")
    (target_home / "dependency.md").write_text("SELECTED_HOME\n")
    (config.parent / "dependency.md").write_text("AMBIENT_HOME\n")
    text = sdk._instructions(config, repo, home=target_home)
    assert "SELECTED_HOME" in text and "AMBIENT_HOME" not in text
    for reference in ("~root/dependency.md", "~//" + str(config.parent / "dependency.md").lstrip("/")):
        (config / "CLAUDE.md").write_text(f"@{reference}\n")
        with pytest.raises(sdk.SDKRefused):
            sdk._instructions(config, repo, home=target_home)


def test_filesystem_check_follows_the_opened_handle_before_read(context):
    binding_available()
    repo, config, record = context
    mutable = config / "mutable"
    mutable.mkdir()
    target = mutable / "status"
    target.write_text("ORDINARY_FILE\n")
    (config / "CLAUDE.md").write_text("@mutable/status\n")
    original_mount = sdk._mount_fstype
    original_fdopen = os.fdopen
    changed = False
    readers = []

    def replace_parent(path):
        nonlocal changed
        kind = original_mount(path)
        if path == target and not changed:
            changed = True
            mutable.rename(config / "saved")
            mutable.symlink_to("/proc/self", target_is_directory=True)
        return kind

    def observe_reader(fd, *args, **kwargs):
        readers.append(Path(f"/proc/self/fd/{fd}").resolve(strict=True))
        return original_fdopen(fd, *args, **kwargs)

    with patch.object(sdk, "_mount_fstype", replace_parent), patch.object(os, "fdopen", observe_reader):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert changed and result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert all(not str(path).startswith("/proc/") for path in readers)
    assert not record.exists()


@pytest.mark.parametrize("repeat", [False, True])
def test_capture_rejects_file_changed_while_collecting_another(context, repeat):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text("@a.md @b.md\n")
    first = config / "a.md"
    second = config / "b.md"
    first.write_text("ORIGINAL\n")
    second.write_text("@a.md\n" if repeat else "OTHER\n")
    (config / "c.md").write_text("MUST_NOT_ENTER_SNAPSHOT\n")
    original_mount = sdk._mount_fstype
    changed = False

    def change_previous_capture(path):
        nonlocal changed
        kind = original_mount(path)
        if path == second and not changed:
            changed = True
            first.write_text("@c.md\n")
        return kind

    with patch.object(sdk, "_mount_fstype", change_previous_capture):
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert changed and result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()
    assert "MUST_NOT_ENTER_SNAPSHOT" not in result.output


@pytest.mark.parametrize("prefix", ["Quote with a ` character.\n\n", "# Heading with a ` character\n",
                                    "- Quote with a ` character\n", "> Quote with a ` character\n",
                                    "Heading with a ` character\n--\n", "<div>Quote with a ` character</div>\n",
                                    "[example]: /path `character\n",
                                    "Quote with a ` character\n```\nexample\n```\n"])
def test_ambiguous_cross_block_backticks_refuse_before_probes(context, prefix):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text(prefix + "@AGENTS.md\n\nRun `ls` first.\n")
    (config / "AGENTS.md").write_text("DEPENDENCY_MUST_NOT_BE_OMITTED\n")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("body", [
    "    indented `example\n@AGENTS.md then `tick\n",
    "# Title\n    code `x\n@AGENTS.md `y\n",
    "\tcode `x\n@AGENTS.md `y\n",
    "Escape with \\` @AGENTS.md ` and `code`.\n",
    'Text <b title="`">bold</b> @AGENTS.md `\n',
    "See <https://example.com/`> @AGENTS.md `\n",
    "| a `b | @AGENTS.md `c |\n|---|---|\n| x | y |\n",
    "<!--\nstart `\n-->\n@AGENTS.md\nend `\n",
    "<?instruction\nstart `\n?>\n@AGENTS.md\nend `\n",
    "<![CDATA[\nstart `\n]]>\n@AGENTS.md\nend `\n",
    "[x](y`) @AGENTS.md `z\n",
    '[x](y "`") @AGENTS.md `z\n',
    "![x](y`) @AGENTS.md `z\n",
    "See [x](y`)\n@AGENTS.md `z\n",
    "<!DOCTYPE\nstart ` x>\n@AGENTS.md `\n",
    "<!X\n`a>\n@AGENTS.md `\n",
    "x <!--\n\n`a\n# @AGENTS.md\nb`\n",
    "- <!-- note\n\n`a\n# @AGENTS.md\nb`\n",
    "Use <!-- here\n\n`a\n- @AGENTS.md\nb`\n",
    "x <? y\n\n`a\n# @AGENTS.md\n`\n",
    "x <!--\n\n`a\n> @AGENTS.md\nb`\n",
    "\n`a\n# @AGENTS.md\nb`\n",
])
def test_ambiguous_markdown_pairing_refuses_before_probes(context, body):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text(body)
    (config / "AGENTS.md").write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("indent", ["    ", "\t", " \t", "  \t", "   \t"])
def test_unfenced_indented_import_refuses_before_read_or_probe(context, indent):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text("Example:\n\n" + indent + "@AGENTS.md\n")
    (config / "AGENTS.md").write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("opening,ending", [
    ("<!--", "-->"), ("<?instruction", "?>"), ("<![CDATA[", "]]>"),
    ("<!DOCTYPE", "html>"), ("<script>", "</script>"), ("<div>", ""),
])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_html_fence_boundaries_refuse_before_probe(context, opening, ending, fence):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text(f"{opening}\n{fence}\n{ending}\n@AGENTS.md\n{fence}\n")
    (config / "AGENTS.md").write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("separator", ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_non_line_endings_do_not_manufacture_fences(context, separator):
    repo, config, _ = context
    text = separator.join(["See", "~~~", "@AGENTS.md", "~~~"]) + "\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_text("REAL_DEPENDENCY\n")
    assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"


@pytest.mark.parametrize("body", [
    "foo <b>\n<!--\n\n```\n-->\n@AGENTS.md\n```\n",
    "see <!X\n<!--\na > b\n```\n-->\n@AGENTS.md\n```\n",
    "foo <b>\n<pre>\n\n~~~\n</pre>\n@AGENTS.md\n~~~\n",
    "# T <b>\n<!--\n\n~~~\n-->\n@AGENTS.md\n~~~\n",
    "x <!--\n<?\n-->\n```\n?>\n@AGENTS.md\n```\n",
    "a <x\n<![CDATA[\n\n```\n]]>\n@AGENTS.md\n",
    "foo <!X\n<div>\n>\n~~~\n\n@AGENTS.md\n~~~\n",
    "foo <!X\n</div>\n>\n~~~\n\n@AGENTS.md\n~~~\n",
    "foo <script>\n\n</pre>\n~~~\n\n@AGENTS.md\n~~~\n",
])
def test_nested_html_boundaries_refuse_before_probe(context, body):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text(body)
    (config / "AGENTS.md").write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("body,closed", [
    ("1. {fence}bash\n   make test\n   {fence}\n\nAlso read @AGENTS.md\n", True),
    ("- {fence}\n  code\n  {fence}\n@AGENTS.md\n", True),
    ("- {fence}\n  code\n  {fence}\n\n@AGENTS.md\n{fence}\n", False),
    ("- item\n\n  {fence}\n@AGENTS.md\n", False),
    ("- item\n\n  {fence}\n  code\n- @AGENTS.md\n", False),
    ("- a\n\n  {fence}\n  x\n     {fence}\n@AGENTS.md\n", True),
    ("- item\n  {fence}\n  example\n@AGENTS.md\n", False),
    ("1. item\n   {fence}\n   example\n@AGENTS.md\n", False),
])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_container_fences_preserve_imports_only_with_explicit_closers(context, body, closed, fence):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text(body.format(fence=fence))
    (config / "AGENTS.md").write_bytes(b"REAL_DEPENDENCY\n" if closed else b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    if closed:
        assert sdk._instructions(config, repo) == body.format(fence=fence) + "\n\nREAL_DEPENDENCY\n"
    else:
        result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
@pytest.mark.parametrize("closer", [False, True])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_indented_candidate_fence_ambiguity_refuses_before_probe(context, indent, closer, fence):
    binding_available()
    repo, config, record = context
    text = (f"- {fence}\n  example\n{indent}{fence}\n@AGENTS.md\n{fence}\n" if closer
            else f"{indent}{fence}\n@AGENTS.md\n{fence}\n")
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("body,complete", [
    ("  {fence} @AGENTS.md\n{fence}\n", False),
    ("  {fence}\n  example\n{fence} @AGENTS.md\n{fence}\n", False),
    ("- item\n  {fence}\n  example\n<script>\n{fence}\n{fence}\n</script>\n@AGENTS.md\n{fence}\n", False),
    ("- item\n  {fence}\n  example\n{fence}\n{fence}\n@AGENTS.md\n{fence}\n", False),
    ("  {fence}\n  example\n plain\n  {fence}\n{fence}\n@AGENTS.md\n{fence}\n", False),
    ("  {fence}\n  example\n\v\n  {fence}\n@AGENTS.md\n", True),
    ("  {fence}\n  example\n  {fence} @AGENTS.md\n  {fence}\n", False),
])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_composed_fence_scopes_capture_completely_or_refuse(context, body, complete, fence):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text(body.format(fence=fence))
    (config / "AGENTS.md").write_bytes(b"REAL_DEPENDENCY\n" if complete else b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    if complete:
        assert sdk._instructions(config, repo) == body.format(fence=fence) + "\n\nREAL_DEPENDENCY\n"
    else:
        result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("fence", ["```", "~~~"])
@pytest.mark.parametrize("example", ["  example", "  <type>", "\texample", " \t", ""])
@pytest.mark.parametrize("info", ["", " <script>"])
def test_indented_example_captures_or_refuses_angle_mixture(context, fence, example, info):
    repo, config, record = context
    text = f"  {fence}{info}\n{example}\n  {fence}\n\n@AGENTS.md\n"
    (config / "CLAUDE.md").write_text(text)
    dependency = config / "AGENTS.md"
    if "<" in example:
        binding_available()
        dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
        with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
            result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    else:
        dependency.write_text("REAL_DEPENDENCY\n")
        assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"
    assert not record.exists()


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_closed_indented_example_cannot_hide_later_fenced_candidate(context, fence):
    repo, config, _ = context
    text = f"  {fence}\n  example\n  {fence}\n{fence}\n@AGENTS.md\n{fence}\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_bytes(b"\xffCODE_EXAMPLE_MUST_NOT_BE_READ")
    with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
        sdk._instructions(config, repo)


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_closed_indented_example_refuses_later_angle_mixture_before_read_or_probe(context, fence):
    binding_available()
    repo, config, record = context
    text = f"  {fence}\n  example\n  {fence}\n{fence}\n<script>\n{fence}\n@AGENTS.md\n"
    (config / "CLAUDE.md").write_text(text)
    dependency = config / "AGENTS.md"
    dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_initial_column_zero_candidate_fence_refuses_with_indented_closer(context, indent, fence):
    repo, config, _ = context
    text = f"{fence}\n@AGENTS.md\n{indent}{fence}\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_bytes(b"\xffCODE_EXAMPLE_MUST_NOT_BE_READ")
    with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
        sdk._instructions(config, repo)


def test_candidate_free_indented_fences_preserve_html(context):
    repo, config, _ = context
    text = "  ~~~\n<script>\n  ~~~\n~~~\n</script>\n~~~\n"
    (config / "CLAUDE.md").write_text(text)
    assert sdk._instructions(config, repo) == text


@pytest.mark.parametrize("fenced", [False, True])
def test_imported_files_receive_the_same_code_candidate_guard(context, fenced):
    repo, config, _ = context
    text = "  ~~~\n  example\n  ~~~\n@dependency.md\n"
    dependency = "~~~\n@must-not-read.md\n~~~\n" if fenced else "Use `@must-not-read.md` here.\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "dependency.md").write_text(dependency)
    (config / "must-not-read.md").write_bytes(b"\xffCODE_EXAMPLE_MUST_NOT_BE_READ")
    if fenced:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
    else:
        assert sdk._instructions(config, repo) == text + "\n\n" + dependency


@pytest.mark.parametrize("prefix", ["- ~~~", "1. ~~~", "> ~~~", "> - ~~~", "- > ~~~"])
def test_prefixed_fence_then_column_zero_candidate_fence_refuses(context, prefix):
    repo, config, _ = context
    text = f"{prefix}\n~~~\n@AGENTS.md\n~~~\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_bytes(b"\xffCODE_EXAMPLE_MUST_NOT_BE_READ")
    with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
        sdk._instructions(config, repo)


def test_candidate_free_nested_html_preserves_original_text(context):
    repo, config, _ = context
    text = "foo <b>\n<pre>\n\n~~~\n</pre>\nexample\n~~~\n"
    (config / "CLAUDE.md").write_text(text)
    assert sdk._instructions(config, repo) == text


@pytest.mark.parametrize("opening,ending", [("- <!--", "  -->"), ("- <script>", "  </script>")])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_list_html_fence_boundaries_refuse_before_probe(context, opening, ending, fence):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text(f"{opening}\n  {fence}\n{ending}\n@AGENTS.md\n{fence}\n")
    (config / "AGENTS.md").write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("candidate", [False, True])
def test_real_line_endings_preserve_examples_or_refuse_fenced_candidates(context, ending, candidate):
    repo, config, _ = context
    text = ending.join(["~~~", "<!--", "@AGENTS.md" if candidate else "ordinary example", "-->", "~~~", ""])
    (config / "CLAUDE.md").write_bytes(text.encode())
    (config / "AGENTS.md").write_bytes(b"\xffCODE_EXAMPLE_MUST_NOT_BE_READ")
    if candidate:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
    else:
        assert sdk._instructions(config, repo) == text


@pytest.mark.parametrize("ending", ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_non_line_endings_cannot_hide_a_fenced_candidate(context, ending):
    repo, config, _ = context
    text = "~~~\n~~~" + ending + "\n@AGENTS.md\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_bytes(b"\xffCODE_EXAMPLE_MUST_NOT_BE_READ")
    with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
        sdk._instructions(config, repo)


@pytest.mark.parametrize("opening,ending", [("<!DOCTYPE", "html>"), ("<script>", "</pre>")])
@pytest.mark.parametrize("separated", [False, True])
def test_html_ends_before_ordinary_code_and_import(context, opening, ending, separated):
    binding_available()
    repo, config, record = context
    text = f"{opening}\n{ending}\n" + ("\n" if separated else "") + "See @AGENTS.md and `code`.\n"
    (config / "CLAUDE.md").write_text(text)
    dependency = config / "AGENTS.md"
    if separated:
        dependency.write_text("REAL_DEPENDENCY\n")
        assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"
    else:
        dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
        with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
            result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("text", ["@AGENTS.md`x`suffix\n", "@AGENTS.md`x`a``y``suffix\n"])
def test_inline_code_does_not_join_import_tokens(context, text):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_text("REAL_DEPENDENCY\n")
    wrong = [config / "AGENTS.mdsuffix", config / "AGENTS.mdasuffix"]
    for path in wrong:
        path.write_bytes(b"\xffWRONG_DEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"
    assert all(Path(call.args[0]) not in wrong for call in opened.call_args_list)


def test_inline_code_does_not_manufacture_absolute_import(context):
    repo, config, _ = context
    outside = repo / "not-an-import.md"
    outside.write_bytes(b"\xffMUST_NOT_BE_READ")
    text = "@`x`" + str(outside) + "\n"
    (config / "CLAUDE.md").write_text(text)
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        assert sdk._instructions(config, repo) == text
    assert all(Path(call.args[0]) != outside for call in opened.call_args_list)


@pytest.mark.parametrize("text", [
    "Use `left|right` here.\n",
    "Use `<type>` here.\n",
    "Use \\`literal` here.\n",
    "    code `x`\n",
    "Use `<!-- -->` here.\n",
    "Use `[label](target)` here.\n",
    "Use `left > right` here.\n",
    "Use `a``b` here.\n",
    "_`_ ` `@AGENTS.md x`\n",
])
def test_nonimport_code_syntax_preserves_complete_instructions(context, text):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text(text)
    assert sdk._instructions(config, repo) == text


@pytest.mark.parametrize("position", ["none", "start", "whitespace"])
def test_multiline_code_spans_preserve_or_refuse_literals(context, position):
    repo, config, record = context
    text = ("Use `first line\n@nonexistent.md\nlast line` as an example.\n" if position == "whitespace"
            else "Use `@nonexistent.md\nlast line` as an example.\n" if position == "start"
            else "Use `first line\nordinary example\nlast line` as an example.\n")
    (config / "CLAUDE.md").write_text(text)
    if position != "none":
        binding_available()
        dependency = config / "nonexistent.md"
        dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
        with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
            result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    else:
        assert sdk._instructions(config, repo) == text
    assert not record.exists()


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("separate", [False, True])
def test_multiline_code_requires_a_separate_block_from_imports(context, ending, separate):
    repo, config, record = context
    text = ("a `x\ny`" + ("\n\n" if separate else "\n") + "@AGENTS.md\n").replace("\n", ending)
    (config / "CLAUDE.md").write_bytes(text.encode())
    dependency = config / "AGENTS.md"
    if separate:
        dependency.write_text("REAL_DEPENDENCY\n")
        assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"
    else:
        binding_available()
        dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
        with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
            result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("body", [
    "- #tag `a\n*a*@AGENTS.md y`\n",
    "- #1 run `make\n**all**@AGENTS.md now`\n",
    "2. #`x\n*a*@AGENTS.md y`\n",
    "- #x `a\n\\*@AGENTS.md y`\n",
    "- #tag `a\nb` and `*a*@AGENTS.md y`\n",
    "a `x\n#\u00a0*a*@AGENTS.md y`\n",
    "#\u00a0`x\n*a*@AGENTS.md y`\n",
    "a `x\n#\ufeff@AGENTS.md y`\n",
    "a `x\n#\u00a0b` `*a*@AGENTS.md y`\n",
    "- a `x\n  #\u00a0*a*@AGENTS.md y`\n",
    "a `x\n#\u00a0b` `@AGENTS.md y`\n",
    "- #tag `a\nb` `@AGENTS.md y`\n",
    "a `x\n#\u3000*a*@AGENTS.md y`\n",
    "a `x\n#\u2028*a*@AGENTS.md y`\n",
    "a `x\n#\v*a*@AGENTS.md y`\n",
    "a `x\n#\f*a*@AGENTS.md y`\n",
])
def test_native_block_splits_refuse_before_read_or_probe(context, ending, body):
    binding_available()
    repo, config, record = context
    dependency = config / "AGENTS.md"
    (config / "CLAUDE.md").write_bytes(body.replace("\n", ending).encode())
    dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("separated", [False, True])
@pytest.mark.parametrize("body", [
    "p\n<?p?> [x](\n`a)` `@AGENTS.md y`\n",
    "p\n<?p?> [x](y \"\n`\") a` `@AGENTS.md y`\n",
    "p\n<?p?> [x](y '\n`') a` `@AGENTS.md y`\n",
    "p\n<!X> [x](\n`a)` `@AGENTS.md y`\n",
    "p\n<![CDATA[x]]> [x](\n`a)` `@AGENTS.md y`\n",
    "Notes\n<!DOCTYPE html> see [docs](\n`cfg)` then `@AGENTS.md y`\n",
    "p [x](y \"\n<?p?>\n`\") a` `@AGENTS.md y`\n",
    "<?p?> [x](\n`a)` `@AGENTS.md y`\n",
])
def test_native_link_carriers_require_a_separate_candidate_run(context, ending, separated, body):
    binding_available()
    repo, config, record = context
    if separated:
        prefix, last, trailing = body.rsplit("\n", 2)
        body = prefix + "\n\n" + last + "\n" + trailing
    text = body.replace("\n", ending)
    (config / "CLAUDE.md").write_bytes(text.encode())
    dependency = config / "AGENTS.md"
    dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        if separated:
            assert sdk._instructions(config, repo) == text
        else:
            result = launch_with_spec(build_launch_spec(request(repo)))
            assert result.failed
            assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("separator", [None, "", "\t", " \t"])
@pytest.mark.parametrize("body, boundary, separated_supported", [
    ("- #tag `a\nz` w\n<?p?>\n`@AGENTS.md y`\n", "<?p?>", False),
    ("\\`a`\n<?p?>\n`@AGENTS.md y`\n", "<?p?>", False),
    ("`a``b` _`_ ` x\n<!X>\n`@AGENTS.md y`\n", "<!X>", False),
    ("a `x\n#\u00a0y\nz` w\n<![CDATA[x]]>\n`@AGENTS.md y`\n", "<![CDATA[x]]>", False),
    ("<b x='`'>`\n<?p?>\n`@AGENTS.md y`\n", "<?p?>", False),
    ("- #1 run `make\nall` now\n2. x\nx `b` `@AGENTS.md y`\n", "2. x", True),
    ("- #tag `a\nz` w\n<!DOCTYPE html>\n`@AGENTS.md y`\n", "<!DOCTYPE html>", False),
    ("- #tag `a\nz` w\n<?a\nb?>\n`@AGENTS.md y`\n", "<?a\nb?>", False),
])
def test_native_block_joins_preserve_supported_boundaries(context, ending, separator, body, boundary, separated_supported):
    binding_available()
    repo, config, record = context
    if separator is not None:
        body = body.replace("\n" + boundary, "\n" + separator + "\n" + boundary)
    text = body.replace("\n", ending)
    (config / "CLAUDE.md").write_bytes(text.encode())
    dependency = config / "AGENTS.md"
    dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        if separator is None or not separated_supported:
            result = launch_with_spec(build_launch_spec(request(repo)))
            assert result.failed
            assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        else:
            assert sdk._instructions(config, repo) == text
    assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("body", [
    "```\nx\n```~\n@AGENTS.md\n```\n",
    "~~~\nx\n~~~`\n@AGENTS.md\n~~~\n",
    "[r]:\n```\n@AGENTS.md\n",
    "[r]:\n~~~\n@AGENTS.md\n~~~\n",
    "[r]:\n ```\n@AGENTS.md\n\tx",
    "[r]:\n  ```\n@AGENTS.md\n+ b\n  - item\n    ```",
    "</pre>\n- item\n\n  ```\n@AGENTS.md\n",
    "</script>\n- item\n\n  ~~~\n@AGENTS.md\n",
    "</textarea>\n- a\n\n   ~~~\n@AGENTS.md\n",
    "<pre/>\n- item\n\n  ```\n@AGENTS.md\n",
    "~~~\nx\n~~~\t\n@AGENTS.md\n~~~\n",
    "[r]:\n~~~\nx\n~~~\n@AGENTS.md\n",
    "[r]:\n~~~\nx\n~~~\n@AGENTS.md\n~~~\n",
    "- [r]:\n  ~~~\n  x\n  ~~~\n@AGENTS.md\n",
    "<script>\n</pre>\n\n~~~\nx\n~~~\n\n@AGENTS.md\n",
    "foo <script>\n\n</pre>\n~~~\n\n@AGENTS.md\n",
    "_a_@AGENTS.md\n",
    "See _note_@AGENTS.md for details.\n",
    "__a__@AGENTS.md\n",
    "\\_@AGENTS.md\n",
    "x\\_@AGENTS.md\n",
    "foo_@AGENTS.md\n",
    "\\@AGENTS.md\n",
    "~~~\n_a_@AGENTS.md\n~~~\n",
    "- `x @AGENTS.md y`\n",
    "- run `cat @AGENTS.md now`\n- other\n",
    "1. use `see @AGENTS.md here`\n",
    "- a\n\n- `x @AGENTS.md y`\n",
    "- item\n  ~~~\n  > ~~~\n@AGENTS.md\n",
    "1. item\n   ~~~\n   > ~~~\n@AGENTS.md\n",
    "- item\n  ```\n  > ```\n@AGENTS.md\n",
    "1. item\n   ```\n   > ```\n@AGENTS.md\n",
    "- item\n  ~~~\n  > > ~~~\n@AGENTS.md\n",
    "`a``b` _`_ ` `@AGENTS.md x`\n",
    "`a``b`\n_`_\n` `@AGENTS.md x`\n",
    "Use `a``b` with _`_ and ` `@AGENTS.md here`.\n",
    "`a``b` **`** ` `@AGENTS.md x`\n",
    "- `a``b` _`_ ` `@AGENTS.md x`\n",
    "```\nx\n```~\n```\n@AGENTS.md\n",
    "~~~\nx\n~~~`\n~~~\n@AGENTS.md\n",
    "````\nx\n`````~\n````\n@AGENTS.md\n",
    "```\nx\n ```~\n```\n@AGENTS.md\n",
    "<a_b>\n~~~\nx\n\n~~~\n@AGENTS.md\n~~~\n~~~\n",
    "- a\n<x>\n```\ny\n\n```\n@AGENTS.md\n```\n```\n",
    "para\n<meta x\n~~~\ny\n\n~~~\n@AGENTS.md\n~~~\n~~~\n",
    "- > <a_b>\n  > ~~~\n  > x\n  >\n  > ~~~\n  > @AGENTS.md\n  > ~~~\n  > ~~~\n",
    "- See [docs](https://x)\n- Run `make`\n- @AGENTS.md\n",
])
def test_native_dialect_ambiguity_refuses_before_read_or_probe(context, body):
    binding_available()
    repo, config, record = context
    dependency = config / "AGENTS.md"
    (config / "CLAUDE.md").write_text(body)
    dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("prefix", ["www.example.com/", "http://example.com/", "https://example.com/"])
@pytest.mark.parametrize("separator", [" ", "\n"])
def test_url_backtick_ambiguity_refuses_before_read_or_probe(context, prefix, separator):
    binding_available()
    repo, config, record = context
    dependency = config / "AGENTS.md"
    (config / "CLAUDE.md").write_text(prefix + "`" + separator + "@AGENTS.md" + separator + "`x\n")
    dependency.write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert all(Path(call.args[0]) != dependency for call in opened.call_args_list)
    assert not record.exists()


@pytest.mark.parametrize("prefix", ["www.example.com/", "http://example.com/", "https://example.com/"])
def test_candidate_free_url_code_preserves_instructions(context, prefix):
    repo, config, _ = context
    text = "Use " + prefix + "`example` here.\n"
    (config / "CLAUDE.md").write_text(text)
    assert sdk._instructions(config, repo) == text


@pytest.mark.parametrize("prefix", ["", "  ", "> "])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_closed_candidate_free_fences_preserve_outside_imports(context, prefix, fence):
    repo, config, _ = context
    text = f"{prefix}{fence}\n{prefix}ordinary example\n{prefix}{fence}\n\n@AGENTS.md\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_text("REAL_DEPENDENCY\n")
    assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("final_ending", [False, True])
@pytest.mark.parametrize("body", ["", "\n", "ordinary\u2028example\n\n"])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_explicit_fence_extent_preserves_body_lines_and_eof(context, ending, final_ending, body, fence):
    repo, config, _ = context
    text = ("@AGENTS.md\n\n" + fence + "\n" + body + fence + ("\n" if final_ending else "")).replace("\n", ending)
    (config / "CLAUDE.md").write_bytes(text.encode())
    (config / "AGENTS.md").write_text("REAL_DEPENDENCY\n")
    assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"


@pytest.mark.parametrize("text", [
    "[unused]: @AGENTS.md\n",
    "<div>\n@AGENTS.md\n</div>\n",
    "Use `<First>` here.\nUse `<Second>` here.\n\n@AGENTS.md\n",
    "    code `x`\n\n@AGENTS.md\n",
])
def test_parser_maps_retain_raw_nonrendered_and_outside_imports(context, text):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_text("REAL_DEPENDENCY\n")
    assert sdk._instructions(config, repo) == text + "\n\nREAL_DEPENDENCY\n"


def test_entity_spelling_cannot_select_a_decoded_dependency(context):
    repo, config, _ = context
    (config / "CLAUDE.md").write_text("@A&amp;B.md\n")
    decoded = config / "A&B.md"
    decoded.write_bytes(b"\xffDECODED_PATH_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
    assert all(Path(call.args[0]) != decoded for call in opened.call_args_list)


def test_parser_nesting_limit_refuses_before_dependency_read(context):
    repo, config, _ = context
    prefix = "> " * 20
    text = f"{prefix}~~~\n{prefix}@AGENTS.md\n{prefix}~~~\n"
    (config / "CLAUDE.md").write_text(text)
    (config / "AGENTS.md").write_bytes(b"\xffDEPENDENCY_MUST_NOT_BE_READ")
    with patch.object(sdk.os, "open", wraps=sdk.os.open) as opened:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
    assert all(Path(call.args[0]) != config / "AGENTS.md" for call in opened.call_args_list)


@pytest.mark.parametrize("text", ["x" * (sdk._INSTRUCTION_SNAPSHOT_BYTES + 1), "NUL\x00"])
def test_snapshot_limits_refuse_before_markdown_parsing(context, text):
    from markdown_it import MarkdownIt

    repo, config, _ = context
    (config / "CLAUDE.md").write_text(text)
    with patch.object(MarkdownIt, "parse", side_effect=AssertionError("oversize or NUL reached parser")):
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)


@pytest.mark.parametrize("oversize", [False, True])
def test_complete_utf8_snapshot_argument_boundary(context, oversize):
    binding_available()
    repo, config, record = context
    parent = "LINKED_PARENT\n@dependency.md\n"
    marker = "LINKED_DEPENDENCY\n"
    remaining = sdk._INSTRUCTION_SNAPSHOT_BYTES - len((parent + "\n\n" + marker).encode())
    (config / "CLAUDE.md").write_text(parent)
    (config / "dependency.md").write_text(marker + "é" * (remaining // 2) + "x" * (remaining % 2 + oversize))
    result = launch_with_spec(build_launch_spec(request(repo)))
    if oversize:
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        assert not record.exists()
    else:
        assert not result.failed, result.claude_route_result or result.output
        rows = [json.loads(line) for line in record.read_text().splitlines()]
        assert any(row["mode"] == "inference" and row["linked_instructions"] for row in rows)


def test_snapshot_limit_includes_user_project_and_rules(context):
    binding_available()
    repo, config, record = context
    (config / "CLAUDE.md").write_text("U" * 32000)
    (repo / "CLAUDE.md").write_text("P" * 2000)
    rules = config / "rules"
    rules.mkdir()
    (rules / "a.md").write_text("R" * 32000)
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


@pytest.mark.parametrize("location", ["user", "project", "rule"])
def test_embedded_nul_refuses_before_probes(context, location):
    binding_available()
    repo, config, record = context
    path = config / "CLAUDE.md" if location == "user" else repo / "CLAUDE.md" if location == "project" else config / "rules/a.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("BEFORE\x00AFTER\n")
    result = launch_with_spec(build_launch_spec(request(repo)))
    assert result.failed
    assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
    assert not record.exists()


def test_repeated_user_alias_still_checks_relative_import_meaning(context):
    repo, config, _ = context
    source = config / "source"
    other = config / "other"
    source.mkdir()
    other.mkdir()
    (config / "CLAUDE.md").write_text("@source/parent.md @other/alias.md\n")
    (source / "parent.md").write_text("@child.md\n")
    (source / "child.md").write_text("ORIGINAL\n")
    (other / "child.md").write_text("DIFFERENT\n")
    (other / "alias.md").symlink_to(source / "parent.md")
    with pytest.raises(sdk.SDKRefused):
        sdk._instructions(config, repo)


@pytest.mark.parametrize("name", ["CLAUDE.md", ".claude/CLAUDE.md"])
@pytest.mark.parametrize("fenced_candidate", [False, True])
def test_plain_instruction_syntax_is_preserved_or_refuses_code_candidates(context, name, fenced_candidate):
    binding_available()
    repo, config, _ = context
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "---\nPLAIN_ONCE security@example.com\n`@README` and ``@other``\n```python\n@decorator\n```\n~~~text\n@literal\n~~~\n"
    if not fenced_candidate:
        text = text.replace("\n@decorator\n", "\ndecorator example\n").replace("\n@literal\n", "\nliteral example\n")
    path.write_text(text)
    if fenced_candidate:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
        result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        return
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


@pytest.mark.parametrize("fenced_candidate", [False, True])
def test_unreferenced_config_agents_are_not_captured(context, fenced_candidate):
    binding_available()
    repo, config, record = context
    (config / "AGENTS.md").write_text("Unrelated config file\n")
    text = "---\nsecurity@example.com\n```python\n@decorator\n```\n"
    if not fenced_candidate:
        text = text.replace("\n@decorator\n", "\ndecorator example\n")
    (repo / "CLAUDE.md").write_text(text)
    if fenced_candidate:
        with pytest.raises(sdk.SDKRefused, match="sdk_instruction_layout_unsupported"):
            sdk._instructions(config, repo)
        result = launch_with_spec(build_launch_spec(request(repo)))
        assert result.failed
        assert result.claude_route_result["event_id"] == "sdk_instruction_layout_unsupported"
        assert not record.exists()
        return
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
    monkeypatch.setattr("phase_loop_runtime.sandbox_policy._MOUNTINFO", Path("/proc/self/mountinfo"))
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
