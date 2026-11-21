"""`verify_qualified_agy_image.py --upstream-only`: membership is advisory (agent-harness#1333 PR1).

A newer upstream agy release that is not a shipped member only warns; hosts self-qualify it
on first use. The newest SHIPPED member's vendor asset digest, URL and archive stay blocking,
so the scheduled `upstream` job reds on any member-integrity failure and never on membership.

The newest upstream release is the first stable entry of the first listing page, chosen with
the resolver's stable filter (PROVFWD-detail §3.2), not ``/releases/latest``.

Nothing here reaches the network: the release API and the asset are served in memory, and
the catalog is replaced by synthetic records whose digests match a synthetic archive.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import re
import tarfile
import time
from urllib.parse import parse_qs, urlsplit

from types import SimpleNamespace

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
REPO = Path(__file__).resolve().parents[2]
QUALIFIED = REPO / ".github" / "workflows" / "qualified-agy-image.yml"
RELEASES = "https://api.github.com/repos/google-antigravity/antigravity-cli/releases"
LISTING = f"{RELEASES}?per_page=100"
PUBLISHED = "2026-11-19T08:38:26Z"
PUBLISHED_S = 1_795_077_506  # PUBLISHED as a POSIX time
INSIDE = "::warning::agy catalog lag: {} is not a member yet, inside the 48 h bound"
DOWNLOAD = "https://github.com/google-antigravity/antigravity-cli/releases/download/"
ASSET = "agy_cli_linux_x64.tar.gz"
WARNING = "::warning::newest upstream agy {} is not a shipped member; hosts self-qualify it on first use"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or not QUALIFIED.is_file(),
    reason="the verifier and its workflow are repository source, absent from the standalone layout",
)


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(executable):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("antigravity")
        info.size = len(executable)
        bundle.addfile(info, io.BytesIO(executable))
    return buffer.getvalue()


class Upstream:
    """The release listing, by-tag lookups and asset downloads; records every URL.

    The listing is ``ahead`` (entries the stable filter must skip), then ``latest``, then the
    other releases."""

    def __init__(self):
        self.releases, self.blobs, self.calls = {}, {}, []
        self.latest, self.ahead = None, []

    def add(self, version, archive, *, digest=None, url=None):
        url = url or f"{DOWNLOAD}{version}/{ASSET}"
        self.blobs[url] = archive
        self.releases[version] = {"tag_name": version, "draft": False, "prerelease": False,
                                  "published_at": PUBLISHED, "assets": [
                                      {"name": ASSET, "browser_download_url": url,
                                       "digest": digest or "sha256:" + sha256(archive).hexdigest()}]}

    def listing(self):
        rest = [release for tag, release in self.releases.items() if tag != self.latest]
        return self.ahead + [self.releases[self.latest]] + rest

    def urlopen(self, request, timeout=None):
        url = getattr(request, "full_url", request)
        self.calls.append(url)
        assert url != f"{RELEASES}/latest", "the newest release comes from the listing"
        if url == LISTING:
            return io.BytesIO(json.dumps(self.listing()).encode())
        if url.startswith(f"{RELEASES}/tags/"):
            return io.BytesIO(json.dumps(self.releases[url.rsplit("/", 1)[1]]).encode())
        return io.BytesIO(self.blobs[url])


@pytest.fixture
def world(verifier, monkeypatch, tmp_path):
    """Three shipped members out of version order, each with a matching synthetic asset.

    Catalog order (and string order) would pick 1.9.0; the newest member is 1.10.0.
    """
    upstream = Upstream()
    records, archives = [], {}
    for version in ("1.0.0", "1.10.0", "1.9.0"):
        executable = f"#!/bin/sh\necho synthetic agy {version}\n".encode()
        archive = _archive(executable)
        archives[version] = tmp_path / f"{version}.tar.gz"
        archives[version].write_bytes(archive)
        upstream.add(version, archive)
        records.append({"release_version": version, "upstream_asset_sha256": sha256(archive).hexdigest(),
                        "image_sha256": sha256(executable).hexdigest(), "source_sha256": {"x.py": "0" * 64}})
    upstream.add("2.0.0", _archive(b"#!/bin/sh\necho not a member\n"))
    upstream.latest = "2.0.0"
    monkeypatch.setattr(verifier, "contract", lambda: records)
    monkeypatch.setattr(verifier, "urlopen", upstream.urlopen)  # asset downloads
    # Releases API reads go through their own redirect-confined opener (agent-harness#1993).
    monkeypatch.setattr(verifier, "_api_opener", lambda *handlers: SimpleNamespace(open=upstream.urlopen))

    def run(*extra, now=PUBLISHED_S + 3600, in_flight=lambda version: [], environ=None):
        # The mode's own function, so a refusal surfaces as its ValueError (main() turns it
        # into exit status 1, tested below). By default the newest release is an hour old.
        archive = Path(extra[extra.index("--archive") + 1]) if "--archive" in extra else None
        result = {**verifier.upstream_only(archive, now=now, in_flight=in_flight, environ=environ or {}),
                  "verified": True}
        print(json.dumps(result))
        return result

    return upstream, archives, run


def _result(capsys):
    lines = capsys.readouterr().out.strip().splitlines()
    return lines[:-1], json.loads(lines[-1])


def test_a_newer_non_member_upstream_only_warns(world, capsys):
    """Mutation: keeping the membership ``require`` (the job reds on every new agy)."""
    upstream, archives, run = world
    run("--archive", str(archives["1.10.0"]))
    annotations, result = _result(capsys)
    assert annotations == [WARNING.format("2.0.0"), INSIDE.format("2.0.0")]
    assert result["latest_release"] == "2.0.0" and result["latest_is_member"] is False
    assert result["verified_member"] == "1.10.0" and result["verified"] is True
    assert f"{RELEASES}/tags/1.10.0" in upstream.calls


def test_the_newest_member_is_fetched_and_its_archive_downloaded_by_tag(world, capsys):
    upstream, _archives, run = world
    run()
    annotations, result = _result(capsys)
    assert annotations == [WARNING.format("2.0.0"), INSIDE.format("2.0.0")]
    assert result["verified_member"] == "1.10.0"
    # the newest member's archive, then the newest release's for its headroom
    assert upstream.calls == [LISTING, f"{RELEASES}/tags/1.10.0", f"{DOWNLOAD}1.10.0/{ASSET}",
                              f"{DOWNLOAD}2.0.0/{ASSET}"]


def test_a_member_latest_verifies_without_a_warning(world, capsys):
    upstream, archives, run = world
    upstream.latest = "1.10.0"
    run("--archive", str(archives["1.10.0"]))
    annotations, result = _result(capsys)
    assert annotations == []
    assert result["latest_release"] == "1.10.0" and result["latest_is_member"] is True
    assert result["verified_member"] == "1.10.0"


@pytest.mark.parametrize("mismatch", ["asset_digest", "asset_url", "archive"])
@pytest.mark.parametrize("latest", ["2.0.0", "1.10.0"])
def test_a_shipped_member_integrity_mismatch_still_fails(world, capsys, mismatch, latest):
    """The member checks stay ``require``s whether or not the latest upstream is a member.

    Mutation: dropping the member-digest ``require`` (or making it advisory) greens the
    ``asset_digest`` cells.
    """
    upstream, archives, run = world
    upstream.latest = latest
    archive = archives["1.10.0"].read_bytes()
    if mismatch == "asset_digest":
        upstream.add("1.10.0", archive, digest="sha256:" + "0" * 64)
        reason = "vendor asset digest mismatch"
    elif mismatch == "asset_url":
        upstream.add("1.10.0", archive, url=f"https://example.invalid/1.10.0/{ASSET}")
        reason = "vendor asset URL mismatch"
    else:
        archives["1.10.0"].write_bytes(_archive(b"#!/bin/sh\necho substituted\n"))
        reason = "archive digest mismatch"
    with pytest.raises(ValueError, match=reason):
        run("--archive", str(archives["1.10.0"]))
    assert '"verified": true' not in capsys.readouterr().out


def test_a_substituted_executable_inside_a_matching_archive_fails(world, verifier, monkeypatch):
    upstream, archives, run = world
    substituted = _archive(b"#!/bin/sh\necho substituted\n")
    records = verifier.contract()
    newest = next(record for record in records if record["release_version"] == "1.10.0")
    newest["upstream_asset_sha256"] = sha256(substituted).hexdigest()
    upstream.add("1.10.0", substituted)
    archives["1.10.0"].write_bytes(substituted)
    with pytest.raises(ValueError, match="executable digest mismatch"):
        run("--archive", str(archives["1.10.0"]))


def test_the_upstream_job_step_is_blocking():
    """The step reds on a member-integrity failure. Mutation: ``continue-on-error``."""
    job = yaml.safe_load(QUALIFIED.read_text())["jobs"]["upstream"]
    (step,) = [step for step in job["steps"] if "--upstream-only" in step.get("run", "")]
    assert step["run"] == ('uv run --locked python scripts/verify_qualified_agy_image.py --upstream-only '
                           '--report "$RUNNER_TEMP/agy-lag-report.json"')
    assert step["working-directory"] == "phase-loop-runtime"
    assert "continue-on-error" not in step and "if" not in step
    assert "continue-on-error" not in job


def test_main_reports_an_upstream_refusal_as_exit_status_one(world, verifier, monkeypatch, capsys):
    upstream, archives, run = world
    records = verifier.contract()
    next(r for r in records if r["release_version"] == "1.10.0")["upstream_asset_sha256"] = "0" * 64
    assert verifier.main(["--upstream-only", "--archive", str(archives["1.10.0"])]) == 1
    assert "verify_qualified_agy_image:" in capsys.readouterr().err


# ------------------------------------------------- PROVFWD: the newest release from the listing

#: One listing for both filters: drafts, prereleases and non-release tags ahead of the newest.
SHARED_LISTING = [
    {"tag_name": "3.0.0", "draft": True, "prerelease": False, "published_at": "2026-11-20T00:00:00Z"},
    {"tag_name": "2.9.0", "draft": False, "prerelease": True, "published_at": "2026-11-19T12:00:00Z"},
    {"tag_name": "nightly", "draft": False, "prerelease": False, "published_at": "2026-11-19T11:00:00Z"},
    {"tag_name": "2.5.0", "draft": None, "prerelease": False, "published_at": "2026-11-19T10:00:00Z"},
    {"tag_name": "2.1.0", "draft": False, "prerelease": False, "published_at": "2026-11-19T09:00:00Z"},
    {"tag_name": "2.0.0", "draft": False, "prerelease": False, "published_at": "2026-11-18T09:00:00Z"},
]


class _Listing:
    """``agy_provenance``'s transport over ``SHARED_LISTING`` (one short page)."""

    def open(self, url, *, accept):
        first = parse_qs(urlsplit(url).query).get("page", ["1"]) == ["1"]
        return io.BytesIO(json.dumps(SHARED_LISTING if first else []).encode())


def test_newest_stable_uses_the_resolvers_stable_filter(verifier):
    """Mutation: ``/releases/latest`` (GitHub's choice), or a filter that keeps a draft or a
    prerelease ahead of the newest stable release."""
    from phase_loop_runtime import agy_provenance as prov
    seen = []
    newest = verifier.newest_stable(lambda url: seen.append(url) or SHARED_LISTING)
    assert newest["tag_name"] == "2.1.0" == prov.stable_releases(_Listing())[0]["tag_name"]
    assert seen == [LISTING]


@pytest.mark.parametrize("listing", [[], [SHARED_LISTING[0], SHARED_LISTING[1]], {"tag_name": "2.0.0"}, None])
def test_a_listing_without_a_stable_release_refuses(verifier, listing):
    with pytest.raises(ValueError, match="listing"):
        verifier.newest_stable(lambda url: listing)


def test_upstream_only_skips_entries_ahead_of_the_newest_stable_release(world, capsys):
    upstream, archives, run = world
    upstream.latest = "1.10.0"
    upstream.ahead = [dict(upstream.releases["2.0.0"], tag_name="3.0.0", prerelease=True),
                      dict(upstream.releases["2.0.0"], tag_name="2.9.0", draft=True)]
    run("--archive", str(archives["1.10.0"]))
    annotations, result = _result(capsys)
    assert annotations == [] and result["latest_release"] == "1.10.0" and result["latest_is_member"] is True
    assert result["lag"]["status"] == "ok"


def test_the_result_carries_the_newest_releases_published_at(world, capsys):
    upstream, archives, run = world
    upstream.releases["2.0.0"]["published_at"] = "2026-11-20T01:02:03Z"
    run("--archive", str(archives["1.10.0"]))
    _, result = _result(capsys)
    assert result["latest_published_at"] == "2026-11-20T01:02:03Z" and result["latest_release"] == "2.0.0"


def test_the_verifier_has_exactly_its_five_modes(verifier, capsys):
    with pytest.raises(SystemExit):
        verifier.main(["--help"])
    usage = " ".join(capsys.readouterr().out.split())
    assert "(--contract | --release | --upstream-only | --intake ISSUE | --catalog-pr)" in usage
    assert usage.count("--") == len(re.findall(
        r"--(?:contract|release|upstream-only|intake|catalog-pr|conformance-report|archive|report|out|base|head|pr|help)"
        r"\b", usage))


# ------------------------------------------- ROLLJOB: the lag rule, both modes, and headroom

HOUR = 3600
ATTESTED = {"schema": "agy_rollout_attestation.v1", "status": "attested",
            "intake_app": {"app_id": 11, "bot_user_id": 111}, "promotion_app": {"app_id": 22, "bot_user_id": 222},
            "main_ruleset": {"id": 5, "target": "refs/heads/main", "enforcement": "active", "bypass_actors": [],
                             "strict_required_status_checks": True,
                             "required_checks": ["agy catalog provenance", "agy catalog contract"]},
            "catalog_ruleset": {"id": 6, "target": "refs/heads/agy-catalog/**", "enforcement": "active",
                                "rules": ["creation", "update", "deletion"],
                                "bypass_actors": [{"actor_type": "Integration", "actor_id": 22,
                                                   "bypass_mode": "always"}]},
            "promotion_environment": {"name": "agy-promotion", "branches": ["main"], "required_reviewers": 0,
                                      "admin_bypass": False},
            "attested_by": "owner", "attested_at": "2026-11-21T00:00:00Z"}


@pytest.mark.parametrize("enforced", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("member", "ok"), ("young", "warn_inside_bound"), ("in_flight", "warn_pr_open"), ("lagging", "fail")])
def test_each_lag_status_in_both_modes(world, verifier, capsys, enforced, case, expected):
    """EC-ROLLJOB-3: report-only never changes the exit; enforced fails only on ``fail``."""
    upstream, archives, run = world
    if case == "member":
        upstream.latest = "1.10.0"
    now = PUBLISHED_S + (HOUR if case == "young" else 49 * HOUR)
    result = run("--archive", str(archives["1.10.0"]), now=now,
                 in_flight=lambda version: [42] if case == "in_flight" else [],
                 environ={"AGY_LAG_ENFORCE": "true"} if enforced else {})
    annotations, printed = _result(capsys)
    assert printed == result and result["lag"]["status"] == expected
    assert result["lag"]["enforced"] is enforced and result["lag"]["release"] == result["latest_release"]
    assert verifier.upstream_exit(result) == (1 if enforced and expected == "fail" else 0)
    lag_lines = [line for line in annotations if "agy catalog lag" in line]
    if expected == "fail":
        assert lag_lines == [f"::{'error' if enforced else 'warning'}::agy catalog lag: 2.0.0 is not a member after "
                             f"the 48 h bound and no promotion is in flight"
                             + ("" if enforced else " (report-only until ACTIVATE)")]
    elif expected == "warn_pr_open":
        assert lag_lines and "agent-harness#42" in lag_lines[0] and lag_lines[0].startswith("::warning::")
    elif expected == "ok":
        assert lag_lines == []


@pytest.mark.parametrize("value", ["", "false", "TRUE", "1", "yes", " true"])
def test_any_switch_value_but_exactly_true_is_report_only(world, verifier, capsys, value):
    upstream, archives, run = world
    result = run("--archive", str(archives["1.10.0"]), now=PUBLISHED_S + 49 * HOUR, environ={"AGY_LAG_ENFORCE": value})
    assert result["lag"]["status"] == "fail" and result["lag"]["enforced"] is False
    assert verifier.upstream_exit(result) == 0


def test_an_unreadable_or_incomplete_pull_listing_counts_as_nothing_in_flight(verifier):
    attested = json.dumps(ATTESTED)

    def down(url):
        raise OSError("api down")

    def full_pages(url):  # never a short page: the end is never reached
        if "/pulls?" in url:
            return [{"number": n, "head": {"ref": "other", "repo": {"full_name": "Consiliency/agent-harness"}}}
                    for n in range(100)]
        raise AssertionError(url)

    for fetch in (down, lambda url: {"message": "not a list"}, full_pages):
        assert verifier.promotions_in_flight("2.0.0", now=PUBLISHED_S, fetch=fetch, environ={},
                                             attestation_text=attested) == []


def _pulls_world(now):
    created = lambda age: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - age))  # noqa: E731
    pulls = [
        {"number": 1, "head": {"ref": "agy-catalog/2.0.0-77-1", "repo": {"full_name": "Consiliency/agent-harness"}},
         "created_at": created(HOUR)},                                   # the App's, young: in flight
        {"number": 2, "head": {"ref": "agy-catalog/2.0.0-70-1", "repo": {"full_name": "Consiliency/agent-harness"}},
         "created_at": created(25 * HOUR)},                              # the App's, too old
        {"number": 3, "head": {"ref": "agy-catalog/2.0.0-71-1", "repo": {"full_name": "Consiliency/agent-harness"}},
         "created_at": created(HOUR)},                                   # another author
        {"number": 4, "head": {"ref": "agy-catalog/2.0.0-72-1", "repo": {"full_name": "someone/fork"}},
         "created_at": created(HOUR)},                                   # a fork's branch
        {"number": 5, "head": {"ref": "agy-catalog/1.9.0-73-1", "repo": {"full_name": "Consiliency/agent-harness"}},
         "created_at": created(HOUR)},                                   # another version
    ]
    app = {"user": {"login": "agy-promotion[bot]", "id": 222, "type": "Bot"},
           "performed_via_github_app": {"id": 22}}
    issues = {1: app, 2: app, 3: {"user": {"login": "agy-promotion[bot]", "id": 999, "type": "User"},
                                  "performed_via_github_app": None}, 4: app, 5: app,
              9: dict(app, title="agy intake: 2.0.0")}  # an intake issue: never listed as a pull request
    seen = []

    def fetch(url):
        seen.append(url)
        if "/pulls?" in url:
            return pulls if "page=1" in url else []
        return issues[int(url.rsplit("/", 1)[1])]

    return fetch, seen


def test_only_a_young_promotion_app_pull_request_on_this_repository_counts_as_in_flight(verifier):
    import time as clock
    now = clock.time()
    fetch, seen = _pulls_world(now)
    assert verifier.promotions_in_flight("2.0.0", now=now, fetch=fetch, environ={},
                                         attestation_text=json.dumps(ATTESTED)) == [1]
    assert [url for url in seen if "/pulls?" in url] == [
        "https://api.github.com/repos/Consiliency/agent-harness/pulls?state=open&per_page=100&page=1"]
    assert not any(url.endswith("/issues/9") for url in seen)


def test_with_an_unattested_file_nothing_is_in_flight(verifier):
    import time as clock
    now = clock.time()
    fetch, seen = _pulls_world(now)
    assert verifier.promotions_in_flight("2.0.0", now=now, fetch=fetch, environ={}) == []  # the shipped file
    assert seen == []


@pytest.mark.parametrize("percent,expected", [(79, "ok"), (80, "warn"), (89, "warn"), (90, "fail")])
@pytest.mark.parametrize("part", ["archive", "member"])
def test_headroom_at_the_thresholds_for_the_archive_and_the_member(world, verifier, monkeypatch, capsys,
                                                                   percent, expected, part):
    """EC-ROLLJOB-8: warn at 80 percent, fail at 90, for the newest release (member or not)."""
    upstream, archives, run = world
    upstream.latest = "1.10.0"
    archive_size, member_size = verifier.archive_sizes(archives["1.10.0"])
    size = archive_size if part == "archive" else member_size
    # at a threshold (80, 90) the size reaches it; just under one (79, 89) it does not
    bound = size * 100 // percent if percent in (80, 90) else -(-size * 100 // percent)
    monkeypatch.setattr(verifier, "MAX_ARCHIVE_BYTES" if part == "archive" else "MAX_MEMBER_BYTES", bound)
    result = run("--archive", str(archives["1.10.0"]))
    annotations, _ = _result(capsys)
    assert result["headroom"][part]["status"] == expected and result["headroom"]["release"] == "1.10.0"
    other = "member" if part == "archive" else "archive"
    assert result["headroom"][other]["status"] == "ok"
    assert verifier.upstream_exit(result) == (1 if expected == "fail" else 0)
    lines = [line for line in annotations if f" {part} is " in line]
    assert len(lines) == (0 if expected == "ok" else 1)
    if lines:
        assert lines[0].startswith("::error::" if expected == "fail" else "::warning::")


def test_headroom_fails_whatever_the_lag_switch_says(world, verifier, monkeypatch):
    upstream, archives, run = world
    upstream.latest = "1.10.0"
    archive_size, _member = verifier.archive_sizes(archives["1.10.0"])
    monkeypatch.setattr(verifier, "MAX_ARCHIVE_BYTES", archive_size * 100 // 95)
    result = run("--archive", str(archives["1.10.0"]), environ={})
    assert result["lag"]["status"] == "ok" and verifier.upstream_exit(result) == 1


def test_headroom_is_measured_for_a_non_member_newest_release(world, verifier, capsys):
    upstream, archives, run = world
    result = run("--archive", str(archives["1.10.0"]))
    assert result["headroom"]["release"] == "2.0.0" and result["latest_is_member"] is False
    assert f"{DOWNLOAD}2.0.0/{ASSET}" in upstream.calls


def test_main_writes_the_report_equal_to_the_printed_result_and_exits_by_mode(world, verifier, monkeypatch,
                                                                              capsys, tmp_path):
    import functools
    upstream, archives, run = world
    real = verifier.upstream_only
    for enforce, code in (("", 0), ("true", 1)):
        monkeypatch.setattr(verifier, "upstream_only", functools.partial(
            real, now=PUBLISHED_S + 49 * HOUR, in_flight=lambda version: [], environ={"AGY_LAG_ENFORCE": enforce}))
        report = tmp_path / f"report-{enforce or 'off'}.json"
        assert verifier.main(["--upstream-only", "--archive", str(archives["1.10.0"]), "--report", str(report)]) == code
        printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert json.loads(report.read_text()) == printed
        assert printed["lag"] == {"status": "fail", "enforced": enforce == "true", "release": "2.0.0",
                                  "published_at": PUBLISHED, "bound_s": 48 * 3600, "in_flight": []}


def test_report_is_only_for_upstream_only(verifier, tmp_path):
    with pytest.raises(SystemExit):
        verifier.main(["--contract", "--report", str(tmp_path / "r.json")])


def test_only_the_upstream_job_may_write_issues_and_it_names_only_the_activation_environment():
    workflow = yaml.safe_load(QUALIFIED.read_text())
    assert workflow["permissions"] == {"contents": "read"}
    upstream = workflow["jobs"]["upstream"]
    assert upstream["permissions"] == {"contents": "read", "issues": "write", "pull-requests": "read"}
    assert upstream["environment"] == "agy-activation"
    # write-capable, so main only: a dispatch can name any ref
    assert upstream["if"] == ("github.ref == 'refs/heads/main' && (github.event_name == 'schedule' "
                              "|| github.event_name == 'workflow_dispatch')")
    for name, job in workflow["jobs"].items():
        if name != "upstream":
            assert "environment" not in job and (job.get("permissions") or {}).get("issues") != "write"
    (verify,) = [s for s in upstream["steps"] if "--upstream-only" in s.get("run", "")]
    assert verify["env"]["AGY_LAG_ENFORCE"] == "${{ vars.AGY_LAG_ENFORCE }}"
    (report,) = [s for s in upstream["steps"] if s.get("run") == "ci/agy-lag-issue.sh"]
    assert report["if"] == "always()" and report["env"] == {
        "AGY_LAG_REPORT": "${{ runner.temp }}/agy-lag-report.json", "GH_TOKEN": "${{ github.token }}"}
    assert upstream["steps"].index(report) == len(upstream["steps"]) - 1
    assert "agy-lag-report.json" in verify["run"]
