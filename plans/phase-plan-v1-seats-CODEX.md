---
phase_loop_plan_version: 1
phase: CODEX
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: b91c98ad7b9097ba411ca21f39cf390878dabac449e59d6fdfd1750915c16a09
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seat_codex_vocabulary.py", "phase-loop-runtime/tests/test_seat_codex_runtime.py", "phase-loop-runtime/tests/test_seat_codex_credential.py", "phase-loop-runtime/tests/test_executor_availability.py", "phase-loop-runtime/tests/test_seat_egress_allowlist_codex.py", "phase-loop-runtime/tests/test_seat_codex_cli_shape.py", "phase-loop-runtime/tests/test_seat_profile_codex.py", "phase-loop-runtime/tests/test_seat_codex_evidence.py", "phase-loop-runtime/tests/test_seat_codex_leg.py", "phase-loop-runtime/tests/test_seat_codex_route_gate.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# CODEX: Codex Seat in the Jail

## Context

This plan covers roadmap Phase 6 (CODEX) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Exit criteria are EC-CODEX-1 to EC-CODEX-5, cited by ID only. The roadmap
is advisory (OD-1) and the runner refuses it, so lanes land as governed PRs under principle 2.

**Inputs.**

- `plans/seats-jailcore-route-contract.md`, sha256
  `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`: §1 profile, §2 walk,
  §3 code classes, §5 key, §7 egress. This phase adds what §1 allows a vendor: one
  `JailProfile`, one allowlist file, its own `codex_seat_*` codes with one additive
  `OD10_CLASSES` entry each, and its window rows as data on the profile. It adds no branch in
  a core builder or the resolver, and no edit to the window kit.
- TEAMHOST. The roadmap declares no `IF-0-TEAMHOST-*` gate; its draft plan, agent-harness#1859,
  does. This plan consumes IF-0-TEAMHOST-1 (seat subject) and IF-0-TEAMHOST-3 (admission gates)
  by ID, pins no digest of that draft, and cites EC-TEAMHOST-2 for concurrent accounts.
- IF-0-FIRSTSEAT-1, IF-0-FIRSTSEAT-2 and IF-0-FIRSTSEAT-3.

**Read-only facts, codex-cli 0.167.0.** No provider request was made.

- `exec` accepts `--sandbox danger-full-access`, `--json`, `--ignore-user-config`,
  `--ignore-rules` and `--ephemeral`. `--ignore-user-config` skips `config.toml`.
- The vendored target holds `bin/codex`, `bin/codex-code-mode-host`, `codex-path/rg`,
  `codex-package.json` and `codex-resources/`. The last holds the bundled `bwrap`.
- `responses_websockets` and `responses_websockets_v2` list as `removed`, and srt's
  terminating proxy refuses an upgrade inside a tunnel. A turn over plain HTTPS is therefore
  unproven. SL-2 proves it first.

**Design decisions.**

- **Workspace.** The CLI's working directory is the empty `/seat/home/workspace`, as for
  Gemini. The staged tree is not its workspace, so project-level loaders find nothing, and
  the seat reads `/seat/tree` with its tools.
- **Credential location.** `.codex` is a directory in `seat-home`. The hand-off already
  covers `seat-home` recursively. A `codex-config/` sibling would need `seat_uid` changes
  outside IF-0-JAILCORE-1, and EC-CODEX-2 states the delivery as seat home.
- **Subject.** The native image is the jailed subject. The launcher is resolved and
  trust-checked on the host (`resolve_seat_subject`, agent-harness#1798). No interpreter
  enters the view (roadmap assumption 2). This is the coordinator's confirmed reading of
  EC-CODEX-2.

**Enablement.** Registering `CODEX_PROFILE` is the switch: contract step L1 stops consulting
the `unconfined` exception. So SL-3 lands as one PR, and its evidence comes from its branch
head before OD-4 is asked. The profile and the wiring land together with the registration,
and nothing on main can reach the route early.

**Execution gate.** Plan now; execute after JAILCORE and TEAMHOST exit (roadmap "Depends on").

## Interface Freeze Gates

- [ ] IF-0-CODEX-1 — `phase_loop_runtime/seat_profile_codex.py` exports `CODEX_PROFILE:
  JailProfile`, with these field values:

  | Field | Value |
  |---|---|
  | `leg`, `vendor` | `codex`, `codex` |
  | `owner_binds` | `--ro-bind <egress-ca> /seat/egress-ca.pem`, then `runtime_binds` (none when a dependency is admitted) |
  | `env` | `CODEX_HOME=/seat/home/.codex`, `HTTPS_PROXY=<proxy url>`, `SSL_CERT_FILE` and `CODEX_CA_CERTIFICATE=/seat/egress-ca.pem`, `PATH=<runtime root>/codex-path:/seat/bin:/usr/bin:/bin` |
  | `home_dirs` | `.codex`, `workspace` |
  | `new_session`, `token_fd` | `True`, `False` |
  | `argv` | `jailed_codex_command`, below |
  | `projection` | `optional` |
  | `credential` | `CredentialDelivery("home_file", "codex-credential-scope")` |
  | `credential_present`, `credential_missing_code` | `seat_codex_credential.present`, `codex_seat_credential_missing` |
  | `preconditions` | `subscription_login`, `token_margin`, `scope_ceiling`, in that order (IF-0-CODEX-2) |
  | `recorded_stop`, `variant` | `None`, `None` |
  | `config_surface` | `ConfigSurface(True, CODEX_PLANTED_PATHS)` |
  | `auth_probe` | the existing `codex login status` tri-state (`_parent_auth_state`) |
  | `output_secret_code` | `codex_seat_token_in_output` |
  | `containment` | `ContainmentEvidence("codex-credential-scope", "codex-refresh-detection", "codex-unlisted-endpoint", None)` |
  | `allowlist_id` | `codex` |
  | `notice_codes` | the IF-0-CODEX-5 table |
  | `window` | `CODEX_WINDOW_ROWS`, below |

  `digest_placeholders` and `mount_points` cover the CA and every runtime destination.
  The profile also creates the runtime bind parents (`/run`, `/run/phase-loop-seat`, the runtime root, `bin`, `codex-path`) as 0755 directories before the file binds, because bwrap would otherwise create a missing bind parent as 0700.
  `CODEX_TREE_ROWS` is one list of `(path, role)` rows. `CODEX_PLANTED_PATHS` is its paths, so
  the falsifier and the window plant the same set. SL-3 may extend it, never shrink it:

  | Role | Paths |
  |---|---|
  | `provider_overrides` | `AGENTS.md`, `AGENTS.override.md`, `.codex/rules/default.rules`, `.codex/skills/s/SKILL.md`, `.agents/skills/s/SKILL.md` |
  | `project_settings` | `.codex/config.toml` |
  | `hooks` | `.codex/hooks.json` |
  | `mcp_servers` | `.mcp.json` |

  `CODEX_WINDOW_ROWS` is `WindowRows` data only (contract §1): record fields `canonical_codex`
  and `codex_route`, route literal `jailed`, tree rows `CODEX_TREE_ROWS`, and these locations:

  | Location | Path in the jail | Host backing |
  |---|---|---|
  | `tree` | `/seat/tree` | the staged tree |
  | `workdir` | `/seat/home/workspace` | `seat-home/workspace` |
  | `home` | `/seat/home` | `seat-home` |
  | `provider_config` | `/seat/home/.codex` | `seat-home/.codex` |

  ```text
  <runtime root>/bin/codex
    --disable <feature>...        # JAILED_CODEX_DISABLED_FEATURES
    exec --ignore-user-config --ignore-rules --ephemeral --json
    --cd /seat/home/workspace --skip-git-repo-check
    --sandbox danger-full-access
    -c approval_policy="never" -c cli_auth_credentials_store="file"
    --model <model> <effort args>
    --output-last-message /seat/out/panel-codex.txt -
  ```

  `JAILED_CODEX_DISABLED_FEATURES` is `_BROKER_CODEX_DISABLED_FEATURES` minus `shell_tool` and
  `code_mode_host`, plus `daemon_auto_start` and `plugin_discovery_prefetch`. The argv never
  carries `--dangerously-bypass-approvals-and-sandbox`, `--dangerously-bypass-hook-trust`,
  `--add-dir`, `--worktree`, `--oss` or `--profile`. Attested controls are
  `_JAILED_CODEX_TOOL_CONTROLS`, which name `inner-sandbox-off-inside-seat-jail`,
  `workspace-empty-cwd`, `tree-not-a-workspace`, `egress-allowlisting-proxy` and `seat-jail`.

  `seat_profile_codex.register_codex()` is the whole registration:
  `seat_profiles.register(CODEX_PROFILE)`, `register_provider_executable("codex", "codex")` and
  `seat_admission.register("codex", codex_admission_gate)`. Its one call site is the Codex
  entry in `seat_profiles.py`, at import. The gate runs the three preconditions in order and
  then `codex_cli_shape_problem`. A shape miss refuses `codex_seat_cli_shape`. It does not
  refuse `codex_seat_tools_unavailable`. With `execute=False` that last check returns
  `unknown` with reason `launch_measurement`.
- [ ] IF-0-CODEX-2 — Runtime and credential.

  ```python
  # seat_codex_runtime.py
  CODEX_RUNTIME_ROOT = "/run/phase-loop-seat/codex-runtime"
  CODEX_RUNTIME_FILES = ("bin/codex", "bin/codex-code-mode-host",
                         "codex-path/rg", "codex-package.json")
  def resolve_runtime(native: Path) -> CodexRuntime        # one regular, unlinked source per file
  def runtime_binds(runtime: CodexRuntime) -> tuple[str, ...]

  # seat_codex_credential.py
  CODEX_SCOPE_CEILING: frozenset[str]                      # measured in SL-1
  CODEX_LOGIN_MIN_S: int                                   # measured in SL-1
  def auth_path(env: Mapping[str, str] | None = None) -> Path
  def present() -> bool
  def subscription_login_problem(raw: bytes) -> str | None
  def token_margin_problem(raw: bytes, *, now: float) -> str | None
  def scope_problem(raw: bytes) -> str | None
  def build_seat_copy(raw: bytes) -> CodexSeatCopy         # data, secrets, tokens_sha256, expires_at
  def tokens_changed(copy: CodexSeatCopy, observed: bytes) -> bool
  ```

  `CodexSeatCopy.data` and `.secrets` are excluded from `repr`. The admitted login is
  `auth_mode == "chatgpt"` with an empty `OPENAI_API_KEY` and a `tokens` object. The copy keeps
  `auth_mode`, `last_refresh`, a null `OPENAI_API_KEY`, and `tokens` with `access_token`,
  `id_token`, `account_id` and an empty `refresh_token`. Any other key is dropped unless SL-1
  measures the CLI needing it. It lands at `seat-home/.codex/auth.json`, mode 0600, before the
  hand-off. `resolve_seat_subject("codex", env)` selects the path. A `standalone` subject's
  `subject_path` goes to `resolve_runtime`. A `session_lease` subject is admitted through the
  profile's projection on that lease's own closure, at the same destinations under
  `CODEX_RUNTIME_ROOT`, with no fallback to `standalone`. A `managed_release` subject is
  admitted the same way and never falls back. This phase specifies its declaration:
  `CODEX_RUNTIME_FILES` at those destinations, never `codex-resources/`. Consiliency/dotfiles
  builds that `declaration.json` (IF-XR-1). No lane here edits dotfiles. `codex-resources/`
  is never projected.
- [ ] IF-0-CODEX-3 — `seat_egress/codex-allowlist.json`, schema
  `phase_loop_seat_egress_allowlist.v1`, `leg: "codex"`, id `codex`, loaded only through
  `allowlist_ref("codex")`. Each `allow` rule has `host`, `port` 443, `method` and one of
  `path` or `path_prefix`. No host carries a wildcard, no `path_prefix` is `/`, and no `allow`
  host appears in another `seat_egress/*-allowlist.json`. The CLI's token endpoint host is in
  `measured_and_refused`, never in `allow`. Rows are measured in SL-2 and not guessed here.
- [ ] IF-0-CODEX-4 — `seat_codex_evidence.py`, the rule for "the seat's tools could not run".

  ```python
  @dataclass(frozen=True)
  class CodexToolRecord:
      stream_valid: bool
      turn_completed: bool
      commands_completed: int   # status completed, exit_code 0, non-empty output
      commands_failed: int
      unknown_event: bool       # a top-level event whose name is outside CODEX_TOOL_EVENTS
  def read_tool_record(stream: bytes) -> CodexToolRecord
  def tools_ran_code(record: CodexToolRecord) -> str | None
  ```

  It reads only the parent-held `--json` stdout, never the reply or the output file. Command
  output inside an event is not parsed as a further event. A leg counts only with
  `stream_valid`, `turn_completed`, `commands_completed >= 1` and `unknown_event` false.
  `tools_ran_code` returns `codex_seat_unknown_event` when `unknown_event` is set,
  `codex_seat_tools_unavailable` when the stream is truncated or no command completed, and
  `None` when the leg counts. Event names are bound in `CODEX_TOOL_EVENTS` from SL-3.1's
  measurement.
  `CODEX_TOOL_EVENTS` includes the measured top-level `error` name; an `error` followed by `turn.completed` in the same turn does not itself invalidate the leg, while all existing stream-validity, completed-command and unknown-event requirements remain in force.

  Post-launch order, first match ends the leg:
  1. a copied secret or the proxy credential in any kept byte: `codex_seat_token_in_output`;
  2. `tokens_changed`, read before teardown: `codex_seat_token_refreshed_in_jail`;
  3. a non-zero exit after `expires_at`: `codex_seat_token_expiring`;
  4. `tools_ran_code`;
  5. `_classify_leg`.
- [ ] IF-0-CODEX-5 — Nine new `codex_seat_*` codes, in `seat_jail.NOTICES`, each with one
  additive `OD10_CLASSES` entry (contract §1). All are terminal. No existing entry changes, and neither do
  `DESCEND_CODES`, `REMOTE_DESCEND_CODES` or `CAPACITY_CODES`. An unsafe auth file reuses
  `seat_sandbox_refused:token_file_unsafe`.

  | Code | Class | Raised | Fix (gist) |
  |---|---|---|---|
  | `codex_seat_credential_missing` | ordinary | L5 | run `codex login`, then re-run |
  | `codex_seat_api_key_refused` | ordinary | L6 | sign in to the CLI with your subscription, then re-run |
  | `codex_seat_token_expiring` | ordinary | L6, launch, post-launch | run the codex CLI as yourself to renew the login, then re-run |
  | `codex_seat_token_scope_excess` | security | L6 | report the outcome privately; the seat stays degraded |
  | `codex_seat_token_in_output` | security | post-launch | report the outcome privately |
  | `codex_seat_token_refreshed_in_jail` | security | post-launch | report the outcome privately |
  | `codex_seat_cli_shape` | ordinary | admission gate | upgrade the codex CLI so `codex exec --help` matches the jailed argv, then re-run |
  | `codex_seat_tools_unavailable` | ordinary | post-launch | read the leg's exec record; the seat did not count as a review |
  | `codex_seat_unknown_event` | security | post-launch | report the outcome privately |

## Lane Index & Dependencies

SL-0 — Codex vocabulary (preamble)
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4
  Parallel-safe: no

SL-1 — Projection and credential (lane B)
  Depends on: SL-0
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-2 — Allowlist measurement and probes (lane C)
  Depends on: SL-0
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-3 — Profile, leg and route enablement (lane A)
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — Documentation, inventory and row reducer (SL-docs)
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Codex vocabulary (preamble)

- **Scope**: Publish the IF-0-CODEX-5 codes and their additive OD-10 entries, with no route change.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_codex_vocabulary.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_jail.py`
- **Interfaces provided**: IF-0-CODEX-5
- **Interfaces consumed**: `seat_route_contract.OD10_CLASSES` (pre-existing), `seat_jail.NOTICES` (pre-existing)
- **Parallel-safe**: no (preamble)

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/test_seat_codex_vocabulary.py` | Each of the nine table codes has a what/why/fix row, one additive `OD10_CLASSES` entry and the table's class. No fix line names a sealed, inline or key route. Removing the `codex_seat_*` entries leaves `OD10_CLASSES` equal to its base, and the three descend sets equal their literal values. The `seat_route` import closure passes. | `V0` |
| SL-0.2 | impl | SL-0.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 files | all SL-0 tests | `V0` |

### SL-1 — Projection and credential (lane B)

- **Scope**: Provide the runtime file set, the credential copy and its measured scope, and fix the logged-out probe, independent of OD-4.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_codex_runtime.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_codex_credential.py`, `phase-loop-runtime/src/phase_loop_runtime/executor_availability.py`, `phase-loop-runtime/tests/test_seat_codex_runtime.py`, `phase-loop-runtime/tests/test_seat_codex_credential.py`, `phase-loop-runtime/tests/test_executor_availability.py`, `plans/evidence/seat-codex/credential-scope.json`
- **Interfaces provided**: IF-0-CODEX-2; evidence id `codex-credential-scope`
- **Interfaces consumed**: IF-0-CODEX-5 (SL-0), `seat_jail.read_regular_file_at` (pre-existing), IF-0-TEAMHOST-1 (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_seat_codex_runtime.py` | Two synthetic layouts resolve the same file set. A missing file gives `seat_provider_unavailable`. A linked, group-writable or wrongly owned file gives `seat_sandbox_refused:identity`. No bind names `codex-resources` or the target directory itself. A `managed_release` subject never reaches `resolve_runtime`. | `V1` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_codex_runtime.py` | — | — |
| SL-1.3 | test | SL-1.2 | `phase-loop-runtime/tests/test_seat_codex_credential.py`, `phase-loop-runtime/tests/test_executor_availability.py` | An `OPENAI_API_KEY` value, `auth_mode` other than `chatgpt`, or absent `tokens` gives `codex_seat_api_key_refused`. The copy has an empty `refresh_token`, no dropped key, and no secret in `repr`. Margin and scope each give their one code. An access token whose claims cannot be decoded gives `codex_seat_token_scope_excess`, and the check calls no issuer. `tokens_changed` is false on an identical read and true when any token differs. `Not logged in`, in either case, is a logged-out probe (agent-harness#1528). Every `codex_seat_*` code this lane raises is one of the nine IF-0-CODEX-5 codes, with its `OD10_CLASSES` entry from SL-0. | `V1` |
| SL-1.4 | impl | SL-1.3 | `phase-loop-runtime/src/phase_loop_runtime/seat_codex_credential.py`, `phase-loop-runtime/src/phase_loop_runtime/executor_availability.py` | — | — |
| SL-1.5 | verify | SL-1.4 | SL-1 files, `plans/evidence/seat-codex/credential-scope.json` | Measure the narrowest copy the CLI runs with, and the scope ceiling, on a developer host. The 0.167.0 CLI renews nothing while the access token is valid, so `CODEX_LOGIN_MIN_S` is the leg backstop plus 300s (`panel_invoker._LEG_TIMEOUT_MAX_S + 300`). The record holds field names and counts only. | `V1`, `VM` |

The scope check decodes the access token's claims on the host and calls no issuer. A token
whose claims cannot be decoded refuses `codex_seat_token_scope_excess`. Its pass is
labelled `no wider than the recorded baseline`.

### SL-2 — Allowlist measurement and probes (lane C)

- **Scope**: Measure Codex's request set, ship its allowlist, prove the refusals, and settle agent-harness#1472.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_egress/codex-allowlist.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_codex_cli_shape.py`, `phase-loop-runtime/tests/test_seat_egress_allowlist_codex.py`, `phase-loop-runtime/tests/test_seat_codex_cli_shape.py`, `plans/evidence/seat-codex/allowlist-probes.json`
- **Interfaces provided**: IF-0-CODEX-3; `codex_cli_shape_problem(exec_help: str, features: str) -> str | None`; evidence id `codex-unlisted-endpoint`
- **Interfaces consumed**: IF-0-JAILCORE-2 (pre-existing), IF-0-CODEX-5 (SL-0)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_seat_egress_allowlist_codex.py`, `phase-loop-runtime/tests/test_seat_codex_cli_shape.py` | The IF-0-CODEX-3 shape rules. Every `probe_rows` entry, path-entered through the real `proxy.mjs`: each allowed row reaches a fixture upstream, and refused, unlisted and Gemini-listed hosts do not. A fixture upstream silent past `FRONT_IDLE_MS` keeps its stream. `gemini-allowlist.json` bytes are unchanged. The shape check names a missing flag, sandbox value or event. | `V2` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_egress/codex-allowlist.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_codex_cli_shape.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 files, `plans/evidence/seat-codex/allowlist-probes.json` | One real tooled turn, with upgrades refused, through the proxy (`VM`). Then each refused row from a jailed tool command under a fixture-registered profile (`VL`). SL-3.9 repeats `VL` on the real profile. | `V2`, `VM`, `VL` |

**STOP condition.** If a turn cannot complete over HTTPS with upgrades refused, or the front's
idle bound closes a healthy stream, SL-2 stops and reports the sentence to change. WebSocket
inspection is an IF-0-JAILCORE-2 amendment, not a CODEX edit to `proxy.mjs` or the srt pin.

agent-harness#1472 disposition: the shape check replaces the `codex sandbox` shape binding on
the jailed route, and `seat_cli_qualification[]` reports it through the Codex gate
(IF-0-TEAMHOST-3). The non-brokered route keeps the agent-harness#1469 probe unchanged.

### SL-3 — Profile, leg and route enablement (lane A)

- **Scope**: Build the profile and jailed leg, prove EC-CODEX-5 from the branch head, then on OD-4 register the profile, record the agent-harness#1480 decision and retire the inner-sandbox retention.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profile_codex.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_codex_evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`, `phase-loop-runtime/tests/test_seat_profile_codex.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_codex_evidence.py`, `phase-loop-runtime/tests/test_seat_codex_leg.py`, `phase-loop-runtime/tests/test_seat_codex_route_gate.py`, `phase-loop-runtime/tests/test_seat_codex_provider_free.py`, `phase-loop-runtime/tests/fixtures/codex_fixture_provider.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_codex_seat_tool_sandbox_1335.py`, `phase-loop-runtime/tests/test_codex_seat_writable_tree_1470.py`, `phase-loop-runtime/tests/test_broker_staged_tree_delivery.py`, `phase-loop-runtime/tests/test_sandbox_egress.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `plans/decision-seats-codex-boundary.md`, `plans/evidence/seat-codex/refresh-detection.json`, `plans/evidence/seat-codex/provider-free.json`
- **Interfaces provided**: IF-0-CODEX-1, IF-0-CODEX-4; evidence id `codex-refresh-detection`
- **Interfaces consumed**: IF-0-CODEX-2 (SL-1), IF-0-CODEX-3 (SL-2), `codex_cli_shape_problem` (SL-2), IF-0-CODEX-5 (SL-0), IF-0-JAILCORE-1 (pre-existing), IF-0-JAILCORE-3 (pre-existing), IF-0-FIRSTSEAT-3 (pre-existing), IF-0-TEAMHOST-1 (pre-existing), IF-0-TEAMHOST-3 (pre-existing), the profile-sourced window kit `seat_window` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_seat_profile_codex.py`, `phase-loop-runtime/tests/test_seat_codex_evidence.py` | Field values and argv literal, including the forbidden flags. The profile registers in a fixture with no core edit. `CODEX_WINDOW_ROWS` reach the window kit with no kit-code edit. `read_tool_record` on recorded CLI streams: a tooled run counts; zero commands, all commands failed, and a truncated stream give `codex_seat_tools_unavailable`; an unknown top-level event gives `codex_seat_unknown_event`. A forged event inside a command-output string does not count. | `V3` |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_profile_codex.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_codex_evidence.py` | — | — |
| SL-3.3 | test | SL-3.2 | `phase-loop-runtime/tests/test_seat_codex_leg.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py` | With a fixture-registered profile, path-entered through `_default_spawn` and the real output read: each post-launch step gives its code in order; a verdict with no completed command is not counted (the agent-harness#1335 record); `qualify("codex")` records a v2 pass; the production and probe views agree. | `V3` |
| SL-3.4 | impl | SL-3.3 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py` | — | — |
| SL-3.5 | test | SL-3.4 | `phase-loop-runtime/tests/test_seat_codex_provider_free.py`, `phase-loop-runtime/tests/fixtures/codex_fixture_provider.py` | `live_jail` cases with the real CLI and a synthetic auth copy, on `jailed_codex_command` plus the fixture provider's `-c` keys: a scripted tool call reads a tree sentinel; no planted marker reaches the fixture's request body; a rewritten `auth.json` gives the refresh code. One jailed `unshare` or `bwrap` attempt is refused by the seat filter and creates no nested namespace. Mutation control: the same run with `--sandbox workspace-write` is typed unavailable. | `VL` |
| SL-3.6 | verify | SL-3.5 | SL-3 files, `plans/evidence/seat-codex/provider-free.json`, `plans/evidence/seat-codex/refresh-detection.json` | `VL` on the designated seat host. OD-4 goes to the owner with this evidence. Stop here until it is recorded. Reproducing agent-harness#1335 on a team host is optional later `done-team` evidence and does not gate OD-4, the phase, or `done-local`. | `V3`, `VL` |
| SL-3.7 | test | SL-3.6 | `phase-loop-runtime/tests/test_seat_codex_route_gate.py`, `phase-loop-runtime/tests/test_codex_seat_tool_sandbox_1335.py`, `phase-loop-runtime/tests/test_codex_seat_writable_tree_1470.py`, `phase-loop-runtime/tests/test_broker_staged_tree_delivery.py`, `phase-loop-runtime/tests/test_sandbox_egress.py`, `phase-loop-runtime/tests/test_panel_invoker.py` | Registered: every `containment` field and `scope_evidence` resolves to a committed record, `allowlist_ref("codex")` has rows, and `plans/decision-seats-codex-boundary.md` records OD-4 accepted. The mode line reads `jailed` on a capable host. `seat_filesystem_unconfined` is unreachable for a `review` seat. L3 failures walk R, N, D. `setfcap` is absent. Agreement rows cover each L5 and L6 code and `codex_seat_cli_shape` through the gate. Repo-only reads skip on an installed wheel. | `V4` |
| SL-3.8 | impl | SL-3.7 | `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_egress.py`, `plans/decision-seats-codex-boundary.md` | — | — |
| SL-3.9 | verify | SL-3.8 | SL-3 files | all SL-3 tests | `V3`, `V4`, `V5`, `VL` |

**SL-3.4 scope.** `_prepare_jailed_codex` and `_exec_jailed_codex_leg` follow the jailed Gemini
order: tree re-hash, provider, login, copy, CA, jail, probe jail, then `stdout_guard` over every
secret and the proxy credential. The leg holds `RouteDecision.lease` throughout.

**SL-3.8 scope.** One line in `seat_profiles.py` calls `register_codex()`. It also removes
`_BROKER_CODEX_SANDBOX_RETAINED_CAPS`, the `setfcap` entry in `SEAT_RETAINABLE_CAPS`, the staged
branch of `_brokered_codex_command` and its writable-tree grant (agent-harness#1470). The
agent-harness#1469 probe stays for the non-brokered route. The decision record states:
agent-harness#1480's seat-launch-owner fallback is removed for `review` seats, because step L1
leaves it no path once the profile is registered. `advisory_document` and
`qualification_candidate` keep their routes (contract §2).

### SL-4 — Documentation, inventory and row reducer (SL-docs)

- **Scope**: Single writer of shared docs and inventories, and of the row's window record.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `plans/manifest.json`, `plans/evidence/seat-qualification/**`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-CODEX-1, IF-0-CODEX-2, IF-0-CODEX-3, IF-0-CODEX-4, IF-0-CODEX-5, IF-0-FIRSTSEAT-1 (pre-existing), IF-0-FIRSTSEAT-2 (pre-existing)
- **Parallel-safe**: no (terminal)

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan with `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if the helper is absent, record "manual catalog audit". |
| SL-docs.2 | docs | SL-docs.1 | per catalog | Per landing: inventory rows for any changed launch reference and an `[Unreleased]` CHANGELOG entry. After SL-3: CONTRACTS.md and the card state the jailed route, the boundary decision, credential delivery as it is, and the codes. |
| SL-docs.3 | docs | SL-docs.2 | `docs/review-seats-readiness.md`, `plans/evidence/seat-qualification/**` | The row reads `candidate` from the provider-free receipt on its current key. The next row window's record, through the profile-sourced kit, takes it to `done-local`, or OD-9 applies. `seat_window.py` is not edited. Comment closure on agent-harness#1335, agent-harness#1003, agent-harness#941, agent-harness#1480, agent-harness#1528, agent-harness#1472 and the Codex half of agent-harness#1653. |
| SL-docs.4 | verify | SL-docs.3 | — | `V6` and the hosted docs-freshness audit. |

## Execution Notes

- **Critical path.** SL-0 lands first. SL-1 and SL-2 then run in parallel, and OD-4 waits for
  neither. SL-3 opens after both merge. SL-4's tasks ride each landing PR.
- **OD-4.** Accepted: SL-3.7 onward proceeds. Rejected: SL-3 does not land, and the roadmap's
  OD-4 row governs what follows. Lanes SL-0, SL-1 and SL-2 stay landed and inert.
- **Exception date.** The matrix's Codex `unconfined` exception expires 2026-12-04 UTC. After
  that a seat with no registered profile resolves degraded unless an owner record renews it.
- **Single writers.** `seat_profile_codex.py` and `codex-allowlist.json` are qualification-
  pinned, and this phase owns their digests (principle 4). `seat_route_contract.py`,
  `seat_jail.py`, `panel_invoker.py` and `seat_profiles.py` are shared with GROK, PI and v11
  PANELSPLIT; the first two take additive rows only. Whichever lands second rebases; if PANELSPLIT has moved the seat-launch code,
  SL-3 edits the named successor and records the path.
- **Coordinator rulings.** Vendor codes follow contract §1's additive rule. JAILCORE owns the
  vendor-parametric window kit (its SL-3.5), so this phase adds only `CODEX_WINDOW_ROWS`, as
  data on the profile. EC-CODEX-2 is read as Context's Subject decision states.
- **Open with TEAMHOST.** Its contract §6 item 5 says "An idle front connection closes after
  `FRONT_IDLE_MS = 30000`" and that the bound cannot be disabled. It does not say the bound ends
  at the splice. The runtime records healthy Codex transcript silences of about 73 seconds, and
  the network gap inside a turn is unmeasured. The sentence should limit the close to before
  the splice.
- **Cross-repo (IF-XR-1).** On a managed host, EC-CODEX-4's designated-seat-host run needs a release whose
  Codex `declaration.json` lists `CODEX_RUNTIME_FILES` at these destinations, plus its pin
  entry. From TEAMHOST's gate G-A on, the seat refuses `authority_missing` until both exist. No
  lane here edits Consiliency/dotfiles, which builds those releases.
- **Shared-host limits.** Before each test command, check `uptime` and `/proc/pressure/io`.
  Run targeted files serially, with no `-n`, under `timeout 900`, using system python3.14.4 for
  jail tests. The full suite runs only in hosted CI and Gate A.
- **OD-10.** A containment finding found while executing is reported privately under the
  operator's private state, never in a PR, commit or test name.
- **Skill deviations (planning).** Reconnaissance ran in-thread because the context was already
  gathered. The `advisor()` step is unavailable here, so the plan goes to the cross-vendor
  review round.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`
- evidence paths: `plans/evidence/seat-codex/provider-free.json`, `plans/evidence/seat-codex/allowlist-probes.json`, `plans/evidence/seat-codex/credential-scope.json`, `plans/evidence/seat-codex/refresh-detection.json`, `plans/evidence/seat-qualification/`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-CODEX-1 — proven by `V3`, `V4` and `VL` (`test_seat_codex_route_gate.py`, `test_seat_codex_provider_free.py`). Falsified by a nested namespace attempt inside the jailed seat, by `seat_filesystem_unconfined` on a capable host, or by enabling the route before egress is confined. The `--sandbox workspace-write` mutation passing, and registration with any unresolved evidence field, are the same failures. Path-entered control: the seat enters through `_default_spawn` and the real jail, and `VL` includes the nested-namespace attempt while the argv keeps `--sandbox danger-full-access`.
- [ ] EC-CODEX-2 — proven by `V1` and `plans/evidence/seat-codex/credential-scope.json`. Falsified by an API-key auth file reaching a copy, a `Not logged in` probe read as logged in, or a bind outside `CODEX_RUNTIME_FILES`. Path-entered control: the file enters through `auth_path` and `build_seat_copy`; the probe through the real availability check.
- [ ] EC-CODEX-3 — proven by `V2` and `VL` (`test_seat_egress_allowlist_codex.py`). Falsified by a jailed tool command or the CLI reaching an unlisted host or a Gemini-listed host. Path-entered control: requests enter through the real `proxy.mjs` and a jailed tool command.
- [ ] EC-CODEX-4 — proven by `VL` on the designated seat host, then the row-window record under `plans/evidence/seat-qualification/`. Reproducing agent-harness#1335 on a team host is optional later `done-team` evidence and does not gate OD-4, the phase, or `done-local`. Falsified by a `done-local` row with no window record on its current qualification key. Path-entered control: through `seat_window.verify_records` on the exported record.
- [ ] EC-CODEX-5 — proven by `V3` (`test_seat_codex_evidence.py`, `test_seat_codex_leg.py`) and `plans/decision-seats-codex-boundary.md`. Falsified by a recorded zero-command stream returning OK. Path-entered control: the stream enters through `_exec_jailed_codex_leg` and the real `_run_leg_with_liveness`.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, with system
python3.14.4 and file paths under `phase-loop-runtime/tests/`. On this plan-only checkout the
new test files are absent, so these are pending selectors, not receipts.

- `V0`: `P test_seat_codex_vocabulary.py test_seat_route_contract.py test_seat_notices.py`
- `V1`: `P test_seat_codex_runtime.py test_seat_codex_credential.py test_executor_availability.py`
- `V2`: `P test_seat_egress_allowlist_codex.py test_seat_codex_cli_shape.py test_seat_egress_allowlists_jailcore.py`
- `V3`: `P test_seat_profile_codex.py test_seat_codex_evidence.py test_seat_codex_leg.py test_seat_profiles.py test_seat_route.py test_seat_jail_qualification_entry.py`
- `V4`: `P test_seat_codex_route_gate.py test_codex_seat_tool_sandbox_1335.py test_codex_seat_writable_tree_1470.py test_broker_staged_tree_delivery.py test_sandbox_egress.py`, then `P test_panel_invoker.py -k codex`
- `V5`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py`
- `V6`: `P test_seat_reference_inventory.py`, then `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_seat_codex_provider_free.py test_seat_egress_allowlist_codex.py -k live_jail --junitxml=<private-receipt>`, provider-free, on a host class with jail prerequisites. A skip or zero collection fails.
- `VM`: `PHASE_LOOP_CODEX_MEASURE=1 P test_seat_egress_allowlist_codex.py -k measured_turn --junitxml=<private-receipt>`, on a developer host with the developer's own login (principle 5). Not a window.
- Full suite: hosted CI and Gate A only.
