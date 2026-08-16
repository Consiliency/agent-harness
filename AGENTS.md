# AGENTS.md

Agent guidance for contributors working in this repository.

This is the anchor for agent-facing conventions in `agent-harness`. Keep it
tight and self-contained.

## Referencing issues & PRs (multi-repo)

`agent-harness` is one node in a multi-repo fleet, so a bare `#123` is
ambiguous — it could mean an issue or PR in any repo. Always qualify the number
with its repository:

- Write `agent-harness#130`, or the fully-qualified `Consiliency/agent-harness#130`.
- Never write a lone `#130`.

This applies **everywhere a number appears**: chat and status updates, commit
messages, PR and issue bodies, handoffs, and closeout reports. When you
reference an issue or PR in another repo, qualify it with that repo
(`portal#42`, `consiliency-contract#7`), never a bare `#42`.

## Plan discipline (why phases stall)

The failure mode that has cost this repo the most is a plan that pins its own
future history — exact commit SHAs, commit counts, or the topology of work not
yet done. Git will not reproduce those identifiers, so the plan becomes
unsatisfiable and every landing forces another amendment.

- **Pin inputs, never your own outputs.** Upstream contract digests, schema
  versions, and frozen-artifact hashes are fine. SHAs, counts, or tree shapes of
  commits this plan will create are not.
- **Reference goals by ID** (`EC-<PHASE>-<N>`); never restate or paraphrase them.
  A paraphrase drifts and then two documents disagree about "done".
- **Keep plans short and let frozen artifacts carry the detail.** There is no
  fixed word cap; treat length as a signal to investigate.
- **Watch the ratio.** If plan amendments start outnumbering implementation, stop
  and diagnose rather than pushing through.

Full rationale, measured evidence, and the portable (one-machine) version:
`docs/agent-phase-convergence.md`.
