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
| `gpt-6-sol`      | codex         | `codex`      | codex, opencode   | max            |
| `gpt-6.1-sol`    | codex         | `codex`      | codex, opencode   | max            |
| `claude-sonnet-5`| claude        | `claude`     | claude            | max            |
| `claude-sonnet-5-5`| claude      | `claude`     | claude            | max            |
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

`gpt-6-sol` is an explicit seat (launch-tested on `codex` only). It answers to the `sol` alias, so it cannot fill a governed review's `grok` seat.

`gpt-6.1-sol` is likewise an explicit seat, not a default: it answers to the `sol` alias, so a governed policy requiring `sol` accepts a board that seats it. It is launch-tested on `codex` only; the `opencode` pair is registered by vendor family and is not launch-verified. No shipped default names it. The production review entry points (`phase-loop advisor-board`, the governed review gate, run-train) compose `code-review` with `compose_review_board()` and do not read the user board file, so today a user `[[boards]]` entry cannot move their codex seat; the shipped default moves through the model roster (agent-harness#1171).

`claude-sonnet-5-5` (Claude Sonnet 5.5) is likewise an explicit seat, not a default. It is registered only: it answers to the `fable` alias, the Anthropic seat, so a governed policy requiring `fable` accepts a board that seats it. It does not answer to `gemini`, so seating it where the gemini seat would sit does not satisfy a policy that requires `gemini`. It runs only on the `claude` lane. It is not a TUI-policy model (that is the `claude-fable-*` and `claude-opus-*` prefixes), so it is routed like `claude-sonnet-5`. No shipped default, preset or tier constant names it, and `claude-sonnet-5` stays the regular tier. As with `gpt-6.1-sol`, there is no user-config route to it in the production review entry points yet (agent-harness#1171).

**Effort is model-first `{model, effort}`**, split out of the model name and mapped
per harness by `render_seat_invocation`: `claude` → `--effort <level>`, `codex` →
`-c model_reasoning_effort=<xhigh|high|…>`, `gemini` → effort baked into the model
token (`gemini-3.8-flash-high`; legacy display names such as
`"Gemini 3.1 Pro (High)"` remain accepted). Canonical effort levels: `low, medium, high, max`.

Built-in presets use one lower canonical effort level than their previous defaults:
`max` becomes `high`, `high` becomes `medium`, and `medium` becomes `low`.
The default and availability-composed code-review boards use `high` for Claude,
Codex and Grok, and `medium` for Gemini. Explicit per-seat `effort` remains authoritative;
the invocation mappings still support the full effort scale.

Claude panel launches default to 128,000 output tokens. Set
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` in the panel launch environment (or its explicit
`base_env`) to override this default. Only that value is copied into run-specific
`--settings`, so it reaches ordinary, brokered and jailed TUI launches while
settings sources remain disabled and credentials remain filtered. Claude Code
clamps the requested budget to the selected model's cap. Codex, Antigravity and
Grok retain their CLI-managed output budgets: their current adapter interfaces
do not expose a verified output-token override. These defaults apply to new
launches; running seats are unaffected.

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
| `default`               | premerge-review       | gpt-6-astra · high · codex · red-team ; gemini-3.8-flash · medium · gemini · alternative-approach ; claude-opus-5-5 · high · claude · correctness ; grok-4.7 · high · grok · adversarial |
| `code-review`           | code-review           | grok-4.7 · high · grok · adversarial ; claude-opus-5-5 · high · claude · correctness ; gpt-6-astra · high · codex · red-team ; gemini-3.8-flash · medium · gemini · alternative-approach |
| `brainstorm`            | brainstorm            | claude-sonnet-5 · medium · claude · adversarial ; gpt-6-astra · medium · codex · supportive ; gemini-3.8-flash · medium · gemini · lateral |
| `doc-edit`              | doc-edit              | claude-sonnet-5 · low · claude · copyedit ; gpt-6-astra · low · codex · structure |
| `legal-review`          | legal-review          | gpt-6-astra · high · codex · opposing-counsel ; gemini-3.8-flash · medium · gemini · risk-liability ; claude-opus-5-5 · high · claude · authority-verification |
| `legal-strategy-review` | legal-strategy-review | gpt-6-astra · high · codex · red-team ; gemini-3.8-flash · medium · gemini · alternatives ; claude-opus-5-5 · high · claude · downside-ethics |
| `legal-brainstorm`      | legal-brainstorm      | claude-sonnet-5 · medium · claude · aggressive ; gpt-6-astra · medium · codex · conservative ; gemini-3.8-flash · medium · gemini · creative |
| `general`               | general               | gpt-6-astra · high · codex · adversarial ; gemini-3.8-flash · medium · gemini · alternative ; claude-opus-5-5 · high · claude · completeness |
| `solo`                  | general               | claude-opus-5-5 · high · claude · completeness |

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

**Advisory runs over a standalone document** (agent-harness#802):

```sh
phase-loop advisor-board research-bundle.md --advisory --json
```

`--advisory` reviews a research bundle, memo, roadmap or plan under the advisory contract
(`advisory.v1`, `advisor_board/advisory_contract.py`) instead of the code-review brief. The
bundle's own charter scopes the analysis, and the verdict protocol still takes precedence. It
runs through the same HARDEN review operation and sandbox as the default board, against a private
scratch authority with no staged tree, so it needs no git repository. It is **non-gating**:
`--landing-tier`, `--native-president` and capture are refused with it, and `invoke_board`
(`AdvisoryLandingRefused`) and the governed gate (hold `advisory_not_landing_evidence`) refuse any
landing path whose brief is an advisory contract (`advisory_contract_not_landing_evidence`).
Inherited `GIT_*` variables are removed for the run and named in one stderr note; `HOME`,
`XDG_CONFIG_HOME` and `PATH` still select git's global config and binary. Its JSON adds
`board: "advisory"`, `composed_board` (the composition it ran), `mode: "advisory"`,
`gating: false` and `contract: {id, sha256}`. Seats run only on Linux. On any other host, the
refusal is followed by a hint line.

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

**Pointer briefs** (agent-harness#1204):

```sh
phase-loop advisor-board bundle.md --pointer-brief --json
```

`--pointer-brief` declares that the brief tells reviewers to open files in the staged tree instead of carrying their content inline.

**Before launch.** Before any seat launches, the board checks each seat's route. A seat that cannot open files gets `seat_pointer_brief_unreadable`, printed on stderr. On main that means the brokered Claude seat and the brokered Gemini (agy) seat. A Claude seat filled natively has file access.

**What happens to that seat.** It still runs, but its verdict is **not source-grounded**:
- It does not count toward the floor, the landing count or the pre-merge minimum of reviewers.
- The president sees it as "not counted".
- A `DISAGREE` from it still blocks.

The payload adds `notices`, `legs[].notices`, `legs[].source_grounded` and `grounded_seats`, and only when the flag is set.

**The fix.** Inline the referenced content, or fill the seat through a route with file access. Once agent-harness#1132 lands, a jailed Claude seat will have file access. The Gemini tool route is agent-harness#1170.

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

The Gemini extension (agent-harness#905) admits only a closed set of qualified
`agy` Linux x64 entry images, `gemini_heartbeat.QUALIFIED_IMAGES`:
1.2.11 (SHA256 `ec7cf797ecb0e1d91ddf3b6d9d6c1d616bb89f78a5b0e43536b72a7fce695f56`),
1.2.12 (SHA256 `ce6fdd9e7621ee9ac6eedaa337731ca1f235e412ff57cf9eabcd2aa23b3576ca`),
1.2.14 (SHA256 `0d0d3eba22daf29504dd290151c7ed9a4d33b0c6aa0acfc5da27bc3b01d2f029`),
1.2.15 (SHA256 `5f9c16b286895f8f7fdecd423883ca256a85077b8acf9a6bc1111761d34df164`),
1.2.16 (SHA256 `a759ce7c7a235d9b6c281a25ead97cbbf2e92314a3ffd224e2f9144f3fae7a86`),
1.2.17 (SHA256 `c54ef90651a8646ae67334d39212c81f5946feec373ad6aa335f9ef401662bc5`),
1.3.0 (SHA256 `19be6af38f7beeaa0db415df9297e314ab3d33fdd6f853434d49f88819bc68e4`)
and 1.3.1 (SHA256 `ce1bdaed3201bb84f35d69d2773caec4f18af52af00e8c25f6cace07e4359615`),
so a host that has not yet auto-updated keeps its Gemini seat (agent-harness#1008).
It requires sealed memfd/pidfd support in the running Python/kernel. It uses
literal `--print-timeout 0`, stdin input (one event when the sealed prompt fits one
chunk, acknowledged chunks otherwise; agent-harness#1175), deny-all settings and no
staged-tree attachment. The executable/settings are immutable mounts in a private
namespace-owned HOME. Credential targets are referenced, never copied or restored;
legitimate refresh writes survive. Required bwrap flags are checked at admission.
Adding an image to the set needs its own qualification first. The
runtime hashes the single `agy` resolved on `PATH` once and binds that digest into the
profile evidence. A set member is admitted as `release_qualified`. Any other digest is
admitted only if it is a genuine stable upstream release for the host's platform that
this host has self-qualified (agent-harness#1076): on first use, the whole-board preflight
verifies the release asset's published digest and archive member without executing
anything, then runs the same three live operations, and records the result in a per-user,
per-host, HMAC-bound store. Such a seat is `locally_qualified` and counts at every tier.
A user config `[agy] self_qualification = false` restores the hard refusal. See
CONTRACTS.md "First-use self-qualification".
Each member has its own redacted qualification record with exact source hashes,
`plans/evidence/agy-<release>-linux-x64-qualification.json`; the records are
not a second admission source.
`plans/evidence/qualified-provider-images.json` lists every member (image digest,
help digest, release and record), and the verifier refuses unless that list and
the runtime set name exactly the same members and every member's record checks.
The `qualified-agy-image` CI check compares every record's hashes of the route's core
files (`agy_qualification.ROUTE_CORE`: `gemini_heartbeat.py`, `agy_qualification.py`,
`agy_provenance.py`) with the checkout on
pull requests and pushes that touch them or the evidence. The full source-hash set
blocks publication, a release-cut pull request and a pull request that changes the
evidence, and is reported without blocking nightly (agent-harness#1029), so a release
still needs a qualification series on its exact tree. Nightly and manual runs also
verify that the latest official release is a set member, and its archive and extracted executable.

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

## Jailed review seats (agent-harness#1132)

A brokered Claude seat can run with its full tool set inside a per-seat jail, reading the
staged clone and the review bundle through tools instead of receiving the bundle inline.
The jail, not the CLI's permission settings, is the boundary. Outside a jail nothing
changes: the seat keeps the sealed inline route and reports why in a typed notice.

A jailed launch needs an EC-EXECFIND-2 falsifier
pass recorded **on this host** for the jail's profile digest. The pass is stored per user,
at `$XDG_STATE_HOME/phase-loop/seat-jail-passes/<digest>.json`, and uses
agent-harness#1071's falsifier-run layout. The digest binds this host's layout, so a pass
does not carry over from another host, and an OS upgrade that changes `/lib*` or the `/etc`
subset needs a new pass. With no recorded pass, a Claude seat qualifies the jail on
first use (see below); `phase-loop seat-sandbox qualify` runs the same qualification by hand,
against a real falsifier run, and records the pass. At launch the built jail is re-checked
against its record, and a launch whose record does not hold is refused before any effect
with `seat_sandbox_refused:jail_unqualified`.
A pass record binds this host, the falsifier-run layout and the
run's evidence, which is re-hashed on every check. A copied, stale or hand-written record
does not qualify another host or another run. The operator's own account can still forge
one, and that is accepted, because the operator is trusted.

**The pass store's directories must be private to you.** This applies to
`$XDG_STATE_HOME` (usually `~/.local/state`), its `phase-loop` directory and
`phase-loop/seat-jail-passes`. Each must be a directory you own, must not be a link, and
must not be writable by others. A group-writable directory is accepted only when its group
is your own user-private group. That is the usual umask-002 layout, where your primary
group is named after you and has no other members, and no other account uses it as its
primary group. Anything else is refused with `seat_sandbox_refused:pass_store_unsafe`. Its
notice names the fix: `chmod go-w` on those three directories, or `chmod 0700`. Neither the
qualification nor the gate ever changes these permissions for you. The store defends against the
seat uid, stale records, other hosts and accidental reuse. Gemini stays sealed with
`gemini_seat_egress_unconfined` until its jail egress is limited to agy's inference hosts
(agent-harness#1170). Codex and grok are
not jailed yet (agent-harness#895) and carry `seat_filesystem_unconfined` when given a tree.

**Where the host supports the jail, Claude seats are jailed by default, and the jail is
qualified on first use.** The seat's credential is your Claude login, which is normally
present (see below). So on a host that has the prerequisite below, every brokered Claude
seat with a staged tree takes the jailed route.
- **No recorded pass:** if no EC-EXECFIND-2 pass is recorded for this host and jail, the
  harness runs the host's jail qualification itself, once, before launching. This is the
  same as `phase-loop seat-sandbox qualify`. Concurrent seats and boards wait for that one
  run.
- **On a pass:** the pass is recorded, and the seat runs jailed. Its mode line reads
  `jailed (qualified now)`.
- **On a failure, or if the run cannot happen:** the seat is degraded and does not run (it
  never falls back to a toolless seat), and its mode line names
  `seat_jail_qualification_failed`, the reason and the fix.
- **Retrying:** a failure is not retried on every seat. It is retried after
  `PHASE_LOOP_SEAT_JAIL_QUALIFY_RETRY_S` (default one hour), or as soon as the jail or the
  host layout changes.

**Seat modes.** Before any seat launches, the board prints one line per seat
(`advisor-board: seat mode: ...`), and the `--json` payload carries `seat_modes`. The modes
are:
- `jailed`: tools inside the jail. `credential` names `login` or `seat_token`.
- `unconfined`: tools on the staged tree without a jail (codex, grok).
- `sealed`: no tools; the bundle is inlined.
- `degraded`: will not run. The line reads `degraded — will not run [<code>]: <reason>;
  fix: <command>`, before the board starts.
- `native`: filled by the driving session.

Every mode other than `jailed` names its notice code, its reason and a one-line fix. The
same modes are written to `seat-modes.json` in the stream directory.

**Host prerequisite (maintainer, root, once per host).** `apt install uidmap`, then
`usermod --add-subuids <start>-<end> --add-subgids <start>-<end> <operator>` (65536 ids is
conventional). The runtime never runs these. Without them the seat stays sealed with
`seat_sandbox_unavailable_seat_uid`. The host must also have `dev.tty.legacy_tiocsti = 0`.

**Ubuntu 24.04+ and 26.04: the AppArmor override (agent-harness#1276).** Ubuntu's
`bwrap-userns-restrict` profile runs every child of `/usr/bin/bwrap` as
`bwrap//&unpriv_bwrap`, whose `audit deny capability` rule denies every capability. The
jail's `setpriv` uid switch then fails (`setresuid failed: Operation not permitted`;
`journalctl -k | grep unpriv_bwrap` shows the denial) and qualification ends
`seat_jail_qualification_failed` with the typed reason `uid_switch_denied`. A host without that
profile (Ubuntu 22.04, and 24.04 as measured) needs nothing. The jail itself is unchanged.
- **The fix is host policy, installed by an administrator.** `python3 -m
  phase_loop_runtime.seat_jail_apparmor` prints a root script. It adds one small named profile
  that is entered only for `/usr/bin/setpriv` (no path attachment, so a plain `setpriv` is
  untouched), grants it `setuid`, `setgid` and `setpcap`, and hands the seat back to
  `bwrap//&unpriv_bwrap` on its next exec. It uses the local include the shipped profile
  provides, appends between markers instead of overwriting, and is idempotent. The runtime
  never runs it.
- **What it changes for the seat:** nothing it could use. Measured on Ubuntu 26.04 (bubblewrap
  0.11.1): after the drop the seat has the seat uid, empty permitted, effective and bounding
  sets and no-new-privs, and cannot switch uid again; other bwrap children keep
  `bwrap//&unpriv_bwrap`; the full qualification records a pass.
- **Revert:** `python3 -m phase_loop_runtime.seat_jail_apparmor --revert` prints the script
  that removes the block and the profile and reloads the shipped profile. `--profile` and
  `--local` print the two policy texts for review.
- **Then:** run `phase-loop seat-sandbox qualify` on the host.

**Claude seat credential.** By default, the seat uses the subscription you are logged in
with.
- **What is read, and when:** at every jailed launch, the runtime reads only the current
  login's access token from the Claude CLI's own store. That is
  `$CLAUDE_CONFIG_DIR/.credentials.json`, else `~/.claude/.credentials.json`, and the login
  Keychain on macOS. It never reads or uses the refresh token.
- **A short token:** if the token has less lifetime left than the seat's deadline (its
  per-leg timeout, else 1800 s), the seat waits for you to renew the login. The harness never
  runs the Claude CLI for this. Set `PHASE_LOOP_SEAT_LOGIN_TOKEN_MARGIN_S` (seconds) to
  override the deadline as the margin.
  - **Before any seat launches:** the mode line says
    `claude_seat_login_token_awaiting_refresh`, with the minutes left. Use Claude, or run
    `claude auth login`.
  - **The wait:** the seat re-reads the store (read-only) every 30 s
    (`PHASE_LOOP_SEAT_LOGIN_REFRESH_POLL_S`), for up to
    `PHASE_LOOP_SEAT_LOGIN_REFRESH_WAIT_S` (default 900 s; 0 means do not wait). Other seats
    are not held. A renewed login runs the seat jailed, and the log says
    `jailed (login refreshed)`.
  - **Not renewed in time:** the seat is degraded and does not run, with
    `claude_seat_login_token_expiring` (fix: run `claude auth login`, or use Claude to
    refresh it, then re-run). The rest of the board runs.
  - A token that expires during a run ends the leg with `claude_seat_login_token_expired`.
    Re-running it reads a fresh token.
- **Switching subscriptions:** `claude auth login` to another subscription takes effect at the
  next launch.
- **No credential:** with no login and no override, the seat is degraded and does not run,
  with `claude_seat_token_missing` (fix: `claude auth login`, then re-run).

**Optional override: a dedicated seat token.** Seats follow the subscription of the session
that launches them, so an override is used only while you are logged in to the account it
was stored for.
- **Storing it:** store a long-lived `claude setup-token` token with the store command,
  while logged in to the account the token belongs to. The command reads the token with no
  echo, or from stdin, and never prints it. It refuses a terminal that cannot hide the
  input; pipe the token on stdin there. It stores the token and the account together as
  one record. It refuses if no login is found.
- **When it is used:** after `claude login` to another account, seats use the login, and
  their mode line and notices show `claude_seat_override_other_subscription`. An override
  stored by hand, without the command, is never used.
- **What to store:** the override carries no expiry information, so it should be a
  long-lived token, not a copied login token.
- **Checking it:** the store prints the account and organization it bound the token to.
  `phase-loop seat-sandbox token-status` shows them, this session's, and whether the
  override applies now. It exits 0 only when the override applies, and never shows the
  token. Logging in to another organization of the same account also moves seats to the
  login.
- **One per user:** there is one override per Unix user. Storing from another account
  replaces it.
- **Upgrading from an earlier release:** a hand-written override file is ignored until you
  store it again with `store-token`, as is an override stored by an earlier version of this
  release (which recorded the account only). A host that never runs `claude login` cannot
  use an override, because the store needs a login to bind the token to.

```bash
claude setup-token                         # mint a long-lived subscription token
phase-loop seat-sandbox store-token        # paste it (hidden); bound to your current login
```

The stored file must stay 0600 in a 0700 directory owned by you, or the leg is refused with
`seat_sandbox_refused:token_file_unsafe`.

Either credential reaches the seat only through one drained pipe. It never appears in an
argv, an environment value, a log or an evidence record, and the seat's output is scanned
for it.
- **The residual:** a jailed seat can read the credential it was given and use it for that
  credential's remaining lifetime. That is hours for a login access token, or the setup
  token's lifetime for an override. This residual is recorded under agent-harness#361
  (EC-HARDEN-5 is UNMET for tooled seats, maintainer decision D3).
- **If a leg reports `claude_seat_token_in_output`**, or `seat_sandbox_retained_after_teardown`
  on a suspect leg:
  - **With the login:** log out and back in (`claude auth logout`, then `claude auth login`). The
    access token also expires on its own within hours.
  - **With an override:** revoke it from your Claude account settings, and mint a new one.

**Replacing the seat token override.** The runtime reads the override at every jailed
launch, so you can swap it between legs or rounds. Run `phase-loop seat-sandbox store-token`
again. It replaces the record (the token and its account together) with one rename, so no
launch reads half a record or a token bound to another account. A leg that is already
running keeps its own token. Replacing the token does not
change the jail's digest or invalidate its recorded qualification. If a leg reports
`claude_seat_token_rate_limited`, the override's subscription hit a rate or usage limit. With
the login, the same outcome is `claude_seat_login_rate_limited`. The leg's detail names the
reset time when the provider gives one. Rotate or replace the credential, or wait for the
reset. The jail itself is fine.

**Notices.** Each seat's notices are `{code, seat_key, what, why, fix}` in the
`advisor-board --json` payload (`notices`, `legs[].notices`) and in the text summary. The
full vocabulary is in `advisor_board/CONTRACTS.md` ("SEATJAIL").

**Retained directories.** If teardown cannot remove a seat's directories, they are kept
under the leg's private 0700 scratch directory and the leg carries
`seat_sandbox_retained_after_teardown`. Remove them with
`phase-loop seat-sandbox reap PATH`; it accepts only a path recorded by that notice.
