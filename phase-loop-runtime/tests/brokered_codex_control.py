"""Explicit pre-registration control for the shared broker/owner regression tests.

These controls measure placement, monitoring and owner cleanup through the real broker
and a synthetic CLI. They do not measure Codex admission or its jail: those enter the
registered route in test_seat_codex_route_gate and test_seat_codex_leg. Keep both the
profile and its admission gate absent together, as they were before SL-3 registration.
Never install this control implicitly for a file or for the suite.
"""


def use_unregistered_codex_broker(monkeypatch):
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from phase_loop_runtime import seat_admission, seat_profiles, seat_route
    from phase_loop_runtime.seat_profile_codex import CODEX_PROFILE, codex_admission_gate

    # Registration adds the shared resource-caps precondition to the frozen profile.
    assert seat_profiles.profile_for("codex").argv is CODEX_PROFILE.argv
    assert codex_admission_gate in seat_admission._GATES["codex"]
    monkeypatch.delitem(seat_profiles._REGISTRY, "codex")
    monkeypatch.delitem(seat_admission._GATES, "codex")
    # SL-3 retired this exception from the shipped matrix. Restore it only in this
    # historical control, with a bounded synthetic expiry, never in production policy.
    load_policy = seat_route.load_route_policy
    exception = seat_route.NamedException(
        "codex", "unconfined", datetime.now(timezone.utc) + timedelta(days=1),
        "synthetic pre-registration broker control",
    )

    def legacy_policy(*args, **kwargs):
        policy = load_policy(*args, **kwargs)
        return replace(policy, exceptions={**policy.exceptions, "codex": exception})

    monkeypatch.setattr(seat_route, "load_route_policy", legacy_policy)
