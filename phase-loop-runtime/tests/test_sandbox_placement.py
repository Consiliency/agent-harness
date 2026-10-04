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
