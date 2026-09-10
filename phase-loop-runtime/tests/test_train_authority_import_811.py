"""agent-harness#811: publication imports cannot replace the finalized train builder."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", ["publishing", "train_runner"])
def test_authority_preimage_is_independent_of_import_order(tmp_path, first):
    source = Path(__file__).resolve().parents[1] / "src"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib, json, sys
from pathlib import Path
from types import SimpleNamespace
importlib.import_module('phase_loop_runtime.' + sys.argv[1])
from phase_loop_runtime import publishing, train_runner
runtime = SimpleNamespace(train_id='fixture-train', coordinator_root=Path(sys.argv[2]),
                          roadmap_digest='a' * 64, workspace_id='fixture-workspace')
node = SimpleNamespace(node_id='fixture-node')
value = train_runner._default_build_publish_authority(runtime, node, Path(sys.argv[2]), ['file.txt'])
print(json.dumps({'builder_module': train_runner._default_build_publish_authority.__module__,
                  'same_preimage_type': train_runner.PublishAuthorityPreimages is publishing.PublishAuthorityPreimages,
                  'authority': value.envelope_authority_preimage}))
""", first, str(workspace)],
        env=dict(os.environ, PYTHONPATH=str(source)), text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["authority"]["expected_version_predicate"] == "head == committed"
    assert data["authority"]["roadmap_digest"] == "a" * 64
    assert data["builder_module"] == "phase_loop_runtime.train_runner"
    assert data["same_preimage_type"] is True
