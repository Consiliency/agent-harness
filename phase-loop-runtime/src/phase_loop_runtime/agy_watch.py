"""The rolling catalog job: the upstream agy release watch (agent-harness#1076, AGYROLL ROLLJOB).

It is deliberately OUTSIDE the seat QCI (``agy_qualification.seat_qci()``): a watch-only fix
never forces a requalification. One tick, run hourly by a user timer on the qualification
host (ROLLJOB-detail §2.1):

1. the platform check: only the release route (Linux x64 glibc) is proposed;
2. (not a dry run) a local preflight, before any live operation: the INTAKE App's key, ids
   and the ``agy-watch`` extra (``agy_intake.preflight``), and the job's signing key;
3. the login (R7): a fresh login costs one file read. Otherwise the login is renewed with
   the image seat admission admits on this host (``admit_seat``, lookup only: the host's own
   subject, or a held image when HOLD applies; never the unqualified candidate). No admitted
   image, or a login still not fresh after renewal, ends the tick ``gemini_login_expired``;
4. signed records kept from a failed submission, of any version, are submitted again first,
   without re-qualifying; the tick reports ``agy_intake_submit_failed`` until none is left.
   Then the newest stable release: ``already_pinned`` when it is a member on ``origin/main``,
   ``up_to_date`` when a submission for it at the tree's QCI is pending (``agy_intake``);
5. the work set: the newest non-member release plus every member whose catalog ``qci`` is
   not the prepared tree's ``seat_qci()``. Members whose ``qci`` matches are not fetched;
6. per member, one at a time (EC-ROLLJOB-9): stream it to a sealed image, measure help with
   the tree's owned profile, run the series (three operations and ``--validate``) with
   retries, write the signed record, and close the image before the next member;
7. ``--contract`` on the prepared tree (its local catalog edit lets the worker gate pass and
   is never pushed; the trusted workflow builds the catalog, aging included);
8. each signed record is submitted through the INTAKE App (``agy_intake.submit``).

**The job makes no git write.** The checkout is fetched, never pushed; there is no branch,
no commit and no pull request. Every return path prints ``{"agy_watch": <status>, ...}`` and
writes the same status and exit code to the tick-status file that ``watch --check`` reads;
``--dry-run`` writes no status and submits nothing.

Each record carries two statuses (AGYROLL §1.3, ``agy_attestation``): a fresh
``attestation`` for every member, and for the new member the ``second_channel`` check against
Google's installer manifest. A second-channel mismatch, or either status unavailable, ends
the tick with exit 2 before anything is submitted.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from . import agy_attestation
from . import agy_catalog_policy as policy
from . import agy_intake
from . import agy_provenance
from . import gemini_heartbeat as gh

RELEASE_ROUTE_PLATFORM = "linux-x64"
CATALOG = policy.CATALOG_PATH
RECORD_SCHEMA = "agy_redacted_qualification_summary.v2"
OPERATIONS = ("completion", "cancel", "owner-loss")

LOGIN_EXPIRED = "gemini_login_expired"
SERIES_VIOLATION = "series_violation"
SERIES_UNAVAILABLE = "series_unavailable"
#: What the renewal raises when the login is still not usable after it: the same
#: ``gemini_login_expired``. Any other failure of the renewal propagates.
_RENEWAL_REFUSALS = frozenset({"gemini_credential_near_expiry", "gemini_credential_refresh_timeout",
                               "seat_profile_unavailable"})


def _run(runner, argv, **kwargs):
    kwargs.setdefault("check", True)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return runner(argv, **kwargs)


_IDENTITY_PROGRAM = ("import sys; sys.path.insert(0, sys.argv[1]); "
                     "from phase_loop_runtime import __version__; "
                     "from phase_loop_runtime.agy_qualification import seat_qci; "
                     "print(seat_qci()); print(__version__)")
# The PREPARED tree's own classifier (``agy_qualification._classify_failure``), called, never
# copied or changed (ROLLJOB-detail §2.3).
_CLASSIFY_PROGRAM = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                     "from phase_loop_runtime.agy_qualification import _classify_failure; "
                     "print(_classify_failure(Path(sys.argv[2]), sys.argv[3]))")


def tree_identity(tree: Path, *, python: str, runner) -> tuple[str, str]:
    """(``seat_qci()``, ``__version__``) of the prepared tree, computed by THAT tree's code."""
    lines = _run(runner, [python, "-I", "-c", _IDENTITY_PROGRAM, str(tree / "phase-loop-runtime/src")]).stdout.split()
    if len(lines) != 2 or not re.fullmatch(r"[0-9a-f]{64}", lines[0]):
        raise ValueError("agy watch cannot compute the prepared tree's seat QCI")
    return lines[0], lines[1]


def classify_failure(tree: Path, root: Path, operation: str, *, python: str, runner) -> str:
    """``failed`` or ``transient`` for a failed operation's directory, by the prepared tree's
    ``_classify_failure``. Anything unreadable is ``failed`` (a violation stops the tick)."""
    done = _run(runner, [python, "-I", "-c", _CLASSIFY_PROGRAM, str(tree / "phase-loop-runtime/src"),
                         str(root), operation], check=False)
    verdict = (done.stdout or "").strip() if getattr(done, "returncode", 1) == 0 else ""
    return verdict if verdict in ("failed", "transient") else "failed"


def pinned_versions(tree: Path) -> set[str]:
    return {member["release_version"] for member in _catalog_members(tree)}


def edit_catalog(tree: Path, *, version: str, image_sha256: str, help_sha256: str, asset_sha256: str,
                 qci: str, published_at: str) -> None:
    """Add (or replace) one member in the prepared tree's data catalog, the only file a member
    edits (AGYROLL §3.1). A replaced member keeps its ``pinned`` flag, which only a human
    sets. This edit is local to the prepared tree: it is never pushed."""
    path = tree / CATALOG
    catalog = json.loads(path.read_text())
    members = catalog["routes"]["linux-x64"]
    pinned = any(m["release_version"] == version and m["pinned"] for m in members)
    catalog["routes"]["linux-x64"] = [m for m in members if m["release_version"] != version] + [{
        "release_version": version, "image_sha256": image_sha256, "help_sha256": help_sha256,
        "asset_sha256": asset_sha256, "qci": qci, "published_at": published_at, "pinned": pinned,
        "record": f"agy-{version}-linux-x64-qualification.json"}]
    text = json.dumps(catalog, indent=2) + "\n"
    gh.parse_catalog(text)  # never write a catalog the runtime would refuse
    path.write_text(text)


def _catalog_members(tree: Path) -> list[dict]:
    return gh.parse_catalog((tree / CATALOG).read_text())


def stream_image(transport, asset, workdir=None) -> gh.VerifiedImage:
    """One member as one sealed image, never held as ``bytes`` (EC-ROLLJOB-9).

    The member is streamed to an anonymous file in the private work directory as it is
    hashed (``fetch_member(..., sink=)``); a refusal discards the file. The image is built
    from it with ``VerifiedImage.from_fd`` and its digest must be the member digest the
    archive check returned. The file is closed before this returns."""
    with tempfile.TemporaryFile(dir=workdir) as sink:
        digest = agy_provenance.fetch_member(transport, asset, sink=sink.fileno())
        os.lseek(sink.fileno(), 0, os.SEEK_SET)
        image = gh.VerifiedImage.from_fd(sink.fileno())
    if image.sha256 != digest:
        image.close()
        raise agy_provenance.ProvenanceError(agy_provenance.UNVERIFIED)
    return image


def _pinned_member(tree: Path, member: dict, host, transport, workdir=None):
    """Re-fetch an existing member's image; its release asset digest and image digest must
    equal its committed record's. Returns ``(asset, image, help_sha256)``; the caller closes
    the image."""
    record = json.loads((tree / "plans/evidence" / member["record"]).read_text())
    asset = agy_provenance.release_asset(agy_provenance.release_by_tag(transport, member["release_version"]), host)
    if asset.digest != record["upstream_asset_sha256"]:
        raise agy_provenance.ProvenanceError(agy_provenance.UNVERIFIED)
    image = stream_image(transport, asset, workdir)
    if image.sha256 != member["image_sha256"] or image.sha256 != record["image_sha256"]:
        image.close()
        raise agy_provenance.ProvenanceError(agy_provenance.UNVERIFIED)
    return asset, image, member["help_sha256"]


def summarize(tree: Path, series: Path, asset, image_sha256: str, help_sha256: str, *,
              qci: str, qualified_under: str, template_name: str | None = None,
              attestation: str = "not_checked", second_channel: str | None = "not_checked") -> dict:
    """The redacted record, in the shape of a committed record (see the release process's
    regeneration rule): each operation row is its receipt restricted to the template row's
    keys. A requalified member is its own template; a new one takes the newest other. The
    record is v2 (AGYROLL §3.2): bound to the tree's seat QCI, with no source pins and an
    empty ``signatures`` list, to which the tick appends the job signature (ROLLJOB-detail §2.4).

    ``attestation`` and ``second_channel`` go into ``upstream``. ``second_channel=None`` keeps
    the committed value, so only a requalified member (its own template) may pass it."""
    members = _catalog_members(tree)
    if template_name is None:
        if second_channel is None:
            raise ValueError("agy watch: a new member's second channel must be checked, not kept")
        template_name = next(m["record"] for m in reversed(members) if m["release_version"] != asset.version)
    template = json.loads((tree / "plans/evidence" / template_name).read_text())
    if second_channel is None:
        second_channel = template["upstream"]["second_channel"]

    def restrict(value, shape):
        if isinstance(shape, dict):
            source = value if isinstance(value, dict) else {}
            return {key: restrict(source.get(key), shape[key]) for key in shape}
        return value

    shapes = {row["operation"]: row for row in template["records"]}
    rows, sources = [], set()
    for operation in sorted(OPERATIONS):
        raw = (series / operation / "qualification.json").read_bytes()
        receipt = json.loads(raw)
        sources.add(json.dumps(receipt["source_sha256"], sort_keys=True))
        row = {}
        for key in shapes[operation]:
            if key == "raw_receipt_sha256":
                row[key] = sha256(raw).hexdigest()
            elif key == "request_digests":
                row[key] = receipt["request"]
            else:
                row[key] = restrict(receipt.get(key), shapes[operation][key])
        rows.append(row)
    if len(sources) != 1:
        raise ValueError("agy watch receipts disagree on source pins")
    release_url = f"https://github.com/{agy_provenance.REPO}/releases/tag/{asset.version}"
    record = {key: value for key, value in template.items() if key != "source_sha256"}
    record.update({
        "schema": RECORD_SCHEMA, "release_version": asset.version,
        "image_sha256": image_sha256, "help_sha256": help_sha256,
        "upstream_asset_name": asset.name, "upstream_asset_sha256": asset.digest,
        "upstream_release_url": release_url, "records": rows,
        "validator": {"validated": 3, "operations": ["cancel", "completion", "owner-loss"], "route_qualified": True},
        "qci": qci, "qualified_under": qualified_under,
        "upstream": {"asset_sha256": asset.digest, "release_url": release_url,
                     "attestation": attestation, "second_channel": second_channel},
        "signatures": [],
    })
    return record


def _tree_python(tree: Path, python: str, args, *, image_fd: int, runner, env):
    return _run(runner, [python, str(tree / "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py"), *args,
                         "--image-fd", str(image_fd)],
                cwd=tree / "phase-loop-runtime", env={**env, "PYTHONPATH": str(tree / "phase-loop-runtime/src")},
                pass_fds=(image_fd,))


def _measure_help(tree, python, image, path: Path, *, runner, env) -> str:
    fd = image.reopen()
    try:
        _tree_python(tree, python, ["--measure-help", "--output", str(path)], image_fd=fd, runner=runner, env=env)
    finally:
        os.close(fd)
    return sha256(path.read_bytes()).hexdigest()


def run_series(tree, python, image, help_path: Path, workdir: Path, version: str, *, runner, env):
    """The series (the three operations, then ``--validate``) for one image, as the prepared
    tree's shim runs it. Returns the passing series directory, or a status: a ``failed``
    classification (or a ``--validate`` refusal) is ``series_violation`` at once; a
    ``transient`` one retries the whole series in a fresh directory, ``SERIES_RETRIES``
    attempts in all, after which it is ``series_unavailable``."""
    shim = str(tree / "phase-loop-runtime/scripts/qualify_gemini_heartbeat.py")
    for attempt in range(1, policy.SERIES_RETRIES + 1):
        series = workdir / "series" / f"{version}-{attempt}"
        series.mkdir(parents=True)
        failed = None
        try:
            for operation in OPERATIONS:
                failed = operation
                fd = image.reopen()
                try:
                    _tree_python(tree, python, ["--operation", operation, "--output", str(series / operation),
                                                "--help-evidence", str(help_path)],
                                 image_fd=fd, runner=runner, env=env)
                finally:
                    os.close(fd)
            failed = None
            _run(runner, [python, shim, "--validate", str(series)], cwd=tree / "phase-loop-runtime",
                 env={**env, "PYTHONPATH": str(tree / "phase-loop-runtime/src")})
            return series
        except subprocess.CalledProcessError:
            if failed is None:
                return SERIES_VIOLATION  # the validator refused the receipts
            if classify_failure(tree, series / failed, failed, python=python, runner=runner) != "transient":
                return SERIES_VIOLATION
    return SERIES_UNAVAILABLE


def _signing_key_safe(path) -> bool:
    try:
        info = os.stat(path, follow_symlinks=False) if path else None
    except OSError:
        return False
    return info is not None and stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077


def _login_fresh(panel, home) -> bool:
    try:
        left = panel._gemini_login_left_s(home)
    except (panel._sandbox_egress.EgressUnavailable, ValueError, OSError):
        left = None  # no readable login file is not a fresh login
    return left is not None and left >= panel._GEMINI_LOGIN_MIN_S


def renew_login(home) -> bool:
    """Whether the job's login is fresh, renewing it when it is not (R7, ROLLJOB-detail §2.1).

    A fresh login costs one file read and makes no admission call. Otherwise the image that
    lookup-only seat admission admits on this host (the subject, or a held image under
    HOLD; never the candidate) renews it through ``_await_gemini_login`` then
    ``_refresh_gemini_credential``. Any ``ValueError`` from admission means "no admitted
    image" (no ``reason`` is read): ``False``, with no renewal call. A typed failure that is
    not a refusal propagates unchanged."""
    from . import agy_qualification
    from . import panel_invoker as panel
    home = Path(home)
    if _login_fresh(panel, home):
        return True
    env = panel._broker_subscription_env()
    env["HOME"] = str(home)
    try:
        admission = agy_qualification.admit_seat(env, None, first_use=False)
    except ValueError:
        return False
    try:
        panel._await_gemini_login(["agy", "models"], env)
        try:
            panel._refresh_gemini_credential(home, admission.image)
        except panel._sandbox_egress.SeatIdentityUnverified as exc:
            if str(exc) not in _RENEWAL_REFUSALS:
                raise
    finally:
        admission.close()
    return _login_fresh(panel, home)


def main(*, repo=None, dry_run=False, runner=subprocess.run, host=None, transport=None,
         python=sys.executable, workdir=None, out=print, version=None, base_ref="origin/main",
         intake_transport=None, environ=None, home=None, store=None) -> int:
    """One watch tick. ``version`` selects any listed stable release instead of the newest
    (an operator re-run, which also ignores the wait after a refused submission, or a dry run
    against a non-pinned build). ``base_ref`` is for a dry run only: a submitting tick always
    prepares from ``origin/main``."""
    if base_ref != "origin/main" and not dry_run:
        raise ValueError("agy watch: --base-ref is only for --dry-run")
    environ = os.environ if environ is None else environ

    def finish(status, code, **extra):
        out(json.dumps({"agy_watch": status, **extra}))
        if not dry_run:
            policy.write_tick_status(status, code, version=extra.get("version"), environ=environ)
        return code

    host = host or agy_provenance.detect_platform()
    if host.name != RELEASE_ROUTE_PLATFORM:
        return finish("platform_not_proposed", 0, platform=host.name)
    intake = None
    if not dry_run:
        try:
            intake = agy_intake.preflight(environ)
        except agy_intake.IntakeError as exc:
            return finish(str(exc), 2)
        if not _signing_key_safe(environ.get(policy.SIGNING_KEY_ENV)):
            return finish(policy.SIGNING_UNAVAILABLE, 2)
    if not renew_login(home or environ.get("HOME") or Path.home()):
        return finish(LOGIN_EXPIRED, 2)
    repo = Path(repo or ".").resolve()
    transport = transport or agy_provenance._Transport()
    try:
        if version is None:
            releases = agy_provenance.stable_releases(transport, limit=1)
        else:
            releases = [r for r in agy_provenance.stable_releases(transport) if r.get("tag_name") == version]
        if not releases:
            return finish("no_stable_release", 0)
        asset = agy_provenance.release_asset(releases[0], host)
    except agy_provenance.ProvenanceError as exc:
        return finish(str(exc), 2)
    _run(runner, ["git", "-C", str(repo), "fetch", "origin", "main"])
    workdir = Path(workdir or tempfile.mkdtemp(prefix="agy-watch-"))
    tree = workdir / "tree"
    # Detached, and never pushed: the watch creates no branch, locally or in origin.
    _run(runner, ["git", "-C", str(repo), "worktree", "add", "--force", "--detach", str(tree), base_ref])
    try:
        return _tick(tree, workdir, asset, releases[0], finish=finish, dry_run=dry_run, runner=runner, host=host,
                     transport=transport, python=python, intake=intake, intake_transport=intake_transport,
                     environ=environ, store=store, operator_version=version is not None)
    finally:
        if not dry_run:
            _run(runner, ["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)], check=False)
            shutil.rmtree(workdir, ignore_errors=True)


def _submit(records, *, finish, version, intake, intake_transport, environ, store, **extra):
    """Submit each signed record (kept in the outbox until its receipt is written). Any failure
    ends the tick ``agy_intake_submit_failed``; what was not submitted stays kept."""
    app_id, installation_id, key_path = intake
    try:
        # A fresh token: qualification can outlast the one that checked for a pending submission.
        token = agy_intake.installation_token(app_id, installation_id, key_path, transport=intake_transport)
    except agy_intake.IntakeError:
        return finish(agy_intake.SUBMIT_FAILED, 2, version=version)
    issues = []
    for record in records:
        try:
            issues.append(agy_intake.submit(record, token, transport=intake_transport, store=store, app_id=app_id))
        except agy_intake.IntakeError:
            return finish(agy_intake.SUBMIT_FAILED, 2, version=version)
        agy_intake.discard(record, environ=environ)
    return finish("submitted", 0, version=version, issues=issues, **extra)


def _tick(tree, workdir, asset, release, *, finish, dry_run, runner, host, transport, python, intake,
          intake_transport, environ, store, operator_version):
    base, qualified_under = tree_identity(tree, python=python, runner=runner)
    if not dry_run:
        # Signed records whose submission failed, of any version, are submitted first and never
        # re-qualified, whether or not the newest release has a pending submission: the tick
        # reports agy_intake_submit_failed until the outbox is empty. A kept record that main
        # already reflects (its version is a member at its qci) is discarded.
        on_main = {(member["release_version"], member["qci"]) for member in _catalog_members(tree)}
        leftovers = []
        for record in agy_intake.kept(base, environ=environ):
            if (record["release_version"], record["qci"]) in on_main:
                agy_intake.discard(record, environ=environ)
            else:
                leftovers.append(record)
        if leftovers:
            return _submit(leftovers, finish=finish, version=asset.version, intake=intake,
                           intake_transport=intake_transport, environ=environ, store=store, resubmitted=True)
    if asset.version in pinned_versions(tree):
        return finish("already_pinned", 0, version=asset.version)
    if not dry_run:
        app_id, installation_id, key_path = intake
        try:
            token = agy_intake.installation_token(app_id, installation_id, key_path, transport=intake_transport)
            if agy_intake.pending(asset.version, base, token, transport=intake_transport, store=store,
                                  app_id=app_id, ignore_wait=operator_version):
                return finish("up_to_date", 0, version=asset.version)
        except agy_intake.IntakeError as exc:
            return finish(str(exc), 2, version=asset.version)
    stale = [member for member in _catalog_members(tree) if member["qci"] != base]
    env = dict(os.environ)
    records = []

    def finish_record(record):
        if not dry_run:
            try:
                record = policy.sign_record(record, environ.get(policy.SIGNING_KEY_ENV))
            except ValueError:
                return None
        (tree / "plans/evidence" / f"agy-{record['release_version']}-linux-x64-qualification.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n")
        records.append(record)
        return record

    # The newest non-member, then each member whose qci is not the tree's: one image at a time.
    try:
        image = stream_image(transport, asset, workdir)
    except agy_provenance.ProvenanceError as exc:
        return finish(str(exc), 2, version=asset.version)
    try:
        try:
            attestation = agy_attestation.attestation_status(asset)
            second_channel = agy_attestation.second_channel_status(asset, image.sha256, host=host)
        except agy_provenance.ProvenanceError as exc:
            # A second-channel mismatch or an unavailable status: nothing is submitted.
            return finish(str(exc), 2, version=asset.version)
        member = {"version": asset.version, "image_sha256": image.sha256, "asset_sha256": asset.digest,
                  "qci": base, "published_at": release.get("published_at")}
        edit_catalog(tree, help_sha256="0" * 64, **member)
        help_path = workdir / f"agy-help-{asset.version}.txt"
        help_sha256 = _measure_help(tree, python, image, help_path, runner=runner, env=env)
        edit_catalog(tree, help_sha256=help_sha256, **member)
        series = run_series(tree, python, image, help_path, workdir, asset.version, runner=runner, env=env)
        if isinstance(series, str):
            return finish(series, 2, version=asset.version)
        record = summarize(tree, series, asset, image.sha256, help_sha256, qci=base,
                           qualified_under=qualified_under, attestation=attestation, second_channel=second_channel)
    finally:
        image.close()
    if finish_record(record) is None:
        return finish(policy.SIGNING_UNAVAILABLE, 2, version=asset.version)
    for existing in stale:
        try:
            member_asset, image, pinned_help = _pinned_member(tree, existing, host, transport, workdir)
        except agy_provenance.ProvenanceError as exc:
            return finish(str(exc), 2, version=asset.version)
        try:
            try:
                # A requalified member: a fresh attestation; its committed second channel stays.
                attestation = agy_attestation.attestation_status(member_asset)
            except agy_provenance.ProvenanceError as exc:
                return finish(str(exc), 2, version=asset.version)
            version_key = existing["release_version"]
            help_path = workdir / f"agy-help-{version_key}.txt"
            if _measure_help(tree, python, image, help_path, runner=runner, env=env) != pinned_help:
                raise ValueError(f"agy watch: member {version_key} help changed")
            edit_catalog(tree, version=version_key, image_sha256=existing["image_sha256"], help_sha256=pinned_help,
                         asset_sha256=existing["asset_sha256"], qci=base, published_at=existing["published_at"])
            series = run_series(tree, python, image, help_path, workdir, version_key, runner=runner, env=env)
            if isinstance(series, str):
                return finish(series, 2, version=asset.version)
            record = summarize(tree, series, member_asset, image.sha256, pinned_help, qci=base,
                               qualified_under=qualified_under, template_name=existing["record"],
                               attestation=attestation, second_channel=None)
        finally:
            image.close()
        if finish_record(record) is None:
            return finish(policy.SIGNING_UNAVAILABLE, 2, version=asset.version)
    _run(runner, [python, str(tree / "phase-loop-runtime/scripts/verify_qualified_agy_image.py"), "--contract"],
         cwd=tree)
    if dry_run:
        return finish("dry_run_verified", 0, version=asset.version, tree=str(tree), image_sha256=records[0]["image_sha256"])
    for record in records:
        agy_intake.keep(record, environ=environ)
    return _submit(records, finish=finish, version=asset.version, intake=intake, intake_transport=intake_transport,
                   environ=environ, store=store)
