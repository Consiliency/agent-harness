"""Opt-in live proof for one real board seat using PMCP 1.20.0 research."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from harden_tdd_guard import invoke_sanctioned_board_control
from phase_loop_runtime.advisor_board import Board, ResearchPolicy, Seat


@unittest.skipUnless(
    os.environ.get("PHASE_LOOP_LIVE_RESEARCH") == "1",
    "set PHASE_LOOP_LIVE_RESEARCH=1 to run the live subscription/MCP proof",
)
class LiveResearchProofTests(unittest.TestCase):
    def test_real_codex_seat_uses_both_research_servers_and_denies_mutation(self) -> None:
        prompt = """Run a governed research integration test using only the session-local
`pmcp_advisor` MCP server. Read the governed research section carefully and put its exact
run_correlation_id, seat_correlation_id, and evidence_label_digest at the TOP LEVEL of every
gateway.invoke call. Use catalog/describe first. Then:
1. Invoke `firecrawl::firecrawl_search` for `site:python.org latest Python release`.
2. Invoke `brightdata::scrape_as_markdown` for `https://www.python.org/downloads/`.
3. Invoke `github::create_issue` once with dummy title/body solely to prove policy denial;
   do not retry it and do not perform any mutation.
If either research provider has a transient failure, correct the arguments and retry that
provider at most once. Do not answer until both research calls succeeded and the denied
mutation was attempted. Include the exact required evidence label in the final answer and
end with a clear recommendation."""
        board = Board(
            name="live-governed-research",
            purpose="advisory",
            research_policy=ResearchPolicy(enabled=True),
            seats=(
                Seat(model="gpt-5.6-sol", effort="max", harness="codex"),
            ),
        )
        result = invoke_sanctioned_board_control(
            board,
            prompt,
            mode="advisory",
            timeouts_by_leg={"codex": 900},
        )
        leg = result.legs[0]
        self.assertEqual(leg.status, "OK", leg.detail)
        self.assertEqual(leg.research_status, "success")
        self.assertIsNotNone(leg.research_ledger)
        ledger = leg.research_ledger
        assert ledger is not None

        by_tool = {}
        for invocation in ledger.invocations:
            by_tool.setdefault(invocation.downstream_tool_id, []).append(invocation)
        for tool_id in (
            "firecrawl::firecrawl_search",
            "brightdata::scrape_as_markdown",
        ):
            self.assertTrue(
                any(
                    entry.terminal_status == "success"
                    and entry.claim_status == "verified"
                    and entry.source_reference_hash
                    for entry in by_tool.get(tool_id, [])
                ),
                f"missing verified live evidence for {tool_id}: {ledger.to_safe_dict()}",
            )
        self.assertTrue(
            any(
                entry.terminal_status == "denied"
                for entry in by_tool.get("github::create_issue", [])
            ),
            f"mutation denial missing: {ledger.to_safe_dict()}",
        )

        evidence = {
            "model": "gpt-5.6-sol",
            "seat_status": leg.status,
            "research_status": ledger.status,
            "policy_digest": ledger.policy_digest,
            "audit_digest": ledger.audit_digest,
            "ledger_digest": ledger.ledger_digest,
            "invocations": [entry.to_safe_dict() for entry in ledger.invocations],
        }
        serialized = json.dumps(evidence, indent=2, sort_keys=True)
        for forbidden in (
            "site:python.org",
            "latest Python release",
            "dummy title",
            "dummy body",
            "api_key",
            "authorization",
        ):
            self.assertNotIn(forbidden.lower(), serialized.lower())
        evidence_path = Path(
            os.environ.get(
                "PHASE_LOOP_LIVE_RESEARCH_EVIDENCE",
                "/tmp/agent-harness-310-advisor-research-live-evidence.json",
            )
        )
        evidence_path.write_text(serialized + "\n", encoding="utf-8")

    @unittest.skipUnless(
        os.environ.get("PHASE_LOOP_LIVE_RESEARCH_CLAUDE") == "1",
        "set PHASE_LOOP_LIVE_RESEARCH_CLAUDE=1 for the Claude TUI MCP proof",
    )
    def test_real_claude_tui_seat_can_use_session_local_pmcp(self) -> None:
        board = Board(
            name="live-claude-governed-research",
            purpose="advisory",
            research_policy=ResearchPolicy(enabled=True),
            seats=(
                Seat(model="claude-opus-5", effort="max", harness="claude"),
            ),
        )
        result = invoke_sanctioned_board_control(
            board,
            """Use only the session-local `pmcp_advisor` MCP server. Read the governed
research section and put its exact three correlation fields at the TOP LEVEL of every
gateway.invoke call. Discover the Firecrawl search tool, invoke it once for
`site:python.org Python downloads`, include the required evidence label, and recommend
whether the provider is operational. Do not use any other MCP server or mutation tool.""",
            mode="advisory",
            timeouts_by_leg={"claude": 900},
        )
        leg = result.legs[0]
        self.assertEqual(leg.status, "OK", leg.detail)
        self.assertEqual(leg.research_status, "success")
        self.assertIsNotNone(leg.research_ledger)
        ledger = leg.research_ledger
        assert ledger is not None
        self.assertTrue(
            any(
                entry.downstream_tool_id == "firecrawl::firecrawl_search"
                and entry.terminal_status == "success"
                and entry.claim_status == "verified"
                for entry in ledger.invocations
            ),
            ledger.to_safe_dict(),
        )


if __name__ == "__main__":
    unittest.main()
