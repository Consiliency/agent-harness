"""The sandbox preamble is the seat-facing contract, and nothing was checking it.

It is a COMPLETE replacement for `_BROKER_REVIEW_SEALED_PREAMBLE`, not a patch: splicing
"...except inside the sandbox" onto a line that forbids "tools, commands, files, network"
would leave two clauses governing one capability and let the seat choose. That design is
stated in the docstring; until now no test held it, so a prohibition dropped during a
rewrite would have been silent.

Two properties, and the second is the one that bites: the grant must be accurate. A seat
told it has "the network" and then blocked from the tailnet spends its round diagnosing a
service outage and reports a confident, cited finding about infrastructure. What the seat
is told has to match what the namespace actually enforces.
"""

from __future__ import annotations

from pathlib import Path

from phase_loop_runtime import panel_invoker


STAGED = Path("/tmp/pl-panel-stage-xyz/reviewed-tree")


def _preamble() -> str:
    return panel_invoker._broker_review_sandbox_preamble(STAGED)


class TestItReplacesTheSealedPreambleRatherThanPatchingIt:
    def test_every_still_binding_prohibition_is_restated(self):
        """`network` and `files` are deliberately absent -- they are GRANTED here."""
        prohibited = ("browser", "MCP", "agents", "subagents", "memory",
                      "provider routing", "follow-up sessions")
        text = _preamble()
        missing = [word for word in prohibited if word not in text]
        assert not missing, (
            f"the sealed preamble forbids these and the sandbox preamble drops them: {missing}"
        )

    def test_the_frame_rule_and_the_verdict_rule_survive_the_replacement(self):
        text = _preamble()
        assert "AUTHORITATIVE INSTRUCTIONS" in text, "the injection boundary must survive"
        assert "AGREE, PARTIALLY AGREE, or DISAGREE" in text, "the verdict contract must survive"

    def test_no_capability_is_governed_by_two_clauses(self):
        """The sealed preamble's blanket ban must not appear alongside the grant."""
        text = _preamble()
        assert "Do not use or request tools, commands, files, network" not in text, (
            "the blanket ban and the grant would both govern commands and files"
        )


class TestTheGrantMatchesWhatIsEnforced:
    def test_the_seat_is_told_where_it_may_act(self):
        assert str(STAGED) in _preamble()

    def test_the_seat_is_told_the_private_network_is_denied(self):
        """Otherwise a denied connection reads as an outage worth reporting."""
        text = _preamble().lower()
        assert "public internet is reachable" in text
        for denied in ("rfc1918", "tailnet", "loopback", "cloud metadata"):
            assert denied in text, f"the seat is not told {denied} is denied"

    def test_what_the_seat_is_told_matches_the_policy_module(self):
        """Bind the prose to the executable policy, not to a second copy of the intent."""
        from phase_loop_runtime import sandbox_egress, sandbox_policy

        policy = sandbox_policy.egress_allowlist()
        assert not policy.allows("10.0.0.5", 443), "prose says RFC1918 denied"
        assert not policy.allows("100.84.171.76", 22), "prose says the tailnet denied"
        assert not policy.allows("127.0.0.1", 8080), "prose says loopback denied"
        assert not policy.allows("169.254.169.254", 80), "prose says metadata denied"
        assert policy.allows("140.82.121.4", 443), "prose says the public internet reachable"
        assert "127.0.0.0/8" in sandbox_egress.PRIVATE_CIDRS

    def test_the_seat_is_told_its_changes_reach_nobody(self):
        """The whole trust model in one line: experiment freely, it is disposable."""
        text = _preamble()
        assert "DISPOSABLE CLONE" in text
        assert "never a deliverable" in text
