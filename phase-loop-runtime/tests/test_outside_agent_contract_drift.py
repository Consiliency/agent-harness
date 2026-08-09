import hashlib
import gzip
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest

import _outside_agent_canonical as canonical

from _outside_agent_canonical import (
    IMMUTABLE_SPEC_V0_2_1_DIGESTS,
    IMMUTABLE_SPEC_V0_2_1_FILES,
    LIVE_BLOCKER_CODE_BY_INVALID_CASE,
    PRODUCTION_SCAN_ROOT_LITERAL,
    FIXTURE_ROOT,
    find_non_enumerated_canonical_copies,
    production_mirror_paths,
    route_verdict_entry,
    source_runtime_available,
    submission_entries,
)


def _assert_installed_wheel_invocations(wheel_path: Path, target: Path, label: str) -> None:
    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheel_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    environment = dict(os.environ, PYTHONPATH=str(target))
    installed_root = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import phase_loop_runtime; "
            "print(Path(phase_loop_runtime.__file__).resolve())",
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed_root.returncode == 0, installed_root.stdout + installed_root.stderr
    assert Path(installed_root.stdout.strip()).is_relative_to(target)

    rows = submission_entries()
    anchor = "CONFORM_RED::sdist_contract_mirror_missing"
    installed_api = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util, importlib.resources, json, sys; from pathlib import Path; "
            "from phase_loop_runtime.conformance.outside_agent_core import validate_outside_agent_submission; "
            "root = Path(sys.argv[1]); rows = json.loads(sys.argv[2]); "
            "oracle_path = importlib.resources.files('phase_loop_runtime.conformance').joinpath('_contract/consiliency_spec/outside_agent_router.py'); "
            "spec = importlib.util.spec_from_file_location('installed_outside_agent_oracle', oracle_path); oracle = importlib.util.module_from_spec(spec); spec.loader.exec_module(oracle); "
            "print(json.dumps({row['case_id']: {'case_id': row['case_id'], 'expected_valid': row['expected_valid'], 'oracle_blocker_class': oracle.blocker_class_of(oracle.route(payload := json.loads((root / row['path']).read_text(encoding='utf-8')), row['schema_target'])), 'status': (verdict := validate_outside_agent_submission(payload)).status.value, 'codes': sorted(item.code for item in verdict.blockers)} for row in rows}, sort_keys=True))",
            str(FIXTURE_ROOT),
            json.dumps(rows),
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed_api.returncode == 0, anchor
    api_payload = json.loads(installed_api.stdout)

    for row in rows:
        expected_exit = 0 if row["expected_valid"] else (
            6 if row["case_id"] == "negative-source-bundle-mismatch" else 2
        )
        expected_status = "pass" if row["expected_valid"] else "blocked"
        api_result = api_payload[row["case_id"]]
        assert set(api_result) == {
            "case_id",
            "expected_valid",
            "oracle_blocker_class",
            "status",
            "codes",
        }, anchor
        assert api_result["case_id"] == row["case_id"], anchor
        assert api_result["expected_valid"] is row["expected_valid"], anchor
        assert api_result["oracle_blocker_class"] == row["expected_blocker_class"], anchor
        assert api_result["status"] == expected_status, anchor
        if row["expected_valid"]:
            assert api_result["codes"] == [], anchor
        else:
            assert LIVE_BLOCKER_CODE_BY_INVALID_CASE[row["case_id"]] in api_result["codes"], anchor
        for command in ("outside-agent-preflight", "outside-agent-validate"):
            output_path = target / f"{label}-{row['case_id']}-{command}.json"
            cli = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "phase_loop_runtime.cli",
                    command,
                    str(FIXTURE_ROOT / row["path"]),
                    "--output",
                    str(output_path),
                ],
                cwd=target,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert cli.returncode == expected_exit, anchor
            payload = json.loads(cli.stdout)
            assert payload["status"] == expected_status, anchor
            assert output_path.read_text(encoding="utf-8") == cli.stdout, anchor
            blocker_codes = {blocker["code"] for blocker in payload["blockers"]}
            if row["expected_valid"]:
                assert blocker_codes == set(), anchor
            else:
                assert LIVE_BLOCKER_CODE_BY_INVALID_CASE[row["case_id"]] in blocker_codes, anchor

    installed_vectors = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, subprocess; "
            "import phase_loop_runtime.cli as phase_loop_cli; "
            "import phase_loop_runtime.conformance.outside_agent_vectors as vector_runner; "
            "original_submission_validator = vector_runner.validate_outside_agent_submission\n"
            "def guarded_submission(payload, *args, **kwargs):\n"
            "    assert payload.get('verdict_schema_version') != 'outside_agent_route_verdict.v0.1', 'route row traversed submission builder'\n"
            "    return original_submission_validator(payload, *args, **kwargs)\n"
            "def forbidden_cli(*args, **kwargs):\n"
            "    raise AssertionError('route row traversed submission CLI')\n"
            "vector_runner.validate_outside_agent_submission = guarded_submission; "
            "phase_loop_cli._outside_agent_validate_command = forbidden_cli; "
            "subprocess.run = forbidden_cli; subprocess.Popen = forbidden_cli; "
            "print(json.dumps({item.vector_name: {'status': item.status.value, 'codes': sorted(blocker.code for blocker in item.blockers), 'dispatch_observation': getattr(item, 'dispatch_observation', None)} for item in vector_runner.run_outside_agent_vectors()}, sort_keys=True))",
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed_vectors.returncode == 0, anchor
    vector_payload = json.loads(installed_vectors.stdout)
    assert set(vector_payload) == {row["case_id"] for row in rows} | {
        route_verdict_entry()["case_id"]
    }, anchor
    for row in rows:
        vector_result = vector_payload[row["case_id"]]
        assert set(vector_result) == {"status", "codes", "dispatch_observation"}, anchor
        assert vector_result["status"] == ("pass" if row["expected_valid"] else "blocked"), anchor
        assert vector_result["dispatch_observation"] is None, anchor
        if row["expected_valid"]:
            assert vector_result["codes"] == [], anchor
        else:
            assert LIVE_BLOCKER_CODE_BY_INVALID_CASE[row["case_id"]] in vector_result["codes"], anchor

    route_row = route_verdict_entry()
    assert route_row["case_id"] not in {row["case_id"] for row in rows}, anchor
    route_payload = vector_payload[route_row["case_id"]]
    assert route_payload["status"] == "blocked", "CONFORM_RED::sdist_contract_mirror_missing"
    assert "schema_validation_failed" in route_payload["codes"], (
        "CONFORM_RED::sdist_contract_mirror_missing"
    )
    route_schema = (
        FIXTURE_ROOT / "schemas/outside-agent-route-verdict.schema.json"
    ).read_bytes()
    assert route_payload["dispatch_observation"] == {
        "entered": True,
        "schema_target": route_row["schema_target"],
        "selected_schema_id": json.loads(route_schema)["$id"],
        "selected_schema_sha256": hashlib.sha256(route_schema).hexdigest(),
        "validation_error_pointer": "/route",
        "validation_error_keyword": "enum",
    }, "CONFORM_RED::sdist_contract_mirror_missing"

    # The route row is never a submission-CLI input.  Each installed variant
    # must instead enter the direct selected-route-schema API and report the
    # pinned canonical row identity/class alongside the schema observation.
    installed_route = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util, importlib.resources, json, sys; from pathlib import Path; "
            "from phase_loop_runtime.conformance.outside_agent_schema import validate_outside_agent_route_verdict_schema; "
            "root = Path(sys.argv[1]); row = json.loads(sys.argv[2]); payload = json.loads((root / row['path']).read_text(encoding='utf-8')); "
            "result = validate_outside_agent_route_verdict_schema(payload, schema_target=row['schema_target']); "
            "oracle_path = importlib.resources.files('phase_loop_runtime.conformance').joinpath('_contract/consiliency_spec/outside_agent_router.py'); "
            "spec = importlib.util.spec_from_file_location('installed_outside_agent_oracle', oracle_path); oracle = importlib.util.module_from_spec(spec); spec.loader.exec_module(oracle); "
            "print(json.dumps({'case_id': row['case_id'], 'expected_valid': row['expected_valid'], 'oracle_blocker_class': oracle.blocker_class_of(oracle.route(payload, row['schema_target'])), 'status': result.status.value, 'codes': sorted(item.code for item in result.blockers), 'dispatch_observation': result.dispatch_observation}, sort_keys=True))",
            str(FIXTURE_ROOT),
            json.dumps(route_row),
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed_route.returncode == 0, anchor
    direct_route_payload = json.loads(installed_route.stdout)
    assert direct_route_payload["case_id"] == route_row["case_id"]
    assert direct_route_payload["expected_valid"] is route_row["expected_valid"] is False
    assert direct_route_payload["oracle_blocker_class"] == route_row["expected_blocker_class"] == "policy_gap"
    assert direct_route_payload["status"] == "blocked"
    assert LIVE_BLOCKER_CODE_BY_INVALID_CASE[route_row["case_id"]] in direct_route_payload["codes"]
    assert direct_route_payload["dispatch_observation"] == route_payload["dispatch_observation"], anchor


def test_no_copied_canonical_outside_agent_schema_or_vectors():
    repo = Path(__file__).resolve().parents[2]
    copied, scanned = find_non_enumerated_canonical_copies(repo)

    assert scanned > 0, PRODUCTION_SCAN_ROOT_LITERAL
    assert copied == ()


def test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes():
    repo = Path(__file__).resolve().parents[2]
    if not source_runtime_available():
        pytest.skip("repository-owned conformance documentation is absent in standalone clean-room")
    documentation = (repo / "docs" / "outside-agent-conformance.md").read_text(encoding="utf-8")

    assert "Consiliency/spec@v0.2.1" in documentation, (
        "CONFORM_RED::documented_consumer_mirror_policy_allows_only_pinned_contract_bytes"
    )
    required = {
        "digest-enumerated",
        "test-only oracle",
        "15",
        "source/mirror",
        "raw-byte",
        "no copied canonical",
        "not a production parser",
        "consiliency/spec remains",
    }
    assert all(term in documentation.lower() for term in required), (
        "CONFORM_RED::documented_consumer_mirror_policy_allows_only_pinned_contract_bytes"
    )


def test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror(tmp_path):
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w:") as archive:
        member = tarfile.TarInfo("stable.txt")
        member.size = len(b"stable tar bytes")
        archive.addfile(member, io.BytesIO(b"stable tar bytes"))
    first.write_bytes(gzip.compress(tar_bytes.getvalue(), mtime=1))
    second.write_bytes(gzip.compress(tar_bytes.getvalue(), mtime=2))
    for archive_path in (first, second):
        with tarfile.open(archive_path, mode="r:gz") as archive:
            assert archive.extractfile("stable.txt").read() == b"stable tar bytes"
    normalize_sdist = getattr(canonical, "_normalize_sdist_gzip", None)
    assert callable(normalize_sdist), "CONFORM_RED::sdist_gzip_timestamp_nondeterministic"
    normalize_sdist(first, source_date_epoch="315532800")
    normalize_sdist(second, source_date_epoch="315532800")
    assert first.read_bytes() == second.read_bytes(), (
        "CONFORM_RED::sdist_gzip_timestamp_nondeterministic"
    )
    with tarfile.open(first, mode="r:gz") as archive:
        assert archive.extractfile("stable.txt").read() == b"stable tar bytes"

    repo = Path(__file__).resolve().parents[2]
    runtime_root = repo / "phase-loop-runtime"
    expected = {
        "phase_loop_runtime/conformance/_contract/VENDOR.json",
        *{
            path.removeprefix("phase-loop-runtime/src/")
            for path in production_mirror_paths()
        },
    }
    if not source_runtime_available():
        wheel_path = next((repo.parent / "dist").glob("*.whl"), None)
        assert wheel_path is not None, (
            "CONFORM_RED::sdist_contract_mirror_missing: package build did not produce archives"
        )
        with zipfile.ZipFile(wheel_path) as archive:
            wheel_members = {member for member in archive.namelist() if "/conformance/_contract/" in member}
            wheel_bytes = {member: archive.read(member) for member in wheel_members}
        assert wheel_members == expected, (
            "CONFORM_RED::sdist_contract_mirror_missing: "
            "phase_loop_runtime/conformance/_contract/VENDOR.json"
        )
        vendor = json.loads(wheel_bytes["phase_loop_runtime/conformance/_contract/VENDOR.json"])
        vendor_records = {
            (row["source_path"], row["mirror_path"], row["raw_byte_sha256"])
            for row in vendor["files"]
        }
        assert vendor_records == set(IMMUTABLE_SPEC_V0_2_1_FILES)
        assert len(vendor_records) == len(vendor["files"]) == 15
        for relative, digest in IMMUTABLE_SPEC_V0_2_1_DIGESTS.items():
            archive_path = "phase_loop_runtime/conformance/_contract/" + relative
            assert hashlib.sha256(wheel_bytes[archive_path]).hexdigest() == digest
            assert wheel_bytes[archive_path] == (FIXTURE_ROOT / relative).read_bytes()
        _assert_installed_wheel_invocations(wheel_path, tmp_path / "direct-wheel", "direct")
        return

    dist_root = tmp_path / "dist"
    missing_build_prerequisites = [
        module
        for module in ("build", "setuptools")
        if importlib.util.find_spec(module) is None
    ]
    assert not missing_build_prerequisites, (
        "package-build prerequisites unavailable: "
        + ", ".join(missing_build_prerequisites)
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--outdir",
            str(dist_root),
            str(runtime_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        "CONFORM_RED::sdist_contract_mirror_missing: package build did not produce archives"
    )
    wheel_path = next(dist_root.glob("*.whl"))
    with zipfile.ZipFile(wheel_path) as archive:
        wheel_members = {member for member in archive.namelist() if "/conformance/_contract/" in member}
        wheel_bytes = {member: archive.read(member) for member in wheel_members}
    assert wheel_members == expected, (
        "CONFORM_RED::sdist_contract_mirror_missing: "
        "phase_loop_runtime/conformance/_contract/VENDOR.json"
    )
    sdist_path = next(dist_root.glob("*.tar.gz"))
    normalize_sdist(
        sdist_path,
        source_date_epoch=os.environ.get("SOURCE_DATE_EPOCH", "315532800"),
    )
    with tarfile.open(sdist_path) as archive:
        sdist_bytes = {
            member.name.split("/src/", 1)[1]: archive.extractfile(member).read()
            for member in archive.getmembers()
            if "/src/phase_loop_runtime/conformance/_contract/" in member.name
            and member.isfile()
        }
        sdist_members = set(sdist_bytes)
    assert sdist_members == expected, (
        "CONFORM_RED::sdist_contract_mirror_missing: "
        "phase_loop_runtime/conformance/_contract/VENDOR.json"
    )
    sdist_extract_root = tmp_path / "sdist-extract"
    sdist_extract_root.mkdir()
    with tarfile.open(sdist_path) as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert member.isfile() or member.isdir()
        top_levels = {PurePosixPath(member.name).parts[0] for member in members}
        assert len(top_levels) == 1
        top_level_name = list(top_levels)[0]
        top_member = next(
            (m for m in members if PurePosixPath(m.name) == PurePosixPath(top_level_name)),
            None
        )
        assert top_member is not None and top_member.isdir()
        archive.extractall(sdist_extract_root)
    sdist_roots = [path for path in sdist_extract_root.iterdir() if path.is_dir()]
    assert len(sdist_roots) == 1
    sdist_dir = sdist_roots[0]
    derived_dist = tmp_path / "derived-wheel"
    derived = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(derived_dist),
            str(sdist_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert derived.returncode == 0, (
        "CONFORM_RED::sdist_derived_wheel_contract_mirror_missing: "
        "package build did not produce an sdist-derived wheel"
    )
    with zipfile.ZipFile(next(derived_dist.glob("*.whl"))) as archive:
        derived_members = {member for member in archive.namelist() if "/conformance/_contract/" in member}
        derived_bytes = {member: archive.read(member) for member in derived_members}
    assert derived_members == expected, (
        "CONFORM_RED::sdist_derived_wheel_contract_mirror_missing: "
        "phase_loop_runtime/conformance/_contract/VENDOR.json"
    )
    assert wheel_bytes == sdist_bytes == derived_bytes
    vendor = json.loads(wheel_bytes["phase_loop_runtime/conformance/_contract/VENDOR.json"])
    vendor_records = {
        (row["source_path"], row["mirror_path"], row["raw_byte_sha256"])
        for row in vendor["files"]
    }
    assert vendor_records == set(IMMUTABLE_SPEC_V0_2_1_FILES)
    assert len(vendor_records) == len(vendor["files"]) == 15
    for relative, digest in IMMUTABLE_SPEC_V0_2_1_DIGESTS.items():
        archive_path = "phase_loop_runtime/conformance/_contract/" + relative
        assert archive_path in wheel_bytes
        assert hashlib.sha256(wheel_bytes[archive_path]).hexdigest() == digest
        assert wheel_bytes[archive_path] == (FIXTURE_ROOT / relative).read_bytes()
    _assert_installed_wheel_invocations(wheel_path, tmp_path / "direct-wheel", "direct")
    _assert_installed_wheel_invocations(
        next(derived_dist.glob("*.whl")),
        tmp_path / "sdist-derived-wheel-install",
        "sdist-derived",
    )
