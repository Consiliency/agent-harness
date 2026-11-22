# Detailed plan: provider_tree_proof imports on native Windows (POSIX unchanged)

## Task
Make `phase_loop_runtime.provider_tree_proof` importable on native Windows with no POSIX
behaviour change. On a platform without `select.poll`, every pidfd/poll proof path fails
closed (`UNKNOWN`, never `PROVEN`). Unblocks agent-harness#2086 (JEVHOST, contract S5).
Report further import-time Windows blockers outside this file, but do not fix them.

## Research summary
`provider_tree_proof.py:48` evaluates `select.POLLIN | select.POLLHUP | select.POLLERR`
at import. Windows' `select` has neither `poll` nor `POLL*`. A simulated Windows import
(stdlib and third-party deps warmed, then the POSIX names removed) fails there. Uses at
call time are `TreeProof._read`/`wait` (`select.poll`), `_release_if_no_reader`, and the
launch-only pin and teardown helpers. The file is a whole-file Claude SDK proof input
(`claude_seat_transport._TP`). `sdk` is not admitted (there is no receipt), so
`verify-proof` and `audit-order` pass trivially, and the rebind is the moved file digest,
reported in the PR. Fixtures key on module and function names, not line numbers.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/provider_tree_proof.py` (modify)
- `_PIDFD_READY`: modify. Keep the same POSIX expression, guarded by
  `hasattr(select, "poll")`, else `None`.
- `TreeProof._read`: modify. When `_PIDFD_READY is None`, raise
  `ProofFault("poll_unavailable")`, so `observe()` records `UNKNOWN`.
- `TreeProof.wait`: modify. Skip the poll slice when `_PIDFD_READY is None`; `observe()`
  then fails closed.

### `phase-loop-runtime/tests/test_provider_tree_proof_windows.py` (create)
- A subprocess Windows-simulation test: the module imports, `_PIDFD_READY is None`, and a
  `bwrap_init` proof over a readable fd yields `observe()`/`wait()` False with `UNKNOWN`
  `poll_unavailable`.
- A POSIX test: `_PIDFD_READY == POLLIN|POLLHUP|POLLERR`.

### `CHANGELOG.md` (modify)
- An Unreleased fix entry that names the SDK proof-binding movement.

## Documentation impact
- `CHANGELOG.md`: add an entry (above). There is no other doc footprint.

## Dependencies & order
Red-first: add the tests, then run them failing on base. Then edit the module, then run
the tests passing. Then re-run the existing `test_provider_tree_proof.py` and
`test_seat_resource_caps.py`. Then `verify-proof` and `audit-order --base origin/main`.

## Verification
- `timeout 600 .venv/bin/python -m pytest -p no:xdist tests/test_provider_tree_proof_windows.py`
- `timeout 600 .venv/bin/python -m pytest -p no:xdist tests/test_provider_tree_proof.py`
- `timeout 600 .venv/bin/python -m pytest -p no:xdist tests/test_seat_resource_caps.py`
- `python -m phase_loop_runtime.claude_seat_transport verify-proof` → OK
- `python -m phase_loop_runtime.claude_seat_transport audit-order --base origin/main` → OK
- Simulated Windows import of provider_tree_proof, panel_invoker, fab_gate,
  closeout_validators, closeout and runner, with the per-module result.

## Acceptance criteria
- [ ] A simulated Windows import of `phase_loop_runtime.provider_tree_proof` succeeds, and a
      bwrap_init proof's `observe()` returns False with status `UNKNOWN`.
- [ ] On Linux, `provider_tree_proof._PIDFD_READY == select.POLLIN | select.POLLHUP | select.POLLERR`.
- [ ] `test_provider_tree_proof.py` and `test_seat_resource_caps.py` pass.
- [ ] `verify-proof` and `audit-order --base origin/main` print OK. Only the
      `provider_tree_proof.py` whole-file binding moves.

## Execution Policy
- execute: effort=low, reason=single-module guarded constant plus fail-closed checks
