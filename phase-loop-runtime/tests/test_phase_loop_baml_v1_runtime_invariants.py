"""BAML v1 client invariants I2-I9, each run in a fresh interpreter.

Split out of tests/test_phase_loop_baml_v1_runtime.py, which still holds the
scenarios, helpers and every other falsifier, so that this driver is its own
work unit under ``--dist loadfile`` instead of lengthening that file's.
"""

import pytest

from tests import test_phase_loop_baml_v1_runtime as rt


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("i2_stalled_caller_after_reply"),
        pytest.param("i2_concurrent_abandonment"),
        pytest.param("i2_stale_frame", marks=rt.needs_posix),
        pytest.param("i3_owner_killed_with_waiters"),
        pytest.param("i3_owner_dies_before_delivery"),
        pytest.param("i3_owner_dies_before_publication"),
        pytest.param("i4_busy"),
        pytest.param("i4_backlog_success"),
        pytest.param("i4_publish_before_expiry"),
        pytest.param("i4_post_handoff_expiries"),
        pytest.param("i4_abandon_service"),
        pytest.param("i6_lock_trace", marks=rt.needs_posix),
        pytest.param("i7_machinery_failures"),
        pytest.param("i7_no_discard"),
        pytest.param("i9_resources"),
    ],
)
def test_client_invariant_scenario(name):
    # I9 pays one worker cold start per dispose cycle: ~95 s on x86_64 glibc,
    # but ~13 s per cold start on musl (verification step 6).
    rt._isolated(name, timeout=2400 if name == "i9_resources" else 600)
