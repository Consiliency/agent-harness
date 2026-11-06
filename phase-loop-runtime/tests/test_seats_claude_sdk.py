"""SEATS CLAUDE SL-3: the jailed ``sdk`` transport's host worker, offline (EC-CLAUDE-3).

Generic controls only, all provider-free with synthetic credentials: the real pinned SDK
runs in the real worker payload (bootstrap, filter, closure verification, adapter) against
a fake CLI, through the parent bridge, as the launch fixture records. These prove the bridge
and lifecycle, not real CLI compatibility, billing or memory behaviour, and they cannot
replace the boundary proof (``VB``/``VL``) that GL-2 requires.

``python tests/test_seats_claude_sdk.py capture`` rewrites the launch fixture and its
packaged copy from a fresh offline capture; ``test_the_fixture_is_the_offline_capture``
fails until the committed fixture is that capture.
"""

from __future__ import annotations

import ast
import base64
import copy
import dataclasses
import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from phase_loop_runtime import claude_seat_sdk as sdk
from phase_loop_runtime import claude_seat_transport as ct
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "seats_claude_sdk"
FIXTURE = DATA / "launch-v1.json"
FAKE_CLI = DATA / "fake_cli.py"
OBSERVER = DATA / "filter_observer.py"
REPO = HERE.parent.parent
PACKAGE = Path(sdk.__file__).resolve().parent
PAYLOAD = PACKAGE / "data" / "claude_sdk" / "worker"
SEAT_TOKEN = b"sk-ant-oat01-" + b"SYNTHETICSEATTOKENxyz0123456789abcdef" * 2
MODEL = pi.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["claude"]
EFFORT = "high"
SESSION_ID = "11111111-2222-4333-8444-555555555555"
PROMPT = "Review the staged change and give a verdict."
TOKEN_FD = 9

# --------------------------------------------------------------------------------------
# The declared half of the launch fixture: the reviewed rules. The capture adds what the
# real SDK and worker did under them.
# --------------------------------------------------------------------------------------

OPTIONS = {
    "tools": {"type": "preset", "preset": "claude_code"}, "allowed_tools": [],
    "system_prompt": {"type": "preset", "preset": "claude_code"}, "mcp_servers": {},
    "strict_mcp_config": True, "permission_mode": "bypassPermissions",
    "continue_conversation": False, "resume": None, "session_id": "<SESSION_ID>",
    "max_turns": None, "max_budget_usd": None, "disallowed_tools": [], "model": "<MODEL>",
    "fallback_model": None, "betas": [], "permission_prompt_tool_name": None, "cwd": None,
    "cli_path": None, "settings": "<SETTINGS>", "add_dirs": [], "env": {}, "extra_args": {},
    "max_buffer_size": None, "debug_stderr": None, "stderr": None, "can_use_tool": None,
    "hooks": None, "user": None, "include_partial_messages": False,
    "include_hook_events": False, "forward_subagent_text": False, "verbatim_prompts": False,
    "fork_session": False, "resume_session_at": None, "resume_drops_turn": None,
    "agents": None, "setting_sources": [], "skills": None, "sandbox": None, "plugins": [],
    "max_thinking_tokens": None, "thinking": None, "effort": "<EFFORT>",
    "output_format": None, "enable_file_checkpointing": False, "session_store": None,
    "session_store_flush": "batched", "load_timeout_ms": 60000, "task_budget": None,
}

DECLARED = {
    "schema": "claude-sdk-launch.v1",
    "sdk": {"package": "claude-agent-sdk", "version": "0.2.167", "bundled_cli_version": "2.1.300",
            "transport": "ClaudeSDKClient(options, transport=IPCTransport)"},
    "cli": {
        "argv0": "/seat/bin/claude",
        "delta": {
            "insert_after_argv0": ["--output-format", "stream-json", "--verbose",
                                   "--input-format", "stream-json", "--no-session-persistence"],
            "equals_form": ["--session-id", "--setting-sources"],
            "value_flags": ["--model", "--session-id", "--effort", "--setting-sources",
                            "--settings", "--mcp-config", "--agents", "--permission-mode",
                            "--tools", "--name"],
            "refuse": ["-p", "--print", "--bare", "--continue", "--resume", "--fork-session",
                       "--session-mirror", "--plugin-dir", "--add-dir", "--system-prompt",
                       "--system-prompt-file", "--append-system-prompt",
                       "--include-partial-messages", "--include-hook-events",
                       "--permission-prompt-tool", "--allowedTools", "--disallowedTools",
                       "--resume-session-at", "--json-schema", "--max-turns"],
            "require": {"--tools": "default", "--permission-mode": "bypassPermissions",
                        "--strict-mcp-config": None, "--mcp-config": '{"mcpServers": {}}',
                        "--setting-sources": "", "--agents": "{}",
                        "--no-session-persistence": None},
        },
        "env": {"source": "jail", "additions": {}, "removals": []},
    },
    "options": OPTIONS,
    "protocol": {
        "framing": "ndjson-canonical", "nesting_bound": 64, "frame_cap_bytes": 16 << 20,
        "hello_cap_bytes": 8 << 20,
        "request_id_pattern": "req_[1-9][0-9]{0,5}_[0-9a-f]{8}",
        "outbound": {
            "initialize": {"type": "control_request", "request_id": "<REQUEST_ID>",
                           "request": {"subtype": "initialize", "hooks": None}},
            "user": {"type": "user", "message": {"role": "user", "content": "<PROMPT>"},
                     "parent_tool_use_id": None, "session_id": "default"},
            "interrupt": {"type": "control_request", "request_id": "<REQUEST_ID>",
                          "request": {"subtype": "interrupt"}},
            "sequence": ["initialize", "user", "end_input"],
        },
        "inbound": {
            "forward": ["assistant", "rate_limit_event", "result", "system", "user"],
            "correlated": ["control_response"],
            "refused": ["control_request", "control_cancel_request", "transcript_mirror"],
        },
        "worker_frames": ["ready", "cli", "end_input", "done", "failed"],
        "parent_frames": ["hello", "start", "cli", "eof", "cancel"],
    },
    "worker": {
        "interpreter_flags": ["-I", "-S", "-B"],
        "env": {"HOME": "/worker/home", "TMPDIR": "/worker/tmp", "LANG": "C.UTF-8",
                "PATH": "/nonexistent",
                "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT": "60000",
                "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "600000"},
        "timers": {"CLAUDE_CODE_STREAM_CLOSE_TIMEOUT": "60000",
                   "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "600000"},
        "mounts": {"payload": "/worker/payload", "closure": "/worker/closure"},
        "tmpfs": {"/worker/home": 16 << 20, "/worker/tmp": 16 << 20, "/worker/cwd": 1 << 20},
        "namespaces": ["--unshare-net", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
                       "--die-with-parent", "--new-session", "--cap-drop", "ALL"],
        "limits": {"memory_bytes": 1 << 30, "cpu_seconds": 1800, "processes": 32,
                   "descriptors": 64, "file_bytes": 16 << 20, "core_bytes": 0},
        "filter": {"architecture": "x86_64", "clone": "CLONE_THREAD only",
                   "clone3": "ENOSYS", "socketpair": "AF_UNIX only",
                   "denied": sorted(sdk.X86_64_DENIED)},
    },
    "normalized": ["<CLOSURE_ROOT>", "<FILTER>", "<INVENTORY>", "<MODEL>", "<NONCE>",
                   "<PROMPT>", "<REQUEST_ID>", "<RESULT_TEXT>", "<SESSION_ID>", "<SETTINGS>",
                   "<TOKEN_FD>"],
}


def fake_jail(token_fd: int = TOKEN_FD):
    return types.SimpleNamespace(
        leg="claude", provider_argv0=DECLARED["cli"]["argv0"],
        env=seat_jail.seat_env("claude", token_fd=token_fd), profile_digest="0" * 64)


def settings() -> str:
    return pi._claude_panel_settings({})


def tui_command(session_id: str = SESSION_ID) -> list[str]:
    return pi._broker_claude_tui_command(model=MODEL, effort=EFFORT, session_id=session_id,
                                         sandboxed=fake_jail(), env={})


def owned_argv(fixture=DECLARED, session_id: str = SESSION_ID) -> list[str]:
    return sdk.apply_cli_delta(tui_command(session_id), fixture["cli"]["delta"])


def leg_options(fixture=DECLARED, session_id: str = SESSION_ID) -> dict:
    return sdk.frozen_options(model=MODEL, effort=EFFORT, session_id=session_id,
                              settings=settings(), fixture=fixture)


# --------------------------------------------------------------------------------------
# A test worker install sealed from this environment's own copy of the closure.
# --------------------------------------------------------------------------------------

def _closure_distributions():
    """The installed closure of the two pinned roots, followed through this environment's own
    dependency metadata (a resolver without the lock may float the transitive versions; the
    packaged manifest's binding to the lock is checked separately)."""
    import re as _re
    from importlib import metadata

    from packaging.requirements import Requirement

    def key(name: str) -> str:
        return _re.sub(r"[-_.]+", "-", name).lower()

    found: dict[str, object] = {}
    extras_seen: dict[str, set] = {}
    pending = [("claude-agent-sdk", ()), ("markdown-it-py", ())]
    while pending:
        name, extras = pending.pop()
        name_key = key(name)
        if name_key in found and set(extras) <= extras_seen[name_key]:
            continue
        dist = metadata.distribution(name)
        found[name_key] = dist
        extras_seen.setdefault(name_key, set()).update(extras)
        for line in dist.requires or ():
            requirement = Requirement(line)
            marker = requirement.marker
            if marker is None or any(marker.evaluate({"extra": e})
                                     for e in (*extras_seen[name_key], "")):
                pending.append((requirement.name, tuple(requirement.extras)))
    assert found["claude-agent-sdk"].version == sdk.SDK_VERSION
    assert found["markdown-it-py"].version == sdk.MARKDOWN_IT_VERSION
    return [found[name] for name in sorted(found)]


@dataclasses.dataclass
class SealedInstall:
    install: sdk.WorkerInstall
    state: Path
    manifest_raw: bytes
    venv: Path


def _build_test_venv(root: Path) -> tuple[Path, bytes]:
    """A venv-shaped directory: this interpreter, and a site directory holding exactly the
    closure's files (no bundled CLI: the custom transport never needs it). Returns the venv
    and its synthetic closure manifest."""
    venv = root / "venv"
    real = Path(os.path.realpath(sys.executable))
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(real)
    version = ".".join(str(n) for n in sys.version_info[:3])
    (venv / "pyvenv.cfg").write_text(f"home = {real.parent}\nversion_info = {version}\n")
    site = venv / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"
    site.mkdir(parents=True)
    packages = []
    for dist in _closure_distributions():
        files = {}
        for entry in dist.files or ():
            rel = entry.as_posix()
            parts = rel.split("/")
            if (rel.startswith("..") or "__pycache__" in parts or rel.endswith((".pyc", ".pyo"))
                    or rel == "claude_agent_sdk/_bundled/claude"):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            target = site / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if parts[0].endswith(".dist-info") and parts[-1] in sdk.INSTALLER_METADATA:
                continue
            files[rel] = sdk.file_sha256(target)
        packages.append({"name": dist.metadata["Name"].lower(), "version": dist.version,
                         "files": [[rel, files[rel]] for rel in sorted(files)]})
    manifest = {"schema": sdk.CLOSURE_SCHEMA, "host_class": sdk.HOST_CLASS,
                "export_sha256": sdk.sha256_hex(sdk.read_packaged(sdk.EXPORT)),
                "packages": packages, "excluded": []}
    return venv, sdk.canonical(manifest)


@pytest.fixture(scope="session")
def test_install(tmp_path_factory, record_testsuite_property) -> SealedInstall:
    root = tmp_path_factory.mktemp("sdk-worker")
    venv, manifest_raw = _build_test_venv(root)
    state = root / "state"
    sdk.seal(venv, directory=state, manifest_raw=manifest_raw)
    install = sdk.verify_install(state, manifest_raw=manifest_raw)
    record_testsuite_property("claude_sdk_worker_install_sha256", install.snapshot_sha256)
    return SealedInstall(install, state, manifest_raw, venv)


#: This offline session's named extras. It is no boundary-proof run: no registered worker
#: install and no private suite, so their bindings are fixed markers, and its JUnit can never
#: match a receipt produced by VB or VL.
OFFLINE_EXTRAS = {
    "worker_install_sha256": hashlib.sha256(b"offline: no registered worker install").hexdigest(),
    "instrumentation_wrapper_sha256": hashlib.sha256(OBSERVER.read_bytes()).hexdigest(),
    "private_suite_sha256": hashlib.sha256(b"offline: no private suite").hexdigest(),
}


def _proof_inputs_present() -> bool:
    return all((REPO / rel).is_file() for rel in (*sdk.PROOF_FILES, *sdk.PROOF_REGIONS))


@pytest.fixture(scope="session", autouse=True)
def proof_binding(record_testsuite_property):
    """Binds this session's JUnit to the executing tree's proof inputs: the binding is
    computed at session start, recorded as a suite property, and recomputed at session
    end, where any drift fails. No environment or argument supplies it."""
    if not _proof_inputs_present():
        yield None
        return
    before = sdk.proof_inputs_sha256(REPO, extras=OFFLINE_EXTRAS)
    record_testsuite_property("claude_sdk_proof_inputs_sha256", before)
    yield before
    assert sdk.proof_inputs_sha256(REPO, extras=OFFLINE_EXTRAS) == before, (
        "the proof inputs changed during the session")


# --------------------------------------------------------------------------------------
# The offline duplex driver: the worker, the fake CLI and the bridge, pumped together.
# --------------------------------------------------------------------------------------

@dataclasses.dataclass
class Run:
    verdict: str
    value: str
    bridge: sdk.SDKBridge
    to_worker: list
    from_worker: list
    cli_record: dict | None
    worker_returncode: int | None
    cli_returncode: int | None
    worker_stderr: bytes
    worker_status: dict


def drive(test: SealedInstall, tmp_path: Path, *, mode: str = "ok", fixture=DECLARED,
          token: bytes = SEAT_TOKEN, interpreter: Path | None = None,
          roots: list[str] | None = None, inventory=None, excluded=None,
          worker_env: dict | None = None, deadline_s: float = 120.0,
          tamper=None, payload: Path = PAYLOAD) -> Run:
    """One leg, start to finish. ``tamper`` may rewrite worker bytes before the bridge sees
    them (a control); it never touches what the CLI receives."""
    session_id = SESSION_ID
    bridge = sdk.SDKBridge(token=token, session_id=session_id,
                           prompt=pi._BROKER_CLAUDE_DIRECT_REQUEST + PROMPT, fixture=fixture)
    home, tmp = tmp_path / "worker-home", tmp_path / "worker-tmp"
    home.mkdir(exist_ok=True)
    tmp.mkdir(exist_ok=True)
    env = dict(fixture["worker"]["env"]) if worker_env is None else dict(worker_env)
    env.update({"HOME": str(home), "TMPDIR": str(tmp)})
    p2w_r, p2w_w = os.pipe()
    w2p_r, w2p_w = os.pipe()
    # Offline legs run the bootstrap on this test interpreter (``-I -S -B``, so none of its
    # paths load) with the closure from the sealed snapshot; the sealed interpreter has its
    # own test, and VB/VL run the registered one through the owned launcher.
    worker = subprocess.Popen(
        [str(interpreter or sys.executable), *fixture["worker"]["interpreter_flags"],
         str(payload / "claude_sdk_bootstrap.py"), str(p2w_r), str(w2p_w)],
        pass_fds=(p2w_r, w2p_w), env=env, cwd=tmp, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    os.close(p2w_r)
    os.close(w2p_w)
    to_worker, from_worker = [], []
    worker_status: dict = {}
    record = tmp_path / "cli-record.json"
    cli = None
    worker_err = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(w2p_r, selectors.EVENT_READ, "worker")
    selector.register(worker.stderr, selectors.EVENT_READ, "worker_err")

    def send_worker(data: bytes) -> None:
        to_worker.append(data)
        os.write(p2w_w, data)

    def perform(actions) -> bool:
        for action in actions:
            if action[0] == sdk.TO_WORKER:
                try:
                    send_worker(action[1])
                except BrokenPipeError:
                    pass
            elif action[0] == sdk.TO_CLI:
                cli.stdin.write(action[1])
                cli.stdin.flush()
            elif action[0] == sdk.CLOSE_CLI_STDIN:
                cli.stdin.close()
            elif action[0] == sdk.STOP:
                return True
        return False

    hello = bridge.hello(
        filter_program=sdk.worker_filter_program(),
        roots=roots if roots is not None else [str(test.install.closure_root)],
        inventory=test.install.inventory if inventory is None else inventory,
        excluded=list(test.install.excluded if excluded is None else excluded),
        options=leg_options(fixture, session_id))
    send_worker(hello)
    stopped = False
    open_streams = {"worker", "worker_err"}
    end = time.monotonic() + deadline_s
    try:
        while open_streams and time.monotonic() < end and not stopped:
            for key, _events in selector.select(timeout=0.5):
                chunk = os.read(key.fd, 1 << 16)
                if key.data == "worker_err":
                    if not chunk:
                        selector.unregister(key.fd)
                        open_streams.discard("worker_err")
                    elif len(worker_err) < sdk.WORKER_STDERR_CAP_BYTES:
                        worker_err.extend(chunk)
                    continue
                if key.data == "worker":
                    if not chunk:
                        selector.unregister(key.fd)
                        open_streams.discard("worker")
                        stopped = perform(bridge.worker_eof())
                        continue
                    from_worker.append(chunk)
                    data = tamper(chunk) if tamper is not None else chunk
                    stopped = perform(bridge.worker_bytes(data))
                    if not stopped and bridge.state == "ready" and cli is None:
                        worker_status.update(_proc_status(worker.pid))
                        cli = subprocess.Popen(
                            [sys.executable, "-I", str(FAKE_CLI), *owned_argv(fixture)[1:]],
                            env={**sdk.cli_env(fake_jail()), "FAKE_CLI_MODE": mode,
                                 "FAKE_CLI_RECORD": str(record),
                                 "FAKE_CLI_TOKEN": token.decode()},
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=tmp_path)
                        selector.register(cli.stdout, selectors.EVENT_READ, "cli")
                        selector.register(cli.stderr, selectors.EVENT_READ, "cli_err")
                        open_streams |= {"cli", "cli_err"}
                        stopped = perform(bridge.start())
                elif key.data == "cli":
                    if not chunk:
                        selector.unregister(key.fd)
                        open_streams.discard("cli")
                        stopped = perform(bridge.cli_stdout_eof())
                    else:
                        stopped = perform(bridge.cli_stdout(chunk))
                elif key.data == "cli_err":
                    if not chunk:
                        selector.unregister(key.fd)
                        open_streams.discard("cli_err")
                    else:
                        stopped = perform(bridge.cli_stderr(chunk))
                if stopped:
                    break
    finally:
        for process in (worker, cli):
            if process is not None and process.poll() is None:
                if stopped or time.monotonic() >= end:
                    process.kill()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for fd in (p2w_w, w2p_r):
            try:
                os.close(fd)
            except OSError:
                pass
        for stream in ((cli.stdin, cli.stdout, cli.stderr) if cli else ()) + (worker.stderr,):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        selector.close()
    assert time.monotonic() < end, "the offline leg hit its deadline"
    returncode = cli.returncode if cli is not None else None
    verdict, value = bridge.outcome(returncode if returncode is not None else 1)
    cli_record = json.loads(record.read_text()) if record.exists() else None
    return Run(verdict, value, bridge, to_worker, from_worker, cli_record, worker.returncode,
               returncode, bytes(worker_err), worker_status)


def _proc_status(pid: int) -> dict:
    """The live worker's filter and privilege state, read from outside it."""
    fields = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        name, _sep, value = line.partition(":")
        if name in ("Seccomp", "NoNewPrivs", "Seccomp_filters"):
            fields[name] = value.strip()
    return fields


def _lines(chunks) -> list[dict]:
    return [json.loads(line) for line in b"".join(chunks).splitlines() if line.strip()]


# --------------------------------------------------------------------------------------
# The capture: what the fixture records.
# --------------------------------------------------------------------------------------

def _normalizer(run: Run):
    nonce = run.bridge.nonce
    prompt = pi._BROKER_CLAUDE_DIRECT_REQUEST + PROMPT
    request_ids: list[str] = []

    def norm(value):
        if isinstance(value, str):
            if value == nonce:
                return "<NONCE>"
            if value == prompt:
                return "<PROMPT>"
            if value == SESSION_ID:
                return "<SESSION_ID>"
            if value == MODEL:
                return "<MODEL>"
            if value == settings():
                return "<SETTINGS>"
            if re.fullmatch(DECLARED["protocol"]["request_id_pattern"], value):
                if value not in request_ids:
                    request_ids.append(value)
                return "<REQUEST_ID>"
            if value.startswith("--session-id="):
                return "--session-id=<SESSION_ID>"
            return value
        if isinstance(value, list):
            return [norm(v) for v in value]
        if isinstance(value, dict):
            return {k: norm(v) for k, v in value.items()}
        return value

    return norm


#: What the stock transport adds to the CLI's environment (it also inherits the caller's).
STOCK_ENV_ADDITIONS = ("CLAUDE_CODE_ENTRYPOINT", "CLAUDE_AGENT_SDK_VERSION",
                       "CLAUDE_CODE_SDK_READS_SESSION_STATE",
                       "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING")


def oracle(options: dict) -> dict:
    """The SDK's stock command for the same frozen options: a drift oracle, constructed in
    this test only and never connected."""
    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk._internal.transport import subprocess_cli

    stock = subprocess_cli.SubprocessCLITransport(prompt="", options=ClaudeAgentOptions(**options))
    stock._cli_path = DECLARED["cli"]["argv0"]
    command = stock._build_command()
    source = Path(subprocess_cli.__file__).read_text()
    additions = sorted(name for name in STOCK_ENV_ADDITIONS if f'"{name}"' in source)
    assert additions == sorted(STOCK_ENV_ADDITIONS), "the stock environment additions moved"
    return {"argv": command, "env_additions": additions, "inherits_environment": True}


def _pairs(argv: list[str]) -> list[list]:
    """An argv as sorted ``[flag, value]`` pairs, ``=``-form split, for semantic comparison."""
    out, index, rest = [], 0, argv[1:]
    values = set(DECLARED["cli"]["delta"]["value_flags"]) | {
        "--output-format", "--input-format", "--settings"}
    while index < len(rest):
        token = rest[index]
        if "=" in token and token.startswith("--"):
            flag, value = token.split("=", 1)
            out.append([flag, value])
            index += 1
        elif token in values and index + 1 < len(rest):
            out.append([token, rest[index + 1]])
            index += 2
        else:
            out.append([token, None])
            index += 1
    return sorted(out, key=lambda pair: (pair[0], str(pair[1])))


def capture(test: SealedInstall, tmp_path: Path) -> dict:
    run = drive(test, tmp_path)
    assert run.verdict == "admitted", run.value
    norm = _normalizer(run)
    fixture = copy.deepcopy(DECLARED)
    to_worker = _lines(run.to_worker)
    hello = to_worker[0]
    hello["body"].update({"filter": "<FILTER>", "inventory": "<INVENTORY>",
                          "roots": ["<CLOSURE_ROOT>"]})
    cli_env = {k: v for k, v in run.cli_record["env"].items() if not k.startswith("FAKE_CLI_")}
    cli_env[seat_jail.CLAUDE_TOKEN_FD_ENV] = "<TOKEN_FD>"
    owned = owned_argv()
    stock = oracle(leg_options())
    fixture["capture"] = {
        "method": "offline: real pinned SDK in the real worker payload, fake CLI, parent bridge",
        "cli_argv": norm([DECLARED["cli"]["argv0"], *run.cli_record["argv"]]),
        "cli_env": norm(cli_env),
        "cli_stdin": [norm(json.loads(line)) for line in run.cli_record["stdin"]],
        "cli_stdin_closed_after": "end_input",
        "parent_to_worker": norm(to_worker),
        "worker_to_parent": norm(_lines(run.from_worker)),
        "outcome": [run.verdict, "<RESULT_TEXT>"],
    }
    fixture["oracle"] = {
        "provenance": "SubprocessCLITransport._build_command() on the frozen options (test-only)",
        "argv": norm(stock["argv"]),
        "env_additions": stock["env_additions"],
        "differences": {
            "owned_only": norm([p for p in _pairs(owned) if p not in _pairs(stock["argv"])]),
            "oracle_only": norm([p for p in _pairs(stock["argv"]) if p not in _pairs(owned)]),
            "env": "the owned CLI env is the jail env exactly; the oracle inherits and adds",
        },
    }
    fixture["argv_template"] = norm(owned)
    return fixture


def fixture_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode()


# --------------------------------------------------------------------------------------
# The fixture and the packaged data.
# --------------------------------------------------------------------------------------

def test_the_packaged_launch_data_is_the_test_fixture_byte_for_byte():
    assert sdk.read_packaged(sdk.LAUNCH_FIXTURE) == FIXTURE.read_bytes()


def test_the_fixture_is_the_offline_capture(test_install, tmp_path):
    fresh = fixture_bytes(capture(test_install, tmp_path))
    assert fresh == FIXTURE.read_bytes(), (
        "the launch fixture is not the offline capture; rerun "
        "`python tests/test_seats_claude_sdk.py capture` and review the diff")


def test_the_fixture_declares_the_contract_freeze():
    fixture = json.loads(FIXTURE.read_text())
    delta = fixture["cli"]["delta"]
    assert "-p" in delta["refuse"] and "--bare" in delta["refuse"]
    assert delta["insert_after_argv0"][-1] == "--no-session-persistence"
    assert fixture["options"]["system_prompt"] == {"type": "preset", "preset": "claude_code"}
    assert fixture["capture"]["cli_stdin"] == [
        fixture["protocol"]["outbound"]["initialize"], fixture["protocol"]["outbound"]["user"]]
    assert fixture["argv_template"] == fixture["capture"]["cli_argv"]
    for name in fixture["worker"]["timers"]:
        assert fixture["worker"]["env"][name] == fixture["worker"]["timers"][name]


def test_the_frozen_options_name_every_field_of_the_pinned_sdk():
    from claude_agent_sdk import ClaudeAgentOptions

    assert set(OPTIONS) == {f.name for f in dataclasses.fields(ClaudeAgentOptions)}


def test_the_export_pins_exactly_the_locked_closure():
    import tomllib

    lock_path = REPO / "phase-loop-runtime" / "uv.lock"
    if not lock_path.is_file():
        pytest.skip("the repository lock is a repository-only file")
    lock = {p["name"]: p for p in tomllib.loads(lock_path.read_text())["package"]}
    pending, closure = [("claude-agent-sdk", ()), ("markdown-it-py", ())], set()
    while pending:
        name, extras = pending.pop()
        if (name, extras) in closure:
            continue
        closure.add((name, extras))
        deps = list(lock[name].get("dependencies", []))
        for extra in extras:
            deps += lock[name].get("optional-dependencies", {}).get(extra, [])
        pending += [(d["name"], tuple(d.get("extra", ()))) for d in deps]
    names = {name for name, _extras in closure}
    pins = sdk.export_pins(sdk.read_packaged(sdk.EXPORT))
    assert set(pins) == names
    for name, pin in pins.items():
        package = lock[name]
        assert pin["version"] == package["version"], name
        locked = {w["hash"].split(":", 1)[1] for w in package.get("wheels", [])}
        if "sdist" in package:
            locked.add(package["sdist"]["hash"].split(":", 1)[1])
        assert pin["hashes"] == locked, name
    assert pins["claude-agent-sdk"]["version"] == sdk.SDK_VERSION
    assert pins["markdown-it-py"]["version"] == sdk.MARKDOWN_IT_VERSION


def test_the_closure_manifest_binds_the_export_and_carries_no_bytecode():
    manifest = sdk.closure_manifest()
    assert manifest["export_sha256"] == sdk.sha256_hex(sdk.read_packaged(sdk.EXPORT))
    pins = sdk.export_pins(sdk.read_packaged(sdk.EXPORT))
    for package in manifest["packages"]:
        assert package["wheel_sha256"] in pins[package["name"]]["hashes"]
    assert manifest["excluded"] == ["claude_agent_sdk/_bundled/claude"]
    assert not any(rel.endswith((".pyc", ".pth")) or "__pycache__" in rel
                   for rel in manifest["_files"])


@pytest.mark.parametrize("rows", [{"a.py": "0" * 64}, [["a.py"]], [["a.py", 1]],
                                  [["a.py", "0" * 64], ["a.py", "1" * 64]]])
def test_a_malformed_closure_file_list_refuses(rows):
    manifest = json.loads(sdk.read_packaged(sdk.CLOSURE_MANIFEST))
    manifest["packages"][0]["files"] = rows
    with pytest.raises(sdk.SDKRefused):
        sdk.closure_manifest(sdk.canonical(manifest))


@pytest.mark.parametrize("planted", ["a.pyc", "pkg/__pycache__/m.pyc", "evil.pth"])
def test_a_closure_manifest_with_bytecode_or_a_path_file_refuses(planted):
    manifest = json.loads(sdk.read_packaged(sdk.CLOSURE_MANIFEST))
    manifest["packages"][0]["files"].append([planted, "0" * 64])
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.closure_manifest(sdk.canonical(manifest))
    assert caught.value.code == sdk.PROVENANCE_REFUSED


def test_packaged_data_is_read_only_from_the_installed_package(tmp_path, monkeypatch):
    planted = tmp_path / "data" / "claude_sdk"
    planted.mkdir(parents=True)
    (planted / sdk.LAUNCH_FIXTURE).write_text('{"schema": "planted"}')
    (planted / sdk.RECEIPT).write_text("{}")
    monkeypatch.chdir(tmp_path)
    assert sdk.data_dir() == PACKAGE / "data" / "claude_sdk"
    assert sdk.read_packaged(sdk.LAUNCH_FIXTURE) == FIXTURE.read_bytes()


def test_missing_package_data_refuses_the_route(monkeypatch, tmp_path):
    (tmp_path / "worker").mkdir()
    monkeypatch.setattr(sdk, "data_dir", lambda: tmp_path)
    for name in (sdk.LAUNCH_FIXTURE, sdk.RECEIPT, sdk.EXPORT):
        with pytest.raises(sdk.SDKRefused) as caught:
            sdk.read_packaged(name)
        assert caught.value.code == sdk.DEPENDENCY_UNAVAILABLE
    (tmp_path / sdk.LAUNCH_FIXTURE).symlink_to(FIXTURE)
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.read_packaged(sdk.LAUNCH_FIXTURE)
    assert caught.value.code == sdk.PROVENANCE_REFUSED


# --------------------------------------------------------------------------------------
# The CLI argv and environment.
# --------------------------------------------------------------------------------------

def test_the_argv_is_the_jailed_tui_command_and_the_frozen_delta():
    argv = sdk.build_sdk_cli_argv(fake_jail(), model=MODEL, effort=EFFORT,
                                  session_id=SESSION_ID, env={})
    assert argv == owned_argv(json.loads(FIXTURE.read_text()))
    fixture = json.loads(FIXTURE.read_text())
    rendered = [{"<MODEL>": MODEL, "<SETTINGS>": settings()}.get(t, t)
                .replace("<SESSION_ID>", SESSION_ID) for t in fixture["argv_template"]]
    assert argv == rendered
    assert "-p" not in argv and "--bare" not in argv
    assert f"--session-id={SESSION_ID}" in argv and "--setting-sources=" in argv
    assert argv[argv.index("--tools") + 1] == "default"


@pytest.mark.parametrize("extra", [["-p"], ["--bare"], ["--resume", "x"], ["--print"],
                                   ["--add-dir", "/"], ["--system-prompt", ""],
                                   ["--verbose"], ["--continue"]])
def test_a_forbidden_flag_in_the_jailed_command_refuses(extra):
    with pytest.raises(ValueError):
        sdk.apply_cli_delta([*tui_command(), *extra], DECLARED["cli"]["delta"])


def test_a_changed_required_flag_refuses():
    command = tui_command()
    command[command.index("--tools") + 1] = ""
    with pytest.raises(ValueError):
        sdk.apply_cli_delta(command, DECLARED["cli"]["delta"])


def test_the_cli_environment_is_the_jail_environment_exactly():
    jail = fake_jail()
    assert sdk.cli_env(jail) == jail.env
    assert not {"CLAUDE_CODE_ENTRYPOINT", "CLAUDE_AGENT_SDK_VERSION"} & set(sdk.cli_env(jail))


# --------------------------------------------------------------------------------------
# The worker's syscall filter, observed from outside the worker.
# --------------------------------------------------------------------------------------

def test_the_filter_refuses_an_unqualified_architecture():
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.worker_filter_program("aarch64")
    assert caught.value.code == sdk.WORKER_UNAVAILABLE


def test_the_installed_filter_denies_what_the_contract_forbids(tmp_path):
    """A separate observation wrapper around the unmodified bootstrap's installer."""
    program = base64.b64encode(sdk.worker_filter_program()).decode()
    done = subprocess.run([sys.executable, "-I", "-S", "-B", str(OBSERVER),
                           str(PAYLOAD / "claude_sdk_bootstrap.py"), program],
                          capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-2000:]
    observed = json.loads(done.stdout)
    assert observed == {
        "thread": "allowed", "socketpair_unix": "allowed", "event_loop": "allowed",
        "execve": "denied", "fork": "denied", "socket_inet": "denied", "socket_unix": "denied",
        "socket_alg": "denied", "socketpair_inet": "denied", "unshare": "denied",
        "setuid": "denied", "keyctl": "denied", "ptrace": "denied", "mount": "denied",
    }


# --------------------------------------------------------------------------------------
# The bridge, entered with synthetic frames.
# --------------------------------------------------------------------------------------

def _bridge(**kwargs) -> sdk.SDKBridge:
    bridge = sdk.SDKBridge(token=SEAT_TOKEN, session_id=SESSION_ID,
                           prompt=pi._BROKER_CLAUDE_DIRECT_REQUEST + PROMPT,
                           fixture=DECLARED, **kwargs)
    bridge.hello(filter_program=b"\0" * 8, roots=["/r"], inventory={}, excluded=[],
                 options=leg_options())
    return bridge


class _Worker:
    """Writes worker frames for a bridge, with its own sequence numbers."""

    def __init__(self, bridge: sdk.SDKBridge, nonce: str | None = None):
        self.nonce = nonce or bridge.nonce
        self.seq = 0

    def frame(self, kind: str, body, *, seq: int | None = None) -> bytes:
        data = sdk.canonical({"launch": self.nonce, "seq": self.seq if seq is None else seq,
                              "kind": kind, "body": body}) + b"\n"
        self.seq += 1
        return data


def _nested(depth: int) -> list:
    value: list = []
    for _ in range(depth):
        value = [value]
    return value


RID = "req_1_0123abcd"
INIT = {"type": "control_request", "request_id": RID,
        "request": {"subtype": "initialize", "hooks": None}}


def _user() -> dict:
    return {"type": "user", "message": {"role": "user",
                                        "content": pi._BROKER_CLAUDE_DIRECT_REQUEST + PROMPT},
            "parent_tool_use_id": None, "session_id": "default"}


def _cli(value) -> bytes:
    return (json.dumps(value) + "\n").encode()


def _init_response(rid=RID) -> bytes:
    return _cli({"type": "control_response",
                 "response": {"subtype": "success", "request_id": rid, "response": {}}})


def _ready(bridge):
    worker = _Worker(bridge)
    assert bridge.worker_bytes(worker.frame("ready", {})) == []
    assert bridge.start()[0][0] == sdk.TO_WORKER
    return worker


def _through_user(bridge):
    worker = _ready(bridge)
    actions = bridge.worker_bytes(worker.frame("cli", INIT))
    assert actions == [(sdk.TO_CLI, sdk.canonical(INIT) + b"\n")]
    forwarded = bridge.cli_stdout(_init_response())
    assert forwarded[0][0] == sdk.TO_WORKER and bridge.state == "init_answered"
    actions = bridge.worker_bytes(worker.frame("cli", _user()))
    assert actions == [(sdk.TO_CLI, sdk.canonical(_user()) + b"\n")]
    return worker


def _stream(session=SESSION_ID, source="none", results=1) -> bytes:
    frames = [{"type": "system", "subtype": "init", "session_id": session, "apiKeySource": source},
              {"type": "assistant", "session_id": session,
               "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}]
    frames += [{"type": "result", "subtype": "success", "is_error": False, "result": "VERDICT: ok",
                "session_id": session}] * results
    return b"".join(_cli(f) for f in frames)


def test_the_full_sequence_is_admitted_with_the_parent_templates():
    bridge = _bridge()
    worker = _through_user(bridge)
    assert bridge.worker_bytes(worker.frame("end_input", {})) == [(sdk.CLOSE_CLI_STDIN,)]
    actions = bridge.cli_stdout(_stream())
    assert all(a[0] == sdk.TO_WORKER for a in actions)
    bridge.worker_bytes(worker.frame("done", {"outcome": "result"}))
    assert bridge.outcome(0) == ("admitted", "VERDICT: ok")


def test_an_alternate_encoding_of_the_envelope_changes_nothing_the_cli_reads():
    bridge = _bridge()
    worker = _ready(bridge)
    spaced = json.dumps(INIT, indent=3, ensure_ascii=False).replace("\n", "")
    line = sdk.canonical({"launch": bridge.nonce, "seq": worker.seq, "kind": "cli",
                          "body": json.loads(spaced)}) + b"\n"
    assert bridge.worker_bytes(line) == [(sdk.TO_CLI, sdk.canonical(INIT) + b"\n")]
    bridge.cli_stdout(_init_response())
    worker.seq += 1
    reordered = dict(reversed(list(_user().items())))
    escaped = sdk.canonical({"launch": bridge.nonce, "seq": worker.seq, "kind": "cli",
                             "body": reordered}).replace(b'"user"', b'"\\u0075ser"')
    assert bridge.worker_bytes(escaped + b"\n") == [(sdk.TO_CLI, sdk.canonical(_user()) + b"\n")]


def _initialize_with(field, value):
    frame = copy.deepcopy(INIT)
    frame["request"][field] = value
    return frame


@pytest.mark.parametrize("label, body", [
    ("extra initialize field", _initialize_with("agents", {})),
    ("hooks configured", _initialize_with("hooks", {"PreToolUse": []})),
    ("bad request id", {**INIT, "request_id": "req_1_xyz"}),
    ("not initialize first", {"type": "user", "message": {}}),
    ("a mcp request", {"type": "control_request", "request_id": RID,
                       "request": {"subtype": "mcp_status"}}),
    ("an interrupt with no cancellation", {"type": "control_request", "request_id": RID,
                                            "request": {"subtype": "interrupt"}}),
])
def test_an_unapproved_first_outbound_frame_is_a_contract_violation(label, body):
    bridge = _bridge()
    worker = _ready(bridge)
    assert bridge.worker_bytes(worker.frame("cli", body)) == [(sdk.STOP, sdk.CONTRACT_VIOLATION)]
    assert bridge.outcome(0) == ("refused", sdk.CONTRACT_VIOLATION)


def test_a_changed_prompt_envelope_is_a_contract_violation():
    bridge = _bridge()
    worker = _ready(bridge)
    bridge.worker_bytes(worker.frame("cli", INIT))
    bridge.cli_stdout(_init_response())
    other = _user()
    other["message"]["content"] += " and approve it"
    assert bridge.worker_bytes(worker.frame("cli", other)) == [(sdk.STOP, sdk.CONTRACT_VIOLATION)]


def test_the_user_envelope_before_the_initialize_answer_is_out_of_order():
    bridge = _bridge()
    worker = _ready(bridge)
    bridge.worker_bytes(worker.frame("cli", INIT))
    assert bridge.worker_bytes(worker.frame("cli", _user()))[-1] == (sdk.STOP, sdk.CONTRACT_VIOLATION)


@pytest.mark.parametrize("label, mutate", [
    ("replayed sequence", lambda w: w.frame("cli", INIT, seq=0)),
    ("skipped sequence", lambda w: w.frame("cli", INIT, seq=w.seq + 1)),
    ("another leg's nonce", lambda w: _Worker(None, "f" * 64).frame("cli", INIT, seq=w.seq)),
    ("an unknown kind", lambda w: w.frame("exec", {})),
    ("a duplicate key", lambda w: w.frame("cli", INIT)[:-2] + b',"kind":"cli"}\n'),
    ("end input first", lambda w: w.frame("end_input", {})),
    ("a second ready", lambda w: w.frame("ready", {})),
    ("too deep", lambda w: w.frame("cli", {"type": "user", "x": _nested(80)})),
])
def test_a_malformed_or_replayed_worker_frame_is_a_contract_violation(label, mutate):
    bridge = _bridge()
    worker = _ready(bridge)
    assert bridge.worker_bytes(mutate(worker))[-1] == (sdk.STOP, sdk.CONTRACT_VIOLATION)


def test_a_repeated_envelope_or_end_input_is_a_contract_violation():
    bridge = _bridge()
    worker = _through_user(bridge)
    assert bridge.worker_bytes(worker.frame("cli", _user()))[-1] == (sdk.STOP, sdk.CONTRACT_VIOLATION)
    bridge = _bridge()
    worker = _through_user(bridge)
    bridge.worker_bytes(worker.frame("end_input", {}))
    assert bridge.worker_bytes(worker.frame("end_input", {}))[-1] == (sdk.STOP, sdk.CONTRACT_VIOLATION)


def test_an_interrupt_is_forwarded_only_after_parent_cancellation():
    bridge = _bridge()
    worker = _through_user(bridge)
    bridge.cancel()
    interrupt = {"type": "control_request", "request_id": "req_2_0badcafe",
                 "request": {"subtype": "interrupt"}}
    assert bridge.worker_bytes(worker.frame("cli", interrupt)) == [
        (sdk.TO_CLI, sdk.canonical(interrupt) + b"\n")]


@pytest.mark.parametrize("failure, code", sorted(sdk.WORKER_FAILURES.items()))
def test_a_worker_failure_maps_to_one_typed_code(failure, code):
    bridge = _bridge()
    assert bridge.worker_bytes(_Worker(bridge).frame("failed", {"code": failure})) == [(sdk.STOP, code)]
    assert code in ct.CODES


@pytest.mark.parametrize("label, frame, code", [
    ("an inbound control request", {"type": "control_request", "request_id": "x",
                                    "request": {"subtype": "can_use_tool"}},
     sdk.CONTRACT_VIOLATION),
    ("a cancel request", {"type": "control_cancel_request", "request_id": RID},
     sdk.CONTRACT_VIOLATION),
    ("a transcript mirror", {"type": "transcript_mirror", "filePath": "x", "entries": []},
     sdk.CONTRACT_VIOLATION),
    ("an unknown type", {"type": "telemetry", "x": 1}, sdk.CONTRACT_VIOLATION),
    ("an uncorrelated response", {"type": "control_response",
                                  "response": {"subtype": "success", "request_id": "req_7_00000000"}},
     sdk.CONTRACT_VIOLATION),
])
def test_an_unapproved_inbound_frame_never_reaches_the_sdk(label, frame, code):
    bridge = _bridge()
    _through_user(bridge)
    actions = bridge.cli_stdout(_cli(frame))
    assert actions == [(sdk.STOP, code)]
    assert not any(a[0] == sdk.TO_WORKER for a in actions)


def test_a_duplicate_key_in_any_inbound_frame_is_refused():
    bridge = _bridge()
    _through_user(bridge)
    actions = bridge.cli_stdout(b'{"type":"assistant","message":{"a":1,"a":2}}\n')
    assert actions == [(sdk.STOP, sdk.CONTRACT_VIOLATION)]


def test_a_token_hidden_in_json_escapes_is_caught_after_decoding():
    bridge = _bridge()
    _through_user(bridge)
    escaped = "".join(f"\\u{c:04x}" for c in SEAT_TOKEN)
    actions = bridge.cli_stdout(
        b'{"type":"assistant","message":{"content":"' + escaped.encode() + b'"}}\n')
    assert actions == [(sdk.STOP, sdk.TOKEN_IN_OUTPUT)]


def test_stderr_is_scanned_and_never_forwarded():
    bridge = _bridge()
    _through_user(bridge)
    assert bridge.cli_stderr(b"warning\n") == []
    assert bridge.cli_stderr(b"x" + SEAT_TOKEN) == [(sdk.STOP, sdk.TOKEN_IN_OUTPUT)]


@pytest.mark.parametrize("label, stream, returncode, code", [
    ("a key source", _stream(source="ANTHROPIC_API_KEY"), 0, "claude_seat_api_key_source"),
    ("a second result", _stream(results=2), 0, sdk.RESULT_UNPROVEN),
    ("no result", _stream(results=0), 0, sdk.RESULT_UNPROVEN),
    ("another session", _stream(session="other"), 0, sdk.RESULT_UNPROVEN),
    ("a nonzero exit", _stream(), 1, sdk.RESULT_UNPROVEN),
])
def test_only_one_conforming_result_with_exit_zero_admits(label, stream, returncode, code):
    bridge = _bridge()
    worker = _through_user(bridge)
    bridge.worker_bytes(worker.frame("end_input", {}))
    bridge.cli_stdout(stream)
    bridge.worker_bytes(worker.frame("done", {"outcome": "result"}))
    assert bridge.outcome(returncode) == ("refused", code)


def test_the_worker_view_of_the_session_confers_nothing():
    bridge = _bridge()
    worker = _through_user(bridge)
    bridge.cli_stdout(_stream())
    bridge.worker_bytes(worker.frame("done", {"outcome": "result"}))
    assert bridge.outcome(0) == ("refused", sdk.RESULT_UNPROVEN)  # stdin never ended
    bridge = _bridge()
    worker = _through_user(bridge)
    bridge.worker_bytes(worker.frame("end_input", {}))
    bridge.cli_stdout(_stream())
    bridge.worker_bytes(worker.frame("done", {"outcome": "no_result"}))
    assert bridge.outcome(0) == ("admitted", "VERDICT: ok")


def test_nothing_reaches_the_worker_before_the_leg_starts():
    bridge = _bridge()
    assert bridge.cli_stdout(_init_response()) == [(sdk.STOP, sdk.CONTRACT_VIOLATION)]


def test_the_hello_carries_no_credential():
    bridge = sdk.SDKBridge(token=SEAT_TOKEN, session_id=SESSION_ID,
                           prompt=PROMPT + SEAT_TOKEN.decode(), fixture=DECLARED)
    with pytest.raises(sdk.SDKRefused) as caught:
        bridge.hello(filter_program=b"\0" * 8, roots=["/r"], inventory={}, excluded=[],
                     options=leg_options())
    assert caught.value.code == sdk.TOKEN_IN_OUTPUT


# --------------------------------------------------------------------------------------
# The real SDK in the real worker, offline.
# --------------------------------------------------------------------------------------

def test_a_real_sdk_session_through_the_worker_is_admitted(test_install, tmp_path):
    run = drive(test_install, tmp_path)
    assert (run.verdict, run.cli_returncode, run.worker_returncode) == ("admitted", 0, 0)
    assert run.value.startswith("VERDICT: approve")
    request_id = json.loads(run.cli_record["stdin"][0])["request_id"]
    assert run.cli_record["stdin"] == [sdk.canonical({**INIT, "request_id": request_id}).decode(),
                                       sdk.canonical(_user()).decode()]
    kinds = [frame["kind"] for frame in _lines(run.from_worker)]
    assert kinds == ["ready", "cli", "cli", "end_input", "done"]
    # Observed from outside: the worker runs filtered, without new privileges.
    assert run.worker_status["Seccomp"] == "2" and run.worker_status["NoNewPrivs"] == "1"
    assert int(run.worker_status["Seccomp_filters"]) >= 1


@pytest.mark.parametrize("mode, code", [
    ("inbound_control_request", sdk.CONTRACT_VIOLATION),
    ("uncorrelated_response", sdk.CONTRACT_VIOLATION),
    ("transcript_mirror", sdk.CONTRACT_VIOLATION),
    ("unknown_type", sdk.CONTRACT_VIOLATION),
    ("duplicate_key", sdk.CONTRACT_VIOLATION),
    ("escaped_token", sdk.TOKEN_IN_OUTPUT),
    ("api_key", "claude_seat_api_key_source"),
    ("second_result", sdk.RESULT_UNPROVEN),
    ("no_result", sdk.RESULT_UNPROVEN),
    ("nonzero_exit", sdk.RESULT_UNPROVEN),
])
def test_a_deviating_cli_is_refused_with_its_code(test_install, tmp_path, mode, code):
    run = drive(test_install, tmp_path, mode=mode)
    assert (run.verdict, run.value) == ("refused", code)


def test_no_synthetic_credential_reaches_the_worker(test_install, tmp_path):
    run = drive(test_install, tmp_path)
    for data in (*run.to_worker, *run.from_worker, run.worker_stderr):
        assert not seat_jail.contains_secret(data, SEAT_TOKEN)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in json.dumps(_lines(run.to_worker))
    assert run.worker_stderr == b""


def test_two_concurrent_legs_keep_their_own_credentials_and_nonces(test_install, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    tokens = (SEAT_TOKEN, b"sk-ant-oat01-" + b"OTHERSYNTHETICSEATTOKEN9876543210zyx" * 2)
    dirs = [tmp_path / "a", tmp_path / "b"]
    for directory in dirs:
        directory.mkdir()
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(lambda pair: drive(test_install, pair[0], token=pair[1]),
                             zip(dirs, tokens)))
    assert [r.verdict for r in runs] == ["admitted", "admitted"]
    assert runs[0].bridge.nonce != runs[1].bridge.nonce
    for run, other in ((runs[0], tokens[1]), (runs[1], tokens[0])):
        for data in (*run.to_worker, *run.from_worker):
            assert not seat_jail.contains_secret(data, other)


def test_a_frame_from_another_leg_is_refused(test_install, tmp_path):
    first_dir, second_dir = tmp_path / "a", tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = drive(test_install, first_dir)
    seen = []

    def splice(chunk: bytes) -> bytes:
        seen.append(chunk)
        return first.from_worker[0] if len(seen) == 1 else chunk

    second = drive(test_install, second_dir, tamper=splice)
    assert first.bridge.nonce != second.bridge.nonce
    assert (second.verdict, second.value) == ("refused", sdk.CONTRACT_VIOLATION)


def test_an_invalid_timer_refuses_before_the_session(test_install, tmp_path):
    env = dict(DECLARED["worker"]["env"])
    env["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] = "1e9"
    run = drive(test_install, tmp_path, worker_env=env)
    assert (run.verdict, run.value) == ("refused", sdk.STREAM_UNSAFE)
    assert run.cli_record is None


# --------------------------------------------------------------------------------------
# Closure verification in the worker: shadow packages and bytecode markers.
# --------------------------------------------------------------------------------------

def _writable_copy(install: sdk.WorkerInstall, tmp_path: Path) -> Path:
    root = tmp_path / "closure"
    shutil.copytree(install.closure_root, root)
    os.chmod(root, 0o755)
    for directory, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            os.chmod(os.path.join(directory, name), 0o755)
    return root


@pytest.mark.parametrize("planted", [
    "claude_agent_sdk/__pycache__/client.cpython-314.pyc",
    "anyio/_marker.pyc",
    "zz_marker.pth",
    "json/__init__.py",
    "claude_agent_sdk/extra_module.py",
])
def test_a_planted_file_in_the_closure_refuses_without_running(test_install, tmp_path, planted):
    root = _writable_copy(test_install.install, tmp_path)
    marker = tmp_path / "marker-ran"
    target = root / planted
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    run = drive(test_install, tmp_path, roots=[str(root)])
    assert (run.verdict, run.value) == ("refused", sdk.PROVENANCE_REFUSED)
    assert run.bridge.worker_failure == "closure_unverified"
    assert not marker.exists() and run.cli_record is None


def test_a_changed_closure_file_refuses(test_install, tmp_path):
    root = _writable_copy(test_install.install, tmp_path)
    (root / "anyio" / "__init__.py").write_text("# changed\n")
    run = drive(test_install, tmp_path, roots=[str(root)])
    assert (run.verdict, run.value) == ("refused", sdk.PROVENANCE_REFUSED)


def test_a_missing_closure_file_is_a_missing_dependency(test_install, tmp_path):
    root = _writable_copy(test_install.install, tmp_path)
    (root / "anyio" / "__init__.py").unlink()
    run = drive(test_install, tmp_path, roots=[str(root)])
    assert (run.verdict, run.value) == ("refused", sdk.DEPENDENCY_UNAVAILABLE)


def test_installer_bytecode_beside_the_payload_is_never_loaded(test_install, tmp_path):
    """An installer byte-compiles the payload; a timestamp-valid ``.pyc`` beside it, built
    from other code, must not run in place of the verified source."""
    import importlib._bootstrap_external as external

    payload = tmp_path / "payload"
    shutil.copytree(PAYLOAD, payload, ignore=shutil.ignore_patterns("__pycache__"))
    marker = tmp_path / "marker-ran"
    for name in ("claude_sdk_worker", "claude_sdk_adapter"):
        source = payload / f"{name}.py"
        info = source.stat()
        code = compile(f"open({str(marker)!r}, 'w').write('x')\n", str(source), "exec")
        cache = payload / "__pycache__" / f"{name}.{sys.implementation.cache_tag}.pyc"
        cache.parent.mkdir(exist_ok=True)
        cache.write_bytes(external._code_to_timestamp_pyc(code, int(info.st_mtime), info.st_size))
    run = drive(test_install, tmp_path, payload=payload)
    assert run.verdict == "admitted" and not marker.exists()


def test_a_cwd_shadow_package_is_never_imported(test_install, tmp_path):
    marker = tmp_path / "marker-ran"
    shadow = tmp_path / "worker-tmp" / "claude_agent_sdk"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    run = drive(test_install, tmp_path)
    assert run.verdict == "admitted" and not marker.exists()


# --------------------------------------------------------------------------------------
# The install: seal, snapshot verification and preflight.
# --------------------------------------------------------------------------------------

def test_the_sealed_snapshot_is_read_only_and_self_describing(test_install):
    snapshot = test_install.install.snapshot
    for directory, dirnames, filenames in os.walk(snapshot):
        for name in (*dirnames, *filenames, "."):
            assert not stat.S_IMODE(os.lstat(os.path.join(directory, name)).st_mode) & 0o222
    recorded = json.loads((snapshot / "snapshot.json").read_text())
    assert hashlib.sha256((snapshot / "snapshot.json").read_bytes()).hexdigest() == snapshot.name
    runtime = recorded["runtime"]["files"]
    assert recorded["runtime"]["interpreter"] in runtime
    assert any(rel.endswith("/os.py") for rel in runtime)
    assert not any(rel.endswith(".pyc") or "/__pycache__/" in rel for rel in runtime)
    assert test_install.install.interpreter.is_file()


def test_the_snapshot_interpreter_starts_isolated(test_install):
    done = subprocess.run([str(test_install.install.interpreter), "-I", "-S", "-B", "-c",
                           "import sys, json; print(json.dumps(sys.path))"],
                          capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0, done.stderr[-2000:]
    paths = json.loads(done.stdout)
    assert all(p.startswith(str(test_install.install.runtime_root)) for p in paths if
               os.path.exists(p))


def test_the_sealed_interpreter_runs_a_whole_leg(test_install, tmp_path):
    run = drive(test_install, tmp_path, interpreter=test_install.install.interpreter)
    assert (run.verdict, run.worker_returncode) == ("admitted", 0)


def _venv_copy(test: SealedInstall, tmp_path: Path) -> Path:
    venv = tmp_path / "venv"
    shutil.copytree(test.venv, venv, symlinks=True)
    return venv


@pytest.mark.parametrize("label, change, code", [
    ("an unlisted file", lambda site: (site / "stray.py").write_text("x"), sdk.PROVENANCE_REFUSED),
    ("a path file", lambda site: (site / "zz.pth").write_text("import os"), sdk.PROVENANCE_REFUSED),
    ("a changed file", lambda site: (site / "anyio" / "__init__.py").write_text("x"),
     sdk.PROVENANCE_REFUSED),
    ("a missing file", lambda site: (site / "anyio" / "__init__.py").unlink(),
     sdk.DEPENDENCY_UNAVAILABLE),
    ("a symlink", lambda site: (site / "linked.py").symlink_to("/etc/hostname"),
     sdk.PROVENANCE_REFUSED),
])
def test_seal_refuses_an_install_that_is_not_the_closure(test_install, tmp_path, label, change,
                                                         code):
    venv = _venv_copy(test_install, tmp_path)
    change(next((venv / "lib").glob("python*/site-packages")))
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.seal(venv, directory=tmp_path / "state", manifest_raw=test_install.manifest_raw)
    assert caught.value.code == code


def test_seal_normalizes_installer_bytecode_away(test_install, tmp_path):
    venv = _venv_copy(test_install, tmp_path)
    site = next((venv / "lib").glob("python*/site-packages"))
    (site / "anyio" / "__pycache__").mkdir()
    (site / "anyio" / "__pycache__" / "x.cpython-314.pyc").write_bytes(b"marker")
    registration = sdk.seal(venv, directory=tmp_path / "state",
                            manifest_raw=test_install.manifest_raw)
    snapshot = Path(registration["snapshot"])
    assert not list(snapshot.rglob("*.pyc")) and not list(snapshot.rglob("__pycache__"))


def test_a_changed_snapshot_is_reverified_and_refused(test_install, tmp_path):
    state = tmp_path / "state"
    registration = sdk.seal(_venv_copy(test_install, tmp_path), directory=state,
                            manifest_raw=test_install.manifest_raw)
    install = sdk.verify_install(state, manifest_raw=test_install.manifest_raw)
    target = install.closure_root / "anyio" / "__init__.py"
    os.chmod(target.parent, 0o755)
    os.chmod(target, 0o644)
    target.write_text("# changed\n")
    os.chmod(target, 0o444)
    os.chmod(target.parent, 0o555)
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.verify_install(state, manifest_raw=test_install.manifest_raw)
    assert caught.value.code == sdk.PROVENANCE_REFUSED
    assert registration["snapshot_sha256"] == install.snapshot_sha256


def test_a_registration_that_is_not_private_refuses(test_install, tmp_path):
    state = tmp_path / "state"
    sdk.seal(_venv_copy(test_install, tmp_path), directory=state,
             manifest_raw=test_install.manifest_raw)
    os.chmod(sdk.registration_path(state), 0o644)
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.verify_install(state, manifest_raw=test_install.manifest_raw)
    assert caught.value.code == sdk.PROVENANCE_REFUSED


def test_an_absent_registration_is_a_missing_dependency(tmp_path):
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.verify_install(tmp_path / "nothing")
    assert caught.value.code == sdk.DEPENDENCY_UNAVAILABLE


def test_preflight_refuses_before_any_credential_without_a_receipt(monkeypatch, tmp_path):
    from phase_loop_runtime import seat_credentials

    read = []
    monkeypatch.setattr(seat_credentials, "resolve_claude_seat_credential",
                        lambda *a, **k: read.append(a))
    with pytest.raises(sdk.SDKRefused) as caught:
        sdk.preflight(tmp_path)
    assert caught.value.code == sdk.DEPENDENCY_UNAVAILABLE  # no packaged receipt before GL-2
    assert read == []


def test_run_jailed_refuses_and_tears_down_without_the_proven_install(monkeypatch):
    torn = []
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: torn.append(seat))
    sink: list = []
    evidence: dict = {}
    seat = types.SimpleNamespace(jail=fake_jail(), token=SEAT_TOKEN)
    status, text = sdk.run_jailed(seat, timeout_s=1, backstop_s=1, model=None, effort=None,
                                  prompt=PROMPT, broker_evidence=evidence,
                                  failure_detail_sink=sink)
    assert (status, text) == ("DEGRADED", "")
    # No launch prepared by a pre-credential preflight on the seat: nothing is selected now.
    assert torn == [seat] and sink[0].template == sdk.WORKER_UNAVAILABLE
    assert evidence["claude_admission"] == {"outcome": "refused",
                                            "code": sdk.WORKER_UNAVAILABLE}
    assert evidence["claude_code_entrypoint"] == "unset"


# --------------------------------------------------------------------------------------
# The seat module: unadmitted, no SDK in the parent, typed codes, the receipt.
# --------------------------------------------------------------------------------------

def test_the_seat_module_imports_no_sdk_or_adapter_anywhere():
    tree = ast.parse(Path(sdk.__file__).read_bytes())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
            assert not any(n.startswith(("claude_agent_sdk", "claude_sdk_adapter",
                                         "claude_sdk_worker", "claude_sdk_bootstrap"))
                           for n in names), ast.dump(node)


def test_a_refused_selection_in_a_fresh_process_loads_neither_sdk_nor_adapter(tmp_path):
    code = (
        "import json, sys\n"
        "from phase_loop_runtime import claude_seat_transport as ct\n"
        "from phase_loop_runtime import panel_invoker\n"
        "print(json.dumps([ct.resolve_jailed_claude_transport({'PHASE_LOOP_PANEL_CLAUDE_ROUTE':"
        " 'sdk'}), sorted(m for m in sys.modules if m.startswith(('claude_agent_sdk', "
        "'claude_sdk_', 'phase_loop_runtime.claude_seat_sdk')))]))\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=120, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-2000:]
    assert json.loads(done.stdout) == [[None, ct.NOT_ADMITTED], []]


def test_sdk_lands_unadmitted_and_the_audit_reads_it():
    facts = ct._module_facts(Path(sdk.__file__).read_bytes(), ("ADMITTED", "ACTIVATION"))
    assert facts == {"ADMITTED": False, "ACTIVATION": None}
    assert ct.transport_module("sdk") is None and not ct.is_admitted("sdk")


@pytest.mark.parametrize("code", [sdk.DEPENDENCY_UNAVAILABLE, sdk.PROVENANCE_REFUSED,
                                  sdk.WORKER_UNAVAILABLE, sdk.CONTRACT_VIOLATION])
def test_every_sdk_code_is_typed_and_classed(code):
    klass = ct.od10_class(code)
    assert klass == (ct.SECURITY if code in (sdk.PROVENANCE_REFUSED, sdk.CONTRACT_VIOLATION)
                     else ct.ORDINARY)
    assert sdk.SDKRefused(code).code == code


def test_the_seat_module_depends_only_on_its_inventory():
    assert sdk.module_dependencies(Path(sdk.__file__).read_bytes()) <= set(
        sdk.DEPENDENCY_INVENTORY)


def _receipt() -> dict:
    digest = "a" * 64
    counts = {"collected": 3, "passed": 3, "failed": 0, "skipped": 0}
    return {
        "schema": sdk.RECEIPT_SCHEMA, "sdk_version": sdk.SDK_VERSION, "lock_sha256": digest,
        "contract_sha256": digest, "proof_inputs_sha256": digest,
        "installed_bindings": {name: digest for name in ct.SDK_INSTALLED_BINDINGS},
        "source_regions": {f"{rel}::{name}": digest
                           for rel, names in sdk.PROOF_REGIONS.items() for name in names},
        "runtime_manifest_sha256": [digest], "worker_install_sha256": digest,
        "instrumentation_wrapper_sha256": digest, "profile_digest": digest,
        "interpreter": {"implementation": "cpython", "version": "3.14.4"},
        "host_class": sdk.HOST_CLASS,
        "public_junit": {s: {"sha256": digest, "files": {"test_seats_claude_sdk.py": counts}}
                         for s in ("VB", "VL")},
        "private_suite": {"suite_sha256": digest, "evidence_ids": ["ev-" + "b" * 32],
                          "junit": {s: {"sha256": digest,
                                        "selectors": {"ev-" + "c" * 32: counts}}
                                    for s in ("VB", "VL")}},
    }


def test_a_complete_receipt_validates():
    assert sdk.validate_receipt(_receipt()) == []


@pytest.mark.parametrize("label, mutate", [
    ("an unknown field", lambda r: r.update(note="x")),
    ("a missing field", lambda r: r.pop("proof_inputs_sha256")),
    ("a skipped test", lambda r: r["public_junit"]["VB"]["files"]["test_seats_claude_sdk.py"]
     .update(skipped=1, passed=2)),
    ("zero collected", lambda r: r["public_junit"]["VL"]["files"]["test_seats_claude_sdk.py"]
     .update(collected=0, passed=0)),
    ("a private test name", lambda r: r["private_suite"]["junit"]["VB"]["selectors"].update(
        {"test_private_case": {"collected": 1, "passed": 1, "failed": 0, "skipped": 0}})),
    ("a path", lambda r: r.update(host_class="/home/operator")),
    ("another sdk", lambda r: r.update(sdk_version="0.2.168")),
])
def test_an_incomplete_or_revealing_receipt_refuses(label, mutate):
    receipt = _receipt()
    mutate(receipt)
    assert sdk.validate_receipt(receipt)


def _proof_tree(tmp_path: Path) -> Path:
    if not _proof_inputs_present():
        pytest.skip("the proof inputs are repository-only files")
    for rel in (*sdk.PROOF_FILES, *sdk.PROOF_REGIONS):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, target)
    return tmp_path


def test_the_proof_binding_moves_only_with_its_inputs(tmp_path):
    tree = _proof_tree(tmp_path)
    before = sdk.proof_inputs_sha256(tree, extras=OFFLINE_EXTRAS)
    (tree / "unrelated.md").write_text("outside the proof inputs\n")
    assert sdk.proof_inputs_sha256(tree, extras=OFFLINE_EXTRAS) == before
    lock = tree / "phase-loop-runtime" / "uv.lock"
    lock.write_text(lock.read_text() + "\n")
    assert sdk.proof_inputs_sha256(tree, extras=OFFLINE_EXTRAS) != before


def test_a_changed_shared_region_stales_the_proof(tmp_path):
    tree = _proof_tree(tmp_path)
    before = sdk.proof_inputs_sha256(tree, extras=OFFLINE_EXTRAS)
    jail = tree / "phase-loop-runtime/src/phase_loop_runtime/seat_jail.py"
    source = jail.read_text()
    jail.write_text(source.replace('"DISABLE_AUTOUPDATER": "1",',
                                   '"DISABLE_AUTOUPDATER": "1", "EXTRA": "1",', 1))
    assert sdk.proof_inputs_sha256(tree, extras=OFFLINE_EXTRAS) != before


def test_a_missing_proof_input_fails_closed(tmp_path):
    tree = _proof_tree(tmp_path)
    (tree / sdk.PROOF_FILES[-1]).unlink()
    with pytest.raises(sdk.SDKRefused):
        sdk.proof_inputs_sha256(tree, extras=OFFLINE_EXTRAS)


# --------------------------------------------------------------------------------------
# Rewriting the fixture (a maintainer action, reviewed like any other diff).
# --------------------------------------------------------------------------------------

def _write_capture() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        venv, manifest_raw = _build_test_venv(root)
        sdk.seal(venv, directory=root / "state", manifest_raw=manifest_raw)
        install = sdk.verify_install(root / "state", manifest_raw=manifest_raw)
        test = SealedInstall(install, root / "state", manifest_raw, venv)
        leg = root / "leg"
        leg.mkdir()
        data = fixture_bytes(capture(test, leg))
        for path in (FIXTURE, PACKAGE / "data" / "claude_sdk" / sdk.LAUNCH_FIXTURE):
            path.write_bytes(data)
        for path in root.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                os.chmod(path, 0o755)
    print(hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    if sys.argv[1:] == ["capture"]:
        _write_capture()
    else:
        raise SystemExit("usage: test_seats_claude_sdk.py capture")
