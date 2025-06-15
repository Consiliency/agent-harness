"""Opt-in solo SDK executor. Configuration is bound before any CLI operation."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from . import seat_credentials
from .advisor_board.backing import scrub_subscription_env
from .claude_channel_sidecar import ClaudeRouteResult
from .sandbox_policy import CHILD_SCRATCH_RELOCATE, child_scratch_env


SDK_VERSION = "0.2.167"
_AUTH_ERRORS = {"authentication_failed", "billing_error", "oauth_org_not_allowed"}
_MUTABLE_DIRS = ("debug", "projects", "todos", "plans", "session-env", "cache", "plugins", "telemetry")
_PROBE_CWD = Path("/etc/phase-loop-sdk-probe")


class SDKRefused(ValueError):
    pass


def sdk_available() -> bool:
    try:
        return importlib.metadata.version("claude-agent-sdk") == SDK_VERSION
    except importlib.metadata.PackageNotFoundError:
        return False


def admit_context(env: Mapping[str, str], repo: Path) -> tuple[Path, bytes]:
    """Offline guard shared by parent preflight and the supervised launch."""
    from .panel_invoker import _claude_caller_supplied_credential

    if _claude_caller_supplied_credential(env):
        raise SDKRefused("sdk_caller_credential_refused")
    if sys.platform != "linux" or not Path("/usr/bin/bwrap").is_file():
        raise SDKRefused("sdk_context_binding_unavailable")
    config = Path(env.get("CLAUDE_CONFIG_DIR") or str(Path(env.get("HOME", "")) / ".claude"))
    if not config.is_absolute() or config.is_symlink():
        raise SDKRefused("sdk_context_unbound")
    raw = seat_credentials.read_login_store(env={**env, "CLAUDE_CONFIG_DIR": str(config)})
    try:
        oauth = json.loads(raw or b"{}").get("claudeAiOauth", {})
    except (ValueError, AttributeError):
        raise SDKRefused("sdk_personal_login_required") from None
    if (not isinstance(oauth, dict) or not isinstance(oauth.get("subscriptionType"), str)
            or oauth["subscriptionType"] not in {"pro", "max"}
            or not seat_credentials.login_subscription_proven(read_store=lambda: raw)):
        raise SDKRefused("sdk_personal_login_required")
    # A local absence is used only after offline credential-class admission.
    # Endpoint policy is never removed to make a managed context qualify.
    _managed_settings()
    try:
        for entry in config.iterdir():
            if any(word in entry.name.lower() for word in ("managed", "remote-settings", "profile")):
                raise SDKRefused("sdk_managed_context_unsupported")
    except OSError:
        raise SDKRefused("sdk_context_uninspectable") from None
    return config, raw


def _managed_settings() -> dict[str, dict]:
    directory = Path("/etc/claude-code")
    files = {}
    try:
        if directory.is_symlink():
            raise SDKRefused("sdk_managed_context_unsupported")
        if directory.exists():
            for entry in directory.iterdir():
                if entry.name == "managed-settings.json":
                    files[entry.name] = _json_file(entry)
                elif entry.name == "managed-settings.d" and entry.is_dir() and not entry.is_symlink():
                    for fragment in entry.iterdir():
                        if fragment.suffix != ".json":
                            raise SDKRefused("sdk_managed_context_unsupported")
                        files[str(Path(entry.name) / fragment.name)] = _json_file(fragment)
                else:
                    raise SDKRefused("sdk_managed_context_unsupported")
    except OSError:
        raise SDKRefused("sdk_context_uninspectable") from None
    return files


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {}
    try:
        if not path.is_file() or path.stat().st_size > 32 << 20:
            raise SDKRefused("sdk_settings_uninspectable")
        with path.open(encoding="utf-8") as handle:
            text = handle.read((32 << 20) + 1)
        if len(text) > 32 << 20:
            raise SDKRefused("sdk_settings_uninspectable")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise SDKRefused("sdk_settings_uninspectable")
        _inspect_settings(data)
        return data
    except (OSError, ValueError, RecursionError) as exc:
        if isinstance(exc, SDKRefused):
            raise
        raise SDKRefused("sdk_settings_uninspectable") from None


def _inspect_settings(data: Any) -> None:
    from .panel_invoker import _claude_caller_supplied_credential

    if isinstance(data, dict):
        for key, value in data.items():
            normalized = key.lower().replace("_", "").replace("-", "")
            if normalized in {"apikeyhelper", "primaryapikey", "anthropicprofile", "activeprofile",
                              "currentprofile", "profiles", "fallbackmodel"} and value:
                raise SDKRefused("sdk_settings_refused")
            if key == "env":
                if not isinstance(value, dict) or _claude_caller_supplied_credential(value):
                    raise SDKRefused("sdk_settings_refused")
                if scrub_subscription_env(value) != value:
                    raise SDKRefused("sdk_settings_refused")
                if any(k in value for k in ("HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR")):
                    raise SDKRefused("sdk_settings_refused")
                if "CLAUDE_CODE_DISABLE_AUTO_MEMORY" in value and value["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] != "1":
                    raise SDKRefused("sdk_settings_refused")
            _inspect_settings(value)
    elif isinstance(data, list):
        for value in data:
            _inspect_settings(value)


def _merge_settings(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_settings(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = [*result[key], *(item for item in value if item not in result[key])]
        else:
            result[key] = value
    return result


def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _instructions(config: Path, repo: Path) -> str:
    instructions = []
    seen = set()

    def collect(path, directory):
        if not path.exists() and not path.is_symlink():
            return
        if any(part.is_symlink() for part in (path, *path.parents) if part != directory and directory in part.parents):
            raise SDKRefused("sdk_instruction_layout_unsupported")
        resolved = path.resolve(strict=True)
        if resolved in seen:
            return
        if not path.is_file() or not resolved.is_relative_to(directory.resolve()) or path.stat().st_size > 32 << 20:
            raise SDKRefused("sdk_instruction_layout_unsupported")
        text = path.read_text(encoding="utf-8")
        # These layouts require native dynamic discovery, disabled on this route.
        if "@" in text or text.lstrip().startswith("---"):
            raise SDKRefused("sdk_instruction_layout_unsupported")
        seen.add(resolved)
        instructions.append(text)

    try:
        for directory in (config, *reversed((repo, *repo.parents))):
            for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
                collect(directory / name, directory)
            rules = directory / ("rules" if directory == config else ".claude/rules")
            if rules.is_symlink():
                raise SDKRefused("sdk_instruction_layout_unsupported")
            if rules.is_dir():
                for path in sorted(rules.iterdir()):
                    if path.is_dir() or path.is_symlink():
                        raise SDKRefused("sdk_instruction_layout_unsupported")
                    if path.suffix == ".md":
                        collect(path, directory)
    except (OSError, UnicodeError):
        raise SDKRefused("sdk_context_uninspectable") from None
    return "\n\n".join(instructions)


@contextlib.contextmanager
def bound_command(command: list[str], repo: Path, env: Mapping[str, str]):
    """Freeze the approved inputs in a private mount namespace for probe AND SDK.

    The same installed CLI loads the opaque login store itself. No credential is
    supplied in options, argv, or an environment variable. The outer launcher owns
    the namespace process and all descendants through its normal supervisor.
    """
    config, raw = admit_context(env, repo)
    if _PROBE_CWD.exists() or any(path.exists() or path.is_symlink() for path in
            (Path("/.claude"), Path("/etc/.claude"), Path("/.git"), Path("/etc/.git"))):
        raise SDKRefused("sdk_context_unbound")
    home = Path(env.get("HOME", ""))
    if not home.is_absolute() or home.is_symlink() or not home.is_dir():
        raise SDKRefused("sdk_context_unbound")
    if not sdk_available():
        raise SDKRefused("sdk_dependency_missing")
    cli = shutil.which("claude", path=env.get("PATH"))
    if not cli:
        raise SDKRefused("sdk_cli_missing")
    cli = str(Path(cli).absolute())
    with tempfile.TemporaryDirectory(prefix="phase-loop-sdk-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        selected = root / "login"
        selected.mkdir(mode=0o700)
        managed = root / "managed"
        managed.mkdir(mode=0o700)
        for name, data in _managed_settings().items():
            destination = managed / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            _write_private(destination, json.dumps(data).encode())
        global_path = config / ".claude.json" if env.get("CLAUDE_CONFIG_DIR") else home / ".claude.json"
        global_config = _json_file(global_path)
        _write_private(selected / ".credentials.json", raw)
        _write_private(selected / ".claude.json", json.dumps(global_config).encode())
        user_settings = _json_file(config / "settings.json")
        settings = user_settings
        for name in ("settings.json", "settings.local.json"):
            project = _json_file(repo / ".claude" / name)
            # Do not elevate user-only keys from a project into --settings.
            if set(project) - {"$schema", "permissions", "hooks"}:
                raise SDKRefused("sdk_project_settings_scope_unsupported")
            project_states = global_config.get("projects", {})
            if not isinstance(project_states, dict):
                raise SDKRefused("sdk_settings_uninspectable")
            project_state = project_states.get(str(repo.resolve()), {})
            trusted = isinstance(project_state, dict) and project_state.get("hasTrustDialogAccepted") is True
            permissions = project.get("permissions", {})
            if not isinstance(permissions, dict):
                raise SDKRefused("sdk_settings_uninspectable")
            if set(permissions) - {"allow", "ask", "deny", "additionalDirectories"}:
                raise SDKRefused("sdk_project_settings_scope_unsupported")
            if (project.get("hooks") or permissions.get("allow") or permissions.get("additionalDirectories")) and not trusted:
                raise SDKRefused("sdk_project_trust_unproven")
            settings = _merge_settings(settings, project)
        if "--settings" in command:
            settings = _merge_settings(settings, _json_file(Path(command[command.index("--settings") + 1])))
        # The SDK's bare -v probe also sees the approved composite at the user tier.
        _write_private(selected / "settings.json", json.dumps(settings).encode())
        _write_private(root / "settings.json", json.dumps(settings).encode())
        _write_private(root / "instructions.txt", _instructions(config, repo).encode())
        for name in _MUTABLE_DIRS:
            (selected / name).mkdir()
        # Rebuild the two directories in tmpfs, so absent global/managed files
        # cannot appear later through an ambient host-directory reload.
        owner = ["/usr/bin/bwrap", "--die-with-parent", "--unshare-user", "--unshare-pid",
                 "--cap-drop", "ALL", "--bind", "/", "/", "--proc", "/proc",
                 "--tmpfs", str(home)]
        for entry in home.iterdir():
            if entry not in {config, global_path, home / ".claude.json", home / ".claude"}:
                owner += (["--symlink", os.readlink(entry), str(entry)] if entry.is_symlink()
                          else ["--bind", str(entry), str(entry)])
        owner += ["--ro-bind", str(selected / ".claude.json"), str(home / ".claude.json"),
                  "--ro-bind", str(selected), str(config)]
        for name in _MUTABLE_DIRS:
            owner += ["--tmpfs", str(config / name)]
        owner += ["--tmpfs", "/etc"]
        for entry in Path("/etc").iterdir():
            if entry.name != "claude-code":
                owner += (["--symlink", os.readlink(entry), str(entry)] if entry.is_symlink()
                          else ["--ro-bind", str(entry), str(entry)])
        owner += ["--ro-bind", str(managed), "/etc/claude-code", "--dir", str(_PROBE_CWD),
                  "--remount-ro", "/etc", "--chdir", str(_PROBE_CWD)]
        resolved = list(command)
        if "--settings" in resolved:
            resolved[resolved.index("--settings") + 1] = str(root / "settings.json")
        else:
            resolved += ["--settings", str(root / "settings.json")]
        if "--mcp-config" in resolved:
            index = resolved.index("--mcp-config") + 1
            _write_private(root / "mcp.json", json.dumps(_json_file(Path(resolved[index]))).encode())
            resolved[index] = str(root / "mcp.json")
        if "--plugin-dir" in resolved:
            plugin = resolved[resolved.index("--plugin-dir") + 1]
            owner += ["--ro-bind", plugin, plugin]
        if "--context-dir" in resolved:
            directory = resolved[resolved.index("--context-dir") + 1]
            owner += ["--ro-bind", directory, directory]
        # Mount after HOME overlays, including when scratch itself is under HOME.
        owner += ["--ro-bind", str(root), str(root)]
        resolved += ["--cli-path", cli, "--instructions-file", str(root / "instructions.txt")]
        child_env = scrub_subscription_env(env)
        child_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        yield [*owner, "--", *resolved], child_env


def auth_preflight(repo: Path, env: Mapping[str, str]) -> bool:
    with bound_command([sys.executable, "-m", __name__, "--auth-only", "--cwd", str(repo)], repo, env) as (command, child_env):
        result = subprocess.run(command, env=child_env, cwd=repo, capture_output=True, timeout=45, check=False)
        return result.returncode == 0


def _probe(cli: str, args: list[str], settings: str) -> subprocess.CompletedProcess:
    return subprocess.run([cli, "--settings", settings, "--setting-sources", "", *args],
                          env=child_scratch_env(os.environ, CHILD_SCRATCH_RELOCATE),
                          capture_output=True, text=True, timeout=20, check=False)


def _check_bound_context(extra_paths=()) -> None:
    config, _ = admit_context(os.environ, Path.cwd())
    if Path.cwd() != _PROBE_CWD or not os.statvfs(_PROBE_CWD).f_flag & os.ST_RDONLY:
        raise SDKRefused("sdk_context_unbound")
    paths = (config, Path(os.environ["HOME"]) / ".claude.json", Path("/etc/claude-code"), *extra_paths)
    if any(not (os.statvfs(path).f_flag & os.ST_RDONLY) for path in paths):
        raise SDKRefused("sdk_context_unbound")
    if scrub_subscription_env(os.environ) != dict(os.environ):
        raise SDKRefused("sdk_environment_unscrubbed")
    if os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") != "1":
        raise SDKRefused("sdk_environment_unscrubbed")


def _check_cli(cli: str, settings: str) -> str:
    if not Path(cli).is_absolute():
        raise SDKRefused("sdk_cli_missing")
    help_result = _probe(cli, ["-h"], settings)
    if help_result.returncode:
        help_result = _probe(cli, ["--help"], settings)
    required = ("--settings", "--setting-sources", "--strict-mcp-config", "--no-session-persistence",
                "--permission-mode", "--tools", "--disallowedTools", "--json-schema", "--effort")
    if help_result.returncode or any(flag not in help_result.stdout for flag in required):
        raise SDKRefused("sdk_cli_capability_missing")
    if _probe(cli, ["auth", "-h"], settings).returncode:
        raise SDKRefused("sdk_cli_capability_missing")
    status = _probe(cli, ["auth", "status", "--json"], settings)
    try:
        data = json.loads(status.stdout)
    except ValueError:
        raise SDKRefused("sdk_subscription_unproven") from None
    if (status.returncode or data.get("loggedIn") is not True or data.get("authMethod") != "claude.ai"
            or data.get("apiProvider") != "firstParty" or data.get("subscriptionType") not in {"pro", "max"}
            or data.get("apiKeySource") not in {None, "none"}):
        raise SDKRefused("sdk_subscription_unproven")
    version = _probe(cli, ["--version"], settings)
    import re
    match = re.match(r"(\d+\.\d+\.\d+)", version.stdout)
    if version.returncode or not match:
        raise SDKRefused("sdk_cli_capability_missing")
    return match.group(1)


def _emit(data: dict) -> None:
    print(json.dumps(data, separators=(",", ":")), flush=True)


def _receipt(status: str, reason: str, *, proven: bool = False) -> dict:
    return ClaudeRouteResult(route="claude_sdk", session_id="sdk-local", event_id=reason,
                             status=status, text="", auth_posture="subscription_local" if proven else "unknown",
                             billing_posture="subscription_included" if proven else "unknown",
                             warnings=() if status == "done" else (reason,),
                             evidence_refs=({"kind": "sdk_subscription_proof", "login_proven": proven,
                                             "init_proven": proven},)).to_json()


def _auth_drift(value) -> bool:
    if isinstance(value, str):
        return value in _AUTH_ERRORS
    if isinstance(value, dict):
        return any(_auth_drift(item) for key, item in value.items()
                   if key in {"error", "type", "code", "error_code", "errorType"})
    if isinstance(value, list):
        return any(_auth_drift(item) for item in value)
    return False


async def _run(options, prompt: str) -> None:
    # Import only in the already-scrubbed, bound helper process.
    from claude_agent_sdk import ClaudeSDKClient, SystemMessage, ResultMessage

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    initialized = False
    completed = False
    async with ClaudeSDKClient(options=options) as client:
        async def receive():
            nonlocal initialized, completed
            await client.query(prompt)
            async for message in client.receive_response():
                data = message.data if isinstance(message, SystemMessage) else {}
                if (_auth_drift(getattr(message, "error", None))
                        or _auth_drift(getattr(message, "errors", None)) or _auth_drift(data)):
                    await client.interrupt()
                    raise SDKRefused("sdk_auth_drift")
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    if initialized or data.get("apiKeySource") != "none":
                        raise SDKRefused("sdk_init_unproven")
                    initialized = True
                    _emit({"type": "system", "subtype": "init", "apiKeySource": "none"})
                elif isinstance(message, ResultMessage):
                    if not initialized:
                        raise SDKRefused("sdk_init_unproven")
                    if message.is_error and message.api_error_status in {401, 403}:
                        await client.interrupt()
                        raise SDKRefused("sdk_auth_drift")
                    if message.is_error and message.api_error_status == 429:
                        raise SDKRefused("sdk_provider_rate_limited")
                    if message.is_error or message.subtype != "success":
                        raise SDKRefused("sdk_result_failed")
                    if options.output_format:
                        import jsonschema
                        try:
                            jsonschema.validate(message.structured_output, options.output_format["schema"])
                        except jsonschema.ValidationError:
                            raise SDKRefused("sdk_invalid_closeout") from None
                        text = json.dumps(message.structured_output)
                    else:
                        text = message.result
                    if not isinstance(text, str) or not text.strip():
                        raise SDKRefused("sdk_result_missing")
                    completed = True
                    _emit({"type": "result", "subtype": "success", "is_error": False, "result": text})
                else:
                    _emit({"type": "sdk_progress"})
            if not completed:
                raise SDKRefused("sdk_result_missing")

        task = asyncio.create_task(receive())
        stop = asyncio.create_task(stopped.wait())
        try:
            done, _ = await asyncio.wait((task, stop), return_when=asyncio.FIRST_COMPLETED)
            if stop in done:
                await client.interrupt()
                raise SDKRefused("sdk_interrupted")
            await task
        finally:
            task.cancel()
            stop.cancel()
            await asyncio.gather(task, stop, return_exceptions=True)


def _options(args):
    from claude_agent_sdk import ClaudeAgentOptions, AgentDefinition, PermissionResultDeny

    async def deny_tool(name, inputs, context):
        return PermissionResultDeny(message="Headless permission request denied")

    agents = {name: AgentDefinition(**definition) for name, definition in json.loads(args.agents).items()}
    extra = {"no-session-persistence": None}
    if args.dangerously_skip_permissions:
        extra["dangerously-skip-permissions"] = None
    return ClaudeAgentOptions(
        cli_path=args.cli_path, cwd=args.cwd, add_dirs=[*args.add_dir, *([args.context_dir] if args.context_dir else [])],
        model=args.model, effort=args.effort, tools=args.tools.split(","), allowed_tools=[],
        disallowed_tools=args.disallowedTools.split(","), permission_mode=args.permission_mode,
        can_use_tool=deny_tool, setting_sources=[], settings=args.settings,
        system_prompt={"type": "preset", "preset": "claude_code",
                       "append": Path(args.instructions_file).read_text(encoding="utf-8")},
        agents=agents, plugins=[{"type": "local", "path": args.plugin_dir}],
        mcp_servers=args.mcp_config, strict_mcp_config=True,
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}, extra_args=extra,
        output_format={"type": "json_schema", "schema": json.loads(args.json_schema)} if args.json_schema else None,
        stderr=lambda _: None, debug_stderr=io.StringIO(),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Subscription-proven solo Claude SDK helper")
    parser.add_argument("--auth-only", action="store_true")
    parser.add_argument("--cli-path", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--instructions-file", required=True)
    parser.add_argument("--context-dir")
    for flag in ("model", "effort", "plugin-dir", "settings", "agents", "mcp-config", "tools", "disallowedTools", "permission-mode", "json-schema"):
        parser.add_argument("--" + flag)
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    args = parser.parse_args(argv)
    try:
        _check_bound_context(tuple(Path(path) for path in
            (args.settings, args.instructions_file, args.mcp_config, args.plugin_dir, args.context_dir) if path))
        version = _check_cli(args.cli_path, args.settings)
        if args.auth_only:
            return 0
        if not sdk_available():
            raise SDKRefused("sdk_dependency_missing")
        logger = logging.getLogger("claude_agent_sdk")
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        _emit({"type": "sdk_version", "sdk": SDK_VERSION, "cli": version,
               "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        asyncio.run(_run(_options(args), sys.stdin.read()))
        _emit({"type": "phase_loop_claude_route_result", "receipt": _receipt("done", "sdk_completed", proven=True)})
        return 0
    except SDKRefused as exc:
        _emit({"type": "phase_loop_claude_route_result", "receipt": _receipt("blocked", str(exc))})
    except Exception:
        # Provider stderr, exceptions, init and dataclass payloads remain private.
        _emit({"type": "phase_loop_claude_route_result", "receipt": _receipt("error", "sdk_failed")})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
