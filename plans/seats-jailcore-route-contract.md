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
`registered_legs()`) and one `seat_egress/<id>-allowlist.json`, and its own `<leg>_seat_*` codes in `seat_jail.NOTICES`, each with one additive `OD10_CLASSES` entry; no existing entry or descend set changes. Its window rows are data on that profile, added under the same rule. `seat_jail.JAILED_LEGS` becomes `frozenset(registered_legs())`.

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
    window: WindowRows | None     # window-kit vendor gate and path rows (data only)
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
- `WindowRows`: the profile's data for `seat_window`'s vendor gate and per-vendor path rows,
  meaning its record-field names, its route literal, and its plant-location and tree rows.
  Gemini's are the FIRSTSEAT containment contract §1–§2 rows, unchanged, so the kit's Gemini
  records, matrix rows and exports stay byte-identical.
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
native: NativeFillRung, capacity: SeatCapacity) -> RouteDecision`. It runs before launch only
and is the one decision `_seat_route_for_spawn` and the seat-mode line both read. It has no
`leg ==` branch.

```python
class SeatLease(Protocol):
    seat_id: int
    def release(self) -> None: ...      # idempotent

class SeatCapacity(Protocol):
    def try_lease(self) -> SeatLease | None: ...   # nonblocking; None means no free seat id
```

The production `SeatCapacity` adapter wraps `seat_uid`'s seat-id lease. The returned
`RouteDecision` owns the optional lease (`RouteDecision.lease`).

`RouteRequest(leg, seat_key, host_class, run_kind, staged_tree_approved, env)`.
The resolver derives vendor from the unique `kind="vendor"` readiness row for leg. For a
registered profile, that value must equal `profile.vendor`. A duplicate row, or a registered
profile with no such row or a vendor that does not equal it, ends terminally with
`seat_route_identity_invalid` (OD-10 security). A leg with no `kind="vendor"` row and no
registered profile is `seat_profile_unregistered`, not a security code. No caller-supplied
vendor value is used for an exception, remote route, capacity grant or `RemoteRequest`.
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
| L7 | allowlist set: `seat_egress_proxy.unavailable_code()` is None. Unset: unexpired `open egress` exception | `seat_egress_not_installed` / `seat_egress_integrity_failed` / `seat_egress_tls_unterminated` / `seat_egress_start_failed`. Unset with no exception: `seat_egress_allowlist_missing`; expired: `seat_route_exception_expired` |
| L8 | qualification pass for the §5 key (EC-EXECFIND-2; A2 auto-qualify) | `seat_jail_qualification_failed` / `seat_sandbox_refused:jail_unqualified` / `seat_sandbox_refused:pass_store_unsafe` |
| L9 | atomically acquire and hold one seat-id lease; runs only after L0-L8 pass | `seat_local_capacity_exhausted` |

L3 checks only the helpers, ranges and non-root operator prerequisite. L9 calls the injected
seat-capacity adapter's nonblocking `try_lease()` exactly once. A successful reservation is
returned with the local decision and remains held through provider launch and the leg's
lifetime; the caller releases it on every exit. No availability probe acquires and releases a
lease before the real acquisition. Failure to acquire is the one pre-launch capacity event
that can enter §6.

Walk rules (each is a test):

- **W1.** A later rung is entered only when the local code is in `DESCEND_CODES` (§3), or
  `(vendor, host_class) in routed_remote` (§6, R-routed), or the capacity gate opens (§6).
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
    vendor: str                   # derived from the readiness row, never caller-supplied
    mode: Literal["jailed", "unconfined", "remote", "native", "degraded"]
    code: str | None              # the one mode-line code; None only for a clean `jailed`
    steps: tuple[RouteStep, ...]  # one entry per evaluated step that failed or skipped
    exception: NamedException | None
    variant: str | None           # Claude transport when jailed
    qualification_key: QualificationKey | None
    also: tuple[str, ...]         # sibling notices, e.g. seat_route_policy_ignored
    lease: SeatLease | None       # held for a local `jailed` decision; released by the caller
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

- `seat_egress_not_installed` (ordinary, descend): trusted Node is absent, cannot execute or
  is below the supported version, or the srt package/lock is absent.
- `seat_egress_integrity_failed` (security, terminal): any present install record/tree or
  existing CA artifact is unreadable, malformed, linked, wrongly owned/mode, wrong-version or
  digest/integrity-mismatched.
- `seat_egress_tls_unterminated` (security, terminal): the ready attestation does not prove
  the fail-closed front, TLS termination and inner-SNI enforcement.
- `seat_egress_start_failed` (ordinary, terminal): verified inputs exist but CA generation,
  process spawn, readiness parsing or readiness timeout fails operationally.
Every `EgressLayerUnavailable` raise site sets one of these codes directly; no caller maps
free text to a code.

The split names are vendor-neutral because the srt install is one host install for every
allowlist. `gemini_seat_egress_unavailable` stays in `NOTICES` for record readback and is no
longer emitted.

OD-10 `security` codes (private record and owner summary; never filed publicly):

- `seat_sandbox_refused:identity`, `seat_sandbox_refused:token_file_unsafe`,
  `seat_sandbox_refused:stage_changed`, `seat_sandbox_refused:output_unsafe`;
- `gemini_seat_token_in_output`, `gemini_seat_token_scope_excess`,
  `gemini_seat_egress_unconfined`, `gemini_seat_token_refreshed_in_jail`,
  `gemini_seat_credential_unusable`;
- `seat_egress_integrity_failed`, `seat_egress_tls_unterminated`, `seat_route_identity_invalid`;
- every `claude_seat_transport.CODES` entry whose class is `security`, read from that table
  and not restated.

Every member of `mode_line_codes()` has an explicit OD-10 entry. Import fails on an
unclassified code; no code becomes `ordinary` by omission. Unknown/unclassified codes are
handled privately and terminally until classified. The security set additionally includes
`seat_sandbox_refused:stage_not_private`, `seat_sandbox_retained_after_teardown`,
`seat_output_retained_after_teardown`, `seat_sandbox_egress_opt_out`,
`gemini_seat_stream_split_unavailable`, and `gemini_seat_subagent_or_unknown_event`, because
they respectively signal a failed private-inode boundary, retained credential/output custody,
unconfined egress, or a failed containment/activity probe. New failure codes remain terminal
unless explicitly added to a reviewed descend set.

The table is `seat_route_contract.OD10_CLASSES`. Importing `seat_route_contract` fails if one
of its own `CODES` has no `OD10_CLASSES` entry. The closure check of those keys against
`mode_line_codes()` runs when `seat_route` is imported, so `seat_route_contract` keeps no
import of `seat_jail`. Default rule: a code is terminal unless it is in `DESCEND_CODES`.

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
| `seat_egress_start_failed` | ordinary | terminal | check the private operator log, then reinstall with `phase-loop seat-egress install` or re-run |
| `seat_route_identity_invalid` | security | terminal | the leg, its profile and its readiness row must name one vendor; report the outcome privately |
| `seat_egress_allowlist_missing` | ordinary | terminal | the vendor phase registers its allowlist; the seat stays degraded until then |
| `seat_profile_unregistered` | ordinary | terminal | the vendor has no jail profile yet; the seat stays degraded until its phase registers one |
| `seat_route_exception_expired` | ordinary | terminal | only an owner record in the readiness matrix renews an exception |
| `seat_local_capacity_exhausted` | ordinary | capacity | wait for a running seat to finish, then re-run |
| `seat_route_row_remote` | ordinary | skip | the readiness matrix routes this vendor on this host class to the remote rung |
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
    routed_remote: frozenset[tuple[str, str]]      # (vendor, host_class) pairs explicitly routed remote
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

- `exceptions` and `routed_remote` are reduced only from unique `kind="vendor"` rows.
  `kind="remote"` rows are activation inventory and never select routing. A vendor row selects
  `(vendor, host_class)` only when that host class is explicitly remote-pending; a separate
  remote-pending inventory row does not make the vendor skip its local route.
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
R-routed: when `(vendor, host_class) in routed_remote`, the seat skips the local rung with one
step (`L`, `skipped`, `seat_route_row_remote`) and walks R, then N, then D.

Shipped state: no grants, the rung inactive and `REMOTE_DESCEND_CODES` empty, so no seat
offloads for capacity. The owner's capacity rulings of 2026-11-06 (EC-JAILCORE-2 as amended,
§8) take effect per host through an overlay and REMOTE's receipt, with no code change.
Owner-controlled targets need the generic probe receipt. Third-party targets need it and
that vendor's OD-7 activation (condition 4); after OD-7 they may take capacity offload.

## 7. Per-provider egress (IF-0-JAILCORE-2)

`seat_egress_proxy.allowlist_ref(allowlist_id) -> AllowlistRef(id, content_digest,
request_set, probe_rows)` reads `seat_egress/<id>-allowlist.json`, schema
`phase_loop_seat_egress_allowlist.v1`. `content_digest` is the sha256 of canonical JSON containing exactly `schema`, `leg`, `allow`
and `measured_and_refused`, with sorted keys and no whitespace. Therefore every change to an
allowed request, the measured refusal set, or the derived `probe_rows` changes the
QualificationKey and invalidates the v2 pass. `gemini-allowlist.json` stays
byte-identical; its id is `gemini`. `probe_rows` are derived from `allow` and
`measured_and_refused`: one allowed request per rule, one refused per measured-and-refused
host, and an unlisted host.

`start_proxy(*, allowlist_id)` starts one process with one session token per call, bound to
exactly that allowlist. The review-seat entry point always enables and attests the fail-closed
front, TLS termination and inner-SNI check. None is caller-disableable. A test-only helper may
inject failed attestations but is not exported or used by a profile. It raises `EgressLayerUnavailable`
with `.code` set to a §3 egress code. `egress_evidence(proxy)` adds `allowlist_id` and
`allowlist_digest`. `unavailable_code() -> str | None` sits beside the unchanged
`unavailable_reason()`, which the CLI and doctor keep using. A seat never shares a proxy
process or token. One proxy never serves two allowlists.

## 8. Capacity owner ruling

The binding 2026-11-06 ruling is: owner-controlled targets may take review seats for capacity
after one current generic egress-and-credential probe set; per-vendor OD-7 activation applies
only to third-party targets. Capacity offload remains disabled in packaged state and can be
enabled only by the private policy grant and the bound, current probe receipt in §6. A
third-party grant also requires its vendor's OD-7 activation reference. No wildcard grant is
valid. This PR reconciles the roadmap text with that ruling; there is no later amendment or
open owner question in the enablement path.
