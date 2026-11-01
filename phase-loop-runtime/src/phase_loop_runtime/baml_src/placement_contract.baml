// Shared placement contract and coordinator wire v1 (agent-harness#1792, agent-harness#1795 revision 6).
// policy is opaque JSON; no OpenShell policy internals are modeled.

enum TargetKind {
    local,
    openshell,
    e2b,
}

enum CapacitySource {
    gateway,
    config,
    host_probe,
}

enum AdmissionOutcome {
    admitted,
    at_capacity,
    refused,
    unreachable,
    timeout,
}

enum AdmissionReason {
    no_capacity,
    pressure,
    fairness_wait,
    reserved_for_other_client,
    recovering,
    telemetry_stale,
    slice_unbounded,
    untracked_vms,
    ledger_restored,
    internal,
}

enum Client {
    agent_harness @alias("agent-harness"),
    agent_toolkit @alias("agent-toolkit"),
}

enum ErrorCode {
    at_capacity,
    owner_mismatch,
    not_enrolled,
    unknown_lease,
    fenced,
    expired,
    lifetime_exceeded,
    digest_mismatch,
    duplicate_binding,
    snapshot_expired,
    invalid_request,
    workload_unsupported,
    deadline_exceeded,
    unavailable,
}

enum Workload {
    leg,
    qualification,
    implementation,
    pi_runner @alias("pi-runner"),
}

enum LeaseState {
    reserved,
    creating,
    ready,
    killing,
    destroyed,
    expired,
    tombstone,
}

enum RestartPolicy {
    never,
}

enum ServiceProtocol {
    tcp,
}

class PlacementTarget {
    name: string,
    kind: TargetKind,
    rank: int,
}

class Limits {
    max_ttl_s: int,
    max_extend_s: int,
    max_lifetime_s: int,
}

class CapacityReading {
    free: int?,
    ceiling: int?,
    source: CapacitySource,
    observed_at: string,
    limits: Limits?,
}

class TrailEntry {
    target: string,
    outcome: AdmissionOutcome,
    code: string,
    reason: AdmissionReason?,
}

class Ownership {
    owner: string,
    lease: string,
    client: Client,
}

class ErrorBody {
    code: ErrorCode,
    reason: AdmissionReason?,
    lease_id: string?,
}

class ServiceExposure {
    name: string,
    target_port: int,
    protocol: ServiceProtocol,
}

class CreateBody {
    image: string,
    policy: map<string, baml.json.json>,
    policy_digest: string,
    service_exposures: ServiceExposure[],
    restart_policy: RestartPolicy,
    providers: string[],
}

class LeaseFlags {
    reserved: bool,
    create_settled: bool,
    ready: bool,
    exec_claimed: bool,
    fenced: bool,
    destruction_observed: bool,
    cleanup_pending: bool,
    barrier_confirmed: bool,
    expired: bool,
}

class Binding {
    label_matches: int,
    duplicates: string[],
}

class LeaseStatus {
    lease_id: string,
    state: LeaseState,
    sandbox_id: string?,
    expires_at: string,
    flags: LeaseFlags,
    binding: Binding,
}

class InventoryPage {
    items: LeaseStatus[],
    next_page_token: string?,
    snapshot: string,
}

class InventoryQuery {
    page_size: int?,
    page_token: string?,
}

class DeadlineHeaders {
    X_Deadline_Ms: int @alias("X-Deadline-Ms"),
}
