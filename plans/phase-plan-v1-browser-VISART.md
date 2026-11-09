---
phase_loop_plan_version: 1
phase: VISART
roadmap: specs/phase-plans-browser-v1.md
roadmap_sha256: 6e3444c54ef27a380048f8033a82f183dddafbff150dc664307a0e5db43c6383
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_browser_observation_contract.py", "phase-loop-runtime/tests/test_seat_visual_staging.py", "phase-loop-runtime/tests/test_seat_uid_visual_handoff.py", "phase-loop-runtime/tests/test_seat_visual_rehash_in_h.py", "phase-loop-runtime/tests/test_seat_visual_profile_neutrality.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_sandbox_permissions.py", "phase-loop-runtime/tests/test_board_visual_delivery.py", "phase-loop-runtime/tests/test_cli_observation.py", "phase-loop-runtime/tests/test_native_fill_visual.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_advisor_board_golden.py", "phase-loop-runtime/tests/test_broker_staged_tree_delivery.py", "phase-loop-runtime/tests/test_review_stage_binding.py", "phase-loop-runtime/tests/test_sandbox_egress.py", "phase-loop-runtime/tests/test_panel_native_fill_183.py", "phase-loop-runtime/tests/test_native_fill_refusal_cause.py", "phase-loop-runtime/tests/test_execute_skill_visual_capture.py", "phase-loop-runtime/tests/test_skills_bundle_drift.py", "phase-loop-runtime/tests/test_launchspec_golden.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# VISART: Observation artifacts and seat staging

## Context

Roadmap phase VISART (`specs/phase-plans-browser-v1.md`). The goals are EC-VISART-1 to
EC-VISART-7. Every rule a lane implements is in the frozen contract
`plans/artifacts/browser-v1-contract.md` (§1–§7, and §8.1) and the schema
`plans/artifacts/browser-v1-observation.schema.json`, both pinned in the roadmap's
External Inputs. This plan does not restate them. No browser runs anywhere in this phase,
and no jail changes.

The owner rulings OR-6 (operator-selected target mode) and OR-7 (observe plus frozen
replay in v1) reach VISART only through the schema. Every observation carries
`target.mode`, `target.bundle_sha256` and `target.policy_sha256`. They are null for
executor observations, which are all that VISART accepts, so the later broker phases need
no schema bump.

What exists today, and what each lane builds on:

- **Executor evidence.** Closeouts carry `visual_evidence_path`, which
  `models.resolve_visual_evidence_artifact` already checks for containment, regular file
  and image magic number. That resolver also accepts GIF and BMP, which the importer
  refuses. `visual_avatar_evidence_validator` feeds a warn-by-default gate. The capture
  guidance lives in two places: the `visual_evidence_path` paragraph of
  `skills-src/codex/codex-execute-phase/SKILL.md`, and the "Browser verification" section
  of `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`. Neither names
  T3 preview.
- **Jailed seats.** `seat_jail.build_seat_jail` creates `seat-home/` fresh, 0700, for each
  launch and binds it at `/seat/home`. The launch argv in `panel_invoker` runs
  `seat_uid handoff <review_dir> <tree> <n> [--gemini] --` as H-root before the owner.
  The handoff proves the tree is private inodes, then chowns the tree, home and out to the
  seat. With `--gemini`, it re-owns the agy config to H-root:seat with directories 0550
  and files 0440 (`_handoff_gemini_tree_at`). Contract §4.3 reuses that shape under the
  seat home, so `seat_jail.py`, the owner argv, `expected_mount_points` and
  `jail_profile_digest` stay untouched.
- **Jailed post-run reads.** After the handoff, `seat-home` is seat-owned and 0700, so
  the parent cannot traverse it. Every existing post-run read of seat-owned objects runs
  in H through the holder pid:
  - `seat_uid.read_in_h` and `scan_in_h`, over `in_h_argv(holder_pid, …)`;
  - the J10 reader `seat_jail.read_regular_file_at`, which opens components
    `O_DIRECTORY|O_NOFOLLOW` and leaves `O_NOFOLLOW|O_NONBLOCK`, then checks with `fstat`.
  These reads run after quiescence and before `teardown_in_h`, against
  `_JailedSeat.seat_dir`. That is the leg's own directory, distinct from the board's
  `review_dir`. The visual rehash follows the same pattern (contract §4.3).
- **Other launch paths** (contract §4.2):
  - Non-brokered sandbox-profile seats (codex, gemini, grok) run with cwd equal to
    `review_dir`. `_seat_view_layers` covers that cwd with a tmpfs, and
    `_seat_command_profile` binds back only `review-bundle.md`, `review-instructions.md`
    and `reviewed-tree`. So `<review_dir>/visual` is outside their view, and they are
    `visual_delivered: false`.
  - A direct Claude seat runs from `out_dir` with `--add-dir review_dir`
    (`_claude_direct_add_dirs`), so it is true.
  - Brokered codex has no grant (sealed argv from `out_dir`). Brokered Claude has no grant
    (`--tools ""`, no add-dirs). Brokered grok runs from `out_dir` with only
    `--cwd <clone>` bound. Brokered agy gets only `--add-dir <clone>`
    (`_require_staged_tree`, `_render_broker_inline_prompt`,
    `test_broker_staged_tree_delivery.py`). Every brokered row is false.
  - v1 makes no grant relaxation (coordinator ruling), so these masked seats do not get
    the stage.
  - A brokered seat without a staged tree gets only the sealed prompt
    (`_BROKER_SEALED_PROMPT_MAX_BYTES`, 512 KiB).
  - Native fill writes `native-fill/<request_id>/` from `cli._advisor_board_command`,
    which also builds the `--json` payload, including `legs`.
- **Notices.** `OD10_CLASSES` folds in only `ordinary` `seat_route_contract.CODES` rows;
  security codes are listed by hand in `_SECURITY_CODES`. A `security` leg code therefore
  needs all three of:
  - a `CODES` row;
  - an explicit `_SECURITY_CODES` entry;
  - membership in `panel_invoker._HARNESS_DETAIL_CODES`.
  `test_seat_route_contract.py::test_every_current_mode_line_code_has_an_explicit_class`
  and `test_seat_notices.py` enforce them.
- **Package data.** `schemas/*.json` already ships as package data, and `jsonschema` is a
  runtime dependency.

agent-harness#1916 has merged, so EXT-SEATSCODEX is satisfied. It changed
`panel_invoker.py`, `seat_jail.py`, CONTRACTS.md, the launch-reference inventory and
several tests these lanes run. Every lane branches from a main that includes it.

## Interface Freeze Gates

- [ ] IF-0-VISART-1 — `phase_loop_runtime.browser_observation` exports:
  - `SCHEMA_ID = "browser_observation.v1"`, `REFUSAL_CODES` (the nine `observation_*`
    codes of contract §7, a frozen tuple) and `ObservationRefused(code, detail)`;
  - frozen dataclasses `ObservationFile(path, sha256, bytes, media_type)` and
    `ObservationRecord(root, manifest, manifest_sha256, files)`;
  - `load_observation(path) -> ObservationRecord` (raises on the first defect; the URL
    scheme check precedes schema validation per §2.3);
  - `validate_observation(path) -> tuple[Finding, ...]` (every defect, as
    `Finding(code, path, detail)`; both producer kinds);
  - `require_executor(record) -> None` (raises `observation_profile_forbidden` for a
    broker producer);
  - `render_index_html(manifest) -> bytes` (renders the manifest without its `index`
    member);
  - `import_visual_evidence(images, *, out_dir, repo_root, tool, profile=None, url=None,
    viewport=None, color_scheme=None, source_commit=None, host=None, now=None) ->
    ObservationRecord`.
  The package schema `schemas/browser_observation.v1.schema.json` is byte-identical to the
  pinned artifact. Contract §2, §3, §7.
- [ ] IF-0-VISART-2 — `phase_loop_runtime.seat_visual_staging` exports:
  - `UNTRUSTED_NOTICE` (contract §4.6, verbatim);
  - frozen dataclasses `StagedVisual(logical_path, sha256, bytes, media_type)` and
    `VisualStage(root, observations, entries, stage_sha256, video_paths)`;
  - `stage_observations(records, review_dir) -> VisualStage | None` (the seat subset, the
    64 MiB budget, None for no records);
  - `revalidate_stage(stage, root) -> None` (checks against the stage entries and
    `stage_sha256`, never section 2; raises `seat_visual_stage_changed`);
  - `bundle_appendix(stage, records) -> str` (route-neutral, at most 64 KiB, otherwise
    `observation_cap_exceeded`);
  - `place_jailed_copy(stage, seat_dir) -> Path` (fresh files under
    `<seat_dir>/seat-home/review-visual`, via `write_new_file_at`, hashed while copying).
  `seat_uid` adds:
  - `handoff(review_dir, seat_id, *, gemini=False, visual=False, tree=None)` and the
    `handoff … --visual` verb, with the `st_nlink == 1` check before any chown and a
    per-inode `fstat`/`fchown`/`fchmod`;
  - `rehash_visual_in_h(holder_pid, seat_dir, entries, *, cap_bytes, time_limit_s) ->
    RehashResult(intact, reason)`, a frozen dataclass whose `reason` comes from a closed
    set, and the `rehash <seat_dir> <cap_bytes> <time_limit_ms>` verb, with entries on
    stdin.
  The rehash runs in H as H-root with no-follow walks. It returns not intact on every
  case in contract §4.3, including any entry (`review-visual` itself included) whose
  owner in H is not uid 0, whose group is not the seat's, or whose mode is not 0550 for a
  directory or 0440 for a file. `seat_route_contract` gains `seat_visual_stage_changed` as a
  `CODES` row of class `security` and an explicit `_SECURITY_CODES` entry. Contract
  §4.1–§4.4, §4.6, §7.
- [ ] IF-0-VISART-3 — The CLI:
  - `phase-loop observation validate <dir> [--json]`;
  - `phase-loop observation import …` with the contract §5 arguments and exit codes;
  - `phase-loop advisor-board … --observation <dir>` (repeatable, at most 4,
    executor-only, validated before composition in governed and default runs).
  `cli._advisor_board_command` appends the appendix before both the emit and the invoke
  arms. It refuses `observation_set_mismatch` per §4.5, by comparing the recomputed
  appendix with the `artifact.md` tail before the `artifact_sha256` refusal. The `--json`
  payload gains a
  top-level `visual_evidence` block and per-leg `visual_delivered` and
  `visual_post_run_intact`; the text summary prints the same paths. Each route's trusted
  instructions name its visual root, or unavailability, and carry `UNTRUSTED_NOTICE`.
  `seat_visual_stage_changed` is a literal in `_HARNESS_DETAIL_CODES`. Contract §4.2, §4.5,
  §5.

## Lane Index & Dependencies

SL-0 — Observation contract (preamble)
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-4
  Parallel-safe: no

SL-1 — Staging, jailed handoff and notice row
  Depends on: SL-0
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-2 — Board delivery, CLI and result block
  Depends on: SL-0, SL-1
  Blocks: SL-4
  Parallel-safe: no

SL-3 — Executor capture guidance and skill regeneration
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes

SL-4 — Documentation, inventory and spec reconciliation (SL-docs)
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Observation contract (preamble)

- **Scope**: Implement the `browser_observation.v1` loader, validator, executor-only gate, importer and deterministic `index.html` renderer, and ship the schema copy.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/browser_observation.v1.schema.json`, `phase-loop-runtime/tests/test_browser_observation_contract.py`, `phase-loop-runtime/tests/fixtures/browser-observation/**`
- **Interfaces provided**: IF-0-VISART-1
- **Interfaces consumed**: `models.resolve_visual_evidence_artifact` (pre-existing); the pinned schema and contract §2, §3, §7 (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/test_browser_observation_contract.py`, `phase-loop-runtime/tests/fixtures/browser-observation/**` | See the test outline below | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_browser_observation_contract.py` |
| SL-0.2 | impl | SL-0.1 | `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/browser_observation.v1.schema.json` | — | — |
| SL-0.3 | verify | SL-0.2 | `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py` | all SL-0 tests | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_browser_observation_contract.py` |

SL-0.1 test outline:

- **Schema identity.** The package copy's sha256 equals the pinned schema sha256 in the
  roadmap's External Inputs.
- **Positive fixtures.** One executor fixture, one broker fixture, and the maximum-size
  fixture: 4 observations × 32 captures with a11y and 2048-character target URLs.
- **Negative fixtures.** One per `observation_*` code, each built by mutating a valid
  fixture and entered through `load_observation`:
  - path defects: a symlink, a hard link, a `../` path and an extra file;
  - media and digest defects: a wrong magic number, digest drift and size drift;
  - each cap;
  - producer defects: `t3_preview` without `incognito`;
  - target defects (§2.3): an executor observation with a non-null `target.mode` or
    `target.policy_sha256`; a broker observation without them; `static_bundle` without
    `target.bundle_sha256`; any other mode with one;
  - URL defects: a `file:` URL (code `observation_target_forbidden`, not
    `observation_schema_invalid`), a userinfo URL and a backtick in a URL;
  - an edited `index.html`.
- **Executor-only gate.** `require_executor` refuses the broker fixture.
- **`index.html`.** Byte-identical across two renderings of one manifest, rendered without
  the `index` member, passes the §3 forbidden-element scan, and renders `observation_id`
  and `created_at`.
- **Importer.** Builds from PNG, JPEG and WebP images under a temp repo root, writing
  `target.mode`, `target.bundle_sha256` and `target.policy_sha256` as null. It refuses GIF
  and BMP, refuses `--tool browser_broker`, and opens no socket or process.

Files are opened with `O_NOFOLLOW` relative to a directory descriptor, and the manifest is
read once. The module imports nothing from `panel_invoker`, `seat_jail` or `cli`.

### SL-1 — Staging, jailed handoff and notice row

- **Scope**: Stage the seat subset under its budget, render the route-neutral appendix, place and hand off the jailed copy read-only under the leg's seat home, provide the in-H post-run rehash, and add the notice entries.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_visual_staging.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_visual_staging.py`, `phase-loop-runtime/tests/test_seat_uid_visual_handoff.py`, `phase-loop-runtime/tests/test_seat_visual_rehash_in_h.py`, `phase-loop-runtime/tests/test_seat_visual_profile_neutrality.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`
- **Interfaces provided**: IF-0-VISART-2
- **Interfaces consumed**: IF-0-VISART-1 (`ObservationRecord`, `load_observation`, `ObservationRefused`); `seat_jail.build_seat_jail`, `jail_profile_digest`, `actual_profile_digest`, `open_dir_nofollow`, `tree_is_private`, `read_regular_file_at`, `write_new_file_at`, `HOST_HOME_DIRNAME`, `seat_profiles.registered_legs`, `seat_uid._handoff_gemini_tree_at`, `seat_uid.in_h_argv` and `seat_uid._pythonpath_env` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_seat_visual_staging.py`, `phase-loop-runtime/tests/test_seat_uid_visual_handoff.py`, `phase-loop-runtime/tests/test_seat_visual_rehash_in_h.py`, `phase-loop-runtime/tests/test_seat_visual_profile_neutrality.py`, `phase-loop-runtime/tests/test_seat_route_contract.py` | See the test outline below | `timeout 600 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_seat_visual_staging.py phase-loop-runtime/tests/test_seat_uid_visual_handoff.py phase-loop-runtime/tests/test_seat_visual_rehash_in_h.py phase-loop-runtime/tests/test_seat_visual_profile_neutrality.py phase-loop-runtime/tests/test_seat_route_contract.py` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_visual_staging.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py` | — | — |
| SL-1.3 | verify | SL-1.2 | `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py` | SL-1 tests plus jail and permission regressions | `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_seat_visual_staging.py phase-loop-runtime/tests/test_seat_uid_visual_handoff.py phase-loop-runtime/tests/test_seat_visual_rehash_in_h.py phase-loop-runtime/tests/test_seat_visual_profile_neutrality.py phase-loop-runtime/tests/test_seat_route_contract.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_sandbox_permissions.py` |

SL-1.1 test outline:

- **Stage.**
  - The stage is a copy of the seat subset with no video; its digest matches §4.1.
  - With-video fixture: an observation whose manifest names `video/01.webm` stages and
    revalidates clean against the stage entries, though its copied manifest still names
    the unstaged video.
  - The 64 MiB budget refuses `observation_cap_exceeded`.
  - A byte change after staging raises `seat_visual_stage_changed`.
- **Appendix.**
  - Byte-stable, and route-neutral: no route path appears.
  - Carries `UNTRUSTED_NOTICE` verbatim.
  - The maximum-size fixture stays under 64 KiB, and a synthetic over-cap input refuses.
- **Placement and handoff.** Runs in a user namespace where available, otherwise skips
  with a reason.
  - `place_jailed_copy` refuses a source byte that changes mid-copy.
  - A placed copy ends H-root:seat, with directories 0550 and files 0440, set per inode
    on the opened descriptor.
  - A hard-linked file, a symlink or a FIFO refuses `seat_sandbox_refused:stage_not_private`
    before any chown changes ownership.
- **In-H rehash** (`test_seat_visual_rehash_in_h.py`). Runs in a user namespace where
  available, otherwise skips with a reason.
  - The fixture is a seat-owned 0700 `seat-home`, as after the handoff. A parent-side read
    from outside H gets EACCES and is never reported intact.
  - Through `in_h_argv`, a clean copy is reported intact.
  - Not intact in each case:
    - a byte-identical, seat-owned rename-and-replace of `review-visual`;
    - an entry with the wrong owner, group or mode;
    - a missing file and an extra file;
    - a symlink to an outside canary (the canary is never opened);
    - a FIFO (returns within the time limit and never blocks);
    - an over-cap file;
    - a timeout and a failed or malformed helper answer.
  - Entries travel on stdin, never on argv.
- **Profile neutrality.** For every leg in `registered_legs()`, compare a jail built
  in-process with a placed copy against one built without it: identical owner argv,
  `jail_profile_digest` and `actual_profile_digest`. The per-host digest goes to evidence
  only, never to a stored fixture.
- **Notice classes.** `test_every_current_mode_line_code_has_an_explicit_class` covers
  `seat_visual_stage_changed` as `security`, through both its `CODES` row and its
  `_SECURITY_CODES` entry.

SL-1 never edits `seat_jail.py`. New file-read references go to SL-4 for the
launch-reference inventory.

### SL-2 — Board delivery, CLI and result block

- **Scope**: Accept executor-only `--observation`, stage before composition, append the appendix before both board arms, deliver per route with trusted instructions, revalidate before and rehash after jailed legs, enforce native-fill identity, and emit the result block and `observation` subcommands.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_board_visual_delivery.py`, `phase-loop-runtime/tests/test_cli_observation.py`, `phase-loop-runtime/tests/test_native_fill_visual.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_seat_notices.py`
- **Interfaces provided**: IF-0-VISART-3
- **Interfaces consumed**: IF-0-VISART-1 (`load_observation`, `validate_observation`, `require_executor`, `import_visual_evidence`, `REFUSAL_CODES`); IF-0-VISART-2 (`UNTRUSTED_NOTICE`, `stage_observations`, `revalidate_stage`, `bundle_appendix`, `place_jailed_copy`, `seat_uid.rehash_visual_in_h`, `handoff --visual`, the `seat_visual_stage_changed` entries); `_JailedSeat.seat_dir`, `_JailedSeat.holder_pid`, `teardown_in_h`, `SeatProfile.readonly_paths`, `_seat_filesystem_view`, `_claude_direct_add_dirs`, `_require_staged_tree`, `preflight_native_leg_fills`, `invoke_board` and `_BROKER_SEALED_PROMPT_MAX_BYTES` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_board_visual_delivery.py`, `phase-loop-runtime/tests/test_cli_observation.py`, `phase-loop-runtime/tests/test_native_fill_visual.py` | See the test outline below | `timeout 600 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_board_visual_delivery.py phase-loop-runtime/tests/test_cli_observation.py phase-loop-runtime/tests/test_native_fill_visual.py` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py` | — | — |
| SL-2.3 | verify | SL-2.2 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py` | SL-2 tests plus board, notice and native-fill regressions | `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_board_visual_delivery.py phase-loop-runtime/tests/test_cli_observation.py phase-loop-runtime/tests/test_native_fill_visual.py phase-loop-runtime/tests/test_seat_notices.py phase-loop-runtime/tests/test_advisor_board_golden.py phase-loop-runtime/tests/test_broker_staged_tree_delivery.py phase-loop-runtime/tests/test_review_stage_binding.py phase-loop-runtime/tests/test_sandbox_egress.py phase-loop-runtime/tests/test_panel_native_fill_183.py phase-loop-runtime/tests/test_native_fill_refusal_cause.py` |

SL-2.1 test outline. Every case enters through `invoke_board` with a fake provider, or
through `cli.main`.

- **Delivery per §4.2 launch path.**
  - Jailed: the copy sits under `<seat_dir>/seat-home/review-visual`. The process
    handoff prefix carries `--visual`, and the probe prefix does not.
  - Direct Claude: under the already granted `review_dir`.
  - Non-brokered sandbox-profile (codex, gemini, grok), and brokered codex, Claude, grok
    and agy: `visual_delivered: false`. Their binds, grants and argv are byte-identical
    to a run without `--observation`, and `test_broker_staged_tree_delivery.py` stays
    green.
  - Native fill: a copy beside `artifact.md`, with `request.json` bytes unchanged.
  - Sealed and remote: `visual_delivered: false`.
  - Every route's instructions carry `UNTRUSTED_NOTICE` and name the visual root, or say
    the files are unavailable.
- **No-op.** With no `--observation`, every route's instructions, argv and bundle are
  unchanged, and `test_advisor_board_golden.py` passes.
- **With video.** A with-video observation is delivered with its video unstaged and
  listed in the board result.
- **Bundle.** It ends with the appendix, identically in the emit and invoke arms. A bundle
  plus appendix over 512 KiB refuses `observation_cap_exceeded`.
- **Refusals with zero seat launches**, each exiting 2:
  - an invalid observation;
  - a broker observation;
  - a fifth observation.
  Each also refuses identically in a governed run.
- **Stage drift.** A stage changed before a jailed launch degrades that leg with
  `seat_visual_stage_changed`.
- **Post-run rehash.**
  - `rehash_visual_in_h` is called with the leg's `holder_pid` and `seat_dir`, after
    quiescence and before `teardown_in_h`.
  - A not-intact result, or a helper failure, records `seat_visual_stage_changed`, sets
    `visual_post_run_intact: false` and flags the leg.
  - No parent-side read of `seat-home` is attempted.
- **Native fill.**
  - A `--native-leg` run with a different observation set refuses
    `observation_set_mismatch`, before the `artifact_sha256` refusal.
  - The check compares recomputed appendix bytes with the `artifact.md` tail. It never
    parses the stage digest out of `artifact.md`.
  - A run with the same set proceeds.
- **Observation subcommands.** `observation validate|import` exit codes and JSON.
- **Result block.** The `visual_evidence` fields are present.
- **Egress.** No seat egress allowlist digest changes.

Observation validation runs before composition, so a refusal spends no seat. The appendix
is appended before the bundle digest is taken. SL-2 adds `seat_visual_stage_changed` to
`_HARNESS_DETAIL_CODES` as a literal.

### SL-3 — Executor capture guidance and skill regeneration

- **Scope**: Name T3 preview on the `incognito` profile as a capture source, and direct moving the screenshot into the worktree, `observation import` and `--observation` in the execute skills, then regenerate the bundles and goldens.
- **Owned files**: `skills-src/codex/codex-execute-phase/SKILL.md`, `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`, `phase-loop-skills/execute-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-execute-phase/**`, `phase-loop-runtime/tests/data/launchspec_golden/**`, `phase-loop-runtime/tests/test_execute_skill_visual_capture.py`
- **Interfaces provided**: (none)
- **Interfaces consumed**: contract §5 and §6 text (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_execute_skill_visual_capture.py` | Each execute-skill source and its generated bundle copy names the three capture sources, `profileId: "incognito"`, moving the file into the worktree, `phase-loop observation import` and `--observation`, and never presents T3's default or a named profile as acceptable; paired with the drift and golden tests | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_execute_skill_visual_capture.py` |
| SL-3.2 | impl | SL-3.1 | `skills-src/codex/codex-execute-phase/SKILL.md`, `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`, `phase-loop-skills/execute-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-execute-phase/**`, `phase-loop-runtime/tests/data/launchspec_golden/**` | — | — |
| SL-3.3 | verify | SL-3.2 | generated outputs | SL-3 test plus drift and golden | `timeout 600 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_execute_skill_visual_capture.py phase-loop-runtime/tests/test_skills_bundle_drift.py phase-loop-runtime/tests/test_launchspec_golden.py` |

SL-3.2 edits only the two sources, then runs
`python phase-loop-runtime/scripts/regenerate_skills_bundle.py` and
`python phase-loop-runtime/scripts/sync_skills_bundle.py`. Generated files are never
hand-edited. The guidance never tells an executor to open a browser for a seat.

### SL-4 — Documentation, inventory and spec reconciliation (SL-docs)

- **Scope**: Single writer of shared docs and the launch-reference inventory; records the phase evidence.
- **Owned files**: `docs/browser-observation.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `plans/evidence/browser/VISART.md`, `specs/phase-plans-browser-v1.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-VISART-1, IF-0-VISART-2, IF-0-VISART-3
- **Parallel-safe**: no (terminal)

It also takes the new launch references SL-1 and SL-2 report, and SL-3's regenerated text.

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan with `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if the helper is absent, record "manual catalog audit". |
| SL-docs.2 | docs | SL-docs.1 | `docs/browser-observation.md`, `CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.doc-decisions.json`, `phase-loop-runtime/tests/data/seat_launch_references.json` | New guide: the artifact, `observation import|validate`, `--observation`, the untrusted-content notice, viewing in T3 and in desktop or mobile Chrome, and OR-4's linked `ai` environment with its copy fallback. CONTRACTS.md: jailed seats find visual evidence at `/seat/home/review-visual`, handed off read-only with no new mount, and rehashed after the run in H as final-state audit evidence; the per-launch-path delivery table; the seat-channel rule of contract §8.1; the new notice. Also the card and an `[Unreleased]` entry, plus inventory rows for SL-1 and SL-2 references. |
| SL-docs.3 | docs | SL-docs.2 | `specs/phase-plans-browser-v1.md`, `plans/evidence/browser/VISART.md` | Metadata-only evidence: test receipts, each host's per-leg `jail_profile_digest` (evidence only) and the regenerated-bundle check. Append `### Post-execution amendments` to VISART only if a freeze proved wrong. |
| SL-docs.4 | verify | SL-docs.3 | — | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_seat_reference_inventory.py`, then `PYTHONPATH=phase-loop-runtime/src timeout 120 python3 -m phase_loop_runtime.cli validate-roadmap --repo . --roadmap specs/phase-plans-browser-v1.md`, then the hosted docs-freshness audit. |

## Execution Notes

- **No gate.** EXT-SEATSCODEX is satisfied (agent-harness#1916 merged), so every lane may
  start. Lanes branch from current main.
- **No release.** This phase dispatches no release, tag or external workflow, so it has no
  post-dispatch evidence reducer.
- **Single-writer files**: `seat_uid.py` and `seat_route_contract.py` (SL-1);
  `panel_invoker.py` and `cli.py` (SL-2); `seat_launch_references.json` (SL-4).
  - No VISART lane edits `seat_jail.py`, `seat_profiles.py`, `sandbox_egress.py`,
    `seat_egress_proxy.py` or an `agy_qualification.ROUTE_CORE` file.
  - AGYROLL's REQUAL and EXECADMIT phases (planned in agent-harness#1927) will also edit
    `panel_invoker.py`; serialize by landing order.
- **Companion tests**: SL-1 owns `test_seat_route_contract.py`. SL-2 owns
  `test_panel_invoker.py` and `test_seat_notices.py`, so any needed regression edit is
  owned.
- **Known destructive changes**: none — every lane is purely additive.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none; callers import `phase_loop_runtime.browser_observation` directly.
- **Generated files**: SL-3 alone writes `phase-loop-skills/**`, `skills_bundle/**` and the
  launch-spec golden, through the two regeneration scripts.
- **Shared-host limits**: every command here is targeted, serial (no `-n`, so it runs with
  or without pytest-xdist) and under `timeout`. No test starts a browser, a seat provider
  or a network listener. Full suites run on hosted CI and Gate A.
- **Validation**: the managed `phase-loop` 0.7.27 does not accept this roadmap's registry
  status; validators run from the in-tree runtime (`PYTHONPATH=phase-loop-runtime/src`).
- **Worktree naming**: claude-execute-phase allocates unique worktree names via `scripts/allocate_worktree_name.sh`. Plan doc does not need to spell out lane worktree paths.
- **Stale-base guidance**: Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Execution Policy

- execute: effort=medium, reason=bounded contract work with frozen inputs
- SL-1: effort=high, reason=privileged handoff ordering is security sensitive
- SL-2: effort=high, reason=delivery spans six routes and two board arms
- SL-3: effort=low, reason=skill text plus scripted regeneration
- SL-4: effort=low, reason=documentation reducer

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/browser-observation.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `plans/evidence/browser/VISART.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-VISART-1 — proven by `V0` (`test_browser_observation_contract.py`), falsified by any §7 negative fixture loading cleanly, by the maximum-size fixture refused, or by a `file:` URL reported as `observation_schema_invalid`. Path-entered control: each fixture enters through `load_observation` on a real directory.
- [ ] EC-VISART-2 — proven by `V0` and `V2` (`test_cli_observation.py`), falsified by two renderings of one manifest differing, by `observation import` accepting a broker tool, `t3_preview` without `incognito`, or a GIF or BMP image, or by the import opening a socket or spawning a process. Path-entered control: images enter through the installed `phase-loop observation import` entry point and `resolve_visual_evidence_artifact`.
- [ ] EC-VISART-3 — proven by `V2` (`test_board_visual_delivery.py`, `test_advisor_board_golden.py`, `test_broker_staged_tree_delivery.py`), falsified by:
  - a delivering route whose seat view lacks the stage or can write it;
  - any route gaining a new grant, or a brokered route reporting `true`;
  - any change to instructions, argv or bundle when no `--observation` is given;
  - any route's trusted instructions missing `UNTRUSTED_NOTICE`;
  - an over-cap appendix or bundle reaching a seat;
  - a with-video observation refused;
  - an invalid or broker observation reaching a launch.

  Path-entered control: Path-entered control: observations enter through `phase-loop advisor-board --observation` and `invoke_board` with a fake provider.
- [ ] EC-VISART-4 — proven by `V1` (`test_seat_visual_profile_neutrality.py`, `test_seat_uid_visual_handoff.py`, `test_seat_visual_rehash_in_h.py`, `test_seat_jail.py`) and `V2`, falsified by:
  - any registered leg whose owner argv, `jail_profile_digest` or `actual_profile_digest` differs with and without a placed copy;
  - a changed seat egress digest;
  - a hard-linked or FIFO entry surviving handoff;
  - a drifted stage launching;
  - a seat-owned 0700 `seat-home` read from outside H being reported intact;
  - an in-H rehash reporting intact over a renamed, missing, extra, linked, FIFO or over-cap entry, or after a timeout or helper failure;
  - the rehash opening an outside canary or blocking on a FIFO.

  Path-entered control: the copy enters through `place_jailed_copy` and `seat_uid handoff --visual`, and the rehash through `rehash_visual_in_h` over `in_h_argv`.
- [ ] EC-VISART-5 — proven by `V2` (`test_cli_observation.py`, `test_board_visual_delivery.py`), falsified by a `--json` payload missing any contract §5 `visual_evidence` field, by a leg missing `visual_delivered`, by any sandbox-profile, brokered, sealed or remote path reporting `true`, or by a jailed leg missing `visual_post_run_intact`. Path-entered control: through `cli.main(["advisor-board", …])`.
- [ ] EC-VISART-6 — proven by `V3` (`test_execute_skill_visual_capture.py`, `test_skills_bundle_drift.py`, `test_launchspec_golden.py`), falsified by a generated bundle that differs from its regenerated source, or by guidance that accepts T3's default profile. Path-entered control: text enters through the two `skills-src` files and the regeneration scripts.
- [ ] EC-VISART-7 — proven by `V2` (`test_native_fill_visual.py`), falsified by a `--native-leg` run with a different observation set reaching a seat, or by the same set being refused. Path-entered control: both runs enter through `cli.main(["advisor-board", …])` with `--emit-native-request`, then `--native-leg`.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, with
file paths under `phase-loop-runtime/tests/`. The new test files are not in the tree yet,
so these selectors name the tests to run once they exist; they are not run receipts.
`automation.suite_command` is the union of `V0` to `V4`.

- `V0`: `P test_browser_observation_contract.py`
- `V1`: `P test_seat_visual_staging.py test_seat_uid_visual_handoff.py test_seat_visual_rehash_in_h.py test_seat_visual_profile_neutrality.py test_seat_route_contract.py test_seat_jail.py test_seat_sandbox_permissions.py`
- `V2`: `P test_board_visual_delivery.py test_cli_observation.py test_native_fill_visual.py test_seat_notices.py test_advisor_board_golden.py test_broker_staged_tree_delivery.py test_review_stage_binding.py test_sandbox_egress.py test_panel_native_fill_183.py test_native_fill_refusal_cause.py`
- `V3`: `P test_execute_skill_visual_capture.py test_skills_bundle_drift.py test_launchspec_golden.py`
- `V4`: `P test_seat_reference_inventory.py`, then `PYTHONPATH=phase-loop-runtime/src timeout 120 python3 -m phase_loop_runtime.cli validate-roadmap --repo . --roadmap specs/phase-plans-browser-v1.md`
- **Visual check** (no browser in any sandbox): open one fixture observation's `index.html`
  in a desktop Chrome and in a mobile-width Chrome viewport, and view one staged PNG
  inline in T3 by absolute path. Record the result in `plans/evidence/browser/VISART.md`.
- **Full suite**: hosted CI and Gate A only.
