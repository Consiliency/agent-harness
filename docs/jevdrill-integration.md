# Discovery-aware JEV Drill integration

Explicit JevDrillAdapter integration is default-disabled and serial. run_loop,
launch_delegated_child and launch_harness_lane_work_unit preserve their existing
request/spec constructors and launch authority. There is no concurrent dispatcher.

discover_objective(inputs, started_at=None) calls the separately installed CLI,
validates DiscoveryResult and permits only selected_guidance/no_optional_guidance.
runner.discover_jevdrill_work_units calls the trusted ordinary planning callback
with transient returned instructions, parses its lane plan and constructs stable
task IDs. The callback owns its normal planning budget and permissions. Drill
never creates task lists. inputs_for supplies strict DiscoveryRouteInputs for
bound tasks; unbound v1 compatibility remains explicit.

The trusted callbacks verify candidate identities, enforce whole-run requested
limits, intersect configured/runtime permissions and optionally decline a
recommendation. Retaining a model requires narrowing the offered inventory or
preserving an explicit selection override; applied identities are never rewritten.
Task prompts remain immutable. Optional instructions inject once; reused prepared
prompts unwrap to their base, and execution reports guidance deactivation.

The same private ReportQueue stores only opaque discovery/task/run binding
metadata and permanent cross-producer objective tombstones. Each lifecycle
operation takes a cross-process lock before binding, preparation, final launch or
deletion. Deletion commits locally before CLI transport and survives lost replies.
Final launch rechecks installed inspect-discovery, exact reference and current
authorized catalog/revisions. Objective deletion keeps task reports independent.
Already-running work completes before a waiting deletion; bounded lock acquisition
can time out and needs caller retry. This does not promise cancellation of work.

Discover/route/report and attached notices have separate spawn-inclusive five
second logical operation budgets and 1,000,000-byte bounds. Canceled children are
killed and reaped. Recursion bypass returns before lifecycle locks/provider traffic.
One bounded queue serves all reports, sanitizes before SQLite/journal writes and
removes only matching durable accepted/duplicate event acknowledgments.

Schema/fixture digests bind the upstream HOST handoff. Native Windows argv uses
the installed JEV interpreter with -m jevdrill.cli; no unsigned launcher policy
change occurs. macOS ordinary execution stays local; JD-084 leased rejection and
Linux supervisor cleanup remain intact. Separate native receipts and independent
synthetic artifacts are software conformance evidence; no model quality,
effectiveness, savings, adoption, promotion or live-provider claim follows.

Codex usage/input capture remains Linux-only. Native macOS and Windows controls
enter launch_with_spec and record disabled/unknown provenance; Linux retains the
full observer regression suites. Imported module hashes bind each installed
companion interpreter to the collected source.
