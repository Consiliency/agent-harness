// Source: phase_loop_runtime/baml_src/placement_contract.baml
// baml-cli: 0.23.0; sha256: 942b22ca7608753429e8908f1189d1cc93688775fd41eb1c249a4e675a7ac594
// Generated; do not edit.

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export const TargetKindValues = ["local", "openshell", "e2b"] as const;
export type TargetKind = "local" | "openshell" | "e2b";

export const CapacitySourceValues = ["gateway", "config", "host_probe"] as const;
export type CapacitySource = "gateway" | "config" | "host_probe";

export const AdmissionOutcomeValues = ["admitted", "at_capacity", "refused", "unreachable", "timeout"] as const;
export type AdmissionOutcome = "admitted" | "at_capacity" | "refused" | "unreachable" | "timeout";

export const AdmissionReasonValues = ["no_capacity", "pressure", "fairness_wait", "reserved_for_other_client", "recovering", "telemetry_stale", "slice_unbounded", "untracked_vms", "ledger_restored", "internal"] as const;
export type AdmissionReason = "no_capacity" | "pressure" | "fairness_wait" | "reserved_for_other_client" | "recovering" | "telemetry_stale" | "slice_unbounded" | "untracked_vms" | "ledger_restored" | "internal";

export const ClientValues = ["agent-harness", "agent-toolkit"] as const;
export type Client = "agent-harness" | "agent-toolkit";

export const ErrorCodeValues = ["at_capacity", "owner_mismatch", "not_enrolled", "unknown_lease", "fenced", "expired", "lifetime_exceeded", "digest_mismatch", "duplicate_binding", "snapshot_expired", "invalid_request", "workload_unsupported", "deadline_exceeded", "unavailable"] as const;
export type ErrorCode = "at_capacity" | "owner_mismatch" | "not_enrolled" | "unknown_lease" | "fenced" | "expired" | "lifetime_exceeded" | "digest_mismatch" | "duplicate_binding" | "snapshot_expired" | "invalid_request" | "workload_unsupported" | "deadline_exceeded" | "unavailable";

export const WorkloadValues = ["leg", "qualification", "implementation", "pi-runner"] as const;
export type Workload = "leg" | "qualification" | "implementation" | "pi-runner";

export const LeaseStateValues = ["reserved", "creating", "ready", "killing", "destroyed", "expired", "tombstone"] as const;
export type LeaseState = "reserved" | "creating" | "ready" | "killing" | "destroyed" | "expired" | "tombstone";

export const RestartPolicyValues = ["never"] as const;
export type RestartPolicy = "never";

export const ServiceProtocolValues = ["tcp"] as const;
export type ServiceProtocol = "tcp";

export interface PlacementTarget {
  "name": string;
  "kind": TargetKind;
  "rank": number;
}

export interface Limits {
  "max_ttl_s": number;
  "max_extend_s": number;
  "max_lifetime_s": number;
}

export interface CapacityReading {
  "free"?: number | null;
  "ceiling"?: number | null;
  "source": CapacitySource;
  "observed_at": string;
  "limits"?: Limits | null;
}

export interface TrailEntry {
  "target": string;
  "outcome": AdmissionOutcome;
  "code": string;
  "reason"?: AdmissionReason | null;
}

export interface Ownership {
  "owner": string;
  "lease": string;
  "client": Client;
}

export interface ErrorBody {
  "code": ErrorCode;
  "reason": AdmissionReason | null;
  "lease_id": string | null;
}

export interface ServiceExposure {
  "name": string;
  "target_port": number;
  "protocol": ServiceProtocol;
}

export interface CreateBody {
  "image": string;
  "policy": { [key: string]: JsonValue };
  "policy_digest": string;
  "service_exposures": ServiceExposure[];
  "restart_policy": RestartPolicy;
  "providers": string[];
}

export interface LeaseFlags {
  "reserved": boolean;
  "create_settled": boolean;
  "ready": boolean;
  "exec_claimed": boolean;
  "fenced": boolean;
  "destruction_observed": boolean;
  "cleanup_pending": boolean;
  "barrier_confirmed": boolean;
  "expired": boolean;
}

export interface Binding {
  "label_matches": number;
  "duplicates": string[];
}

export interface LeaseStatus {
  "lease_id": string;
  "state": LeaseState;
  "sandbox_id": string | null;
  "expires_at": string;
  "flags": LeaseFlags;
  "binding": Binding;
}

export interface InventoryPage {
  "items": LeaseStatus[];
  "next_page_token": string | null;
  "snapshot": string;
}

export interface InventoryQuery {
  "page_size"?: number | null;
  "page_token"?: string | null;
}

export interface DeadlineHeaders {
  "X-Deadline-Ms": number;
}
