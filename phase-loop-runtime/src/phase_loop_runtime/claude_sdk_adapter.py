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
from .sandbox_policy import CHILD_SCRATCH_RELOCATE, child_scratch_env, _mount_fstype


SDK_VERSION = "0.2.167"
_MARKDOWN_VERSION = "4.2.0"
_AUTH_ERRORS = {"authentication_failed", "billing_error", "oauth_org_not_allowed"}
_MUTABLE_DIRS = ("debug", "projects", "todos", "plans", "session-env", "cache", "plugins", "telemetry")
_PROBE_CWD = Path("/etc/phase-loop-sdk-probe")
_INSTRUCTION_CAPTURE_BYTES = 32 << 20
_INSTRUCTION_CAPTURE_VISITS = 256
_INSTRUCTION_SNAPSHOT_BYTES = 64 << 10


class SDKRefused(ValueError):
    pass


def sdk_available() -> bool:
    try:
        return (importlib.metadata.version("claude-agent-sdk") == SDK_VERSION
                and importlib.metadata.version("markdown-it-py") == _MARKDOWN_VERSION)
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


def _instructions(config: Path, repo: Path, *, home: Path | None = None) -> str:
    import re
    import stat
    import yaml
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        raise SDKRefused("sdk_dependency_missing") from None

    instructions = []
    seen = set()
    active = set()
    user_dependencies = set()
    user_captures = {}
    user_aliases = []
    snapshot_bytes = 0
    remaining_bytes = _INSTRUCTION_CAPTURE_BYTES
    remaining_visits = _INSTRUCTION_CAPTURE_VISITS
    filesystems = {"btrfs", "ext2", "ext3", "ext4", "overlay", "tmpfs", "xfs", "zfs"}

    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def links(path):
        pending = [path]
        recorded = {}
        inspected = set()
        while pending:
            candidate = pending.pop()
            for part in (candidate, *candidate.parents):
                if part in inspected:
                    continue
                inspected.add(part)
                metadata = part.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    target = Path(os.readlink(part))
                    recorded[part] = (identity(metadata), target)
                    if len(recorded) > 40:
                        raise SDKRefused("sdk_instruction_layout_unsupported")
                    pending.append(target if target.is_absolute() else part.parent / target)
        return recorded

    def collect(path, directory, *, rule=False, user=False, depth=0, expected=None, edge=None):
        nonlocal remaining_bytes, remaining_visits, snapshot_bytes
        if not path.exists() and not path.is_symlink():
            if depth:
                raise SDKRefused("sdk_instruction_layout_unsupported")
            return
        if not user and any(part.is_symlink() for part in (path, *path.parents) if part != directory and directory in part.parents):
            raise SDKRefused("sdk_instruction_layout_unsupported")
        before_links = links(path) if user else None
        edge_links = links(edge) if edge is not None else None
        resolved = path.resolve(strict=True)
        if depth > 4 or resolved in active:
            raise SDKRefused("sdk_instruction_layout_unsupported")
        if user:
            remaining_visits -= 1
            if (remaining_visits < 0 or (expected is not None and resolved != expected)
                    or (edge is not None and edge.resolve(strict=True) != resolved)
                    or _mount_fstype(resolved) not in filesystems):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            fd = os.open(resolved, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_uid not in (0, os.getuid()) or before.st_size > remaining_bytes:
                    raise SDKRefused("sdk_instruction_layout_unsupported")
                handle = Path(f"/proc/self/fd/{fd}")
                opened_path = handle.resolve(strict=True)
                previous = user_captures.get(resolved)
                if (_mount_fstype(handle) not in filesystems
                        or identity(opened_path.stat()) != identity(before)
                        or (previous is not None and previous[0] != identity(before))):
                    raise SDKRefused("sdk_instruction_layout_unsupported")
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    data = stream.read(remaining_bytes + 1)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            if (len(data) != before.st_size or identity(before) != identity(after)
                    or path.resolve(strict=True) != resolved or before_links != links(path)
                    or (edge is not None and (edge.resolve(strict=True) != resolved or edge_links != links(edge)))
                    or identity(after) != identity(resolved.stat())):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            remaining_bytes -= len(data)
            capture = (identity(after), data)
            if user_captures.setdefault(resolved, capture) != capture:
                raise SDKRefused("sdk_instruction_layout_unsupported")
            user_aliases.append((path, resolved, before_links, edge, edge_links))
            text = data.decode("utf-8")
            if depth:
                user_dependencies.add(path)
        else:
            if not path.is_file() or not resolved.is_relative_to(directory.resolve()) or path.stat().st_size > 32 << 20:
                raise SDKRefused("sdk_instruction_layout_unsupported")
            text = path.read_text(encoding="utf-8")
        if rule:
            frontmatter = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.S)
            if frontmatter:
                try:
                    metadata = yaml.safe_load(frontmatter.group(1))
                except yaml.YAMLError:
                    raise SDKRefused("sdk_instruction_layout_unsupported") from None
                if isinstance(metadata, dict) and "paths" in metadata:
                    raise SDKRefused("sdk_instruction_layout_unsupported")
                text = text[frontmatter.end():]
        if resolved not in seen:
            size = len(text.encode("utf-8")) + (2 if instructions else 0)
            if "\x00" in text or snapshot_bytes + size > _INSTRUCTION_SNAPSHOT_BYTES:
                raise SDKRefused("sdk_instruction_layout_unsupported")
        import_pattern = r"(?<![^\W_])@([^\s`\"'][^\s]*)"
        scanning = text.replace("\r\n", "\n").replace("\r", "\n")
        has_import = re.search(import_pattern, scanning)
        lines = scanning.split("\n")
        candidate_lines = [False] * len(lines)
        group_start = 0
        for group_end in range(len(lines) + 1):
            if group_end < len(lines) and lines[group_end].strip(" \t"):
                continue
            group = "\n".join(lines[group_start:group_end])
            group_import = bool(re.search(import_pattern, group))
            if group_import and "`" in group and any(char in group for char in "<[]"):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            candidate_lines[group_start:group_end] = [group_import] * (group_end - group_start)
            group_start = group_end + 1
        visible = lines.copy()
        covered = set()
        parser = MarkdownIt("commonmark")
        tokens = parser.parse(scanning)
        if any(token.level >= parser.options.maxNesting - 1 for token in tokens):
            raise SDKRefused("sdk_instruction_layout_unsupported")
        if has_import and re.search(r"`{3,}|~{3,}", scanning) and (
                "]:" in scanning or any(token.type == "html_block" for token in tokens)
                or re.search(r"(?m)^[ \t]*(?:(?:>[ \t]*|(?:[*+-]|\d{1,9}[.)])[ \t]+))*<", scanning)):
            raise SDKRefused("sdk_instruction_layout_unsupported")
        for token in tokens:
            if token.type not in {"fence", "code_block", "inline"}:
                continue
            if token.map is None:
                raise SDKRefused("sdk_instruction_layout_unsupported")
            start, end = token.map
            region = set(range(start, end))
            if not 0 <= start < end <= len(lines) or covered & region:
                raise SDKRefused("sdk_instruction_layout_unsupported")
            covered.update(region)
            block = "\n".join(lines[start:end])
            if token.type in {"fence", "code_block"}:
                if re.search(import_pattern, block):
                    raise SDKRefused("sdk_instruction_layout_unsupported")
                if token.type == "fence" and has_import:
                    closer = r"(?: *> ?)* *" + re.escape(token.markup[0]) + "{" + str(len(token.markup)) + r",} *"
                    native_closer = r"(?: *> ?)* *" + re.escape(token.markup[0]) + "{" + str(len(token.markup)) + r",}[`~]* *"
                    body_lines = token.content.count("\n") + bool(token.content and not token.content.endswith("\n"))
                    if (end - start != body_lines + 2 or not re.fullmatch(closer, lines[end - 1])
                            or any(re.fullmatch(native_closer, line) for line in lines[start + 1:end - 1])):
                        raise SDKRefused("sdk_instruction_layout_unsupported")
                visible[start:end] = [" " * len(line) for line in lines[start:end]]
                continue
            group_has_import = any(candidate_lines[start:end])
            indented = [line for line in block.split("\n") if line.expandtabs(4).startswith("    ")]
            if ((group_has_import and "`" in block
                 and ("\\`" in block or "<" in block or ">" in block or "[" in block or "]" in block or "|" in block or indented
                                   or re.search(r"-->|\?>|\]\]>|(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.)", block, re.I)))
                    or any(re.search(import_pattern, line) for line in indented)):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            span_pattern = r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)"
            if any(re.search(r"\s@\S", match[0])
                   or (group_has_import
                       and ("`" in match[0][len(match[1]):-len(match[1])] or "\n" in match[0]))
                   for match in re.finditer(span_pattern, block, re.S)):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            plain = re.sub(span_pattern,
                           lambda match: re.sub(r"[^\n]", " ", match[0]), block, flags=re.S)
            if "`" in plain:
                raise SDKRefused("sdk_instruction_layout_unsupported")
            visible[start:end] = plain.split("\n")
        prose = "\n".join(visible)
        if "`" in prose:
            raise SDKRefused("sdk_instruction_layout_unsupported")
        dependencies = []
        for match in re.finditer(import_pattern, prose):
            if (not user or len(dependencies) >= remaining_visits
                    or (match.start() and prose[match.start() - 1] in "_\\")):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            reference = match[1]
            if not re.fullmatch(r"[A-Za-z0-9_./~+\-]+", reference):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            if reference.startswith("~"):
                if not reference.startswith("~/") or reference.startswith("~//"):
                    raise SDKRefused("sdk_instruction_layout_unsupported")
                dependency = (home if home is not None else Path.home()) / reference[2:]
            else:
                dependency = Path(reference)
            edge = None
            if not dependency.is_absolute():
                dependency = path.parent / dependency
                edge = resolved.parent / reference
            expected = dependency.resolve(strict=True)
            if edge is not None and expected != edge.resolve(strict=True):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            dependencies.append((dependency, expected, edge))
        if resolved not in seen:
            snapshot_bytes += size
            seen.add(resolved)
            instructions.append(text)
        active.add(resolved)
        try:
            for dependency, expected, edge in dependencies:
                collect(dependency, directory, user=True, depth=depth + 1, expected=expected, edge=edge)
        finally:
            active.remove(resolved)

    try:
        def unreadable_tree(error):
            raise SDKRefused("sdk_context_uninspectable") from None

        for root, directories, files in os.walk(repo, followlinks=False, onerror=unreadable_tree):
            directories[:] = [name for name in directories if name != ".git"]
            directory = Path(root)
            if any((directory / name).is_symlink() for name in directories):
                raise SDKRefused("sdk_instruction_layout_unsupported")
            nested_names = {"CLAUDE.md", "CLAUDE.local.md"} & set(files)
            if directory == repo / ".claude":
                nested_names.discard("CLAUDE.md")
            if "AGENTS.md" in files or (directory != repo and (
                    nested_names
                    or (directory.name == "rules" and directory.parent.name == ".claude"
                        and directory.parent.parent != repo))):
                raise SDKRefused("sdk_instruction_layout_unsupported")
        collect(config / "CLAUDE.md", config, user=True)
        for directory in (repo, *repo.parents):
            for name in ("AGENTS.md", ".claude/AGENTS.md"):
                path = directory / name
                if path == config / "AGENTS.md" and path in user_dependencies:
                    continue
                if path.exists() or path.is_symlink():
                    raise SDKRefused("sdk_instruction_layout_unsupported")
        for directory in (config, *reversed((repo, *repo.parents))):
            for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
                if directory / name != config / "CLAUDE.md":
                    collect(directory / name, directory)
            rules = directory / ("rules" if directory == config else ".claude/rules")
            if rules.is_symlink():
                raise SDKRefused("sdk_instruction_layout_unsupported")
            if rules.is_dir():
                for path in sorted(rules.iterdir()):
                    if path.is_dir() or path.is_symlink():
                        raise SDKRefused("sdk_instruction_layout_unsupported")
                    if path.suffix == ".md":
                        collect(path, directory, rule=True)
        for path, resolved, before_links, edge, edge_links in user_aliases:
            if (path.resolve(strict=True) != resolved or links(path) != before_links
                    or identity(resolved.stat()) != user_captures[resolved][0]
                    or (edge is not None and (edge.resolve(strict=True) != resolved or links(edge) != edge_links))):
                raise SDKRefused("sdk_instruction_layout_unsupported")
    except (FileNotFoundError, RuntimeError):
        raise SDKRefused("sdk_instruction_layout_unsupported") from None
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
        _write_private(root / "instructions.txt", _instructions(config, repo, home=home).encode())
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
            context = Path(directory) / "context.md"
            _write_private(root / "context.md", context.read_bytes())
            owner += ["--ro-bind", str(root / "context.md"), str(context)]
        # Mount after HOME overlays, including when scratch itself is under HOME.
        owner += ["--ro-bind", str(root), str(root)]
        resolved += ["--cli-path", cli, "--instructions-file", str(root / "instructions.txt")]
        child_env = scrub_subscription_env(env)
        child_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        yield [*owner, "--", *resolved], child_env


def auth_preflight(repo: Path, env: Mapping[str, str]) -> bool:
    from .seat_uid import trusted_module_argv

    with bound_command(trusted_module_argv("phase_loop_runtime.claude_sdk_adapter",
                                          "--auth-only", "--cwd", str(repo)), repo, env) as (command, child_env):
        result = subprocess.run(command, env=child_scratch_env(child_env, CHILD_SCRATCH_RELOCATE),
                                cwd=repo, capture_output=True, timeout=45, check=False)
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
            (args.settings, args.instructions_file, args.mcp_config, args.plugin_dir,
             str(Path(args.context_dir) / "context.md") if args.context_dir else None) if path))
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
