# Detailed plan: PMCP prerequisite for scoped advisor research

## Target repository

`pmcp` (companion prerequisite for Consiliency/agent-harness#310). Execute this as
its own PMCP issue/PR and release before agent-harness enables research mode.

## Task

Add a fail-closed scoped-advisor gateway profile: explicit policy errors terminate,
gateway control tools are allowlisted, concurrent stdio instances isolate locks,
and invocation provenance is sufficient to prove each seat's research without
logging raw queries, credentials, or results.

## Changes

### `src/pmcp/policy/policy.py` (modify)

- When the operator supplies `--policy`/`PMCP_POLICY`, make missing, unreadable,
  malformed, or schema-invalid policy fatal. Default-location best-effort behavior
  may remain compatible only when no explicit policy was requested.
- Add `gateway_tools.allowlist`/`denylist` to the typed policy schema and enforce
  case-sensitive names.

### `src/pmcp/server.py` and `src/pmcp/tools/handlers.py` (modify)

- Filter both `list_tools` and `call_tool` through the gateway-tool policy. A
  denied control is absent from discovery and rejected before dispatch.
- The advisor policy exposes only health, catalog search, describe, and invoke;
  it excludes provision/auth/startup-policy/connect/disconnect/restart/update/
  cancel and task-control tools.
- Preserve downstream `tools.allowlist` enforcement so invoke accepts only
  `firecrawl::*` and `brightdata::*` read/search/scrape/query tools.

### Structured audit (modify/add existing audit module)

- Freeze `scoped_advisor_audit.v1` as newline-delimited JSON written to an explicit
  `--audit-jsonl <path>`/`PMCP_AUDIT_JSONL` sink. Add typed optional
  `run_correlation_id`, `seat_correlation_id`, and `evidence_label_digest` to
  `InvokeInput`; reject partial/malformed correlation fields in scoped mode.
- Emit `audit.started`, one `audit.invocation` per accepted or denied gateway
  invocation, and exactly one `audit.completed` containing sequence bounds and
  record count. Append and flush every record; fsync the terminal marker before
  PMCP exits so the consumer can prove completeness after child close.
- Each invocation record carries run correlation ID, seat
  correlation ID, gateway tool, downstream tool ID, terminal status, timestamp,
  policy digest, and redacted result digest.
- Add a privacy-safe evidence reference: normalized public source origin/URL hash
  plus caller-supplied evidence-label digest. Do not log the raw URL, query,
  arguments, credentials, or result body.
- This record is the trusted provenance channel; model-authored summaries cannot
  establish success.
- Advertise exact capability `scoped_advisor_audit.v1` only when fatal explicit
  policy, gateway-tool filtering, correlation inputs, JSONL sink, and terminal
  completeness are all active.

### `src/pmcp/cli.py` (modify if needed)

- Preserve `--lock-dir`; document that concurrent scoped stdio instances require
  unique directories. Expose capability/version metadata for fatal explicit
  policy, gateway-tool filtering, structured audit, and unique-lock support.

### Tests (modify/add)

- `tests/test_policy.py`: fatal explicit-policy errors and gateway-tool allowlist.
- `tests/test_server.py`/`test_tools.py`: filtered listing and denied dispatch.
- Add concurrent stdio instances with distinct lock dirs.
- Add audit privacy/provenance tests, including Firecrawl/Bright Data success,
  out-of-policy denial, and no raw URL/query/result/secret leakage.
- Test truncated/missing terminal markers, sequence gaps, duplicate completion,
  sink write failure, flush on termination, and correlation-schema rejection.

## Verification

```bash
pytest tests/test_policy.py tests/test_server.py tests/test_tools.py -q
pytest -q
```

`automation.suite_command`: `pytest -q`

## Acceptance criteria

- [ ] Explicit policy failure exits non-zero; permissive defaults are never retained.
- [ ] Gateway controls are filtered in discovery and dispatch.
- [ ] Invoke can reach only allowlisted Firecrawl/Bright Data research tools.
- [ ] Four concurrent stdio instances operate with unique lock dirs.
- [ ] Structured audit proves tool/status/policy/run/seat correlation and privacy-safe source evidence.
- [ ] `scoped_advisor_audit.v1` JSONL has explicit sink/config, typed correlation inputs, sequence/count completeness, and a flushed terminal marker.
- [ ] Audit contains no raw query, URL, arguments, credentials, or result body.
- [ ] A released capability/version probe lets agent-harness fail closed on older PMCP.
