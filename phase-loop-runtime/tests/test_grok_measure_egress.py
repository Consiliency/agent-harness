"""Lane L2a of the grok tool-surface plan: vendor-only ``grok-review`` egress with a request
budget (plans/artifacts/grok-tool-surface-contract-v1.md sections 5.2, 5.3, 8 and BA-1 of
section 10). No test contacts a vendor or runs a model.

Layers, cheapest first:

- the ``grok-review`` allowlist file, the reserved ``grok`` id, and the pinned ``codex`` and
  ``gemini`` digests (offline);
- ``proxy.mjs`` under a fake srt module that drives its ``filterRequest`` directly, through
  the real ``start_proxy``: the budget, its narrowing, the end-of-stream marker and the BA-1
  completion proof (needs only node);
- the real ``start_proxy`` over the pinned srt, with port-443 dials sent to a loopback fixture
  upstream (skips where the egress layer is absent);
- the proxy-only namespace a launch-owner leg holds (skips where its prerequisites are absent;
  ``PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1`` makes a missing prerequisite fail);
- the grok ``seat_profile`` proxy projection (offline).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import ssl
import subprocess
import threading
import time
import urllib.parse

import pytest

from phase_loop_runtime import grok_tool_surface
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_profiles

#: Contract section 8: these two must not move. Taken from origin/main before this lane.
CODEX_ALLOWLIST_DIGEST = "559e7973c7c0d4e1234d1d23db3d5eab6c83996dfaaf75ff65482f19abffa21e"
GEMINI_ALLOWLIST_DIGEST = "e29dc83b60705beed3d87c600b023dc959a51c76c5e1ab8df9001b1d7daaa296"
#: The new pin this lane adds (contract section 8, "Egress allow-list content digests").
GROK_REVIEW_ALLOWLIST_DIGEST = "06a42988e74f9163eb50621c6836068d2cf4c9e387b874ec328dd470b5e259ee"
INFERENCE_HOST = "cli-chat-proxy.grok.com"
INFERENCE_PATH = "/v1/chat/completions"
GROK_REVIEW = seat_egress_proxy.allowlist_ref("grok-review")


def _document(name: str) -> dict:
    return json.loads(seat_egress_proxy._data_path(name).read_text(encoding="utf-8"))


def _other_allowlists() -> dict[str, dict]:
    directory = seat_egress_proxy._data_path("grok-review-allowlist.json").parent
    return {path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*-allowlist.json"))
            if path.name != "grok-review-allowlist.json"}


# --------------------------------------------------------------------------------------
# The allowlist file (contract section 5.2).
# --------------------------------------------------------------------------------------

def test_the_grok_review_allowlist_is_the_statically_known_inference_row():
    document = _document("grok-review-allowlist.json")
    assert document["schema"] == "phase_loop_seat_egress_allowlist.v1"
    assert document["leg"] == "grok-review"
    assert document["allow"] == [
        {"host": INFERENCE_HOST, "port": 443, "method": "POST", "path": INFERENCE_PATH},
    ]
    # Sign-in and token-refresh hosts are refused, so an expired credential fails closed.
    assert document["measured_and_refused"] == ["accounts.x.ai", "auth.x.ai"]
    for rule in document["allow"]:
        assert "path" in rule and "path_prefix" not in rule, "every row is an exact path"
        assert "*" not in rule["host"]


def test_the_grok_review_allowlist_loads_and_binds_every_row():
    document = _document("grok-review-allowlist.json")
    assert GROK_REVIEW.id == "grok-review"
    assert list(GROK_REVIEW.request_set) == document["allow"]
    assert GROK_REVIEW.content_digest == GROK_REVIEW_ALLOWLIST_DIGEST
    assert GROK_REVIEW.content_digest == seat_egress_proxy._digest({
        key: document[key] for key in ("schema", "leg", "allow", "measured_and_refused")})
    refused = [row["host"] for row in GROK_REVIEW.probe_rows if row["decision"] == "refuse"]
    assert refused == [*document["measured_and_refused"], "seat-egress-unlisted.invalid"]


def test_the_grok_id_stays_reserved_for_the_jailed_seat():
    assert not seat_egress_proxy._data_path("grok-allowlist.json").exists()
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        seat_egress_proxy.allowlist("grok")
    assert caught.value.code == seat_egress_proxy.ALLOWLIST_MISSING_CODE
    assert seat_egress_proxy.GROK_REVIEW_ALLOWLIST == "grok-review"
    # Reserved FOR the jailed seat (IF-0-GROK-2, ruling 4): only the registered Grok jail
    # profile, the `grok` leg defined by `seat_profile_grok`, adopts it.
    users = {leg: profile for leg, profile in seat_profiles._REGISTRY.items()
             if profile.allowlist_id == "grok-review"}
    assert set(users) <= {"grok"}
    for profile in users.values():
        assert profile.owner_binds.__module__ == "phase_loop_runtime.seat_profile_grok"


def test_no_grok_review_host_is_listed_by_another_seat():
    ours = {rule["host"] for rule in _document("grok-review-allowlist.json")["allow"]}
    for name, document in _other_allowlists().items():
        theirs = {rule["host"] for rule in document["allow"]}
        assert not ours & theirs, name


def test_the_codex_and_gemini_allowlist_digests_do_not_move():
    assert seat_egress_proxy.allowlist_ref("codex").content_digest == CODEX_ALLOWLIST_DIGEST
    assert seat_egress_proxy.allowlist_ref("gemini").content_digest == GEMINI_ALLOWLIST_DIGEST


def test_a_missing_allowlist_refuses_before_any_proxy_starts(monkeypatch, tmp_path):
    real = seat_egress_proxy._data_path
    monkeypatch.setattr(seat_egress_proxy, "_data_path", lambda name: (
        tmp_path / "absent.json" if name == "grok-review-allowlist.json" else real(name)))
    monkeypatch.setattr(seat_egress_proxy, "_node", lambda: "/usr/bin/node")
    monkeypatch.setattr(seat_egress_proxy, "_require_srt_host_tools", lambda _node: None)
    monkeypatch.setattr(seat_egress_proxy, "verify_install", lambda: tmp_path / "index.js")
    monkeypatch.setattr(seat_egress_proxy, "ensure_ca",
                        lambda *_a: (tmp_path / "ca.crt", tmp_path / "ca.key"))

    def no_popen(*_a, **_k):
        raise AssertionError("a proxy was started without its allowlist")

    monkeypatch.setattr(seat_egress_proxy.subprocess, "Popen", no_popen)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review"):
            pass
    assert caught.value.code == seat_egress_proxy.ALLOWLIST_MISSING_CODE


@pytest.mark.parametrize("budget", [-1, seat_egress_proxy.MAX_REQUEST_BUDGET + 1, True, 1.0, "1"])
def test_an_invalid_request_budget_is_refused_before_anything_runs(budget, monkeypatch):
    def no_layer():
        raise AssertionError("the layer was consulted for an invalid budget")

    monkeypatch.setattr(seat_egress_proxy, "_node", no_layer)
    with pytest.raises(ValueError):
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=budget):
            pass


# --------------------------------------------------------------------------------------
# The shared launch-owner egress refuses before any launch (contract sections 5.2, 4.6).
# --------------------------------------------------------------------------------------

def _forbid_launches(monkeypatch):
    def launched(*_a, **_k):
        raise AssertionError("something was launched")

    monkeypatch.setattr(pi, "launch_provider", launched)
    monkeypatch.setattr(pi, "launch_owned", launched)


def test_the_egress_layer_unavailable_refuses_before_any_launch(monkeypatch):
    _forbid_launches(monkeypatch)

    def unavailable():
        raise seat_egress_proxy.EgressLayerUnavailable(
            seat_egress_proxy.NOT_INSTALLED_CODE, "srt is not installed")

    def no_namespace(*_a, **_k):
        raise AssertionError("a namespace was held without a proxy")

    monkeypatch.setattr(seat_egress_proxy, "_node", unavailable)
    monkeypatch.setattr(sandbox_egress, "isolated_network", no_namespace)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with pi._grok_review_egress(timeout_s=60.0):
            pytest.fail("the egress yielded without its layer")
    assert caught.value.code == seat_egress_proxy.NOT_INSTALLED_CODE


class _StandInProxy:
    socket = "/stand-in.sock"


def _stand_in_proxy(monkeypatch, record: list):
    @contextlib.contextmanager
    def start(**kwargs):
        record.append(("start", kwargs))
        try:
            yield _StandInProxy()
        finally:
            record.append(("stop", None))

    monkeypatch.setattr(seat_egress_proxy, "start_proxy", start)


def test_the_namespace_unavailable_refuses_and_stops_the_proxy(monkeypatch):
    _forbid_launches(monkeypatch)
    record: list = []
    _stand_in_proxy(monkeypatch, record)

    @contextlib.contextmanager
    def unavailable(*_a, **kwargs):
        record.append(("namespace", kwargs))
        raise sandbox_egress.EgressUnavailable("egress isolation unavailable")
        yield ()  # pragma: no cover

    monkeypatch.setattr(sandbox_egress, "isolated_network", unavailable)
    with pytest.raises(sandbox_egress.EgressUnavailable):
        with pi._grok_review_egress(timeout_s=60.0, request_budget=1):
            pytest.fail("the egress yielded without its namespace")
    assert record[0] == ("start", {"allowlist_id": "grok-review", "request_budget": 1})
    assert record[1] == ("namespace", {
        "timeout_s": 60.0, "required": True, "seat_uid_map": True,
        "proxy_socket": "/stand-in.sock", "proxy_port": seat_egress_proxy.SEAT_PROXY_PORT})
    assert record[-1] == ("stop", None)


def test_an_empty_namespace_prefix_refuses(monkeypatch):
    _forbid_launches(monkeypatch)
    record: list = []
    _stand_in_proxy(monkeypatch, record)

    @contextlib.contextmanager
    def empty(*_a, **_k):
        yield ()

    monkeypatch.setattr(sandbox_egress, "isolated_network", empty)
    with pytest.raises(sandbox_egress.EgressUnavailable):
        with pi._grok_review_egress(timeout_s=None):
            pytest.fail("the egress yielded an empty prefix")
    assert record[-1] == ("stop", None)


# --------------------------------------------------------------------------------------
# proxy.mjs under a fake srt, through the real start_proxy.
# --------------------------------------------------------------------------------------

_FAKE_SRT = r"""
// Test-only stand-in for srt: SandboxManager hands its filterRequest to a trigger file, so a
// test can decide requests directly. FAKE_SRT_MODE picks how reset() (the orderly
// shutdown) ends: "orderly", "exit0" (exit without the marker), "hang" (never exits).
import { createServer } from 'node:net';
import { existsSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
const socketPath = process.env.FAKE_SRT_SOCKET;
const mode = process.env.FAKE_SRT_MODE || 'orderly';
let server;
let filter;
async function run(script) {
  let verdicts;
  const decide = r => filter(new Request(r.url, { method: r.method }));
  if (script.concurrent) {
    verdicts = (await Promise.all(script.requests.map(decide))).map(v => v.action);
  } else {
    verdicts = [];
    for (const r of script.requests) verdicts.push((await decide(r)).action);
  }
  if (script.truncate !== undefined) {
    process.stdout.write(script.truncate, () => process.exit(0));
    return;
  }
  writeFileSync(process.env.FAKE_SRT_DONE, JSON.stringify(verdicts));
}
export const SandboxManager = {
  async initialize(options) {
    filter = options.network.filterRequest;
    copyFileSync(process.argv[3], process.env.FAKE_SRT_CONFIG_COPY);
    server = createServer(client => client.destroy());
    await new Promise((resolve, reject) => {
      server.once('error', reject); server.listen(socketPath, resolve);
    });
    const timer = setInterval(() => {
      const trigger = process.env.FAKE_SRT_TRIGGER;
      if (!existsSync(trigger)) return;
      clearInterval(timer);
      run(JSON.parse(readFileSync(trigger, 'utf8')));
    }, 20);
  },
  getMitmCA() { return { secureContexts: new Map() }; },
  getLinuxHttpSocketPath() { return socketPath; },
  getProxyAuthToken() { return 'fake-srt-token'; },
  async reset() {
    if (mode === 'exit0') process.exit(0);
    if (mode === 'hang') { setInterval(() => {}, 1000); return new Promise(() => {}); }
    await new Promise(resolve => server.close(resolve));
  },
};
"""


def _node_or_skip() -> str:
    try:
        return seat_egress_proxy._node()
    except seat_egress_proxy.EgressLayerUnavailable as exc:
        pytest.skip(f"node is unavailable here ({exc})")


class FakeSrt:
    """The real ``start_proxy`` and ``proxy.mjs``, over a stand-in srt module."""

    def __init__(self, tmp_path: Path, monkeypatch, *, mode: str = "orderly",
                 proxy_script: Path | None = None) -> None:
        node = _node_or_skip()
        root = tmp_path / "fake-srt"
        root.mkdir(mode=0o700)
        self.root = root
        module = root / "index.mjs"
        module.write_text(_FAKE_SRT, encoding="utf-8")
        # A stand-in CA: the proxy only fingerprints it; the fake srt never uses it.
        self.ca_der = b"phase-loop fixture CA " + os.urandom(16)
        cert = root / "ca.crt"
        cert.write_text(ssl.DER_cert_to_PEM_cert(self.ca_der), encoding="ascii")
        key = root / "ca.key"
        key.write_bytes(b"unused")
        self.cert = cert
        self.key = key
        self.trigger = root / "trigger.json"
        self.done = root / "done.json"
        self.config_copy = root / "config-copy.json"
        socket_path = Path("/tmp") / ("pl-fake-srt-" + hashlib.sha256(
            str(root).encode()).hexdigest()[:16] + ".sock")
        socket_path.unlink(missing_ok=True)
        self.socket_path = socket_path
        real_env = seat_egress_proxy._proxy_env
        values = {
            "FAKE_SRT_SOCKET": str(socket_path), "FAKE_SRT_MODE": mode,
            "FAKE_SRT_TRIGGER": str(self.trigger), "FAKE_SRT_DONE": str(self.done),
            "FAKE_SRT_CONFIG_COPY": str(self.config_copy),
        }

        def proxy_env(node_path, home):
            env = real_env(node_path, home)
            if home is not None:
                env.update(values)
            return env

        monkeypatch.setattr(seat_egress_proxy, "_node", lambda: node)
        monkeypatch.setattr(seat_egress_proxy, "_require_srt_host_tools", lambda _node: None)
        monkeypatch.setattr(seat_egress_proxy, "verify_install", lambda: module)
        monkeypatch.setattr(seat_egress_proxy, "ensure_ca", lambda *_a: (cert, key))
        monkeypatch.setattr(seat_egress_proxy, "_proxy_env", proxy_env)
        if proxy_script is not None:
            real = seat_egress_proxy._data_path
            monkeypatch.setattr(seat_egress_proxy, "_data_path", lambda name: (
                proxy_script if name == "proxy.mjs" else real(name)))

    def decide(self, requests, *, concurrent: bool = False, truncate: str | None = None,
               timeout_s: float = 15.0):
        script = {"requests": requests, "concurrent": concurrent}
        if truncate is not None:
            script["truncate"] = truncate
        staged = self.trigger.with_suffix(".tmp")
        staged.write_text(json.dumps(script), encoding="utf-8")
        os.replace(staged, self.trigger)
        if truncate is not None:
            return None
        deadline = time.monotonic() + timeout_s
        while not self.done.exists():
            assert time.monotonic() < deadline, "the fake srt did not decide"
            time.sleep(0.02)
        return json.loads(self.done.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.socket_path.unlink(missing_ok=True)


@pytest.fixture
def fake_srt(tmp_path, monkeypatch):
    opened: list[FakeSrt] = []

    def make(**kwargs) -> FakeSrt:
        run = tmp_path / f"run-{len(opened)}"
        run.mkdir()
        fake = FakeSrt(run, monkeypatch, **kwargs)
        opened.append(fake)
        return fake

    yield make
    for fake in opened:
        fake.close()


def _post(host: str = INFERENCE_HOST, path: str = INFERENCE_PATH) -> dict:
    return {"method": "POST", "url": f"https://{host}{path}"}


def _events(proxy) -> list[tuple[str, str, str | None, str]]:
    stream = seat_egress_proxy.proxy_stream(proxy)
    return [(event.method, event.host, event.path, event.decision)
            for event in stream.outside_events]


def test_the_budget_denies_counted_request_n_plus_one(fake_srt):
    fake = fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=2) as proxy:
        assert proxy.request_budget == 2
        verdicts = fake.decide([_post(), _post(), _post()])
    assert verdicts == ["allow", "allow", "deny"]
    assert _events(proxy) == [("POST", INFERENCE_HOST, INFERENCE_PATH, "allow")] * 2 + [
        ("POST", INFERENCE_HOST, INFERENCE_PATH, "deny")]
    proof = seat_egress_proxy.completion(proxy)
    assert proof.complete and (proof.requests, proof.counted, proof.budget) == (3, 2, 2)
    assert seat_egress_proxy.charged_requests(proxy) == 2


def test_concurrent_requests_never_share_a_unit_of_the_budget(fake_srt):
    fake = fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        verdicts = fake.decide([_post()] * 24, concurrent=True)
    assert verdicts.count("allow") == 1 and verdicts.count("deny") == 23
    assert seat_egress_proxy.charged_requests(proxy) == 1


def test_a_zero_budget_refuses_every_request(fake_srt):
    fake = fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=0) as proxy:
        verdicts = fake.decide([_post()])
    assert verdicts == ["deny"]
    assert seat_egress_proxy.charged_requests(proxy) == 0


def test_the_budget_only_narrows_the_allowlist(fake_srt):
    """A refused request stays refused and is not charged; an allowed GET is not counted;
    once the budget is spent every request is refused, counted or not."""
    fake = fake_srt()
    get_path = "/backend-api/wham/accounts/check"
    post_path = "/backend-api/codex/responses"
    with seat_egress_proxy.start_proxy(allowlist_id="codex", request_budget=1) as proxy:
        verdicts = fake.decide([
            _post(INFERENCE_HOST, INFERENCE_PATH),              # not on the codex allowlist
            _post("chatgpt.com", "/backend-api/other"),        # listed host, unlisted path
            {"method": "GET", "url": f"https://chatgpt.com{get_path}"},   # allowed, uncounted
            _post("chatgpt.com", post_path),                   # allowed, counted: spends it
            {"method": "GET", "url": f"https://chatgpt.com{get_path}"},   # now refused
        ])
    assert verdicts == ["deny", "deny", "allow", "allow", "deny"]
    proof = seat_egress_proxy.completion(proxy)
    assert proof.complete and (proof.requests, proof.counted) == (5, 1)


def test_a_budgetless_proxy_keeps_its_configuration_stream_and_decisions(fake_srt):
    fake = fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review") as proxy:
        assert proxy.request_budget is None
        verdicts = fake.decide([_post()] * 3)
    assert verdicts == ["allow"] * 3
    # The configuration bytes are the ones written before the budget existed.
    assert fake.config_copy.read_text(encoding="utf-8") == json.dumps({
        "allow": list(GROK_REVIEW.request_set), "ca_cert": str(fake.cert),
        "ca_key": str(fake.key), "inner_sni_check": True})
    stream = seat_egress_proxy.proxy_stream(proxy)
    assert stream.final and not stream.protocol_error
    assert len(stream.outside_events) == 3 and proxy._end is None
    assert seat_egress_proxy.completion(proxy).reason == "unbudgeted"
    with pytest.raises(ValueError):
        seat_egress_proxy.charged_requests(proxy)


def test_a_budgeted_configuration_adds_only_the_budget(fake_srt):
    fake = fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1):
        fake.decide([])
    assert json.loads(fake.config_copy.read_text(encoding="utf-8")) == {
        "allow": list(GROK_REVIEW.request_set), "ca_cert": str(fake.cert),
        "ca_key": str(fake.key), "inner_sni_check": True, "request_budget": 1}


def test_a_proxy_that_does_not_attest_its_budget_is_refused(fake_srt, tmp_path):
    text = seat_egress_proxy._data_path("proxy.mjs").read_text(encoding="utf-8")
    needle = "    ...(remaining !== null ? { request_budget: BUDGET } : {}),\n"
    assert text.count(needle) == 1
    unattested = tmp_path / "unattested-proxy.mjs"
    unattested.write_text(text.replace(needle, ""), encoding="utf-8")
    fake_srt(proxy_script=unattested)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1):
            pytest.fail("an unattested budget was accepted")
    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE


def test_a_proxy_without_the_data_guard_does_not_start(fake_srt, proxy_diagnostics, tmp_path):
    """agent-harness#2067: the start-up check attests the Readable.toWeb data guard on Node's
    real adapter. A copy whose replacement listener is the adapter's own listener exits 3
    with the guard diagnostic before any ready line, and the launcher refuses it."""
    text = seat_egress_proxy._data_path("proxy.mjs").read_text(encoding="utf-8")
    needle = "      source.on('data', guardDataListener(source, listener));\n"
    assert text.count(needle) == 1
    unguarded = tmp_path / "unguarded-proxy.mjs"
    unguarded.write_text(text.replace(needle, "      source.on('data', listener);\n"),
                         encoding="utf-8")
    fake_srt(proxy_script=unguarded)
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1):
            pytest.fail("a proxy without the data guard started")
    assert caught.value.code == seat_egress_proxy.START_FAILED_CODE
    [process] = proxy_diagnostics.processes
    assert process.wait(timeout=15) == 3
    assert proxy_diagnostics.stderr() == "toWeb data guard is not in force\n"
    # Run directly: the same exit, and nothing on stdout, so no ready line.
    node = seat_egress_proxy._node()
    done = subprocess.run([node, str(unguarded), str(tmp_path / "unused.mjs"),
                           str(tmp_path / "unused.json")],
                          capture_output=True, text=True, timeout=15)
    assert (done.returncode, done.stdout) == (3, "")
    assert done.stderr == "toWeb data guard is not in force\n"


def test_an_invalid_budget_in_the_configuration_stops_the_proxy(tmp_path):
    node = shutil.which("node") or _node_or_skip()
    module = tmp_path / "unused.mjs"
    module.write_text("export const SandboxManager = {};\n", encoding="utf-8")
    for budget in (-1, 1.5, "1", True, seat_egress_proxy.MAX_REQUEST_BUDGET + 1):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"allow": [], "request_budget": budget}), encoding="utf-8")
        done = subprocess.run(
            [node, str(seat_egress_proxy._data_path("proxy.mjs")), str(module), str(config)],
            capture_output=True, text=True, timeout=15)
        assert done.returncode == 3 and "request budget is invalid" in done.stderr, budget


# -- BA-1: completion proof before a reduced charge ---------------------------------------

def test_ba1_an_orderly_zero_event_shutdown_settles_to_zero(fake_srt):
    fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        pass
    assert proxy._end == {"event": "end", "requests": 0, "counted": 0, "budget": 1}
    proof = seat_egress_proxy.completion(proxy)
    assert proof.complete and proof.reason == "complete"
    assert seat_egress_proxy.charged_requests(proxy) == 0


def test_ba1_an_abrupt_exit_with_a_valid_zero_event_stream_is_charged_in_full(fake_srt):
    fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        os.kill(proxy.process.pid, signal.SIGKILL)
        proxy.process.wait(timeout=10)
    stream = seat_egress_proxy.proxy_stream(proxy)
    assert stream.final and not stream.protocol_error and not stream.outside_events
    proof = seat_egress_proxy.completion(proxy)
    assert not proof.complete and proof.reason == "exit_status" and proof.requests == 0
    assert seat_egress_proxy.charged_requests(proxy) == 1


def test_ba1_a_clean_exit_that_lost_the_marker_is_charged_in_full(fake_srt):
    """Exit status 0 and a stream that parses, but no marker: what a crash that drops
    buffered output at a record boundary looks like."""
    fake = fake_srt(mode="exit0")
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        fake.decide([_post()])
    assert proxy._returncode == 0 and not proxy._killed
    proof = seat_egress_proxy.completion(proxy)
    assert not proof.complete and proof.reason == "no_end_marker" and proof.counted == 1
    assert seat_egress_proxy.charged_requests(proxy) == 1


@pytest.mark.parametrize("partial", [
    '{"event": "request", "method": "PO',
    '{"event":"end","requests":0,',
    # Whole JSON, cut before the newline: still a truncated frame (review fix round 1).
    '{"event":"end","requests":0,"counted":0,"budget":1}',
    '{"event":"request","method":"POST","host":"cli-chat-proxy.grok.com",'
    '"path":"/v1/chat/completions","decision":"deny"}',
], ids=["mid-request-record", "mid-marker", "whole-marker-no-newline",
        "whole-request-no-newline"])
def test_ba1_a_stream_truncated_mid_record_is_charged_in_full(partial, fake_srt):
    fake = fake_srt()
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        fake.decide([], truncate=partial)
        proxy.process.wait(timeout=10)
    assert proxy._returncode == 0
    proof = seat_egress_proxy.completion(proxy)
    assert not proof.complete and proof.reason == "protocol_error"
    assert seat_egress_proxy.charged_requests(proxy) == 1


def test_ba1_the_start_proxy_shutdown_timeout_kill_path_is_charged_in_full(fake_srt,
                                                                           monkeypatch):
    monkeypatch.setattr(seat_egress_proxy, "_SHUTDOWN_TIMEOUT_S", 1.0)
    fake_srt(mode="hang")
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        pass
    assert proxy._killed and proxy._returncode == -signal.SIGKILL
    proof = seat_egress_proxy.completion(proxy)
    assert not proof.complete and proof.reason == "killed"
    assert seat_egress_proxy.charged_requests(proxy) == 1


def _budgeted_stand_in(budget: int = 1):
    proxy = seat_egress_proxy.SeatEgressProxy(
        socket="/fixture", proxy_url="http://srt:fixture@127.0.0.1:3128",
        ca_cert=Path("/fixture-ca"), ca_sha256="a" * 64, inner_sni_check=True,
        process=None, allowlist_id="grok-review", _rules=tuple(GROK_REVIEW.request_set),
        request_budget=budget)
    return proxy


def _finish(proxy, returncode: int = 0) -> None:
    proxy._eof = proxy._exited = True
    proxy._returncode = returncode


def _line(**item) -> str:
    return json.dumps(item) + "\n"


_ALLOWED_POST = dict(event="request", method="POST", host=INFERENCE_HOST, path=INFERENCE_PATH,
                     decision="allow")


@pytest.mark.parametrize("marker,reason", [
    (dict(event="end", requests=1, counted=1, budget=2), "complete"),
    (dict(event="end", requests=2, counted=1, budget=2), "count_mismatch"),
    (dict(event="end", requests=1, counted=0, budget=2), "count_mismatch"),
    # Not the four-field marker of this budget: an unknown line, so a protocol error.
    (dict(event="end", requests=1, counted=1, budget=3), "protocol_error"),
    (dict(event="end", requests=1, counted=1, budget=2, extra=0), "protocol_error"),
    (dict(event="end", requests=True, counted=1, budget=2), "protocol_error"),
], ids=["matching", "requests-mismatch", "counted-mismatch", "other-budget", "extra-key",
        "bool-count"])
def test_ba1_only_a_matching_marker_proves_completion(marker, reason):
    proxy = _budgeted_stand_in(budget=2)
    seat_egress_proxy._accept(proxy, _line(**_ALLOWED_POST))
    seat_egress_proxy._accept(proxy, _line(**marker))
    _finish(proxy)
    proof = seat_egress_proxy.completion(proxy)
    assert proof.reason == reason and proof.complete is (reason == "complete")
    # Complete: the one counted request; anything else: the whole budget.
    assert seat_egress_proxy.charged_requests(proxy) == (1 if reason == "complete" else 2)


def test_ba1_a_record_after_the_marker_is_a_protocol_error():
    proxy = _budgeted_stand_in()
    seat_egress_proxy._accept(proxy, _line(event="end", requests=0, counted=0, budget=1))
    seat_egress_proxy._accept(proxy, _line(**_ALLOWED_POST))
    _finish(proxy)
    assert seat_egress_proxy.completion(proxy).reason == "protocol_error"
    assert seat_egress_proxy.charged_requests(proxy) == 1


def test_ba1_an_unterminated_whole_marker_does_not_settle_the_charge():
    """The review's reproduction: exit 0, EOF, a marker whose JSON is intact and whose
    counts match, but no trailing newline. It is a truncated frame, so the full charge
    stays."""
    proxy = _budgeted_stand_in()
    seat_egress_proxy._accept(proxy, json.dumps(
        {"event": "end", "requests": 0, "counted": 0, "budget": 1}))
    _finish(proxy)
    assert proxy._end is None
    assert seat_egress_proxy.completion(proxy).reason == "protocol_error"
    assert seat_egress_proxy.charged_requests(proxy) == 1


def test_ba1_the_reader_hands_an_unterminated_final_frame_to_the_check():
    """Through ``_read_stream`` itself: the stdout iterator yields the unterminated last
    line at EOF, and the budgeted reader refuses it."""
    import io
    import types

    proxy = _budgeted_stand_in()
    terminated = json.dumps(_ALLOWED_POST) + "\n"
    marker = json.dumps({"event": "end", "requests": 1, "counted": 1, "budget": 1})
    proxy.process = types.SimpleNamespace(stdout=io.StringIO(terminated + marker))
    seat_egress_proxy._read_stream(proxy)
    proxy._exited = True
    proxy._returncode = 0
    assert seat_egress_proxy.completion(proxy).reason == "protocol_error"
    assert seat_egress_proxy.charged_requests(proxy) == 1
    # The same bytes with the newline settle to the one counted request.
    whole = _budgeted_stand_in()
    whole.process = types.SimpleNamespace(stdout=io.StringIO(terminated + marker + "\n"))
    seat_egress_proxy._read_stream(whole)
    whole._exited = True
    whole._returncode = 0
    assert seat_egress_proxy.completion(whole).complete
    assert seat_egress_proxy.charged_requests(whole) == 1 and whole._end is not None


def test_a_budgetless_reader_still_accepts_an_unterminated_final_event():
    """The framing rule is for budgeted streams only; a budgetless proxy's reader is
    unchanged."""
    proxy = _budgeted_stand_in()
    proxy.request_budget = None
    seat_egress_proxy._accept(proxy, json.dumps(_ALLOWED_POST))
    stream = seat_egress_proxy.proxy_stream(proxy)
    assert not stream.protocol_error and len(stream.outside_events) == 1


def test_ba1_a_marker_on_a_budgetless_stream_is_a_protocol_error():
    proxy = _budgeted_stand_in()
    proxy.request_budget = None
    seat_egress_proxy._accept(proxy, _line(event="end", requests=0, counted=0, budget=1))
    assert seat_egress_proxy.proxy_stream(proxy).protocol_error


@pytest.mark.parametrize("returncode,killed,final,reason", [
    (0, False, False, "not_final"),
    (0, True, True, "killed"),
    (-signal.SIGTERM, False, True, "exit_status"),
    (1, False, True, "exit_status"),
])
def test_ba1_without_a_clean_exit_the_marker_proves_nothing(returncode, killed, final, reason):
    proxy = _budgeted_stand_in()
    seat_egress_proxy._accept(proxy, _line(event="end", requests=0, counted=0, budget=1))
    proxy._eof = proxy._exited = final
    proxy._returncode = returncode
    proxy._killed = killed
    assert seat_egress_proxy.completion(proxy).reason == reason
    assert seat_egress_proxy.charged_requests(proxy) == 1


def test_the_completion_detail_says_what_the_stream_and_shutdown_showed():
    """CI fixes 2: a record of an incomplete observation says what was missing -- the
    marker, the last record read, the proxy's exit status, a kill, EOF -- metadata only, and
    the detail decides nothing."""
    proxy = _budgeted_stand_in()
    detail = seat_egress_proxy.completion_detail(proxy)
    assert set(detail) == seat_egress_proxy.COMPLETION_DETAIL_KEYS
    assert detail == {"marker": False, "last_record": None, "records": 0, "exit_status": None,
                      "killed": False, "stdout_eof": False, "exited": False,
                      "protocol_error": False}
    seat_egress_proxy._accept(proxy, _line(**_ALLOWED_POST))
    proxy._eof = proxy._exited = proxy._killed = True
    proxy._returncode = -signal.SIGKILL
    assert seat_egress_proxy.completion_detail(proxy) == {
        "marker": False, "last_record": "request", "records": 1, "exit_status": -9,
        "killed": True, "stdout_eof": True, "exited": True, "protocol_error": False}
    assert seat_egress_proxy.completion(proxy).reason == "killed"
    whole = _budgeted_stand_in()
    seat_egress_proxy._accept(whole, _line(**_ALLOWED_POST))
    seat_egress_proxy._accept(whole, _line(event="end", requests=1, counted=1, budget=1))
    _finish(whole)
    assert seat_egress_proxy.completion_detail(whole) == {
        "marker": True, "last_record": "end", "records": 2, "exit_status": 0, "killed": False,
        "stdout_eof": True, "exited": True, "protocol_error": False}
    assert seat_egress_proxy.completion(whole).complete


# --------------------------------------------------------------------------------------
# The real proxy over the pinned srt, against a loopback fixture upstream.
# --------------------------------------------------------------------------------------

_DIAL_HOOK = r"""
// Test-only: every TCP dial to port 443 from the proxy goes to the fixture upstream; a
// unix-socket dial is left alone (the pattern of test_seat_egress_allowlist_codex.py).
import net from 'node:net';
import tls from 'node:tls';
import { syncBuiltinESMExports } from 'node:module';
const port = Number(process.env.PHASE_LOOP_FIXTURE_UPSTREAM_PORT);
function redirect(options) {
  if (options !== null && typeof options === 'object' && options.path == null
      && options.socket == null && Number(options.port) === 443) {
    options.host = '127.0.0.1';
    options.port = port;
    delete options.lookup;
  }
}
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  redirect(Array.isArray(args[0]) ? args[0][0] : args[0]);
  return connect.apply(this, args);
};
const tlsConnect = tls.connect;
tls.connect = function (...args) {
  redirect(args[0]);
  return tlsConnect.apply(this, args);
};
syncBuiltinESMExports();
"""


def _layer_or_skip() -> None:
    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None:
        pytest.skip(f"the seat egress layer is not installed here ({reason})")
    for name in ("socat", "openssl"):
        if shutil.which(name, path="/usr/bin:/bin") is None:
            pytest.skip(f"{name} is unavailable")


def _openssl(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


class FixtureUpstream:
    """A TLS server on loopback that answers every request 200 and records what reached it
    (SNI, method, path, Host, and the complete body); it trusts nothing but its own CA."""

    def __init__(self, directory: Path, hosts: list[str]) -> None:
        directory.mkdir(mode=0o700)
        curve = ("-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes")
        _openssl("req", "-x509", *curve, "-keyout", "ca.key", "-out", "ca.crt", "-days", "2",
                 "-subj", "/CN=phase-loop fixture upstream CA",
                 "-addext", "basicConstraints=critical,CA:TRUE",
                 "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=directory)
        _openssl("req", "-new", *curve, "-keyout", "leaf.key", "-out", "leaf.csr",
                 "-subj", "/CN=phase-loop fixture upstream", cwd=directory)
        (directory / "leaf.ext").write_text(
            "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\n"
            "extendedKeyUsage=serverAuth\n"
            "subjectAltName=" + ",".join(f"DNS:{host}" for host in hosts) + "\n",
            encoding="ascii")
        _openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
                 "-CAcreateserial", "-out", "leaf.crt", "-days", "2", "-extfile", "leaf.ext",
                 cwd=directory)
        self.ca = directory / "ca.crt"
        self.connections = 0
        self.requests: list[tuple[str | None, str, str, str]] = []
        #: Each request's complete body, in arrival order: a Content-Length body, or a
        #: chunked entity decoded to its zero-size chunk. Read in full before the reply.
        self.bodies: list[bytes] = []
        self._lock = threading.Lock()
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(directory / "leaf.crt", directory / "leaf.key")
        self._context.set_alpn_protocols(["http/1.1"])
        self._context.sni_callback = lambda sock, name, _c: setattr(sock, "phase_loop_sni", name)
        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(0.2)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except (TimeoutError, OSError):
                continue
            with self._lock:
                self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(10)
        try:
            tls = self._context.wrap_socket(conn, server_side=True)
        except (OSError, ssl.SSLError):
            conn.close()
            return
        with tls:
            try:
                head = b""
                while b"\r\n\r\n" not in head and len(head) < 65536:
                    chunk = tls.recv(4096)
                    if not chunk:
                        return
                    head += chunk
                head, _, rest = head.partition(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                method, target, _version = (lines[0].split(" ") + ["", "", ""])[:3]
                headers = {name.strip().lower(): value.strip() for name, _, value in
                           (line.partition(":") for line in lines[1:])}
                with self._lock:
                    self.requests.append((getattr(tls, "phase_loop_sni", None), method, target,
                                          headers.get("host", "")))
                if "chunked" in headers.get("transfer-encoding", "").lower():
                    entity = self._read_chunked(tls, rest)
                    if entity is None:
                        return
                else:
                    length = int(headers.get("content-length", "0") or 0)
                    while len(rest) < length:
                        chunk = tls.recv(min(65536, length - len(rest)))
                        if not chunk:
                            return
                        rest += chunk
                    entity = rest[:length]
                with self._lock:
                    self.bodies.append(entity)
                body = f"fixture-upstream {method} {target}".encode()
                tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                            + f"Content-Length: {len(body)}\r\n".encode()
                            + b"Connection: close\r\n\r\n" + body)
            except (OSError, ssl.SSLError, ValueError):
                return

    @staticmethod
    def _read_chunked(tls, data: bytes) -> bytes | None:
        """The decoded entity of a chunked body, read through its zero-size chunk and the
        trailer section; ``None`` if the connection ends first."""
        buffer = data

        def fill(ready) -> bool:
            nonlocal buffer
            while not ready(buffer):
                chunk = tls.recv(65536)
                if not chunk:
                    return False
                buffer += chunk
            return True

        entity = b""
        while True:
            if not fill(lambda b: b"\r\n" in b):
                return None
            line, _, buffer = buffer.partition(b"\r\n")
            size = int(line.split(b";", 1)[0].strip(), 16)
            if size == 0:
                while True:
                    if not fill(lambda b: b"\r\n" in b):
                        return None
                    line, _, buffer = buffer.partition(b"\r\n")
                    if not line:
                        return entity
            if not fill(lambda b: len(b) >= size + 2):
                return None
            entity += buffer[:size]
            buffer = buffer[size + 2:]

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._server.close()


def _fixture_hosts() -> list[str]:
    hosts = {row["host"] for row in GROK_REVIEW.probe_rows}
    for document in _other_allowlists().values():
        hosts.update(rule["host"] for rule in document["allow"])
        hosts.update(host for host in document["measured_and_refused"] if "*" not in host)
    return sorted(hosts)


@pytest.fixture
def real_proxy_upstream(tmp_path, monkeypatch):
    """The real ``start_proxy`` over the pinned srt, with port-443 dials sent to a fixture
    upstream."""
    _layer_or_skip()
    upstream = FixtureUpstream(tmp_path / "upstream", _fixture_hosts())
    hook = tmp_path / "dial-hook.mjs"
    hook.write_text(_DIAL_HOOK, encoding="utf-8")
    real_env = seat_egress_proxy._proxy_env

    def proxy_env(node, home):
        values = real_env(node, home)
        values.update({
            "NODE_OPTIONS": f"--import={hook.as_uri()}",
            "NODE_EXTRA_CA_CERTS": str(upstream.ca),
            "PHASE_LOOP_FIXTURE_UPSTREAM_PORT": str(upstream.port),
        })
        return values

    monkeypatch.setattr(seat_egress_proxy, "_proxy_env", proxy_env)
    yield upstream
    upstream.close()


class ProxyDiagnostics:
    """Test-only evidence for a proxy that dies: its stderr, kept in a private file instead
    of the launcher's DEVNULL, and every exchange's ``OSError``. It changes no decision and
    no launch argument but ``stderr``."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.files: list[Path] = []
        self.errors: list[str] = []
        self.processes: list[subprocess.Popen] = []

    def stderr(self) -> str:
        return "".join(path.read_text(encoding="utf-8", errors="replace")
                       for path in self.files)

    def exchange(self, proxy, host: str, request: bytes) -> tuple[bytes, bytes]:
        try:
            return _exchange(proxy, host, request)
        except OSError as exc:  # a proxy that died before its reply
            self.errors.append(f"{type(exc).__name__}: {exc}")
            return b"", b""

    def detail(self, proxy) -> str:
        return (f"completion_detail={seat_egress_proxy.completion_detail(proxy)} "
                f"exchange_errors={self.errors} stderr_tail={self.stderr()[-4000:]!r}")


@pytest.fixture
def proxy_diagnostics(tmp_path, monkeypatch):
    """Keep each ``proxy.mjs`` child's stderr (``seat_egress_proxy.py`` discards it)."""
    directory = tmp_path / "proxy-stderr"
    directory.mkdir(mode=0o700)
    diagnostics = ProxyDiagnostics(directory)
    real = subprocess.Popen

    def popen(args, *rest, **kwargs):
        if (isinstance(args, (list, tuple)) and len(args) > 1
                and str(args[1]).endswith("proxy.mjs")
                and kwargs.get("stdin") is subprocess.PIPE
                and kwargs.get("start_new_session") is True
                and kwargs.get("stderr") in (subprocess.DEVNULL, subprocess.PIPE)):
            path = directory / f"proxy-{len(diagnostics.files)}.stderr"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            diagnostics.files.append(path)
            kwargs["stderr"] = fd
            try:
                process = real(args, *rest, **kwargs)
            finally:
                os.close(fd)
            diagnostics.processes.append(process)
            return process
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(seat_egress_proxy.subprocess, "Popen", popen)
    return diagnostics


def _authorization(proxy) -> bytes:
    token = urllib.parse.urlsplit(proxy.proxy_url).password
    assert token
    return base64.b64encode(f"srt:{token}".encode())


def _read_head(sock) -> bytes:
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 65536:
        chunk = sock.recv(4096)
        if not chunk:
            break
        head += chunk
    return head


def _exchange(proxy, host: str, request: bytes, *, cafile: str | None = "seat",
              timeout_s: float = 20.0) -> tuple[bytes, bytes]:
    """``(CONNECT status line, decrypted reply)`` for one request inside one tunnel.
    ``cafile="seat"`` trusts the seat egress CA; ``None`` trusts the system store only."""
    raw = socket.socket(socket.AF_UNIX)
    raw.settimeout(timeout_s)
    raw.connect(proxy.socket)
    raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n".encode()
                + b"Proxy-Authorization: Basic " + _authorization(proxy) + b"\r\n\r\n")
    status = _read_head(raw).split(b"\r\n", 1)[0]
    if not status.startswith(b"HTTP/1.1 200"):
        raw.close()
        return status, b""
    context = ssl.create_default_context(
        cafile=str(proxy.ca_cert) if cafile == "seat" else cafile)
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    with context.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(request)
        reply = b""
        try:
            while True:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                reply += chunk
        except (ssl.SSLError, OSError):
            pass
    return status, reply


def _http(method: str, host: str, path: str) -> bytes:
    return (f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nContent-Length: 0\r\n"
            "Connection: close\r\n\r\n").encode()


@pytest.mark.parametrize("row", GROK_REVIEW.probe_rows,
                         ids=lambda row: f"{row['decision']}-{row['method']}-{row['host']}")
def test_every_grok_review_probe_row_through_the_real_proxy(row, real_proxy_upstream):
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review") as proxy:
        assert proxy.allowlist_digest == GROK_REVIEW_ALLOWLIST_DIGEST
        if row["decision"] == "allow":
            status, reply = _exchange(proxy, row["host"],
                                      _http(row["method"], row["host"], row["path"]))
            assert status.startswith(b"HTTP/1.1 200"), status
            assert reply.startswith(b"HTTP/1.1 200"), reply[:120]
            assert upstream.requests == [(row["host"], row["method"], row["path"], row["host"])]
        else:
            status, reply = _exchange(proxy, row["host"], _http("GET", row["host"], "/"))
            assert status.startswith(b"HTTP/1.1 403"), status
            assert reply == b"" and upstream.connections == 0


def _other_seat_rows() -> list[tuple[str, str, str, str]]:
    rows = []
    for name, document in _other_allowlists().items():
        for rule in document["allow"]:
            path = rule["path"] if "path" in rule else rule["path_prefix"] + "phase-loop-probe"
            rows.append((name, rule["host"], rule["method"], path))
        rows.extend((name, host, "GET", "/") for host in document["measured_and_refused"]
                    if "*" not in host)
    return rows


@pytest.mark.parametrize("source,host,method,path", _other_seat_rows(), ids=str)
def test_a_host_listed_only_for_another_seat_is_refused(source, host, method, path,
                                                       real_proxy_upstream):
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review") as proxy:
        status, reply = _exchange(proxy, host, _http(method, host, path))
    assert status.startswith(b"HTTP/1.1 403"), (source, status)
    assert reply == b"" and upstream.connections == 0


def test_a_listed_host_on_an_unlisted_path_method_or_inner_host_is_refused(real_proxy_upstream):
    upstream = real_proxy_upstream
    requests = {
        "path": _http("POST", INFERENCE_HOST, "/v1/responses"),
        "settings": _http("GET", INFERENCE_HOST, "/v1/settings"),
        "method": _http("GET", INFERENCE_HOST, INFERENCE_PATH),
        "inner-host": _http("POST", "auth.x.ai", INFERENCE_PATH),
    }
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review") as proxy:
        replies = {label: _exchange(proxy, INFERENCE_HOST, request)
                   for label, request in requests.items()}
    for label, (status, reply) in replies.items():
        assert status.startswith(b"HTTP/1.1 200"), (label, status)
        assert reply.startswith(b"HTTP/1.1 403"), (label, reply[:120])
    assert upstream.requests == []


def test_a_client_that_does_not_trust_the_seat_ca_completes_no_request(real_proxy_upstream):
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        with pytest.raises(ssl.SSLCertVerificationError):
            _exchange(proxy, INFERENCE_HOST, _http("POST", INFERENCE_HOST, INFERENCE_PATH),
                      cafile=str(upstream.ca))
    assert upstream.requests == []
    assert [event.decision for event in seat_egress_proxy.proxy_stream(proxy).outside_events] == []
    assert seat_egress_proxy.charged_requests(proxy) == 0


def test_the_real_proxy_denies_counted_request_n_plus_one(real_proxy_upstream):
    upstream = real_proxy_upstream
    request = _http("POST", INFERENCE_HOST, INFERENCE_PATH)
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        first = _exchange(proxy, INFERENCE_HOST, request)
        second = _exchange(proxy, INFERENCE_HOST, request)
    assert first[1].startswith(b"HTTP/1.1 200"), first
    assert second[0].startswith(b"HTTP/1.1 200") and second[1].startswith(b"HTTP/1.1 403")
    assert [entry[1:3] for entry in upstream.requests] == [("POST", INFERENCE_PATH)]
    assert _events(proxy) == [("POST", INFERENCE_HOST, INFERENCE_PATH, "allow"),
                              ("POST", INFERENCE_HOST, INFERENCE_PATH, "deny")]
    assert proxy._end == {"event": "end", "requests": 2, "counted": 1, "budget": 1}
    assert seat_egress_proxy.charged_requests(proxy) == 1


def _body_post(host: str, path: str, body: bytes = b"{}", *, length: int | None = None) -> bytes:
    """A POST carrying a body, as every real client's inference request does."""
    return (f"POST {path} HTTP/1.1\r\nHost: {host}\r\n"
            f"Content-Length: {len(body) if length is None else length}\r\n"
            "Connection: close\r\n\r\n").encode() + body


def test_a_refused_request_with_a_body_leaves_the_real_proxy_running(real_proxy_upstream):
    """CI fixes 2: srt cancels a refused request's body while the client's bytes may still be
    in flight. On Node 22 that killed the proxy with an uncaught ERR_INVALID_STATE, so it
    wrote no end-of-stream marker and every rehearsal ended ``observation_incomplete``.
    Refusals of requests with bodies -- by the spent budget, the rules and the inner Host --
    each get their 403 from a proxy that keeps running, and the observation is complete."""
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=0) as proxy:
        replies = {label: _exchange(proxy, INFERENCE_HOST, _body_post(host, path))
                   for label, host, path in (("budget", INFERENCE_HOST, INFERENCE_PATH),
                                             ("rules", INFERENCE_HOST, "/v1/responses"),
                                             ("inner-host", "auth.x.ai", INFERENCE_PATH))}
    for label, (status, reply) in replies.items():
        assert status.startswith(b"HTTP/1.1 200"), (label, status)
        assert reply.startswith(b"HTTP/1.1 403"), (label, reply[:120])
    assert upstream.requests == []
    proof = seat_egress_proxy.completion(proxy)
    assert proof.complete, seat_egress_proxy.completion_detail(proxy)
    assert (proof.requests, proof.counted) == (3, 0)
    assert [event.cause for event in seat_egress_proxy.proxy_stream(proxy).outside_events] == [
        "budget", "rules", "inner_host"]


def test_a_refused_body_is_read_only_within_its_bounds(real_proxy_upstream):
    """The refused body is read to its end only within a byte and a time bound, never
    forwarded: a body that stalls is refused once the time bound passes, one over the byte
    bound is refused at once, and neither ends the proxy or the observation. Past the byte
    bound the client is still sending, so srt's reset of the connection may discard the 403
    before it arrives (Gate A, hosted): that refusal is proven by the observation, not the
    reply."""
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=0) as proxy:
        started = time.monotonic()
        stalled = _exchange(proxy, INFERENCE_HOST,
                            _body_post(INFERENCE_HOST, INFERENCE_PATH, length=100))
        stalled_s = time.monotonic() - started
        started = time.monotonic()
        oversized = _exchange(proxy, INFERENCE_HOST,
                              # Just past the 4 MiB bound.
                              _body_post(INFERENCE_HOST, INFERENCE_PATH,
                                         b"x" * ((4 << 20) + (64 << 10))))
        oversized_s = time.monotonic() - started
        after = _exchange(proxy, INFERENCE_HOST, _body_post(INFERENCE_HOST, INFERENCE_PATH))
    for label, (status, reply) in (("stalled", stalled), ("oversized", oversized),
                                   ("after", after)):
        assert status.startswith(b"HTTP/1.1 200"), (label, status)
        # Nothing but the refusal ever comes back; only the oversized one may be cut off.
        assert reply.startswith(b"HTTP/1.1 403") or (label == "oversized" and reply == b""), (
            label, reply[:120])
    assert 4.0 <= stalled_s < 15.0, stalled_s
    assert oversized_s < stalled_s, (oversized_s, stalled_s)
    assert upstream.requests == []
    proof = seat_egress_proxy.completion(proxy)
    assert proof.complete and proof.requests == 3, seat_egress_proxy.completion_detail(proxy)
    # Each of the three, the oversized one included, was the budget's own refusal.
    assert [(event.decision, event.cause)
            for event in seat_egress_proxy.proxy_stream(proxy).outside_events] == [
        ("deny", "budget")] * 3


#: The two ways a request declares a body: (header, the body as sent).
_DECLARED_BODIES = {
    "content-length": ("Content-Length: 2", b"{}"),
    "chunked": ("Transfer-Encoding: chunked", b"2\r\n{}\r\n0\r\n\r\n"),
}
CODEX_CHECK_PATH = "/backend-api/wham/accounts/check"


def _declaring(method: str, host: str, path: str, framing: str) -> bytes:
    """A request of any method that declares a complete body."""
    header, body = _DECLARED_BODIES[framing]
    return (f"{method} {path} HTTP/1.1\r\nHost: {host}\r\n{header}\r\n"
            "Connection: close\r\n\r\n").encode() + body


def _chunked_post(host: str, path: str, chunks: list[bytes]) -> bytes:
    return (f"POST {path} HTTP/1.1\r\nHost: {host}\r\nTransfer-Encoding: chunked\r\n"
            "Connection: close\r\n\r\n").encode() + b"".join(
        f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n" for chunk in chunks) + b"0\r\n\r\n"


def _cause_events(proxy) -> list[tuple[str, str, str | None, str, str | None]]:
    return [(event.method, event.host, event.path, event.decision, event.cause)
            for event in seat_egress_proxy.proxy_stream(proxy).outside_events]


# (allowlist, budget, tunnel host, [(method, inner Host, path, framing)], observed path, cause)
_BODY_REFUSALS = {
    "rules": ("grok-review", 1, INFERENCE_HOST,
              [(method, INFERENCE_HOST, "/v1/models", framing)
               for method in ("GET", "HEAD", "OPTIONS") for framing in _DECLARED_BODIES],
              "<other>", "rules"),
    "inner_host": ("grok-review", 1, INFERENCE_HOST,
                   [("GET", "auth.x.ai", "/v1/models", framing) for framing in _DECLARED_BODIES],
                   "<other>", "inner_host"),
    "budget": ("codex", 0, "chatgpt.com",
               [("GET", "chatgpt.com", CODEX_CHECK_PATH, "content-length")],
               CODEX_CHECK_PATH, "budget"),
}


@pytest.mark.parametrize("case", sorted(_BODY_REFUSALS))
def test_a_refused_request_that_declares_a_body_leaves_the_real_proxy_running(
        case, real_proxy_upstream, proxy_diagnostics):
    """agent-harness#2067: srt tees a GET, HEAD or OPTIONS that declares a body, hands the
    filter a bodyless request, and on refusal cancels the tee while the body's bytes are
    still arriving. On Node 22 the stream adapter's late ``enqueue`` then threw an uncaught
    ERR_INVALID_STATE and the proxy exited 1 with no end-of-stream marker. Each refusal --
    by the rules, the inner Host and the spent budget -- gets its 403 from a proxy that keeps
    running, nothing is forwarded, and the observation is complete."""
    upstream = real_proxy_upstream
    diagnostics = proxy_diagnostics
    allowlist_id, budget, tunnel, requests, path, cause = _BODY_REFUSALS[case]
    with seat_egress_proxy.start_proxy(allowlist_id=allowlist_id,
                                       request_budget=budget) as proxy:
        replies = [(request, diagnostics.exchange(proxy, tunnel, _declaring(*request)))
                   for request in requests]
    detail = diagnostics.detail(proxy)
    proof = seat_egress_proxy.completion(proxy)
    assert proof.complete and proxy._returncode == 0, detail
    assert "ERR_INVALID_STATE" not in diagnostics.stderr(), detail
    assert (proof.requests, proof.counted) == (len(requests), 0), detail
    for request, (status, reply) in replies:
        assert status.startswith(b"HTTP/1.1 200"), (request, status, detail)
        assert reply.startswith(b"HTTP/1.1 403"), (request, reply[:120], detail)
    assert upstream.requests == [], detail
    assert _cause_events(proxy) == [(method, tunnel, path, "deny", cause)
                                    for method, *_rest in requests], detail


def test_an_allowed_request_with_a_body_is_forwarded_unchanged(real_proxy_upstream,
                                                               proxy_diagnostics):
    """agent-harness#2067: an allowed request that declares a body reaches the upstream
    byte for byte -- a budgeted codex GET, and grok-review POSTs with an empty JSON body, a
    256 KiB body and a three-chunk body -- and each observation is complete."""
    upstream = real_proxy_upstream
    diagnostics = proxy_diagnostics
    with seat_egress_proxy.start_proxy(allowlist_id="codex", request_budget=1) as codex:
        check = diagnostics.exchange(codex, "chatgpt.com", _declaring(
            "GET", "chatgpt.com", CODEX_CHECK_PATH, "content-length"))
    detail = diagnostics.detail(codex)
    assert check[0].startswith(b"HTTP/1.1 200") and check[1].startswith(b"HTTP/1.1 200"), (
        check, detail)
    assert upstream.requests == [("chatgpt.com", "GET", CODEX_CHECK_PATH, "chatgpt.com")], detail
    assert upstream.bodies == [b"{}"], detail
    assert _cause_events(codex) == [
        ("GET", "chatgpt.com", CODEX_CHECK_PATH, "allow", "allowed")], detail
    proof = seat_egress_proxy.completion(codex)
    assert proof.complete and (proof.requests, proof.counted) == (1, 0), detail

    large = bytes(range(256)) * 1024  # 256 KiB
    chunks = [b"phase-loop ", b"chunked ", b"payload"]
    requests = [_body_post(INFERENCE_HOST, INFERENCE_PATH, b"{}"),
                _body_post(INFERENCE_HOST, INFERENCE_PATH, large),
                _chunked_post(INFERENCE_HOST, INFERENCE_PATH, chunks)]
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=3) as grok:
        replies = [diagnostics.exchange(grok, INFERENCE_HOST, request) for request in requests]
    detail = diagnostics.detail(grok)
    for status, reply in replies:
        assert status.startswith(b"HTTP/1.1 200"), (status, detail)
        assert reply.startswith(b"HTTP/1.1 200"), (reply[:120], detail)
    assert upstream.requests[1:] == [
        (INFERENCE_HOST, "POST", INFERENCE_PATH, INFERENCE_HOST)] * 3, detail
    assert upstream.bodies[1:] == [b"{}", large, b"".join(chunks)], detail
    assert _cause_events(grok) == [
        ("POST", INFERENCE_HOST, INFERENCE_PATH, "allow", "allowed")] * 3, detail
    proof = seat_egress_proxy.completion(grok)
    assert proof.complete and (proof.requests, proof.counted) == (3, 3), detail


def test_ba1_the_real_proxy_settles_an_orderly_zero_event_shutdown_to_zero(real_proxy_upstream):
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        pass
    assert seat_egress_proxy.completion(proxy).complete
    assert seat_egress_proxy.charged_requests(proxy) == 0


def test_ba1_the_real_proxy_killed_mid_launch_is_charged_in_full(real_proxy_upstream):
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1) as proxy:
        os.kill(proxy.process.pid, signal.SIGKILL)
        proxy.process.wait(timeout=10)
    assert not seat_egress_proxy.completion(proxy).complete
    assert seat_egress_proxy.charged_requests(proxy) == 1


def test_a_budgetless_real_proxy_writes_no_marker(real_proxy_upstream):
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review") as proxy:
        for _ in range(2):
            _exchange(proxy, INFERENCE_HOST, _http("POST", INFERENCE_HOST, INFERENCE_PATH))
    stream = seat_egress_proxy.proxy_stream(proxy)
    assert stream.final and not stream.protocol_error and proxy._end is None
    assert [event.decision for event in stream.outside_events] == ["allow", "allow"]
    assert len(real_proxy_upstream.requests) == 2


# --------------------------------------------------------------------------------------
# The proxy-only namespace of a launch-owner leg (contract section 5.2).
# --------------------------------------------------------------------------------------

_CHILD = r"""
import base64, json, socket, ssl, sys, urllib.parse
proxy_url, cafile, host, path, direct_ip, direct_port = sys.argv[1:7]
result = {}
parts = urllib.parse.urlsplit(proxy_url)
try:
    raw = socket.create_connection((parts.hostname, parts.port), 10)
    auth = base64.b64encode(f"{parts.username}:{parts.password}".encode()).decode()
    raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = raw.recv(4096)
        if not chunk:
            break
        head += chunk
    result["connect"] = head.split(b"\r\n", 1)[0].decode("latin-1")
    context = ssl.create_default_context(cafile=cafile)
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    with context.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Length: 0\r\n"
                    "Connection: close\r\n\r\n".encode())
        reply = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            reply += chunk
    result["proxied"] = reply.split(b"\r\n", 1)[0].decode("latin-1")
except OSError as exc:
    result["proxied"] = "error:" + type(exc).__name__
try:
    socket.create_connection((direct_ip, int(direct_port)), 3).close()
    result["direct"] = "connected"
except OSError as exc:
    result["direct"] = "refused:" + type(exc).__name__
print(json.dumps(result))
"""


def _namespace_or_skip() -> None:
    required = os.environ.get("PHASE_LOOP_REQUIRE_GROK_EGRESS_NS") == "1"
    if not sandbox_egress.egress_isolation_available():
        if required:
            pytest.fail("egress isolation is unavailable on a host that requires it")
        pytest.skip("egress isolation is unavailable here")
    for tool in ("newuidmap", "newgidmap", "socat", "python3"):
        if shutil.which(tool, path="/usr/bin:/bin") is None:
            if required:
                pytest.fail(f"{tool} is unavailable on a host that requires it")
            pytest.skip(f"{tool} is unavailable")


def _host_reachable_listener() -> socket.socket:
    """A listener on this host's first non-loopback IPv4 address: reachable from the host,
    so a refusal from inside the namespace is the namespace's doing."""
    address = next((value for value in sandbox_egress.host_addresses()
                    if ":" not in value and not value.startswith("127.")), None)
    if address is None:
        pytest.skip("this host has no non-loopback IPv4 address")
    listener = socket.create_server((address, 0))
    listener.settimeout(5)
    return listener


def test_the_grok_review_namespace_reaches_the_proxy_and_nothing_else(real_proxy_upstream):
    _namespace_or_skip()
    upstream = real_proxy_upstream
    listener = _host_reachable_listener()
    address, port = listener.getsockname()[:2]
    accepted: list[bool] = []
    try:
        socket.create_connection((address, port), 3).close()
        conn, _ = listener.accept()
        conn.close()
        accepted.append(True)
        with pi._grok_review_egress(timeout_s=300.0, request_budget=1) as (proxy, prefix):
            assert prefix and "--net" in prefix and "-t" in prefix
            done = subprocess.run(
                [*prefix, "/usr/bin/python3", "-I", "-S", "-c", _CHILD, proxy.proxy_url,
                 str(proxy.ca_cert), INFERENCE_HOST, INFERENCE_PATH, address, str(port)],
                capture_output=True, text=True, timeout=120)
    finally:
        listener.close()
    assert accepted == [True]
    assert done.returncode == 0, done.stderr[-400:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["connect"].startswith("HTTP/1.1 200"), result
    assert result["proxied"].startswith("HTTP/1.1 200"), result
    assert result["direct"].startswith("refused:"), result
    assert [entry[1:3] for entry in upstream.requests] == [("POST", INFERENCE_PATH)]
    assert seat_egress_proxy.charged_requests(proxy) == 1


_OWNED_CHILD = "#!/usr/bin/python3 -I\n" + _CHILD.replace(
    "proxy_url, cafile, host, path, direct_ip, direct_port = sys.argv[1:7]",
    "import os\nproxy_url, cafile = os.environ['HTTPS_PROXY'], os.environ['SSL_CERT_FILE']\n"
    "host, path, direct_ip, direct_port = sys.argv[1:5]")


def test_the_launch_owner_composition_serves_the_grok_review_namespace(real_proxy_upstream,
                                                                       tmp_path):
    """Contract section 5.2: the proxy-only namespace serves the launch-owner composition
    (``launch_owned`` with ``PROVIDER_REVIEW``) unchanged, so ``sandbox_egress`` is not
    extended. The same owned child reaches the proxy and fails a direct connection to a
    listener the host can reach. Binding the final check to the exact holder and proxy is
    lane L2c's (BA-3)."""
    _namespace_or_skip()
    if shutil.which("bwrap", path="/usr/bin:/bin") is None:
        pytest.skip("bwrap is unavailable")
    upstream = real_proxy_upstream
    provider = tmp_path / "stand-in-provider"
    provider.write_text(_OWNED_CHILD, encoding="utf-8")
    provider.chmod(0o700)
    work = tmp_path / "work"
    work.mkdir()
    listener = _host_reachable_listener()
    address, port = listener.getsockname()[:2]
    try:
        socket.create_connection((address, port), 3).close()
        listener.accept()[0].close()
        with pi._grok_review_egress(timeout_s=300.0, request_budget=1) as (proxy, prefix):
            token = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
            try:
                profile = pi.SeatProfile(
                    env={"PATH": "/usr/bin:/bin", "HOME": str(work),
                         seat_egress_proxy.SEAT_PROXY_ENV: proxy.proxy_url,
                         seat_egress_proxy.SEAT_CA_ENV: str(proxy.ca_cert)},
                    readonly_paths=(provider, proxy.ca_cert))
                try:
                    process = pi.launch_owned(
                        [str(provider), INFERENCE_HOST, INFERENCE_PATH, address, str(port)],
                        role=pi.SeatLaunchRole.PROVIDER_REVIEW, profile=profile, cwd=work,
                        env=dict(profile.env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        start_new_session=True)
                except sandbox_egress.SeatIdentityUnverified as exc:
                    if os.environ.get("PHASE_LOOP_REQUIRE_GROK_EGRESS_NS") == "1":
                        raise
                    pytest.skip(f"this host cannot own a seat ({exc})")
                try:
                    out, err = process.communicate(timeout=120)
                finally:
                    pi._terminate_process_group(process)
            finally:
                pi._EGRESS_LAUNCH_PREFIX.reset(token)
    finally:
        listener.close()
    assert process.returncode == 0, err[-600:]
    result = json.loads(out.decode().strip().splitlines()[-1])
    assert result["connect"].startswith("HTTP/1.1 200"), result
    assert result["proxied"].startswith("HTTP/1.1 200"), result
    assert result["direct"].startswith("refused:"), result
    assert [entry[1:3] for entry in upstream.requests] == [("POST", INFERENCE_PATH)]
    assert seat_egress_proxy.charged_requests(proxy) == 1


# --------------------------------------------------------------------------------------
# The grok seat_profile proxy projection (contract section 5.2).
# --------------------------------------------------------------------------------------

def _grok_home(tmp_path: Path) -> Path:
    home = tmp_path / "operator"
    (home / ".grok").mkdir(parents=True)
    (home / ".grok/auth.json").write_text(json.dumps(
        {"https://accounts.x.ai/sign-in": {"key": "synthetic-grok-bearer-token"}}))
    (home / ".grok/agent_id").write_text("synthetic-agent")
    return home


def _projection_proxy(tmp_path: Path, *, allowlist_id: str = "grok-review",
                      token: str = "synthetic-proxy-session-token"):
    der = b"phase-loop projection CA " + os.urandom(8)
    cert = tmp_path / "egress-ca.crt"
    cert.write_text(ssl.DER_cert_to_PEM_cert(der), encoding="ascii")
    return seat_egress_proxy.SeatEgressProxy(
        socket="/fixture.sock", proxy_url=f"http://srt:{token}@127.0.0.1:3128",
        ca_cert=cert, ca_sha256=hashlib.sha256(der).hexdigest(), inner_sni_check=True,
        process=None, allowlist_id=allowlist_id, allowlist_digest=GROK_REVIEW.content_digest)


_FD_FLAGS = {"--file", "--ro-bind-data"}


def _normalised(args) -> list[str]:
    out = list(args)
    for index, item in enumerate(out[:-1]):
        if item in _FD_FLAGS:
            out[index + 1] = "<fd>"
    return out


def _compose(tmp_path, home, **kwargs):
    with pi.seat_profile(harness="grok", executable="/usr/bin/true",
                         env={"HOME": str(home)}, cwd=tmp_path, **kwargs) as (dest, profile):
        args = list(profile.mount_args)
        ca = None
        for index, item in enumerate(args):
            if item == "--ro-bind-data":
                ca = (os.pread(int(args[index + 1]), 1_000_000, 0), args[index + 2])
        redacted = pi._redact_seat_credentials("REVIEW synthetic-proxy-session-token END")
        return dest, dict(profile.env), args, dict(profile.evidence), ca, redacted


def test_the_grok_profile_carries_the_proxy_projection_and_nothing_else(tmp_path):
    home = _grok_home(tmp_path)
    proxy = _projection_proxy(tmp_path)
    dest, plain_env, plain_args, plain_evidence, plain_ca, _ = _compose(tmp_path, home)
    dest2, env, args, evidence, ca, redacted = _compose(tmp_path, home, egress_proxy=proxy)
    destination = "/home/phase-loop-seat/.phase-loop-seat-egress-ca.pem"
    assert dest2 == dest and plain_ca is None
    assert {key: value for key, value in env.items() if key not in plain_env} == {
        "HTTPS_PROXY": proxy.proxy_url, "SSL_CERT_FILE": destination}
    assert {key: env[key] for key in plain_env} == plain_env
    assert "NO_PROXY" not in env and "no_proxy" not in env
    added = ["--perms", "0444", "--ro-bind-data", "<fd>", destination]
    normalised = _normalised(args)
    # Beside the proxy projection the profile carries the seat config of the contract's
    # erratum 8: exactly one read-only data mount of a descriptor, never a writable file.
    config = ["--perms", "0444", "--ro-bind-data", "<fd>",
              "/home/phase-loop-seat/" + grok_tool_surface.SEAT_CONFIG_RELATIVE]
    at = [i for i in range(len(normalised)) if normalised[i:i + 5] == config]
    assert len(at) == 1 and not [word for word in plain_args if "config.toml" in word]
    normalised = normalised[:at[0]] + normalised[at[0] + 5:]
    start = next(i for i in range(len(normalised)) if normalised[i:i + 5] == added)
    assert normalised[:start] + normalised[start + 5:] == _normalised(plain_args)
    assert ca == (proxy.ca_cert.read_bytes(), destination)
    assert not destination.startswith("/home/phase-loop-seat/.grok/")
    assert "synthetic-proxy-session-token" not in redacted
    assert {key: value for key, value in evidence.items() if key not in plain_evidence} == {
        "seat_egress_allowlist_id": "grok-review",
        "seat_egress_allowlist_digest": GROK_REVIEW.content_digest,
        "seat_egress_ca_sha256": proxy.ca_sha256}


@pytest.mark.parametrize("harness,allowlist_id", [
    ("codex", "grok-review"), ("grok", "gemini"), ("grok", "codex"),
])
def test_the_projection_is_only_the_grok_review_proxy_on_a_grok_profile(harness, allowlist_id,
                                                                        tmp_path):
    proxy = _projection_proxy(tmp_path, allowlist_id=allowlist_id)
    with pytest.raises(ValueError):
        with pi.seat_profile(harness=harness, executable="/usr/bin/true",
                             env={"HOME": str(_grok_home(tmp_path))}, cwd=tmp_path,
                             egress_proxy=proxy):
            pytest.fail("the projection was composed")


def test_the_projection_refuses_a_ca_that_changed_after_the_proxy_started(tmp_path):
    proxy = _projection_proxy(tmp_path)
    proxy.ca_cert.write_text(ssl.DER_cert_to_PEM_cert(b"another CA"), encoding="ascii")
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as caught:
        with pi.seat_profile(harness="grok", executable="/usr/bin/true",
                             env={"HOME": str(_grok_home(tmp_path))}, cwd=tmp_path,
                             egress_proxy=proxy):
            pytest.fail("a changed CA was projected")
    assert caught.value.code == seat_egress_proxy.INTEGRITY_CODE


def test_the_projection_names_the_variables_the_offline_confirmation_found():
    assert (seat_egress_proxy.SEAT_PROXY_ENV, seat_egress_proxy.SEAT_CA_ENV) == (
        "HTTPS_PROXY", "SSL_CERT_FILE")
    source = Path(pi.__file__).read_text(encoding="utf-8")
    assert re.search(r"def seat_profile\(.*egress_proxy=None\)", source, re.S)
