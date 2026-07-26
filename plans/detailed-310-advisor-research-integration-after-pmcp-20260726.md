# Detailed plan: integrate version-pinned scoped PMCP research into advisor boards

## Task

After `detailed-310-pmcp-scoped-advisor-prerequisite-20260726.md` is released,
add opt-in per-seat Firecrawl/Bright Data research to agent-harness. This plan is
blocked until the PMCP capability probe passes; it must not partially enable an
ambient or older gateway.

## Changes

### `advisor_board/schema.py` (modify)

- Add frozen `ResearchPolicy` to `Board`, default disabled. It is the single
  effective policy source for `invoke_board`.
- `PanelRequest` may carry the same policy for legacy `invoke_panel_request`;
  `invoke_panel` gains one additive keyword-only policy parameter. A request and
  board/argument mismatch is a config-time error—never precedence by accident.
- Validate shipped policy to exact servers `firecrawl`, `brightdata`, allowed
  read/search/scrape/query globs, audit required, and all-seats-capable behavior.

### `advisor_board/research.py` (add) and `panel_invoker.py` (modify)

- Require the exact released PMCP `scoped_advisor_audit.v1` capability/version
  before materialization; reject older or partially advertised gateways.
- Generate immutable run-local policy/config and unique per-seat `--lock-dir`,
  correlation IDs, and audit output paths inside staged board state.
- Inject only strict session-local config into Claude TUI, Codex, Grok, and agy.
  If a client cannot prove isolation, return
  `UNAVAILABLE/research_profile_unenforceable`; never inherit ambient PMCP.
- Keep each review workspace staged/read-only and expose only PMCP health/catalog/
  describe/invoke plus that client's existing read tools.
- Attach research status/ledger digest as non-dataclass state with read-only
  properties, following `_needs_native_agent`; legacy `asdict`/field serializers
  must not gain keys when research is disabled. Reduce the attached ledger from
  PMCP audit records. Join a
  model-authored citation/evidence label only by matching correlation/tool/status
  and privacy-safe source hash; unmatched claims are `unverified`, never success.
- Accept audit evidence only after child close and a matching `audit.completed`
  marker with contiguous sequence/count, run/seat IDs, and policy digest. Missing,
  truncated, duplicated, or mismatched JSONL is a failed research seat.
- Record failed, denied, cancelled, and unavailable calls truthfully; telemetry
  carries only ledger/audit digests and status.

### Tests and docs (modify/add)

- Extend `test_panel_invoker_spawn.py`, `test_review_leg_sandbox.py`,
  `test_advisor_board_integration.py`, `test_advisor_board_observability.py`, and
  `test_advisor_board_backcompat.py`.
- Prove disabled byte compatibility, single-policy mismatch rejection, exact
  config on both board and legacy request paths, four unique lock dirs, mutation
  denial, audit-derived evidence, and fail-closed old-PMCP/agy-unenforceable paths.
- Include exact `asdict`/serializer regression coverage for disabled/unattached
  research metadata.
- Add `tests/test_advisor_board_live_research.py` behind an explicit
  `PHASE_LOOP_LIVE_RESEARCH=1` marker. It must launch the real version-pinned PMCP
  and one real board run, require successful Firecrawl and Bright Data calls from
  a research seat, require matching complete audit evidence for both, attempt and
  observe denial of one mutation/control call, and write a redacted
  `advisor-research-live-evidence.json` artifact with model, tool IDs, statuses,
  policy/audit digests, and no raw query/result/credentials.
- Update advisor-board docs/skills and regenerate bundles.

## Dependencies and order

1. Released PMCP prerequisite with passing capability probe.
2. Freeze one effective policy contract and legacy threading.
3. Materialize/inject per-seat config.
4. Reduce audit-derived ledgers.
5. Verify adapters, observability, docs, and generated skills.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest \
  tests/test_panel_invoker_spawn.py tests/test_review_leg_sandbox.py \
  tests/test_advisor_board_integration.py tests/test_advisor_board_observability.py \
  tests/test_advisor_board_backcompat.py -q
PHASE_LOOP_LIVE_RESEARCH=1 PYTHONPATH=src:tests python -m pytest \
  tests/test_advisor_board_live_research.py -q
```

`automation.suite_command`: `cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest tests/test_panel_invoker_spawn.py tests/test_review_leg_sandbox.py tests/test_advisor_board_integration.py tests/test_advisor_board_observability.py tests/test_advisor_board_backcompat.py -q`

## Acceptance criteria

- [x] Research stays disabled on unsupported/older PMCP.
- [x] One effective policy governs board and legacy request paths; mismatches fail closed.
- [x] Every capable seat uses strict session-local PMCP and a unique lock/audit directory.
- [x] Only Firecrawl/Bright Data research tools are callable; mutation/control tools are absent or denied.
- [x] Ledger success is derived from correlated PMCP audit evidence, not seat prose.
- [x] A real version-pinned board+PMCP smoke proves successful Firecrawl and Bright Data calls plus denied mutation in one evidence artifact.
- [x] Unenforceable clients and failed/cancelled/denied calls remain explicit failures.
- [x] Disabled boards remain byte-compatible.

## Exact-head reconciliation addendum

The final implementation also materializes highest-precedence run-local provider
definitions and a final PMCP manifest overlay for exactly Firecrawl and Bright Data,
passes both paths explicitly, and removes every inherited `PMCP_*` control. Claude
research seats omit MCP-disabling safe mode, disable the Chrome integration, and keep
the strict MCP/tool allowlists on the existing first-party subscription TUI route.
Regression coverage proves a pre-existing caller directory survives failed
materialization. Live subscription proofs passed for both Codex and Claude TUI.
The final dissent repair also withholds the live repository add-directory from a
research-enabled Claude seat and makes any mismatched invocation correlation fail
the whole research ledger, even when another invocation verified successfully.
