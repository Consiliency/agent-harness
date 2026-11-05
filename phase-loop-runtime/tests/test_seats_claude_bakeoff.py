"""SEATS CLAUDE lane D: the W0 bake-off record, V7 and the W0 kit (IF-0-CLAUDE-2, EC-CLAUDE-5).

Every control enters through ``claude_bakeoff validate`` (the CLI's ``main``) on a disposable
record directory and git repository, or through the kit's own entry points, and each must
fail. Nothing here runs a provider: the kit's board runs, meter readings and control files
are stand-ins, which is the point -- W0 itself is an owner action.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import claude_bakeoff as bk
from phase_loop_runtime import claude_seat_transport as ct

TOKEN = b"fake-w0-credential-" + b"q" * 32
TUI = "a" * 64
RECORD_4A = ("# Record\n\n## 4a. Amendment to §4, proposed 2026-10-20: the jailed Claude seat\n\n"
             "Print.\n\n## 5. Relation\n\nx\n")
SDK_4B = "\n## 4b. OD-3a: the jailed Claude transports\n\nThe amendment.\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@e.st"], ["config", "user.name", "t"]):
        _git(root, *args)
    record = root / ct.DECISION_RECORD
    record.parent.mkdir(parents=True)
    record.write_text(RECORD_4A)
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "seed")
    return root


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _section(repo: Path, section: str) -> str:
    raw = (repo / ct.DECISION_RECORD).read_bytes()
    return ct.record_sections(raw)[section][1]


def _set(entries=None, completeness="complete"):
    entries = entries if entries is not None else [
        {"method": "POST", "host": "api.anthropic.com", "path_template": "/v1/messages"}]
    return {"completeness": completeness, "capture_digest": "c" * 64, "entries": entries}


def native(repo: Path, *, block=1, n=1, arm="print", **overrides) -> dict:
    record = {
        "run_id": f"w0-b{block}-r{n}", "arm": arm, "block": block, "w0_head": _head(repo),
        "cli_version": "2.1.318", "canonical_output": "admitted", "code": "none",
        "admission": {p: "pass" for p in bk.ADMISSION_PREDICATES},
        "item7": {p: "pass" for p in bk.ITEM7_PREDICATES},
        "billing": "subscription", "meter_ref": f"w0-block-{block}", "meter_digest": "d" * 64,
        "claude_code_entrypoint": "unset", "claude_api_key_source": "none",
        "request_set": _set(), "jail_profile_digest": TUI,
        "dependency_projection_digest": "e" * 64 if arm == "sdk" else "not_applicable",
        "activation_section_sha256": overrides.get("activation_section_sha256") or _section(
            repo, "4b" if arm == "sdk" else "4a"),
        "co_seats_unconfined": [], "security_outcome": "none",
    }
    record.update(overrides)
    return record


def control(repo: Path, *, block=2, n=1, **overrides) -> dict:
    outcome = bk.ingest_control(json.dumps({
        "entrypoint": "sdk-ts", "api_key_source": "none", "model": "claude-opus-5-5",
        "canonical_output": "admitted", "verdict": "AGREE", "cli_version": "2.1.318"}).encode())
    record = bk.build_record(arm=bk.CONTROL, block=block, n=n, w0_head=_head(repo), outcome=outcome,
                             billing="subscription", meter_digest="d" * 64,
                             request_set=_set([], "partial"),
                             activation_section_sha256="not_applicable")
    record.update(overrides)
    return record


def write(directory: Path, *records: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for record in records:
        (directory / f"{record['run_id']}.json").write_bytes(bk.canonical_bytes(record))
    return directory


def validate(directory: Path, repo: Path, *extra: str) -> int:
    return bk.main(["validate", str(directory), "--repo", str(repo), *extra])


# --------------------------------------------------------------------------------------
# What must pass.
# --------------------------------------------------------------------------------------

def test_a_valid_window_passes_v7(repo, tmp_path):
    directory = write(tmp_path / "w0", native(repo), native(repo, n=2), control(repo))
    assert validate(directory, repo, "--tui-digest", TUI) == 0


def test_the_shipped_evidence_directory_passes_v7():
    root = Path(__file__).resolve().parents[2]
    assert bk.main(["validate", bk.EVIDENCE_DIR, "--repo", str(root)]) == 0


def test_the_evidence_digest_is_order_independent(repo, tmp_path):
    records = [native(repo), native(repo, n=2), control(repo)]
    one = write(tmp_path / "one", *records)
    two = write(tmp_path / "two", *records)
    # Rename so that name order is the reverse of the first directory's.
    for index, path in enumerate(sorted(two.glob("*.json"))):
        path.rename(path.with_name(f"{9 - index}-{path.name}"))
    assert [p.read_bytes() for p in sorted(one.glob("*.json"))] != [
        p.read_bytes() for p in sorted(two.glob("*.json"))]
    assert bk.evidence_digest(one) == bk.evidence_digest(two)
    write(tmp_path / "three", *records[:2])
    assert bk.evidence_digest(tmp_path / "three") != bk.evidence_digest(one)


# --------------------------------------------------------------------------------------
# One record: each control must fail.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("billing"),
    lambda r: r.update(extra_field="x"),
    lambda r: r.update(arm="tui"),
    lambda r: r.update(canonical_output="ok"),
    lambda r: r.update(billing="free"),
    lambda r: r.update(code="looks_typed_but_unknown"),
    lambda r: r.update(code="claude_seat_api_key_source"),
    lambda r: r.update(run_id="run-1"),
    lambda r: r.update(run_id="w0-b2-r1"),
    lambda r: r.update(run_id="w0-b1-r4"),
    lambda r: r.update(meter_ref="w0-block-2"),
    lambda r: r.update(w0_head="HEAD"),
    lambda r: r.update(cli_version="2.1.318 (Claude Code)"),
    lambda r: r.update(claude_code_entrypoint="Some Entry Point"),
    lambda r: r.update(claude_api_key_source="ANTHROPIC_API_KEY"),
    lambda r: r.update(dependency_projection_digest="e" * 64),
    lambda r: r.update(co_seats_unconfined=["grok", "codex"]),
    lambda r: r.update(security_outcome="withheld_private"),
    lambda r: r["admission"].update(jail="self_reported"),
    lambda r: r["item7"].pop("verdict"),
    lambda r: r["request_set"].update(completeness="mostly"),
    lambda r: r["request_set"].update(raw="GET /"),
])
def test_a_malformed_record_fails_v7(repo, tmp_path, mutate):
    record = native(repo)
    mutate(record)
    assert validate(write(tmp_path / "w0", record), repo) == 1


@pytest.mark.parametrize("planted, where", [
    ("sk-ant-oat01-" + "Zz9" * 12, "entrypoint"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig", "path"),
    ("AbCdEf0123456789AbCdEf0123456789xyzQ", "path"),
    ("12345678-1234-1234-1234-123456789abc", "path"),
    ("owner@example.com", "host"),
    ("/home/someone/repo", "path"),
    ("10.1.2.3", "host"),
    ("2001:db8::1", "host"),
    ("buildbox", "host"),
    ("api.corp.internal", "host"),
    ("devbox.local", "host"),
    ("node.tailnet-name.ts.net", "host"),
    ("printer.lan", "host"),
    ("/v1/organizations/9f8e7d6c5b4a/usage", "path"),
    ("/v1/sessions/1234567/events", "path"),
    ("/v1/sessions/sesn01abc23/events", "path"),
    ("/v1/files/abcdefghijklmnopqrstuvwxyz", "path"),
    ("/v1/messages?beta=true", "path"),
])
def test_a_planted_identifier_or_secret_shape_fails_v7(repo, tmp_path, planted, where):
    record = native(repo)
    if where == "host":
        record["request_set"]["entries"] = [
            {"method": "GET", "host": planted, "path_template": "/v1/messages"}]
    elif where == "path":
        record["request_set"]["entries"] = [
            {"method": "GET", "host": "api.anthropic.com", "path_template": planted}]
    else:
        record["claude_code_entrypoint"] = planted
    assert validate(write(tmp_path / "w0", record), repo) == 1
    assert bk.validate_record(record) != []


def test_a_templated_identifier_path_passes(repo, tmp_path):
    record = native(repo)
    record["request_set"]["entries"] = [
        {"method": "GET", "host": "api.anthropic.com", "path_template": "/v1/organizations/{id}/usage"}]
    assert bk.validate_record(record) == []


def test_a_live_credential_hit_blocks_the_write(repo, tmp_path):
    """A record that passes every shape check but carries the live credential (here as its
    hex encoding, which fits a digest field) is never written."""
    credential = bytes(range(160, 192))  # 32 bytes: its hex is exactly a sha256's shape
    record = native(repo, meter_digest=credential.hex())
    assert bk.validate_record(record) == []
    out = tmp_path / "w0"
    with pytest.raises(ValueError, match="live credential"):
        bk.write_record(out, record, token=credential)
    assert not out.exists() or list(out.iterdir()) == []


def test_a_record_with_a_problem_is_never_written(repo, tmp_path):
    record = native(repo, billing="free")
    with pytest.raises(ValueError):
        bk.write_record(tmp_path / "w0", record, token=TOKEN)
    assert not (tmp_path / "w0").exists()


def test_non_canonical_bytes_or_a_misnamed_file_fail(repo, tmp_path):
    directory = tmp_path / "w0"
    directory.mkdir()
    record = native(repo)
    (directory / "w0-b1-r1.json").write_text(json.dumps(record, indent=2))
    assert validate(directory, repo) == 1
    directory2 = tmp_path / "w0b"
    directory2.mkdir()
    (directory2 / "renamed.json").write_bytes(bk.canonical_bytes(record))
    assert validate(directory2, repo) == 1


# --------------------------------------------------------------------------------------
# Across records.
# --------------------------------------------------------------------------------------

def test_a_block_mixing_arms_fails(repo, tmp_path):
    assert validate(write(tmp_path / "w0", native(repo), native(repo, n=2, arm="sdk",
                                                                activation_section_sha256="f" * 64)),
                    repo) == 1


def test_a_block_on_the_wrong_arm_fails(repo, tmp_path):
    assert validate(write(tmp_path / "w0", control(repo, block=1)), repo) == 1


def test_a_shared_meter_ref_fails(repo, tmp_path):
    record = control(repo)
    record["meter_ref"] = "w0-block-1"
    assert validate(write(tmp_path / "w0", native(repo), record), repo) == 1


def test_an_sdk_record_whose_head_lacks_4b_fails(repo, tmp_path):
    assert validate(write(tmp_path / "w0", native(repo, block=3, arm="sdk",
                                                  activation_section_sha256="f" * 64)), repo) == 1


def test_an_sdk_record_whose_head_has_4b_passes_that_check(repo, tmp_path):
    (repo / ct.DECISION_RECORD).write_text(RECORD_4A + SDK_4B)
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qam", "4b")
    record = native(repo, block=3, arm="sdk")
    assert validate(write(tmp_path / "w0", record), repo) == 0


def test_a_native_record_off_the_tui_digest_fails(repo, tmp_path):
    other = native(repo, n=2, jail_profile_digest="b" * 64)
    assert validate(write(tmp_path / "w0", native(repo), other), repo) == 1
    assert validate(write(tmp_path / "w1", native(repo)), repo, "--tui-digest", "b" * 64) == 1


@pytest.mark.parametrize("predicate", ["login_proof", "single_result", "exact_model_match"])
def test_a_control_record_marking_a_non_permitted_check_not_applicable_fails(repo, tmp_path,
                                                                             predicate):
    record = control(repo)
    group = "admission" if predicate in bk.ADMISSION_PREDICATES else "item7"
    record[group][predicate] = "not_applicable"
    assert validate(write(tmp_path / "w0", record), repo) == 1


def test_the_control_may_mark_exactly_its_four_checks_not_applicable(repo):
    record = control(repo)
    marked = {name for group in ("admission", "item7") for name, value in record[group].items()
              if value == "not_applicable"}
    assert marked == set(bk.CONTROL_NOT_APPLICABLE)
    assert bk.validate_record(record) == []


def test_an_od3b_section_must_cite_the_evidence_digest(repo, tmp_path):
    directory = write(tmp_path / "w0", native(repo))
    digest = bk.evidence_digest(directory)
    wrong = (RECORD_4A + "\n## 4c. OD-3b: the jailed Claude default\n\n"
             "**Jailed Claude default:** `print`\n\n**W0 evidence digest:** `" + "0" * 64 + "`\n")
    right = wrong.replace("0" * 64, digest)
    assert bk.validate_directory(directory, repo=repo, record_text=wrong.encode()) != []
    assert bk.validate_directory(directory, repo=repo, record_text=right.encode()) == []


# --------------------------------------------------------------------------------------
# The capture twin and the recorder's output.
# --------------------------------------------------------------------------------------

def _rec(*lines: dict) -> bytes:
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


REQUEST = {"kind": "request", "method": "POST", "host": "api.anthropic.com",
           "path_template": "/v1/messages"}
DONE = {"kind": "connection", "terminated": True, "parsed": True}


def test_clean_recorder_output_becomes_a_complete_request_set():
    result = bk.ingest_recorder_output(_rec(REQUEST, REQUEST, DONE), token=TOKEN)
    assert result["completeness"] == "complete"
    assert result["entries"] == [{k: v for k, v in REQUEST.items() if k != "kind"}]


@pytest.mark.parametrize("line", [
    {**REQUEST, "headers": {"authorization": "Bearer x"}},
    {**REQUEST, "body": "{}"},
    {**REQUEST, "path_template": "/v1/sessions/123456789"},
    {**REQUEST, "path_template": "/v1/messages?key=1"},
    {"kind": "request", "method": "POST", "host": "api.anthropic.com"},
    {"kind": "connection", "terminated": True, "parsed": True, "sni": "x"},
])
def test_recorder_output_with_a_header_body_or_untemplated_path_fails(line):
    with pytest.raises(ValueError):
        bk.ingest_recorder_output(_rec(line, DONE), token=TOKEN)


def test_recorder_output_holding_the_token_fails():
    with pytest.raises(ValueError, match="token"):
        bk.ingest_recorder_output(_rec(REQUEST) + b"leak " + TOKEN + b"\n", token=TOKEN)


@pytest.mark.parametrize("connection", [
    {"kind": "connection", "terminated": True, "parsed": False},
    {"kind": "connection", "terminated": False, "parsed": False},
])
def test_a_set_with_an_unparsed_connection_is_never_complete(connection):
    result = bk.ingest_recorder_output(_rec(REQUEST, DONE, connection), token=TOKEN)
    assert result["completeness"] == "partial"


def _jail_env():
    from phase_loop_runtime import seat_jail

    return seat_jail.seat_env("claude", token_fd=9)


def test_the_twin_environment_is_the_declared_delta_only(tmp_path):
    jail = _jail_env()
    env = bk.twin_environment(jail, home=tmp_path / "home", proxy="http://srt:x@127.0.0.1:1",
                              ca=tmp_path / "ca.crt", bin_dir=tmp_path / "bin")
    assert bk.twin_delta_problems(jail, env) == []
    assert set(env) - set(jail) == bk.TWIN_DELTA_KEYS
    assert env["HOME"] == str(tmp_path / "home") and env[
        "CLAUDE_CONFIG_DIR"] == str(tmp_path / "home" / ".claude")


@pytest.mark.parametrize("widen", [
    lambda env: env.update(ANTHROPIC_BASE_URL="https://example.invalid"),
    lambda env: env.update(CLAUDE_CODE_USE_BEDROCK="1"),
    lambda env: env.update(DISABLE_AUTOUPDATER="0"),
    lambda env: env.pop("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"),
])
def test_a_twin_environment_beyond_the_declared_delta_fails(tmp_path, widen):
    jail = _jail_env()
    env = bk.twin_environment(jail, home=tmp_path / "home", proxy="http://srt:x@127.0.0.1:1",
                              ca=tmp_path / "ca.crt", bin_dir=tmp_path / "bin")
    widen(env)
    assert bk.twin_delta_problems(jail, env) != []


def test_a_bundle_head_off_main_is_refused(repo, tmp_path):
    _git(repo, "update-ref", "refs/remotes/origin/main", _head(repo))
    assert bk.head_on_main(repo, _head(repo))
    (repo / "x.txt").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "off main")
    assert not bk.head_on_main(repo, _head(repo))


def test_the_twin_command_is_the_jailed_print_argv_with_the_host_image(tmp_path):
    from phase_loop_runtime import claude_seat_print as cp

    command = bk.twin_command("print", tmp_path / "claude", model=None, effort=None,
                              session_id="s")
    assert command[0] == str(tmp_path / "claude")
    assert tuple(command[1:1 + len(cp.CLI_DELTA)]) == cp.CLI_DELTA
    assert command[command.index("--tools") + 1] == "default"
    with pytest.raises(ValueError):
        bk.twin_command("sdk", tmp_path / "claude", model=None, effort=None, session_id="s")


def test_the_recorder_records_no_header_query_or_body():
    assert bk.RECORDER.name == "claude_bakeoff_recorder.mjs" and bk.RECORDER.is_file()
    text = bk.RECORDER.read_text()
    recorded = re.findall(r"record\(\{([^}]*)\}\)", text)
    assert recorded and all("header" not in r and "body" not in r and "search" not in r
                            for r in recorded)
    assert "path_template: template(url.pathname)" in text  # never url.search or url.href


# --------------------------------------------------------------------------------------
# The kit.
# --------------------------------------------------------------------------------------

def _plan(repo: Path, **overrides) -> dict:
    plan = {"blocks": list(bk.EXECUTION_NOTES.blocks), "runs_per_block": 3, "meter_readings": 7,
            "settle_s": 300, "timeout_s": 1800, "twins_per_native_block": 1, "sessions": 1,
            "w0_head": _head(repo), "artifact": "bundle.md", "model": "claude-opus-5-5",
            "effort": "high", "board": {
                "president": {"harness": "codex", "model": "gpt-x"},
                "seats": [{"harness": "claude", "model": "claude-opus-5-5", "role": "w0_arm"},
                          {"harness": "codex", "model": "gpt-x"}]}}
    plan.update(overrides)
    return plan


@pytest.mark.parametrize("change", [
    {"runs_per_block": 5}, {"blocks": ["print", "sdk", "t3-sdk-control"] * 2},
    {"meter_readings": 19}, {"settle_s": 60}, {"timeout_s": 3600},
    {"twins_per_native_block": 3}, {"sessions": 2}, {"unknown": 1}, {"w0_head": "main"},
])
def test_a_run_plan_that_differs_from_execution_notes_is_refused(repo, change):
    assert bk.check_run_plan(_plan(repo, **change)) != []
    assert bk.check_run_plan(_plan(repo)) == []


@pytest.mark.parametrize("board", [
    {"president": {"harness": "claude", "model": "claude-fable-5-1"},
     "seats": [{"harness": "claude", "model": "claude-opus-5-5", "role": "w0_arm"}]},
    {"president": {"harness": "codex", "model": "gpt-x"},
     "seats": [{"harness": "claude", "role": "w0_arm"}, {"harness": "claude", "model": "claude-x"}]},
    {"president": {"model": "claude-opus-5-5"}, "seats": [{"harness": "claude", "role": "w0_arm"}]},
    {"seats": []},
])
def test_a_board_using_the_w0_claude_account_is_refused(repo, board):
    assert bk.composition_problems(board) != []


def test_a_president_on_another_operator_account_is_allowed(repo):
    board = {"president": {"harness": "claude", "model": "claude-fable-5-1",
                           "account": "other_operator"},
             "seats": [{"harness": "claude", "role": "w0_arm"}, {"harness": "codex"}]}
    assert bk.composition_problems(board) == []


class _Ledger(bk.MeterLedger):
    def __init__(self, root):
        answers = iter(["10%", "none", "none"] + [f"{10 + i}%", "none", "none"]
                       for i in range(1, 8))
        flat = [a for group in answers for a in group]
        super().__init__(root=root, prompt=lambda _q: flat.pop(0), sleep=lambda _s: None)


def _window(repo, tmp_path, *, native_outcomes, monkeypatch, **kw):
    monkeypatch.setattr(bk, "head_on_main", lambda _r, _h: True)
    outcomes = iter(native_outcomes)
    calls: list[tuple[str, int]] = []

    def run_native(arm, timeout):
        calls.append((arm, timeout))
        return next(outcomes)

    def run_control(block, n):
        return json.dumps({"entrypoint": "sdk-ts", "api_key_source": "none",
                           "model": "claude-opus-5-5", "canonical_output": "admitted",
                           "verdict": "AGREE", "cli_version": "2.1.318"}).encode()

    (repo / ct.DECISION_RECORD).write_text(RECORD_4A + SDK_4B)
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qam", "4b")
    window = bk.Window(plan=_plan(repo), out_dir=tmp_path / "w0", ledger=_Ledger(tmp_path / "private"),
                       token=TOKEN, repo=repo, native=run_native, control=run_control,
                       twin=lambda block, arm: _set(), report=lambda _m: None, **kw)
    return window, calls


def _ok(**overrides):
    return bk.RunOutcome(**{"canonical_output": "admitted",
                            "admission": {p: "pass" for p in bk.ADMISSION_PREDICATES},
                            "item7": {p: "pass" for p in bk.ITEM7_PREDICATES},
                            "claude_api_key_source": "none", "jail_profile_digest": TUI,
                            **overrides})


def test_the_kit_writes_eighteen_valid_records_over_six_blocks(repo, tmp_path, monkeypatch):
    sdk = _ok(dependency_projection_digest="e" * 64)
    window, calls = _window(repo, tmp_path, monkeypatch=monkeypatch,
                            native_outcomes=[_ok()] * 3 + [sdk] * 6 + [_ok()] * 3)
    written = window.run()
    assert len(written) == 18
    assert [arm for arm, _t in calls] == ["print"] * 3 + ["sdk"] * 6 + ["print"] * 3
    assert all(timeout == 1800 for _a, timeout in calls)
    assert validate(tmp_path / "w0", repo, "--tui-digest", TUI) == 0
    readings = json.loads((tmp_path / "private" / "meter.json").read_text())
    assert len(readings) == 7
    assert (tmp_path / "private" / "meter.json").stat().st_mode & 0o777 == 0o600
    for path in written:
        assert "10%" not in path.read_text()  # readings stay private; records carry a digest


def test_a_security_outcome_stops_the_arm_and_publishes_only_withheld(repo, tmp_path, monkeypatch):
    leak = _ok(canonical_output="refused", code="claude_seat_token_in_output")
    sdk = _ok(dependency_projection_digest="e" * 64)
    window, calls = _window(repo, tmp_path, monkeypatch=monkeypatch,
                            native_outcomes=[_ok(), leak] + [sdk] * 6)
    written = window.run()
    print_records = [json.loads(p.read_text()) for p in written if "w0-b1-" in p.name or "w0-b6-" in p.name]
    assert [r["security_outcome"] for r in print_records] == ["none", "withheld_private"]
    assert all("claude_seat_token_in_output" not in json.dumps(r) for r in print_records)
    assert [arm for arm, _t in calls].count("print") == 2  # block 6 never ran
    private = (tmp_path / "private" / "security-outcomes.txt").read_text()
    assert "claude_seat_token_in_output" in private
    assert validate(tmp_path / "w0", repo) == 0


def test_a_run_past_its_timeout_records_timed_out(repo, tmp_path, monkeypatch):
    def slow(*_a, **kwargs):
        raise subprocess.TimeoutExpired("phase-loop", kwargs.get("timeout"))

    outcome = bk.run_native("print", _plan(repo), timeout_s=1800, tui_digest=TUI, runner=slow)
    assert outcome.canonical_output == "timed_out"
    record = bk.build_record(arm="print", block=1, n=1, w0_head=_head(repo), outcome=outcome,
                             billing="unknown", meter_digest="d" * 64, request_set=_set(),
                             activation_section_sha256=_section(repo, "4a"))
    assert record["canonical_output"] == "timed_out" and bk.validate_record(record) == []


def test_the_kit_refuses_before_any_run(repo, tmp_path, monkeypatch):
    window, calls = _window(repo, tmp_path, monkeypatch=monkeypatch, native_outcomes=[])
    window.plan = _plan(repo, runs_per_block=5)
    with pytest.raises(ValueError, match="refused before any run"):
        window.run()
    assert calls == [] and not (tmp_path / "private" / "meter.json").exists()
    window.plan = _plan(repo)
    monkeypatch.setattr(bk, "head_on_main", lambda _r, _h: False)
    with pytest.raises(ValueError, match="not on main"):
        window.run()


def test_billing_follows_the_meter_bracket(tmp_path):
    answers = ["10%", "$0", "$0", "20%", "$0", "$0", "20%", "$5", "$0", "20%", "$5", "$9",
               "20%", "$5", "$9"]
    ledger = bk.MeterLedger(root=tmp_path / "p", prompt=lambda _q: answers.pop(0),
                            sleep=lambda _s: None)
    for index in range(5):
        ledger.read(index, settle_s=300)
    assert [ledger.billing(block) for block in (1, 2, 3, 4)] == [
        "subscription", "extra_usage", "api", "unknown"]
    assert ledger.digest(1) != ledger.digest(2)
    # The digest is salted with a private salt, so a public record cannot be checked
    # against guessed readings.
    bracket = json.dumps(ledger.readings[0:2], sort_keys=True).encode()
    assert ledger.digest(1) != hashlib.sha256(bracket).hexdigest()
    assert (tmp_path / "p" / "meter.salt").stat().st_mode & 0o777 == 0o600


def test_the_native_outcome_reads_only_closed_values():
    board = {"legs": [{"leg": "claude", "status": "OK", "detail": None, "text": "secret review",
                       "broker_evidence": {"claude_admission": {"outcome": "admitted"},
                                           "claude_api_key_source": "none",
                                           "claude_code_entrypoint": "unset",
                                           "seat_jail_profile_digest": TUI}}]}
    outcome = bk.native_outcome(board, timed_out=False, tui_digest=TUI)
    assert outcome.canonical_output == "admitted" and "secret" not in repr(outcome)
    refused = copy.deepcopy(board)
    refused["legs"][0].update(status="DEGRADED", detail="claude_seat_stream_unsafe")
    assert bk.native_outcome(refused, timed_out=False, tui_digest=TUI).code == "claude_seat_stream_unsafe"


def test_the_control_brief_names_the_w0_account_child_and_the_closed_file():
    brief = bk.control_brief(2, {"w0_head": "c" * 40, "model": "claude-opus-5-5", "effort": "high"})
    assert "W0 account" in brief and "own model is not on the W0 account" in brief
    for name in bk.CONTROL_FIELDS:
        assert name in brief


@pytest.mark.parametrize("data", [
    {"entrypoint": "sdk-ts", "api_key_source": "none", "model": "m", "canonical_output": "ok",
     "verdict": "AGREE", "cli_version": "1.2.3"},
    {"entrypoint": "sdk-ts", "api_key_source": "none", "model": "m",
     "canonical_output": "admitted", "verdict": "AGREE", "cli_version": "1.2.3", "extra": 1},
    {"entrypoint": "Not A Slug", "api_key_source": "none", "model": "m",
     "canonical_output": "admitted", "verdict": "AGREE", "cli_version": "1.2.3"},
])
def test_a_malformed_control_file_is_refused(data):
    with pytest.raises(ValueError):
        bk.ingest_control(json.dumps(data).encode())
