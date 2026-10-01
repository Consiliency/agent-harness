"""EC-RATIFY-3: real Git histories and measured guard evidence.

The tests freeze ``check_ruling_ledger(repo, ledger_path, landing_ref, now,
guard_proofs={nodeid: {verification_artifact_path, junit_path}})``. Its result
has ``ok`` and ``guard_states``. Checking a proposed append must not require
the proposed row's own containing commit to exist already.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import ratify_content_tdd_adapter as tdd

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
CLASSES = ("round_local", "contract_changing", "roadmap_changing", "release_rule")
LEDGER = "plans/rulings.jsonl"


def _git(repo, *argv):
    return subprocess.run(["git", "-C", str(repo), *argv], check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(repo, message="fixture"):
    _git(repo, "add", ".")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path):
    repo = tmp_path / "ledger-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "RATIFY fixture")
    _git(repo, "config", "user.email", "ratify@example.test")
    (repo / "plans").mkdir()
    (repo / LEDGER).write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text(".phase-loop/\n__pycache__/\n.pytest_cache/\n")
    (repo / "test_guard.py").write_text("def test_guard():\n    assert 2 + 2 == 4\n")
    return repo, _commit(repo, "base")


def _row(head, *, ruling_id="r1", ruling_class="contract_changing", bound="2026-10-02T00:00:00Z", guard="pending"):
    return {
        "schema": "ruling_ledger.v1", "event": "issued", "ruling_id": ruling_id,
        "ruling_class": ruling_class, "pr": "Consiliency/agent-harness#1203",
        "reviewed_sha": head, "president_model": "claude-opus-5-5",
        "authorization_identity": "public_board_president.v1",
        "seat_verdicts": [
            {"seat_key": "claude:correctness", "model": "claude-opus-5-5", "vendor": "claude", "verdict": "AGREE"},
            {"seat_key": "codex:adversarial", "model": "gpt-6-astra", "vendor": "codex", "verdict": "AGREE"},
        ],
        "decision": "Retain the guard and this exact ruling.",
        "guard_nodeid": guard, "resolution_bound": bound,
    }


def _write(repo, rows):
    (repo / LEDGER).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _check(repo, *, ref="HEAD", proofs=None, now=NOW):
    module = tdd.capability("ledger")
    checker = tdd.require_attr(module, "check_ruling_ledger")
    return checker(repo=repo, ledger_path=Path(LEDGER), landing_ref=ref,
                   now=now, guard_proofs=proofs or {})


def _proof(repo):
    from phase_loop_runtime.verification_evidence import ARTIFACT_NAME, run_verification, validate_verification_artifact
    folder = repo / ".phase-loop" / "guard"
    junit = folder / "guard.xml"
    node = "test_guard.py::test_guard"
    result = run_verification(
        repo=repo, run_dir=folder,
        commands=[
            ["git", "rev-parse", "HEAD"],
            [sys.executable, "-m", "pytest", "-q", node, f"--junitxml={junit}"],
            ["sha256sum", str(junit)],
        ], suite_command=None, env_refresh=None, timeout_s=None,
    )
    artifact = folder / ARTIFACT_NAME
    assert validate_verification_artifact(artifact).ok
    assert all(command.exit_code == 0 for command in result.commands)
    return {node: {"verification_artifact_path": str(artifact), "junit_path": str(junit)}}


def test_closed_vocabulary():
    def check():
        module = tdd.capability("ledger")
        assert tuple(module.RULING_CLASSES) == CLASSES
    tdd.run_contract("closed_vocabulary", "ledger", check)


def test_empty_ledger(tmp_path):
    def check():
        repo, _head = _repo(tmp_path)
        result = _check(repo)
        assert result.ok and result.guard_states == {}
        _write(repo, [_row(_git(repo, "rev-parse", "HEAD"))])
        assert _check(repo).ok
    tdd.run_contract("empty_ledger", "ledger", check)


def test_ancestor_prefix(tmp_path):
    def check():
        repo, head = _repo(tmp_path)
        row = _row(head)
        _write(repo, [row]); _commit(repo, "issued")
        original = (repo / LEDGER).read_bytes()
        row["decision"] = "In-place rewrite"
        _write(repo, [row]); _commit(repo, "invalid edit")
        # Looking only at the immediate parent is insufficient after another commit.
        (repo / "unrelated.txt").write_text("sibling")
        _commit(repo, "descendant")
        assert not _check(repo).ok
        (repo / LEDGER).write_bytes(original)
        # A later restoration cannot erase an invalid reachable ancestor.
        assert not _check(repo).ok
    tdd.run_contract("ancestor_prefix", "ledger", check)


def test_second_parent_prefix(tmp_path):
    def check():
        repo, base = _repo(tmp_path)
        _git(repo, "checkout", "-qb", "right")
        _write(repo, [_row(base, ruling_id="right")]); right = _commit(repo, "right row")
        _git(repo, "checkout", "-qb", "left", base)
        _write(repo, [_row(base, ruling_id="left")]); left = _commit(repo, "left row")
        # Construct a real two-parent object retaining left and dropping right.
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        merge = _git(repo, "-c", "commit.gpgsign=false", "commit-tree", tree,
                     "-p", left, "-p", right, "-m", "dropped second-parent row")
        assert not _check(repo, ref=merge).ok
        _git(repo, "checkout", "-qb", "ordinary-left", base)
        (repo / "left.txt").write_text("ordinary unrelated landing")
        ordinary_left = _commit(repo, "ordinary left")
        ordinary_tree = _git(repo, "rev-parse", "HEAD^{tree}")
        _git(repo, "checkout", "-qb", "ordinary-right", base)
        (repo / "right.txt").write_text("another unrelated landing")
        ordinary_right = _commit(repo, "ordinary right")
        ordinary_merge = _git(repo, "-c", "commit.gpgsign=false", "commit-tree", ordinary_tree,
                              "-p", ordinary_left, "-p", ordinary_right, "-m", "ordinary siblings")
        assert _check(repo, ref=ordinary_merge).ok
    tdd.run_contract("second_parent_prefix", "ledger", check)


def test_reviewed_sha_ancestry(tmp_path):
    def check():
        repo, head = _repo(tmp_path)
        _write(repo, [_row(head)])
        assert _check(repo).ok
        _git(repo, "checkout", "--orphan", "foreign")
        (repo / "foreign.txt").write_text("foreign")
        foreign = _commit(repo, "foreign history")
        _git(repo, "checkout", "--detach", head)
        _write(repo, [_row(foreign)])
        assert not _check(repo).ok
    tdd.run_contract("reviewed_sha_ancestry", "ledger", check)


def test_duplicate_and_foreign_rows(tmp_path):
    def check():
        repo, head = _repo(tmp_path)
        row = _row(head)
        _write(repo, [row, row]); assert not _check(repo).ok
        for key, value in (("ruling_class", "invented"), ("pr", "935"),
                           ("authorization_identity", "public_board_review.v1")):
            _write(repo, [{**row, key: value}]); assert not _check(repo).ok
        _write(repo, [row, {"schema": "ruling_ledger.v1", "event": "guard_resolved",
                           "ruling_id": "absent", "guard_nodeid": "test_guard.py::test_guard"}])
        assert not _check(repo).ok
    tdd.run_contract("duplicate_and_foreign_rows", "ledger", check)


def test_pending_and_resolved_fold(tmp_path):
    def check():
        repo, head = _repo(tmp_path)
        row = _row(head)
        _write(repo, [row]); _commit(repo, "pending")
        original = (repo / LEDGER).read_bytes()
        assert _check(repo).guard_states["r1"] == "pending"
        node = "test_guard.py::test_guard"
        _write(repo, [row, {"schema": "ruling_ledger.v1", "event": "guard_resolved",
                           "ruling_id": "r1", "guard_nodeid": node}])
        assert (repo / LEDGER).read_bytes().startswith(original)
        assert not _check(repo).ok  # A node name is not a proof.
        proofs = _proof(repo)
        result = _check(repo, proofs=proofs)
        assert result.ok and result.guard_states["r1"] == "guarded"
        assert _check(repo, proofs=proofs, now=datetime(2030, 1, 1, tzinfo=timezone.utc)).guard_states["r1"] == "guarded"
    tdd.run_contract("pending_and_resolved_fold", "ledger", check)


def test_unguarded_same_class(tmp_path):
    def check():
        repo, head = _repo(tmp_path)
        row = _row(head, bound="2026-09-30T00:00:00Z")
        _write(repo, [row]); _commit(repo, "expired pending")
        assert _check(repo).guard_states["r1"] == "unguarded"
        _write(repo, [row, _row(head, ruling_id="same")]); assert not _check(repo).ok
        _write(repo, [row, _row(head, ruling_id="other", ruling_class="roadmap_changing")])
        assert _check(repo).ok
    tdd.run_contract("unguarded_same_class", "ledger", check)


def test_same_class_multirow(tmp_path):
    def check():
        repo, head = _repo(tmp_path)
        expired = _row(head, bound="2026-09-30T00:00:00Z")
        _write(repo, [expired, _row(head, ruling_id="r2")])
        assert not _check(repo).ok
        _write(repo, [_row(head), _row(head, ruling_id="r2")])
        assert _check(repo).ok  # Pending within bounds is not unguarded.
    tdd.run_contract("same_class_multirow", "ledger", check)


def test_guard_provenance(tmp_path, monkeypatch):
    def check():
        repo, head = _repo(tmp_path)
        node = "test_guard.py::test_guard"
        row = _row(head, guard=node, bound=None)
        _write(repo, [row])
        assert not _check(repo, proofs={node: {"passed": True}}).ok
        proofs = _proof(repo)
        assert _check(repo, proofs=proofs).guard_states["r1"] == "guarded"
        # A checker must read and validate retained proof, never rerun arbitrary commands.
        import phase_loop_runtime.verification_evidence as ve
        monkeypatch.setattr(ve, "run_verification", lambda *a, **k: (_ for _ in ()).throw(AssertionError("checker executed commands")))
        original_run = subprocess.run
        def git_only(argv, *args, **kwargs):
            assert Path(str(argv[0])).name == "git", "checker executed a non-Git command"
            return original_run(argv, *args, **kwargs)
        monkeypatch.setattr(subprocess, "run", git_only)
        assert _check(repo, proofs=proofs).ok
        junit = Path(proofs[node]["junit_path"])
        original = junit.read_bytes()
        junit.write_bytes(original + b" ")
        assert not _check(repo, proofs=proofs).ok
        junit.write_bytes(original)
        artifact = Path(proofs[node]["verification_artifact_path"])
        original_artifact = artifact.read_bytes()
        changed = json.loads(original_artifact)
        changed["commands"].pop()
        artifact.write_text(json.dumps(changed))
        assert not _check(repo, proofs=proofs).ok
        artifact.write_bytes(original_artifact)
        (repo / "next.txt").write_text("new head")
        _commit(repo, "advance")
        # Previously measured guard evidence cannot authenticate a new landing head.
        assert not _check(repo, proofs=proofs).ok
    tdd.run_contract("guard_provenance", "ledger", check)


def test_unavailable_history(tmp_path):
    def check():
        repo, head = _repo(tmp_path)
        _write(repo, [_row(head)])
        assert not _check(repo, ref="missing-history-object").ok
        _write(repo, [_row("f" * 40)])
        assert not _check(repo).ok
    tdd.run_contract("unavailable_history", "ledger", check)
