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
    placement_lease,
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
            # Keep advisory legacy cleanup inside this test's owned roots too.
            legacy = tmp_path_factory.mktemp(f"{leg}-legacy")
            patch.setattr(sandbox_policy, "legacy_staging_root", lambda: legacy)
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


def test_local_equivalence_isolates_unrelated_legacy_cleanup(tmp_path, tmp_path_factory, monkeypatch):
    legacy = tmp_path / "unrelated-legacy"
    leftover = legacy / "pl-egress-ns-unready"
    leftover.mkdir(parents=True)
    (leftover / sandbox_egress.EGRESS_WORK_MARKER).touch()
    os.utime(leftover, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(sandbox_policy, "legacy_staging_root", lambda: legacy)

    record = _equivalence_record(tmp_path_factory, monkeypatch)

    assert leftover.is_dir(), "local-equivalence swept an unrelated legacy root"
    assert record == json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sandbox_policy.legacy_staging_root() == legacy
    panel_invoker._gc_stale_panel_scratch(root=legacy)
    assert not leftover.exists(), "the real sweep must still reclaim a stale unready holder"


# --- shared helpers for the falsifiers below -------------------------------------------

from contextvars import copy_context  # noqa: E402
import dataclasses  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import types  # noqa: E402
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

    def endpoint(self, root):
        self._record("endpoint")
        return None

    def admit(self, request, bound):
        self._record("admit")

    def commit(self, prepared, request, bound=None):
        self._record("commit")
        return sandbox_placement.BackendReceipt("committed", "fx-1", prepared.snapshot_sha256)

    def release(self, prepared, bound=None):
        self._record("release")

    def execute(self, sandbox_ref, spec, bound):
        self._record("execute")
        return sandbox_placement.BackendReceipt("launched", sandbox_ref, "0" * 64)

    def wait(self, sandbox_ref, wait_s):
        self._record("wait")

    def cancel(self, sandbox_ref, bound):
        self._record("cancel")

    def renew(self, sandbox_ref, until_s, bound):
        self._record("renew")

    def list_owned(self, owner_id, bound):
        self._record("list_owned")
        return []

    def kill(self, lease_id, bound):
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
    # The record names the AUTHORIZATION's digest; the receipt carries what was staged.
    evidence = result.sandbox_placement_evidence
    assert evidence["sandbox_snapshot_sha256"] == "f" * 64
    assert evidence["sandbox_placement_receipts"][0]["snapshot_sha256"] == (
        review_stage.review_tree_manifest_sha256(repo)
    )


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
    # A calling context that already holds facts (another test, or a careless caller): a
    # leg reports only what IT recorded, and restores the context it was called in.
    ambient = {"sandbox_network_filtered": True}
    token = panel_invoker._SANDBOX_ROUND_FACTS.set(ambient)
    try:
        bad = dataclasses.replace(_authorization(repo), staged_tree_sha256="f" * 64)
        first = _spawn("codex", repo, auth=bad)
        assert first[0] == "DEGRADED" and first.sandbox_placement_evidence
        assert first.sandbox_placement_evidence["sandbox_network_filtered"] is None
        assert panel_invoker._SANDBOX_ROUND_FACTS.get() is ambient

        def boom(*args, **kwargs):
            raise OSError("injected stage failure")

        monkeypatch.setattr(review_stage, "stage_review_tree", boom)
        second = _spawn("codex", repo)
        assert second[0] == "DEGRADED"
        assert second.sandbox_placement_evidence == {}
        assert panel_invoker._SANDBOX_ROUND_FACTS.get() is ambient
    finally:
        panel_invoker._SANDBOX_ROUND_FACTS.reset(token)


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
    with pytest.warns(RuntimeWarning, match="falling back"):
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
    probed: list[str] = []
    real_probe = sandbox_policy._probe_with_deadline
    monkeypatch.setattr(
        sandbox_policy, "_probe_with_deadline",
        lambda *a, **k: probed.append("probe") or real_probe(*a, **k),
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = _spawn(_branch_leg(branch), repo, tree=spec.get("tree", True))

    # agent-harness#1244: a brokered seat with no staged tree is refused before the knob is
    # asked (it would otherwise run toolless); it is refused all the same, with nothing staged.
    refused = ("seat_sandbox_not_staged" if not spec.get("tree", True) and branch == "brokered"
               else REQUIRED)
    assert (result[0], result[-1]) == ("DEGRADED", refused)
    assert staged == [], "1a refuses before prepare"
    assert probed == [], "nothing is probed for a leg the knob refuses"
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
        # agent-harness#1222 §5: the trusted host git that staged the tree.
        "host_git_executable", "host_git_version",
    }
    assert set(seen) == legacy | added
    assert seen["sandbox_root_host"] == "ai" and seen["sandbox_root_fell_back"] is False
    assert seen["sandbox_root_applied"] is False
    assert seen["sandbox_root_unapplied_reason"].startswith("the selected root is recorded")
    assert seen["sandbox_staged_at"].endswith(review_stage.REVIEW_STAGE_TREE_DIRNAME)


# --- round 1 (agent-harness#1246): infrastructure launches, teardown, root spellings ---


def test_network_helpers_cannot_attest_a_provider_launch(tmp_path, monkeypatch):
    """The egress namespace holder and its uplink start through the launch interface but
    are infrastructure: an uplink that dies before any provider runs records no provider
    spawn and no `launched` receipt. Mutation: count infrastructure launches."""
    import re

    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    launches: list[str] = []
    _setup_branch(monkeypatch, "exec_leg", launches)
    monkeypatch.setattr(panel_invoker, "revalidate_review_isolation_authorization",
                        lambda *a, **k: None)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: True)
    monkeypatch.setattr(sandbox_egress.time, "sleep", lambda _: None)
    real_popen = subprocess.Popen
    helpers: list[str] = []

    class Helper:
        returncode = 0

        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self, **kwargs):
            return 0

    def popen(argv, **kwargs):
        # The helpers are trusted absolute paths since agent-harness#1222: match by name.
        name = Path(argv[0]).name
        if name not in ("unshare", "slirp4netns"):
            return real_popen(argv, **kwargs)
        helpers.append(name)
        if name == "unshare":
            pid, ready = re.search(r"echo \$\$ > (\S+); \S*touch (\S+);", argv[-1]).groups()
            Path(pid).write_text("12345")
            Path(ready).touch()
        return Helper()

    monkeypatch.setattr(subprocess, "Popen", popen)
    result = _spawn("codex", repo, monitor=_monitor(tmp_path))
    assert result[0] == "DEGRADED" and launches == []
    assert helpers == ["unshare", "slirp4netns"]
    evidence = result.sandbox_placement_evidence
    assert evidence["sandbox_local_provider_spawns"] == 0
    assert [r["step"] for r in evidence["sandbox_placement_receipts"]] == ["prepared"]


def test_a_launch_that_fails_to_exec_is_not_a_spawn(tmp_path):
    """`launched` means a process the runtime started. Mutation: count before `Popen`."""
    counter = panel_invoker._SpawnCounter()
    missing = str(tmp_path / "no-such-binary")
    with panel_invoker._bind_spawn_counter(counter):
        with pytest.raises(OSError):
            panel_invoker.launch_provider([missing])
        with pytest.raises(OSError):
            panel_invoker.run_provider([missing])
        assert counter.count == 0
        panel_invoker.launch_provider(["true"]).wait()
        panel_invoker.run_provider(["true"], check=True)
    assert counter.count == 2


def test_an_egress_teardown_failure_does_not_taint_the_next_leg(tmp_path, monkeypatch):
    """However the leg exits -- even egress teardown raising -- its facts and its spawn
    counter are reset and its stage released. Mutation: reset after an unguarded close."""
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    _setup_branch(monkeypatch, "exec_leg", [])
    facts_token = panel_invoker._SANDBOX_ROUND_FACTS.set({})
    spawns_token = panel_invoker._LEG_SPAWNS.set(None)
    released: list[Path] = []
    real_release = sandbox_placement.LocalBackend.release
    monkeypatch.setattr(
        sandbox_placement.LocalBackend, "release",
        lambda self, prepared: released.append(prepared.local_tree) or real_release(self, prepared),
    )

    @contextlib.contextmanager
    def egress(*args, **kwargs):
        yield ("/usr/bin/env",)
        raise OSError("injected egress exit failure")

    def fail_stage(*args, **kwargs):
        raise OSError("injected prepare failure")

    monkeypatch.setattr(sandbox_egress, "isolated_network", egress)
    try:
        with pytest.raises(OSError, match="injected egress exit failure"):
            _spawn("codex", repo)
        assert len(released) == 1 and not released[0].exists()
        monkeypatch.setattr(review_stage, "stage_review_tree", fail_stage)
        second = _spawn("codex", repo)
        assert second[0] == "DEGRADED"
        assert second.sandbox_placement_evidence == {}
        assert panel_invoker._sandbox_evidence() == {}
        assert panel_invoker._LEG_SPAWNS.get() is None
    finally:
        panel_invoker._SANDBOX_ROUND_FACTS.reset(facts_token)
        panel_invoker._LEG_SPAWNS.reset(spawns_token)


_SECRET = "s3cr3t_pw"
_QUERY = "q_t0ken"

#: Every spelling of a credential-bearing root the round-1 board found, and their kin.
CREDENTIAL_SPELLINGS = [
    f"https://user:{_SECRET}@h.example/p?k={_QUERY}",
    f"HTTPS://user:{_SECRET}@h.example/p?k={_QUERY}#frag",
    f"  https://user:{_SECRET}@h.example/p?k={_QUERY}",
    f"\thttps://user:{_SECRET}@h.example/p?k={_QUERY}\n",
    f"local://user:{_SECRET}@h.example/p?k={_QUERY}",
    f"hostpath://user:{_SECRET}@h.example/p?k={_QUERY}",
    f"my_vendor://user:{_SECRET}@h.example/p?k={_QUERY}",
    f"https:/user:{_SECRET}@h.example/p",
    f"//user:{_SECRET}@h.example/p",
    f"user:{_SECRET}@h.example:/p",
    f"h.example:/p?token={_QUERY}",
    f"e2b://user:{_SECRET}@tmpl?k={_QUERY}",
    f"https://user:{_SECRET}@h.example:notaport/p",
    f"https://{_SECRET}@h.example/p",
    f" https://{_SECRET}@h.example/p",
    f"my_vendor://{_SECRET}@h.example/p",
    f"https:/{_SECRET}@h.example/p?x",
]


@pytest.mark.parametrize("root", CREDENTIAL_SPELLINGS)
def test_no_spelling_of_a_root_renders_its_credential(tmp_path, monkeypatch, root):
    """Strip; anything with `://` is a URL (a malformed or built-in scheme is a typed,
    never-probed refusal); a non-URL value carrying `user:secret@` or a query is refused;
    no warning, reason, path or probe argument ever sees the raw value. Mutations: no
    strip; URL detection by the anchored regex; render the configured value."""
    _env(monkeypatch, tmp_path, root=root)
    repo = _repo(tmp_path)
    _setup_branch(monkeypatch, "exec_leg", [])
    _egress(monkeypatch)
    probed: list[str] = []
    monkeypatch.setattr(
        sandbox_policy, "_probe_with_deadline",
        lambda location, timeout: probed.append(str(location)) or False,
    )
    location = sandbox_policy.parse_location(root)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _spawn("codex", repo)
    rendered = (
        json.dumps(result.sandbox_placement_evidence, default=str)
        + "".join(str(w.message) for w in caught)
        + "".join(probed)
        + str(location) + repr(location)
        + json.dumps(dataclasses.asdict(location), default=str)
    )
    assert _SECRET not in rendered and _QUERY not in rendered
    assert result.sandbox_placement_evidence["sandbox_root_fell_back"] is True


@pytest.mark.parametrize(("root", "code"), [
    ("local://h/p", "sandbox_root_scheme_builtin"),
    ("hostpath://h/p", "sandbox_root_scheme_builtin"),
    ("my_vendor://h/p", "sandbox_root_scheme_invalid"),
    ("u:pw@h:/p", "sandbox_root_unrecognised"),
    ("h:/p?x=1", "sandbox_root_unrecognised"),
])
def test_unusable_root_forms_are_typed_refusals_and_never_probed(tmp_path, monkeypatch, root, code):
    monkeypatch.setattr(
        sandbox_policy, "_probe_with_deadline",
        lambda *a, **k: pytest.fail("an unusable root was probed"),
    )
    with pytest.warns(RuntimeWarning, match=code):
        choice = sandbox_policy.select_sandbox_root(
            configured=root, fallback=tmp_path, floor_bytes=0,
        )
    assert choice.fell_back is True and code in choice.reason


def test_ordinary_roots_still_parse_as_before():
    assert sandbox_policy.parse_location("ai:/storage/sandboxes") == sandbox_policy.SandboxLocation(
        "ai", Path("/storage/sandboxes"), "hostpath",
    )
    assert sandbox_policy.parse_location("user@ai:/storage").host == "user@ai"
    assert sandbox_policy.parse_location("/srv/sandboxes").scheme == "local"
    windows = sandbox_policy.parse_location("C:\\Users\\a@b\\sandboxes")
    assert windows.scheme == "local" and windows.refusal is None
    url = sandbox_policy.parse_location(" https://h.example:8443/p ")
    assert (url.scheme, url.host, str(url)) == ("https", "h.example:8443", "https://h.example:8443/p")


# --- brokered and claude TUI success paths ---------------------------------------------


class _FakeBroker:
    """The parent broker's surface, running the provider adapter in a copied context the
    way the real serve thread does."""

    def __init__(self, *args, **kwargs) -> None:
        self.evidence: dict[str, object] = {}

    def run_credentialless_client(self, adapter, deadline_s=None, **kwargs):
        status, text = copy_context().run(adapter.invoke)
        return {"status": status, "text": text}, self.evidence

    def close(self) -> None:
        pass


def test_a_brokered_success_records_the_spawn_it_made(tmp_path, monkeypatch):
    """The brokered record is refreshed when it is serialized: a spawn after the pre-launch
    snapshot is in it, and the result carries the placement. Mutations: drop the refresh;
    pass no placement on the brokered success return."""
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    _egress(monkeypatch)
    monkeypatch.setattr(panel_invoker, "revalidate_review_isolation_authorization",
                        lambda *a, **k: None)
    monkeypatch.setattr(panel_invoker, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=1))
    monkeypatch.setattr(panel_invoker, "ParentUnixBroker", _FakeBroker)

    def exec_leg(*args, **kwargs):
        panel_invoker.run_provider(["true"], check=True)
        return 0, "a review\nAGREE", "log"

    # Installed as the PRODUCTION adapter too, so the brokered branch is the one taken.
    monkeypatch.setattr(panel_invoker, "_exec_leg", exec_leg)
    monkeypatch.setattr(panel_invoker, "_PRODUCTION_EXEC_LEG", exec_leg)
    result = _spawn("codex", repo)

    assert result[0] == "OK"
    assert result.harden_isolation_evidence["sandbox_local_provider_spawns"] == 1
    assert [r["step"] for r in result.harden_isolation_evidence["sandbox_placement_receipts"]] == [
        "prepared", "launched",
    ]
    assert result.sandbox_placement_evidence["sandbox_local_provider_spawns"] == 1


def test_a_claude_tui_success_carries_the_placement(tmp_path, monkeypatch):
    """Mutation: return the TUI result without `_with_placement`."""
    _env(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    _egress(monkeypatch)
    _setup_branch(monkeypatch, "claude_tui", [])
    result = _spawn("claude", repo)
    assert result[0] == "OK"
    assert result.sandbox_placement_evidence["sandbox_placement_backend"] == "local"


# --- named roots (agent-harness#1245 amendment) ----------------------------------------


def _user_config(monkeypatch, tmp_path: Path, body: str) -> None:
    home = tmp_path / "xdg"
    (home / "agent-harness").mkdir(parents=True)
    (home / "agent-harness" / "advisor-boards.toml").write_text(body, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_ROOT", raising=False)


def test_named_roots_are_tried_in_the_configured_order(tmp_path, monkeypatch):
    _user_config(monkeypatch, tmp_path, (
        '[sandbox]\n'
        'roots.extra = "modal://t"\n'
        f'roots.e2b = "e2b://user:{_SECRET}@tmpl"\n'
        'roots.self-hosted = "https://sandbox.example/p"\n'
    ))
    assert sandbox_policy.configured_roots() == (
        ("self-hosted", "https://sandbox.example/p"),
        ("e2b", f"e2b://user:{_SECRET}@tmpl"),
        ("extra", "modal://t"),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        choice = sandbox_policy.select_sandbox_root(
            fallback=tmp_path, floor_bytes=0, roots=sandbox_policy.configured_roots(),
        )
    assert choice.fell_back is True
    assert [part.split(":", 1)[0] for part in choice.reason.split("; ")] == [
        "self-hosted", "e2b", "extra",
    ]
    rendered = choice.reason + "".join(str(w.message) for w in caught)
    assert _SECRET not in rendered


def test_a_configured_order_wins_and_the_first_usable_root_is_chosen(tmp_path, monkeypatch, fake_backend):
    _user_config(monkeypatch, tmp_path, (
        '[sandbox]\norder = ["fake", "self-hosted"]\n'
        'roots.self-hosted = "https://sandbox.example/p"\n'
        'roots.fake = "fakex://h/p"\n'
    ))
    roots = sandbox_policy.configured_roots()
    assert [name for name, _ in roots] == ["fake", "self-hosted"]
    choice = sandbox_policy.select_sandbox_root(fallback=tmp_path, floor_bytes=0, roots=roots)
    assert (choice.fell_back, choice.scheme, choice.name) == (False, "fakex", "fake")
    # The execution gate passes over it, to the next root, and touches no backend method.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        gated = sandbox_policy.select_sandbox_root(
            fallback=tmp_path, floor_bytes=0, roots=roots, accept=panel_invoker._placement_gate,
        )
    assert gated.fell_back is True
    assert gated.reason.startswith(f"fake: fakex://h/p: {DRIVER}")
    assert fake_backend.calls == []


def test_the_single_root_is_an_alias_for_one_backend(tmp_path, monkeypatch):
    _user_config(monkeypatch, tmp_path, '[sandbox]\nroots.self-hosted = "https://h/p"\n')
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ROOT", "  e2b://tmpl  ")
    assert sandbox_policy.configured_roots() == ((None, "e2b://tmpl"),)


@pytest.mark.parametrize("body", [
    '[sandbox]\nroots = "https://h/p"\n',
    '[sandbox]\nroots.Bad_Name = "https://h/p"\n',
    '[sandbox]\nroots.ok = 3\n',
    '[sandbox]\norder = ["a", "a"]\n',
    '[sandbox]\nunknown = 1\n',
])
def test_a_malformed_sandbox_table_is_refused_not_ignored(tmp_path, monkeypatch, body):
    _user_config(monkeypatch, tmp_path, body)
    with pytest.raises(sandbox_policy.SandboxConfigError) as excinfo:
        sandbox_policy.configured_roots()
    assert str(excinfo.value) == "sandbox_config_invalid"


def test_named_roots_reach_the_leg(tmp_path, monkeypatch, fake_backend):
    """Through `_default_spawn`: the gate passes over a registered backend, the leg runs
    local, and the reason names the backend and the code."""
    _env(monkeypatch, tmp_path)
    _user_config(monkeypatch, tmp_path, '[sandbox]\nroots.self-hosted = "fakex://h/p"\n')
    repo = _repo(tmp_path)
    launches: list[str] = []
    _setup_branch(monkeypatch, "exec_leg", launches)
    _egress(monkeypatch)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = _spawn("codex", repo)
    assert launches == ["exec_leg"] and fake_backend.calls == []
    reason = result.sandbox_placement_evidence["sandbox_root_reason"]
    assert reason.startswith("self-hosted: fakex://h/p:") and DRIVER in reason


# --- the runner persists the placement --------------------------------------------------


def test_the_runner_persists_a_failed_legs_placement(tmp_path, monkeypatch):
    from test_president_wiring import _ruling, _runner_fixture, _stub_board_result

    from phase_loop_runtime import runner

    repo, run_dir, bundle = _runner_fixture(tmp_path)
    board = _stub_board_result(_ruling("FINDING F001: DEFERRED - ok\nFORCING DECISION: LAND"))
    placement = {"sandbox_placement_backend": "local", "sandbox_local_provider_spawns": 0}
    first = board.legs[0]
    object.__setattr__(first, "sandbox_placement_evidence", placement)
    first.status, first.usable, first.text = "DEGRADED", False, ""
    monkeypatch.setattr(panel_invoker, "invoke_board", lambda *a, **k: board)
    with contextlib.suppress(Exception):
        runner._run_legible_panel(repo, run_dir, "1" * 40, bundle)
    record = json.loads((run_dir / f"implementation-panel-{first.leg}.json").read_text())
    assert record["sandbox_placement_evidence"] == placement
    others = [p for p in run_dir.glob("implementation-panel-*.json") if first.leg not in p.name]
    assert all("sandbox_placement_evidence" not in json.loads(p.read_text()) for p in others)


# --- root-value parsing and [sandbox] validation (agent-harness#1246 president) --------


@pytest.mark.parametrize("separator", [" ", "\t", "\n"])
def test_a_named_root_value_is_parsed_strictly(tmp_path, monkeypatch, separator):
    password = f"synthetic{separator}password"
    root = f"user:{password}@host.invalid:/p"
    _user_config(monkeypatch, tmp_path, f'[sandbox]\nroots.self-hosted = "{root.encode("unicode_escape").decode()}"\n')
    assert sandbox_policy.configured_roots()[0][1] == root
    probes: list[str] = []
    monkeypatch.setattr(
        sandbox_policy, "_probe_with_deadline",
        lambda value, timeout: probes.append(value) or False,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        choice = sandbox_policy.select_sandbox_root(
            roots=sandbox_policy.configured_roots(), fallback=tmp_path, floor_bytes=0,
        )
    rendered = choice.reason + "".join(str(w.message) for w in caught)
    assert "password" not in rendered
    assert probes == []
    assert "sandbox_root_unrecognised" in choice.reason


def test_a_host_with_whitespace_is_refused():
    assert sandbox_policy.parse_location("bad host:/p").refusal == "sandbox_root_unrecognised"


def test_board_loading_refuses_a_malformed_sandbox_table(tmp_path):
    from phase_loop_runtime.advisor_board import config

    path = tmp_path / "advisor-boards.toml"
    path.write_text('[sandbox]\nroots = "https://h/p"\n', encoding="utf-8")
    with pytest.raises(config.BoardConfigError):
        config.load_boards(
            path, validate=False, is_available=lambda _: True, auth_ok=lambda _: True,
        )
    path.write_text('[sandbox]\nroots.self-hosted = "https://h/p"\n', encoding="utf-8")
    config.load_boards(path, validate=False, is_available=lambda _: True, auth_ok=lambda _: True)

# OSCOORD2 SL-0: ranked local uses fresh three-dimensional headroom and admission.
def _headroom(**changes):
    values = dict(memory_available_bytes=4 * 1024**3, load_per_cpu_percent=25,
                  live_sandboxes=0, observed_monotonic=sandbox_placement._monotonic())
    values.update(changes)
    return sandbox_placement.LocalHeadroom(**values)


def _reserved(**changes):
    return sandbox_placement.LocalAdmission(sandbox_placement.LocalReservation('test-slot'),
                                             _headroom(**changes))


def _ranked_walk(monkeypatch, *, readings=None, admission=None, roots=None):
    reading = _headroom() if readings is None else readings
    roots = sandbox_policy.candidate_roots([('local', '/stage')]) if roots is None else roots
    return _sl0_walk(roots, last_rung='none', required=frozenset(),
                settings=sandbox_policy.PlacementDriverSettings(0, 30, 4),
                local_capacity=lambda: reading,
                local_admit=admission or (lambda settings, bound: _reserved()))


def test_ranked_local_candidate_position():
    roots = sandbox_policy.candidate_roots([
        ('ai', 'drv://ai.invalid/stage'), ('local', '/stage'),
        ('overflow', 'drw://overflow.invalid/stage')])
    assert [root.scheme for root in roots] == ['drv', 'local', 'drw']


def test_capacity_then_local_with_headroom_before_overflow(tmp_path, monkeypatch):
    from test_placement_driver import FarSide, rungs, raises, CAPACITY
    far = FarSide('drv', None)
    far.behave['admit'] = raises(CAPACITY)
    monkeypatch.setitem(sandbox_placement._REGISTRY, 'drv', far)
    local = sandbox_policy.SandboxRootChoice(None, '/stage', False, scheme='local', name='local')
    admitted = []
    decision = _sl0_walk((*rungs('drv'), local, *rungs('missing')), last_rung='none',
                    settings=sandbox_policy.PlacementDriverSettings(0, 30, 4),
                    local_capacity=lambda: _headroom(),
                    local_admit=lambda settings, bound: admitted.append(True) or _reserved())
    assert decision.outcome == 'launching_host'
    assert admitted == [True]
    assert [entry['rung'] for entry in decision.trail] == ['r1', 'local']
    assert decision.trail[0]['code'] == CAPACITY


@pytest.mark.parametrize('changes', [
    {'memory_available_bytes': None}, {'load_per_cpu_percent': None},
    {'live_sandboxes': None}, {'observed_monotonic': -1000},
    {'memory_available_bytes': 0}, {'load_per_cpu_percent': 100},
    {'live_sandboxes': 4}, {'load_per_cpu_percent': float('nan')},
])
def test_ranked_local_refuses_unknown_stale_or_full(monkeypatch, changes):
    admitted = []
    decision = _ranked_walk(monkeypatch, readings=_headroom(**changes),
                            admission=lambda *args: admitted.append(True))
    assert decision.outcome == 'not_run'
    assert not admitted


def test_local_read_admit_race_never_uses_advisory_slot(monkeypatch):
    from test_placement_driver import raises, CAPACITY
    decision = _ranked_walk(monkeypatch, admission=raises(CAPACITY))
    assert decision.outcome == 'not_run'
    assert decision.trail[-1]['code'] == CAPACITY


def test_local_requires_authoritative_fresh_headroom(monkeypatch):
    decision = _ranked_walk(monkeypatch, admission=lambda *args: _reserved(live_sandboxes=4))
    assert decision.outcome == 'not_run'


def test_ranked_local_respects_remote_required(monkeypatch):
    monkeypatch.setenv('PHASE_LOOP_SANDBOX_REMOTE_REQUIRED', '1')
    assert _ranked_walk(monkeypatch).outcome == 'not_run'


def _sl0_walk(roots, *, local_capacity=None, local_admit=None, local_release=lambda handle: None, **kwargs):
    from test_placement_driver import prepared_stage, exec_spec
    prepared = prepared_stage(Path('/nonexistent/stage'))
    return sandbox_placement.place(
        roots, kwargs.pop('last_rung', 'none'), prepared,
        lambda root: sandbox_placement.PlacementRequest(
            'codex', 'codex:a', '/repo', prepared.snapshot_sha256, None,
            sandbox_placement.EgressNeeds()),
        placement_lease.open_lease, preflight=kwargs.get("preflight", lambda: None), seal=exec_spec,
        driver_enabled=True, cancelled=kwargs.get("cancelled", threading.Event()),
        local_capacity=local_capacity, local_admit=local_admit, local_release=local_release,
        settings=kwargs.get('settings'))


def test_local_refusal_overflows_only_after_authoritative_answer(monkeypatch):
    from test_placement_driver import FarSide, rungs, raises, CAPACITY
    backend = FarSide('drv', None)
    monkeypatch.setitem(sandbox_placement._REGISTRY, 'drv', backend)
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    decision = _sl0_walk((local, *rungs('drv')), local_capacity=lambda: _headroom(),
                    local_admit=raises(CAPACITY),
                    settings=sandbox_policy.PlacementDriverSettings(0, 30, 4))
    assert decision.outcome == 'placed'
    assert decision.trail[0]['code'] == CAPACITY
    sandbox_placement.run_placed(decision.placement, on_progress=None,
                                 cancelled=threading.Event())


def test_uncertain_local_admission_stops_overflow(monkeypatch):
    from test_placement_driver import raises, TIMEOUT, rungs
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    decision = _ranked_walk(monkeypatch, admission=raises(TIMEOUT), roots=(local, *rungs('missing')))
    assert decision.code == 'sandbox_placement_local_release_unconfirmed'
    assert len(decision.trail) == 1


@pytest.mark.parametrize('confirmed', [True, False])
def test_release_before_ranked_local(monkeypatch, confirmed):
    from test_placement_driver import FarSide, rungs, raises, REFUSED
    backend = FarSide('drv', None)
    backend.behave['commit'] = raises(REFUSED)
    events = []
    def kill(*args):
        events.append('kill')
        if not confirmed:
            raise RuntimeError('unconfirmed')
        backend.held.clear()
    backend.behave['kill'] = kill
    monkeypatch.setitem(sandbox_placement._REGISTRY, 'drv', backend)
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    decision = _sl0_walk((*rungs('drv'), local), local_capacity=lambda: _headroom(),
                    local_admit=lambda *args: events.append('local') or _reserved(),
                    settings=sandbox_policy.PlacementDriverSettings(0, 30, 4))
    assert decision.outcome == ('launching_host' if confirmed else 'not_run')
    assert events == (['kill', 'local'] if confirmed else ['kill'])


def test_capacity_then_full_local_then_overflow(monkeypatch):
    from test_placement_driver import FarSide, rungs, raises, CAPACITY
    full = FarSide('drv', None)
    overflow = FarSide('drw', None)
    full.behave['admit'] = raises(CAPACITY)
    monkeypatch.setitem(sandbox_placement._REGISTRY, 'drv', full)
    monkeypatch.setitem(sandbox_placement._REGISTRY, 'drw', overflow)
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    decision = _sl0_walk((*rungs('drv'), local, *rungs('drw')),
                         local_capacity=lambda: _headroom(memory_available_bytes=0),
                         local_admit=lambda *args: pytest.fail('full local admitted'),
                         settings=sandbox_policy.PlacementDriverSettings(0, 30, 4))
    assert decision.outcome == 'placed'
    assert [entry['code'] for entry in decision.trail[:2]] == [CAPACITY, CAPACITY]
    sandbox_placement.run_placed(decision.placement, on_progress=None, cancelled=threading.Event())


def test_missing_local_inventory_and_admission_refuse(monkeypatch):
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    assert _sl0_walk((local,)).outcome == 'not_run'


def test_local_authoritative_stale_reservation_releases_before_overflow(monkeypatch):
    from test_placement_driver import rungs
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    decision = _ranked_walk(monkeypatch, admission=lambda *args: _reserved(observed_monotonic=-1000),
                            roots=(local, *rungs('missing')))
    assert decision.code == 'sandbox_placement_backend_unregistered'
    assert len(decision.trail) == 2


@pytest.mark.parametrize('case', [
    'ok', 'stale', 'full', 'budget', 'cancel', 'raise', 'timeout',
    'release-fail', 'release-timeout', 'cancel-release-fail',
    'no-handle', 'missing-handle', 'invalid-handle', 'probe-raise', 'probe-timeout', 'probe-budget',
    'policy-refusal', 'reading-raise', 'probe-validation-budget',
])
def test_local_reservation_lifecycle_property(monkeypatch, case):
    """Grok r1: a slot is either launched, released, or explicitly uncertain.

    Advance the clock in both local calls, inject every local admission/release
    outcome, and observe held slots independently of the driver's result/trail.
    """
    from test_placement_driver import rungs
    sp = sandbox_placement
    clock = [100.0]
    monkeypatch.setattr(sp, '_monotonic', lambda: clock[0])
    monkeypatch.setattr(sp, 'ANSWER_BOUND_S', 0.02)
    cancelled, finish_release, released = threading.Event(), threading.Event(), threading.Event()
    held, calls, bounds = set(), [], []
    handle = sp.LocalReservation('review-slot')
    required = [False]
    monkeypatch.setattr(sandbox_policy, 'remote_required', lambda: required[0])

    class AdvancingReading(sp.LocalHeadroom):
        def admits(self, settings):
            clock[0] += 1
            return True

    class BrokenReading(sp.LocalHeadroom):
        def admits(self, settings):
            raise RuntimeError('malformed authoritative reading')

    def capacity():
        calls.append('capacity')
        if case == 'probe-raise':
            raise RuntimeError('unknown reading')
        if case == 'probe-timeout':
            finish_release.wait(1)
        if case == 'probe-budget':
            clock[0] += 1
        if case == 'probe-validation-budget':
            return AdvancingReading(4 * 1024**3, 25, 0, clock[0])
        return _headroom()

    def admit(settings, bound):
        calls.append('admit')
        bounds.append(bound)
        if case == 'no-handle':
            return _headroom(live_sandboxes=3)  # No slot was reserved.
        if case == 'missing-handle':
            return sp.LocalAdmission(None, _headroom())
        if case == 'invalid-handle':
            return sp.LocalAdmission(object(), _headroom())
        held.add(handle)
        if case == 'raise':
            raise RuntimeError('reply lost after reserve')
        if case == 'timeout':
            assert bound.cancelled.wait(1), 'abandoned admission was not cancelled'
        if case == 'budget':
            clock[0] += 1
        if case == 'policy-refusal':
            required[0] = True
        if case in {'cancel', 'cancel-release-fail'}:
            cancelled.set()
        changes = {}
        if case in {'stale', 'release-fail', 'release-timeout', 'cancel-release-fail'}:
            changes['observed_monotonic'] = 90
        if case == 'full':
            changes['memory_available_bytes'] = 0
        reading = (BrokenReading(4 * 1024**3, 25, 0, clock[0])
                   if case == 'reading-raise' else _headroom(**changes))
        return sp.LocalAdmission(handle, reading)

    def release(slot):
        assert slot is handle
        calls.append('release')
        if case in {'release-fail', 'cancel-release-fail'}:
            raise RuntimeError('release failed')
        if case == 'release-timeout':
            finish_release.wait(1)
        held.remove(slot)
        released.set()

    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    try:
        if case in {'cancel', 'cancel-release-fail'}:
            with pytest.raises(sp.PlacementCancelled) as caught:
                _sl0_walk((local, *rungs('missing')), local_capacity=capacity,
                          local_admit=admit, local_release=release, cancelled=cancelled,
                          settings=sandbox_policy.PlacementDriverSettings(0, 1, 4))
            assert calls == ['capacity', 'admit', 'release']
            assert bounds[0].cancelled.is_set()
            assert caught.value.trail[-1]['release_confirmed'] is (case == 'cancel')
            if case == 'cancel':
                assert not held
            else:
                assert caught.value.trail[-1]['code'] == sp._LOCAL_RELEASE_UNCONFIRMED
                assert caught.value.local_reservation is handle
            return
        decision = _sl0_walk((local, *rungs('missing')), local_capacity=capacity,
                             local_admit=admit, local_release=release, cancelled=cancelled,
                             settings=sandbox_policy.PlacementDriverSettings(0, 1, 4))
        if case == 'ok':
            assert decision.outcome == 'launching_host'
            assert decision.local_reservation is handle and held == {handle}
            assert calls == ['capacity', 'admit']
            release(decision.local_reservation)  # Caller owns cleanup after launch.
        elif case in {'raise', 'timeout', 'release-fail', 'release-timeout'}:
            assert decision.outcome == 'not_run'
            assert decision.code == sp._LOCAL_RELEASE_UNCONFIRMED
            assert decision.trail[-1]['code'] == sp._LOCAL_RELEASE_UNCONFIRMED
            assert len(decision.trail) == 1
            assert bounds[0].cancelled.is_set()
            if case == 'timeout':
                assert released.wait(1), 'late returned reservation was leaked'
                assert not held
            if case in {'raise', 'release-fail'}:
                assert held == {handle}
            if case in {'release-fail', 'release-timeout'}:
                assert decision.local_reservation is handle
                assert calls == ['capacity', 'admit', 'release']
        elif case in {'budget', 'probe-budget', 'probe-validation-budget'}:
            assert decision.code == 'sandbox_placement_budget_spent'
            assert len(decision.trail) == 1
            assert not held
            assert calls == (['capacity', 'admit', 'release'] if case == 'budget' else ['capacity'])
        elif case == 'policy-refusal':
            assert decision.code == 'sandbox_placement_required_unavailable'
            assert not held and calls == ['capacity', 'admit', 'release']
        else:
            assert decision.code == 'sandbox_placement_backend_unregistered'
            assert len(decision.trail) == 2  # Nothing held: continue to next ranked target.
            assert not held
            if case in {'stale', 'full', 'reading-raise'}:
                assert calls == ['capacity', 'admit', 'release']
            if case.startswith('probe-'):
                assert calls == ['capacity']
    finally:
        finish_release.set()
        if case == 'release-timeout':
            assert released.wait(1)


@pytest.mark.parametrize('missing', ['local_capacity', 'local_admit', 'local_release'])
def test_missing_local_hook_refuses_before_reserving(missing):
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    hooks = dict(local_capacity=lambda: pytest.fail('probe with a missing hook'),
                 local_admit=lambda *args: pytest.fail('admit with a missing hook'),
                 local_release=lambda handle: pytest.fail('release with nothing held'))
    hooks[missing] = None
    decision = _sl0_walk((local,), **hooks)
    assert decision.outcome == 'not_run'
    assert decision.local_reservation is None
    assert decision.code == 'sandbox_placement_refused'


def test_compatibility_local_preserves_budget_reason(monkeypatch):
    sp = sandbox_placement
    clock = [0.0]
    monkeypatch.setattr(sp, '_monotonic', lambda: clock[0])
    def capacity():
        clock[0] = 1.0
        return _headroom()
    result = _sl0_walk((), last_rung='local', local_capacity=capacity,
                       local_admit=lambda *args: pytest.fail('admit after budget'),
                       local_release=lambda handle: pytest.fail('nothing held'),
                       settings=sandbox_policy.PlacementDriverSettings(0, 1, 4))
    assert result.code == 'sandbox_placement_budget_spent'
    assert result.code == result.trail[-1]['code']


@pytest.mark.parametrize('case', ['success', 'no-handle', 'release-raises', 'release-hangs',
                                  'admit-raises', 'cancel-release-raises'])
def test_late_local_reservation_handoff(monkeypatch, case):
    """A late slot is released or retained, including abandoned cleanup workers."""
    sp = sandbox_placement
    monkeypatch.setattr(sp, 'ANSWER_BOUND_S', 0.02)
    admit_started, finish_admit = threading.Event(), threading.Event()
    finish_release, release_done = threading.Event(), threading.Event()
    cancelled = threading.Event()
    handle = sp.LocalReservation('late-slot')
    held = set()
    results = []

    def admit(settings, bound):
        admit_started.set()
        assert finish_admit.wait(2)
        if case == 'admit-raises':
            raise RuntimeError('admission failed without a handle')
        if case == 'no-handle':
            return sp.LocalAdmission(None, _headroom())
        held.add(handle)
        return sp.LocalAdmission(handle, _headroom())

    def release(slot):
        assert slot in held
        if case in {'release-raises', 'cancel-release-raises'}:
            raise RuntimeError('release failed')
        if case == 'release-hangs':
            assert finish_release.wait(2)
        held.remove(slot)
        release_done.set()

    def walk():
        try:
            results.append(_sl0_walk((), last_rung='local', local_capacity=_headroom,
                                     local_admit=admit, local_release=release,
                                     cancelled=cancelled))
        except sp.PlacementCancelled as exc:
            results.append(exc)

    worker = threading.Thread(target=walk)
    worker.start()
    try:
        assert admit_started.wait(1)
        if case == 'cancel-release-raises':
            cancelled.set()  # After admission starts, before its late release.
        worker.join(1)
        assert not worker.is_alive()
        result = results[0]
        if case == 'cancel-release-raises':
            assert isinstance(result, sp.PlacementCancelled)
        else:
            assert result.code == 'sandbox_placement_local_release_unconfirmed'
        pending = result.pending_local_reservation
        assert pending.inspect() == ('pending', None)
        assert pending.wait(0) == ('pending', None)
        finish_admit.set()
        expected = ('none_returned' if case in {'admit-raises', 'no-handle'} else
                    'released' if case == 'success' else 'retained')
        assert pending.wait(1) == (expected, handle if expected == 'retained' else None)
        assert held == ({handle} if expected == 'retained' else set())
    finally:
        finish_admit.set()
        finish_release.set()
        worker.join(1)
        if case == 'release-hangs':
            assert release_done.wait(1)
            assert pending.inspect() == ('retained', handle)


@pytest.mark.parametrize('budget_spent', [False, True])
def test_preflight_code_survives_compatibility_local_refusal(monkeypatch, budget_spent):
    sp = sandbox_placement
    clock = [0.0]
    monkeypatch.setattr(sp, '_monotonic', lambda: clock[0])

    def capacity():
        if budget_spent:
            clock[0] = 1.0
        return _headroom(memory_available_bytes=0)

    result = _sl0_walk((), last_rung='local',
                       preflight=lambda: 'seat_credential_below_floor',
                       local_capacity=capacity,
                       local_admit=lambda *args: pytest.fail('refused local admitted'),
                       settings=sandbox_policy.PlacementDriverSettings(0, 1, 4))
    assert result.code == 'seat_credential_below_floor'
    assert result.trail[-1]['code'] == ('sandbox_placement_budget_spent' if budget_spent
                                       else 'sandbox_placement_at_capacity')


def test_process_worker_cap_bounds_abandoned_local_releases(monkeypatch):
    """A full shared cap skips local without claiming a held reservation."""
    from test_placement_driver import FarSide, rungs

    sp = sandbox_placement
    limit = 3
    monkeypatch.setattr(sp, '_PROCESS_WORKERS', threading.BoundedSemaphore(limit))
    monkeypatch.setattr(sp, 'ANSWER_BOUND_S', 0.02)
    gates = [threading.Event() for _ in range(limit)]
    workers = []
    baseline = set(threading.enumerate())
    cleanup = object.__new__(sp._Walk)
    cleanup.settings = sandbox_policy.PlacementDriverSettings(0, 1, 4)

    def release(handle):
        workers.append(threading.current_thread())
        assert gates[int(handle.token)].wait(5)

    cleanup.local_release = release
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    admissions = []
    backend = FarSide('drv', None)
    monkeypatch.setitem(sp._REGISTRY, 'drv', backend)

    def admit(settings, bound):
        admissions.append(True)
        return sp.LocalAdmission(sp.LocalReservation('new'), _headroom())

    try:
        for index in range(limit):
            assert not cleanup._release_local(sp.LocalReservation(str(index)))
        assert len(workers) == limit
        refused = _sl0_walk((local, *rungs('drv')), local_capacity=_headroom,
                            local_admit=admit)
        assert refused.outcome == 'not_run'
        assert refused.trail[0]['code'] == 'sandbox_placement_at_capacity'
        assert len(refused.trail) == 2
        assert 'available' in backend.calls
        assert not backend.held
        assert refused.local_reservation is None
        assert refused.pending_local_reservation is None
        assert not admissions
        gates[0].set()
        workers[0].join(1)
        assert not workers[0].is_alive()
        accepted = _sl0_walk((local,), local_capacity=_headroom, local_admit=admit)
        assert accepted.outcome == 'launching_host'
        assert admissions == [True]
    finally:
        for gate in gates:
            gate.set()
        for worker in workers:
            worker.join(1)
        # Also join the successful walk's worker before restoring the shared quota.
        for worker in set(threading.enumerate()) - baseline:
            if worker.name == 'placement-call':
                worker.join(1)
                assert not worker.is_alive()
        assert all(not worker.is_alive() for worker in workers)


def test_saturated_compatibility_local_preserves_preflight_code(monkeypatch):
    sp = sandbox_placement
    monkeypatch.setattr(sp, '_PROCESS_WORKERS', threading.BoundedSemaphore(0))
    decision = _sl0_walk((), last_rung='local',
                        preflight=lambda: 'seat_credential_below_floor',
                        local_capacity=lambda: pytest.fail('saturated probe ran'),
                        local_admit=lambda *args: pytest.fail('saturated local admitted'))
    assert decision.code == 'seat_credential_below_floor'
    assert decision.trail[-1]['code'] == 'sandbox_placement_at_capacity'
    assert decision.local_reservation is None
    assert decision.pending_local_reservation is None


def test_saturated_local_release_stops_overflow_and_retains_handle(monkeypatch):
    from test_placement_driver import FarSide, rungs

    sp = sandbox_placement
    monkeypatch.setattr(sp, '_PROCESS_WORKERS', threading.BoundedSemaphore(1))
    handle = sp.LocalReservation('held-slot')
    backend = FarSide('drv', None)
    monkeypatch.setitem(sp._REGISTRY, 'drv', backend)
    local = sandbox_policy.candidate_roots([('local', '/stage')])[0]
    baseline = set(threading.enumerate())
    try:
        decision = _sl0_walk((local, *rungs('drv')), local_capacity=_headroom,
                            local_admit=lambda *args: sp.LocalAdmission(
                                handle, _headroom(memory_available_bytes=0)),
                            local_release=lambda slot: pytest.fail('saturated release ran'))
        assert decision.outcome == 'not_run'
        assert decision.code == 'sandbox_placement_local_release_unconfirmed'
        assert len(decision.trail) == 1
        assert decision.local_reservation is handle
        assert not backend.calls
    finally:
        for worker in set(threading.enumerate()) - baseline:
            if worker.name == 'placement-call':
                worker.join(1)
                assert not worker.is_alive()


@pytest.mark.parametrize('stage', ['queue', 'start', 'started'])
@pytest.mark.parametrize('failure', [RuntimeError, KeyboardInterrupt])
def test_call_startup_exceptions_roll_back_before_start_and_consume_after(monkeypatch, stage, failure):
    """Pre-start failures roll back; called-start failures consume permits fail-closed."""
    sp = sandbox_placement
    quota = threading.BoundedSemaphore(1)
    monkeypatch.setattr(sp, '_PROCESS_WORKERS', quota)

    class PublicationFailureCalls(sp._Calls):
        fail_publication = False

        def __setattr__(self, name, value):
            if name == '_jobs' and value is not None and self.fail_publication:
                self.fail_publication = False
                raise failure()
            super().__setattr__(name, value)

    calls = PublicationFailureCalls(settings=sandbox_policy.PlacementDriverSettings(0, 1, 1))
    calls.fail_publication = stage == 'started'
    started, failed_queues = [], []
    start = threading.Thread.start

    def injected_start(worker):
        if stage == 'start':
            failed_queues.append(worker._args[0])
            raise failure()  # No OS thread; every exception must still fail closed.
        start(worker)
        started.append(worker)
        # Post-start exceptions are injected at queue publication, after start
        # returns. No exception from start itself establishes failed creation.

    def broken_queue():
        raise failure()

    try:
        with monkeypatch.context() as patch:
            if stage == 'queue':
                patch.setattr(sp.queue, 'SimpleQueue', broken_queue)
            else:
                patch.setattr(threading.Thread, 'start', injected_start)
            expected = sp.PlacementUnavailable if failure is RuntimeError else failure
            with pytest.raises(expected):
                calls.ready()
        assert calls._jobs is None
        if stage == 'start':
            assert failed_queues[0].get_nowait() is None
            assert not quota.acquire(blocking=False)
            assert not calls._permits.acquire(blocking=False)
            with pytest.raises(sp.PlacementUnavailable):
                calls.ready()
            with pytest.raises(sp.PlacementUnavailable):
                sp._Calls().ready()
            return
        calls.close()
        for worker in started:
            worker.join(1)
            assert not worker.is_alive()
        assert quota.acquire(blocking=False)
        assert not quota.acquire(blocking=False)
        quota.release()
        # Recovery also proves the per-group permit was returned exactly once.
        with monkeypatch.context() as patch:
            def record_start(worker):
                start(worker)
                started.append(worker)
            patch.setattr(threading.Thread, 'start', record_start)
            assert calls.run(lambda: 'recovered', 1) == 'recovered'
    finally:
        calls.close()
        for worker in started:
            worker.join(1)
            assert not worker.is_alive()


@pytest.mark.parametrize('failure', [KeyboardInterrupt, MemoryError])
def test_interrupted_start_before_identity_keeps_permits_until_worker_exit(monkeypatch, failure):
    """A real OS thread exists before ident publication and the parent's startup wait interrupts."""
    sp = sandbox_placement
    quota = threading.BoundedSemaphore(1)
    monkeypatch.setattr(sp, '_PROCESS_WORKERS', quota)
    calls = sp._Calls(settings=sandbox_policy.PlacementDriverSettings(0, 1, 1))
    boot_entered, allow_identity = threading.Event(), threading.Event()
    serve_entered, allow_exit = threading.Event(), threading.Event()
    workers, queues, errors = [], [], []
    thread_type, serve = threading.Thread, sp._serve

    class DelayedIdentityThread(thread_type):
        def _set_ident(self):
            boot_entered.set()
            assert allow_identity.wait(5)
            super()._set_ident()

    def interrupted_wait(*args, **kwargs):
        assert boot_entered.wait(1)
        raise failure()

    def make_worker(*args, **kwargs):
        worker = DelayedIdentityThread(*args, **kwargs)
        queues.append(kwargs['args'][0])
        worker._started.wait = interrupted_wait
        workers.append(worker)
        return worker

    def paused_serve(*args):
        serve_entered.set()
        try:
            assert allow_exit.wait(5)
            serve(*args)
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(sp.threading, 'Thread', make_worker)
    monkeypatch.setattr(sp, '_serve', paused_serve)
    try:
        expected = sp.PlacementUnavailable if issubclass(failure, Exception) else failure
        with pytest.raises(expected):
            calls.ready()
        assert len(workers) == 1
        assert not quota.acquire(blocking=False), 'permit returned while OS thread is live'
        assert calls._jobs is None, 'uncertain worker remained attached to the group'
        jobs = queues[0]
        assert not calls._permits.acquire(blocking=False)
        with pytest.raises(sp.PlacementUnavailable):
            calls.ready()
        with pytest.raises(sp.PlacementUnavailable):
            sp._Calls().ready()
        assert len(workers) == 1, 'a second OS thread started under a cap of one'
        allow_identity.set()
        assert serve_entered.wait(1)
        assert not quota.acquire(blocking=False), 'permit returned before worker exit'
        allow_exit.set()
        workers[0].join(1)
        assert not workers[0].is_alive()
        assert jobs.empty(), 'worker did not consume the shutdown sentinel'
        assert not errors, 'worker over-released a semaphore'
        for permits in (quota, calls._permits):
            assert permits.acquire(blocking=False)
            assert not permits.acquire(blocking=False)
            permits.release()

        def make_fresh_worker(*args, **kwargs):
            worker = thread_type(*args, **kwargs)
            queues.append(kwargs['args'][0])
            workers.append(worker)
            return worker

        monkeypatch.setattr(sp.threading, 'Thread', make_fresh_worker)
        assert calls.run(lambda: 'fresh worker', 1) == 'fresh worker'
        assert len(workers) == 2
        calls.close()
        workers[1].join(1)
        assert not workers[1].is_alive()
        assert not errors
    finally:
        allow_identity.set()
        allow_exit.set()
        # Also clean up rollback mutations that fail to enqueue shutdown.
        for jobs in queues:
            jobs.put(None)
        if workers:
            assert serve_entered.wait(1)
        for worker in workers:
            worker.join(1)
            assert not worker.is_alive()
        calls.close()


def test_interrupt_between_worker_acquires_returns_group_permit(monkeypatch):
    sp = sandbox_placement

    class InterruptedQuota:
        def acquire(self, *, blocking):
            raise KeyboardInterrupt()

    monkeypatch.setattr(sp, '_PROCESS_WORKERS', InterruptedQuota())
    calls = sp._Calls(settings=sandbox_policy.PlacementDriverSettings(0, 1, 1))
    with pytest.raises(KeyboardInterrupt):
        calls.ready()
    assert calls._jobs is None
    assert calls._permits.acquire(blocking=False)
    assert not calls._permits.acquire(blocking=False)
    calls._permits.release()
