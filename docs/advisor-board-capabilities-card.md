# Advisor Board — Capabilities Card

The **Advisor Board** is a customizable, model-first, multi-harness review board
(`phase_loop_runtime.advisor_board` over the `phase_loop_runtime.panel_invoker`
runtime primitive). It evolved the fixed 3-vendor `advisor-panel` into a named,
purpose-tagged, open-ended board of **seats**, where a seat is a *cognition*
(`{model, effort, harness?, lens?, auth?, backing?}`) — the harness is a
defaulted-but-overridable execution lane, not the primary key.

This card is the release reference for **how the board is invoked**, **which
models run on which harnesses**, **the built-in board presets**, and **how to add
a custom board**. It is derived from the live registries / install code so it
cannot drift; a `pytest` smoke (`tests/test_advisor_board_alias_install.py`,
`tests/test_advisor_board_integration.py`) keeps the skill names and matrix honest.

---

## Skill names — the `<harness>-advisor-board` rule

The board is installed **per harness** under a harness prefix. Invoke it as
`<harness>-advisor-board`:

| Harness    | Canonical skill (invoke this) | Historical alias (still resolves) |
| ---------- | ----------------------------- | --------------------------------- |
| `claude`   | `claude-advisor-board`        | `claude-advisor-panel`            |
| `codex`    | `codex-advisor-board`         | `codex-advisor-panel`             |
| `gemini`   | `gemini-advisor-board`        | `gemini-advisor-panel`            |
| `opencode` | `opencode-advisor-board`      | `opencode-advisor-panel`          |

The supported prefixes are exactly the installed skill roots
(`skill_paths.HARNESS_DEFAULT_SKILL_ROOTS`): **claude, codex, gemini, opencode**.

**The alias exception.** The prior name `advisor-panel` remains a working alias of
`advisor-board`. On every install, `install_skills` installs the canonical
`advisor-board` a second time under the prefixed alias name
`<harness>-advisor-panel`, copied FROM the canonical source — so
`/claude-advisor-panel` (the maintainer's habitual invocation) resolves to
**today's** advisor-board, and a stale pre-rename `<harness>-advisor-panel` dir is
overwritten (content refreshed, orphan files pruned), never left drifting.
`skill_install.canonical_skill_name("<harness>-advisor-panel")` maps back to
`advisor-board` for callers that resolve by string.

> `advisor-board` is the *unprefixed* canonical skill inside the neutral bundle
> (`phase-loop-skills/advisor-board/`); the `<harness>-` prefix is added at install.

---

## Model × harness matrix

A seat is valid only when its `(model, harness)` pairing is registered — a
cross-vendor pairing (e.g. `claude:gpt-6-astra`) is **rejected at config time** with an
actionable message, before any subprocess is spawned. Source of truth:
`DefaultHarnessRegistry` / `DefaultModelRegistry` / `DefaultCompatibilityMatrix`.

### Harnesses (execution lanes)

| Harness    | CLI            | Auth lanes              | Backing    |
| ---------- | -------------- | ----------------------- | ---------- |
| `claude`   | `claude`       | subscription, api_key   | homebrew   |
| `codex`    | `codex`        | subscription, api_key   | homebrew   |
| `gemini`   | `agy`          | subscription, api_key   | homebrew   |
| `opencode` | `opencode`     | subscription, api_key   | omnigent   |
| `pi`       | `pi`           | subscription, api_key   | omnigent   |
| `cursor`   | `cursor-agent` | subscription, api_key   | omnigent   |

- **homebrew** = the built-3 native launch (claude native/TUI, codex, gemini) + the
  native host leg. Byte-for-byte the legacy panel for the `default` board.
- **omnigent** = harness breadth (opencode/pi, and cursor/amp when the live
  `GET /v1/harnesses` catalog reports them) routed through omniagent-plus →
  Omnigent v0.4.0, **opt-in and fail-closed** (an unavailable lane skips-with-warning,
  never a silent homebrew fallback).

### Models

| Model            | Vendor family | Default lane | Runnable by       | Effort ceiling |
| ---------------- | ------------- | ------------ | ----------------- | -------------- |
| `gpt-6-astra`    | codex         | `codex`      | codex, opencode   | max            |
| `gpt-5.6-sol`    | codex         | `codex`      | codex, opencode   | max            |
| `claude-sonnet-5`| claude        | `claude`     | claude            | max            |
| `claude-opus-4-8`| claude        | `claude`     | claude            | max            |
| `claude-opus-5`  | claude        | `claude`     | claude            | max            |
| `claude-haiku-4-5-20251001`| claude | `claude`     | claude            | max            |
| `claude-fable-5-1` | claude      | `claude`     | claude            | max            |
| `claude-fable-5` | claude        | `claude`     | claude            | max            |
| `Gemini 3.1 Pro` | gemini        | `gemini`     | gemini            | max            |
| `gemini-3.8-flash` | gemini      | `gemini`     | gemini            | high           |
| `gemini-3.7-flash` | gemini      | `gemini`     | gemini            | high           |
| `gemini-3.6-flash` | gemini      | `gemini`     | gemini            | high           |
| `grok-4.6`       | grok          | `grok`       | grok              | max            |
| `grok-4.5`       | grok          | `grok`       | grok              | max            |

**Effort is model-first `{model, effort}`**, split out of the model name and mapped
per harness by `render_seat_invocation`: `claude` → `--effort <level>`, `codex` →
`-c model_reasoning_effort=<xhigh|high|…>`, `gemini` → effort baked into the model
token (`gemini-3.8-flash-high`; legacy display names such as
`"Gemini 3.1 Pro (High)"` remain accepted). Canonical effort levels: `low, medium, high, max`.

**Auth is subscription-default, never-silent-key.** A subscription seat actively
scrubs *every* vendor API-key var from the subprocess env / gateway payload; an
api-key seat is reachable only behind `Board.allow_api_key_fallback` and injects
ONLY its own vendor's key. Claude Fable/Opus seats are stricter: API-key fallback
is forbidden, custom request headers and alternate endpoint/cloud-provider/helper selectors are scrubbed,
run-isolated settings disable API-key helpers, and the TUI launches only after a
metadata-only auth probe proves a first-party `claude.ai` subscription. A board
can't even be constructed holding an api-key seat without opting in.

**Claude execution is TUI-only.** Fable and Opus require the homebrew backing and
use the existing Claude Code self-PTY adapter with the exact requested model.
An alternate backing reports `tui_backing_required` before gateway access. No API, SDK, Messages, direct
HTTP, or native Task/subagent path may fulfill those seats. A host that cannot
run the adapter reports `tui_adapter_required`; an unproven subscription reports
`subscription_auth_unproven`. Today's adapter has no typed classifier-refusal
capability, so refusal-looking text never triggers fallback. The bounded future
policy permits one Opus TUI retry only for typed classifier refusal plus an
independent defensive-security attestation, then fails closed.

---

## Board presets

Nine built-in presets (`advisor_board.presets`), each a named, purpose-tagged,
open-ended seat list. Load via `load_boards()` (self-validates every preset against
the matrix at load time).

| Preset                  | Purpose               | Seats (model · effort · harness · lens) |
| ----------------------- | --------------------- | ---------------------------------------- |
| `default`               | premerge-review       | gpt-6-astra · max · codex · red-team ; gemini-3.8-flash · high · gemini · alternative-approach ; claude-fable-5-1 · max · claude · correctness ; grok-4.6 · max · grok · adversarial |
| `code-review`           | code-review           | grok-4.6 · max · grok · adversarial ; claude-fable-5-1 · max · claude · correctness ; gpt-6-astra · max · codex · red-team ; gemini-3.8-flash · high · gemini · alternative-approach |
| `brainstorm`            | brainstorm            | claude-sonnet-5 · high · claude · adversarial ; gpt-6-astra · high · codex · supportive ; gemini-3.8-flash · high · gemini · lateral |
| `doc-edit`              | doc-edit              | claude-sonnet-5 · medium · claude · copyedit ; gpt-6-astra · medium · codex · structure |
| `legal-review`          | legal-review          | gpt-6-astra · max · codex · opposing-counsel ; gemini-3.8-flash · high · gemini · risk-liability ; claude-fable-5-1 · max · claude · authority-verification |
| `legal-strategy-review` | legal-strategy-review | gpt-6-astra · max · codex · red-team ; gemini-3.8-flash · high · gemini · alternatives ; claude-fable-5-1 · max · claude · downside-ethics |
| `legal-brainstorm`      | legal-brainstorm      | claude-sonnet-5 · high · claude · aggressive ; gpt-6-astra · high · codex · conservative ; gemini-3.8-flash · high · gemini · creative |
| `general`               | general               | gpt-6-astra · max · codex · adversarial ; gemini-3.8-flash · high · gemini · alternative ; claude-fable-5-1 · max · claude · completeness |
| `solo`                  | general               | claude-fable-5-1 · max · claude · completeness |

**Catch-alls for unmodeled tasks.** `general` (top-tier cross-vendor panel) and
`solo` (one top-end member) are the domain-agnostic fallbacks — hand either any task
and it convenes frontier review without a pre-defined domain board. Both default to
top-end models: an unanticipated task is not assumed low-stakes, so the safe default
is frontier; dial down explicitly when a task is known-cheap.

**Parallel by default.** `invoke_board` / `invoke_panel` run their legs
CONCURRENTLY out of the box (a bounded thread pool — wall-clock ≈ slowest leg, not
the sum). `max_concurrency` is the knob: `None` (default) = parallel; `1` =
sequential (the opt-in escape hatch for debugging / rate-limits / a constrained
host); `N` = cap at N. Result order is always preserved regardless of finish order.

**Review-class boards run on Fable, never the implementer.** Pre-merge and legal
review are mid-tier decisions where being wrong is expensive, so the review-class
boards (`default`, `code-review`, `legal-review`, `legal-strategy-review`) seat
Fable (`claude-fable-5-1`) on the claude lane, decoupled from the implementer model
`claude-sonnet-5` (`panel_invoker.DEFAULT_LEG_MODELS["claude"]` is the single source
of truth, so the live governed gates `governed_review` / `governed_premerge` also
review on Fable). The divergent-thinking boards (`brainstorm`, `doc-edit`,
`legal-brainstorm`) deliberately keep Sonnet, where a diverse / cheap voice is the
right tool. The legal boards encode the PRIMARY review lens per seat; the richer
4-lens-per-seat + apex-Opus seat + verify-round + retrieval-grounded
citation-verification treatment is a documented deep-seat follow-on
(`advisor_board/CONTRACTS.md`), not yet built.

`default` **is** the shared four-vendor fixture board (`fixtures.DEFAULT_BOARD`).
The explicit `PANEL_LEGS == (codex, gemini, claude)` and `invoke_panel` API stay
separately frozen for legacy callers (proven in `tests/test_advisor_board_golden.py`).

The president availability ladder is Fable → Sol → Grok 4.6 → Gemini 3.8 Flash
(`Sol` is the GPT seat alias: `gpt-6-astra` by default, `gpt-5.6-sol` accepted as an explicit legacy id).
It advances only on typed unavailability, not on disagreement or a blocking ruling.
`requires_president` landing policies execute it (`invoke_board(president_invoke=)`)
and fail the landing closed without a ruling; today no HARDEN-authorized president
execution operation exists, so a seated rung reports
`president_execution_route_unavailable` rather than riding a review leg
(`advisor_board/CONTRACTS.md` → ABDPRES).

### Invoking a board

```
advisor-board <artifact>                       # bare → the `default` board
advisor-board --board code-review <artifact>   # a named preset
advisor-board --seats gpt-6-astra:max:codex <art>  # ad-hoc seats (model:effort[:harness])
```

Runtime entry point: `panel_invoker.invoke_board(board, artifact, ...)`. Legacy
callers keep using `panel_invoker.invoke_panel(...)` unchanged.

**Choose inline, read-file-and-stage, or true by-reference material.** Use
`artifact="..."` only for small inline text. Use `artifact_ref="path/to/bundle.md"`
(or an ordered list of paths) and `brief_ref="path/to/brief.md"` when you want the
runtime to read local files and stage their bytes into `review-bundle.md` or
`review-instructions.md`; this keeps the caller context lean but every leg still
receives the file contents. Use `context_refs=["/path/to/material.pdf"]` for the
true by-reference mode: the runtime stages a path and metadata manifest instead of
file bytes, and each leg must intentionally inspect the referenced local file with
its own tools.

`artifact_ref` wins over `artifact` if both are given. Missing `artifact_ref`,
`brief_ref`, and hard `context_refs` paths fail closed. `context_refs_soft_warn=True`
can emit `MISSING` or `UNREADABLE` manifest entries instead. Pathnames and hashes can
still disclose sensitive metadata, and a leg may disclose file contents after it
intentionally inspects a referenced path unless an output policy forbids disclosure.
Remote providers, sandboxed backings, or service-backed harnesses may not share the
caller host's local file access, so `context_refs` is safest only when the selected
provider/backing can see the same filesystem. Entry points: `invoke_panel` /
`invoke_board` / `invoke_panel_request`.

**Legs run in parallel by default.** `invoke_board` / `invoke_panel` fan their
seats/legs out across a bounded thread pool, so wall-clock is ~`max(leg)`, not
`sum(leg)` (the legs are blocking subprocess I/O). Both take a single
`max_concurrency` knob — **parallel by default** (`None` → bounded by
`min(len(seats), 8)`); pass **`max_concurrency=1` for sequential** (debugging, a
throttled provider, a constrained host), or `N` to cap. Seat order and
fail-closed-per-seat semantics are identical regardless; the governed gates thread
the knob through, defaulting to parallel.

### Opt-in governed web research

`ResearchPolicy(enabled=True)` gives enforceable homebrew Codex and Claude TUI
seats session-local access to PMCP `scoped_advisor_audit.v1`. The integration
pins `pmcp==1.20.0`, requires its exact capability declaration, and exposes only
`gateway.health`, `gateway.catalog_search`, `gateway.describe`, and
`gateway.invoke`. PMCP then permits only Firecrawl and Bright Data search/scrape/
crawl/query tools. Resources, prompts, ambient MCP servers, and mutation tools are
absent or denied. The runtime supplies run-local, highest-precedence definitions for
both approved providers plus a final manifest overlay, and strips inherited `PMCP_*`
controls before launch. Codex native web search/apps and Claude's Chrome integration
are disabled. Claude receives the same four PMCP controls in its tool-availability and
pre-approval CLI lists, receives only the staged review directory rather than the live
repository, and remains subscription-TUI only; research does not introduce an API,
SDK, direct-HTTP, gateway, or native Task fallback for Claude seats.

Each seat gets a unique lock directory, audit file, and typed run/seat/evidence
correlations. A seat cannot claim successful research from its prose: the runtime
waits for PMCP's fsynced `audit.completed` record, validates the contiguous audit,
fails the whole research ledger if any invocation has mismatched run/seat/evidence
correlations, and attaches only a privacy-safe ledger plus policy/audit/ledger digests. Source
references are hashed; raw queries, results, credentials, and authorization headers
are not emitted through observability. Gemini's `agy` adapter, Grok (which lacks a
proven session-local user-config isolation switch), Omnigent seats, native host
legs, and custom spawn callbacks currently report
`UNAVAILABLE/research_profile_unenforceable` when research is enabled.

```python
from dataclasses import replace
from phase_loop_runtime.advisor_board import ResearchPolicy
from phase_loop_runtime.advisor_board.composition import compose_review_board
from phase_loop_runtime.panel_invoker import invoke_board

board = replace(
    compose_review_board(),
    research_policy=ResearchPolicy(enabled=True),
)
result = invoke_board(board, "", artifact_ref="path/to/research-brief.md")
for leg in result.legs:
    print(leg.seat_key, leg.status, leg.research_status, leg.research_ledger_digest)
```

---

## Failure diagnostics and streaming retention

Brokered Gemini errors and Claude TUI operational failures retain a bounded,
credential-scrubbed explanation in the existing `PanelLegResult.detail` channel.
The adapter's return code is included. Diagnostics do not replace review text,
change a verdict, or turn an unusable seat into approval.
Known credential forms are redacted before truncation; escaped/encoded log lines
are suppressed conservatively. This scrubber is not a general declassification
boundary for arbitrary provider content.

With the existing `stream_dir` opt-in, a leg carrying diagnostics or broker
metadata additionally writes an immutable
`leg-<index>-<digest>.diagnostic.json` sidecar. Its independent schema,
`advisor_leg_diagnostic.v1`, binds the exact verdict-file bytes, local publication
identity, seat-key digest,
and allowlisted input/output digests, counts, Gemini stream outcome, timing
limits and cleanup observations. It omits arbitrary broker fields, raw sessions,
provider responses, prompts, argument lists and credential paths. The existing
verdict JSON, dataclass serialization and HARDEN evidence schema are unchanged.

Diagnostic files use mode 0600 and exclusive, descriptor-relative publication
with file/directory synchronization. The diagnostic writer requires a canonical,
owner-controlled directory and rejects symlinked ancestors, conflicting files,
hard links and unsafe modes. Existing sidecars are not overwritten. Streaming
remains best-effort: a failed write does not change the leg result. Inspect the
non-serializing `leg.diagnostic_retention` receipt (`saved` with filename/hash,
or `failed`), including from `on_leg_complete`; `None` means no capture was
attempted. A receipt is marked `pending` while its write is in progress. Without
`stream_dir`, no sidecar is written. These receipts are not approval evidence.
Hosts without the required POSIX descriptor operations retain ordinary verdict
streaming; diagnostic capture reports failure rather than using an unsafe fallback.

For disk-only correlation, match both `verdict_sha256` and
`verdict_file_identity` (device, inode, size, mtime_ns and post-publication
ctime_ns). Read and check the verdict through one no-follow descriptor, checking
identity before and after hashing. Identical verdict bytes from a new publication
must not select an older sidecar. A copied or restored artifact whose identity no
longer matches is historical, not a proven current binding. This is not protection
against privileged filesystem identity recreation or snapshot rollback.

The binding identifies the **currently present local verdict artifact**, not the
latest attempted review: a failed verdict replacement can leave a previously
saved pair intact. Use the consolidated result and current run state to establish
attempt status; never infer freshness or approval solely from a retained pair.

These sidecars retain diagnostic metadata, **not raw sessions**. They cannot
reconstruct deleted raw data. The separate private capture below is not enabled
by `stream_dir`. See agent-harness#369, agent-harness#525 and agent-harness#734.

### Explicit private session capture

Python callers can opt in around an already-authorized brokered Claude/Gemini
invocation without changing its public signature:

```python
from phase_loop_runtime.private_session_capture import PrivateSessionCapture

# Existing absolute canonical directory, owned by this user with mode 0700.
with PrivateSessionCapture(private_root) as capture:
    result = invoke_board(board, artifact, **authorized_arguments)
# Inspect capture.receipts privately; a receipt is not a reviewer verdict.
```

There is no CLI flag or implicit environment opt-in. This scope does not grant
HARDEN authority, change the requested model/route, or enable a provider retry.
Only brokered Claude/Gemini attempts are captured; skipped seats, injected test
spawns and other routes need not create receipts. An empty receipt list is not
proof that a requested seat was captured.

Each attempt gets a random mode-0700 directory with exclusively created mode-0600
files. Capture includes the staged bundle and instructions, intended inline
prompt, raw Gemini stdout/stderr, and Claude PTY bytes plus the exact newly
allocated session JSONL when present. Numbered pipe files distinguish existing
adapter attempts. `stdin-N.bin` records prepared input, not proof every byte was
delivered or consumed; existing protocol acknowledgements retain that role.
No adjacent sessions, credential stores, Gemini temporary-home contents, or
native debug/trajectory stores are copied. Default temporary-home cleanup stays
unchanged.

Raw stream bytes are captured before decoding, including non-UTF-8 bytes and
output drained during the existing process-group shutdown. Claude's exact JSONL
is copied, synchronized and verified before retirement. Retirement checks the
captured inode and content again through a private quarantine; replacement or
capture failure preserves the remaining source. An absent transcript is recorded
as missing, never reconstructed. Unproven process shutdown remains a fatal error
and preserves the source; capture failures cannot replace that authority.

The `private_provider_session.v1` manifest separates capture status from provider
outcome. A `saved` capture can contain a failed or unavailable provider response.
Preflight rejection may produce inputs only; absent files are not proof that a
provider emitted no data. Files include byte counts and hashes, while the receipt
binds the manifest hash. A private source locator records where an original or
quarantined Claude transcript may still need recovery; it is not exported into
verdicts or HARDEN evidence. Canonical owner-controlled paths, no-follow file
descriptors, stable inode checks, final-path readback and file/directory `fsync`
establish capture-time integrity. They do not prevent later same-user changes or
make restored files current review evidence.

Defaults limit each attempt to 32 MiB and each scope to 128 MiB, including
manifests; both limits can be set explicitly up to a 1 GiB scope ceiling. Limits
are not a rolling disk-retention policy. Exhaustion, unsafe paths or storage/read
failure produce a failed receipt and propagate `PrivateCaptureError`, never an
ordinary reviewer verdict. Existing provider termination runs before that error
escapes. Prefix files remain private and incomplete; even the manifest may be
missing or incomplete if storage fails. No successful-recovery claim follows from
mere file presence. Storage work uses the existing caller deadline; this feature
does not extend liveness thresholds.

Raw captures and their receipts can contain sensitive prompts, provider output
and local source paths. They are **not redacted, encrypted, remotely backed up,
or safe to attach to public issues**. Keep the root private and outside source
control; archive or dispose of it through a separately authorized workflow. This
opt-in requires POSIX descriptor operations, and Claude retirement requires
no-clobber rename support; unsupported hosts fail capture instead of weakening
the checks. Without this scope, existing capture/cleanup behavior is unchanged.

## How to add a custom board

Boards layer over the presets from
`$XDG_CONFIG_HOME/agent-harness/advisor-boards.toml`
(`advisor_board.board_config_path()`; shape frozen by
`fixtures/advisor-boards.example.toml`). A user board with the same name as a
preset overrides it.

```toml
# ~/.config/agent-harness/advisor-boards.toml
default_board = "my-review"          # optional: what bare `advisor-board` resolves to

[[boards]]
name = "my-review"
purpose = "code-review"
research_enabled = true                 # optional; default false, exact PMCP profile

  [[boards.seats]]
  model = "gpt-6-astra"                  # must be a registered model…
  effort = "high"                    # …at/under its effort ceiling…
  harness = "codex"                  # …on a compatible lane (else config-time reject)

  [[boards.seats]]
  model = "claude-sonnet-5"
  effort = "max"
  harness = "claude"
  lens = "adversarial"               # optional thinking lens; distinguishes same-model seats
```

Rules enforced at `load_boards()` time (never a silent drop):

- an unknown config key → clear error;
- an unregistered model or a cross-vendor `(model, harness)` pairing → rejected
  with the valid lanes named;
- an effort above the model's ceiling → rejected;
- `allow_api_key_fallback` defaults `false`; an api-key seat without opting in is
  rejected (never-silent-key);
- `backing` defaults `homebrew`; set `omnigent` for a breadth-harness seat (routes
  through the gateway when available, skips-with-warning when not).

Two seats that differ only by `lens` (or model/effort) are fully expressible: results
are keyed by **seat position** with `seat.seat_key` as the human-readable label, so
a two-same-vendor board is not collapsed.

---

## Migration note — for existing `advisor-panel` callers

**Nothing you have breaks.** The rename is additive and back-compat by construction:

1. **The name.** `advisor-panel` → `advisor-board`. The old name remains a working
   alias: `/<harness>-advisor-panel` still resolves (to the current advisor-board),
   agent instructions that say "advisor-panel" keep working, and
   `canonical_skill_name()` maps the alias back. There is **no** action required to
   keep an existing invocation working; prefer `<harness>-advisor-board` for new
   instructions.

2. **The runtime API.** `panel_invoker.invoke_panel(artifact, legs, ...)` keeps the
   same positional contract and disabled behavior. It has one additive keyword-only
   `research_policy=None` parameter. The live governed gates
   (`governed_review`, `governed_premerge`) still call it. The new
   `invoke_board(board, artifact, ...)` seam is *additive*; migrate to it only when
   you want boards/presets/breadth. When you do, the `default` board reproduces the
   legacy 3-leg run byte-for-byte on launch order, per-leg argv/env/timeout, status,
   text, and failure semantics.

   - **One intentional result-shape enrichment:** `invoke_board` populates
     `PanelLegResult.seat_key` with a richer per-seat label (e.g.
     `codex:gpt-6-astra:max`) instead of the bare leg (`codex`). `.leg` is preserved, so
     any caller keying on `.leg` / `.status` / `.usable` is unaffected; this only
     *adds* the ability to tell two same-vendor seats apart. This is the sole
     contract-sanctioned delta (ABDRESOLVE finding 4), asserted explicitly in the
     golden proof.

3. **The presets.** If you invoked the panel for a premerge review, that is now the
   `default` board (bare `advisor-board`). For a lens-differentiated review reach for
   `--board code-review`; for divergent thinking, `--board brainstorm`. Define your
   own in `advisor-boards.toml` (above).

4. **Auth / observability posture is unchanged for the default path.** Subscription
   stays the default lane; the default board scrubs vendor keys exactly as before;
   `sink=None` (the default) emits no observability envelope, so the live default
   panel stays byte-neutral.
