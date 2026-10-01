# Detailed plan: model roster and job-slot tiers (plan 1 of 5, agent-harness#1171) — r2

## Task
This is plan 1 of agent-harness#1171. The motivation and the approved direction are stated in the issue and are not repeated here.

Plan 1 has two parts, and each part lands as its own PR:
- **Part A — job slots and the shipped roster.**
  - It adds the slots `frontier`/`standard`/`fast`.
  - It keeps the old tier names as read-only, deprecated aliases.
  - It adds one shipped model roster per vendor, and every executor-path pin derives from it.
  - The only shipped-default change is the approved one: Claude `heavy` moves from `claude-opus-5` to `claude-opus-5-5`.
- **Part B — user/repo overrides, resolved at call time.**
  - It adds the `models.toml` user and repo layers.
  - Each launch site resolves the roster when it runs, including native skill lanes, which go through a `phase-loop models resolve` CLI.
  - Each call site has its own falsifier.

Part B is how a "for now" choice such as gpt-6.1-sol reaches the codex executor, without changing any shipped default.

**Why r2 split the plan.** The r1 plan, reviewed in board round hb1, grew past the bounded-plan threshold once the call-site inventory was added. Parts A and B are disjoint in files and in risk.

**Vocabulary.** The code uses "slot". "Tier" survives only in the legacy aliases. `specs/phase-plans-v2.md` (around l.70) and the `MODEL_CLASSES` comment in `models.py` already avoid "tier", because it collides with the evidence-audit tiers.

## Maintainer decisions (recorded 2026-09-29, comment on agent-harness#1173)
- **The shipped openai frontier is `["gpt-6-astra"]`.**
  - gpt-6.1-sol is registered only (agent-harness#1172, merged), and reaches launches through a Part-B override.
  - The shipped default flips to `["gpt-6.1-sol","gpt-6-astra"]` only through a promotion. That promotion is the plan-3 record, including a codex-executor launch falsifier. It also needs the **golden gate** (see "Follow-on gates").
- **Anthropic.**
  - Fable 5.1 stays registered (`advisor_board/registries._MODEL_DEFS`) but is not in the roster.
  - `claude-opus-5` leaves the default roster.
  - There is no anthropic frontier fallback.
- **Plan 2 presets derive from the roster.** One `sl0_repairs` entry is accepted, and it is raised when plan 2 is planned.
- **Google and xAI: every value stays byte-identical until measured.**

## Research summary
**Pinned inputs.**
- origin/main `3c61b270` (v0.7.21), rechecked at `b6a482fa`, which includes agent-harness#1172 at `6686c952`.
- PANEL SL-1 is the local branch `claude/1078-panel-sl1`, observed at `0e7f9efb` (agent-harness#1078; amendment agent-harness#1169).
- No SHA of this plan's own output is pinned.

**What the pin surface is today.**
- `models.py`: `MODEL_TIERS` (l.44) and `MODEL_CLASSES` (l.32).
- `profiles.py`:
  - `DEFAULT_PROFILES` (l.58) and `EXECUTOR_MODEL_OVERRIDES` (l.76);
  - `_TIER_ADVISORY_EFFORT` (l.212) and `TIER_MODELS` (l.265);
  - `SUPERVISOR_TIER` (l.302), `ROLE_TIERS` (l.307), `tier_for_role` (l.321) and `resolve` (l.331);
  - `_CLASS_TIER_BRIDGE` (l.464) and `CLASS_MODEL_OVERRIDES` (l.480);
  - the `*_MODEL` constants (l.27-56, 165-239).
- `capability_registry.py:30-33` holds the `CLAUDE_*_MODEL` constants.

**Only two internal callers pass a legacy tier *name*:** `supervise_selection` (via `SUPERVISOR_TIER`) and `_class_model_from_tier` (via the bridge). Both go through `resolve`.

**No mapping is keyed by model id over the Claude constants.** A grep for `CLAUDE_(ULTRA|HEAVY)_MODEL` used as a dict key, index or comparison found none, so the ultra/heavy collapse cannot fold any table.

**`ClaudeTeamPolicy.default_model` is metadata only.** The comment at `capability_registry.py:161-167` says so. Nothing launches from it.

**The real launch sites.** These are the functions that turn an action into a model:
- `runner.run_loop`, around l.1382, l.1482 and l.2973-2992. The last of these calls `resolve_profile_for_executor`, `resolve_execution_policy`, `shipped_model_policy_rule` and `apply_model_class_escalation`.
- `runner.launch_delegated_child`, around l.5180.
- `runner.launch_harness_lane_work_unit`, around l.5960.
- `maintenance.py:173` (`resolve_profile`).
- `train_review_packet.py:680` (`supervise_selection`, advisory).
- The native claude execute-phase lanes. The skill's Step 3 (`phase-loop-skills/execute-phase/_overrides/claude/SKILL.md`, around l.291-311) maps a lane to a tier name, looks it up in a table baked into the skill, and passes the result to `Agent(model: …)`.

`cli.py` uses `DEFAULT_PROFILES` only for `--model-profile` choices, which are profile names and not models.

**The frozen coupling.** The frozen PANEL support `tests/panel_content_tdd_adapter.py::capture_golden` normalizes every seat of `CODE_REVIEW_BOARD`, `_STANDIN_CODE_REVIEW`, `DEFAULT_BOARD` and **every** `PRESETS` board. It does so through `model_pin`, which is a first-match walk over `profiles.TIER_MODELS`. The frozen `tests/data/panel_code_review_snapshot.golden.json` records 38 pins:

| pin | count |
|---|---|
| `claude/ultra` | 9 |
| `claude/regular` | 3 |
| `codex/heavy` | 11 |
| `gemini/regular` | 10 |
| `grok/heavy` | 5 |

Two frozen consumers in `tests/test_panel_lanes.py` read it: `::test_ec1_import_time_snapshots_equal_the_base_golden` and `::test_ec1_every_builtin_task_has_a_table_composing_todays_seats`. Both are skipped until PANEL lands.

**Measured 2026-09-29 at `b6a482fa`, by patching `profiles.TIER_MODELS` in memory before running the full capture:**

| view | result |
|---|---|
| the main view | capture == golden bytes |
| the r2 view (only `claude/heavy` moved to opus-5-5) | capture == golden bytes |
| codex/heavy set to gpt-6.1-sol | `ValueError: model 'gpt-6-astra' is not a registry pin` (brainstorm, doc-edit and legal-brainstorm keep astra) |

**The frozen sweep.** It covered 42 paths: `HARDEN_TEST_PATHS`, every `.phase-loop/evidence/*/content-tdd-receipt.json` `test_files`, and govlean `DEFAULT_FROZEN_SUPPORT_PATHS`. For each path it searched for the tier symbols, the override tables, the `*_MODEL` constants and the literal `gpt-6-astra`/`claude-opus-5`. It found assertions on `gpt-6-astra` in board presets only (HARDEN `test_advisor_board_presets.py`), and plan 1 leaves those unchanged. There are no warnings-as-errors settings in `pyproject.toml`, `tests/conftest.py` or the CI workflows.

**Skill-source sweep.** It looked for the token-bounded regex `claude-opus-5(?!-5)`, for `gpt-6-astra` and for tier words:
- `claude-opus-5` appears in the execute-phase and plan-phase claude pairs (`phase-loop-skills/*/_overrides/claude/SKILL.md` and `skills-src/claude/claude-*-phase/SKILL.md`) and in their `skills_bundle` outputs.
- `gpt-6-astra` appears in plan-phase (l.70) and in the advisor-board skills. The advisor-board mentions are board surfaces owned by plan 2 and are unchanged, because astra ships.
- Tier words appear only as advisor-board prose ("never on model tier"), which is unrelated.

## Design decisions (binding)
1. **Slots.**
   - `MODEL_SLOTS = ("frontier","standard","fast")`.
   - `ROLE_SLOTS`: roadmap, plan, review, advise, security and supervise map to frontier; execute and repair map to standard; worker and cheap map to fast.
   - `ROLE_EFFORT` is the cost dial. Review, advise and security get `max`; roadmap, plan and supervise get `xhigh`; execute and repair get `medium`; worker and cheap get `low`.
   - These equal today's `_TIER_ADVISORY_EFFORT` values for the mapped tiers. `SHIPPED_MODEL_POLICY` and `EXECUTOR_EFFORT_OVERRIDES` are unchanged.
2. **Two cells per slot: a taxonomy cell and a launch cell.** Each `(vendor, slot)` has:
   - a **taxonomy list**: the vendor-canonical id, index 0 live, the rest declared fallbacks;
   - an optional **launch override per harness**, for launch ids that differ from the taxonomy cell.
   
   Who reads which:
   - The legacy `TIER_MODELS` and `resolve()` read **only the taxonomy cell**, never a launch override.
   - The launch tables `EXECUTOR_MODEL_OVERRIDES`, `CLASS_MODEL_OVERRIDES` and `DEFAULT_PROFILES` read the launch override when one exists, and the taxonomy cell otherwise.
   
   This keeps `resolve("heavy","gemini")` = `gemini-3.1-pro-preview`, `resolve("lite","gemini")` = `gemini-3.5-flash-lite` and `resolve("regular"|"lite","grok")` = `grok-4.3`/`grok-build-0.1`, exactly as today.
3. **Legacy views are derived and byte-identical except for the approved move.**
   - `MODEL_TIERS`, `ROLE_TIERS`, `SUPERVISOR_TIER`, `TierResolution`, `tier_for_role`, `resolve` and `supervise_selection` keep their values, signatures and return shapes.
   - `LEGACY_TIER_SLOT` = {ultra→frontier, heavy→frontier, regular→standard, lite→fast}.
   - `TIER_MODELS` stays a **plain dict** (not `MappingProxyType`; see `patch.dict`/deepcopy/pickle/`json.dumps`). It keeps the same vendors, the same per-vendor key order and the same cells.
   - Read-only is enforced by a test: after every `phase_loop_runtime` module is imported, `TIER_MODELS` equals a fresh builder output.
   - The only cell that changes is `claude/heavy` (opus-5 → opus-5-5). `codex/heavy` stays `gpt-6-astra`, so every preset still pins (measured above).
4. **The before/after snapshot is a closed allow-list.** Part A first adds `tests/test_model_pin_snapshot.py` against **unmodified main**. It snapshots:
   - `TIER_MODELS`;
   - `EXECUTOR_MODEL_OVERRIDES`, `EXECUTOR_EFFORT_OVERRIDES` and `CLASS_MODEL_OVERRIDES`;
   - `DEFAULT_PROFILES`;
   - every public `*_MODEL` export of `profiles` and `capability_registry`;
   - `resolve(tier, vendor)` for all 13 `(vendor, tier)` cells, plus `resolve(role, vendor)` for every role;
   - the effective `(model, effort)` of `resolve_profile_for_executor(action, executor)` for every executor and action.
   
   The snapshot is committed with `ALLOWED_DELTAS`, which names only these:
   - `TIER_MODELS["claude"]["heavy"].model_id`
   - `EXECUTOR_MODEL_OVERRIDES["claude"]["roadmap"|"plan"]`
   - `CLASS_MODEL_OVERRIDES["claude"]["planner"]`
   - `CLAUDE_HEAVY_MODEL`
   - `resolve("heavy"|"roadmap"|"plan"|"supervise","claude").model_id`
   - `resolve_profile_for_executor(roadmap|plan, claude).model`
   - `ClaudeTeamPolicy.default_model` (metadata)
   
   The value of every allowed delta is `claude-opus-5-5`. Any other difference fails.
5. **Deprecation.**
   - `tier_for_role` and `resolve` emit `DeprecationWarning` (stacklevel=2) when given a legacy tier *name*. Role names do not warn, and data access does not warn.
   - Internal callers move to the slot API: `supervise_selection` calls `resolve_slot("supervise", …)` and re-labels the result `tier="heavy"`. The class bridge calls `resolve_slot`.
   - A test runs one `run_loop` dry-run dispatch per executor under `warnings.simplefilter("error", DeprecationWarning)`. It fails if a warning originates in `phase_loop_runtime`.
   - The aliases last at least until the release after the one that ships Part A. Plan 5 retires them.
6. **The shipped roster lives in Python, in one annotated place.**
   - `phase_loop_runtime/model_roster.py` holds `SHIPPED_ROSTER`. Every model-id line carries `# model-id-source: shipped roster`.
   - `SHIPPED_ROSTER` may not carry `expires`; a test enforces it, since expiry is config-only (Part B).
   - `model_roster.py` imports nothing from `phase_loop_runtime`, which rules out import cycles.
7. **The initial shipped roster.** Every cell is today's value, except the approved Claude move.

   | vendor | frontier (taxonomy) | standard | fast | launch overrides (harness: slot → id) | why each override differs |
   |---|---|---|---|---|---|
   | anthropic | `claude-opus-5-5` | `claude-sonnet-5` | `claude-haiku-4-5-20251001` | — | — |
   | openai | `gpt-6-astra` | `gpt-5.6-terra` | `gpt-5.6-luna` | opencode: `openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`, `openai/gpt-5.6-luna` | opencode needs the `openai/` provider prefix. Its frontier stays on 5.6-sol because opencode was measured rejecting `openai/gpt-6-astra` on 2026-09-04 (comment above `OPENCODE_OPENAI_HEAVY_MODEL`). |
   | google | `gemini-3.1-pro-preview` (volatile) | `gemini-3.8-flash` | `gemini-3.5-flash-lite` (aspirational) | gemini: `pro`, `gemini-3.8-flash`, `gemini-3.5-flash-high` | agy launches frontier through the `pro` routing alias. For fast, agy lists no flash-lite, so the live worker is `gemini-3.5-flash-high`, while the taxonomy cell keeps today's aspirational `gemini-3.5-flash-lite` (the comment at `GEMINI_WORKER_MODEL`, profiles.py around l.171-177). Both values are unchanged. |
   | xai | `grok-4.7` (volatile) | `grok-4.3` (volatile) | `grok-build-0.1` (volatile) | grok: `grok-4.7` for all three slots | grok's live class and executor routing is single-model by design (comment above the grok `TIER_MODELS` entry). |

   **Non-roster executors pass through unchanged.** `models.EXECUTORS` = codex, claude, gemini, grok, opencode, pi, command and manual. The builder emits keys only for the roster harnesses in `VENDOR_HARNESSES`, which are claude, codex, opencode, gemini and grok. The others are handled like this:
   - `pi` is the default lane executor (`capability_registry.DEFAULT_LANE_EXECUTOR`). It routes through its `auto` alias and is not a vendor.
     - Its rows live in a hand-listed `NON_ROSTER_EXECUTOR_MODELS = {"pi": {"actions": {every action: PI_AUTO_ROUTED_MODEL}, "classes": {every class: PI_AUTO_ROUTED_MODEL}}}` in `profiles.py`.
     - These rows are copied verbatim into `EXECUTOR_MODEL_OVERRIDES["pi"]` and `CLASS_MODEL_OVERRIDES["pi"]`, which is what `profiles.py` hand-lists today (around l.131-137 and l.506-511).
     - The builder raises if a roster harness and a non-roster executor share a key, so neither can overwrite the other.
     - No roster layer (shipped, user or repo) can set a pi row. `pi` is not a valid `harness` name in `models.toml`.
   - `command` and `manual` have no rows in either table today and still get none. Their resolution is unchanged.
   - Neither `DEFAULT_PROFILES` nor `TIER_MODELS` is keyed by executor, so neither is affected.
   - Without this rule, a missing `"pi"` key makes `resolve_profile_for_executor(executor="pi")` fall through to `DEFAULT_PROFILES` (gpt-6-astra) instead of `auto`. Round hb2 found that.
   
   `VENDOR_HARNESSES` = {anthropic: (claude,), openai: (codex, opencode), google: (gemini,), xai: (grok,)}. This is the single map between vendor names and harness names, which PANEL SL-1's `PANEL_VENDORS` also uses.
8. **The guard enforces that the roster is the only pin source.** A new check, `no_model_id_literals_in_launch_modules`, allows zero model-id literals (`MODEL_ID_REGEX`, with no marker escape) in:
   - `profiles.py` and `capability_registry.py`;
   - `runner.py`, `launcher.py`, `default_executor_resolver.py`, `maintenance.py`, `train_review_packet.py` and `cli.py`.
   
   The allowlisted `profiles.py` therefore cannot re-pin, and cannot keep a retired id such as `claude-opus-5`. The existing scan is otherwise unchanged.
9. **Skills reflect the shipped defaults in Part A.**
   - The tables are regenerated from `shipped_roster()`.
   - A non-frozen test asserts each skill table equals the shipped roster. It matches on token boundaries, because `claude-opus-5` is a prefix of `claude-opus-5-5`.
   - A doc note says skill tables show shipped defaults only until Part B, which makes native lanes resolve at call time.
10. **Part B: override layers.**
    - **Files.** `$XDG_CONFIG_HOME/agent-harness/models.toml` (then `$HOME/.config/...`, with `env` authoritative) and `<repo>/.agent-harness/models.toml`. This is a sibling of `advisor-boards.toml`, so it does not collide with SL-1's `config.py`.
    - **Path helper.** `model_roster` has its own `_user_config_dir(env)`, plus a parity test against `advisor_board.config._user_config_path`. It does not import that private helper.
    - **Grammar.** `[models.<vendor>]` holds `<slot> = [entry, …]`. `[models.<vendor>.harness.<harness>]` holds `<slot> = [entry, …]`. An entry is a string, or an inline table `{model, since, review_by, expires, note}`.
    - **Precedence.** shipped < user < repo, per list, and a layer replaces a whole list. Launch overrides are overridable per layer with the same list-replace semantics.
    - **Shadowing is a hard error.**
      - If a layer changes a `(vendor, slot)` taxonomy list while a *lower* layer's launch override for one of that vendor's harnesses still stands, and the same layer does not also set that override, that is a hard `RosterConfigError`.
      - The error names the key to set. Example: a repo `openai.frontier = ["gpt-6.1-sol"]` without `[models.openai.harness.opencode] frontier` fails.
      - This way an override never silently misses a harness.
    - **Validation.** These are hard errors:
      - an unknown key, vendor, slot or harness;
      - an empty or duplicate list;
      - an id that fails the vendor-membership check. That check uses the vendor families of `MODEL_ID_REGEX`, and launch overrides also accept the declared routing aliases and provider prefixes.
    - **Repo-layer `review_by`.** Requiring `review_by` on repo-layer entries is deferred to plan 3 (promotion records). Until then, a repo-layer entry without dates prints a warning in `phase-loop models resolve` and in status output.
    - **Expiry.** It is checked only when `load_roster(…, today=)` is called, with an injectable clock, and never at import. An expired entry is a `RosterConfigError`, raised at run start (see resolve-once) and surfaced by `phase-loop models resolve --check`.
11. **Part B: resolve once per run, from committed config.**
    - **Where the roster is read.** At run start, `run_loop` resolves the roster once. The repo layer is read from the **committed blob at the run's base HEAD** (`git show HEAD:.agent-harness/models.toml`), not the working tree, so a phase's own diff cannot change the models that plan or review it. The user layer is read from `env`.
    - **How it is passed down.** The resolved `Roster` and its `roster_digest` are passed down to `launch_delegated_child` and `launch_harness_lane_work_unit`. A child in a worktree never re-reads config.
    - **What is recorded.** Every dispatch decision records `model`, `model_source_layer` (shipped, user or repo) and `roster_digest`. Labels and provenance come from that same resolution.
    - **Signatures.** `resolve_profile_for_executor`, `resolve_execution_policy`, `resolve_model_class`, `apply_model_class_escalation`, `resolve_profile`, `resolve_slot` and `supervise_selection` gain a keyword-only `roster: Roster | None = None`. `None` means the shipped snapshot. Legacy positional signatures are unchanged.
    - **One builder.** A single pure builder, `build_launch_tables(roster)`, produces both the import-time snapshot (`build_launch_tables(shipped_roster())`) and call-time tables. A test asserts the builder's output with no override equals the snapshot.
12. **Part B: native lanes resolve through the CLI.**
    - `phase-loop models resolve --slot <slot> --vendor <vendor> [--harness <h>] [--repo DIR] --json` prints `{model, slot, source_layer, roster_digest, declared_fallbacks}`.
    - execute-phase Step 3 maps a lane to a slot. `strong` is accepted as an alias of `standard` for existing `Execution hint:` lines. The skill then calls this CLI and passes the returned `model` to `Agent(model: …)`.
    - If the CLI is unavailable, the skill uses its shipped table and must log `roster unavailable: shipped default <id>` in the lane brief. The fallback is never silent.
13. **Out of scope.**
    - Board seat surfaces: `panel_invoker.DEFAULT_LEG_MODELS`, `DEFAULT_REVIEW_SEAT_ALIASES`, presets, composition and registries. These belong to plan 2.
    - Seat names. Plan 2.
    - PANEL's `vendors` field. PANEL owns it.
    - The fallback walk. Plan 4.

## Changes — Part A (job slots and shipped roster)

### `phase-loop-runtime/tests/test_model_pin_snapshot.py` (create, FIRST, against unmodified main)
- The decision-4 snapshot and `ALLOWED_DELTAS`. It is committed green on main before any source edit.

### `phase-loop-runtime/src/phase_loop_runtime/model_roster.py` (create)
- `MODEL_SLOTS`, `VENDORS`, `VENDOR_HARNESSES` — add — the vocabulary (decisions 1 and 7).
- `RosterEntry`, `Roster` (taxonomy lists plus per-harness launch overrides), `SHIPPED_ROSTER`, `shipped_roster()` — add — the table in decision 7, annotated per decision 6.
- `build_launch_tables(roster, *, passthrough)` — add — the pure builder for `TIER_MODELS` (taxonomy cells only), `EXECUTOR_MODEL_OVERRIDES`, `CLASS_MODEL_OVERRIDES` and `DEFAULT_PROFILES` (launch cells). It emits roster-harness keys only, then merges `passthrough` (the decision-7 non-roster rows). It raises on a key collision and never lets roster data overwrite a passthrough row.

### `phase-loop-runtime/src/phase_loop_runtime/models.py` (modify)
- `MODEL_SLOTS` — add — re-exported.
- The `MODEL_TIERS` comment — modify — mark it deprecated and point to `LEGACY_TIER_SLOT`. The value is unchanged.

### `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py` (modify)
- `CLAUDE_ULTRA/HEAVY/REGULAR/LITE_MODEL` — modify — derive them from `shipped_roster()`, where ultra and heavy both mean frontier. Their literals are removed.
- The comment around l.161-167 — modify — `default_model` stays metadata only, and now names opus-5-5.

### `phase-loop-runtime/src/phase_loop_runtime/profiles.py` (modify)
- `ROLE_SLOTS`, `ROLE_EFFORT`, `LEGACY_TIER_SLOT`, `slot_for_role`, `SlotResolution`, `resolve_slot` — add.
- Every `*_MODEL` constant (`OPENAI_*`, `OPENCODE_OPENAI_*`, `GEMINI_*`, `GROK_*`, `CODEX_*`, `CLAUDE_IMPLEMENTER_MODEL`, `PI_AUTO_ROUTED_MODEL` stays) — modify — derive each from the roster's taxonomy or launch cell, keeping every name and value. All model-id literals are removed (decision 8).
- `NON_ROSTER_EXECUTOR_MODELS` — add — the hand-listed pi rows (decision 7), built from `PI_AUTO_ROUTED_MODEL`.
- `TIER_MODELS`, `EXECUTOR_MODEL_OVERRIDES`, `CLASS_MODEL_OVERRIDES`, `DEFAULT_PROFILES` — modify — `= build_launch_tables(shipped_roster(), passthrough=NON_ROSTER_EXECUTOR_MODELS)`. The call-time builds in Part B pass the same `passthrough`.
- `tier_for_role`, `resolve` — modify — delegate to the slot API. `resolve` reads the taxonomy cell only. Add the deprecation warning (decision 5).
- `supervise_selection` and `_CLASS_TIER_BRIDGE` → `_CLASS_SLOT_BRIDGE` — modify — move them to the slot API. There are no internal legacy-name calls.

### `phase-loop-runtime/scripts/check_model_id_sources.py` (modify)
- `no_model_id_literals_in_launch_modules` — add — the decision-8 check.

### Tests (create or modify; none frozen)
- `tests/test_model_roster.py` — create — covers:
  - roster shape;
  - the vendor-membership check on the shipped roster;
  - `SHIPPED_ROSTER` having no `expires`;
  - the `TIER_MODELS` builder equality after importing every module;
  - the full `capture_golden()` byte-equality with the frozen golden;
  - the dry-run dispatch with no deprecation warnings (decision 5);
  - **the pi passthrough falsifier.** After the build, `resolve_profile_for_executor(action=a, executor="pi").model == "auto"` for every action, and `resolve_model_class("pi", c) == "auto"` for every class. The same holds under a Part-B repo `models.toml` that overrides every vendor slot.
    - `command` and `manual` have the same (absent) rows as on main.
    - The executor-key set of both tables equals main's exactly.
    - **Named mutation:** calling the builder with `passthrough={}` must fail this test, with pi resolving to `gpt-6-astra`.
    - A second mutation, a roster harness key named `pi`, must raise the collision error;
  - `pytest.warns(DeprecationWarning)` for `resolve("ultra","claude")` and `tier_for_role("heavy")`.
- `tests/test_model_tier_taxonomy.py`, `tests/test_model_class_policy.py` — modify — update expected values only for the `ALLOWED_DELTAS` cells. `test_grokexec.py` needs no change, because grok is untouched.
- `tests/test_skill_model_tables.py` — create — decision 9. It uses token-bounded matching across every skill source and bundle output.

### Skills (modify; byte-parallel pairs enforced by `test_skills_canon_parity`)
- `phase-loop-skills/execute-phase/_overrides/claude/SKILL.md` and `skills-src/claude/claude-execute-phase/SKILL.md`:
  - the "Model tiers" table (around l.118-132) becomes frontier `claude-opus-5-5`, standard `claude-sonnet-5` and fast haiku;
  - `strong` is renamed `standard`, with `strong` still accepted in `Execution hint:`;
  - the ladder becomes `fast → standard → frontier`;
  - the planner/reviewer prose now says both route to frontier and that effort is the dial;
  - add the doc note from decision 9.
- `phase-loop-skills/plan-phase/_overrides/claude/SKILL.md` and `skills-src/claude/claude-plan-phase/SKILL.md` (around l.70-71): `claude` → `claude-opus-5-5`. The codex entry stays `gpt-6-astra`.
- Regenerate `phase_loop_runtime/skills_bundle/`. `build_bundle.PRESERVE_LITERALS` drops `"claude-opus-5"` once the token-bounded sweep finds no skill source that names it. The install-output presence gate requires this, and a substring gate would never notice, because the id is a prefix of `claude-opus-5-5`.

## Changes — Part B (overrides, resolved at call time)

### `phase-loop-runtime/src/phase_loop_runtime/model_roster.py` (modify)
- `RosterConfigError`, `load_roster(repo_dir, *, env, today, base_ref="HEAD")`, `roster_digest(roster)` and `_user_config_dir(env)` — add — the decision-10 grammar, validation, shadowing error and expiry, plus the decision-11 committed-blob read.

### `phase-loop-runtime/src/phase_loop_runtime/profiles.py` (modify)
- Add a keyword-only `roster=` to `resolve_profile`, `resolve_profile_for_executor`, `resolve_execution_policy`, `resolve_model_class`, `apply_model_class_escalation`, `resolve_slot` and `supervise_selection`. When a roster is given, it builds via `build_launch_tables(roster)`.

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify)
- `run_loop` — resolve the roster once at start (decision 11), then pass `roster=` at the resolution calls around l.1382, 1482 and 2973-2992. Record `model_source_layer` and `roster_digest` in the dispatch decision.
- `launch_delegated_child` (around l.5180) and `launch_harness_lane_work_unit` (around l.5960) — accept and forward `roster=`, with no re-read.

### `phase-loop-runtime/src/phase_loop_runtime/maintenance.py` (modify)
- l.173 `resolve_profile` — pass the loaded roster.

### `phase-loop-runtime/src/phase_loop_runtime/train_review_packet.py` (modify)
- l.680 `supervise_selection("claude")` — pass the loaded roster. The packet's `tier` label stays `"heavy"`.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `models resolve` subcommand — add — decision 12, with `--check` for preflight and expiry.

### Skills (modify, byte-parallel)
- execute-phase claude pair, Step 3 (around l.291-311) and the lane-model table (around l.691-696) — resolve through `phase-loop models resolve` (decision 12). Regenerate the bundle.

### `phase-loop-runtime/tests/test_model_roster_overrides.py` (create)
Each falsifier asserts on the **launch argv or dispatch decision** of the real function, never on a resolver helper alone, and each one names its site:
- `run_loop` main dispatch (l.2973): a repo `models.toml` with `openai.frontier=["gpt-6.1-sol"]` plus the opencode override makes the codex `plan` dispatch decision carry `gpt-6.1-sol`, `source_layer=repo` and the digest.
- `run_loop` l.1382 and l.1482 profile paths.
- `launch_delegated_child`: the child argv carries the override without the child reading any config (the test sets the child's HOME/XDG to an empty dir).
- `launch_harness_lane_work_unit`: the harness-lane argv.
- `maintenance` l.173.
- `train_review_packet` `coordinator_supervise.model_id` under an anthropic frontier override.
- **Each launch harness:**
  - opencode: the shadowing error without the harness key, and success with it;
  - gemini: `[models.google.harness.gemini]` fast override → worker argv;
  - grok: the harness override → `-m` argv.
- **Working-tree trust:** an uncommitted repo `models.toml` edit does not change the dispatch. The committed one does.
- **Expiry:** an injected `today` past `expires` gives `RosterConfigError` at run start, and `models resolve --check` exits non-zero.
- **Validation:** a cross-vendor id (`claude-sonnet-5` under `[models.openai]`) is a hard error.
- **CLI:** `phase-loop models resolve --slot standard --vendor anthropic --repo <tmp>` returns the override.

## Documentation impact
- `CHANGELOG.md` — add:
  - Part A: job slots, the shipped roster, the deprecated tier aliases and their window, the one default move (Claude planning opus-5 → opus-5-5), and the guard check.
  - Part B: `models.toml`, the `models resolve` CLI, and committed-config resolution.
- `README.md` (tier line, around l.164) — modify — describe slots and the roster, and point to the doc below.
- `docs/phase-loop/model-roster.md` — add — the grammar, precedence, launch overrides and shadowing error, resolve-once from committed config, expiry, the slot/legacy table, the deprecation window, and the note that skills show shipped defaults (Part A) and resolve at call time (Part B).
- `plans/design-model-tier-taxonomy.md` — modify — a header note: superseded by job slots (agent-harness#1171).
- The `advisor-boards.toml` header and `advisor_board/CONTRACTS.md` — no change (board surfaces belong to plan 2, and `CLAUDE_IMPLEMENTER_MODEL` is unchanged).

## Dependencies & order
1. **Part A.** The order is: the snapshot test on unmodified main, then `model_roster.py`, then `capability_registry.py`, then `profiles.py`, then the guard, then the tests, then skills and bundle, then docs. There is no dependency on PANEL SL-1, because no SL-1 file is edited. agent-harness#1172 has already merged.
2. **Part B** depends on Part A landing. It edits `runner.py` and `cli.py`, which SL-1 also changes. Whichever lands second rebases, and there is no shared symbol.
3. **Follow-on plans:** plan 2 needs Part A and SL-1. Plan 4 needs Part B **and plan 2** (board seats only derive from the roster once plan 2 lands). Plan 3 needs Part B.

## Verification
From `phase-loop-runtime/`:
```bash
# Part A
PYTHONPATH=src python3 -m pytest -q tests/test_model_pin_snapshot.py tests/test_model_roster.py tests/test_skill_model_tables.py tests/test_model_tier_taxonomy.py tests/test_model_class_policy.py tests/test_grokexec.py tests/test_routing_invariants.py tests/test_governed_premerge.py tests/test_route_log.py tests/test_phase_loop_runner.py tests/test_skills_canon_parity.py
PYTHONPATH=src python3 scripts/check_model_id_sources.py
# mutation: a retired id planted in an allowlisted file must fail the new check
sed -i '0,/^SUPERVISOR_TIER/s//_PROBE = "claude-opus-5"\nSUPERVISOR_TIER/' src/phase_loop_runtime/profiles.py && ! PYTHONPATH=src python3 scripts/check_model_id_sources.py; git checkout -- src/phase_loop_runtime/profiles.py
# COMPLETE frozen golden capture, byte-equal (every board and preset, codex seats included):
PYTHONPATH=src:tests python3 -c "
from pathlib import Path; import panel_content_tdd_adapter as ad
assert ad.golden_bytes() == (Path('..')/ad.GOLDEN_PATH).read_bytes(); print('golden OK')"
# every frozen file is byte-identical to origin/main (all three sets):
python3 - <<'EOF'
import glob, json, re, subprocess, sys
sys.path.insert(0, 'tests')
from harden_tdd_guard import HARDEN_TEST_PATHS
from govlean_freeze_receipt import DEFAULT_FROZEN_SUPPORT_PATHS
paths = set(HARDEN_TEST_PATHS) | set(DEFAULT_FROZEN_SUPPORT_PATHS)
for f in glob.glob('../.phase-loop/evidence/*/content-tdd-receipt.json'):
    paths |= {t['path'] if isinstance(t, dict) else t for t in json.load(open(f)).get('test_files', [])}
out = subprocess.run(['git', '-C', '..', 'diff', '--name-only', 'origin/main', '--', *sorted(paths)], capture_output=True, text=True).stdout
assert not out.strip(), out; print(len(paths), 'frozen paths unchanged')
EOF
# frozen nodes pass:
PYTHONPATH=src python3 -m pytest -q $(python3 -c "import sys;sys.path.insert(0,'tests');from harden_tdd_guard import HARDEN_TEST_PATHS as P;print(' '.join(p.replace('phase-loop-runtime/','') for p in P))") tests/test_govlean_panel_policy.py tests/test_panel_lanes.py tests/test_president_wiring.py
# Part B
PYTHONPATH=src python3 -m pytest -q tests/test_model_roster_overrides.py
PYTHONPATH=src python3 -m phase_loop_runtime.cli models resolve --slot frontier --vendor openai --json
```

**Operational evidence (Part B), which cannot be fully machine-checked.** A native execute-phase lane is launched by the orchestrating agent following the skill. The evidence is a single-lane execute-phase run in a scratch repo that commits `.agent-harness/models.toml` with an anthropic `standard` override. The lane brief must show the `models resolve` JSON, and the `Agent(model:)` value must equal it. The transcript is attached to the Part-B PR as `native-lane-override-evidence.md`. If it is missing, Part B is not done.

**Measured at r2 (2026-09-29, `b6a482fa`).** Patching `TIER_MODELS` in memory to the r2 view (only `claude/heavy` → opus-5-5) and running the full capture gives `golden_bytes()` equal to the frozen golden. The counterfactual `codex/heavy` = gpt-6.1-sol raises `ValueError` for `gpt-6-astra`.

## Acceptance criteria
- [ ] Part A: `tests/test_model_pin_snapshot.py`, committed green on unmodified main, passes after the change with differences confined to `ALLOWED_DELTAS`, all equal to `claude-opus-5-5`. The pi passthrough falsifier in `tests/test_model_roster.py` passes (pi → `auto` for every action and class, and the executor-key sets equal main's), and it fails under the named `passthrough={}` mutation.
- [ ] Part A: the full `capture_golden()` output is byte-equal to the frozen golden, every frozen path across the three sets is unchanged against origin/main, and the frozen nodes pass.
- [ ] Part A: `scripts/check_model_id_sources.py` exits 0, and it exits non-zero when the retired-id mutation (`"claude-opus-5"` planted in `profiles.py`) is applied.
- [ ] Part A: a `run_loop` dry-run dispatch per executor raises no `DeprecationWarning` from `phase_loop_runtime`, while `resolve("ultra","claude")` and `tier_for_role("heavy")` do warn.
- [ ] Part B: every site falsifier in `tests/test_model_roster_overrides.py` passes, asserting on real argv or dispatch decisions, and `native-lane-override-evidence.md` shows `Agent(model:)` equal to the `models resolve` output.

## Execution Policy
- execute: effort=high, reason=cross-seam derivation under a frozen-golden invariant (Part A); call-site threading and trust boundary (Part B).

## Follow-on gates and decisions
- **Golden gate for any shipped `codex/heavy` flip.** Plan 3 promotion is how gpt-6.1-sol reaches the shipped default. The frozen PANEL golden stays valid only if **every captured board and preset seats that one openai id**, including brainstorm, doc-edit and legal-brainstorm. Otherwise a PANEL `sl0_repairs` entry is needed. Plan 2's preset derivation (one accepted `sl0_repairs`) is the natural place to satisfy this. The flip must not land before plan 2.
- **Plan 4 open question (from hb1).** What happens when a vendor's candidate list is exhausted? The proposed answer, pending plan 4: exhaust the model candidates, then hand to PANEL's next vendor for board lanes; executor seams fail closed with a recorded `model_candidates_exhausted`. Also from hb1:
  - account-scoped failures (auth, usage_limit, billing/402) go straight to PANEL's vendor fallback, not the model walk, because another model on the same account fails the same way;
  - the model walk covers only model-scoped failures (model_not_found, per-model capacity);
  - exactly one fallback record per failure.

## Follow-on plans (each a bounded plan under agent-harness#1171)
- **Plan 2: vendor seat names, and board pins that derive from the roster.** Depends on Part A and PANEL SL-1.
  - Add `VENDOR_SEAT_ALIASES = {anthropic: fable, openai: sol, google: gemini, xai: grok}`. They are accepted wherever a seat or rung name is accepted: `validate_president_ladder`, `_validate_review_board_policy` and `president_adapter.seat_for_rung`. `load_president_ladder` still returns its input verbatim.
  - Canonical outputs keep the old names during the window.
  - Normalize before `ladder.index()` at both `president_operation.py` sites.
  - `DEFAULT_LEG_MODELS` and **presets derive from the roster**. The maintainer accepted one `sl0_repairs` for the HARDEN `test_advisor_board_presets.py` nodes, and it satisfies the golden gate above.
  - Alias-first keeps these frozen nodes unedited:
    - `test_govlean_panel_policy.py::test_president_ladder_is_the_ec_presroute_3_seat_alias_order` and `::test_review_policy_uses_full_board_and_president_only_for_plan_or_production_code`
    - `test_advisor_board_config.py::test_gpt_6_sol_cannot_fill_a_governed_grok_seat`
    - `test_panel_lanes.py::test_ec1_existing_loaders_tolerate_a_sibling_panel_table`, `::test_ec5_labels_carry_the_explicit_profile_and_its_provenance` and `::test_ec3e_target_head_profile_panel_list_change_after_the_gate_forces_a_regate`
    - `test_president_wiring.py::test_brief_binding_rejects_changed_brief_at_resume_and_accepts_control`
  - Persisted records keep the old names, and readers accept both.
- **Plan 3: promotion records and the fixed eval.** Depends on Part B.
  - **Records** are `.agent-harness/model-promotions/<vendor>-<slot>-<model>-<date>.json` (`model_promotion.v1`) with these fields:
    - `vendor`, `slot`, `model`, `promoted_on`;
    - `review_by` (≤ 90 days) and optional `expires`;
    - `launch_falsifiers[]`, one per consumer site and harness;
    - `eval` and `approved_by`.
  - A shipped index-0 entry must reference a record, and the plan-1 entries get grandfathered records dated 2026-09-29. **A grandfathered record cannot promote a model that was not already shipped.** gpt-6.1-sol needs a real record.
  - Repo-layer entries need `review_by`.
  - **Eval corpus:** 12 frozen past board rounds (8 with a finding confirmed by a landed fix, 4 clean). Each has its exact bundle plus `expected.json` anchors (file plus symbol or quoted line) and a sha256 manifest.
  - **Scoring** is deterministic:
    - recall is the share of known findings matched, where a match means an anchor file plus an anchor token;
    - a fabrication is a cited file, line or quote absent from the bundle;
    - a false blocker is a blocking finding on a clean round.
  - **Pass bar:** recall ≥ max(0.6, incumbent − 1), fabrication = 0, and false blockers ≤ 1. The candidate runs at the slot's effort twice and scores the minimum.
- **Plan 4: ordered fallback execution.** Depends on Part B and plan 2. It follows the model-scoped and account-scoped split above, and the within-vendor walk only.
  - Vendor ordering stays with PANEL (agent-harness#1078/#1169).
  - A `model_fallback` route-log event carries `from`, `to`, `reason` and `slot`.
  - The shared failure classifier is extracted from `panel_invoker._leg_failure_kind`, and adds `billing`/402.
- **Plan 5: alias retirement.** Earliest the release after Part A, and a maintainer decision. It needs `sl0_repairs` for every plan-2 node and for the PANEL golden if `TIER_MODELS` keys go. The alternative is to keep the frozen-facing views permanently.
