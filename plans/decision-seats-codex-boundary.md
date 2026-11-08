# Codex review-seat boundary — OD-4 accepted

Status: **accepted**. Decision owner: repository owner. Date: **2026-11-08**.
Scope: CODEX SL-3, agent-harness#1916; roadmap OD-4 and EC-CODEX-2,
EC-CODEX-3, EC-CODEX-5.

The owner selected **“Accept (Recommended)”** in response to: “should the jail be
Codex review seats' only boundary, with Codex's inner sandbox off, accepting that
tools can read the seat's own Codex login copy and share the seat's proxy-only
egress”. The owner communicated this acceptance to the SL-3 executor on 2026-11-08
and authorized SL-3.7 onward. This supersedes the earlier OD-4 hold.

The jail is the Codex review seat's only boundary. Its argv uses
`--sandbox danger-full-access`; the inner sandbox is off. Tools can read the
seat's own Codex login copy in seat home and inherit its allowlisted proxy
egress. Credential delivery is a file copy, not a sealed descriptor. Its measured
scope ceiling, empty refresh token, refresh detection and parent-held completed
command evidence remain required. A zero-command or failed-command leg does not
count as a review. This accepts the boundary described above; it does not admit
a wider credential or egress set.

## Evidence accepted by the owner

Input head: `36d785c19464f5b9dcde202528f9c7651755296a` in agent-harness#1916.
The two records below are preserved byte for byte as the accepted inputs; their
OD-4 hold text describes their publication time, before this decision.

| Record | SHA256 |
|---|---|
| [provider-free.json](evidence/seat-codex/provider-free.json) | `2d3ec21ed625e2a766547d59c0471ee8b727be67484e0fdc83cb440b6e07c83e` |
| [refresh-detection.json](evidence/seat-codex/refresh-detection.json) | `b59d933d12445c2a97a048b4714c43bb1d5349e2d306301022131fb84218dfa6` |

The packet records ai VL **6 passed, 0 failed, 0 skipped**, ai
`qualify("codex")` **8/8 checks passed**, and dev0 VL **6 passed, 0 failed,
0 skipped**. Credential scope is recorded in
[credential-scope.json](evidence/seat-codex/credential-scope.json); refused
endpoints are recorded in [allowlist-probes.json](evidence/seat-codex/allowlist-probes.json).
The provider-free and refresh receipts carry the subsequent live results.
No provider turn or real-login operation is authorized by this decision.

## agent-harness#1480 route decision

**Removed:** the seat-launch-owner fallback for `review` seats. Registration of
`CODEX_PROFILE`, its provider executable and its admission gate means contract
step L1 cannot take the `unconfined` exception for Codex. A missing local
prerequisite walks the contract's remote, native-fill and degraded rungs; a
terminal refusal stays terminal. It never silently runs an unconfined review.
`advisory_document` and `qualification_candidate` keep their contract §2 routes.

The staged `workspace-write` branch, writable-tree grant and Codex's retained
`setfcap` capability are retired. The agent-harness#1469 sandbox probe remains on
the non-brokered route. The jailed route uses its completed-command record and
CLI-shape gate. Claude/Gemini profiles and golden digests are unchanged.

## Related dispositions and post-merge text

These are prepared texts, **not posted closure actions**. Independent review and
merge of agent-harness#1916 remain outstanding. The row window and `done-local`
reducer belong to SL-4, not this SL-3 landing.

- **agent-harness#1480 — post-merge closure draft:** “Delivered by agent-harness#1916.
  OD-4 was accepted on 2026-11-08 with the linked credential, egress, completed-command
  and provider-free evidence. Codex review seats use the registered jail profile;
  the seat-launch-owner fallback is removed for reviews. The jail is the boundary,
  tools can read their own seat login copy, and egress is proxy-only. Row-window
  qualification and optional team-host coverage retain their separate roadmap scope.”
- **agent-harness#1644 — citation / post-merge follow-up draft:** “OD-4 accepted
  2026-11-08; the jailed Codex route in agent-harness#1916 supersedes the nested
  AppArmor candidate. The [existing INVENTORY closure](https://github.com/Consiliency/agent-harness/pull/1644#issuecomment-6690193918)
  remains applicable. No candidate policy installation or qualification is claimed.”
- **agent-harness#1731 — citation / post-merge follow-up draft:** “The
  [existing INVENTORY closure](https://github.com/Consiliency/agent-harness/pull/1731#issuecomment-6690194320)
  cites the denial evidence in [agent-harness#1641](https://github.com/Consiliency/agent-harness/pull/1641).
  OD-4 accepted 2026-11-08 and agent-harness#1916 supersede the nested-sandbox
  diagnostic route, together with agent-harness#1644. This does not claim the
  canary's outstanding live acceptance was completed.”

agent-harness#1644 and agent-harness#1731 were already closed by INVENTORY on
2026-11-06. OD-4 acceptance does not trigger their conditional reopening. No
issue or PR is closed by this change.

## SL-3.9 follow-up

[post-registration.json](evidence/seat-codex/post-registration.json) records the
passing post-registration dev0 compatibility replay and provider-free VL against
source head `388be402`, completing SL-3 verification. The exact owner watchdog
predicate passed eight synthetic controls before the single authorized retry.
The accepted OD-4 input records above remain byte-identical. No ai run, live
provider turn, real-login operation, issue closure or row-window promotion was
performed in this follow-up. Independent review remains the next step.
