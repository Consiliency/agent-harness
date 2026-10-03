import test_agent_cli_scratch_inventory_1147 as inventory


def test_partial_getattr_launch_requires_classification(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "m.py").write_text(
        "import functools, subprocess\n"
        "def launch():\n"
        "    runner = functools.partial(getattr(subprocess, 'run'), ['claude'])\n"
        "    return runner()\n",
        encoding="utf-8",
    )
    assert ("m.py", "launch") in inventory._undecided(package), (
        "an unclassified launch reference escaped the inventory"
    )
