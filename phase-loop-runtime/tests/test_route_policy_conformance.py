"""Conformance test: `resolve_claude_route` + posture helpers must match every
golden route-selection fixture.

The fixtures (`phase_loop_runtime/route_policy/fixtures/route_selection.golden.json`)
are the frozen, language-neutral contract that gp's TS `resolveClaudeRoute`
(gp #25) also validates against. This test is CLI-independent (pure policy, no
CLI entrypoint) and should be listed in the CLI-independent unit guard.

ROUTESPEC is behavior-preserving: this test EXTERNALIZES the existing policy. It
drives the production `resolve_claude_route` through every fixture; it does not
change behavior. A fixture that does not match production reveals either a
fixture bug (fix the fixture) or a latent policy bug (STOP and report — do not
patch policy here).
"""

import importlib.resources as resources
import json
import unittest

from phase_loop_runtime.launcher import (
    claude_route_billing_posture,
    claude_route_fallback_posture,
    resolve_claude_route,
)

# The actual number of resolve-layer conformance cases. Pinned to the real count
# (not the IF-0-ROUTESPEC-1 floor of 13) so a deletion of any case — including the
# billing-sensitive print cases — drops below this and fails the anti-shrink guard.
# Legitimate future additions raise this number; deletions must not lower it
# silently. (>= 13 remains the contract floor.)
MIN_FIXTURE_CASES = 18


def _load_fixtures():
    raw = (
        resources.files("phase_loop_runtime.route_policy.fixtures")
        .joinpath("route_selection.golden.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)


class RoutePolicyConformanceTest(unittest.TestCase):
    def test_fixture_count_does_not_shrink(self):
        cases = _load_fixtures()
        self.assertGreaterEqual(
            len(cases),
            MIN_FIXTURE_CASES,
            f"fixture count {len(cases)} shrank below the known conformance floor "
            f"{MIN_FIXTURE_CASES} — silent fixture loss",
        )

    def test_fixture_names_are_unique(self):
        names = [case["name"] for case in _load_fixtures()]
        self.assertEqual(len(names), len(set(names)), "duplicate fixture names")

    def test_every_fixture_matches_resolve_claude_route(self):
        cases = _load_fixtures()
        self.assertTrue(cases, "no fixtures loaded")
        for case in cases:
            with self.subTest(case=case["name"]):
                inputs = case["inputs"]
                expected = case["expected"]
                # Always pass env explicitly (including {}) so the case is
                # hermetic and does not inherit the host's CI / route env.
                selection = resolve_claude_route(
                    inputs["value"], env=dict(inputs["env_vars"])
                )
                self.assertEqual(
                    selection.route, expected["route"], f"{case['name']}: route"
                )
                self.assertEqual(
                    selection.reason, expected["reason"], f"{case['name']}: reason"
                )

                billing = claude_route_billing_posture(
                    selection.route, selection.reason
                )
                self.assertEqual(
                    billing,
                    expected["billing_posture"],
                    f"{case['name']}: billing_posture",
                )

                fallback = claude_route_fallback_posture(
                    selection.route, selection.reason
                )
                self.assertEqual(
                    fallback,
                    expected["fallback_posture"],
                    f"{case['name']}: fallback_posture",
                )

                # Selection OUTPUT fields (channel sidecar URL + session id). These
                # are populated by resolve_claude_route from env (default loopback /
                # PHASE_LOOP_CHANNEL_SESSION_ID), distinct from the build_launch_spec
                # preflight VALIDATION which is out of this cross-language contract.
                # Always assert against the expected value (default None) so a route
                # can't silently start (or stop) carrying these.
                self.assertEqual(
                    selection.sidecar_url,
                    expected.get("sidecar_url"),
                    f"{case['name']}: sidecar_url",
                )
                self.assertEqual(
                    selection.session_id,
                    expected.get("session_id"),
                    f"{case['name']}: session_id",
                )

                # Error expectation: ALWAYS assert (default None) so a success case
                # can't silently start carrying a spurious error. A substring match
                # lowercases BOTH sides; an exact match defaults to None.
                if "error_contains" in expected:
                    self.assertIsNotNone(
                        selection.error, f"{case['name']}: expected an error"
                    )
                    self.assertIn(
                        expected["error_contains"].lower(),
                        selection.error.lower(),
                        f"{case['name']}: error substring",
                    )
                else:
                    self.assertEqual(
                        selection.error,
                        expected.get("error"),
                        f"{case['name']}: error",
                    )

                # Warning expectation. Two-sided: when the fixture names a
                # warning substring, a matching warning MUST be recorded;
                # otherwise the selection MUST carry NO warnings (catches a
                # regression that attaches a billing warning to a subscription
                # route).
                if "warning_contains" in expected:
                    self.assertTrue(
                        selection.warnings, f"{case['name']}: expected a warning"
                    )
                    needle = expected["warning_contains"].lower()
                    self.assertTrue(
                        any(needle in w.lower() for w in selection.warnings),
                        f"{case['name']}: warning substring",
                    )
                else:
                    self.assertFalse(
                        selection.warnings,
                        f"{case['name']}: expected NO warnings, got {selection.warnings!r}",
                    )


if __name__ == "__main__":
    unittest.main()
