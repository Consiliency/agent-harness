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
  subscription-only grok harness, scrubbed but never injectable -- and
  `GROK_SUBSCRIPTION_BLOCKED_ENV_VARS`, grok's endpoint redirects.

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
  and a GC failure can NEVER affect the run (fully swallowed). It sweeps both the
  current staging root and the system temp dir, where releases before
  agent-harness#1147 staged.
- **Staging root and retention (agent-harness#1147, `sandbox_policy`).**
  - **Invariant.** Sandbox staging and spawned-CLI scratch are never RAM-backed while a
    disk-backed candidate is usable. Otherwise they run in a typed DEGRADED mode
    (`ScratchLocation.degraded`): one warning and hard-clamped retention, and the round is
    never crashed. `PHASE_LOOP_SANDBOX_REFUSE_RAM=1` refuses instead (leg detail
    `env_failure: no disk-backed scratch and RAM fallback refused`).
  - **RAM-backed** means a Linux tmpfs or ramfs, identified by the device serving the path
    (`st_dev` matched against `/proc/self/mountinfo`), so overmounts and moved mounts are
    judged correctly. macOS and Windows temp dirs count as disk.
  - **Named exceptions**, each a typed scratch decision (`child_scratch_env`): the agy
    qualification and capture jails keep a tmpfs `/tmp` and their frozen env, because they
    are qualification evidence (follow-up agent-harness#1179); and the Gemini HEARTBEAT
    seat's jail mounts its own private `/tmp` (agent-harness#1181). Neither covers a
    bounded Gemini leg or the bounded Gemini president, which run on the host.
  - **Staging root.** Each round's `pl-panel-*` scratch, and the sandbox clone inside it,
    is created under `staging_root()`. That is `PHASE_LOOP_SANDBOX_STAGING_DIR` when set;
    otherwise `phase-loop/sandboxes` in the platform's per-user cache dir (`$XDG_CACHE_HOME`
    or `~/.cache` on Linux, `~/Library/Caches` on macOS, `%LOCALAPPDATA%` on Windows); else
    the system temp dir when it is not RAM-backed. `TMPDIR` is not the override. The
    launcher's agy review copy (without a run log) and the falsifier's stage and
    dependency snapshot use the same root. Every directory the runtime creates below the
    cache dir is created 0700 and must be a real directory owned by this account.
  - **Capacity.** Filesystem size comes from `shutil.disk_usage`, which works on every
    platform.
    - Retention ceiling: `min(PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES (40 GiB), 25% of the
      filesystem)`, or 10% on a RAM-backed one.
    - Default floor: 2 GiB capped at 25% of the filesystem, or 25% of a RAM-backed one.
    - A floor that is configured (by the setting's presence) is used verbatim.
  - **Reaping.** Before a round is refused for space, retained sandboxes are reaped
    oldest-first. The TTL, footprint and free-space reaps all skip a sandbox whose owning
    process is still running. The owner marker is published atomically (temp file, fsync,
    rename).
  - **Other knobs:** `PHASE_LOOP_SANDBOX_ROOT` (the selected root, recorded in the
    evidence; see the placement seam below), `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED`,
    `PHASE_LOOP_SANDBOX_TTL_S` (24 h), `PHASE_LOOP_SANDBOX_PROBE_TIMEOUT_S`,
    `PHASE_LOOP_SANDBOX_ARCHIVE_DEST`, `PHASE_LOOP_SANDBOX_DISABLE`.
- **Sandbox placement seam (agent-harness#896, `sandbox_placement`).** One vendor-neutral
  seam, several backends. The built-in `LocalBackend` is today's path; a remote host or a
  cloud sandbox registers a backend under a URL scheme, directly or through the
  `phase_loop_runtime.placement_backends` entry-point group, which is loaded only when a
  configured root names that scheme. Core names no vendor.
  - **Phases, in order, for every backend.** `prepare` is runtime code
    (`prepare_local_stage`: stage locally, owning the partial stage until it returns), never
    a backend method. The runtime's revalidations then run against that local stage,
    unchanged. `commit` transfers the revalidated stage (a no-op locally); it owns any
    partial remote state until it returns and the backend recomputes the digest. `execute` /
    `wait` / `cancel` / `renew` are the runtime's own launch branches locally. `release`
    removes the stage. Code never leaves the operator's custody before revalidation.
  - **Launch is final.** Once `execute` is called, even if it raised, the attempt is
    launched: it never falls back to local, and a retry in the same round reuses the same
    backend or refuses.
  - **Receipts.** Backends return `BackendReceipt`s only. Only the runtime builds a
    `PlacementReceipt(attested_by="runtime")`, for a step it performed and observed
    (`prepared`, `committed`, `launched` -- `execute` called, or a local provider process
    the runtime started, counted once `Popen` returned; a launch that fails to exec is not
    one, and infrastructure launches such as the egress namespace holder and its uplink are
    never counted -- and `completed`). A backend's claim is recorded as `attested_by="backend"`. Every
    receipt carries `sandbox_ref` (`[A-Za-z0-9._:-]{1,128}`, anything else refuses the
    placement) and `snapshot_sha256`, which the runtime computes from the local stage.
  - **`sandbox_root_applied`.** Local: the built-in backend, no host, and the root is the
    stage's parent. Non-local: runtime-attested `committed` and `completed` share one
    `sandbox_ref`, both carry the authorization's staged-tree digest, the leg spawned no
    local provider, and any backend receipts agree. Backend receipts alone never make it
    true. `sandbox_staged_at` is the path locally and `<scheme>:<sandbox_ref>` otherwise.
  - **Capabilities and declarations.** `capabilities()` is what a backend can enforce, from
    a closed set (`private_ranges_unreachable`, `public_egress`, `private_allowlist`,
    `inbound_closed`, `filesystem_confined`, `uid_isolated`, `bounding_set_empty`,
    `seccomp_filtered`, `resource_bounded`, `one_shot_secret_channel`, `operator_custody`).
    `verified` maps a capability verified for this placement to `runtime_end_to_end` (only
    the runtime writes it) or `backend_attested`, and is a subset of `capabilities()`.
    `LocalBackend.capabilities()` is empty: local egress and uid facts stay in their own
    fields. `declaration()` names the backend's egress residuals (closed kinds, each with
    `closed_in_guest`), the control-plane variables it injects into the guest (values
    redacted), and `max_lifetime_s`.
  - **Roots.** `PHASE_LOOP_SANDBOX_ROOT` is the single-root form. Otherwise the user
    config's `[sandbox]` table in `advisor-boards.toml` names one root per remote backend
    (`roots.self-hosted = "https://…"`, `roots.e2b = "e2b://…"`) and the order to try them
    (`order`, default `["self-hosted", "e2b"]`; named roots it omits follow in file order).
    The single root is an alias for one backend and, when set, the only candidate. A
    malformed table or unknown key raises `sandbox_config_invalid`; a repository file cannot
    carry `[sandbox]`. Candidates are tried in order and the first usable one is chosen;
    each one passed over adds `<name>: <reason>` to `sandbox_root_reason`.
  - **Root parsing.** A value is stripped; anything containing `://` is a URL and keeps only
    scheme, host, port and path. A malformed scheme (`sandbox_root_scheme_invalid`), a
    built-in scheme written as a URL (`sandbox_root_scheme_builtin`), and a non-URL value
    with `user:…@` or a query (`sandbox_root_unrecognised`) are refused without a probe and
    rendered as a placeholder. No warning, reason, recorded path or probe argument is built
    from the configured text; all use the parsed form.
  - **Execution gate.** A build calls a non-local backend's methods only if its own driver
    executes on that backend (`panel_invoker._NONLOCAL_EXECUTION_DRIVER`). This release has
    no such driver: root selection passes over every non-local backend before `prepare` and
    before any of its methods, and the leg falls back to local with
    `sandbox_root_fell_back=true` and a reason naming the root and
    `sandbox_placement_driver_unavailable`.
  - **Fail-closed knob.** `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED` (`1`/`true`/`yes`/`on`; any
    unrecognised value is on) refuses a seat leg -- every review-mode leg `_default_spawn`
    launches for a board seat, tree or no tree -- unless the runtime ran it through a remote
    backend's `execute`. Exemption is by execution, never by where placement came from, so
    in this release it refuses every seat leg, before any root is probed or anything is
    staged, with detail `sandbox_placement_required_unavailable`. Advisory-mode boards are
    not seat legs and are not governed by it.
  - **Evidence.** The leg's placement record (`sandbox_placement_backend`,
    `sandbox_placement_receipts`, `sandbox_placement_verified`,
    `sandbox_local_provider_spawns`, `sandbox_snapshot_sha256` -- the authorization's
    digest) is recorded right after `prepare` and travels on
    `PanelLegResult.sandbox_placement_evidence` on every exit, failures included; the
    runner persists it in the leg's `implementation-panel-<leg>.json`. The local spawn count
    is read when the record is serialized. Every exit, including egress teardown raising,
    releases the stage and resets the leg's facts and spawn counter. A brokered leg's broker evidence
    carries the same keys, and `scripts/verify_harden_evidence.py` enumerates them and
    checks the `applied` rule for the recorded backend.
- **Spawned CLI scratch (agent-harness#1147, `fill_child_tmp_env`).** Agent CLIs write
  large scratch of their own; Claude Code uses `$CLAUDE_CODE_TMPDIR`, else the temp dir
  (`/tmp/claude-<uid>`).
  - **What is filled.** Each of `TMPDIR` and `CLAUDE_CODE_TMPDIR` that the child env does
    not already set is judged against its own default destination. If that destination is
    RAM-backed, the variable is set to a private (0700, ours) disk-backed per-user dir that
    is above its free-space floor: `phase-loop/tmp` in the cache dir, else
    `phase-loop-<uid>/tmp` under the temp dir.
  - **Where it applies.** Every review-provider launch: `panel_invoker.launch_provider` /
    `run_provider` apply `child_scratch_env` to the env they launch with, and only the
    named exceptions can opt out (`child_scratch=`). The env builders fill too, so the
    recorded provider evidence matches the launch: board legs and advisory seats
    (`_subscription_env`, the `_exec_leg` explicit-env route), brokered legs including
    bounded Gemini, and both presidents (`_broker_leg_env`). Outside the provider
    interface: executors (`child_executor_env`) and convergence adapters
    (`_child_environment`). The Agent View executor's `claude --bg` goes through the
    interface: `ClaudeAgentViewAdapter`'s default runner calls `run_provider` with an
    explicit env. A bounded brokered agy leg's owned HOME is created in the
    relocated dir as well. A decision returns a `DecidedEnv` labelled
    `PHASE_LOOP_SCRATCH_DECIDED=<decision>` and recorded by object identity
    (`sandbox_policy.decided_scratch`). The test suite's audit hook
    (`tests/_scratch_audit_hook.py`) -- a regression tripwire, not an adversarial boundary
    -- fails any test in which the runtime spawns an agent CLI, named from the runtime's own
    harness registries, with an env object that is not one a decision returned, whatever
    API spawns it. That is the completeness check. `tests/test_agent_cli_scratch_inventory_1147.py` is a static early
    warning: it enumerates every process launch in the package and fails on one with no
    stated decision. It is conservative: an unresolvable use of a launch-capable module (a computed `getattr`,
    `__dict__`, the module as a value, a dynamic import, `exec`/`eval`) needs a stated
    decision too. Env builders (`_broker_subscription_env`, `scrub_subscription_env`)
    take no decision; each route decides after building, so a named exception is never
    refused by a relocation it is exempt from.
  - **Overrides.** A value the caller set is never overridden. The brokered allowlist
    still drops ambient values, so there only the runtime's own dir can appear.
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

## Leg `detail` vocabulary (agent-harness#1096 / #1102)

A `PanelLegResult.detail` is built ONLY from this runtime's closed vocabulary; raw CLI text
never enters it. It is a harness code (`_HARNESS_DETAIL_CODES`, or a
`_HARNESS_DETAIL_CODE_TEMPLATES` pattern whose fields are typed tokens), a failure template
(`_FAILURE_DETAIL_TEMPLATES`: `timeout`, `signal <N>`, `auth_failure`,
`usage_limit[ (resets <HH:MM[, Mon D YYYY]>)]`, the five `env_failure: …` forms,
`tool_denied: …`, `unknown failure[ (exit <N>)]; CLI output: leg-logs/<name>.log | not
retained`), or `<harness code>: <failure template>`. Provenance is by type: a parametrized
harness code is kept only as a `_HarnessCode` built by this runtime; CLI output, exception
messages and PTY tails are never turned into one, and a plain string survives only by
equality with a fixed literal. Every template field is enumerated or checked against the
run's own values. `detail` is a validating data descriptor (write and read), and
`PanelLegResult` may not be subclassed (checked on the exact instance type, not only by
`__init_subclass__`). An unknown failure's raw output is kept
only in a private 0600 per-leg file under the run's stream dir (`leg-logs/`, 0700), which
`detail` names by its run-relative path. That file is never in the verdict JSON, governed
reasons or the board summary. Its name carries only closed fields:
`leg-logs/<registry harness | leg>-<24 hex>.log`.

**Threat model.** I3 defends against untrusted TEXT: CLI stdout/stderr, leg bodies, exception messages and PTY output. None of it can choose or enter `detail`. In-process Python code is trusted runtime code and is out of scope: it can do anything (for example `object.__setattr__` on arbitrary objects, or replacing this module's functions). The exact-type checks (`PanelLegResult` refuses any subclass instance; only an exact `_HarnessCode` / `_LegFailure` has provenance; contents are read with `str.__str__` and re-created as a fresh `_HarnessCode`) close the cheap structural bypasses, but they are not a sandbox against hostile in-process code.

## ABDMODE — Purpose-derived default mode + advisory prompt hygiene · `panel_invoker.py` (#107)

A board's PURPOSE now selects its default panel MODE automatically, so a domain
board (esp. the legal boards) runs in the right posture instead of being hard
code-review-gated. `tests/test_advisor_board_advisory_mode.py`.

- **`_mode_for_purpose(purpose) -> str`.** Code-review-class purposes
  (`code-review`, `premerge-review`) → `"review"` (the strict pre-merge gate:
  bundle is untrusted material to accept/reject, a conforming AGREE / PARTIALLY
  AGREE / DISAGREE verdict is REQUIRED). The known domain purposes (`legal-review`,
  `legal-strategy-review`, `legal-brainstorm`, `brainstorm`, `doc-edit`, `general`)
  → `"advisory"` (analysis / recommendation, no AGREE/DISAGREE verdict). Its success
  artifact is substantial prose (>= 40 characters) whose last line is
  `RECOMMENDATION: <one line>`; `_ADVISORY_INSTRUCTIONS` asks for that line, and a leg
  without it fails closed (agent-harness#1102: outcome is decided only by that
  artifact, never by scanning the text for failure wording). An UNKNOWN purpose → `"review"` (back-compat safe default: a strict
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
  the broker's agy stream with the PRESIDENT's own final instruction (a ruling,
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
- **Brokered, monitored launch** (agent-harness#1001). Every non-native rung launch runs
  under the isolation a review seat gets: `isolated_network` egress (no retained
  capabilities), a single-use broker capability minted by
  `backing.derive_president_leg_authorization` from the operation's lease
  (`prepare_president_isolation_authorization(..., monitoring_policy=)` registers it;
  `activate_/close_president_isolation_authorization` bracket each launch) carrying the
  PRESIDENT operation identity, and the `ParentUnixBroker` over read-only staged bytes (the
  brief and a fixed president instruction marker). Under `heartbeat_only` the transport runs
  with a `_ReviewMonitor` -- no model-thinking deadline, no silence kill; cancellation (the
  board's `cancel_event`) and owner loss are the only stops -- and the gemini rung uses the
  owned heartbeat agy profile, and the Claude rung hands the broker's quiescence latch to its
  TUI session. A missing canonical repository, an empty egress prefix (always -- the
  authorization declares no network egress) or a cancelled operation
  (`president_operation_cancelled`, which stops the walk) is a typed refusal before any provider
  starts. Under BOUNDED monitoring only, a patched transport or launch site is the in-process
  control seam and is not brokered (never evidence), as for review seats; `heartbeat_only` is
  always brokered.
- **Configured ladder** (agent-harness#998 follow-up). `PRESIDENT_LADDER` is the BUILT-IN
  order; the effective order is `advisor_board.config.load_president_ladder(repo_dir, *,
  env, path)`: built-in < the user file's `[president] ladder`
  (`$XDG_CONFIG_HOME/agent-harness/advisor-boards.toml`) < the repository's
  `<repo>/.agent-harness/advisor-boards.toml` (`[president]` only; `[[boards]]` there is
  refused). A ladder is a non-empty list of distinct seat aliases or alias-table model ids
  (`validate_president_ladder`); a malformed one or an unknown key is `BoardConfigError`,
  never a silent fall-back. The seam carries it (`build_president_invoke(..., ladder=)`,
  `PresidentInvoke.ladder`); `invoke_president` walks `effective_president_ladder(invoke)`
  (the seam's ladder, else the built-in), and `rung_index` is the rung's position in THAT
  ladder. The phase-loop runner (`_run_legible_panel`), `advisor-board --landing-tier` and
  `invoke_board`'s auto-wired seam load it; a malformed ladder is refused before any seat
  (`president_ladder_invalid` / CLI exit 2). The user layer follows the environment it is
  given: the auto-wired seam reads it from the passed `base_env` (its `XDG_CONFIG_HOME`,
  else its `HOME`; neither ⇒ no user layer), never from the process HOME.
- **Defer → resume** (EC-PRESROUTE-2). A deferred Fable rung makes `invoke_board` return
  the seats with `PanelResult.needs_native_president` = `{rung, brief_digest,
  findings_digest, prompt}` and no ruling, persisting `president.pending.json`
  (`president.pending.v1`: the request plus the findings and seat verdicts it was built
  from) to `stream_dir`; a deferral without `stream_dir` is refused
  (`president_native_fill_stream_required`). `invoke_board(..., native_president_fill=
  {rung, brief_digest, findings_digest, text})` RESUMES after the same factory /
  revalidation gate and before any seat launches -- no seat is re-run, so seats that would
  word things differently cannot strand the route. The pending request is BOUND to its run
  (resolved-artifact digest, the review-brief digest captured ONCE before any seat runs,
  the board's ordered seat keys, mode, landing policy, president ladder and the seat each
  rung resolves to under the run's `review_seat_aliases`) and the resume
  refuses any difference. A new deferral removes any `president.ruling.json` an earlier
  run left in the stream (after its pending request is written); every persisted ruling
  removes any pending request (so an older request cannot later resume over it). The
  resume and the ruling record resolve the rung through the run's `review_seat_aliases`. The fill is accepted only when that binding matches, the
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
Neither state is a health attestation or permission to terminate.
The record also carries a progress notice (agent-harness#1176). When no genuine
progress has been seen for `stall_notice_s` (default 3600 s; override with
`PHASE_LOOP_REVIEW_STALL_NOTICE_S`), and no progress at all counts from seat
start, `progress_notice` is `seat_progress_stalled`, `progress_notice_count`
counts crossings, and one operator warning with only that code and numbers is
logged. Resumed progress and a terminal observation clear the active notice;
`last_progress_notice` and the count stay as history. The notice never ends the
seat. The record reaches the board: `advisor-board --json` legs carry it as
`review_monitoring`, the text summary prints a `[seat_progress_stalled]` line
per affected seat on stderr, each streamed per-leg verdict file carries it, and
the governed record adds a `seat_progress_stalled` warn finding per seat.
The exact brokered Claude transcript is classified once per change, by
`_claude_transcript_outcome`, into one outcome; the answer parser and the
give-up detector are views of it, so they cannot disagree:
- `answer`: the route's answer parser (the agent-harness#1002/#1077/#1017
  rules; the president route fails closed on any error record in the turn)
  returns text. An accepted answer always wins, whatever follows it. An
  `isApiErrorMessage` record is never answer text. Every record of the answer
  must be a member of the current request (defined below; a sidechain sighting
  counts), so a record that is not evidence for the request never answers it
  either. If the text is not an
  accepted verdict, the leg is handed it back as
  `claude_tui_broker_terminal_nonconforming` instead of waiting.
- `gave_up`: no answer, and the last live record after the current request is
  an `isApiErrorMessage` give-up. The leg ends at once as DEGRADED with
  `claude_seat_output_budget_exhausted` (`error: max_output_tokens`),
  `claude_seat_usage_limited` (`error: rate_limit` with
  `quotaLimits.status: rejected`, a subscription cap, followed by
  `: usage_limit (resets HH:MM, Mon D YYYY)` rendered in UTC from
  `quotaLimits.resetsAt` when present), `claude_seat_rate_limited` (any other
  `rate_limit`) or `claude_seat_provider_api_error`.
- `rejected`: no answer, and the turn ended in a completed (`end_turn` /
  `stop_sequence`) answer carrying a text block that the route's parser refuses.
  The leg ends at once as DEGRADED with `claude_seat_transcript_rejected`.
- `pending`: anything else (an open or capped message, the CLI's resume prompt,
  a newer request, a writer mid-append). A `max_tokens` stop is never terminal.
The "last live record" is decided in APPEND order among the current request's
records, chosen by membership, not position. The current request is the last
user record that is not `isMeta`, carries no tool_result and is not a replay (its
uuid and content recurring, whatever its completion metadata, as in the answer
parser). A record is evidence for it only when it is a new version first seen in
it: its uuid was first seen after the request (a record of an earlier request is
never evidence, wherever it is appended, except an `isApiErrorMessage` record
appended in the current request, which always is); it is not an exact replay of a
version already seen (same uuid, content, `stop_reason` presence and value, and
error flag) nor a stale open copy of a stopped record whose content is unchanged;
and it is not a sidechain record (`isSidechain`), which the answer parser drops
too. An open record first seen in the current request, even a changed version
after its own stop, is still streaming and reads `pending`. An `isApiErrorMessage`
record is terminal event evidence and is never collapsed into an earlier
version of its uuid. Replays and rewritten metadata are not progress. `provider_terminal_state` records the code that
ended the leg. `isApiErrorMessage` matches JSON `true` or the string `"true"`,
on the record or the message. Frozen
broker request/response keys, status literals, and observer envelopes are unchanged.

When staging requires egress isolation, acquisition follows staged-tree and operation
authorization revalidation. Heartbeat-only holds the network helper lifetime through
an owner pipe, with no aggregate expiry; owner exit closes both helpers. Provider
PID ownership is established after network entry but before the capability bounding
set is emptied. Every launch retains the common provider launch seam and broker
threads inherit its ContextVar prefix. EgressUnavailable stays DEGRADED with empty
review text and the exception in detail; sandbox facts describe actual enforcement.

### Qualified Gemini extension (agent-harness#905)

The Linux x64 subscription `agy` entry image must match one member of the closed
set `gemini_heartbeat.QUALIFIED_IMAGES`: 1.2.11 SHA256
`ec7cf797ecb0e1d91ddf3b6d9d6c1d616bb89f78a5b0e43536b72a7fce695f56`, 1.2.12 SHA256
`ce6fdd9e7621ee9ac6eedaa337731ca1f235e412ff57cf9eabcd2aa23b3576ca`, 1.2.14 SHA256
`0d0d3eba22daf29504dd290151c7ed9a4d33b0c6aa0acfc5da27bc3b01d2f029` or 1.2.15 SHA256
`5f9c16b286895f8f7fdecd423883ca256a85077b8acf9a6bc1111761d34df164`. Each member
carries its measured help digest and has its own qualification record; the
evidence catalog and the runtime set must name exactly the same members.
The running Python/kernel must support sealed memfds, pidfds and pidfd signaling;
Python version alone is not a capability check. Unknown images or missing
capabilities refuse before availability/auth effects. Required bwrap mount/gate
flags are checked at admission, before inference. Measure help through the
admitted `agy` filename: the usage line includes that name, while the same
archive member invoked as `antigravity` produces different help bytes. The
measured help defines literal `--print-timeout 0` as waiting for completion.
A quick real completion establishes compatibility; clock controls establish
that old runtime deadlines and silence cannot terminate a healthy heartbeat-only
operation.

The sealed image and deny-all settings are read-only mounts inside a private
HOME owned by the existing PID/mount namespace. A private symlink references the
subscription credential; no credential payload is copied, logged or restored.
Heartbeat credential lookup uses the supplied scrubbed HOME, recording a process
HOME fallback truthfully if HOME is absent. Legitimate refresh writes survive.
The real qualification driver requires an explicit HOME and checks target
presence before and after, without reading its contents.

The broker transports same-session input over stdin (one event when the sealed prompt fits
one chunk, acknowledged chunks otherwise; agent-harness#1175), with no tree
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

The driver lives in the package, `phase_loop_runtime.agy_qualification`; the script
is a shim over it, so an installed runtime can run it too (agent-harness#1076).

### First-use self-qualification (agent-harness#1076)

A non-release `agy` image is admitted only by verifying it, never by trusting it.

- **Admission classes.** Every Gemini heartbeat leg carries exactly one class in
  its profile evidence (`provider_admission_class`): `release_qualified` (digest in
  `QUALIFIED_IMAGES`), `locally_qualified` (a verified local record), or
  `qualification_candidate` (only inside a qualification run; never counted, never
  persisted). The evidence's `provider_image_sha256` is the admitted image's own digest.
- **VerifiedImage.** `PATH` is resolved once (a versioned-install symlink to its final
  target), the target is opened once (`O_NOFOLLOW`, regular file, size cap) and read
  into memory; that buffer is hashed and fills a sealed memfd, which is re-hashed.
  Help measurement, the three live operations, board legs and the president execute
  that memfd (an independent, re-hashed read of it per profile) and never open the path
  again.
- **Admission order.** (1) A release-qualified digest is admitted before any config,
  store or network access. (2) If the user config sets `[agy] self_qualification = false`
  (the repository config cannot), today's `gemini_heartbeat_capability_unavailable`
  refusal is returned and nothing else is read. (3) A `failed` entry refuses
  (`gemini_heartbeat_self_qualification_failed`) with no execution. (4) Help is measured
  from the memfd only after a `provenance` entry verifies against the live key; the
  `qualified` entry is then verified against the full live key, including that help
  digest. (5) Otherwise the image is absent: legs and the president refuse; only the
  whole-board preflight (`_preflight_gemini_heartbeat`) and `phase-loop
  agy-qualification run` go on to first use. Legs re-admit by lookup rather than
  receiving the preflight's Admission object; any future cross-process hand-off of an
  image memfd must reuse the worker's seal check.
- **Provenance** (coordinator process, nothing executes). Host platform from the running
  host (D4: `linux-{x64,arm64}[-musl]`); the newest `agy_provenance.RECENCY_WINDOW`
  stable releases (no prerelease, no draft); the exact platform asset; its URL equal to
  `https://github.com/google-antigravity/antigravity-cli/releases/download/<tag>/<asset>`;
  a strict `sha256:<hex>` asset digest equal to the streamed archive digest; exactly one
  regular-file `antigravity` member (duplicates and links refuse), stream-hashed and
  never extracted, equal to the image digest. The transport sends no credentials, has
  no proxy support, uses the interpreter's compiled-in OpenSSL trust store (not
  `SSL_CERT_FILE`/`SSL_CERT_DIR`), and follows at most three https redirects within
  GitHub's download hosts. Fetch failure refuses `gemini_heartbeat_provenance_unavailable`;
  no match refuses `gemini_heartbeat_provenance_unverified`.
- **Behaviour.** Only after the provenance entry is written: help, then the three live
  operations through the packaged driver and the release path's own validators. All
  passing writes the `qualified` entry. Any observed isolation or identity violation (an
  executable outside the helper policy, an unqualified provider image, a writable image
  mount, an unverified network policy, a surviving process, a rejected record) writes a
  `failed` entry at whatever stage it was seen (until `agy-qualification clear`). Only a
  provider that was never observed running, a completion the provider did not answer
  (HTTP 5xx, quota, auth), and our own local failure are transient, and cancellation writes
  nothing. Transients are counted per key; the third consecutive one writes a `failed`
  entry, success resets the count, and `agy-qualification clear` removes it. A lock waiter
  that finds a transient recorded while it waited refuses without running or counting.
- **Worker gate.** The qualification worker receives the image as an inherited fd and,
  before hashing, requires a regular-file memfd with `F_SEAL_WRITE`, `F_SEAL_GROW`,
  `F_SEAL_SHRINK` and `F_SEAL_SEAL` (`F_SEAL_FUTURE_WRITE` alone is refused). It admits
  the fd as a candidate only if its digest is a release constant (the manual shim and the
  upstream watch's prepared tree) or has a provenance entry for the current runtime
  identity. It sets `PR_SET_PDEATHSIG`, so a killed coordinator leaves no worker.
- **Store.** `$XDG_STATE_HOME/phase-loop/agy-qualification/hosts/<machine>/`, per user,
  namespaced by machine-id. Directories 0700 and files 0600, owned by the euid, opened
  `O_NOFOLLOW`; otherwise the store is absent to lookups and first use refuses
  (`gemini_heartbeat_self_qualification_store_unsafe`). Every entry is HMAC-SHA256'd under
  a per-host key over its type, the euid, the machine-id and a context recomputed from the
  live key. The qualification entries (`provenance`, `qualified`, `failed`, `member_cache`,
  `transient`) bind the image digest, platform and runtime identity, plus the asset name,
  profile id or help digest as the type requires. The watch's `watch_push` entry binds the
  branch, the version and the route-core base.
  Without a readable machine-id, self-qualification refuses; the release path is unaffected.
- **Lock.** One `flock` per host namespace; waiters are cancellable and heartbeat (the board
  preflight writes a content-free `agy-qualification.json` progress record into the
  board's stream directory and a line on stderr, throttled per phase), and re-check the
  store after acquiring. Qualification happens once per key per user per host.
- **Runtime identity (D2).** `__version__` plus the digests of the installed
  `agy_qualification.ROUTE_CORE` files (`gemini_heartbeat.py`, `agy_qualification.py`,
  `agy_provenance.py`), the same tuple `verify_qualified_agy_image.py --route-core` checks.
- **Counting (D1).** At `governed_review`'s gate (the rule itself is
  `agy_qualification.counts_toward_landing`), a usable heartbeat Gemini leg is a vote at every
  tier only if its recorded class is `release_qualified` or `locally_qualified`. A
  candidate leg, or a leg with no class (including legs from boards run before the class
  existed: re-run the board), cannot approve; a blocking verdict from it still blocks. The
  president's input builder applies the same rule (`agy_qualification.president_input_items`):
  an uncounted non-blocking leg contributes a `not counted` item instead of its review, and an
  uncounted `DISAGREE` keeps its objections. A leg is an agy leg by name or by the
  coordinator's profile evidence. A
  Gemini leg whose admitted digest appears in the reviewed artifact is flagged
  (`gemini_seat_reviews_its_own_pin`, non-gating). Boards admit with the installed base
  runtime, never the reviewed tree.
- **Upstream watch.** `phase-loop agy-qualification watch` (a host timer on a subscribed
  host; see `docs/ops/agy-upstream-watch.md`) proposes only the Linux x64 glibc release
  route, from a fresh checkout of `main`, and opens a draft PR; it never merges. Each tick
  makes exactly one ref write (a fresh `agy-watch/<version>-<utc>-<random>` branch, pushed
  with an empty-expected-value lease and accepted only when `--porcelain` reports that exact
  ref as newly created) and one object create (the PR). It never updates, force-pushes,
  adopts, closes, edits or deletes anything that existed before the tick; the new PR body
  names the own older PRs it supersedes for a maintainer to close. It requires `origin` to
  have exactly one push URL, pushes to the remote NAME `origin` (never to the printed URL,
  which git would resolve again). It compares no URL strings; a `--dry-run` pre-flight
  must print exactly one `To` block, and the real push exactly one `To` block and one `*` row
  for exactly the new ref. Both pushes carry `--no-verify`; the bot host's git/ssh
  configuration is trusted. It pre-flights its store, records the
  verified pushed oid in its own `watch_push` entry, and reads both the record and the
  created PR back (the PR body's copy is display-only). "Up to date" requires that local record, `headRefOid` and `ls-remote` to
  agree. It refuses when it cannot prove its open-PR listing complete.

## ABDFALSIFY — Executable review findings (IF-0-EXECFIND-1)

An optional `falsifier` attachment names one `FindingFalsifier` with
`finding_id`, `new_test_path`, `expected_nodeid`, and a unified `diff` creating
only `phase-loop-runtime/tests/test_finding_<finding_id>.py`. A
`FindingFalsifierAttachment` contains a tuple of these entries with unique
finding IDs. The attachment is a non-field property on `PanelLegResult`; it
does not change the serialized leg or board schema. The seat supplies text,
never an executable command or a claimed test outcome.

`run_finding_falsifier` accepts one attached falsifier, board `seat_key`, canonical
repository, positive wall-clock/output bounds, and a single-use
`FalsifierIsolationAuthorization` bound to the exact 40-character `reviewed_sha`.
Its identity is `public_board_falsifier.v1`; its child has no credentials,
network egress, or live-tree mount. The source must be clean at that SHA.
Before applying the diff, the staged materialized path set, bytes, symlink
targets, and executable bits must equal the reviewed Git tree, including no
ignored extra files. Only the named pytest node runs in the staged clone.

Each run stages its own tree from the canonical repository at the head under
test, never from a seat's tree, and copies installed dependency files into a
per-run import root (copies, never links; uv's `--link-mode=copy` equivalent).
Those two trees are the run's protected objects: every regular file in them,
`.git` included, must have a link count of exactly one before the node starts
and after it exits, or the run is `error` (agent-harness#1134). The shared system
interpreter is read-only to the run and is not a protected object. The runner
resolves `/usr/bin/python3` once and launches exactly that file. Falsifier runs
execute without site processing (`-S`): no `.pth`, `sitecustomize` or
`usercustomize` runs and no host site directory is on `sys.path`, so the
interpreter's inputs are its standard-library entries plus the run's explicit
staged paths. Every dependency, pytest included, comes from the per-run staged
dependency root (a distribution without a RECORD is staged from its declared
top-level modules); a host site directory on the falsifier path is refused as
`falsifier_host_site_packages_refused`. The measured set is the launched
interpreter's own `sys.path` under the same flags and environment, so the
inventory and the launch are identical by construction. Every entry is
digested before and after the run: archive entries and `.pth`, archive and
customize files by content, directories by an lstat manifest (mode, size,
device, inode, mtime, ctime), and every symlink target outside the set followed
and hashed by content. An entry the runner cannot digest fails closed, and a
changed scope or digest is `error`.
Before staging, the canonical repository must not be reachable through any
system-root mount (compared by device and in-filesystem path, not by pathname),
and a repository that contains any mount point is refused as
`falsifier_repository_submount_refused`. The record schema is unchanged; the reason
stays in the result's `detail`.

The frozen outcome tuple is `red_on_head`, `green_on_head`, `apply_failed`,
`node_missing`, `error`. Pytest emits JUnit, but the recorded outcome comes from
the wrapper's reported call-phase result; the test-writable XML is not read as
authority. Seat-authored and reviewed-tree Python (including conftest) run
in the wrapper's process and can forge
the reported status, including a parent-keyed frame. RED and GREEN are therefore
observed, untrusted results: neither binds nor dismisses a finding. Drift,
expiry, unavailable isolation, and incomplete evidence are `error`; every
valid attached result remains a blocking `finding_receipt` pending a president
ruling. The metadata-only
`finding_falsifier.v1` record has exactly `schema`,
`authorization_identity`, `seat_key`, `reviewed_sha`, `finding_id`, `nodeid`,
`outcome`, `red_output_digest`, `diff_digest`, `wall_clock_bound_s`, and
`output_cap_bytes`. `diff_digest` hashes the offered UTF-8 diff bytes;
`red_output_digest` hashes separately captured stdout followed by stderr
and is null unless RED. The caller binds the record with SHA-256 over
canonical JSON (`sort_keys=True`, compact separators, `ensure_ascii=False`).
The full freeze and golden values live in
`tests/data/execfind_falsifier_attachment_v1.golden.json`.
