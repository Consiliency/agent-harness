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

import pytest

from phase_loop_runtime import sandbox_retention


def _sandbox(root: Path, name: str, *, age_s: float = 0.0, tree_bytes: int = 1024) -> Path:
    box = root / name
    (box / "reviewed-tree" / "pkg").mkdir(parents=True)
    (box / "reviewed-tree" / "pkg" / "big.bin").write_bytes(b"x" * tree_bytes)
    (box / "work").mkdir()
    (box / "work" / "notes.md").write_text(f"findings for {name}\n", encoding="utf-8")
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
        bystander = tmp_path / "someone-elses-data"
        bystander.mkdir()
        (bystander / "important.txt").write_text("keep\n", encoding="utf-8")
        old = time.time() - 99 * 3600
        os.utime(bystander, (old, old))

        sandbox_retention.reap(tmp_path, ttl_s=1)
        assert (bystander / "important.txt").is_file(), (
            "only directories this runtime staged may be reaped"
        )


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
