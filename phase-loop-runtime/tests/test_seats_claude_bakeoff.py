"""SEATS CLAUDE lane D: the W0 bake-off record, V7 and the W0 kit (IF-0-CLAUDE-2, EC-CLAUDE-5).

Every control enters through ``claude_bakeoff validate`` (the CLI's ``main``) on a disposable
record directory and git repository, or through the kit's own entry points, and each must
fail. Nothing here runs a provider: the kit's board runs, meter readings and control files
are stand-ins, which is the point -- W0 itself is an owner action.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import textwrap
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
    (root / "docs").mkdir()
    (root / "docs" / "bundle.md").write_text("# The W0 review bundle\n")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "seed")
    _publish(root)
    return root


def _publish(repo: Path) -> None:
    """Put the current HEAD on this disposable repository's ``main``."""
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")


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
    ("127.1", "host"),
    ("10.1.2", "host"),
    ("0x7f.1", "host"),
    ("/api/organizations/acme-corp/usage", "path"),
    ("/u/first.last/profile", "path"),
    ("/v1/users/someone/settings", "path"),
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
    _publish(repo)
    record = native(repo, block=3, arm="sdk")
    assert validate(write(tmp_path / "w0", record), repo, "--tui-digest", TUI) == 0


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
    assert bk.validate_directory(directory, repo=repo, record_text=wrong.encode(),
                                 tui_digest=TUI) != []
    assert bk.validate_directory(directory, repo=repo, record_text=right.encode(),
                                 tui_digest=TUI) == []


@pytest.mark.parametrize("entry", ["capture.jsonl", "meter.txt", "sub/raw.json", "link.json",
                                   "w0-b1-r1.json.bak", "notes.md"])
def test_v7_refuses_anything_but_records_and_the_readme(repo, tmp_path, entry):
    directory = write(tmp_path / "w0", native(repo))
    (directory / "README.md").write_text("# W0\n")
    target = directory / entry
    target.parent.mkdir(parents=True, exist_ok=True)
    if entry == "link.json":
        target.symlink_to(directory / "w0-b1-r1.json")
    else:
        target.write_text("Authorization: Bearer x\n")
    assert validate(directory, repo, "--tui-digest", TUI) == 1


def test_v7_derives_the_tui_digest_per_w0_head_when_none_is_given(repo, tmp_path):
    """V7 as the plan writes it (no --tui-digest) checks every native record against its
    head's TUI digest; one it cannot derive fails, never passes."""
    directory = write(tmp_path / "w0", native(repo))
    seen: list[str] = []

    def derive(_repo, head):
        seen.append(head)
        return frozenset({TUI, "b" * 64})

    assert bk.validate_directory(directory, repo=repo, tui_digests=derive) == []
    assert seen == [_head(repo)]
    assert bk.validate_directory(directory, repo=repo,
                                 tui_digests=lambda _r, _h: frozenset({"b" * 64})) != []
    assert bk.validate_directory(directory, repo=repo,
                                 tui_digests=lambda _r, _h: frozenset()) != []
    assert validate(directory, repo) == 1  # this disposable head carries no runtime source


RUNTIME = "phase-loop-runtime/src/phase_loop_runtime"


def _runtime_head(repo: Path, tmp_path: Path, *, jail_source: bytes | None = None) -> tuple[str, Path]:
    """A commit carrying this runtime's own ``seat_jail.py`` (or ``jail_source``) and a
    package ``__init__`` that, if anything ever ran it, would write a marker file."""
    marker = tmp_path / "executed.marker"
    package = repo / RUNTIME
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n")
    own = Path(bk.__file__).with_name("seat_jail.py").read_bytes()
    (package / "seat_jail.py").write_bytes(jail_source if jail_source is not None else own)
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "runtime")
    return _head(repo), marker


def _host_digests() -> frozenset[str]:
    from phase_loop_runtime import seat_jail

    return frozenset(seat_jail.jail_profile_digest("claude", arch) for arch in bk.ARCHES)


def test_v7_through_the_documented_cli_refuses_a_wrong_but_consistent_digest(repo, tmp_path):
    """The exact V7 command (no --tui-digest) on records at a head on main whose jail source
    is this runtime's: the digest it derives is accepted, a uniformly wrong one is refused,
    and nothing of that head runs."""
    head, marker = _runtime_head(repo, tmp_path)
    _publish(repo)
    assert bk.tui_digests_at(repo, head) == _host_digests()
    right = sorted(_host_digests())[0]
    for digest, expected in ((right, 0), ("0" * 64, 1)):
        record = {**native(repo), "w0_head": head, "jail_profile_digest": digest}
        directory = write(tmp_path / f"w0-{expected}", record)
        assert bk.main(["validate", str(directory), "--repo", str(repo)]) == expected
    assert not marker.exists()


def test_v7_refuses_a_head_off_main_and_runs_none_of_its_code(repo, tmp_path):
    """A record naming a commit that is not on main, whose own jail source would vouch for
    the record's digest, fails V7, with or without --tui-digest; that commit never runs."""
    head, marker = _runtime_head(repo, tmp_path)
    record = {**native(repo), "w0_head": head, "jail_profile_digest": sorted(_host_digests())[0]}
    directory = write(tmp_path / "w0", record)
    problems = bk.validate_directory(directory, repo=repo)
    assert "a record's W0 head is not on main" in problems
    assert validate(directory, repo) == 1
    assert validate(directory, repo, "--tui-digest", record["jail_profile_digest"]) == 1
    assert not marker.exists()


def test_v7_will_not_derive_from_a_head_whose_jail_source_differs(repo, tmp_path):
    """On main, but with a jail source other than this runtime's: V7 cannot derive the digest
    without running that head, so it fails; --tui-digest remains the no-execution path."""
    own = Path(bk.__file__).with_name("seat_jail.py").read_bytes()
    head, marker = _runtime_head(repo, tmp_path, jail_source=own + b"\n# changed\n")
    _publish(repo)
    assert bk.tui_digests_at(repo, head) == frozenset()
    record = {**native(repo), "w0_head": head, "jail_profile_digest": TUI}
    directory = write(tmp_path / "w0", record)
    assert validate(directory, repo) == 1
    assert validate(directory, repo, "--tui-digest", TUI) == 0
    assert not marker.exists()


def test_v7_will_not_derive_when_another_form_could_shadow_the_jail_source(repo, tmp_path):
    head, _marker = _runtime_head(repo, tmp_path)
    (repo / RUNTIME / "seat_jail").mkdir()
    (repo / RUNTIME / "seat_jail" / "__init__.py").write_text("")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "package")
    _publish(repo)
    assert bk.tui_digests_at(repo, _head(repo)) == frozenset()


def test_the_jail_digest_reads_only_the_declared_sources():
    """Computing the TUI digest loads, of this package, only its ``__init__`` and
    JAIL_PROFILE_SOURCES; a new dependency must be declared there."""
    code = textwrap.dedent("""
        import json, os, sys
        package = os.path.join(sys.argv[1], "phase_loop_runtime")
        opened = set()

        def hook(event, args):
            if event == "open" and isinstance(args[0], str):
                path = os.path.abspath(args[0])
                if path.startswith(package + os.sep) and "__pycache__" not in path:
                    opened.add(os.path.relpath(path, package))

        sys.addaudithook(hook)
        sys.path.insert(0, sys.argv[1])
        from phase_loop_runtime import seat_jail
        for arch in ("x86_64", "aarch64"):
            seat_jail.jail_profile_digest("claude", arch)
        loaded = {os.path.relpath(m.__file__, package) for name, m in list(sys.modules.items())
                  if name.startswith("phase_loop_runtime") and getattr(m, "__file__", None)}
        print(json.dumps(sorted(opened | loaded)))
    """)
    source = str(Path(bk.__file__).resolve().parents[1])
    done = subprocess.run([sys.executable, "-I", "-B", "-c", code, source], capture_output=True,
                          text=True, timeout=120, check=True)
    assert set(json.loads(done.stdout)) <= {"__init__.py", *bk.JAIL_PROFILE_SOURCES}


# --------------------------------------------------------------------------------------
# The capture twin and the recorder's output.
# --------------------------------------------------------------------------------------

def _rec(*lines: dict, summary: bool = True) -> bytes:
    connections = sum(1 for line in lines if line.get("kind") == "connection")
    tail = [{"kind": "summary", "accepted": connections, "recorded": connections}] if summary else []
    return b"".join(json.dumps(line).encode() + b"\n" for line in (*lines, *tail))


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
    {"kind": "summary", "accepted": 1, "recorded": 1, "hosts": ["x"]},
    {"kind": "unattributed", "host": "api.anthropic.com"},
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


@pytest.mark.parametrize("name, raw, returncode", [
    ("empty-capture", b"", 0),
    ("summary-only", _rec(), 0),
    ("requests-without-connections", _rec(REQUEST), 0),
    ("no-summary", _rec(REQUEST, DONE, summary=False), 0),
    ("accepted-not-all-recorded", _rec(REQUEST, DONE, summary=False)
     + b'{"kind":"summary","accepted":2,"recorded":1}\n', 0),
    ("unattributed-request", _rec(REQUEST, {"kind": "unattributed"}, DONE), 0),
    ("twin-failed", _rec(REQUEST, DONE), 1),
    ("twin-timed-out", _rec(REQUEST, DONE), None),
])
def test_complete_fails_closed(name, raw, returncode):
    result = bk.ingest_recorder_output(raw, token=TOKEN, twin_returncode=returncode)
    assert result["completeness"] == "partial", name


@pytest.mark.parametrize("line", [
    {**REQUEST, "host": "api.internal"},
    {**REQUEST, "host": "10.0.0.5"},
    {**REQUEST, "host": "my_host.example.com"},
    {**REQUEST, "method": "PROPFIND"},
])
def test_a_request_that_cannot_be_published_makes_the_set_partial_and_stays_private(line):
    dropped: list[str] = []
    result = bk.ingest_recorder_output(_rec(REQUEST, line, DONE), token=TOKEN, dropped=dropped)
    assert result["completeness"] == "partial"
    assert result["entries"] == [{k: v for k, v in REQUEST.items() if k != "kind"}]
    assert len(dropped) == 1 and line["host"] in dropped[0]


def test_an_oversized_path_template_makes_the_set_partial_and_stays_private():
    dropped: list[str] = []
    line = {**REQUEST, "path_template": "/" + "a" * 513}
    result = bk.ingest_recorder_output(_rec(REQUEST, line, DONE), token=TOKEN, dropped=dropped)
    assert result["completeness"] == "partial"
    assert result["entries"] == [{k: v for k, v in REQUEST.items() if k != "kind"}]
    assert dropped == ["path-template-too-long"]


def _jail_env():
    from phase_loop_runtime import seat_jail

    return seat_jail.seat_env("claude", token_fd=9)


PROXY = "http://srt:" + "t" * 24 + "@127.0.0.1:41000"


def _twin(tmp_path):
    jail = _jail_env()
    home, bin_dir, ca_root = tmp_path / "home", tmp_path / "bin", tmp_path / "ca"
    env = bk.twin_environment(jail, home=home, proxy=PROXY, ca=ca_root / "ca.crt",
                              bin_dir=bin_dir)
    return jail, env, {"home": home, "bin_dir": bin_dir, "ca_root": ca_root}


def test_the_twin_environment_is_the_declared_delta_only(tmp_path):
    jail, env, where = _twin(tmp_path)
    assert bk.twin_delta_problems(jail, env, **where) == []
    assert set(env) - set(jail) == bk.TWIN_DELTA_KEYS
    assert env["HOME"] == str(tmp_path / "home") and env[
        "CLAUDE_CONFIG_DIR"] == str(tmp_path / "home" / ".claude")


@pytest.mark.parametrize("widen", [
    lambda env, home: env.update(ANTHROPIC_BASE_URL="https://example.invalid"),
    lambda env, home: env.update(CLAUDE_CODE_USE_BEDROCK="1"),
    lambda env, home: env.update(DISABLE_AUTOUPDATER="0"),
    lambda env, home: env.pop("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"),
    lambda env, home: env.pop("NODE_EXTRA_CA_CERTS"),
    lambda env, home: env.update(HOME=str(Path.home())),
    lambda env, home: env.update(CLAUDE_CONFIG_DIR=str(Path.home() / ".claude")),
    lambda env, home: env.update(XDG_CONFIG_HOME=str(home) + "/../elsewhere"),
    lambda env, home: env.update(PATH="/usr/local/bin:/usr/bin:/bin"),
    lambda env, home: env.update(HTTPS_PROXY="http://evil.example:1"),
    lambda env, home: env.update(HTTPS_PROXY="http://srt:x@127.0.0.1:1"),
    lambda env, home: env.update(NODE_EXTRA_CA_CERTS="/etc/ssl/certs/ca-certificates.crt"),
])
def test_a_twin_environment_beyond_the_declared_delta_fails(tmp_path, widen):
    jail, env, where = _twin(tmp_path)
    widen(env, where["home"])
    assert bk.twin_delta_problems(jail, env, **where) != []


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


def test_the_disposable_bundle_is_a_real_copy_with_no_link_to_the_repository(repo, tmp_path):
    head = _head(repo)
    bundle = bk.disposable_bundle(repo, head, tmp_path / "bundle")
    assert (bundle / "docs" / "bundle.md").read_text() == "# The W0 review bundle\n"
    assert (bundle / ".git").is_dir()  # its own repository, not a linked worktree's .git file
    common = _git(bundle, "rev-parse", "--path-format=absolute", "--git-common-dir")
    assert Path(common).resolve() == (bundle / ".git").resolve()
    assert _git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    (bundle / "new.txt").write_text("x")
    _git(bundle, "add", "-A")
    _git(bundle, "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@e.st",
         "commit", "-qm", "from the twin")
    assert _head(repo) == head and "from the twin" not in _git(repo, "log", "--all", "--oneline")


def _pid_gone(pid: int, wait_s: float = 10.0) -> bool:
    import time

    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            with open(f"/proc/{pid}/stat") as handle:
                if handle.read().split(") ", 1)[1].startswith("Z"):
                    return True
        except FileNotFoundError:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("timeout_s, expected", [(30, 0), (1, None)])
def test_the_twin_launch_kills_its_whole_group_on_every_exit(tmp_path, timeout_s, expected):
    import os
    import sys

    pidfile = tmp_path / "child.pid"
    script = ("import subprocess, sys, time; child = subprocess.Popen(['sleep', '120']); "
              "open(sys.argv[1], 'w').write(str(child.pid)); "
              "time.sleep(float(sys.argv[2]))")
    read_fd, write_fd = os.pipe()
    try:
        returncode = bk.launch_capture_twin(
            [sys.executable, "-c", script, str(pidfile), "0" if expected == 0 else "60"],
            cwd=tmp_path, env=dict(os.environ), token_fd=read_fd, prompt=b"", timeout_s=timeout_s)
    finally:
        os.close(read_fd)
        os.close(write_fd)
    assert returncode == expected
    assert _pid_gone(int(pidfile.read_text()))


def test_the_twin_launch_reaps_a_descendant_that_starts_another_session(tmp_path):
    import os
    import sys

    pidfile = tmp_path / "descendant.pid"
    descendant = ("import os, sys, time; os.setsid(); "
                  "open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(120)")
    parent = ("import subprocess, sys, time; "
              "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); "
              "time.sleep(0.5)")
    read_fd, write_fd = os.pipe()
    try:
        returncode = bk.launch_capture_twin(
            [sys.executable, "-c", parent, descendant, str(pidfile)], cwd=tmp_path,
            env=dict(os.environ), token_fd=read_fd, prompt=b"", timeout_s=30)
    finally:
        os.close(read_fd)
        os.close(write_fd)
    assert returncode == 0
    assert _pid_gone(int(pidfile.read_text()))


def test_a_ca_left_by_an_earlier_window_refuses(tmp_path):
    ca_dir = tmp_path / "twin-ca"
    ca_dir.mkdir()
    with pytest.raises(ValueError, match="earlier window"):
        bk.create_window_ca(ca_dir, "node", tmp_path / "srt.js")
    assert ca_dir.is_dir()


def test_the_recorder_records_no_header_query_or_body():
    assert bk.RECORDER.name == "claude_bakeoff_recorder.mjs" and bk.RECORDER.is_file()
    text = bk.RECORDER.read_text()
    recorded = re.findall(r"record\(\{([^}]*)\}\)", text)
    assert recorded and all("header" not in r and "body" not in r and "search" not in r
                            for r in recorded)
    assert "path_template: template(url.pathname)" in text  # never url.search or url.href
    assert "parsedHosts" not in text  # completeness is never inferred from a host counter


# --------------------------------------------------------------------------------------
# The recorder, end to end on the pinned srt with a local TLS client.
# --------------------------------------------------------------------------------------

def _srt():
    from phase_loop_runtime import seat_egress_proxy

    try:
        return seat_egress_proxy.verify_install(), seat_egress_proxy._node()
    except Exception as exc:  # noqa: BLE001 -- any missing prerequisite skips
        pytest.skip(f"the pinned srt install is unavailable: {type(exc).__name__}")


class _Recorder:
    def __init__(self, tmp_path):
        import os

        from phase_loop_runtime import seat_egress_proxy

        index, node = _srt()
        self.ca = tmp_path / "ca"
        self.ca.mkdir(mode=0o700)
        subprocess.run([node, str(seat_egress_proxy._data_path("ca.mjs")), str(index),
                        str(self.ca)], check=True, capture_output=True, timeout=120)
        self.out = tmp_path / "capture.jsonl"
        config = tmp_path / "recorder.json"
        config.write_text(json.dumps({"ca_cert": str(self.ca / "ca.crt"),
                                      "ca_key": str(self.ca / "ca.key"), "out": str(self.out)}))
        self.process = subprocess.Popen([node, str(bk.RECORDER), str(index), str(config)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                        start_new_session=True, env=dict(os.environ))
        ready = json.loads(self.process.stdout.readline())
        self.port, self.token = int(ready["port"]), ready["token"]

    def tunnel(self, host: str):
        import base64
        import socket

        sock = socket.create_connection(("127.0.0.1", self.port), timeout=30)
        auth = base64.b64encode(f"srt:{self.token}".encode()).decode()
        sock.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                     f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            chunk = sock.recv(4096)
            assert chunk, "the recorder closed the tunnel"
            reply += chunk
        assert reply.startswith(b"HTTP/1.1 200")
        return sock

    def request(self, host: str) -> None:
        import ssl

        context = ssl.create_default_context(cafile=str(self.ca / "ca.crt"))
        with context.wrap_socket(self.tunnel(host), server_hostname=host) as tls:
            tls.sendall(f"GET /v1/models HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
                        .encode())
            while tls.recv(4096):
                pass

    def hello_then_close(self, host: str):
        """A matching ClientHello, then nothing: the handshake never finishes."""
        import ssl

        context = ssl.create_default_context(cafile=str(self.ca / "ca.crt"))
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        tls = context.wrap_bio(incoming, outgoing, server_hostname=host)
        try:
            tls.do_handshake()
        except ssl.SSLWantReadError:
            pass
        sock = self.tunnel(host)
        sock.sendall(outgoing.read())
        return sock

    def finish(self) -> bytes:
        self.process.stdin.close()
        self.process.wait(timeout=60)
        return self.out.read_bytes()


def test_live_recorder_concurrent_connections_to_one_host_never_vouch_for_each_other(tmp_path):
    """One connection completes a request while another to the same host stops after its
    ClientHello: the set is partial, never complete."""
    recorder = _Recorder(tmp_path)
    try:
        stalled = recorder.hello_then_close("w0-recorder-test.example")
        recorder.request("w0-recorder-test.example")
        stalled.close()
        raw = recorder.finish()
    finally:
        recorder.process.kill()
    lines = [json.loads(line) for line in raw.splitlines()]
    assert [line["kind"] for line in lines].count("connection") == 2
    assert lines[-1] == {"kind": "summary", "accepted": 2, "recorded": 2}
    assert bk.ingest_recorder_output(raw, token=TOKEN)["completeness"] == "partial"


def test_live_recorder_records_a_connection_still_open_at_shutdown(tmp_path):
    """A connection the client never closes is still recorded, as not parsed, so every
    accepted connection appears exactly once and the set is partial."""
    recorder = _Recorder(tmp_path)
    try:
        held = recorder.hello_then_close("w0-recorder-test.example")
        raw = recorder.finish()
        held.close()
    finally:
        recorder.process.kill()
    lines = [json.loads(line) for line in raw.splitlines()]
    assert {"kind": "connection", "terminated": True, "parsed": False} in lines
    assert lines[-1] == {"kind": "summary", "accepted": 1, "recorded": 1}
    assert bk.ingest_recorder_output(raw, token=TOKEN)["completeness"] == "partial"


def test_live_recorder_one_parsed_connection_alone_is_complete(tmp_path):
    recorder = _Recorder(tmp_path)
    try:
        recorder.request("w0-recorder-test.example")
        raw = recorder.finish()
    finally:
        recorder.process.kill()
    result = bk.ingest_recorder_output(raw, token=TOKEN)
    assert result["completeness"] == "complete"
    assert result["entries"] == [{"method": "GET", "host": "w0-recorder-test.example",
                                  "path_template": "/v1/models"}]


# --------------------------------------------------------------------------------------
# The kit.
# --------------------------------------------------------------------------------------

SEATS = ["grok:grok-4.7:high:adversarial", "claude:claude-opus-5-5:high:correctness",
         "codex:gpt-6-astra:high:red-team", "gemini:gemini-4-argon:medium:alternative-approach"]


def _plan(repo: Path, **overrides) -> dict:
    plan = {"blocks": list(bk.EXECUTION_NOTES.blocks), "runs_per_block": 3, "meter_readings": 7,
            "settle_s": 300, "timeout_s": 1800, "twins_per_native_block": 1, "sessions": 1,
            "w0_head": _head(repo), "artifact": "docs/bundle.md", "model": "claude-opus-5-5",
            "effort": "high", "board": {"seats": list(SEATS)}}
    plan.update(overrides)
    return plan


@pytest.mark.parametrize("change", [
    {"runs_per_block": 5}, {"blocks": ["print", "sdk", "t3-sdk-control"] * 2},
    {"meter_readings": 19}, {"settle_s": 60}, {"timeout_s": 3600},
    {"twins_per_native_block": 3}, {"sessions": 2}, {"unknown": 1}, {"w0_head": "main"},
    {"landing_tier": "plan"}, {"artifact": "/tmp/untrusted-injection.md"},
    {"artifact": "../outside.md"}, {"artifact": "docs/../docs/bundle.md"},
])
def test_a_run_plan_that_differs_from_execution_notes_is_refused(repo, change):
    assert bk.check_run_plan(_plan(repo, **change)) != []
    assert bk.check_run_plan(_plan(repo)) == []


@pytest.mark.parametrize("board", [
    {"seats": SEATS + ["claude:claude-fable-5-1:high:alternative"]},
    {"seats": SEATS + ["cursor:claude-sonnet-5-5:high:lens"]},
    {"seats": SEATS + ["@claude:claude-opus-5-5:high:other"]},
    {"seats": [s for s in SEATS if not s.startswith("claude:")]},
    {"seats": ["claude:claude-opus-5-5:medium:correctness"]},
    {"seats": SEATS, "president": {"harness": "codex"}},
    {"seats": []},
    {"seats": ["claude"]},
])
def test_a_board_that_would_use_the_w0_account_or_another_model_is_refused(repo, board):
    assert bk.composition_problems(_plan(repo, board=board)) != []
    assert bk.composition_problems(_plan(repo)) == []


def test_preflight_retains_the_host_modes_when_a_board_result_is_unavailable(monkeypatch):
    from phase_loop_runtime.advisor_board import composition

    board = composition.compose_review_board(
        is_available=lambda vendor: vendor in {"claude", "codex", "grok", "gemini"})
    monkeypatch.setattr(composition, "compose_review_board", lambda *args, **kwargs: board)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    assert bk.effective_unconfined_co_seats() == ("codex", "grok")
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_DISABLE", "1")
    assert bk.effective_unconfined_co_seats() == ()


def test_the_artifact_is_read_at_the_w0_head_never_from_the_working_tree(repo):
    head = _head(repo)
    (repo / "docs" / "bundle.md").write_text("an edit that was never committed\n")
    assert bk.bundle_artifact(repo, head, "docs/bundle.md") == b"# The W0 review bundle\n"
    for artifact in ("docs/missing.md", "/etc/passwd", "../x.md"):
        with pytest.raises(ValueError):
            bk.bundle_artifact(repo, head, artifact)


def test_the_checkout_must_be_the_clean_w0_head_running_its_own_runtime(repo):
    head = _head(repo)
    runtime = "checkout: this runtime is not the W0 tree's"
    assert bk.checkout_problems(repo, head) == [runtime]  # the test runtime is not this repo's
    evidence = repo / bk.EVIDENCE_DIR / "w0-b1-r1.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}")
    assert bk.checkout_problems(repo, head) == [runtime]  # W0's own records are allowed
    (repo / "claude_seat_sdk.py").write_text("ADMITTED = True\n")
    assert "checkout: the W0 tree has local changes" in bk.checkout_problems(repo, head)
    (repo / "claude_seat_sdk.py").unlink()
    (repo / "docs" / "bundle.md").write_text("edited\n")
    assert "checkout: the W0 tree has local changes" in bk.checkout_problems(repo, head)
    assert "checkout: the repository is not at the W0 head" in bk.checkout_problems(repo, "f" * 40)


class _Ledger(bk.MeterLedger):
    def __init__(self, root):
        answers = iter(["10%", "none", "none"] + [f"{10 + i}%", "none", "none"]
                       for i in range(1, 8))
        flat = [a for group in answers for a in group]
        super().__init__(root=root, prompt=lambda _q: flat.pop(0), sleep=lambda _s: None)


def _window(repo, tmp_path, *, native_outcomes, monkeypatch, admit_sdk=True, **kw):
    monkeypatch.setattr(bk, "head_on_main", lambda _r, _h: True)
    monkeypatch.setattr(bk, "checkout_problems", lambda _r, _h: [])
    if admit_sdk:
        real = ct.is_admitted
        monkeypatch.setattr(ct, "is_admitted", lambda arm: arm == "sdk" or real(arm))
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
    settings = {"compose": lambda: list(SEATS), "cli_version": "2.1.318", **kw}
    window = bk.Window(plan=_plan(repo), out_dir=tmp_path / "w0", ledger=_Ledger(tmp_path / "private"),
                       token=TOKEN, repo=repo, native=run_native, control=run_control,
                       twin=lambda block, arm: _set(), report=lambda _m: None, **settings)
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
    assert validate(tmp_path / "w0", repo, "--tui-digest", TUI) == 0


@pytest.mark.parametrize("code", sorted(c for c in ct.CODES if ct.od10_class(c) == ct.SECURITY))
def test_a_withheld_record_publishes_no_diagnostic_of_its_outcome(repo, code):
    outcome = _ok(canonical_output="refused", code=code, claude_api_key_source="present",
                  claude_code_entrypoint="cli")
    record = bk.build_record(arm="print", block=1, n=1, w0_head=_head(repo), outcome=outcome,
                             billing="unknown", meter_digest="d" * 64, request_set=_set(),
                             activation_section_sha256=_section(repo, "4a"))
    assert bk.validate_record(record) == []
    assert record["claude_api_key_source"] == "unknown"
    assert record["claude_code_entrypoint"] == "unset"
    assert set(record["admission"].values()) == set(record["item7"].values()) == {"fail"}
    for leak in ({"claude_api_key_source": "present"}, {"claude_code_entrypoint": "cli"},
                 {"admission": {**record["admission"], "jail": "pass"}}):
        assert bk.validate_record({**record, **leak}) != []


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


@pytest.mark.parametrize("miss", ["sdk-not-admitted", "no-4b", "lineup", "cli-version",
                                  "checkout", "artifact"])
def test_every_arm_and_the_lineup_are_checked_before_the_first_meter_reading(
        repo, tmp_path, monkeypatch, miss):
    window, calls = _window(repo, tmp_path, monkeypatch=monkeypatch, native_outcomes=[],
                            admit_sdk=miss != "sdk-not-admitted")
    if miss == "no-4b":
        (repo / ct.DECISION_RECORD).write_text(RECORD_4A)
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-qam", "no 4b")
        window.plan = _plan(repo)
    elif miss == "lineup":
        window.compose = lambda: SEATS[:2] + ["claude:claude-fable-5-1:high:alternative"]
    elif miss == "cli-version":
        window.cli_version = "unknown"
    elif miss == "checkout":
        monkeypatch.setattr(bk, "checkout_problems", lambda _r, _h: ["checkout: changed"])
    elif miss == "artifact":
        window.plan = _plan(repo, artifact="docs/missing.md")
    assert len(window.preflight()) == 1, miss  # the one miss under test, nothing else
    with pytest.raises(ValueError, match="refused before any run"):
        window.run()
    assert calls == [] and not (tmp_path / "private" / "meter.json").exists()


@pytest.mark.parametrize(("changed_on", "message", "native_calls"), [
    (3, "after the capture twin", 0),
    (4, "after the block's runs", 3),
])
def test_a_checkout_change_during_a_native_block_stops_the_window(
        repo, tmp_path, monkeypatch, changed_on, message, native_calls):
    window, calls = _window(
        repo, tmp_path, monkeypatch=monkeypatch, native_outcomes=[_ok()] * 3)
    checks = 0

    def changed(_repo, _head):
        nonlocal checks
        checks += 1
        return ["checkout: changed"] if checks >= changed_on else []

    monkeypatch.setattr(bk, "checkout_problems", changed)
    with pytest.raises(ValueError, match=message):
        window.run()
    assert len(calls) == native_calls


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


# --------------------------------------------------------------------------------------
# The native runner reads the board's real output and its observation, nothing else.
# --------------------------------------------------------------------------------------

HEAD = "c" * 40


def _expected(**overrides) -> bk.NativeExpectation:
    values = {"arm": "print", "w0_head": HEAD, "tui_digest": TUI, "seats": tuple(SEATS),
              "model": "claude-opus-5-5", "staged_path_sha256": bk.staged_path_sha256(
                  "docs/bundle.md"), "cli_version": "2.1.318",
              "co_seats_unconfined": ("codex",)}
    values.update(overrides)
    return bk.NativeExpectation(**values)


def _payload(status="OK", detail=None, seats=SEATS, unconfined=("codex",)) -> dict:
    """The field set `phase-loop advisor-board --json` emits (cli.py): no broker evidence."""
    legs = [{"seat_key": key, "leg": key.split(":")[0], "status": status if key.startswith(
        "claude:") else "OK", "detail": detail if key.startswith("claude:") else None,
        "text": "the review text", "needs_native_agent": None, "notices": []} for key in seats]
    modes = [{"seat_key": key, "leg": key.split(":")[0],
              "mode": "unconfined" if key.split(":")[0] in unconfined else "jailed"}
             for key in seats]
    return {"composition": {"seats": list(seats), "excluded": []}, "seat_modes": modes,
            "legs": legs, "notices": [], "usable": True}


def _seen(**overrides) -> dict:
    observation = {
        "schema": ct.W0_OBSERVATION_SCHEMA, "transport": "print", "status": "ok", "code": None,
        "admission": "admitted", "api_key_source": "none", "entrypoint": "unset",
        "filesystem_confined": True, "jail_profile_digest": TUI,
        "dependency_projection_digest": None, "token_pipe": True,
        "login_proof": ["login", "oauth_token", "none"], "staged_source_commit": HEAD,
        "session_matches": True, "result_count": 1, "model": "claude-opus-5-5",
        "diagnostics_valid": True, "diagnostics_truncated": False, "model_status": "match",
        "read_path_sha256": [bk.staged_path_sha256("docs/bundle.md")],
    }
    observation.update(overrides)
    return observation


def test_the_real_payload_alone_proves_nothing():
    """The board's own JSON carries no broker evidence: without an observation an OK leg is
    absent and every predicate fails."""
    outcome = bk.native_outcome(_payload(), [], timed_out=False, expected=_expected())
    assert outcome.canonical_output == "absent"
    assert set(outcome.admission.values()) == set(outcome.item7.values()) == {"fail"}
    assert outcome.cli_version == "2.1.318" and outcome.co_seats_unconfined == ("codex",)
    assert "the review text" not in repr(outcome)


def test_an_observed_jailed_run_admits_with_every_predicate_from_its_own_field():
    outcome = bk.native_outcome(_payload(), [_seen()], timed_out=False, expected=_expected())
    assert outcome.canonical_output == "admitted" and outcome.code == "none"
    assert set(outcome.admission.values()) == set(outcome.item7.values()) == {"pass"}
    assert outcome.jail_profile_digest == TUI and outcome.claude_api_key_source == "none"


@pytest.mark.parametrize("change, failed", [
    ({"jail_profile_digest": "b" * 64}, {"jail"}),
    ({"staged_source_commit": "d" * 40}, {"staged_clone"}),
    ({"token_pipe": False}, {"token_pipe"}),
    ({"login_proof": ["login", "api_key", "none"]}, {"login_proof", "subscription"}),
    ({"api_key_source": "present"}, {"init_api_key_source_none", "subscription"}),
    ({"session_matches": False}, {"session_matches", "session"}),
    ({"result_count": 2}, {"single_result", "result"}),
    ({"diagnostics_truncated": True}, {"seat_diagnostics"}),
    ({"model": "claude-sonnet-5-5"}, {"exact_model_match"}),
    ({"read_path_sha256": ["e" * 64]}, {"staged_path_digest"}),
    ({"read_path_sha256": []}, {"staged_path_digest", "read_completed"}),
    ({"admission": "absent"}, {"result_success", "exit_zero", "verdict_conforming", "result",
                               "exit", "verdict"}),
])
def test_each_predicate_fails_on_its_own_evidence(change, failed):
    outcome = bk.native_outcome(_payload(), [_seen(**change)], timed_out=False,
                                expected=_expected())
    observed = {name for group in (outcome.admission, outcome.item7)
                for name, value in group.items() if value == "fail"}
    assert observed == failed


@pytest.mark.parametrize("change", [{"transport": "tui"}, {"filesystem_confined": False},
                                    {"jail_profile_digest": None}])
def test_an_unconfined_or_other_transport_run_is_absent_never_admitted(change):
    outcome = bk.native_outcome(_payload(), [_seen(**change)], timed_out=False,
                                expected=_expected())
    assert outcome.canonical_output == "absent"
    assert set(outcome.admission.values()) == {"fail"}


def test_two_observations_for_one_run_prove_nothing():
    outcome = bk.native_outcome(_payload(), [_seen(), _seen()], timed_out=False,
                                expected=_expected())
    assert outcome.canonical_output == "absent"


def test_a_refusal_keeps_its_typed_code():
    seen = _seen(status="degraded", admission="refused", code="claude_seat_stream_unsafe")
    outcome = bk.native_outcome(_payload(status="DEGRADED", detail="claude_seat_stream_unsafe"),
                                [seen], timed_out=False, expected=_expected())
    assert (outcome.canonical_output, outcome.code) == ("refused", "claude_seat_stream_unsafe")


def test_a_seat_deadline_is_recorded_as_timed_out():
    seen = _seen(status="timeout", admission="timed_out", code="claude_seat_result_unproven")
    outcome = bk.native_outcome(
        _payload(status="TIMEOUT", detail="claude_seat_result_unproven"), [seen],
        timed_out=False, expected=_expected())
    assert outcome.canonical_output == "timed_out"
    assert outcome.code == "claude_seat_result_unproven"


def test_a_board_that_ran_another_lineup_stops_the_window():
    with pytest.raises(ValueError, match="another lineup"):
        bk.native_outcome(_payload(seats=SEATS[:3] + ["gemini:gemini-4-argon:high:x"]),
                          [_seen()], timed_out=False, expected=_expected())


def test_the_runner_launches_this_trees_board_from_the_w0_checkout(repo, tmp_path):
    """Through run_native: the command, cwd, selector and observation channel are bound; the
    fake board writes its observation through the transport module's real writer."""
    import sys

    seen: dict = {}

    def board(command, *, cwd, env, timeout_s, pass_fds):
        seen.update(command=command, cwd=cwd, env=env, timeout_s=timeout_s,
                    pass_fds=pass_fds)
        evidence = {"claude_admission": {"outcome": "admitted", "code": "none"},
                    "claude_api_key_source": "none", "claude_code_entrypoint": "unset",
                    "sandbox_filesystem_confined": True, "claude_login_source": "login",
                    "claude_login_auth_method": "oauth_token",
                    "claude_login_api_key_source": "none", "claude_session_id_matches": True,
                    "claude_result_count": 1, "provider_model": "claude-opus-5-5",
                    "claude_item7_diagnostics": {"valid": True, "truncated": False,
                                                 "model_status": "match", "tools": [
                                                     {"path_sha256": bk.staged_path_sha256(
                                                         "docs/bundle.md"), "read_completed": True}]}}
        jail = type("J", (), {"profile_digest": TUI, "dependency_projection_digest": "",
                              "env": {"CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR": "3"}})()
        stage = tmp_path / "stage" / "reviewed-tree" / ".git"
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "phase-loop-source-commit").write_text(HEAD + "\n")
        seat = type("S", (), {"jail": jail, "review_dir": tmp_path / "stage"})()
        import os

        assert pass_fds == (int(env[ct.W0_OBSERVATION_ENV]),)
        os.environ[ct.W0_OBSERVATION_ENV] = env[ct.W0_OBSERVATION_ENV]
        try:
            ct._record_w0_observation("print", seat, evidence, ("OK", "x"), None,
                                      ct._staged_source_commit(seat))
        finally:
            del os.environ[ct.W0_OBSERVATION_ENV]
        return json.dumps(_payload())

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    outcome = bk.run_native("print", repo=repo, artifact_copy=private / "bundle.md",
                            observations=private / "observations.jsonl",
                            expected=_expected(), timeout_s=1800, runner=board)
    assert seen["command"][:4] == [sys.executable, "-m", "phase_loop_runtime.cli", "advisor-board"]
    assert seen["command"][4] == str(private / "bundle.md") and "--landing-tier" not in seen["command"]
    assert seen["cwd"] == repo and seen["timeout_s"] == 1800
    assert seen["env"][ct.ROUTE_ENV] == "print"
    assert seen["pass_fds"] == (int(seen["env"][ct.W0_OBSERVATION_ENV]),)
    assert json.loads(seen["env"][ct.W0_LINEUP_ENV]) == list(SEATS)
    assert outcome.canonical_output == "admitted"
    assert set(outcome.admission.values()) == {"pass"}


def _board_cli(monkeypatch, tmp_path, repo, *, pin_from_composed):
    """``advisor-board`` through the real CLI and the real ``invoke_board``, with the composer
    over a fixed availability and every seat launch counted, never run."""
    from phase_loop_runtime import cli
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.advisor_board import composition

    real = composition.compose_review_board
    board = real(is_available=lambda vendor: vendor in {"claude", "codex", "grok", "gemini"})
    monkeypatch.setattr(composition, "compose_review_board", lambda *a, **k: board)
    launches: list[str] = []

    def spawn(leg, artifact, **kwargs):
        launches.append(leg)
        return "UNAVAILABLE", "counted, not run"

    monkeypatch.setattr(pi, "_default_spawn", spawn)
    monkeypatch.setenv(ct.W0_LINEUP_ENV, json.dumps(pin_from_composed(
        [seat.seat_key for seat in board.seats])))
    artifact = tmp_path / "bundle.md"
    artifact.write_text("# bundle\n")
    monkeypatch.chdir(repo)  # the kit runs the board from the W0 checkout
    rc = cli.main(["advisor-board", str(artifact), "--json", "--monitoring-policy", "bounded",
                   "--pointer-brief"])
    return rc, launches, board


def test_a_board_composed_other_than_the_pinned_lineup_launches_no_seat(
        monkeypatch, tmp_path, capsys, repo):
    """Availability that changed after preflight makes the CLI compose a lineup the run plan
    did not approve: the pinned W0 lineup refuses it before any seat launches."""
    rc, launches, board = _board_cli(monkeypatch, tmp_path, repo,
                                     pin_from_composed=lambda keys: keys[:-1])
    out = capsys.readouterr().out
    assert len(board.seats) > 1
    assert launches == []
    payload = json.loads(out[out.index("{"):])
    legs = payload["legs"]
    assert legs and {leg["status"] for leg in legs} == {"UNAVAILABLE"}
    assert {leg["detail"] for leg in legs} == {ct.W0_LINEUP_MISMATCH}


def test_the_pinned_lineup_lets_its_own_board_past_the_pin(monkeypatch, tmp_path, capsys, repo):
    """The approved lineup is not refused by the pin: its legs carry the next guard's
    refusal (here, the review path refusing the counted launch stand-in), never the pin's."""
    _rc, launches, _board = _board_cli(monkeypatch, tmp_path, repo,
                                       pin_from_composed=lambda keys: keys)
    out = capsys.readouterr().out
    legs = json.loads(out[out.index("{"):])["legs"]
    assert legs and ct.W0_LINEUP_MISMATCH not in {leg["detail"] for leg in legs}
    assert launches == []


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}", '["a", 1]'])
def test_a_malformed_lineup_pin_is_a_mismatch(raw):
    assert ct.w0_lineup_problem(["a"], {ct.W0_LINEUP_ENV: raw}) == ct.W0_LINEUP_MISMATCH
    assert ct.w0_lineup_problem(["a"], {}) is None
    assert ct.w0_lineup_problem(["a", "b"], {ct.W0_LINEUP_ENV: '["a", "b"]'}) is None
    assert ct.w0_lineup_problem(["b", "a"], {ct.W0_LINEUP_ENV: '["a", "b"]'}) == ct.W0_LINEUP_MISMATCH


def test_a_run_past_its_timeout_records_timed_out(repo, tmp_path):
    def slow(*_a, **kwargs):
        raise subprocess.TimeoutExpired("phase-loop", kwargs.get("timeout_s"))

    outcome = bk.run_native("print", repo=repo, artifact_copy=tmp_path / "a.md",
                            observations=tmp_path / "obs.jsonl", expected=_expected(),
                            timeout_s=1800, runner=slow)
    assert outcome.canonical_output == "timed_out"
    assert set(outcome.admission.values()) == {"fail"}
    assert outcome.co_seats_unconfined == ("codex",)
    record = bk.build_record(arm="print", block=1, n=1, w0_head=_head(repo), outcome=outcome,
                             billing="unknown", meter_digest="d" * 64, request_set=_set(),
                             activation_section_sha256=_section(repo, "4a"))
    assert record["canonical_output"] == "timed_out" and bk.validate_record(record) == []


def test_the_cli_version_is_read_beside_the_native_image(tmp_path):
    image = tmp_path / "claude"
    image.write_bytes(b"\x7fELF")
    assert bk.cli_version_beside(image) == "unknown"
    (tmp_path / "package.json").write_text(json.dumps({"version": "2.1.318"}))
    assert bk.cli_version_beside(image) == "2.1.318"
    (tmp_path / "package.json").write_text(json.dumps({"version": "2.1.318 (beta)"}))
    assert bk.cli_version_beside(image) == "unknown"


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
