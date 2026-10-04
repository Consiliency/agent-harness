import shutil

import test_agent_cli_scratch_inventory_1147 as inventory


def test_getattr_agent_launch_is_not_silently_unlisted(tmp_path):
    package = tmp_path / "phase_loop_runtime"
    shutil.copytree(inventory.PACKAGE, package,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (package / "_r4_launch.py").write_text(
        "import subprocess\n"
        "def launch():\n"
        "    return getattr(subprocess, 'run')(['claude', '-p', 'hi'])\n",
        encoding="utf-8",
    )
    assert ("_r4_launch.py", "launch") in inventory._undecided(package), (
        "an agent launch bypasses both the scratch interface and its inventory")
