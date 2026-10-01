from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime.cli import main
from phase_loop_runtime.convergence.broker import live


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


def _probe(tmp_path: Path, repo: Path, *, history: Path | None = None) -> dict:
    return live.probe_zero_history_bootstrap(
        cutover_id="bootstrap-test",
        authority_root=tmp_path / "authority",
        worktrees=(repo,),
        legacy_roots=(tmp_path / "legacy",),
        historical_evidence_roots=(history,) if history else (),
        search_roots=(tmp_path,),
    )


@pytest.mark.parametrize("empty_bootstrap_roots", [False, True])
def test_explicit_roots_retain_authenticated_bootstrap_binding(
    tmp_path: Path, empty_bootstrap_roots: bool
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = (
        live.probe_zero_history_bootstrap(
            cutover_id="bootstrap-test",
            authority_root=tmp_path / "authority",
            worktrees=(known,),
        )
        if empty_bootstrap_roots
        else _probe(tmp_path, known)
    )
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    sealed_path = tmp_path / "authority" / "bootstrap-test.bootstrap-inventory.json"
    sealed_bytes = sealed_path.read_bytes()
    roots = (tmp_path / "additional-history",)

    receipt = live.onboard_zero_legacy_repository(
        fresh, roots=roots, authority_root=tmp_path / "authority"
    )

    assert receipt.cutover_id == inventory["cutover_id"]
    assert receipt.legacy_root_inventory == tuple(str(root) for root in roots)
    assert live._receipt_bootstrap_claim(receipt) == {
        "authority_root": tmp_path / "authority",
        "inventory_sha256": inventory["inventory_sha256"],
    }
    assert live._receipt_active_authority_exists(
        receipt, authority_root=tmp_path / "authority"
    )
    assert live.onboard_zero_legacy_repository(
        fresh, roots=roots, authority_root=tmp_path / "authority"
    ) == receipt
    assert sealed_path.read_bytes() == sealed_bytes
    report = live.fabpub_activation_barrier([fresh])
    try:
        assert report["repositories"] == [str(fresh)]
        assert live.WriterGenerationLatch.open(fresh).held_leases()
    finally:
        live.release_barrier_leases(report)
    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()


def test_explicit_roots_hold_bootstrap_and_history_locks_through_activation(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    roots = (tmp_path / "additional-history", tmp_path / "legacy")
    expected = {
        *live._bootstrap_seal_lock_paths(inventory),
        *(root / "fabpub-global-cutover" / "root.lock" for root in roots),
    }
    original_hold = live._hold_all
    original_proof = live._prove_zero_source
    held_sets = []
    boundaries = []

    @contextlib.contextmanager
    def observe_hold(paths):
        paths = tuple(paths)
        assert paths == tuple(sorted(set(paths), key=str))
        held_sets.append(set(paths))
        with original_hold(paths):
            yield

    def observe_proof(snapshot, scanned_roots, boundary):
        assert tuple(scanned_roots) == roots
        boundaries.append(boundary)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import fcntl,sys\n"
                "for path in sys.argv[1:]:\n"
                "    with open(path, 'a') as handle:\n"
                "        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                "        except BlockingIOError: pass\n"
                "        else: sys.exit(1)\n",
                *map(str, sorted(expected, key=str)),
            ],
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode()
        return original_proof(snapshot, scanned_roots, boundary)

    monkeypatch.setattr(live, "_hold_all", observe_hold)
    monkeypatch.setattr(live, "_prove_zero_source", observe_proof)
    live.onboard_zero_legacy_repository(
        fresh, roots=roots, authority_root=tmp_path / "authority"
    )
    assert held_sets[-1] == expected
    report = live.fabpub_activation_barrier([fresh])
    try:
        assert held_sets[-1] == expected
        assert boundaries == [
            "before_zero_source_proof",
            "before_receipt_write",
            "before_receipt_fsync",
            "after_receipt_write",
            "before_generation_lease",
        ]
    finally:
        live.release_barrier_leases(report)
    assert not any((str(path), threading.get_ident()) in live._LOCK_DEPTH for path in expected)


@pytest.mark.parametrize("alias_kind", ["dotdot", "relative", "symlink"])
def test_explicit_root_alias_does_not_double_acquire_bootstrap_lock(
    tmp_path: Path, alias_kind: str
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    canonical = tmp_path / "legacy"
    (tmp_path / "alias-parent").mkdir()
    if alias_kind == "dotdot":
        alias = tmp_path / "alias-parent" / ".." / "legacy"
    elif alias_kind == "relative":
        alias = Path("legacy")
    else:
        alias = tmp_path / "legacy-link"
        alias.symlink_to(canonical, target_is_directory=True)
    script = """
import sys
from pathlib import Path
from phase_loop_runtime.convergence.broker import live
fresh, root, authority = map(Path, sys.argv[1:4])
kind = sys.argv[4]
try:
    receipt = live.onboard_zero_legacy_repository(fresh, roots=(root,), authority_root=authority)
except live.LegacyCutoverConflict as error:
    assert kind != 'dotdot', str(error)
    assert ('absolute' if kind == 'relative' else 'symlink') in str(error)
    assert not live.repository_namespace_root(fresh).exists()
else:
    assert kind == 'dotdot'
    assert receipt.legacy_root_inventory == (str(root.resolve()),)
    locks = live._receipt_seal_lock_paths(receipt)
    assert len(locks) == len({path.resolve() for path in locks})
    report = live.fabpub_activation_barrier([fresh])
    try:
        assert live.WriterGenerationLatch.open(fresh).held_leases()
    finally:
        live.release_barrier_leases(report)
    assert not live.WriterGenerationLatch.open(fresh).held_leases()
print('alias boundary checked')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(fresh), str(alias),
         str(tmp_path / "authority"), alias_kind],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(live.__file__).resolve().parents[3])},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "alias boundary checked" in result.stdout


def test_relative_supplemental_root_is_refused_before_namespace(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    live.bootstrap_zero_history_authority(_probe(tmp_path, known), confirmed_zero_history=True)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(live.LegacyCutoverConflict, match="absolute"):
        live.onboard_zero_legacy_repository(
            fresh, roots=(Path("history"),), authority_root=tmp_path / "authority"
        )
    assert not live.repository_namespace_root(fresh).exists()


def test_absolute_supplemental_root_blocks_legacy_from_another_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    live.bootstrap_zero_history_authority(_probe(tmp_path, known), confirmed_zero_history=True)
    root = tmp_path / "history"
    live.onboard_zero_legacy_repository(
        fresh, roots=(root,), authority_root=tmp_path / "authority"
    )
    leaf = root / "legacy-train" / "legacy-repository"
    leaf.mkdir(parents=True)
    (leaf / "admissions.jsonl").write_text("{}\n", encoding="utf-8")
    other = tmp_path / "barrier-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    with pytest.raises(live.LegacyCutoverConflict, match="live legacy source"):
        live.fabpub_activation_barrier([fresh])
    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()
    assert not (other / "history").exists()


def test_relative_supplemental_root_in_historical_receipt_blocks_other_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    operator = tmp_path / "operator-cwd"
    operator.mkdir()
    monkeypatch.chdir(operator)
    roots = (Path("history"),)
    locks = {*live._bootstrap_seal_lock_paths(inventory),
             *live._zero_source_seal_lock_paths(roots, tmp_path / "authority")}
    with live._hold_all(sorted(locks, key=str)):
        receipt = live._onboard_zero_legacy_repository_under_seal(
            fresh, cutover_id=inventory["cutover_id"], roots=roots,
            authority_root=tmp_path / "authority",
            bootstrap_inventory_sha256=inventory["inventory_sha256"],
            bootstrap_authority_root=tmp_path / "authority",
        )
    assert receipt.legacy_root_inventory == ("history",)
    leaf = operator / "history" / "legacy-train" / "legacy-repository"
    leaf.mkdir(parents=True)
    (leaf / "admissions.jsonl").write_text("{}\n", encoding="utf-8")
    other = tmp_path / "barrier-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    with pytest.raises(live.LegacyCutoverConflict, match="absolute"):
        live.fabpub_activation_barrier([fresh])
    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()
    assert not (other / "history").exists()


def test_historical_dotdot_receipt_scans_canonical_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(tmp_path / "authority"))
    parent = tmp_path / "alias-parent"
    parent.mkdir()
    alias = parent / ".." / "history"
    roots = (alias,)
    locks = {*live._bootstrap_seal_lock_paths(inventory),
             *live._zero_source_seal_lock_paths(roots, tmp_path / "authority")}
    with live._hold_all(sorted(locks, key=str)):
        receipt = live._onboard_zero_legacy_repository_under_seal(
            fresh, cutover_id=inventory["cutover_id"], roots=roots,
            authority_root=tmp_path / "authority",
            bootstrap_inventory_sha256=inventory["inventory_sha256"],
            bootstrap_authority_root=tmp_path / "authority",
        )
    assert receipt.legacy_root_inventory == (str(alias),)
    receipt_path = live.repository_snapshot(fresh).store_root / live.RECEIPT_FILENAME
    sealed_receipt = receipt_path.read_bytes()
    parent.rename(tmp_path / "moved-alias-parent")
    leaf = tmp_path / "history" / "legacy-train" / "legacy-repository"
    leaf.mkdir(parents=True)
    (leaf / "admissions.jsonl").write_text("{}\n", encoding="utf-8")
    assert not alias.exists()
    report = None
    try:
        with pytest.raises(live.LegacyCutoverConflict, match="live legacy source"):
            report = live.fabpub_activation_barrier([fresh])
    finally:
        if report is not None:
            live.release_barrier_leases(report)
    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()
    assert receipt_path.read_bytes() == sealed_receipt
    assert not parent.exists()


def test_barrier_bootstrap_appearance_refuses_before_namespace(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(tmp_path / "authority"))
    monkeypatch.setenv(live.FABPUB_LEGACY_ROOTS_ENV, str(tmp_path / "legacy"))
    original = live._active_bootstrap_inventory
    checked = False

    def activate_after_initial_read(authority_root=None):
        nonlocal checked
        observed = original(authority_root)
        if not checked:
            checked = True
            assert observed is None
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
        return observed

    monkeypatch.setattr(live, "_active_bootstrap_inventory", activate_after_initial_read)
    report = None
    try:
        with pytest.raises(live.LegacyCutoverConflict, match="bootstrap changed"):
            report = live.fabpub_activation_barrier([fresh])
    finally:
        if report is not None:
            live.release_barrier_leases(report)
    assert checked
    assert not live.repository_namespace_root(fresh).exists()


def test_existing_receipt_guards_bootstrap_reappearance_before_lease(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    history = tmp_path / "additional-history"
    receipt = live.onboard_zero_legacy_repository(
        fresh, roots=(history,), authority_root=tmp_path / "authority"
    )
    pointer = tmp_path / "authority" / "ACTIVE_BOOTSTRAP"
    pointer_bytes = pointer.read_bytes()
    pointer.unlink()
    original_authority_check = live._receipt_active_authority_exists
    writer_results = []

    def restore_bootstrap_before_authority_check(value, authority_root=None):
        script = (
            "import fcntl,sys\n"
            "from pathlib import Path\n"
            "with open(sys.argv[1], 'a') as lock:\n"
            "    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "    except BlockingIOError: raise SystemExit(2)\n"
            "    Path(sys.argv[2]).write_bytes(bytes.fromhex(sys.argv[3]))\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path / "authority" / "bootstrap.lock"),
                str(pointer),
                pointer_bytes.hex(),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        writer_results.append(result.returncode)
        return original_authority_check(value, authority_root=authority_root)

    monkeypatch.setattr(
        live, "_receipt_active_authority_exists", restore_bootstrap_before_authority_check
    )
    report = None
    try:
        with pytest.raises(
            live.LegacyCutoverConflict, match="no matching global ACTIVE authority"
        ):
            report = live.fabpub_activation_barrier([fresh])
    finally:
        if report is not None:
            live.release_barrier_leases(report)

    assert writer_results == [2]
    assert set(live._receipt_seal_lock_paths(receipt)) == {
        tmp_path / "authority" / "bootstrap.lock",
        history / "fabpub-global-cutover" / "root.lock",
    }
    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()


def test_existing_receipt_revalidates_bootstrap_lock_set_after_acquisition(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    receipt = live.onboard_zero_legacy_repository(
        fresh,
        roots=(tmp_path / "additional-history",),
        authority_root=tmp_path / "authority",
    )
    pointer = tmp_path / "authority" / "ACTIVE_BOOTSTRAP"
    pointer_bytes = pointer.read_bytes()
    pointer.unlink()
    original_lock_paths = live._receipt_seal_lock_paths
    reads = 0

    def activate_after_initial_lock_discovery(value):
        nonlocal reads
        paths = original_lock_paths(value)
        reads += 1
        if reads == 1:
            with live._reentrant_flock(tmp_path / "authority" / "bootstrap.lock"):
                pointer.write_bytes(pointer_bytes)
        return paths

    monkeypatch.setattr(live, "_receipt_seal_lock_paths", activate_after_initial_lock_discovery)
    report = None
    try:
        with pytest.raises(
            live.LegacyCutoverConflict, match="different authority while entering the barrier"
        ):
            report = live.fabpub_activation_barrier([fresh])
    finally:
        if report is not None:
            live.release_barrier_leases(report)

    assert reads == 2
    assert live._receipt_active_authority_exists(receipt)
    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()


def test_absent_bootstrap_appearing_before_seal_refuses_before_namespace(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    original = live.global_active_authority_exists
    activated = False

    def activate_before_authority_check(roots=None, *, authority_root=None):
        nonlocal activated
        if not activated:
            activated = True
            live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
        return original(roots, authority_root=authority_root)

    monkeypatch.setattr(live, "global_active_authority_exists", activate_before_authority_check)
    with pytest.raises(live.LegacyCutoverConflict, match="bootstrap changed"):
        live.onboard_zero_legacy_repository(
            fresh, roots=(tmp_path / "history",), authority_root=tmp_path / "authority"
        )
    assert activated
    assert not live.repository_namespace_root(fresh).exists()


def test_traditional_scan_guards_bootstrap_slot_when_absent(tmp_path: Path, monkeypatch) -> None:
    fresh = _git_repo(tmp_path / "fresh")
    root = tmp_path / "traditional"
    authority = root / "fabpub-global-cutover"
    authority.mkdir(parents=True)
    cutover_id = "traditional-only"
    (authority / "ACTIVE_CUTOVER").write_text(cutover_id + "\n", encoding="utf-8")
    (authority / f"{cutover_id}.journal.jsonl").write_text(
        json.dumps({"cutover_id": cutover_id, "state": "ACTIVE"}) + "\n",
        encoding="utf-8",
    )
    original = live._prove_zero_source
    boundaries = []
    guard = tmp_path / "authority" / "bootstrap.lock"

    def observe_guard(snapshot, roots, boundary):
        result = subprocess.run(
            [sys.executable, "-c",
             "import fcntl,sys\n"
             "with open(sys.argv[1], 'a') as handle:\n"
             "    try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
             "    except BlockingIOError: pass\n"
             "    else: sys.exit(1)\n", str(guard)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        boundaries.append(boundary)
        return original(snapshot, roots, boundary)

    monkeypatch.setattr(live, "_prove_zero_source", observe_guard)
    receipt = live.onboard_zero_legacy_repository(
        fresh, cutover_id=cutover_id, roots=(root,), authority_root=tmp_path / "authority"
    )
    assert boundaries
    assert live._receipt_bootstrap_claim(receipt) is None
    assert not (tmp_path / "authority" / "ACTIVE_BOOTSTRAP").exists()


@pytest.mark.parametrize("authority_name", ["a-authority", "z-authority"])
def test_traditional_barrier_guards_complete_lock_set_before_onboarding(
    tmp_path: Path, monkeypatch, authority_name: str
) -> None:
    fresh = _git_repo(tmp_path / "fresh")
    root = tmp_path / "m-traditional"
    authority = root / "fabpub-global-cutover"
    authority.mkdir(parents=True)
    cutover_id = "traditional-only"
    (authority / "ACTIVE_CUTOVER").write_text(json.dumps({
        "cutover_id": cutover_id, "primary_authority": str(authority),
        "root_set_sha256": live._root_set_digest((root,)),
    }), encoding="utf-8")
    (authority / f"{cutover_id}.journal.jsonl").write_text(
        json.dumps({"cutover_id": cutover_id, "state": "ACTIVE"}) + "\n",
        encoding="utf-8",
    )
    bootstrap_root = tmp_path / authority_name
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(bootstrap_root))
    monkeypatch.setenv(live.FABPUB_LEGACY_ROOTS_ENV, str(root))
    expected = live._zero_source_seal_lock_paths((root,), bootstrap_root)
    original_onboard = live.onboard_zero_legacy_repository
    original_lock = live._reentrant_flock
    entered = []

    @contextlib.contextmanager
    def observe_lock(path):
        with original_lock(path):
            entered.append(path)
            yield

    def assert_initial_locks(worktree, **kwargs):
        assert tuple(entered) == expected
        result = subprocess.run(
            [sys.executable, "-c", "import fcntl,sys\n"
             "for path in sys.argv[1:]:\n"
             "    with open(path, 'a') as handle:\n"
             "        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
             "        except BlockingIOError: pass\n"
             "        else: sys.exit(1)\n", *map(str, expected)],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        return original_onboard(worktree, **kwargs)

    monkeypatch.setattr(live, "_reentrant_flock", observe_lock)
    monkeypatch.setattr(live, "onboard_zero_legacy_repository", assert_initial_locks)
    report = live.fabpub_activation_barrier([fresh])
    try:
        assert report["repositories"] == [str(fresh)]
        assert live.WriterGenerationLatch.open(fresh).held_leases()
    finally:
        live.release_barrier_leases(report)
    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()
    assert not (bootstrap_root / "ACTIVE_BOOTSTRAP").exists()


def test_traditional_barrier_declared_alias_does_not_self_deadlock(
    tmp_path: Path, monkeypatch
) -> None:
    fresh = _git_repo(tmp_path / "fresh")
    root = tmp_path / "traditional"
    authority = root / "fabpub-global-cutover"
    authority.mkdir(parents=True)
    cutover_id = "traditional-only"
    (authority / "ACTIVE_CUTOVER").write_text(cutover_id + "\n", encoding="utf-8")
    (authority / f"{cutover_id}.journal.jsonl").write_text(
        json.dumps({"cutover_id": cutover_id, "state": "ACTIVE"}) + "\n",
        encoding="utf-8",
    )
    parent = tmp_path / "alias-parent"
    parent.mkdir()
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(tmp_path / "authority"))
    monkeypatch.setenv(live.FABPUB_LEGACY_ROOTS_ENV, str(parent / ".." / "traditional"))
    script = """
import sys
from phase_loop_runtime.convergence.broker import live
report = live.fabpub_activation_barrier([sys.argv[1]])
try:
    assert report['repositories'] == [sys.argv[1]]
    assert live.WriterGenerationLatch.open(sys.argv[1]).held_leases()
finally:
    live.release_barrier_leases(report)
assert live.WriterGenerationLatch.open(sys.argv[1]).held_leases() == ()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(fresh)], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(live.__file__).resolve().parents[3])},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_explicit_roots_reject_conflicting_bootstrap_cutover_before_mutation(
    tmp_path: Path,
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    with pytest.raises(live.LegacyCutoverConflict, match="may not onboard receipt"):
        live.onboard_zero_legacy_repository(
            fresh,
            cutover_id="different-cutover",
            roots=(tmp_path / "additional-history",),
            authority_root=tmp_path / "authority",
        )

    assert not live.repository_namespace_root(fresh).exists()


def test_explicit_roots_refuse_bootstrap_binding_drift_before_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    original_active = live._active_bootstrap_inventory
    reads = 0

    def drift_after_initial_read(authority_root=None):
        nonlocal reads
        active = original_active(authority_root)
        reads += 1
        if reads > 1 and active is not None:
            return {**active, "inventory_sha256": "0" * 64}
        return active

    monkeypatch.setattr(live, "_active_bootstrap_inventory", drift_after_initial_read)
    with pytest.raises(live.LegacyCutoverConflict, match="bootstrap changed"):
        live.onboard_zero_legacy_repository(
            fresh,
            roots=(tmp_path / "additional-history",),
            authority_root=tmp_path / "authority",
        )

    assert not live.repository_namespace_root(fresh).exists()


@pytest.mark.parametrize("interrupted", [False, True])
def test_explicit_roots_refuse_changed_history_coverage_on_retry(
    tmp_path: Path, monkeypatch, interrupted: bool
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    roots = (tmp_path / "additional-history",)
    original_proof = live._prove_zero_source

    def interrupt_before_receipt(snapshot, scanned_roots, boundary):
        result = original_proof(snapshot, scanned_roots, boundary)
        if boundary == "before_receipt_write":
            raise live.LegacyCutoverConflict("interrupted before receipt")
        return result

    with monkeypatch.context() as patcher:
        if interrupted:
            patcher.setattr(live, "_prove_zero_source", interrupt_before_receipt)
            with pytest.raises(live.LegacyCutoverConflict, match="interrupted"):
                live.onboard_zero_legacy_repository(
                    fresh, roots=roots, authority_root=tmp_path / "authority"
                )
        else:
            live.onboard_zero_legacy_repository(
                fresh, roots=roots, authority_root=tmp_path / "authority"
            )
    namespace = live.repository_namespace_root(fresh)
    onboarding = namespace / "zero-legacy-onboarding"
    before = {path.name: path.read_bytes() for path in onboarding.iterdir() if path.is_file()}

    with pytest.raises(live.LegacyCutoverConflict, match="history coverage"):
        live.onboard_zero_legacy_repository(
            fresh,
            roots=(tmp_path / "different-history",),
            authority_root=tmp_path / "authority",
        )

    assert {path.name: path.read_bytes() for path in onboarding.iterdir() if path.is_file()} == before
    if interrupted:
        assert not (namespace / live.RECEIPT_FILENAME).exists()
    else:
        assert live.load_partition_receipt(live.repository_snapshot(fresh).store_root) is not None


@pytest.mark.parametrize("after_onboarding", [False, True])
def test_explicit_roots_refuse_real_supplemental_legacy_evidence(
    tmp_path: Path, after_onboarding: bool
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    root = tmp_path / "additional-history"
    if after_onboarding:
        live.onboard_zero_legacy_repository(
            fresh, roots=(root,), authority_root=tmp_path / "authority"
        )
    leaf = root / "legacy-train" / "legacy-repository"
    leaf.mkdir(parents=True)
    (leaf / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="live legacy source"):
        if after_onboarding:
            live.fabpub_activation_barrier([fresh])
        else:
            live.onboard_zero_legacy_repository(
                fresh, roots=(root,), authority_root=tmp_path / "authority"
            )

    assert live.WriterGenerationLatch.open(fresh).held_leases() == ()
    if not after_onboarding:
        assert not (live.repository_namespace_root(fresh) / live.RECEIPT_FILENAME).exists()


def test_zero_history_bootstrap_requires_confirmation_without_mutation(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)

    with pytest.raises(live.LegacyCutoverConflict, match="explicit confirmation"):
        live.bootstrap_zero_history_authority(inventory)

    assert not (tmp_path / "authority").exists()
    assert not live.repository_namespace_root(repo).exists()


def test_zero_history_bootstrap_reprobes_then_activates_and_retries(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    history = tmp_path / "historical"
    history.mkdir()
    (history / "admissions.jsonl").write_text(
        json.dumps({"epoch": 1, "request": {}, "sequence": 1}) + "\n",
        encoding="utf-8",
    )
    (history / "evidence.jsonl").write_text(
        json.dumps({"idempotency_key": "old", "state": "completed"}) + "\n",
        encoding="utf-8",
    )
    inventory = _probe(tmp_path, repo, history=history)

    first = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )
    second = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )

    assert first == second
    assert first["state"] == "ACTIVE"
    assert live.global_active_authority_exists(
        authority_root=tmp_path / "authority"
    )
    snapshot = live.repository_snapshot(repo)
    receipt = live.load_partition_receipt(snapshot.store_root)
    assert receipt is not None and receipt.zero_source
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "ACTIVE"
    assert not (tmp_path / "legacy" / "RETIRED").exists()
    assert not (tmp_path / "legacy" / "legacy-archive").exists()
    assert history.exists()

    with (history / "evidence.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"state": "late"}) + "\n")
    with pytest.raises(live.LegacyCutoverConflict, match="historical evidence bytes changed"):
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)


def test_zero_history_bootstrap_supports_existing_empty_legacy_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    (tmp_path / "legacy").mkdir()
    inventory = _probe(tmp_path, repo)

    first = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )
    second = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )

    assert first == second
    assert live.load_partition_receipt(live.repository_snapshot(repo).store_root) is not None
    assert (tmp_path / "legacy" / "fabpub-global-cutover" / "root.lock").exists()


def test_zero_history_bootstrap_refuses_probe_apply_drift(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    history = tmp_path / "historical"
    history.mkdir()
    evidence = history / "evidence.jsonl"
    evidence.write_text(json.dumps({"state": "completed"}) + "\n", encoding="utf-8")
    inventory = _probe(tmp_path, repo, history=history)
    evidence.write_text(json.dumps({"state": "changed"}) + "\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="changed between probe and apply"):
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    assert live.load_partition_receipt(live.repository_snapshot(repo).store_root) is None


def test_zero_history_bootstrap_revalidates_after_drain_before_active(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_record = live._record_bootstrap_state

    def inject_allocator_after_drain(journal, cutover_id, state):
        original_record(journal, cutover_id, state)
        if state == "DRAINING":
            legacy = tmp_path / "legacy"
            legacy.mkdir(exist_ok=True)
            (legacy / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(live, "_record_bootstrap_state", inject_allocator_after_drain)

    with pytest.raises(live.LegacyCutoverConflict, match="allocator state appeared"):
        live.bootstrap_zero_history_authority(
            inventory, confirmed_zero_history=True
        )

    journal = tmp_path / "authority" / "bootstrap-test.bootstrap-journal.jsonl"
    assert live._bootstrap_journal_states(journal, "bootstrap-test") == ("DRAINING",)
    assert not (tmp_path / "authority" / "ACTIVE_BOOTSTRAP").exists()


def test_zero_history_bootstrap_resumes_interrupted_onboarding(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_write = live.LegacyRepositoryPartitionReceipt.write

    with monkeypatch.context() as patcher:
        patcher.setattr(
            live.LegacyRepositoryPartitionReceipt,
            "write",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        with pytest.raises(RuntimeError, match="crash"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    snapshot = live.repository_snapshot(repo)
    assert not (snapshot.store_root / live.RECEIPT_FILENAME).exists()
    assert (snapshot.namespace_root / "zero-legacy-onboarding").exists()
    assert live.LegacyRepositoryPartitionReceipt.write is original_write

    result = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )

    assert result["state"] == "ACTIVE"
    assert live.load_partition_receipt(snapshot.store_root) is not None
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "ACTIVE"


def test_barrier_resumes_interrupted_onboarding_under_bootstrap_id(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            live.LegacyRepositoryPartitionReceipt,
            "write",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        with pytest.raises(RuntimeError, match="crash"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )
    monkeypatch.setenv(
        "PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority")
    )

    report = live.fabpub_activation_barrier([repo])

    receipt = live.load_partition_receipt(live.repository_snapshot(repo).store_root)
    assert receipt is not None and receipt.cutover_id == inventory["cutover_id"]
    assert len(report["leases"]) == 1
    live.release_barrier_leases(report)
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"


def test_bootstrap_resumes_after_atomic_receipt_temp_is_stranded(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_replace = live.os.replace

    def interrupt_receipt_replace(source, target):
        if Path(target).name == live.RECEIPT_FILENAME:
            raise RuntimeError("process interrupted before receipt replace")
        return original_replace(source, target)

    with monkeypatch.context() as patcher:
        patcher.setattr(live.os, "replace", interrupt_receipt_replace)
        with pytest.raises(RuntimeError, match="interrupted"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    snapshot = live.repository_snapshot(repo)
    assert list(snapshot.store_root.glob(".partition-receipt.json.*.tmp"))
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"
    assert live.load_partition_receipt(snapshot.store_root) is not None


def test_bootstrap_resumes_after_atomic_authority_temp_is_stranded(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_replace = live.os.replace

    def interrupt_authority_replace(source, target):
        if Path(target).name == "bootstrap-test.bootstrap-inventory.json":
            raise RuntimeError("process interrupted before authority replace")
        return original_replace(source, target)

    with monkeypatch.context() as patcher:
        patcher.setattr(live.os, "replace", interrupt_authority_replace)
        with pytest.raises(RuntimeError, match="interrupted"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    authority = tmp_path / "authority"
    assert list(authority.glob(".bootstrap-test.bootstrap-inventory.json.*.tmp"))
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"


def test_cutover_id_cannot_escape_authority_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")

    with pytest.raises(live.LegacyCutoverConflict, match="cutover_id"):
        live.probe_zero_history_bootstrap(
            cutover_id="../escaped",
            authority_root=tmp_path / "authority",
            worktrees=(repo,),
        )

    assert not (tmp_path / "escaped.bootstrap-inventory.json").exists()
    assert not (tmp_path / "authority").exists()


def test_active_bootstrap_rejects_non_prefix_journal(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    journal = tmp_path / "authority" / "bootstrap-test.bootstrap-journal.jsonl"
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"cutover_id": "bootstrap-test", "state": "ACTIVE"}) + "\n")

    with pytest.raises(live.LegacyCutoverConflict, match="exact monotonic state prefix"):
        live.global_active_authority_exists(authority_root=tmp_path / "authority")


def test_multi_root_traditional_authority_uses_claimed_primary_journal(
    tmp_path: Path,
) -> None:
    roots = (tmp_path / "a", tmp_path / "b")
    cutover_id = "multi-root"
    primary = roots[0] / "fabpub-global-cutover"
    primary.mkdir(parents=True)
    (primary / f"{cutover_id}.journal.jsonl").write_text(
        json.dumps({"cutover_id": cutover_id, "state": "ACTIVE"}) + "\n",
        encoding="utf-8",
    )
    root_set_sha256 = live._root_set_digest(roots)
    for root in roots:
        authority = root / "fabpub-global-cutover"
        authority.mkdir(parents=True, exist_ok=True)
        (authority / "ACTIVE_CUTOVER").write_text(
            json.dumps(
                {
                    "cutover_id": cutover_id,
                    "primary_authority": str(primary),
                    "root_set_sha256": root_set_sha256,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    assert live.global_active_authority_exists(roots)


def test_unrelated_bootstrap_cannot_activate_traditional_receipt(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    root = tmp_path / "traditional"
    authority = root / "fabpub-global-cutover"
    authority.mkdir(parents=True)
    collision_id = inventory["cutover_id"]
    (authority / "ACTIVE_CUTOVER").write_text(collision_id + "\n", encoding="utf-8")
    (authority / f"{collision_id}.journal.jsonl").write_text(
        json.dumps({"cutover_id": collision_id, "state": "ARMED"}) + "\n",
        encoding="utf-8",
    )
    receipt = SimpleNamespace(
        legacy_root_inventory=(str(root),),
        zero_source=False,
        global_journal_path=str(authority / f"{collision_id}.journal.jsonl"),
        cutover_id=collision_id,
    )

    assert not live._receipt_active_authority_exists(
        receipt, authority_root=tmp_path / "authority"
    )


def test_bootstrap_receipt_cannot_downgrade_to_same_id_traditional_authority(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    receipt = live.load_partition_receipt(live.repository_snapshot(repo).store_root)
    assert receipt is not None

    (tmp_path / "authority" / "ACTIVE_BOOTSTRAP").unlink()
    traditional = tmp_path / "legacy" / "fabpub-global-cutover"
    traditional.mkdir(parents=True, exist_ok=True)
    (traditional / "ACTIVE_CUTOVER").write_text(
        "bootstrap-test\n", encoding="utf-8"
    )
    (traditional / "bootstrap-test.journal.jsonl").write_text(
        json.dumps({"cutover_id": "bootstrap-test", "state": "ACTIVE"}) + "\n",
        encoding="utf-8",
    )

    assert not live._receipt_active_authority_exists(
        receipt, authority_root=tmp_path / "authority"
    )


def test_bootstrap_resume_rejects_same_id_receipt_without_inventory_binding(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    authority = tmp_path / "authority"
    authority.mkdir()
    live._atomic_write_json(
        authority / "bootstrap-test.bootstrap-inventory.json", inventory
    )

    traditional_root = tmp_path / "traditional"
    traditional_authority = traditional_root / "fabpub-global-cutover"
    traditional_authority.mkdir(parents=True)
    (traditional_authority / "ACTIVE_CUTOVER").write_text(
        "bootstrap-test\n", encoding="utf-8"
    )
    (traditional_authority / "bootstrap-test.journal.jsonl").write_text(
        "".join(
            json.dumps({"cutover_id": "bootstrap-test", "state": state}) + "\n"
            for state in ("ARMED", "ACTIVE")
        ),
        encoding="utf-8",
    )
    receipt = live.onboard_zero_legacy_repository(
        repo,
        cutover_id="bootstrap-test",
        roots=(traditional_root,),
        authority_root=authority,
    )
    assert live._receipt_bootstrap_claim(receipt) is None

    with pytest.raises(live.LegacyCutoverConflict, match="not owned by bootstrap"):
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    assert not (authority / "ACTIVE_BOOTSTRAP").exists()


def test_direct_zero_source_onboarding_requires_global_active(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    legacy_root = tmp_path / "legacy"
    monkeypatch.setenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority"))
    monkeypatch.setenv("PHASE_LOOP_FABPUB_LEGACY_ROOTS", str(legacy_root))

    with pytest.raises(live.LegacyCutoverConflict, match="global ACTIVE"):
        live.onboard_zero_legacy_repository(repo)

    assert not live.repository_namespace_root(repo).exists()
    assert not legacy_root.exists()


def test_onboarding_rejects_unattested_canonical_state_before_latch_mutation(
    tmp_path: Path,
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    snapshot = live.repository_snapshot(fresh)
    snapshot.store_root.mkdir(parents=True)
    (snapshot.store_root / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="unattested canonical"):
        live.onboard_zero_legacy_repository(
            fresh, authority_root=tmp_path / "authority"
        )

    assert not (snapshot.namespace_root / "writer-generation.json").exists()


def test_post_write_zero_source_failure_never_receives_a_barrier_lease(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_proof = live._prove_zero_source

    def fail_after_write(snapshot, roots, boundary):
        result = original_proof(snapshot, roots, boundary)
        if boundary == "after_receipt_write":
            raise live.LegacyCutoverConflict("late source after receipt write")
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(live, "_prove_zero_source", fail_after_write)
        with pytest.raises(live.LegacyCutoverConflict, match="late source"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    snapshot = live.repository_snapshot(repo)
    assert live.load_partition_receipt(snapshot.store_root) is not None
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "DRAINING"
    monkeypatch.setenv(
        "PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority")
    )
    with pytest.raises(live.LegacyCutoverConflict, match="ACTIVE writer generation"):
        live.fabpub_activation_barrier([repo])


def test_existing_receipt_barrier_revalidates_global_authority(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.setenv(
        "PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority")
    )
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir(exist_ok=True)
    (legacy_root / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="allocator state appeared"):
        live.fabpub_activation_barrier([repo])

    assert live.WriterGenerationLatch.open(repo).held_leases() == ()


def test_receipt_discovers_custom_bootstrap_authority_in_fresh_process(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.delenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "unused-default-state"))

    report = live.fabpub_activation_barrier([repo])

    assert report["repositories"] == [str(repo)]
    bootstrap = live._active_bootstrap_inventory(tmp_path / "authority")
    assert bootstrap is not None
    lock_keys = {
        (str(path), threading.get_ident())
        for path in live._bootstrap_seal_lock_paths(bootstrap)
    }
    assert lock_keys.issubset(live._LOCK_DEPTH)
    live.release_barrier_leases(report)
    assert lock_keys.isdisjoint(live._LOCK_DEPTH)


def test_manifest_activation_barrier_completes_active_transition(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "cutover.json"
    manifest.write_text(
        json.dumps({"cutover_id": "legacy-cutover", "rows": []}), encoding="utf-8"
    )
    monkeypatch.setenv(live.FABPUB_CUTOVER_MANIFEST_ENV, str(manifest))

    class Transaction:
        cutover_id = "legacy-cutover"
        state = "ARMED"

        def activate(self):
            self.state = "ACTIVE"
            return self

    transaction = Transaction()
    monkeypatch.setattr(live, "run_legacy_broker_cutover", lambda _manifest: transaction)

    report = live.fabpub_activation_barrier([])

    assert report["cutover"] == {"cutover_id": "legacy-cutover", "state": "ACTIVE"}


@pytest.mark.parametrize("as_json", [False, True])
def test_fabpub_bootstrap_cli_probe_and_apply(
    tmp_path: Path, monkeypatch, capsys, as_json: bool
) -> None:
    repo = _git_repo(tmp_path / "repo")
    authority = tmp_path / "authority"
    inventory = tmp_path / "probe.json"
    monkeypatch.setenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(authority))
    output_args = ["--json"] if as_json else []

    assert main(
        [
            "fabpub-bootstrap",
            "--probe",
            "--inventory",
            str(inventory),
            "--cutover-id",
            "cli-test",
            "--worktree",
            str(repo),
            "--legacy-root",
            str(tmp_path / "legacy"),
            "--search-root",
            str(tmp_path),
            *output_args,
        ]
    ) == 0
    probe_report = json.loads(capsys.readouterr().out)
    assert probe_report["schema"] == "ZeroHistoryBootstrapProbeResult.v1"

    assert main(
        [
            "fabpub-bootstrap",
            "--apply",
            "--inventory",
            str(inventory),
            "--confirm-zero-history",
            *output_args,
        ]
    ) == 0
    apply_report = json.loads(capsys.readouterr().out)
    assert apply_report["state"] == "ACTIVE"
