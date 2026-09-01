---
name: gemini-advisor-board
description: Run a customizable cross-vendor advisor board (formerly advisor-panel; that name remains a working alias) through the agent-harness runtime primitive when a high-stakes change needs independent review evidence.
---

# Advisor Board

Use this skill when a plan, implementation diff, release closeout, or other high-stakes artifact needs an independent cross-vendor review board. This skill was formerly named `advisor-panel`; that name still resolves as an alias, so existing instructions that say "advisor-panel" keep working.

## Source Of Truth

The advisor-board (formerly advisor-panel) implementation is owned by `agent-harness`:

- Runtime primitive: `phase_loop_runtime.panel_invoker`
- Board model: `phase_loop_runtime.advisor_board` (seats, boards, resolver, validation)
- Entry points (runnable default): `advisor_board.composition.compose_review_board` + `panel_invoker.invoke_board`, exposed as the `phase-loop advisor-board <artifact>` CLI. The legacy `available_panel_legs`/`invoke_panel`/`invoke_panel_request` stay in place for the governed review/pre-merge gates (unchanged, byte-identical golden).
- Governed workflow integration: phase-loop governed review/pre-merge paths

Do not call dotfiles advisor-panel scripts, copy provider-specific shell scripts, or introduce a separate implementation in the skill body. The skill is a thin operator guide over the runtime primitive.

## Boards & Availability-Aware Composition

Named boards live in `phase_loop_runtime.advisor_board.presets`; the default review board is `code-review`, a 4-vendor cross-vendor panel: Claude Fable 5 (`claude-fable-5`), Grok 4.6 (`grok-4.6`), GPT-5.6 Sol (`gpt-5.6-sol`), and Gemini 3.7 Flash (`gemini-3.7-flash`). Each seat uses its maximum supported thinking level and a distinct review lens (correctness / adversarial / red-team / alternative-approach).

Composition is AVAILABILITY-AWARE (`composition.compose_review_board`): it targets 4 independent reviewers (hard floor 3) and NEVER collapses to 1–2 when vendors are down. Each vendor that is both present on PATH AND authenticated gets one lens-distinct seat first; the remaining seats are BACKFILLED onto the available (up + authed) vendors with DIFFERENT lenses. So 2 vendors up still yields a full 4-seat board, and 1 vendor up yields 4 distinct-lens seats on that vendor. The `default`/premerge board uses the same four model defaults; only the explicit legacy `invoke_panel` API retains its three-leg shape.

When a president is required, the availability ladder is Fable, then Sol, then Grok 4.6, then Gemini 3.7 Flash. Advance only on a typed `president_unavailable` result; disagreement or a blocking ruling never triggers fallback.

## Three Ways To Feed Material

There are THREE DISTINCT ways to give the panel material. The #114 fix names them accurately: `artifact_ref` and `brief_ref` are Read-file-and-stage conveniences, while `context_refs` is the true by-reference mode.

- **Inline** (`artifact="..."`) — small material passed as a string, written verbatim into `review-bundle.md`. A large inline artifact logs a steering warning.
- **Read-file-and-stage** (`artifact_ref="path/to/bundle.md"`, or a list) — the runtime READS the local file(s) off disk and stages their bytes into `review-bundle.md` (a single path verbatim; multiple paths under per-file headers). This keeps YOUR context lean, but the file CONTENTS still land in the staged bundle every leg reads. Use it when you WANT the legs to read the material verbatim. `artifact_ref` wins over `artifact` if both are given.
- `brief_ref="path/to/brief.md"` — a Read-file-and-stage path for a large review brief; staged as `review-instructions.md`. Omit it to use the built-in review/advisory brief.
- **TRUE by-reference** (`context_refs=["path/to/large.pdf", ...]`, #114) — the runtime stages ONLY a path + metadata manifest (path, size, sha256, MIME/extension, and PDF page count when cheap) plus an instruction telling each leg to OPEN the files with its own local tools. Raw file contents are not read into the bundle or prompt by this runtime path. Use it for LARGE or PRIVATE local material when the selected provider/backing can access the same local file path. A missing/unreadable path fails CLOSED naming the path, unless you pass `context_refs_soft_warn=True` (logs a warning and emits an `UNREADABLE` manifest entry). Pathnames and hashes can disclose sensitive metadata, and a leg may disclose file contents after it intentionally inspects a referenced file unless an output policy forbids disclosure.

## Bounding A Slow Leg

Legs fan out concurrently, so panel wall-clock ≈ max(leg), not sum. Each leg's default
timeout is INPUT-SCALED (~600s floor + ~12s/KB) and then raised to a ~1800s backstop.

**Liveness is heartbeat-based, not clock-based.** A leg is reclaimed when its heartbeat goes
EXTINCT — no new stdout/stderr byte AND no process-group CPU advance for 180s — not when a
timer expires. Print-mode legs (codex/gemini/grok) heartbeat on any new stdout OR stderr byte
(different CLIs stream on different channels — some to stderr, some to stdout — so both
are watched); advancing
process-group CPU is a secondary signal that can only EXTEND a leg's life, never kill it. The
TUI route heartbeats on genuine reviewer progress — novel transcript/output growth — and
reports a TUI stall marker carrying the age of the last progress, so cosmetic animation and
idle CPU do not keep a wedged leg alive.

The wall-clock deadline is a rarely-hit BACKSTOP. Reliable stall detection is exactly what
makes that generous backstop safe.

**`timeouts_by_leg` is a HARD DEADLINE, not a stall threshold.** Passing an explicit value
REPLACES the backstop with your number for that leg, and it fires even while the leg is making
healthy progress: `{"gemini": 300}` kills an attempt at 300s whether or not it is still streaming.
On the print routes it is a deadline **per ATTEMPT on the print routes, not a leg-wide ceiling**;
the routes differ, and the numbers below are derived from the runtime's retry guards:

- **`codex` seat (print route):** a soft-empty first attempt that failed fast (elapsed under 0.5 × T) is retried
  once with a fresh deadline and a fresh liveness clock — worst case just under **1.5 × T**.
- **`gemini` and `grok` seats (print route):** the same retry, but "fast" is elapsed under 0.5 × (T + 60 s), so the
  worst case is **1.5 × T + 30 s** (1.6 × at T = 300; approaching 2 × as T falls toward 60).
- **`claude` seat (TUI route):** ONE backstop for the whole leg — a retry gets only the **remainder of T**,
  so there T is the leg-wide ceiling.

These figures are retry algebra, not absolute wall-clock ceilings. When a deadline fires the
leg's process group is sent SIGTERM and given 5 s to exit, then SIGKILL after another 5 s — add
~10 s of teardown to every figure above — and a process that ignores signals can hold its slot
past any stated maximum. If policy needs a leg-wide ceiling on a print-route leg, the runtime does
not provide one today — size the value for the worst case above, plus teardown, and record that in
the policy.

- **Default: omit it.** Heartbeat extinction already reclaims dead legs, normally long before
  any deadline is reached.
- **Use it only** when policy requires an absolute ceiling on an actively-progressing leg.
- **Do not reach for it because you saw a leg stall.** Stalls are already handled, and a value
  shorter than the real work converts a recoverable stall into a guaranteed kill: the leg's
  process group is terminated and it is reported as a timeout result, verdict unwritten.

When a leg does end early, distinguish the two causes before diagnosing: heartbeat extinction
(a `[leg-liveness]` stall marker, or a TUI stall marker with `last_progress_age_s`) means the
leg went silent; a hard-deadline expiry means a wall-clock ceiling fired — your override if you
set one, otherwise the ~1800s backstop — so an expiry alone does not prove an override was
passed. They are not the same failure and are not retried on the same basis.

A transient CLI stall (an empty turn or a "timeout waiting for response" marker) is retried
once, but only when it fails FAST, so a retry can never double a slow leg's wall-clock.

## Use

### Optional governed research

For current external evidence, opt in with `ResearchPolicy(enabled=True)` on the
board. The runtime requires the exact published `pmcp==1.20.0`
`scoped_advisor_audit.v1` capability, creates unique per-seat locks/audits, and
exposes only PMCP health/catalog/describe/invoke backed by Firecrawl and Bright
Data research tools. It disables Codex native web search/apps, derives success
from the completed correlated audit rather than model prose, and emits only
privacy-safe tool IDs, statuses, source hashes, and digests. Claude still runs
only through the subscription TUI adapter—never an API, SDK, direct HTTP call,
gateway backing, or native Task Agent. Gemini/agy, Grok, Omnigent, native-host,
and custom-spawn research seats fail closed as
`research_profile_unenforceable`.

1. Prefer the repo's governed phase-loop path when reviewing phase execution or pre-merge work.
2. For a standalone smoke or diagnostic, run `phase-loop advisor-board <artifact>` (or, in-process, compose with `compose_review_board` and pass the material's path via `artifact_ref` to `phase_loop_runtime.panel_invoker.invoke_board`).
3. Require every leg to end with `AGREE`, `PARTIALLY AGREE`, or `DISAGREE`.
4. Treat `EMPTY`, `TIMEOUT`, `ERROR`, `DEGRADED`, and `UNAVAILABLE` as structured evidence, not successful reviews.
5. Keep provider API keys and custom authorization headers out of the environment; the runtime strips known API-key variables and request-header overrides and uses local subscription CLIs.
6. Every Fable or Opus seat requires the homebrew Claude Code self-PTY adapter after a metadata-only probe proves first-party `claude.ai` subscription auth. Never substitute a gateway, API, SDK, direct HTTP call, or native Task/subagent; `tui_backing_required`, `subscription_auth_unproven`, and `tui_adapter_required` fail closed.

## Standalone Smoke Shape

```python
from phase_loop_runtime.advisor_board.composition import compose_review_board
from phase_loop_runtime.panel_invoker import invoke_board

# Availability-aware by default: compose_review_board seats only vendors that are
# BOTH on PATH and authenticated (unauthed vendors are dropped and backfilled).
board = compose_review_board()
result = invoke_board(board, "", artifact_ref="path/to/bundle.md")
for leg in result.legs:
    print(leg.seat_key, leg.status)
```
