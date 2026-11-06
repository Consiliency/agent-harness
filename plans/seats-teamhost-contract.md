# SEATS TEAMHOST contract

Normative for `plans/phase-plan-v1-seats-TEAMHOST.md`. Changing this file is a plan
amendment. Sections are cited as §1–§8.

**Inputs (pinned, never outputs of this phase).**

| Input | sha256 |
|---|---|
| `specs/phase-plans-seats-v1.md` | `29549f8845411c40c6dc817dda51d009132325fadb812b3a16c01aec564adc7a` |
| `plans/seats-jailcore-route-contract.md` (JAILCORE; consumed only through IF-0-JAILCORE-1, IF-0-JAILCORE-2 and EC-JAILCORE-4) | `d912090c88ba431de10e82f83fea40a54bf422d3d1c91a2621d421dad91ddd9b` |
| `docs/executable-dependency-projection.md` (roadmap External Input) | `c3e955fcdcae3d36dc59c60c293d84cb4df5df3fbcb6efdc3abe9e86ba1a8d9c` |
| `.consiliency/plans/detailed-lkg-cli-qualification-1602-20261014-0359.md` (reference only; agent-harness#1602 owns its lifecycle) | `9fbfb9d08c3ae69dfc400db2a3a7ca9db0f558d0a5a597c3ddcccfa3ccb0a63b` |
| `agy_diagnosis.py` at commit `782c97c0` (row wording only; its logic is not salvaged) | `062d377b4ac99519795a7972c47fa357bb8b7e1b04aacd9cedc1cf70f59d1bb1` |

## 0. General rules

- **G1.** TEAMHOST adds no `seat_jail.NOTICES` code, no route code and no member of either
  descend set. Every refusal below uses a code that already exists on the base, or a JAILCORE
  code once IF-0-JAILCORE-1 has landed.
- **G2.** No sealed, inline or unconfined route is added or widened. No fix line names one, or
  an API-key lane.
- **G3.** Public text states requirements. It never describes a weakness (OD-10). A
  containment failure seen during execution takes the private route under
  `~/.local/state/agent-harness/`.
- **G4.** Files another phase also writes are edited only at the functions §8 names. No
  function is edited concurrently by two phases. Whichever phase lands second rebases.
- **G5.** No path in code, docs or evidence names a private host or user. The two fixed
  product paths in §1 are public deployment constants.

## 1. Seat subject (IF-0-TEAMHOST-1, lane A)

New module `phase_loop_runtime/seat_subject.py`:

```python
MANAGED_RELEASES_ROOT = Path("/opt/consiliency/tooling/releases")  # panel_invoker._FRONTDOOR_RELEASES aliases it
MANAGED_AUTHORITY_PIN = Path("/etc/consiliency/tooling/seat-authority.json")
SubjectSource = Literal["session_lease", "managed_release", "standalone"]

@dataclass(frozen=True)
class SeatSubject:
    leg: str
    source: SubjectSource
    subject_path: Path | None          # resolved native target; None for session_lease
    release_id: str | None             # managed_release only
    requirement: DependencyRequirement | None  # managed_release only

def resolve_seat_subject(leg: str, env: Mapping[str, str]) -> SeatSubject
def open_managed_authority(subject: SeatSubject) -> tuple[int, str]  # borrowed fd, expected sha256
def deployment_kind() -> Literal["managed", "uv_tool", "pip", "source", "unknown"]
```

**Resolution order** (first match wins):

1. A bound task lease for `leg` (pre-existing `current_dependency_for_provider`) gives
   `session_lease`. That path is unchanged.
2. Otherwise the leg's provider is looked up on `env["PATH"]` at call time, never an
   import-time snapshot. If it resolves through a guarded frontdoor (the pre-existing
   agent-harness#1798 checks) into a release directly under `MANAGED_RELEASES_ROOT`, the
   result is `managed_release`. The subject is the release's native provider target only:
   the selected subject (roadmap Assumption 2). No interpreter, launcher or adjacent file is
   part of it.
3. Otherwise the result is `standalone`: today's trust-checked resolution, unchanged.

**Managed-release authority (IF-XR-1).**
- The release ships, per leg, `share/phase-loop/seat-dependencies/<leg>/authority.json` and
  `declaration.json`, relative to the release directory, in the projection contract's
  packaged schemas.
- The expected authority digest comes only from `MANAGED_AUTHORITY_PIN`. That file must be a
  regular file owned by uid 0, not group- or world-writable, with every ancestor owned by
  uid 0. It is RFC 8785 JSON:
  `{"schema":"seat_authority_pin.v1","releases":{"<release_id>":{"<leg>":"<sha256>"}}}`.
  The release's own bytes never establish their authority.
- A missing pin, or no entry for (release, leg), gives `authority_missing`. An unsafe pin or a
  digest mismatch gives `authority_invalid`. A subject that differs from the declaration's
  gives `subject_mismatch`. These are the existing `ExecutableDependencyError` codes.
- A `managed_release` resolution never falls back to `standalone` or to an ambient path.

**`deployment_kind()`** inspects paths only and spawns nothing.
- `managed`: the running package resolves under `MANAGED_RELEASES_ROOT`.
- `uv_tool`: it resolves under a uv tool environment named `phase-loop-runtime`.
- `pip`: its distribution `INSTALLER` record reads `pip`.
- `source`: it runs from a checkout whose `phase-loop-runtime/pyproject.toml` is a sibling of
  the package source root.
- `unknown`: anything else.

**Switch-on (gate G-A, §8).** Registered profiles (IF-0-JAILCORE-1) whose projection
requirement is `optional` or `required` admit the `managed_release` requirement through
EC-JAILCORE-4's per-profile projection, and the subject launches at the profile's declared
destination. Before gate G-A, `resolve_seat_subject` returns `managed_release`, but launch
sites keep today's resolution. Profile digests are unchanged, because dependency mounts are
outside the digest. A projected launch changes the row's qualification key through
`dependency_projection_digest` (EC-JAILCORE-4), so the affected rows return to `candidate`.

**Further requirements.**
- Every Gemini subject, whatever its source, passes §5's agy admission before launch.
- Codex and Grok keep their named-exception routes (EC-JAILCORE-5) until CODEX and GROK
  register profiles. Those phases consume this interface without editing this module.
- The keyring helper the generic seat binds goes through the same bind-source checks as
  every other seat bind.

**Search-only workspace.** With `TMPDIR` and the cwd below an ancestor of mode `0o111` that
the operator owns, the real auth-probe path must reach the CLI. That path is
`executor_availability.auth_ok_for` → `_run_probe` → `_seat_probe_marker` →
`_seat_bind_source`. The test requires a non-root euid. Under euid 0 it fails rather than
skips, because root ignores the mode bits and the pass would be vacuous. If the probe raises
inside `executable_dependency.py`, lane A stops and reports to JAILCORE's owner of that file
(§8). It does not edit the file.

## 2. Operator state (IF-0-TEAMHOST-2, lane B)

New module `phase_loop_runtime/seat_host_namespace.py`:

```python
OperatorStateKind = Literal["seat_uid_leases", "native_fill", "scratch"]

def operator_private_dir(kind: OperatorStateKind, *, base: Path | None = None) -> Path
def write_private_atomic(directory: Path, name: str, data: bytes) -> None
def subordinate_ranges_disjoint(uid: int | None = None, *,
                                subuid: Path = SUBUID_FILE, subgid: Path = SUBGID_FILE) -> bool
def scratch_root_allowed(path: Path) -> bool
```

- **`operator_private_dir`.** Creates the directory with mode 0700, or accepts an existing
  one only if it is owned by the euid, has mode exactly 0700 and is not a link. Every
  component is opened `O_PATH|O_NOFOLLOW`, so search-only ancestors are allowed. Any other
  case raises `SeatSandboxRefused("seat_sandbox_refused:identity")`.
- **`write_private_atomic`.** Writes a 0600 temporary file with
  `O_CREAT|O_EXCL|O_NOFOLLOW`, fsyncs it and renames it into place. It refuses a directory
  that `operator_private_dir` would refuse.
- **`subordinate_ranges_disjoint`.** Is true only when the operator's `/etc/subuid` and
  `/etc/subgid` ranges each intersect no other entry's range. An unreadable file is false.
- **`scratch_root_allowed`.** Is false for any path at or below `/dev`, `/proc` or `/sys`.

**Construction sites.**
- `seat_uid.seat_runtime_dir`'s `/tmp/phase-loop-<uid>` fallback goes through
  `operator_private_dir("seat_uid_leases")`.
- Overlapping ranges fail the range prerequisite with `seat_sandbox_unavailable_seat_uid`
  (JAILCORE step L3). Lease semantics stay JAILCORE's (step L9).
- `sandbox_policy._child_tmp_dir` and `child_scratch_candidates` skip any `TMPDIR` that
  `scratch_root_allowed` rejects.
- The native-fill writers (`panel_invoker._write_json_atomically` and
  `president_operation`'s pending/ruling writer) use `write_private_atomic`. The directory
  layout and file names are unchanged, because external fillers read them.

**agent-harness#1108 disposition (closed list).**

| # | Item | Disposition |
|---|---|---|
| 1 | Claude channel sidecar port | Not a seat resource; recorded only. v11 RESIDUAL owns the file. |
| 2 | Task-message broker port | Not a seat resource; recorded only. |
| 3 | President native-fill files | Fixed: `write_private_atomic`. |
| 4 | Staging free-space floor | Capacity, not isolation; the refusal is already typed. Recorded. |
| 5 | CI offload lock | CI-only; recorded. |
| 6 | `TMPDIR` under `/dev` | Fixed: `scratch_root_allowed`. |
| 7 | Seat-uid lease fallback directory | Fixed: `operator_private_dir`. |
| 8 | Overlapping subordinate ranges | Fixed: L3 prerequisite, a doctor row (§3) and checklist item LA1-SUBID (§4). |

## 3. Seat admission verdicts and doctor JSON (IF-0-TEAMHOST-3, lane C)

New module `phase_loop_runtime/seat_admission.py`:

```python
Status = Literal["admits", "refuses", "unknown"]
Reason = Literal["platform_unsupported", "inventory_failed", "launch_measurement", "provider_absent"]

@dataclass(frozen=True)
class Verdict:
    leg: str
    status: Status
    code: str | None    # an existing refusal code when status == "refuses"
    fix: str | None
    reason: Reason | None

Gate = Callable[[str, Mapping[str, str], bool], Verdict | None]  # None: this gate passes

def register(leg: str, gate: Gate) -> None       # appends; idempotent per (leg, gate)
def registered_legs() -> tuple[str, ...]
def verdict(leg: str, env: Mapping[str, str], *, execute: bool = False) -> Verdict
```

**Built-in gates**, in launch order. Each calls the same function the launch path calls:
1. Host capability: `seat_jail.seat_sandbox_capable()`, which is JAILCORE step L3 once that
   lands. Applies to `claude` and `gemini`.
2. Jail pass record for the leg's live key. This is lookup only and never auto-qualifies.
   It is the pre-existing `pass_record_verdict`, or JAILCORE step L8's store once that lands.
3. `gemini`: §5's `admission_verdict`, on the `subject_path` that `resolve_seat_subject`
   returns.
4. `grok`: the pre-existing `panel_invoker.require_grok_admission`, whose code is
   `grok_tool_surface_unverified`.

**Gate rules.**
- **`execute=False`.** No provider binary is spawned. A gate that would spawn one returns
  `unknown` with reason `launch_measurement`. Host-capability probing may spawn `unshare`, as
  the route does, and only on Linux.
- **Off Linux.** Every row is `unknown` with reason `platform_unsupported`, and nothing is
  spawned.
- **Agreement (EC-TEAMHOST-5).** For every fixture state:
  - doctor `admits` implies that the real seat preparation admits;
  - doctor `refuses` carries the seat's own refusal code.
  
  A vendor phase that registers a gate adds its own agreement rows.

**Doctor JSON** (additive to `phase-loop-doctor.v1`; closed objects, `required` unchanged):

- `seat_jail_prerequisites[]` items have these keys:
  - `name`, `status` (`present|missing|unknown`) and `unlocks`;
  - optional `fix` (one §4 sentence);
  - optional `reason` (`platform_unsupported|inventory_failed`);
  - optional `checklist` (a §4 item id).

  The rows form a closed list, each using the route's or the qualification's own predicate:
  - `pytest`
  - `bwrap`
  - `setpriv`
  - `nsenter`
  - `egress_isolation`
  - `legacy_tiocsti`
  - `subordinate_ids`: present only when the ranges exist and `subordinate_ranges_disjoint()`
  - `machine_id`

  Every row reads `present` exactly when `seat_sandbox_capable()` is `None` and the
  qualification prerequisites hold.
- `seat_cli_qualification[]` (new, optional) items are
  `{leg, status, code?, fix?, reason?}`, one per registered leg. No row says `qualified` or
  `locally_qualified`.
- The golden file is updated in the same change.

## 4. Fix sentences and the LA-1 checklist (lane C)

**One sentence per fix.** `seat_jail_prerequisites.fix_sentence(name, *, deployment) -> str`
returns exactly one sentence: one terminal period, no "Also:" and one install command.
`seat_jail_autoqualify.fix_for("prerequisite_missing")` returns the missing prerequisite's
sentence when one is missing, and otherwise the existing host text. It never joins the two.

Templates, where `<Q>` is "then run `phase-loop seat-sandbox qualify`":

| `deployment` | Sentence |
|---|---|
| `managed` | "Ask the host administrator to install a managed release that carries the seat dependencies (`docs/team-host-admin.md`, item LA1-RELEASE), <Q>." |
| `uv_tool` | "Run `uv tool upgrade phase-loop-runtime`, <Q>." |
| `pip` | "Run `pip install --upgrade phase-loop-runtime` in the runtime's environment, <Q>." |
| `source` | "Run `uv sync --project phase-loop-runtime` in the checkout, <Q>." |
| `unknown` | "Reinstall `phase-loop-runtime` with the installer that installed it, <Q>." |

Host-capability rows point at their checklist item instead of an install command.

**Checklist `docs/team-host-admin.md`.** Each item gives what it is, the EC it serves, a
read-only check command and the root action as text.

| Item | What |
|---|---|
| LA1-SUBID | Disjoint subordinate uid/gid ranges for every operator account |
| LA1-TIOCSTI | `dev.tty.legacy_tiocsti = 0` |
| LA1-APPARMOR | Ubuntu 24.04+ user-namespace/setpriv override; printed by the existing `python3 -m phase_loop_runtime.seat_jail_apparmor` |
| LA1-USERNS | `kernel.unprivileged_userns_clone = 1` where that sysctl exists |
| LA1-PACKAGES | bwrap, setpriv, nsenter, newuidmap/newgidmap, slirp4netns, iptables |
| LA1-MACHINE-ID | A readable `/etc/machine-id` |
| LA1-RELEASE | A managed release that carries the runtime's declared seat dependencies (EC-TEAMHOST-3) |
| LA1-AUTHORITY-PIN | §1's root-owned pin file, with one entry per release and leg |

**Print-only module.** `python3 -m phase_loop_runtime.seat_host_admin [--all]` prints the
root actions as text. By default it covers the items the doctor rows report missing; `--all`
prints every item.
- It reads files only. It imports no `subprocess`, `pty` or `os.exec*/system/spawn*`.
- No runtime module imports it, and it never runs a root action.
- Falsifiers: an AST import scan, a runtime import-graph scan, and a run with spy executables
  on `PATH` in which none of them is invoked.

## 5. agy admission key (IF-0-TEAMHOST-4, lane D)

In `agy_qualification.py` and `gemini_heartbeat.py`:

```python
OPERATIONS_CONTRACT: tuple[Operation, ...]  # closed: operation id, argv template, env-name set
def agy_profile_digest() -> str
def qualification_key(image_sha256: str, help_sha256: str, host: str) -> dict[str, str]
def has_record(image_sha256: str, *, store: Store | None = None) -> bool  # read-only; executes nothing
class AgyVerdict(NamedTuple):  # lane C maps it onto §3's Verdict
    status: Literal["admits", "refuses", "unknown"]
    code: str | None
    reason: Literal["launch_measurement", "provider_absent"] | None
def admission_verdict(env, subject_path: Path | None, *, execute: bool) -> AgyVerdict
def requalify_once(env, *, cancel_event=None, heartbeat=None) -> Admission | None
LkgProvider = Callable[[], VerifiedImage | None]
def register_last_known_good(provider: LkgProvider) -> None
def last_known_good() -> VerifiedImage | None
# gemini_heartbeat.admit(env, *, subject_path: Path | None = None) -> Admission
```

**The key.**
- `agy_profile_digest()` is the sha256 of the canonical JSON
  `{profile_id: gemini_heartbeat.PROFILE_ID, profile: <the owned heartbeat profile
  description rendered with an <image> placeholder>, operations: OPERATIONS_CONTRACT}`.
- It excludes `__version__`, the shipped release set, file paths and file hashes.
- Every entry type is keyed by
  `{image_sha256, platform, help_sha256, host, agy_profile_digest}`.
- `written_under` (`__version__`) is MAC-bound and used for reporting only.
- Entries under the old key are ignored, never translated.
- **Rendering rule.** The qualification operations render argv and environment only from
  `OPERATIONS_CONTRACT` and the owned profile. A test pins that:
  - editing either changes `agy_profile_digest()`;
  - a version bump or a release-set edit does not.

**`requalify_once`.**
- It runs only from two places:
  - the board's pre-composition preflight, for any board composing a Gemini seat (jailed or
    heartbeat), before composition is fixed;
  - `phase-loop agy-qualification run`.
- It calls the existing `ensure_admitted` at most once per (store, key, image) within the
  existing failure window. A failure writes the existing `failed` entry, and the Gemini seat
  is refused typed.
- **Mid-run** means after the board's composition is fixed. Legs and the president stay
  lookup-only, and nothing qualifies mid-run.
- Inside a required dependency session, it refuses with `dependency_route_unwired`
  (projection contract).
- Login renewal uses the existing wait-and-renew path, so no manual `agy models` is needed.

**Last-known-good.** Suppose the subject image has no record under the live key, and
`last_known_good()` returns an image with a valid record. Then admission admits the
last-known-good image as `locally_qualified`, with `Admission.source = "lkg"`.
- With no provider registered, the function returns `None` and behaviour is unchanged.
- agent-harness#1602 registers its provider later and needs no TEAMHOST file.

**Doctor and status.**
- With `execute=False`, `admission_verdict` verifies everything except the launch-time help
  measurement, which it reports as `unknown` (`launch_measurement`). Release members give
  `admits`.
- `phase-loop agy-qualification status` adds `verdict` (computed with `execute=True`). It
  prints `key` and `written_under` in place of `runtime`.
- Codes are unchanged: `agy_image_unqualified`, `gemini_heartbeat_capability_unavailable`,
  and the existing self-qualification refusal.

## 6. agent-harness#1706 ledger (IF-0-TEAMHOST-5, lane D)

Proofs are in `test_seats_teamhost_gemini.py` and enter the real `proxy.mjs`, the jail
builder or the receipt runner. Each check has a neutralising mutant that must turn the test
red.

| Item | Disposition and proof |
|---|---|
| 1 Tests | Closed. Behavioural cases cover the inner Host check, CONNECT-host versus SNI mismatch, a non-ClientHello first record, and each `start_proxy` startup integrity check, each failing closed. |
| 2 CA key | Closed. Build the jailed Gemini seat view and scan every seat-visible bound file: the CA key bytes appear nowhere. Mutant: the CA writer places the key in the bound CA directory. |
| 3 Docs | Closed. (a) `run_mutation_receipts_1170.py` labels each run with the base it ran on; runs the file cannot attribute read `unattributed` and cite agent-harness#1555, with no head invented. (b) The red-on-main counts are recorded only for runs the file holds. (c) The J7 step-4 wording matches the resolver as landed; SL-docs edits CONTRACTS.md from text lane D supplies. |
| 4 Strict lengths | Closed. An extension or `server_name_list` length that exceeds its enclosing length is refused, never clamped. Mutant: restore the clamp. |
| 5 Bounds | Closed. Before the splice the front buffers at most one ClientHello record (`FRONT_MAX_HELLO_BYTES = 16389`), and after it nothing. An idle front connection closes after `FRONT_IDLE_MS = 30000`. This is a proxy argument with that default, which the production wrapper never passes. |
| 6 Overlay | Closed if measured. The writable `.gemini/config` overlay is narrowed to the subpaths agy writes, measured on a developer host with the developer's own login (principle 5) and recorded as metadata in `plans/evidence/seat-teamhost/gemini-config-writes.json`. If no measurement can be made, the item is deferred with that reason recorded. Lands under gate G-D. |
| 7 Probe | Shape-(b) row: closed as a row in the behavioural front suite, with an offline fixture plus a live variant where the egress layer is installed. The pinned FIRSTSEAT probes are unchanged. Live re-witness: deferred to the first Gemini row window, because the window kit (IF-0-FIRSTSEAT-2) is the single qualification procedure and the p4 probe is a pinned FIRSTSEAT method input. |

**Gemini transition.** Items 4–6 and §5 change the Gemini qualification key, so the Gemini row
returns to `candidate`. Every such change names the first row window after TEAMHOST exits.
TEAMHOST runs no window.

## 7. Cross-repo (IF-XR-1)

Consiliency/dotfiles builds the managed releases. A release that serves review seats ships
§1's per-leg `authority.json` and `declaration.json`. The host administrator writes §1's pin
file (LA1-AUTHORITY-PIN). Until both exist on a host:
- that host's seats resolve `managed_release` and refuse with `authority_missing`;
- the doctor reports the checklist item.

TEAMHOST lands no dotfiles change.

## 8. Cross-phase edit scopes and gates

| File | Also written by | TEAMHOST scope |
|---|---|---|
| `panel_invoker.py` | JAILCORE SL-3, v11 PANELSPLIT | Lane A2 only. `_FRONTDOOR_RELEASES` aliases `MANAGED_RELEASES_ROOT`. Subject resolution in `_seat_provider_source`, `seat_profile` and `_seat_command_profile`; the keyring-helper bind; `_write_json_atomically`; the subject seam in `_prepare_jailed_gemini` and `_prepare_jailed_claude`; the preflight call in `_preflight_gemini_heartbeat` and `invoke_board`. |
| `seat_uid.py` | JAILCORE SL-3 (L9 split) | Lane B: `seat_runtime_dir`, plus the range conjunct of the L3 prerequisite. |
| `seat_jail_autoqualify.py` | JAILCORE SL-3 | Lane C: `fix_for` only. |
| `seat_jail.py`, `seat_profiles.py` | JAILCORE SL-3 | Lane D: the Gemini writable-overlay data and the Gemini bind builder only. |
| `seat_egress/proxy.mjs` | JAILCORE SL-1 | Lane D: the ClientHello parser and the front connection handler only. |
| `doctor.py` | v11 GOVSETUP | Lane C: the seat rows only. |
| `CHANGELOG.md`, `advisor_board/CONTRACTS.md`, the capabilities card, `tests/data/seat_launch_references.json` | JAILCORE SL-4 | SL-docs: TEAMHOST entries and sections only, union-resolved. |

**Gates** (cross-phase; not lane-DAG edges):
- **G-F.** Every lane executes after FIRSTSEAT exits (roadmap scope).
- **G-A.** Lane A2's switch-on lands only on a base that contains EC-JAILCORE-4's per-profile
  projection under IF-0-JAILCORE-1.
- **G-D.** Lane D's item-6 overlay change lands only on a base that contains the
  IF-0-JAILCORE-1 registration of the Gemini profile. It edits that registered form.

No TEAMHOST dependant waits longer because of G-A or G-D: CODEX, GROK, PI and CLAUDENET
already depend on JAILCORE.
