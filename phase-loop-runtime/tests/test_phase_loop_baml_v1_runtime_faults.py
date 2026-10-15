"""BAML v1 worker faults and owner death at every terminal transition line.

Split out of tests/test_phase_loop_baml_v1_runtime.py, which still holds the
scenarios, helpers and every other falsifier, so that this pair of drivers is its own
work unit under ``--dist loadfile`` instead of lengthening that file's.
"""

import pytest

from tests import test_phase_loop_baml_v1_runtime as rt


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("idle_death_sigkill", marks=rt.needs_posix),
        pytest.param("idle_death_sigterm", marks=rt.needs_posix),
        "idle_death_spawn_hook",
        "spawn_hook_default_budget",
        pytest.param("inflight_kill_retries_zero", marks=rt.needs_posix),
        pytest.param("inflight_kill_within_budget", marks=rt.needs_posix),
        pytest.param("retry_budget_exhaustion", marks=rt.needs_posix),
        pytest.param("recovery_parity_parse_closeout", marks=rt.needs_posix),
        pytest.param("recovery_parity_closeout_request", marks=rt.needs_posix),
        pytest.param("recovery_parity_evidence_request", marks=rt.needs_posix),
        "timeout_disposes_the_worker",
        "blocked_write",
        "stalled_spawn",
        pytest.param("dead_spawner_is_recreated", marks=rt.needs_linux),
        "missing_interpreter_is_a_spawn_error",
        "framing_faults",
        "broken_source_is_an_init_fault",
        "in_baml_panic_is_contained",
        "frame_cap_derivation",
    ],
)
def test_worker_fault_scenario(name):
    rt._isolated(name)


@pytest.mark.parametrize("flow,owner,name,line", list(rt._terminal_cases()))
def test_owner_death_at_every_terminal_transition_line(flow, owner, name, line):
    if not rt._owner_death_case(flow, owner, name, line):
        pytest.skip("this line is not executed by the owner in this flow")
