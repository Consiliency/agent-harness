"""The staged tree a review seat reads must be BOUND by its authorization.

`advisor_board/backing.py` already `--ro-bind`s the staged dir into the review
sandbox, so any tree placed there is readable by the seat. Before this binding the
authorization digest-covered only `review-bundle.md` and `review-instructions.md`,
so the tree itself was unattested: nothing recorded which bytes were reviewed, and
a tree swapped between authorization and launch would be reviewed silently.

These tests mutate exactly what the field claims. Each one fails if
`_revalidate_staged_tree` is deleted or weakened to a presence check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import review_stage
from phase_loop_runtime.advisor_board import backing


def _authorization(staged_tree_sha256):
    """A sealed authorization carrying only what this check reads."""
    return backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="test",
        input_sha256="0" * 64, instructions_sha256="1" * 64,
        broker_contract=backing.PARENT_UNIX_BROKER_V1, routes=(),
        readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=staged_tree_sha256,
    )


def _staged_dir_with_tree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "src.py").write_text("reviewed bytes\n", encoding="utf-8")

    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    tree = review_stage.stage_review_tree(repo, tmp_path / "scratch")
    destination = staged_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME
    tree.rename(destination)
    return staged_dir, destination


def test_matching_tree_is_accepted(tmp_path):
    staged_dir, tree = _staged_dir_with_tree(tmp_path)
    auth = _authorization(review_stage.review_tree_manifest_sha256(tree))
    backing._revalidate_staged_tree(auth, staged_dir)


def test_an_unattested_tree_is_refused(tmp_path):
    """The case the field exists for: a tree nobody authorized is not reviewable."""
    staged_dir, _tree = _staged_dir_with_tree(tmp_path)
    auth = _authorization(None)
    with pytest.raises(ValueError, match="without authorization"):
        backing._revalidate_staged_tree(auth, staged_dir)


def test_a_swapped_tree_is_refused(tmp_path):
    """Authorize one tree, stage different bytes: must fail closed, not review it."""
    staged_dir, tree = _staged_dir_with_tree(tmp_path)
    approved = review_stage.review_tree_manifest_sha256(tree)

    swapped = tree / "src.py"
    swapped.chmod(0o600)
    swapped.write_text("attacker bytes\n", encoding="utf-8")

    auth = _authorization(approved)
    with pytest.raises(ValueError, match="does not match authorization"):
        backing._revalidate_staged_tree(auth, staged_dir)


def test_an_added_file_is_refused(tmp_path):
    """Adding a path is a swap too: the digest binds the path SET, not just bytes."""
    staged_dir, tree = _staged_dir_with_tree(tmp_path)
    auth = _authorization(review_stage.review_tree_manifest_sha256(tree))

    tree.chmod(0o700)
    (tree / "injected.py").write_text("extra\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match authorization"):
        backing._revalidate_staged_tree(auth, staged_dir)


def test_a_missing_tree_is_refused(tmp_path):
    """An authorization naming a tree must not silently pass when none is staged."""
    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    auth = _authorization("3" * 64)
    with pytest.raises(ValueError, match="missing"):
        backing._revalidate_staged_tree(auth, staged_dir)


def test_no_tree_and_no_authorization_is_the_historical_shape(tmp_path):
    """Byte-for-byte prior behaviour: no staged tree, nothing to bind, no refusal."""
    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    backing._revalidate_staged_tree(_authorization(None), staged_dir)


def test_authorization_defaults_to_permitting_no_tree():
    """A caller that never opts in gets the historical authorization shape."""
    assert _authorization(None).staged_tree_sha256 is None


def test_default_spawn_stages_the_tree_only_when_authorized(tmp_path, monkeypatch):
    """End-to-end wiring: the authorization, not the caller, decides.

    The pre-existing bundle-only invariant
    (`test_panel_leg_review_dir_never_contains_the_repo`) still holds for an
    unauthorized spawn; this covers the opt-in path it does not reach.
    """
    from phase_loop_runtime import panel_invoker

    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "SOURCE.py").write_text("code under review\n", encoding="utf-8")

    seen: dict[str, object] = {}

    def _fake_exec_leg(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
        review_dir = Path(review_dir)
        seen["entries"] = sorted(p.name for p in review_dir.iterdir())
        tree = review_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME
        seen["staged_source"] = (
            (tree / "SOURCE.py").read_text(encoding="utf-8") if tree.is_dir() else None
        )
        seen["review_dir"] = review_dir
        return 0, "ok review", "log"

    monkeypatch.setattr(panel_invoker, "_exec_leg", _fake_exec_leg)

    approved = review_stage.review_tree_manifest_sha256(repo)
    panel_invoker._default_spawn(
        "gemini", "REVIEW BUNDLE BODY", repo_dir=repo,
        review_authorization=_authorization(approved),
        canonical_repo_authority=repo,
    )

    assert review_stage.REVIEW_STAGE_TREE_DIRNAME in seen["entries"]
    assert seen["staged_source"] == "code under review\n", "the seat must be able to read the code"
    # The seat read a copy; the reviewed tree is untouched and no .git was exposed.
    assert (repo / "SOURCE.py").read_text(encoding="utf-8") == "code under review\n"
    assert not (Path(seen["review_dir"]) / review_stage.REVIEW_STAGE_TREE_DIRNAME / ".git").exists()


def test_default_spawn_removes_the_readonly_stage_on_the_way_out(tmp_path, monkeypatch):
    """A read-only stage defeats `rmtree(ignore_errors=True)`; it must not leak."""
    from phase_loop_runtime import panel_invoker

    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "SOURCE.py").write_text("code under review\n", encoding="utf-8")

    captured: dict[str, Path] = {}

    def _fake_exec_leg(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
        captured["base"] = Path(review_dir).parent
        return 0, "ok review", "log"

    monkeypatch.setattr(panel_invoker, "_exec_leg", _fake_exec_leg)
    panel_invoker._default_spawn(
        "gemini", "REVIEW BUNDLE BODY", repo_dir=repo,
        review_authorization=_authorization(review_stage.review_tree_manifest_sha256(repo)),
        canonical_repo_authority=repo,
    )

    assert not captured["base"].exists(), "the staged tree must not survive the leg"


def test_staging_a_tree_the_authorization_did_not_approve_is_refused(tmp_path, monkeypatch):
    """The bug this caught: stage one tree, authorize another, and it must refuse.

    `resolved_repo_dir` follows the CANONICAL repo authority, not `repo_dir`, so a
    caller whose authority disagrees with the tree it means to review would
    otherwise hand the seat an entirely different repository.
    """
    from phase_loop_runtime import panel_invoker

    reviewed = tmp_path / "reviewed"
    reviewed.mkdir()
    subprocess.run(["git", "init", "-q", str(reviewed)], check=True)
    (reviewed / "SOURCE.py").write_text("reviewed\n", encoding="utf-8")

    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    (other / "OTHER.py").write_text("not the reviewed tree\n", encoding="utf-8")

    monkeypatch.setattr(panel_invoker, "_exec_leg",
                        lambda *a, **k: (0, "ok review", "log"))

    # Authorize `reviewed`, but point the canonical authority at `other`.
    status, detail = panel_invoker._default_spawn(
        "gemini", "REVIEW BUNDLE BODY", repo_dir=reviewed,
        review_authorization=_authorization(
            review_stage.review_tree_manifest_sha256(reviewed)
        ),
        canonical_repo_authority=other,
    )
    assert status == "DEGRADED"
    assert "staged tree does not match authorization" in detail
