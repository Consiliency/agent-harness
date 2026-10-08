"""Host paths that reach the seat through a linked directory the operator owns.

A worktree or scratch directory is often reached through a directory link (a volume
mounted elsewhere and linked into place). The owner's host-side walks never follow a
link, so before this every seat whose cwd, inputs or outputs sat below such a link was
refused. A link owned by root or the operator in a PARENT component is resolved once;
the last component is still never followed, and a link anyone else owns is still refused.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress

needs_owner = pytest.mark.skipif(
    not (os.path.exists("/usr/bin/bwrap") and shutil.which("python3")) or os.getuid() == 0,
    reason="needs bubblewrap and a non-root operator")


def _linked_workspace(tmp_path: Path) -> tuple[Path, Path]:
    real = tmp_path / "volume"
    (real / "work").mkdir(parents=True)
    link = tmp_path / "workspace"
    link.symlink_to(real, target_is_directory=True)
    return real, link


def test_a_parent_link_the_operator_owns_is_resolved(tmp_path):
    real, link = _linked_workspace(tmp_path)
    assert pi._trusted_host_path(link / "work" / "out.txt") == str(real / "work" / "out.txt")
    assert pi._seat_bind_source(link / "work") == str(real / "work")


def test_the_last_component_is_never_followed(tmp_path):
    real, link = _linked_workspace(tmp_path)
    target = real / "work" / "target.txt"
    target.write_text("x")
    leaf = real / "work" / "leaf.txt"
    leaf.symlink_to(target)
    assert pi._trusted_host_path(link / "work" / "leaf.txt") == str(leaf)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
        pi._seat_bind_source(link / "work" / "leaf.txt", output=True)


@pytest.mark.skipif(os.getuid() == 0, reason="root reads a search-only directory anyway")
def test_a_search_only_ancestor_does_not_refuse_the_bind_source(tmp_path, monkeypatch):
    # Team hosts make /mnt/workspace/{users,worktrees} root-owned 0711 (agent-harness#1317).
    gate = tmp_path / "gate"
    work = gate / "user" / "work"
    work.mkdir(parents=True)
    out = work / "out.txt"
    out.write_text("x")
    (work / "link").symlink_to(gate / "user", target_is_directory=True)
    gate.chmod(0o111)
    try:
        assert pi._seat_bind_source(work) == str(work)
        assert pi._seat_bind_source(out, output=True) == str(out)
        # The walk itself still never follows a link component it meets.
        monkeypatch.setattr(pi, "_trusted_host_path", lambda p: os.path.abspath(os.fspath(p)))
        with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
            pi._seat_bind_source(work / "link" / "work")
    finally:
        gate.chmod(0o755)


def test_a_parent_link_another_account_owns_is_still_refused(tmp_path, monkeypatch):
    _real, link = _linked_workspace(tmp_path)
    operator = os.getuid()
    monkeypatch.setattr(pi.os, "getuid", lambda: operator + 1 if operator else 1)
    assert pi._trusted_host_path(link / "work") == str(link / "work")
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
        pi._seat_bind_source(link / "work")


@needs_owner
def test_an_owned_seat_runs_below_a_linked_workspace(tmp_path):
    """The seat sees its cwd, input and output at the paths its argv names; the host reads
    the output back through the resolved path."""
    _real, link = _linked_workspace(tmp_path)
    cwd = link / "work"
    (cwd / "review-bundle.md").write_text("BUNDLE-CONTENT\n")
    output = cwd / "out.txt"
    command = ["/bin/sh", "-c", 'cat review-bundle.md > "$1"', "sh", str(output)]
    with pi._seat_command_profile(command, env={"PATH": "/usr/bin:/bin"}, cwd=cwd,
                                  outputs=(output,),
                                  role=pi.SeatLaunchRole.PROVIDER_ADMIN) as (owned, profile):
        process = pi.launch_owned(owned, role=pi.SeatLaunchRole.PROVIDER_ADMIN, profile=profile,
                                  cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  start_new_session=True)
        try:
            _out, err = process.communicate(timeout=60)
        finally:
            pi._terminate_process_group(process)
    assert process.returncode == 0, err
    assert pi._read_seat_text(output) == "BUNDLE-CONTENT\n"


@pytest.mark.skipif(os.getuid() == 0, reason="root reads a search-only directory anyway")
def test_the_seat_io_parent_is_readable_below_a_search_only_ancestor(tmp_path):
    # Intermediate hops are O_PATH; the parent handed back must stay O_RDONLY because
    # `_seat_transcripts` scandirs it (agent-harness#1317, advisor-board stack review).
    from phase_loop_runtime.agy_canary_evidence import _seat_parent_descriptor

    gate = tmp_path / "gate"
    work = gate / "user" / "work"
    work.mkdir(parents=True)
    (work / "a.txt").write_text("x")
    gate.chmod(0o111)
    root = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        directory, name = _seat_parent_descriptor(root, str(work / "a.txt").lstrip("/"))
        try:
            assert name == "a.txt"
            with os.scandir(directory) as entries:
                assert [entry.name for entry in entries] == ["a.txt"]
        finally:
            os.close(directory)
    finally:
        os.close(root)
        gate.chmod(0o755)
