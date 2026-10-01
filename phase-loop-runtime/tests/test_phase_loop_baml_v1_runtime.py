"""BAML v1 worker runtime: parity, register pins, worker faults and the client
invariants I1-I9 (agent-harness#1135).

Everything here drives the REAL ``_baml_worker.py`` subprocess and the real
v1 runtime; nothing on the BAML side is stubbed.  Two narrow exceptions, each
named where it is used:

- framing, blocked-write and hung-init cases launch a scripted peer
  (``tests/fixtures/baml_worker_peers.py``) through the client's own spawn
  seam ``baml_modular._spawn_popen``, because a real worker cannot be made to
  emit a malformed frame;
- the I1 cold-start and stalled-spawn sweeps use the ``echo`` peer, so that a
  few hundred injection runs do not each pay the ~0.8 s v1 cold start.  The
  sweep exercises the client's lifecycle, which is identical for either peer.

Fault, signal, fork and owner-death cases each run in a fresh interpreter
(``_isolated``) that must exit 0, so a scenario can never poison the pytest
process.  Assertions use ``type(e)``, ``.kind`` and ``.rc`` only, never message
text (register #19).
"""
from __future__ import annotations

import ast
import collections
import ctypes
import gc
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from phase_loop_runtime import baml_modular as m
from phase_loop_runtime.baml_modular import BamlValidationError, BamlWorkerError

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
PKG = SRC / "phase_loop_runtime"
PEERS = TESTS / "fixtures" / "baml_worker_peers.py"
BASELINE = TESTS / "data" / "baml_v0_baseline"
PROMPT_GOLDENS = TESTS / "data" / "baml_closeout_prompt_goldens.json"
MODULE = Path(__file__).stem

POSIX = os.name == "posix"
LINUX = sys.platform.startswith("linux")
MACOS = sys.platform == "darwin"
WINDOWS = os.name == "nt"
PY312 = sys.version_info >= (3, 12)

OK_PAYLOAD = {
    "terminal_status": "complete",
    "verification_status": "passed",
    "dirty_paths": [],
    "produced_if_gates": ["G"],
    "required_human_inputs": [],
}
OK = json.dumps(OK_PAYLOAD)
EVIDENCE = {
    "tier2_signal_summary": "signal",
    "sample_artifact_content": "sample",
    "expected_artifact_characteristics": "expected",
}
CLOSEOUT = {"phase_alias": "P1", "plan_produces": ["IF-0-P1-1"], "plan_owned_files": ["a.py"], "closeout_commit_sha": "abc123"}
ENV_SENTINELS = {
    "OPENAI_API_KEY": "ENVSENTINEL-openai-api-key",
    "OPENAI_BASE_URL": "https://envsentinel-openai-base-url.invalid/v1",
    "ANTHROPIC_API_KEY": "ENVSENTINEL-anthropic-api-key",
    "BAML_LOG": "ENVSENTINEL-baml-log",
    "BAML_TRACE": "ENVSENTINEL-baml-trace",
    "BAML_HOME": "/envsentinel-baml-home",
    "BOUNDARY_API_KEY": "ENVSENTINEL-boundary-api-key",
    "BOUNDARY_PROJECT_ID": "ENVSENTINEL-boundary-project-id",
    "HOME": "/envsentinel-home",
    "HTTPS_PROXY": "http://envsentinel-https-proxy.invalid:1",
}
REAP_BOUND = m._REAP_BOUND_S
_REAL_RAW = m._read_raw_baml_files
_REAL_SPAWN = m._spawn_popen

needs_posix = pytest.mark.skipif(not POSIX, reason="POSIX-only: fork, signals and process groups")
needs_linux = pytest.mark.skipif(not LINUX, reason="Linux-only: PR_SET_PDEATHSIG and /proc")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _baseline(name: str) -> dict:
    return json.loads((BASELINE / name).read_text(encoding="utf-8"))


def _pid() -> int | None:
    gen = m._CLIENT.gen
    return gen.pid if gen is not None else None


def _gone(pid: int) -> bool:
    """True when ``pid`` no longer exists at all: exited AND reaped.

    The same predicate on every platform.  A zombie is NOT gone: for a worker
    of this process only the client itself can reap it, so a zombie means the
    client killed it but never waited on it (it hid a leak on Linux, where this
    once counted zombies as gone; found on macOS)."""
    if LINUX:
        return not Path(f"/proc/{pid}").exists()
    if WINDOWS:
        import psutil  # os.kill(pid, 0) would send CTRL_C_EVENT on Windows

        return not psutil.pid_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _reaped(gen) -> bool:
    """The client itself waited on this worker (``returncode`` is set only by
    the client's own poll/wait) AND the process no longer exists.  On Windows,
    where ``_gone`` can only see the PID, the return code is what proves it."""
    return gen.proc.returncode is not None and _gone(gen.pid)


def _wait(cond, timeout: float, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if cond():
            return True
        if time.monotonic() >= deadline:
            return bool(cond())
        time.sleep(interval)


def _log() -> list[dict]:
    return m.worker_fault_log()


def _bridge_with(fn: str, prefix: str) -> str:
    """The real bridge with ``prefix`` statements inserted at the top of ``fn``."""
    text = _REAL_RAW()["phase_loop_bridge.baml"]
    start = text.index(f"function {fn}(")
    brace = text.index("-> map<string, string> {", start) + len("-> map<string, string> {")
    return text[:brace] + "\n    " + prefix + text[brace:]


def _sleep(seconds: float) -> str:
    return f"baml.sys.sleep(baml.time.Duration.from_milliseconds({int(seconds * 1000)}));"


def _files(**overrides: str) -> dict[str, str]:
    files = dict(_REAL_RAW())
    for name, text in overrides.items():
        files[name if name.endswith(".baml") else name + ".baml"] = text
    return files


def _hostile(fn: str, prefix: str) -> dict[str, str]:
    return _files(phase_loop_bridge=_bridge_with(fn, prefix))


SPAWN_HOOK = 'let hook = spawn with baml.spawn.options(detach = true) { throw baml.errors.Io { message: "boom" } };'
PANIC_PARSE = (
    "function phase_loop_parse_closeout(raw: string) -> map<string, string> {\n"
    "    let xs = [1];\n    let y = xs[5];\n    { \"ok\": \"x\" }\n}\n"
)


def _panic_files() -> dict[str, str]:
    text = _REAL_RAW()["phase_loop_bridge.baml"]
    start = text.index("function phase_loop_parse_closeout(")
    end = text.index("function phase_loop_closeout_request(")
    return _files(phase_loop_bridge=text[:start] + PANIC_PARSE + "\n" + text[end:])


def _use(files: dict[str, str] | None = None, **config) -> None:
    m._read_raw_baml_files = (lambda files=files: dict(files)) if files is not None else _REAL_RAW
    m._reset_worker_for_tests(test_mode=True, **config)


def _peer_spawn(mode: str, *, first_only: bool = False, record: list | None = None):
    """A ``_spawn_popen`` replacement that launches a scripted peer."""
    used = {"n": 0}

    def spawn(argv, **kwargs):
        used["n"] += 1
        if first_only and used["n"] > 1:
            proc = _REAL_SPAWN(argv, **kwargs)
        else:
            proc = _REAL_SPAWN([argv[0], "-I", "-S", str(PEERS), mode, *argv[4:]], **kwargs)
        if record is not None:
            record.append(proc.pid)
        return proc

    return spawn


def _parse() -> dict:
    return m.parse_baml_response("EmitPhaseCloseout", OK).payload


def _raises(fn, *args, **kwargs) -> BaseException:
    try:
        fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 - the caller asserts the exact type
        return exc
    raise AssertionError("expected an exception")


def _cold_slack() -> float:
    """Extra time for waits that include a worker cold start (~0.8 s on x86_64
    glibc, ~13 s on musl).  Measured by ``_deadline()``, which every scenario
    setup runs first."""
    return 3 * _COLD[0] if _COLD else 30.0


def _busy_pid(timeout: float | None = None) -> int:
    timeout = 10.0 + _cold_slack() if timeout is None else timeout
    assert _wait(lambda: m._CLIENT.gen is not None and m._CLIENT.gen.state == "busy", timeout), "worker never became busy"
    return m._CLIENT.gen.pid


class _Killer:
    """Kills busy workers mid-call: the first one only, or every one."""

    def __init__(self, *, every: bool = False, delay: float = 0.5) -> None:
        self.every = every
        self.delay = delay
        self.killed: list[int] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop.is_set():
            gen = m._CLIENT.gen
            if gen is not None and gen.state == "busy" and gen.pid not in self.killed:
                time.sleep(self.delay)
                if gen.state == "busy":
                    os.kill(gen.pid, signal.SIGKILL)
                    self.killed.append(gen.pid)
                    if not self.every:
                        return
            time.sleep(0.01)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(5)


def _async_raise(thread: threading.Thread, exc_type: type) -> None:
    ident = ctypes.c_ulong(thread.ident)
    if ctypes.pythonapi.PyThreadState_SetAsyncExc(ident, ctypes.py_object(exc_type)) != 1:
        raise AssertionError("could not deliver an async exception")


def _thread_named(name: str) -> threading.Thread | None:
    return next((t for t in threading.enumerate() if t.name == name and t.is_alive()), None)


class _DeliverySpy:
    """Counts deliveries per request at the reply seam (I2)."""

    def __init__(self) -> None:
        self.requests: list = []
        self.counts: collections.Counter = collections.Counter()
        self.outcomes: dict = {}
        self._deliver = m._deliver
        self._handle = m._Client._handle
        spy = self

        def handle(client, event):
            # A request counts once the owner has ACCEPTED it; one that never left
            # the calling thread (an exception before the hand-off) has no reply.
            if event[0] == "request":
                spy.requests.append(event[1])
            spy._handle(client, event)

        def deliver(req, outcome):
            spy.counts[id(req)] += 1
            spy.outcomes[id(req)] = outcome
            assert spy.counts[id(req)] == 1, "a request was answered twice"
            spy._deliver(req, outcome)

        m._Client._handle = handle
        m._deliver = deliver

    def close(self) -> None:
        m._Client._handle = self._handle
        m._deliver = self._deliver

    def assert_each_once(self, timeout: float = 10.0) -> None:
        assert _wait(lambda: all(self.counts[id(r)] == 1 for r in self.requests), timeout), [
            self.counts[id(r)] for r in self.requests
        ]


_COLD: list[float] = []


def _deadline() -> float:
    """A per-attempt deadline that covers this host's real cold start.

    The attempt deadline spans spawn + init + op, and v1's init is ~0.8 s on a
    fast x86_64 host but slower elsewhere (it timed out at 1 s on
    macos-15-intel).  Measured once per scenario process."""
    if not _COLD:
        _use(None)
        started = time.perf_counter()
        _parse()
        _COLD.append(time.perf_counter() - started)
    return max(1.5, 4 * _COLD[0])


def _isolated(name: str, *, timeout: float = 180.0, env: dict | None = None) -> str:
    """Run ``scenario_<name>`` from this module in a fresh interpreter; it must exit 0.

    Every scenario interpreter re-installs Python's SIGINT handler first: a
    parent started as a background job (``cmd &`` without job control) passes
    SIGINT down IGNORED, and Python then never installs ``default_int_handler``,
    so SIGINT-driven scenarios would silently receive nothing."""
    code = (
        "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; t.scenario_%s(); "
        "sys.stdout.flush(); import os; os._exit(0)" % (str(TESTS), str(SRC), MODULE, name)
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
        cwd=str(TESTS.parent),
    )
    assert proc.returncode == 0, f"scenario_{name} exited {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    return proc.stdout


def _scenario_setup(files=None, **config) -> _DeliverySpy:
    _deadline()  # measures this host's cold start once per process (see _cold_slack)
    _use(files, **config)
    return _DeliverySpy()


@pytest.fixture
def client():
    """In-process tests: a fresh test-mode client, restored afterwards."""
    spy = _scenario_setup()
    try:
        yield spy
        spy.assert_each_once()
    finally:
        spy.close()
        m._spawn_popen = _REAL_SPAWN
        _use(None)
        m._reset_worker_for_tests()


# ---------------------------------------------------------------------------
# parity against the Step 0 goldens (register #1-#3, #12, #20, #21, #23)
# ---------------------------------------------------------------------------


def test_parse_corpus_matches_v0_on_one_worker(client):
    corpus = _baseline("parse_corpus.json")["corpus"]
    assert len(corpus) >= 95
    _parse()
    pid, log = _pid(), _log()
    for key, entry in corpus.items():
        expected = entry["v0"]
        try:
            actual = m.parse_baml_response("EmitPhaseCloseout", entry["input"]).payload
        except BaseException as exc:  # noqa: BLE001
            assert type(exc) is BamlValidationError, (key, type(exc))
            actual = "BamlValidationError"
        if key == "pix_2p70":
            # #12: v0 clamped an int > i64; v1 yields null.  Flagged, accepted.
            assert expected["visual_evidence_non_black_pixels"] == 2**63 - 1
            assert actual["visual_evidence_non_black_pixels"] is None
            assert {k: v for k, v in actual.items() if k != "visual_evidence_non_black_pixels"} == {
                k: v for k, v in expected.items() if k != "visual_evidence_non_black_pixels"
            }
            continue
        assert actual == expected, key
    assert _pid() == pid, "an input surfaced as a worker fault"
    assert _log() == log


def test_function_names_outside_the_bridge_table_match_v0(client):
    names = _baseline("parse_corpus.json")["names"]
    for key, entry in names.items():
        exc = _raises(m.parse_baml_response, entry["function"], entry["input"])
        assert type(exc) is BamlValidationError and entry["v0"] == "BamlValidationError", key
    requests = _baseline("closeout_requests_v0.json")["requests"]
    for fn in ("NoSuchFunction", "DotfilesAdoptionManifest"):
        assert requests[f"name:{fn}"]["v0"] == "BamlValidationError"
        exc = _raises(m.build_baml_request, fn, {})
        assert type(exc) is BamlValidationError, fn


def _request_view(req) -> dict:
    messages = req.body.get("messages") or []
    return {
        "url": req.url,
        "method": req.method,
        "headers": req.headers,
        "body": req.body,
        "message_roles": [msg.get("role") for msg in messages],
        "message_content_types": [type(msg.get("content")).__name__ for msg in messages],
        "prompt": req.prompt,
        "prompt_sha256": hashlib.sha256(req.prompt.encode("utf-8")).hexdigest(),
    }


def test_evidence_request_equals_v0_on_every_field(client):
    for key, entry in _baseline("evidence_requests.json")["requests"].items():
        request = m.build_baml_request("EvaluateSuspectedFakeEvidence", entry["payload"])
        assert request.id is None  # #20
        assert _request_view(request) == entry["v0"], key


def test_closeout_request_envelope_equals_v0(client):
    requests = _baseline("closeout_requests_v0.json")["requests"]
    for key in ("empty", "two_gates_sha", "two_gates_nosha", "sentinels", "sha_empty"):
        v0 = requests[key]["v0"]
        view = _request_view(m.build_baml_request("EmitPhaseCloseout", requests[key]["payload"]))
        for field in ("url", "method", "headers", "message_roles", "message_content_types"):
            assert view[field] == v0[field], (key, field)
        assert sorted(view["body"]) == sorted(v0["body"])
        assert view["body"]["model"] == v0["body"]["model"]
        # The prompt differs by D1 only; its bytes are pinned by the refresh goldens.
        assert view["prompt"] != v0["prompt"]


def test_closeout_prompt_goldens_d1_d1a(client):
    goldens = json.loads(PROMPT_GOLDENS.read_text(encoding="utf-8"))
    requests = _baseline("closeout_requests_v0.json")["requests"]
    schema = m.export_function_schema("EmitPhaseCloseout")
    schema_sha = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    marker = "\n\nPhase-loop closeout JSON schema description:\n"
    for key, golden in goldens["prompts"].items():
        request = m.build_baml_request("EmitPhaseCloseout", requests[key]["payload"])
        assert hashlib.sha256(request.prompt.encode("utf-8")).hexdigest() == golden["sha256"], key
        assert request.prompt == golden["prompt"], key
        assert request.prompt.count(marker) == 1
        assert f"schema_sha256: {schema_sha}" in request.prompt
        # D1a: the description tail is byte-identical to v0's.
        v0_prompt = requests[key]["v0"]["prompt"]
        assert request.prompt[request.prompt.index(marker):] == v0_prompt[v0_prompt.index(marker):]
        (message,) = request.body["messages"]
        assert message["role"] == "user"
        assert message["content"] == request.prompt
        assert not request.prompt.startswith("[")
    literals = m._baml_prompt_context_constants()
    prompt = m.build_baml_request("EmitPhaseCloseout", CLOSEOUT).prompt
    contract = prompt[: prompt.index(marker)]
    for values in literals.values():
        for literal in values:
            assert literal in contract, literal  # #5: enums stay in the contract prose


def test_schema_dump_equals_step_0(client):
    golden = _baseline("schema_dump.json")["schema"]
    text = "\n".join(m._read_baml_files().values())
    classes = sorted(set(re.findall(r"\bclass\s+([A-Za-z_]\w*)\s*\{", text)))
    functions = sorted(set(re.findall(r"\bfunction\s+([A-Z]\w*)\s*\(", text)))
    assert {c: [list(f) for f in m._class_fields(text, c)] for c in classes} == golden["class_fields"]
    assert {n: m.export_function_schema(n) for n in [*classes, *functions]} == golden["export_function_schema"]
    assert {k: list(v) for k, v in sorted(m._enum_literal_map().items())} == golden["enum_literal_map"]


def test_payload_filtering_requirements_and_normalization(client):
    base = m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
    # #7: an extra key is filtered to the signature.
    assert m.build_baml_request("EvaluateSuspectedFakeEvidence", {**EVIDENCE, "extra": "x"}) == base
    # #8: a missing key is a plain error before the worker is called.
    pid, log = _pid(), _log()
    exc = _raises(m.build_baml_request, "EvaluateSuspectedFakeEvidence", {"tier2_signal_summary": "a"})
    assert type(exc) is BamlValidationError
    assert (_pid(), _log()) == (pid, log)
    # #9: closeout_commit_sha "" is v0's "none".
    empty_sha = m.build_baml_request("EmitPhaseCloseout", {**CLOSEOUT, "closeout_commit_sha": ""})
    no_sha = m.build_baml_request("EmitPhaseCloseout", {**CLOSEOUT, "closeout_commit_sha": None})
    assert empty_sha == no_sha
    assert "Closeout commit SHA: none" in no_sha.prompt
    # #10: a backslash in a list value renders (v0 raised re.error).
    assert _baseline("closeout_requests_v0.json")["requests"]["backslash"]["v0"] == "re.error"
    backslash = m.build_baml_request("EmitPhaseCloseout", {**CLOSEOUT, "plan_produces": ["C:\\new\\s"]})
    assert "- C:\\new\\s" in backslash.prompt
    # #11: template syntax inside caller values stays literal.
    templated = m.build_baml_request(
        "EmitPhaseCloseout", {**CLOSEOUT, "phase_alias": "P${X}{{ y }}", "plan_owned_files": ["{% if %}"]}
    )
    assert "P${X}{{ y }}" in templated.prompt and "- {% if %}" in templated.prompt


def test_snapshot_is_per_process_until_reset(client):
    """#29: the regex readers read the snapshot taken at first use."""
    before = m.export_function_schema("EmitPhaseCloseout")
    edited = _files(emit_phase_closeout=_REAL_RAW()["emit_phase_closeout.baml"].replace(
        "    next_action: string?,", "    next_action: string?,\n    extra_field: string?,"
    ))
    m._read_raw_baml_files = lambda: dict(edited)
    assert m.export_function_schema("EmitPhaseCloseout") == before
    m._reset_worker_for_tests(test_mode=True)
    assert "extra_field" in m.export_function_schema("EmitPhaseCloseout")["properties"]


def test_d3_field_syntax_stays_strict():
    text = 'class Strict {\n    status: "a" | "b",\n}\n'
    assert type(_raises(m._class_fields, text, "Strict")) is BamlValidationError
    assert m._class_fields("class Both {\n    a: string,\n    b int?\n}\n", "Both") == [("a", "string", False), ("b", "int", True)]


def test_adoption_bundle_excludes_the_bridge(tmp_path):
    """#26: schema refs are the 8 schema files; editing the bridge changes nothing."""
    from phase_loop_runtime import adoption_bundle

    root = tmp_path / adoption_bundle.BAML_SCHEMA_ROOT
    root.mkdir(parents=True)
    for path in (PKG / "baml_src").glob("*.baml"):
        (root / path.name).write_bytes(path.read_bytes())
    refs = adoption_bundle._schema_refs(tmp_path)
    assert len(refs) == 8
    assert all(not ref["source_path"].endswith("phase_loop_bridge.baml") for ref in refs)
    (root / "phase_loop_bridge.baml").write_text("// edited\n", encoding="utf-8")
    assert adoption_bundle._schema_refs(tmp_path) == refs
    assert adoption_bundle._stale_schema_refs(refs, adoption_bundle._schema_refs(tmp_path)) == []


def test_adoption_bundle_refresh_and_check_end_to_end(tmp_path):
    """#26 end to end: refresh writes a bundle whose check is fresh; a bridge edit
    keeps it fresh; a schema edit makes it stale."""
    from phase_loop_runtime import adoption_bundle

    root = tmp_path / adoption_bundle.BAML_SCHEMA_ROOT
    root.mkdir(parents=True)
    for path in (PKG / "baml_src").glob("*.baml"):
        (root / path.name).write_bytes(path.read_bytes())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for doc in (adoption_bundle.SOURCE_AUTHORITY_CONTRACT, adoption_bundle.C4_DOCUMENT, adoption_bundle.TASK_CATALOG):
        (tmp_path / doc).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / doc).write_text("# fixture\n\n## Anchors\n\n## Audiences\n- operator\n", encoding="utf-8")
    # A bundle committed before the upgrade: its digests are the v0 sources'.
    stale = adoption_bundle.generate_adoption_bundle(tmp_path)
    stale["schema_refs"] = [{**ref, "digest": "sha256:" + "0" * 64} for ref in stale["schema_refs"]]
    bundle_path = tmp_path / adoption_bundle.ADOPTION_BUNDLE_PATH
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_bytes(adoption_bundle.stable_json_bytes(stale))
    assert adoption_bundle.adoption_bundle_status(tmp_path)["status"] == "stale"
    assert adoption_bundle.refresh_adoption_bundle(tmp_path)["refreshed"] is True
    bundle = json.loads((tmp_path / adoption_bundle.ADOPTION_BUNDLE_PATH).read_text(encoding="utf-8"))
    assert len(bundle["schema_refs"]) == 8
    assert not any(ref["source_path"].endswith("phase_loop_bridge.baml") for ref in bundle["schema_refs"])
    assert adoption_bundle.adoption_bundle_status(tmp_path)["status"] == "fresh"
    (root / "phase_loop_bridge.baml").write_text("// host glue edited\n", encoding="utf-8")
    assert adoption_bundle.adoption_bundle_status(tmp_path)["status"] == "fresh"
    (root / "verification_evidence.baml").write_text("// schema edited\n", encoding="utf-8")
    assert adoption_bundle.adoption_bundle_status(tmp_path)["status"] == "stale"


def test_environment_inside_the_worker_is_the_allowlist(client):
    """#15: sentinels in the parent never reach the worker or a request."""
    with mock.patch.dict(os.environ, ENV_SENTINELS):
        os.environ["LC_CTYPE"] = "C.UTF-8"
        m._reset_worker_for_tests(test_mode=True)
        outcome, info = m._worker_call("env", {})
        evidence = [
            m.build_baml_request("EvaluateSuspectedFakeEvidence", entry["payload"])
            for entry in _baseline("evidence_requests.json")["requests"].values()
        ]
        closeout = m.build_baml_request("EmitPhaseCloseout", CLOSEOUT)
        allowlist = set(m._worker_env())
    assert outcome == "ok"
    # The allowlist, plus the one key the worker itself forces (profiling off).
    assert set(info["env"]) <= allowlist | {"BAML_PROFILE"}, set(info["env"]) - allowlist
    assert "BAML_PROFILE" in info["env"]
    assert "LC_CTYPE" not in info["env"] and "__PYVENV_LAUNCHER__" not in info["env"]
    assert Path(info["cwd"]).resolve() == PKG.resolve()
    golden = [entry["v0"] for entry in _baseline("evidence_requests.json")["requests"].values()]
    assert [_request_view(r) for r in evidence] == golden
    blob = json.dumps([_request_view(r) for r in [*evidence, closeout]])
    for value in ENV_SENTINELS.values():
        assert value not in blob
    err = m._CLIENT.gen.err_file
    err.seek(0)
    assert err.read() == b"", "worker wrote to stdout/stderr"


def test_worker_env_keys_are_a_subset_of_the_allowlist():
    with mock.patch.dict(os.environ, {**ENV_SENTINELS, "LD_LIBRARY_PATH": "/x", "TMPDIR": "/tmp"}):
        keys = set(m._worker_env())
    allowed = {"PATH", *m._WORKER_ENV_KEYS, *m._WORKER_LOADER_KEYS.get(sys.platform, ())}
    assert keys <= allowed
    assert not keys & set(ENV_SENTINELS)


def test_second_call_reuses_the_worker_quickly(client):
    """#16: ~0.8 s once per process, then milliseconds on the same pid."""
    _parse()
    pid = _pid()
    started = time.perf_counter()
    _parse()
    assert time.perf_counter() - started < 0.25
    assert _pid() == pid


def test_parent_never_imports_baml_bridge(client):
    _parse()
    m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
    assert "baml_bridge" not in sys.modules


def test_serialization_errors_are_plain_and_send_nothing(client):
    _parse()
    pid, log = _pid(), _log()
    for exc in (
        _raises(m.parse_baml_response, "EmitPhaseCloseout", '{"x": "\ud83d"}'),
        _raises(m._worker_call, "parse_closeout", {"raw": object()}),
        _raises(m.build_baml_request, "EvaluateSuspectedFakeEvidence", {**EVIDENCE, "sample_artifact_content": "\udfff"}),
    ):
        assert type(exc) is BamlValidationError
    assert (_pid(), _log()) == (pid, log)



@pytest.mark.parametrize("field", ["plan_produces", "plan_owned_files"])
def test_a_non_list_closeout_field_is_a_plain_content_error(client, field):
    """Opus round 3 N1: a bad payload shape is content, never an untyped TypeError."""
    exc = _raises(m.build_baml_request, "EmitPhaseCloseout", {**CLOSEOUT, field: 5})
    assert type(exc) is BamlValidationError


def _boom(exc):
    def raise_(*_args, **_kwargs):
        raise exc

    return raise_


# I7 (codex hb1 B3): every seam of the client's own machinery on the calling
# thread.  Whatever ordinary Exception escapes there must surface as
# BamlWorkerError(kind="fault"), never untyped and never as a plain content error.
_MACHINERY_SEAMS = {
    "raw-source-read": ("_read_raw_baml_files", None, OSError(5, "I/O error")),
    "source-render": ("_read_baml_files", None, UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")),
    "fingerprint": ("_fingerprint", None, RuntimeError("hash failure")),
    "serialize": ("_serialize_args", None, TypeError("encoder bug")),
    "drain-warnings": ("_drain_pending", "_Client", ValueError("logging bug")),
    "owner-launch": ("_ensure_owner", "_Client", OSError(12, "Cannot allocate memory")),
    "wait": ("_wait", "_Client", KeyError("queue bug")),
}


@pytest.mark.parametrize("seam", sorted(_MACHINERY_SEAMS))
def test_client_machinery_failures_are_typed_faults(client, seam):
    name, owner, exc = _MACHINERY_SEAMS[seam]
    target = getattr(m, owner) if owner else m
    for call in (_parse, lambda: m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)):
        m._reset_worker_for_tests(test_mode=True)
        with mock.patch.object(target, name, _boom(exc)):
            raised = _raises(call)
        assert type(raised) is BamlWorkerError and raised.kind == "fault", (seam, type(raised), raised)
        assert raised.__cause__ is exc
    # Content errors stay plain, and the next call is healthy.
    assert type(_raises(m.parse_baml_response, "EmitPhaseCloseout", "\ud83d")) is BamlValidationError
    assert _parse()["terminal_status"] == "complete"



# codex round 2 F002: the typed boundary extends past the reply, over all of the
# public functions' processing of it (prompt extraction, the D1a schema append,
# request and model construction).  Content errors stay plain, and an interrupt
# is never mapped.
_POST_REPLY_SEAMS = {
    "extract-prompt": ("_extract_prompt", None, "build", MemoryError("prompt allocation failed")),
    "schema-description": ("_render_schema_description", None, "closeout", RuntimeError("render bug")),
    "request-model": ("BamlRequest", None, "build", TypeError("model bug")),
    "closeout-validate": ("model_validate", "PhaseLoopCloseoutV1", "parse", MemoryError("validation allocation failed")),
    "closeout-dump": ("model_dump", "PhaseLoopCloseoutV1", "parse", RecursionError("dump bug")),
    # The class-name branch never calls the worker, but it is public response
    # processing too, and Tier 3 parses its judgment through it.
    "class-find-json": ("_find_json_payload", None, "class", MemoryError("scan allocation failed")),
    "class-validate": ("_validate_payload_against_schema", None, "class", RecursionError("schema walk bug")),
}

JUDGMENT = json.dumps({"verdict": "real", "confidence": 0.9, "reasoning": "r", "specific_concerns": []})


def _post_reply_call(which: str):
    if which == "build":
        return lambda: m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
    if which == "closeout":
        return lambda: m.build_baml_request("EmitPhaseCloseout", CLOSEOUT)
    if which == "class":
        return lambda: m.parse_baml_response("EvidenceJudgment", JUDGMENT)
    return _parse


@pytest.mark.parametrize("seam", sorted(_POST_REPLY_SEAMS))
def test_post_reply_processing_failures_are_typed_faults(client, seam):
    name, owner, which, exc = _POST_REPLY_SEAMS[seam]
    target = getattr(m, owner) if owner else m
    call = _post_reply_call(which)
    call()  # warm: the worker is up, so the injection lands after a real reply
    with mock.patch.object(target, name, _boom(exc)):
        raised = _raises(call)
    assert type(raised) is BamlWorkerError and raised.kind == "fault", (seam, type(raised), raised)
    assert raised.__cause__ is exc
    # A content error raised at the same seam stays plain ...
    content = BamlValidationError("content")
    with mock.patch.object(target, name, _boom(content)):
        assert _raises(call) is content
    # ... an interrupt is never mapped ...
    interrupt = KeyboardInterrupt()
    with mock.patch.object(target, name, _boom(interrupt)):
        assert _raises(call) is interrupt
    # ... and the next call is healthy.
    call()



# The v1 runtime keeps a profile store of call data under its working directory
# (``.baml/profiles-v1``) unless profiling is off.  The worker forces it off, so
# no call data is written to disk: in a checkout (cwd = src/phase_loop_runtime)
# or an installed package (cwd = site-packages/phase_loop_runtime).  The real
# installed wheel is also checked by the Gate A probe and the publish smoke.


def _package_copy(root: Path, layout: str) -> Path:
    base = root / ("src" if layout == "checkout" else f"lib/python{sys.version_info[0]}.{sys.version_info[1]}/site-packages")
    target = base / "phase_loop_runtime"
    shutil.copytree(PKG, target, ignore=shutil.ignore_patterns(".baml", "__pycache__"))
    return target


@pytest.mark.parametrize("layout", ["checkout", "installed"])
def test_the_worker_writes_no_profile_data_into_its_working_directory(tmp_path, layout):
    pkg = _package_copy(tmp_path, layout)
    client = m._Client(test_mode=True, retries=0)
    try:
        with mock.patch.object(m, "_worker_script", lambda: str(pkg / "_baml_worker.py")), \
                mock.patch.object(m, "_worker_cwd", lambda: str(pkg)), mock.patch.object(m, "_CLIENT", client):
            assert m.parse_baml_response("EmitPhaseCloseout", OK).payload["terminal_status"] == "complete"
            m.build_baml_request("EmitPhaseCloseout", CLOSEOUT)
            m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
            assert client.gen is not None and str(pkg / "_baml_worker.py") in client.gen.proc.args  # this copy ran
    finally:
        client.stop(graceful=True, timeout=5)
    assert not (pkg / ".baml").exists(), sorted(p.name for p in pkg.iterdir())


def test_profiling_passed_in_by_the_parent_is_still_forced_off(tmp_path):
    """Forced, not defaulted: even a worker started WITH profiling on (and a
    profile directory) writes nothing."""
    pkg = _package_copy(tmp_path, "checkout")
    env = {**m._worker_env(), "BAML_PROFILE": "1", "BAML_PROFILE_DIR": str(tmp_path / "profiles")}
    proc = subprocess.Popen(
        [sys.executable, "-I", "-S", str(pkg / "_baml_worker.py"), str(os.getpid()), ",".join(sorted(env))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=str(pkg),
    )
    try:
        def send(obj):
            proc.stdin.write((json.dumps(obj) + "\n").encode())
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        init = {"id": 1, "op": "init", "files": m._read_baml_files(), "sys_path": m._worker_sys_path(), "test_mode": True}
        assert "ok" in send(init)
        assert "ok" in send({"id": 2, "op": "parse_closeout", "args": {"raw": OK}})
        assert "request" in send({"id": 3, "op": "evidence_request", "args": {
            "tier2_signal_summary": "a", "sample_artifact_content": "b", "expected_artifact_characteristics": "c"}})
        names = send({"id": 4, "op": "env", "args": {}})["ok"]["env"]
        assert "BAML_PROFILE" in names and "BAML_PROFILE_DIR" not in names, names
    finally:
        proc.stdin.close()
        proc.wait(10)
    assert not (pkg / ".baml").exists() and not (tmp_path / "profiles").exists()


def test_worker_protocol_rejects_ops_before_init_and_a_second_init():
    files = m._read_baml_files()
    proc = subprocess.Popen(
        [sys.executable, "-I", "-S", str(PKG / "_baml_worker.py"), str(os.getpid()), ",".join(sorted(m._worker_env()))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=m._worker_env(),
        cwd=str(PKG),
    )
    try:
        def send(obj):
            proc.stdin.write((json.dumps(obj) + "\n").encode())
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        early = send({"id": 1, "op": "parse_closeout", "args": {"raw": OK}})
        assert set(early) == {"id", "fingerprint", "fault"} and early["id"] == 1
        init = {"id": 2, "op": "init", "files": files, "sys_path": m._worker_sys_path()}
        ready = send(init)
        assert set(ready) == {"id", "fingerprint", "ok"} and ready["id"] == 2
        assert ready["fingerprint"] == m._CLIENT.files()[1] or ready["fingerprint"] == __import__(
            "phase_loop_runtime._baml_worker", fromlist=["fingerprint"]
        ).fingerprint(files)
        again = send({**init, "id": 3})
        assert set(again) == {"id", "fingerprint", "fault"} and again["id"] == 3
        env_without_test_mode = send({"id": 4, "op": "env", "args": {}})
        assert "fault" in env_without_test_mode
        good = send({"id": 5, "op": "parse_closeout", "args": {"raw": OK}})
        assert set(good) == {"id", "fingerprint", "ok"}
        proc.stdin.close()
        assert proc.wait(10) == 0  # stdin EOF is the graceful exit
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# tripwires
# ---------------------------------------------------------------------------


def _strip_baml_code(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"`[^`]*`", "``", text, flags=re.S)
    text = re.sub(r'#"(.*?)"#', '""', text, flags=re.S)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def test_no_spawn_statement_in_packaged_sources():
    for path in (PKG / "baml_src").glob("*.baml"):
        assert not re.search(r"\bspawn\b", _strip_baml_code(path.read_text(encoding="utf-8"))), path.name
    assert re.search(r"\bspawn\b", _strip_baml_code(SPAWN_HOOK))  # the scan can see a real one


def test_rendered_sources_have_no_template_syntax():
    for name, text in m._read_baml_files().items():
        assert "{{" not in text and "{%" not in text, name
    broken = {"x.baml": "class X {\n    a: string,\n}\n// {{ unknown_thing }}\n"}
    with mock.patch.object(m, "_read_raw_baml_files", return_value=broken):
        assert type(_raises(m._read_baml_files)) is BamlValidationError


def _src_files() -> list[Path]:
    return sorted(PKG.rglob("*.py"))


def test_no_v0_console_scripts_or_package_remain():
    """#18: ``baml``/``baml-cli`` console scripts and baml_py are gone."""
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        assert "baml_py" not in text, path
        assert not re.search(r"""["']baml(-cli)?["']\s*,""", text), path


def _exception_text_assertions(path: Path) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name.endswith(("assertRaisesRegex", "assertRaisesRegexp")):
                lines.append(node.lineno)
            if name.endswith("raises") and any(kw.arg == "match" for kw in node.keywords):
                lines.append(node.lineno)
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Call) and _dotted(sub.func) == "str" and sub.args and isinstance(sub.args[0], ast.Name) and sub.args[0].id in ("exc", "e", "err", "error"):
                    lines.append(node.lineno)
    return lines


def test_the_v1_suites_assert_no_exception_text():
    """#19: exception text is not contractual; tests use type, .kind and .rc."""
    for path in TESTS.glob("test_phase_loop_baml_v1_*.py"):
        assert _exception_text_assertions(path) == [], path.name


def test_importing_the_worker_module_has_no_side_effects():
    code = textwrap.dedent(
        """
        import os, sys, threading
        before = (os.fstat(1).st_ino, os.fstat(2).st_ino, threading.active_count())
        sys.path.insert(0, %r)
        import phase_loop_runtime._baml_worker
        after = (os.fstat(1).st_ino, os.fstat(2).st_ino, threading.active_count())
        assert before == after, (before, after)
        assert "baml_bridge" not in sys.modules
        """
        % str(SRC)
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)


_FORK_ALLOWLIST = {
    # agent-harness#1140 (D7): the supervisor is an exec'd PROGRAM; its fork runs
    # in that single-threaded process, never between fork and exec of ours.
    ("lease_supervisor.py", "os.fork"),
}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def test_fork_invariant_tripwire():
    """D7 / #28 / #30: no Python runs between fork and exec anywhere in src/."""
    found = set()
    for path in _src_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                if any(n and n.split(".")[0] == "multiprocessing" for n in names):
                    found.add((path.name, "multiprocessing"))
                if any(n == "ProcessPoolExecutor" for n in names):
                    found.add((path.name, "ProcessPoolExecutor"))
            if isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name in ("os.fork", "os.forkpty", "pty.fork") or name.endswith("set_start_method") or name.endswith("ProcessPoolExecutor"):
                    found.add((path.name, name))
                for kw in node.keywords:
                    if kw.arg == "preexec_fn" and not (isinstance(kw.value, ast.Constant) and kw.value.value is None):
                        found.add((path.name, "preexec_fn"))
    assert found <= _FORK_ALLOWLIST, sorted(found - _FORK_ALLOWLIST)


def _module_tree() -> ast.Module:
    return ast.parse((PKG / "baml_modular.py").read_text(encoding="utf-8"))


def test_client_defines_no_finalizer_handler_or_lock():
    """I6 finalizer and handler lint: nothing in the client can reach a daemon-held lock.

    The client creates no lock at all, which makes the call-graph question moot;
    this lint pins that, plus the absence of every asynchronous entry point."""
    tree = _module_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            assert node.name != "__del__"
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            assert name not in (
                "weakref.finalize", "signal.signal", "threading.excepthook", "sys.excepthook",
                "threading.Lock", "threading.RLock", "threading.Condition", "threading.Semaphore",
                "threading.BoundedSemaphore", "threading.Event", "threading.Barrier", "_thread.allocate_lock",
            ), name
            assert not name.endswith("addHandler"), name
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assert _dotted(target) not in ("threading.excepthook", "sys.excepthook")


def _function_defs() -> dict[str, ast.FunctionDef]:
    defs = {}
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.FunctionDef):
            defs.setdefault(node.name, node)
    return defs


def _reachable(roots: list[str]) -> set[str]:
    defs = _function_defs()
    seen, todo = set(), list(roots)
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        for node in ast.walk(defs[name]):
            if isinstance(node, ast.Call):
                called = _dotted(node.func).split(".")[-1]
                if called in defs:
                    todo.append(called)
    return seen


def test_daemon_thread_bodies_never_log_import_or_lock():
    """Thread-body hygiene lint (not a deadlock claim; D7 removed that hazard)."""
    bodies = ["_own", "_spawner_loop", "_reader_loop", "_writer_loop"]
    defs = _function_defs()
    for body in bodies:
        tops = [n for n in defs[body].body if not isinstance(n, ast.Expr)]
        assert any(
            isinstance(n, ast.Try) and any(_dotted(h.type) == "BaseException" for h in n.handlers if h.type is not None)
            for n in ast.walk(defs[body])
        ), body
        assert tops
    for name in _reachable(bodies):
        for node in ast.walk(defs[name]):
            assert not isinstance(node, (ast.Import, ast.ImportFrom)) or name in ("_spawn_worker", "files"), (name, "import")
            if isinstance(node, ast.Call):
                called = _dotted(node.func)
                assert not called.startswith(("_LOG.", "logging.")), (name, called)
                assert "Lock" not in called and ".acquire" not in called, (name, called)


# ---------------------------------------------------------------------------
# worker faults (each in a fresh interpreter)
# ---------------------------------------------------------------------------


def scenario_idle_death_sigkill():
    spy = _scenario_setup(retries=0)
    first = _parse()
    pid = _pid()
    before = len(_log())
    os.kill(pid, signal.SIGKILL)
    assert _wait(lambda: _gone(pid), 3)
    assert _parse() == first
    assert _pid() != pid
    assert _wait(lambda: len(_log()) == before + 1, 3)
    entry = _log()[-1]
    assert (entry["kind"], entry["phase"], entry["pid"], entry["rc"]) == ("died", "idle", pid, -signal.SIGKILL)
    spy.assert_each_once()


def scenario_idle_death_sigterm():
    spy = _scenario_setup(retries=0)
    first = _parse()
    pid = _pid()
    before = len(_log())
    os.kill(pid, signal.SIGTERM)
    assert _wait(lambda: _gone(pid), 3)
    assert _parse() == first and _pid() != pid
    assert len(_log()) == before + 1 and _log()[-1]["pid"] == pid
    spy.assert_each_once()


def scenario_idle_death_spawn_hook():
    """The hostile bridge's detached failing spawn fires the runtime's
    os._exit(1) after the call: an idle death, recovered on the next call."""
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", SPAWN_HOOK), retries=0)
    try:
        assert _parse() == m.parse_baml_response("EmitPhaseCloseout", OK).payload
    except BamlWorkerError as exc:
        assert exc.kind == "died"
    pid = m._CLIENT.fault_log[-1]["pid"] if _log() else _pid()
    assert _wait(lambda: any(e["pid"] == pid and e["rc"] not in (0, None) for e in _log()), 5), _log()
    request = m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
    assert request.body["model"] == "phase-loop-evidence-audit"
    assert _pid() != pid
    # The runtime's unhandled-spawn hook exits 1 on POSIX; on Windows the
    # process exit code was 15 in the platform dispatch.  Either way: one entry.
    assert [e["rc"] for e in _log()] == ([1] if POSIX else [_log()[0]["rc"]]) and _log()[0]["rc"] not in (0, None), _log()
    spy.assert_each_once()


def scenario_spawn_hook_default_budget():
    started: list[int] = []

    def spawn(argv, **kwargs):
        proc = _REAL_SPAWN(argv, **kwargs)
        started.append(proc.pid)
        return proc

    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", SPAWN_HOOK))
    m._spawn_popen = spawn
    for _ in range(3):
        try:
            _parse()
        except BamlWorkerError as exc:
            assert exc.kind == "died"
        time.sleep(1.0)
    assert _wait(lambda: all(_gone(p) for p in started[:-1]), 5)
    dead = {p for p in started if _gone(p)}
    assert _wait(lambda: {e["pid"] for e in _log()} == dead, 5), (_log(), dead)
    assert len(_log()) == len(dead)
    spy.assert_each_once()


def scenario_inflight_kill_retries_zero():
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)), retries=0)
    killer = _Killer()
    try:
        exc = _raises(_parse)
    finally:
        killer.close()
    assert type(exc) is BamlWorkerError and exc.kind == "died" and exc.rc == -signal.SIGKILL
    assert len(_log()) == 1 and _log()[0]["pid"] == killer.killed[0]
    spy.assert_each_once()


def scenario_inflight_kill_within_budget():
    healthy = _parse_with(None)
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(1.5)))
    killer = _Killer()
    try:
        assert _parse() == healthy
    finally:
        killer.close()
    assert len(killer.killed) == 1
    assert [e["pid"] for e in _log()] == killer.killed
    spy.assert_each_once()


def _parse_with(files) -> dict:
    _use(files)
    try:
        return _parse()
    finally:
        m._reset_worker_for_tests(test_mode=True)


def scenario_retry_budget_exhaustion():
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)))
    killer = _Killer(every=True, delay=0.3)
    try:
        exc = _raises(_parse)
    finally:
        killer.close()
    assert type(exc) is BamlWorkerError and exc.kind == "died"
    assert len(killer.killed) == 3
    assert [e["pid"] for e in _log()] == killer.killed
    spy.assert_each_once()


_OPS = {
    "parse_closeout": ("phase_loop_parse_closeout", lambda: m.parse_baml_response("EmitPhaseCloseout", OK).payload),
    "closeout_request": ("phase_loop_closeout_request", lambda: _request_view(m.build_baml_request("EmitPhaseCloseout", CLOSEOUT))),
    "evidence_request": (
        "phase_loop_evidence_request",
        lambda: _request_view(m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)),
    ),
}


def _recovery_parity(op: str) -> None:
    """Kill attempt 1 mid-call: the retried answer equals a healthy call's, and
    the frames actually WRITTEN to the two workers' stdin differ only in ``id``
    (observed at the os.write boundary, not at the client's inputs)."""
    bridge_fn, call = _OPS[op]
    _use(None)
    healthy = call()
    spy = _scenario_setup(_hostile(bridge_fn, _sleep(1.5)))
    worker_fds: dict[int, int] = {}  # write fd -> worker pid
    written: dict[int, bytearray] = collections.defaultdict(bytearray)
    real_send, real_write = m._Client._send_op, os.write

    def send_spy(self, gen, req):
        worker_fds[gen.write_fd] = gen.pid
        real_send(self, gen, req)

    def write_spy(fd, data):
        count = real_write(fd, data)
        if fd in worker_fds:
            written[(fd, worker_fds[fd])].extend(bytes(data[:count]))
        return count

    m._Client._send_op = send_spy
    m.os.write = write_spy
    killer = _Killer()
    try:
        assert call() == healthy
    finally:
        killer.close()
        m._Client._send_op = real_send
        m.os.write = real_write
    frames = []
    for (_fd, pid), data in written.items():
        for line in bytes(data).split(b"\n"):
            if line and json.loads(line).get("op") == op:
                frames.append((pid, line))
    assert len(frames) == 2 and frames[0][0] != frames[1][0], [f[0] for f in frames]
    strip = [re.sub(rb'^\{"id":\d+,', b"{", line) for _pid, line in frames]
    assert strip[0] == strip[1], "retry frames differ in more than the id"
    assert frames[0][1] != frames[1][1]  # the ids do differ
    spy.assert_each_once()


def scenario_recovery_parity_parse_closeout():
    _recovery_parity("parse_closeout")


def scenario_recovery_parity_closeout_request():
    _recovery_parity("closeout_request")


def scenario_recovery_parity_evidence_request():
    _recovery_parity("evidence_request")


def scenario_timeout_disposes_the_worker():
    deadline = _deadline()
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(60)), retries=0, deadline_s=deadline)
    started = time.monotonic()
    exc = _raises(_parse)
    assert time.monotonic() - started < deadline + 1.0
    assert type(exc) is BamlWorkerError and exc.kind == "timeout"
    pid = _log()[-1]["pid"]
    assert _wait(lambda: _gone(pid), REAP_BOUND)
    spy.assert_each_once()


def scenario_blocked_write():
    """A peer that never reads stdin; the frame is larger than the pipe buffer."""
    deadline = _deadline()
    spy = _scenario_setup(retries=0, deadline_s=deadline)
    m._spawn_popen = _peer_spawn("stall_after_init")
    started = time.monotonic()
    exc = _raises(m.parse_baml_response, "EmitPhaseCloseout", "x" * (2 * 1024 * 1024))
    assert time.monotonic() - started < deadline + 1.0
    assert type(exc) is BamlWorkerError and exc.kind == "timeout"
    entry = _log()[-1]
    assert _wait(lambda: _gone(entry["pid"]), REAP_BOUND)
    # Both helpers exit, and each closed the fd it owned.
    assert _wait(lambda: not any(t.name.endswith(f"-{entry['pid']}") for t in threading.enumerate()), REAP_BOUND)
    m._spawn_popen = _REAL_SPAWN
    assert _parse()["terminal_status"] == "complete" and _pid() != entry["pid"]
    spy.assert_each_once()


def scenario_stalled_spawn():
    deadline = _deadline()
    spy = _scenario_setup(retries=0, deadline_s=deadline)
    returned: list[tuple[float, int]] = []

    def slow(argv, **kwargs):
        if not returned:
            time.sleep(deadline + 2.0)
        proc = _REAL_SPAWN(argv, **kwargs)
        returned.append((time.monotonic(), proc.pid))
        return proc

    m._spawn_popen = slow
    started = time.monotonic()
    exc = _raises(_parse)
    assert type(exc) is BamlWorkerError and exc.kind == "spawn"
    assert time.monotonic() - started < deadline + 1.0
    assert _wait(lambda: returned, deadline + 5)
    back_at, late_pid = returned[0]
    assert _wait(lambda: _gone(late_pid), REAP_BOUND)
    assert time.monotonic() - back_at <= REAP_BOUND + 0.3
    assert m._CLIENT.gen is None or m._CLIENT.gen.pid != late_pid, "the late process entered the slot"
    assert _wait(lambda: [e["kind"] for e in _log()] == ["spawn_late"], 2), _log()
    assert _parse()["terminal_status"] == "complete"
    assert _pid() not in (None, late_pid)
    spy.assert_each_once()


def scenario_dead_spawner_is_recreated():
    spy = _scenario_setup()
    _parse()
    spawner = _thread_named("phase-loop-baml-spawner")
    _async_raise(spawner, SystemExit)
    m._CLIENT.spawns.put(object())  # wake it so the async exception lands
    assert _wait(lambda: not spawner.is_alive(), 5)
    assert _parse()["terminal_status"] == "complete"
    assert _thread_named("phase-loop-baml-spawner") is not spawner
    spy.assert_each_once()


def scenario_missing_interpreter_is_a_spawn_error():
    spy = _scenario_setup(retries=0)
    with mock.patch.object(m, "_worker_interpreter", return_value="/nonexistent/phase-loop/python3"):
        exc = _raises(_parse)
    assert type(exc) is BamlWorkerError and exc.kind == "spawn"
    spy.assert_each_once()


_FRAMING = {
    "unterminated_eof": "framing",
    "non_json": "framing",
    "json_array": "framing",
    "wrong_id": "desync",
    "wrong_fingerprint": "fingerprint",
    "extra_key": "framing",
    "non_json_ok": "framing",
    "over_cap": "framing",
}


def scenario_framing_faults():
    for mode, kind in _FRAMING.items():
        spy = _scenario_setup(retries=0)
        pids: list[int] = []
        m._spawn_popen = _peer_spawn(mode, record=pids)
        exc = _raises(_parse)
        assert type(exc) is BamlWorkerError and exc.kind == kind, (mode, type(exc), getattr(exc, "kind", None))
        assert _wait(lambda: _gone(pids[0]), REAP_BOUND), mode
        assert [e["pid"] for e in _log()] == pids, mode
        spy.assert_each_once()
        spy.close()
        m._spawn_popen = _REAL_SPAWN


def scenario_broken_source_is_an_init_fault():
    spy = _scenario_setup(_files(bad="class Bad {\n    x: strin,\n}\n"), retries=0)
    for call in (_parse, lambda: m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)):
        exc = _raises(call)
        assert type(exc) is BamlWorkerError and exc.kind == "init_fault"
    assert [e["kind"] for e in _log()] == ["init_fault", "init_fault"]
    spy.assert_each_once()


def scenario_in_baml_panic_is_contained():
    """#13: a panic comes back as a fault; the worker is discarded and killed."""
    spy = _scenario_setup(_panic_files())
    exc = _raises(_parse)
    assert type(exc) is BamlWorkerError and exc.kind == "fault"
    pid = _log()[-1]["pid"]
    assert _wait(lambda: _gone(pid), REAP_BOUND)
    request = m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
    assert request.id is None and _pid() != pid
    spy.assert_each_once()


def _fit(make_args, limit: int) -> int:
    """The largest n whose serialized request body stays under ``limit`` bytes."""
    lo, hi = 0, limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(json.dumps(make_args(mid), ensure_ascii=True, sort_keys=True, allow_nan=False)) < limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


def scenario_frame_cap_derivation():
    """#27: an in-cap request can never produce an over-cap response.

    Each op, each character shape, the parse error branch (the input echoed
    back) and nested inputs (closeout list values made of the shape), each at a
    serialized request just under the 4 MiB cap."""
    spy = _scenario_setup()
    sizes: list[int] = []
    real_frame = m._Client._on_frame

    def frame_spy(self, gen, line):
        sizes.append(len(line))
        real_frame(self, gen, line)

    m._Client._on_frame = frame_spy
    shapes = {"backslash": "\\", "quote": '"', "astral": "\U0001f600", "control": "\x01", "bmp": "\u4e2d", "ascii": "a"}
    limit = m._REQUEST_CAP - 64

    def nested(char, n):
        return json.dumps({**OK_PAYLOAD, "terminal_status": "executed", "dirty_paths": [char * n], "produced_if_gates": []})

    cases = {
        "parse_error_branch": lambda char: (lambda n: {"raw": char * n}),
        "parse_nested": lambda char: (lambda n: {"raw": nested(char, n)}),
        "closeout_request": lambda char: (lambda n: m._bridge_args("EmitPhaseCloseout", (), {**CLOSEOUT, "plan_owned_files": [char * n]})),
        "evidence_request": lambda char: (lambda n: {**EVIDENCE, "sample_artifact_content": char * n}),
    }
    ops = {"parse_error_branch": "parse_closeout", "parse_nested": "parse_closeout",
           "closeout_request": "closeout_request", "evidence_request": "evidence_request"}
    try:
        for case, factory in cases.items():
            for shape, char in shapes.items():
                make = factory(char)
                args = make(_fit(make, limit))
                assert len(m._serialize_args(args)) >= limit - 64, (case, shape)
                before = len(sizes)
                m._worker_call(ops[case], args)
                assert len(sizes) > before
                assert sizes[-1] < m._RESPONSE_CAP, (case, shape, sizes[-1])
        pid, log = _pid(), _log()
        exc = _raises(m.parse_baml_response, "EmitPhaseCloseout", "a" * (m._REQUEST_CAP + 1))
        assert type(exc) is BamlValidationError
        assert (_pid(), _log()) == (pid, log)
    finally:
        m._Client._on_frame = real_frame
    print("max response frame", max(sizes), "of cap", m._RESPONSE_CAP)
    spy.assert_each_once()


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("idle_death_sigkill", marks=needs_posix),
        pytest.param("idle_death_sigterm", marks=needs_posix),
        "idle_death_spawn_hook",
        "spawn_hook_default_budget",
        pytest.param("inflight_kill_retries_zero", marks=needs_posix),
        pytest.param("inflight_kill_within_budget", marks=needs_posix),
        pytest.param("retry_budget_exhaustion", marks=needs_posix),
        pytest.param("recovery_parity_parse_closeout", marks=needs_posix),
        pytest.param("recovery_parity_closeout_request", marks=needs_posix),
        pytest.param("recovery_parity_evidence_request", marks=needs_posix),
        "timeout_disposes_the_worker",
        "blocked_write",
        "stalled_spawn",
        pytest.param("dead_spawner_is_recreated", marks=needs_linux),
        "missing_interpreter_is_a_spawn_error",
        "framing_faults",
        "broken_source_is_an_init_fault",
        "in_baml_panic_is_contained",
        "frame_cap_derivation",
    ],
)
def test_worker_fault_scenario(name):
    _isolated(name)


# ---------------------------------------------------------------------------
# owner death, signals and concurrency (platform table; I3, I5)
# ---------------------------------------------------------------------------


def _scenario_proc(name: str, *args: str, new_session: bool = False) -> subprocess.Popen:
    code = (
        "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; t.scenario_%s(*sys.argv[1:])"
        % (str(TESTS), str(SRC), MODULE, name)
    )
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=new_session,
        cwd=str(TESTS.parent),
    )


def _read_tagged(proc: subprocess.Popen, tag: str, timeout: float = 120.0) -> list[str]:
    result: dict = {}

    def read():
        for line in proc.stdout:
            if line.startswith(tag + " "):
                result["fields"] = line.split()[1:]
                return

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    assert "fields" in result, f"scenario never printed {tag}; stderr={proc.stderr.read() if proc.poll() is not None else '(running)'}"
    return result["fields"]


def _announce_busy() -> None:
    def watch():
        pid = _busy_pid()
        print("BUSY", pid, flush=True)

    threading.Thread(target=watch, daemon=True).start()


def scenario_owner_hung(no_pdeathsig: str = "0") -> None:
    _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)), no_pdeathsig=no_pdeathsig == "1")
    _announce_busy()
    _parse()


@needs_posix
@pytest.mark.parametrize(
    "mechanism",
    [pytest.param("pdeathsig", marks=needs_linux), "watchdog"],
)
def test_owner_death_kills_a_worker_hung_in_a_native_op(mechanism):
    """Owner death per platform: the worker is inside a 30 s BAML sleep."""
    owner = _scenario_proc("owner_hung", "1" if mechanism == "watchdog" else "0")
    try:
        (worker,) = _read_tagged(owner, "BUSY")
        worker = int(worker)
        owner.kill()
        owner.wait(10)
        assert _wait(lambda: _gone(worker), 3.0), f"worker {worker} outlived its owner ({mechanism})"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


def scenario_pool_thread_exit() -> None:
    spy = _scenario_setup()
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("pid", (_parse(), _pid())[1]))
    thread.start()
    thread.join(30)
    pid = box["pid"]
    time.sleep(1.0)
    assert not _gone(pid), "the worker died with the short-lived calling thread"
    assert _parse()["terminal_status"] == "complete" and _pid() == pid
    spy.assert_each_once()


def scenario_killpg_leaves_worker() -> None:
    got = []
    signal.signal(signal.SIGINT, lambda *_: got.append(1))  # the runner survives a terminal Ctrl-C here
    spy = _scenario_setup()
    _parse()
    pid = _pid()
    print("READY", pid, flush=True)
    assert sys.stdin.readline().strip() == "go"
    assert got, "the SIGINT never reached the runner"
    assert not _gone(pid)
    _parse()
    assert _pid() == pid
    spy.assert_each_once()
    print("DONE", flush=True)


@needs_posix
def test_killpg_sigint_to_the_runner_group_leaves_the_worker():
    owner = _scenario_proc("killpg_leaves_worker", new_session=True)
    try:
        _read_tagged(owner, "READY")
        os.killpg(owner.pid, signal.SIGINT)
        time.sleep(0.5)
        try:
            owner.stdin.write("go\n")
            owner.stdin.flush()
        except BrokenPipeError:
            pass  # the runner already exited; report its status and stderr below
        out, err = owner.communicate(timeout=30)
        assert owner.returncode == 0, (owner.returncode, err[-3000:])
        assert "DONE" in out
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.communicate(timeout=10)


def scenario_sigint_mid_wait() -> None:
    _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)))
    _announce_busy()
    try:
        _parse()
    except KeyboardInterrupt as exc:
        assert type(exc) is KeyboardInterrupt
        pid = _log()[-1]["pid"] if _wait(lambda: _log(), REAP_BOUND) else None
        assert pid is not None and _wait(lambda: _gone(pid), REAP_BOUND)
        print("INTERRUPTED", flush=True)
        return
    raise AssertionError("the call returned")


@needs_posix
def test_sigint_mid_wait_is_an_unmapped_keyboard_interrupt():
    owner = _scenario_proc("sigint_mid_wait")
    try:
        _read_tagged(owner, "BUSY")
        os.kill(owner.pid, signal.SIGINT)
        out, err = owner.communicate(timeout=30)
        assert owner.returncode == 0, err
        assert "INTERRUPTED" in out
        assert "BamlValidationError" not in err and "BamlWorkerError" not in err
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.communicate(timeout=10)


def scenario_cold_start_concurrency() -> None:
    spy = _scenario_setup()
    spawned: list[int] = []

    def spawn(argv, **kwargs):
        proc = _REAL_SPAWN(argv, **kwargs)
        spawned.append(proc.pid)
        return proc

    m._spawn_popen = spawn
    barrier = threading.Barrier(8)
    results: list = []

    def call():
        barrier.wait()
        results.append((_parse(), _pid()))

    threads = [threading.Thread(target=call) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert len(results) == 8
    assert all(result == results[0][0] for result, _ in results)
    assert len(spawned) == 1 and {pid for _, pid in results} == set(spawned)
    assert m._CLIENT.owner_starts == 1
    spy.assert_each_once()


# ---------------------------------------------------------------------------
# fork (#30, I5) and the executor launch path after agent-harness#1140 (D7)
# ---------------------------------------------------------------------------


def _install_child_spies(record_path: str) -> None:
    """Record every os.read/os.write/os.kill/os.killpg in this (forked) process."""
    real_open, real_write = os.open, os.write
    fd = real_open(record_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    for name in ("read", "write", "kill", "killpg"):
        real = getattr(os, name)

        def spy(*args, _real=real, _name=name):
            if not (_name == "write" and args and args[0] == fd):
                real_write(fd, f"{_name}\n".encode())
            return _real(*args)

        setattr(os, name, spy)


def scenario_fork_after_use(record_path: str) -> None:
    spy = _scenario_setup()
    _parse()
    pid = _pid()
    child = os.fork()
    if child == 0:
        try:
            _install_child_spies(record_path)
            started = time.monotonic()
            exc = _raises(_parse)
            ok = type(exc) is BamlWorkerError and exc.kind == "forked" and time.monotonic() - started < 1.0
            ok = ok and type(_raises(m.build_baml_request, "EvaluateSuspectedFakeEvidence", EVIDENCE)) is BamlWorkerError
            # The regex-only surface keeps working in a fork child, as in v0.
            ok = ok and "terminal_status" in m.export_function_schema("EmitPhaseCloseout")["properties"]
        except BaseException:  # noqa: BLE001
            os._exit(4)
        sys.exit(0 if ok else 3)  # a NORMAL exit: atexit, finalizers, thread teardown
    assert _parse() and _pid() == pid  # served during the child's life
    started = time.monotonic()
    _, status = os.waitpid(child, 0)
    exited_in = time.monotonic() - started
    assert os.waitstatus_to_exitcode(status) == 0
    assert exited_in < 1.0, exited_in
    assert Path(record_path).read_text() == "", "the fork child touched an fd or signalled"
    assert _parse() and _pid() == pid and not _gone(pid)
    spy.assert_each_once()


def scenario_fork_while_mid_call() -> None:
    _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(2)))
    box = {}
    worker = threading.Thread(target=lambda: box.setdefault("result", _parse()))
    worker.start()
    pid = _busy_pid()
    child = os.fork()
    if child == 0:
        started = time.monotonic()
        exc = _raises(_parse)
        os._exit(0 if type(exc) is BamlWorkerError and exc.kind == "forked" and time.monotonic() - started < 1.0 else 3)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    worker.join(30)
    assert box["result"]["terminal_status"] == "complete" and _pid() == pid


def scenario_exit_with_fork_child(mode: str = "normal", no_pdeathsig: str = "0") -> None:
    _scenario_setup(no_pdeathsig=no_pdeathsig == "1")
    _parse()
    child = os.fork()
    if child == 0:
        time.sleep(30)  # holds every inherited fd, including the worker's stdin
        os._exit(0)
    print("WORKER", _pid(), child, flush=True)
    if mode == "wait":
        time.sleep(3600)
    sys.exit(0)


@needs_posix
@pytest.mark.parametrize(
    "mode,no_pdeathsig,bound",
    [
        ("normal", "0", 5.0 + 1.0),
        pytest.param("kill", "0", 3.0, marks=needs_linux),
        ("kill", "1", 3.0),
    ],
    ids=["graceful-exit", "sigkill-pdeathsig", "sigkill-watchdog"],
)
def test_worker_is_gone_after_owner_exit_with_a_non_exec_fork_child(mode, no_pdeathsig, bound):
    owner = _scenario_proc("exit_with_fork_child", "wait" if mode == "kill" else "normal", no_pdeathsig)
    child = None
    try:
        worker, child = (int(x) for x in _read_tagged(owner, "WORKER"))
        started = time.monotonic()
        if mode == "kill":
            owner.kill()
        owner.wait(15)
        assert _wait(lambda: _gone(worker), bound), f"worker outlived its owner by more than {bound}s"
        assert time.monotonic() - started <= bound + 0.5
    finally:
        # The fork child holds the owner's stdio pipes: kill it before draining them.
        if child:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


@needs_posix
def test_fork_after_use_is_typed_and_touches_nothing(tmp_path):
    code = (
        "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; t.scenario_fork_after_use(%r)"
        % (str(TESTS), str(SRC), MODULE, str(tmp_path / "child-calls"))
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(TESTS.parent))
    assert proc.returncode == 0, proc.stderr


@needs_posix
def test_fork_while_another_thread_is_mid_call():
    _isolated("fork_while_mid_call")


def scenario_atexit_with_backlog() -> None:
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(3)))
    outcomes: dict = {}

    def call(name):
        outcomes[name] = _raises(_parse)

    first = threading.Thread(target=call, args=("active",))
    first.start()
    pid = _busy_pid()
    second = threading.Thread(target=call, args=("queued",))
    second.start()
    assert _wait(lambda: len(m._CLIENT.backlog) == 1, 5)
    starts: list = []
    real_start = threading.Thread.start
    threading.Thread.start = lambda self: (starts.append(self.name), real_start(self))[1]
    try:
        started = time.monotonic()
        m._atexit_shutdown()
        assert time.monotonic() - started < 5.0
    finally:
        threading.Thread.start = real_start
    assert starts == [], starts
    first.join(10)
    second.join(10)
    for name in ("active", "queued"):
        exc = outcomes[name]
        assert type(exc) is BamlWorkerError and exc.kind == "shutdown", (name, exc)
    assert _wait(lambda: _gone(pid), 1.0)
    later = _raises(_parse)
    assert type(later) is BamlWorkerError and later.kind == "shutdown"
    spy.assert_each_once()


def test_atexit_serves_the_backlog_shutdown_and_starts_no_thread():
    _isolated("atexit_with_backlog")


def scenario_launch_path_with_live_worker_and_stalled_spawn(tmp: str) -> None:
    import fcntl

    from phase_loop_runtime.launcher import launch

    tmp_path = Path(tmp)

    class _Lease:
        generation = "baml-v1-launch-path"

        def __init__(self, fd):
            self._fd = fd

        def fileno(self):
            return self._fd

    lease = os.open(tmp_path / "lease.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    script = 'for f in /proc/$$/fd/* /proc/$PPID/fd/*; do readlink "$f"; done > "$1"'

    def run_executor(name):
        out = tmp_path / name
        started = time.monotonic()
        result = launch(
            ["/bin/sh", "-c", script, "sh", str(out)],
            lease_authority=_Lease(lease),
            log_path=tmp_path / f"{name}.log",
            heartbeat_interval_seconds=30,
        )
        assert result.returncode == 0
        assert time.monotonic() - started < 15
        return set(out.read_text().split())

    # (a) a live, serving worker
    spy = _scenario_setup()
    _parse()
    gen = m._CLIENT.gen
    pid = gen.pid
    inodes = {os.readlink(f"/proc/self/fd/{fd}") for fd in (gen.read_fd, gen.write_fd)}
    assert all(i.startswith("pipe:") for i in inodes)
    seen = run_executor("live")
    assert not inodes & seen, "a BAML pipe leaked into the supervisor or the executor"
    assert _parse() and _pid() == pid
    spy.assert_each_once()
    spy.close()

    # (b) a stalled BAML spawn
    deadline = _deadline()
    spy = _scenario_setup(retries=0, deadline_s=deadline)
    returned: list = []

    def slow(argv, **kwargs):
        if not returned:
            time.sleep(deadline + 2.0)
        proc = _REAL_SPAWN(argv, **kwargs)
        returned.append(proc.pid)
        return proc

    m._spawn_popen = slow
    box = {}
    stalled = threading.Thread(target=lambda: box.setdefault("exc", _raises(_parse)))
    stalled.start()
    time.sleep(0.2)
    run_executor("stalled")
    stalled.join(deadline + 10)
    assert type(box["exc"]) is BamlWorkerError and box["exc"].kind == "spawn"
    assert _wait(lambda: returned and _gone(returned[0]), deadline + 5)
    assert _parse() and _pid() not in (None, returned[0])
    spy.assert_each_once()


@needs_linux
def test_executor_launch_path_after_1140_with_a_live_worker_and_a_stalled_spawn(tmp_path):
    code = (
        "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; "
        "t.scenario_launch_path_with_live_worker_and_stalled_spawn(%r)" % (str(TESTS), str(SRC), MODULE, str(tmp_path))
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=str(TESTS.parent))
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", ["pool_thread_exit", "cold_start_concurrency"])
def test_lifecycle_scenario(name):
    if name == "pool_thread_exit" and not LINUX:
        pytest.skip("PDEATHSIG follows the spawning thread only on Linux")
    _isolated(name)


# ---------------------------------------------------------------------------
# I1: interrupts
# ---------------------------------------------------------------------------


class InjectedAbort(BaseException):
    """A custom BaseException the client has never heard of."""


_EXCEPTIONS = {
    "KeyboardInterrupt": lambda n: KeyboardInterrupt(f"injected-{n}"),
    "SystemExit": lambda n: SystemExit(73),
    "InjectedAbort": lambda n: InjectedAbort(f"injected-{n}"),
}


class _Boundaries:
    """Every instruction boundary the calling thread executes during a call.

    sys.monitoring INSTRUCTION events on 3.12+, sys.settrace opcode events on
    3.10/3.11.  Frames of this test module (the harness) are excluded; every
    other frame on the calling thread counts: client helpers and the stdlib
    callees they reach."""

    TOOL = 4

    def __init__(self) -> None:
        self.main = threading.get_ident()
        self.trace: list = []
        self.target = None
        self.exc: BaseException | None = None
        self.fired = False
        self.second = None  # (predicate(code, offset), exception)
        self.second_fired = False
        self.active = False
        self._installed = False

    def hit(self, code, offset) -> None:
        if not self.active or threading.get_ident() != self.main or code.co_filename == __file__:
            return
        key = (code, offset)
        if self.target is None:
            self.trace.append(key)
            return
        if not self.fired:
            if key == self.target:
                self.fired = True
                raise self.exc
            return
        if self.second is not None and not self.second_fired and self.second[0](code, offset):
            self.second_fired = True
            raise self.second[1]

    def __enter__(self):
        self.active = True
        if PY312:
            mon = sys.monitoring
            if not self._installed:
                mon.use_tool_id(self.TOOL, "baml-i1-sweep")
                mon.register_callback(self.TOOL, mon.events.INSTRUCTION, self.hit)
                self._installed = True
            mon.set_events(self.TOOL, mon.events.INSTRUCTION)
        else:
            def local(frame, event, arg):
                if event == "opcode":
                    self.hit(frame.f_code, frame.f_lasti)
                return local

            def tracer(frame, event, arg):
                frame.f_trace_opcodes = True
                return local

            sys.settrace(tracer)
        return self

    def __exit__(self, *exc):
        self.active = False
        if PY312:
            sys.monitoring.set_events(self.TOOL, 0)
        else:
            sys.settrace(None)
        return False

    def close(self) -> None:
        if PY312 and self._installed:
            sys.monitoring.register_callback(self.TOOL, sys.monitoring.events.INSTRUCTION, None)
            sys.monitoring.free_tool_id(self.TOOL)
            self._installed = False


class _AbandonSpy:
    """Records what each abandoned request still owned, and every notice sent."""

    def __init__(self) -> None:
        self.records: list[tuple] = []
        self.notices: list = []
        self._abandon = m._Client._abandon
        self._send = m._send_abandon
        spy = self

        def abandon(client, req):
            gen = req.gen if req.gen is not None and req.gen.state in ("init", "busy", "dying") else None
            spy.records.append((req, gen.pid if gen is not None else None, req.spawn, req.done))
            spy._abandon(client, req)

        def send(client, req):
            spy.notices.append(req)
            spy._send(client, req)

        m._Client._abandon = abandon
        m._send_abandon = send

    def close(self) -> None:
        m._Client._abandon = self._abandon
        m._send_abandon = self._send


def _settled(timeout: float) -> bool:
    """The owner has processed every queued event (notices included) and holds
    no request: the condition must hold on two polls one owner tick apart."""
    client = m._CLIENT

    def idle() -> bool:
        # With no owner running, nothing is processing and nothing is owned.
        drained = client.events.empty() or not client.owner_running
        return drained and client.active is None and not client.backlog and not client.dying

    def stable() -> bool:
        if not idle():
            return False
        time.sleep(2 * m._OWNER_TICK_S)
        return idle()

    return _wait(stable, timeout)


def _check_cleanup(spy: _AbandonSpy, log_before: int, pid_before: int | None, injected_at: float, bound: float) -> None:
    assert _settled(bound + 1.0)
    owned = [pid for (_req, pid, _spawn, done) in spy.records if pid is not None and not done]
    new = _log()[log_before:]
    disposed = [e["pid"] for e in new if e["kind"] == "abandoned"]
    assert sorted(disposed) == sorted(owned), (new, spy.records)
    for pid in owned:
        assert _wait(lambda: _gone(pid), max(0.0, injected_at + bound - time.monotonic()) + 0.05), pid
    if not owned and pid_before is not None and not any(e["pid"] == pid_before for e in new):
        assert not _gone(pid_before), ("a generation not owned by the request was disturbed", pid_before, new, spy.records)


def _prepare(variant: str) -> None:
    if variant in ("normal", "mid_op"):
        if _pid() is None:
            _parse()
        return
    _use(None, **_VARIANT_CONFIG.get(variant, {}))
    # Cold LIFECYCLE: no owner thread, no spawner, no worker.  The per-process
    # source snapshot is taken first: rendering the sources is pure computation
    # with no lifecycle state (and ~20k boundaries), so it is not swept here.
    m._CLIENT.files()
    m._spawn_popen = _peer_spawn("echo")
    if variant == "stalled_spawn":
        fast = m._spawn_popen

        def stalled(argv, **kwargs):
            time.sleep(0.15)  # the spawn is still pending when the wait loop starts
            return fast(argv, **kwargs)

        m._spawn_popen = stalled


_VARIANT_CONFIG = {"cold": {}, "stalled_spawn": {}}


def _sweep(variant: str, exc_name: str, stride: int = 1, select=None) -> dict:
    if variant == "mid_op":
        _use(_hostile("phase_loop_parse_closeout", _sleep(0.15)))
    elif variant == "normal":
        _use(None)
    make_exc = _EXCEPTIONS[exc_name]
    boundaries = _Boundaries()
    stats = collections.Counter()
    try:
        # Count on a second, steady-state pass: the first call in a process also
        # runs one-time code (lazy stdlib initialisation) that later runs never reach.
        _prepare(variant)
        _parse()
        _prepare(variant)
        with boundaries:
            _parse()
        points = list(dict.fromkeys(boundaries.trace))
        stats["boundaries"] = len(points)
        chosen = points[::stride] if select is None else select(points)
        if select is not None:
            stats["selected"] = len(chosen)
        for index, key in enumerate(chosen):
            run_started = time.monotonic()
            _prepare(variant)
            pid_before, log_before = _pid(), len(_log())
            spy = _AbandonSpy()
            injected = make_exc(index)
            boundaries.target, boundaries.exc, boundaries.fired = key, injected, False
            raised = None
            try:
                with boundaries:
                    _parse()
            except BaseException as exc:  # noqa: BLE001
                raised = exc
            injected_at = time.monotonic()
            try:
                if not boundaries.fired:
                    assert raised is None, raised
                    assert select is None, f"selected boundary not reached: {key}"
                    stats["not_reached"] += 1
                    continue
                where = (key[0].co_name, key[0].co_filename.rsplit("/", 1)[-1], next((ln for (s, e, ln) in key[0].co_lines() if s <= key[1] < e), None))
                assert raised is injected, (where, raised)
                if PY312:
                    lost = not any(r in spy.notices for (r, *_rest) in spy.records) and bool(spy.records)
                    stats["d2" if lost else "d1"] += 1
                bound = REAP_BOUND if not spy.records or spy.notices else m._CLIENT.abandon_grace_s + REAP_BOUND
                try:
                    _check_cleanup(spy, log_before, pid_before, injected_at, bound)
                except AssertionError as failure:
                    raise AssertionError((where, failure.args)) from None
                stats["disposals"] += sum(1 for e in _log()[log_before:] if e["kind"] == "abandoned")
            finally:
                spy.close()
            assert _parse()["terminal_status"] == "complete"  # the next call succeeds
            stats["runs"] += 1
            if os.environ.get("BAML_SWEEP_SLOW") and time.monotonic() - run_started > 0.5:
                print("SLOW", round(time.monotonic() - run_started, 2), key[0].co_name, key[0].co_filename.rsplit("/", 1)[-1], flush=True)
    finally:
        boundaries.close()
        m._spawn_popen = _REAL_SPAWN
    assert stats["runs"] > 0
    print("SWEEP", variant, exc_name, dict(stats), flush=True)
    return stats


def scenario_i1_sweep(variant: str, exc_name: str) -> None:
    _use(None)
    _sweep(variant, exc_name)


FULL_SWEEP_ENV = "PHASE_LOOP_BAML_FULL_SWEEP"


@pytest.mark.skipif(
    os.environ.get(FULL_SWEEP_ENV) != "1",
    reason=f"the full I1 sweep (~40 min per Python) runs in .github/workflows/baml-i1-sweep.yml "
    f"(weekly, dispatch, release cut) with {FULL_SWEEP_ENV}=1; PR CI runs test_i1_boundary_subset",
)
@pytest.mark.parametrize("exc_name", sorted(_EXCEPTIONS))
@pytest.mark.parametrize("variant", ["normal", "mid_op", "cold", "stalled_spawn"])
def test_i1_boundary_sweep(variant, exc_name):
    """I1(a): inject at every instruction boundary of the calling-thread path."""
    code = "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; t.scenario_i1_sweep(%r, %r)" % (
        str(TESTS), str(SRC), MODULE, variant, exc_name,
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=1500, cwd=str(TESTS.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert "SWEEP" in proc.stdout


def _line_of(fn, needle: str) -> int:
    import inspect

    source, first = inspect.getsourcelines(fn)
    matches = [first + i for i, line in enumerate(source) if needle in line]
    assert len(matches) == 1, (fn.__qualname__, needle, matches)
    return matches[0]


def _at_line(fn, needle: str):
    """Select the first boundary executed on the line of ``fn`` containing ``needle``."""
    code, line = fn.__code__, _line_of(fn, needle)

    def pick(points):
        for point in points:
            if point[0] is code and next((ln for (s, e, ln) in code.co_lines() if s <= point[1] < e), None) == line:
                return [point]
        raise AssertionError(f"no boundary on {fn.__qualname__}:{line} ({needle!r})")

    return pick


def _through(fn, needle: str):
    """Select every boundary from the first one on ``fn``'s ``needle`` line up to
    the last boundary ``fn`` itself executes: the operation's INTERIOR, including
    every callee boundary it reaches (codex hb1 B4)."""
    code, line = fn.__code__, _line_of(fn, needle)

    def pick(points):
        def line_of(point):
            return next((ln for (s, e, ln) in point[0].co_lines() if s <= point[1] < e), None)

        start = next((i for i, p in enumerate(points) if p[0] is code and line_of(p) == line), None)
        assert start is not None, f"no boundary on {fn.__qualname__}:{line} ({needle!r})"
        end = max(i for i, p in enumerate(points) if p[0] is code)
        return points[start:end + 1]

    return pick


# The fixed PR-CI subset of the I1 sweep.  Each entry is (variant, label, selector).
# First, middle and last boundary of a warm call; the request hand-off; the
# owner launch and its compare-and-set ticket (where an interrupt once wedged
# threading's _active_limbo_lock via Thread.start, and where an interrupted launch
# once stalled the next call); the first wait-loop boundary mid-op (disposal of an
# owned generation) and during a stalled spawn (spawn retirement).  The other two
# client bugs are regression-tested outside the sweep: the idle death charged to
# the next call (test_worker_fault_scenario[idle_death_*]) and the per-restart
# _DummyThread leak (test_client_invariant_scenario[i9_resources]).
_SUBSET = [
    ("normal", "first", lambda points: points[:1]),
    ("normal", "middle", lambda points: [points[len(points) // 2]]),
    ("normal", "last", lambda points: points[-1:]),
    ("normal", "request-hand-off", lambda points: _at_line(m._Client.call, 'self.events.put(("request", req))')(points)),
    # Every boundary from the launch ticket through the owner start and its
    # error handling, including whatever the start reaches on the calling
    # thread.  A threading.Thread.start here would put threading's internals
    # into this range, and injecting there wedges the process or maps the
    # interrupt (the historical bug).
    ("cold", "owner-launch-interior", lambda points: _through(m._Client._launch_owner, "owner_launches.setdefault(")(points)),
    ("mid_op", "wait-mid-op", lambda points: _at_line(m._Client._wait, "req.heartbeat = now")(points)),
    ("stalled_spawn", "wait-during-spawn", lambda points: _at_line(m._Client._wait, "req.heartbeat = now")(points)),
]


def scenario_i1_subset(exc_name: str) -> None:
    import faulthandler

    # A wedged process (e.g. a stuck threading lock) fails fast, not at the CI timeout.
    faulthandler.dump_traceback_later(240, exit=True)
    for variant, label, select in _SUBSET:
        _use(None)
        stats = _sweep(variant, exc_name, select=select)
        assert stats["runs"] == stats["selected"] >= 1, (variant, label, dict(stats))
        print("SUBSET", variant, label, stats["runs"], flush=True)
    faulthandler.cancel_dump_traceback_later()


@pytest.mark.parametrize("exc_name", sorted(_EXCEPTIONS))
def test_i1_boundary_subset(exc_name):
    """I1(a) in PR CI: the fixed regression boundaries, each with the full I1 checks."""
    code = "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; t.scenario_i1_subset(%r)" % (
        str(TESTS), str(SRC), MODULE, exc_name,
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600, cwd=str(TESTS.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert proc.stdout.count("SUBSET") == len(_SUBSET)


def _except_body_lines() -> set[int]:
    source, first = __import__("inspect").getsourcelines(m._Client.call)
    tree = ast.parse(textwrap.dedent("".join(source)))
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                for stmt in handler.body:
                    for sub in ast.walk(stmt):
                        if hasattr(sub, "lineno"):
                            lines.add(sub.lineno + first - 1)
    return lines


def scenario_i1_double_injection(mode: str) -> None:
    """I1(b): a second exception lands inside the client's own exception path."""
    _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)), abandon_grace_s=1.0)
    first, second = KeyboardInterrupt("first"), InjectedAbort("second")
    spy = _AbandonSpy()
    where = {}
    if mode == "monitoring":
        lines = _except_body_lines()
        call_code = m._Client.call.__code__

        def in_except(code, offset):
            if code is not call_code:
                return False
            line = next((ln for (s, e, ln) in code.co_lines() if s <= offset < e), None)
            if line in lines:
                where["line"] = line
                return True
            return False

        boundaries = _Boundaries()
        boundaries.target = ("__first_wait__",)
        wait_code = m._Client._wait.__code__

        def hit(code, offset, _orig=boundaries.hit):
            if not boundaries.fired and code is wait_code and m._CLIENT.gen is not None and m._CLIENT.gen.state == "busy":
                boundaries.target = (code, offset)
            return _orig(code, offset)

        boundaries.hit = hit
        boundaries.exc, boundaries.second = first, (in_except, second)
    else:
        real_send = m._send_abandon

        def seam(client, req):
            where["seam"] = True
            raise second  # the notice is lost

        m._send_abandon = seam
    raised = None
    try:
        if mode == "monitoring":
            with boundaries:
                _parse()
        else:
            killer = threading.Thread(target=lambda: (_busy_pid(), signal.pthread_kill(threading.main_thread().ident, signal.SIGINT)))
            killer.start()
            _parse()
    except BaseException as exc:  # noqa: BLE001
        raised = exc
    injected_at = time.monotonic()
    if mode == "monitoring":
        boundaries.close()
        assert boundaries.fired and boundaries.second_fired, where
        assert raised is second and raised.__context__ is first
    else:
        m._send_abandon = real_send
        assert where.get("seam") and raised is second and type(raised.__context__) is KeyboardInterrupt
    assert "line" in where or "seam" in where
    # The notice was lost: the backstop, not the notice, disposes of the worker.
    assert spy.notices == []
    bound = m._CLIENT.abandon_grace_s + REAP_BOUND
    assert _wait(lambda: any(e["kind"] == "abandoned" for e in _log()), bound + 0.5), _log()
    pid = [e for e in _log() if e["kind"] == "abandoned"][0]["pid"]
    assert _wait(lambda: _gone(pid), max(0.0, injected_at + bound - time.monotonic()) + 0.2)
    spy.close()
    # The next call, on the SAME client (no reset), succeeds on a fresh worker.
    # (The evidence op: only the closeout parse is made to hang here.)
    request = m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
    assert request.body["model"] == "phase-loop-evidence-audit" and _pid() not in (None, pid)
    print("DOUBLE", mode, where, flush=True)


@needs_posix
@pytest.mark.parametrize("mode", [pytest.param("monitoring", marks=pytest.mark.skipif(not PY312, reason="sys.monitoring is 3.12+")), "seam"])
def test_i1_double_injection(mode):
    code = "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; t.scenario_i1_double_injection(%r)" % (
        str(TESTS), str(SRC), MODULE, mode,
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(TESTS.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]


def scenario_i1_real_signals() -> None:
    """I1(c): SIGINT delivered by pthread_kill, gated on the owner's phase."""
    main = threading.main_thread().ident
    for phase in ("published", "mid_op", "reply_delivered"):
        _use(_hostile("phase_loop_parse_closeout", _sleep(0.3)))
        _parse()
        pid_before, log_before = _pid(), len(_log())
        spy = _AbandonSpy()
        armed = {"on": True}
        real_handle, real_deliver = m._Client._handle, m._deliver

        def fire():
            if armed["on"]:
                armed["on"] = False
                signal.pthread_kill(main, signal.SIGINT)

        if phase == "published":
            def handle(client, event):
                real_handle(client, event)
                if event[0] == "request":
                    fire()
            m._Client._handle = handle
        elif phase == "reply_delivered":
            def deliver(req, outcome):
                real_deliver(req, outcome)
                fire()
            m._deliver = deliver
        else:
            threading.Thread(target=lambda: (_busy_pid(), fire()), daemon=True).start()
        raised = None
        try:
            try:
                _parse()
                time.sleep(0.5)  # a signal that lands after the return is raised here
            finally:
                m._Client._handle, m._deliver = real_handle, real_deliver
        except KeyboardInterrupt as exc:
            raised = exc
        injected_at = time.monotonic()
        assert raised is not None and type(raised) is KeyboardInterrupt, phase
        _check_cleanup(spy, log_before, pid_before, injected_at, REAP_BOUND)
        spy.close()
        assert _parse()["terminal_status"] == "complete"
        print("SIGNAL", phase, len(spy.records), flush=True)


def scenario_i1_never_calls_again(variant: str) -> None:
    """I1(d): the caller catches the interrupt and never calls BAML again."""
    _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)), abandon_grace_s=1.0)
    spy = _AbandonSpy()
    main = threading.main_thread().ident
    if variant == "d2":
        def lost(client, req):
            spy.notices.append(None)
            raise InjectedAbort("second")  # a second exception suppresses the notice
        m._send_abandon = lost
    threading.Thread(target=lambda: (_busy_pid(), signal.pthread_kill(main, signal.SIGINT)), daemon=True).start()
    try:
        _parse()
    except (KeyboardInterrupt, InjectedAbort):
        pass
    injected_at = time.monotonic()
    delivered = [r for r in spy.notices if r is not None]
    if variant == "d1":
        assert len(delivered) == 1
        bound = REAP_BOUND
    else:
        assert delivered == []
        bound = m._CLIENT.abandon_grace_s + REAP_BOUND
    assert _wait(lambda: any(e["kind"] == "abandoned" for e in _log()), bound)
    pid = [e for e in _log() if e["kind"] == "abandoned"][0]["pid"]
    assert _wait(lambda: _gone(pid), max(0.0, injected_at + bound - time.monotonic()) + 0.2)
    assert time.monotonic() - injected_at <= bound + 0.3
    spy.close()


@needs_posix
@pytest.mark.parametrize("name,arg", [("i1_real_signals", None), ("i1_never_calls_again", "d1"), ("i1_never_calls_again", "d2")])
def test_i1_signals_and_abandonment(name, arg):
    args = "" if arg is None else repr(arg)
    code = "import signal, sys; signal.signal(signal.SIGINT, signal.default_int_handler); sys.path[:0] = [%r, %r]; import %s as t; t.scenario_%s(%s)" % (str(TESTS), str(SRC), MODULE, name, args)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=str(TESTS.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]


# ---------------------------------------------------------------------------
# I2: ownership
# ---------------------------------------------------------------------------


def scenario_i2_stalled_caller_after_reply() -> None:
    """A's reply is delivered; A's caller then stalls well past the abandonment
    grace while B executes on the same worker for longer than that grace."""
    grace = 0.5
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(3 * grace)), abandon_grace_s=grace)
    _parse()
    pid = _pid()
    real_wait = m._Client._wait
    a_req: list = []
    b_started = threading.Event()
    b_done = threading.Event()

    def wait(client, req):
        if threading.current_thread().name == "A":
            a_req.append(req)
            while not req.done:
                req.heartbeat = time.monotonic()
                time.sleep(0.01)
            # A's reply is delivered.  Stall (no heartbeat) until B has run for
            # longer than the grace, then past B's completion.
            assert b_started.wait(10)
            assert b_done.wait(20)
            time.sleep(2 * grace)
        return real_wait(client, req)

    m._Client._wait = wait
    box = {}
    a = threading.Thread(target=lambda: box.setdefault("a", _parse()), name="A")
    a.start()
    assert _wait(lambda: a_req and a_req[0].done, 10 + _cold_slack())
    b_started.set()
    started = time.monotonic()
    box["b"] = _parse()
    assert time.monotonic() - started > grace  # B executed across A's grace interval
    b_done.set()
    a.join(30)
    m._Client._wait = real_wait
    assert box["a"] == box["b"]
    assert _log() == [] and _pid() == pid
    spy.assert_each_once()


def scenario_i2_concurrent_abandonment() -> None:
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(0.4)), abandon_grace_s=1.0)
    aspy = _AbandonSpy()
    results: dict = {}

    def call(name):
        try:
            results[name] = _parse()
        except InjectedAbort as exc:
            results[name] = exc

    threads = {f"t{i}": threading.Thread(target=call, args=(f"t{i}",), name=f"t{i}") for i in range(6)}
    for thread in threads.values():
        thread.start()
    time.sleep(0.3)
    for name in ("t1", "t4"):
        _async_raise(threads[name], InjectedAbort)
    for thread in threads.values():
        thread.join(60)
    for name, value in results.items():
        if isinstance(value, BaseException):
            assert type(value) is InjectedAbort, name
        else:
            assert value["terminal_status"] == "complete", name
    assert _settled(5)
    owned = sorted(pid for (_r, pid, _s, done) in aspy.records if pid is not None and not done)
    assert sorted(e["pid"] for e in _log() if e["kind"] == "abandoned") == owned
    assert all(e["kind"] == "abandoned" for e in _log()), _log()
    aspy.close()
    spy.assert_each_once()


def scenario_i2_stale_frame() -> None:
    spy = _scenario_setup(retries=0)
    _parse()
    old = m._CLIENT.gen
    os.kill(old.pid, signal.SIGKILL)
    assert _wait(lambda: _gone(old.pid), 3)
    _parse()
    log = _log()
    new_pid = _pid()
    stale = json.dumps({"id": m._CLIENT.next_frame_id + 1, "fingerprint": old.fp, "ok": "{}"}).encode()
    m._CLIENT.events.put(("frame", old, stale))
    m._CLIENT.events.put(("eof", old, False))
    assert _parse()["terminal_status"] == "complete"
    assert _pid() == new_pid and _log() == log
    spy.assert_each_once()


# ---------------------------------------------------------------------------
# I3: a single owner
# ---------------------------------------------------------------------------


class _OwnerDeath(BaseException):
    """Raised inside the owner thread to kill it at a chosen transition."""


def _call_in_thread(fn, timeout: float):
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "the caller is still waiting: the request was lost"
    return box


def scenario_i3_owner_dies_before_delivery() -> None:
    """codex hb1 B1: the owner dies between accepting a reply and delivering it.
    Recovery must still answer the request, with no further API call, and
    dispose of the worker it held."""
    spy = _scenario_setup(retries=0)
    m._spawn_popen = _peer_spawn("echo")
    _parse()
    pid = _pid()
    real = m._deliver
    armed = {"on": True}

    def dying_deliver(req, outcome):
        if armed["on"] and outcome[0] == "reply":
            armed["on"] = False
            raise _OwnerDeath()
        real(req, outcome)

    m._deliver = dying_deliver
    try:
        box = _call_in_thread(_parse, 10)
    finally:
        m._deliver = real
    exc = box.get("exc")
    assert type(exc) is BamlWorkerError and exc.kind == "fault", box
    assert m._CLIENT.owner_starts == 2
    assert _wait(lambda: _gone(pid), REAP_BOUND + 1)
    assert any(e["pid"] == pid and e["phase"] == "owner_death" for e in _log()), _log()
    assert _parse()["terminal_status"] == "complete" and _pid() != pid
    spy.assert_each_once()


def scenario_i3_owner_dies_before_publication() -> None:
    """codex hb1 B1: the owner dies after the spawn returned and before the new
    worker is published.  The worker and its helper threads must still be
    disposed of, and the caller answered, without a further API call."""
    spy = _scenario_setup(retries=0)
    pids: list[int] = []
    m._spawn_popen = _peer_spawn("echo", record=pids)
    real = m._Client._on_spawned
    armed = {"on": True}

    def dying_on_spawned(self, spawn, result):
        if armed["on"]:
            armed["on"] = False
            raise _OwnerDeath()
        real(self, spawn, result)

    m._Client._on_spawned = dying_on_spawned
    try:
        box = _call_in_thread(_parse, 10)
    finally:
        m._Client._on_spawned = real
    exc = box.get("exc")
    assert type(exc) is BamlWorkerError and exc.kind == "fault", box
    assert pids, "no worker was spawned"
    orphan = pids[0]
    assert _wait(lambda: _gone(orphan), REAP_BOUND + 1), "the unpublished worker outlived its owner"
    assert _wait(lambda: not any(t.name.endswith(f"-{orphan}") for t in threading.enumerate()), REAP_BOUND + 1)
    assert any(e["pid"] == orphan and e["phase"] == "owner_death" for e in _log()), _log()
    assert _parse()["terminal_status"] == "complete"
    spy.assert_each_once()


# codex rounds 2 and 3 (F001): recovery must finish terminal side effects, not
# trust the flags that stand for them, and it must never wait for a future API
# call.  Every check below runs BEFORE any further call on the client.  The owner is killed at EVERY line of every
# terminal transition it runs (reply delivery, disposal, kill, release, stop,
# spawn publication), in the flow that reaches that line.  Whatever line it dies
# on, the caller gets a terminal outcome from recovery (never from the
# independent total-budget bound), no worker outlives the reap bound, no helper
# thread survives its worker, the registry forgets every released generation,
# and the client keeps working.


def _die_at_line(client, fn, line: int, fired: list):
    """``fn`` wrapped so that, on the owner thread, the owner dies (once) on the
    first ``line`` event of ``fn``'s own frame."""
    code = fn.__code__

    def local(frame, event, arg):
        if event == "line" and frame.f_lineno == line and not fired:
            fired.append(line)
            raise _OwnerDeath()
        return local

    def tracer(frame, event, arg):
        return local if frame.f_code is code else None

    def wrapper(*args, **kwargs):
        if fired or threading.get_ident() != client.owner_ident:
            return fn(*args, **kwargs)
        previous = sys.gettrace()
        sys.settrace(tracer)
        try:
            return fn(*args, **kwargs)
        finally:
            sys.settrace(previous)

    return wrapper


def _body_lines(fn) -> list[int]:
    code = fn.__code__
    return sorted({ln for (_s, _e, ln) in code.co_lines() if ln is not None and ln > code.co_firstlineno})


# flow -> (peer mode, functions whose every line the owner dies on)
_TERMINAL_FLOWS = {
    "reply": ("echo", [("module", "_deliver"), ("_Client", "_reply"), ("_Client", "_on_frame")]),
    "dispose": ("non_json", [("_Client", "_fail"), ("_Client", "_dispose"), ("_Client", "_kill"), ("_Client", "_attempt_failed"), ("_Client", "_log")]),
    "release": ("non_json", [("_Client", "_reap"), ("_Client", "_release")]),
    "publish": ("echo", [("_Client", "_on_spawned"), ("_Client", "_request_spawn"), ("_Client", "_start")]),
    "stop": ("echo", [("_Client", "_begin_stop"), ("_Client", "_stop_gen"), ("_Client", "_kill"), ("_Client", "_continue_stop"), ("_Client", "_release")]),
    # A spawn that returns after its request gave up: the late-spawn branch.
    "late_spawn": ("echo", [("_Client", "_on_spawned"), ("_Client", "_kill"), ("_Client", "_log")]),
    # A stop that drains a spawned worker still queued behind it (_begin_stop's
    # drained-spawn branch).
    "stop_drain": ("echo", [("_Client", "_begin_stop"), ("_Client", "_kill")]),
}


def _terminal_cases():
    for flow, (_mode, fns) in _TERMINAL_FLOWS.items():
        for owner, name in fns:
            fn = getattr(m if owner == "module" else m._Client, name)
            for line in _body_lines(fn):
                yield pytest.param(flow, owner, name, line, id=f"{flow}-{name}-L{line - fn.__code__.co_firstlineno}")


def _owner_death_case(flow: str, owner: str, name: str, line: int) -> bool:
    mode, _fns = _TERMINAL_FLOWS[flow]
    late = flow == "late_spawn"
    drain = flow == "stop_drain"
    client = m._Client(test_mode=True, retries=0, deadline_s=0.4 if late else 2.0, queue_budget_s=2.0, abandon_grace_s=0.5)
    target = m if owner == "module" else m._Client
    fired: list = []
    pids: list[int] = []
    gens: list = []
    real_spawn_worker = m._Client._spawn_worker

    def recording_spawn_worker(self, spawn):
        gen = real_spawn_worker(self, spawn)
        gens.append(gen)
        return gen

    def call():
        # The independent bound in _wait adds _OWNER_STALE_S on top of this: a
        # caller released only by that bound was never answered by recovery.
        answered_by = client.queue_budget_s + client.deadline_s + client.abandon_grace_s + REAP_BOUND
        started = time.monotonic()
        box = _call_in_thread(lambda: client.call("parse_closeout", {"raw": OK}), 30)
        elapsed = time.monotonic() - started
        exc = box.get("exc")
        assert exc is None or type(exc) is BamlWorkerError, box
        assert elapsed < answered_by, ("recovery never answered the caller", round(elapsed, 2), box)
        return box

    wrapped = _die_at_line(client, getattr(target, name), line, fired)
    peer = _peer_spawn(mode, record=pids)
    release = threading.Event()
    if late or drain:
        first = peer

        def peer(argv, **kwargs):  # noqa: F811 - the first spawn is held back
            if not pids:
                if late:
                    time.sleep(0.8)
                else:
                    release.wait(5)
            return first(argv, **kwargs)

    real_handle = m._Client._handle

    def handle_stop_after_spawned(self, event):
        # Deterministic drain: the stop is handled only once the held spawn has
        # returned and its "spawned" event is queued behind it.
        if self is client and event[0] == "stop":
            release.set()
            _wait(lambda: not client.events.empty(), 5)
        return real_handle(self, event)

    try:
        with mock.patch.object(m, "_spawn_popen", peer), \
                mock.patch.object(m._Client, "_spawn_worker", recording_spawn_worker):
            if flow == "stop":
                assert "value" in call()
                with mock.patch.object(target, name, wrapped):
                    client.stop(graceful=False, timeout=5)
            elif late:
                with mock.patch.object(target, name, wrapped):
                    call()  # fails with kind="spawn": the spawn is retired
                    _wait(lambda: fired or (gens and gens[0].state == "disposed"), 5)
            elif drain:
                box: dict = {}

                def waiting_call():
                    try:
                        box["value"] = client.call("parse_closeout", {"raw": OK})
                    except BaseException as exc:  # noqa: BLE001
                        box["exc"] = exc

                caller = threading.Thread(target=waiting_call, daemon=True)
                with mock.patch.object(m._Client, "_handle", handle_stop_after_spawned), mock.patch.object(target, name, wrapped):
                    caller.start()
                    assert _wait(lambda: client.spawn is not None, 5)
                    client.stop(graceful=False, timeout=5)
                    caller.join(10)
                assert not caller.is_alive(), "the caller was never answered"
                assert type(box.get("exc")) is BamlWorkerError, box
            else:
                with mock.patch.object(target, name, wrapped):
                    call()
                    if flow == "release":
                        # The failed worker is released by the owner's next pass.
                        _wait(lambda: fired or not client.late, 5)
            # The owner may still be on its way to the line after the caller returned.
            if not _wait(lambda: bool(fired), 0.3):
                return False
            # (Usually the owner died and recovered in-thread; a few lines sit
            # inside a handler of their own, e.g. _request_spawn's spawner start.)
            # WITHOUT any further call: every worker is killed AND reaped by the
            # client (a zombie does not count; returncode is set only by the
            # client's own poll), its helpers are gone, and it is released,
            # all within the I4 bound.
            deadline = REAP_BOUND + 0.5
            for gen in gens:
                assert _wait(lambda: _reaped(gen), deadline), (
                    flow, name, line, "worker not reaped without a further call", gen.state, gen.killed_at,
                    client.owner_running, client.recover,
                )
                assert _wait(lambda: not any(t.is_alive() for t in gen.threads), deadline), (flow, name, line, "helper outlived its worker")
                assert _wait(lambda: gen not in client.generations and gen.err_file.closed, deadline), (flow, name, line, "not released")
            if flow not in ("stop", "stop_drain"):
                # The client keeps working, and a later owner pass releases every
                # disposed generation (nothing stays registered or open).
                with mock.patch.object(m, "_spawn_popen", _peer_spawn("echo", record=pids)):
                    assert "value" in call(), (flow, name, line)
                assert _wait(lambda: client.generations == {client.gen}, REAP_BOUND + 1.0), (flow, name, line, client.generations)
            else:
                assert _wait(lambda: not client.generations, REAP_BOUND + 1.0), (flow, name, line, client.generations)
            for gen in gens:
                if gen is not client.gen:
                    assert gen.err_file.closed, (flow, name, line)
        return True
    finally:
        client.stop(graceful=False, timeout=5)
        for gen in gens:
            if gen.proc.poll() is None:
                gen.proc.kill()
                gen.proc.wait(5)
            for thread in gen.threads:
                thread.join(5)


@pytest.mark.parametrize("flow,owner,name,line", list(_terminal_cases()))
def test_owner_death_at_every_terminal_transition_line(flow, owner, name, line):
    if not _owner_death_case(flow, owner, name, line):
        pytest.skip("this line is not executed by the owner in this flow")


# codex round 2's two falsifiers, as filed (F001).


@pytest.mark.parametrize("boundary", ["reply", "dispose"])
def test_owner_recovery_finishes_terminal_transitions(boundary):
    import inspect

    client = m._Client(test_mode=True, retries=0, deadline_s=0.5, queue_budget_s=0.5, abandon_grace_s=0.2)
    captured = []
    fired = []
    original_deliver = m._deliver
    original_kill = m._Client._kill
    source, first = inspect.getsourcelines(original_deliver)
    put_line = next(first + i for i, line in enumerate(source) if "req.reply.put(outcome)" in line)

    def deliver(req, outcome):
        captured.append(req)

        def trace(frame, event, arg):
            if event == "line" and frame.f_code is original_deliver.__code__ and frame.f_lineno == put_line and not fired:
                fired.append(True)
                raise _OwnerDeath()
            return trace

        sys.settrace(trace)
        try:
            original_deliver(req, outcome)
        finally:
            sys.settrace(None)

    def kill(self, gen):
        if self is client and not fired:
            captured.append(gen)
            fired.append(True)
            raise _OwnerDeath()
        original_kill(self, gen)

    injection = mock.patch.object(m, "_deliver", deliver) if boundary == "reply" else mock.patch.object(m._Client, "_kill", kill)
    mode = "echo" if boundary == "reply" else "non_json"
    try:
        with mock.patch.object(m, "_spawn_popen", _peer_spawn(mode)), injection:
            try:
                client.call("parse_closeout", {"raw": "{}"})
            except BamlWorkerError:
                pass
        assert fired and client.owner_starts >= 2
        if boundary == "reply":
            assert captured[0].consumed, "the accepted request received no terminal outcome"
        else:
            gen = captured[0]
            deadline = time.monotonic() + m._REAP_BOUND_S + 0.25
            while gen.proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert gen.proc.poll() is not None, "recovery trusted disposed=True before the worker was killed"
            # (As filed, this checked the helpers at the instant the worker exited;
            # they stop on its EOF a moment later, so it raced on a slow macOS
            # runner.  Same bound, now waited for.)
            assert _wait(lambda: all(not t.is_alive() for t in gen.threads), max(0.0, deadline - time.monotonic()))
    finally:
        for gen in list(client.generations):
            original_kill(client, gen)
            gen.proc.wait(timeout=2)
            for thread in gen.threads:
                thread.join(timeout=2)
        client.stop(graceful=False, timeout=3)



# codex round 3 (F001), as filed: a late worker whose spawn was retired must be
# reaped after owner death with no caller left to trigger recovery.


def test_retired_spawn_is_reaped_after_owner_death_without_another_call():
    client = m._Client(test_mode=True, retries=0, deadline_s=0.2, queue_budget_s=0.5, abandon_grace_s=0.5)
    release_spawn = threading.Event()
    owner_died = threading.Event()
    generations = []
    real_spawn = m._spawn_popen
    original_on_spawned = m._Client._on_spawned

    def delayed_spawn(argv, **kwargs):
        assert release_spawn.wait(5)
        return real_spawn(argv, **kwargs)

    def die_before_late_kill(self, spawn, result):
        if self is client and spawn.retired and isinstance(result, m._Gen):
            generations.append(result)
            owner_died.set()
            raise _OwnerDeath()
        return original_on_spawned(self, spawn, result)

    try:
        with mock.patch.object(m, "_spawn_popen", delayed_spawn), mock.patch.object(m._Client, "_on_spawned", die_before_late_kill):
            raised = _raises(client.call, "parse_closeout", {"raw": "{}"})
            assert type(raised) is BamlWorkerError and raised.kind == "spawn"
            release_spawn.set()
            assert owner_died.wait(5), "late-spawn injection did not fire"
            gen = generations[0]
            deadline = time.monotonic() + m._REAP_BOUND_S + 0.25
            while gen.proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert gen.proc.poll() is not None, "retired worker survives the reap bound until another API call"
            assert _wait(lambda: all(not thread.is_alive() for thread in gen.threads), 0.5)
            assert _wait(lambda: gen.err_file.closed and gen not in client.generations, 0.5)
    finally:
        release_spawn.set()
        client.stop(graceful=False, timeout=3)
        for gen in generations:
            if gen.proc.poll() is None:
                gen.proc.kill()
            gen.proc.wait(timeout=2)
            gen.writes.put(None)
            for thread in gen.threads:
                thread.join(timeout=2)



def test_owner_recovers_in_thread_without_a_relaunch():
    """The primary path: a transition that dies is recovered by the SAME owner
    thread at once; no relaunch (by a caller or the supervisor) is involved."""
    client = m._Client(test_mode=True, retries=0, deadline_s=2.0)
    real_dispose = m._Client._dispose
    real_launch = m._Client._launch_owner
    armed = {"on": False}
    launches: list[str] = []

    def dying_dispose(self, gen, kind, *, phase, rc=None):
        if self is client and armed["on"]:
            armed["on"] = False
            raise _OwnerDeath()
        real_dispose(self, gen, kind, phase=phase, rc=rc)

    def recording_launch(self):
        if self is client:
            launches.append(threading.current_thread().name)
        real_launch(self)

    try:
        with mock.patch.object(m, "_spawn_popen", _peer_spawn("non_json")), \
                mock.patch.object(m._Client, "_dispose", dying_dispose), \
                mock.patch.object(m._Client, "_launch_owner", recording_launch):
            # Start an owner first, then arm the death for the framing disposal.
            client._ensure_owner()
            assert _wait(lambda: client.owner_running, 2)
            ident, starts = client.owner_ident, client.owner_starts
            launches.clear()
            armed["on"] = True
            box = _call_in_thread(lambda: client.call("parse_closeout", {"raw": OK}), 10)
            assert type(box.get("exc")) is BamlWorkerError, box
            assert not armed["on"], "the injection never fired"
            assert client.owner_ident == ident and client.owner_starts == starts + 1
            assert launches == [], launches
    finally:
        client.stop(graceful=False, timeout=3)



def test_a_worker_is_released_only_after_it_is_reaped():
    """Released means waited on.  A killed worker that has not exited by the
    reap bound is killed again and logged once (``reap_overdue``), and it stays
    tracked; it is released only once the client has reaped it."""
    client = m._Client(test_mode=True, retries=0, deadline_s=0.5)
    procs: list = []
    real = _peer_spawn("hang")

    def unkillable(argv, **kwargs):
        proc = real(argv, **kwargs)
        proc.kill = lambda: None  # the client's kills do not land
        procs.append(proc)
        return proc

    try:
        with mock.patch.object(m, "_spawn_popen", unkillable):
            raised = _raises(client.call, "parse_closeout", {"raw": OK})
            assert type(raised) is BamlWorkerError and raised.kind == "timeout"
            gen = next(g for g in list(client.generations))
            time.sleep(REAP_BOUND + 0.5)
            assert gen.proc.returncode is None and not _gone(gen.pid)
            assert gen in client.generations and gen in client.late, "released before it was reaped"
            assert [e["kind"] for e in client.fault_log].count("reap_overdue") == 1, client.fault_log
            subprocess.Popen.kill(procs[0])  # the kill finally lands
            assert _wait(lambda: gen.proc.returncode is not None and _gone(gen.pid), 2.0)
            assert _wait(lambda: gen not in client.generations and gen.err_file.closed, 2.0)
    finally:
        client.stop(graceful=False, timeout=3)
        for proc in procs:
            if proc.poll() is None:
                subprocess.Popen.kill(proc)
                proc.wait(5)



# codex round 4 (F001) and Opus round 4 F1: a spawn that returns after shutdown
# must still be killed, reaped and released with no further call.  A live
# spawner is pending work: the owner does not exit, stop() does not
# acknowledge, and the supervisor does not retire, while a spawn can publish.


def test_late_spawn_after_shutdown_is_reaped_without_another_call():
    """codex's falsifier, adapted: it waited up to 2 s for the owner and the
    supervisor to EXIT after stop() (the defect's precondition) and asserted
    that they had.  The wait is kept, so the spawn is released at the same
    point; the assertion is replaced by its opposite, since under the fix they
    stay until the spawn publishes."""
    client = m._Client(test_mode=True, retries=0, deadline_s=0.2)
    release_spawn = threading.Event()
    spawned = threading.Event()
    generations = []
    returned_at = []
    real_spawn = m._spawn_popen
    real_worker = m._Client._spawn_worker

    def delayed_spawn(argv, **kwargs):
        assert release_spawn.wait(5)
        proc = real_spawn(argv, **kwargs)
        returned_at.append(time.monotonic())
        return proc

    def record_worker(self, token):
        gen = real_worker(self, token)
        if self is client:
            generations.append(gen)
            spawned.set()
        return gen

    try:
        with mock.patch.object(m, "_spawn_popen", delayed_spawn), mock.patch.object(m._Client, "_spawn_worker", record_worker):
            raised = _raises(client.call, "parse_closeout", {"raw": "{}"})
            assert type(raised) is BamlWorkerError and raised.kind == "spawn"
            client.stop(graceful=False, timeout=2)  # returns unacknowledged: a spawn can still publish
            _wait(lambda: not client.owner_running and not client.supervisor.is_alive(), 2)
            assert client.owner_running or client.supervisor.is_alive(), "nothing is left to watch the spawn"
            # No API call after shutdown; only release the outstanding Popen.
            release_spawn.set()
            assert spawned.wait(2)
            gen = generations[0]
            deadline = returned_at[0] + m._REAP_BOUND_S + 0.25

            def disposed():
                return (
                    gen.killed_at is not None
                    and _reaped(gen)
                    and not any(t.is_alive() for t in gen.threads)
                    and gen.err_file.closed
                    and gen not in client.generations
                )

            assert _wait(disposed, max(0, deadline - time.monotonic())), (
                gen.state, gen.killed_at, gen.proc.returncode,
                client.owner_running, client.supervisor.is_alive(),
                [t.is_alive() for t in gen.threads], gen.err_file.closed,
            )
            # With nothing left that can publish, the owner and supervisor retire.
            assert _wait(lambda: not client.owner_running and not client.supervisor.is_alive(), 2.0)
    finally:
        release_spawn.set()
        for gen in generations:
            if gen.proc.poll() is None:
                gen.proc.kill()
            gen.proc.wait(2)
            gen.writes.put(None)
            for thread in gen.threads:
                thread.join(2)
            gen.err_file.close()
        client.stop(graceful=False, timeout=2)


@pytest.mark.parametrize("stop_timeout", [0.2, 5.0], ids=["stop-times-out", "stop-waits"])
@pytest.mark.parametrize("delay", [0.05, 0.3, 0.6, 1.5])
def test_stop_during_a_spawn_ends_killed_reaped_released_without_another_call(delay, stop_timeout):
    """The sweep over stop() landing while a spawn is in flight, at several
    spawn delays.  A stop given enough time acknowledges only after the late
    worker is reaped; one that times out first returns, and the client still
    finishes the job on its own within the bound of the spawn's return."""
    client = m._Client(test_mode=True, retries=0, deadline_s=5.0)
    gens: list = []
    returned_at: list = []
    real = _peer_spawn("echo")
    real_worker = m._Client._spawn_worker

    in_spawn = threading.Event()

    def slow(argv, **kwargs):
        in_spawn.set()  # the spawn is in flight from here until it returns
        time.sleep(delay)
        proc = real(argv, **kwargs)
        returned_at.append(time.monotonic())
        return proc

    def record_worker(self, token):
        gen = real_worker(self, token)
        gens.append(gen)
        return gen

    box: dict = {}

    def call():
        try:
            box["value"] = client.call("parse_closeout", {"raw": OK})
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    try:
        with mock.patch.object(m, "_spawn_popen", slow), mock.patch.object(m._Client, "_spawn_worker", record_worker):
            caller = threading.Thread(target=call, daemon=True)
            caller.start()
            # Not a poll of client.spawn: at the shortest delay the spawn can come
            # and go between two polls (seen on macOS).
            assert in_spawn.wait(5)
            started = time.monotonic()
            client.stop(graceful=False, timeout=stop_timeout)
            stop_took = time.monotonic() - started
            caller.join(10)
            assert not caller.is_alive() and type(box.get("exc")) is BamlWorkerError, box
            assert _wait(lambda: returned_at and gens, delay + 5)
            gen = gens[0]
            if stop_timeout > delay + REAP_BOUND:
                # An acknowledged stop means the late worker is already gone.
                assert stop_took < stop_timeout, "stop was never acknowledged"
                assert _reaped(gen) and gen not in client.generations, (gen.state, gen.killed_at)
            deadline = returned_at[0] + REAP_BOUND + 0.25 - time.monotonic()
            assert _wait(lambda: gen.killed_at is not None and _reaped(gen), max(0.0, deadline)), (
                "late worker not reaped without a further call", gen.state, gen.killed_at, client.owner_running,
            )
            assert _wait(lambda: not any(t.is_alive() for t in gen.threads) and gen.err_file.closed and gen not in client.generations, 0.5)
            assert [e["kind"] for e in client.fault_log if e["pid"] == gen.pid] == ["spawn_late"], client.fault_log
            assert _wait(lambda: not client.owner_running and not client.supervisor.is_alive(), 2.0)
    finally:
        client.stop(graceful=False, timeout=2)
        for gen in gens:
            if gen.proc.poll() is None:
                gen.proc.kill()
                gen.proc.wait(5)


def test_owner_death_in_its_final_statement_does_not_strand_the_baton():
    """codex round 4: an exception landing on the owner's baton hand-back (before
    the put) strands the baton; the supervisor reclaims it -- exactly one."""
    client = m._Client(test_mode=True, retries=0, deadline_s=2.0)
    real_own = m._Client._own
    code = real_own.__code__
    line = _line_of(real_own, "self.baton.put(token)")
    fired: list = []

    def local(frame, event, arg):
        if event == "line" and frame.f_lineno == line and not fired:
            fired.append(True)
            raise _OwnerDeath()
        return local

    def own(self):
        if fired:
            return real_own(self)
        sys.settrace(lambda f, e, a: local if f.f_code is code else None)
        try:
            real_own(self)
        finally:
            sys.settrace(None)

    try:
        with mock.patch.object(m, "_spawn_popen", _peer_spawn("echo")), mock.patch.object(m._Client, "_own", own):
            client.call("parse_closeout", {"raw": OK})
            client.stop(graceful=False, timeout=3)  # the owner exits via its final statement
            assert fired, "the owner never reached its hand-back"
            assert _wait(lambda: not client.baton.empty(), 2.0), "the stranded baton was never reclaimed"
            time.sleep(2 * m._SUPERVISE_S)
            assert client.baton.qsize() == 1  # reclaimed exactly once
            assert any("reclaimed" in note for note in client.pending), client.pending
    finally:
        client.stop(graceful=False, timeout=2)



def test_async_exception_after_baton_put_does_not_duplicate_the_token():
    """codex round 5 (F001), as filed: an asynchronous exception delivered when
    the hand-back's put returns must not lead to a second put (two owners)."""
    import ctypes

    client = m._Client(test_mode=True)
    injected = threading.Event()
    failures = []

    def profile(frame, event, function):
        if (
            frame.f_code is m._Client._own.__code__
            and event == "c_return"
            and getattr(function, "__self__", None) is client.baton
            and getattr(function, "__name__", None) == "put"
            and not injected.is_set()
        ):
            injected.set()
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(threading.get_ident()), ctypes.py_object(SystemExit))

    def own():
        sys.setprofile(profile)
        try:
            client._own()
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)
        finally:
            sys.setprofile(None)

    with mock.patch.object(client, "_loop", return_value=True):
        owner = threading.Thread(target=own, daemon=True)
        owner.start()
        owner.join(2)
    assert injected.is_set(), "the post-put async exception was not delivered"
    assert not owner.is_alive() and not failures
    assert client.baton.qsize() == 1, "retrying the completed put duplicated the owner baton"



# codex round 6 (F001): any number of reclaimers mint at most one baton.  The
# mechanism is a compare-and-set on a monotonic baton epoch; recording the
# supervisor before it starts only reduces how many reclaimers there are.


def _strand_the_baton(client) -> None:
    client.baton.get_nowait()  # dropped at once: no queue and no thread holds it
    gc.collect()
    assert client.baton_ref() is None and client.baton.empty()


def _supervisors_of(client) -> list:
    return [t for t in threading.enumerate() if getattr(getattr(t, "_target", None), "__self__", None) is client]


@pytest.mark.parametrize("reclaimers", [2, 4, 8, 16])
def test_concurrent_reclaimers_mint_exactly_one_baton(reclaimers):
    """The sweep: N reclaimers against a stranded baton, every one of them past
    its epoch read and live-baton check before any of them tries to mint."""
    client = m._Client(test_mode=True)
    real = m._Baton
    for _round in range(25):
        _strand_the_baton(client)
        gate = threading.Barrier(reclaimers)

        class GatedBaton(real):
            __slots__ = ()

            def __init__(self):
                gate.wait(5)  # all N have observed the same epoch and a dead baton

        with mock.patch.object(m, "_Baton", GatedBaton):
            threads = [threading.Thread(target=client._reclaim_baton) for _ in range(reclaimers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        assert client.baton.qsize() == 1, (reclaimers, _round, client.baton.qsize())
        assert client.baton_ref() is not None



def test_an_interrupted_reclaim_never_strands_the_baton_for_good():
    """A reclaimer interrupted at any line after it won its epoch must leave the
    next reclaimer able to mint, and never leave two batons."""
    real = m._Client._reclaim_baton
    code = real.__code__
    for line in _body_lines(real):
        client = m._Client(test_mode=True)
        _strand_the_baton(client)
        fired: list = []

        def trace(frame, event, arg, line=line, fired=fired):
            if frame.f_code is code and event == "line" and frame.f_lineno == line and not fired:
                fired.append(line)
                raise SystemExit
            return trace

        sys.settrace(trace)
        try:
            client._reclaim_baton()
        except SystemExit:
            pass
        finally:
            sys.settrace(None)
        gc.collect()
        client._reclaim_baton()  # the next reclaimer
        assert client.baton.qsize() == 1, (line - code.co_firstlineno, client.baton.qsize(), client.baton_epoch)



# codex round 7 (F001): an interrupted claim must never pin its epoch, whatever
# else is interrupted.  A ticket is a weak reference to the claimant's
# candidate token, so it goes dead by construction when the claimant's frame
# unwinds; there is no cleanup code left to interrupt.


def _reclaim_events(client) -> list:
    """Every point in _reclaim_baton's own frame where an interruption can land:
    each line event and each return from a C call, in order."""
    code = m._Client._reclaim_baton.__code__
    events: list = []

    def trace(frame, event, arg):
        if frame.f_code is code and event == "line":
            events.append(("line", frame.f_lineno))
        return trace

    def profile(frame, event, arg):
        if frame.f_code is code and event == "c_return":
            events.append(("c_return", getattr(arg, "__name__", repr(arg))))

    sys.settrace(trace)
    sys.setprofile(profile)
    try:
        client._reclaim_baton()
    finally:
        sys.settrace(None)
        sys.setprofile(None)
    return events


def _interrupted_reclaim(client, index: int, then: int | None = None) -> list:
    """Run one reclaim, interrupted at its index-th event, and again at its
    then-th event if it gets that far (an interruption of whatever runs while
    the first one unwinds).  A line event raises there; a C return gets an
    asynchronous exception, as codex delivered it."""
    import ctypes

    code = m._Client._reclaim_baton.__code__
    seen = [0]
    fired: list = []

    def hit(kind):
        n = seen[0]
        seen[0] += 1
        if (n == index and not fired) or (then is not None and n == then and len(fired) == 1):
            fired.append((kind, n))
            return True
        return False

    def trace(frame, event, arg):
        if frame.f_code is code and event == "line" and hit("line"):
            raise SystemExit
        return trace

    def profile(frame, event, arg):
        if frame.f_code is code and event == "c_return" and hit("c_return"):
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(threading.get_ident()), ctypes.py_object(KeyboardInterrupt))

    sys.settrace(trace)
    sys.setprofile(profile)
    try:
        client._reclaim_baton()
    except (SystemExit, KeyboardInterrupt):
        pass
    finally:
        sys.settrace(None)
        sys.setprofile(None)
    try:
        time.sleep(0)  # deliver a still-pending asynchronous exception here, not later
    except KeyboardInterrupt:
        pass
    gc.collect()
    return fired


def test_reclaim_interrupted_anywhere_once_or_twice_stays_one_baton_and_recoverable():
    """(a) never more than one baton; (b) after any interruptions the next
    uninterrupted reclaim restores exactly one.  Every interruption point of a
    reclaim; for each, every later point of the SAME reclaim (a second
    interruption of whatever runs while the first unwinds); and every point of
    a second, separately interrupted reclaimer."""
    probe = m._Client(test_mode=True)
    _strand_the_baton(probe)
    points = len(_reclaim_events(probe))
    assert points >= 8, points
    for first in range(points):
        for later in range(first + 1, points + 8):  # +8: events only an unwinding path emits
            client = m._Client(test_mode=True)
            _strand_the_baton(client)
            _interrupted_reclaim(client, first, then=later)
            assert client.baton.qsize() <= 1, (first, later)
            if client.baton.qsize() == 0:
                client._reclaim_baton()
            assert client.baton.qsize() == 1, ("same reclaim", first, later, client.baton_epoch)
        for second in [None, *range(points)]:
            client = m._Client(test_mode=True)
            _strand_the_baton(client)
            _interrupted_reclaim(client, first)
            assert client.baton.qsize() <= 1, (first, second)
            if second is not None and client.baton.qsize() == 0:
                _interrupted_reclaim(client, second)
                assert client.baton.qsize() <= 1, (first, second)
            if client.baton.qsize() == 0:
                client._reclaim_baton()
            assert client.baton.qsize() == 1, (first, second, client.baton_epoch, dict(client.baton_mints))
            client._reclaim_baton()  # a live baton: nothing more is minted
            assert client.baton.qsize() == 1


def test_second_interrupt_after_an_interrupted_claim_does_not_poison_the_epoch():
    """codex's round-7 falsifier, adapted.  As filed, its second interruption
    lands on the c_return of ``baton_mints.get`` inside the old cleanup
    ``finally``; that cleanup no longer exists, so the hook could never fire.
    Kept: the claimant is interrupted at registration, a second asynchronous
    interruption lands on the next C return the reclaim frame makes, and 100
    later reclaims must restore exactly one baton."""
    import ctypes

    client = m._Client(test_mode=True)
    _strand_the_baton(client)
    fn = m._Client._reclaim_baton
    register = _line_of(fn, "self.baton_ref = weakref.ref(token)")
    fired = []

    def trace(frame, event, arg):
        if frame.f_code is fn.__code__ and event == "line" and frame.f_lineno == register and not fired:
            fired.append("registration")
            raise SystemExit
        return trace

    def profile(frame, event, function):
        if frame.f_code is fn.__code__ and event == "c_return" and fired == ["registration"]:
            fired.append("second")
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(threading.get_ident()), ctypes.py_object(KeyboardInterrupt))

    sys.settrace(trace)
    sys.setprofile(profile)
    try:
        try:
            client._reclaim_baton()
        except (SystemExit, KeyboardInterrupt):
            pass
    finally:
        sys.settrace(None)
        sys.setprofile(None)
    assert fired[0] == "registration"
    gc.collect()
    assert client.baton_ref() is None and client.baton.empty()
    for _ in range(100):
        client._reclaim_baton()
    assert client.baton.qsize() == 1, "an interrupted claim left its epoch permanently claimed"


def test_two_live_supervisors_reclaim_exactly_one_baton():
    """codex's falsifier, adapted: it produced two live supervisors through an
    interrupted start, which can no longer happen (the next test).  Here the
    two are started directly, and both are held past the live-baton check and
    then released into the mint together, as in codex's trace."""
    client = m._Client(test_mode=True)
    ready = threading.Event()
    together = threading.Barrier(2)
    check_line = _line_of(m._Client._reclaim_baton, "if self.baton_ref() is not None:")
    mint_line = _line_of(m._Client._reclaim_baton, "token = _Baton()")
    code = m._Client._reclaim_baton.__code__
    previous = threading.gettrace()

    def trace(frame, event, arg):
        if frame.f_code is code and event == "line":
            if frame.f_lineno == check_line:
                ready.wait(5)
            elif frame.f_lineno == mint_line:
                try:
                    together.wait(5)
                except threading.BrokenBarrierError:
                    pass
        return trace

    _strand_the_baton(client)
    threading.settrace(trace)
    try:
        supervisors = [threading.Thread(target=client._supervise, daemon=True) for _ in range(2)]
        for supervisor in supervisors:
            supervisor.start()
    finally:
        threading.settrace(previous)
    client.closed = True
    ready.set()
    for supervisor in supervisors:
        supervisor.join(6)
    assert all(not t.is_alive() for t in supervisors)
    assert client.baton.qsize() == 1, "two supervisor reclaimers minted two owner batons"


def test_an_interrupted_supervisor_start_leaves_at_most_one_supervisor():
    """Recorded before it starts: an interruption at any line of
    _ensure_supervisor cannot leave a live supervisor nothing knows about."""
    real = m._Client._ensure_supervisor
    code = real.__code__
    for line in _body_lines(real):
        client = m._Client(test_mode=True)
        fired: list = []

        def trace(frame, event, arg, line=line, fired=fired):
            if frame.f_code is code and event == "line" and frame.f_lineno == line and not fired:
                fired.append(line)
                raise SystemExit
            return trace

        sys.settrace(trace)
        try:
            client._ensure_supervisor()
        except SystemExit:
            pass
        finally:
            sys.settrace(None)
        client._ensure_supervisor()
        try:
            assert len([t for t in _supervisors_of(client) if t.is_alive()]) == 1, (line, fired)
        finally:
            client.closed = True
            for t in _supervisors_of(client):
                t.join(2)


def test_a_disposal_keeps_a_sanitized_tail_of_the_workers_stderr():
    """Opus N7: a worker's own diagnostics survive into its fault-log entry."""
    peer = (
        "import json, sys, hashlib\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    sys.stderr.write('native panic: something broke token=abc123\\n'); sys.stderr.flush()\n"
        "    raise SystemExit(3)\n"
    )
    client = m._Client(test_mode=True, retries=0, deadline_s=2.0)

    def spawn(argv, **kwargs):
        return _REAL_SPAWN([argv[0], "-I", "-S", "-c", peer], **kwargs)

    try:
        with mock.patch.object(m, "_spawn_popen", spawn):
            raised = _raises(client.call, "parse_closeout", {"raw": OK})
        assert type(raised) is BamlWorkerError
        assert _wait(lambda: any("stderr_tail" in e for e in client.fault_log), REAP_BOUND + 1.0), client.fault_log
        tail = next(e["stderr_tail"] for e in client.fault_log if "stderr_tail" in e)
        assert "native panic" in tail and "abc123" not in tail
    finally:
        client.stop(graceful=False, timeout=2)



def test_a_worker_recovery_disposed_is_not_logged_again_as_spawn_late():
    """Opus N7: recovery disposes of a registered worker whose "spawned" event
    is still queued; handling that event later must not log it a second time."""
    client = m._Client(test_mode=True, retries=0, deadline_s=5.0)
    real_worker = m._Client._spawn_worker
    real_service = m._Client._service
    armed = threading.Event()
    fired = threading.Event()
    gens: list = []

    def registered_then_wait(self, spawn):
        gen = real_worker(self, spawn)  # now in client.generations
        gens.append(gen)
        armed.set()
        fired.wait(5)  # the "spawned" event is sent only after the owner died
        return gen

    def dying_service(self):
        if self is client and armed.is_set() and not fired.is_set():
            fired.set()
            raise _OwnerDeath()
        real_service(self)

    try:
        with mock.patch.object(m, "_spawn_popen", _peer_spawn("echo")), \
                mock.patch.object(m._Client, "_spawn_worker", registered_then_wait), \
                mock.patch.object(m._Client, "_service", dying_service):
            box = _call_in_thread(lambda: client.call("parse_closeout", {"raw": OK}), 15)
            assert fired.is_set() and gens, box
            gen = gens[0]
            assert _wait(lambda: _reaped(gen) and gen not in client.generations, REAP_BOUND + 1.0)
        entries = [e["kind"] for e in client.fault_log if e["pid"] == gen.pid]
        assert len(entries) == 1, entries
    finally:
        client.stop(graceful=False, timeout=2)



def test_stderr_tail_is_redacted():
    """The worker's stderr tail goes through the same redaction as messages."""
    client = m._Client(test_mode=True, retries=0, deadline_s=2)
    sentinel = "sample-value-0001"
    peer = (
        "import sys\n"
        "sys.stdin.readline()\n"
        f"sys.stderr.write('native panic: password={sentinel}\\n')\n"
        "sys.stderr.flush()\n"
        "raise SystemExit(3)\n"
    )

    def spawn(argv, **kwargs):
        return _REAL_SPAWN([argv[0], "-I", "-S", "-c", peer], **kwargs)

    try:
        with mock.patch.object(m, "_spawn_popen", spawn):
            exc = _raises(client.call, "parse_closeout", {"raw": OK})
        assert isinstance(exc, m.BamlWorkerError)
        assert _wait(lambda: any("stderr_tail" in e for e in client.fault_log), m._REAP_BOUND_S + 0.25)
        tail = next(e["stderr_tail"] for e in client.fault_log if "stderr_tail" in e)
        assert sentinel not in tail and "password=<redacted>" in tail, tail
    finally:
        client.stop(graceful=False, timeout=2)


# Values starting with any character class, including the letters that name
# regex escapes (s S d D w W b B).
_SECRET_STARTS = ["s", "S", "d", "D", "w", "W", "b", "B", "a", "Z", "0", "9", "\\", "-", "_", "/", "+", "=", ".", "~", "%"]
_SECRET_FORMS = [
    "password={v}", "PASSWORD: {v}", "api_key={v}", "api-key = {v}", 'OPENAI_API_KEY="{v}"',
    '{{"api_key": "{v}"}}', "Authorization: Bearer {v}", "secret:{v}", "token = '{v}'", "x-auth-token={v}",
]


@pytest.mark.parametrize("start", _SECRET_STARTS)
def test_redaction_covers_values_starting_with_any_character(start):
    value = f"{start}ampleValue42"
    for form in _SECRET_FORMS:
        text = "native error: " + form.format(v=value) + " trailing words"
        out = m._sanitize_text(text)
        assert "ampleValue42" not in out, (form, out)
        assert "\\1" not in out and "trailing words" in out, (form, out)


def test_redaction_covers_known_environment_values(monkeypatch):
    """Known values first: a value of a secret-named environment variable is
    redacted wherever it appears; the patterns are the backup."""
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "knownValue12345")
    assert "knownValue12345" not in m._sanitize_text("worker said: knownValue12345 (while starting)")
    assert m._sanitize_text("the token was invalid") == "the token was invalid"  # prose is left alone


def test_owner_launch_tickets_do_not_grow_without_bound():
    """Opus N-D: a recurring fault relaunches the owner every bucket; the
    tickets of past buckets are dropped."""
    client = m._Client(test_mode=True)
    try:
        now = int(time.monotonic() / m._OWNER_LAUNCH_BUCKET_S)
        for key in range(now - 500, now):
            client.owner_launches[key] = object()
        client._launch_owner()
        assert all(key >= now for key in client.owner_launches), sorted(client.owner_launches)[:3]
    finally:
        client.stop(graceful=False, timeout=2)


def test_supervisor_relaunches_an_owner_that_exited_with_recovery_pending():
    """The backstop: the owner thread really exits (its in-thread recovery keeps
    failing without progress), no caller is waiting, and the supervisor still
    relaunches an owner that disposes of the worker within the I4 bound."""
    client = m._Client(test_mode=True, retries=0, deadline_s=2.0)
    real_recover = m._Client._recover
    real_service = m._Client._service
    real_launch = m._Client._launch_owner
    state = {"service": 1, "recover": m._OWNER_REENTRIES + 1}
    launchers: list[str] = []

    def dying_service(self):
        if self is client and state["service"]:
            state["service"] -= 1
            raise _OwnerDeath()
        real_service(self)

    def failing_recover(self):
        if self is client and state["recover"]:
            state["recover"] -= 1
            raise _OwnerDeath()
        real_recover(self)

    def recording_launch(self):
        if self is client:
            launchers.append(threading.current_thread().name)
        real_launch(self)

    try:
        with mock.patch.object(m, "_spawn_popen", _peer_spawn("echo")):
            client.call("parse_closeout", {"raw": OK})
            gen = client.gen
            launchers.clear()
            with mock.patch.object(m._Client, "_service", dying_service), \
                    mock.patch.object(m._Client, "_recover", failing_recover), \
                    mock.patch.object(m._Client, "_launch_owner", recording_launch):
                assert _wait(lambda: gen.proc.returncode is not None, REAP_BOUND + m._SUPERVISE_S + 0.5), (
                    "no relaunch: the worker waits for a future call", client.owner_running, client.recover,
                )
            assert state == {"service": 0, "recover": 0}
            assert "phase-loop-baml-supervisor" in launchers, launchers
            assert _wait(lambda: gen not in client.generations and gen.err_file.closed, 1.0)
            assert "value" in _call_in_thread(lambda: client.call("parse_closeout", {"raw": OK}), 10)
    finally:
        client.stop(graceful=False, timeout=3)


def scenario_i3_owner_killed_with_waiters() -> None:
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(3)))
    results: dict = {}

    def call(name):
        try:
            results[name] = _parse()
        except BamlWorkerError as exc:
            results[name] = exc

    a = threading.Thread(target=call, args=("a",))
    a.start()
    pid = _busy_pid()
    waiters = [threading.Thread(target=call, args=(name,)) for name in ("b", "c")]
    for waiter in waiters:
        waiter.start()
    assert _wait(lambda: len(m._CLIENT.backlog) == 2, 5)
    ident = m._CLIENT.owner_ident
    if ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), ctypes.py_object(SystemExit)) != 1:
        raise AssertionError("could not kill the owner thread")
    for thread in (a, *waiters):
        thread.join(60)
    assert set(results) == {"a", "b", "c"}
    for name, value in results.items():
        assert (isinstance(value, dict) and value["terminal_status"] == "complete") or (
            type(value) is BamlWorkerError
        ), name
    assert not isinstance(results["b"], BaseException) and not isinstance(results["c"], BaseException)
    assert _wait(lambda: _gone(pid), REAP_BOUND)
    assert m._CLIENT.owner_starts == 2
    spy.assert_each_once()


# ---------------------------------------------------------------------------
# I4: deadlines, retries and budgets
# ---------------------------------------------------------------------------


def scenario_i4_busy() -> None:
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(4)), queue_budget_s=1.0, deadline_s=20)
    spawned: list[int] = []
    sent: list[bytes] = []
    real_send = m._Client._send_op
    m._Client._send_op = lambda self, gen, req: (sent.append(req.body), real_send(self, gen, req))[1]
    _parse_ok = threading.Thread(target=_parse)
    _parse_ok.start()
    pid = _busy_pid()
    m._spawn_popen = lambda argv, **kw: (spawned.append(1), _REAL_SPAWN(argv, **kw))[1]
    log = _log()
    outcomes: dict = {}

    def call(name, raw):
        started = time.monotonic()
        outcomes[name] = (_raises(m.parse_baml_response, "EmitPhaseCloseout", raw), time.monotonic() - started)

    ahead = threading.Thread(target=call, args=("ahead", OK + " "))
    victim = threading.Thread(target=call, args=("victim", OK + "  "))
    ahead.start()
    victim.start()
    ahead.join(10)
    victim.join(10)
    exc, waited = outcomes["victim"]
    assert type(exc) is BamlWorkerError and exc.kind == "busy"
    assert 1.0 <= waited <= 2.0, waited
    assert spawned == [] and all(b != m._serialize_args({"raw": OK + "  "}) for b in sent)
    assert _pid() == pid and _log() == log
    _parse_ok.join(30)
    m._Client._send_op = real_send
    spy.assert_each_once()


def scenario_i4_backlog_success() -> None:
    deadline = _deadline()
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(deadline / 2)), deadline_s=deadline, retries=0)
    first = threading.Thread(target=_parse)
    first.start()
    _busy_pid()
    started = time.monotonic()
    assert _parse()["terminal_status"] == "complete"
    assert time.monotonic() - started < deadline / 2 + deadline + 1.0
    first.join(10)
    assert _log() == []
    spy.assert_each_once()


def scenario_i4_publish_before_expiry() -> None:
    """Published, then the deadline fires during init: that worker is disposed
    of and the retry runs on a fresh pid."""
    spy = _scenario_setup(retries=1, deadline_s=_deadline())
    pids: list[int] = []
    m._spawn_popen = _peer_spawn("hang_init", first_only=True, record=pids)
    assert _parse()["terminal_status"] == "complete"
    assert len(pids) == 2 and _pid() == pids[1]
    assert [(e["kind"], e["phase"], e["pid"]) for e in _log()] == [("timeout", "init", pids[0])], (_log(), pids)
    assert _wait(lambda: _gone(pids[0]), REAP_BOUND)
    spy.assert_each_once()


def scenario_i4_post_handoff_expiries() -> None:
    # blocked write, then a fresh real worker answers (a content error for "x"*2MiB)
    deadline = _deadline()
    spy = _scenario_setup(retries=1, deadline_s=deadline)
    pids: list[int] = []
    m._spawn_popen = _peer_spawn("stall_after_init", first_only=True, record=pids)
    exc = _raises(m.parse_baml_response, "EmitPhaseCloseout", "x" * (2 * 1024 * 1024))
    assert type(exc) is BamlValidationError
    assert [(e["kind"], e["pid"]) for e in _log()] == [("timeout", pids[0])] and _pid() == pids[1]
    spy.assert_each_once()
    spy.close()
    # a hung op: each expiry disposes of its worker; each attempt runs on a fresh pid
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(60)), retries=1, deadline_s=deadline)
    exc = _raises(_parse)
    assert type(exc) is BamlWorkerError and exc.kind == "timeout"
    entries = _log()
    assert [e["kind"] for e in entries] == ["timeout", "timeout"] and entries[0]["pid"] != entries[1]["pid"]
    assert _wait(lambda: all(_gone(e["pid"]) for e in entries), REAP_BOUND)
    spy.assert_each_once()


def scenario_i4_abandon_service() -> None:
    # during a hung op
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)))
    box = {}
    caller = threading.Thread(target=lambda: box.setdefault("exc", _raises(_parse)))
    caller.start()
    pid = _busy_pid()
    injected = time.monotonic()
    _async_raise(caller, InjectedAbort)
    assert _wait(lambda: _gone(pid), 1.0), "abandonment during a hung op was not serviced within 1 s"
    assert time.monotonic() - injected <= 1.05
    caller.join(5)
    assert type(box["exc"]) is InjectedAbort
    spy.assert_each_once()
    spy.close()
    # during a stalled spawn
    spy = _scenario_setup()
    returned: list = []

    def slow(argv, **kwargs):
        time.sleep(3.0)
        proc = _REAL_SPAWN(argv, **kwargs)
        returned.append((time.monotonic(), proc.pid))
        return proc

    m._spawn_popen = slow
    box = {}
    caller = threading.Thread(target=lambda: box.setdefault("exc", _raises(_parse)))
    caller.start()
    assert _wait(lambda: m._CLIENT.spawn is not None, 5)
    spawn = m._CLIENT.spawn
    injected = time.monotonic()
    _async_raise(caller, InjectedAbort)
    assert _wait(lambda: spawn.retired and m._CLIENT.spawn is None, 1.0), "the stalled spawn was not retired within 1 s"
    assert _wait(lambda: returned, 5)
    back_at, late = returned[0]
    assert _wait(lambda: _gone(late), REAP_BOUND)
    assert time.monotonic() - back_at <= REAP_BOUND + 0.3
    assert [e["kind"] for e in _log()] == ["spawn_late"]
    caller.join(5)
    spy.assert_each_once()


# ---------------------------------------------------------------------------
# I6: calling-thread hygiene (lock-tracing spy)
# ---------------------------------------------------------------------------


def scenario_i6_lock_trace() -> None:
    _scenario_setup()
    acquisitions: list[tuple[str, int]] = []
    lock_types = (type(threading.Lock()), type(threading.RLock()))

    def profile(frame, event, arg):
        if event == "c_call" and getattr(arg, "__name__", "") in ("acquire", "__enter__", "acquire_lock"):
            owner = getattr(arg, "__self__", None)
            if isinstance(owner, lock_types):
                acquisitions.append((threading.current_thread().name, id(owner)))

    threading.setprofile(profile)
    sys.setprofile(profile)
    try:
        for _ in range(5):
            _parse()
        os.kill(_pid(), signal.SIGKILL)
        time.sleep(0.2)
        for _ in range(5):
            m.build_baml_request("EvaluateSuspectedFakeEvidence", EVIDENCE)
        m._reset_worker_for_tests(test_mode=True)
        _parse()
    finally:
        sys.setprofile(None)
        threading.setprofile(None)
    main = threading.main_thread().name
    caller = {lock for name, lock in acquisitions if name == main}
    daemon = {lock for name, lock in acquisitions if name.startswith("phase-loop-baml-")}
    shared = caller & daemon
    # The only locks the calling thread and a client thread both touch are the
    # per-thread bootstrap handshakes of threading.Thread.start (held for a
    # notify, never across I/O, Popen, kill, reap, sleep or a wait).
    bootstrap = {id(t._started._cond._lock) for t in threading.enumerate() if hasattr(t, "_started")}
    assert shared <= bootstrap or not shared, (len(shared), len(caller), len(daemon))
    print("LOCKS caller", len(caller), "daemon", len(daemon), "shared", len(shared), flush=True)


# ---------------------------------------------------------------------------
# I7: error typing
# ---------------------------------------------------------------------------


def scenario_i7_machinery_failures() -> None:
    spy = _scenario_setup(retries=0)
    real_start = threading.Thread.start

    def failing(self):
        raise RuntimeError("can't start new thread")

    threading.Thread.start = failing
    try:
        exc = _raises(_parse)
    finally:
        threading.Thread.start = real_start
    assert type(exc) is BamlWorkerError and exc.kind == "spawn"
    # the owner's raw C-level thread start fails
    _use(None, retries=0)
    real_raw = m._thread.start_new_thread

    def raw_failing(*args, **kwargs):
        raise RuntimeError("can't start new thread")

    m._thread.start_new_thread = raw_failing
    try:
        exc = _raises(_parse)
    finally:
        m._thread.start_new_thread = real_raw
    assert type(exc) is BamlWorkerError and exc.kind == "spawn"
    # the spawner's own thread start fails once the owner is up
    _use(None, retries=0)

    def failing_spawner(self):
        if self.name == "phase-loop-baml-spawner":
            raise RuntimeError("can't start new thread")
        return real_start(self)

    threading.Thread.start = failing_spawner
    try:
        exc = _raises(_parse)
    finally:
        threading.Thread.start = real_start
    assert type(exc) is BamlWorkerError and exc.kind == "spawn"
    _use(None, retries=0)
    real_pipe = os.pipe

    def emfile():
        raise OSError(24, "Too many open files")

    os.pipe = emfile
    try:
        exc = _raises(_parse)
    finally:
        os.pipe = real_pipe
    assert type(exc) is BamlWorkerError and exc.kind == "spawn"
    assert _parse()["terminal_status"] == "complete"
    spy.close()


def scenario_i7_no_discard() -> None:
    spy = _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(3)), queue_budget_s=0.5, deadline_s=20)
    spawned: list = []
    first = threading.Thread(target=_parse)
    first.start()
    pid = _busy_pid()
    log = _log()
    m._spawn_popen = lambda argv, **kw: (spawned.append(1), _REAL_SPAWN(argv, **kw))[1]
    busy = _raises(_parse)
    assert type(busy) is BamlWorkerError and busy.kind == "busy"
    assert (_pid(), _log(), spawned) == (pid, log, [])
    first.join(30)
    m._CLIENT.closing = True
    shutdown = _raises(_parse)
    m._CLIENT.closing = False
    assert type(shutdown) is BamlWorkerError and shutdown.kind == "shutdown"
    assert (_pid(), _log(), spawned) == (pid, log, []) and not _gone(pid)
    if POSIX:
        child = os.fork()
        if child == 0:
            exc = _raises(_parse)
            os._exit(0 if type(exc) is BamlWorkerError and exc.kind == "forked" else 3)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert (_pid(), _log(), spawned) == (pid, log, []) and not _gone(pid)
    spy.assert_each_once()


# ---------------------------------------------------------------------------
# I9: resources
# ---------------------------------------------------------------------------


def _fd_count() -> int:
    if LINUX:
        return len(os.listdir("/proc/self/fd"))
    import psutil

    proc = psutil.Process()
    return proc.num_handles() if WINDOWS else proc.num_fds()


def _pidfds() -> int:
    if not LINUX:
        return 0
    count = 0
    for fd in os.listdir("/proc/self/fd"):
        try:
            count += "pidfd" in os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            pass
    return count


def scenario_i9_resources() -> None:
    """N = 50 mixed dispose cycles (kill, timeout, abandon, fault); every
    resource returns to baseline within the reap bound."""
    _deadline()  # measure the cold start before the baseline
    # No _DeliverySpy here: it keeps every _Request (and so its reply queue's
    # lock) alive, which on Windows shows up as leaked Semaphore handles.
    _scenario_setup(abandon_grace_s=1.0).close()
    _parse()
    _settled(2)
    time.sleep(0.5)
    gc.collect()
    fds, threads, pidfds = _fd_count(), threading.active_count(), _pidfds()
    os_threads = len(os.listdir("/proc/self/task")) if LINUX else 0
    handles = _process_handle_count() if WINDOWS else 0
    handle_types = _handle_types() if WINDOWS else None
    disposed: list[int] = []
    jobs: list[str] = []
    hang = _hostile("phase_loop_parse_closeout", _sleep(60))
    panic = _panic_files()
    for cycle in range(50):
        kind = ("kill", "timeout", "abandon", "fault")[cycle % 4]
        if kind == "kill":
            _use(None, abandon_grace_s=1.0)
            _parse()
            pid = _pid()
            _hard_kill(pid)
            _wait(lambda: _gone(pid), 3)
            _parse()
        elif kind == "timeout":
            _use(hang, deadline_s=max(1.5, 2 * _COLD[0]), retries=0)  # covers init; the op then hangs
            assert _raises(_parse).kind == "timeout"
        elif kind == "abandon":
            _use(hang, abandon_grace_s=1.0)
            box = {}
            caller = threading.Thread(target=lambda: box.setdefault("e", _raises(_parse)))
            caller.start()
            _busy_pid()
            _async_raise(caller, InjectedAbort)
            caller.join(10)
        else:
            _use(panic)
            assert _raises(_parse).kind == "fault"
        assert _settled(REAP_BOUND + 1)
        disposed.extend(e["pid"] for e in _log())
        jobs.extend(e["job"] for e in _log() if "job" in e)
    assert len(disposed) >= 50, len(disposed)
    _use(None)
    _parse()  # the permitted current worker and its long-lived threads
    assert _settled(REAP_BOUND + 1)
    ok = _wait(lambda: (gc.collect() or True) and _fd_count() <= fds + (16 if WINDOWS else 2) and threading.active_count() <= threads + 1, REAP_BOUND + 1)
    assert ok, (
        fds, _fd_count(), threads, threading.active_count(), [t.name for t in threading.enumerate()],
        _handle_types() if WINDOWS else None, handle_types,
    )
    # The owner is a raw thread (not in threading.enumerate); count OS threads too.
    if LINUX:
        assert _wait(lambda: len(os.listdir("/proc/self/task")) <= os_threads + 1, REAP_BOUND + 1), (
            os_threads, len(os.listdir("/proc/self/task"))
        )
    assert _pidfds() == pidfds
    if POSIX:
        for pid in disposed:
            try:
                result = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                continue
            raise AssertionError(f"disposed worker {pid} was not reaped: {result}")
    if WINDOWS:
        import psutil

        # Windows reuses PIDs quickly: a live PID from the list counts only if it
        # is still one of OUR children and not the current, permitted worker
        # (whose PID may itself be a reused one from the list).
        def ours(pid):
            try:
                proc = psutil.Process(pid)
                return pid != _pid() and proc.ppid() == os.getpid()
            except psutil.Error:
                return False

        def described(pid):
            try:
                proc = psutil.Process(pid)
                return (pid, proc.ppid(), proc.name(), proc.create_time())
            except psutil.Error as exc:
                return (pid, repr(exc))

        survivors = [pid for pid in set(disposed) if ours(pid)]
        assert not survivors, ("a disposed worker is still running", [described(pid) for pid in survivors], os.getpid(), _pid())
        # Every disposed generation's Job Object is gone: with its last handle
        # closed the named object no longer exists (named, so a reused numeric
        # handle value cannot fake this; codex r15).
        assert len(jobs) == len(disposed), (len(jobs), len(disposed))
        assert _wait(lambda: not [name for name in jobs if _job_exists(name)], REAP_BOUND + 1), [
            name for name in jobs if _job_exists(name)
        ]
        assert _wait(lambda: _process_handle_count() <= handles + 16, REAP_BOUND + 1), (handles, _process_handle_count())
    print("I9", len(disposed), "disposals", flush=True)


def _hard_kill(pid: int) -> None:
    os.kill(pid, signal.SIGKILL if POSIX else signal.SIGTERM)  # SIGTERM is TerminateProcess on Windows


def _kernel32():
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    kernel32.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32


def _process_handle_count() -> int:
    from ctypes import wintypes

    kernel32 = _kernel32()
    count = wintypes.DWORD(0)
    assert kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(count)), ctypes.get_last_error()
    return count.value


def _handle_types() -> dict[str, int]:
    """Diagnostic: this process's open handles by object type (Windows)."""
    from ctypes import wintypes

    kernel32 = _kernel32()
    kernel32.GetHandleInformation.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtQueryObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))
    counts: collections.Counter = collections.Counter()
    buf = ctypes.create_string_buffer(4096)
    flags = wintypes.DWORD(0)
    for value in range(4, 4 * 8192, 4):
        if not kernel32.GetHandleInformation(value, ctypes.byref(flags)):
            continue
        returned = wintypes.ULONG(0)
        if ntdll.NtQueryObject(value, 2, buf, len(buf), ctypes.byref(returned)) != 0:  # ObjectTypeInformation
            counts["?"] += 1
            continue
        length = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort))[0]
        address = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[1]
        counts[ctypes.wstring_at(address, length // 2)] += 1
    return dict(counts)


def _job_exists(name: str) -> bool:
    kernel32 = _kernel32()
    handle = kernel32.OpenJobObjectW(0x0004, False, name)  # JOB_OBJECT_QUERY
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("i2_stalled_caller_after_reply"),
        pytest.param("i2_concurrent_abandonment"),
        pytest.param("i2_stale_frame", marks=needs_posix),
        pytest.param("i3_owner_killed_with_waiters"),
        pytest.param("i3_owner_dies_before_delivery"),
        pytest.param("i3_owner_dies_before_publication"),
        pytest.param("i4_busy"),
        pytest.param("i4_backlog_success"),
        pytest.param("i4_publish_before_expiry"),
        pytest.param("i4_post_handoff_expiries"),
        pytest.param("i4_abandon_service"),
        pytest.param("i6_lock_trace", marks=needs_posix),
        pytest.param("i7_machinery_failures"),
        pytest.param("i7_no_discard"),
        pytest.param("i9_resources"),
    ],
)
def test_client_invariant_scenario(name):
    # I9 pays one worker cold start per dispose cycle: ~95 s on x86_64 glibc,
    # but ~13 s per cold start on musl (verification step 6).
    _isolated(name, timeout=2400 if name == "i9_resources" else 600)


# ---------------------------------------------------------------------------
# Windows and macOS owner death (run in the pre-merge dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not WINDOWS, reason="Windows-only: Job Object owner death")
def test_windows_job_object_kills_a_hung_worker_when_the_owner_dies():
    owner = _scenario_proc("owner_hung_windows")
    try:
        worker, in_job, image = _read_tagged(owner, "BUSY")
        assert in_job == "1", "the worker is not in the owner's Job Object"
        assert Path(image).resolve() == Path(getattr(sys, "_base_executable", sys.executable)).resolve()
        subprocess.run(["taskkill", "/F", "/PID", str(owner.pid)], check=False, capture_output=True)
        owner.wait(10)
        import psutil

        assert _wait(lambda: not psutil.pid_exists(int(worker)), 3.0)
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


def scenario_owner_hung_windows() -> None:
    import psutil

    _scenario_setup(_hostile("phase_loop_parse_closeout", _sleep(30)))

    def watch():
        pid = _busy_pid(30)
        gen = m._CLIENT.gen
        in_job = ctypes.c_int(0)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.IsProcessInJob(ctypes.c_void_p(int(gen.proc._handle)), ctypes.c_void_p(gen.job.handle), ctypes.byref(in_job))
        print("BUSY", pid, 1 if in_job.value else 0, psutil.Process(pid).exe(), flush=True)

    threading.Thread(target=watch, daemon=True).start()
    _parse()


@pytest.mark.skipif(not MACOS, reason="macOS-only: getppid watchdog is the owner-death mechanism")
def test_macos_watchdog_kills_a_hung_worker_when_the_owner_dies():
    test_owner_death_kills_a_worker_hung_in_a_native_op("watchdog")
