# FABPUB: a routing client built before a partition rotation (agent-harness#1315)

## Probe result on main

`tests/test_fabpub_stale_client_1315.py` builds the client with
`build_routing_broker_client()`, publishes once so the client caches its stores
and its writer-generation lease, and then blocks the partition.

- While the client holds its lease, the rotation's drain counts the lease and the
  rotation refuses with `PartitionRotationRefused`. The latch keeps its nonce, so
  the client keeps working. This already passes on main.
- If the lease file was removed anyway (the runbook §6 deviation) and the
  rotation completed, the stale client wrote nothing and made no provider call.
  The refusal was still wrong in two ways:
  - A new head was refused by the retired generation's own block, with a plain
    `PermissionError("epoch permanently blocked")`. That tells the caller the
    partition is blocked when the operator has just rotated past the block.
  - A head the client had already published was answered as a replay from the
    retired generation's ledger.
  The cause: `_RepositoryRoutingBrokerService._service_for` returned the cached
  service without re-resolving the generation, and the `_stores_for` cache hit
  never compared the cached root with the ACTIVE one.

## Contract

The client refuses with a typed error and never rebinds itself. It cannot tell an
orphaned lease from a live one, and the rotation handoff already tells the
operator to restart broker processes.

## Change

- `_service_for` calls `_stores_for` on every request, before it looks in the
  service cache.
- On a cache hit, `_stores_for` raises `WriterGenerationBlocked` when the cached
  evidence root is not `snapshot.store_root`. The message names the retired
  generation, the ACTIVE generation and the restart.

Each check fails the probe when it is removed: the refusal falls back to
`epoch permanently blocked`.

## Out of scope

- The publishing handoff for this refusal (owned by Lane C). The human path builds
  and closes its own client on every call, so it never holds a stale one.
- Lease liveness (agent-harness#820).
