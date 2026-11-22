# Detailed plan: the Codex availability probe honours CODEX_HOME (agent-harness#2078)

## Task
**Outcome served:** standalone: a Codex board seat whose login lives in `$CODEX_HOME` passes board composition. The `codex login status` probe reads the same login that the seat's admission gate reads.

`panel_invoker.seat_profile` copies Codex's `auth.json` from `$HOME/.codex` only. Every other Codex read uses `seat_codex_credential.auth_path(env)`, which tries `$CODEX_HOME` and then `~/.codex`. See the triage at agent-harness#2078 (issuecomment-7079120602).

## Research summary
- `seat_profile` takes `home = Path(env["HOME"])` and calls `credential(".codex/auth.json")`, which calls `_seat_credential(home, relative)`.
- `_seat_credential(home, relative)` checks the root with `_seat_bind_source` and reads with `read_seat_output`. That read refuses links and files owned by other accounts.
- In the `PROVIDER_ADMIN` role, a missing source (`FileNotFoundError`) is skipped.
- `seat_codex_credential.auth_path(env)` is the CLI's own resolution. The fix reuses it and adds no new read primitive.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `seat_profile.credential` — modify — take an optional `source_root` and `source_relative`; keep the destination `relative`.
- `seat_profile` codex branch — modify — the source is `auth_path(env).parent` / `auth.json`. The destination, shape, tolerance and `CODEX_HOME` value do not change.

### `phase-loop-runtime/tests/test_seat_profile_codex_home.py` (create)
- Cases (a), (b) and (c) from the triage, using synthetic `auth.json` files with distinct `tokens.account_id`.

### `CHANGELOG.md` (modify)
- Add an Unreleased "Fixed" entry.

## Documentation impact
None. This is a bug fix to internal resolution and needs only the CHANGELOG entry.

## Dependencies & order
1. The test (red).
2. The fix.
3. Mutation check: revert to the HOME-only source; (b) and (c) must fail.

## Verification
Run each file serially under `timeout 600`, gated on memory headroom and PSI:
- `tests/test_seat_profile_codex_home.py`
- `tests/test_seat_profiles.py`
- `tests/test_seat_reference_inventory.py`
- `tests/test_executor_availability.py`
- `tests/test_seat_profile_codex.py`
- `tests/test_seat_codex_credential.py`

Then check that no SDK proof binding moved and that `tests/data/seat_profile_digests_jailcore.json` did not move.

## Acceptance criteria
- (a) passes; (b) projects the `CODEX_HOME` account and is not skipped; (c) the copied account id equals `read_auth(env)`'s.
- The launch inventory, SDK proof bindings and jail digests are unchanged.
