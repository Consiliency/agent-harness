"""Verify the shipped agy catalog against its v2 qualification records (AGYROLL §3.3).

``--contract`` (every pull request and push, no path filter, plus nightly): a strict parse of
``phase_loop_runtime/data/agy_catalog.json`` that refuses an empty catalog; every member has
exactly one v2 record (unlisted records are ignored) that agrees with it; every record's and
member's ``qci`` equals this tree's ``seat_qci()``. A QCI difference prints
``requalify: <members>``.

``--release --conformance-report <junit.xml>`` (``publish-pypi.yml``, before the build, inside
the provisioned systemd user manager): ``--contract``; then it RUNS the strict conformance suite
itself (``AGY_CONFORMANCE_STRICT=1``), writing its JUnit report to ``--conformance-report``, a
path that must not exist beforehand. The run must exit 0, and the report it just wrote must
carry this checkout's identity, with every id of ``CONFORMANCE_OBLIGATIONS``
(``tests/test_agy_route_conformance.py``) passed exactly once and no case skipped, xfailed,
failed or errored. A report made elsewhere is never accepted (agent-harness#1937 re-check M4).
Finally every member's official archive is fetched by tag and its extracted executable must
be the recorded image.

``--upstream-only`` (nightly): ``--contract``, then the newest shipped member's vendor asset
digest, URL and archive; a newest upstream release that is not a member only warns, because
hosts self-qualify it on first use (agent-harness#1333 PR1).

R1 (agent-harness#1008) removed the full pin (``--source-only``, agent-harness#1032) and the
per-pull-request route-core gate (``--route-core``, agent-harness#1029).
"""

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "phase-loop-runtime/src/phase_loop_runtime"
CATALOG = PACKAGE / "data/agy_catalog.json"
EVIDENCE = REPO / "plans/evidence"
CONFORMANCE_SUITE = REPO / "phase-loop-runtime/tests/test_agy_route_conformance.py"
CONFORMANCE_FIXTURES = REPO / "phase-loop-runtime/tests/fixtures/agy_conformance"
# The properties a real strict run writes into its JUnit report (agent-harness#1937 review B4).
IDENTITY_PROPERTIES = ("agy_conformance_strict", "agy_conformance_commit", "agy_conformance_source_sha256")
ASSET = "agy_cli_linux_x64.tar.gz"
UPSTREAM = "google-antigravity/antigravity-cli"
RELEASES = f"https://api.github.com/repos/{UPSTREAM}/releases"
API = RELEASES + "/latest"
RECORD_SCHEMA = "agy_redacted_qualification_summary.v2"
RECORD_KEYS = frozenset({
    "schema", "provider", "route", "platform", "architecture", "release_version", "image_sha256",
    "help_sha256", "isolation_profile", "raw_receipts_local_only", "records", "role",
    "upstream_asset_name", "upstream_asset_sha256", "upstream_release_url", "validator",
    "qci", "qualified_under", "upstream", "signatures",
})
UPSTREAM_KEYS = frozenset({"asset_sha256", "release_url", "attestation", "second_channel"})
ROUTE = {"provider": "gemini", "route": "brokered_subscription_heartbeat_only",
         "platform": "linux", "architecture": "x86_64"}
OBLIGATION_CASE = re.compile(r"test_obligation\[([a-z0-9_]+)\]")
# The tree's own runtime decides the QCI and the catalog schema; the verifier copies neither.
sys.path.insert(0, str(PACKAGE.parent))


class RequalifyRequired(ValueError):
    """Members whose evidence no longer matches this tree's seat QCI."""

    def __init__(self, members):
        super().__init__("requalify: " + ", ".join(members))
        self.members = list(members)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest_file(path):
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def catalog_members():
    """The shipped catalog, parsed by the runtime's own strict parser; empty FAILS here."""
    from phase_loop_runtime.gemini_heartbeat import parse_catalog
    try:
        members = parse_catalog(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"agy catalog {CATALOG.name} is missing or malformed: {exc}") from exc
    require(members, "agy catalog has no members")
    return members


def validate_record(member, record):
    """One member against its own v2 record; raises naming the member."""
    from phase_loop_runtime.gemini_heartbeat import PROFILE_ID
    version = member["release_version"]
    name = member["record"]
    require(isinstance(record, dict) and set(record) == RECORD_KEYS, f"record {name} is not a closed v2 record")
    require(record["schema"] == RECORD_SCHEMA, f"record {name} schema mismatch")
    for key, value in {**ROUTE, "release_version": version, "image_sha256": member["image_sha256"],
                       "help_sha256": member["help_sha256"], "upstream_asset_name": ASSET,
                       "upstream_asset_sha256": member["asset_sha256"],
                       "upstream_release_url": f"https://github.com/{UPSTREAM}/releases/tag/{version}",
                       "isolation_profile": PROFILE_ID}.items():
        require(record[key] == value, f"record {name} {key} mismatch")
    upstream = record["upstream"]
    require(isinstance(upstream, dict) and set(upstream) == UPSTREAM_KEYS, f"record {name} upstream is not closed")
    require(upstream["asset_sha256"] == member["asset_sha256"] and
            upstream["release_url"] == record["upstream_release_url"], f"record {name} upstream mismatch")
    require(all(isinstance(upstream[key], str) and upstream[key] for key in ("attestation", "second_channel")),
            f"record {name} upstream status malformed")
    require(isinstance(record["signatures"], list), f"record {name} signatures malformed")
    require(isinstance(record["qualified_under"], str) and record["qualified_under"],
            f"record {name} qualified_under malformed")
    require(isinstance(record["qci"], str) and re.fullmatch(r"[0-9a-f]{64}", record["qci"]),
            f"record {name} qci malformed")
    require(record["validator"] == {"validated": 3, "operations": ["cancel", "completion", "owner-loss"],
                                    "route_qualified": True}, f"record {name} qualification validation mismatch")
    rows = record["records"]
    require(isinstance(rows, list) and sorted(row.get("operation") for row in rows) ==
            ["cancel", "completion", "owner-loss"], f"record {name} qualification operations mismatch")
    require(all(row["image_sha256"] == record["image_sha256"] and row["help_sha256"] == record["help_sha256"]
                and row["profile"]["id"] == PROFILE_ID and row["profile"]["image_sha256"] == record["image_sha256"]
                for row in rows), f"record {name} image or profile mismatch")


def contract():
    """``--contract``: the records of every member, bound to this tree's seat QCI."""
    from phase_loop_runtime.agy_qualification import seat_qci
    qci = seat_qci()
    records, requalify = [], []
    for member in catalog_members():
        path = EVIDENCE / member["record"]
        require(path.is_file(), f"member {member['release_version']} has no record {member['record']}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"record {member['record']} is not JSON") from exc
        validate_record(member, record)
        if record["qci"] != qci or member["qci"] != qci:
            requalify.append(member["release_version"])
        records.append(record)
    if requalify:
        raise RequalifyRequired(requalify)
    return records


def conformance_obligations(suite=None):
    """``CONFORMANCE_OBLIGATIONS``, read from the suite as a literal (never imported)."""
    tree = ast.parse(Path(suite or CONFORMANCE_SUITE).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CONFORMANCE_OBLIGATIONS"
                                                for t in node.targets):
            value = ast.literal_eval(node.value)
            require(isinstance(value, tuple) and value and len(set(value)) == len(value),
                    "CONFORMANCE_OBLIGATIONS is malformed")
            return value
    raise ValueError("the conformance suite declares no CONFORMANCE_OBLIGATIONS")


def conformance_source_sha256(repo=None):
    """One digest over what a conformance run proves: the package sources and data, the suite
    and its stand-in fixtures. The suite records it; ``--release`` recomputes it."""
    repo = Path(repo or REPO)
    package = repo / "phase-loop-runtime/src/phase_loop_runtime"
    files = [path for path in package.rglob("*") if path.is_file() and path.suffix in (".py", ".json")
             and "__pycache__" not in path.parts]
    files.append(repo / "phase-loop-runtime/tests/test_agy_route_conformance.py")
    files += [path for path in (repo / "phase-loop-runtime/tests/fixtures/agy_conformance").rglob("*") if path.is_file()]
    table = {str(path.relative_to(repo)): digest_file(path) for path in sorted(files)}
    return sha256(json.dumps(table, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def conformance_identity(repo=None, *, strict=True):
    """The identity a strict conformance run at this checkout records, and ``--release`` requires."""
    repo = Path(repo or REPO)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True, timeout=30).stdout.strip()
    return {"agy_conformance_strict": "1" if strict else "0", "agy_conformance_commit": commit,
            "agy_conformance_source_sha256": conformance_source_sha256(repo)}


def check_conformance_report(path, obligations, identity=None):
    """A strict run at this commit and source (its recorded identity), every obligation passed
    exactly once, and nothing in the report skipped, xfailed, failed or errored."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"conformance report {path} is unavailable") from exc
    require("<!DOCTYPE" not in text and "<!ENTITY" not in text, "conformance report declares a DTD")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError("conformance report is not JUnit XML") from exc
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    require(len(suites) == 1, "conformance report must hold exactly one test suite")
    recorded = {}
    for prop in suites[0].iter("property"):
        name = prop.get("name")
        require(name not in recorded, f"conformance report repeats property {name}")
        recorded[name] = prop.get("value")
    expected = identity if identity is not None else conformance_identity()
    for key in IDENTITY_PROPERTIES:
        require(key in recorded, f"conformance report has no {key}: not a run of the strict suite")
        require(recorded[key] == expected[key],
                f"conformance report {key} is {recorded[key]!r}, this checkout needs {expected[key]!r}")
    for suite in suites:
        for key in ("errors", "failures", "skipped"):
            require(suite.get(key, "0") == "0", f"conformance report has {suite.get(key)} {key}")
    seen = []
    for case in root.iter("testcase"):
        outcome = [child.tag for child in case if child.tag in ("skipped", "failure", "error")]
        if outcome:
            raise ValueError(f"conformance case {case.get('name')} is {outcome[0]} (skips and xfails never pass)")
        match = OBLIGATION_CASE.fullmatch(case.get("name") or "")
        if match is not None and "test_agy_route_conformance" in (case.get("classname") or ""):
            seen.append(match.group(1))
    missing = sorted(set(obligations) - set(seen))
    unknown = sorted(set(seen) - set(obligations))
    repeated = sorted({ident for ident in seen if seen.count(ident) > 1})
    require(not missing, "conformance report is missing obligations: " + ", ".join(missing))
    require(not unknown, "conformance report has unknown obligations: " + ", ".join(unknown))
    require(not repeated, "conformance report repeats obligations: " + ", ".join(repeated))
    return sorted(seen)


def release_key(version):
    parts = version.split(".")
    require(all(part.isdigit() for part in parts), f"release version {version!r} is not dotted numeric")
    return tuple(int(part) for part in parts)


def fetch_release(url):
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": "agent-harness-qualified-image-check"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def verify_asset(record, release):
    """The member's vendor asset by its tag: digest and download URL."""
    version = record["release_version"]
    require(release.get("tag_name") == version, f"vendor release tag mismatch for {version}")
    assets = [item for item in release.get("assets", []) if item.get("name") == ASSET]
    require(len(assets) == 1, f"vendor release {version} has no single {ASSET}")
    asset, = assets
    require(asset.get("digest") == "sha256:" + record["upstream_asset_sha256"], f"vendor asset digest mismatch for {version}")
    require(str(asset.get("browser_download_url", "")).startswith(
        f"https://github.com/{UPSTREAM}/releases/download/{version}/"), f"vendor asset URL mismatch for {version}")
    return asset


def verify_archive(record, archive):
    require(digest_file(archive) == record["upstream_asset_sha256"], "archive digest mismatch")
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember("antigravity")
        require(member.isfile() and member.size <= 250_000_000, "archive member invalid")
        stream = bundle.extractfile(member)
        require(stream is not None, "archive member missing")
        h = sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    require(h.hexdigest() == record["image_sha256"], "executable digest mismatch")


DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF_S = (1, 2)


def download_asset(url, target, *, opener=None, sleep=None):
    """Fetch one asset. A server error (HTTP 5xx) is retried, at most three attempts in all,
    after 1 s and 2 s; every attempt restarts the file; exhaustion re-raises. Size and digests
    are checked by the callers as before."""
    opener, sleep = opener or urlopen, sleep or time.sleep  # resolved per call (tests patch urlopen)
    request = Request(url, headers={"User-Agent": "agent-harness-qualified-image-check"})
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            with opener(request, timeout=60) as response, Path(target).open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
                    require(stream.tell() <= 128_000_000, "release asset exceeds expected size")
            return
        except HTTPError as exc:
            if not 500 <= exc.code < 600 or attempt == DOWNLOAD_ATTEMPTS - 1:
                raise
            sleep(DOWNLOAD_BACKOFF_S[attempt])


def run_conformance_suite(report, *, runner=subprocess.run, python=sys.executable):
    """Run the strict conformance suite (AGYROLL §3.4) in a subprocess, writing its JUnit
    report to ``report``; returns the exit status."""
    root = REPO / "phase-loop-runtime"
    env = {**os.environ, "AGY_CONFORMANCE_STRICT": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root / "tests")])}
    done = runner([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(CONFORMANCE_SUITE),
                   f"--junitxml={report}"], cwd=root, env=env, timeout=900)
    return done.returncode


def release(report, *, fetch=fetch_release, download=download_asset, identity=None,
            run_suite=run_conformance_suite):
    """``--release``: the contract; a strict conformance run executed HERE, whose fresh report
    must be bound to this checkout; and every member's official archive by tag, whose
    extracted executable must be the record's and the catalog's image (agent-harness#1937)."""
    records = contract()
    report = Path(report)
    require(not os.path.lexists(report),
            f"conformance report {report} already exists: --release writes its own report and never accepts one")
    require(report.parent.is_dir(), f"conformance report directory {report.parent} does not exist")
    status = run_suite(report)
    require(status == 0, f"the strict conformance run failed (exit status {status})")
    obligations = check_conformance_report(report, conformance_obligations(), identity)
    images = {member["release_version"]: member["image_sha256"] for member in catalog_members()}
    with tempfile.TemporaryDirectory(prefix="agy-release-") as scratch:
        for record in records:
            version = record["release_version"]
            asset = verify_asset(record, fetch(f"{RELEASES}/tags/{version}"))
            archive = Path(scratch) / f"{version}-{ASSET}"
            download(asset["browser_download_url"], archive)
            verify_archive(record, archive)
            require(images[version] == record["image_sha256"], f"catalog image of {version} differs from its record")
    return records, obligations


def upstream_only(archive=None, *, fetch=fetch_release):
    records = contract()
    latest = fetch(API)
    latest_is_member = any(record["release_version"] == latest["tag_name"] for record in records)
    if not latest_is_member:
        # Advisory only: a host admits a genuine newer release by first-use self-qualification.
        print(f"::warning::newest upstream agy {latest['tag_name']} is not a shipped member; "
              "hosts self-qualify it on first use")
    record = max(records, key=lambda item: release_key(item["release_version"]))
    asset = verify_asset(record, latest if latest["tag_name"] == record["release_version"]
                         else fetch(f"{RELEASES}/tags/{record['release_version']}"))
    if archive is not None:
        verify_archive(record, archive)
    else:
        with tempfile.TemporaryDirectory(prefix="agy-qualification-") as scratch:
            path = Path(scratch) / ASSET
            download_asset(asset["browser_download_url"], path)
            verify_archive(record, path)
    return {"latest_release": latest["tag_name"], "latest_is_member": latest_is_member,
            "verified_member": record["release_version"], "asset_sha256": record["upstream_asset_sha256"],
            "image_sha256": record["image_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--contract", action="store_true", help="the catalog and its records against this tree's QCI")
    mode.add_argument("--release", action="store_true", help="--contract, a strict conformance report and every asset")
    mode.add_argument("--upstream-only", action="store_true", help="--contract and the newest shipped member's asset")
    parser.add_argument("--conformance-report", type=Path,
                        help="where --release writes the JUnit report of the strict conformance run it executes "
                             "(must not exist)")
    parser.add_argument("--archive", type=Path, help="a locally downloaded official asset (--upstream-only)")
    args = parser.parse_args(argv)
    if args.release != (args.conformance_report is not None):
        parser.error("--conformance-report is required with --release, and only with it")
    if args.archive is not None and not args.upstream_only:
        parser.error("--archive is only for --upstream-only")
    try:
        if args.contract:
            records = contract()
            print(json.dumps({"qualified_releases": [r["release_version"] for r in records], "contract": True}))
        elif args.release:
            records, obligations = release(args.conformance_report)
            print(json.dumps({"qualified_releases": [r["release_version"] for r in records], "contract": True,
                              "conformance_obligations": obligations, "assets_verified": True}))
        else:
            print(json.dumps({**upstream_only(args.archive), "verified": True}))
    except RequalifyRequired as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError) as exc:
        print(f"verify_qualified_agy_image: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
