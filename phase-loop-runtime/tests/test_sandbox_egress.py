"""Egress isolation: internet yes, your private network no.

Blanket network denial is the wrong boundary -- a panelist needs to search, read docs and
install what a check requires. What must stay unreachable is everything INSIDE: the rest of
the tailnet, loopback services (the review broker among them), the docker bridges, and cloud
metadata.

Measured on this host before building it, so the design is not theoretical:

    public 1.1.1.1    -> 301      reachable
    ai:8020 router    -> 200      reachable (allowlisted by host AND port)
    ai:6333 qdrant    -> BLOCKED  ~69 GB of user data on the same machine
    169.254.169.254   -> BLOCKED  cloud metadata / credential theft target

The enforcement is a user namespace: inside one we hold NET_ADMIN, so the rules are real
rather than advisory, and no privilege is needed outside. That matters because the honest
alternative -- proxy environment variables -- is opt-in by the program and a speed bump
rather than a wall.
"""

from __future__ import annotations

import shutil

import pytest

from phase_loop_runtime import sandbox_egress, sandbox_policy


class TestRuleGeneration:
    def test_the_allowlist_precedes_the_denies(self):
        """Order is the whole policy: a deny for 100.64/10 would otherwise eat ai:8020."""
        rules = sandbox_egress.egress_rules(sandbox_policy.egress_allowlist())
        first_allow = next(i for i, r in enumerate(rules) if "8020" in r)
        first_private_deny = next(i for i, r in enumerate(rules) if "100.64.0.0/10" in r)
        assert first_allow < first_private_deny

    def test_every_private_range_is_denied(self):
        rules = " ".join(sandbox_egress.egress_rules(sandbox_policy.egress_allowlist()))
        for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                     "100.64.0.0/10", "169.254.0.0/16", "127.0.0.0/8"):
            assert cidr in rules, f"{cidr} must be denied"

    def test_the_uplink_subnet_is_re_allowed(self):
        """slirp's own 10.0.2.0/24 sits inside 10/8; denying it kills all networking."""
        rules = sandbox_egress.egress_rules(sandbox_policy.egress_allowlist())
        uplink = [i for i, r in enumerate(rules) if "10.0.2.0/24" in r and "ACCEPT" in r]
        deny_10 = next(i for i, r in enumerate(rules) if "10.0.0.0/8" in r)
        assert uplink and uplink[0] < deny_10, "the uplink must be allowed before 10/8 is denied"

    def test_allowlisted_endpoints_are_bound_to_a_port(self):
        """Allowlisting the HOST would expose qdrant, file_browser, NFS and ssh with it."""
        for rule in sandbox_egress.egress_rules(sandbox_policy.egress_allowlist()):
            if "ACCEPT" in rule and "100.84.171.76" in rule:
                assert "--dport" in rule, f"host-wide allow: {rule}"


class TestCapabilityDeclaration:
    def test_a_sandbox_declares_what_it_actually_enforced(self):
        report = sandbox_egress.enforcement_report(available=True, applied=True)
        assert report["network_filtered"] is True
        assert report["mechanism"] == "user-namespace+slirp4netns"

    def test_an_unavailable_mechanism_is_declared_not_assumed(self):
        """A sandbox claiming filtering it cannot deliver is a fail-open in the record."""
        report = sandbox_egress.enforcement_report(available=False)
        assert report["network_filtered"] is False
        assert report["reason"], "it must say WHY, not just report false"

    def test_refuse_is_the_default_when_filtering_is_required_but_unavailable(self):
        with pytest.raises(sandbox_egress.EgressUnavailable):
            sandbox_egress.require_egress_isolation(available=False)


@pytest.mark.skipif(
    shutil.which("slirp4netns") is None or shutil.which("unshare") is None,
    reason="needs unshare + slirp4netns (Linux)",
)
class TestRealEnforcement:
    def test_the_policy_is_enforced_for_real(self):
        """The load-bearing test: run it, do not assert the rule text and call it done."""
        if not sandbox_egress.egress_isolation_available():
            pytest.skip("user namespaces unavailable on this host")

        probe = (
            'echo "public=$(timeout 6 curl -s -o /dev/null -w %{http_code} --max-time 5 '
            'https://1.1.1.1 2>/dev/null || echo BLOCKED)";'
            'echo "private=$(timeout 6 curl -s -o /dev/null -w %{http_code} --max-time 5 '
            'http://100.84.171.76:6333/collections 2>/dev/null || echo BLOCKED)"'
        )
        out = sandbox_egress.run_in_isolated_network(probe, timeout_s=45)
        assert "public=301" in out or "public=200" in out, f"internet must work:\n{out}"
        assert "private=BLOCKED" in out or "private=000" in out, (
            f"private space must NOT be reachable:\n{out}"
        )


class TestEvidenceRecording:
    def test_the_enforcement_report_reaches_the_leg_evidence(self):
        """pyflakes caught this: the report was computed and discarded.

        A value that is calculated and never recorded is indistinguishable, from the
        outside, from one that was never calculated -- and the commit message claimed it
        was recorded. The lint finding was a real defect, not noise.
        """
        from phase_loop_runtime import panel_invoker, sandbox_policy

        choice = sandbox_policy.SandboxRootChoice(
            host="ai", path=__import__("pathlib").Path("/storage/sb"),
            fell_back=True, reason="ai unreachable within 5.0s",
        )
        panel_invoker._record_sandbox_facts(
            choice, sandbox_egress.enforcement_report(True, applied=True)
        )
        recorded = panel_invoker._sandbox_evidence()

        assert recorded["sandbox_root_host"] == "ai"
        assert recorded["sandbox_root_fell_back"] is True
        assert "unreachable" in recorded["sandbox_root_reason"]
        assert recorded["sandbox_network_filtered"] is True
        assert recorded["sandbox_network_mechanism"] == "user-namespace+slirp4netns"

    def test_unenforced_egress_is_recorded_as_unenforced_with_a_reason(self):
        from phase_loop_runtime import panel_invoker, sandbox_policy

        choice = sandbox_policy.SandboxRootChoice(
            host=None, path=__import__("pathlib").Path("/tmp"), fell_back=False,
        )
        panel_invoker._record_sandbox_facts(choice, sandbox_egress.enforcement_report(False))
        recorded = panel_invoker._sandbox_evidence()

        assert recorded["sandbox_network_filtered"] is False
        assert recorded["sandbox_network_unfiltered_reason"], (
            "a seat that was NOT isolated must say so, and say why"
        )


class TestTheReportCannotClaimUnappliedFiltering:
    """Board round 2, BLOCKING: the filtering was never applied to a provider launch.

    `enforcement_report()` was wired into the leg evidence and `run_in_isolated_network`
    was never called from `panel_invoker`. So a seat's record said
    `sandbox_network_filtered=True` while nothing restricted that seat -- the exact
    fail-open this module exists to prevent, inside the module that prevents it.
    """

    def test_available_but_unapplied_is_reported_as_NOT_filtered(self):
        report = sandbox_egress.enforcement_report(available=True)
        assert report["network_filtered"] is False
        assert report["available_but_unapplied"] is True
        assert "does not yet run through it" in report["reason"]

    def test_only_an_applied_launch_may_claim_filtering(self):
        report = sandbox_egress.enforcement_report(available=True, applied=True)
        assert report["network_filtered"] is True

    def test_panel_invoker_does_not_claim_filtering_it_did_not_apply(self):
        """Guard the wiring itself: if a launch path starts applying isolation, it must
        pass `applied=True` deliberately rather than inherit a true-by-default."""
        from pathlib import Path as _P
        import phase_loop_runtime.panel_invoker as pi
        source = _P(pi.__file__).read_text(encoding="utf-8")
        if "run_in_isolated_network" not in source:
            assert "applied=True" not in source, (
                "the evidence claims applied filtering while no launch routes through it"
            )
