# FIRSTSEAT lane interfaces: frozen detail

This file is a frozen input to `plans/phase-plan-v1-seats-FIRSTSEAT.md`, which pins it by
SHA-256. It freezes the Python call interfaces between lanes A (SL-0), D (SL-3) and E (SL-4)
that IF-0-FIRSTSEAT-5 needs. It is derived from the containment contract
`plans/seats-firstseat-containment-contract.md`
(`a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6`), cited here as §1–§16,
and adds no requirement to it. No lane edits this file. Any change is a plan amendment.

`FROZEN-NEW` marks a name or shape that the contract leaves open. Each is fixed here at its
minimum. Unmarked items restate the plan or the contract.

## 1. Conventions

- Every type is `@dataclass(frozen=True, slots=True, kw_only=True)` unless it is a `Literal`,
  an exception or a `Protocol`. Sequences are tuples, and mappings are read-only `Mapping`s.
  A `Literal` is a closed set: any other value is a `contract_bug`.
- `Digest` is a 64-character lowercase hex SHA-256 string. `RowId` is `"<location>:<row>"`,
  with a §1 location and a §2 or §3 row spelled exactly as written there.
- Types that the reducer consumes live in lane A's module, so A never imports D or E. The
  lane named as producer fills in their values.
- A field marked `(private)` may hold a host name, a path, a nonce or a credential digest.
  It goes only to the per-operator private record (OD-10). It never appears in a public
  export, a log line or an exception message. No type carries output text, argv values,
  prompts or credential bytes, except `DeliveredCopy` and `JailedStep`, which stay in memory
  and are never persisted.
- A measurement function never raises for an observation it could not make. It returns the
  closed code instead. `TypeError` and `ValueError` signal caller misuse only.

```python
Location = Literal["tree", "workdir", "home", "provider_config"]                     # §1
Surface = Literal["project_settings", "hooks", "mcp_servers", "provider_overrides"]  # §2
ContainmentField = Literal["credential_scope", "refresh_detection", "project_settings",
                           "hooks", "mcp_servers", "provider_overrides"]  # = seat_window.CONTAINMENT_FIELDS
LaunchKind = Literal["help", "plugin_validation", "tree_control", "runtime_control",
                     "credentialed_tree_control", "credentialed_runtime_control",
                     "measured", "expired_copy"]                                     # §15 launches 1-6
WindowLabel = Literal["leg", "bracket"]                                              # §9, §14
```

## 2. Index

Modules are under `phase_loop_runtime.`. Ownership follows the plan's owned files.

| # | Interface | Module | Owner | Caller | Status |
|---|---|---|---|---|---|
| I-1 | `start_proxy(refuse_all=True)` | `seat_egress_proxy` | A | D | §15; `allowlist_sha256` field FROZEN-NEW |
| I-2 | `fence`, `proxy_stream`, proxy stdout lines | `seat_egress_proxy`, `seat_egress/proxy.mjs` | A | D, A | protocol §14; symbols and request-event fields FROZEN-NEW |
| I-3 | `wait_bridge_exit` | `sandbox_egress` | A | D | FROZEN-NEW |
| I-4 | `plant_layout`, `build_qualification_input`, `HostPathMap`, `seed_runtime_plants` | `seat_jail_qualification` | A | E, D | FROZEN-NEW |
| I-5 | `arm_watch`, `SeatWatch` (the watch handle) | `seat_jail_qualification` | A | D | FROZEN-NEW |
| I-6 | `scan` verb; `scan_seat` | `seat_uid`; `seat_jail_qualification` | A | D | verb §16; call FROZEN-NEW |
| I-7 | `run_bracket` (§9/§11 bracket result) | `seat_jail_qualification` | A | D | FROZEN-NEW |
| I-8 | `measure_issuer`, `DeliveredCopy` | `seat_jail_qualification` | A | D | FROZEN-NEW |
| I-9 | `JailedRun` | `seat_jail_qualification` (type); `panel_invoker` (implementation) | A type, D implementation | A | FROZEN-NEW |
| I-10 | `definition_probe` | `seat_jail_qualification` | A | E | name from the plan; shape FROZEN-NEW |
| I-11 | `window_control_launch` | `panel_invoker` | D | E | §15; signature FROZEN-NEW |
| I-12 | `window_board_launch` (the board-leg runner) | `panel_invoker` | D | E | FROZEN-NEW |
| I-13 | `reduce_containment` (the reducer) | `seat_jail_qualification` | A | E | FROZEN-NEW |
| I-14 | `OwnerSummary` record | `seat_jail_qualification` (type); `seat_window` (write) | A, E | E | FROZEN-NEW |
| I-15 | per-context call order | `seat_window.qualify` | E | CLI | restates §15 |

## 3. Lane A interfaces

### I-1 Proxy start

```python
@contextlib.contextmanager
def start_proxy(*, inner_sni_check: bool = True, refuse_all: bool = False) -> Iterator[SeatEgressProxy]
```

- `refuse_all=True` writes `"allow": []` into the existing configuration argument. Nothing
  else changes. No parameter supplies or widens rules, and the production allowlist file is
  unchanged (§15). The function raises `EgressLayerUnavailable` exactly as it does today.
- FROZEN-NEW: `SeatEgressProxy` gains `allowlist_sha256: Digest`. It is the SHA-256 of the
  canonical JSON (sorted keys, separators `,` and `:`) of the `allow` list that was passed
  to the proxy, which is `[]` under `refuse_all`. Existing fields are unchanged.

### I-2 Fences and the observation stream

Proxy stdout carries one JSON object per line, after the unchanged readiness line:

- FROZEN-NEW request event: exactly the keys `event`, `method`, `host`, `path` and
  `decision`, as in
  `{"event":"request","method":"<METHOD>","host":"<host>","path":"<template>"|null,"decision":"allow"|"deny"}`,
  in a closed vocabulary. `method` is one of GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS
  and CONNECT, else `<other>`. `host` is the lowercase host when it is an allowlist host, a
  §9 table host or a canary `<32 lowercase hex>.invalid`, else `<other>`. `path` is the
  templated path: the matching allowlist rule's `path`, or its `path_prefix` followed by
  `*`; else `/oauth2/v2/userinfo` when it is exactly that path; else `/oauth2/*` for any
  other `/oauth2/` path; else `<other>`. It is `null` when the proxy observed no request
  line (a CONNECT-level decision). `decision` is the existing `action`. No reason, query or
  fragment is emitted. The proxy emits one event per decision on an authenticated client:
  a front CONNECT refusal, a front first-flight refusal (`CONNECT`, `null`, `deny`) and each
  inner request. It emits none for a 407, so the namespace bridge's unauthenticated
  self-check, which precedes every fence, is never an outside event.
- The fence acknowledgement `{"event":"fence","id":"<32 lowercase hex>"}` and the stdin line
  `{"op":"fence","id":"<id>"}` are as given in §14.

```python
FENCE_ACK_TIMEOUT_S: Final = 10.0    # §14 wrapper wait
FENCE_QUIET_S: Final = 2.0           # §14 quiet interval

def fence(proxy: SeatEgressProxy, marker: Literal["start", "end"], window: WindowLabel) -> FenceResult
def proxy_stream(proxy: SeatEgressProxy) -> ProxyStream

class FenceResult:   fence_id: str; acknowledged: bool; acked_ns: int | None   # time.monotonic_ns()
class RequestEvent:  method: str; host: str (private); path: str | None (private); decision: Literal["allow", "deny"]
class ProxyWindow:   label: WindowLabel; start_acked: bool; end_acked: bool; events: tuple[RequestEvent, ...]
class ProxyStream:   final: bool; protocol_error: bool; windows: tuple[ProxyWindow, ...]
                     outside_events: tuple[RequestEvent, ...]; allowlist_sha256: Digest
```

- `fence` sends one fresh id and waits up to `FENCE_ACK_TIMEOUT_S` for its acknowledgement.
  It sends nothing, and returns `acknowledged=False`, when a fence is already outstanding or
  `protocol_error` is set. A timeout, a mismatched or unsolicited acknowledgement, or any
  other unknown line sets `protocol_error`.
- An event belongs to a window only when it lies, in stdout order, between that window's
  start acknowledgement and its end acknowledgement. Every other event goes to
  `outside_events`.
- `proxy_stream` returns `final=True` only after the `start_proxy` context has exited and
  stdout has reached EOF. Before that it returns `final=False`.
- The reducer treats a stream as incomplete when any of these holds: it is not final; it has
  a protocol error; it has any outside event; a window lacks either acknowledgement; or it has
  more windows than §15 schedules (one `leg` window, plus a `bracket` window on `measured`).
  Outside events still carry §8 positives.

### I-3 Bridge wait

```python
BRIDGE_EXIT_TIMEOUT_S: Final = 10.0
def wait_bridge_exit(prefix: Sequence[str], *, timeout_s: float = BRIDGE_EXIT_TIMEOUT_S) -> bool
```

`prefix` is the value that `isolated_network(..., proxy_socket=...)` yielded. The function
returns `True` once every child that the launch bridge forked for that prefix has exited. It
returns `False` on a timeout or an unknown prefix. D calls it before each end fence. On
`False`, D sends no further fence (§15).

### I-4 Plants and host paths

```python
class PlantRow:          row_id: RowId; location: Location; role: Surface; nonce: str (private)
class PlantLayout:       rows: tuple[PlantRow, ...]; canary_hosts: Mapping[Surface, tuple[str, ...]] (private)
                         plugin_form: Literal["nested", "plugin_json"]; layout_sha256: Digest
class QualificationInput: repo: Path (private); commit: str; layout: PlantLayout
class HostPathMap:       tree: Path; seat_home: Path; gemini_config: Path; agy_rw: Path; seat_out: Path
                         delivered_credential: Path | None          # all private
class PlantLayoutRefused(ValueError): ...

def plant_layout(*, plugin_form: Literal["nested", "plugin_json"]) -> PlantLayout
def build_qualification_input(layout: PlantLayout, base: Path) -> QualificationInput
def seed_runtime_plants(layout: PlantLayout, paths: HostPathMap) -> None
```

- `rows` holds every §2 row at each of the four §1 locations, plus the §3 rows. Each row has
  a unique nonce and its §4 form. `canary_hosts` maps each surface to its `.invalid` hosts.
  The canary of `.gemini/settings.json`'s URL server is listed under `mcp_servers` (§4).
- `plugin_form` is `"nested"` when launch 1 reports `help_lists_plugin=True`, and
  `"plugin_json"` otherwise (§4).
- `build_qualification_input` creates a disposable repository under `base`, never this
  repository. It commits the `tree` plants, `window-read.txt` and the §5 sentinels in one
  commit, and writes nothing elsewhere.
- D builds `HostPathMap` from the jail it constructed. `seed_runtime_plants` writes the
  non-`tree` rows at their §1 host backing. It raises `PlantLayoutRefused` for a shadowed
  path, or when two rows resolve to one host path. D calls it only for the runtime kinds,
  after `gemini-config/` is written and before `arm_watch`.

### I-5 Watch handle

```python
class WatchUnavailable(RuntimeError): ...

def arm_watch(layout: PlantLayout, paths: HostPathMap, *, kind: LaunchKind | Literal["board"]) -> SeatWatch

class SeatWatch:
    armed_ns: int
    def prove_sentinel(self, run: JailedRun) -> bool
    def drain_and_close(self, *, quiescent: bool) -> WatchObservation

class WatchObservation:
    armed_ns: int; closed_ns: int
    sentinel_observed: bool            # §5 item 2: both the open and the exec were seen
    overflow: bool                     # §5 item 3
    read_marker_opened: bool           # §5 item 4; required on `measured` only
    drained_after_quiescence: bool     # §5 item 5
    opened_rows: tuple[RowId, ...]     # open-class events, including the exec of a row's plant
    changed_rows: tuple[RowId, ...]    # §5 modification at workdir, home or provider_config rows
    row_ancestor_created: bool         # §5: a directory created or renamed into place on a row path
    credential_path_events: int        # §10, first bullet
    pre_row_sha256: Mapping[RowId, Digest | None] (private)
    pre_tree_manifest_sha256: Digest
```

- `arm_watch` takes the pre-leg digests and the pre-leg tree manifest, then arms the watch on
  every plant location and on `delivered_credential`. It raises `WatchUnavailable` when it
  cannot arm.
- D calls `prove_sentinel` as the seat's first jailed launch. It runs the §5 sentinel step in
  the leg's own jail, through `/seat/tree`.
- After process-group quiescence, D calls `drain_and_close`, passing its quiescence
  observation. This must happen before `scan_seat`. A digests the manifest so that an
  unchanged tree gives equal pre-leg and post-leg digests across the hand-off.

### I-6 Seat scan

The `seat_uid scan` verb runs only through `in_h_argv`. Its argv and stdio framing are
internal to lane A, with two fixed rules: the token travels on stdin and never on argv, and
the output holds only the fields of `ScanResult`.

```python
def scan_seat(holder_pid: int, seat_root: str, layout: PlantLayout, paths: HostPathMap,
              *, delivered: DeliveredCopy | None) -> ScanResult

class RowState:          state: Literal["regular", "directory", "absent", "non_regular", "unread"]
                         sha256: Digest | None; mode: int | None
class CredentialCounts:  field_names: int; token: int                # §10 counts
class ScanResult:        rows: Mapping[RowId, RowState]; tree_manifest_sha256: Digest | None
                         credential_counts: CredentialCounts | None; scan_complete: bool
```

- `rows` covers every non-`tree` row of the layout. A merges in operator-owned locations,
  which it reads directly (§16).
- `directory` is a directory at a §2 row spelled with a trailing `/`. Its `sha256` is the
  manifest digest, in the tree-manifest form, of the entries under it.
- `non_regular` means a link or a non-regular entry at the row path or at a row ancestor,
  including a directory at a row not spelled with a trailing `/`. It counts as a change.
- `unread` means an entry that was over the cap, unreadable or unwalked. It sets
  `scan_complete=False`.
- `credential_counts` is `None` when `delivered` is `None`. Otherwise it counts the §10 field
  names, and the delivered token in every `seat_jail.contains_secret` encoding, across file
  names and contents.
- When the helper fails (a nonzero exit, a timeout or malformed output), every row is
  `unread`, `tree_manifest_sha256` and `credential_counts` are `None`, and `scan_complete`
  is `False`.
- D passes `delivered` on the credentialed kinds, the measured leg and the expired-copy leg
  only (launches 4 to 6).

### I-7 Bracket

```python
BracketRowName = Literal["b_forbidden_hosts", "b_forbidden_paths", "b_tunnel_inner_host",
                         "b_tunnel_inner_sni_and_host", "b_tunnel_inner_sni_only",
                         "b_fail_closed_front", "b_direct_without_proxy", "f006_config_ancestor"]
BRACKET_SIGNATURES: Final[Mapping[BracketRowName, frozenset[str]]]   # A freezes per row in the port (§11)

def run_bracket(proxy: SeatEgressProxy, run: JailedRun) -> BracketResult

class BracketRow:    row: BracketRowName; outcome: Literal["refused", "unavailable"]; signature: str | None
class BracketResult: start: FenceResult; end: FenceResult; post_refused: bool; rows: tuple[BracketRow, ...]
```

- D calls `run_bracket` on `measured` only, and only when all of these hold: the leg's end
  fence is acknowledged; the process group is gone; `wait_bridge_exit` returned `True`; and at
  least `FENCE_QUIET_S` has passed since the end fence's `acked_ns`. Otherwise `bracket` is
  `None`.
- A fences the `bracket` window itself. Through `run`, it sends the §9 token POST and then the
  eight rows, under §11's client rules.
- `post_refused` is `True` only when the POST's client reported the proxy's refusal
  (CONNECT 403).
- `rows` holds exactly the eight names, in the order above. `signature` is a member of
  `BRACKET_SIGNATURES[row]`, and is present exactly when `outcome == "refused"`.
- The bracket's events stay in the stream's `bracket` window. The reducer applies §9 to them:
  exactly one matching event, and that event refused.

### I-8 Issuer measurement

```python
class DeliveredCopy:     content: bytes = field(repr=False); sha256: Digest (private)
class IssuerMeasurement: outcome: Literal["pass", "gemini_seat_token_scope_excess", "unavailable"]
                         measured_sha256: Digest | None (private)

def measure_issuer(delivered: DeliveredCopy) -> IssuerMeasurement
```

D builds `DeliveredCopy` in memory from the copy it delivers. It calls `measure_issuer`
immediately before the `measured` argv (§15). `pass` requires every §11 condition, and
`measured_sha256 == delivered.sha256`.

### I-9 Jailed step callable (type owned by A, implemented by D)

```python
class JailedStep: exit_code: int | None; timed_out: bool; stdout: bytes = field(repr=False)
class JailedRun(Protocol):
    def __call__(self, argv: Sequence[str], *, env: Mapping[str, str], use_proxy: bool,
                 timeout_s: float) -> JailedStep: ...
```

D's implementation runs `argv` as the seat uid, inside the jail, namespace and proxy instance
of the launch that issued it, with `/seat/tree` as the working directory. The environment is
exactly `env`, plus the proxy variables when `use_proxy` is true. `stdout` is capped at
65536 bytes and is kept in memory only. A uses this callable only for the sentinel step and
for the bracket steps.

### I-10 Definition probe

```python
VoidReason = Literal["tool_step", "subagent_step", "token_endpoint_event", "credential_event",
                     "plugin_validation_void", "help_void", "incomplete_watch", "launch_error"]
class VoidedControl:     kind: LaunchKind; reason: VoidReason
class DefinitionResult:
    defined_rows: tuple[RowId, ...]; defined_surfaces: tuple[Surface, ...]
    home_row_baseline: Literal["write_recorded", "no_write_final", "absent"]
    credentialed_control_required: bool
    counted_lookups: Mapping[LaunchKind, int]          # §7 lookups that make the outcome `unavailable`
    uncounted_home_lookups: Mapping[LaunchKind, int]   # seat-writable `home` lookups that §7 did not count
    voided: tuple[VoidedControl, ...]
    baseline_sha256: Mapping[RowId, Digest] (private)

def definition_probe(layout: PlantLayout, controls: Sequence[WindowLaunchResult]) -> DefinitionResult
```

- `controls` contains the control launches that have run so far: `tree_control`,
  `runtime_control` and, after launch 4, both credentialed kinds. The function is pure.
- `home_row_baseline` describes §3's `home` row:
  - `write_recorded`: a control recorded a CLI write there, with its digest (§7).
  - `no_write_final`: the credentialed tree control ran and recorded no write there. This is
    final: launch 4 is never re-run, and any later write is a change.
  - `absent`: neither of the above.
- `credentialed_control_required` is `True` only when no credentialed control is in
  `controls` and either a surface is undefined or `home_row_baseline == "absent"`.

## 4. Lane D interfaces

### I-11 `window_control_launch`

```python
class WindowLaunchSpec: kind: LaunchKind; qualification_input: QualificationInput; model: str; timeout_s: float
def window_control_launch(spec: WindowLaunchSpec) -> WindowLaunchResult
```

The kind table restates §7, §10 and §15. "Live" and "expired" name the credential copy. The
expired copy is the live delivered copy with only its expiry set in the past (FROZEN-NEW).

| `kind` | argv | input (§6) | credential | allowlist | tracer | runtime plants | §10 scan | issuer and bracket |
|---|---|---|---|---|---|---|---|---|
| `help` | sealed image help | none | none | refuse-all | no | no | no | no |
| `plugin_validation` | `plugin validate <copy> --strict --json`, per plugin row | none | none | refuse-all | no | no | no | no |
| `tree_control` | P3 control | control | none | refuse-all | yes | no | no | no |
| `runtime_control` | production | control | none | refuse-all | yes | yes | no | no |
| `credentialed_tree_control` | P3 control | control | live | production | yes | no | yes | no |
| `credentialed_runtime_control` | production | control | live | production | yes | yes | yes | no |
| `measured` | production | measured | live | production | no | no | yes | yes |
| `expired_copy` | production | measured | expired | production | no | no | yes | no |

Every launch runs these steps in this order:

1. Use a fresh seat directory. Stage the input through the approved-stage path, under its own
   review isolation authorization.
2. Build the canonical Gemini jail. Enter `start_proxy(refuse_all=...)`.
3. For the runtime kinds, call `seed_runtime_plants`.
4. Call `arm_watch`, then `prove_sentinel`.
5. Call `fence("start", "leg")`. On `measured`, call `measure_issuer`. Run the argv and wait
   for process-group quiescence.
6. Call `wait_bridge_exit`, then `fence("end", "leg")`.
7. Call `drain_and_close`, then `scan_seat`.
8. On `measured`, hold the gap and call `run_bracket`.
9. Clean up the jail, exit the proxy context, then call `proxy_stream`.

A failed bridge wait or end fence sends no further fence and skips the bracket. The reads in
step 7 still run.

```python
LaunchError = Literal["stage_refused", "jail_unavailable", "proxy_unavailable", "plant_layout_refused",
                      "watch_unavailable", "credential_unavailable", "launch_failed",
                      "bridge_wait_timeout", "fence_unacknowledged", "scan_failed"]
class TracedPath:    location: Location; relpath: str (private)
class LaunchBinding: image_sha256: Digest; admission_class: str; stage_manifest_sha256: Digest
                     argv_sha256: Digest; input_sha256: Digest | None; jail_profile_sha256: Digest
                     allowlist_sha256: Digest
class WindowLaunchResult:                       # type in seat_jail_qualification; D fills it
    kind: LaunchKind
    status: Literal["SUCCESS", "FAILURE", "NONE"]; timed_out: bool; error: LaunchError | None
    quiescent: bool; model_turn: bool | None; tool_steps: int | None; subagent_steps: int | None
    stream: ProxyStream | None; bridge_exited: bool | None
    lookups: tuple[TracedPath, ...] | None; created: tuple[TracedPath, ...] | None; lookup_complete: bool | None
    watch: WatchObservation | None; scan: ScanResult | None; first_jailed_launch_ns: int | None
    bracket: BracketResult | None; issuer: IssuerMeasurement | None
    delivered_copy_sha256: Digest | None (private)
    help_sha256: Digest | None; help_lists_plugin: bool | None
    plugin_validation: Literal["valid", "void"] | None
    binding: LaunchBinding | None
```

- `status` is `SUCCESS` when the CLI's final event reports `SUCCESS`, and `FAILURE` for any
  other final status. It is `NONE` when no final event was observed. For `help` and
  `plugin_validation`, `status` is `SUCCESS` exactly when the exit code is 0 (for help, also
  only when the output is non-empty). On those two kinds the step counts and `model_turn` are
  `None`.
- `tool_steps` and `subagent_steps` come from D's stream parser. They are `None` when the
  parser cannot account for the whole stream.
- The FROZEN-NEW fields are `bridge_exited`, `first_jailed_launch_ns`, `help_sha256`,
  `help_lists_plugin`, `plugin_validation`, `binding` and the `LaunchError` values.
- `help_lists_plugin` is a closed boolean that D derives from the help output. The output
  itself is never returned.
- `plugin_validation` is `valid` when every plugin row's run exits 0 with zero error or
  warning findings, and with nonzero hooks, mcpServers, rules and skills counts (§4).
  Otherwise it is `void`.
- `admission_class` takes its values from `agy_qualification`.
- Fields that do not apply to the launch kind are `None`. The function returns errors as
  codes and never raises for them.

### I-12 `window_board_launch`

```python
class WindowBoardSpec:     qualification_input: QualificationInput; monitoring_policy: Literal["bounded"]
class BoardLegObservation: watch: WatchObservation | None; stream: ProxyStream | None
                           input_sha256: Digest; binding: LaunchBinding | None   # type in seat_jail_qualification
class WindowBoardResult:
    composition: Literal["admitted", "refused"]
    board_outcome: Literal["terminated", "not_terminated"]
    canonical_gemini: bool; staged_read: bool
    board_sha256: Digest | None; exec_record_sha256: Digest | None; tool_receipt_sha256: Digest | None
    delivered_turn_sha256: Digest | None
    leg_exec_records: Mapping[str, Digest | None]     # vendor -> leg_exec.v1 digest
    co_seats: tuple[str, ...]
    gemini: BoardLegObservation

def window_board_launch(spec: WindowBoardSpec) -> WindowBoardResult
```

- The function runs the plan-tier board on the same qualification input. The Gemini seat gets
  the §6 board input in D's qualification frame and a fresh seat directory.
- `arm_watch(kind="board")` runs before that seat's first jailed launch. The seat has its own
  production-allowlist proxy instance, which may close at EOF.
- There is no bracket, no issuer measurement and no §10 scan.
- `board_outcome` is `terminated` exactly when D's `integrated_board_outcome` reports a
  terminated board.
- A composition refusal launches no seat. It returns `composition="refused"` with
  `gemini.watch` and `gemini.stream` set to `None`.

## 5. The reducer and the owner summary

### I-13 `reduce_containment`

```python
class ContextBinding: context_id: str; account_label: str
                      dependency_subject_sha256: Digest | None; dependency_projection_sha256: Digest | None
class ContainmentInputs:
    context: ContextBinding; layout: PlantLayout
    help: WindowLaunchResult | None; plugin_validation: WindowLaunchResult | None
    controls: tuple[WindowLaunchResult, ...]          # launches 3 and 4
    measured: WindowLaunchResult | None; expired_copy: WindowLaunchResult | None
    board: BoardLegObservation | None
FieldOutcome = Literal["not_loaded", "loaded", "pass", "gemini_seat_token_scope_excess",
                       "gemini_seat_token_refreshed_in_jail", "unavailable"]
class ContainmentReduction:
    containment: Mapping[ContainmentField, FieldOutcome]
    checks: Mapping[ContainmentField, bool]
    observation_sha256: Digest
    binding: Mapping[str, Digest | str | None]
    admitted: bool
    private: Mapping[str, object] (private)
    owner_summary: OwnerSummary

def reduce_containment(inputs: ContainmentInputs) -> ContainmentReduction
```

- `ContainmentInputs.context`, together with each launch's `binding`, is §15's "section 12
  binding". `layout` is "the layouts".
- The reducer is pure: it does no I/O and reads no clock.
- `containment` has exactly the six `CONTAINMENT_FIELDS`, with these values:
  - surfaces: `not_loaded`, `loaded` or `unavailable` (§8);
  - `credential_scope`: `pass`, `gemini_seat_token_scope_excess` or `unavailable` (§11);
  - `refresh_detection`: `pass`, `gemini_seat_token_refreshed_in_jail` or `unavailable`
    (IF-0-FIRSTSEAT-5).
- Any rendering of a `credential_scope` pass uses the label `no wider than the recorded
  baseline` (§11).
- `checks[field]` is `True` exactly when the value is `not_loaded` or `pass`. E stores
  `seat_window.measurement(dict(checks), observation_digest=observation_sha256)` as the
  record's `containment`.
- A missing input makes the fields that need it `unavailable` (§15).
- A launch whose binding disagrees with the context's other launches is treated as missing.
  Differences in argv, input and allowlist that its kind requires are expected and do not
  count (§12).
- When the image is not admitted, all six values are `unavailable` and `admitted` is
  `False`. Positives still go to `private` and `owner_summary` (§12).
- `binding` has exactly the §12 keys: `image_sha256`, `admission_class`, `help_sha256`,
  `stage_manifest_sha256`, `plant_layout_sha256`, `contract_sha256`, `control_argv_sha256`,
  `production_argv_sha256`, `control_input_sha256`, `measured_input_sha256`,
  `board_input_sha256`, `jail_profile_sha256`, `production_allowlist_sha256`,
  `refuse_all_allowlist_sha256`, `watch_sha256`, `proxy_sha256`, `validator_sha256`,
  `dependency_subject_sha256`, `dependency_projection_sha256`, `context_id` and
  `account_label`. The delivered-copy digest is not among them.
- `private` has exactly these top-level keys: `rows`, `canaries`, `token_endpoint_events`,
  `credential_events`, `lookups`, `home_row` (the baseline and measured digests of §3's
  `home` row), `manifest_differences`, `delivered_copy_sha256`, `bracket`, `issuer` and
  `unavailable_reasons`.
- `observation_sha256` is `seat_window.digest(private)`.

### I-14 `OwnerSummary`

```python
UnavailableReason = Literal["missing_input", "not_admitted", "binding_mismatch", "undefined_surface",
                            "counted_lookup", "incomplete_watch", "incomplete_stream", "incomplete_scan",
                            "bracket_void", "bracket_row_unavailable", "issuer_unavailable",
                            "expired_copy_unavailable", "launch_error", "timed_out"]
class OwnerSummary:
    schema: Literal["seat_window_owner_summary.v1"]
    context_id: str
    outcomes: Mapping[ContainmentField, FieldOutcome]
    unavailable_reasons: Mapping[ContainmentField, tuple[UnavailableReason, ...]]
    undefined_surfaces: tuple[Surface, ...]                          # §7
    plugin_validation: Literal["valid", "not_listed", "void", "not_run"]   # §4
    home_row_baseline: Literal["write_recorded", "no_write_final", "absent"]
    counted_lookups: Mapping[LaunchKind, int]
    uncounted_home_lookups: Mapping[LaunchKind, int]                 # the plan's E5 count, per control
    voided_controls: tuple[VoidedControl, ...]                       # §7, §4
    expired_copy_control: Literal["pass", "fail", "unavailable"]     # §10
    private_route: bool                                              # any §8, §10 or §11 positive (OD-10)
```

E writes the summary with
`president_adapter.write_private_record(f"owner-summary-W1-{context_id}.json", ...)`. It is
never selected as a window record, never read by `verify` and never exported.

## 6. I-15 Per-context call order (lane E, `seat-window qualify`)

The order restates §15. Each step completes before the next one starts.

1. Run the existing preflight, attendance and host-readiness checks.
2. Call `L = plant_layout(plugin_form="nested")` and `Q0 = build_qualification_input(L, ...)`.
3. Run launch 1, `help`, on `Q0`.
   - If `help_lists_plugin` is true, run launch 2, `plugin_validation`, on `Q0`.
   - Otherwise, set `L = plant_layout(plugin_form="plugin_json")`.
4. Call `Q = build_qualification_input(L, ...)`. Run launch 3, `tree_control` and then
   `runtime_control`, on `Q`.
5. If `definition_probe(L, launch-3 results).credentialed_control_required` is true, run
   launch 4 (both credentialed kinds) once.
6. Run launch 5, `measured`, then launch 6, `expired_copy`.
7. Call `window_board_launch`.
   - A composition refusal ends the attempt and routes LA-2 remediation.
   - With no canonical review, the case goes to the owner, and no open is exempted.
8. Call `reduce_containment`. Write the record's `containment` from the reduction (I-13),
   and write `OwnerSummary` privately.
