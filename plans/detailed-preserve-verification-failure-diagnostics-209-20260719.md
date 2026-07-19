# Detailed plan: preserve raw failure diagnostics on verification failure (Consiliency/agent-harness#209)

## Task

When runner-executed verification fails, the runner-owned terminal artifact
must **localize and preserve the raw diagnostic of the stage that broke** — not
scrub it down to a bare `exit_code`. Concretely (from Consiliency/agent-harness#209):

1. A failed/blocked verification verdict must carry a **bounded raw diagnostic**
   (a tail of the failing stage's captured output) plus a typed
   `failure_kind ∈ {timeout, error, nonzero_exit}` and the exit context (argv,
   role, exit_code).
2. An **empty diagnostic on a failed verdict is itself rejected** — you cannot
   claim "verification failed" while surfacing no evidence of *why* (this is the
   anti-scrubbing property; scrubbed diagnostics were a named contributor to the
   multi-day thrash in Consiliency/agent-harness#213).
3. A **declared multi-step chain** preserves per-step pass/fail in **declared
   order** and reduces **fail-closed** if an earlier step failed even when a
   later step passed.

## Research summary

Verified against source this session (`phase-loop-runtime/src/phase_loop_runtime/`):

- **`verification_evidence.py`** — `_run_process` (~:815) already captures
  **combined stdout+stderr** into `verification.log` (`stderr=subprocess.STDOUT`),
  records `exit_code` (124 on `TimeoutExpired`, 127 on `FileNotFoundError`/empty
  argv, else child's code), and each `VerificationCommandEvidence` records a
  **start** `log_offset = log_file.tell()`. So the raw bytes of every stage
  already survive in `verification.log`, addressable by successive offsets.
- **The gate verdict** is `VerificationArtifactValidation` (`:435`), returned by
  `validate_verification_artifact` (`:628`), serialized by `.to_json()`. On a red
  chain its `findings` is just `("commands[0].exit_code=1",)` — **no typed kind,
  no raw excerpt**. `_nonzero_exit_findings` (`:757`) already iterates **all**
  commands + env_refresh + suite and blocks on any non-zero → the **ordered
  fail-closed reduction already exists** (repro below confirms step1-fails /
  step2-passes → `ok=False, code=nonzero_exit`).
- **`closeout.py`** — `_apply_verification_evidence_gate` (`:336`) calls
  `validate_verification_artifact`, takes `validation.to_json()` as
  `validation_payload`, and returns it under `results`. The caller collects
  `verification_results` (`:108–190`) and threads it into
  `PhaseLoopVerification(results=tuple(verification_results))` (`:245`) →
  `closeout.to_json()` → **persisted closeout artifact**. `PhaseLoopVerification.results`
  is `tuple[dict[str, Any], ...]` (`models.py:932`), serialized via
  `asdict`+`clean_dict`. **Durability confirmed**: enriching `validation_payload`
  lands the diagnostic in the durable, terminal-summary-read record — not just a
  transient list. `clean_dict` (`models.py:2286`) strips only `None`, so a
  non-empty diagnostic survives.

**Repro on current main** (two-step chain, step1 writes `DISTINCTIVE_FAILURE_REASON`
to stderr + exits 1, step2 passes): gate → `ok=False code=nonzero_exit`,
`findings=('commands[0].exit_code=1',)`, and the distinctive stderr is present in
`verification.log` but **absent from the verdict** (`failure_kind` absent too).
Gap confirmed; fail-closed reduction confirmed already-present.

## Design decision: enrich the non-frozen verdict layer (Option A) — no schema bump

`verification.json` is schema-v1 **frozen** by
`_contract_docs/runtime/verification-evidence-contract.md`, but the diagnostic
belongs on the **runner-owned verdict** (`VerificationArtifactValidation` /
`validation_payload`), which is **not** part of that frozen producer artifact and
already flows durably into the closeout record. Raw bytes are already captured in
`verification.log`; we only **slice a bounded tail** at gate time. No new capture,
no schema bump.

> Note (scope framing for CR): the contract "freezes the additive artifact for
> future runner wiring" — a *stable-base-extend-additively* posture, and #209 is
> that future wiring. A minimal additive `suite.log_offset` (schema v2) remains a
> live fallback **only** if the verdict layer proves insufficient. This plan does
> **not** bump the schema; it states the fallback so the choice is deliberate.

### Frozen-vocabulary confirmation

`verification.json` top-level fields and `commands[]` / `env_refresh` / `suite`
item fields (contract lines 10–22) are **unchanged**. `SCHEMA_VERSION` stays `1`.
`_result_to_payload` / `_command_to_payload` / `load_verification_artifact` /
`_require_keys` are **untouched**. No new producer-artifact vocabulary is
introduced. All new fields live on the verdict payload only.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` (modify)

- `_classify_failure_kind(exit_code) -> str` — **add** — new module-level helper.
  Typed map, stated as a table:

  | exit_code | failure_kind |
  |-----------|--------------|
  | `124`     | `timeout`    (set by `_run_process` on `TimeoutExpired`) |
  | `127`     | `error`      (missing executable / empty argv) |
  | any other non-zero | `nonzero_exit` |

  Only called for non-zero codes; `0` never produces a diagnostic.

- `_stage_log_slice(log_bytes, start, end, cap) -> str` — **add** — slice
  `log_bytes[start:end]`, take the **last `cap` bytes** (tail — the failure
  reason is at the end of a stage's output), decode `utf-8, errors="replace"`.
  `cap` = module constant `DIAGNOSTIC_TAIL_BYTES = 4096` (**bounded**; named,
  not open-ended). Returns `""` if the region is empty.

- `_stage_boundaries(result) -> list[tuple[role, index, argv, exit_code, start, end]]`
  — **add** — compute per-stage `[start, end)` byte regions over
  `verification.log`, in **declared order**:
  - `commands[i]`: `start = commands[i].log_offset`,
    `end = commands[i+1].log_offset` if present, else the **suite start** if a
    suite exists (see boundary rule), else `len(log_bytes)`.
  - `suite`: **`suite` has no `log_offset`** (frozen shape). The suite always
    runs **last**, so its bytes are at the log tail. **Boundary rule (fail
    closed, do not mislabel):** the suite region is `[last_command_end, EOF)`
    when there are commands, else `[end_of_preamble, EOF)`. Because we only ever
    take a **bounded tail** of a region and the suite is last, a whole-log tail
    is a correct superset for a suite failure; we **never** attribute suite bytes
    to a *command* region (commands are bounded above by the next command's
    offset or the suite's start, never by EOF when a suite follows).
  - `env_refresh`: has **no** `log_offset`; env-refresh output is written before
    commands. We do **not** attempt a precise env_refresh slice. On an
    env_refresh-only failure, the diagnostic falls back to a **whole-log bounded
    tail** with `failure_kind` from its exit_code and an explicit
    `region: "log_tail"` marker (see empty-diagnostic rule). This is the one
    imprecise case; it is marked, not silently mislabeled.

- `VerificationArtifactValidation` (`:435`) — **modify** — add one field:
  `diagnostics: tuple[dict[str, Any], ...] = ()`. Extend `.to_json()` to emit
  `"diagnostics": list(self.diagnostics)`. (Additive; default `()` keeps every
  existing `ok=True` / integrity-only path byte-stable except the new key.)

- `_build_failure_diagnostics(result, log_bytes) -> tuple[dict, ...]` — **add** —
  for each stage with a non-zero exit (in declared order: `commands[0..n]`,
  `env_refresh`, `suite` — matching `_nonzero_exit_findings`' traversal), emit:
  ```
  {"role": "command"|"env_refresh"|"suite", "index": int|None,
   "argv": [...], "exit_code": int, "failure_kind": "...",
   "raw_tail": "<bounded tail>", "region": "stage"|"log_tail",
   "truncated": bool}
  ```
  `truncated` = region length > cap. Non-failing steps are **not** emitted here
  (their pass/fail is already in `exit_summary.commands`, preserved in declared
  order — see per-step reduction note). Ordered exactly as traversed.

- `validate_verification_artifact` (`:628`) — **modify** — in the `nonzero_exit`
  branch (and the `log_sha256_mismatch` / `missing_log` branches that still carry
  a parsed `result` with non-zero exits), read `log_bytes` (already read for the
  sha check on the `nonzero_exit` path) and populate `diagnostics=` via
  `_build_failure_diagnostics`. **Empty-diagnostic rejection (anti-scrubbing):**
  if the verdict is a failure due to a non-zero exit **and** the computed
  `diagnostics` is empty **or** every failing stage's `raw_tail` is empty, emit a
  synthetic diagnostic `{"role":..., "failure_kind":..., "exit_code":...,
  "raw_tail":"", "region":"absent", "note":"failing stage produced no captured
  output"}` — the verdict **still carries the typed failure context** (argv +
  kind + code are never empty for a real failure), so "empty diagnostic on a
  failed verdict" cannot occur. Define **empty** for the verdict as: a failed
  verdict whose `diagnostics` tuple is `()` → that is the rejected state, and it
  is made unreachable by always constructing at least the typed context per
  failing stage.

  > Scope guard: the executor-self-reported path
  > (`_apply_verification_evidence_gate`: `reported != "passed" → return None`,
  > closeout.py:344–346) is **out of scope** — #209 is about the *runner-executed
  > multi-stage proof*, not the agent's self-assertion. No change there.

### `phase-loop-runtime/src/phase_loop_runtime/closeout.py` (no functional change; verify pass-through)

`validation.to_json()` now includes `diagnostics`; it already flows through
`verification_results` → `PhaseLoopVerification.results` → persisted closeout.
**No edit** unless a pass-through drops the key — confirmed it does not
(`clean_dict` strips only `None`; `diagnostics` is a non-`None` list). This
section exists to record the deliberate no-op, per scope discipline.

## Documentation impact

- `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md`
  — **modify** — add a short subsection documenting the **verdict-layer**
  `diagnostics` field on `VerificationArtifactValidation` (typed `failure_kind`
  map, bounded `DIAGNOSTIC_TAIL_BYTES` tail, declared-order per-stage,
  empty-diagnostic rejection, suite/env_refresh `log_tail` fallback). Explicitly
  state the **producer `verification.json` schema is unchanged at v1** — the
  diagnostic is a non-frozen verdict/consumer surface. This documents the
  redaction posture: *bounded tail of already-captured `verification.log` bytes,
  same trust boundary as the log, no new capture path.*
- `CHANGELOG.md` — **add** — entry under the next version: "Preserve raw failure
  diagnostics on verification failure (Consiliency/agent-harness#209): the
  verification verdict now carries a typed `failure_kind` + bounded raw-output
  tail per failing stage, in declared order; a failed verdict can no longer be
  emitted without diagnostic context."
- No `README`/`AGENTS`/`llms.txt` footprint — internal runtime verdict surface.

## Dependencies & order

1. `_classify_failure_kind` + `DIAGNOSTIC_TAIL_BYTES` + `_stage_boundaries` +
   `_stage_log_slice` + `_build_failure_diagnostics` (pure helpers, no callers yet).
2. `VerificationArtifactValidation` field + `.to_json()` (additive).
3. Wire into `validate_verification_artifact` failure branches + empty-diagnostic rejection.
4. Contract-doc + CHANGELOG.
5. Regression tests (below).

No blocking external dependency; no migration. Redaction posture is unchanged
(no new bytes captured; only a bounded slice of the existing log surfaces into a
record that already surfaces `exit_summary`).

## Verification

Run from `phase-loop-runtime/`:

```bash
# New + existing evidence/closeout tests (unmarked module → not dotfiles_integration-skipped)
PYTHONPATH=src:tests python3 -m pytest tests/test_verification_evidence.py \
  tests/test_closeout_verification_gate.py -q

# Regression asserts (baked into test_verification_evidence.py):
#  (a) single failing command: stderr excerpt SURVIVES in verdict.diagnostics[0].raw_tail,
#      failure_kind=="nonzero_exit", argv present.
#  (b) two-step chain step1 fails / step2 passes: verdict ok is False (terminal NOT passed),
#      diagnostics[0].index==0 present with step1's raw_tail; exit_summary.commands==[1,0]
#      preserves per-step order.
#  (c) timeout (exit 124) -> failure_kind=="timeout"; missing exec (127) -> "error".
#  (d) failing stage with NO output -> verdict still carries typed context
#      (argv+kind+code), diagnostics tuple is NON-empty (anti-scrubbing).
#  (e) bounded: a failing command emitting >DIAGNOSTIC_TAIL_BYTES of output ->
#      raw_tail length <= cap and truncated==True.
#  (f) green run -> diagnostics == () (no diagnostic on success; no key churn beyond []).

# Mutation check: revert _build_failure_diagnostics wiring -> (a),(b),(d) fail.
```

## Acceptance criteria

- [ ] A single failing verification command yields a verdict whose
  `diagnostics[0].raw_tail` contains the command's real stderr excerpt and
  `failure_kind == "nonzero_exit"` (repro's `DISTINCTIVE_FAILURE_REASON` case).
- [ ] A declared two-step chain where step 1 fails and step 2 passes yields a
  verdict with `ok is False` (terminal not `passed`) **and** step 1's diagnostic
  present, with per-step order preserved in `exit_summary.commands`.
- [ ] `exit_code == 124 → failure_kind == "timeout"`; `127 → "error"`; other
  non-zero `→ "nonzero_exit"`.
- [ ] A failed verdict can never carry an empty `diagnostics` tuple — a
  no-output failure still surfaces typed `{role, argv, exit_code, failure_kind}`.
- [ ] `raw_tail` is bounded by `DIAGNOSTIC_TAIL_BYTES`; over-cap output sets
  `truncated == True`.
- [ ] `verification.json` producer schema is unchanged (`SCHEMA_VERSION == 1`;
  `load_verification_artifact` `_require_keys` set untouched); contract doc
  documents the verdict-layer `diagnostics` field and unchanged producer schema.
- [ ] A green run produces `diagnostics == ()` (no diagnostic on success).

## Execution Policy

- execute: effort=medium, reason=security/verification-sensitive verdict layer
  with fail-closed + anti-scrubbing semantics and boundary-slicing edge cases;
  not mechanical, but bounded to one module + tests + docs.
