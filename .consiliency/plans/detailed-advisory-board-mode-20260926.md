# Advisory board mode for `phase-loop advisor-board` (agent-harness#802, agent-harness#1098 items 1 and 3)

## Problem

`phase-loop advisor-board <bundle>` always runs the code-review contract. A research bundle or a
plan with its own reviewer charter is judged as "a phase's pre-merge change" (`_REVIEW_INSTRUCTIONS`),
the result is labelled `board: code-review`, and the command needs a git repository only to name a
HARDEN review authority. On macOS it refuses with a bare "requires Linux".

## What the code allows today (findings that fix the design)

- Panel `mode="advisory"` (the #63 non-verdict framing, and the mode every non-code preset purpose
  maps to) is **refused in production**: `invoke_board` returns `harden_advisory_execution_refused`
  unless a test seam is injected, and `prepare_review_isolation_authorization` only mints for
  `mode == "review"`. EC-HARDEN-5 and the interim president decision note both say nothing routes
  around that refusal. So an advisory run cannot use panel `mode="advisory"` without a HARDEN
  decision.
- The sealed review route already takes a caller brief. On the brokered route the brief is the
  entire digest-bound `AUTHORITATIVE-INSTRUCTIONS` frame; the sealed preamble keeps the verdict
  protocol (`AGREE` / `PARTIALLY AGREE` / `DISAGREE`). `governed_review.py` already passes
  `brief_ref=` in review mode. Every seat the CLI composes is brokered under HARDEN.
- The review authority is only an identity (`sha256` of the repo root) plus a broker probe that the
  repo has one tracked file and is **not** visible inside the seat. No tree is staged unless the
  authorization carries `staged_tree_sha256`, and `stage_review_tree=False` guarantees that.

## Design

1. **Selection: `--advisory`** (opt-in flag on `advisor-board`). It keeps the existing auth-aware
   composition and execution route. It changes the contract, the authority and the labels only.
   With no flag, the command is unchanged.
2. **Contract.** The seats' authoritative instructions are a fixed advisory contract
   (`advisor_board/advisory_contract.py`, `advisory.v1`). It says the run is advisory and
   non-gating, that there is no diff or repository, that unchecked criteria in a plan are not
   defects, and that the bundle's own charter sets the scope of the analysis. The charter can
   narrow what the seats analyze; it cannot change the rules, the tools or the verdict protocol,
   which takes precedence. The contract defines the verdicts relative to the bundle's provisional
   recommendation unless the charter defines them. The bundle stays in the untrusted frame; its
   charter is never promoted into the authoritative frame.
3. **No repository.** An advisory run never uses the caller's repository. It mints its HARDEN
   authority against a private scratch git repository (`git init` plus one tracked placeholder, no
   commit), with `stage_review_tree=False`. Seats get no tree and the broker's exposure probes still
   run. The scratch is removed when the command returns. This uses the HARDEN APIs unchanged.
4. **Non-gating.**
   - `--advisory` with `--landing-tier` or `--native-president` is a usage error (exit 2) before
     any probe, so an advisory run can never carry a president ruling or a landing policy.
   - `--advisory` with agy canary capture is refused (capture is a governed exact-four run).
   - The JSON carries `"board": "advisory"`, `"mode": "advisory"`, `"gating": false` and the
     contract id and digest. Text output says "advisory, non-gating". The default JSON is unchanged.
   - Native fills bind the brief digest, so a fill emitted under the advisory contract is refused
     by the default review preflight (and vice versa).
   - The governed gate, the runner and `run-train` do not read the flag.
5. **Mac.** The sandbox stays Linux-only. The existing refusal lines are unchanged and each is
   followed by a hint: on a non-Linux host, run the board on a Linux host (for example dev0); in a
   directory that is not a git repository, run from the repository under review or pass
   `--advisory` for a standalone document.

## Relation to PANEL (Phase 18) — not implemented here, proposed

- **`--board <preset>` / task selection** is not implemented. Every non-code preset purpose maps
  to panel `mode="advisory"`, which HARDEN refuses. Choosing a board by task for `advisor-board` is
  also EC-PANEL-1/EC-PANEL-3 (`[panel.<task>]` tables; "`advisor-board` … all use it").
  **Proposal:** once PANEL slice 1 lands, `advisor-board --task <name>` selects the `[panel.<task>]`
  lanes. `--advisory` then becomes the contract selector for any task whose built-in table is
  advisory. PANEL's roadmap text needs one sentence recording that an advisory task runs through
  the review operation with the advisory contract, or HARDEN needs a ruling for a sealed advisory
  operation.
- **Lens delivery (EC-PANEL-6)** is untouched. The advisory contract replaces the whole
  authoritative instructions for every seat identically, so the verdict protocol text stays the
  same across seats. PANEL slice 2 renders its lens heading inside the same frame.
- **Default board, lens cycle and labels:** unchanged. PANEL's corpus drives the default,
  flag-less path.

## Tests

`phase-loop-runtime/tests/test_advisor_board_advisory_mode.py`:

- flag parsing;
- default path unchanged (compose called with no kwargs, `brief_ref` absent, review digest,
  JSON key set);
- every seat's brokered prompt carries the advisory contract as its authoritative frame;
- `--advisory` with a landing tier or native president is refused before any probe;
- an advisory native fill is refused by the review preflight;
- a no-repo run mints a real authorization against a scratch authority with no staged tree, and
  that authorization revalidates.
