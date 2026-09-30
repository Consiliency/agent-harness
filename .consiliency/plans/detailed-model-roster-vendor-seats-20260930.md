# Detailed plan: vendor-named seats, seat eligibility and model-honest native fill (plan 2 of 5, agent-harness#1171)

## Task
This is plan 2 of agent-harness#1171. Plan 1 (`.consiliency/plans/detailed-model-roster-job-slots-20260929.md`, merged as agent-harness#1173) scoped it under "Follow-on plans: Plan 2". This plan does not repeat plan 1's decisions; it cites them by number, as "P1-D<n>".

It also takes on the president condition that agent-harness#1178 assigned to plan 2 (see the 2026-09-30 comment on agent-harness#1171). That condition has two parts:
- **`fable` tier fungibility.** Decide which Claude tiers may stand in for `fable`, and encode the answer in the policy match.
- **Native fill.** A native fill runs the requested model or refuses. It never silently substitutes the driving session's model.

The work is too large for one bounded plan, so plan 2 is split in two:
- **Plan 2a (this document, in full).** Vendor seat names as accepted aliases, a per-seat eligibility floor enforced in the policy match and the president rung match, and model-honest native fill. It has no dependency on the roster code or on PANEL SL-1, so it can land first.
- **Plan 2b (scoped below).** Board model pins derived from the roster, and the config route into the production composition entry points. It depends on plan 1 Part A/B being implemented and on PANEL SL-1.

Goal IDs referenced: EC-PRESROUTE-2, EC-PRESROUTE-3, EC-PRESROUTE-4, EC-PRESROUTE-5.

## Research summary
Pinned inputs are origin/main `60585b97` and agent-harness#1178 (merged as `d5774a93`). No SHA of this plan's own output is pinned.

**How seats are matched to names today.** All of it happens through alias values in `panel_invoker.py`:
- `review_policy_for_tier` (around l.491) requires `("fable","sol","gemini","grok")`.
- `DEFAULT_REVIEW_SEAT_ALIASES` (around l.501-520) maps model ids to seat names. `claude-sonnet-5-5` maps to `fable`, which agent-harness#1178 added.
- `_validate_review_board_policy` (around l.554-573) compares `Counter(aliases.get(seat.model, seat.model))` against `required_seats`, after merging the caller's `seat_aliases` over the defaults.
- `validate_president_ladder` (around l.597-616) accepts alias keys or values, and deduplicates on the canonical alias.
- `president_adapter.seat_for_rung` (around l.99-111) returns the first seat whose model id or alias equals the rung.
- `president_operation` (around l.104 and l.146-155) indexes the ladder by `ruling.model`, which is the rung string.

The consequence is that, today, a standard-tier Sonnet satisfies a governed `fable` seat and fills the `fable` president rung.

**Native fill is honest about nothing.** Specifically:
- `PresidentInvoke._native_fill` (around l.193-205) defers with `{status, rung, brief_digest, findings_digest}` and no model.
- The only production resume is `cli.py` around l.2296 (`--native-president FILL.json`), which leads to `invoke_board(native_president_fill=...)` and then `_resume_native_president` (around l.992). That path checks the rung and the digests only.
- The ruling record's `model_id` is `seat.model`, so the record claims the requested model, while the model that actually ran was the driving session's.
- Review-seat fills go through `native_fill_request_payload` (around l.7093, which writes `model: seat.model`), then `load_native_leg_fill(s)` (around l.7144/7171) and `preflight_native_leg_fills`/`apply_native_leg_fills`. These compare the fill with the *request* model, never with what actually ran.
- The runtime cannot observe the session model: `_under_claude_code` checks only `CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT`, and `launcher.py`/`profiles.py` already record `session_model_unbound`. So the only enforceable guarantee is a **declared** model, checked against the request and recorded.

**Frozen constraints** (HARDEN_TEST_PATHS, the content-tdd receipts and the govlean frozen support, swept at `60585b97`):
- PRESROUTE `tests/test_president_wiring.py::test_brief_binding_rejects_changed_brief_at_resume_and_accepts_control` passes `invoke_board` a fill `{brief_digest, findings_digest, rung, text}` with **no** declared model, and expects it to be ACCEPTED with `CLAUDECODE=1` on the `fable` rung.
- `::test_native_fable_rung_filled_under_claude_code_without_second_tui` asserts the deferred response key by key (status and digests), never by dict equality. A grep for `== {` on the pending, response or request objects found none. An additive `model` key is therefore safe.
- The plan-1 alias-first node list is still binding: EC-PRESROUTE-3 order, `required_seats`, `'sol': 2`, the loader returning its input verbatim, and the `test_panel_lanes.py` label and profile echoes.

**The seat-launch and sandbox area is off-limits.** It belongs to a private hardening effort (agent-harness#1132 and agent-harness#1166). It covers:
- `seat_jail.py`, `seat_keyring_exec.py`, `seat_uid.py`, `sandbox_egress.py` and `advisor_board/backing.py`;
- in `panel_invoker`: `_provider_launch_prefix`, `_compose_launch_prefix`, `launch_provider`/`run_provider`, `_brokered_*_command`, `_broker_*`, `_exec_claude_tui_leg`, `_run_claude_tui_session`, `_default_spawn` and `_require_seat_identity`;
- in `president_adapter`: `_launch*` and `_transport`;
- the `cli.py` notices and reap sites.

Plan 2a edits none of these.

## Design decisions (binding)
1. **Vendor seat names are accepted aliases.** Add `VENDOR_SEAT_NAMES = {"anthropic": "fable", "openai": "sol", "google": "gemini", "xai": "grok"}` next to `DEFAULT_REVIEW_SEAT_ALIASES`, plus `canonical_seat_name(name) -> str`, which maps a vendor name or an old name to the old name and passes an unknown name through unchanged.
   - Vendor names are accepted wherever a seat or rung name is accepted: `ReviewLandingPolicy.required_seats` (a caller-built policy), `validate_president_ladder` (its `known` set and dedupe), `seat_for_rung`, and `_resume_native_president`'s `rung in ladder` check (compared canonically).
   - **Canonical outputs keep the old names** during the plan-5 window. That covers `PRESIDENT_LADDER`, `review_policy_for_tier().required_seats`, the values of `DEFAULT_REVIEW_SEAT_ALIASES` and the persisted binding.
   - `load_president_ladder` still returns its input verbatim (frozen `test_ec1_existing_loaders_tolerate_a_sibling_panel_table`).
   - `ruling.model` stays the rung string *as configured*, so `ladder.index(ruling.model)` at both `president_operation` sites stays consistent with the ladder. A vendor-spelled ladder therefore works with no `.index()` change. This is backed by a test rather than a normalization edit.
   - The **lens** stays on `Seat.lens`, which already exists. The seat identity reported in *new* additive fields is `(vendor, lens)`, via `seat_vendor(seat_name)`. No existing field changes shape.
2. **`fable` fungibility is frontier only, enforced as a per-seat floor.**
   - `advisor_board/registries.py` gains `MODEL_SLOT_CLASS`, which maps each **registered** model id to its job slot (P1-D1 vocabulary):

     | slot | model ids |
     |---|---|
     | frontier | `claude-opus-5-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-fable-5-1`, `claude-fable-5`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6.1-sol`, `gpt-5.6-sol`, `Gemini 3.1 Pro`, `grok-4.7`, `grok-4.6`, `grok-4.5` |
     | standard | `claude-sonnet-5`, `claude-sonnet-5-5`, `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash` |
     | fast | `claude-haiku-4-5-20251001` |

   - This is an explicit registration table, like `_MODEL_DEFS`. It is not a roster. After plan 1 Part A lands, a test asserts that every roster slot list is consistent with it.
   - `SEAT_MIN_SLOT = {"fable": "frontier", "sol": "frontier", "grok": "frontier", "gemini": "standard"}`. The gemini floor is `standard` because the shipped gemini seat is the google **standard** model (`gemini-3.8-flash`, per P1-D7). Every shipped seat therefore meets its floor.
   - `seat_eligible(seat_name, model_id) -> (bool, reason)` returns true when `MODEL_SLOT_CLASS[model_id]` is at or above the floor for the canonical seat name. The order is `frontier > standard > fast`. A model not in the table is **not** eligible for a floored seat.
   - **The floor applies to every match on a governed tier, whatever alias produced it (hb1 F1/F001).**
     - Governed means any policy other than `("grounded",)`: PLAN, PRODUCTION_CODE, and any caller-built policy naming floored seats.
     - Every seat counted under a floored seat name must pass `seat_eligible`. This holds whether the name came from `DEFAULT_REVIEW_SEAT_ALIASES`, from a caller `seat_aliases` entry (including one byte-identical to a default entry, such as `{"claude-sonnet-5-5": "fable"}`), from a vendor name, or from the model id itself.
     - A seat that fails raises `PresidentPolicyError("review_seat_below_floor", …)`, naming the seat name, model, slot and alias source. That code is new, and it is distinct from `review_board_policy_mismatch`.
     - The existing Counter check runs **first** and is unchanged, so frozen `test_gpt_6_sol_cannot_fill_a_governed_grok_seat` still fails on `'sol': 2`.
   - Result: `claude-sonnet-5-5` keeps its `fable` alias (agent-harness#1178's registration test stays green). It can sit on a non-governed or user board, but on a governed tier it **cannot** satisfy the `fable` seat or fill any floored president rung, by any alias route.
   - **Caller-supplied `seat_aliases` are explicit operator substitutions.** On a governed tier they are honoured only when the model **meets the seat's floor**. Such a substitution, for example `gpt-6.1-sol` mapped to `grok`, is allowed and recorded as `{"seat_name", "model", "slot", "vendor", "seat_vendor", "cross_vendor", "via": "caller_alias"}`. On a non-governed tier caller aliases behave as today, and are also recorded.
   - **Consequence, stated plainly.** Once plan 2a is implemented, the fleet's operational board tool can no longer count a Sonnet stand-in as a governed `fable` or `grok` seat. That covers `CLAUDE_SEAT_MODEL=claude-sonnet-5-5`, and "sonnet fills grok until 2026-10-02". A governed board seating one is refused with `review_seat_below_floor`. This is intended: the maintainer calls manual substitution a stopgap, which automatic fallback replaces.
   - **Where substitutions are durably visible (hb1 grok 3).**
     - `PanelResult` gains an additive field, `seat_substitutions: tuple[Mapping[str, object], ...] = ()`. `PanelResult` has no `labels` field; that was an error in r1.
     - On a governed tier with a `stream_dir`, `invoke_board` writes **`board.policy.json`** atomically, right after `_validate_review_board_policy` succeeds and before any seat runs. Its schema is `board.policy.v1`, with these keys:
       - `landing_tier` and `required_seats`;
       - `seats`: a list of `{seat_key, model, seat_name, vendor, slot, eligible, via}`, where `via` is one of `default_alias`, `caller_alias`, `vendor_name` or `model_id`;
       - `seat_substitutions`.
     - The president binding (`president.pending.json`, around l.900-920) gains the same `seat_substitutions` list as an additive key. It is written by defer and compared by resume symmetrically, so a resume under a different substitution set is refused like any other binding change.
     - Governed callers already pass `stream_dir` (`governed_review`, `train_runner`). Without a `stream_dir`, the record exists only on `PanelResult`, and CONTRACTS.md says so.
   - **Manual substitutions are a stopgap, and plan 4 retires them** (maintainer decision on agent-harness#1199, 2026-09-30).
     - **Retirement condition:** automatic fallback runs in **every production composition entry point** (`cli.py` advisor-board, `governed_review`, `train_runner`). The harness itself picks the next available model or vendor, and records what it picked:
       - PANEL fallback lanes choose the vendor (agent-harness#1078);
       - plan 4's ordered model walk, with plan 3's expiry records, chooses the model within a vendor.
     - **What plan 4 does when that holds:** in governed tiers it removes the remaining floor-meeting caller substitutions (including cross-vendor ones). Plan 2a already refuses below-floor substitutions. From then on, `seat_substitutions` logs only automatic fallbacks.
     - **Until then:** plan 3's expiring substitution records are the interim, time-boxed form. Plan 3 **adds expiry**, and plan 4 **retires** the manual route; both plans list this in their scope.
3. **The president rung obeys the same floor.**
   - New `rung_seat(board, rung, *, seat_aliases) -> tuple[Seat | None, str | None]` returns the seat and, when there is no eligible seat, a reason: `rung_unseated` or `rung_below_floor`.
   - `seat_for_rung` keeps its signature and returns only an eligible seat, or `None`.
   - The floor applies on **every** rung, whatever alias produced the match: caller alias, default alias, vendor name, or the model id itself (hb1 F1).
   - A rung spelled as a model id, for example `"claude-sonnet-5-5"`, which `validate_president_ladder` accepts, takes the floor of its canonical seat name, so `claude-sonnet-5-5` falls under `fable` and frontier. It is `rung_below_floor` on a board seating it (hb1 F7).
   - `president_adapter._monitor` (around l.279) indexes the ladder for monitor-file naming. It compares rungs canonically, so a vendor-spelled ladder does not collapse to `rung-0.json`.
   - `PresidentInvoke` reports `rung_below_floor` through the existing typed-unavailable path (`president_unavailable`), so the ladder descends. The detail is recorded; it is never a silent skip.
4. **Native fill is model-honest.**
   - **Requests carry the requested model.** Additive keys:
     - president: `_native_fill` adds `"model": seat.model` to the deferred response, the persisted pending request and `PanelResult.needs_native_president`;
     - review seats: `native_fill_request_payload` already carries `model`.
   - **Fills declare what ran.** A fill must carry `ran_model` (the exact model id the filler ran). The runtime compares it with the request's `model`:
     - equal: accepted, and `ran_model` is recorded durably. For review seats it goes in the leg record's fill provenance (`attach_native_fill_provenance`). For the president it goes in a **`president.fill.json`** sidecar (hb1 F2):
       - the sidecar is written by `_resume_native_president` atomically next to `president.ruling.json`, as the step immediately before it, so either both files exist or neither does;
       - its schema is `president.fill.v1`, with keys `{rung, requested_model, ran_model, model_declared, brief_digest, findings_digest}`;
       - `_resume_native_president` builds no `PresidentInvoke` and has no attempt log, so r1's "PresidentAttempt record" wording does not apply on the resume path;
       - the frozen `president.ruling.v1` shape is unchanged (see `president_operation.py` in Changes), and the frozen test asserts only that ruling file's contents and that it is absent on refusal. The sidecar does not conflict with either assertion.
     - different: refused, with `PRESIDENT_FILL_MODEL_MISMATCH` (president; nothing persisted, like the digest refusal in EC-PRESROUTE-5) or `NATIVE_FILL_MODEL_MISMATCH` (a `NativeFillRefusal` code for review seats);
     - absent, at the **production loaders**: refused, with `PRESIDENT_FILL_MODEL_UNDECLARED` or `NATIVE_FILL_MODEL_UNDECLARED`.
   - **Where the enforcement point is.**
     - President: the only production president resume is `cli.py` `--native-president` (around l.2296). It goes through a new `load_declared_president_fill(path, *, pending)`, which requires `ran_model`.
     - Review seats: `load_native_leg_fill` requires `ran_model` in the fill directory's `fill.json` (new, next to the emitted `request.json`). `preflight_native_leg_fills` compares it.
     - **The library seam `invoke_board(native_president_fill=…)` still accepts a fill without `ran_model`.** The frozen PRESROUTE positive control does exactly that. The accepted result is marked `model_declared: false, ran_model: null` in `president.fill.json` and on `PanelResult`, so it is disclosed durably, never silent.
     - **The leg library seam behaves the same way (hb1 F6).**
       - `NativeLegFill` gains `ran_model: str | None = None`.
       - `preflight_native_leg_fills` refuses a present-but-different `ran_model` (`NATIVE_FILL_MODEL_MISMATCH`), always.
       - A `None` from a directly constructed fill is accepted and recorded `model_declared: false` in the leg's fill provenance.
       - Only the loader (`load_native_leg_fill`) refuses an undeclared fill.
     - **The production-path test (hb1 F6, grok 4).** It proves the invariant at the **construction** sites rather than scanning keyword names:
       - (a) inside `src/`, `NativeLegFill(` is constructed only in `load_native_leg_fill`;
       - (b) the only `src/` function that reads a president fill file is `load_declared_president_fill`, and `cli.py` is the only `native_president_fill=` caller that supplies one from a file;
       - (c) the pass-through sites only **forward** a parameter they received and construct nothing. At `60585b97` these are `governed_review.py` around l.741, `train_runner.py` around l.2391 and l.3602, and `legible_evidence.py` around l.745. This is checked by asserting each forwards its own parameter name unchanged;
       - (d) the file-reading roots are `cli.py` around l.2229 and l.4727 (legs) and around l.2296 (president), and every one of them calls a declaring loader.
   - **The filler's duty.** The fill instructions (the CLI message around l.2357, the native-fill request payload's instruction text and the skills) tell the driving session two things:
     - run the review in a sub-agent **launched with the requested model**, and declare that id;
     - if the host cannot launch that exact model, **do not fill**. Let the rung or seat stay unavailable (the ladder then descends).
   - The runtime cannot verify the declaration, because the session model is unobservable (see the research summary). This is stated in CONTRACTS.md as the trust boundary.
5. **Out of scope.**
   - Seat launch and sandbox (agent-harness#1132/#1166). If a later step needs launch-time model enforcement, such as passing `--model` to a native sub-agent spawn, that is a dependency on that effort, filed there.
   - Board pins and the config route (plan 2b).
   - Expiring substitution records and promotion (plan 3). Plan 3 adds expiry to manual substitutions but does not retire them.
   - Fallback walks, and the retirement of manual caller substitutions once automatic fallback runs in every production entry point (plan 4; see decision 2).
   - Flipping canonical outputs to vendor names (plan 5).

## Changes (plan 2a)

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py` (modify)
- `MODEL_SLOT_CLASS` — add — decision 2 table. It covers every `_MODEL_DEFS` id exactly: a test enforces set equality. The file is on the guard allowlist.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `VENDOR_SEAT_NAMES`, `canonical_seat_name`, `seat_vendor`, `SEAT_MIN_SLOT`, `seat_eligible` — add — decisions 1 and 2.
- `_validate_review_board_policy` (around l.554) — modify:
  - canonicalize `required_seats`;
  - on a governed tier, enforce `seat_eligible` for **every** match onto a floored seat, whatever the alias source, raising `review_seat_below_floor` after the unchanged Counter check;
  - return the per-seat eligibility rows and `seat_substitutions` (floor-meeting caller-alias matches).
- `invoke_board` (around l.10057) — modify — write `board.policy.json` atomically after validation when governed and `stream_dir` is set, set `PanelResult.seat_substitutions`, and pass the substitutions into the president binding.
- `PanelResult` (around l.1620) — modify — add the additive field `seat_substitutions`.
- `validate_president_ladder` (around l.597) — modify — accept vendor names; deduplicate on `canonical_seat_name(DEFAULT_REVIEW_SEAT_ALIASES.get(r, r))`.
- `_resume_native_president` (around l.992) — modify:
  - compare `rung` against the ladder canonically;
  - check `ran_model` against the pending `model`, raising `PRESIDENT_FILL_MODEL_MISMATCH` (nothing persisted);
  - write `president.fill.json` (`president.fill.v1`) atomically, as the step immediately before `president.ruling.json`.
- The pending-request persistence and `needs_native_president` (around l.821-915) — modify — carry `model` as an additive key.
- `load_native_leg_fill(s)` (around l.7144/7171), `preflight_native_leg_fills` (around l.7189), `attach_native_fill_provenance` (around l.7227) — modify — require, compare and record `ran_model`, using the new `NativeFillRefusal` codes `NATIVE_FILL_MODEL_MISMATCH`/`NATIVE_FILL_MODEL_UNDECLARED`.
- `native_fill_request_payload` (around l.7093) — modify — add a **separate additive key** `fill_duty` naming the requested model and the duty to refuse. The digest-bound `instructions` text, and therefore `brief_sha256`, is **unchanged** (hb1 F4).
- `load_declared_president_fill` — add — the production president-fill loader (decision 4).

### `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py` (modify)
- `rung_seat` — add. `seat_for_rung` — modify — accept vendor names and return only an eligible seat (decisions 1 and 3).
- `PresidentInvoke.__call__` — modify — report `rung_below_floor` through the typed-unavailable path.
- `PresidentInvoke._native_fill` — modify — add `model` to the deferred response.

### `phase-loop-runtime/src/phase_loop_runtime/president_operation.py` (modify)
- `board_president_ruling_record` (around l.146) — modify — use `rung_seat` only. The `president.ruling.v1` record gets **no new keys**: frozen PRESROUTE `test_ruling_record_matches_frozen_contract` (test_president_wiring.py around l.877-883) asserts that the record's keys and types *equal* `data/president_ruling_v1.golden.json`. `ran_model`/`model_declared` are recorded in the `PresidentAttempt` record and in `PanelResult` provenance instead. Adding them to the ruling record would need a v2 record schema, which is out of scope.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify; president-fill loader only, around l.2296 and l.2348-2357)
- `--native-president` — modify — read through `load_declared_president_fill`, and print the requested `model` and the `ran_model` duty in the deferral message. The #1132-owned notice and reap sites are untouched.

### Tests (create or modify; none frozen)
- `tests/test_seat_vendor_names.py` — create:
  - vendor names are accepted in the policy, the ladder and `seat_for_rung`;
  - a vendor-spelled ladder `["anthropic","openai","xai","google"]` resolves and indexes (the `president_operation` `.index` consistency);
  - canonical outputs are unchanged;
  - `load_president_ladder` returns its input verbatim.
- `tests/test_seat_eligibility_floor.py` — create:
  - `MODEL_SLOT_CLASS` covers `_MODEL_DEFS` exactly;
  - a governed PRODUCTION_CODE board seating `claude-sonnet-5-5` for `fable` raises `review_seat_below_floor`;
  - the same board with `claude-opus-5-5`, `claude-fable-5-1` or `gpt-6.1-sol` (for `sol`) passes, which also closes the agent-harness#1172 president item 2;
  - a ladder whose `fable` seat is Sonnet descends with `rung_below_floor` recorded;
  - **`test_caller_alias_cannot_bypass_governed_fable_floor`** (codex F001's falsifier): a PRODUCTION_CODE board seating `claude-sonnet-5-5` with `seat_aliases={"claude-sonnet-5-5": "fable"}` raises `review_seat_below_floor`, and `seat_for_rung(board, "fable", seat_aliases=…)` is `None`;
  - **`test_caller_alias_cannot_seat_sonnet_on_a_governed_grok_seat`**: `{"claude-sonnet-5": "grok"}` on a governed tier is refused. This covers the stated fleet-tool consequence;
  - **`test_floor_meeting_caller_substitution_is_recorded`**: `{"gpt-6.1-sol": "grok"}` passes and appears in `PanelResult.seat_substitutions` **and** in `board.policy.json` read back from `stream_dir` with `cross_vendor: true`;
  - **`test_model_id_rung_takes_its_canonical_floor`**: a ladder `["claude-sonnet-5-5", "sol", "grok", "gemini"]` over a board seating Sonnet reports `rung_below_floor` for rung 0;
  - a vendor-spelled ladder names the monitor files by canonical index;
  - **named mutation 1:** making `seat_eligible` always return `(True, None)` lets Sonnet satisfy `fable` through the caller alias, and the test must fail. **Named mutation 1b:** restricting the check to default-alias matches, which was r1's rule, must also fail it.
- `tests/test_native_fill_declared_model.py` — create:
  - president: the deferral carries `model`; a CLI fill with a matching `ran_model` is accepted and recorded; a mismatch is refused with nothing persisted; a missing `ran_model` through the CLI is refused; the library seam without `ran_model` is accepted **and** marked `model_declared: false`;
  - review seats: the same three cases through `load_native_leg_fill`;
  - the president sidecar: an accepted CLI fill writes `president.fill.json` with `ran_model`, a library-seam fill without one writes `model_declared: false, ran_model: null`, and a refused fill writes neither the sidecar nor the ruling;
  - `fill_duty` is present, and `brief_sha256` over `instructions` equals main's value for the same request;
  - the construction-site checks (a)–(d) from decision 4;
  - **named mutation:** skipping the `ran_model` comparison accepts a mismatched fill, and the test must fail.
- `tests/test_native_claude_seat_fill.py`, `tests/test_native_claude_seat_fill_green.py`, `tests/test_native_fill_refusal_cause.py`, `tests/test_presroute_cli.py`, `tests/test_advisor_board_advisory_cli_802.py` (the `load_native_leg_fills` calls around l.613 and l.835, and the `--native-leg` runs around l.444-452), `tests/test_train_review_packet.py` (the `--native-leg` continuation around l.2020-2029) — modify — their fill fixtures gain `ran_model`. None of these is frozen: checked against the 42-path set at `60585b97` (hb1 F5).

### Skills (modify, byte-parallel pairs; bundle regenerated)
- `phase-loop-skills/advisor-board/_overrides/claude/SKILL.md` and `skills-src/claude/claude-advisor-board/SKILL.md`, the native-leg and native-president sections: launch the fill sub-agent with the requested model, write `ran_model`, and refuse when that model can't be launched.
- `phase-loop-skills/run-train/**/SKILL.md` and `skills-src/*/*-run-train/SKILL.md`: the same instruction wherever they describe `--native-leg` fills.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify:
  - vendor seat names (aliases, canonical outputs unchanged);
  - `SEAT_MIN_SLOT` and `review_seat_below_floor`;
  - `seat_substitutions`, and the governed record files `board.policy.json` (`board.policy.v1`) and `president.fill.json` (`president.fill.v1`);
  - the native-fill `ran_model` contract and the trust boundary (a declared model, since the session model is unobservable).
- `docs/advisor-board-capabilities-card.md` — modify — the Models table gains a slot class column, and there is a note that a Sonnet id cannot fill a governed `fable` seat.
- `CHANGELOG.md` — add — vendor seat names, the eligibility floor (a behaviour change: on a governed tier a below-floor model is refused **whatever alias maps it**, so Sonnet stand-ins no longer count as governed `fable`/`grok` seats or president rungs), and declared-model native fills (a behaviour change: `--native-president`/`--native-leg` fills need `ran_model`).

## Dependencies & order
1. **Order inside plan 2a:** `registries.MODEL_SLOT_CLASS`, then the `panel_invoker` helpers, then the policy match and ladder, then `president_adapter` and `president_operation`, then native fill (`panel_invoker`, then `cli.py`), then tests, then skills and bundle, then docs.
2. **External dependencies:** none are blocking.
   - Plan 2a does not need `model_roster.py` or PANEL SL-1.
   - **Coordination:** the fleet's operational board tool passes caller `seat_aliases` for its substitutions, and those stay honoured (decision 2). A native president or leg fill through the CLI after 2a lands needs `ran_model`, so the fill instructions the fleet uses must be updated when 2a lands.
3. **Plan 2b depends on** plan 1 Part A being implemented (`model_roster.py`), plan 1 Part B (call-time roster, for the config route), PANEL SL-1 (agent-harness#1078, which owns composition order and `[panel.<task>]` tables) and plan 2a.

## Verification
From `phase-loop-runtime/`:
```bash
PYTHONPATH=src python3 -m pytest -q tests/test_seat_vendor_names.py tests/test_seat_eligibility_floor.py tests/test_native_fill_declared_model.py tests/test_advisor_board_registries.py tests/test_native_claude_seat_fill.py tests/test_native_claude_seat_fill_green.py tests/test_native_fill_refusal_cause.py tests/test_presroute_cli.py tests/test_advisor_board_advisory_cli_802.py tests/test_train_review_packet.py tests/test_train_review_monitoring_policy.py tests/test_review_monitor_policy.py tests/test_president_ladder_config.py tests/test_skills_canon_parity.py
PYTHONPATH=src python3 scripts/check_model_id_sources.py
# frozen HARDEN + PRESROUTE + PANEL + govlean nodes pass, and every frozen file is byte-identical to origin/main:
python3 - <<'EOF'
import glob, json, subprocess, sys
sys.path.insert(0, 'tests')
from harden_tdd_guard import HARDEN_TEST_PATHS
from govlean_freeze_receipt import DEFAULT_FROZEN_SUPPORT_PATHS
paths = set(HARDEN_TEST_PATHS) | set(DEFAULT_FROZEN_SUPPORT_PATHS)
for f in glob.glob('../.phase-loop/evidence/*/content-tdd-receipt.json'):
    paths |= {t['path'] if isinstance(t, dict) else t for t in json.load(open(f)).get('test_files', [])}
out = subprocess.run(['git', '-C', '..', 'diff', '--name-only', 'origin/main', '--', *sorted(paths)], capture_output=True, text=True).stdout
assert not out.strip(), out; print(len(paths), 'frozen paths unchanged')
EOF
PYTHONPATH=src python3 -m pytest -q $(python3 -c "import sys;sys.path.insert(0,'tests');from harden_tdd_guard import HARDEN_TEST_PATHS as P;print(' '.join(p.replace('phase-loop-runtime/','') for p in P if p.endswith('.py')))") tests/test_govlean_panel_policy.py tests/test_president_wiring.py tests/test_panel_lanes.py
# PANEL golden is unaffected (no board model changes in 2a):
PYTHONPATH=src:tests python3 -c "
from pathlib import Path; import panel_content_tdd_adapter as ad
assert ad.golden_bytes() == (Path('..')/ad.GOLDEN_PATH).read_bytes(); print('golden OK')"
# named mutations (each must turn its test red), then restore:
#   1. seat_eligible always returns (True, None)           -> test_seat_eligibility_floor fails
#   2. drop the ran_model comparison in _resume_native_president -> test_native_fill_declared_model fails
```
Edge cases:
- A ladder that mixes spellings for one seat (`["fable","anthropic"]`) raises `president_ladder_invalid` (duplicate).
- An unknown vendor name (`"mistral"`) is refused like an unknown rung.
- `ran_model` differing only in case or date suffix is a mismatch, because the comparison is exact.

## Acceptance criteria
- [ ] `tests/test_seat_eligibility_floor.py` passes. A governed PRODUCTION_CODE board seating `claude-sonnet-5-5` for `fable` raises `review_seat_below_floor` through the default alias **and** through a caller alias, `seat_for_rung` returns `None` for it, a floor-meeting caller substitution appears in `board.policy.json` read back from `stream_dir`, and mutations 1 and 1b each turn it red.
- [ ] `tests/test_native_fill_declared_model.py` passes. A mismatched or undeclared `ran_model` through the CLI and leg loaders is refused with nothing persisted, the library seam without `ran_model` is accepted and recorded `model_declared: false` in `president.fill.json`, which is read back from `stream_dir`, and mutation 2 turns it red.
- [ ] `tests/test_seat_vendor_names.py` passes. Vendor names are accepted in the policy, the ladder and the rung match, and a vendor-spelled ladder indexes consistently, while `PRESIDENT_LADDER`, `review_policy_for_tier().required_seats` and the `DEFAULT_REVIEW_SEAT_ALIASES` values are unchanged.
- [ ] Every frozen path is byte-identical to origin/main, the frozen HARDEN, PRESROUTE, govlean and PANEL nodes pass (EC-PRESROUTE-2/-3/-4/-5 included), and `golden_bytes()` equals the frozen golden.

## Execution Policy
- execute: effort=high, reason=governed-policy match and president trust boundary; frozen PRESROUTE positive control constrains the seam.

## Plan 2b: board pins from the roster, and the config route (scoped; a separate bounded plan)
**Depends on** plan 1 Part A and Part B being implemented, PANEL SL-1 and plan 2a.

**Pin sites, and the roster cell each derives from.** Each seat gets an **explicit `(vendor, slot)` pin**, not a `ROLE_SLOTS` lookup. A role lookup would demote openai on brainstorm and doc-edit, and promote Sonnet.

| site | seat → cell |
|---|---|
| `panel_invoker.DEFAULT_LEG_MODELS` (around l.1201) | claude → anthropic/frontier; codex → openai/frontier; grok → xai/frontier; gemini → google/standard **plus** the agy effort suffix, built through `harness_mapping` (the value is `gemini-3.8-flash-high`, not a roster id) |
| `advisor_board/composition._VENDOR_SEAT` (around l.93-97) and `fixtures.DEFAULT_SEATS`/`DEFAULT_SEAT_RENDERED_MODEL` | the same cells. `_VENDOR_ORDER` stays and is PANEL's. |
| `presets.py` general, legal-review, legal-strategy-review | openai/frontier, google/standard, anthropic/frontier |
| `presets.py` solo | anthropic/frontier |
| `presets.py` brainstorm, legal-brainstorm | **anthropic/standard**, openai/frontier, google/standard |
| `presets.py` doc-edit | anthropic/standard, openai/frontier |

The effort stays per seat, not from `ROLE_EFFORT`.

`registries._MODEL_DEFS` and `fixtures.CANONICAL_VALID_PAIRS` stay explicit registrations.

**Frozen impact.** With the shipped roster equal to P1-D7, every asserted board id is unchanged, so **no frozen test file needs editing and no `sl0_repairs` entry is needed for plan 2b**. The measurement to repeat when 2b is written covers:
- HARDEN `test_advisor_board_presets.py`, `_golden`, `_composition` and `_backcompat`;
- the PANEL golden, whose pin counts are claude/ultra 9, claude/regular 3, codex/heavy 11, gemini/regular 10 and grok/heavy 5.

The maintainer-accepted `sl0_repairs` stays reserved for the shipped openai frontier flip. That flip is plan-1's golden gate: every board seats one openai id, or a PANEL `sl0_repairs` is needed. It lands through the plan-3 promotion, not in 2b.

**The config route.** agent-harness#1171 comment of 2026-09-29 found that `load_boards` has no production caller. The production entry points call `compose_review_board()` directly:
- `cli.py` around l.2169;
- `governed_review.py` around l.589-595;
- `train_runner.py` around l.3862.

Plan 2b threads the Part-B call-time roster into composition at each of them, with one falsifier per entry point asserting the launched seat model. It also adds governed-policy validation to any board a config supplies (agent-harness#1172 president item 3), including the plan-2a floor. How this interacts with PANEL's `[panel.<task>]` vendor lists follows the PANEL/roster split in plan 1: PANEL picks the vendor, and the roster picks the model.
