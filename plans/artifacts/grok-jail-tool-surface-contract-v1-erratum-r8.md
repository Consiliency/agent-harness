# Grok jail tool-surface contract v1, erratum r8

Amends §2.4, §4.5, §7, §7.1 and §20 of
[the frozen jail contract](grok-jail-tool-surface-contract-v1.md) for
agent-harness#2101. The eligibility record schemas and carry-forward rules still apply.

- **Condition 3.** The owner reviews the observation from the separately approved offline,
  credential-free, no-egress confirmation of §2.4. The attended `measure-tools --record`
  stage verifies the private observation, the resolved image, and the running context and
  production launch digest on this architecture. It writes the §2.4 confirmation using
  the observed outcome and the owner's approval ID and date.
- **Condition 4.** SL-4's standalone `measure-tools --hosted-check` stage takes the GitHub
  Actions run ID or its canonical run URL. It verifies the successful upstream `main`
  run on the installed head and the same-attempt, no-skip JUnit evidence for both BA-J1
  (§7) and BA-J5 (§2.4). The hosted BA-J5 launch and context digests must match the
  confirmed local production jail. A new jailed grant must name the recorded run.
  The [operator procedure](../../docs/ops/grok-jail-measurement.md) gives the invocation
  and the hosted receipt format.
- **OWNER-DECISION r7-1 = A′ (owner, 2026-11-24).** A counted reservation settled
  `unspawned` leaves its label open once when its refusal code is in the closed transient
  class. The only member is `grok_sink_probe_timeout`, the §4.5 M2 helper timeout.
  Generic capped preflight, credential, qualification, identity, sink and binding
  refusals stop the grant. A second `unspawned` settlement for the same label also
  stops the grant. Unspawned reservations spend no request or retry. A later attended
  invocation resumes the label subject to the ledger, the rehearsal, and the remaining
  request and retry allowances. A consumed admission without settlement is still
  unresolved and charged in full. The budget-zero rehearsal keeps its separate attempt
  rules.
