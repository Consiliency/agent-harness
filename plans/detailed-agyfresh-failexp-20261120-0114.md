# Detailed plan: expire repeated-transient failures and name the hold in the doctor (FAILEXP)

## Task

**Outcome served:** the REQUAL early slice of `specs/phase-plans-agyroll-v1.md`: a host
that hit three transient qualification failures recovers without a hand `clear`, and the
doctor shows when the Gemini seat is running on a held image or cannot be covered by one.

Implement EC-REQUAL-5 and EC-REQUAL-8. This is lane SL-3 of
`plans/phase-plan-v1-agyroll-HOLD.md`; it starts after SL-2 (HOLD-CACHE) merges, because it
is the next writer of `agy_qualification.py`. One PR. Planning only here: nothing below was
run.

## Research summary

Read on the RESTORE caps-lane tree. `Store.put_failed` writes a MAC-bound payload
(`help_sha256`, `operation`, `reason`, `status`, `written_under`) with no time and no class;
`Store.get_failed` returns it for ever. `ensure_admitted` has two writers: the failed-outcome
branch (`reason` from the outcome) and the repeated-transient branch (`reason =
"repeated_transient"` once `note_transient` reaches `MAX_TRANSIENT_ATTEMPTS`). Every reader
(`lookup`, `has_record`, `admission_verdict`, the agent-harness#1602 seam, and after SL-1
`admit_seat` and `admit_held`) goes through `get_failed`, so expiry belongs there.
`doctor._seat_cli_qualification` builds one row per leg from
`seat_admission.verdict(leg, os.environ, execute=False)`; the row schema in
`schemas/phase-loop-doctor.v1.schema.json` is closed (`additionalProperties: false`), and
`run_doctor` prints `code`, `reason` or `ready` per row. SL-1 provides
`agy_qualification.hold_status(env, subject_path)` with the object of
`plans/artifacts/agyfresh-hold-lanes.md` §B6.

Paths below are under `phase-loop-runtime/`.

## Changes

### `src/phase_loop_runtime/agy_qualification.py` (modify)

- `Store.put_failed` — modify — new keyword `failure_class` (`"violation"` |
  `"repeated_transient"`, default `"violation"`); the payload gains `class` and `at`
  (epoch seconds, from an injectable clock). MAC context and file name are unchanged.
- `Store.get_failed` — modify — new keywords `now=None`, `prune=False`. An entry whose
  class is `repeated_transient` and whose `at` is more than 24 h before `now` returns
  `None`. With `prune=True` it is also unlinked; only callers that hold `Store.lock()`
  pass it. **Legacy entries** (no `class`): `reason == "repeated_transient"` is treated as
  expired; anything else is a `violation`. A `violation` never expires.
- `FAILED_TRANSIENT_TTL_S = 86_400` — add.
- First-use body (inside the store lock) — modify — the failed-outcome branch writes
  `failure_class="violation"`; the repeated-transient branch writes
  `failure_class="repeated_transient"`; the `get_failed` check at the top of the locked
  section passes `prune=True`. When an expired entry is pruned, the transient counter for
  that key is reset, so first use gets its full attempts again.
- `_classify_failure`, `validate_records`, `validate_directory` and everything on the
  AGYFRESH §3 list — not edited.

### `src/phase_loop_runtime/doctor.py` (modify)

- `_seat_cli_qualification` — modify — for the `gemini` row only, and only when its status
  is not `admits`, resolve the seat subject as `seat_admission` does and add
  `row["hold"] = agy_qualification.hold_status(env, subject_path)` reduced to `coverage`
  and `held`. Any exception leaves the row without the key (the doctor never raises).
- `run_doctor` text — modify — under the Gemini row, one line: `hold: <version>
  (<admission_class>) from <origin>` for an active hold, or `hold: not covered (managed
  release)`.

### `src/phase_loop_runtime/schemas/phase-loop-doctor.v1.schema.json` and `phase-loop-doctor.v1.golden.json` (modify)

- `seat_cli_qualification[].hold` — add — optional object, closed: `coverage` (the two §B6
  values) and `held` (object with `origin`, `version`, `image_sha256`, `admission_class`,
  optional `pending`, or `null`). The golden gains one Gemini row with it.

### `tests/test_agy_self_qualification.py` (modify)

- Expiry at 24 h with an injected clock (just under: still refuses; just over: `None`).
- A `violation` entry persists past any age.
- Both legacy kinds.
- An expired entry is pruned under the lock, the counter resets, and first use runs again
  (the `qualify` stub is called).
- Lookup-only readers see `None` after expiry and do not unlink.
- The existing repeated-transient and `clear` tests stay green; where one asserts the exact
  payload, it gains the two fields.

### `tests/test_agy_hold.py` (modify)

- A subject whose `repeated_transient` entry expired stops being `subject_failed`: at spawn
  the hold reason becomes `subject_unqualified`; at preflight first use runs for the
  subject before any hold.

### `tests/test_seats_teamhost_doctor.py` (modify)

- The Gemini row names an active hold; names "not covered (managed release)" for a managed
  subject; has no `hold` key when the seat admits; and survives `hold_status` raising.
- The golden validates against the schema; `test_doctor_maps_registered_admission_verdicts`
  stays green unmodified.

### `src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `docs/TEAM-ONBOARDING.md`, `CHANGELOG.md` (modify)

- `CONTRACTS.md` — the first-use section's "until `agy-qualification clear`" sentence gains
  the two classes and the 24 h rule; the HOLD section gains the doctor row.
- The card and the onboarding `seat_cli_qualification[]` line — the `hold` key.
- `CHANGELOG.md` — one `[Unreleased]` entry.

## Documentation impact

Listed above. `plans/seats-teamhost-contract.md` is not touched: the §5 repin is the rest
of REQUAL (EC-REQUAL-7).

## Dependencies & order

1. SL-2 merged (single writer of `agy_qualification.py`: RECBIND → HOLD → REQUAL).
2. Tests first, then `agy_qualification.py`, then the schema and golden, then `doctor.py`,
   then docs.
3. Entries written by this change read under the old code (extra payload fields are
   ignored), so rollback is a revert.

Stop rules: `tests/test_agy_qci.py`'s verdict-vector pin changes (AGYFRESH §3); the doctor
row would need a `seat_admission.py` or `panel_invoker.py` edit; another closed schema
rejects the `hold` key.

## Verification

Serial, targeted and bounded (shared-host rule); the locked venv has no xdist, so pass
`-n 0` only where it is installed. Full suite, strict conformance, `--release` and Gate A
(docs changed) run in hosted CI.

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_hold.py tests/test_agy_hold_cache.py tests/test_seats_teamhost_doctor.py \
  tests/test_doctor_bom.py tests/test_seats_teamhost_gemini.py tests/test_agy_qci.py \
  tests/test_seat_reference_inventory.py
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_self_qualification.py
timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract
```

## Acceptance criteria

- [ ] EC-REQUAL-5 — proven by `pytest tests/test_agy_self_qualification.py -k "expir or legacy or violation"`; falsified by a 25-hour-old `repeated_transient` entry that still refuses, or by a `violation` entry that stops refusing.
- [ ] EC-REQUAL-8 — proven by `pytest tests/test_seats_teamhost_doctor.py -k hold`; falsified by a Gemini row with no `hold` key while `hold_status` reports a held image.
- [ ] A managed subject's Gemini row reads "not covered (managed release)" — proven by the same selector.
- [ ] `tests/test_agy_qci.py` passes with the verdict-vector pin unchanged.
