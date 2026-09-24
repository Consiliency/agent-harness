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

- **homebrew** = the built-3 CLI-lane launch (claude TUI, codex, gemini) + the
  in-process host leg. Byte-for-byte the legacy panel for the `default` board.
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
| `claude-opus-5-5`  | claude      | `claude`     | claude            | max            |
| `claude-fable-5-1` | claude      | `claude`     | claude            | max            |
| `claude-fable-5` | claude        | `claude`     | claude            | max            |
| `Gemini 3.1 Pro` | gemini        | `gemini`     | gemini            | max            |
| `gemini-3.8-flash` | gemini      | `gemini`     | gemini            | high           |
| `gemini-3.7-flash` | gemini      | `gemini`     | gemini            | high           |
| `gemini-3.6-flash` | gemini      | `gemini`     | gemini            | high           |
| `grok-4.7`       | grok          | `grok`       | grok              | max            |
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
HTTP path may fulfill those seats. Under Claude Code the seat defers as
`under_claude_code` with a native-fill request the driving session fills natively
(EC-REVIEWTRUTH-14); a non-native host that cannot run the adapter reports
`tui_adapter_required`; an unproven subscription reports
`subscription_auth_unproven`. Today's adapter has no typed classifier-refusal
capability, so refusal-looking text never triggers fallback. The bounded future
policy permits one Opus TUI retry only for typed classifier refusal plus an
independent defensive-security attestation, then fails closed.

**Seat routing keys on the vendor's harness-nativeness, never on model tier** (maintainer
rule; agent-harness#396 / #525 / #924). A harness fills the seat of its OWN vendor with its
native subagent; every other seat runs through that vendor's CLI lane, and the Anthropic seat
on any host other than Claude Code through the subscription TUI adapter. No cell admits an API key, SDK,
direct HTTP call, gateway backing or alternate endpoint; a native fill counts only once its
verdict is bound.

| host ↓ / seat vendor → | Anthropic (`claude-opus-5-5` / Fable) | OpenAI (`gpt-6-astra`) | Google (`gemini-3.8-flash`) | xAI (`grok-4.7`) |
|---|---|---|---|---|
| Claude Code | native sub-agent (emit → fill → invoke) | `codex` CLI | `agy` CLI | `grok` CLI |
| `codex` | TUI adapter (self-PTY) | native `codex` subagent | `agy` CLI | `grok` CLI |
| `agy` (Antigravity) | TUI adapter | `codex` CLI | native, where the CLI offers subagents | `grok` CLI |
| `opencode` | TUI adapter | `codex` CLI | `agy` CLI | `grok` CLI |
| standalone runner | TUI adapter | `codex` CLI | `agy` CLI | `grok` CLI |

Implemented today: only the Claude Code → Anthropic cell (agent-harness#921). Under `codex`,
`agy` or `opencode` the host's own vendor seat is still launched as a CLI subprocess; the
remaining cells are tracked on agent-harness#924.

---

## Board presets

Nine built-in presets (`advisor_board.presets`), each a named, purpose-tagged,
open-ended seat list. Load via `load_boards()` (self-validates every preset against
the matrix at load time).

| Preset                  | Purpose               | Seats (model · effort · harness · lens) |
| ----------------------- | --------------------- | ---------------------------------------- |
| `default`               | premerge-review       | gpt-6-astra · max · codex · red-team ; gemini-3.8-flash · high · gemini · alternative-approach ; claude-opus-5-5 · max · claude · correctness ; grok-4.7 · max · grok · adversarial |
| `code-review`           | code-review           | grok-4.7 · max · grok · adversarial ; claude-opus-5-5 · max · claude · correctness ; gpt-6-astra · max · codex · red-team ; gemini-3.8-flash · high · gemini · alternative-approach |
| `brainstorm`            | brainstorm            | claude-sonnet-5 · high · claude · adversarial ; gpt-6-astra · high · codex · supportive ; gemini-3.8-flash · high · gemini · lateral |
| `doc-edit`              | doc-edit              | claude-sonnet-5 · medium · claude · copyedit ; gpt-6-astra · medium · codex · structure |
| `legal-review`          | legal-review          | gpt-6-astra · max · codex · opposing-counsel ; gemini-3.8-flash · high · gemini · risk-liability ; claude-opus-5-5 · max · claude · authority-verification |
| `legal-strategy-review` | legal-strategy-review | gpt-6-astra · max · codex · red-team ; gemini-3.8-flash · high · gemini · alternatives ; claude-opus-5-5 · max · claude · downside-ethics |
| `legal-brainstorm`      | legal-brainstorm      | claude-sonnet-5 · high · claude · aggressive ; gpt-6-astra · high · codex · conservative ; gemini-3.8-flash · high · gemini · creative |
| `general`               | general               | gpt-6-astra · max · codex · adversarial ; gemini-3.8-flash · high · gemini · alternative ; claude-opus-5-5 · max · claude · completeness |
| `solo`                  | general               | claude-opus-5-5 · max · claude · completeness |

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

**Review-class boards run on Opus 5.5, never the implementer.** Pre-merge and legal
review are mid-tier decisions where being wrong is expensive, so the review-class
boards (`default`, `code-review`, `legal-review`, `legal-strategy-review`) seat
Opus 5.5 (`claude-opus-5-5`) on the claude lane — the maintainer's default for now
(2026-09-23), replacing every former Fable default; Fable (`claude-fable-5-1`) remains
an explicit, selectable id — decoupled from the implementer model `claude-sonnet-5`
(`panel_invoker.DEFAULT_LEG_MODELS["claude"]` is the single source of truth, so the live
governed gates `governed_review` / `governed_premerge` also review on Opus 5.5). The divergent-thinking boards (`brainstorm`, `doc-edit`,
`legal-brainstorm`) deliberately keep Sonnet, where a diverse / cheap voice is the
right tool. The legal boards encode the PRIMARY review lens per seat; the richer
4-lens-per-seat + apex-Opus seat + verify-round + retrieval-grounded
citation-verification treatment is a documented deep-seat follow-on
(`advisor_board/CONTRACTS.md`), not yet built.

`default` **is** the shared four-vendor fixture board (`fixtures.DEFAULT_BOARD`).
The explicit `PANEL_LEGS == (codex, gemini, claude)` and `invoke_panel` API stay
separately frozen for legacy callers (proven in `tests/test_advisor_board_golden.py`).

The president availability ladder is Fable (the Anthropic seat — Opus 5.5 by default) → Sol → Grok 4.7 → Gemini 3.8 Flash
(`Sol` is the GPT seat alias: `gpt-6-astra` by default, `gpt-5.6-sol` accepted as an explicit legacy id).
It advances only on typed unavailability, not on disagreement or a blocking ruling.
`requires_president` landing policies execute it (`invoke_board(president_invoke=)`)
and fail the landing closed without a ruling; today no HARDEN-authorized president
execution operation exists, so a seated rung reports
`president_execution_route_unavailable` rather than riding a review leg
(`advisor_board/CONTRACTS.md` → ABDPRES).

### Invoking a board

```sh
phase-loop advisor-board <artifact>      # runtime-composed four-vendor board
```

The public CLI does not accept `--board` or `--seats`, and does not load the TOML
configuration below. Named presets and custom boards are library interfaces;
they are not operator controls for this command. CLI configuration is follow-up
[agent-harness#927](https://github.com/Consiliency/agent-harness/issues/927).

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

## Custom boards through the library

This section describes `advisor_board.config.load_boards()`, not CLI setup.
Library callers explicitly load boards layered over presets from
`$XDG_CONFIG_HOME/agent-harness/advisor-boards.toml`
(`advisor_board.board_config_path()`; shape frozen by
`fixtures/advisor-boards.example.toml`). A user board with the same name as a
preset overrides it.

```toml
# ~/.config/agent-harness/advisor-boards.toml
default_board = "my-review"          # library default; does not configure the CLI

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

3. **The presets.** The public `advisor-board` command composes its board through
   the runtime. Named presets and custom TOML boards are available to library
   callers through `load_boards()`; the CLI does not select them.

4. **Auth / observability posture is unchanged for the default path.** Subscription
   stays the default lane; the default board scrubs vendor keys exactly as before;
   `sink=None` (the default) emits no observability envelope, so the live default
   panel stays byte-neutral.

## Explicit heartbeat-only monitoring (agent-harness#892)

`invoke_board(..., monitoring_policy="heartbeat_only", cancel_event=event)`
requests one attempt per seat without model-thinking or silence deadlines.
Omission means `bounded` and retains the backstop; timeout overrides conflict
with heartbeat-only. Silence and flat CPU indicate `progress_unobserved`, not
provider health. No reviewer is dropped or substituted by policy preflight.

| Route | Bounded | Heartbeat-only |
| --- | --- | --- |
| Brokered homebrew/subscription Claude TUI | Existing behavior | Supported on Linux with bwrap |
| Brokered homebrew/subscription Codex | Existing behavior | Supported on Linux with bwrap |
| Brokered homebrew/subscription Grok | Existing behavior | Supported on Linux with bwrap |
| Brokered subscription Gemini / agy | Existing internal print timer | Qualified image and Linux memfd/pidfd support required |
| Gateway, API-key, capture, research, native host fill | Existing route restrictions | Unsupported |
| Legacy invoke_panel | Existing behavior | Unsupported |
| CLI default four-vendor board | Existing behavior | Preserves four vendors; refuses before auth if Gemini capability is missing or changed |

The Gemini extension (agent-harness#905) admits only the qualified `agy` 1.2.10
Linux x64 entry image SHA256
`aea7ed8df1e79b716c0ccd14c7d8086db75b14da535ffb7febdec9a488deff67`
and requires sealed memfd/pidfd support in the running Python/kernel. It uses
literal `--print-timeout 0`, acknowledged stdin input, deny-all settings and no
staged-tree attachment. The executable/settings are immutable mounts in a private
namespace-owned HOME. Credential targets are referenced, never copied or restored;
legitimate refresh writes survive. Required bwrap flags are checked at admission.
An image update needs qualification before the supported digest changes. The
runtime performs no release discovery or image search: it hashes the single
`agy` resolved on `PATH` and refuses any other digest, including the previously
qualified 1.2.9 and 1.2.7 images. A durable image catalog, upstream-release
discovery and fleet updater coordination are tracked by agent-harness#1008.
The redacted 1.2.10 qualification record and exact source hashes are in
`plans/evidence/agy-1.2.10-linux-x64-qualification.json`; that evidence record is
not a second admission source.
`plans/evidence/qualified-provider-images.json` points to the current record.
The `qualified-agy-image` CI check compares the record's hashes of the route's core
files (`gemini_heartbeat.py`, `qualify_gemini_heartbeat.py`) with the checkout on
pull requests and pushes that touch them or the evidence. The full source-hash set
blocks publication, a release-cut pull request and a pull request that changes the
evidence, and is reported without blocking nightly (agent-harness#1029), so a release
still needs a qualification series on its exact tree. Nightly and manual runs also
verify the latest official release archive and extracted executable.

Rejected, empty and native-failed streams retain fixed diagnostics and remain
non-votes. The qualification driver records distinct completion, cancellation
and owner-loss receipts with namespace/process/fd observations. Helper image
checks are sampled; the entry pin does not freeze every helper. Abrupt owner
loss may briefly release the blocked execution gate before parent-death cleanup.
See the qualified Gemini extension in the advisor-board contracts for the full
scope and the repository's qualification script. These receipts are separate
from the historical bounded-success verifier.

Only admission has a finite 10-second window. Once admitted, the broker waits
for completion, terminal failure, cancellation, or owner loss. Provider PID
namespaces enforce owner-loss cleanup, including descendants that detach their
sessions. Metadata-only `review_monitoring.v1` snapshots live below
`stream_dir/<invocation>/seat-<position>.json` (default:
`<repo>/.phase-loop/review-monitoring/`). Final leg records expose
`review_monitoring` without changing legacy dataclass serialization.
No record proves provider-side billing settlement or remote request health.

With a staged review tree, heartbeat-only retains the required egress namespace.
Its holder and uplink follow an owner pipe rather than a wall-clock lease; context
exit or owner death closes them. The provider ownership namespace is created
after network entry and before capability removal, so cancellation ownership
does not restore the provider's ability to change its firewall. Missing required
egress remains a DEGRADED leg with the exception detail, never an isolation claim.
