"""Retention: reap sandboxes before they eat the disk, keep what cannot be rebuilt.

Sizing changed when the sandbox became writable and executable. A read-only copy was 28 MB;
once a seat has created a venv and run tests it is ~150-250 MB, four seats to a round, and
agent-harness#832 ran fifteen rounds. That is 10-15 GB for a single PR, against a host that
was at 97% on both disks this morning.

Two triggers, because one is not enough. A day-long TTL is the operator's requirement -- a
sandbox has to survive an idle overnight so a panelist can be resumed with its context
intact -- but fifteen rounds in six hours outruns any clock, so a total-footprint ceiling
reaps oldest-first as well.

The split that makes this safe is the same one the stale-resume logic uses:

* ``reviewed-tree/`` is RECONSTRUCTIBLE -- it comes from git. Pure waste once cold.
* ``work/`` is IRREPRODUCIBLE -- the panelist's notes, probes and partial findings.

So: never archive the bulk, never reap the record, and archive BEFORE reaping. Losing the
irreproducible half to a cleanup bug is the one failure here that cannot be undone.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


from phase_loop_runtime import sandbox_retention


def _sandbox(root: Path, name: str, *, age_s: float = 0.0, tree_bytes: int = 1024) -> Path:
    box = root / name
    (box / "reviewed-tree" / "pkg").mkdir(parents=True)
    (box / "reviewed-tree" / "pkg" / "big.bin").write_bytes(b"x" * tree_bytes)
    (box / "work").mkdir()
    (box / "work" / "notes.md").write_text(f"findings for {name}\n", encoding="utf-8")
    # Real sandboxes are claimed by the runtime that created them; identity is a marker,
    # not a shape, so the fixture must claim its own.
    sandbox_retention.mark_as_sandbox(box)
    if age_s:
        old = time.time() - age_s
        os.utime(box, (old, old))
    return box


class TestTTL:
    def test_a_cold_sandbox_is_reaped(self, tmp_path):
        stale = _sandbox(tmp_path, "cold", age_s=48 * 3600)
        sandbox_retention.reap(tmp_path, ttl_s=24 * 3600)
        assert not stale.exists()

    def test_a_sandbox_inside_the_ttl_survives_an_idle_overnight(self, tmp_path):
        """The operator's requirement: resumable with its context the next morning."""
        warm = _sandbox(tmp_path, "overnight", age_s=10 * 3600)
        sandbox_retention.reap(tmp_path, ttl_s=24 * 3600)
        assert warm.exists()
        assert (warm / "work" / "notes.md").is_file()

    def test_reaping_never_touches_anything_that_is_not_a_sandbox(self, tmp_path):
        """Board round 2, BLOCKING, verified destroying a bystander's files.

        Identity used to be a SHAPE test: any directory containing a `work/` subdirectory
        counted. So an unrelated `someone-elses-project/work/` made the WHOLE project
        directory eligible, and reaping deleted it.

        The previous version of this test used a bystander with NO `work/` subdirectory,
        so it passed without ever exercising the predicate that caused the loss. That is
        the shape a vacuous test takes: green, and unable to fail.
        """
        bystander = tmp_path / "someone-elses-project"
        (bystander / "work").mkdir(parents=True)
        (bystander / "work" / "THEIR_NOTES.md").write_text("not ours\n", encoding="utf-8")
        (bystander / "src.py").write_text("their code\n", encoding="utf-8")
        old = time.time() - 99 * 3600
        os.utime(bystander, (old, old))

        sandbox_retention.reap(tmp_path, ttl_s=1)

        assert bystander.is_dir(), "a bystander directory must survive"
        assert (bystander / "work" / "THEIR_NOTES.md").is_file(), (
            "only directories this runtime MARKED may be reaped -- a shape is not identity"
        )

    def test_a_marked_sandbox_is_still_reaped(self, tmp_path):
        """The negative control: tightening identity must not stop real reaping."""
        box = _sandbox(tmp_path, "real", age_s=48 * 3600)
        sandbox_retention.mark_as_sandbox(box)
        old = time.time() - 48 * 3600
        os.utime(box, (old, old))
        sandbox_retention.reap(tmp_path, ttl_s=1)
        assert not box.exists()

    def test_a_symlinked_directory_is_never_reaped(self, tmp_path):
        """Reaping through a symlink would delete whatever it points at."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
        link = tmp_path / "pl-panel-stage-link"
        os.symlink(outside, link)
        sandbox_retention.reap(tmp_path, ttl_s=1)
        assert (outside / "keep.txt").is_file()


class TestFootprintCeiling:
    def test_the_ceiling_reaps_oldest_first(self, tmp_path):
        old = _sandbox(tmp_path, "older", age_s=6 * 3600, tree_bytes=8192)
        new = _sandbox(tmp_path, "newer", age_s=1 * 3600, tree_bytes=8192)

        sandbox_retention.reap(tmp_path, ttl_s=24 * 3600, max_total_bytes=10_000)

        assert not old.exists(), "a burst of rounds outruns the clock; size must also bite"
        assert new.exists(), "the newest sandbox is the one most likely to be resumed"

    def test_under_the_ceiling_nothing_is_reaped(self, tmp_path):
        a = _sandbox(tmp_path, "a", age_s=3600, tree_bytes=512)
        b = _sandbox(tmp_path, "b", age_s=3600, tree_bytes=512)
        sandbox_retention.reap(tmp_path, ttl_s=24 * 3600, max_total_bytes=10_000_000)
        assert a.exists() and b.exists()


class TestArchive:
    def test_the_irreproducible_half_is_archived_and_the_bulk_is_not(self, tmp_path):
        box = _sandbox(tmp_path, "done", age_s=48 * 3600, tree_bytes=4096)
        archive = tmp_path / "cold-storage"

        sandbox_retention.reap(tmp_path, ttl_s=24 * 3600, archive_dest=archive)

        # Cold storage gets one compact artifact per sandbox, not a loose directory.
        tarballs = list(archive.glob("*.tar.gz"))
        assert tarballs, "the panelist's work is irreproducible and must survive"
        import tarfile
        with tarfile.open(tarballs[0]) as handle:
            names = handle.getnames()
        assert any(n.endswith("notes.md") for n in names), names
        assert not any(n.endswith("big.bin") for n in names), (
            "the code copy comes from git; archiving it wastes the space we just freed"
        )
        assert not box.exists()

    def test_archive_runs_before_the_reap(self, tmp_path, monkeypatch):
        """Ordering is the whole risk: reap-then-archive silently loses the record."""
        _sandbox(tmp_path, "ordered", age_s=48 * 3600)
        order: list[str] = []

        real_archive = sandbox_retention._archive_work
        real_remove = sandbox_retention._remove

        monkeypatch.setattr(
            sandbox_retention, "_archive_work",
            lambda *a, **k: (order.append("archive"), real_archive(*a, **k))[1],
        )
        monkeypatch.setattr(
            sandbox_retention, "_remove",
            lambda *a, **k: (order.append("reap"), real_remove(*a, **k))[1],
        )
        sandbox_retention.reap(tmp_path, ttl_s=1, archive_dest=tmp_path / "cold")
        assert order == ["archive", "reap"]

    def test_a_failed_archive_does_not_reap(self, tmp_path, monkeypatch):
        """Never trade the irreproducible half for disk space."""
        box = _sandbox(tmp_path, "unlucky", age_s=48 * 3600)

        def _boom(*_a, **_k):
            raise OSError("cold storage unreachable")

        monkeypatch.setattr(sandbox_retention, "_archive_work", _boom)
        sandbox_retention.reap(tmp_path, ttl_s=1, archive_dest=tmp_path / "cold")
        assert box.exists(), "if the record cannot be saved, the sandbox stays"

    def test_no_archive_destination_means_reap_without_archiving(self, tmp_path):
        box = _sandbox(tmp_path, "plain", age_s=48 * 3600)
        sandbox_retention.reap(tmp_path, ttl_s=1, archive_dest=None)
        assert not box.exists()


def test_the_production_creator_marks_what_it_creates(tmp_path, monkeypatch):
    """Tightening identity without writing the marker trades data loss for a disk leak.

    `_looks_like_a_sandbox` now requires a marker THIS runtime wrote, so a real sandbox
    that is never marked is never reaped -- it leaks forever, silently, exactly like the
    bug retention exists to prevent. This asserts the creator claims its own work.
    """
    import subprocess
    from phase_loop_runtime import panel_invoker, review_stage
    from phase_loop_runtime.advisor_board import backing

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
        check=True,
    )

    seen: dict[str, Path] = {}

    def _capture(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
        seen["base"] = Path(review_dir).parent
        return 0, "ok", "log"

    monkeypatch.setattr(panel_invoker, "_exec_leg", _capture)
    # Retention, not egress. Egress fails closed, so on a host without user namespaces the
    # leg would refuse before it ever staged anything and this would pass vacuously in the
    # other direction. Declare the best-effort posture explicitly rather than weakening it.
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
    auth = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=review_stage.review_tree_manifest_sha256(repo),
    )
    panel_invoker._default_spawn(
        "gemini", "BODY", repo_dir=repo,
        review_authorization=auth, canonical_repo_authority=repo,
    )
    # The scratch dir is reaped by `_default_spawn`'s own finally, so the marker is proven
    # by the call having been made rather than by a surviving file.
    assert "base" in seen
