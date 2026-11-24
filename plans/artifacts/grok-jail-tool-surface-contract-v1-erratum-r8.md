# Grok jail contract revision r8

Amends §2.4, §4.5, §5.2, §7, §7.1, §11, §14 item 4 and §20 of
[the frozen jail contract](grok-jail-tool-surface-contract-v1.md) for
agent-harness#2101. The eligibility record schemas and carry-forward rules still apply. This is the
jail contract revision. The tool-surface (TS) contract has its own erratum 8.

- **r8-1 — Condition 3 writer.** The owner reviews the observation from the separately approved offline,
  credential-free, no-egress confirmation of §2.4. The attended `measure-tools --record`
  stage verifies the private observation, the resolved image, and the running context and
  production launch digest on this architecture. It writes the §2.4 confirmation using
  the observed outcome and the owner's approval ID and date.
- **r8-2 — Condition 4 writer.** SL-4's standalone `measure-tools --hosted-check` stage takes the GitHub
  Actions run ID or its canonical run URL. It verifies the successful upstream `main`
  run on the installed head and the same-attempt, no-skip JUnit evidence for both BA-J1
  (§7) and BA-J5 (§2.4). The hosted BA-J5 launch and context digests must match the
  confirmed local production jail. A new jailed grant must name the recorded run.
  The [operator procedure](../../docs/ops/grok-jail-measurement.md) gives the invocation
  and the hosted receipt format. The operator supplies the installed head from the
  release manifest. The writer compares it with GitHub and verifies the runtime and jail
  digests. It does not independently read the release manifest or attest all packaged data
  bytes. The writer requires the whole upstream workflow to succeed. If unrelated job
  failures make that impractical, a later revision can pin the receipt producer to a
  specific successful job or dedicated workflow.
- **r8-3 — OWNER-DECISION r7-1 = A′ (owner, 2026-11-24).** A counted reservation settled
  `unspawned` leaves its label open once when its refusal code is in the closed transient
  class. The only member is `grok_sink_probe_timeout`, the §4.5 M2 helper timeout.
  Generic capped preflight, credential, qualification, identity, sink and binding
  refusals stop the grant. A second `unspawned` settlement for the same label also
  stops the grant. Unspawned reservations spend no request or retry. A later attended
  invocation resumes the label subject to the ledger, the rehearsal, and the remaining
  request and retry allowances. A consumed admission without settlement is still
  unresolved and charged in full. The budget-zero rehearsal keeps its separate attempt
  rules.

- **r8-4 — Refuse new unjailed grants (§5.2).** Once the Grok jail profile is registered,
  production grant creation must refuse new `grok_seat_context.v1` grants before writing
  grant state. Preserve the frozen TS basis and its unmodified test suites. Reading existing
  unjailed grants and exercising the legacy path with no Grok profile registered remain
  supported. The managed-subject plan's `GROK-R8-FOLLOWUP` lane delivers this guard. It blocks
  the §7 grant run.
- **r8-5 — Publish credential metadata at managed sign-in.** The credential-store writer
  for attended managed Grok sign-in publishes the private `credential-metadata.json`
  after successful sign-in. It records the positive `subscription` marker, Unix-second
  `expires_at`, and `auth_state` bound to a no-follow stat of the resulting `auth.json`.
  No credential bytes enter the metadata. Missing, stale or ambiguous metadata leaves
  the jailed credential preflight closed. The managed-subject plan's
  `GROK-R8-FOLLOWUP` lane delivers the sign-in publisher. It blocks the §7 grant run.
