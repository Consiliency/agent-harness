# Settings amendment to placement-driver hardening (agent-harness#1504)

This records the Unit B tunables amendment authorized by the 2026-10-18 r3
president plan ruling. It accompanies the implementation for actual-source review;
it is not implementation acceptance or an offload-readiness claim.

The originating plan is `plans/detailed-placement-driver-hardening-1504-20261012.md`
at agent-harness#1556, input commit `dc34fea120b94b426aa98a71048ec0585a3000f1`,
SHA-256 `46b6c610a5db14f8b84f9e2258d72719813417193b19c973be350c1fe7624a63`.
That historical plan and its checkout remain intact. This additive amendment is
submitted with the repair through the existing review and governance route.

The worker bound is configurable per existing call group, rather than a fixed
internal constant. The sole defaults authority is packaged
`advisor_board/fixtures/placement-driver.defaults.toml`. The existing user and
explicit repository `advisor-boards.toml` files may override only the driver keys
`admit_wait_s`, `transfer_allowance_s`, and `max_live_workers` in `[sandbox.driver]`.
The existing duration environment aliases take final precedence. No worker
environment alias or second configuration service is introduced.

Repository authority does not extend to roots, order, endpoints, authentication,
egress, enablement or last-rung selection. Review-base loading uses trusted
committed controls. Every participating layer is validated, including shadowed
values; blank overrides inherit. Missing or corrupt packaged defaults and
malformed overrides fail with input-free `sandbox_config_invalid`.

Before future review launch-site activation, any caller resolving settings with
the reviewed candidate as `repo_dir` must pass `review_base=True`, so the candidate
cannot tune its own review durations or worker bound. This is an obligation for
the activation/workload lane; no launch-site wiring or activation is added here.

Durations accept non-bool integers and signed ASCII decimal strings, clamp
negatives to zero, and saturate positive magnitudes lexically at half the platform
thread timeout maximum. Worker limits are positive non-bool integers within
`sys.maxsize`. An immutable resolved snapshot supplies lifetime arithmetic,
placement, and its result/renewal groups.

All live workers hold capacity until actual exit, including abandoned workers.
Startup failure rolls back its permit. Local readiness refusal precedes probe
and lease allocation and preserves C7 fallback and the capacity bar. There is no
extra cleanup allowance. C7 tables, workload gates and the disabled nonlocal
driver flag are unchanged; C6 remains owned by the separate cancellation lane.

Narrow and broader controls, settings-authority mutation evidence, lint and Gate A
are implementation evidence only. Original full/live acceptance, independent
actual-source review, president ruling, exact-head hosted checks and postmerge
proof remain required. No endpoint activation, push, merge or provider use is
authorized by this amendment.
