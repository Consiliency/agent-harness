"""agent-harness#807: real Git namespaces and flock must not self-deadlock."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


def git(directory, *args):
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)


@pytest.fixture
def repositories(tmp_path):
    primary = tmp_path / "primary"
    primary.mkdir()
    git(primary, "init", "-q")
    git(primary, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "fixture")
    linked = tmp_path / "linked"
    git(primary, "worktree", "add", "--detach", str(linked), "HEAD")
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    return primary, linked, other


def environment():
    return dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))


@pytest.mark.parametrize("shape,expected", [
    ("single", 1), ("duplicate", 1), ("linked", 2), ("subdirectories", 2), ("independent", 2),
])
def test_each_worktree_keeps_its_lease_without_locking_one_namespace_twice(repositories, shape, expected):
    primary, linked, other = repositories
    paths = {"single": [primary], "duplicate": [primary, primary],
             "linked": [primary, linked], "independent": [primary, other]}
    if shape == "subdirectories":
        paths[shape] = [primary / "one", primary / "two"]
        for path in paths[shape]:
            path.mkdir()
    result = subprocess.run(
        [sys.executable, "-c", """
import json, sys
from pathlib import Path
from phase_loop_runtime.convergence.fencing import run_train_generation_leases
from phase_loop_runtime.convergence.broker.live import repository_namespace_root
paths = [Path(p) for p in sys.argv[1:]]
with run_train_generation_leases(paths) as leases:
    count = len(leases)
assert all(not list((repository_namespace_root(p) / 'generation-leases').glob('*.json')) for p in paths)
print(json.dumps({'leases': count}))
""", *map(str, paths[shape])],
        env=environment(), capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["leases"] == expected


def test_other_process_cannot_enter_a_linked_worktree_while_primary_holds_lock(repositories, tmp_path):
    primary, linked, _ = repositories
    script = """
import sys, time
from pathlib import Path
from phase_loop_runtime.convergence.fencing import run_train_generation_leases
Path(sys.argv[4]).touch()
with run_train_generation_leases([Path(sys.argv[1])]):
    Path(sys.argv[2]).touch()
    while not Path(sys.argv[3]).exists():
        time.sleep(.02)
"""
    first_entered, second_entered, release = [tmp_path / name for name in ("first", "second", "release")]
    second_attempted = tmp_path / "second-attempted"
    processes = []
    try:
        first = subprocess.Popen([sys.executable, "-c", script, str(primary), str(first_entered), str(release), str(tmp_path / "first-attempted")], env=environment())
        processes.append(first)
        deadline = time.monotonic() + 5
        while not first_entered.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert first_entered.exists()
        second = subprocess.Popen([sys.executable, "-c", script, str(linked), str(second_entered), str(release), str(second_attempted)], env=environment())
        processes.append(second)
        deadline = time.monotonic() + 5
        while not second_attempted.exists() and second.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert second_attempted.exists()
        time.sleep(.3)
        assert second.poll() is None and not second_entered.exists()
        release.touch()
        assert first.wait(timeout=5) == second.wait(timeout=5) == 0
        assert second_entered.exists()
    finally:
        release.touch()
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


def test_rejected_second_generation_releases_earlier_lease_and_shared_lock(repositories):
    primary, linked, _ = repositories
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
from pathlib import Path
from phase_loop_runtime.convergence import fencing
from phase_loop_runtime.convergence.broker.live import WriterGenerationBlocked, repository_namespace_root
paths = sorted([Path(p).resolve() for p in sys.argv[1:]], key=str)
fencing._FORCED_WRITER_GENERATIONS[str(paths[1])] = 'stale-fixture-generation'
try:
    with fencing.run_train_generation_leases(paths):
        raise AssertionError('stale generation entered')
except WriterGenerationBlocked:
    pass
finally:
    fencing._FORCED_WRITER_GENERATIONS.clear()
assert not list((repository_namespace_root(paths[0]) / 'generation-leases').glob('*.json'))
with fencing.run_train_generation_leases(paths) as leases:
    assert len(leases) == 2
""", str(primary), str(linked)],
        env=environment(), capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
