# SEATS REMOTE contract (IF-0-REMOTE-1, IF-0-REMOTE-2)

Frozen artifact for `plans/phase-plan-v1-seats-REMOTE.md`. Roadmap: `specs/phase-plans-seats-v1.md`,
Phase 10. EC IDs are cited, never restated. A change to this file after the plan merges is a plan
amendment. A change to §4 (credential delivery) or §5 (codes, classes, descend set) is a security
change and needs a security review.

Pure types live in the new module `phase_loop_runtime/seat_remote_contract.py`. It holds data and
pure functions only and imports nothing beyond `seat_route_contract`. Names below are normative.

## 0. What REMOTE consumes, and what it never builds

| Consumed | Source | Used for |
|---|---|---|
| `RemoteRung.admit(RemoteRequest) -> RemoteAdmission(placed, code, activation_ref)`, `INACTIVE_REMOTE_RUNG`, `REMOTE_DESCEND_CODES`, `RoutePolicy`, `CapacityGrant`, `seat_remote_probe_receipt.v1`, `MODE_REMOTE` | JAILCORE contract §2, §3, §6 | the rung's shape, capacity entry and receipt |
| `JailProfile.argv`, `.config_surface`, `.allowlist_id`, `allowlist_ref`, `start_proxy(*, allowlist_id)` | JAILCORE contract §1, §7 | in-guest argv, upload masks, host-side upstream egress |
| `agent-harness-placement --client agent-harness reserve\|release\|reap\|version`; workload `leg`; rank policy `seats_single_target`; `Reservation.providers`, `.egress_sha256`, `.bridge`; the canonical effective-egress resolver | v13 IF-0-PLACECLI-1, IF-0-PLACECLI-2 | every placement effect |
| reserve, snapshot upload, one restricted exec of a fixed argv template, bridge attach, status/cancel, release, caller-scoped reap, bounded return | v13 IF-0-LANEEXEC-1 | every remote exec |
| `landlock-exec --policy <manifest> -- <argv>` | agent-harness#1795 revision 14, as pinned by `images/review-runner/Containerfile` | the in-guest restriction |
| `stock_policy_digest`, the stock field inventory, `REVIEW_POLICY_DIGEST` | `openshell_worker` | vector digests and field checks |

REMOTE builds no placement client, coordinator call, snapshot uploader, launch envelope, bridge,
worker launcher or local placement. A reserve, release or reap is one call to the placement
console entry from one inventoried launch site (`tests/data/seat_launch_references.json`). A
remote exec is one IF-0-LANEEXEC-1 launch. REMOTE requests only `openshell` targets, so the v13 local-headroom gate
(EC-PLACECLI-5) and XREQ-SEATS-LOCAL-CGROUP-1 are never on its path.

## 1. Per-provider vectors (IF-0-REMOTE-1)

File `contracts/placement/vectors/seat-provider-vectors.json`, schema `seat_provider_vectors.v1`.
It is the reviewed provider artifact that the v13 agent-harness client configuration references
(PLACECLI contract `x-provider-egress.registry`).

```json
{
  "schema": "seat_provider_vectors.v1",
  "baseline": "full-remote-pi-runner",
  "baseline_digest": "<policies.json policy_digest of the baseline>",
  "providers": [
    {
      "provider": "anthropic",
      "status": "pending_qualification",
      "network_policies": {},
      "request_set": "<request-set evidence record id>",
      "vector_digest": "<stock_policy_digest of the materialised vector>"
    }
  ]
}
```

- **One entry per provider.** `provider` matches the v13 `ProviderName` pattern and is unique.
  Keys: `anthropic` (claude), `google` (gemini), `openai` (codex), `xai` (grok), and OD-5's routed
  provider id (pi). `network_policies` is `{}` or `{<provider>: NetworkPolicyRule}` with exactly
  that one key. No entry names a second provider's host.
- **Materialised vector.** The `full-remote-pi-runner` document from `policies.json`, with
  `network_policies` replaced by the entry's map and nothing else changed. `vector_digest` is
  `stock_policy_digest` of that document. REMOTE v1 lists no path difference; one would need a new
  v13 protocol artifact version.
- **Endpoint rules.** Every `NetworkEndpoint` has `enforcement` ENFORCE, `tls` TERMINATE,
  `allow_uninspected_credentials` false and `rules` equal to the entry's measured guest-direct
  request set (method and path). `binaries` lists only the vendor CLI's in-image path, pinned by
  the image digest. Every other `NetworkEndpoint` field is unset or false: `access`,
  `allowed_ips`, `credential_binding`, `provider_credentialed`, `credential_signing`,
  `signing_service`, `signing_region`, `token_grant_owner`, the credential-rewrite flags, `mcp`,
  the GraphQL and JSON-RPC fields and `advisor_proposed`. `network_middlewares` stays the
  baseline's.
- **Guest-direct set.** Model traffic travels over the reservation bridge (§4), so the measured
  guest-direct set holds only requests the CLI makes outside its API base. It may be empty, and
  then the vector equals the baseline.
- **Status.** Each entry carries its own `pending_qualification`. Stage 2's flip of `policies.json`
  never changes an entry. Only that entry's activation-window record (§8) changes its status.
- **Validator.** `seat_remote_vectors.validate(vectors, vector_map, policies) ->
  tuple[VectorFinding, ...]` returns a finding for: any difference outside `network_policies`; a
  rule off ENFORCE or TERMINATE (AUDIT and PASSTHROUGH included); a listed field set; `allow_uninspected_credentials` not false; `binaries` other than exactly one
  absolute in-image path; an endpoint host that another entry also lists; rules not equal to the
  request set; a map key that is not the entry's provider; a duplicate provider; a
  digest that does not re-hash; or a `policies.json` baseline digest change. `policies.json`,
  `policy-digests.json` and `full-remote-pi-runner` are never written.

## 2. Vector map, probe set and C5

**Vector map.** `contracts/placement/vectors/seat-vector-map.json`, schema `seat_vector_map.v1`.
It holds one row per `(leg, routed_provider)`, which is unique:

`{leg, routed_provider, vendor, provider, image_digest, invocation, credential_row, projection}`

- `vendor` equals the leg's unique `kind="vendor"` readiness row (JAILCORE §2).
- `provider` is a §1 key.
- `invocation` is a §6 template id. `credential_row` is a §3 key. `projection` is `"none"`.
- Pi's `routed_provider` comes from `PiRoutedIdentity` (IF-0-PI-3).

The map replaces `openshell_worker`'s single pin as the selector of a seat's egress. The reserve
request names `full-remote-pi-runner` and exactly the row's `provider`, and v13 binds the result
into `egress_sha256`. `REVIEW_POLICY_DIGEST` remains the baseline check. REMOTE does not edit
`openshell_worker.py`, which v13 owns.

**Probe set.** `contracts/placement/vectors/remote-probe-set.json`, schema
`seat_remote_probe_set.v1`. Its `probe_set_digest` is sha256 over canonical JSON (sorted keys, no
whitespace).

- Each row is `{id, kind: egress|credential, origin: pinned_binary|tool_command, check}`.
- **Egress checks:** `unlisted_host`, `other_provider_host`, `same_front_end_host`,
  `denied_method_path`, `raw_ip`, `dns`, `private_range` and `metadata`. Each expects a refusal and
  runs once for each origin.
- **Credential checks:** `guest_holds_placeholder_only`, `refresh_request_refused`,
  `non_placeholder_bearer_refused` and `placeholder_expires`.
- This is the one generic egress-and-credential probe set (JAILCORE §6 and §8). v13 EC-ACTIVATE-2
  consumes it, and no second generic set exists.

**Probe evidence.** Schema `seat_remote_probe_evidence.v1`, stored in the operator-private store:

`{target, target_class, probe_set_digest, providers, openshell_version, gateway_version, image_digests, rows: [{probe_id, provider, origin, outcome}], observed_at}`

The JAILCORE receipt's `evidence_sha256` is sha256 of this file. A receipt covers exactly the
`providers` listed in it.

**C5 amendment** (`contracts/placement/README.md`). A placed review seat's egress is exactly the v13
effective grant for its one declared provider: the §1 materialised vector, recorded as
`egress_sha256`. Its only host link is the reservation bridge, and `service_exposures` stays empty.
The private allowlist stays empty. `inbound_closed`, `one_shot_secret_channel` and
`private_ranges_unreachable` are kept.

## 3. Credential table (IF-0-REMOTE-2)

`seat_remote_credentials.CREDENTIAL_TABLE: Mapping[str, RemoteCredentialRow]`, keyed by vendor.

```python
@dataclass(frozen=True)
class RemoteCredentialRow:
    vendor: str
    shape: Literal["oauth_access", "api_key"]
    delivery: Literal["requester_proxy", "unsupported"]
    host_lane: str                 # the existing host credential lane the local profile reads
    scope_evidence: str | None     # measured-scope record id; None keeps delivery "unsupported"
    placeholder_margin_s: Literal[60]  # fixed; not vendor-configurable
    refresh_matchers: tuple[str, ...]   # request (method, path) patterns the proxy refuses
    revocation: Literal["session_close", "session_close_and_upstream"]
    od7_api_key_ref: str | None    # required, and only allowed, when shape == "api_key"
    od7_lifetime_ceiling_s: int | None  # OD-7 ceiling for third-party targets only
```

- Each vendor row ships `unsupported` until lane B's measured record shows two things: the CLI
  sends all model traffic to an overridable API base, and it works with a placeholder credential.
  Each one-line justification goes in that record.
- No row's delivery is guest-held. The table has no channel that moves credential bytes into a
  sandbox.

## 4. Requester credential proxy and link

- **Placeholder.** For each seat, `open_session(row, reservation, deadline) -> ProxySession`
  mints one random placeholder. The placeholder is the only credential-shaped value the guest
  receives. It reaches the guest through its home or environment, and the CLI's API base is
  `http://127.0.0.1:<port>/<provider>`. The proxy accepts it only through `deadline + 60s` and
  refuses it after that instant. This is the EC-REMOTE-2 lifetime bound, and it applies to the
  placeholder—the only credential the guest can reach. An `od7_lifetime_ceiling_s`, where
  recorded, cannot extend the placeholder's expiry.
- **Pre-launch checks.** The host credential's scope must not exceed `scope_evidence`. An
  `api_key` row needs `od7_api_key_ref`. Both checks run before any reserve.
- **Swap and forward.** The proxy replaces the placeholder with the host credential and forwards
  upstream through `start_proxy(allowlist_id=profile.allowlist_id)`. That is one process and token
  per seat, bound to the vendor's IF-0-JAILCORE-2 allowlist. A profile with no allowlist refuses
  with `seat_egress_allowlist_missing`, and no open-egress exception applies remotely.
- **Refusals that end the seat typed:**
  - a request matching `refresh_matchers`;
  - a request carrying any credential other than the session placeholder;
  - downlink bytes that contain the host credential in any `contains_secret` encoding.
- **Renewal.** Host-side renewal stays in the host credential lane, and the renewal token never
  enters a frame.
- **Revocation.** `ProxySession.revoke()` runs on every terminal code, on deadline and on
  `release_unconfirmed` or `lost_after_launch`. It is idempotent. It invalidates the placeholder
  and closes the link. With `session_close_and_upstream` it also runs the vendor's upstream
  revocation.

**Link.** It runs over the reservation's `ForwardTcpUnixBridge` (IF-0-PLACECLI-2; XR-1).

- Framing is version 1 of the agent-toolkit link protocol at the v13-pinned revision
  (`docs/remote-placement.md`, "The link protocol"), restricted to the frames `hello`, `open`,
  `data`, `end` and `ping`.
- The receive-side bounds are unchanged: at most 2 requests in flight per proxied connection and
  128 overall, 32 MiB unread per connection and 64 MiB overall, and the pinned maximum frame size.
- Any other frame type, or a protocol error, ends the seat typed.
- The guest side is `seat_remote_relay`, baked into the image. It listens on loopback for the CLI
  and carries each connection as one channel.

## 5. Codes, classes and remote descend

The codes are additive entries in `seat_route_contract.CODES` and `OD10_CLASSES` (JAILCORE §3–§4
rules: each has a fix line, and none names a sealed or inline route or a key-based credential).
`REMOTE_DESCEND_CODES` becomes `{seat_remote_at_capacity, seat_remote_unreachable}`. That
addition is the security change this packet reviews. Every other code is terminal (W2).

| Code | Class | Raised at | Fix line (gist) |
|---|---|---|---|
| `seat_remote_at_capacity` | ordinary | R5 (descend) | the remote target is full; native fill or retry later |
| `seat_remote_unreachable` | ordinary | R5 (descend) | the remote target did not answer; nothing is held |
| `seat_remote_placement_refused` | ordinary | R5 | read the placement code in the decision's `also`; fix that configuration |
| `seat_remote_placement_uncertain` | ordinary | R5 | release runs; `phase-loop placement reap` clears what remains |
| `seat_remote_activation_missing` | ordinary | R1 | record a current probe receipt (owner-controlled) or OD-7 activation (third-party) |
| `seat_remote_activation_ignored` | ordinary | R0 sibling | fix the activation file's ownership or shape; the rung stays inactive |
| `seat_remote_activation_mismatch` | security | R1 | re-approve under OD-7 after re-running the probe set; report privately |
| `seat_remote_probe_scope_mismatch` | ordinary | R1 | re-run the probe set covering this provider |
| `seat_remote_vector_unmapped` | ordinary | R2 | no vector-map row for this leg and provider; the seat stays degraded |
| `seat_remote_vector_invalid` | security | R2 | reinstall the release; report privately |
| `seat_remote_lane_unsupported` | ordinary | R3 | this vendor's remote credential lane is pending; the seat stays degraded |
| `seat_remote_credential_lane_unapproved` | ordinary | R3 | API-key lanes need per-vendor OD-7 approval |
| `seat_remote_dependency_unwired` | ordinary | R4 | remote seats use image-baked runtimes only (agent-harness#1787) |
| `seat_remote_token_scope_excess` | security | R3 | re-issue the host credential at the measured scope; report privately |
| `seat_remote_target_mismatch` | security | R6 | target configuration disagrees with the activation; report privately |
| `seat_remote_deactivated` | ordinary | pre-exec | the vendor was deactivated after admission; nothing ran |
| `seat_remote_refresh_attempt` | security | post-launch | report privately |
| `seat_remote_foreign_credential` | security | post-launch | report privately |
| `seat_remote_credential_in_guest` | security | pre-exec or post-launch | report privately |
| `seat_remote_secret_in_output` | security | post-launch | report privately |
| `seat_remote_link_protocol_error` | security | post-launch | report privately |
| `seat_remote_tool_evidence_missing` | ordinary | post-launch | the result is not admitted; the board treats the seat as failed |
| `seat_remote_lost_after_launch` | ordinary | post-launch | revocation ran; nothing is replayed |
| `seat_remote_release_unconfirmed` | ordinary | post-launch | revocation ran; reap the reservation |

Post-launch codes never re-enter the walk (W5).

## 6. Rung and invocation

**Rung.** `SeatRemoteRung(policy, activation, deactivation, placement, *, routed_provider)`
implements `RemoteRung`. The JAILCORE construction site of `seat_route.resolve` builds one
instance per call. `routed_provider` comes from the leg's launch configuration: for Pi it is
`PiRoutedIdentity.launch_provider`, and for any other leg it is that leg's single map row.
- `RemoteRequest` keeps JAILCORE's five frozen fields (`leg`, `vendor`, `host_class`, `trigger`,
  `trigger_code`) and carries no target (JAILCORE ruling S2). For trigger `capacity`, the rung
  resolves the target from the matching `CapacityGrant` in the `RoutePolicy` it was built with.

- `admit` reserves at most once. After a placed admission, `held() -> RemoteSeat | None` returns
  the seat. The caller calls `release_unused()` on every exit that does not launch.
- Steps run in order, and the first failure returns its §5 code:

| Step | Check |
|---|---|
| R0 | an activation entry for vendor and host class, and the vendor not deactivated. Trigger `capacity` takes the entry from the matching `CapacityGrant`; any other trigger takes it from the activation file. Otherwise `seat_remote_rung_inactive` (JAILCORE skip). |
| R1 | Owner-controlled, and every trigger `capacity`: the receipt passes JAILCORE §6 condition 3; the receipt's and its evidence's `probe_set_digest` both equal the digest computed from the installed `remote-probe-set.json`; and the evidence has a `refused` row for every probe id and origin for the row's provider. Third-party: the vendor's OD-7 record and `activation_digests(vendor)` equal it; for trigger `capacity`, both the receipt checks and the OD-7 checks apply. |
| R2 | a vector-map row for `(leg, routed_provider)`, with `validate()` returning no findings. |
| R3 | a delivering credential row, scope within its evidence, and an allowlist present. |
| R4 | `projection == "none"`, else `refuse_unwired_dependency_route`. |
| R5 | `reserve`: `{schema, request_id (fresh), workload: "leg", ttl_s, image_digest, policy_vector: "full-remote-pi-runner", providers: [row.provider], deadline_ms, caller_context: {"route": "seat_remote"}}`. Outcome `admitted` goes to R6. `at_capacity`, `unreachable`, `refused` and `timeout` map to the R5 codes. Exit 70 retries once with the same `request_id`. |
| R6 | the reservation has `workload == "leg"`, `target.kind == "openshell"`, `target.name` equal to the R0 entry's target (the `CapacityGrant.target` for trigger `capacity`), `client` and `inventory` `agent-harness`, `rank_policy` `seats_single_target`, `image_digest == row.image_digest`, `policy_vector == "full-remote-pi-runner"`, `policy_digest == REVIEW_POLICY_DIGEST`, `providers == [row.provider]`, a non-null `bridge`, and `egress_sha256` equal to the v13 resolver's digest for the row. Otherwise release, then return `seat_remote_target_mismatch`. |

**Activation file.** `<state_home>/phase-loop/seat-remote-activation.json`, schema
`seat_remote_activation.v1`:

`{target, target_class, vendors: {vendor: {host_classes, probe_receipt | null, od7: {ref, digests} | null}}}`

- Reads use the JAILCORE overlay's ownership and mode checks. An unsafe file is ignored with
  `seat_remote_activation_ignored`.
- `activation_digests(vendor)` is computed from installed bytes. It covers the vectors file, the
  vector map, `seat_remote_vectors.py`, the row's image digest, its invocation template and relay
  module, and `seat_remote_credentials.py`, plus the OpenShell and gateway versions from the probe
  evidence. An owner-controlled entry binds no digest list (EC-REMOTE-3).
- **Deactivation** has its own file, `<state_home>/phase-loop/seat-remote-deactivated.json`
  (schema `seat_remote_deactivation.v1`, `{vendors: [vendor]}`), under the same checks. It covers
  both triggers.
  - `phase-loop seat-remote deactivate --vendor V` appends V atomically, creating the file if it
    is absent.
  - An unsafe or malformed deactivation file deactivates every vendor and adds
    `seat_remote_activation_ignored`.
  - R0 and the pre-exec check both read it.

**Invocation.** `run_remote_seat(seat, request, *, cancelled) -> RemoteSeatResult` makes one
IF-0-LANEEXEC-1 launch. Before exec, it re-checks that the vendor is active and the downlink holds
no host credential.

- **Image:** the row's `image_digest`, built from that vendor's target of
  `images/review-runner/Containerfile`. Each target adds one pinned vendor CLI and the relay, and
  the `landlock-exec` stage is unchanged.
- **Argv template** (one per vendor):
  `landlock-exec --policy <manifest> -- <relay> --port <p> -- <profile.argv(remote inputs)>`.
  Remote inputs:
  - tree `/work/<run-id>/tree`, read-only;
  - home `/work/<run-id>/home`, holding placeholders only;
  - out `/work/<run-id>/out`;
  - the API base pointed at the relay;
  - no credential fd.
- **Snapshot:** the approved staged tree in `full` mode under LANEEXEC's size cap, masked by
  `profile.config_surface.planted_paths`.
- **Return:** one bounded `seat_remote_result.v1` (`verdict`, `tool_evidence`, `exit_code`,
  `truncated: false`; no patch). It is admitted only when `tool_evidence` proves a staged-tree read
  (IF-0-FIRSTSEAT-3) and the output scan is clean.
- **Records:** the leg's exec record carries route `remote`, the template id, `reservation_id`
  and `activation_ref`.
- **Teardown:** release always runs. `sandbox_placement_lost_after_launch` and
  `sandbox_placement_release_unconfirmed` map to their §5 codes and call `revoke()`.

`run_probe_set(target, providers, *, cancelled)` uses the same launch path with the probe-image
target. That target installs the probe helper at each pinned binary path. The function writes
`seat_remote_probe_evidence.v1` and its receipt to the operator-private store.

## 7. Security-review packet and receipt

The EC-REMOTE-3 packet is private: it lives in the operator-private store, and the owner holds the
approval. The repository carries only
`plans/evidence/seats-remote/security-review-receipt.json`, schema `seat_remote_review_receipt.v1`:

`{packet_sha256, od7_ref, approved_on, scope: "design", covers: ["IF-0-REMOTE-1", "IF-0-REMOTE-2", "REMOTE_DESCEND_CODES"]}`

The receipt contains no packet content.

## 8. Activation-window record (EC-REMOTE-5)

The record is `plans/evidence/seats-remote/windows/<date>.json`, schema `seat_remote_window.v1`,
metadata only:

`{target_class, probe_set_digest, receipt_evidence_sha256, openshell_version, gateway_version, rows: [{vendor, host_class, status, evidence_digest}], providers_flipped}`

- It lands through a reviewed window PR (roadmap principle 5).
- That PR alone may move a §1 entry out of `pending_qualification` and a matrix row to
  `done-remote`.
