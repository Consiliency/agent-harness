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
| C | Archive a session only after its output is verified | C1: one call at closeout acceptance (`launcher.py`/`runner.py`); C2: seat epilogue in `panel_invoker.py` | After agent-harness#1222 and agent-harness#1253; C2 also needs the maintainer's OK on hard-killing unverified seats |

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
- **Requisite-data checks (maintainer: the verifier is schema verification with the required data).** Beyond the BAML type parse, `PanelSeatReply` carries cross-field validators so a reply is *verified* only when it holds what its mode requires: review mode needs a verdict; advisory mode forbids one; `summary` is non-blank; every finding has a non-blank title and body; a `DISAGREE` reply carries at least one `blocking` finding and an `AGREE` reply none; length bounds on every string. A reply that parses but fails these is a typed `schema_mismatch`/`verdict_inconsistent` outcome, never verified. Static type checking of the model module (the repo's type checker, if configured) is a CI check on the code, not the runtime verifier.
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
- The label is the Claude Code session name (`--name`, which the registry records as `nameSource: user`). **It must be derived by the runtime from data it already holds, so it works in a client repo with no agent cooperation** (maintainer: if a client-repo install depends on guidance an agent may ignore, the implementation is flawed). Composition: `<repo> · <board purpose or landing tier> · <topic> · <seat_key>`, where `repo` is the git root name of the reviewed repo, and `topic` is, in order: an explicit `--topic`, else the first heading line of the brief or artifact file, else the artifact file name, else omitted. Every part is sanitised and bounded. `--topic` is an optional override (A2/B, `cli.py`, gated), not a requirement.
- **Naming guidance for driving agents (maintainer: override any existing guidance and edit the guidance files).** A search of the repo `AGENTS.md`, `~/.claude/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` and the dotfiles copies found **no existing session-naming guidance**, so there is nothing to override.
  - **It is only an optional hint, because the runtime already derives the label.** Where it goes if added: the shipped skill, not the repo root `AGENTS.md`. The root `AGENTS.md` is, in its own words, guidance for contributors working in this repository, and agent-harness runs mainly in client repos. A client repo receives the harness through `phase-loop install` from `phase-loop-skills/`, so the line belongs in `phase-loop-skills/advisor-board/SKILL.md` and its `_overrides/<harness>` files (then regenerated into the bundles per `docs/phase-loop/skills-canonical-source.md`). It tells the driving agent to pass `--topic` with a few words naming what the board is reviewing. A short note in `docs/TEAM-ONBOARDING.md` is optional.
  - **Root `AGENTS.md`:** edited only if the maintainers want it for dogfooding; not part of this plan.
  - **Owner-fleet global files:** not edited (maintainer decision: nothing that must work in a client repo may depend on them).
  - Land the text with the `--topic` flag, not before, so the guidance never names a flag that does not exist.
- Non-Claude executors have no name flag: label goes in the first line of the prompt **only where the host app titles from it**. The Agent View launch is special: its nonce proof reads the first user turn (`phase-loop-launch-nonce`), so a label must not alter that turn. Codex cannot be titled this way (see Research summary), so codex labelling is part of Plan C's decision, not this plan.
- Pinned by goldens: `tests/data/launchspec_golden/launchspec_golden.json`, `tests/data/launchspec_golden/pre_d1_closeout_prompt.json`, `tests/test_broker_command_builders.py`, `tests/test_phase_loop_claude_agent_view_adapter.py`. All must pass unmodified on the default path; new tests assert the label only when enabled.

### Plan C — archive a session only after its output is verified (measured 2026-10-06; ready to plan in detail)

**Scope (maintainer):** the cluttered surface is **Claude Code's own native app session list**, independent of T3 Code. **Remote Control is set to auto** and is wanted: it lets the maintainer watch running panelists in the app. The problem is what remains after a job is verified complete. **Invariant: never archive a session before the harness has verified that it produced its required output.** T3 "settled", the codex `archived_sessions` store and `codex exec --ephemeral` are out of scope for this goal.

**Measured on dev0 (throwaway sessions, no prompt or one trivial prompt, `--debug-file` logs read for the CLI's own bridge lines; scratch state purged afterwards):**
- A seat-style launch (`--safe-mode`, `--setting-sources ""`, strict empty MCP, no `--remote-control` flag) **creates a Remote Control bridge session on its own** (`[remote-bridge] Created session cse_...`). Remote Control auto does apply to harness-style seats.
- **PTY (interactive) sessions archive themselves at exit.** Ending one with `/exit`, or with SIGTERM to the process group exactly as `_terminate_process_group` does first, or with SIGTERM while a model call was in flight, each logged `[code-session] Archive cse_... status=200` and `[remote-bridge] Torn down (archive=200)`, exiting in about 1 to 1.5 seconds. So an earlier hypothesis (that the harness's kill pre-empts the CLI's archive step) is **false for a normal SIGTERM exit**.
- **Background (`claude --bg`, Agent View) sessions do not archive when they finish.** The probe session reached state `done` with a bridge session created and **no archive** until `claude stop <id>` was issued; `stop` then logged `Archive ... status=200` and kept the conversation, and `claude rm <id>` removed the listing. In the launcher, `adapter.stop` runs only on a launch timeout and nothing stops or removes a session on success (`claude_agent_view.py` has `stop` and `remove`; `remove` has no caller). This is the most likely source of the post-completion clutter.
- **Not tested:** SIGKILL (expected: no teardown, no archive), the jailed route (seat token and per-seat config directory; the archive call could fail there), the brokered route's scrubbed environment, and a stalled seat that needs the 5-second grace to expire. A PTY seat that does not exit within the grace is killed and would stay in the app.

**Verifier (maintainer decision):** *output schema verification with the requisite data*. For a PTY panel seat that is A1/A2's `extract_reply` succeeding with the requisite-data checks above (until A2 lands, today's conforming terminal verdict). For a background (executor) session it is the existing closeout verification: the BAML `parse_closeout` path plus the `PhaseLoopCloseoutV1` validators (for example, a completed closeout must list produced gates), accepted by the runner.

**Design (two routes, one rule: verify first, then end the session in the way that archives it):**
- **C1 — background (executor) sessions.** After the runner has accepted the closeout (the maintainer's "requisite output", not merely `state=done`), call the adapter's `stop` for the recorded session id. `stop` keeps the conversation and triggers the CLI's own archive; do **not** use `remove`, which deletes the listing and its conversation. Failed or unverified sessions are left alone and stay visible. The session id is already recorded as an evidence ref (`claude stop <id>`), so no new data is needed. Likely files: `launcher.py` or `runner.py` (one call at the acceptance point) and `claude_agent_view.py` (existing `stop`); `launcher.py` is touched by agent-harness#1222, so this is gated.
- **C2 — PTY panel seats.** Today the seat is ended with SIGTERM right after its output is read, which archives it **before** the later verdict check, even if the reply is non-conforming. To honour the invariant, check the seat output **inside** `_run_claude_tui_session` while the process is still alive, using the same local conformity test the leg already uses (a parsed terminal verdict now; `extract_reply` after A2), and then choose the exit: verified, SIGTERM or `/exit` (the CLI archives); not verified, a hard kill so no teardown runs and the session stays in the app for diagnosis. The maintainer agreed (2026-10-06): unverified seats stay visible for debugging observability. This includes stalled seats, which already end by hard kill. The seat epilogue is in `panel_invoker.py`, so it is gated like A2.
- A failed first attempt followed by a verified retry leaves the first attempt visible; it was never verified. Archiving it is a separate decision.
- **Concurrency:** none of this touches the shared `~/.claude.json` from the harness; the CLI itself does the archiving, so there is no purge race. `claude purge` is not needed for this goal.

**Verification for C (after the gates clear):** a fake-CLI unit test that `stop` is called exactly once and only after acceptance; a test that a rejected closeout never calls it; a test that a non-conforming PTY reply takes the hard-kill exit and a conforming one the graceful exit; plus one manual run on a scratch repo that reads the CLI debug log for the archive line. No live board in tests.

- **Existing backlog.** 443 `pl-panel` project entries sit in `~/.claude.json` on `dev0` (27 project directories), and the Agent View list holds finished background sessions. Cleaning them is a separate, owner-run task (`claude stop`/`claude rm` per session, `claude purge` per path); nothing in this plan does it.

## Related work (separate bounded plans; recorded here, not planned in detail)

**Plan D — deterministic model selection and fallback (maintainer, 2026-10-06).** Stated problem: model choice and fallback must not rest on skill markdown hints, because after a harness upgrade the agent keeps following the pattern already in its context. Already tracked: agent-harness#1171 (job-slot tiers, config roster, promotion records, recorded fallback; plan 1 merged as agent-harness#1173, plan 2 is the draft agent-harness#1199), agent-harness#648 (layered resolution with provenance), agent-harness#1078 (lane fallback), agent-harness#1217 and agent-harness#1182 (seat override). Gaps that those do not state, observed on current `main`: (1) the shipped skills carry about 20 model-id literals across seven files (`advisor-board`, `plan-phase`, `execute-phase` and their overrides), which is exactly the stale-hint path; (2) `advisor-board` has no `--model-profile`-style input, while `phase-loop run` does; (3) nothing tells a long-lived driving agent that the roster changed under it. Candidate mechanisms for the owning plan: skills pass a **role** (`review`, `plan`) and never a model id, with a lint failing any model literal in `phase-loop-skills/`; the runtime resolves role to model and fallback from config in code, records the winning layer, and emits a roster epoch in every result so a stale caller is detectable; an explicit model id that is not in the registry is refused with a typed error naming the current choice instead of being passed through. Needs a decision on amendment versus separate plan (Open items 1).

**Plan E — large-bundle stalls on the Claude TUI seat.** Stated cause: no sandbox for the TUI adapter, so it chokes on large bundles with long time to first token. Consistent with the code: the plain brokered Claude seat has `--tools ""` and must receive the whole sealed prompt through the PTY, while the jailed route (agent-harness#1132) can read pointer files with a small prompt. The jailed route is **inert on a host with no recorded qualification pass for the current jail digest**: dev0 has no `seat-jail-passes` directory; claw has one pass recorded 2026-09-30, which may predate the current digest (not checked). **Qualification attempted on dev0 on 2026-10-06 (maintainer approved) and did not pass.** The installed runtime (0.7.23, released before the jail merge) has no `seat-sandbox` command, so it was run from current `main` source with Python 3.14.4. It failed with `setpriv: setresuid failed: Operation not permitted` on this host's newer stack (Ubuntu 26.04, bubblewrap 0.11.1, util-linux 2.41.3, kernel 7.0), although a hand-built user namespace with the same `setpriv` arguments works; claw (Ubuntu 22.04, bubblewrap 0.6.1) has a recorded pass. A second finding: the jail code needs `fcntl.F_ADD_SEALS`, which only exists on Python 3.14, so a client install on 3.10 to 3.13 cannot qualify. Both are filed as agent-harness#1276. The first step is therefore a fix in agent-harness#1276, then qualification per host. Also relevant: agent-harness#734 (in-flight wait versus turn extinction), the `context_refs` by-reference input (agent-harness#114) and the existing stall-threshold scaling with input size.

## Documentation impact

- `phase-loop-skills/advisor-board/SKILL.md` and its `_overrides/*` — modify — B call sites only: the `--topic` line, landed with the flag; regenerate the installed bundles through the repo's canonical-source tooling. No existing naming guidance to override.
- `docs/TEAM-ONBOARDING.md` — optional one-line note — same landing.
- Root `AGENTS.md` — **not edited** (contributor guidance; client repos do not receive it).
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
- **Archive target: Claude Code's native app session list**, independent of T3 Code; **Remote Control stays on auto** (it gives live visibility of running panelists); **no archive before the harness verifies the required output** (2026-10-06).
- **Verification and failure visibility (2026-10-06):** the verifier is schema verification with the requisite data (BAML parse plus typed, cross-field validation); seats that fail it, including stalled seats, stay visible in the app for debugging observability (hard-kill exit).
- **Guidance is never load-bearing:** naming is derived by the runtime; skill and AGENTS.md hints are optional extras, and the owner-fleet dotfiles copies are not edited.
- **Filed 2026-10-06:** agent-harness#1275 (deterministic model selection, linked from agent-harness#1171; separate so it does not disturb plan 2, agent-harness#1199) and agent-harness#1276 (seat jail qualification fails on Python 3.13 and below and on the Ubuntu 26.04 stack).
- **agent-harness#1114 coordination:** a comment was posted on that issue proposing that its unconditional per-leg fields land first and A2's optional `reply` key follow additively in the same builder. As of 2026-10-06 that issue had no assignee, PR, branch or comment, and a targeted read-only search of the claw worktrees found no change touching those fields. The search sees committed and visible work only; claw's refs were also stale (its main checkout was thousands of commits behind), so re-run it before A2.

## Open items for the maintainer

1. **Plan D is filed as agent-harness#1275** (decision delegated to this planner: separate issue, cross-linked from agent-harness#1171). Say if you would rather it be folded into plan 3 or 4 of that chain.
2. **Plan E (large-bundle stalls) is blocked on agent-harness#1276.** The maintainer approved qualifying the jail; on dev0 it fails until that issue is fixed. Who takes it, and is a stopgap needed for the stalls meanwhile (for example `context_refs` by reference for large bundles)?
3. **Which launches fill the app list.** Confirmed as a mix of completed and stalled. Completed background sessions are covered by C1; stalled seats are killed and stay visible by design (C2), which is what you asked for, so the remaining clutter from stalls is addressed by Plan E, not by archiving.

## Execution Policy

- execute (A1): effort=medium, reason=new modules and tests with a schema spike; no concurrency or security surface.
- execute (A2, B call sites): effort=high, reason=edits inside sealed, hash-attested launch paths with golden-pinned bytes.
