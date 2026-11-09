# Disabled OpenShell coordinator and stock exec transport

This path is retained for existing links. The private cancellation-lease SDK and
source-RPC recipe are retired by OSCOORD2 SL-4 (agent-harness#1795). Current source
uses the coordinator v1 HTTPS JSON contract and stock NVIDIA/OpenShell v0.1.4
`ExecSandbox`. Nothing registers the backend; `_NONLOCAL_EXECUTION_DRIVER` stays
false. Offline evidence does not authorize enrollment, deployment or activation.

## Responsibilities and evidence

- **Coordinator (ai-stack):** authenticated owner CN and client OU authority,
  capacity reservation, create/renew/kill, immutable label-backed sandbox binding,
  duplicate destruction, durable fences, reclaim records and complete snapshot
  inventories. Clients never call stock create/delete/start/stop/suspend/resume.
  Kill's destruction barrier must cover every matching sandbox and unsettled
  create. A successful HTTP reply or terminal display state alone is insufficient.
- **Client (agent-harness):** explicit CA/client certificate/key with
  `OU=agent-harness`, local-owner binding, fixed caller allowance and
  `X-Deadline-Ms`, durable lease UUID and attempt markers before effects, one stock
  exec with deterministic request_id, and no retry/reconnect/replay after dispatch.
  Recovery grants cleanup authority only. Release requires both the coordinator
  barrier and complete inventory proving absence or terminality. Uncertain held
  operations reconcile status → kill → barrier → complete inventory, with no
  overflow. Cancellation invalidates racing results; they cannot be imported.
- **Stock OpenShell v0.1.4:** sandbox execution and outer policy enforcement.
  Streaming exec is not intercepted; sandbox destruction is its fence.
  `exec_claimed` is client evidence, not an atomic stock claim/fence or runtime
  attestation. Stock does not enforce the client's inner read-only projection.
- **Worker/client inner restriction:** one bounded stdin envelope carries sealed
  metadata, source/dependency manifests and verified content. Load as uid 10001,
  probe guest Landlock ABI 3–8, then shared `landlock-exec` applies restrictions
  before agent exec. Failures exit 126 without agent launch. Records say
  `read_only_enforced_by: client-landlock`, with policy digest and restricted roots.
  No subsequent exec, upload or SSH session may run agent work outside that tree.
  Quarantined output still needs native validation, isolated same-base client
  retest and owner acceptance; worker echoes are not runtime attestation.

Outer stock `SandboxPolicy` uses original snake_case message field names, no
unknown fields, and unchanged user-named map keys. Its exact document is RFC 8785
JCS-digested. The review-runner uses the checked-in `full-remote-pi-runner` policy
verbatim, `hard_requirement`, no providers or service exposures, and restart never.
The image supplies `/work` (10001:10001, 0700); per-run mappings live below it.
Nonexistent workload paths are skipped by stock, so per-run leaves must never be
outer-policy entries. Empty policy does not prove no egress.

`placement_lease`, `lease_store` and `lease_supervisor` remain: dispatch journals,
path-set leases and process supervision have separate duties. Genuine fork-era
journal entries refuse backend startup without erasure or remote calls; deliberate
operator cleanup is required. Malformed/incomplete entries retain cleanup debt.
The deferred journal hardening below remains an activation gate.

## Stock provenance (identity, not qualification)

Upstream authority: [NVIDIA/OpenShell v0.1.4](https://github.com/NVIDIA/OpenShell/tree/v0.1.4),
commit `5a7728c304b5528e954e9ae900cf21f84e1a12b1`.
`proto/openshell.proto` defines exec; `proto/datamodel.proto` defines the workspace
selector; `proto/sandbox.proto` defines stock policy. These are Apache-2.0 NVIDIA
sources. The retained descriptor in `tests/_openshell_channel_server.py` records
NVIDIA copyright and license attribution.

SL-1 generated a descriptor set with grpcio-tools **1.78.0** (`protoc
--include_imports --descriptor_set_out=stock.pb`), retaining unmodified exec
messages/method and WorkspaceSelector. Reserved request field 5, `request_id`
field 11 and `execution_timeout` field 105 remain. `stock_bindings()` loads this
checked-in subset into a fresh protobuf descriptor pool, using the installed
`google.protobuf.duration_pb2` and dynamic message factory. It is a test fixture,
not a full SDK, generated production client or proof of upstream runtime behavior.
The gRPC tests register only `/openshell.v1.OpenShell/ExecSandbox` locally.

SL-1's recorded generator/runtime combination was grpcio/grpcio-tools 1.78.0 and
protobuf 6.33.6 (agent-harness#1809). The ordinary test environment's dependency
authority is `pyproject.toml` plus `uv.lock`; grpcio is an explicit optional test
prerequisite, not an activated production SDK dependency. `rfc8785==0.1.4` supplies
policy canonicalization. This replaces the fork manifest's qualification claim;
there is no current SDK qualification command or receipt generator.

The review-runner Containerfile separately pins its Python image by digest,
shared Consiliency/agent-toolkit helper commit
`d945fdd060aab9ad9471845f4f8e78406a0ac841`, BUILD.lock, toolchain and helper hashes,
and rfc8785 wheel hash. See agent-harness#1813 for local network-disabled container
evidence. Its default entrypoint reaches restriction then refuses with
`isolation_adapter_unavailable`: no production adapter/provider is supplied.

## Offline regression recipe

Use Python 3.12, `uv`, and `openssl`. Initial dependency installation needs package
access; the tests use synthetic credentials, in-process models and ephemeral
loopback mTLS only. They never contact live coordinator/proxy endpoints.

```sh
umask 0022
export TMPDIR="$HOME/workspace/tmp"
mkdir -p "$TMPDIR"
uv sync --project phase-loop-runtime --group test --extra visual --locked --python 3.12
uv pip install --python phase-loop-runtime/.venv/bin/python 'grpcio==1.78.0'
export PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests"
timeout 900 phase-loop-runtime/.venv/bin/python -m pytest -q -p no:cacheprovider \
  phase-loop-runtime/tests/test_openshell*.py \
  phase-loop-runtime/tests/test_placement_contract.py \
  phase-loop-runtime/tests/test_seat_reference_inventory.py \
  phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py
```

No private checkout, generated-SDK environment variable or qualification plugin is
needed. The retained provenance test guards retirement and stock descriptor wire
identity. Transport/channel/gRPC tests cover bounded streams, cancellation,
silence, dropped replies, caps, mTLS failures and single dispatch. Backend/journal
tests cover durable markers, crash recovery and barrier-plus-inventory release;
worker tests cover digest/manifest/load failures and restrict-before-exec. Real
helper and local-image tests are explicitly opt-in; ordinary skips do not prove
guest enforcement. These checks establish offline behavior, not live qualification.

## Remaining activation evidence and authority

All gates remain open until independently evidenced:

- Owner-run live qualification: actual stock guest/outer-policy isolation,
  no network egress or providers, physical destruction and no late start, fixed
  ends, authenticated ownership, credential handling, reconciliation and recovery.
- ai-stack **Unit 7** deployment and its live integration evidence.
- Owner-qualified policy documents and flipping agent-harness#1805 vectors from
  `pending_qualification`; candidate vectors alone authorize offline tests only.
- Production IsolatedRuntime adapter, provider executable in the review-runner
  image, and authenticated dependency projections (agent-harness#1787).
- Image build/push by digest, signing and ai-stack allowlist; local builds are not
  published or qualified images.
- Explicit certificates, endpoint SAN/CA issuance evidence, enrollment and tailnet
  grants; TLS readiness alone is not authorization.
- agent-harness#1808: bound abandoned local-release workers before local hooks
  are wired; agent-harness#1810: resolve stock exec SAN/CN verification before
  enabling the channel; agent-harness#1812: journal hardening before activation.
- Registration and launch-site wiring, then the `_NONLOCAL_EXECUTION_DRIVER`
  flip: **owner approval after a board review**, only after every prerequisite.
  The lead coordinates and reports; ai-stack owns deployment; the owner owns live
  qualification and activation approval. This lane performs none of those actions.

## Historical receipts

`plans/evidence/openshell-cancellation/CONFORMANCE.md` and its neighboring receipts
remain historical fork-era evidence. They are not current coordinator/stock
conformance. The patched manifest, qualification executable/plugin and private
source publication recipe are retired; Git history preserves their exact bytes.
No historical pin is an executable dependency or current qualification authority.
