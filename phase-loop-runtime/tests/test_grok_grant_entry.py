"""Grok grant creation and legacy readback through the measurement entry points."""

import json

import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import seat_profiles, seat_window

from test_grok_tool_surface_measure import Bench, GRANT, HOSTED_RUN, SEAT


@pytest.fixture
def bench(tmp_path, monkeypatch):
    return Bench(tmp_path, monkeypatch)


def test_the_cli_refuses_a_new_unjailed_grant_with_a_registered_profile(bench, capsys):
    assert seat_profiles.profile_for("grok") is not None
    args = bench.args("--new-grant", "--planned", "review", "--retries", "0",
                      "--hosted-check", HOSTED_RUN)
    code = seat_window.cli_main(args)
    report = json.loads(capsys.readouterr().out)
    assert (code, report["status"], report.get("code"), bench.grant_dir().exists()) == (
        1, "refused", "unjailed_grant_refused", False)


def test_the_grant_writer_refuses_unjailed_creation(bench):
    with pytest.raises(gts.MeasurementRefused) as refused:
        gts.new_grant(GRANT, binary_sha256=bench.digest, planned=SEAT, retries=0,
                      hosted_check=HOSTED_RUN)
    assert refused.value.code == "unjailed_grant_refused"
    assert not bench.grant_dir().parent.exists()


def test_the_cli_reads_a_legacy_grant_with_a_registered_profile(bench, capsys, monkeypatch):
    with monkeypatch.context() as legacy:
        legacy.delitem(seat_profiles._REGISTRY, "grok")
        grant = bench.open_grant(planned="review", rehearse=False)["grant"]
    assert seat_profiles.profile_for("grok") is not None
    assert "context" not in grant
    assert seat_window.cli_main(bench.args("--status")) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["grant"] == grant
    assert report["charged"] == 0
    assert json.loads((bench.grant_dir() / "grant.json").read_text()) == grant
