# Partial review and bounded SL-0 repair

Reviewed candidate: `833c31c7bb0851ccac31c7de3aec2e1f1cad1a20`,
agent-harness#1208. GPT-6 Astra/red-team and GPT-6.1 Sol/adversarial each
returned usable DISAGREE through supported tool-enabled broker routes.
This was two seats from one actual vendor, not a full panel or approval.
Both records report heartbeat_only with model/silence deadlines null and
verified child/provider/broker quiescence plus root cleanup.

Astra F002: the frozen gate cases did not reject promotion after DEFERRED when
a changing ruling had no checked ledger row or the board was non-unanimous.
The downstream consumer tests did not cover this separate gate boundary.
Host reproduced its controlled bypass: all existing gate cases passed the
mutation, so the probe's assertion failed. The repair adds both gate-level
falsifiers, asserts that the post-receipt president seam was actually entered,
retains the ruling record and the successful agreeing/round-local control.

Sol F001: malformed `foreign` digest values allowed a format-only resolver to
pass the binding test while accepting a different well-formed candidate,
instruction, board or finding digest. Host reproduced its probe: DID NOT RAISE
at the expected assertion. The repair retains malformed controls and adds a
different valid-width hexadecimal value for each of those four identities.

Both host probes pass after the repair. Two frozen controls now demonstrate
that the gate-bypass and shape-only binding mutations are killed, with positive
controls and restoration of the original seams. This is synthetic test-strength
evidence, not a production implementation or route qualification.

The raw reports and host RED/green JUnit observations are retained under
`/mnt/workspace/archives/agent-harness-v10-continuation-20260930/` in
`ratify-sl0-supported-panel-20261001-round1/`, `ratify-sl0-F001-probe/`,
`ratify-sl0-F002-probe/` and `ratify-sl0-finding-probes-green.xml`.
Sol's offered new-file attachment path collided with an existing tracked node;
the host reproduction used a distinct scratch path, not an admitted production
attachment. Reviewer-side failures in unrelated existing network tests are
sandbox verification limitations, not candidate findings or waived failures.

The repair changes only the owned tests/adapter and evidence. The approved plan,
runtime, manifest, roster, transports and owner-held train wiring are unchanged.
The old receipt and regression artifacts are retained byte-for-byte under
`pre-review-833c31c7/`; the content boundary was restarted. Fresh exact-byte
reviews and required CI are required. No prior votes or CI transfer.
