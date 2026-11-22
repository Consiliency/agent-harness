# Detailed plan: grok seat tool-surface verification for builds with no `--list-tools`

Revision r4 (2026-11-20): r3 plus the r3 review's three implementation proofs, binding on
their lanes (contract §10). The detail is in the contract; this plan points at it.

## Task

`probe_grok_tools` can only verify a grok build that has `--list-tools`. No installed build
has it (0.1.220, 1.0.13, 1.0.77, 1.0.88, 1.0.89), so every route records
`grok_tool_surface_unverified` and `grok_tool_gate` refuses every grok launch.
A downstream board run is below its three-seat floor partly because of this.

Give the probe a second basis: a frozen, measured tool surface per grok binary digest and
route argv digest, valid only inside one enforced launch context. The code lands first and
fails closed with no record. The measurement is a separate, owner-gated live step on the measurement host. The outcome that counts is a grok seat the review
board can launch, not evidence alone.

All schemas, rules, offline results and the owner procedure are frozen in
`plans/artifacts/grok-tool-surface-contract-v1.md` ("the contract", r4). This plan cites its
sections and does not restate them.

## Research summary

- `panel_invoker.py`: `probe_grok_tools` (around line 15319) gates on two help strings;
  `record_tool_probe` writes the `tool_probe.v1` receipt that `grok_tool_gate` checks by
  binary and argv digest. `grok_runtime_forms` builds the five route forms.
- The 1.0.89 binary documents a per-session `tool_definitions.json`, rewritten on each model
  request. It is the only record of the offered surface (contract §1).
- All five forms parse on 1.0.89, hidden `--no-memory` included. That is parsing only
  (contract §2).
- `seat_profile` builds the grok seat's private home and projects two credential files.
- Egress: `start_proxy` plus `isolated_network(…, proxy_socket=…)` is the Gemini seat's
  proxy-only namespace. Only `codex` and `gemini` allow-lists ship (contract §5.2).
- A governed board review is brokered (`brokered_route`, around line 2086), so its grok leg
  launches the `sealed` or `staged` form; the `review` form is the unbrokered leg. All three
  share one launch site (contract §4.6).
- Reuse: the shipped agy catalog pattern, and the `qualification` rows in
  `tests/data/seat_launch_references.json`.

## Changes

Paths are under `phase-loop-runtime/` unless they start with `plans/`, `docs/` or `CHANGELOG`.
Contract erratum 8 adds lanes E8-A to E8-C.

### Lane L1 — frozen basis in the probe and gate (code; lands alone, fails closed)

#### `src/phase_loop_runtime/grok_tool_surface.py` (create)
- `load_catalog()` — add — strict loader, `revoked` list included (contract §3.1).
- `load_host_record(binary_sha256)` — add — host-local reader, host-bound (contract §3.2).
- `frozen_surface(...)` — add — precedence, shadow reporting, version and help binding
  (contract §3.2, §4.1).
- `GROK_SEAT_CONTEXT`, the pinned discovery set, `context_digest()`, `verify_launch_context(...)`
  — add — the launch context and its checks (contract §4.4).

#### `src/phase_loop_runtime/data/grok_tool_surfaces.json` (create)
- catalog with empty `surfaces` and `revoked` — add.

#### `pyproject.toml` (modify)
- package-data list — modify — add `data/grok_tool_surfaces.json`.

#### `src/phase_loop_runtime/panel_invoker.py` (modify)
- `probe_grok_tools` — modify — frozen branch when the help gate fails (contract §4.1). The
  `--list-tools` branch is not edited.
- `record_tool_probe` — modify — additive receipt fields (contract §4.2). Its nonempty rule
  is not edited (contract §3.1, "Empty lists").
- `grok_tool_gate` — modify — keyword `context=None`; field-combination validation;
  re-resolution of the record on every consumption (contract §4.2, §4.3).
- early gates and `launch_owned` — modify — the two-step check: provisional at the early
  gates, final after composition; every consumer ineligible by default (contract §4.4).
- Untouched: `_grok_tools_admitted`, `_grok_argv_digest`, `_grok_admin_command`, the forms,
  `_HARNESS_DETAIL_CODES`. No public code is added (contract §4.5 quotes the vocabulary).

#### `src/phase_loop_runtime/seat_window.py` (modify)
- `cli_main`, `probe-tools` branch — modify — additive row fields (contract §4.5).

#### `tests/fixtures/grok_1_0_89/` (create)
- `help.out`, `version.out`, `listtools.err`, `forms.json`, `argv-parse-summary.json` — add —
  real 1.0.89 outputs, checked against the five digests in the contract header.

#### `tests/test_grok_tool_surface.py` (create)
- basis selection on the real 1.0.89 help and on the stand-in help;
- empty catalog: all five forms refuse;
- a matching record passes the provisional step and launches only on a marked profile; each refusal of contract
  §4.1–§4.4 alone refuses, including a revoked digest, a replaced or withdrawn host-local
  record, a context-digest drift, a tree containing a discovery path, a `GROK_*` variable, a
  managed-config file, and `context=None`;
- precedence and `shadowed` reporting (contract §3.2);
- the empty-list cases of contract §3.1;
- loader refusals, one per rule;
- one row per consumer in the contract §4.4 table, with a legacy, a `list_tools` and a
  `frozen_measurement` receipt;
- fixture guard (five digests; `forms.json` digests equal the live forms');
- catalog parity on the full context (contract §3.3); trivial while empty.

#### `tests/data/seat_launch_references.json` (modify)
- rows for the detected call sites — add — as contract §8 describes.

### Lane L2a — vendor-only `grok-review` egress with a request budget (code; no live run)

#### `src/phase_loop_runtime/seat_egress/grok-review-allowlist.json` (create)
- allow-list `grok-review` — add — derived and confirmed offline; shared by the measurement
  and the board leg; the id `grok` stays reserved (contract §5.2).

#### `src/phase_loop_runtime/seat_egress/proxy.mjs`, `src/phase_loop_runtime/seat_egress_proxy.py` (modify)
- `request_budget` — add — narrowing-only cap, decremented before forwarding (contract §5.3).

#### `src/phase_loop_runtime/panel_invoker.py`, `src/phase_loop_runtime/sandbox_egress.py` (modify)
- `seat_profile` proxy projection; the proxy-only namespace for a launch-owner leg — add,
  `sandbox_egress.py` only if it must be extended (contract §5.2).

#### `tests/test_grok_measure_egress.py` (create)
- the refusal tests of contract §5.2; the budget stops request N+1; the `codex` and `gemini`
  allow-list digests and budget-less proxy decisions are unchanged (contract §8).

### Lane L2b — measurement tool (code; no live run)

#### `src/phase_loop_runtime/grok_tool_surface.py` (modify)
- `measure_route(...)` — add — one launch through the seat's own composition under a
  measurement admission (contract §5.1, §5.4).
- `read_definitions(...)`, `extract_tool_names(...)` — add — descriptor-checked read; shapes
  S1–S3 (contract §5.5, §5.6).
- the grant ledger (reserve, settle), result records, `aggregate(...)`, `reprocess(...)`,
  `purge(...)`, `verify_probe(...)` — add — contract §5.3, §5.7–§5.10.

#### `src/phase_loop_runtime/panel_invoker.py` (modify)
- `require_grok_admission` — modify — measurement admission (contract §5.1).
- `seat_profile` — modify only if needed — the sessions bind (contract §5.1).

#### `src/phase_loop_runtime/seat_window.py` (modify)
- `register_parser`, `cli_main` — modify — action `measure-tools` with the flags the
  procedure uses (contract §5.10).

#### `tests/test_grok_tool_surface_measure.py` (create)
- recording runner and fixture upstream only; no test contacts the vendor;
- digest-equal launch argv; the admission refuses without an egress prefix;
- each `status` of contract §5.8; the interruption, restart and concurrency tests of
  contract §5.3;
- immutable records, withdraw-before-launch, latest-attempt-wins, cross-directory locking
  (contract §5.7); a TLS failure or bypass yields no qualifying capture (contract §5.5);
- `format_unrecognised` blocks the grant until reprocessed, with no second charge (contract
  §5.6);
- the key allow-list, untrusted strings, the sentinel, and operative retention (contract
  §5.9).

#### `tests/data/seat_launch_references.json` (modify)
- the measurement launch under `qualification`, and its `host-io` rows — add.

### Lane L2c — the board review leg consumes the basis (code; no live run)

#### `src/phase_loop_runtime/panel_invoker.py` (modify)
- the board leg's egress setup (search `gemini_egress`) and `_run_leg_with_liveness` — modify
  — for a grok leg on a frozen-basis receipt: the `grok-review` proxy-only namespace, then
  the final context check; no fallback (contract §4.6). Other legs are byte-identical.

#### `tests/test_grok_board_leg_frozen_basis.py` (create)
- the end-to-end stand-in test of contract §4.6: `sealed`, `staged` and `review` legs
  complete through `_exec_leg`; each listed refusal launches nothing.

### Lane L3 — record the measurement (data; after the owner-gated step)

#### `plans/evidence/seat-grok/tool-surface.json` (create)
- the aggregate from the measurement host — add.

#### `src/phase_loop_runtime/data/grok_tool_surfaces.json` (modify)
- one `surfaces` entry from the eligible, measured routes — add.

L3 supplies the `tool-surface.json` input EC-GROK-2 names. It does not tick EC-GROK-2; the
other proofs and the SL-2.1 cases stay open.

## Documentation impact

- `CHANGELOG.md` — modify — one Unreleased entry per lane, each naming the pins that move
  and the requalification it causes (contract §8).
- `docs/review-seats-readiness.md` — modify — Grok row: the probe basis, its context, and
  that a new digest needs a measurement.
- `phase-loop-runtime/README.md` — modify — only if it lists `seat-window` actions.
- `plans/phase-plan-v1-seats-GROK.md` — not edited.

## Dependencies & order

1. **L1** first; independent of any live result.
2. **L2a**, independent of L1.
3. **L2b** and **L2c** after L1 and L2a; independent of each other.
4. **Owner-gated measurement** after all four merge and the re-review accepts. Without L2c
   a measurement would be evidence only, so it does not run before L2c.
5. **L3** after the measurement.

L2 is split because it exceeds the bounded-change size as one lane. Land the four code lanes
close together and requalify windows once (contract §8).

## Owner-gated measurement (not a code lane)

Decision D4, the only one put to the owner. Exact commands and preconditions: contract
§5.10.

- **Where:** the measurement host, a scratch worktree of merged `main`.
- **Grant, for one named release image:** 3 planned launches (the `review` pilot, then
  `sealed` and `staged`), a retry allowance of 2, budget 1 per launch: at most 5 counted
  requests. The cap of 7 is the ledger's ceiling. The ledger is durable and bound to grant,
  host and binary (contract §5.3).
- **Procedure:** paste-safe, image verified first, pilot record checked before the other
  routes, probe results compared explicitly (contract §5.10).
- **Egress:** vendor-only, proxy-only namespace; no host networking (contract §5.2).
- **Secrets:** the seat's own credential projection; names and digests only in evidence;
  retention per contract §5.9.
- **A failed pilot** costs at most one request and is fixed offline.

No agent runs this without the owner's grant.

## New grok builds and integrity

Contract §6: a new digest fails closed until measured, and each needs a grant. Contract §8:
the pins each lane moves, the window requalification, and the guards for pins that must not
move.

## Verification

Shared-host rules: one command at a time, serial, without `-n`, with a timeout, after
checking headroom. No whole-suite run. Full verification is hosted CI or Gate A.

```bash
cd phase-loop-runtime
for PY in 3.12 3.14.10; do
  UV_PROJECT_ENVIRONMENT=".venv-$PY" timeout 900 uv run --frozen --python "$PY" \
    pytest -p no:cacheprovider -q \
    tests/test_grok_tool_surface.py \
    tests/test_grok_measure_egress.py \
    tests/test_grok_tool_surface_measure.py \
    tests/test_grok_board_leg_frozen_basis.py \
    tests/test_grok_sandbox_seat_approval.py \
    tests/test_seat_reference_inventory.py \
    tests/test_agy_qci.py
done
```

Each lane runs the files it owns plus the last three. L2a also runs, one at a time,
`tests/test_gemini_seat_egress_1170.py` and `tests/test_seat_egress_allowlist_codex.py`.
Then, with no model call:

```bash
timeout 300 uv run --frozen phase-loop seat-window probe-tools --vendor grok
```

Before any record exists: exit 1, `"status": "candidate"`, every route
`"passed": false, "basis": "none"`.

## Acceptance criteria

- [ ] With the real 1.0.89 fixtures and an empty catalog, every form refuses with
      `grok_tool_surface_unverified` (`tests/test_grok_tool_surface.py`).
- [ ] A board review leg on a frozen-basis record launches the `sealed`, `staged` and
      `review` forms under the `grok-review` policy, and every refusal in contract
      §4.1–§4.6 launches nothing (`tests/test_grok_board_leg_frozen_basis.py`);
      `tests/test_grok_sandbox_seat_approval.py` passes unedited.
- [ ] A measurement launch cannot start without vendor-only egress, and the proxy denies
      counted request N+1 (`tests/test_grok_measure_egress.py`).
- [ ] The grant ledger keeps its charge across a kill, a restart and a fresh output
      directory, and no stale passing route stays consumable
      (`tests/test_grok_tool_surface_measure.py`).
- [ ] `tests/test_seat_reference_inventory.py` and `tests/test_agy_qci.py` pass on Python
      3.12 and 3.14.10.

Contract §10's binding criteria BA-1 (L2a, L2b), BA-2 (L2b) and BA-3 (L2c, L2b) are
acceptance criteria of those lanes too, and gate D4.

## Follow-ups

- F1 — a grok watch job (the AGYROLL watch pattern).
- F2 — measure a candidate release before `current` flips (agent-harness#1820).
- F3 — ask xAI for a definitions-only, credential-free listing flag.
- F4 — the jailed seat's `grok` allow-list (SEATS GROK SL-1) and broader networking.
- F5 — fix any route form the measurement shows as not admitted.
- F6 — other models and efforts.
- F7 — executor-context eligibility for `execute` and `workflow`, and their measurement
  (dropped here by ruling C1).
- F8 — the remaining EC-GROK-2 proofs and SL-2.1 cases.
- F9 — a standing grant, scoped as contract §6 states (D5, deferred).
- F10 — bind account and server-side rollout scope, or expire records.
- F11 — file the tracking issue (draft in the triage).
- F12 — mask project-config paths in the disposable clone, so `staged` works for a
  repository that carries them (contract §4.4).

## Decisions

Rulings on D1–D3, D5, D6, C1, C2 (resolved) and the reviews are recorded in contract §9.
Open: D4, the owner's grant (1.0.92: contract erratum 8, item 9).

## Execution Policy

- execute: effort=high, reason=fail-closed admission gate, egress policy and a credential-handling launch path
