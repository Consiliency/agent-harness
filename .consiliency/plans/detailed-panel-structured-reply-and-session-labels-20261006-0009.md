# Detailed plan: opt-in structured panel-seat replies, descriptive session labels, and a blocked archive analysis

## Task

Three related asks, from the maintainer, for `agent-harness`:

1. **Machine-consumable panel replies.** An opt-in, schema'd reply for advisor-board seats (verdict, findings[], summary; an advisory variant without a verdict), parsed in the harness through the BAML v1 worker, failing closed to a typed leg status.
2. **Descriptive session labels.** Sessions and threads the harness launches should carry a name that shows repo, topic and seat/lane instead of a random or first-message title.
3. **Auto-archive of completed sessions in the host app panel.** Once a session completes successfully (and, for panel seats, its reply verified), it should stop cluttering the app's session panel. Progress must stay viewable while the session runs.

Hard constraints from the maintainer: do not interfere with the Claude and codex work already in flight on `dev0`; keep default launch argv/prompt bytes byte-identical (golden-pinned); run no live panel seats in tests; qualify every issue and PR number with its repository.

## Split recommendation (bounded-plan threshold)

This touches more than three conceptually distinct changes, so it is split into **four bounded plans**. This document fully specifies **Plan A1** (new files only) and gives **Plans A2, B and C** as sequenced, gated follow-ons. A2 and part of B are **blocked on Consiliency PR merges**; C is **blocked on an owner answer**.

**Roadmap home (maintainer decision, 2026-10-06): standalone**, on the condition that it can be executed without interfering with ongoing work. This plan therefore carries no `EC-<ALIAS>-<N>` goals; its acceptance items are plain testable assertions. The non-interference condition is enforced by the sequencing below and by the overlap check in Verification.

| Plan | Scope | Touches hot files? | Gate |
|---|---|---|---|
| A1 | Reply schema, BAML parse op, typed parse result, corpus tests | No (new files plus three additive table entries in BAML-only files) | None. Can land now. |
| A2 | Opt-in plumbing: flag, prompt suffix, leg detail codes, verdict derivation, JSON output | `panel_invoker.py`, `cli.py`, `advisor_board/CONTRACTS.md` | After agent-harness#1253 and agent-harness#1222 merge |
| B | Opt-in session label helper and call sites | `launcher.py` (agent-harness#1222 touches it), `panel_invoker.py` | Helper now; call sites after agent-harness#1222 and agent-harness#1253 |
| C | Auto-archive in Claude Code's native app | Seat epilogue in `panel_invoker.py` if H1 holds | One validation experiment |

## Research summary

**Structured replies are not planned anywhere.** The v10 roadmap (`specs/phase-plans-v10.md`) has no phase or exit criterion for them. The nearest items are grammar-in-prose: the EXECFIND `falsifier` fence (IF-0-EXECFIND-1), the PRESROUTE `FINDING <id>:` lines and `president.ruling.json` (IF-0-PRESROUTE-1), and the RATIFY `ruling_ledger.v1` rows. Today a seat ends with `AGREE` / `PARTIALLY AGREE` / `DISAGREE`, read by `terminal_verdict` in `panel_invoker.py`; governed review turns whole legs, not findings, into `ReviewFinding` objects. Related open issues: agent-harness#1110 (seat prose split into fragments), agent-harness#1114 (sandbox and monitoring evidence missing from the result JSON), agent-harness#1180 (structured `seat_key` on `ReviewFinding`), agent-harness#1107 (typed provider failures). The roadmap has no home for this work, so a maintainer decision is needed on whether it is a new phase, an EXECFIND/RATIFY extension, or standalone (Open items).

**BAML v1 is the parser to reuse.** agent-harness#1160 moved the runtime to `baml-bridge==0.20.1`, run in a worker subprocess (`_baml_worker.py`) so the parent never imports `baml_bridge`. Reaching the worker takes three coordinated tables: the worker's `_OP_FUNCTIONS` (op name to bridge function, params, result keys), the client's `_OUTCOMES_BY_OP` and `_BRIDGE_TABLE` in `baml_modular.py`, and a primitive-returning function in `baml_src/phase_loop_bridge.baml` (every bridge function returns `map<string,string>` so no codegen typemap is needed). `parse_baml_response` is hard-wired to `EmitPhaseCloseout` (it raises "function not found" for any other name), so a panel op must be a **new** public function, not a generalisation of the existing one. Two tripwires exist: `tests/data/baml_call_sites.json` (a caller table checked by `test_phase_loop_baml_v1_callers.py`) and `tests/data/baml_worker_handler_allowlist.json` (an exception-handler tripwire, currently empty).

**Where replies can come from.** A non-brokered Claude seat and the jailed Claude seat (agent-harness#1132) both write `panel-claude.txt`; a plain brokered Claude seat has `--tools ""` and replies only in chat, read from the session transcript. So the JSON must be extractable from either a file or a final chat message. Keeping the filename `panel-claude.txt` (content becomes JSON) avoids touching ingestion.

**Labels: the thread clutter most likely comes from executor launches, not only panel seats.** From the repo survey (`launcher.py` command builders): the codex executor (`build_codex_command`) has no `--ephemeral` and no name flag; `claude -p`, `claude --bg`, agy, opencode and grok launches pass no name. `ClaudeAgentViewAdapter.launch_command` already supports `name=` but neither caller passes it. Panel seats are partly better: the brokered codex seat uses `--ephemeral`. The first user turn of an executor session is `codex-execute-phase <plan>` or "Read the workflow command at the top of ...", which is what a host app that titles from the first message would show. `LaunchRequest` already carries `repo`, `roadmap`, `phase`, `plan`, `action`, `executor`, so a label needs no new data plumbing.

**Codex threads cannot be titled by a prompt prefix.** In the one codex rollout inspected, the first user message is the injected `# AGENTS.md instructions` block, ahead of the real prompt. On this host, 63 of 93 imported threads are titled `# AGENTS.md instructions...`. (Inference from one rollout plus titles; Plan C's experiment should confirm.)

**Host app facts (T3 Code, local database read-only).** Threads have `archived_at`, `settled_at`, and `thread.settled` events; 92 of 93 provider sessions carry an `importedTranscripts` payload key, so the app imports transcripts from the CLIs' session stores. The harness repo has no T3 references, the `t3` CLI has no thread subcommand, and the `t3-code` tools exposed to agents cover only previews, devices and pull-request links. Codex has its own `~/.codex/archived_sessions` store; Claude has `claude rm` / `claude stop` (Agent View) and `claude purge <path>` (project state), and `purge` accepts a path that no longer exists. `claude_agent_view.py` already has `stop` and `remove` helpers with no production caller. Per the maintainer, the app's threads are created by the harness's launches on various machines, usually codex.

**Concurrency and ownership.** Open PRs touching `panel_invoker.py`: agent-harness#1253, agent-harness#1222, agent-harness#851. agent-harness#1222 also touches `launcher.py`, `cli.py` and `advisor_board/*`; agent-harness#1253 also touches `cli.py` and `advisor_board/CONTRACTS.md`. Nine v10 phases (HARDEN, REVIEWTRUTH, LEGLIFE, GOVLEAN, PRESROUTE, EXECFIND, RATIFY, GOVSETUP, PANEL) list those files and none has a completed exit criterion. No open PR touches `baml_modular.py`, `_baml_worker.py` or `baml_src/`. The roadmap-ownership workflow is advisory; the repo's precedent (PRESROUTE) is to declare shared-file overlap and use additive seams only.

## Changes

### Plan A1 — new files and additive table entries (lands first, no overlap with open PRs)

#### `phase-loop-runtime/src/phase_loop_runtime/baml_src/panel_seat_reply.baml` (create)
- `class PanelFindingV1` — add — severity (`blocking|non_blocking`), title, body, optional location; one finding per item, so findings are items of an array and are never scraped from prose.
- `class PanelSeatReplyV1` — add — `mode` implied by the call; `verdict` (nullable; required only in review mode), `summary`, `findings[]`.
- `function ReviewSeatReply(mode: string) -> PanelSeatReplyV1` — add — a client and prompt modelled on `emit_phase_closeout.baml`, whose prompt carries BAML's output-format instruction so the schema text comes from one source of truth.
- Syntax of the v1 output-format interpolation is **not yet verified**; settle it in the spike (Verification step 1).

#### `phase-loop-runtime/src/phase_loop_runtime/baml_src/phase_loop_bridge.baml` (modify, additive)
- `function phase_loop_parse_panel_reply(raw: string, mode: string) -> map<string,string>` — add — returns exactly one of `ok` (JSON of the parsed reply) or `error`, mirroring `phase_loop_parse_closeout`.
- `function phase_loop_panel_reply_prompt(mode: string) -> map<string,string>` — add — returns the rendered schema-instruction text for appending to a seat prompt.

#### `phase-loop-runtime/src/phase_loop_runtime/_baml_worker.py` (modify, additive)
- `_OP_FUNCTIONS` — add two entries: `parse_panel_reply` and `panel_reply_prompt`, with their params and result keys. No behaviour change to existing ops.

#### `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py` (modify, additive)
- `_OUTCOMES_BY_OP` — add the two new ops with their outcome keys.
- New public `parse_panel_reply(raw_text, mode)` and `panel_reply_instructions(mode)` — add — thin wrappers over `_worker_call`, reusing the existing sanitising and `_client_boundary` fault mapping. `parse_baml_response` and the `EmitPhaseCloseout` path are **not modified**.

#### `phase-loop-runtime/src/phase_loop_runtime/panel_reply.py` (create)
- `PanelSeatReply` pydantic model (`extra="forbid"`) mirroring the BAML class — add — the typed value consumers use.
- `extract_reply(raw_text, mode) -> ReplyOutcome` — add — tries a whole-text parse, then the last fenced JSON block, then the largest balanced JSON object; returns either a `PanelSeatReply` or a **typed failure kind** (`empty`, `no_json`, `schema_mismatch`, `verdict_missing`, `verdict_forbidden`, `worker_fault`). Never raises on seat content; a `BamlWorkerError` maps to `worker_fault`.
- `derive_terminal_verdict(reply) -> str | None` — add — returns the reply's verdict in the same vocabulary `terminal_verdict` uses, so downstream code that expects `AGREE`/`PARTIALLY AGREE`/`DISAGREE` keeps working.
- No leg detail codes are emitted here. Mapping failure kinds to the closed detail vocabulary happens in A2, because that vocabulary lives in `panel_invoker.py`.

#### `phase-loop-runtime/tests/test_panel_reply_schema.py` and `phase-loop-runtime/tests/data/panel_reply_corpus/` (create)
- Corpus-driven tests: clean JSON; fenced JSON; prose before and after the JSON; truncated JSON; wrong enum; extra field; missing verdict in review mode; verdict present in advisory mode; empty text; non-UTF-8 bytes; a reply claiming a different `mode`. Each asserts the typed outcome, never an exception.
- A falsifier test that mutates the parse to accept a missing verdict and must go red.
- Tests use the existing worker through `baml_modular` fixtures; **no live seat is launched**.

#### `phase-loop-runtime/tests/data/baml_call_sites.json` (modify, additive)
- Add rows for the new direct call sites so `test_phase_loop_baml_v1_callers.py` stays green.

#### `CHANGELOG.md` (modify)
- Add an `[Unreleased]` entry under its own heading (see Documentation impact).

### Plan A2 — opt-in plumbing (gated on agent-harness#1253 and agent-harness#1222 merging)

#### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify, additive seam only)
- New keyword `reply_format: str | None = None` threaded through `invoke_board`, `invoke_panel` and `_default_spawn` — add. `None` is the default and leaves every argv, prompt and result byte-identical.
- When set: append `panel_reply_instructions(mode)` to the seat prompt (inside the sealed prompt, so the attested prompt hash simply covers it), parse the seat text with `extract_reply`, and attach the parsed reply to `PanelLegResult` through a **non-field attachment** (the `attach_native_agent_request` / EXECFIND falsifier precedent), so `dataclasses.asdict` and the golden never see it.
- Add typed leg detail codes for each failure kind to the closed detail vocabulary (exact literals, per CHANGELOG F030) — add. A non-conforming structured reply fails closed as today's `panel_nonconforming`, never as a quiet pass.
- `_write_incremental_verdict` — add an optional `reply` key **only when a reply was parsed**; the default payload (`index, leg, seat_key, status, usable, text, detail`) is unchanged. This overlaps agent-harness#1114's ask; coordination is recorded on that issue (see Decided) and A2 builds on top of its fields, never ahead of them.

#### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify, additive)
- `--reply-format json` on `advisor-board` — add — maps to `reply_format`; unset by default.

#### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` and `docs/advisor-board-capabilities-card.md` (modify)
- Document the schema, the failure kinds, the opt-in flag and the non-field attachment — add a section at the end of each.

### Plan B — descriptive session labels (helper now; call sites gated)

#### `phase-loop-runtime/src/phase_loop_runtime/session_label.py` (create)
- `build_label(repo, topic, role) -> str` — add — pure function producing `<repo> · <topic> · <role>`, sanitised (no control characters, bounded length, no secrets, no path separators). `role` is the lane/phase/action for executors and `seat_key` for panel seats. Fully unit-testable and conflict-free.
- `labelling_enabled(env) -> bool` — add — opt-in switch (default off) so all default argv and prompt bytes stay unchanged.

#### Call sites (gated)
- `launcher.py` — Agent View `launch_command(name=...)` calls (two sites) and the claude `-p` builder: pass `--name` when enabled — modify. After agent-harness#1222 merges.
- `panel_invoker.py` — the three Claude TUI command builders (`_claude_tui_command`, `_broker_claude_tui_command` and its `sandboxed=` branch) — add `--name` when a label is supplied. After agent-harness#1253 and agent-harness#1222 merge.
- The label is the Claude Code session name (`--name`, which the registry records as `nameSource: user`). The input to it is a topic only the driving agent knows, so add an opt-in `--topic <short text>` to `advisor-board` (A2/B, `cli.py`, gated) that is composed into `<repo> · <topic> · <seat_key>`; with no topic it falls back to `<repo> · <seat_key>`. The topic is sanitised and bounded like every label.
- **AGENTS.md guidance (maintainer: "override it and edit AGENTS.md as well").** A search of the repo `AGENTS.md`, `~/.claude/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` and the dotfiles copies found **no existing session-naming guidance**, so there is nothing to override. Add a short section to the repo `AGENTS.md` (and a matching line in the `advisor-board` skill sources under `phase-loop-skills/advisor-board/`) telling a driving agent to pass `--topic` with a few words naming what the board is reviewing. Land the text with the `--topic` flag, not before, so the guidance never names a flag that does not exist. The global copies live in the dotfiles repo, outside this repo; flag them to the owner, do not edit them here.
- Non-Claude executors have no name flag: label goes in the first line of the prompt **only where the host app titles from it**. The Agent View launch is special: its nonce proof reads the first user turn (`phase-loop-launch-nonce`), so a label must not alter that turn. Codex cannot be titled this way (see Research summary), so codex labelling is part of Plan C's decision, not this plan.
- Pinned by goldens: `tests/data/launchspec_golden/launchspec_golden.json`, `tests/data/launchspec_golden/pre_d1_closeout_prompt.json`, `tests/test_broker_command_builders.py`, `tests/test_phase_loop_claude_agent_view_adapter.py`. All must pass unmodified on the default path; new tests assert the label only when enabled.

### Plan C — auto-archive (analysis only; **blocked on an experiment**)

**Re-scoped by the maintainer (2026-10-06):** the cluttered surface is **Claude Code's own native app session list**, independent of T3 Code. The T3 `settled` state is adequate for threads viewed in T3 but does not help sessions that a non-Claude harness (usually codex) launches through the Claude TUI adapter and that then appear in Claude Code's app. Mechanisms 1 and 2 below (host-app archive, codex store) therefore **drop out** for this goal; they stay recorded only as the T3 and codex-side alternatives.

No code is proposed. The plan to produce is chosen after the experiment below runs.

**What is known locally (dev0, read-only):**
- Claude Code keeps a live session registry in `~/.claude/sessions/<pid>.json` with `name`, `nameSource` (observed values `user` and `derived`), `kind` and `entrypoint`. A name given explicitly (`--name`, `/rename`) is `user`; the default is `derived` from the conversation. Archive state is **not** in that registry, in `~/.claude.json`, or in a transcript record I could find.
- The CLI's cached feature flags include `tengu_bridge_unarchive_on_resume` and a `teardown_archive_timeout_ms` of 1500 inside the bridge/Remote Control configuration. That points to archive being a **bridge-session action performed at CLI teardown** (and reversed on resume), i.e. server-side state for sessions that Remote Control mirrors to the app. This is an inference from flag names, not a verified mechanism.
- The harness ends a Claude TUI seat with `_terminate_process_group` (SIGTERM, a grace period, then SIGKILL) once the reply is read. I did not find a graceful exit step (an `/exit` or end-of-input and wait) in the matched code; I did not read the whole function.
- The desktop app's remote server for `dev0` runs under a different user account that this account cannot read, so the app's own list and archive store were not inspected.
- No `claude archive` command exists; `claude archive` is parsed as a prompt.

**Hypotheses to test (cheapest first):**
- **H1 — teardown pre-empted.** A bridged TUI seat is killed before the CLI can run its own archive-on-teardown (1500 ms budget), so it is never archived. Fix would be harness-side: after a verified success, send a graceful exit and wait for the CLI to exit on its own before any TERM/KILL. No new API.
- **H2 — not bridged, listed from local state.** The app lists seat sessions from local transcripts or the registry, and only removal clears them. Fix: `claude rm <id>` for `--bg` sessions and a serialized, fail-open `claude purge <path>` for PTY seat state.
- **H3 — app-side state only.** Archive lives only in the app's store with no CLI hook. Then it needs an app feature or API; out of this repo.

**Experiment (needs the owner at the app, on a scratch repo, no real review):** launch one throwaway `claude --safe-mode` seat-style TUI session through the harness's own launch path with a fake reply, then (a) end it by process-group kill, (b) end it with a graceful exit, (c) `claude rm`/`purge` it, and note after each whether the app lists it and whether it is archived. Run once with Remote Control active and once without.

- **Trigger.** "Success" is: for executors, the Agent View success path (state `done`, nonce proof, readable final text) or the codex closeout accepted by the runner; for panel seats, a verified reply (today a parsed terminal verdict, later `extract_reply` success). A failed or non-conforming session stays visible for diagnosis.
- **Mechanisms, now ordered for the Claude Code app target.**
  1. **Graceful exit (H1):** after verified success, end the TUI gracefully and wait before any kill. Smallest change, no new API; edits the seat epilogue in `panel_invoker.py`, so it is gated like A2.
  2. **`claude rm` / `claude purge` (H2):** `claude rm <id>` for Agent View sessions (the adapter's `remove` already exists with no caller), and a serialized, fail-open `claude purge <path>` for PTY seat state after the pool drains. `purge` rewrites the shared `~/.claude.json`, so concurrent purges are a hazard; batch it after the pool drains.
  3. **App-side archive (H3):** needs an app feature or API; recorded, not planned here.
  4. *(T3 / codex-side, no longer in scope):* T3 `settled`/`archived_at`, the codex `~/.codex/archived_sessions` store and `codex exec --ephemeral`. Panel codex seats already use `--ephemeral`.
- **Existing backlog.** 443 `pl-panel` project entries sit in `~/.claude.json` on `dev0` (27 project directories). Cleaning them is a separate, owner-run `claude purge` task; nothing in this plan does it.

## Documentation impact

- `AGENTS.md` — add section — B call sites only: session-naming guidance (`--topic`), landed together with the flag. No existing naming guidance to override.
- `phase-loop-skills/advisor-board/SKILL.md` and its `_overrides/*` — modify — B call sites only: the same `--topic` line.
- `CHANGELOG.md` — modify — `[Unreleased]` entry per plan landed (A1: new parse op and module, no behaviour change).
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — add section — A2 only (deferred; agent-harness#1253 also edits this file).
- `docs/advisor-board-capabilities-card.md` — add section — A2 only: `--reply-format`, failure kinds, non-field attachment.
- `docs/releases/baml-v1-release-checks.md` — check — the new `.baml` file and ops may need a line in the release checklist.
- `specs/phase-plans-v10.md` — **not edited by this plan.** Whether to add a roadmap phase is an owner decision (Open items). If one is added, reference its `EC-<ALIAS>-<N>` goals here instead of the acceptance items below.

## Dependencies & order

1. **A1** first; it is independent of everything in flight.
2. **B helper** (`session_label.py`) can land alongside A1: new file, no overlap.
3. **A2** after agent-harness#1253 and agent-harness#1222 are merged; rebase onto them, keep the diff in `panel_invoker.py` to the declared seam. A2 also needs the A1 modules.
4. **B call sites** after agent-harness#1222 (for `launcher.py`) and agent-harness#1253 (for the Claude command builders).
5. **C** after the owner answers (Open items) and the experiment runs; it may land in a different repo.
6. Check whether agent-harness#851 (diagnostic retention before cleanup) lands first, since it also edits `panel_invoker.py` near the leg epilogue.

## Verification

Run from a worktree. The system Python in this environment has neither `pytest` nor `baml_bridge`, so create a virtualenv first (baseline not run in this planning pass).

```bash
cd phase-loop-runtime
uv venv && uv pip install -e '.[dev]'   # confirm the extra name in pyproject.toml; baml-bridge==0.20.1 is a core dependency

# Plan A1
python -m pytest tests/test_panel_reply_schema.py -q
python -m pytest tests/test_phase_loop_baml_v1_callers.py tests/test_phase_loop_baml_v1_runtime.py \
  tests/test_phase_loop_baml_modular.py tests/test_phase_loop_baml_dependency.py -q

# Unchanged behaviour on the default path (must pass with no edits to these files)
python -m pytest tests/test_advisor_board_golden.py tests/test_broker_command_builders.py \
  tests/test_launchspec_golden.py tests/test_phase_loop_claude_agent_view_adapter.py -q

# Overlap check against in-flight work (re-run before opening a PR)
git fetch origin && git diff --stat origin/main...HEAD -- \
  phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py \
  phase-loop-runtime/src/phase_loop_runtime/cli.py \
  phase-loop-runtime/src/phase_loop_runtime/launcher.py \
  phase-loop-runtime/src/phase_loop_runtime/advisor_board   # A1 must show no changes here
```

1. **Spike first (A1, before writing the corpus):** call the new bridge op on a fenced-JSON string and a prose-plus-JSON string and record exactly what the v1 parser accepts. The earlier docs fetch did not say how the parser treats markdown fences or surrounding prose, and the result decides how much extraction `extract_reply` must do itself.
2. **Edge cases:** a seat that echoes the schema; a reply with two JSON objects; a very large reply (frame-size cap on the worker, 4 MiB); a worker outage returning `worker_fault` and not a verdict.
3. **A2 only:** a golden-style test that an unset `reply_format` leaves argv, prompt bytes, serialized `PanelLegResult` and the per-leg `.verdict.json` payload byte-identical.

## Acceptance criteria

- [ ] `python -m pytest tests/test_panel_reply_schema.py -q` passes, and the falsifier test goes red when the verdict check is mutated out.
- [ ] `extract_reply` returns a typed failure kind (never raises) for every corpus case that is not a valid reply, including a worker fault.
- [ ] `git diff --stat origin/main...HEAD` for Plan A1 shows **no** change to `panel_invoker.py`, `cli.py`, `launcher.py` or `advisor_board/`.
- [ ] `tests/test_advisor_board_golden.py`, `tests/test_broker_command_builders.py` and `tests/test_launchspec_golden.py` pass without edits.
- [ ] `parse_baml_response("EmitPhaseCloseout", ...)` behaviour is unchanged (`tests/test_phase_loop_baml_modular.py` passes unmodified).

## Decided

- **Roadmap home: standalone** (2026-10-06), provided it does not interfere with ongoing work.
- **Archive target: Claude Code's native app session list**, independent of T3 Code (2026-10-06).
- **agent-harness#1114 coordination:** a comment was posted on that issue proposing that its unconditional per-leg fields land first and A2's optional `reply` key follow additively in the same builder. As of 2026-10-06 that issue had no assignee, PR, branch or comment, and a targeted read-only search of the claw worktrees found no change touching those fields. The search sees committed and visible work only; claw's refs were also stale (its main checkout was thousands of commits behind), so re-run it before A2.

## Open items for the maintainer

1. **Archive experiment.** May the Plan C experiment run, and where? It needs someone watching Claude Code's app list while one throwaway seat-style session is ended three ways. H1 (graceful exit) is the cheapest fix and the first thing it tests.
2. **Is Remote Control active for harness-launched seats?** It decides whether the CLI's own archive-on-teardown applies at all (H1) or the sessions are only local files (H2).
3. **Dotfiles copies of AGENTS.md.** The global guidance files live in the dotfiles repo, outside this one; do they get the same `--topic` line?
4. **Codex-launched sessions in the Claude app.** Confirm that the Claude seat sessions in question are the ones the TUI adapter launches for a non-Claude driver, so the label (`--name`) and cleanup (Plan C) land in the right launch path.

## Execution Policy

- execute (A1): effort=medium, reason=new modules and tests with a schema spike; no concurrency or security surface.
- execute (A2, B call sites): effort=high, reason=edits inside sealed, hash-attested launch paths with golden-pinned bytes.
