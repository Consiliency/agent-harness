"""The vendor-neutral sandbox placement seam (agent-harness#896, plan 1a).

A configured sandbox root used to be resolved and then ignored: the stage was built and
the seat run locally regardless. Plan 1a puts today's local path behind one placement seam
without changing what it does, records what placement actually happened as runtime-attested
receipts, and adds an opt-in knob that refuses a seat leg which was not placed remotely.

Every test here drives the production `_default_spawn` (or the production helper the
contract names), and each is red under the mutation its docstring names.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from phase_loop_runtime import (
    panel_invoker,
    review_stage,
    sandbox_egress,
    sandbox_policy,
    sandbox_retention,
)
from phase_loop_runtime.advisor_board import backing

GOLDEN = Path(__file__).parent / "fixtures" / "sandbox_placement_896" / "local_equivalence.json"
_CAPTURE_ENV = "PHASE_LOOP_896_CAPTURE_GOLDEN"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
        check=True,
    )
    return repo


def _authorization(repo: Path | None, *, tree: bool = True) -> backing.ReviewIsolationAuthorization:
    return backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=(
            review_stage.review_tree_manifest_sha256(repo) if tree and repo is not None else None
        ),
    )


class _Recorder:
    """Spies that WRAP the real placement steps, recording the order they ran in."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[str] = []
        self.base: Path | None = None
        self.launch: dict[str, object] = {}

    def norm(self, value: object) -> str:
        text = str(value)
        if self.base is not None:
            text = text.replace(str(self.base), "<BASE>")
        return text.replace(str(self.tmp_path.resolve()), "<TMP>").replace(str(self.tmp_path), "<TMP>")

    def install(self, monkeypatch, *, egress_prefix=("/usr/bin/env",)) -> None:
        rec = self

        def wrap(module, name, label=None):
            real = getattr(module, name)

            def spy(*args, **kwargs):
                rec.calls.append(label or name)
                return real(*args, **kwargs)

            monkeypatch.setattr(module, name, spy)

        wrap(sandbox_policy, "select_sandbox_root")
        wrap(sandbox_policy, "ensure_staging_space")
        wrap(review_stage, "stage_review_tree")
        wrap(sandbox_retention, "mark_as_sandbox")
        wrap(backing, "_revalidate_staged_tree")

        real_rename = Path.rename

        def rename(self_path, target):
            if Path(target).name == review_stage.REVIEW_STAGE_TREE_DIRNAME:
                rec.calls.append("rename")
            return real_rename(self_path, target)

        monkeypatch.setattr(Path, "rename", rename)

        real_remove = review_stage.remove_review_stage

        def remove(path):
            rec.calls.append(f"remove_review_stage:{rec.norm(Path(path))}")
            return real_remove(path)

        monkeypatch.setattr(review_stage, "remove_review_stage", remove)

        @contextlib.contextmanager
        def isolated_network(*args, **kwargs):
            rec.calls.append("isolated_network:enter")
            try:
                yield egress_prefix
            finally:
                rec.calls.append("isolated_network:exit")

        monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)

        def exec_leg(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
            review_dir = Path(review_dir)
            rec.base = review_dir.parent
            tree = panel_invoker._sandbox_in(review_dir)
            rec.calls.append(f"launch:{leg}")
            argv = panel_invoker._brokered_codex_command(
                model=None, out_dir=Path(out_dir), out_file=Path(out_dir) / "x.txt",
                codex_effort_args=(), staged_tree=tree,
            )
            # The model is not a placement fact: normalized, so a model-id bump does not
            # re-capture a golden it has nothing to do with.
            argv = [
                "<MODEL>" if i and argv[i - 1] == "--model" else a for i, a in enumerate(argv)
            ]
            rec.launch = {
                "argv": [rec.norm(a) for a in argv],
                # The attested preimage is `str(cwd.resolve())` (`_record_provider_launch`);
                # the scratch base differs per run, so it is hashed base-relative.
                "provider_cwd_sha256": sha256(
                    rec.norm(Path(out_dir).resolve()).encode()
                ).hexdigest(),
                "tree": rec.norm(tree) if tree is not None else None,
            }
            return 0, "ok review", "log"

        def exec_claude_tui_leg(review_dir, out_dir, timeout_s, artifact, **kwargs):
            review_dir = Path(review_dir)
            rec.base = review_dir.parent
            rec.calls.append("launch:claude")
            tree = panel_invoker._sandbox_in(review_dir)
            rec.launch = {
                "provider_cwd_sha256": sha256(
                    rec.norm(Path(kwargs["repo_dir"]).resolve()).encode()
                ).hexdigest(),
                "tree": rec.norm(tree) if tree is not None else None,
            }
            return "OK", "ok review"

        monkeypatch.setattr(panel_invoker, "_exec_leg", exec_leg)
        monkeypatch.setattr(panel_invoker, "_exec_claude_tui_leg", exec_claude_tui_leg)


def _drive(tmp_path, monkeypatch, leg: str, *, tree: bool = True, **kwargs):
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path / "staging"))
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_ROOT", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", raising=False)
    repo = _repo(tmp_path)
    rec = _Recorder(tmp_path)
    rec.install(monkeypatch)
    result = panel_invoker._default_spawn(
        leg, "REVIEW BUNDLE BODY", repo_dir=repo,
        review_authorization=_authorization(repo, tree=tree), canonical_repo_authority=repo,
        **kwargs,
    )
    return rec, result


def _equivalence_record(tmp_path_factory, monkeypatch) -> dict[str, object]:
    record: dict[str, object] = {}
    for leg in ("codex", "claude"):
        with monkeypatch.context() as patch:
            rec, result = _drive(tmp_path_factory.mktemp(leg), patch, leg)
            record[leg] = {
                "result": [result[0], result[1]],
                "calls": rec.calls,
                "launch": rec.launch,
            }
    return record


def test_local_equivalence_matches_the_base_golden(tmp_path_factory, monkeypatch):
    """With no root configured, placement is byte-for-byte today's: the same steps in the
    same order (egress exit included), the same provider argv and the same attested cwd.

    The golden was captured on the base this change starts from, before any code moved
    (`PHASE_LOOP_896_CAPTURE_GOLDEN=1`). Mutations that go red: `mark_as_sandbox` before
    the rename; the local tree reported at its pre-rename path; release before egress exit.
    """
    record = _equivalence_record(tmp_path_factory, monkeypatch)
    if os.environ.get(_CAPTURE_ENV) == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert record == json.loads(GOLDEN.read_text(encoding="utf-8"))


# --- shared helpers for the falsifiers below -------------------------------------------

from contextvars import copy_context  # noqa: E402
import dataclasses  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import warnings  # noqa: E402

from phase_loop_runtime import sandbox_placement  # noqa: E402

REQUIRED = "sandbox_placement_required_unavailable"
DRIVER = "sandbox_placement_driver_unavailable"

#: The three launch branches `_default_spawn` dispatches to, each selected the way the
#: production code selects it: brokered is the UNMODIFIED path (no injected adapter), the
#: other two are reached by replacing their adapter.
BRANCHES = ("brokered", "claude_tui", "exec_leg")


def _branch_leg(branch: str) -> str:
    return "claude" if branch == "claude_tui" else "codex"


class _Counters:
    """Every `_SpawnCounter` a leg installed, so a refused leg's count can be read."""

    def __init__(self, monkeypatch) -> None:
        self.cells: list[object] = []
        real = panel_invoker._SpawnCounter
        outer = self

        class Recording(real):
            def __init__(self) -> None:
                super().__init__()
                outer.cells.append(self)

        monkeypatch.setattr(panel_invoker, "_SpawnCounter", Recording)

    @property
    def total(self) -> int:
        return sum(cell.count for cell in self.cells)


def _setup_branch(monkeypatch, branch: str, launches: list[str]) -> None:
    """Route a leg to ``branch``; record every launch the branch reaches."""
    if branch == "brokered":
        # The production path. The fixture authorization is not a live HARDEN lease, so the
        # lease checks are replaced; nothing below them is.
        monkeypatch.setattr(
            panel_invoker, "revalidate_review_isolation_authorization", lambda *a, **k: None,
        )

        def broker(*args, **kwargs):
            launches.append("broker")
            raise RuntimeError("broker reached")

        monkeypatch.setattr(panel_invoker, "ParentUnixBroker", broker)
    elif branch == "claude_tui":
        def tui(*args, **kwargs):
            launches.append("claude_tui")
            return "OK", "ok"

        monkeypatch.setattr(panel_invoker, "_exec_claude_tui_leg", tui)
    else:
        def exec_leg(*args, **kwargs):
            launches.append("exec_leg")
            return 0, "ok", "log"

        monkeypatch.setattr(panel_invoker, "_exec_leg", exec_leg)


def _egress(monkeypatch, *, fail: bool = False, calls: list[str] | None = None) -> None:
    @contextlib.contextmanager
    def isolated_network(*args, **kwargs):
        if calls is not None:
            calls.append("isolated_network:enter")
        if fail:
            raise sandbox_egress.EgressUnavailable("egress isolation unavailable")
        yield ("/usr/bin/env",)

    monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)


def _env(monkeypatch, tmp_path: Path, *, root: str | None = None, knob: str | None = None):
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_STAGING_DIR", str(tmp_path / "staging"))
    if root is None:
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_ROOT", raising=False)
    else:
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_ROOT", root)
    if knob is None:
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", raising=False)
    else:
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", knob)


def _spy_stage(monkeypatch) -> list[str]:
    staged: list[str] = []
    real = review_stage.stage_review_tree

    def spy(*args, **kwargs):
        staged.append("stage")
        return real(*args, **kwargs)

    monkeypatch.setattr(review_stage, "stage_review_tree", spy)
    return staged


def _spawn(leg: str, repo: Path, *, tree: bool = True, monitor=None, auth=None):
    kwargs = {"review_monitor": monitor} if monitor is not None else {}
    return panel_invoker._default_spawn(
        leg, "REVIEW BUNDLE BODY", repo_dir=repo,
        review_authorization=auth if auth is not None else _authorization(repo, tree=tree),
        canonical_repo_authority=repo, **kwargs,
    )


def _monitor(tmp_path: Path):
    return panel_invoker._ReviewMonitor(
        tmp_path / "monitor" / "seat-0.json", "inv", 0, threading.Event(),
    )


class _FakeExecutingBackend:
    """A conformant non-local backend that counts every call made to it."""

    name = "fakex"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _record(self, method: str):
        self.calls.append(method)

    def capabilities(self):
        self._record("capabilities")
        return frozenset({"inbound_closed"})

    def declaration(self):
        self._record("declaration")
        return sandbox_placement.Declaration()

    def available(self, request):
        self._record("available")
        return True

    def commit(self, prepared, request):
        self._record("commit")
        return sandbox_placement.BackendReceipt("committed", "fx-1", prepared.snapshot_sha256)

    def release(self, prepared):
        self._record("release")

    def execute(self, sandbox_ref, spec):
        self._record("execute")
        return sandbox_placement.BackendReceipt("launched", sandbox_ref, "0" * 64)

    def wait(self, sandbox_ref, deadline_s):
        self._record("wait")

    def cancel(self, sandbox_ref):
        self._record("cancel")

    def renew(self, sandbox_ref, until_s):
        self._record("renew")

    def list_owned(self, owner_id):
        self._record("list_owned")
        return []

    def kill(self, sandbox_ref):
        self._record("kill")


@pytest.fixture
def fake_backend():
    backend = _FakeExecutingBackend()
    sandbox_placement.register_backend("fakex", backend)
    try:
        yield backend
    finally:
        sandbox_placement._REGISTRY.pop("fakex", None)


# --- partial-failure ownership ---------------------------------------------------------


@pytest.mark.parametrize("fault", ["rename", "mark_as_sandbox", "digest"])
def test_prepare_owns_its_partial_stage_until_it_returns(tmp_path, monkeypatch, fault):
    """A fault after `stage_review_tree`, after the rename, or at `mark_as_sandbox` leaves
    no stage behind and propagates. Mutation: remove `prepare_local_stage`'s rollback."""
    repo = _repo(tmp_path)
    review_dir = tmp_path / "review"
    review_dir.mkdir()

    def boom(*args, **kwargs):
        raise OSError(f"injected {fault}")

    if fault == "rename":
        real_rename = Path.rename
        monkeypatch.setattr(
            Path, "rename",
            lambda self, target: boom() if Path(target).name == review_stage.REVIEW_STAGE_TREE_DIRNAME
            else real_rename(self, target),
        )
    elif fault == "mark_as_sandbox":
        monkeypatch.setattr(sandbox_retention, "mark_as_sandbox", boom)
    else:
        monkeypatch.setattr(review_stage, "review_tree_manifest_sha256", boom)

    with pytest.raises(OSError, match=f"injected {fault}"):
        sandbox_placement.prepare_local_stage(
            repo, review_dir, floor_bytes=0, mark=tmp_path,
        )
    assert list(review_dir.iterdir()) == [], "prepare left a partial stage behind"


def test_a_revalidation_failure_after_prepare_is_released(tmp_path, monkeypatch):
    """The `finally` releases a prepared stage when revalidation refuses it."""
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    released: list[Path] = []
    monkeypatch.setattr(
        sandbox_placement.LocalBackend, "release",
        lambda self, prepared: released.append(prepared.local_tree)
        or review_stage.remove_review_stage(prepared.local_tree),
    )
    launches: list[str] = []
    _setup_branch(monkeypatch, "exec_leg", launches)
    auth = dataclasses.replace(_authorization(repo), staged_tree_sha256="f" * 64)

    result = _spawn("codex", repo, auth=auth)

    assert result[0] == "DEGRADED" and launches == []
    assert len(released) == 1 and not released[0].exists()


# --- failure exits keep the evidence ---------------------------------------------------


@pytest.mark.parametrize("monitored", [False, True], ids=["no-monitor", "monitor"])
@pytest.mark.parametrize("branch", BRANCHES)
def test_an_egress_failure_after_prepare_keeps_the_placement(tmp_path, monkeypatch, branch, monitored):
    """Acceptance: the DEGRADED result of every branch, with or without a review monitor,
    carries the placement and a runtime-attested `prepared` receipt.
    Mutation: attach only when a broker exists."""
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    launches: list[str] = []
    _setup_branch(monkeypatch, branch, launches)
    monkeypatch.setattr(
        panel_invoker, "revalidate_review_isolation_authorization", lambda *a, **k: None,
    )
    _egress(monkeypatch, fail=True)

    result = _spawn(_branch_leg(branch), repo, monitor=_monitor(tmp_path) if monitored else None)

    assert result[0] == "DEGRADED" and launches == []
    evidence = result.sandbox_placement_evidence
    receipts = evidence["sandbox_placement_receipts"]
    assert [(r["step"], r["attested_by"]) for r in receipts] == [("prepared", "runtime")]
    assert receipts[0]["snapshot_sha256"] == review_stage.review_tree_manifest_sha256(repo)
    assert evidence["sandbox_placement_backend"] == "local"
    assert evidence["sandbox_local_provider_spawns"] == 0
    # It travels on its own attribute: a broker receipt it is not.
    assert "sandbox_placement_receipts" not in result.harden_isolation_evidence


def test_the_placement_reaches_the_panel_leg_result(tmp_path, monkeypatch):
    """Through the provider seam to the PanelLegResult the board returns."""
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    _setup_branch(monkeypatch, "exec_leg", [])
    _egress(monkeypatch, fail=True)
    result = panel_invoker._default_spawn_via_provider(
        "codex", "REVIEW BUNDLE BODY", repo_dir=repo,
        review_authorization=_authorization(repo), canonical_repo_authority=repo,
    )
    assert result[0] == "DEGRADED"
    receipts = result.sandbox_placement_evidence["sandbox_placement_receipts"]
    assert receipts[0]["step"] == "prepared"


# --- no stale facts --------------------------------------------------------------------


def test_no_facts_survive_into_the_next_leg_on_the_same_thread(tmp_path, monkeypatch):
    """Leg one fails at revalidation (after its facts are recorded); leg two fails inside
    `prepare`. Leg two must carry no sandbox facts. Mutation: reset only through the egress
    stack, which a leg that never reached egress never closes over its facts."""
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    _setup_branch(monkeypatch, "exec_leg", [])
    bad = dataclasses.replace(_authorization(repo), staged_tree_sha256="f" * 64)
    first = _spawn("codex", repo, auth=bad)
    assert first[0] == "DEGRADED" and first.sandbox_placement_evidence

    def boom(*args, **kwargs):
        raise OSError("injected stage failure")

    monkeypatch.setattr(review_stage, "stage_review_tree", boom)
    second = _spawn("codex", repo)
    assert second[0] == "DEGRADED"
    assert second.sandbox_placement_evidence == {}
    assert panel_invoker._sandbox_evidence() == {}


# --- spawn counter ---------------------------------------------------------------------


def test_the_spawn_counter_sees_helper_threads_and_copied_contexts():
    """A spawn from a copied context and from a helper thread handed the counter both count.
    Mutation: an integer ContextVar -- each copy then owns its own integer."""
    counter = panel_invoker._SpawnCounter()
    with panel_invoker._bind_spawn_counter(counter):
        copy_context().run(panel_invoker.run_provider, ["true"], check=True)

        def helper():
            with panel_invoker._bind_spawn_counter(counter):
                panel_invoker.run_provider(["true"], check=True)

        thread = threading.Thread(target=helper)
        thread.start()
        thread.join()
        panel_invoker.launch_provider(["true"]).wait()
    assert counter.count == 3


def test_a_degraded_record_after_a_spawn_reports_it(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    _egress(monkeypatch)

    def exec_leg(*args, **kwargs):
        panel_invoker.run_provider(["true"], check=True)
        raise RuntimeError("provider failed after it started")

    monkeypatch.setattr(panel_invoker, "_exec_leg", exec_leg)
    result = _spawn("codex", repo)
    assert result[0] == "DEGRADED"
    evidence = result.sandbox_placement_evidence
    assert evidence["sandbox_local_provider_spawns"] == 1
    assert [r["step"] for r in evidence["sandbox_placement_receipts"]] == ["prepared", "launched"]


# --- unregistered schemes never probe ---------------------------------------------------


@pytest.mark.parametrize("root", ["https://example.invalid/x", "e2b://t", "modal://t"])
def test_an_unregistered_scheme_is_never_probed(tmp_path, monkeypatch, root):
    """No ssh, no DNS, no socket during selection; the leg runs local with a recorded
    fallback. Mutation: route unknown schemes to `_probe_root`."""
    _env(monkeypatch, tmp_path, root=root)
    repo = _repo(tmp_path)
    launches: list[str] = []
    _setup_branch(monkeypatch, "exec_leg", launches)
    _egress(monkeypatch)
    effects: list[str] = []
    real_select = sandbox_policy.select_sandbox_root

    def select(*args, **kwargs):
        with monkeypatch.context() as spy:
            spy.setattr(subprocess, "run", lambda *a, **k: effects.append("run"))
            spy.setattr(subprocess, "Popen", lambda *a, **k: effects.append("Popen"))
            spy.setattr(socket, "getaddrinfo", lambda *a, **k: effects.append("getaddrinfo"))
            spy.setattr(socket.socket, "connect", lambda *a, **k: effects.append("connect"))
            spy.setattr(sandbox_policy, "_probe_root", lambda *a, **k: effects.append("probe"))
            return real_select(*args, **kwargs)

    monkeypatch.setattr(sandbox_policy, "select_sandbox_root", select)
    with pytest.warns(RuntimeWarning, match="not placeable"):
        result = _spawn("codex", repo)

    assert effects == []
    assert launches == ["exec_leg"]
    evidence = result.sandbox_placement_evidence
    scheme = root.split("://", 1)[0]
    assert evidence["sandbox_root_fell_back"] is True
    assert f"{scheme}://" in evidence["sandbox_root_reason"]
    assert evidence["sandbox_placement_backend"] == "local"


def test_with_nothing_configured_no_probe_runs(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sandbox_policy, "_probe_with_deadline",
        lambda *a, **k: pytest.fail("probed with no root configured"),
    )
    choice = sandbox_policy.select_sandbox_root(configured=None, fallback=tmp_path, floor_bytes=0)
    assert choice.fell_back is False and choice.scheme == "local"


# --- the execution gate ----------------------------------------------------------------


@pytest.mark.parametrize("knob", [None, "1"], ids=["knob-off", "knob-on"])
def test_the_execution_gate_commits_nothing_this_build_cannot_execute(
    tmp_path, monkeypatch, fake_backend, knob,
):
    """Acceptance: a conformant registered backend gets ZERO calls to `available`, `commit`
    and `execute`, with the knob off and on. Mutations: exempt by where placement came
    from; set `_NONLOCAL_EXECUTION_DRIVER = True` without an execute branch."""
    _env(monkeypatch, tmp_path, root="fakex://sandbox.example/p", knob=knob)
    repo = _repo(tmp_path)
    launches: list[str] = []
    _setup_branch(monkeypatch, "exec_leg", launches)
    _egress(monkeypatch)
    counters = _Counters(monkeypatch)
    staged = _spy_stage(monkeypatch)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = _spawn("codex", repo)

    assert fake_backend.calls == []
    if knob is None:
        assert launches == ["exec_leg"] and staged == ["stage"]
        evidence = result.sandbox_placement_evidence
        assert evidence["sandbox_root_fell_back"] is True
        assert "fakex" in evidence["sandbox_root_reason"]
        assert DRIVER in evidence["sandbox_root_reason"]
        assert evidence["sandbox_placement_backend"] == "local"
    else:
        assert result[0] == "DEGRADED" and result[-1] == REQUIRED
        assert launches == [] and staged == [] and counters.total == 0


# --- plugin failure --------------------------------------------------------------------


_PLUGIN_PROBE = r"""
import json, sys, warnings
from pathlib import Path
from phase_loop_runtime import panel_invoker, sandbox_placement, sandbox_policy

marker = Path(sys.argv[1])
out = {"after_import": marker.exists()}
none = sandbox_policy.select_sandbox_root(configured=None, fallback=sys.argv[2], floor_bytes=0)
out["after_unconfigured"] = marker.exists()
local = sandbox_policy.select_sandbox_root(configured=sys.argv[2], fallback=sys.argv[2], floor_bytes=0)
out["after_local_root"] = marker.exists()
with warnings.catch_warnings(record=True):
    warnings.simplefilter("always")
    broken = sandbox_policy.select_sandbox_root(
        configured="boomx://h/p", fallback=sys.argv[2], floor_bytes=0,
    )
out["after_configured"] = marker.exists()
out["fell_back"] = broken.fell_back
out["reason"] = broken.reason
out["local_still_local"] = sandbox_policy.select_sandbox_root(
    configured=None, fallback=sys.argv[2], floor_bytes=0,
).scheme
print(json.dumps(out))
"""


def test_a_broken_plugin_is_loaded_only_for_its_scheme_and_falls_back(tmp_path):
    """A broken entry point is never imported while no root (or a local root) is configured;
    configured, it is a pre-launch fallback naming its scheme. Mutation: load all entry
    points at import."""
    site = tmp_path / "site"
    dist = site / "boomx_backend-0.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: boomx-backend\nVersion: 0.0\n")
    (dist / "entry_points.txt").write_text(
        f"[{sandbox_placement.ENTRY_POINT_GROUP}]\nboomx = boomx_plugin:register\n"
    )
    marker = tmp_path / "imported"
    (site / "boomx_plugin.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n"
        "raise ImportError('broken plugin')\n"
    )
    src = Path(panel_invoker.__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(site), str(src)])}
    probe = subprocess.run(
        [sys.executable, "-c", _PLUGIN_PROBE, str(marker), str(tmp_path / "local")],
        capture_output=True, text=True, env=env, check=True,
    )
    out = json.loads(probe.stdout.strip().splitlines()[-1])
    assert out["after_import"] is False
    assert out["after_unconfigured"] is False
    assert out["after_local_root"] is False
    assert out["after_configured"] is True
    assert out["fell_back"] is True
    assert "boomx://" in out["reason"]
    assert "sandbox_placement_plugin_unavailable" in out["reason"]
    assert out["local_still_local"] == "local"


def test_a_broken_plugin_fails_closed_under_the_knob(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path, root="boomy://h/p", knob="1")
    repo = _repo(tmp_path)
    launches: list[str] = []
    _setup_branch(monkeypatch, "exec_leg", launches)

    def broken(scheme):
        raise sandbox_placement.PlacementUnavailable("sandbox_placement_plugin_unavailable")

    monkeypatch.setattr(sandbox_placement, "_load_plugins", broken)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = _spawn("codex", repo)
    assert result[-1] == REQUIRED and launches == []


# --- backend claims never apply --------------------------------------------------------


def _non_local_receipts(attested_by: str, *, ref: str = "fx-1", digest: str = "a" * 64):
    if attested_by == "runtime":
        make = sandbox_placement._runtime_receipt
        return [make("committed", ref, digest), make("completed", ref, digest)]
    return [
        sandbox_placement.PlacementReceipt.from_backend(
            sandbox_placement.BackendReceipt(step, ref, digest)
        )
        for step in ("committed", "completed")
    ]


def _applied(receipts, *, spawns: int = 0):
    return sandbox_placement.applied_rule(
        backend=_FakeExecutingBackend(), host="sandbox.example", path=Path("/p"),
        staged_at=Path("/stage/reviewed-tree"), receipts=receipts,
        authorization_sha256="a" * 64, local_spawns=spawns,
    )


def test_backend_claims_never_apply():
    """Acceptance, at derivation level (1a cannot reach a non-local placement end to end).
    Backend-attested `committed` and `completed` with the right ref and digest and zero
    spawns: NOT applied -- `attested_by` is the only guard. Mutation: ignore `attested_by`.
    Runtime receipts plus a disagreeing backend receipt: not applied, with its own reason.
    Mutation: ignore backend receipts."""
    applied, reason = _applied(_non_local_receipts("backend"))
    assert applied is False and "runtime-attested" in reason

    # The control: the same receipts attested by the runtime DO apply.
    assert _applied(_non_local_receipts("runtime")) == (True, None)
    # A local spawn on a remote placement does not.
    assert _applied(_non_local_receipts("runtime"), spawns=1)[0] is False

    for disagreeing in (
        sandbox_placement.BackendReceipt("completed", "fx-2", "a" * 64),
        sandbox_placement.BackendReceipt("completed", "fx-1", "b" * 64),
    ):
        receipts = _non_local_receipts("runtime") + [
            sandbox_placement.PlacementReceipt.from_backend(disagreeing)
        ]
        applied, reason = _applied(receipts)
        assert applied is False and reason == "the backend's receipts disagree with the runtime's"


def test_only_the_runtime_can_attest_a_receipt():
    with pytest.raises(ValueError):
        sandbox_placement.PlacementReceipt("committed", "fx-1", "a" * 64, "runtime")


# --- registry and self-declared honesty inputs ----------------------------------------


def test_registration_and_declarations_are_checked():
    """Mutations: accept the non-executing backend; accept the built-in scheme; keep the
    backend's method label."""

    class PlacementOnly:
        name = "half"

        def capabilities(self):
            return frozenset()

        def declaration(self):
            return sandbox_placement.Declaration()

        def available(self, request):
            return True

        def commit(self, prepared, request):
            return None

        def release(self, prepared):
            return None

    with pytest.raises(TypeError):
        sandbox_placement.register_backend("half", PlacementOnly())
    for scheme in ("local", "hostpath"):
        with pytest.raises(ValueError):
            sandbox_placement.register_backend(scheme, _FakeExecutingBackend())
    assert "half" not in sandbox_placement._REGISTRY

    verified = sandbox_placement.verified_from_backend(
        _FakeExecutingBackend(), {"inbound_closed": "runtime_end_to_end"},
    )
    assert verified == {"inbound_closed": "backend_attested"}
    with pytest.raises(sandbox_placement.PlacementUnavailable):
        sandbox_placement.verified_from_backend(
            _FakeExecutingBackend(), {"uid_isolated": "backend_attested"},
        )
    assert sandbox_placement.LocalBackend().capabilities() == frozenset()

    for bad in ("", "has space", "a/b", "x" * 129, "ref?q"):
        with pytest.raises(sandbox_placement.PlacementUnavailable):
            sandbox_placement.BackendReceipt("committed", bad, "a" * 64)


# --- fail closed -----------------------------------------------------------------------


def _hostpath_probe(monkeypatch, *, passes: bool) -> None:
    monkeypatch.setattr(sandbox_policy, "_probe_with_deadline", lambda *a, **k: passes)
    real = sandbox_policy._free_bytes_at
    monkeypatch.setattr(
        sandbox_policy, "_free_bytes_at",
        lambda location, timeout: 10**15 if location.host else real(location, timeout),
    )


FAIL_CLOSED_CASES = {
    "hostpath-reachable": dict(root="ai:/storage/sandboxes", probe=True),
    "hostpath-unreachable": dict(root="ai:/storage/sandboxes", probe=False),
    "unset": dict(root=None),
    "local-root": dict(root="LOCAL"),
    "unregistered-scheme": dict(root="e2b://t"),
    "no-authorized-tree": dict(root=None, tree=False),
    "sandbox-disabled": dict(root=None, tree=False, disabled=True),
    "unrecognised-knob": dict(root=None, knob="enable"),
}


@pytest.mark.parametrize("branch", BRANCHES)
@pytest.mark.parametrize("case", sorted(FAIL_CLOSED_CASES))
def test_the_knob_refuses_every_seat_leg_this_build_cannot_place_remotely(
    tmp_path, monkeypatch, case, branch,
):
    """Acceptance: under `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED`, each case ends with the
    fixed code, nothing staged and a spawn count of 0. Mutations: decide by `fell_back`;
    read an unrecognised value as off; drop the pre-`prepare` refusal (the launch-boundary
    backstop still refuses, but staging is then observed)."""
    spec = FAIL_CLOSED_CASES[case]
    root = spec.get("root")
    if root == "LOCAL":
        root = str(tmp_path / "local-root")
    _env(monkeypatch, tmp_path, root=root, knob=spec.get("knob", "1"))
    if spec.get("disabled"):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_DISABLE", "1")
    if "probe" in spec:
        _hostpath_probe(monkeypatch, passes=spec["probe"])
    repo = _repo(tmp_path)
    launches: list[str] = []
    _setup_branch(monkeypatch, branch, launches)
    egress: list[str] = []
    _egress(monkeypatch, calls=egress)
    counters = _Counters(monkeypatch)
    staged = _spy_stage(monkeypatch)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = _spawn(_branch_leg(branch), repo, tree=spec.get("tree", True))

    assert (result[0], result[-1]) == ("DEGRADED", REQUIRED)
    assert staged == [], "1a refuses before prepare"
    assert launches == [] and egress == []
    assert counters.total == 0


def test_the_knob_reads_its_value_fail_closed(monkeypatch):
    for on in ("1", "true", "YES", "On"):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", on)
        assert sandbox_policy.remote_required() is True
    for off in ("", "0", "false", "No", "OFF"):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", off)
        assert sandbox_policy.remote_required() is False
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED")
    assert sandbox_policy.remote_required() is False
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", "enable")
    with pytest.warns(RuntimeWarning, match="unrecognised"):
        assert sandbox_policy.remote_required() is True


def test_the_knob_leaves_a_non_seat_leg_alone(tmp_path, monkeypatch):
    """RD3 is seats only: an execute-mode leg is not governed."""
    _env(monkeypatch, tmp_path, knob="1")
    launches: list[str] = []
    _setup_branch(monkeypatch, "exec_leg", launches)
    panel_invoker._default_spawn("codex", "BUNDLE", repo_dir=tmp_path, mode="execute")
    assert launches == ["exec_leg"]


# --- no credential leaks ---------------------------------------------------------------


def test_a_credential_in_the_root_never_reaches_the_record(tmp_path, monkeypatch):
    """`https://u:t@h/p?k=v` is `https://h/p` in repr, asdict, warnings and the evidence.
    Mutation: redact only in `__str__`."""
    secret_root = "https://u:t0ps3cret@h.example/p?k=v4lue"
    location = sandbox_policy.parse_location(secret_root)
    for rendered in (str(location), repr(location), json.dumps(dataclasses.asdict(location), default=str)):
        assert "t0ps3cret" not in rendered and "v4lue" not in rendered and "u:" not in rendered
    assert str(location) == "https://h.example/p"

    _env(monkeypatch, tmp_path, root=secret_root)
    repo = _repo(tmp_path)
    _setup_branch(monkeypatch, "exec_leg", [])
    _egress(monkeypatch)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _spawn("codex", repo)
    rendered = json.dumps(result.sandbox_placement_evidence) + "".join(str(w.message) for w in caught)
    assert "https://h.example/p" in rendered
    assert "t0ps3cret" not in rendered and "v4lue" not in rendered


# --- vocabulary ------------------------------------------------------------------------


@pytest.mark.parametrize("code", [REQUIRED, DRIVER])
def test_both_codes_are_fixed_harness_detail_codes(code):
    """Mutation: remove either member -- the detail becomes the unknown-failure template."""
    assert code in panel_invoker._HARNESS_DETAIL_CODES
    failure = panel_invoker._exception_failure(
        sandbox_placement.PlacementUnavailable(code, "a reason that must not leak")
    )
    assert failure == code
    assert panel_invoker._finalize_leg_detail(failure) == code


# --- edge cases ------------------------------------------------------------------------


def test_a_drive_letter_root_is_local():
    location = sandbox_policy.parse_location("C:\\work\\sandboxes")
    assert location.host is None and location.scheme == "local"
    assert sandbox_policy.parse_location("ai:/storage").scheme == "hostpath"


def test_a_hostpath_record_keeps_its_fields_and_only_adds(tmp_path, monkeypatch):
    """The existing `host:path` record is identical; the placement fields are added."""
    _env(monkeypatch, tmp_path, root="ai:/storage/sandboxes")
    _hostpath_probe(monkeypatch, passes=True)
    repo = _repo(tmp_path)
    seen: dict[str, object] = {}

    def exec_leg(*args, **kwargs):
        seen.update(panel_invoker._sandbox_evidence())
        return 0, "ok", "log"

    monkeypatch.setattr(panel_invoker, "_exec_leg", exec_leg)
    _egress(monkeypatch)
    _spawn("codex", repo)
    legacy = {
        "sandbox_root_host", "sandbox_root_path", "sandbox_root_fell_back",
        "sandbox_root_reason", "sandbox_staged_at", "sandbox_root_applied",
        "sandbox_network_filtered", "sandbox_network_mechanism",
        "sandbox_network_unfiltered_reason", "sandbox_seat_identity",
        "sandbox_root_unapplied_reason",
    }
    added = {
        "sandbox_placement_backend", "sandbox_placement_receipts",
        "sandbox_placement_verified", "sandbox_local_provider_spawns",
        "sandbox_snapshot_sha256",
    }
    assert set(seen) == legacy | added
    assert seen["sandbox_root_host"] == "ai" and seen["sandbox_root_fell_back"] is False
    assert seen["sandbox_root_applied"] is False
    assert seen["sandbox_root_unapplied_reason"].startswith("the selected root is recorded")
    assert seen["sandbox_staged_at"].endswith(review_stage.REVIEW_STAGE_TREE_DIRNAME)
