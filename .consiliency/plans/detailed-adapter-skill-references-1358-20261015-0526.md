# Detailed plan: context-file adapter runs can read the `references/` files their skills link (agent-harness#1358)

## Task
Let non-Claude adapter runs read the `references/` files that a skill's `SKILL.md`
links by relative path, so the codex, gemini and opencode plan-phase and
execute-phase skills can be split the way the Claude ones were
(agent-harness#1572, agent-harness#1687). Today `_skill_bodies` delivers only
`SKILL.md` text, so a moved section would vanish from adapter runs.

## Research summary
- **Delivery by harness.** `_skill_bodies` (`injection.py:649-660`) feeds only `_render_context_body` (around `injection.py:533`).
  - Claude and pi return early, so they never call it.
  - gemini, grok, opencode, pi-via-context and `command` use `context_file` (`HARNESS_INJECTION_MODES`, `injection.py:196-208`).
  - For those modes the launcher writes `context.md` through `_phase_loop_context_path` (`launcher.py:3595`) or `_gemini_workspace_context_path` (`launcher.py:3585`), then points the CLI at it.
  - The call sites are `launcher.py:2323, 3507, 3537, 3554, 3559, 3564, 3569`.
- **Readable locations.**
  - gemini's context directory is added through `--add-dir`, so it is already readable.
  - opencode's run directory is `.phase-loop/runs/<run-id>/`, inside the repo.
  - So a file copied next to `context.md` is readable wherever `context.md` is, and the existing pointer text ("do not try to read installed skill files outside the workspace", `launcher.py:970`) stays true.
- **codex is different.** It is `prompt_only` (`injection.py:197`): its prompt is only the workflow command, and it uses the codex skills installed natively. Install copies the whole skill directory, including `references/` (`skill_install.py:142-156`).
- **Nothing is broken today.** No codex, gemini or opencode skill pack in `HARNESS_ACTION_SKILLS` (`injection.py:83-140`) carries `references/`. Only `*-execute-detailed` and `*-task-contextualizer` do, and those aren't in any adapter pack. This plan unblocks the future splits.
- **Where reference files live.** `resolve_source_skill_dir` (`skill_inventory.py:381-406`) can return a canonical `phase-loop-skills/<skill>` directory, where harness-only references sit in `_overrides/<harness>/references/`, or a bundle directory, where they sit in `references/`.
- **Coupling.**
  - `seat_launch_references.json` requires every file read at launch to be recorded.
  - `_bundle_sha256` gains `_skill_references_sha256` in agent-harness#1687.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/injection.py` (modify)
- `skill_reference_files(repo, harness_target, expected_skill_pack) -> tuple[tuple[str, Path], ...]` — add — the single list of `(f"skills/{skill}/references/{rel}", source_path)` for each pack skill. It reads `<dir>/references/` and, for a canonical directory, `<dir>/_overrides/<harness>/references/`, sorted by destination. Both the copy step and the digest use it.
- `_skill_bodies` — modify — after the `SKILL.md` text of each skill that has reference files, append one line: "This skill's linked `references/` files are copied beside this context file under `skills/<skill>/references/`; read one at the step that links it." Skills without references get no line, so the context for every current pack stays byte-identical.
- `_skill_references_sha256` (from agent-harness#1687) — modify — build it from `skill_reference_files` so the digest and the copied files list the same files, including the `_overrides/<harness>/` case.

### `phase-loop-runtime/src/phase_loop_runtime/launcher.py` (modify)
- `_phase_loop_context_path` and `_gemini_workspace_context_path` — modify — add a keyword-only `references: tuple[tuple[str, Path], ...] = ()` argument and copy each source to `target.parent / dest` (`mkdir(parents=True)`, `shutil.copyfile`). The default keeps the Claude call (`launcher.py:2323`, `:3507`) unchanged.
- The context-file branches at `launcher.py:3537, 3554, 3559, 3564, 3569` — modify — pass `references=injection.skill_reference_files(repo, harness_target, spec.prompt_bundle.expected_skill_pack)`. Take the repo and harness from the spec fields the branch already uses; search for how `repo_path` is obtained at `:3534`.

### `phase-loop-runtime/tests/test_adapter_skill_references.py` (create)
- `test_context_file_harnesses_get_linked_references` — add — use a temporary skill directory with `references/a.md` and patch `_resolve_pack_skill_dirs`. For gemini and opencode, assert that `render_context()` contains the note line and that the launcher's materialize step writes `skills/<skill>/references/a.md` next to `context.md` with identical bytes.
- `test_canonical_override_references_are_found` — add — a `_overrides/gemini/references/b.md` layout is listed for gemini and not for opencode.
- `test_skills_without_references_leave_context_unchanged` — add — the real packaged gemini and opencode packs produce no note line and copy nothing.

### `phase-loop-runtime/tests/data/seat_launch_references.json` (modify)
- Add rows for the new `injection.skill_reference_files` reads (`io.rglob` or `io.is_dir`) and the `launcher` copy. Keep module/function order.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/protocol.md` — modify — extend the `context.md` bullet (around line 1815: "It must live beside `launch.json` and contain the same repo-sourced workflow bundle…"). Add that the linked `references/` files of the injected skills are copied beside it under `skills/<skill>/references/`. This adds no new vocabulary, launch field or mode.
- `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/harness-capability-matrix.md` — none. Line 518 still describes the opencode pointer correctly.

## Dependencies & order
1. agent-harness#1687 must merge first, because it adds `_skill_references_sha256`. Rebase onto it.
2. Change the injection helper before the launcher, since the launcher imports it.
3. Update the inventory JSON last, from the actual failing Counter diff.

Out of scope, as follow-ups on agent-harness#1358:
- **codex.** It relies on installed native skills, which include `references/`. Whether codex's native skill loader gives the model the skill directory path, so relative links resolve, is unverified. Check it with one live codex run before splitting `codex-*-phase`.
- **The cross-skill read.** `*-execute-phase` read `pr-writing.md` from the installed `<harness>-execute-detailed` directory (`phase-loop-skills/execute-phase/SKILL.md:265`). Context-file adapters are told not to read installed skill files, and `execute-detailed` isn't in their pack. Fix this when execute-phase is split: either ship `pr-writing.md` with execute-phase or add `execute-detailed` to the pack.
- The actual splits of `{codex,gemini,opencode}-{plan,execute}-phase` and the change to `test_harness_only_references_do_not_leak_into_other_harnesses` that comes with them.

## Verification
```bash
cd phase-loop-runtime
PYTHONPATH=src:tests uv run python -m pytest -q -p no:cacheprovider \
  tests/test_adapter_skill_references.py tests/test_claude_bundle_reference_reads.py \
  tests/test_seat_reference_inventory.py tests/test_phase_loop_injection.py \
  tests/test_injection_skill_failloud.py tests/test_phase_loop_launcher.py \
  tests/test_skills_canon_parity.py
# Goldens: the codex prompt sha and the gemini/opencode pointer text must not move.
PYTHONPATH=src:tests uv run python -m pytest -q -p no:cacheprovider -k golden tests/
```
- Negative control: revert the `launcher.py` copy. `test_context_file_harnesses_get_linked_references` must then fail on the missing file.
- Edge case: a skill whose `references/` is empty or missing adds no note and no copies.

## Acceptance criteria
- [ ] For a gemini or opencode pack skill with `references/a.md`, the launch writes `skills/<skill>/references/a.md` beside `context.md` with identical bytes, and `context.md` contains the note line for that skill. Proven by `tests/test_adapter_skill_references.py`.
- [ ] For every current packaged gemini and opencode pack, `render_context()` is byte-identical before and after the change, and `launchspec_golden.json` is unchanged.
- [ ] `skill_bundle_sha256` and the copied files come from the same `skill_reference_files` list. Editing an `_overrides/<harness>/references/` file changes the digest.
- [ ] `tests/test_seat_reference_inventory.py` passes with the new reads recorded.

## Execution Policy
- execute: effort=medium, reason=two-module plumbing change with an exact-match inventory test and goldens that must not move
