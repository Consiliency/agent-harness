"""A landed RATIFY corpus must execute every node, including its docs falsifier."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import ratify_content_tdd_adapter as tdd


def _ratify_completed():
    manifest = Path(__file__).resolve().parents[2] / "plans/manifest.json"
    if not manifest.exists():
        return False
    rows = json.loads(manifest.read_text(encoding="utf-8"))["plans"]
    return any(row.get("phase_alias") == "RATIFY" and (
        row.get("status") == "completed" or any(
            event.get("transition") == "completed" for event in row.get("lifecycle", ())
        )
    ) for row in rows)


def test_no_ratify_contract_skips_as_unimplemented():
    def check():
        tdd.capability("ledger")
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_XDIST")}
        env.pop("PHASE_LOOP_TDD_EXPECT_RATIFY", None)
        env.pop("PYTEST_CURRENT_TEST", None)
        env["PHASE_LOOP_TDD_REQUIRE_RATIFY_GREEN"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(("src", "tests"))
        runtime = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="ratify-landed-") as temp:
            junit = Path(temp) / "corpus.xml"
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
                 "tests/test_ratify_phase.py", "tests/test_ruling_ledger.py", f"--junitxml={junit}"],
                cwd=runtime, env=env, capture_output=True, text=True,
            )
            assert proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]
            # This nested run excludes this guard itself, while still requiring
            # every frozen semantic and soundness control to execute.
            from xml.etree import ElementTree
            cases = list(ElementTree.parse(junit).getroot().iter("testcase"))
            expected = {node.rsplit("::", 1)[1] for node in tdd.EXPECTED_RED_NODES | tdd.EXPECTED_GREEN_NODES
                        if "test_ratify_landed.py" not in node}
            assert len(cases) == len(expected) and {case.get("name") for case in cases} == expected
            assert not any(any(case.find(tag) is not None for tag in ("skipped", "error", "failure")) for case in cases)
    # Completion is durable manifest history, independent of removable source
    # markers. A later deletion must fail ordinary CI, even with no strict env.
    overrides = {"PHASE_LOOP_TDD_REQUIRE_RATIFY_GREEN": "1"} if _ratify_completed() else {}
    with patch.dict(os.environ, overrides):
        tdd.run_contract("landed_no_skips", "resolution", check)
