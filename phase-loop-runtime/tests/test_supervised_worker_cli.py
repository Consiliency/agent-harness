"""Isolated WORKER CLI fixture checks; no production state is accessed."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from phase_loop_runtime import supervised_worker_cli as cli
from phase_loop_runtime.supervised_launch import Refused


@pytest.mark.parametrize("argv,reason", [(["launch", "--envelope", "/absent", "--result", "/absent"],
                                        "codec_unavailable"), (["unknown"], "invalid choice")])
def test_isolated_cli_before_root(tmp_path, argv, reason):
    root = Path(cli.__file__).parents[1]
    for name in ("json.py", "argparse.py", "validator.py"):
        (tmp_path / name).write_text('raise RuntimeError("shadow loaded")')
    result = subprocess.run([sys.executable, "-I", "-c",
        'import sys; sys.path.insert(0,sys.argv.pop(1)); '
        'from phase_loop_runtime.supervised_worker_cli import main; raise SystemExit(main())',
        str(root), *argv], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode in (2, 10)
    assert reason in result.stdout + result.stderr
    assert "shadow loaded" not in result.stderr


def test_cli_preflight_before_codec_and_reads(monkeypatch, capsys):
    monkeypatch.setattr(cli, "preflight_supervised_route", lambda _: Refused("fixture_required"))
    def unexpected():
        raise AssertionError("codec reached")
    monkeypatch.setattr(cli, "_production_codec", unexpected)
    assert cli.main(["launch", "--envelope", "/absent", "--result", "/absent"]) == 10
    assert capsys.readouterr().out.strip() == "fixture_required"


def test_envelope_file_and_result_modes(tmp_path):
    tmp_path.chmod(0o700)
    source = tmp_path / "envelope"
    source.write_bytes(b"fixture")
    source.chmod(0o600)
    result = cli.read_envelope_file(source, cap=10)
    assert result[0] == b"fixture"
    assert isinstance(cli.read_envelope_file(source, cap=2), Refused)
    source.chmod(0o622)
    assert isinstance(cli.read_envelope_file(source, cap=10), Refused)
    link = tmp_path / "link"
    link.symlink_to(source)
    assert isinstance(cli.read_envelope_file(link, cap=10), Refused)
    result_path = tmp_path / "result"
    fd = cli.open_result_file(result_path, excluded=())
    assert isinstance(fd, int)
    assert os.fstat(fd).st_mode & 0o777 == 0o600
    os.close(fd)
    assert isinstance(cli.open_result_file(result_path, excluded=()), Refused)
    assert isinstance(cli.open_result_file(tmp_path / "other", excluded=(tmp_path,)), Refused)


def test_status_missing_root_in_process(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=1)))
    assert cli.main(["status", "--attempt", "fixture"], state_root=tmp_path / "absent") == 10
    assert "journal_missing" in capsys.readouterr().out
