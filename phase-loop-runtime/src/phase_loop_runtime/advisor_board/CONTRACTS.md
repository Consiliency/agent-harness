# Advisor Board — Frozen Contracts (Phase 1 ABDFREEZE)

Interface-freeze for the model-first, multi-harness Advisor Board
(`specs/phase-plans-v5.md`). Everything here is **additive and behavior-neutral**:
no running path changes, `panel_invoker` is untouched, and the `default` board
reproduces today's 3-leg panel byte-for-byte. Downstream phases (ABDREG,
ABDRESOLVE, ABDHOME) code against these interfaces so the fan-out integrates
without a big-bang.

Where a contract must reproduce today's behavior, the anchor line in
`phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` is cited and the
equivalence is proven by a test (not asserted in prose).

## IF-0-ABDFREEZE-1 — Seat + Board schema (model-first) · `schema.py`, `harness_mapping.py`

- **`Seat{model, effort, harness?, lens?, auth?, backing?, host_leg?}`** — a seat
  is a cognition; the harness is a defaulted-but-overridable execution *lane*, not
  the primary key. `effort` is a canonical level in `EFFORT_LEVELS =
  (low, medium, high, max)`. Frozen dataclass with fail-closed validation.
- **`Board{name, purpose, seats:[Seat], allow_api_key_fallback=false}`** —
  named, purpose-tagged, open-ended seat list; rejects api-key seats unless the
  board opts in.
- **Config format + location** — `$XDG_CONFIG_HOME/agent-harness/advisor-boards.toml`
  (`board_config_path()`); shape frozen by `fixtures/advisor-boards.example.toml`.
  The loader is ABDREG.
- **Per-harness model/effort mapping** — `render_seat_invocation(harness, model,
  effort) -> SeatInvocation`. Freezes how `seat.effort` reaches each CLI, incl.
  the **agy/gemini leg where effort is embedded in the model-name string**
  (`render_gemini_model`, panel_invoker.py:1016). Built-3 lanes are concrete;
  breadth lanes raise `EffortMappingError` until ABDREG/ABDHOME/ABDOMNI.
  Round-trip (proven): claude→`--effort max`, codex→
  `-c model_reasoning_effort=xhigh`, Gemini Flash→`gemini-3.8-flash-high`;
  explicit legacy Pro display names remain compatible.
- **Seat identity for result re-keying** — `Seat.seat_key` is a stable LABEL over
  every distinguishing field (lane, model, effort, lens), so lens-only-different
  seats get distinct keys. It is not a guaranteed-unique id — a board may hold two
  byte-identical seats — so ABDRESOLVE keys results by **seat position** and uses
  `seat_key` only as the label.
- **Host-leg identity** — `Seat.host_leg` marker + `identify_host_leg(board,
  HostContext)`. A seat is the native in-process host leg only when the board runs
  *inside* that harness (`HostContext.host_harness`). The standalone runner
  (`host_harness=None`) has no host leg — every leg is a subprocess, exactly as
  today.
- **Host×seat routing rule (maintainer; agent-harness#396 / #525 / #924)** — a harness
  fills the seat of its OWN vendor with its native subagent; every other seat runs through
  that vendor's CLI lane, and the Anthropic seat on any host other than Claude Code runs
  through the subscription TUI adapter. Routing keys on the vendor's harness-nativeness, never on
  model tier. Implemented today only for the Claude Code → Anthropic cell
  (`under_claude_code` + `NativeAgentLegRequest`, the emit → fill → invoke protocol);
  no production caller constructs a `HostContext` yet, so the host leg above is
  identified only when a caller passes one, and the remaining cells are tracked on
  agent-harness#924.
- **Seat → vendor-family projection** — `vendor_family(model, harness)` /
  `seat_vendor_family(seat)`, model-first with a harness-lane fallback.
  Byte-consistent with `governed_review.author_vendor_for_model` (:60-75) and
  `_EXECUTOR_VENDOR` (:47-53). Two same-vendor seats on different harnesses
  (`gpt-6-astra` on `codex` and on `opencode`) project to the same family, so the
  governed reviewer≠author disjointness survives model-first. ABDHOME rewires the
  governed gates onto *this* canonical function (not a copy).

## IF-0-ABDFREEZE-2 — Registry interfaces + shared fixtures · `registries.py`, `fixtures.py`

- **Interfaces (Protocols):** `HarnessRegistry`, `ModelRegistry`,
  `CompatibilityMatrix` with `is_valid(model, harness) -> (bool,
  AuthAvailability)` and `default_lane(model) -> str`.
- **Frozen return types:** `HarnessSpec`, `ModelSpec`, `AuthAvailability`
  (concrete, so no-silent-key is testable), `MatrixVerdict` alias.
- **Stubs:** `Stub{Harness,Model}Registry`, `StubCompatibilityMatrix` — raise
  `NotImplementedError`; no six-harness data (that is ABDREG).
- **Shared canonical fixtures** (the anti-divergence keystone ABDREG populates
  *from* and ABDRESOLVE/ABDHOME test *against*): `DEFAULT_BOARD`, `DEFAULT_SEATS`,
  `CANONICAL_LEG_ORDER`, `CANONICAL_VALID_PAIRS`, `CANONICAL_INVALID_PAIRS`,
  `TWO_SAME_VENDOR_BOARD`.

## IF-0-ABDFREEZE-3 — Provider-backing selector + auth enforcement · `backing.py`

- **Backing selector** — `select_backing(seat, gateway_available) ->
  BackingDecision`. Per-seat `homebrew | omnigent`; an `omnigent` seat with no
  gateway degrades **skip-with-warning** (fail-closed — never a silent homebrew
  breadth fallback).
- **Auth = active env scrubbing** — `resolve_seat_env(seat, base_env,
  allow_api_key_fallback)`, freezing the `_subscription_env` pattern
  (panel_invoker.py:226-230,348-353): a subscription seat scrubs **every** vendor
  API-key var; an api-key seat (only behind the board opt-in) scrubs everything
  then injects **only the seat vendor's** key(s). Never silent — an api-key seat
  without the opt-in raises.
- **Claude Fable/Opus = subscription TUI only** — the shared scrub additionally
  removes Anthropic tokens, alternate base URLs, credential-helper inputs, and
  Bedrock/Vertex/Foundry/Mantle/AWS-provider selectors. Run-isolated settings
  disable `apiKeyHelper`; `claude auth status --json` must prove first-party
  `claude.ai` subscription auth before the exact-model self-PTY launch. The
  homebrew backing is mandatory; alternate backings fail before gateway access.
  API-key fallback is forbidden on every host. Task/subagent fulfillment of the claude
  seat is forbidden on every host EXCEPT Claude Code, where the driving session fills the
  deferred seat natively and the fill counts only once bound (EC-REVIEWTRUTH-14,
  agent-harness#921) — the host×seat routing rule above.
- **`VENDOR_API_KEY_VARS`** — the flat `_API_KEY_VARS` tuple re-keyed by vendor
  family; its union equals today's tuple (proven). It is also the api-key INJECTION map.
  `scrub_subscription_env` additionally removes `SUBSCRIPTION_SCRUB_ONLY_VARS`
  (`XAI_API_KEY`, `GROK_CODE_XAI_API_KEY`; agent-harness#864): the api-key variables of the
  subscription-only grok harness, scrubbed but never injectable.

## IF-0-ABDFREEZE-4 — Back-compat contract · `fixtures.py` + `tests/test_advisor_board_backcompat.py`

- The model-first `default` board (`DEFAULT_BOARD`) resolves four vendors in
  `DEFAULT_BOARD_VENDOR_ORDER`: Codex/Sol, Gemini/Flash high, Claude/Opus 5.5, and
  Grok 4.7. The separate legacy `PANEL_LEGS` tuple and explicit `invoke_panel`
  API remain the frozen three-leg Codex/Gemini/Claude boundary.
- `advisor-panel` stays a working alias of `advisor-board` — the rename + alias is
  ABDRESOLVE; this contract only *states* the invariant.
- **Behavior-neutrality proof:** `git diff` on `panel_invoker.py` is empty and the
  full existing suite is green (this package is purely additive).

## IF-0-ABDFREEZE-5 — Observability contract · `events.py`

- **Internal envelope** — `AdvisorBoardEvent` (our shape, `EVENT_SCHEMA_VERSION =
  advisor_board.event.v1`, kinds in `EVENT_KINDS`). NOT a guessed Omnigent schema.
- **launcher ≠ observability-plane** — a natively-launched leg *emits* into a
  forwarded stream; it is never relaunched through the gateway for observability.
- **Forwarding is async/best-effort and can never delay or fail the native leg** —
  `best_effort_forward(sink, event)` swallows every sink error and never raises;
  `NullSink` keeps the default board a no-op. The mapping to a concrete sink
  (Omnigent v0.4.0 endpoint, or omniagent-plus ui-read-model/state-ledger) is
  deferred to ABDOBS — do not freeze against a guessed upstream schema.

## ABDOBS — Observability forwarding (Phase 6) · `observability.py`, `panel_invoker.invoke_board`

Builds the mapping ABDFREEZE-5 deferred. **Confirmed sink:** omniagent-plus's own
`state-ledger` / `ui-read-model` (we control it) — NOT an Omnigent HTTP ingestion
endpoint. v0.4.0's HTTP surface is launcher-centric and exposes **no** ingestion
endpoint for an externally-launched (native) session, so a native leg is
*observed*, never relaunched.

- **Envelope → sink mapping** — `map_event_to_runtime_event(event, session_id)`
  and `map_event_to_ledger_record(event, session_id)` project our
  `AdvisorBoardEvent` onto omniagent-plus's *own frozen* wire shapes:
  `runtime_event.v0.1` (`core-contracts/src/events.ts`) inside a
  `state_ledger_record.v0.1`, kind `runtime_event` (`core-contracts/src/state-ledger.ts`)
  — exactly what `AuditLedger.appendRuntimeEvent` (`state-ledger/src/audit-ledger.ts`)
  writes. **A board run projects to a session; each seat projects to a turn.** A
  per-run `sessionId` is minted (`new_session_id()` — never the board name);
  `turnId` derives from the seat's frozen `seat_key` label. `redaction` is
  `metadata_only` (never a raw key; `content_allowed` only for a text delta). A
  `seat.failed` payload conforms to the full `runtime_failure.v0.1` (`errors.ts`)
  — all of schema/category/retryable/actor/scope/message are required upstream.
  NB: the record-level `recordId` / `sequence` are meaningful only for the
  reference `JsonlLedgerWriter`; the real TS `AppendOnlyStore` ASSIGNS them on
  append (its `AppendRecordInput` has no `sequence`), so a real binding overrides
  them. The authoritative, per-session sequence is the `runtime_event` payload's.
- **Cross-language transport seam** — the ledger is TypeScript, the emit is
  Python, so the boundary is `LedgerWriter` (a Protocol a real omniagent-plus
  binding implements over IPC/HTTP/a shared file) + `JsonlLedgerWriter`, a
  reference transport appending the exact `state_ledger_record.v0.1` records the TS
  `AppendOnlyStore` ingests. We do **not** reimplement ledger internals
  (retention / replay / compaction stay TS-side). This is the integration seam.
- **Async / best-effort (never delays or fails the native leg)** —
  `AsyncForwardingSink.emit` does a NON-BLOCKING put and returns; a background
  daemon thread does the real (slow / failing) write via `best_effort_forward`.
  The never-**raise** guarantee is frozen in `events.py`; the never-**delay**
  guarantee is here (unbounded queue; a bounded queue drops on full). `BoardObserver`
  wraps construct+map+enqueue in a swallow-all, so even a bad kind / full queue
  never touches the leg. `flush()` / `close()` drain deterministically (tests /
  graceful shutdown only — never on the leg's critical path).
- **launcher ≠ observability-plane, in code** — every sink here is structurally
  emit-only (no `create_session` / `send_turn`), so the observability path
  *cannot* launch a leg. Combined with the frozen `enforce_native_host_leg`
  (which hard-raises on a gatewayed host leg), the native host leg is observed,
  never relaunched.
- **Per-workload boundary (documented + enforced)** — `WORKLOAD_BOARD` =
  native launch **+ optional forward** (this path); `WORKLOAD_PHASE_EXECUTION` =
  Omnigent-as-launcher (CS-2.2, out of scope here). `invoke_board(sink=...)` is
  the ONLY opt-in; `sink=None` builds no envelope (default board byte-neutral).
  `invoke_panel` is untouched, so the live default panel is byte-neutral by
  construction.
- **Key-file note (reviewers):** the phase plan lists
  `agent_runtime_provider.py`; the emit lands in `panel_invoker.invoke_board`
  instead, because the envelope's vocabulary is `board.*` / `seat.*` (with
  `seat_key` / `vendor_family` / `harness`) which only the board seam knows — the
  provider only knows sessions/turns and cannot populate it. `observability.py`
  maps our envelope onto the provider-mirrored `runtime_event.v0.1` shape, so the
  provider layer is still the wire target, just not the emit site.

## ABDPRESET — Board preset library + Fable review-path · `presets.py`, `panel_invoker.py`

The seven built-in presets (`presets.PRESETS`). Every preset self-validates against
the real matrix at `load_boards()` time (`tests/test_advisor_board_config.py`,
`tests/test_advisor_board_integration.py`).

- **Review-class = Opus 5.5 (for now), decoupled from the implementer.** Pre-merge
  and legal review are mid-tier decisions where being wrong is expensive, so the
  review-class boards (`default`, `code-review`, `legal-review`,
  `legal-strategy-review`) seat Opus 5.5 (`claude-opus-5-5`) on the claude lane — the
  maintainer's review default "for now" (2026-09-23), Fable (`claude-fable-5-1`)
  before that and still selectable — NOT the implementer model
  `profiles.CLAUDE_IMPLEMENTER_MODEL` (`claude-sonnet-5`). `panel_invoker.DEFAULT_LEG_MODELS["claude"]`
  is the SINGLE source of truth for the panel's default claude model: the claude
  leg builder (`_claude_tui_command`) and the Agent-View attempt both read it, so
  the *legacy* `invoke_panel` path AND the live governed gates
  (`governed_review` / `governed_premerge`, which call `invoke_panel` with no model
  override) review on Opus 5.5. `CLAUDE_IMPLEMENTER_MODEL` is untouched — the
  implementer stays Sonnet. The `default` board (`fixtures.DEFAULT_BOARD`) is
  byte-pinned to this `invoke_panel` panel by the golden proof
  (`tests/test_advisor_board_golden.py`); the sole sanctioned delta stays `seat_key`.
- **`default` and `code-review` are four-vendor frontier boards.** Gemini uses
  `gemini-3.8-flash` at its `high` ceiling alongside Sol, Opus 5.5, and Grok 4.7;
  `code-review` preserves availability-aware backfill and distinct lenses.
- **President availability ladder.** Review findings go first to the `fable` seat
  (Opus 5.5 by default — the rung names the seat, not the model), then
  Sol, Grok 4.7, and Gemini 3.8 Flash. Descent occurs only for a typed
  `president_unavailable` result, never because a president dissents. The ladder
  is EXECUTED (not merely declared) by every `requires_president` landing policy —
  see ABDPRES below.
- **Divergent-thinking boards keep Sonnet.** `brainstorm` / `doc-edit` /
  `legal-brainstorm` deliberately retain `claude-sonnet-5` — a diverse voice, a
  low-stakes copyedit, a cheap aggressive ideation seat — where it is the right tool.
- **Legal boards (`legal-review`, `legal-strategy-review`, `legal-brainstorm`)**
  encode the PRIMARY review lens per seat. `lens` / `purpose` are free-form strings
  (`schema.py`), so the legal lenses/purposes need no enum extension.
- **Catch-alls for unmodeled tasks (`general`, `solo`).** So the board library is not
  limited to the pre-modeled domains: `general` is the domain-agnostic top-tier PANEL
  (three frontier vendors — gpt-6-astra/adversarial, gemini-3.8-flash/alternative,
  claude-opus-5-5/completeness — hand it any task + brief), and `solo` is the
  single-MEMBER form (one `claude-opus-5-5` seat) for a quick top-end opinion when a
  panel is overkill. A ONE-seat board validates + resolves through `invoke_board` like
  any other (bare/single seats are supported). Both default to TOP-END models: an
  unanticipated task cannot be assumed low-stakes, so the safe default is frontier —
  dial down explicitly (a cheaper board) when a task is known-cheap. Their lenses
  (`adversarial`/`alternative`/`completeness`) and purpose (`general`) are free-form
  strings, so no enum extension.
- **Deep-seat FOLLOW-ON (documented, NOT built here).** The richer legal treatment —
  four lenses per seat, an apex-Opus (`claude-opus-5`) seat, a verify-round, and
  retrieval-grounded citation-verification — is a deliberate follow-on. The current
  legal boards ship the single-primary-lens-per-seat form; the deep-seat form layers
  onto the same seat/board schema (no schema change) when built.

## ABDPAR — Concurrent leg execution · `panel_invoker.invoke_board` / `invoke_panel`

`invoke_board` and `invoke_panel` fan their seats/legs out across a bounded
`ThreadPoolExecutor` (`_run_legs_ordered`), not a sequential loop — legs are blocking
subprocess I/O (the CLI wait releases the GIL), so wall-clock is `~max(leg)`, not
`sum(leg)`.

- **Parallel is the DEFAULT (opt-out, not opt-in).** Both entry points take a single
  `max_concurrency: int | None = None` knob, threaded through the governed gates
  (`governed_planning_gate` → `run_governed_premerge_loop` → `governed_premerge_for_run`)
  so a caller CAN request sequential, while the default everywhere stays parallel:
  - `None` (default) → parallel, bounded by `min(len(seats), 8)`.
  - `1` → sequential (the opt-in escape hatch — debugging, a rate-limited / throttled
    provider, a constrained host).
  - `N` → cap concurrency at `N`.
  It is the SAME thread-pool path: `max_workers = max(1, min(max_concurrency or len(seats), 8))`,
  so `max_concurrency=1` degrades to one worker (strictly serial) with no separate
  sequential branch. `max_concurrency` is a keyword-only, default-valued additive
  extension to the frozen `invoke_panel` signature (back-compat, like `models` #66).

Frozen invariants (concurrency is a **timing-only** change — never a leg's outcome;
the golden proves byte-identity):

- **Positional order** — futures are submitted in seat/leg order and read back by
  index, so `result[i]` corresponds to `seats[i]`/`legs[i]` regardless of finish
  order. `resolver.key_results_by_seat` re-keys by position and the golden asserts
  order + content, so this is load-bearing.
- **Fail-closed per seat** — the extracted per-seat/per-leg body returns a DEGRADED
  `PanelLegResult` on any exception, so a future's `.result()` never raises and one
  broken leg can never crash the pool or the board.
- **Single shared reads before the pool** — the one `GET /v1/harnesses` gateway-catalog
  fetch and the seat-validation/host-leg checks stay ABOVE the pool (one fetch, shared
  read); the observability emit stays AFTER, in seat order. Bounded `max_workers =
  min(len(seats), 8)`.
- **Proof** — a `threading.Barrier(N)` test proves both directions without real sleeps:
  the DEFAULT satisfies the barrier (all N legs in-flight at once → all OK), and
  `max_concurrency=1` makes the same barrier unsatisfiable (one worker → it times out →
  fail-closed DEGRADED), so the pair discriminates parallel from sequential. A third
  test confirms sequential mode returns byte-identical ordered results.
- **Thread-safety of the real leg paths** — the leg execs install NO signal handlers or
  timers (`signal.signal` / `alarm` / `setitimer` would raise `ValueError: signal only
  works in main thread` off the main thread); the only `signal.` use is `os.killpg(pid,
  SIGTERM/SIGKILL)` (a constant, thread-safe), and timeouts run on `select.select(...)`
  / `subprocess.run(timeout=...)`, not `SIGALRM`. Each leg stages its own temp review
  dir, so concurrent legs never share filesystem state. Verified: the real `spawn=None`
  path runs inside worker threads with no signal-in-thread error.
- **Known edge (untested):** a custom board with two seats on the SAME lane (e.g. two
  `claude` seats) now runs two concurrent same-lane CLI/PTY sessions — a scenario this
  fan-out newly enables and nothing yet tests. The `default` board has one claude seat,
  so it is unaffected.
- **Opt-in streaming delivery (REVIEWGOV IF-0-REVIEWGOV-2).** `_run_legs_ordered` (and
  the `invoke_panel` / `invoke_board` entry points) take optional, keyword-only,
  default-`None` `on_leg_complete` (a per-leg callback) and `stream_dir` /
  `review_dir` (incremental per-leg verdict files). When BOTH are `None` the path is
  byte-for-byte the historical one — block on the futures in submission order — so the
  golden is untouched. When EITHER is set, results are collected via `as_completed` so
  each leg is delivered the MOMENT it lands (callback + a `leg-<i>-<label>.verdict.json`
  file written into the dir), while the **consolidated return is still re-sorted to
  submission order** (`result[i]` ↔ `items[i]`). The side-channel is **fail-open**: a
  raising callback or an unwritable dir is swallowed (logged), never breaking the pool
  or failing a leg. Proven by a SINGLE shared out-of-order-completion fixture used by
  both the default-ordering (golden) and fast-before-slow (streaming) tests, so the
  golden cannot pass trivially.

## ABDREF — "Reference, don't inline" ingestion · `panel_invoker._resolve_artifact` / `_resolve_brief`

The leg prompt was already lean (it stages `review-bundle.md` and instructs the leg
to READ the file); the remaining inline path was the caller→runtime boundary, where
building `artifact: str` forces the caller to hold the whole (20k+ token) bundle in
its own context. `artifact_ref` / `brief_ref` promote that to by-reference ingestion:
the caller passes a PATH and the runtime reads it.

- **Entry points.** `invoke_panel` and `invoke_board` accept keyword-only
  `artifact_ref: str | Sequence[str] | None` and `brief_ref: str | None`
  (default-valued additive extensions to the frozen signatures — back-compat, like
  `models` / `max_concurrency`). `invoke_panel_request` consumes
  `PanelRequest.artifact_ref` but deliberately does not define `PanelRequest.brief_ref`
  in this contract; callers that need a custom brief use the direct `invoke_panel` or
  `invoke_board` entry point. The artifact is resolved at the TOP of the entry point
  so timeout scaling, staging, and metadata all see the resolved content.
- **`_resolve_artifact(artifact, artifact_ref)`.** `artifact_ref is None` →
  `artifact or ""` (today's bytes, verbatim). A single path (a bare string OR a
  one-element sequence) returns the file content VERBATIM — no header — so
  `artifact_ref=P` is byte-identical to `artifact=<contents of P>`. Multiple paths
  concatenate deterministically in the given order, each under a `## {filename}`
  header, joined by a blank line. `artifact_ref` WINS when both it and `artifact` are
  supplied. A `str` is checked BEFORE the `Sequence` branch (a string is itself an
  iterable of characters).
- **`_resolve_brief(mode, brief_ref)`.** `brief_ref` file when set, else
  `_mode_instructions(mode)` — staged as `review-instructions.md`. Threaded through
  `_default_spawn` / `_default_spawn_via_provider` (omitted-when-`None`, so the
  default path's `_default_spawn` call stays byte-identical).
- **Fail-closed.** A missing `artifact_ref` / `brief_ref` path raises `ValueError`
  NAMING the path — never a silent-empty bundle that would read as a real (empty)
  review.
- **Inline-size guard (`_maybe_warn_inline_size`, `_MAX_INLINE_ARTIFACT_BYTES = 16 KB`).**
  An INLINE (not-from-ref) artifact over the threshold logs ONE steering warning
  pointing to `artifact_ref` — **WARN, never refuse, never mutate** (refusing would
  break existing callers). A from-ref artifact is never warned.
- **Crash-residual scratch GC (`_gc_stale_panel_scratch`).** Best-effort, age-gated
  (`max_age_s = 24h`) sweep of `pl-panel-*` dirs, called at the top of
  `_default_spawn`. Reclaims dirs leaked when a run is KILLED before the per-run
  `finally: rmtree` (timeout/crash); a concurrent run's fresh dir is never touched,
  and a GC failure can NEVER affect the run (fully swallowed).
- **Golden byte-identity preserved.** No ref ⇒ identical staged bytes ⇒ identical
  per-leg argv / env / timeout. `tests/test_advisor_board_golden.py` (Proof A hits
  `_exec_leg`; Proof B injects `spawn=`) is untouched;
  `tests/test_advisor_board_ingestion.py` proves the new path is byte-transparent.

## CTXFREEZE — Context references and panel reliability (#114)

CTXFREEZE freezes the #114 public contract for downstream implementation and
documentation phases. It does not claim that `artifact_ref` or `brief_ref` are true
non-inlining modes: both are read-file-and-inline conveniences that keep bytes out
of the caller context but still stage raw contents for each leg.

- **Ingestion modes and precedence.** `artifact` is inline text. `artifact_ref` is a
  file path, or ordered path sequence, whose contents replace `artifact` when both
  are supplied. `brief_ref` is a file path used only by `invoke_panel` and
  `invoke_board`; it replaces the generated review/advisory instruction file.
  `context_refs` is the only true by-reference mode. `invoke_panel_request` threads
  `PanelRequest.artifact_ref`, `PanelRequest.context_refs`,
  `PanelRequest.context_refs_soft_warn`, and `PanelRequest.timeout_seconds_by_leg`;
  `PanelRequest.brief_ref` is explicitly out of contract for this phase.
- **True by-reference manifest.** `context_refs` appends a deterministic manifest to
  the already-resolved artifact. Each entry is emitted in caller order and contains a
  JSON-escaped absolute path, byte count, streamed SHA-256 digest, untrusted MIME
  guess, untrusted extension hint, and optional best-effort PDF page count. Raw file
  contents are not written into `review-bundle.md`, prompt text, or the manifest.
- **Metadata sensitivity.** Absolute pathnames and hashes can disclose sensitive
  project names, customer names, filenames, document structure, and content
  fingerprints even when raw bytes are not inlined. Callers should treat the
  manifest as metadata-bearing, not private-by-construction.
- **Filesystem boundary.** Paths are interpreted relative to the current process
  working directory when relative and are reported as `Path.resolve()` absolute
  paths. Entries must be regular files at validation time; missing paths,
  directories, devices, and other non-regular files fail closed by default. Symlinks
  are followed only if their resolved target is a regular file under normal OS path
  resolution. The runtime opens the file once to stream size/hash metadata and, for
  PDF-looking files only, may reopen a bounded prefix for page counting; CTXIMPL owns
  any stronger root jail or TOCTOU hardening.
- **Provider and backing limits.** `context_refs` assumes the selected provider and
  backing can access the same local filesystem path from the leg runtime. Remote,
  sandboxed, or service-backed harnesses may not have local file access even when
  the manifest validates on the caller host.
- **Soft-warning opt-in.** Missing or unreadable `context_refs` raise `ValueError`
  unless `context_refs_soft_warn=True`. Soft warning logs a warning and emits a
  `MISSING` or `UNREADABLE` entry. The manifest instruction text remains strict:
  a leg must not infer, guess, or fabricate unavailable contents.
- **Output-boundary claim.** The frozen privacy claim is runtime non-inlining only:
  referenced contents are absent from the staged bundle and prompt produced by this
  runtime path. This is not a global DLP guarantee for provider logs, human-visible
  outputs, handoffs, screenshots, shell commands, or tools the leg chooses to run
  after reading a referenced file. A leg may disclose file contents after it
  intentionally inspects a referenced path unless an output policy forbids that
  disclosure.
- **Reliability names.** Direct entry points accept `timeouts_by_leg`; `PanelRequest`
  uses `timeout_seconds_by_leg`. Both feed the same per-leg override. Unset legs keep
  input-scaled defaults. The codex and gemini CLI legs retry one fast soft-empty or
  transient-stall result once, guarded by elapsed-time fraction; hard subprocess
  timeouts return timeout status without retry. CTXRELY owns any follow-on reliability
  split beyond these frozen names and retry/timeout invariants.

## ABDMODE — Purpose-derived default mode + advisory prompt hygiene · `panel_invoker.py` (#107)

A board's PURPOSE now selects its default panel MODE automatically, so a domain
board (esp. the legal boards) runs in the right posture instead of being hard
code-review-gated. `tests/test_advisor_board_advisory_mode.py`.

- **`_mode_for_purpose(purpose) -> str`.** Code-review-class purposes
  (`code-review`, `premerge-review`) → `"review"` (the strict pre-merge gate:
  bundle is untrusted material to accept/reject, a conforming AGREE / PARTIALLY
  AGREE / DISAGREE verdict is REQUIRED). The known domain purposes (`legal-review`,
  `legal-strategy-review`, `legal-brainstorm`, `brainstorm`, `doc-edit`, `general`)
  → `"advisory"` (analysis / recommendation, no verdict — substantial prose is a
  real leg). An UNKNOWN purpose → `"review"` (back-compat safe default: a strict
  gate never silently loosens on an unrecognized board).
- **`invoke_board(mode=None)` derives, a caller-passed `mode` overrides.**
  `invoke_board` defaults `mode` to `None`; when `None` it derives
  `_mode_for_purpose(board.purpose)`. `invoke_panel` KEEPS its legacy
  `mode="review"` default (no board / no purpose). `DEFAULT_BOARD.purpose` is
  `premerge-review` → derives `"review"` → **the golden byte-identity holds** —
  `invoke_board(DEFAULT_BOARD)` stays byte-identical to the legacy review path.
- **Mode-aware prompt hygiene (`_render_leg_prompt`, `_ADVISORY_INSTRUCTIONS`).**
  The REVIEW framing is **byte-for-byte unchanged** (the golden asserts the exact
  prompt/argv). The ADVISORY framing DROPS the code-review-gate posture — no
  "authoritative", no "untrusted material under review", no accept/reject — while
  KEEPING the instructions/material SEPARATION (injection-safe: the brief is your
  task, the bundle is only material, never authoritative instructions).

## ABDPRES — President ruling on `requires_president` boards · `panel_invoker.invoke_board`, `president_adapter.py`, `runner._run_legible_panel` (Consiliency/agent-harness#736)

A `ReviewLandingPolicy` with `requires_president=True` (the `plan` and
`production_code` tiers) is no longer policy-only: `invoke_board` runs the
president ladder after every seat has returned and before any result can reach
a landing decision. `tests/test_president_wiring.py`.

- **Seam.** `invoke_board(..., president_invoke=)` takes the ladder's
  `invoke(rung, prompt)` callable. A president-requiring policy WITHOUT a seam is
  refused at policy time (`PresidentPolicyError("president_seam_missing")`),
  before any seat spends effort. `requires_president=False` policies (including
  `tests_only` / `docs_only`) are byte-neutral: no findings are collected, no
  president is invoked, `PanelResult.president` stays `None`.
- **Findings → prompt.** `president_findings_from_legs` gives every usable seat's
  finding paragraphs stable positional IDs (`F001: [seat] text`) in seat order;
  whitespace-collapsed duplicates fold into one ID with every contributing seat
  named, so the same text never earns two rulings.
- **Ruling → result.** A valid ruling lands on `PanelResult.president`
  (`PresidentRuling`) with `PanelResult.president_findings`; `president_finding_rulings`,
  `president_forcing_decision`, and `president_blocks_landing` read it. The board
  itself does NOT apply BLOCKING — applying the ruling to a landing is the governed
  caller's job (the runner refuses the landing; nothing waives it).
- **No ruling → refusal.** Every ladder outcome that yields no valid ruling
  (`president_unavailable`, `president_invocation_failed`,
  `president_ruling_format_missing`, `degraded_president_validation_deferred`)
  refuses EVERY seat with detail `president_ruling_missing:<code>` so the
  unadjudicated verdicts cannot be read as a landing; the finding list the ladder
  was asked to rule on is kept on the refusal. `president_invocation_failed` is a
  refusal rather than an exception because the production seam answers every
  seated rung with it: the governed caller must receive that as a board result it
  persists, not as an error it never records. Only a caller-contract error
  (`president_round_limit`) propagates as `PresidentPolicyError`.
- **Execution route — SUPERSEDED by ABDPRESROUTE below** (agent-harness#952): a seated
  rung now runs through `public_board_president.v1`. The text of this bullet records the
  pre-PRESROUTE route. `president_adapter.build_president_invoke`
  binds the ladder to a board's seats (`seat_for_rung`: rung alias → seat model →
  harness). An UNSEATED rung answers typed `president_unavailable` (the ladder
  descends). A SEATED rung answers `failed` / `president_execution_route_unavailable`
  WITHOUT spawning: post-HARDEN the only production execution operation is the
  governed review (`public_board_review.v1`, frozen AGREE grammar) and advisory
  execution is refused, so a `FORCING DECISION:` ruling has no sanctioned operation
  to ride. The ladder treats that as an ordinary failure (`president_invocation_failed`,
  no descent), the board refuses every seat with
  `president_ruling_missing:president_invocation_failed`, and the landing fails
  closed. Routing the president through `invoke_panel(mode="advisory")` or laundering it through a
  review leg is NOT permitted (EC-HARDEN-5). A HARDEN-authorized president
  operation (own mode, brief, completion grammar, and authorization identity) is
  the follow-up; every attempt is recorded on the seam (`PresidentInvoke.attempts`)
  and persisted by the runner.
- **Runner.** `_run_legible_panel` declares `landing_tier=production_code` and the
  seam only when `_govlean_authority_switched(repo)` — post-switch the invoker
  already refused a tierless call (`review_landing_tier_required`), so the failure
  reason becomes the honest president one; pre-switch repos keep the tierless call
  byte-for-byte. Post-switch it writes `implementation-panel-president.json`
  (`advisor_board_president.v1`: head, model, text, rulings, forcing_decision,
  substantive_rounds, format_reasks, findings, attempts, refusal) BEFORE it judges
  the board -- on a board refusal or a missing ruling the record still lands with
  the ruling fields null, `refusal` naming the `president_ruling_missing:<code>`
  detail, and every seam attempt -- and refuses the landing on a non-unanimous
  board, a missing ruling, or any BLOCKING disposition. `implementation-panel.json`
  is written only after those checks pass. A run directory carries exactly ONE
  attempt's records: every prior `implementation-panel*.json` (a landing, a
  president record, a partial `.tmp`) is invalidated before the board runs, and
  both records are published atomically (temp file + rename), so a president
  record without a panel record is this attempt's refused landing -- never an
  earlier attempt's landing beside a later refusal, and never a partial write.
- **Standalone launchers.** A caller that wants the four-seat board without a
  president passes an explicit `review_policy=ReviewLandingPolicy(required_seats=...,
  requires_president=False)` rather than a president-requiring tier.

## ABDPRESROUTE — The president operation · `president_operation.py`, `president_adapter.py`, `advisor_board/backing.py`, `panel_invoker.invoke_board` (IF-0-PRESROUTE-1, Consiliency/agent-harness#952)

The president's OWN HARDEN-authorized operation, `public_board_president.v1`, beside —
never through — the review operation `public_board_review.v1`. Frozen falsifiers:
`tests/test_president_wiring.py`, `tests/test_govlean_panel_policy.py` (SL-0,
`content_tdd_receipt.v1`), golden `tests/data/president_ruling_v1.golden.json`.

- **Callable.** `president_operation.run_president_operation(*, brief, findings,
  authorization, invoke, max_substantive_rounds) -> PresidentOperationResult(ruling,
  authorization_identity, rung_index, brief_digest, findings_digest)`. It refuses an
  authorization whose `operation` is not exactly `public_board_president.v1`
  (`PresidentPolicyError("president_operation_authorization_mismatch")`) BEFORE any rung
  is invoked, then walks `PRESIDENT_LADDER` through `invoke` with the president prompt
  built from the findings; the brief is digested, not sent.
- **Digests.** `brief_digest = sha256(brief)`; `findings_digest =
  sha256("\n".join(findings))` in prompt order; lowercase hex. On a board, the brief is
  the composed president prompt `_president_prompt(findings)`.
- **Completion grammar.** Per-finding `FINDING <id>: BLOCKING|DEFERRED — <reason>`,
  terminal `FORCING DECISION: <decision>` (`_valid_president_grammar`); a launched rung's
  turn is complete when its last line is a non-empty `FORCING DECISION:`
  (`_completion_ok(text, "president")`), never a review verdict.
- **Authorization.** `backing.prepare_president_isolation_authorization(board, brief)`
  mints `PresidentIsolationAuthorization` (same seal as review isolation;
  `child_credentialless=True`, `child_network_egress=False`, `live_tree_exposed=False`,
  `api_fallback=False`; subscription routes; brief digest; repository identity when the
  launch has one — the operation reads no tree). The adapter revalidates it
  (`revalidate_president_isolation_authorization`) immediately before a rung launches and
  launches that authorization's route; a seat the authorization does not route (Claude
  included) is refused without launching.
- **Rung routes** (`president_adapter.build_president_invoke(..., monitoring_policy=)`).
  Unseated rung → typed `president_unavailable` (descend). `sol` / `grok` → the brokered
  `_exec_leg` in a throwaway directory, whose only launch is `launch_provider`. `gemini` →
  the broker's acknowledged agy stream with the PRESIDENT's own final instruction (a ruling,
  not a review verdict), launched through `_run_leg_with_liveness` → `launch_provider` and
  decoded by `_broker_gemini_stream_result`; with the agy subscription credential it runs in
  the broker's agy profile, without one in an empty private HOME (no credential of any kind),
  so the provider itself refuses and the failure is typed. `fable` under Claude Code (from the passed `base_env`; the adapter
  falls back to the process environment only when none is passed, so it never spawns a
  second TUI) → a deferred native fill `{"status": "native_fill_deferred", rung,
  brief_digest, findings_digest}`, refused with `president_fill_heartbeat_refused` under
  `heartbeat_only`. `fable` elsewhere → the brokered self-PTY session
  (`_run_claude_tui_session`, tools off, no directory grant). A failed launch is a typed
  `failed` (`president_invocation_failed`, no descent).
- **Ladder** (EC-PRESROUTE-3). `PRESIDENT_LADDER` is the seat-alias tuple; each alias
  resolves to its vendor's registry PIN through `DEFAULT_REVIEW_SEAT_ALIASES` (where the
  `model-id-source:` markers live). No model id is spelled in the ladder.
- **Defer → resume** (EC-PRESROUTE-2). A deferred Fable rung makes `invoke_board` return
  the seats with `PanelResult.needs_native_president` = `{rung, brief_digest,
  findings_digest, prompt}` and no ruling, persisting `president.pending.json`
  (`president.pending.v1`: the request plus the findings and seat verdicts it was built
  from) to `stream_dir`; a deferral without `stream_dir` is refused
  (`president_native_fill_stream_required`). `invoke_board(..., native_president_fill=
  {rung, brief_digest, findings_digest, text})` RESUMES after the same factory /
  revalidation gate and before any seat launches -- no seat is re-run, so seats that would
  word things differently cannot strand the route. The pending request is BOUND to its run
  (resolved-artifact digest, the board's ordered seat keys, mode, landing policy) and the
  resume refuses any difference. The fill is accepted only when that binding matches, the
  stored verdicts are this board's seats in order and re-derive the stored findings, the
  pending rung is this board's natively filled (Claude) rung, the persisted digests
  recompute from the stored findings, the fill's rung and BOTH digests equal them, and the
  text passes the ruling grammar for those findings. An accepted request is CONSUMED (it
  answers once). This guards against a stale or mismatched stream, not a caller who forges
  its own stream directory (the stream is the caller's durable context); otherwise `president_fill_digest_mismatch` (or
  `president_ruling_format_missing` / `president_native_fill_stream_required`) and nothing
  is persisted. The resumed result carries the deferred seats' verdicts (republished to the
  stream) and the ruling. Under Claude Code, `invoke_board` wires the adapter itself when no
  seam is passed -- keyed on the PASSED `base_env` only, never the process environment.
- **Ruling record** (EC-PRESROUTE-5). Every president ruling a board obtains on a call that
  has a review stream (`stream_dir`; the runner and the CLI always pass one, and the native
  path refuses without one) is written atomically to `<stream_dir>/president.ruling.json`.
  A stream-less call -- which the frozen SL-0 corpus exercises on several president nodes --
  returns its ruling unrecorded, since there is no stream to record it in. Schema
  `president.ruling.v1`:
  `schema`, `authorization_identity` (`public_board_president.v1`), `rung_index`,
  `model_id` (the ruling rung's registry PIN on the board), `format_reask_count`,
  `brief_digest`, `findings_digest`, `forcing_decision`, `finding_rulings`
  (`[{id, disposition, reason}]`). `president_operation.president_ruling_record(result)`
  builds the same shape from a `PresidentOperationResult`.
- **Override expiry** (EC-PRESROUTE-4). `panel_invoker.enforce_requires_president(tier,
  *, requires_president)` refuses a `plan`/`production_code` landing carrying
  `requires_president=False` (`requires_president_override_refused`); `invoke_board`
  calls it whenever a `landing_tier` is given. The interim ratification note is EXPIRED.
- **CLI.** `advisor-board --landing-tier <tier>` runs the board under a tier (a president
  tier binds the seam to the driving process's environment);
  `--native-president FILL.json` resumes a deferred rung against the pending request
  under `--native-fill-dir`/`native-fill/president/`.

## Review monitoring policy v1 (agent-harness#892)

The opt-in policy vocabulary is `bounded | heartbeat_only`; omission is bounded.
Heartbeat-only permits brokered subscription/homebrew Claude TUI, Codex and
Grok, plus the qualified Gemini extension below. It permits no timeout overrides,
capture, research, API fallback, gateway or native host seat. Whole-board
capability preflight precedes availability, auth, session creation and provider
dispatch. Missing or changed Gemini capability refuses the requested whole board;
its membership is never reduced or backfilled to satisfy this policy.

The requested/effective policy is bound to the operation lease and minted leg.
Heartbeat-only admission expires 10 seconds after minting and is single-use;
complete frame receipt and ownership are checked before inference. Admitted
model response waiting has no aggregate wall-clock deadline or silence cutoff.
It makes one attempt, including when that attempt completes empty.
Cancellation and owner loss retain child/provider/server ownership until
quiescence; unproven quiescence cannot become successful evidence.
Private staged inputs and diagnostics are retained when quiescence cannot be
proven; that retention is failure evidence, not successful cleanup.

`review_monitoring.v1` is a separate metadata-only opt-in record: invocation and
seat position, requested/effective policy, admission window, null model/silence
deadlines, last observed progress age, observation state, and terminal reason.
Genuine output within the existing print-read observation interval is
`progress_observed`; older output or no output is `progress_unobserved`.
The TUI timestamp is refreshed by novel output lines, review-file growth and
transcript growth — a startup banner is novel output and refreshes it; only
repeated cosmetic repaints do not, once the existing novelty detector has seen
their text. The CPU-tick heartbeat never refreshes it.
Neither state is a health attestation or permission to terminate. Frozen
broker request/response keys, status literals, and observer envelopes are unchanged.

When staging requires egress isolation, acquisition follows staged-tree and operation
authorization revalidation. Heartbeat-only holds the network helper lifetime through
an owner pipe, with no aggregate expiry; owner exit closes both helpers. Provider
PID ownership is established after network entry but before the capability bounding
set is emptied. Every launch retains the common provider launch seam and broker
threads inherit its ContextVar prefix. EgressUnavailable stays DEGRADED with empty
review text and the exception in detail; sandbox facts describe actual enforcement.

### Qualified Gemini extension (agent-harness#905)

The Linux subscription `agy` entry image must match SHA256
`9991515b6d5307bcf701069622b0537b6b206e605f3c891c0cf3a3d208dea8b0`.
The running Python/kernel must support sealed memfds, pidfds and pidfd signaling;
Python version alone is not a capability check. Unknown images or missing
capabilities refuse before availability/auth effects. Required bwrap mount/gate
flags are checked at admission, before inference. The measured help defines
literal `--print-timeout 0` as waiting for completion. A quick real completion
establishes compatibility; clock controls establish that old runtime deadlines
and silence cannot terminate a healthy heartbeat-only operation.

The sealed image and deny-all settings are read-only mounts inside a private
HOME owned by the existing PID/mount namespace. A private symlink references the
subscription credential; no credential payload is copied, logged or restored.
Heartbeat credential lookup uses the supplied scrubbed HOME, recording a process
HOME fallback truthfully if HOME is absent. Legitimate refresh writes survive.
The real qualification driver requires an explicit HOME and checks target
presence before and after, without reading its contents.

The broker transports same-session acknowledged input over stdin, with no tree
attachment, `--add-dir`, permission bypass, retry or native thinking timer. Empty,
rejected and nonzero-exit streams remain non-votes with fixed diagnostics;
provider stdout/stderr and arbitrary exception strings are not substituted for
review prose. Native timeout under zero has a distinct diagnostic. Bounded
retry timing and supported positive deadline argv remain unchanged; accepted
Gemini review prose excludes stderr.

Namespace init identity is held before execution is released. Cancellation
reaps before closing a blocked execution gate; abrupt owner death can release
its EOF gate shortly before the parent-death signal takes effect. There is no
strict zero-exec claim for abrupt loss. Cleanup requires namespace-init exit
and corroborating observations, including detached/nested descendants. Failed
quiescence cannot yield a usable vote. No receipt proves remote billing settlement.

`phase-loop-runtime/scripts/qualify_gemini_heartbeat.py` separately qualifies
completion, cancellation after observed progress, and abrupt owner loss. Its
receipts bind package source, image/help/profile/helper hashes, inputs, argv,
monitoring, broker records and local cleanup observations. Helper evidence is
sampled, not a complete exec audit; the entry image pin does not freeze helper
images. Directory validation accounts for every attempt in the declared series
root, rejecting failures, omissions and terminal/admission mismatches. Preserve
failed series; diagnose a changed candidate before another attempt. Validation
uses that host's measured helper images. These receipts do not replace the
historical bounded-success evidence verifier.
