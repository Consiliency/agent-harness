# Proposal: review-seat sandbox roadmap phases

This proposal adds execution capability for review seats: agent-harness#848.

**It is a proposal, not a roadmap.** Nothing reads this directory. It is not registered in
`specs/roadmap-status.json`, has no entry in `plans/manifest.json`, and no phase-loop runner or gate
selects it. The phases in [`review-seat-sandbox.phases.md`](review-seat-sandbox.phases.md) become
executable only through the promotion rule below.

## Why a proposal instead of a roadmap edit

The location was decided by the four-seat panel, and the ruling is recorded on agent-harness#848:
[governance ruling](https://github.com/Consiliency/agent-harness/issues/848#issuecomment-5676508655).
In short:
- **v10's bytes are digest-frozen.** They are pinned in `roadmap_assumptions.CANONICAL_ROADMAP_SHA256` and in the committed plans, and HARDEN's proof asserts that binding.
- **A mid-flight edit already failed once.** The last one was reverted in `856ba198`.
- **A new active v11 would take the runner away from v10.**

So the phases wait here, as a fragment in v10 grammar.

## Pinned inputs

All pins are external inputs. None is an output of this work.

| Input | Pin |
|---|---|
| Base roadmap `specs/phase-plans-v10.md` | sha256 `9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0` |
| Consensus design (rounds 3–4, 4/4 AGREE) | [agent-harness#848 comment 5674979186](https://github.com/Consiliency/agent-harness/issues/848#issuecomment-5674979186), body sha256 `c720b742fb8de61c11dd7a31309307441033d7d6ef6b517705ab3830ebdd5d80` (measured as `gh api repos/Consiliency/agent-harness/issues/comments/5674979186 --jq .body \| sha256sum`) |
| Phase-0 gate evidence | Not yet published. Passing evidence for gates 9 and 11 is posted on agent-harness#848 and pinned here by digest before promotion (see the promotion rule). Every other gate's evidence is recorded as that phase's closeout evidence when it passes, before activation; this file is not its home after promotion. |

The design comment carries the detail: the architecture, numbers, layer keys, result taxonomy, and
the 12 Phase-0 gates. The phases cite it by gate number and never restate it. If that comment's body
digest changes, this proposal is stale and must be re-panelled.

## Validate and score

A fragment on its own cannot pass `validate-roadmap`: it has no level-2 headings, and `HARDEN` is an
unknown alias outside v10. Validate a composed copy in a temporary directory, never under `specs/`:

```bash
set -e
export PYTHONPATH="$PWD/phase-loop-runtime/src"
# the pinned base must be the bytes being spliced; a reseal changes the digest and stales this proposal
echo "9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0  specs/phase-plans-v10.md" | sha256sum -c
N=$(grep -n '^## Phase Dependency DAG$' specs/phase-plans-v10.md | cut -d: -f1)   # splice before this heading
T=$(mktemp -d) && mkdir -p "$T/specs"
{ head -n $((N - 1)) specs/phase-plans-v10.md
  cat docs/proposals/review-seat-sandbox.phases.md
  printf '\n'
  tail -n +"$N" specs/phase-plans-v10.md; } > "$T/specs/phase-plans-v10.md"
python3 -m phase_loop_runtime.roadmap_lint "$T/specs/phase-plans-v10.md"                   # expect: OK, 17 phases
python3 -m phase_loop_runtime.cli validate-roadmap --repo . --roadmap specs/phase-plans-v10.md  # registry coherence, run separately
python3 -m phase_loop_runtime.roadmap_ownership --repo . --base origin/main \
  --report 30 --candidate-roadmap "$T/specs/phase-plans-v10.md"
```

Run coherence as its own command. `validate-roadmap` on a path under `docs/` or a temp directory
derives the coherence repository from the path, so the coherence check becomes a silent no-op.

`roadmap_lint` does not check the `## Phase Dependency DAG` section, or whether a `Produces` gate is
listed under `## Top Interface-Freeze Gates`, and it accepts some wrong splice points. That is why
the recipe checks the digest and anchors on the heading.

Results when this proposal was written, at base `333dbc2b`:
- **Composed lint:** OK, 17 phases.
- **Coherence:** OK.
- **Ownership flag rate (last 30 landed changes):** 28/30 against both v10 and the candidate. The fragment adds no flags.

## Ownership overlap record

Owners computed by `roadmap_ownership.owners_for` on the composed candidate:

| File | Owners |
|---|---|
| `panel_invoker.py` | HARDEN, REVIEWTRUTH, LEGLIFE, GOVLEAN (directory token), SBXEXEC, SBXSEAT |
| `advisor_board/composition.py` | HARDEN, REVIEWTRUTH, LEGLIFE, GOVLEAN, SBXSEAT |
| `advisor_board/backing.py` | GOVLEAN (directory token), SBXEXEC. It is also a HARDEN *plan* owned file. |
| `phase-loop-runtime/scripts/verify_harden_evidence.py` | SBXSEAT. It is also a HARDEN *plan* owned file. |
| `review_sandbox/` (new) | GOVLEAN (directory token), SBXEXEC, SBXFETCH, SBXSEAT |
| `recipes/`, `.harden/execution.toml` (new) | SBXEXEC |

The overlaps are sequenced, not avoided. SBXEXEC depends on HARDEN, REVIEWTRUTH, and LEGLIFE, the
v10 phases with named claims on these files. GOVLEAN's claims are directory tokens, and its
`plans/manifest.json` lifecycle was already `completed` at base `333dbc2b`.

## Promotion rule

Promotion is one v10 amendment PR. It appends the fragment verbatim as Phases 14–16 and, because the
lint checks none of these, also adds:
- the DAG edges (`HARDEN`/`REVIEWTRUTH`/`LEGLIFE → SBXEXEC → SBXFETCH → SBXSEAT`), plus the serial-edge and frontier prose;
- the `IF-0-SBXEXEC-*` entries under `## Top Interface-Freeze Gates`;
- a `**Spec closeout policy**` block per phase;
- the design-comment pin (comment id and body digest) and the gate 9 and 11 evidence digests, so both survive leaving `docs/proposals/`.

One obligation falls on the SBXEXEC detailed plan rather than this file: gate 9's positive control
("the real test subset passes") must pass at SBXEXEC closeout, before the fetch and publish pipeline
EC-SBXFETCH-4 later requires exists. That plan names the test subset and the fixture layer that
satisfy it.

Who: the LEGIBLE owner authors it, it is reviewed by the four-seat board, and the operator signs it.

Mechanics: it is resealed with `roadmap_reseal.py`, and every committed plan's `roadmap_sha256` is
rebound in the same PR. No executing plan is rebound, because the Fallback below forbids amending at
all while one exists; that check is evaluated at the promotion PR's merge, not only when it opens.

It may open only when all of these hold:
1. HARDEN's manifest lifecycle is `completed`, and EC-HARDEN-5's state is recorded.
2. The two host-fact agent-harness#848 Phase-0 gates, which could invalidate the design before any code exists, have passing evidence pinned above by digest: every check of gate 9, whose positive control is the design-invalidating host fact, and gate 11 (full-suite calibration).
3. The composed candidate passes the validate-and-score recipe against the then-current v10.

Every gate, including those two, is also carried by a phase exit criterion, so activation requires passing evidence for every gate against the built code.

**Fallback.** "Executing" means a v10 plan with an open implementation PR or an in-flight runner
lane at that time. `committed` plans with no work in flight are rebound. If the rebind would touch an
executing plan, do not amend. Instead,
promote the fragment into the next `specs/phase-plans-v<N>.md` when v10 is flipped to `delivered`,
flipping the registry and banner in the same LEGIBLE-owned PR.

**Stopping rule.** Board rounds on this proposal's first PR are review rounds, not re-panels. After
it merges, each revision that needs a new board review counts as one re-panel. A revision that only
pins published evidence digests is not a re-panel: it changes no obligation. If more than two
re-panels are needed before HARDEN lands, abandon or re-diagnose the proposal rather than amending
again.
