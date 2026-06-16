"""BREAKGLASS (roadmap v40) — CLI surface for ``--closeout-allow-unowned``.

Mirrors the ``--allow-cross-phase-dirty`` reason-flag contract: valid only for
the dispatch commands (run/resume/dry-run), rejects a blank reason before
``run_loop`` is ever called, and the reason is threaded into ``run_loop`` as
``allow_unowned_reason``. A blank reason -> SystemExit (operator-override audit
trail cannot be empty).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import unittest

from phase_loop_runtime.cli import build_parser, main
from phase_loop_test_utils import make_repo, provenanced_state


class CloseoutBreakGlassCliTest(unittest.TestCase):
    def test_flag_is_limited_to_dispatch_commands(self):
        parser = build_parser()
        for command in ("run", "resume", "dry-run"):
            args = parser.parse_args([command, "--closeout-allow-unowned", "owner sign-off in #123"])
            self.assertEqual(args.closeout_allow_unowned, "owner sign-off in #123")
        for command in ("status", "handoff", "execute", "reconcile"):
            with self.subTest(command=command), self.assertRaises(SystemExit):
                parser.parse_args([command, "--closeout-allow-unowned", "owner sign-off in #123"])

    def test_flag_help_documents_reason_required(self):
        for command in ("run", "resume", "dry-run"):
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, "-m", "phase_loop_runtime.cli", command, "--help"],
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertIn("--closeout-allow-unowned", result.stdout)

    def test_blank_reason_rejected_before_run_loop(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            with patch("phase_loop_runtime.cli.run_loop") as fake_run_loop, self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "run",
                        "--repo",
                        str(repo),
                        "--roadmap",
                        str(roadmap),
                        "--closeout-allow-unowned",
                        "   ",
                    ]
                )
            self.assertEqual(raised.exception.code, 2)
            fake_run_loop.assert_not_called()

    def test_reason_is_threaded_into_run_loop(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            seen = []

            def fake_run_loop(**kwargs):
                seen.append(kwargs["action"])
                self.assertEqual(kwargs["allow_unowned_reason"], "owner sign-off in #123")
                return provenanced_state(repo, roadmap, {"RUNNER": "planned"}), []

            with patch("phase_loop_runtime.cli.run_loop", side_effect=fake_run_loop), patch(
                "phase_loop_runtime.cli.render_status", return_value="status"
            ):
                for command in ("run", "resume", "dry-run"):
                    with self.subTest(command=command):
                        self.assertEqual(
                            main(
                                [
                                    command,
                                    "--repo",
                                    str(repo),
                                    "--roadmap",
                                    str(roadmap),
                                    "--phase",
                                    "RUNNER",
                                    "--closeout-allow-unowned",
                                    " owner sign-off in #123 ",
                                ]
                            ),
                            0,
                        )
            self.assertEqual(seen, ["run", "resume", "dry-run"])


if __name__ == "__main__":
    unittest.main()
