"""Synthetic in-process codec and launcher; never a production command."""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, sys.argv[1])
import phase_loop_runtime
assert Path(phase_loop_runtime.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
from phase_loop_runtime import supervised_launch as launch
from phase_loop_runtime.convergence.adapters import patch_return as worker

job = json.loads(Path(sys.argv[2]).read_bytes())
root = Path(job["root"])
config = launch.LaunchConfig(Path(job["config"]), Path(job["template"]))
prepared = launch.prepare_launch(json.dumps(job["envelope"]).encode(),
    validator=lambda view: launch.Admit(view.launch_digest, view.envelope["attempt_id"]),
    decoder=lambda capture: (capture.envelope, capture.raw_digest), config=config)
assert isinstance(prepared, launch.PreparedLaunch), prepared
original = worker._audit
first = True

def audit(*args):
    global first
    if first:
        first = False
        if job["mode"] == "crash":
            os._exit(0)
        if job["mode"] == "queued":
            (root / "ready").write_text("queued")
            time.sleep(.5)
    return original(*args)

worker._audit = audit
result = worker.run_patch_return(prepared, config_bytes=config.config_path.read_bytes(), state_root=root / "state")
(root / job["result"]).write_text(json.dumps(worker.asdict(result)))
