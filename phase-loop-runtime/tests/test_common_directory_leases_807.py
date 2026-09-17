"""agent-harness#807: real Git namespaces and flock must not self-deadlock."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


_GIT_LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_GRAFT_FILE",
    "GIT_SHALLOW_FILE",
)


def git(directory, *args):
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True,
                   env={key: value for key, value in os.environ.items() if key not in _GIT_LOCATION_ENV})


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
    return dict({key: value for key, value in os.environ.items() if key not in _GIT_LOCATION_ENV},
                PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))


def test_fixture_helpers_scrub_repository_routing_git_environment(tmp_path, monkeypatch):
    import hashlib

    control_env = {key: value for key, value in os.environ.items() if key not in _GIT_LOCATION_ENV}
    external = (tmp_path / "external").resolve()
    intended = (tmp_path / "intended").resolve()
    external.mkdir()
    intended.mkdir()
    subprocess.run(["git", "-C", str(external), "init", "-q"], check=True, capture_output=True,
                   env=control_env)
    (external / "tracked.txt").write_text("baseline\n")
    subprocess.run(["git", "-C", str(external), "add", "tracked.txt"], check=True, capture_output=True,
                   env=control_env)
    subprocess.run(
        ["git", "-C", str(external), "-c", "user.name=Fixture",
         "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "baseline"],
        check=True, capture_output=True, env=control_env,
    )
    external_index = Path(subprocess.run(
        ["git", "-C", str(external), "rev-parse", "--path-format=absolute", "--git-path", "index"],
        check=True, capture_output=True, text=True, env=control_env,
    ).stdout.strip())
    external_head_before = subprocess.run(
        ["git", "-C", str(external), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
        env=control_env,
    ).stdout.strip()
    external_index_before = external_index.read_bytes()
    external_index_digest_before = hashlib.sha256(external_index_before).hexdigest()
    ambient_git_variable_names = sorted(name for name in os.environ if name.startswith("GIT_"))
    routing_paths = {
        "GIT_DIR": (external / ".git").resolve(),
        "GIT_WORK_TREE": external,
        "GIT_COMMON_DIR": (external / ".git").resolve(),
        "GIT_INDEX_FILE": external_index.resolve(),
    }
    for name in _GIT_LOCATION_ENV:
        if name not in routing_paths:
            monkeypatch.delenv(name, raising=False)
    for name, path in routing_paths.items():
        monkeypatch.setenv(name, str(path))
    git(intended, "init", "-q")
    git_init_completed = True
    git(intended, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "intended")
    git_commit_completed = True
    intended_git = intended / ".git"
    intended_commit_identity = None
    if intended_git.is_dir():
        intended_commit_identity = subprocess.run(
            ["git", "-C", str(intended), "rev-parse", "HEAD"], check=True, capture_output=True,
            text=True, env=control_env,
        ).stdout.strip()
    child = subprocess.run(
        [sys.executable, "-c", """
from pathlib import Path
import sys
from phase_loop_runtime.convergence.broker.live import repository_namespace_root
print(repository_namespace_root(Path(sys.argv[1])))
""", str(intended)],
        env=environment(), capture_output=True, text=True, timeout=5,
    )
    external_head_after = subprocess.run(
        ["git", "-C", str(external), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
        env=control_env,
    ).stdout.strip()
    external_index_after = external_index.read_bytes()
    external_index_digest_after = hashlib.sha256(external_index_after).hexdigest()
    child_namespace = child.stdout.strip()
    child_namespace_path = Path(child_namespace).resolve() if child.returncode == 0 and child_namespace else None
    expected_namespace_parent = intended_git.resolve()
    namespace_in_intended_git = child_namespace_path is not None and (
        child_namespace_path == expected_namespace_parent
        or expected_namespace_parent in child_namespace_path.parents
    )
    namespace_outside_external = child_namespace_path is not None and (
        child_namespace_path != external and external not in child_namespace_path.parents
    )
    observations = {
        "ambient_git_variable_names": ambient_git_variable_names,
        "child_namespace": child_namespace,
        "child_returncode": child.returncode,
        "child_stderr": child.stderr,
        "expected_namespace_parent": str(expected_namespace_parent),
        "external_head_after": external_head_after,
        "external_head_before": external_head_before,
        "external_index_after": external_index_after,
        "external_index_before": external_index_before,
        "external_index_digest_after": external_index_digest_after,
        "external_index_digest_before": external_index_digest_before,
        "external_index_path": str(external_index),
        "git_commit_completed": git_commit_completed,
        "git_init_completed": git_init_completed,
        "intended_commit_identity": intended_commit_identity,
        "intended_git_exists": intended_git.is_dir(),
        "namespace_in_intended_git": namespace_in_intended_git,
        "namespace_outside_external": namespace_outside_external,
        "routing_paths": {name: str(path) for name, path in routing_paths.items()},
    }
    assert (
        git_init_completed
        and git_commit_completed
        and external_head_before == external_head_after
        and external_index_before == external_index_after
        and external_index_digest_before == external_index_digest_after
        and intended_git.is_dir()
        and intended_commit_identity is not None
        and child.returncode == 0
        and namespace_in_intended_git
        and namespace_outside_external
    ), observations


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
