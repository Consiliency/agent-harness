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
   - Inherited `GIT_*` (round 2). The HARDEN authority probes run `git -C <authority>` in this
     process with its environment. An advisory run never uses the caller's repository, so
     nothing it does depends on any `GIT_*` variable: the CLI removes every one from the process
     environment before the authority is built or any probe runs, prints one stderr note naming
     them, and restores them when the command returns. Nothing is refused, so ordinary shell and
     CI variables (`GIT_OPTIONAL_LOCKS`, `GIT_PS1_*`, Jenkins `GIT_COMMIT`/`GIT_BRANCH`, GitLab
     `GIT_DEPTH`/`GIT_STRATEGY`, `GIT_LFS_SKIP_SMUDGE`) no longer stop the run, and redirecting
     ones (`GIT_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_CONFIG_*`, `GIT_EXEC_PATH`) never reach the
     probes. Scope: this covers the `GIT_` namespace only. `HOME`, `XDG_CONFIG_HOME` and `PATH`
     still select git's global config and binary, as they do for every board run.
   - The JSON carries `"board": "advisory"`, `"mode": "advisory"`, `"gating": false` and the
     contract id and digest. Text output says "advisory, non-gating". The default JSON is unchanged.
   - Native fills bind the brief digest, so a fill emitted under the advisory contract is refused
     by the default review preflight (and vice versa).
   - The governed gate, the runner and `run-train` do not read the flag.
   - **Runtime enforcement** (round 1, maintainer ruling). `invoke_board` refuses, as its first
     step, any call that carries a landing path (`landing_tier`, `review_policy`,
     `president_invoke` or `native_president_fill`) while its resolved brief is the advisory
     contract: `AdvisoryLandingRefused` (code `advisory_contract_not_landing_evidence`), before
     the artifact is resolved, before any authorization, fill preflight, president or seat. The
     error type is deliberately outside `PresidentPolicyError`/`ValueError`/`OSError`/
     `RuntimeError`, so no existing fallback swallows it. The governed gate
     (`governed_board_gate`, which is tierless) holds with the distinct category
     `advisory_not_landing_evidence` before composition.
   - **One read** (round 2). Both entry points resolve the brief once and pin that text (or its
     failure) in a context variable for the rest of the call; every later `_resolve_brief` of the
     same ref in that context returns the pinned bytes. A file replaced after the check, a ref
     created after an unreadable check, or a one-shot pipe cannot change what runs. Worker threads
     that re-read are still bound by the HARDEN instruction digest minted from the pinned text.
   - **Identity** (round 2). The match is against `ADVISORY_CONTRACT_DIGESTS`, every advisory
     contract digest ever shipped (today only `advisory.v1`). A golden test fails when the
     contract text changes until its new digest is added, so an old advisory fill stays advisory.
   - **Landing-path sweep** (round 2). Production callers of `invoke_board`: the CLI (tierless
     unless `--landing-tier`, which `--advisory` refuses), `runner._run_legible_panel` (a
     landing tier on GOVLEAN-switched repos; on pre-switch repos tierless, but with a
     runner-authored brief that is never the advisory contract), and the governed gate's
     injected invoke (covered by the gate's own check). The gate's production callers
     (`train_runner`, `legible_evidence`) pass no brief, so they run the built-in review brief. `governed_planning_gate` and
     `governed_premerge` use `invoke_panel` with the built-in instructions and take no caller
     brief. No other tierless promoter of a `PanelResult` takes a caller brief.
   - **Exposure-probe coverage, disclosed.** An advisory run's canonical-repo exposure probe
     targets the scratch authority, not the repository the caller runs from. Probing that
     repository as well needs a second probe target inside `ParentUnixBroker`, a broker internal
     this change does not touch. So an advisory run from inside a private repository does not
     re-check that the brokered child cannot see it. The child's bwrap mount set is fixed
     (`/usr`, `/lib*`, the broker socket dir, the staged review dir) and does not take the
     authority as an input; the probe is a canary on that, not the boundary. Default-board runs
     still probe their repository. That fixed set includes `/usr` and `/lib*`, so a repository
     under them (a container `WORKDIR /usr/src/app`, say) is readable by every seat whatever the
     authority; a default run from it refuses because its canary fires, an advisory run from it
     does not. This predates this change and applies to any repository not under review.
5. **Mac.** The sandbox stays Linux-only. The existing refusal lines are unchanged and each is
   followed by a hint: on a non-Linux host, run the board on a Linux host; in a
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

`phase-loop-runtime/tests/test_advisor_board_advisory_cli_802.py` (the existing
`test_advisor_board_advisory_mode.py` covers the #107 panel advisory mode and is unchanged):

- flag parsing;
- default path unchanged (compose called with no kwargs, `brief_ref` absent, review digest,
  JSON key set);
- the brokered seat prompt (one staged brief per board) carries the advisory contract as its
  authoritative frame, and the code-review brief is absent;
- `--advisory` with a landing tier, native president or capture is refused before any probe;
  inherited `GIT_*` is removed for the run and no probe seam sees it;
- runtime: every landing path refuses an advisory brief (`AdvisoryLandingRefused`), resolved once;
- an advisory native fill is refused by the review preflight;
- a no-repo run mints a real authorization against a scratch authority with no staged tree, and
  that authorization revalidates.
