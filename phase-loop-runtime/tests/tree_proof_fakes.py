"""Test-only completion proofs for faked capped launches."""

import os


def attach_pipe_proof(process, *, complete=True):
    """Give a faked capped launch the completion proof production attaches.

    The proof is a real pipe's read end; it reads as complete once the write end is
    closed. With ``complete`` (ordinary tests) it is closed at once, so cleanup keeps its
    process-group behaviour; otherwise the write end is returned for the test to close.
    """
    from phase_loop_runtime import provider_tree_proof

    read_fd, write_fd = os.pipe()
    provider_tree_proof.attach(process, provider_tree_proof.TreeProof.bwrap_init(read_fd))
    if complete:
        os.close(write_fd)
        return None
    return write_fd
