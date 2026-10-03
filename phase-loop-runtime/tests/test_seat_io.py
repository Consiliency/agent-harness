"""Seat I/O accepts bounded private regular files through directory descriptors."""

import os
import sys

import pytest

from phase_loop_runtime import agy_canary_evidence as evidence


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat I/O contract")


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink", "large", "parent-link"])
def test_reader_refuses_non_private_or_unbounded_files(tmp_path, kind):
    original = tmp_path / "original"
    original.write_bytes(b"synthetic")
    target = tmp_path / "answer"
    if kind == "symlink":
        target.symlink_to(original)
    elif kind == "fifo":
        os.mkfifo(target)
    elif kind == "hardlink":
        os.link(original, target)
    elif kind == "large":
        target.write_bytes(b"x" * 65)
    else:
        target.symlink_to(tmp_path, target_is_directory=True)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError):
            evidence.read_seat_output(descriptor, "answer/original" if kind == "parent-link" else "answer",
                                      max_bytes=64, expect_uid=os.getuid())
    finally:
        os.close(descriptor)


def test_reader_accepts_regular_nested_output(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/answer").write_bytes(b"synthetic")
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert evidence.read_seat_output(descriptor, "nested/answer", max_bytes=64,
                                         expect_uid=os.getuid()) == b"synthetic"
    finally:
        os.close(descriptor)


def test_writer_refuses_a_changed_precreated_inode(tmp_path):
    output = tmp_path / "answer"
    output.write_bytes(b"")
    initial = output.stat()
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"synthetic")
    replacement.replace(output)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(evidence.AgyCanaryEvidenceError):
            evidence.write_seat_path(descriptor, "answer", b"changed",
                                     expected_inode=(initial.st_dev, initial.st_ino))
        assert output.read_bytes() == b"synthetic"
    finally:
        os.close(descriptor)
