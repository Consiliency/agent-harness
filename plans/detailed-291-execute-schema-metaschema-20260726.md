# Detailed plan: Claude execute fails on unsupported draft-2020-12 meta-schema (ah#291)

## Task
A governed full-phase run completes Claude planning, then the Claude **execute** launch dies before
the model turn with:

```
Error: --json-schema is not a valid JSON Schema: no schema with key or ref "https://json-schema.org/draft/2020-12/schema"
```

The phase-loop-generated structured-output schema (the closeout contract) declares
`"$schema": "https://json-schema.org/draft/2020-12/schema"`. The Claude Code CLI's `--json-schema`
validator (Ajv, default draft-07 meta-registry) has no meta-schema registered for the 2020-12 ref and
**fails closed at argument-parse time** — before any model call. The native Codex executor accepts the
same schema (`codex --output-schema`), so the failure is Claude-adapter-specific. Fix: the Claude
adapter down-converts the schema at its own boundary (strip the unsupported `$schema` meta-schema
declaration) while preserving every constraint. Codex/gemini/opencode/pi paths stay byte-identical.

## Research summary (source-verified on current main `9f9b20d`; issue filed at `ecd1258`)

**Reproduces on main.** `export_function_schema("EmitPhaseCloseout")` (baml_modular.py:153) returns a
dict whose top-level `$schema` is `https://json-schema.org/draft/2020-12/schema` (baml_modular.py:165).
`CLOSEOUT_SCHEMA = export_function_schema("EmitPhaseCloseout")` (models.py:389) is that dict.

**Who rejects it — proven empirically, not inferred.** Ran `claude 2.1.220` (issue: 2.1.215):
- With `$schema: draft/2020-12` → `Error: --json-schema is not a valid JSON Schema: no schema with key
  or ref "https://json-schema.org/draft/2020-12/schema"` (exact issue error; fails at parse time, no
  model turn).
- Same schema with `$schema` removed → CLI accepts it and returns valid structured output
  (`{"x":"hello"}`).

So the rejecter is the **Claude CLI's** schema validator (not our validator, not the API); the accepted
form is "no `$schema`" (Ajv falls back to its default draft-07 registry). The closeout schema body uses
only draft-07-compatible constructs (`type`, `enum`, `const`, `additionalProperties`, `required`,
`type: [x, "null"]` unions), so stripping the declaration is constraint-preserving.

**Where the schema reaches the Claude CLI.** `build_claude_command` (launcher.py:490) appends
`["--json-schema", json.dumps(closeout_schema, separators=(",", ":"), sort_keys=True)]` when
`closeout_schema is not None` (launcher.py:528-529). `closeout_schema` originates from
`_closeout_schema_for_request` (launcher.py:699) → `CLOSEOUT_SCHEMA`, only for actions
`{execute, repair, review}` (launcher.py:706). `plan`/`roadmap`/`maintain-skills` get `None`, so this
touches exactly the three closeout-emitting actions — **not `plan`** (the run's plan step succeeded,
consistent with the issue). `build_claude_command` is invoked from the claude branch of the launch
builder (launcher.py:1304, `closeout_schema=closeout_schema` at :1312).

**Why the codex path is unaffected.** The codex branch carries the schema on the spec for launch-time
materialization (`build_codex_command` emits an `--output-schema <placeholder>`; the real file is
written by `_materialize_codex_schema`, launcher.py:2637, and substituted at launch). It never runs
through Ajv and demonstrably accepts 2020-12 (issue workaround). The gemini/opencode/pi paths inject
the schema **as prompt text** via `inject_schema_description` (`_prompt_bundle_with_closeout_schema`,
launcher.py:713) — `$schema` there is descriptive prose, harmless.

**The canonical contract intentionally IS 2020-12 — so this is an adapter down-convert, not a "wrong
declaration."** Both producers declare 2020-12: `baml_modular.export_function_schema` (:165) and the
separate exported-artifact producer `schema_export.build_schema` (schema_export.py:205). The maintainers
intend 2020-12 union-type nullability — asserted by
`test_export_schema.py::test_nullable_field_uses_draft_2020_union_type` (:60, targets the
`schema_export` file artifact, NOT the claude command). The right fix therefore respects that intent and
localizes the down-convert to the one consumer that can't parse the dialect.

**Fix site choice — boundary, not source.** Strip at the `build_claude_command` chokepoint, **not** at
`CLOSEOUT_SCHEMA` construction. This keeps `CLOSEOUT_SCHEMA` byte-identical, so:
- `test_phase_loop_schema_flow.py::test_models_schema_is_baml_exported_schema` (:44) stays green;
- the `schema_sha256` gemini/opencode/pi see in prompts (schema_flow:64) is unperturbed;
- the codex materialized schema (schema_flow:55) is unperturbed;
- **any** schema handed to claude — including future `spec_delta`/`doc_delta` review closeouts — is
  sanitized regardless of its own `$schema`. This coverage is a design advantage of the chokepoint.

**Tests coupled to the current (unsanitized) claude arg — all must move together:**
1. `tests/test_phase_loop_native_flags.py::test_claude_command_uses_compact_inline_json_schema` (:44)
   asserts `json.loads(schema_text) == JSON_CLOSEOUT_SCHEMA` where
   `JSON_CLOSEOUT_SCHEMA = json.loads(json.dumps(CLOSEOUT_SCHEMA))` (:22) — i.e. WITH `$schema`. Breaks
   under the strip; must assert the sanitized body instead + `$schema` absent.
2. `tests/test_phase_loop_schema_flow.py::test_all_closeout_actions_receive_same_schema_across_five_harnesses`
   — only the **claude subTest** (:59) asserts `hash(claude --json-schema arg) == hash(generator)`;
   under the strip the claude constraint-body is identical but the meta-schema declaration diverges
   per-adapter. Codex (:55) and prompt-injected harnesses (:64) stay green. (Both files are marked
   `pytest.mark.dotfiles_integration` — schema_flow whole-module; native_flags: confirm at edit time.)
3. `tests/data/launchspec_golden/launchspec_golden.json` (:353-354) embeds the full claude
   `--json-schema` arg with 2020-12 inline. Regenerated deterministically via the sanctioned env flag
   (see Verification), not hand-edited.

## Relationship to ah#297 / ah#311 (asked by requester)
**Not the same root cause; one fix does not cover all three.** #297 and #311 are near-duplicates **of
each other**: a planner may emit `browser_automation` as a required capability
(`models.DISPATCH_CAPABILITIES` accepts the literal, planner validation treats it valid) but every
record in `DEFAULT_CAPABILITY_REGISTRY` reports `browser_automation=False`, so no executor can be
dispatched — a **capability-registry vs planner-validation** mismatch in
`models.py` / `capability_registry.py`. #291 is a **JSON-Schema meta-schema dialect** mismatch between
the generated closeout contract and the Claude CLI's Ajv validator, fixed in
`baml_modular.py` / `launcher.py`. Different file, different mechanism, different consumer. They share
only a loose theme ("a declared thing a downstream tool can't accept"). This #291 fix is independent;
#297/#311 should be planned/fixed together but separately from #291.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/launcher.py` (modify)
- **Add** module-level helper `_claude_cli_schema(schema: dict[str, Any]) -> dict[str, Any]` (place it
  just above `build_claude_command`, ~launcher.py:489). Return a shallow copy of `schema` with the
  top-level `$schema` key removed (`{k: v for k, v in schema.items() if k != "$schema"}`). Docstring:
  the Claude Code CLI's `--json-schema` validator (Ajv, default draft-07 meta-registry) rejects the
  canonical closeout contract's `$schema: draft-2020-12` ref at arg-parse time; strip the meta-schema
  declaration at the claude adapter boundary. The body uses only draft-07-compatible constructs, so the
  down-convert is constraint-preserving; codex/prompt-injected harnesses are untouched. Reason: fix the
  reported blocker while respecting maintainer intent that the canonical contract remains 2020-12.
  - Defensive note (implementer's call): the generator only sets `$schema` at top level, so a top-level
    pop suffices. If a recursive strip is preferred for future-proofing against nested meta-schema
    refs, keep it a pure helper and cover it in the unit test — but do NOT rewrite `$ref` constraint
    references (there are none to the meta-schema today).
- **Modify** `build_claude_command` (:490): at the `--json-schema` append (:528-529), wrap the schema:
  `command.extend(["--json-schema", json.dumps(_claude_cli_schema(closeout_schema), separators=(",", ":"), sort_keys=True)])`.
  Reason: this chokepoint carries every schema handed to the Claude CLI (execute/repair/review, and any
  future closeout variant), so sanitizing here fixes all claude closeout actions at once.

### `phase-loop-runtime/tests/test_phase_loop_native_flags.py` (modify)
- **Modify** `test_claude_command_uses_compact_inline_json_schema` (~:44): keep the compact-JSON /
  no-newline assertions; change the value assertion so `json.loads(schema_text)` equals the **sanitized**
  schema (`{k: v for k, v in JSON_CLOSEOUT_SCHEMA.items() if k != "$schema"}`), and add
  `self.assertNotIn("$schema", json.loads(schema_text))`. Reason: reflect the adapter down-convert while
  still proving the constraint body is fully preserved and compact.

### `phase-loop-runtime/tests/test_phase_loop_schema_flow.py` (modify)
- **Modify** only the claude subTest of
  `test_all_closeout_actions_receive_same_schema_across_five_harnesses` (:57-59): assert the claude
  `--json-schema` arg's **constraint body** matches the generator with the meta-schema declaration
  removed — e.g. compare `_schema_hash({k: v for k, v in export_function_schema("EmitPhaseCloseout").items() if k != "$schema"})`
  against `_schema_hash(json.loads(spec.command[spec.command.index("--json-schema") + 1]))`, and assert
  the parsed claude arg has no `$schema`. Leave the codex (:55) and gemini/opencode/pi (:64) subTests
  unchanged. Reason: encode the intended per-adapter divergence (identical constraints, adapter-local
  dialect) without weakening the cross-harness constraint-equivalence invariant.

### `phase-loop-runtime/tests/test_phase_loop_execute_claude_metaschema_291.py` (create — UNMARKED module)
Regression test. Placed in an **unmarked** module so CI (`pytest -m "not dotfiles_integration"`) runs it
— native_flags/schema_flow are marked and would be skipped in the default CI lane, so the bite must live
here. No dotfiles/skill-bundle dependency: call `build_claude_command` directly with a fixed selection.
- **Add** `test_claude_json_schema_arg_omits_unsupported_2020_12_metaschema`: build the claude command
  with `closeout_schema=CLOSEOUT_SCHEMA` (mirror native_flags' construction: `resolve_profile_for_executor`
  or a hand-built `ModelSelection`, `permission_mode="bypassPermissions"`), parse the `--json-schema`
  arg, and assert
  `json.loads(schema_text).get("$schema") != "https://json-schema.org/draft/2020-12/schema"`. Use the
  `!=`-to-the-unsupported-ref form (not pure absence) so the test bites on main today AND survives if a
  future fix down-converts to an explicitly-supported draft rather than stripping. Reason: guarantee no
  generated schema reaches the Claude CLI declaring the meta-schema the CLI provably rejects.
- **Add** `test_claude_json_schema_arg_preserves_constraint_body`: assert the parsed claude arg equals
  `CLOSEOUT_SCHEMA` minus its `$schema` key (every property/required/enum/const preserved) — proves the
  fix strips only the dialect declaration, not constraints.

### `phase-loop-runtime/tests/data/launchspec_golden/launchspec_golden.json` (regenerate)
- The claude branch's inline `--json-schema` value (:354) currently carries `$schema: draft/2020-12`.
  **Regenerate** (do not hand-edit) via the sanctioned flag so the golden matches the sanitized arg:
  `PYTHONPATH=src:tests PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1 python3 -m pytest tests/test_launchspec_golden.py`
  (per `tests/test_launchspec_golden.py:14-15,37-41`). Diff-review the result: the ONLY change must be
  the removal of the `"$schema":"https://json-schema.org/draft/2020-12/schema",` fragment inside the
  claude `--json-schema` string — no other executor/spec bytes move. Reason: keep the byte-stability
  golden honest about the adapter's emitted command.

## Out of scope / follow-up (state plainly; not required for closure)
- **Preflight adapter/schema-compat detection** (issue's second "Expected" bullet). The chokepoint strip
  makes the 2020-12 incompatibility **structurally impossible** on the claude path, so a preflight
  becomes defense-in-depth rather than the fix. Recommend a **separate follow-up issue**: a launch-time
  assertion (or a startup self-check) that any schema bound for a native-CLI `--json-schema`/`--output-schema`
  flag declares a dialect that adapter's validator accepts, failing loud with an actionable message.
  Not planned here to keep this blocker fix minimal and reviewable.
- **This is not an upstream/vendor-blocked fix.** We fully control the adapter boundary; no wait on the
  Claude CLI. If a future Claude CLI adds 2020-12 support, the strip is still safe (constraint body is
  dialect-neutral) and can be revisited then. No silent workaround: the down-convert is explicit,
  documented in code, and asserted by the regression test.

## Dependencies / order
1. `launcher.py` helper + `build_claude_command` edit (source of truth for the emitted arg).
2. `test_phase_loop_native_flags.py` + `test_phase_loop_schema_flow.py` edits (reflect new arg).
3. New regression module `test_phase_loop_execute_claude_metaschema_291.py`.
4. Regenerate `launchspec_golden.json` **last** (it snapshots the post-fix command).

To prove the regression bites: on current main (before the launcher edit) run only the new module — it
must FAIL (the arg carries `$schema: draft/2020-12`). Apply the launcher edit → it PASSES.

## Verification
From `phase-loop-runtime/`:
- Prove the bite (pre-fix): `PYTHONPATH=src:tests python3 -m pytest -q tests/test_phase_loop_execute_claude_metaschema_291.py` → **fails** before the launcher edit, **passes** after.
- Full default lane: `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"`
  (known pre-existing unrelated failure: `test_task_message_resolver::test_control_socket_...` reproduces on clean main — not caused by this change).
- Marked lane (native_flags/schema_flow live here): `PYTHONPATH=src:tests python3 -m pytest -q tests/test_phase_loop_native_flags.py tests/test_phase_loop_schema_flow.py` (requires a dotfiles-reachable env; if unavailable the marked module skips — run in an env where it does not).
- Golden regen + verify byte-stable: `PYTHONPATH=src:tests PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1 python3 -m pytest tests/test_launchspec_golden.py` then `PYTHONPATH=src:tests python3 -m pytest -q tests/test_launchspec_golden.py` (must pass without the regen flag); `git diff` shows only the `$schema` fragment removed from the claude arg.
- Model-id guard (unchanged surface, run for hygiene): `python3 phase-loop-runtime/scripts/check_model_id_sources.py`.
- Integration acceptance (already demonstrated during research; re-run after fix): build the claude
  command and feed its `--json-schema` arg to `claude -p --json-schema <arg> --model claude-haiku-4-5-20251001 "…"`
  — the 2020-12 reject must no longer occur and structured output returns.

## Acceptance criteria
- [ ] New regression test asserts the claude `--json-schema` arg does not declare
      `https://json-schema.org/draft/2020-12/schema`; it FAILS on pre-fix main and PASSES after the launcher edit.
- [ ] `build_claude_command` emits a `--json-schema` arg whose parsed body equals `CLOSEOUT_SCHEMA`
      minus only the `$schema` key (all constraints preserved; compact, no newlines).
- [ ] `CLOSEOUT_SCHEMA`, the codex `--output-schema` materialized schema, and the gemini/opencode/pi
      prompt `schema_sha256` are unchanged (schema_flow codex + prompt-injected subTests stay green).
- [ ] `tests/data/launchspec_golden/launchspec_golden.json` regenerated; the only byte change is the
      removed `$schema` fragment in the claude `--json-schema` string; the golden test passes without the regen flag.
- [ ] `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"` shows no new failures
      beyond the known pre-existing `test_task_message_resolver::test_control_socket_...`.
