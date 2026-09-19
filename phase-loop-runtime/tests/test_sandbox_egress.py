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
from pathlib import Path

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
        # Through `isolated_network` -- the context manager the LAUNCH PATH uses -- not
        # the retired `run_in_isolated_network`, which had no production caller and was
        # deleted in board round 6. Testing enforcement through a mechanism nothing
        # launches through proves the policy, never the product.
        import subprocess as sp

        with sandbox_egress.isolated_network(timeout_s=60.0) as prefix:
            assert prefix, "isolation must be in force for this test to mean anything"
            out = sp.run(
                [*prefix, "bash", "-c", probe],
                capture_output=True, text=True, timeout=60,
            ).stdout

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
            choice, sandbox_egress.enforcement_report(True, applied=True),
            staged_at=Path("/tmp/pl-panel-test/reviewed-tree"),
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
        panel_invoker._record_sandbox_facts(
            choice, sandbox_egress.enforcement_report(False),
            staged_at=Path("/tmp/pl-panel-test/reviewed-tree"),
        )
        recorded = panel_invoker._sandbox_evidence()

        assert recorded["sandbox_network_filtered"] is False
        assert recorded["sandbox_network_unfiltered_reason"], (
            "a seat that was NOT isolated must say so, and say why"
        )


class TestTheReportCannotClaimUnappliedFiltering:
    """Board round 2, BLOCKING: the filtering was never applied to a provider launch.

    `enforcement_report()` was wired into the leg evidence and the isolation helper
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

    def test_the_evidence_claims_filtering_only_where_a_namespace_is_held(self):
        """Guard the wiring: `applied=` may only be reported where isolation is held open.

        The original defect was that the report was computed and recorded while no launch
        routed through a namespace. This fails if that ever becomes true again -- including
        by someone deleting the context manager and leaving the claim behind.
        """
        from pathlib import Path as _P
        import phase_loop_runtime.panel_invoker as pi
        source = _P(pi.__file__).read_text(encoding="utf-8")
        if "applied=" in source:
            assert "isolated_network(" in source, (
                "the evidence claims applied filtering while no namespace is opened"
            )
            assert "_EGRESS_LAUNCH_PREFIX.get()" in source, (
                "a namespace is opened but the spawn does not launch inside it"
            )


@pytest.mark.skipif(
    shutil.which("slirp4netns") is None or shutil.which("unshare") is None,
    reason="needs unshare + slirp4netns (Linux)",
)
class TestTheLaunchSeamIsActuallyIsolated:
    """The fix for the round-2 blocking finding, tested where it matters.

    `isolated_network()` yields an argv prefix; the shared leg spawn prepends it. So the
    provider lands INSIDE the namespace rather than beside it. Asserting the prefix exists
    proves nothing -- these run a real process through the real seam.
    """

    def test_a_process_launched_through_the_seam_is_filtered(self):
        import subprocess as sp
        from phase_loop_runtime import panel_invoker, sandbox_egress as se

        if not se.egress_isolation_available():
            pytest.skip("user namespaces unavailable")

        with se.isolated_network() as prefix:
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
            try:
                launched = [*panel_invoker._EGRESS_LAUNCH_PREFIX.get(), "bash", "-c",
                            'timeout 6 curl -s -o /dev/null -w %{http_code} --max-time 5 '
                            'http://100.84.171.76:6333/collections || echo BLOCKED']
                private = sp.run(launched, capture_output=True, text=True, timeout=40).stdout
                launched_pub = [*panel_invoker._EGRESS_LAUNCH_PREFIX.get(), "bash", "-c",
                                'timeout 6 curl -s -o /dev/null -w %{http_code} --max-time 5 '
                                'https://1.1.1.1 || echo BLOCKED']
                public = sp.run(launched_pub, capture_output=True, text=True, timeout=40).stdout
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)

        assert "BLOCKED" in private or "000" in private, (
            f"a launched process reached private space: {private!r}"
        )
        assert "301" in public or "200" in public, f"the internet must work: {public!r}"

    def test_without_a_held_namespace_the_seam_adds_nothing(self):
        """Byte-identical spawn when no sandbox is in use."""
        from phase_loop_runtime import panel_invoker
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()


def test_the_unavailable_path_warns_instead_of_crashing(monkeypatch):
    """Ruff caught `warnings` unimported: the unavailable branch would have raised
    NameError instead of warning, and every test exercised only the AVAILABLE path
    because this host has user namespaces. A host without them would have crashed.

    This is now the BEST-EFFORT posture (`required=False`); the default refuses. See
    :class:`TestItFailsClosed`.
    """
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)
    with pytest.warns(RuntimeWarning, match="refusing to launch WITHOUT"):
        with sandbox_egress.isolated_network(required=False) as prefix:
            assert prefix == (), "no isolation means no prefix, not a crash"


class TestItFailsClosed:
    """Round 4, the finding that ended the board: honest evidence, open execution.

    Round 2 claimed filtering that was never applied. Round 3 let a PARTIAL install claim
    `applied`. Round 4 recorded truthfully -- `network_filtered=False` -- and launched the
    seat completely unrestricted anyway. Three rounds of fixing the reported symptom and
    reproducing the property, because the record was treated as the boundary.

    `isolated_network` has THREE ways to fail, and all three used to `yield ()`. A
    caller-side `require_egress_isolation()` guards only the first, which is why the
    decision now lives in the module that owns the policy.
    """

    def test_the_default_refuses_when_the_mechanism_is_absent(self, monkeypatch):
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
        monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)
        with pytest.raises(sandbox_egress.EgressUnavailable, match="unavailable"):
            with sandbox_egress.isolated_network():
                pytest.fail("the body must never run unisolated")

    def test_a_namespace_that_never_comes_up_refuses(self, monkeypatch):
        """Failure two of three: the mechanism exists and the namespace does not appear."""
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
        monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)
        monkeypatch.setattr(sandbox_egress.os.path, "exists", lambda _p: False)

        class _Dead:
            def terminate(self): pass

        monkeypatch.setattr(sandbox_egress.subprocess, "Popen", lambda *a, **k: _Dead())
        with pytest.raises(sandbox_egress.EgressUnavailable, match="did not come up"):
            with sandbox_egress.isolated_network(timeout_s=1.0):
                pytest.fail("the body must never run unisolated")

    def test_rules_that_fail_to_install_refuse(self, monkeypatch):
        """Failure three, and the worst: the namespace is up, so everything LOOKS
        isolated while specific denies are missing.

        Everything outside the branch under test is stubbed. An earlier version of this
        test needed a REAL namespace and skipped on `which(slirp4netns)`, which meant it
        silently tested nothing in a container where the binaries exist but namespaces are
        denied -- and then failed there, in Gate A, for the wrong reason: it reached the
        "did not come up" branch instead of the rule-install branch it names.
        """
        import subprocess as sp
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
        monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)

        class _Holder:
            def __init__(self, *a, **k):
                pass

            def terminate(self):
                pass

        # Bring the namespace "up" without one: the readiness file and pid the context
        # manager polls for are the only things it needs from `unshare`/`slirp4netns`.
        real_exists = sandbox_egress.os.path.exists
        monkeypatch.setattr(sandbox_egress.subprocess, "Popen", _Holder)
        monkeypatch.setattr(
            sandbox_egress.os.path, "exists",
            lambda pth: True if str(pth).endswith("ready") else real_exists(pth),
        )
        monkeypatch.setattr(
            sandbox_egress.Path, "read_text", lambda self, **k: "12345",
        )
        monkeypatch.setattr(sandbox_egress.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            sandbox_egress.subprocess, "run",
            lambda *a, **k: sp.CompletedProcess(
                a[0] if a else [], 1, "", "iptables: permission denied"
            ),
        )

        with pytest.raises(sandbox_egress.EgressUnavailable, match="failed to install"):
            with sandbox_egress.isolated_network(timeout_s=5.0):
                pytest.fail("a partial ruleset must not yield a prefix")

    def test_a_partial_ruleset_is_tolerated_only_under_the_opt_out(self, monkeypatch):
        """The falsifier: the refusal above must come from the POSTURE, not the stubs."""
        import subprocess as sp
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
        monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)

        class _Holder:
            def __init__(self, *a, **k):
                pass

            def terminate(self):
                pass

        real_exists = sandbox_egress.os.path.exists
        monkeypatch.setattr(sandbox_egress.subprocess, "Popen", _Holder)
        monkeypatch.setattr(
            sandbox_egress.os.path, "exists",
            lambda pth: True if str(pth).endswith("ready") else real_exists(pth),
        )
        monkeypatch.setattr(
            sandbox_egress.Path, "read_text", lambda self, **k: "12345",
        )
        monkeypatch.setattr(sandbox_egress.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            sandbox_egress.subprocess, "run",
            lambda *a, **k: sp.CompletedProcess(
                a[0] if a else [], 1, "", "iptables: permission denied"
            ),
        )

        with pytest.warns(RuntimeWarning, match="failed to install"):
            with sandbox_egress.isolated_network(timeout_s=5.0) as prefix:
                assert prefix == (), "a partial ruleset must never yield a usable prefix"


class TestTheOptOutIsOptionalNotDisable:
    """The knob makes isolation BEST-EFFORT; it must never drop it on a capable host.

    A `..._DISABLE` knob would do the opposite, and an operator setting it once for a bare
    CI container would silently unfilter every seat on claw.
    """

    def test_required_by_default(self, monkeypatch):
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
        assert sandbox_egress.egress_required() is True

    def test_the_knob_makes_it_best_effort(self, monkeypatch):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
        assert sandbox_egress.egress_required() is False

    def test_opting_out_still_isolates_where_it_can(self, monkeypatch):
        """Best-effort means best EFFORT: an available mechanism is still applied."""
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
        if not sandbox_egress.egress_isolation_available():
            pytest.skip("needs the mechanism to prove it is still used")
        with sandbox_egress.isolated_network(timeout_s=5.0) as prefix:
            assert prefix, "the opt-out must not disable a working mechanism"

    def test_the_opt_out_reason_is_distinguishable_from_a_missing_mechanism(self, monkeypatch):
        """Two different facts. An operator decision and a host limitation must not read
        the same in the evidence."""
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
        opted = sandbox_egress.enforcement_report(False)
        monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
        absent = sandbox_egress.enforcement_report(False)

        assert opted["network_filtered"] is False and absent["network_filtered"] is False
        assert opted.get("operator_opt_out") is True
        assert absent.get("operator_opt_out") is not True
        assert opted["reason"] != absent["reason"]


@pytest.mark.skipif(
    shutil.which("slirp4netns") is None or shutil.which("setpriv") is None,
    reason="needs slirp4netns + setpriv (Linux)",
)
class TestTheSeatCannotWithdrawItsOwnFirewall:
    """Board round 3, BLOCKING and DEMONSTRATED.

    The provider launched inside the same user namespace that owned the network namespace,
    so it held CAP_NET_ADMIN over its own confinement. Measured before the fix:

        before flush  qdrant -> BLOCKED
        iptables -F OUTPUT   -> FLUSHED
        after flush   qdrant -> 200

    One command took ~69 GB of user data from unreachable to readable. Rules a reviewer can
    withdraw are a suggestion, not a boundary. The bounding set is now emptied, so the
    capability cannot be regained even by re-exec.
    """

    def test_flushing_the_rules_is_refused_and_the_policy_still_holds(self):
        import subprocess as sp
        from phase_loop_runtime import sandbox_egress as se

        if not se.egress_isolation_available():
            pytest.skip("user namespaces unavailable")

        with se.isolated_network() as prefix:
            assert prefix, "isolation must be available for this test to mean anything"

            def run(script):
                return sp.run([*prefix, "bash", "-c", script],
                              capture_output=True, text=True, timeout=45).stdout.strip()

            flush = run("iptables -F OUTPUT 2>&1 && echo FLUSHED || echo REFUSED")
            assert "FLUSHED" not in flush, f"the seat withdrew its own firewall: {flush!r}"

            after = run(
                "timeout 5 curl -s -o /dev/null -w %{http_code} --max-time 4 "
                "http://100.84.171.76:6333/collections || echo BLOCKED"
            )
            assert "BLOCKED" in after or "000" in after, (
                f"private space reachable after a flush attempt: {after!r}"
            )
            public = run(
                "timeout 5 curl -s -o /dev/null -w %{http_code} --max-time 4 "
                "https://1.1.1.1 || echo BLOCKED"
            )
            assert "301" in public or "200" in public, "the internet must still work"

    def test_the_prefix_drops_the_capability_bounding_set(self):
        from phase_loop_runtime import sandbox_egress as se
        if not se.egress_isolation_available():
            pytest.skip("user namespaces unavailable")
        with se.isolated_network() as prefix:
            assert "--bounding-set=-all" in prefix, (
                "emptying the EFFECTIVE set alone is regainable by re-exec"
            )


def test_round_facts_do_not_leak_between_legs():
    """Board round 3: `_SANDBOX_ROUND_FACTS` was a process-global dict.

    A sandboxed launch attached `network_filtered=True`, and a later UNSANDBOXED launch
    inherited it -- reporting a boundary for a seat that had no prefix. Legs fan out across
    threads, and a ContextVar gives each thread its own context, so one seat's facts cannot
    become another's.
    """
    from concurrent.futures import ThreadPoolExecutor
    from phase_loop_runtime import panel_invoker, sandbox_policy

    choice = sandbox_policy.SandboxRootChoice(host=None, path=Path("/tmp"), fell_back=False)
    panel_invoker._record_sandbox_facts(
        choice, sandbox_egress.enforcement_report(True, applied=True),
        staged_at=Path("/tmp/pl-panel-test/reviewed-tree"),
    )
    assert panel_invoker._sandbox_evidence()["sandbox_network_filtered"] is True

    with ThreadPoolExecutor(max_workers=1) as pool:
        other = pool.submit(panel_invoker._sandbox_evidence).result()

    assert other.get("sandbox_network_filtered") is not True, (
        "an unsandboxed leg inherited a sandboxed leg's isolation claim"
    )


def test_round_facts_do_not_leak_to_the_NEXT_leg_on_the_same_thread():
    """The leak the board actually found, which the cross-thread test above does not reach.

    A ContextVar gives each THREAD its own context, so the cross-thread test passes whether
    or not anyone resets the token -- it was green throughout the round the leak survived.
    Legs also run SEQUENTIALLY on a reused worker: leg 1 records `network_filtered=True`,
    leg 2 runs unsandboxed on that same thread and inherits it. The recorder was fixed to
    return a token; the caller kept discarding it, so the leak stayed live through the
    round whose commit message said it was fixed.

    Both legs run on ONE pool worker, which is the shape the leak needs. Running it in a
    fresh thread also keeps it honest: assert in this thread and an earlier test's
    unreset write is the baseline, so the test measures pollution rather than resetting.
    """
    from concurrent.futures import ThreadPoolExecutor
    from phase_loop_runtime import panel_invoker, sandbox_policy

    choice = sandbox_policy.SandboxRootChoice(host=None, path=Path("/tmp"), fell_back=False)

    def leg_one() -> object:
        token = panel_invoker._record_sandbox_facts(
            choice, sandbox_egress.enforcement_report(True, applied=True),
            staged_at=Path("/tmp/pl-panel-test/reviewed-tree"),
        )
        assert token is not None, "the recorder must hand back something resettable"
        assert panel_invoker._sandbox_evidence()["sandbox_network_filtered"] is True
        # What the launch site does in its ExitStack callback.
        panel_invoker._SANDBOX_ROUND_FACTS.reset(token)
        return token

    def leg_two() -> dict:
        return dict(panel_invoker._sandbox_evidence())

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(leg_one).result()
        inherited = pool.submit(leg_two).result()

    assert inherited.get("sandbox_network_filtered") is not True, (
        "the next leg on this worker inherited the previous leg's isolation claim"
    )


def test_a_leg_that_never_resets_DOES_leak(monkeypatch):
    """The falsifier for the test above: without the reset, the leak is real and visible.

    Without this, a `_sandbox_evidence()` that stopped reporting the key at all would make
    the leak test pass by saying nothing.
    """
    from concurrent.futures import ThreadPoolExecutor
    from phase_loop_runtime import panel_invoker, sandbox_policy

    choice = sandbox_policy.SandboxRootChoice(host=None, path=Path("/tmp"), fell_back=False)

    def leg_one() -> None:
        panel_invoker._record_sandbox_facts(  # token deliberately discarded
            choice, sandbox_egress.enforcement_report(True, applied=True),
            staged_at=Path("/tmp/pl-panel-test/reviewed-tree"),
        )

    def leg_two() -> dict:
        return dict(panel_invoker._sandbox_evidence())

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(leg_one).result()
        inherited = pool.submit(leg_two).result()

    assert inherited.get("sandbox_network_filtered") is True, (
        "if discarding the token does NOT leak, the reset above proves nothing"
    )


def test_the_launch_site_resets_the_facts_token():
    """Returning a token nobody resets is the mechanism-without-activation pattern again."""
    import inspect
    from phase_loop_runtime import panel_invoker

    source = inspect.getsource(panel_invoker._default_spawn)
    assert "_record_sandbox_facts(" in source, "the launch site must record facts"
    assert "_SANDBOX_ROUND_FACTS.reset" in source, (
        "the launch site records facts and never resets them"
    )


class TestTheRecordSaysWhereTheSandboxACTUALLYIs:
    """`select_sandbox_root` resolves a LOCATION; nothing consumes it for placement.

    The stage is always `mkdtemp(prefix="pl-panel-")` on the local filesystem
    (`panel_invoker.py:5857`), so setting `PHASE_LOOP_SANDBOX_ROOT=ai:/storage/sandboxes`
    used to publish `sandbox_root_host: "ai"` into the review evidence for a sandbox that
    never left this machine. Mechanism complete, activation absent, mechanism described as
    the capability -- the fourteenth instance of that pattern on this branch, and the one
    the board would have found in round 5.

    Implementing co-location is agent-harness#896. Not lying about it is here.
    """

    def _choice(self, host, path):
        from phase_loop_runtime import sandbox_policy
        return sandbox_policy.SandboxRootChoice(
            host=host, path=Path(path), fell_back=False,
        )

    def test_a_remote_selection_is_recorded_as_NOT_applied(self):
        from phase_loop_runtime import panel_invoker

        token = panel_invoker._record_sandbox_facts(
            self._choice("ai", "/storage/sandboxes"),
            sandbox_egress.enforcement_report(True, applied=True),
            staged_at=Path("/tmp/pl-panel-abc/reviewed-tree"),
        )
        try:
            facts = panel_invoker._sandbox_evidence()
            assert facts["sandbox_root_applied"] is False
            assert facts["sandbox_staged_at"] == "/tmp/pl-panel-abc/reviewed-tree"
            assert "not implemented" in str(facts["sandbox_root_unapplied_reason"]) or \
                   "NOT used for placement" in str(facts["sandbox_root_unapplied_reason"])
        finally:
            panel_invoker._SANDBOX_ROUND_FACTS.reset(token)

    def test_a_local_root_that_really_is_the_parent_is_recorded_as_applied(self):
        """The falsifier: `applied` must not be hardcoded False."""
        from phase_loop_runtime import panel_invoker

        token = panel_invoker._record_sandbox_facts(
            self._choice(None, "/tmp/pl-panel-abc"),
            sandbox_egress.enforcement_report(True, applied=True),
            staged_at=Path("/tmp/pl-panel-abc/reviewed-tree"),
        )
        try:
            facts = panel_invoker._sandbox_evidence()
            assert facts["sandbox_root_applied"] is True
            assert "sandbox_root_unapplied_reason" not in facts
        finally:
            panel_invoker._SANDBOX_ROUND_FACTS.reset(token)

    def test_the_evidence_always_carries_where_it_is(self):
        """`sandbox_staged_at` is the field a reader can act on; it must never be absent."""
        from phase_loop_runtime import panel_invoker

        for host, path in (("ai", "/storage/x"), (None, "/tmp/pl-panel-abc")):
            token = panel_invoker._record_sandbox_facts(
                self._choice(host, path),
                sandbox_egress.enforcement_report(False),
                staged_at=Path("/tmp/pl-panel-abc/reviewed-tree"),
            )
            try:
                assert panel_invoker._sandbox_evidence()["sandbox_staged_at"]
            finally:
                panel_invoker._SANDBOX_ROUND_FACTS.reset(token)
