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
digest, URL and archive; a newest upstream release that is not a member warns, because hosts
self-qualify it on first use (agent-harness#1333 PR1). The newest upstream release is the
first stable entry of the first listing page, chosen with the resolver's stable filter
(AGYROLL PROVFWD), and its ``published_at`` is reported. ROLLJOB adds the lag rule (AGYROLL
§6.3) and headroom: ``lag`` is always computed and reported, and changes the exit status only
when ``AGY_LAG_ENFORCE`` is exactly ``true``; ``headroom`` fails at 90 percent of a size
bound whatever that switch says. ``--report <path>`` writes the printed result to a file.

``--intake <issue> --out <dir>`` (the intake workflow, on ``main``): the only step that parses
a submission. It reads the issue once, authenticates its author as the attested INTAKE App,
parses and validates the record, requires a job signature from this checkout's signer list
and re-derives the member from the fixed upstream, then builds the catalog and decides one
class: ``ignored``, ``refused``, ``manual`` or ``auto`` (``decision.json``).

``--catalog-pr --base <sha> --head <sha> --pr <number>`` (the required ``agy catalog
provenance`` check, on every pull request, run from the BASE commit): passes at once when
neither the catalog nor a record changed; otherwise re-derives every added or changed
member from the fixed upstream, whoever wrote the pull request. It imports nothing but the
standard library and ``agy_catalog_policy`` and reads head files as git data only.

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
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
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
# The archive's ``antigravity`` member bound and the release asset bound (AGYFRESH §1.1);
# tested equal to ``agy_provenance.MAX_MEMBER_BYTES`` and ``agy_provenance.MAX_ARCHIVE_BYTES``.
MAX_MEMBER_BYTES = 512_000_000
MAX_ARCHIVE_BYTES = 256_000_000
UPSTREAM = "google-antigravity/antigravity-cli"
RELEASES = f"https://api.github.com/repos/{UPSTREAM}/releases"
# The first page of the listing, as the resolver (agy_provenance.LISTING_PAGE) reads it.
LISTING = RELEASES + "?per_page=100"
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


def catalog_members(text=None):
    """The shipped catalog (or ``text``), parsed by the runtime's own strict parser; empty
    FAILS here."""
    from phase_loop_runtime.gemini_heartbeat import parse_catalog
    try:
        members = parse_catalog(CATALOG.read_text(encoding="utf-8") if text is None else text)
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
    from phase_loop_runtime.agy_attestation import ATTESTATION_STATUSES, SECOND_CHANNEL_STATUSES
    for key, vocabulary in (("attestation", ATTESTATION_STATUSES), ("second_channel", SECOND_CHANNEL_STATUSES)):
        require(isinstance(upstream[key], str) and upstream[key] in vocabulary,
                f"record {name} upstream {key} is not one of {', '.join(vocabulary)}")
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


def contract(*, catalog_text=None, record_paths=None):
    """``--contract``: the records of every member, bound to this tree's seat QCI.
    ``catalog_text`` and ``record_paths`` (record name -> path) stand in for the shipped
    catalog and records, for a catalog built but not yet committed (``--intake``)."""
    from phase_loop_runtime.agy_qualification import seat_qci
    qci = seat_qci()
    records, requalify = [], []
    for member in catalog_members(catalog_text):
        path = (record_paths or {}).get(member["record"], EVIDENCE / member["record"])
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


GITHUB_API_HOST = "api.github.com"
TOKEN_ENV = "GITHUB_TOKEN"


def _api_origin(url):
    """Whether ``url`` is on the HTTPS GitHub API origin, the only place the token may go."""
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname == GITHUB_API_HOST
            and parts.port in (None, 443) and parts.username is None and parts.password is None)


class _ApiOnlyRedirect(HTTPRedirectHandler):
    """Checked at every hop: a redirect away from HTTPS is refused, and one off the API
    origin is followed without the token. urllib's default handler copies every header,
    Authorization included, to any target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise HTTPError(newurl, code, "refusing a redirect away from HTTPS", headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and not _api_origin(newurl):
            new.remove_header("Authorization")
        return new


def _api_opener(*handlers):
    return build_opener(_ApiOnlyRedirect(), *handlers)


def fetch_release(url, *, environ=None, opener=None):
    """One GitHub releases API document. When ``GITHUB_TOKEN`` is set (CI passes the job's
    read-only token), the request is authenticated, which lifts the per-address limit that
    unauthenticated calls from shared runner addresses exhaust (agent-harness#1993). The
    token is sent to the HTTPS GitHub API origin only, at every redirect hop, and never
    printed."""
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "agent-harness-qualified-image-check"}
    token = (os.environ if environ is None else environ).get(TOKEN_ENV, "").strip()
    if token and _api_origin(url):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with (opener or _api_opener()).open(request, timeout=30) as response:
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
        require(member.isfile() and member.size <= MAX_MEMBER_BYTES, "archive member invalid")
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
    # Never authenticated: the asset URL redirects to a download host outside the API.
    request = Request(url, headers={"User-Agent": "agent-harness-qualified-image-check"})
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            with opener(request, timeout=60) as response, Path(target).open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
                    require(stream.tell() <= MAX_ARCHIVE_BYTES, "release asset exceeds expected size")
            return
        except HTTPError as exc:
            if not 500 <= exc.code < 600 or attempt == DOWNLOAD_ATTEMPTS - 1:
                raise
            exc.close()
            sleep(DOWNLOAD_BACKOFF_S[attempt])


def run_conformance_suite(report, *, runner=subprocess.run, python=sys.executable):
    """Run the strict conformance suite (AGYROLL §3.4) in a subprocess, writing its JUnit
    report to ``report``; returns the exit status."""
    root = REPO / "phase-loop-runtime"
    # No ambient pytest or Python configuration reaches the run (PYTEST_ADDOPTS could deselect
    # an obligation, PYTEST_PLUGINS or PYTHONSTARTUP could load code): only the fixed keys.
    # Nor does the API token: the suite makes no GitHub call.
    base = {key: value for key, value in os.environ.items()
            if not key.startswith(("PYTEST_", "PYTHON")) and key != TOKEN_ENV}
    env = {**base, "AGY_CONFORMANCE_STRICT": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root / "tests")])}
    done = runner([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(CONFORMANCE_SUITE),
                   f"--junitxml={report}"], cwd=root, env=env, timeout=900)
    return done.returncode


def tree_status():
    """Uncommitted or untracked paths under phase-loop-runtime/, as git prints them."""
    return subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=all", "--",
                           "phase-loop-runtime"], capture_output=True, text=True, check=True, timeout=60).stdout


def release(report, *, fetch=fetch_release, download=download_asset, identity=None,
            run_suite=run_conformance_suite, status_of_tree=tree_status):
    """``--release``: the contract; a strict conformance run executed HERE, whose fresh report
    must be bound to this checkout; and every member's official archive by tag, whose
    extracted executable must be the record's and the catalog's image (agent-harness#1937)."""
    records = contract()
    report = Path(report)
    require(not os.path.lexists(report),
            f"conformance report {report} already exists: --release writes its own report and never accepts one")
    require(report.parent.is_dir(), f"conformance report directory {report.parent} does not exist")
    # The run's identity is the committed tree, so the tree must BE committed: a planted
    # conftest or any other uncommitted file would run under the same identity. Checked before
    # the run, so nothing the suite creates can trip it.
    dirty = status_of_tree()
    require(not dirty.strip(), "phase-loop-runtime has uncommitted or untracked files; --release runs only a "
                               "committed tree:\n" + dirty[:2000])
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


_TAG = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def _is_stable(release):
    """The resolver's stable filter (``agy_provenance``): not a draft, not a prerelease, an
    ``x.y.z`` tag. Tested to agree with it on a shared listing."""
    return (isinstance(release, dict) and release.get("draft") is False and release.get("prerelease") is False
            and isinstance(release.get("tag_name"), str) and _TAG.fullmatch(release["tag_name"]) is not None)


def newest_stable(fetch):
    """The newest stable release: the first stable entry of the first listing page, in API order."""
    releases = fetch(LISTING)
    require(isinstance(releases, list), "the release listing is not a list")
    newest = next((release for release in releases if _is_stable(release)), None)
    require(newest is not None, "the first listing page has no stable release")
    return newest


# ------------------------------------------------------------------- ROLLJOB (SL-3) shared

API = "https://api.github.com"
DEFAULT_REPOSITORY = "Consiliency/agent-harness"
ATTESTATION_FILE = REPO / "config/agy-rollout-attestation.json"
ALLOWED_SIGNERS_FILE = REPO / "plans/evidence/agy-allowed-signers"
MAX_PULL_PAGES = 50
_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_NUMBER = re.compile(r"[0-9]{1,9}")


def _policy():
    """``agy_catalog_policy``: standard library only, the one runtime module ``--catalog-pr``
    imports."""
    from phase_loop_runtime import agy_catalog_policy
    return agy_catalog_policy


def _repository(environ=None):
    value = (os.environ if environ is None else environ).get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) is not None, "GITHUB_REPOSITORY is malformed")
    return value


def _stable_release(release, version):
    require(_is_stable(release) and release.get("tag_name") == version, f"upstream release {version} is not stable")
    return release


def upstream_member(record, *, fetch=fetch_release, download=None):
    """Provenance from the fixed upstream only (``UPSTREAM``): the release by tag, stable; its
    asset digest and URL equal the record's; the archive downloaded and the member digest
    re-derived. The record supplies a version and digests to compare, never a location.
    Returns the release (``published_at`` comes from it)."""
    version = record["release_version"]
    release = _stable_release(fetch(f"{RELEASES}/tags/{version}"), version)
    asset = verify_asset(record, release)
    with tempfile.TemporaryDirectory(prefix="agy-provenance-") as scratch:
        archive = Path(scratch) / ASSET
        (download or download_asset)(asset["browser_download_url"], archive)
        verify_archive(record, archive)
    return release


# ----------------------------------------------------------------------- --upstream-only

def _latest_asset(latest):
    """The newest release's archive URL and digest, from the API listing, checked as
    ``verify_asset`` checks a member's."""
    assets = [item for item in latest.get("assets", []) if item.get("name") == ASSET]
    require(len(assets) == 1, f"upstream release {latest.get('tag_name')} has no single {ASSET}")
    asset, = assets
    digest = asset.get("digest")
    require(isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None,
            "upstream asset digest malformed")
    require(str(asset.get("browser_download_url", "")).startswith(
        f"https://github.com/{UPSTREAM}/releases/download/{latest['tag_name']}/"), "upstream asset URL mismatch")
    return asset["browser_download_url"], digest.split(":", 1)[1]


def archive_sizes(archive):
    """``(archive bytes, antigravity member bytes)`` of a downloaded archive."""
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember("antigravity")
        require(member.isfile(), "archive member invalid")
        return Path(archive).stat().st_size, member.size


def headroom_of(release, archive, bound_archive=None, bound_member=None):
    policy = _policy()
    archive_size, member_size = archive_sizes(archive)
    archive_bound = MAX_ARCHIVE_BYTES if bound_archive is None else bound_archive
    member_bound = MAX_MEMBER_BYTES if bound_member is None else bound_member
    return {"release": release,
            "archive": {"size": archive_size, "bound": archive_bound,
                        "status": policy.headroom(archive_size, archive_bound)},
            "member": {"size": member_size, "bound": member_bound,
                       "status": policy.headroom(member_size, member_bound)}}


def promotions_in_flight(version, *, now, fetch=fetch_release, environ=None, attestation_text=None):
    """Open promotion pull requests for ``version`` (AGYROLL §6.3 ``warn_pr_open``): on
    ``agy-catalog/<version>-…`` in this repository, authored by the attested PROMOTION App
    and created less than ``IN_FLIGHT_MAX_S`` ago. An intake issue never counts. With an
    unattested file nothing counts, and a listing that cannot be read or proven complete
    (paged to a short page) counts as none."""
    policy = _policy()
    try:
        attestation = policy.load_attestation(ATTESTATION_FILE.read_text(encoding="utf-8")
                                              if attestation_text is None else attestation_text)
    except (OSError, ValueError):
        return []
    if not attestation.attested:
        return []
    repository = _repository(environ)
    prefix = f"{policy.CATALOG_BRANCH_PREFIX}{version}-"
    found = []
    try:
        for page in range(1, MAX_PULL_PAGES + 1):
            pulls = fetch(f"{API}/repos/{repository}/pulls?state=open&per_page=100&page={page}")
            require(isinstance(pulls, list), "pull request listing is not a list")
            for pull in pulls:
                head = pull.get("head") or {}
                if not str(head.get("ref", "")).startswith(prefix) or (head.get("repo") or {}).get(
                        "full_name") != repository:
                    continue
                created = policy.parse_instant(pull.get("created_at"))
                if created is None or now - created >= policy.IN_FLIGHT_MAX_S:
                    continue
                issue = fetch(f"{API}/repos/{repository}/issues/{int(pull['number'])}")
                if policy.authentic_author(issue.get("user"), issue.get("performed_via_github_app"),
                                           attestation.promotion_app):
                    found.append(int(pull["number"]))
            if len(pulls) < 100:
                return found
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    return []  # the listing never reached its end: not proven complete


def lag_status(latest, records, *, now, enforced, in_flight):
    """The lag rule (AGYROLL §6.3): ``ok`` when the newest release ``L`` is a member;
    ``warn_inside_bound`` when it is not and was published less than ``LAG_BOUND_S`` ago;
    ``warn_pr_open`` when it is older and its promotion is in flight; ``fail`` otherwise. An
    unreadable ``published_at`` is treated as outside the bound."""
    policy = _policy()
    version = latest["tag_name"]
    published = policy.parse_instant(latest.get("published_at"))
    flight = []
    if any(record["release_version"] == version for record in records):
        status = "ok"
    elif published is not None and now - published < policy.LAG_BOUND_S:
        status = "warn_inside_bound"
    else:
        flight = in_flight(version)
        status = "warn_pr_open" if flight else "fail"
    return {"status": status, "enforced": enforced, "release": version, "published_at": latest.get("published_at"),
            "bound_s": policy.LAG_BOUND_S, "in_flight": flight}


def _lag_annotation(lag):
    version, status = lag["release"], lag["status"]
    if status == "warn_inside_bound":
        return f"::warning::agy catalog lag: {version} is not a member yet, inside the 48 h bound"
    if status == "warn_pr_open":
        numbers = ", ".join(f"agent-harness#{n}" for n in lag["in_flight"])
        return (f"::warning::agy catalog lag: {version} is older than the 48 h bound; its promotion "
                f"{numbers} is open, awaiting its required checks or merge")
    if status == "fail":
        level = "error" if lag["enforced"] else "warning"
        mode = "" if lag["enforced"] else " (report-only until ACTIVATE)"
        return (f"::{level}::agy catalog lag: {version} is not a member after the 48 h bound and no "
                f"promotion is in flight{mode}")
    return None


def upstream_only(archive=None, *, fetch=fetch_release, download=None, environ=None, now=None, in_flight=None):
    """``--upstream-only``: the newest shipped member's asset and archive (blocking); the lag
    status of the newest upstream release; headroom for the newest release's archive and
    member. ``archive`` is a local copy of the newest member's asset."""
    environ = os.environ if environ is None else environ
    download = download or download_asset
    now = time.time() if now is None else now
    records = contract()
    latest = newest_stable(fetch)
    latest_is_member = any(record["release_version"] == latest["tag_name"] for record in records)
    if not latest_is_member:
        # A host admits a genuine newer release by first-use self-qualification.
        print(f"::warning::newest upstream agy {latest['tag_name']} is not a shipped member; "
              "hosts self-qualify it on first use")
    record = max(records, key=lambda item: release_key(item["release_version"]))
    asset = verify_asset(record, latest if latest["tag_name"] == record["release_version"]
                         else fetch(f"{RELEASES}/tags/{record['release_version']}"))
    with tempfile.TemporaryDirectory(prefix="agy-qualification-") as scratch:
        member_archive = archive
        if member_archive is None:
            member_archive = Path(scratch) / ASSET
            download(asset["browser_download_url"], member_archive)
        verify_archive(record, member_archive)
        if latest["tag_name"] == record["release_version"]:
            latest_archive = member_archive  # the same download serves both checks
        else:
            url, digest = _latest_asset(latest)
            latest_archive = Path(scratch) / f"latest-{ASSET}"
            download(url, latest_archive)
            require(digest_file(latest_archive) == digest, f"upstream {latest['tag_name']} archive digest mismatch")
        room = headroom_of(latest["tag_name"], latest_archive)
    for part in ("archive", "member"):
        item = room[part]
        if item["status"] != "ok":
            level = "error" if item["status"] == "fail" else "warning"
            print(f"::{level}::agy {room['release']} {part} is {item['size']} bytes, "
                  f"{item['size'] * 100 // item['bound']}% of its {item['bound']}-byte bound")
    enforced = environ.get(_policy().LAG_ENFORCE_ENV) == "true"
    lag = lag_status(latest, records, now=now, enforced=enforced,
                     in_flight=in_flight or (lambda version: promotions_in_flight(
                         version, now=now, fetch=fetch, environ=environ)))
    annotation = _lag_annotation(lag)
    if annotation:
        print(annotation)
    return {"latest_release": latest["tag_name"], "latest_published_at": latest.get("published_at"),
            "latest_is_member": latest_is_member,
            "verified_member": record["release_version"], "asset_sha256": record["upstream_asset_sha256"],
            "image_sha256": record["image_sha256"], "lag": lag, "headroom": room}


def upstream_exit(result):
    """1 when headroom fails, or lag fails with enforcement on; 0 otherwise."""
    lag, room = result["lag"], result["headroom"]
    if any(room[part]["status"] == "fail" for part in ("archive", "member")):
        return 1
    return 1 if lag["status"] == "fail" and lag["enforced"] else 0


# ------------------------------------------------------------------------------ --intake

def _decision(out, **fields):
    keys = ("class", "issue", "record_sha256", "version", "base_sha", "catalog_sha256", "run_id", "reasons")
    decision = {key: fields.get(key) for key in keys}
    decision["reasons"] = list(fields.get("reasons") or [])
    (Path(out) / "decision.json").write_text(json.dumps(decision, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return decision


def _head_sha():
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True, timeout=30).stdout.strip()


def intake(issue_number, out, *, fetch=fetch_release, download=None, environ=None, now=None, base_sha=None):
    """``--intake``: one class for one intake issue, decided from this checkout (ROLLJOB-detail
    §4.2). The issue is read once and every check works from that copy.

    ``decision.json`` records the class and reasons, the issue, this run, this checkout's
    commit (``base_sha``), the version, and the digests of the two files an ``auto`` decision
    also writes: the record file (``record_sha256``) and the built catalog
    (``catalog_sha256``). An API or upstream outage raises: no decision is written."""
    policy = _policy()
    environ = os.environ if environ is None else environ
    require(_NUMBER.fullmatch(str(issue_number)) is not None, "the issue number is malformed")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = environ.get("GITHUB_RUN_ID", "local")
    require(re.fullmatch(r"[0-9]{1,20}|local", run_id) is not None, "GITHUB_RUN_ID is malformed")
    base = {"issue": int(issue_number), "run_id": run_id, "base_sha": base_sha or _head_sha()}
    attestation = policy.load_attestation(ATTESTATION_FILE.read_text(encoding="utf-8"))
    issue = fetch(f"{API}/repos/{_repository(environ)}/issues/{int(issue_number)}")
    require(isinstance(issue, dict), "the issue is not an object")
    # 1. the author is the attested INTAKE App, or nothing else happens
    if "pull_request" in issue or not policy.authentic_author(issue.get("user"), issue.get("performed_via_github_app"),
                                                              attestation.intake_app):
        return _decision(out, **base, **{"class": "ignored", "reasons": ["author_not_the_intake_app"]})

    def refused(reason, **extra):
        return _decision(out, **base, **extra, **{"class": "refused", "reasons": [reason]})

    # 2. the body
    try:
        record = policy.parse_intake(issue.get("body"))
    except (ValueError, TypeError, RecursionError):
        return refused("body_malformed")
    record_text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    found = {"version": record.get("release_version"),
             "record_sha256": sha256(record_text.encode("utf-8")).hexdigest()}
    # 3. a closed v2 record for this route, at this checkout's QCI
    try:
        member = policy.candidate_member(record)
    except (ValueError, TypeError, KeyError):
        return refused("record_invalid", **found)
    from phase_loop_runtime.agy_qualification import seat_qci
    if record["qci"] != seat_qci():
        return refused("record_qci_stale", **found)
    # 4. a job signature from this checkout's signer list
    if not policy.verified_signers(record, ALLOWED_SIGNERS_FILE):
        return refused("no_verified_signer", **found)
    # 5. provenance from the fixed upstream; published_at from the API
    try:
        release = upstream_member(record, fetch=fetch, download=download)
    except HTTPError as exc:
        if exc.code == 404:
            return refused("upstream_release_absent", **found)
        raise  # unavailable: no decision, the run fails and reconcile retries it
    except (ValueError, KeyError, tarfile.TarError) as exc:
        return refused(f"upstream_mismatch: {exc}", **found)
    published_at = release.get("published_at")
    # 6. eligibility and the diff class
    base_members = policy.parse_catalog(CATALOG.read_text(encoding="utf-8"))
    when = time.time() if now is None else now
    try:
        built = policy.build_catalog(base_members, record, published_at=published_at, now=when)
    except ValueError as exc:
        return _decision(out, **base, **found, **{"class": "manual", "reasons": [f"not_a_new_newest_member: {exc}"]})
    change = policy.catalog_change(base_members, built, now=when)
    if not change.auto:
        return _decision(out, **base, **found, **{"class": "manual", "reasons": list(change.reasons)})
    # 7. the built tree passes the contract
    catalog_text = policy.render_catalog(built)
    record_path = out / member["record"]
    record_path.write_text(record_text, encoding="utf-8")
    try:
        contract(catalog_text=catalog_text, record_paths={member["record"]: record_path})
    except ValueError as exc:
        record_path.unlink()
        return refused(f"contract: {exc}", **found)
    (out / "agy_catalog.json").write_text(catalog_text, encoding="utf-8")
    return _decision(out, **base, **found, **{"class": "auto", "reasons": [],
                                             "catalog_sha256": sha256(catalog_text.encode("utf-8")).hexdigest()})


# --------------------------------------------------------------------------- --catalog-pr

def _git(*args):
    """git over this checkout, as data: no external diff, no textconv, no pager."""
    done = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(REPO), *args], capture_output=True,
                          check=True, timeout=120, env={**os.environ, "GIT_PAGER": "cat", "GIT_EXTERNAL_DIFF": ""})
    return done.stdout


def changed_paths(base, head, *, git=None):
    """``[(status, source mode, destination mode, path)]`` between the two trees. Renames are
    not detected, so a rename is its two sides: a deletion and an addition."""
    raw = (git or _git)("diff", "--raw", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", base, head)
    parts = raw.split(b"\0")
    entries = []
    index = 0
    while index < len(parts) - 1:
        header = parts[index].decode("utf-8")
        require(header.startswith(":"), "unreadable diff")
        src_mode, dst_mode, _src, _dst, status = header[1:].split(" ")
        entries.append((status, src_mode, dst_mode, parts[index + 1].decode("utf-8")))
        index += 2
    return entries


def catalog_pr(base, head, pr, *, fetch=fetch_release, download=None, git=None):
    """The required ``agy catalog provenance`` check (ROLLJOB-detail §4.4). Raises
    ``ValueError`` naming the failure; returns the passing result."""
    policy = _policy()
    git = git or _git
    require(_SHA.fullmatch(str(base)) is not None and _SHA.fullmatch(str(head)) is not None,
            "--base and --head must be commit ids")
    require(_NUMBER.fullmatch(str(pr)) is not None, "--pr must be a pull request number")
    catalog_path = policy.CATALOG_PATH

    def relevant(path):
        return path == catalog_path or policy.RECORD_PATH.fullmatch(path) is not None

    touched = [entry for entry in changed_paths(base, head, git=git) if relevant(entry[3])]
    result = {"agy_catalog_provenance": "pass", "pr": int(pr), "checked": []}
    if not touched:
        return {**result, "reason": "catalog untouched"}
    for status, _src_mode, dst_mode, path in touched:
        require(status in ("A", "M", "D"), f"{path} changed type or was copied ({status})")
        require(status == "D" or dst_mode == "100644", f"{path} is not a regular file in the head")
        require(not (path == catalog_path and status == "D"), "the catalog was removed or renamed")

    def blob(commit, path):
        return git("cat-file", "blob", f"{commit}:{path}").decode("utf-8")

    base_members = policy.parse_catalog(blob(base, catalog_path))
    try:
        head_members = policy.parse_catalog(blob(head, catalog_path))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ValueError(f"the head catalog does not parse: {exc}") from exc
    records_changed = {Path(path).name for _s, _a, _b, path in touched if path != catalog_path}
    base_by = {member["release_version"]: member for member in base_members}

    def bytes_of(member):
        return {key: value for key, value in member.items() if key != "pinned"}

    to_check = [member for member in head_members
                if member["release_version"] not in base_by
                or bytes_of(member) != bytes_of(base_by[member["release_version"]])
                or member["record"] in records_changed]
    for member in to_check:
        version = member["release_version"]
        try:
            record = json.loads(blob(head, f"plans/evidence/{member['record']}"))
        except (subprocess.CalledProcessError, ValueError) as exc:
            raise ValueError(f"member {version} has no readable record in the head") from exc
        candidate = policy.candidate_member(record)
        require(all(candidate[key] == member[key] for key in candidate), f"member {version} disagrees with its record")
        release = upstream_member(record, fetch=fetch, download=download)
        require(release.get("published_at") == member["published_at"],
                f"member {version} published_at is not upstream's")
        result["checked"].append(version)
    return {**result, "reason": "every added or changed member is upstream's" if to_check
            else "no member's bytes changed"}


# ----------------------------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--contract", action="store_true", help="the catalog and its records against this tree's QCI")
    mode.add_argument("--release", action="store_true", help="--contract, a strict conformance report and every asset")
    mode.add_argument("--upstream-only", action="store_true", help="--contract and the newest shipped member's asset")
    mode.add_argument("--intake", metavar="ISSUE", help="decide the class of one intake issue (the intake workflow)")
    mode.add_argument("--catalog-pr", action="store_true", help="the agy catalog provenance check of one pull request")
    parser.add_argument("--conformance-report", type=Path,
                        help="where --release writes the JUnit report of the strict conformance run it executes "
                             "(must not exist)")
    parser.add_argument("--archive", type=Path, help="a locally downloaded official asset (--upstream-only)")
    parser.add_argument("--report", type=Path, help="--upstream-only: also write the printed result here")
    parser.add_argument("--out", type=Path, help="--intake: the directory the decision and files are written to")
    parser.add_argument("--base", help="--catalog-pr: the pull request's base commit")
    parser.add_argument("--head", help="--catalog-pr: the pull request's head commit")
    parser.add_argument("--pr", help="--catalog-pr: the pull request number")
    args = parser.parse_args(argv)
    if args.release != (args.conformance_report is not None):
        parser.error("--conformance-report is required with --release, and only with it")
    if args.archive is not None and not args.upstream_only:
        parser.error("--archive is only for --upstream-only")
    if args.report is not None and not args.upstream_only:
        parser.error("--report is only for --upstream-only")
    if (args.intake is not None) != (args.out is not None):
        parser.error("--out is required with --intake, and only with it")
    if args.catalog_pr != (args.base is not None and args.head is not None and args.pr is not None) or (
            not args.catalog_pr and (args.base or args.head or args.pr)):
        parser.error("--base, --head and --pr are required with --catalog-pr, and only with it")
    if args.catalog_pr:
        try:
            result = catalog_pr(args.base, args.head, args.pr)
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
            print(json.dumps({"agy_catalog_provenance": "fail", "pr": args.pr, "reason": str(exc)}))
            return 1
        print(json.dumps(result))
        return 0
    try:
        if args.contract:
            records = contract()
            print(json.dumps({"qualified_releases": [r["release_version"] for r in records], "contract": True}))
        elif args.release:
            records, obligations = release(args.conformance_report)
            print(json.dumps({"qualified_releases": [r["release_version"] for r in records], "contract": True,
                              "conformance_obligations": obligations, "assets_verified": True}))
        elif args.intake is not None:
            try:
                print(json.dumps(intake(args.intake, args.out), sort_keys=True))
            except OSError as exc:
                # The API or upstream is unavailable: no decision; the run fails and reconcile retries.
                print(f"verify_qualified_agy_image: intake unavailable: {type(exc).__name__}", file=sys.stderr)
                return 1
        else:
            result = {**upstream_only(args.archive), "verified": True}
            print(json.dumps(result))
            if args.report is not None:
                args.report.write_text(json.dumps(result) + "\n", encoding="utf-8")
            return upstream_exit(result)
    except RequalifyRequired as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError) as exc:
        print(f"verify_qualified_agy_image: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
