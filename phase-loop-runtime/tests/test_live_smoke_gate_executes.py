"""The live-smoke gate must actually EXECUTE (agent-harness#542).

`phase_loop_smoke_utils.live_smoke_enabled` ended in a third clause that could
never run:

    ... and shutil.which(harness.binary) is not None and BIN.exists()

`BIN` was a `str`, so `BIN.exists()` is an `AttributeError`, not a check. It
survived indefinitely because the leading `os.environ.get(...) == "1"` short-
circuits it in every ordinary run: the clause is only reached when someone
actually enables a live smoke, which is exactly the moment it was supposed to
protect. A guard that cannot run is a guard that isn't there.

These arms drive the gate to its FINAL clause -- env var set, harness binary
present -- which is the state no ordinary run reaches. Restore `BIN.exists()` and
they fail with `AttributeError`, so they are coupled to the defect rather than
merely adjacent to it.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import phase_loop_smoke_utils as smoke


class LiveSmokeGateExecutesTest(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for harness in smoke.LIVE_HARNESSES:
            os.environ.pop(harness.env_var, None)
        # `codex` short-circuits on re-entrancy when this is set, which would skip
        # the very clause under test.
        os.environ.pop("CODEX_THREAD_ID", None)

    def _enable(self, executor: str) -> None:
        os.environ[smoke.live_harness(executor).env_var] = "1"

    def test_gate_reaches_its_final_clause_and_returns_a_bool(self):
        """The whole point: evaluate the last clause instead of raising."""
        self._enable("claude")
        with mock.patch.object(smoke.shutil, "which", return_value="/usr/bin/claude"):
            result = smoke.live_smoke_enabled("claude")
        self.assertIsInstance(result, bool)
        self.assertTrue(
            result,
            "env var set + harness binary present + CLI importable must ENABLE the "
            "live smoke; a False here means the final clause is wrong, not absent",
        )

    def test_gate_is_false_when_the_harness_binary_is_absent(self):
        """Positive control: an always-true gate cannot survive this arm."""
        self._enable("claude")
        with mock.patch.object(smoke.shutil, "which", return_value=None):
            self.assertFalse(smoke.live_smoke_enabled("claude"))

    def test_gate_is_false_when_the_cli_cannot_be_run(self):
        """The clause that used to be `BIN.exists()` must still be able to say NO."""
        self._enable("claude")
        with mock.patch.object(smoke.shutil, "which", return_value="/usr/bin/claude"), \
                mock.patch.object(smoke, "phase_loop_cli_available", return_value=False):
            self.assertFalse(smoke.live_smoke_enabled("claude"))

    def test_enabled_executors_enumeration_does_not_raise(self):
        """`enabled_live_smoke_executors` calls the gate for EVERY harness, so it hit
        the unreachable clause for each one the moment any live smoke was enabled."""
        for harness in smoke.LIVE_HARNESSES:
            os.environ[harness.env_var] = "1"
        with mock.patch.object(smoke.shutil, "which", return_value="/usr/bin/x"):
            enabled = smoke.enabled_live_smoke_executors()
        self.assertEqual(
            set(enabled), {h.executor for h in smoke.LIVE_HARNESSES}
        )

    def test_cli_availability_probe_is_true_in_this_tree(self):
        self.assertTrue(smoke.phase_loop_cli_available())


if __name__ == "__main__":
    unittest.main()
