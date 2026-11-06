# SEATS JAILCORE route contract (IF-0-JAILCORE-1, IF-0-JAILCORE-2)

Frozen artifact for `plans/phase-plan-v1-seats-JAILCORE.md`. It carries the detail the plan
points at. Roadmap: `specs/phase-plans-seats-v1.md`, Phase 3. EC IDs are cited, never restated.
Downstream phases (CODEX, GROK, PI, CLAUDENET, REMOTE) plan against this file. A change to it
after the plan merges is a plan amendment. A change to §3 (descend list) or §6 (capacity gate)
is a security change and needs a security review.

All types live in the new module `phase_loop_runtime/seat_route_contract.py`. It holds pure
data and pure functions only. It imports nothing from `panel_invoker`, `seat_jail` or any I/O
module. Names below are normative.

## 1. Leg profile (IF-0-JAILCORE-1)

A vendor joins the jail by adding one `JailProfile` to the registry in
`phase_loop_runtime/seat_profiles.py` (`register(profile)`, `profile_for(leg)`,
`registered_legs()`). `seat_jail.JAILED_LEGS` becomes `frozenset(registered_legs())`.

```python
@dataclass(frozen=True)
class JailProfile:
    leg: str                      # board harness name; registry key
    vendor: str                   # readiness-matrix vendor row id
    # Owner-argv contributions. The core builders in seat_jail.py contain no leg branch.
    owner_binds: Callable[[OwnerPaths], Sequence[str]]   # inserted where _gemini_binds sits today
    env: Callable[[EnvInputs], Mapping[str, str]]        # added to the base seat_env
    home_dirs: tuple[str, ...]                           # created 0700 under seat-home
    digest_placeholders: Callable[[OwnerPaths], Mapping[str, str]]  # actual -> canonical
    mount_points: Callable[[OwnerPaths], Sequence[str]]  # extra declared mount points (J1)
    new_session: bool
    token_fd: bool                # passes CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR-style fd
    # Provider launch.
    argv: Callable[[ArgvInputs], Sequence[str]]          # provider argv inside the jail
    projection: Literal["none", "optional", "required"]  # executable-dependency requirement
    # Credential.
    credential: CredentialDelivery
    credential_present: Callable[[], bool]
    credential_missing_code: str
    # Ordered local preconditions after host capability and credential; each returns
    # None or exactly one code. Gemini: profile qualification. Egress is NOT here (§2, L7).
    preconditions: tuple[Precondition, ...]
    recorded_stop: str | None     # GEMINI_RECORDED_STOP moves here
    # EC-JAILCORE-6 declarations.
    config_surface: ConfigSurface
    auth_probe: Callable[[], Literal["healthy", "signed_out", "unavailable"]]  # IF-0-FIRSTSEAT-3
    output_secret_code: str       # terminal; e.g. claude_seat_token_in_output
    containment: ContainmentEvidence
    # Egress (IF-0-JAILCORE-2). None: degraded unless an unexpired "open egress" exception.
    allowlist_id: str | None
    # Variant selector (Claude only today): returns (variant, None) or (None, refusal).
    variant: Callable[[Mapping[str, str]], tuple[str | None, str | None]] | None
    notice_codes: frozenset[str]  # every code this profile may emit
```

Supporting shapes, all frozen dataclasses:

- `CredentialDelivery(channel: Literal["token_fd", "home_file", "none"], scope_evidence: str | None)`.
  Claude is `token_fd`; Gemini is `home_file` (the access-token-only copy). `scope_evidence`
  names the evidence record of the measured scope, or `None` while unmeasured.
- `ConfigSurface(closed: bool, planted_paths: tuple[str, ...])`. `planted_paths` are tree-relative
  paths the falsifier plants: project settings, hooks, MCP servers and provider overrides. `closed`
  must be `True` for every registered profile.
- `ContainmentEvidence(credential_scope: str | None, refresh_detection: str | None,
  unlisted_endpoint_refused: str | None, deferred_to: str | None)`. Each field names an evidence
  record id, never a value. Claude sets `deferred_to="EC-CLAUDENET-3"` and leaves the rest `None`.
- `Precondition(name: str, check: Callable[[], str | None])`.
- `OwnerPaths`, `EnvInputs`, `ArgvInputs`: the per-launch values `_owner_argv`, `seat_env` and the
  provider launch take today (tree, home, out, provider, fds, egress CA, proxy URL, transport).

Registration invariants (tested): every `notice_codes` member is in `mode_line_codes()` (§4);
`output_secret_code` is OD-10 `security`; `config_surface.closed` is true; a profile with
`allowlist_id=None` has a named exception or resolves degraded (§2, L7).

Digest invariance (EC-JAILCORE-1): `_profile_digest_of` keeps its formula and `PROFILE_ID`.
`jail_profile_digest(leg)` and `actual_profile_digest(jail)` produce byte-identical canonical
documents for `claude` and `gemini` before and after the registry change.

## 2. Resolver walk (EC-JAILCORE-2, EC-JAILCORE-5)

`seat_route.resolve(request: RouteRequest, *, policy: RoutePolicy, remote: RemoteRung,
native: NativeFillRung) -> RouteDecision`. It runs before launch only and is the one decision
`_seat_route_for_spawn` and the seat-mode line both read. It has no `leg ==` branch.

`RouteRequest(leg, vendor, seat_key, host_class, run_kind, staged_tree_approved, env)`.
`run_kind` is one of `review`, `advisory_document` or `qualification_candidate`. Only `review`
is governed by this walk. The other two keep their current routes unchanged
(agent-harness#802, agent-harness#1170). A Claude seat deferred to the driving session
(`under_claude_code`) keeps that route before the walk; it is not a failed step.

Local rung, in order; the first step that yields a code ends the rung:

| Step | Check | Code on failure |
|---|---|---|
| L0 | staged tree approved | `seat_sandbox_not_staged` |
| L1 | `profile_for(leg)` exists | named exception `unconfined`, unexpired: mode `unconfined` with `seat_filesystem_unconfined`. Expired: `seat_route_exception_expired`. None: `seat_profile_unregistered` |
| L2 | `profile.recorded_stop is None` | that stop's code |
| L3 | `seat_jail.seat_sandbox_capable()` | `seat_sandbox_unavailable_host` / `_tiocsti` / `_seat_uid` |
| L4 | `profile.variant` (Claude transport selector) | `panel_claude_route_invalid` / `panel_claude_transport_not_admitted` |
| L5 | `profile.credential_present()` | `profile.credential_missing_code` |
| L6 | `profile.preconditions` in order | the precondition's code |
| L7 | allowlist set: `seat_egress_proxy.unavailable_code()` is None. Unset: unexpired `open egress` exception | `seat_egress_not_installed` / `seat_egress_integrity_failed` / `seat_egress_tls_unterminated`. Unset with no exception: `seat_egress_allowlist_missing`; expired: `seat_route_exception_expired` |
| L8 | qualification pass for the §5 key (EC-EXECFIND-2; A2 auto-qualify) | `seat_jail_qualification_failed` / `seat_sandbox_refused:jail_unqualified` / `seat_sandbox_refused:pass_store_unsafe` |
| L9 | free seat id (`seat_uid` lease available); runs only after L0–L8 pass | `seat_local_capacity_exhausted` |

L9 splits today's `seat_uid_available()`. Missing helpers, range or a uid-0 operator stays
`seat_sandbox_unavailable_seat_uid` at L3. No free seat id is capacity, not host capability,
and it is checked last so it never hides another step's code. A lease that fails at launch
after L9 saw a free id is also `seat_local_capacity_exhausted`, before launch.

Walk rules (each is a test):

- **W1.** A later rung is entered only when the local code is in `DESCEND_CODES` (§3), or
  the policy routes the vendor remote (§6, R-routed), or the capacity gate opens (§6).
  Any other code yields mode `degraded` with that code, and no later rung is consulted.
- **W2.** Remote rung: `remote.admit(RemoteRequest(leg, vendor, host_class, trigger,
  trigger_code))` returns `RemoteAdmission(placed, code, activation_ref)`. JAILCORE ships
  `INACTIVE_REMOTE_RUNG`, which always returns `(False, "seat_remote_rung_inactive", None)`.
  That is a skip, so the walk continues. Any other unplaced code moves on only if it is in
  `REMOTE_DESCEND_CODES`, which JAILCORE ships empty. REMOTE adds codes there under security
  review. Otherwise the result is `degraded` with that code.
- **W3.** Native-fill rung: `native.offer(seat_key, leg) -> bool`. JAILCORE backs it with the
  existing `_native_fillable_seats` routing. Offered gives mode `native` with the triggering
  code and native-fill provenance. Not offered is a skip (`seat_native_fill_unavailable`).
- **W4.** Degraded: mode `degraded`. The mode-line code is the first `failed` step's code or,
  when no step failed (an R-routed row), the remote rung's code. Nothing launches.
- **W5.** Codes raised after launch never re-enter the walk. The leg ends with its terminal
  code, and no rung launches for that seat again.
- **W6.** A review seat never gets mode `sealed`. Every `SEALED_FALLBACK_CODES` member yields
  `degraded`, unless it is on the descend list (W1). This is the agent-harness#1282 falsifier.

```python
@dataclass(frozen=True)
class RouteStep:
    rung: Literal["local", "remote", "native_fill", "degraded"]
    step: str                     # "L0".."L9", "R", "N", "D"
    outcome: Literal["selected", "failed", "skipped"]
    code: str | None
    od10_class: Literal["security", "ordinary"] | None

@dataclass(frozen=True)
class RouteDecision:
    leg: str
    vendor: str
    mode: Literal["jailed", "unconfined", "remote", "native", "degraded"]
    code: str | None              # the one mode-line code; None only for a clean `jailed`
    steps: tuple[RouteStep, ...]  # one entry per evaluated step that failed or skipped
    exception: NamedException | None
    variant: str | None           # Claude transport when jailed
    qualification_key: QualificationKey | None
    also: tuple[str, ...]         # sibling notices, e.g. seat_route_policy_ignored
```

`seat_preflight` gains `MODE_REMOTE = "remote"`. Nothing emits it until REMOTE activates a
rung.

## 3. Closed descend list and code classes

```python
DESCEND_CODES = frozenset({
    "seat_sandbox_unavailable_host",
    "seat_sandbox_unavailable_tiocsti",
    "seat_sandbox_unavailable_seat_uid",
    "seat_egress_not_installed",      # the not-installed half of gemini_seat_egress_unavailable
})
REMOTE_DESCEND_CODES: frozenset[str] = frozenset()
CAPACITY_CODES = frozenset({"seat_local_capacity_exhausted"})  # never descends; §6 gate only
```

`gemini_seat_egress_unavailable` is split by cause, inside
`seat_egress_proxy.unavailable_code()`:

- `seat_egress_not_installed` means node or srt is absent: `_node()` fails, or
  `verify_install` cannot read `package.json` or the lock file.
- `seat_egress_integrity_failed` means an installed tree does not verify: wrong version, wrong
  package record, a link, or a tree digest mismatch. It is terminal and `security`.
- `seat_egress_tls_unterminated` means the proxy started without TLS inspection or without its
  fail-closed front. It is terminal and `security`.

The split names are vendor-neutral because the srt install is one host install for every
allowlist. `gemini_seat_egress_unavailable` stays in `NOTICES` for record readback and is no
longer emitted.

OD-10 `security` codes (private record and owner summary; never filed publicly):

- `seat_sandbox_refused:identity`, `seat_sandbox_refused:token_file_unsafe`,
  `seat_sandbox_refused:stage_changed`, `seat_sandbox_refused:output_unsafe`;
- `gemini_seat_token_in_output`, `gemini_seat_token_scope_excess`,
  `gemini_seat_egress_unconfined`, `gemini_seat_token_refreshed_in_jail`,
  `gemini_seat_credential_unusable`;
- `seat_egress_integrity_failed`, `seat_egress_tls_unterminated`;
- every `claude_seat_transport.CODES` entry whose class is `security`, read from that table
  and not restated.

Every other code is `ordinary`. Default rule: a code is terminal unless it is in
`DESCEND_CODES`. A new code is terminal by default.

## 4. Route codes (new; `seat_route_contract.CODES`)

Each entry is `code: (od10_class, what, why, fix)`. Like `claude_seat_transport.CODES`, these
stay outside `seat_jail.NOTICES`. `mode_line_codes()` returns `seat_jail.NOTICE_CODES |
claude_seat_transport.CODES | seat_route_contract.CODES`, and `panel_invoker._HARNESS_DETAIL_CODES`
includes all three. No fix line names a sealed or inline route, or a key-based credential.

| Code | Class | Role | Fix line (gist) |
|---|---|---|---|
| `seat_egress_not_installed` | ordinary | descend | run `phase-loop seat-egress install`, then re-run |
| `seat_egress_integrity_failed` | security | terminal | reinstall with `phase-loop seat-egress install`; report the outcome privately |
| `seat_egress_tls_unterminated` | security | terminal | reinstall the egress layer; report the outcome privately |
| `seat_egress_allowlist_missing` | ordinary | terminal | the vendor phase registers its allowlist; the seat stays degraded until then |
| `seat_profile_unregistered` | ordinary | terminal | the vendor has no jail profile yet; the seat stays degraded until its phase registers one |
| `seat_route_exception_expired` | ordinary | terminal | only an owner record in the readiness matrix renews an exception |
| `seat_local_capacity_exhausted` | ordinary | capacity | wait for a running seat to finish, then re-run |
| `seat_route_row_remote` | ordinary | skip | the readiness matrix routes this vendor to the remote rung |
| `seat_remote_rung_inactive` | ordinary | skip | no remote route is active for this vendor on this host class |
| `seat_native_fill_unavailable` | ordinary | skip | the driving session cannot fill this seat |
| `seat_capacity_offloaded` | ordinary | notice | none (informational) |
| `seat_route_policy_ignored` | ordinary | sibling notice | fix the host route-policy file's ownership or shape; capacity offload stays off |

## 5. Qualification key (EC-JAILCORE-4)

```python
@dataclass(frozen=True)
class QualificationKey:
    profile_digest: str              # jail_profile_digest(leg)
    allowlist_digest: str | None     # §7 content digest; None only under an open-egress exception
    falsifier_layout: str            # seat_jail.falsifier_layout_identity()
    projection_digest: str | None    # DependencyProjection.digest when projected, else None
    variant: str | None              # Claude transport; None for other legs
    host_identity: str               # seat_jail.host_identity()

def key_digest(key: QualificationKey) -> str  # sha256 over canonical JSON, sorted keys
def record_binding(key: QualificationKey) -> Mapping[str, object]  # fields a record must equal
```

Pass records move to schema `seat_jail_pass.v2`, named `<key_digest>.json` in the same
operator-private store, with the same evidence-file binding. v1 records are not honoured, so
a pass never carries across a key part. The host re-records on first use through the existing
A2 auto-qualify. No row status changes, because no profile or allowlist digest changes. The
auto-qualify cache and failure records are keyed by `key_digest`.

## 6. Route policy and the capacity gate

```python
@dataclass(frozen=True)
class RoutePolicy:
    schema: Literal["seat_route_policy.v1"]
    routed_remote: frozenset[str]                  # vendors the matrix marks remote-pending
    exceptions: Mapping[str, NamedException]       # from seat_window.readiness_rows()
    capacity_offload: tuple[CapacityGrant, ...]    # default: ()

@dataclass(frozen=True)
class NamedException:
    vendor: str
    kind: Literal["unconfined", "open egress"]
    expiry: datetime                               # UTC
    end_condition: str

@dataclass(frozen=True)
class CapacityGrant:
    target: str                                    # remote target id (REMOTE's vector or backend ref)
    target_class: Literal["owner_controlled", "third_party"]
    host_classes: frozenset[str]
    vendors: frozenset[str]                        # explicit; no wildcard
    probe_set_digest: str                          # the generic egress-and-credential probe set
    probe_receipt: str                             # receipt id in the operator-private store
    activation_refs: Mapping[str, str]             # vendor -> OD-7 activation; third_party only
```

Sources:

- `exceptions` and `routed_remote` are read from `seat_window.readiness_rows()`, read-only.
- `capacity_offload` is the packaged default `()`. It can be overlaid only by an
  operator-private host file, `<state_home>/phase-loop/seat-route-policy.json`, under the
  same ownership and mode checks as the pass store (`pass_store_dir_problem`, private file
  read).
- An unsafe, unreadable or malformed overlay is ignored: offload stays off, and the decision
  carries `seat_route_policy_ignored`.
- The overlay may set `capacity_offload` only. It cannot change `DESCEND_CODES`,
  `REMOTE_DESCEND_CODES`, exceptions or routed rows.

Gate. Capacity offload is entered only when all of these hold:

1. L9 yields `seat_local_capacity_exhausted` (so L0–L8 passed).
2. A grant lists the vendor and the host class.
3. Its probe receipt (schema `seat_remote_probe_receipt.v1`: `target`, `target_class`,
   `probe_set_digest`, `result: "pass"`, `observed_at`, `expires_at`, `evidence_sha256`)
   binds the same target, class and probe-set digest, is unexpired, and its evidence
   re-hashes.
4. For `third_party`, `activation_refs` holds that vendor's OD-7 activation.
5. The remote rung places the seat.

Otherwise the seat keeps today's behaviour for a capacity code: `degraded` with
`seat_local_capacity_exhausted` (W1). A placed seat carries `seat_capacity_offloaded`.
R-routed: a vendor in `routed_remote` skips the local rung with one step (`L`, `skipped`,
`seat_route_row_remote`) and walks R, then N, then D.

Shipped state: no grants, the rung inactive and `REMOTE_DESCEND_CODES` empty. With that,
the walk satisfies EC-JAILCORE-2's "never capacity overflow" as written today. The owner's
capacity ruling becomes effective through a host overlay and REMOTE's receipt, with no code
change, once the roadmap sentences listed in the plan are amended.

## 7. Per-provider egress (IF-0-JAILCORE-2)

`seat_egress_proxy.allowlist_ref(allowlist_id) -> AllowlistRef(id, content_digest,
request_set, probe_rows)` reads `seat_egress/<id>-allowlist.json`, schema
`phase_loop_seat_egress_allowlist.v1`. `content_digest` is the sha256 of the canonical JSON of
its `allow` array, with sorted keys and no whitespace. `gemini-allowlist.json` stays
byte-identical; its id is `gemini`. `probe_rows` are derived from `allow` and
`measured_and_refused`: one allowed request per rule, one refused per measured-and-refused
host, and an unlisted host.

`start_proxy(*, allowlist_id: str, inner_sni_check: bool = True)` starts one process with one
session token per call, bound to exactly that allowlist. It raises `EgressLayerUnavailable`
with `.code` set to a §3 egress code. `egress_evidence(proxy)` adds `allowlist_id` and
`allowlist_digest`. `unavailable_code() -> str | None` sits beside the unchanged
`unavailable_reason()`, which the CLI and doctor keep using. A seat never shares a proxy
process or token. One proxy never serves two allowlists.

## 8. Roadmap sentences the pending capacity ruling amends

The owner's pending ruling: on owner-controlled hosts, review seats may offload for capacity
once the remote route passes one generic egress-and-credential probe set, and the per-vendor
OD-7 review stays only for third-party clouds. This contract implements the ruling as a
policy input (§6) that ships disabled. It does not amend the roadmap. The coordinator amends
these sentences in `specs/phase-plans-seats-v1.md`, quoted verbatim; the rest of each EC stays.

Capacity (required before any grant is honoured):

1. Architecture North Star, rung 2: "(per-vendor owner activation; REMOTE). Never used for
   capacity."
2. Architecture North Star, rung 1 note: "only the closed descend list (host capability)
   descends, only before launch"
3. IF-0-JAILCORE-1: "It also fixes the closed descend list, the only codes that may move to a
   later rung:"
4. EC-JAILCORE-2: "Only codes on IF-0-JAILCORE-1's descend list move to a later rung, and only
   before launch (the agent-harness#1250 precedent)."
5. EC-JAILCORE-2: "The remote rung serves only rows and host classes the matrix routes there,
   never capacity overflow."

Activation scope (owner-controlled targets activate by the generic probe set; per-vendor OD-7
stays for third-party clouds):

6. Owner Decisions table, OD-7 row: "Approve the remote design; later, activate each vendor,
   binding the digests EC-REMOTE-3 lists"
7. Principle 1: "A remote row means the same on the remote rung after per-vendor activation."
8. REMOTE Objective: "Give each row the matrix routes remote, and each host class without jail
   prerequisites, a remote sandbox seat with provider-only egress, behind security review and
   per-vendor owner activation."
9. EC-REMOTE-3: "Each vendor's activation approval binds the digests of the vectors, the vector
   map, the validator, the image, EC-REMOTE-6's guest invocation and delivered runtime, and the
   credential module, plus the OpenShell and gateway versions."
10. EC-REMOTE-4: "The remote rung is the resolver's step 2, disabled until per-vendor
    activation, and refuses unwired dependency routes (agent-harness#1787)." and "The rung
    refuses a vector with no activation record for its vendor."
11. EC-REMOTE-5: "Then, with Stage 2's infrastructure live (LA-4) and per-vendor activation
    under OD-7, every row the matrix routes remote reads `done-remote` from the activation
    window."
12. REMOTE Governance: "and per-vendor activation, which binds the EC-REMOTE-3 digests, before
    EC-REMOTE-5 (a later change to any bound digest voids it)."
13. Roadmap Acceptance Criteria: "Each row the matrix routes remote, and each host class with
    no local jail, has a remote route activated per vendor under OD-7, after the Stage 2 proof
    amendment."

Open for the owner: whether third-party targets may take capacity offload at all, even after
OD-7 activation. §6 can express either answer, and both ship disabled.
