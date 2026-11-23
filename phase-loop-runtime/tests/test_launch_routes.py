"""LANEEXEC SL-7: routes, templates, registration and the ``launch`` settings (V3b).

Binding §7 E3-3 assigns these rows to SL-7: the C2 registration matrix at
``launch_routes.register_templates`` (never replaced by a test double), the pure L-S7 route
mapping as a closed function, template selection and argv expansion, naming the other
target's template, a ``template_sha256`` mismatch, the local template's LANEEXEC-v1-errata-1
form (E1, E2), and the ``launch`` settings decoder of §7 E3-2. The production refusals
through ``build_launch_service`` belong to SL-8.

Host files live in a private directory that :class:`HostFiles` maps every template path into.
Toolkit file bytes are fixtures, pinned by a test configuration (``ToolkitPin``) so each case
reaches its own check past the digest. The pinned manifest itself is carried, as an operator
configuration carries it, by the constant ``PINNED_MANIFEST``, whose digest is checked against
the packaged contract pin.
"""

from __future__ import annotations

import copy
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import rfc8785

from phase_loop_runtime import launch_routes, launch_snapshot
from phase_loop_runtime.launch_process_contract import Command, schema_bytes
from phase_loop_runtime.launch_routes import (
    PI_RUNNER_TEMPLATE_IDS,
    ROUTE_TABLE,
    HostFiles,
    TemplateRefused,
    ToolkitPin,
    check_toolkit_manifest,
    expand_argv,
    manifest_digest_argument,
    pi_policy_refusal,
    recheck_template,
    register_templates,
    relay_endpoint_argument,
    route_refusal,
    select_template,
    template_summaries,
)
from phase_loop_runtime.launch_settings import (
    DEFAULT_LAUNCH_SETTINGS,
    REMOTE_ROUTES,
    decode_launch_object,
    decode_launch_settings,
)
from phase_loop_runtime.sandbox_policy import PlacementClientConfig, PlacementConfigError

# -- inputs ---------------------------------------------------------------------------------

#: ``x-contract-pins.toolkit_pins``: the manifest bytes an agent-toolkit operator
#: configuration carries (agent-toolkit ``harnesses/pi/contracts/pins.json`` at the pinned
#: ``toolkit_commit``). Their digest is checked against the packaged pin below.
PINNED_MANIFEST = (
    '{"files":[{"path":"docs/remote-placement.md","role":"remote_placement_reference","sha256'
    '":"8a9ec51604ea64609d88567b7e0ab6c12e3b5b4b2a53f8970ce4452cbde7a2cd"},{"path":"harnesses'
    '/pi/sandbox/bwrap.mjs","role":"remote_inner_closure:harnesses/pi/sandbox/bwrap.mjs","sha'
    '256":"de5ae6dc1da9ebad9565cebb5a32a2cbd3ccb2521b42cfbec720f52824690568"},{"path":"harnes'
    'ses/pi/sandbox/cred-proxy.mjs","role":"cred_proxy_reference","sha256":"dc84548328c38345f'
    '0d190e89fa1bb5c2ac1d438273c49408b172796d6844c30"},{"path":"harnesses/pi/sandbox/engines/'
    'loopback.mjs","role":"toolkit_loopback_engine","sha256":"3ce769c1d3a89190b667d1055e88112'
    'e46dfc8c26fc1a3721b1e3ed8ce335829"},{"path":"harnesses/pi/sandbox/engines/openshell-cli.'
    'mjs","role":"toolkit_openshell_cli","sha256":"42f5e18d7cc403f02abcd47f695e7a8a2fb123e130'
    'c8ffa4b27ca1be506473ca"},{"path":"harnesses/pi/sandbox/engines/openshell-image.mjs","rol'
    'e":"toolkit_openshell_image","sha256":"867ead621b8e9403b183661e848c606a48781651898cbbb02'
    '2527dffdc89d9a0"},{"path":"harnesses/pi/sandbox/engines/openshell-landlock.mjs","role":"'
    'toolkit_openshell_layout","sha256":"25a56a4840e92e7f9604d05c3ed1c4a70699ff9a651875892f6c'
    '25ac63ccf464"},{"path":"harnesses/pi/sandbox/engines/openshell.mjs","role":"toolkit_open'
    'shell_engine","sha256":"4b960f0e41652ebbf86c9bbb1b4559505c440ff1d4e0ddf6cf3c23e92a682210'
    '"},{"path":"harnesses/pi/sandbox/exec-clean.mjs","role":"toolkit_exec_clean","sha256":"7'
    '1e2a46c0e30579d6d389303e5f8ae905f5a34e9d004d9c6b09f512be744f302"},{"path":"harnesses/pi/'
    'sandbox/git-adapter.mjs","role":"remote_inner_closure:harnesses/pi/sandbox/git-adapter.m'
    'js","sha256":"30dc246351ccd8270c543e3fd9f869cff04acd76b9713c7c76b1e4893ef62ed5"},{"path"'
    ':"harnesses/pi/sandbox/guest-bin/git","role":"remote_inner_closure:harnesses/pi/sandbox/'
    'guest-bin/git","sha256":"6208a100d8e3dd952d1709a6e7dc239c1b32e2cb85f21ec1f32cc39c2cbbb82'
    '4"},{"path":"harnesses/pi/sandbox/image/Dockerfile","role":"toolkit_runner_image_recipe"'
    ',"sha256":"17756aabcb7bb7767c63ae94c7a944203b83fd802a3e8573d6af087d1d2b5ec0"},{"path":"h'
    'arnesses/pi/sandbox/image/build-runner-image.mjs","role":"toolkit_runner_image_build","s'
    'ha256":"8cff09b73ba9de1c370edef8db1738a14a24626b53e860e0837ba0a7a251ed97"},{"path":"harn'
    'esses/pi/sandbox/landlock/Dockerfile","role":"toolkit_landlock_helper_recipe","sha256":"'
    '360ac287479fcb42f7d8c935eee148ce82bb4b94509784e6bcac9ecf2ef85f27"},{"path":"harnesses/pi'
    '/sandbox/landlock/manifest.mjs","role":"toolkit_landlock_manifest","sha256":"84a1a1d743e'
    'f9ed374805b7262d49b58597a838a9a4218a9e4e0dafff3612d39"},{"path":"harnesses/pi/sandbox/li'
    'nk.mjs","role":"toolkit_link","sha256":"0375816abe60f90b675ec9d8b889a64534750f294d3ff128'
    '7332fbf274841f5d"},{"path":"harnesses/pi/sandbox/plan.mjs","role":"remote_inner_closure:'
    'harnesses/pi/sandbox/plan.mjs","sha256":"1a1aa11494f5e477fae8755a2e59b88fd4b73f6f2c065a9'
    '413effc5d6c5b27e3"},{"path":"harnesses/pi/sandbox/policy.json","role":"snapshot_limits_r'
    'eference","sha256":"6bcea95104978fda3a2790e8f31bc94715b74f80440a49d8e93fca4f43107b8f"},{'
    '"path":"harnesses/pi/sandbox/policy.mjs","role":"remote_inner_closure:harnesses/pi/sandb'
    'ox/policy.mjs","sha256":"3b6e6cd3e0678271b7f70ac9e146c8e3202193794a13ee56e848067910fbd37'
    'b"},{"path":"harnesses/pi/sandbox/relay.mjs","role":"remote_inner_closure:harnesses/pi/s'
    'andbox/relay.mjs","sha256":"c8dab61e4dd1ea9fea76d311ae6b275001ffa0fa9e6a58a25f8631cf7a7b'
    'd525"},{"path":"harnesses/pi/sandbox/remote-inner.mjs","role":"toolkit_remote_inner","sh'
    'a256":"d2e5b38bd2594e30f89f6dcca882a596d98848a1f12f97552fa4dc379356c805"},{"path":"harne'
    'sses/pi/sandbox/remote-launch.mjs","role":"toolkit_remote_launch","sha256":"130bc5404519'
    'a87b0fd0c63ab8514b54d096f1b71e042e2e998e435aca4e6f0a"},{"path":"harnesses/pi/sandbox/sna'
    'pshot.mjs","role":"remote_inner_closure:harnesses/pi/sandbox/snapshot.mjs","sha256":"993'
    'a2dfcb3c583f646ccdce041fb90599cfc942b918a73ad430c7ec8fad722e1"},{"path":"harnesses/pi/sa'
    'ndbox/writer-bundle.mjs","role":"remote_inner_closure:harnesses/pi/sandbox/writer-bundle'
    '.mjs","sha256":"a17ffab8c741b34a15094e2f162e9861367a0519dd2298d618171b7473ee9475"},{"pat'
    'h":"harnesses/pi/sandbox/writer-consumer.mjs","role":"remote_inner_closure:harnesses/pi/'
    'sandbox/writer-consumer.mjs","sha256":"014b9149f08fa131458d88dea94da281c76571f7e3d3cfd6d'
    '55ccbac07bc595d"},{"path":"harnesses/pi/sandbox/writer-snapshot.mjs","role":"writer_snap'
    'shot_reference","sha256":"d4d9f1b23fd359b83457adfe1c0df1b451f115a5435dcda79573492e25fe51'
    'ab"},{"path":"harnesses/pi/sandbox/writer-transfer.mjs","role":"remote_inner_closure:har'
    'nesses/pi/sandbox/writer-transfer.mjs","sha256":"129ea5e55e879aa3a376a6212d1fb44edd53f8b'
    'b44d9adf034efd289e73127be"}],"schema":"toolkit_pins.v1","toolkit_commit":"cd9174e326140d'
    'c27471ff3bfc8abdd056f6e7bd"}'
)
#: LANEEXEC-v1-errata-1 E2(ii): the pre-erratum local ``template_sha256`` (an input).
PRE_ERRATUM_TEMPLATE_SHA256 = "0905bff04c6976d8eaf096579e2398ada265fcc2980c024919b2527c20257449"

#: The local template argv in its erratum form, as frozen (literal tokens and slots).
FROZEN_LOCAL_ARGV = [
    "/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session",
    "--cap-drop", "ALL", "--clearenv", "--proc", "/proc", "--dev", "/dev",
    "--tmpfs", "/tmp",
    "--ro-bind", "/etc", "/etc", "--ro-bind", "/lib", "/lib", "--ro-bind", "/usr", "/usr",
    "--tmpfs", "/var/log", "--remount-ro", "/var/log",
    "<host symlink entries>", "<ro_trees binds>",
    "--bind", {"slot": "tree"}, {"slot": "tree_dest"},
    "--bind", {"slot": "scratch"}, {"slot": "scratch"},
    "--chdir", {"slot": "tree_dest"},
    "--", "<node>", "<remote_inner>",
]
FROZEN_OPENSHELL_ARGV = [
    "/usr/libexec/agent-toolkit/landlock-exec", "--policy", {"slot": "manifest"}, "--",
    "<node>", "<remote_inner>", "--listen", {"slot": "relay_endpoint"},
    "--landlock", {"slot": "manifest"}, {"slot": "manifest_digest"},
]
ERRATUM_FORM = ["--tmpfs", "/var/log", "--remount-ro", "/var/log"]
PREVIOUS_FORM = ["--ro-bind", "/var/log", "/var/log"]
USR_BIND = ["--ro-bind", "/usr", "/usr"]
BIND_FLAGS = {"--bind", "--ro-bind", "--bind-try", "--ro-bind-try", "--dev-bind", "--dev-bind-try"}

LOCAL_IMAGE = "sha256:" + "a" * 64
OPENSHELL_IMAGE = "sha256:" + "b" * 64
HELPER = "/usr/libexec/agent-toolkit/landlock-exec"
HELPER_SHA = hashlib.sha256(b"fixture landlock-exec").hexdigest()
IMAGE_NODE = "/opt/node/bin/node"
IMAGE_NODE_SHA = hashlib.sha256(b"fixture image node").hexdigest()
IMAGE_TOOLKIT = "/opt/agent-toolkit"
IMAGE_LINK = "/opt/agent-toolkit/pi-agent/npm"
FIXTURE_COMMIT = "f" * 40
REMOTE_INNER = "harnesses/pi/sandbox/remote-inner.mjs"

CONTRACT = json.loads(schema_bytes())
CONTRACT_PIN = ToolkitPin.from_contract()
PINNED_DOC = json.loads(PINNED_MANIFEST)
CLOSURE_NAMED = {"toolkit_remote_inner", "toolkit_link", "toolkit_exec_clean",
                 "toolkit_landlock_manifest", "snapshot_limits_reference", "writer_snapshot_reference"}
CLOSURE_PATHS = sorted(e["path"] for e in PINNED_DOC["files"]
                       if e["role"] in CLOSURE_NAMED or e["role"].startswith("remote_inner_closure:"))
REQUIRED_ROLES = sorted(CONTRACT_PIN.roles)


def jcs(value) -> bytes:
    return rfc8785.dumps(value)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_bytes(path: str) -> bytes:
    return b"fixture toolkit file " + path.encode()


def fixture_manifest(files=None) -> dict:
    """A manifest with the pinned paths and roles and fixture bytes, for a fixture pin."""
    rows = files if files is not None else [
        {"path": e["path"], "role": e["role"], "sha256": sha(fixture_bytes(e["path"]))}
        for e in PINNED_DOC["files"]]
    return {"files": rows, "schema": "toolkit_pins.v1", "toolkit_commit": FIXTURE_COMMIT}


def pin_for(raw: bytes) -> ToolkitPin:
    """A test configuration pinning exactly these manifest bytes."""
    return ToolkitPin(FIXTURE_COMMIT, sha(raw), len(raw), CONTRACT_PIN.roles)


# -- the fixture host -----------------------------------------------------------------------

class Host:
    """A private host root: bwrap, a node release, the toolkit tree and an npm tree."""

    def __init__(self, base: Path, *, digests=None):
        self.root = base / "host"
        self.files = HostFiles(str(self.root))
        self.write("usr/bin/bwrap", b"fixture bwrap")
        self.write("opt/node/bin/node", b"fixture node", mode=0o755)
        self.write("opt/npm/lib/pi/index.js", b"fixture pi")
        (self.root / "usr/lib64").mkdir(parents=True)
        os.symlink("usr/bin", self.root / "bin")
        os.symlink("usr/lib64", self.root / "lib64")
        os.symlink("/opt/elsewhere", self.root / "sbin")  # not into /usr: no entry
        for path in CLOSURE_PATHS:
            self.write(f"opt/toolkit/{path}", (digests or {}).get(path, fixture_bytes(path)))

    def write(self, rel: str, data: bytes, mode: int = 0o644) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)

    def tree(self, path: str) -> str:
        rows = self.files.tree_rows(path)
        assert rows is not None
        return sha(jcs(rows))

    def file_sha(self, path: str) -> str:
        digest = self.files.sha256(path)
        assert digest is not None
        return digest


def expand_placeholders(argv, fills):
    out = []
    for token in argv:
        if isinstance(token, str) and token in fills:
            out.extend(fills[token])
        else:
            out.append(copy.deepcopy(token))
    return out


def local_record(host: Host, manifest: dict, *, argv=None, **changes) -> dict:
    remote_inner_sha = next(e["sha256"] for e in manifest["files"] if e["role"] == "toolkit_remote_inner")
    trees = [{"path": "/opt/node", "tree_sha256": host.tree("/opt/node")},
             {"path": "/opt/toolkit", "tree_sha256": host.tree("/opt/toolkit")},
             {"path": "/opt/npm", "tree_sha256": host.tree("/opt/npm")}]
    fills = {
        "<host symlink entries>": ["--symlink", "usr/bin", "/bin", "--symlink", "usr/lib64", "/lib64"],
        "<ro_trees binds>": [x for t in trees for x in ("--ro-bind", t["path"], t["path"])],
        "<node>": ["/opt/node/bin/node"],
        "<remote_inner>": [f"/opt/toolkit/{REMOTE_INNER}"],
    }
    record = {
        "template_id": "pi-runner.local.v1", "workload": "pi-runner", "target_kind": "local",
        "policy_vectors": ["minimal-without-app"], "action": "execution", "result_kinds": ["none"],
        "image_digest": LOCAL_IMAGE,
        "argv": argv if argv is not None else expand_placeholders(FROZEN_LOCAL_ARGV, fills),
        "executable_chain": [
            {"role": "wrapper", "locator_kind": "declared", "locator": "/usr/bin/bwrap",
             "sha256": host.file_sha("/usr/bin/bwrap")},
            {"role": "wrapper", "locator_kind": "declared", "locator": "/opt/node/bin/node",
             "sha256": host.file_sha("/opt/node/bin/node")},
            {"role": "worker", "locator_kind": "declared", "locator": f"/opt/toolkit/{REMOTE_INNER}",
             "sha256": remote_inner_sha},
        ],
        "ro_trees": trees, "image_links": ["/opt/npm/lib"],
        "link": {"mode": "stdio", "guest_port": None},
        "environment_policy": "constructed and empty (--clearenv)", "references": [],
        "max_timeout_seconds": 3600, "result_schema_id": None,
    }
    record.update(changes)
    return record


def openshell_record(manifest: dict, **changes) -> dict:
    remote_inner_sha = next(e["sha256"] for e in manifest["files"] if e["role"] == "toolkit_remote_inner")
    worker = f"{IMAGE_TOOLKIT}/{REMOTE_INNER}"
    record = {
        "template_id": "pi-runner.openshell.v1", "workload": "pi-runner", "target_kind": "openshell",
        "policy_vectors": ["full-remote-pi-runner"], "action": "execution", "result_kinds": ["none"],
        "image_digest": OPENSHELL_IMAGE,
        "argv": expand_placeholders(FROZEN_OPENSHELL_ARGV, {"<node>": [IMAGE_NODE], "<remote_inner>": [worker]}),
        "executable_chain": [
            {"role": "wrapper", "locator_kind": "declared", "locator": HELPER, "sha256": HELPER_SHA},
            {"role": "wrapper", "locator_kind": "declared", "locator": IMAGE_NODE, "sha256": IMAGE_NODE_SHA},
            {"role": "worker", "locator_kind": "declared", "locator": worker, "sha256": remote_inner_sha},
        ],
        "ro_trees": [], "image_links": [IMAGE_LINK],
        "link": {"mode": "listen", "guest_port": 17690},
        "environment_policy": "constructed and empty", "references": ["the manifest, role configuration"],
        "max_timeout_seconds": 3600, "result_schema_id": None,
    }
    record.update(changes)
    return record


def runtime_record(manifest: dict, *, files=None) -> dict:
    digests = {e["path"]: e["sha256"] for e in manifest["files"]}
    return {
        "version": 3,
        "helper": {"path": HELPER, "version": 1, "sha256": HELPER_SHA},
        "node": {"path": IMAGE_NODE, "sha256": IMAGE_NODE_SHA},
        "launcher": {"path": IMAGE_TOOLKIT,
                     "files": files if files is not None else {
                         p: digests.get(p, sha(fixture_bytes(p))) for p in CLOSURE_PATHS}},
        "trees": ["/opt/agent-toolkit/harnesses/pi/sandbox", IMAGE_LINK, "/opt/node"],
    }


def toolkit_settings(records, manifest_raw: bytes, **launch):
    try:
        manifest = json.loads(manifest_raw)
        manifest["files"][0]["path"]
    except (ValueError, KeyError, TypeError, IndexError):
        manifest = fixture_manifest()
    del manifest
    images = [{"image_digest": LOCAL_IMAGE, "workload": "pi-runner", "target_kind": "local"},
              {"image_digest": OPENSHELL_IMAGE, "workload": "pi-runner", "target_kind": "openshell"}]
    value = {"templates": [r if isinstance(r, str) else jcs(r).decode() for r in records],
             "toolkit_pins": manifest_raw.decode(), "images": images}
    value.update(launch)
    return decode_launch_object(value, client="agent-toolkit")


def fixture_runtime(manifest_raw: bytes, runtime=None):
    """The test-only image runtime seam: the normalized record for the openshell image."""
    try:
        manifest = json.loads(manifest_raw)
        manifest["files"][0]["path"]
    except (ValueError, KeyError, TypeError, IndexError):
        manifest = fixture_manifest()
    record = runtime if runtime is not None else runtime_record(manifest)

    def supply(image):
        return record if image.image_digest == OPENSHELL_IMAGE else None
    return supply


@pytest.fixture(autouse=True)
def no_effects(monkeypatch):
    """Registration, routes and selection start nothing and read no snapshot or seed."""
    calls = []

    def trip(name):
        def _trip(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"unexpected effect: {name}")
        return _trip

    monkeypatch.setattr(subprocess, "Popen", trip("Popen"))
    monkeypatch.setattr(os, "fork", trip("fork"))
    monkeypatch.setattr(os, "posix_spawn", trip("posix_spawn"))
    monkeypatch.setattr(launch_snapshot, "build_snapshot", trip("build_snapshot"))
    monkeypatch.setattr(launch_snapshot, "build_seed", trip("build_seed"))
    yield calls
    assert calls == []


@pytest.fixture
def host(tmp_path):
    return Host(tmp_path)


@pytest.fixture
def fixture_raw():
    return jcs(fixture_manifest())


def register(records, raw, host, *, pin="fixture", runtime=None, fixture=True, **kwargs):
    settings = toolkit_settings(records, raw, **kwargs)
    return register_templates(settings, host=host.files, pin=pin_for(raw) if pin == "fixture" else pin,
                              fixture_image_runtime=fixture_runtime(raw, runtime) if fixture else None), settings


def refused_all(registry, reason):
    assert dict(registry.templates) == {}
    assert set(registry.refused.values()) == {reason}, registry.refused


# -- launch settings (binding §7 E3-2) ------------------------------------------------------

def test_absent_launch_object_is_the_shipped_defaults():
    for client in ("agent-harness", "agent-toolkit"):
        settings = decode_launch_object(None, client=client)
        assert settings == DEFAULT_LAUNCH_SETTINGS[client]
        assert settings.local_pi_runner_launcher == "toolkit_interim"
        assert settings.lane_placement == "disabled"
        assert settings.routes_enabled == frozenset()
        assert settings.templates == () and settings.images == () and settings.toolkit_pins is None
        assert settings.seed_root is None and settings.local_link_root is None
        assert settings.review_runner_image is None
        assert (settings.return_max_bytes, settings.snapshot_budget_s, settings.return_budget_s) == (67108864, 300, 120)
        assert settings.effective_snapshot_limits("pi-runner", "local") == {
            "max_bytes": 536870912, "max_entries": 200000, "untracked_blob_max_bytes": 67108864}
        assert settings.effective_seed_limits("pi-runner", "openshell") == {
            "max_entries": 4096, "entry_max_bytes": 16777216, "max_bytes": 67108864, "manifest_max_bytes": 1048576}


def test_settings_are_read_from_the_captured_client_configuration():
    launch = {"lane_placement": "enabled", "return_max_bytes": 1024}
    config = PlacementClientConfig("agent-harness", {}, {}, (), {}, launch, {}, "0" * 64, b"{}", "0" * 64)
    settings = decode_launch_settings(config)
    assert settings.client == "agent-harness"
    assert settings.lane_placement == "enabled" and settings.return_max_bytes == 1024
    empty = PlacementClientConfig("agent-toolkit", {}, {}, (), {}, None, {}, "0" * 64, b"{}", "0" * 64)
    assert decode_launch_settings(empty) == DEFAULT_LAUNCH_SETTINGS["agent-toolkit"]


def test_operators_may_only_lower_limits_per_workload_or_target():
    settings = decode_launch_object({
        "snapshot_limits": {"max_bytes": 1000, "by_workload": {"pi-runner": {"max_entries": 10}},
                            "by_target_kind": {"openshell": {"max_bytes": 10, "untracked_blob_max_bytes": 5}}},
        "seed_limits": {"max_entries": 100, "by_target_kind": {"local": {"manifest_max_bytes": 64}}},
        "snapshot_budget_s": 60, "return_budget_s": 30,
    }, client="agent-toolkit")
    assert settings.effective_snapshot_limits("pi-runner", "local") == {
        "max_bytes": 1000, "max_entries": 10, "untracked_blob_max_bytes": 67108864}
    assert settings.effective_snapshot_limits("pi-runner", "openshell") == {
        "max_bytes": 10, "max_entries": 10, "untracked_blob_max_bytes": 5}
    assert settings.effective_snapshot_limits("leg", "local")["max_entries"] == 200000
    assert settings.effective_seed_limits("pi-runner", "local") == {
        "max_entries": 100, "entry_max_bytes": 16777216, "max_bytes": 67108864, "manifest_max_bytes": 64}
    assert (settings.snapshot_budget_s, settings.return_budget_s) == (60, 30)


@pytest.mark.parametrize("client,launch", [
    ("agent-toolkit", {"unknown": 1}),
    ("agent-toolkit", {"templates": "x"}),
    ("agent-toolkit", {"templates": [1]}),
    ("agent-toolkit", {"templates": [""]}),
    ("agent-toolkit", {"toolkit_pins": {}}),
    ("agent-toolkit", {"snapshot_limits": {"max_bytes": 536870913}}),
    ("agent-toolkit", {"snapshot_limits": {"max_bytes": -1}}),
    ("agent-toolkit", {"snapshot_limits": {"max_bytes": True}}),
    ("agent-toolkit", {"snapshot_limits": {"max_files": 1}}),
    ("agent-toolkit", {"snapshot_limits": {"by_workload": {"other": {}}}}),
    ("agent-toolkit", {"snapshot_limits": {"by_target_kind": {"local": {"max_entries": 200001}}}}),
    ("agent-toolkit", {"seed_limits": {"max_entries": 4097}}),
    ("agent-toolkit", {"seed_limits": {"manifest_max_bytes": 1048577}}),
    ("agent-toolkit", {"seed_root": "relative"}),
    ("agent-toolkit", {"seed_root": "/a/../b"}),
    ("agent-toolkit", {"local_link_root": 3}),
    ("agent-toolkit", {"local_pi_runner_launcher": "enabled"}),
    ("agent-toolkit", {"lane_placement": True}),
    ("agent-toolkit", {"routes_enabled": ["leg/local"]}),
    ("agent-toolkit", {"routes_enabled": ["implementation/local"]}),
    ("agent-toolkit", {"routes_enabled": ["pi-runner/openshell", "pi-runner/openshell"]}),
    ("agent-toolkit", {"return_max_bytes": 67108865}),
    ("agent-toolkit", {"snapshot_budget_s": 301}),
    ("agent-toolkit", {"snapshot_budget_s": 0}),
    ("agent-toolkit", {"return_budget_s": 121}),
    ("agent-toolkit", {"return_budget_s": 1.5}),
    ("agent-toolkit", {"images": [{"image_digest": LOCAL_IMAGE, "workload": "pi-runner",
                                   "target_kind": "local", "runtime": None}]}),
    ("agent-toolkit", {"images": [{"image_digest": "sha256:" + "A" * 64, "workload": "pi-runner",
                                   "target_kind": "local"}]}),
    ("agent-toolkit", {"images": [{"image_digest": LOCAL_IMAGE, "workload": "pi-runner",
                                   "target_kind": "local"}] * 2}),
    ("agent-toolkit", {"images": [{"image_digest": OPENSHELL_IMAGE, "workload": "pi-runner",
                                   "target_kind": "openshell", "runtime": {"version": 3}}]}),
    ("agent-toolkit", {"review_runner_image": {"image": "x"}}),
    ("agent-harness", {"toolkit_pins": "{}"}),
    ("agent-harness", {"seed_root": "/srv/seeds"}),
    ("agent-harness", {"local_pi_runner_launcher": "laneexec"}),
    ("agent-harness", {"local_link_root": "/run/link"}),
])
def test_an_invalid_launch_object_makes_the_configuration_invalid(client, launch):
    with pytest.raises(PlacementConfigError) as raised:
        decode_launch_object(launch, client=client)
    assert str(raised.value) == "placement_config_invalid"
    assert raised.value.__cause__ is None or raised.value.__suppress_context__


def test_the_review_runner_image_record_decodes_strictly():
    record = {"image": "registry.example/review-runner@sha256:" + "c" * 64, "platform": "linux/amd64",
              "config_digest": "sha256:" + "d" * 64, "source_commit": "e" * 40,
              "containerfile_sha256": "1" * 64, "helper": {"path": HELPER, "sha256": "2" * 64}}
    image = decode_launch_object({"review_runner_image": record}, client="agent-harness").review_runner_image
    assert (image.helper_path, image.helper_sha256) == (HELPER, "2" * 64)
    for change in ({"platform": "linux/arm64"}, {"image": "registry.example/review-runner:latest"},
                   {"helper": {"path": "/bin/sh", "sha256": "2" * 64}}, {"extra": 1}):
        with pytest.raises(PlacementConfigError):
            decode_launch_object({"review_runner_image": {**record, **change}}, client="agent-harness")


def test_no_input_value_reaches_a_settings_error():
    secret = "/sentinel-secret-value"
    with pytest.raises(PlacementConfigError) as raised:
        decode_launch_object({"seed_root": secret + "/../x"}, client="agent-toolkit")
    assert secret not in str(raised.value) and secret not in repr(raised.value.args)


# -- the L-S7 route mapping -----------------------------------------------------------------

DEFAULTS_TK = DEFAULT_LAUNCH_SETTINGS["agent-toolkit"]
DEFAULTS_AH = DEFAULT_LAUNCH_SETTINGS["agent-harness"]
ENABLED_TK = decode_launch_object({"local_pi_runner_launcher": "laneexec", "lane_placement": "enabled",
                                   "routes_enabled": list(REMOTE_ROUTES)}, client="agent-toolkit")
ENABLED_AH = decode_launch_object({"lane_placement": "enabled", "routes_enabled": list(REMOTE_ROUTES)},
                                  client="agent-harness")
WRITER = {"pi-runner": ("agent-toolkit", "execution", "none"),
          "implementation": ("agent-harness", "execution", "patch"),
          "leg": ("agent-harness", "review", "result"),
          "qualification": ("agent-harness", "review", "result")}


def route(settings, workload, target):
    client, action, kind = WRITER[workload]
    return route_refusal(settings, client=client, workload=workload, action=action,
                         result_kind=kind, target_kind=target)


@pytest.mark.parametrize("workload,target,expected", [
    ("implementation", "local", "sandbox_launch_route_disabled"),
    ("pi-runner", "local", "sandbox_launch_local_route_interim"),
    ("pi-runner", "openshell", "sandbox_launch_route_disabled"),
    ("leg", "openshell", "sandbox_launch_route_disabled"),
    ("qualification", "openshell", "sandbox_launch_route_disabled"),
    ("leg", "local", "sandbox_launch_route_disabled"),
    ("qualification", "local", "sandbox_launch_route_disabled"),
    ("implementation", "openshell", "sandbox_launch_route_disabled"),
    ("pi-runner", "e2b", "sandbox_launch_route_disabled"),
    ("leg", "e2b", "sandbox_launch_route_disabled"),
])
def test_shipped_defaults_disable_every_route(workload, target, expected):
    settings = DEFAULTS_TK if workload == "pi-runner" else DEFAULTS_AH
    assert route(settings, workload, target) == expected


@pytest.mark.parametrize("workload,target,expected", [
    ("implementation", "local", None),
    ("pi-runner", "local", None),
    ("pi-runner", "openshell", None),
    ("leg", "openshell", None),
    ("qualification", "openshell", None),
    ("leg", "local", "sandbox_launch_route_disabled"),
    ("qualification", "local", "sandbox_launch_route_disabled"),
    ("implementation", "openshell", "sandbox_launch_route_disabled"),
    ("pi-runner", "e2b", "sandbox_launch_route_disabled"),
])
def test_each_route_follows_only_its_own_activation_value(workload, target, expected):
    settings = ENABLED_TK if workload == "pi-runner" else ENABLED_AH
    assert route(settings, workload, target) == expected


def test_each_activation_value_enables_exactly_its_own_route():
    only_launcher = decode_launch_object({"local_pi_runner_launcher": "laneexec"}, client="agent-toolkit")
    assert route(only_launcher, "pi-runner", "local") is None
    assert route(only_launcher, "pi-runner", "openshell") == "sandbox_launch_route_disabled"
    only_remote = decode_launch_object({"routes_enabled": ["pi-runner/openshell"]}, client="agent-toolkit")
    assert route(only_remote, "pi-runner", "local") == "sandbox_launch_local_route_interim"
    assert route(only_remote, "pi-runner", "openshell") is None
    only_lanes = decode_launch_object({"lane_placement": "enabled"}, client="agent-harness")
    assert route(only_lanes, "implementation", "local") is None
    assert route(only_lanes, "leg", "openshell") == "sandbox_launch_route_disabled"


def test_the_route_table_is_closed_and_total():
    outcomes = {None, "sandbox_launch_route_disabled", "sandbox_launch_local_route_interim",
                "sandbox_launch_writer_route_refused", "sandbox_launch_refused"}
    for settings in (DEFAULTS_TK, DEFAULTS_AH, ENABLED_TK, ENABLED_AH):
        for client in ("agent-harness", "agent-toolkit"):
            for workload in ("leg", "qualification", "implementation", "pi-runner"):
                for action in ("execution", "review"):
                    for kind in ("patch", "result", "none"):
                        for target in ("local", "openshell", "e2b"):
                            got = route_refusal(settings, client=client, workload=workload, action=action,
                                                result_kind=kind, target_kind=target)
                            assert got in outcomes
                            if got is None:
                                assert (client, action, kind) == WRITER[workload]
                                assert ROUTE_TABLE[(workload, target)] in (
                                    "lane_placement", "local_pi_runner_launcher", "route")
    assert {key for key, value in ROUTE_TABLE.items() if value == "never"} == {
        ("leg", "local"), ("qualification", "local")}


@pytest.mark.parametrize("client,workload,action,kind,expected", [
    ("agent-toolkit", "pi-runner", "execution", "patch", "sandbox_launch_writer_route_refused"),
    ("agent-toolkit", "pi-runner", "execution", "result", "sandbox_launch_writer_route_refused"),
    ("agent-toolkit", "pi-runner", "review", "none", "sandbox_launch_writer_route_refused"),
    ("agent-harness", "implementation", "execution", "none", "sandbox_launch_writer_route_refused"),
    ("agent-harness", "implementation", "review", "patch", "sandbox_launch_writer_route_refused"),
    ("agent-harness", "leg", "execution", "result", "sandbox_launch_writer_route_refused"),
    ("agent-harness", "qualification", "review", "none", "sandbox_launch_writer_route_refused"),
    ("agent-harness", "pi-runner", "execution", "none", "sandbox_launch_refused"),
    ("agent-toolkit", "implementation", "execution", "patch", "sandbox_launch_refused"),
])
def test_writer_route_and_client_pairing_refusals(client, workload, action, kind, expected):
    settings = ENABLED_TK if client == "agent-toolkit" else ENABLED_AH
    assert route_refusal(settings, client=client, workload=workload, action=action,
                         result_kind=kind, target_kind="local") == expected


def test_settings_of_another_client_never_open_a_route():
    assert route_refusal(ENABLED_AH, client="agent-toolkit", workload="pi-runner", action="execution",
                         result_kind="none", target_kind="local") == "sandbox_launch_refused"


@pytest.mark.parametrize("client,workload,action,kind,expected", [
    ("agent-toolkit", "pi-runner", "execution", "none", None),
    ("agent-harness", "implementation", "execution", "patch", None),
    ("agent-harness", "leg", "review", "result", None),
    ("agent-harness", "qualification", "review", "result", None),
    ("agent-toolkit", "pi-runner", "execution", "patch", "sandbox_launch_writer_route_refused"),
    ("agent-harness", "leg", "execution", "result", "sandbox_launch_writer_route_refused"),
    ("agent-toolkit", "leg", "execution", "none", "sandbox_launch_refused"),
    ("agent-toolkit", "unknown", "execution", "none", "sandbox_launch_refused"),
])
def test_static_route_refusal_is_independent_of_activation(client, workload, action, kind, expected):
    active = ENABLED_TK if client == "agent-toolkit" else ENABLED_AH
    for settings in (DEFAULT_LAUNCH_SETTINGS[client], active):
        assert launch_routes.static_route_refusal(
            settings, client=client, workload=workload, action=action, result_kind=kind,
        ) == expected


def test_static_route_refusal_requires_the_captured_client():
    assert launch_routes.static_route_refusal(
        ENABLED_AH, client="agent-toolkit", workload="pi-runner", action="execution", result_kind="none",
    ) == "sandbox_launch_refused"


@pytest.mark.parametrize("workload,target,default_refusal,enabled_refusal", [
    ("implementation", "local", "sandbox_launch_route_disabled", None),
    ("pi-runner", "local", "sandbox_launch_local_route_interim", None),
    ("pi-runner", "openshell", "sandbox_launch_route_disabled", None),
    ("leg", "openshell", "sandbox_launch_route_disabled", None),
    ("qualification", "openshell", "sandbox_launch_route_disabled", None),
    ("leg", "local", "sandbox_launch_route_disabled", "sandbox_launch_route_disabled"),
    ("qualification", "local", "sandbox_launch_route_disabled", "sandbox_launch_route_disabled"),
    ("implementation", "openshell", "sandbox_launch_route_disabled", "sandbox_launch_route_disabled"),
    ("pi-runner", "e2b", "sandbox_launch_route_disabled", "sandbox_launch_route_disabled"),
    ("unknown", "openshell", "sandbox_launch_refused", "sandbox_launch_refused"),
])
def test_activation_refusal_preserves_default_and_opt_in_mapping(workload, target, default_refusal, enabled_refusal):
    defaults, active = (DEFAULTS_TK, ENABLED_TK) if workload == "pi-runner" else (DEFAULTS_AH, ENABLED_AH)
    assert launch_routes.activation_refusal(defaults, workload=workload, target_kind=target) == default_refusal
    assert launch_routes.activation_refusal(active, workload=workload, target_kind=target) == enabled_refusal


@pytest.mark.parametrize("settings,workload", [
    (ENABLED_AH, "pi-runner"),
    (ENABLED_TK, "leg"),
])
def test_activation_refusal_requires_a_workload_for_the_captured_client(settings, workload):
    assert launch_routes.activation_refusal(
        settings, workload=workload, target_kind="openshell",
    ) == "sandbox_launch_refused"


def test_route_refusal_preserves_the_legacy_mapping():
    disabled = "sandbox_launch_route_disabled"
    # Frozen L-S7 activation outcomes (shipped defaults, all opt-ins enabled).
    golden = {
        ("implementation", "local"): (disabled, None),
        ("pi-runner", "local"): ("sandbox_launch_local_route_interim", None),
        ("pi-runner", "openshell"): (disabled, None),
        ("leg", "openshell"): (disabled, None),
        ("qualification", "openshell"): (disabled, None),
    }
    for (settings, mode), client, workload, action, kind, target in product(
        ((DEFAULTS_TK, 0), (DEFAULTS_AH, 0), (ENABLED_TK, 1), (ENABLED_AH, 1)),
        ("agent-harness", "agent-toolkit", "unknown-client"),
        (*WRITER, "unknown-workload"),
        ("execution", "review"),
        ("patch", "result", "none"),
        ("local", "openshell", "e2b", "unknown-target"),
    ):
        writer = WRITER.get(workload)
        if writer is None or writer[0] != client or settings.client != client:
            expected = "sandbox_launch_refused"
        elif writer[1:] != (action, kind):
            expected = "sandbox_launch_writer_route_refused"
        else:
            expected = golden.get((workload, target), (disabled, disabled))[mode]
        assert route_refusal(
            settings, client=client, workload=workload, action=action,
            result_kind=kind, target_kind=target,
        ) == expected


@pytest.mark.parametrize("target,vector,expected", [
    ("openshell", "full-remote-pi-runner", None),
    ("local", "minimal-without-app", None),
    ("openshell", "minimal-without-app", "sandbox_launch_input_mismatch"),
    ("local", "full-remote-pi-runner", "sandbox_launch_input_mismatch"),
    ("e2b", "full-remote-pi-runner", "sandbox_launch_input_mismatch"),
])
def test_crossed_pi_pairs_refuse_input_mismatch(target, vector, expected):
    assert pi_policy_refusal("pi-runner", target, vector) == expected
    assert pi_policy_refusal("implementation", target, vector) is None


# -- registration: positive cases -----------------------------------------------------------

def test_the_fixture_pinned_manifest_registers_both_pi_templates(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    records = [local_record(host, manifest), openshell_record(manifest)]
    registry, _ = register(records, fixture_raw, host)
    assert registry.refused == {}
    assert sorted(registry.templates) == ["pi-runner.local.v1", "pi-runner.openshell.v1"]
    for record in records:
        template = registry.templates[record["template_id"]]
        assert template.raw == jcs(record)
        assert template.template_sha256 == sha(jcs(record))
    assert [s.to_json() for s in template_summaries(registry)] == [
        {"template_id": r["template_id"], "template_sha256": sha(jcs(r)), "workload": "pi-runner"}
        for r in sorted(records, key=lambda r: r["template_id"])]
    assert registry.toolkit.closure == frozenset(CLOSURE_PATHS) and len(CLOSURE_PATHS) == 16


def test_the_pinned_manifest_itself_matches_the_contract_pin():
    raw = PINNED_MANIFEST.encode()
    assert (len(raw), sha(raw)) == (CONTRACT_PIN.byte_length, CONTRACT_PIN.sha256)
    accepted = check_toolkit_manifest(raw)
    assert accepted.closure == frozenset(CLOSURE_PATHS)
    assert len(REQUIRED_ROLES) == 17 and set(accepted.roles) >= set(REQUIRED_ROLES)


def test_the_pinned_manifest_registers_the_openshell_template_on_its_recorded_closure(host):
    raw = PINNED_MANIFEST.encode()
    registry, _ = register([openshell_record(PINNED_DOC)], raw, host, pin=None)
    assert registry.refused == {} and list(registry.templates) == ["pi-runner.openshell.v1"]


TOOLKIT_CHECKOUT = os.environ.get("LANEEXEC_TEST_TOOLKIT_CHECKOUT")


@pytest.mark.skipif(not TOOLKIT_CHECKOUT, reason="no agent-toolkit checkout at the pinned commit "
                    "(LANEEXEC_TEST_TOOLKIT_CHECKOUT) to bind the local closure's real bytes")
def test_the_pinned_manifest_registers_the_local_template_on_the_real_closure(tmp_path):
    source = Path(TOOLKIT_CHECKOUT)
    digests = {p: (source / p).read_bytes() for p in CLOSURE_PATHS}
    real = Host(tmp_path, digests=digests)
    raw = PINNED_MANIFEST.encode()
    registry, _ = register([local_record(real, PINNED_DOC), openshell_record(PINNED_DOC)], raw, real, pin=None)
    assert registry.refused == {}
    assert sorted(registry.templates) == ["pi-runner.local.v1", "pi-runner.openshell.v1"]


def test_a_generic_local_template_registers_for_agent_harness(host):
    host.write("usr/bin/worker", b"fixture worker", mode=0o755)
    record = {
        "template_id": "implementation.local.v1", "workload": "implementation", "target_kind": "local",
        "policy_vectors": ["minimal-with-app"], "action": "execution", "result_kinds": ["patch"],
        "image_digest": LOCAL_IMAGE, "argv": ["/usr/bin/worker", {"slot": "tree"}, {"slot": "out"}],
        "executable_chain": [{"role": "worker", "locator_kind": "declared", "locator": "/usr/bin/worker",
                              "sha256": host.file_sha("/usr/bin/worker")}],
        "ro_trees": [], "image_links": [], "link": None, "environment_policy": "constructed",
        "references": [], "max_timeout_seconds": 600, "result_schema_id": None,
    }
    settings = decode_launch_object({"templates": [jcs(record).decode()]}, client="agent-harness")
    registry = register_templates(settings, host=host.files)
    assert list(registry.templates) == ["implementation.local.v1"] and registry.toolkit is None


# -- registration: the toolkit pins manifest (C2) -------------------------------------------

def manifest_case(host, raw, *, pin="fixture"):
    records = [local_record(host, fixture_manifest()), openshell_record(fixture_manifest())]
    registry, _ = register(records, raw, host, pin=pin)
    return registry


def test_manifest_bytes_of_another_length_refuse(host, fixture_raw):
    registry = manifest_case(host, fixture_raw + b" ", pin=pin_for(fixture_raw))
    refused_all(registry, "manifest_length")


def test_manifest_bytes_of_another_digest_refuse(host, fixture_raw):
    other = bytearray(fixture_raw)
    other[-3] = ord("0") if other[-3] != ord("0") else ord("1")
    registry = manifest_case(host, bytes(other), pin=pin_for(fixture_raw))
    refused_all(registry, "manifest_digest")


def test_the_contract_pin_refuses_a_fixture_manifest(host, fixture_raw):
    registry = manifest_case(host, fixture_raw, pin=None)
    refused_all(registry, "manifest_length" if len(fixture_raw) != CONTRACT_PIN.byte_length else "manifest_digest")


@pytest.mark.parametrize("mutate,reason", [
    (lambda raw: json.dumps(json.loads(raw), indent=1).encode(), "manifest_not_canonical"),
    (lambda raw: raw + b"\n", "manifest_not_canonical"),
    (lambda raw: b"[]", "manifest_not_json"),
    (lambda raw: raw.replace(b'"schema":"toolkit_pins.v1"',
                             b'"schema":"toolkit_pins.v1","schema":"toolkit_pins.v1"', 1), "manifest_not_json"),
])
def test_manifest_serialization_refusals(host, fixture_raw, mutate, reason):
    raw = mutate(fixture_raw)
    refused_all(manifest_case(host, raw, pin=pin_for(raw)), reason)


def files_case(host, mutate_rows, *, document=None):
    rows = fixture_manifest()["files"]
    rows = mutate_rows(copy.deepcopy(rows))
    doc = document or fixture_manifest(rows)
    raw = jcs(doc)
    return manifest_case(host, raw, pin=pin_for(raw))


def test_a_schema_mismatch_refuses(host):
    doc = fixture_manifest()
    doc["schema"] = "toolkit_pins.v2"
    refused_all(files_case(host, lambda r: r, document=doc), "manifest_schema")


def test_a_toolkit_commit_mismatch_refuses(host):
    doc = fixture_manifest()
    doc["toolkit_commit"] = "e" * 40
    refused_all(files_case(host, lambda r: r, document=doc), "manifest_commit")


def test_files_not_sorted_by_path_refuse(host):
    refused_all(files_case(host, lambda r: list(reversed(r))), "manifest_unsorted")


def test_a_duplicate_path_refuses(host):
    def dup(rows):
        twin = dict(rows[0], role="remote_inner_closure:docs/remote-placement.md")
        return [rows[0], twin] + rows[1:]
    refused_all(files_case(host, dup), "manifest_duplicate_path")


@pytest.mark.parametrize("mutate", [
    lambda e: {k: v for k, v in e.items() if k != "role"},
    lambda e: {**e, "extra": "x"},
    lambda e: {**e, "path": 7},
    lambda e: {**e, "sha256": None},
])
def test_a_malformed_entry_refuses(host, mutate):
    refused_all(files_case(host, lambda rows: [mutate(rows[0])] + rows[1:]), "manifest_entry_malformed")


@pytest.mark.parametrize("digest", ["a" * 63, "a" * 65, "A" * 64, "g" * 64])
def test_a_hash_of_the_wrong_shape_refuses(host, digest):
    refused_all(files_case(host, lambda rows: [dict(rows[0], sha256=digest)] + rows[1:]),
                "manifest_hash_malformed")


def resort(rows):
    return sorted(rows, key=lambda e: e["path"].encode())


@pytest.mark.parametrize("role", REQUIRED_ROLES)
def test_each_required_role_missing_refuses(host, role):
    refused_all(files_case(host, lambda rows: [e for e in rows if e["role"] != role]), "role_missing")


@pytest.mark.parametrize("role", REQUIRED_ROLES)
def test_each_required_role_duplicated_refuses(host, role):
    def dup(rows):
        return resort(rows + [{"path": "zz/duplicate-" + role, "role": role, "sha256": "0" * 64}])
    refused_all(files_case(host, dup), "role_duplicated")


@pytest.mark.parametrize("role", REQUIRED_ROLES)
def test_each_required_role_at_another_path_refuses(host, role):
    def moved(rows):
        return resort([dict(e, path="zz/moved/" + e["path"]) if e["role"] == role else e for e in rows])
    refused_all(files_case(host, moved), "role_path")


@pytest.mark.parametrize("extra", [
    {"path": "zz/extra.mjs", "role": "toolkit_unknown", "sha256": "0" * 64},
    {"path": "zz/extra.mjs", "role": "remote_inner_closure:zz/other.mjs", "sha256": "0" * 64},
])
def test_an_unknown_role_refuses(host, extra):
    refused_all(files_case(host, lambda rows: resort(rows + [extra])), "role_unknown")


def test_a_missing_manifest_leaves_the_registry_unregistered(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    value = {"templates": [jcs(local_record(host, manifest)).decode()]}
    registry = register_templates(decode_launch_object(value, client="agent-toolkit"), host=host.files)
    refused_all(registry, "pins_missing")


# -- registration: listed files and the 16-file closure (C2) ---------------------------------

def test_a_listed_closure_file_whose_bytes_differ_refuses_locally(tmp_path, fixture_raw):
    host = Host(tmp_path, digests={"harnesses/pi/sandbox/link.mjs": b"changed"})
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    assert registry.refused == {0: "file_mismatch"}


def test_a_recorded_closure_file_whose_digest_differs_refuses_on_openshell(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    runtime = runtime_record(manifest)
    runtime["launcher"]["files"]["harnesses/pi/sandbox/link.mjs"] = "0" * 64
    registry, _ = register([openshell_record(manifest)], fixture_raw, host, runtime=runtime)
    assert registry.refused == {0: "file_mismatch"}


def test_a_worker_whose_digest_differs_from_its_manifest_entry_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    record = openshell_record(manifest)
    record["executable_chain"][2]["sha256"] = "0" * 64
    runtime = runtime_record(manifest)
    runtime["launcher"]["files"][REMOTE_INNER] = "0" * 64
    registry, _ = register([record], fixture_raw, host, runtime=runtime)
    assert registry.refused == {0: "file_mismatch"}


@pytest.mark.parametrize("path", CLOSURE_PATHS)
def test_a_local_bound_closure_omitting_each_file_refuses(tmp_path, fixture_raw, path):
    host = Host(tmp_path)
    (host.root / "opt/toolkit" / path).unlink()
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    assert registry.refused == {0: "closure_mismatch"}


@pytest.mark.parametrize("path", CLOSURE_PATHS)
def test_an_openshell_recorded_closure_omitting_each_file_refuses(host, fixture_raw, path):
    manifest = json.loads(fixture_raw)
    runtime = runtime_record(manifest)
    del runtime["launcher"]["files"][path]
    registry, _ = register([openshell_record(manifest)], fixture_raw, host, runtime=runtime)
    assert registry.refused == {0: "closure_mismatch"}


def test_a_local_bound_closure_adding_a_file_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    host.write("opt/toolkit/harnesses/pi/sandbox/cred-proxy.mjs",
               fixture_bytes("harnesses/pi/sandbox/cred-proxy.mjs"))
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    assert registry.refused == {0: "closure_mismatch"}


def test_a_local_bound_closure_adding_an_unlisted_file_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    host.write("opt/toolkit/harnesses/pi/sandbox/unlisted.mjs", b"not in the manifest")
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    assert registry.refused == {0: "file_unlisted"}


def test_an_openshell_recorded_closure_adding_a_file_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    listed = runtime_record(manifest)
    listed["launcher"]["files"]["harnesses/pi/sandbox/cred-proxy.mjs"] = sha(
        fixture_bytes("harnesses/pi/sandbox/cred-proxy.mjs"))
    registry, _ = register([openshell_record(manifest)], fixture_raw, host, runtime=listed)
    assert registry.refused == {0: "closure_mismatch"}
    unlisted = runtime_record(manifest)
    unlisted["launcher"]["files"]["harnesses/pi/sandbox/unlisted.mjs"] = "0" * 64
    registry, _ = register([openshell_record(manifest)], fixture_raw, host, runtime=unlisted)
    assert registry.refused == {0: "file_unlisted"}


def test_a_chain_file_the_manifest_does_not_list_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    host.write("opt/toolkit/bin/node", b"fixture node in the toolkit tree", mode=0o755)
    record = local_record(host, manifest)
    record["executable_chain"][1] = {"role": "wrapper", "locator_kind": "declared",
                                     "locator": "/opt/toolkit/bin/node",
                                     "sha256": host.file_sha("/opt/toolkit/bin/node")}
    record["argv"] = [("/opt/toolkit/bin/node" if a == "/opt/node/bin/node" else a) for a in record["argv"]]
    registry, _ = register([record], fixture_raw, host)
    assert registry.refused == {0: "file_unlisted"}


def test_local_chain_and_tree_digests_are_checked_against_host_bytes(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    record = local_record(host, manifest)
    record["executable_chain"][0]["sha256"] = "0" * 64
    tree = local_record(host, manifest)
    tree["ro_trees"][0]["tree_sha256"] = "0" * 64
    registry, _ = register([record, tree], fixture_raw, host)
    assert registry.refused == {0: "chain_mismatch", 1: "tree_mismatch"}


def test_an_openshell_template_needs_a_registered_image_runtime(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    record = openshell_record(manifest, image_digest="sha256:" + "9" * 64)
    record_ok = openshell_record(manifest)
    registry, _ = register([record], fixture_raw, host)
    assert registry.refused == {0: "image_unregistered"}
    record_ok["executable_chain"][0]["sha256"] = "0" * 64
    registry, _ = register([record_ok], fixture_raw, host)
    assert registry.refused == {0: "chain_mismatch"}


# -- recheck_before_start -------------------------------------------------------------------

def test_recheck_refuses_a_mutated_listed_file_and_passes_once_restored(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    registry, settings = register([local_record(host, manifest)], fixture_raw, host)
    template = registry.templates["pi-runner.local.v1"]
    pin = pin_for(fixture_raw)
    recheck_template(template, registry, settings, host=host.files, pin=pin)
    target = host.root / "opt/toolkit/harnesses/pi/sandbox/policy.json"
    original = target.read_bytes()
    target.write_bytes(b"mutated")
    with pytest.raises(TemplateRefused) as raised:
        recheck_template(template, registry, settings, host=host.files, pin=pin)
    assert raised.value.code == "sandbox_launch_template_refused"
    target.write_bytes(original)
    recheck_template(template, registry, settings, host=host.files, pin=pin)


def test_recheck_refuses_swapped_manifest_bytes(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    records = [openshell_record(manifest)]
    registry, _ = register(records, fixture_raw, host)
    other = fixture_manifest()
    other["files"][0] = dict(other["files"][0], sha256="1" * 64)
    swapped = toolkit_settings(records, jcs(other))
    with pytest.raises(TemplateRefused):
        recheck_template(registry.templates["pi-runner.openshell.v1"], registry, swapped,
                         host=host.files, pin=pin_for(fixture_raw))


# -- registration: image links, record bytes, slots ------------------------------------------

@pytest.mark.parametrize("link", [
    "opt/npm/lib", "/opt/npm/./lib", "/opt/npm/../npm/lib", "/opt/npm//lib", "/opt/npm/lib/",
    "/opt/outside/lib",
])
def test_local_image_link_refusals(host, fixture_raw, link):
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest, image_links=[link])], fixture_raw, host)
    assert registry.refused == {0: "image_link"}


def test_one_image_link_at_or_under_another_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    for links in (["/opt/npm/lib", "/opt/npm/lib/pi"], ["/opt/npm/lib", "/opt/npm/lib"]):
        registry, _ = register([local_record(host, manifest, image_links=links)], fixture_raw, host)
        assert registry.refused == {0: "image_link"}


def test_an_openshell_image_link_outside_every_runtime_tree_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    registry, _ = register([openshell_record(manifest, image_links=["/opt/npm/lib"])], fixture_raw, host)
    assert registry.refused == {0: "image_link"}


@pytest.mark.parametrize("encode", [
    lambda r: json.dumps(r, indent=2),
    lambda r: jcs(r).decode() + "\n",
    lambda r: jcs({**r, "extra": 1}).decode(),
])
def test_template_bytes_other_than_the_canonical_record_refuse(host, fixture_raw, encode):
    manifest = json.loads(fixture_raw)
    registry, _ = register([encode(openshell_record(manifest))], fixture_raw, host)
    assert registry.templates == {} and registry.refused[0] in {"record_bytes", "record_invalid"}


@pytest.mark.parametrize("argv", [
    ["/usr/bin/worker", {"slot": "unknown"}],
    ["/usr/bin/worker", {"slot": "manifest"}],
    ["/usr/bin/worker", {"slot": "relay_endpoint"}],
    ["/usr/bin/worker", {"slot": "relay_port"}],
    ["/usr/bin/worker", {"slot": "tree", "extra": 1}],
])
def test_a_slot_outside_the_slots_or_its_target_refuses(host, argv):
    host.write("usr/bin/worker", b"fixture worker", mode=0o755)
    record = {
        "template_id": "implementation.local.v1", "workload": "implementation", "target_kind": "local",
        "policy_vectors": ["minimal-with-app"], "action": "execution", "result_kinds": ["patch"],
        "image_digest": LOCAL_IMAGE, "argv": argv,
        "executable_chain": [{"role": "worker", "locator_kind": "declared", "locator": "/usr/bin/worker",
                              "sha256": host.file_sha("/usr/bin/worker")}],
        "ro_trees": [], "image_links": [], "link": None, "environment_policy": "constructed",
        "references": [], "max_timeout_seconds": 600, "result_schema_id": None,
    }
    settings = decode_launch_object({"templates": [jcs(record).decode()]}, client="agent-harness")
    registry = register_templates(settings, host=host.files)
    assert registry.refused == {0: "slot_invalid"}


def test_tree_dest_is_refused_on_openshell(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    record = openshell_record(manifest)
    record["argv"] = record["argv"] + [{"slot": "tree_dest"}]
    registry, _ = register([record], fixture_raw, host)
    assert registry.refused == {0: "slot_invalid"}


def test_pi_templates_register_only_for_agent_toolkit_and_ids_are_unique(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    record = openshell_record(manifest)
    settings = decode_launch_object({"templates": [jcs(record).decode()]}, client="agent-harness")
    assert register_templates(settings, host=host.files).refused == {0: "pi_form"}
    registry, _ = register([record, record], fixture_raw, host)
    assert registry.templates == {} and registry.refused == {0: "duplicate_template", 1: "duplicate_template"}


@pytest.mark.parametrize("change", [
    {"template_id": "pi-runner.openshell.v1"},
    {"policy_vectors": ["full-remote-pi-runner"]},
    {"result_kinds": ["patch"]},
    {"max_timeout_seconds": 3599},
    {"link": {"mode": "listen", "guest_port": 17690}},
    {"references": ["extra"]},
])
def test_the_local_pi_template_fields_are_fixed(host, fixture_raw, change):
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest, **change)], fixture_raw, host)
    assert registry.templates == {} and registry.refused[0] in {"pi_form", "record_invalid"}


# -- LANEEXEC-v1-errata-1 E1 and E2: the local template form ---------------------------------

def index_of(argv, tokens):
    for i in range(len(argv) - len(tokens) + 1):
        if argv[i:i + len(tokens)] == tokens:
            return i
    return -1


def var_log_is_erratum_form(argv):
    usr = index_of(argv, USR_BIND)
    if usr < 0 or argv[usr + 3:usr + 7] != ERRATUM_FORM:
        return False
    return not any(flag in BIND_FLAGS and (src == "/var/log" or str(src).startswith("/var/log/"))
                   for flag, src in zip(argv, argv[1:]))


LOCAL_SLOTS = {"tree": "/state/r1/tree", "tree_dest": "/work/repo", "scratch": "/state/r1/scratch"}


def test_e1_the_local_template_expands_to_exactly_its_erratum_form(host, fixture_raw):
    assert launch_routes.frozen_pi_runner_template("local")["argv"] == FROZEN_LOCAL_ARGV
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    argv = expand_argv(registry.templates["pi-runner.local.v1"], LOCAL_SLOTS)
    assert var_log_is_erratum_form(list(argv))
    assert list(argv) == [
        "/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
        "--clearenv", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", "/etc", "/etc", "--ro-bind", "/lib", "/lib", "--ro-bind", "/usr", "/usr",
        "--tmpfs", "/var/log", "--remount-ro", "/var/log",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", "/opt/node", "/opt/node", "--ro-bind", "/opt/toolkit", "/opt/toolkit",
        "--ro-bind", "/opt/npm", "/opt/npm",
        "--bind", "/state/r1/tree", "/work/repo", "--bind", "/state/r1/scratch", "/state/r1/scratch",
        "--chdir", "/work/repo", "--", "/opt/node/bin/node", f"/opt/toolkit/{REMOTE_INNER}",
    ]


def test_e1_mutation_control_the_previous_bind_fails_the_form(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    argv = list(expand_argv(registry.templates["pi-runner.local.v1"], LOCAL_SLOTS))
    i = index_of(argv, ERRATUM_FORM)
    assert not var_log_is_erratum_form(argv[:i] + PREVIOUS_FORM + argv[i + 4:])


def test_e2i_registration_refuses_the_pre_erratum_argv(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    current = local_record(host, manifest)["argv"]
    i = index_of(current, ERRATUM_FORM)
    previous = current[:i] + PREVIOUS_FORM + current[i + 4:]
    for argv in (previous, current + ["--ro-bind", "/var/log", "/srv/log"],
                 [a for a in current if a != "--die-with-parent"]):
        registry, _ = register([local_record(host, manifest, argv=argv)], fixture_raw, host)
        assert registry.templates == {} and registry.refused == {0: "argv_form"}


def test_e2ii_a_pre_erratum_template_sha256_refuses_before_any_effect(host, fixture_raw, no_effects):
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    template = registry.templates["pi-runner.local.v1"]
    with pytest.raises(TemplateRefused) as raised:
        select_local(registry, PRE_ERRATUM_TEMPLATE_SHA256)
    assert (raised.value.code, raised.value.reason) == ("sandbox_launch_template_refused", "template_digest")
    assert select_local(registry, template.template_sha256) is template
    assert no_effects == []


def select_local(registry, digest, template_id="pi-runner.local.v1", **changes):
    args = {"workload": "pi-runner", "target_kind": "local", "policy_vector": "minimal-without-app",
            "action": "execution", "result_kind": "none", "image_digest": LOCAL_IMAGE}
    args.update(changes)
    return select_template(registry, Command(template_id, digest), **args)


# -- C9: template selection and argv expansion ------------------------------------------------

def test_selection_by_target_kind_and_naming_the_other_template_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest), openshell_record(manifest)], fixture_raw, host)
    local = registry.templates["pi-runner.local.v1"]
    remote = registry.templates["pi-runner.openshell.v1"]
    assert select_local(registry, local.template_sha256) is local
    assert select_template(registry, Command("pi-runner.openshell.v1", remote.template_sha256),
                           workload="pi-runner", target_kind="openshell",
                           policy_vector="full-remote-pi-runner", action="execution",
                           result_kind="none", image_digest=OPENSHELL_IMAGE) is remote
    for template_id, digest in (("pi-runner.openshell.v1", remote.template_sha256),
                                ("pi-runner.local.v1", "0" * 64)):
        with pytest.raises(TemplateRefused) as raised:
            select_local(registry, digest, template_id)
        assert raised.value.reason == ("template_target" if template_id != "pi-runner.local.v1"
                                       else "template_digest")
    for changes in ({"policy_vector": "minimal-with-app"}, {"image_digest": OPENSHELL_IMAGE},
                    {"action": "review"}, {"result_kind": "patch"}):
        with pytest.raises(TemplateRefused) as raised:
            select_local(registry, local.template_sha256, **changes)
        assert raised.value.reason == "template_unregistered"


def test_an_unknown_or_unregistered_template_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    bad = local_record(host, manifest)
    bad["executable_chain"][0]["sha256"] = "0" * 64
    registry, _ = register([bad], fixture_raw, host)
    with pytest.raises(TemplateRefused) as raised:
        select_local(registry, sha(jcs(bad)))
    assert raised.value.reason == "template_unregistered"
    with pytest.raises(TemplateRefused) as raised:
        select_template(registry, Command("implementation.v9", "0" * 64), workload="implementation",
                        target_kind="local", policy_vector="minimal-with-app", action="execution",
                        result_kind="patch", image_digest=LOCAL_IMAGE)
    assert raised.value.reason == "template_unregistered"


def test_the_openshell_template_expands_to_exactly_its_frozen_form(host, fixture_raw):
    assert launch_routes.frozen_pi_runner_template("openshell")["argv"] == FROZEN_OPENSHELL_ARGV
    manifest = json.loads(fixture_raw)
    registry, _ = register([openshell_record(manifest)], fixture_raw, host)
    template = registry.templates["pi-runner.openshell.v1"]
    policy = b"landlock manifest bytes"
    values = {"manifest": "/work/r1/inputs/landlock-policy.bin",
              "relay_endpoint": relay_endpoint_argument(template),
              "manifest_digest": manifest_digest_argument(policy)}
    assert values["relay_endpoint"] == "127.0.0.1:17690"
    assert values["manifest_digest"] == "sha256:" + sha(policy)
    assert expand_argv(template, values) == (
        HELPER, "--policy", "/work/r1/inputs/landlock-policy.bin", "--", IMAGE_NODE,
        f"{IMAGE_TOOLKIT}/{REMOTE_INNER}", "--listen", "127.0.0.1:17690", "--landlock",
        "/work/r1/inputs/landlock-policy.bin", "sha256:" + sha(policy))


def test_expansion_takes_slot_values_only_from_laneexec(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest)], fixture_raw, host)
    template = registry.templates["pi-runner.local.v1"]
    for values in ({"tree": "/t", "tree_dest": "/d"}, {**LOCAL_SLOTS, "scratch": ""},
                   {**LOCAL_SLOTS, "tree": "/t\x00x"}):
        with pytest.raises(ValueError):
            expand_argv(template, values)
    with pytest.raises(ValueError):
        relay_endpoint_argument(template)


def test_the_pi_runner_template_ids_follow_the_frozen_rule():
    rule = CONTRACT["x-argv-templates"]["pi_runner_templates"]["rule"]
    assert "openshell takes pi-runner.openshell.v1 and local takes pi-runner.local.v1" in rule
    assert dict(PI_RUNNER_TEMPLATE_IDS) == {"openshell": "pi-runner.openshell.v1", "local": "pi-runner.local.v1"}


def test_no_refusal_carries_an_input_value(host, fixture_raw):
    secret = "sentinel-secret-template-value"
    manifest = json.loads(fixture_raw)
    record = local_record(host, manifest, environment_policy=secret)
    record["executable_chain"][0]["sha256"] = "0" * 64
    registry, _ = register([record], fixture_raw, host)
    assert secret not in repr(registry.refused) and secret not in repr(registry)
    with pytest.raises(TemplateRefused) as raised:
        select_local(registry, secret)
    assert secret not in str(raised.value) and secret not in repr(raised.value.args)


# -- review round 1 (Consiliency/agent-harness#2134) ------------------------------------------

def protected_record(host, manifest, path):
    record = local_record(host, manifest)
    trees = record["ro_trees"] + [{"path": path, "tree_sha256": host.tree(path)}]
    i = record["argv"].index("--bind")
    binds = ["--ro-bind", path, path]
    return {**record, "ro_trees": trees, "argv": record["argv"][:i] + binds + record["argv"][i:]}


@pytest.mark.parametrize("path", ["/var/log", "/var", "/usr/share", "/tmp/x", "/etc/ssl"])
def test_a_read_only_tree_over_a_protected_mount_refuses(host, fixture_raw, path):
    """errata-1: a digest-correct ``/var/log`` tree must not replace the empty read-only one."""
    host.write(path.lstrip("/") + "/host.log", b"host log bytes")
    manifest = json.loads(fixture_raw)
    record = protected_record(host, manifest, path)
    registry, _ = register([record], fixture_raw, host)
    assert registry.templates == {} and registry.refused == {0: "tree_protected"}


def test_a_read_only_tree_resolving_onto_a_protected_mount_refuses(host, fixture_raw):
    """An ancestor symlink (``/opt/logroot`` -> ``../var``) puts the tree on ``/var/log``."""
    host.write("var/log/host.log", b"host log bytes")
    os.symlink("../var", host.root / "opt/logroot")
    manifest = json.loads(fixture_raw)
    record = local_record(host, manifest)
    record["ro_trees"].append({"path": "/opt/logroot/log", "tree_sha256": host.tree("/opt/logroot/log")})
    i = record["argv"].index("--bind")
    record["argv"][i:i] = ["--ro-bind", "/opt/logroot/log", "/opt/logroot/log"]
    registry, _ = register([record], fixture_raw, host)
    assert registry.templates == {} and registry.refused == {0: "tree_protected"}


def test_production_openshell_registration_is_closed(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    registry, _ = register([openshell_record(manifest)], fixture_raw, host, fixture=False)
    assert registry.templates == {} and registry.refused == {0: "runtime_unavailable"}


def test_an_operator_authored_runtime_record_is_not_accepted_in_settings(fixture_raw):
    image = {"image_digest": OPENSHELL_IMAGE, "workload": "pi-runner", "target_kind": "openshell",
             "runtime": runtime_record(json.loads(fixture_raw))}
    with pytest.raises(PlacementConfigError):
        decode_launch_object({"images": [image]}, client="agent-toolkit")


def test_a_malformed_fixture_runtime_record_refuses(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    bad = runtime_record(manifest)
    bad["node"] = "v22.0.0"  # the toolkit v3 manifest's node version string
    registry, _ = register([openshell_record(manifest)], fixture_raw, host, runtime=bad)
    assert registry.refused == {0: "image_unregistered"}


@pytest.mark.parametrize("broken", ["local", "openshell"])
def test_a_toolkit_file_failure_leaves_the_whole_registry_unregistered(tmp_path, fixture_raw, broken):
    digests = {"harnesses/pi/sandbox/link.mjs": b"changed"} if broken == "local" else None
    host = Host(tmp_path, digests=digests)
    manifest = json.loads(fixture_raw)
    runtime = runtime_record(manifest)
    if broken == "openshell":
        runtime["launcher"]["files"]["harnesses/pi/sandbox/link.mjs"] = "0" * 64
    registry, _ = register([local_record(host, manifest), openshell_record(manifest)],
                           fixture_raw, host, runtime=runtime)
    assert registry.templates == {}
    bad, good = (0, 1) if broken == "local" else (1, 0)
    assert registry.refused == {bad: "file_mismatch", good: "toolkit_unregistered"}


def test_a_non_toolkit_failure_leaves_the_sibling_registered(host, fixture_raw):
    manifest = json.loads(fixture_raw)
    bad = local_record(host, manifest, image_links=["/opt/outside/lib"])
    registry, _ = register([bad, openshell_record(manifest)], fixture_raw, host)
    assert registry.refused == {0: "image_link"} and list(registry.templates) == ["pi-runner.openshell.v1"]


@pytest.mark.parametrize("links", [
    [("opt/npm/lib/pi", "/opt/outside")],
    [("opt/npm/lib/pi", "hop"), ("opt/npm/lib/hop", "/opt/outside")],
    [("opt/npm/lib/pi", "../../elsewhere")],
])
def test_an_image_link_resolving_outside_its_tree_refuses(tmp_path, fixture_raw, links):
    host = Host(tmp_path)
    shutil.rmtree(host.root / "opt/npm/lib/pi")
    (host.root / "opt/outside").mkdir(parents=True)
    for rel, target in links:
        os.symlink(target, host.root / rel)
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest, image_links=["/opt/npm/lib/pi/node_modules"])],
                           fixture_raw, host)
    assert registry.refused == {0: "image_link"}


def test_an_image_link_through_an_in_tree_symlink_registers(tmp_path, fixture_raw):
    host = Host(tmp_path)
    os.symlink("pi", host.root / "opt/npm/lib/alias")
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest, image_links=["/opt/npm/lib/alias"])],
                           fixture_raw, host)
    assert registry.refused == {} and list(registry.templates) == ["pi-runner.local.v1"]


def without_lib64(argv):
    i = index_of(argv, ["--symlink", "usr/lib64", "/lib64"])
    return argv[:i] + argv[i + 3:]


def test_a_host_symlink_resolving_outside_usr_through_another_link_is_excluded(tmp_path, fixture_raw):
    host = Host(tmp_path)
    (host.root / "usr/lib64").rmdir()
    (host.root / "opt/evil").mkdir(parents=True)
    os.symlink("/opt/evil", host.root / "usr/lib64")
    manifest = json.loads(fixture_raw)
    with_entry = local_record(host, manifest)
    registry, _ = register([with_entry], fixture_raw, host)
    assert registry.refused == {0: "argv_form"}
    registry, _ = register([local_record(host, manifest, argv=without_lib64(with_entry["argv"]))],
                           fixture_raw, host)
    assert registry.refused == {} and list(registry.templates) == ["pi-runner.local.v1"]


def test_host_resolve_follows_indirect_links_in_the_host_view(host):
    os.symlink("usr/../opt", host.root / "lib32")
    os.symlink("a", host.root / "opt/b")
    os.symlink("b", host.root / "opt/c")
    assert host.files.resolve("/lib64/x") == "/usr/lib64/x"
    assert host.files.resolve("/lib32") == "/opt"
    assert host.files.resolve("/opt/c/z") == "/opt/a/z"
    os.symlink("loop2", host.root / "opt/loop1")
    os.symlink("loop1", host.root / "opt/loop2")
    assert host.files.resolve("/opt/loop1") is None


# -- review round 2 (Consiliency/agent-harness#2134) ------------------------------------------

def test_a_stale_tree_digest_cannot_mask_a_toolkit_file_failure(host, fixture_raw):
    """The tree digest is captured before a pinned closure file changes: the toolkit check
    still runs first and the whole registry, the valid openshell sibling included, is
    unregistered (the recomputed-digest case is the ``[local]`` whole-registry test)."""
    manifest = json.loads(fixture_raw)
    stale = local_record(host, manifest)
    host.write("opt/toolkit/harnesses/pi/sandbox/link.mjs", b"changed after the digest was taken")
    registry, _ = register([stale, openshell_record(manifest)], fixture_raw, host)
    assert registry.templates == {}
    assert registry.refused == {0: "file_mismatch", 1: "toolkit_unregistered"}


def test_an_image_link_resolving_through_host_var_log_refuses(tmp_path, fixture_raw):
    """``/opt/npm/lib/pi`` -> host ``/var/log/hop`` -> ``/opt/npm/lib/real``: the host view
    lands back in the tree, but in the sandbox ``/var/log`` is an empty mount."""
    host = Host(tmp_path)
    shutil.rmtree(host.root / "opt/npm/lib/pi")
    host.write("opt/npm/lib/real/index.js", b"fixture pi")
    host.write("var/log/keep", b"")
    os.symlink("../../../var/log/hop", host.root / "opt/npm/lib/pi")
    os.symlink("../../opt/npm/lib/real", host.root / "var/log/hop")
    assert host.files.resolve("/opt/npm/lib/pi") == "/opt/npm/lib/real"
    manifest = json.loads(fixture_raw)
    registry, _ = register([local_record(host, manifest, image_links=["/opt/npm/lib/pi"])],
                           fixture_raw, host)
    assert registry.refused == {0: "image_link"}


def test_a_host_symlink_resolving_through_host_var_log_is_excluded(tmp_path, fixture_raw):
    """``/lib64`` -> ``usr/lib64`` -> host ``/var/log/l`` -> ``/usr/lib``: inside /usr in
    the host view, absent in the sandbox, so no ``--symlink`` entry is emitted."""
    host = Host(tmp_path)
    (host.root / "usr/lib64").rmdir()
    (host.root / "usr/lib").mkdir(parents=True)
    host.write("var/log/keep", b"")
    os.symlink("../var/log/l", host.root / "usr/lib64")
    os.symlink("../../usr/lib", host.root / "var/log/l")
    assert host.files.resolve("/lib64") == "/usr/lib"
    manifest = json.loads(fixture_raw)
    with_entry = local_record(host, manifest)
    registry, _ = register([with_entry], fixture_raw, host)
    assert registry.refused == {0: "argv_form"}
    registry, _ = register([local_record(host, manifest, argv=without_lib64(with_entry["argv"]))],
                           fixture_raw, host)
    assert registry.refused == {} and list(registry.templates) == ["pi-runner.local.v1"]
