"""AGYFRESH HOLD, lane SL-2 (HOLD-CORE): the seat admission boundary and the hold.

AGYFRESH §2.1-§2.7 as amended (plans/artifacts/agyfresh-contract.md): one admission
boundary, ``agy_qualification.admit_seat``; a hold on typed subject-side refusals only; a
bounded, ordered, descriptor-relative candidate search (``agy_hold``); the evidence keys; the
route-aware ``hold`` status. Goal IDs are the roadmap's EC-HOLD-n; each test is named for one.

"Both paths" is ``admit_seat(first_use=True)`` (preflight) and
``agy_integrity.admit_for_seat`` (spawn). Every case enters through one of them, or through
``gemini_heartbeat.admit``/``owned_profile`` (route 2) or ``cli_main`` (status), over files on
disk: a synthetic subject, a vendor store and a qualification store under ``tmp_path``. Help
measurement is a counting fake; provenance never reaches the network; no provider runs.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import random
import shutil
import sys
import threading
import tracemalloc
from hashlib import sha256
from types import SimpleNamespace

import pytest

from phase_loop_runtime import agy_hold
from phase_loop_runtime import agy_integrity
from phase_loop_runtime import agy_provenance as prov
from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_subject
from phase_loop_runtime.agy_canary_evidence import AgyCanaryEvidenceError

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(os, "memfd_create"),
    reason="Linux sealed-memfd seat admission",
)

MACHINE = "a" * 32
HOST = prov.HostPlatform("linux", "x64", "glibc")
HELP = b"synthetic help\n"
MEMBER_VERSION = "1.5.3"
#: AGYFRESH §1.2: one sealed image plus at most 2 MiB per seat admission (as
#: tests/test_agy_size_bounds.py): everything Python allocates stays within this.
OVERHEAD_CEILING = 2 * 1024 * 1024
SOURCE = Path(agy_hold.__file__)
_REAL_RUN_HELP = q._run_help


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _image(tag: str, size: int = 4096) -> bytes:
    head = f"#!/bin/sh\necho synthetic agy {tag}\n".encode()
    return head + b"#" * max(0, size - len(head))


def _token(home: Path, expiry: datetime) -> Path:
    path = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"auth_method": "oauth", "token": {
        "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
        "token_type": "Bearer", "expiry": expiry.isoformat()}}))
    return path


def _open_fds():
    return sorted(os.listdir("/proc/self/fd"))


def _no_network(*_args, **_kwargs):
    raise prov.ProvenanceError(prov.UNVERIFIED)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A non-member subject on PATH, an empty vendor store and qualification store, and a
    catalog of one member (1.5.3) whose bytes are NOT on disk until a test places them."""
    previous = os.umask(0o022)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(q, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(prov, "detect_platform", lambda **_: HOST)
    monkeypatch.setattr(prov, "find_provenance", _no_network)
    monkeypatch.setattr(gh, "_CANDIDATE", None)
    monkeypatch.setattr(q, "_LAST_KNOWN_GOOD_PROVIDER", None)
    monkeypatch.setattr(q, "_HELP_MEMO", {})
    monkeypatch.setattr(q, "_REQUALIFIED", set())
    monkeypatch.setattr(agy_hold, "_WALK_ROOT", tmp_path)
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    monkeypatch.setattr(agy_hold, "VENDOR_STORES", (vendor,))
    members: list[dict] = []
    qualified: dict[str, str] = {}
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", qualified)
    monkeypatch.setattr(gh, "catalog_members", lambda path=None: [dict(item) for item in members])
    bindir = tmp_path / "bin"
    bindir.mkdir()
    subject = _image("subject 9.9.9")
    agy = bindir / "agy"
    agy.write_bytes(subject)
    agy.chmod(0o755)
    home = tmp_path / "home"
    token = _token(home, datetime.now(timezone.utc) + timedelta(hours=1))
    helps: list[str] = []
    help_for: dict[str, bytes] = {}

    def fake_help(image, env):
        helps.append(image.sha256)
        return help_for.get(image.sha256, HELP)

    monkeypatch.setattr(q, "_run_help", fake_help)
    w = SimpleNamespace(tmp=tmp_path, vendor=vendor, agy=agy, subject=subject, home=home,
                        token=token, helps=helps, help_for=help_for, members=members,
                        qualified=qualified, env={"PATH": str(bindir), "HOME": str(home)})

    def add_member(data, version=MEMBER_VERSION):
        members.append({"release_version": version, "image_sha256": _sha(data),
                        "help_sha256": _sha(HELP)})
        qualified[_sha(data)] = _sha(HELP)
        return _sha(data)

    def vendor_dir(version, data, suffix=None, *, root=None):
        directory = (root or vendor) / f"{version}-{suffix or _sha(data)[:16]}"
        directory.mkdir(mode=0o755)
        target = directory / "agy"
        target.write_bytes(data)
        target.chmod(0o755)
        return target

    def store():
        value = q.Store()
        value.create()
        return value

    def seed_local(data, version, *, help_bytes=HELP, qualified_entry=True):
        value = store()
        key = q.agy_profile_digest()
        asset = SimpleNamespace(name=HOST.asset, version=version, digest="sha256:" + "0" * 64)
        value.put_provenance(SimpleNamespace(image_sha256=_sha(data), platform=HOST.name, asset=asset), key)
        if qualified_entry:
            value.put_qualified(_sha(data), _sha(help_bytes), HOST, key, version)
        return value

    def seed_failed(data):
        value = store()
        value.put_failed(_sha(data), _sha(HELP), HOST, q.agy_profile_digest(), "completion", "synthetic")
        return value

    def cache(data, *, name=None):
        value = store()
        held = value.host_dir / agy_hold.HELD_DIRNAME
        held.mkdir(mode=0o700, exist_ok=True)
        target = held / (name or _sha(data))
        target.write_bytes(data)
        target.chmod(0o600)
        return target

    def config(text):
        path = tmp_path / "config" / "agent-harness" / "advisor-boards.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    w.add_member, w.vendor_dir, w.store, w.seed_local = add_member, vendor_dir, store, seed_local
    w.seed_failed, w.cache, w.config = seed_failed, cache, config
    try:
        yield w
    finally:
        os.umask(previous)


@pytest.fixture
def member(world):
    """A held release member in the vendor store."""
    data = _image("member 1.5.3")
    world.add_member(data)
    world.vendor_dir(MEMBER_VERSION, data)
    return SimpleNamespace(data=data, digest=_sha(data))


def _spy(monkeypatch, world):
    """Record every candidate, anchor and directory the hold opens, and every image read
    other than the subject's own (``reads``: digests, in order)."""
    calls = SimpleNamespace(candidates=[], anchors=[], dirs=[], reads=[])
    subject = os.path.realpath(world.agy)
    real_candidate, real_anchor, real_dir = agy_hold._open_candidate, agy_hold.open_anchor, agy_hold._open_dir_at
    real_from_fd = gh.VerifiedImage.from_fd.__func__

    def candidate(anchor, item):
        calls.candidates.append(item)
        return real_candidate(anchor, item)

    def anchor(path):
        calls.anchors.append(Path(path))
        return real_anchor(path)

    def directory(name, parent):
        calls.dirs.append(name)
        return real_dir(name, parent)

    def from_fd(cls, fd, *, path=None):
        source = os.readlink(f"/proc/self/fd/{fd}")
        image = real_from_fd(cls, fd, path=path)
        if source != subject:
            calls.reads.append(image.sha256)
        return image

    monkeypatch.setattr(agy_hold, "_open_candidate", candidate)
    monkeypatch.setattr(agy_hold, "open_anchor", anchor)
    monkeypatch.setattr(agy_hold, "_open_dir_at", directory)
    monkeypatch.setattr(gh.VerifiedImage, "from_fd", classmethod(from_fd))
    return calls


def _preflight(world, path=None, **kwargs):
    return q.admit_seat(world.env, world.agy if path is None else path, first_use=True, **kwargs)


def _spawn(world, path=None, evidence=None):
    return agy_integrity.admit_for_seat(str(world.agy if path is None else path), world.env, evidence=evidence)


# ------------------------------------------------------------------ EC-HOLD-1 cases

def _over_bound(world, monkeypatch):
    world.subject = _image("subject 9.9.9", 8192)
    world.agy.write_bytes(world.subject)
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", 4096)  # the member (4096 bytes) is within it


def _unreadable(world, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    world.agy.chmod(0o000)


def _removed(world, monkeypatch):
    world.agy.unlink()


def _directory(world, monkeypatch):
    world.agy.unlink()
    world.agy.mkdir()


def _no_record(world, monkeypatch):
    pass


def _provenance_only(world, monkeypatch):
    world.seed_local(world.subject, "9.9.9", qualified_entry=False)


def _failed(world, monkeypatch):
    world.seed_failed(world.subject)


def _opted_out(world, monkeypatch):
    world.config("[agy]\nself_qualification = false\n")


def _first_use_failed(world, monkeypatch):
    world.seed_local(world.subject, "9.9.9", qualified_entry=False)
    world.qualify = lambda *a, **k: {"status": "failed", "operation": "completion", "reason": "synthetic"}


def _first_use_transient(world, monkeypatch):
    world.seed_local(world.subject, "9.9.9", qualified_entry=False)
    world.qualify = lambda *a, **k: {"status": "transient", "operation": "completion"}


def _provenance_unverifiable(world, monkeypatch):
    pass  # find_provenance is the world's no-network fake: UNVERIFIED


def _provenance_unavailable(world, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise prov.ProvenanceError(prov.UNAVAILABLE)

    monkeypatch.setattr(prov, "find_provenance", unavailable)


# name: (setup, preflight reason, spawn reason, subject digest is read)
CASES = {
    "over_bound": (_over_bound, "subject_over_bound", "subject_over_bound", False),
    "unreadable": (_unreadable, "subject_unreadable", "subject_unreadable", False),
    "removed": (_removed, "subject_unreadable", "subject_unreadable", False),
    "directory": (_directory, "subject_not_regular", "subject_not_regular", False),
    "no_record": (_no_record, "provenance_unverified", "subject_unqualified", True),
    "provenance_only": (_provenance_only, "first_use_unavailable", "subject_unqualified", True),
    "failed_entry": (_failed, "subject_failed", "subject_failed", True),
    "self_qualification_off": (_opted_out, "self_qualification_disabled", "self_qualification_disabled", True),
    "first_use_failed": (_first_use_failed, "first_use_failed", "subject_unqualified", True),
    "first_use_transient": (_first_use_transient, "first_use_unavailable", "subject_unqualified", True),
    "provenance_unverifiable": (_provenance_unverifiable, "provenance_unverified", "subject_unqualified", True),
    "provenance_unavailable": (_provenance_unavailable, "provenance_unavailable", "subject_unqualified", True),
}


def _setup(world, monkeypatch, name):
    world.qualify = lambda *a, **k: {"status": "transient", "operation": "completion"}
    CASES[name][0](world, monkeypatch)


def _outcome(fn):
    """``(exception type, str)`` of what ``fn`` raises, or ``None`` if it admits."""
    try:
        result = fn()
    except BaseException as exc:  # noqa: BLE001 - the refusal is the observation
        return type(exc), str(exc)
    (result.close if hasattr(result, "close") else (lambda: None))()
    return None


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_1_a_subject_side_refusal_admits_the_held_member(world, member, monkeypatch, name, path):
    _setup(world, monkeypatch, name)
    _, preflight_reason, spawn_reason, digest_read = CASES[name]
    subject_sha256 = _sha(world.subject) if digest_read else None
    if path == "preflight":
        admission = _preflight(world, qualify=world.qualify)
        try:
            assert (admission.source, admission.path) == ("lkg", None)
            assert admission.admission_class == "release_qualified"
            assert admission.image.sha256 == member.digest
            assert os.pread(admission.image.fd, 1 << 20, 0) == member.data
            assert admission.evidence() == {
                "provider_admission_class": "release_qualified",
                "provider_image_sha256": member.digest,
                "provider_admission_source": "lkg",
                "provider_hold_reason": preflight_reason,
                "provider_subject_image_sha256": subject_sha256,
            }
        finally:
            admission.close()
    else:
        evidence = {}
        image = _spawn(world, evidence=evidence)
        try:
            assert image.sha256 == member.digest
            assert os.pread(image.fd, 1 << 20, 0) == member.data
        finally:
            image.close()
        assert evidence == {
            "provider_admission_class": "release_qualified",
            "provider_image_sha256": member.digest,
            "provider_admission_source": "lkg",
            "provider_hold_reason": spawn_reason,
            "provider_subject_image_sha256": subject_sha256,
        }
        assert spawn_reason in q.HOLD_REASONS


# What today's code raises for each case, per path, with no candidate (and no hold).
_CAPABILITY = (ValueError, gh._CAPABILITY)
_UNQUALIFIED = (agy_integrity.AgyImageUnqualified, "agy_image_unqualified")
PREFLIGHT_REFUSAL = {
    "over_bound": _CAPABILITY, "unreadable": _CAPABILITY, "removed": _CAPABILITY,
    "directory": _CAPABILITY,
    "no_record": (ValueError, prov.UNVERIFIED),
    "provenance_only": (ValueError, q.SELF_QUALIFICATION_UNAVAILABLE),
    "failed_entry": (ValueError, q.SELF_QUALIFICATION_FAILED),
    "self_qualification_off": _CAPABILITY,
    "first_use_failed": (ValueError, q.SELF_QUALIFICATION_FAILED),
    "first_use_transient": (ValueError, q.SELF_QUALIFICATION_UNAVAILABLE),
    "provenance_unverifiable": (ValueError, prov.UNVERIFIED),
    "provenance_unavailable": (ValueError, prov.UNAVAILABLE),
}


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_1_with_no_candidate_the_original_refusal_returns(world, monkeypatch, name, path):
    _setup(world, monkeypatch, name)
    calls = _spy(monkeypatch, world)
    if path == "preflight":
        refusal = _outcome(lambda: _preflight(world, qualify=world.qualify))
        expected = PREFLIGHT_REFUSAL[name]
    else:
        refusal = _outcome(lambda: _spawn(world))
        expected = _UNQUALIFIED
    assert refusal is not None and (refusal[0], refusal[1]) == expected
    # The hold ran (the vendor store was opened) and found nothing to read.
    assert world.vendor in calls.anchors and calls.reads == []


@pytest.mark.parametrize("route", ["admit", "owned_profile"])
def test_ec_hold_1_route_2_holds_once_and_records_the_held_digest(world, member, monkeypatch, route):
    """The non-jailed heartbeat route: PATH ``agy``, no admission passed in."""
    calls = _spy(monkeypatch, world)
    if route == "admit":
        admission = gh.admit(world.env)
        try:
            assert (admission.source, admission.hold_reason, admission.image.sha256) == (
                "lkg", "subject_unqualified", member.digest)
            assert gh.require_capability(world.env) == Path(gh.PRIVATE_HOME + "/agy")
        finally:
            admission.close()
    else:
        with gh.owned_profile(world.env, settings_bytes=b"{}", credential_path=world.token) as profile:
            assert os.pread(profile.image_fd, 1 << 20, 0) == member.data
            evidence = profile.evidence
        assert {key: evidence[key] for key in (
            "provider_image_sha256", "provider_admission_class", "provider_admission_source",
            "provider_hold_reason", "provider_subject_image_sha256")} == {
            "provider_image_sha256": member.digest, "provider_admission_class": "release_qualified",
            "provider_admission_source": "lkg", "provider_hold_reason": "subject_unqualified",
            "provider_subject_image_sha256": _sha(world.subject)}
    assert calls.reads.count(member.digest) == (2 if route == "admit" else 1)


def _bound_provider(profile):
    args = profile.mount_args
    index = next(i for i, arg in enumerate(args)
                 if arg == "--ro-bind-data" and args[i + 2] == "/run/phase-loop-seat/provider")
    return int(args[index + 1])


def test_ec_hold_1_a_seat_profile_launch_executes_and_records_the_held_image(world, member):
    """Route 1: the owned seat binds the held memfd; its evidence carries the three keys."""
    cwd = world.tmp / "out"
    cwd.mkdir()
    with pi.seat_profile(harness="gemini", executable=str(world.agy), env=world.env, cwd=cwd) as (
            destination, profile):
        assert destination == "/run/phase-loop-seat/provider"
        assert os.pread(_bound_provider(profile), 1 << 20, 0) == member.data
        assert profile.evidence == {
            "provider_admission_class": "release_qualified", "provider_image_sha256": member.digest,
            "provider_admission_source": "lkg", "provider_hold_reason": "subject_unqualified",
            "provider_subject_image_sha256": _sha(world.subject)}


def test_ec_hold_1_a_subject_admission_records_source_subject(world, monkeypatch):
    world.add_member(world.subject)
    evidence = {}
    _spawn(world, evidence=evidence).close()
    assert evidence == {"provider_admission_class": "release_qualified",
                        "provider_image_sha256": _sha(world.subject),
                        "provider_admission_source": "subject"}


# ------------------------------------------------------------------ EC-HOLD-2 propagation

class _Typed(Exception):
    pass


def _help_raising(world, monkeypatch, exc):
    world.seed_local(world.subject, "9.9.9")

    def refuse(image, env):
        raise exc

    monkeypatch.setattr(q, "_run_help", refuse)


def _typed_outcomes():
    from phase_loop_runtime.panel_invoker import ProviderProcessGroupQuiescenceError
    from phase_loop_runtime.sandbox_egress import EgressUnavailable
    from phase_loop_runtime.seat_jail import SeatSandboxRefused, refused

    return {
        "egress": lambda: EgressUnavailable("seat_filtered_egress_unavailable"),
        "gemini_quiescence": lambda: gh.GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified"),
        "group_quiescence": lambda: ProviderProcessGroupQuiescenceError("synthetic group quiescence"),
        "sandbox": lambda: SeatSandboxRefused(refused("identity")),
        "cancelled": lambda: ValueError(q.CANCELLED),
    }


TYPED = sorted(_typed_outcomes())


def _never_eligible(world, monkeypatch, name):
    if name == "local_capabilities":
        def broken():
            raise ValueError(gh._CAPABILITY)

        monkeypatch.setattr(gh, "_local_capabilities", broken)
    elif name == "seal_abi_unavailable":
        # H2: the seal ABI is unavailable as ``_new_image_memfd`` creates the image memfd.
        monkeypatch.setattr(gh, "_local_capabilities", lambda: None)

        def no_seals():
            raise AgyCanaryEvidenceError("tracked snapshot requires Linux sealed memfds")

        monkeypatch.setattr(gh, "_linux_memfd_seal_abi", no_seals)
    elif name == "seal_failure":
        def unsealable(_fd):
            raise AgyCanaryEvidenceError("synthetic memfd seal failure")

        monkeypatch.setattr(gh, "_seal_image_memfd", unsealable)
    elif name == "unsupported_platform":
        def unsupported(**_):
            raise prov.ProvenanceError(prov.UNSUPPORTED)

        monkeypatch.setattr(prov, "detect_platform", unsupported)
    elif name == "cancelled_in_first_use":
        world.seed_local(world.subject, "9.9.9", qualified_entry=False)
        world.qualify = lambda *a, **k: {"status": "cancelled"}
    else:
        _help_raising(world, monkeypatch, _typed_outcomes()[name]())


NEVER = ["local_capabilities", "seal_abi_unavailable", "seal_failure", "unsupported_platform",
         "cancelled_in_first_use", *TYPED]


# What each never-eligible condition raises, per path: today's refusal, unchanged.
NEVER_REFUSAL = {
    ("preflight", "local_capabilities"): _CAPABILITY,
    # H2: the private classification is a ValueError with today's message.
    ("preflight", "seal_abi_unavailable"): (q._SubjectImageUnsealed, gh._CAPABILITY),
    ("preflight", "seal_failure"): (q._SubjectImageUnsealed, gh._CAPABILITY),
    ("preflight", "unsupported_platform"): (ValueError, prov.UNSUPPORTED),
    ("preflight", "cancelled_in_first_use"): (ValueError, q.CANCELLED),
    ("preflight", "cancelled"): (ValueError, q.CANCELLED),
    # The typed process-group quiescence outcome keeps its type in first use too (§2.2).
}


@pytest.mark.parametrize("name", NEVER)
@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_2_a_never_eligible_condition_propagates_with_a_member_present(
        world, member, monkeypatch, name, path):
    if path == "spawn" and name == "cancelled_in_first_use":
        pytest.skip("spawn never runs first use")
    world.qualify = lambda *a, **k: {"status": "passed"}
    _never_eligible(world, monkeypatch, name)
    calls = _spy(monkeypatch, world)
    before = _open_fds()
    if path == "preflight":
        refusal = _outcome(lambda: _preflight(world, qualify=world.qualify))
    else:
        refusal = _outcome(lambda: _spawn(world))
    assert refusal is not None
    assert calls.candidates == [] and calls.anchors == []
    assert _open_fds() == before
    typed = {"egress", "gemini_quiescence", "group_quiescence", "sandbox"}
    if (path, name) in NEVER_REFUSAL:
        assert refusal == NEVER_REFUSAL[(path, name)]
    elif name in typed:
        error = _typed_outcomes()[name]()
        assert refusal == (type(error), str(error))  # keeps its type
    else:
        assert refusal == _UNQUALIFIED  # the seal cases too: the typed refusal, nothing held


@pytest.mark.parametrize("name", ["seal_abi_unavailable", "seal_failure"])
def test_ec_hold_2_h2_the_seal_error_is_classified_before_the_mapping(world, member, monkeypatch, name):
    """H2: through ``check`` both are ``agy_image_unqualified`` (the same code an unqualified
    subject raises), their cause is still the seal error, and no candidate was opened."""
    _never_eligible(world, monkeypatch, name)
    calls = _spy(monkeypatch, world)
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="^agy_image_unqualified$") as caught:
        _spawn(world)
    assert isinstance(caught.value.__cause__, AgyCanaryEvidenceError)
    with pytest.raises(ValueError, match=f"^{gh._CAPABILITY}$") as raw:
        q.admit_seat(world.env, world.agy)
    assert isinstance(raw.value, AgyCanaryEvidenceError)
    assert calls.candidates == [] and calls.anchors == []


def test_ec_hold_2_no_provider_on_path_propagates(world, member, monkeypatch):
    calls = _spy(monkeypatch, world)
    env = {**world.env, "PATH": str(world.tmp / "empty")}
    with pytest.raises(ValueError, match=f"^{gh._CAPABILITY}$"):
        q.admit_seat(env, None, first_use=True)
    with pytest.raises(ValueError, match=f"^{gh._CAPABILITY}$"):
        gh.admit(env)
    assert calls.candidates == [] and calls.anchors == []


def test_ec_hold_2_seat_provider_unavailable_from_the_cli(world, member, monkeypatch, capsys):
    calls = _spy(monkeypatch, world)

    def absent(leg, env):
        raise FileNotFoundError("seat_provider_unavailable")

    monkeypatch.setattr(seat_subject, "resolve_seat_subject", absent)
    assert q.cli_main(argparse.Namespace(action="run")) == 1
    assert "seat_provider_unavailable" in capsys.readouterr().err
    assert calls.candidates == [] and calls.anchors == []


@pytest.mark.parametrize("name", TYPED)
def test_ec_hold_2_a_candidates_typed_help_outcome_propagates_and_closes_it(world, monkeypatch, name):
    local = _image("local 1.6.0")
    world.seed_local(local, "1.6.0")
    world.vendor_dir("1.6.0", local)
    error = _typed_outcomes()[name]()

    def refuse(image, env):
        raise error

    monkeypatch.setattr(q, "_run_help", refuse)
    calls = _spy(monkeypatch, world)
    before = _open_fds()
    with pytest.raises(type(error)) as caught:
        q.admit_seat(world.env, world.agy)
    assert caught.value is error
    assert calls.reads == [_sha(local)]
    assert _open_fds() == before


# -------------------------------------------------------------------- EC-HOLD-3 predicates

def _local_candidate(world, version="1.6.0", *, cache=False, **seed):
    data = _image(f"local {version}")
    world.seed_local(data, version, **seed)
    if cache:
        world.cache(data)
    else:
        world.vendor_dir(version, data)
    return data


@pytest.mark.parametrize("where", ["vendor", "cache"])
@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_3_a_locally_qualified_candidate_is_admitted(world, monkeypatch, where, path):
    data = _local_candidate(world, cache=where == "cache")
    if path == "preflight":
        admission = _preflight(world)
        assert (admission.source, admission.admission_class, admission.image.sha256) == (
            "lkg", "locally_qualified", _sha(data))
        assert admission.help_sha256 == _sha(HELP)
        admission.close()
    else:
        evidence = {}
        _spawn(world, evidence=evidence).close()
        assert evidence["provider_admission_class"] == "locally_qualified"
        assert evidence["provider_image_sha256"] == _sha(data)
    assert world.helps[-1] == _sha(data)


def _foreign_key(world):
    store = q.Store()
    (store.host_dir / "key").unlink()
    store._write(store.host_dir / "key", b"\x01" * 32, exclusive=True)


@pytest.mark.parametrize("reason", ["failed_entry", "different_help", "foreign_key", "denied"])
def test_ec_hold_3_a_candidate_failing_the_predicate_is_refused(world, monkeypatch, reason):
    data = _local_candidate(world)
    if reason == "failed_entry":
        world.seed_failed(data)
    elif reason == "different_help":
        world.help_for[_sha(data)] = b"other help\n"
    elif reason == "foreign_key":
        _foreign_key(world)
    else:
        world.config(f'[agy]\nhold_deny = ["{_sha(data)}"]\n')
    with pytest.raises(agy_integrity.AgyImageUnqualified):
        _spawn(world)
    with pytest.raises(ValueError, match=f"^{gh._CAPABILITY}$"):
        q.admit_seat(world.env, world.agy)


def test_ec_hold_3_help_never_runs_for_a_candidate_without_provenance(world, monkeypatch):
    data = _image("local 1.6.0")
    store = world.store()
    # A hint only (an unauthenticated qualified-*.json naming 1.6.0), no provenance entry.
    (store.host_dir / f"qualified-{'b' * 64}.json").write_text(json.dumps({"payload": {"release_version": "1.6.0"}}))
    world.vendor_dir("1.6.0", data)
    calls = _spy(monkeypatch, world)
    with pytest.raises(agy_integrity.AgyImageUnqualified):
        _spawn(world)
    assert calls.reads == [_sha(data)]  # read and hashed ...
    assert world.helps == []  # ... never executed, not even for --help


def test_ec_hold_3_the_subjects_own_bytes_are_never_the_hold(world, monkeypatch):
    world.seed_local(world.subject, "1.6.0")  # its qualified entry is the 1.6.0 hint
    world.vendor_dir("1.6.0", world.subject)
    world.cache(world.subject)
    world.config("[agy]\nself_qualification = false\n")
    calls = _spy(monkeypatch, world)
    with pytest.raises(agy_integrity.AgyImageUnqualified):
        _spawn(world)
    assert world.helps == []
    assert [c.origin for c in calls.candidates] == ["vendor"]  # the cache name is excluded unread


def test_ec_hold_3_self_qualification_off_admits_a_member_but_not_a_local_image(world, monkeypatch):
    world.config("[agy]\nself_qualification = false\n")
    _local_candidate(world, "1.6.0")
    with pytest.raises(agy_integrity.AgyImageUnqualified):
        _spawn(world)
    data = _image("member 1.5.3")
    world.add_member(data)
    world.vendor_dir(MEMBER_VERSION, data)
    evidence = {}
    _spawn(world, evidence=evidence).close()
    assert (evidence["provider_image_sha256"], evidence["provider_hold_reason"]) == (
        _sha(data), "self_qualification_disabled")
    assert world.helps == []


def test_ec_hold_3_an_unsafe_store_admits_a_member_only(world, monkeypatch):
    _local_candidate(world, "1.6.0", cache=True)
    store = q.Store()
    store.host_dir.chmod(0o755)
    assert store.status() == "unsafe"
    calls = _spy(monkeypatch, world)
    with pytest.raises(agy_integrity.AgyImageUnqualified):
        _spawn(world)
    assert calls.candidates == []  # no cache, no hints: nothing to read
    data = _image("member 1.5.3")
    world.add_member(data)
    world.vendor_dir(MEMBER_VERSION, data)
    evidence = {}
    _spawn(world, evidence=evidence).close()
    assert (evidence["provider_image_sha256"], evidence["provider_hold_reason"]) == (_sha(data), "store_unsafe")


# --------------------------------------------------------------------- EC-HOLD-4 first use

def test_ec_hold_4_first_use_runs_for_the_subject_before_any_hold(world, member, monkeypatch):
    world.seed_local(world.subject, "9.9.9", qualified_entry=False)
    called = []

    def passing(image, help_bytes, **_kwargs):
        called.append(image.sha256)
        return {"status": "passed"}

    calls = _spy(monkeypatch, world)
    admission = _preflight(world, qualify=passing)
    try:
        assert (admission.source, admission.admission_class, admission.image.sha256) == (
            "subject", "locally_qualified", _sha(world.subject))
    finally:
        admission.close()
    assert called == [_sha(world.subject)]
    assert calls.candidates == [] and calls.anchors == []


# ------------------------------------------------------------------ EC-HOLD-5 compatibility

def test_ec_hold_5_admission_verdict_without_execution_never_admits_because_of_a_hold(world, member):
    assert q.admission_verdict(world.env, world.agy, execute=False).status != "admits"
    assert q.admission_verdict(world.env, world.agy, execute=True).status == "admits"


@pytest.mark.parametrize("config", ["[agy]\nhold = false\n", '[agy]\nhold = "no"\n',
                                    '[agy]\nhold_deny = "everything"\n', "[agy\n"])
@pytest.mark.parametrize("name", sorted(CASES))
def test_ec_hold_5_hold_off_or_a_malformed_config_refuses_as_today(world, member, monkeypatch, config, name):
    _setup(world, monkeypatch, name)
    if name == "self_qualification_off":
        config = config.replace("[agy]\n", "[agy]\nself_qualification = false\n", 1)
    world.config(config)
    calls = _spy(monkeypatch, world)
    assert _outcome(lambda: _spawn(world)) == _UNQUALIFIED
    preflight = _outcome(lambda: _preflight(world, qualify=world.qualify))
    if config == "[agy\n":
        # An unreadable file fails self-qualification closed too: today's opt-out refusal.
        assert preflight == _CAPABILITY
    else:
        # hold = false, or a malformed HOLD value, disables the hold only (AGYFRESH §2.7).
        assert preflight == PREFLIGHT_REFUSAL[name]
    assert calls.candidates == [] and calls.anchors == []


# ------------------------------------------------------------- EC-HOLD-7 order and budgets

def _junk(tag, size=4096):
    return _image(f"junk {tag}", size)


def test_ec_hold_7_a_newer_vendor_member_beats_an_older_cache_member(world, monkeypatch):
    older, newer = _image("member 1.5.3"), _image("member 1.5.4")
    world.add_member(older, "1.5.3")
    world.add_member(newer, "1.5.4")
    cached = world.cache(older)
    future = 4_000_000_000_000_000_000
    os.utime(cached, ns=(future, future))
    world.vendor_dir("1.5.4", newer)
    admission = q.admit_seat(world.env, world.agy)
    try:
        assert admission.image.sha256 == _sha(newer)
    finally:
        admission.close()


def test_ec_hold_7_an_earlier_admitted_image_never_beats_a_newer_eligible_one(world, monkeypatch):
    """B1, no memo: a newer eligible candidate that appears between two holds wins the second."""
    older, newer = _image("member 1.5.3"), _image("member 1.5.4")
    world.add_member(older, "1.5.3")
    world.add_member(newer, "1.5.4")
    world.vendor_dir("1.5.3", older)
    first = q.admit_seat(world.env, world.agy)
    assert first.image.sha256 == _sha(older)
    first.close()
    world.vendor_dir("1.5.4", newer)
    second = q.admit_seat(world.env, world.agy)
    try:
        assert second.image.sha256 == _sha(newer)
    finally:
        second.close()


def test_ec_hold_7_a_candidate_rejected_earlier_and_since_eligible_is_admitted(world, monkeypatch):
    data = _local_candidate(world, "1.6.0")
    store = world.seed_failed(data)
    with pytest.raises(ValueError):
        q.admit_seat(world.env, world.agy)
    store.remove(("failed",))
    admission = q.admit_seat(world.env, world.agy)
    try:
        assert admission.image.sha256 == _sha(data)
    finally:
        admission.close()


def _hint(world, version, index):
    store = world.store()
    name = f"qualified-{sha256(f'{version}-{index}'.encode()).hexdigest()}.json"
    (store.host_dir / name).write_text(json.dumps({"schema": "x", "payload": {"release_version": version}}))


def test_ec_hold_7_sixty_four_forged_hints_cannot_displace_the_catalog_member(world, member, monkeypatch):
    for index in range(64):
        version = f"9.9.{index}"
        _hint(world, version, index)
        world.vendor_dir(version, _junk(version))
    calls = _spy(monkeypatch, world)
    admission = q.admit_seat(world.env, world.agy)
    try:
        assert admission.image.sha256 == member.digest
    finally:
        admission.close()
    assert len(calls.reads) == agy_hold.HINT_READS + 1  # two hinted reads, then the member


def test_ec_hold_7_two_directories_per_version_in_name_order_and_a_third_is_ignored(world, monkeypatch):
    data = _image("member 1.5.3")
    world.add_member(data)
    world.vendor_dir(MEMBER_VERSION, _junk("a"), suffix="0" * 15 + "a")
    world.vendor_dir(MEMBER_VERSION, _junk("b"), suffix="0" * 15 + "b")
    world.vendor_dir(MEMBER_VERSION, data, suffix="0" * 15 + "c")
    calls = _spy(monkeypatch, world)
    with pytest.raises(ValueError):
        q.admit_seat(world.env, world.agy)
    assert [c.name for c in calls.candidates] == [f"1.5.3-{'0' * 15}a", f"1.5.3-{'0' * 15}b"]


@pytest.mark.parametrize("extra, admitted", [(3, True), (4, False)])
def test_ec_hold_7_a_directory_with_too_many_names_is_skipped(world, member, monkeypatch, extra, admitted):
    monkeypatch.setattr(agy_hold, "MAX_DIR_ENTRIES", 4)
    for index in range(extra):
        (world.vendor / f"other-{index}").mkdir()
    outcome = _outcome(lambda: q.admit_seat(world.env, world.agy))
    assert (outcome is None) is admitted


def _ordering_world(world):
    members = []
    for version in ("1.5.2", "1.5.3", "1.5.4"):
        data = _image(f"member {version}")
        world.add_member(data, version)
        members.append(data)
    world.vendor_dir("1.5.4", _junk("1.5.4-a"), suffix="0" * 15 + "a")
    world.cache(members[1])
    world.vendor_dir("1.5.3", members[1])
    world.vendor_dir("1.5.4", _junk("1.5.4-b"), suffix="0" * 15 + "b")
    return members


@pytest.mark.parametrize("order", ["natural", "reversed", "shuffled"])
def test_ec_hold_7_the_walk_is_the_same_whatever_scandir_order(world, monkeypatch, order):
    members = _ordering_world(world)
    real_scandir = os.scandir

    class Reordered:
        def __init__(self, target):
            with real_scandir(target) as entries:
                self.entries = list(entries)
            if order == "reversed":
                self.entries.reverse()
            elif order == "shuffled":
                random.Random(7).shuffle(self.entries)

        def __enter__(self):
            return iter(self.entries)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(os, "scandir", Reordered)
    calls = _spy(monkeypatch, world)
    admission = q.admit_seat(world.env, world.agy)
    try:
        assert admission.image.sha256 == _sha(members[1])
    finally:
        admission.close()
    # Version descending, authenticated first, cache before vendor, name ascending.
    assert [(c.origin, c.name) for c in calls.candidates] == [
        ("vendor", f"1.5.4-{'0' * 15}a"), ("vendor", f"1.5.4-{'0' * 15}b"), ("cache", _sha(members[1]))]


def test_ec_hold_7_image_reads_never_exceed_the_two_budgets(world, monkeypatch):
    for index, version in enumerate(("2.0.0", "2.0.1", "2.0.2", "2.0.3")):
        world.add_member(_image(f"member {version}"), version)  # bytes never on disk
        world.vendor_dir(version, _junk(version))
        _hint(world, f"3.0.{index}", index)
        world.vendor_dir(f"3.0.{index}", _junk(f"3.0.{index}"))
    calls = _spy(monkeypatch, world)
    with pytest.raises(ValueError):
        q.admit_seat(world.env, world.agy)
    assert len(calls.reads) == agy_hold.AUTH_READS + agy_hold.HINT_READS


def test_ec_hold_7_after_three_failing_authenticated_candidates_a_fourth_is_not_read(world, member, monkeypatch):
    for version in ("1.5.4", "1.5.5", "1.5.6"):
        world.add_member(_image(f"member {version}"), version)
        world.vendor_dir(version, _junk(version))
    calls = _spy(monkeypatch, world)
    with pytest.raises(ValueError):
        q.admit_seat(world.env, world.agy)
    assert member.digest not in calls.reads and len(calls.reads) == agy_hold.AUTH_READS


# -------------------------------------------------------------------- EC-HOLD-8 resources

def _track_images(monkeypatch):
    """Instrument VerifiedImage creation (``from_fd``) and ``close``."""
    live, events = set(), []
    peak = [0]
    real_from_fd = gh.VerifiedImage.from_fd.__func__
    real_close = gh.VerifiedImage.close

    def from_fd(cls, fd, *, path=None):
        image = real_from_fd(cls, fd, path=path)
        live.add(id(image))
        events.append(("open", image.sha256))
        peak[0] = max(peak[0], len(live))
        return image

    def close(self):
        if self.fd is not None and id(self) in live:
            live.discard(id(self))
            events.append(("close", self.sha256))
        real_close(self)

    monkeypatch.setattr(gh.VerifiedImage, "from_fd", classmethod(from_fd))
    monkeypatch.setattr(gh.VerifiedImage, "close", close)
    return SimpleNamespace(live=live, events=events, peak=peak)


@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_8_never_two_images_and_the_subject_closes_first(world, member, monkeypatch, path):
    world.add_member(_image("member 1.5.4"), "1.5.4")
    world.vendor_dir("1.5.4", _junk("1.5.4"))
    tracked = _track_images(monkeypatch)
    if path == "preflight":
        _preflight(world, qualify=lambda *a, **k: {"status": "transient"}).close()
    else:
        _spawn(world).close()
    assert tracked.peak[0] == 1
    subject = _sha(world.subject)
    assert tracked.events[:2] == [("open", subject), ("close", subject)]
    assert tracked.events[2:] == [("open", _sha(_junk("1.5.4"))), ("close", _sha(_junk("1.5.4"))),
                                  ("open", member.digest), ("close", member.digest)]
    assert not tracked.live


def _admission_constructor_fails(world, monkeypatch):
    real = gh.Admission.__init__

    def broken(self, *args, **kwargs):
        if kwargs.get("source") == "lkg":
            raise RuntimeError("synthetic admission failure")
        real(self, *args, **kwargs)

    monkeypatch.setattr(gh.Admission, "__init__", broken)


def _candidate_raises_mid_read(world, monkeypatch):
    real_readv = os.readv
    target = world.vendor_dir("1.5.4", _junk("1.5.4", 3 << 20))
    world.add_member(_image("member 1.5.4"), "1.5.4")

    def readv(fd, buffers):
        if os.readlink(f"/proc/self/fd/{fd}") == os.path.realpath(target):
            raise OSError(5, "synthetic read failure")
        return real_readv(fd, buffers)

    monkeypatch.setattr(os, "readv", readv)


def _rejected_candidate(world):
    world.vendor_dir("1.6.0", _junk("1.6.0"))
    _hint(world, "1.6.0", 0)


REFUSAL_BRANCHES = {
    "local_capabilities": lambda w, m: _never_eligible(w, m, "local_capabilities"),
    "seal_abi_unavailable": lambda w, m: _never_eligible(w, m, "seal_abi_unavailable"),
    "seal_failure": lambda w, m: _never_eligible(w, m, "seal_failure"),
    "no_candidate": lambda w, m: None,
    "rejected_candidate": lambda w, m: _rejected_candidate(w),
    "candidate_mid_read": _candidate_raises_mid_read,
    "cancellation": lambda w, m: _never_eligible(w, m, "cancelled"),
    "admission_constructor": None,
}


@pytest.mark.parametrize("name", sorted(REFUSAL_BRANCHES))
@pytest.mark.parametrize("reason", ["unreadable", "no_record", "failed_entry"])
def test_ec_hold_8_every_refusal_branch_leaves_no_descriptor(world, monkeypatch, name, reason):
    """H1: the subject's and every candidate's image is closed exactly once on every branch."""
    _setup(world, monkeypatch, reason)
    if name == "admission_constructor":
        data = _image("member 1.5.3")
        world.add_member(data)
        world.vendor_dir(MEMBER_VERSION, data)
        _admission_constructor_fails(world, monkeypatch)
    else:
        REFUSAL_BRANCHES[name](world, monkeypatch)
    tracked = _track_images(monkeypatch)
    before = _open_fds()
    assert _outcome(lambda: q.admit_seat(world.env, world.agy)) is not None
    assert _outcome(lambda: _spawn(world)) is not None
    assert _open_fds() == before
    assert not tracked.live


def _peak(fn):
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        result = fn()
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


IMAGE_MIB = 24


@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_8_h3_a_whole_hold_stays_within_the_overhead_ceiling(world, monkeypatch, path):
    """Subject refused, two candidates rejected, the third admitted, all 24 MiB images."""
    size = IMAGE_MIB * 1024 * 1024
    world.agy.write_bytes(os.urandom(size))
    data = os.urandom(size)
    world.add_member(data, "1.5.3")
    world.vendor_dir("1.5.3", data)
    del data
    for version in ("1.5.4", "1.5.5"):
        world.add_member(_image(f"member {version}"), version)
        world.vendor_dir(version, os.urandom(size))
    world.subject = b""
    if path == "preflight":
        result, peak = _peak(lambda: _preflight(world, qualify=lambda *a, **k: {"status": "transient"}))
    else:
        result, peak = _peak(lambda: _spawn(world))
    result.close()
    assert peak < OVERHEAD_CEILING, peak


def test_ec_hold_8_h3_agy_hold_names_no_second_reader():
    tree = ast.parse(SOURCE.read_text())
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not names & {"_open_image", "_read_image", "from_bytes", "realpath"}


@pytest.mark.parametrize("growth", ["at_fstat", "while_streaming"])
def test_ec_hold_8_h4_the_bound_is_read_at_call_time(world, monkeypatch, growth):
    bound = 8192
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", bound)  # the module attribute, never an alias
    exact, over, older = _image("member 1.5.4", bound), _image("member 1.5.5", bound + 1), _image("m 1.5.3")
    for data, version in ((exact, "1.5.4"), (over, "1.5.5"), (older, "1.5.3")):
        world.add_member(data, version)
    if growth == "at_fstat":
        world.vendor_dir("1.5.5", over)
        world.vendor_dir("1.5.4", exact)
        expected = _sha(exact)
    else:
        grower = world.vendor_dir("1.5.5", _image("member 1.5.5", bound)[:bound])
        world.vendor_dir("1.5.3", older)
        real_from_fd = gh.VerifiedImage.from_fd.__func__

        def grow_then_read(cls, fd, *, path=None):
            if os.readlink(f"/proc/self/fd/{fd}") == os.path.realpath(grower):
                with open(grower, "ab") as handle:
                    handle.write(b"#")
            return real_from_fd(cls, fd, path=path)

        monkeypatch.setattr(gh.VerifiedImage, "from_fd", classmethod(grow_then_read))
        expected = _sha(older)
    admission = q.admit_seat(world.env, world.agy)
    try:
        assert admission.image.sha256 == expected  # the walk continued past the oversized one
    finally:
        admission.close()


# ------------------------------------------------------------------- EC-HOLD-9 filesystem

def _refused_without_reading(world, monkeypatch, member):
    calls = _spy(monkeypatch, world)
    with pytest.raises(ValueError):
        q.admit_seat(world.env, world.agy)
    assert member.digest not in calls.reads


def test_ec_hold_9_a_symlinked_candidate_is_not_read(world, monkeypatch):
    data = _image("member 1.5.3")
    world.add_member(data)
    elsewhere = world.tmp / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "agy").write_bytes(data)
    directory = world.vendor / "1.5.3-0000000000000000"
    directory.mkdir()
    (directory / "agy").symlink_to(elsewhere / "agy")
    _refused_without_reading(world, monkeypatch, SimpleNamespace(digest=_sha(data)))


def test_ec_hold_9_a_symlinked_version_directory_is_not_read(world, monkeypatch):
    data = _image("member 1.5.3")
    world.add_member(data)
    real = world.tmp / "real-vendor"
    real.mkdir()
    target = world.vendor_dir(MEMBER_VERSION, data, root=real)
    (world.vendor / "1.5.3-0000000000000000").symlink_to(target.parent)
    _refused_without_reading(world, monkeypatch, SimpleNamespace(digest=_sha(data)))


def test_ec_hold_9_a_directory_swapped_for_a_symlink_after_listing_is_not_read(world, member, monkeypatch):
    directory = next(world.vendor.iterdir())
    real = agy_hold.candidates

    def list_then_swap(**kwargs):
        ordered = real(**kwargs)
        moved = world.tmp / "moved"
        directory.rename(moved)
        directory.symlink_to(moved)
        return ordered

    monkeypatch.setattr(agy_hold, "candidates", list_then_swap)
    _refused_without_reading(world, monkeypatch, member)


@pytest.mark.parametrize("where", ["version_directory", "vendor_root"])
def test_ec_hold_9_a_group_writable_directory_is_not_read(world, member, monkeypatch, where):
    target = next(world.vendor.iterdir()) if where == "version_directory" else world.vendor
    target.chmod(0o775)
    _refused_without_reading(world, monkeypatch, member)


@pytest.mark.parametrize("where", ["vendor_root", "version_directory", "file"])
def test_ec_hold_9_a_component_owned_by_another_uid_is_not_read(world, member, monkeypatch, where):
    directory = next(world.vendor.iterdir())
    target = {"vendor_root": world.vendor, "version_directory": directory, "file": directory / "agy"}[where]
    foreign = os.stat(target).st_ino
    real = agy_hold._require_safe

    def as_if_foreign(info, kind):
        if info.st_ino == foreign:
            info = os.stat_result(tuple(info[:4]) + (os.geteuid() + 4242,) + tuple(info[5:10]))
        return real(info, kind)

    monkeypatch.setattr(agy_hold, "_require_safe", as_if_foreign)
    _refused_without_reading(world, monkeypatch, member)


def _during_read(monkeypatch, target, action):
    """Run ``action`` once, after the first chunk of ``target`` is read at the production site."""
    real_readv = os.readv
    done = []

    def readv(fd, buffers):
        count = real_readv(fd, buffers)
        if not done and os.readlink(f"/proc/self/fd/{fd}") == os.path.realpath(target):
            done.append(True)
            action()
        return count

    monkeypatch.setattr(os, "readv", readv)
    return done


@pytest.mark.parametrize("swap", ["renamed_over", "unlinked", "rewritten_in_place", "untouched"])
def test_ec_hold_9_b2_an_observed_replacement_during_the_read_is_rejected(world, monkeypatch, swap):
    size = 3 * 1024 * 1024  # several chunks: the swap lands after the first
    data, other = _image("member 1.5.3", size), _image("member 1.5.2", size)
    world.add_member(data, "1.5.3")
    world.add_member(other, "1.5.2")
    target = world.vendor_dir("1.5.3", data)
    staged = world.tmp / "staged-agy"
    staged.write_bytes(other)
    staged.chmod(0o755)

    def renamed_over():
        os.rename(staged, target)

    def unlinked():
        target.unlink()

    def rewritten_in_place():
        with open(target, "r+b") as handle:
            handle.write(b"X" * 16)
        stamp = os.stat(target).st_mtime_ns + 1_000_000_000
        os.utime(target, ns=(stamp, stamp))

    actions = {"renamed_over": renamed_over, "unlinked": unlinked,
               "rewritten_in_place": rewritten_in_place, "untouched": lambda: None}
    done = _during_read(monkeypatch, target, actions[swap])
    calls = _spy(monkeypatch, world)
    outcome = _outcome(lambda: q.admit_seat(world.env, world.agy))
    assert done
    if swap == "untouched":
        assert outcome is None
    else:
        assert outcome is not None
        assert _sha(other) not in calls.reads  # the replacement's bytes are not read in that walk


# ------------------------------------------------------------- EC-HOLD-12/15 status

def _status(world, monkeypatch, subject_path=None):
    monkeypatch.setenv("PATH", world.env["PATH"])
    monkeypatch.setenv("HOME", world.env["HOME"])
    path = world.agy if subject_path is None else subject_path

    def resolved(leg, env):
        return seat_subject.SeatSubject(leg, "standalone", Path(path), None, None)

    monkeypatch.setattr(seat_subject, "resolve_seat_subject", resolved)
    # The verdict is today's (it may execute); only the hold object is under test here.
    monkeypatch.setattr(q, "admission_verdict", lambda *a, **k: q.AgyVerdict("refuses", "agy_image_unqualified", None))
    out = io.StringIO()
    with redirect_stdout(out):
        assert q.cli_main(argparse.Namespace(action="status")) == 0
    text = out.getvalue()
    assert "active" not in text.lower() and "in use" not in text.lower()
    return json.loads(text)["hold"]


NOT_COVERED = {"seat_profile": "not_covered", "heartbeat": "not_covered", "jailed": "not_covered"}
COVERED = {"seat_profile": "covered", "heartbeat": "covered", "jailed": "not_covered"}


def test_ec_hold_12_status_with_the_hold_disabled(world, member, monkeypatch):
    world.config("[agy]\nhold = false\n")
    calls = _spy(monkeypatch, world)
    assert _status(world, monkeypatch) == {"enabled": False, "subject": "standalone",
                                           "routes": NOT_COVERED, "candidate": None}
    assert calls.anchors == []


def test_ec_hold_15_status_for_a_managed_release_subject(world, member, monkeypatch):
    releases = world.tmp / "releases"
    native = releases / "sync-0" / "native" / "agy"
    native.parent.mkdir(parents=True)
    native.write_bytes(world.subject)
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", releases)
    calls = _spy(monkeypatch, world)
    assert _status(world, monkeypatch, native) == {"enabled": True, "subject": "managed_release",
                                                   "routes": NOT_COVERED, "candidate": None}
    assert calls.anchors == [] and calls.reads == []


def test_ec_hold_15_status_names_a_ready_release_member(world, member, monkeypatch):
    assert _status(world, monkeypatch) == {
        "enabled": True, "subject": "standalone", "routes": COVERED,
        "candidate": {"origin": "vendor", "version": MEMBER_VERSION, "image_sha256": member.digest,
                      "admission_class": "release_qualified", "state": "ready"}}


def test_ec_hold_15_status_names_a_store_qualified_candidate_without_measuring_help(world, monkeypatch):
    data = _local_candidate(world, "1.6.0", cache=True)
    hold = _status(world, monkeypatch)
    assert hold["candidate"] == {"origin": "cache", "version": "1.6.0", "image_sha256": _sha(data),
                                 "admission_class": "locally_qualified",
                                 "state": "pending_help_measurement"}
    assert world.helps == []


def test_ec_hold_15_status_with_no_candidate(world, monkeypatch):
    assert _status(world, monkeypatch) == {"enabled": True, "subject": "standalone",
                                           "routes": COVERED, "candidate": None}


def test_ec_hold_15_the_jailed_route_is_not_covered_in_this_lane():
    assert dict(agy_hold.ROUTE_COVERAGE) == {"seat_profile": True, "heartbeat": True, "jailed": False}


def test_ec_hold_12_status_with_no_provider_still_reports_the_hold(world, monkeypatch):
    monkeypatch.setenv("PATH", str(world.tmp / "empty"))

    def absent(leg, env):
        raise FileNotFoundError("seat_provider_unavailable")

    monkeypatch.setattr(seat_subject, "resolve_seat_subject", absent)
    out = io.StringIO()
    with redirect_stdout(out):
        assert q.cli_main(argparse.Namespace(action="status")) == 0
    assert json.loads(out.getvalue())["hold"] == {"enabled": True, "subject": "standalone",
                                                  "routes": NOT_COVERED, "candidate": None}


# ---------------------------------------------------------------------------- concurrency

def test_ec_hold_8_concurrent_holds_are_serialized(world, member, monkeypatch):
    """Candidate loading in one process is serialized by the module lock (AGYFRESH §1.2)."""
    active, peak, lock = [0], [0], threading.Lock()
    real = agy_hold.select

    def counting(*args, **kwargs):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            return real(*args, **kwargs)
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(agy_hold, "select", counting)
    results = []

    def hold():
        admission = q.admit_seat(world.env, world.agy)
        results.append(admission.image.sha256)
        admission.close()

    threads = [threading.Thread(target=hold) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [member.digest] * 4 and peak[0] == 1


# ------------------------------------------- fix round 1: the review's REQUIRED items 1 to 4

def _when_read(monkeypatch, target, action):
    """Run ``action(fd)`` once, right after the first chunk of ``target`` is read at the
    production read site (``os.readv`` in ``VerifiedImage.from_fd``)."""
    real_readv = os.readv
    hit = []

    def readv(fd, buffers):
        count = real_readv(fd, buffers)
        if not hit and os.readlink(f"/proc/self/fd/{fd}") == os.path.realpath(target):
            hit.append(True)
            action(fd)
        return count

    monkeypatch.setattr(os, "readv", readv)
    return hit


@pytest.mark.parametrize("last", ["would_win", "would_lose"])
def test_ec_hold_2_a_cancellation_during_the_last_candidates_read_is_a_cancellation(world, monkeypatch, last):
    """REQUIRED 1: the caller cancels while the last candidate streams. The walk raises the
    cancellation code: never an admission of a winner, never the subject's refusal after a
    loser, and every image it opened is closed."""
    size = 3 * 1024 * 1024
    data = _image("member 1.5.3", size)
    world.add_member(data)
    target = world.vendor_dir(MEMBER_VERSION, data if last == "would_win" else _junk("1.5.3", size))
    event = threading.Event()
    hit = _when_read(monkeypatch, target, lambda fd: event.set())
    tracked = _track_images(monkeypatch)
    before = _open_fds()
    assert _outcome(lambda: _preflight(world, cancel_event=event)) == (ValueError, q.CANCELLED)
    assert hit and _open_fds() == before and not tracked.live


@pytest.mark.parametrize("measured", ["returns_help", "run_stopped"])
def test_ec_hold_2_a_cancellation_during_the_last_candidates_measurement_is_a_cancellation(
        world, monkeypatch, measured):
    """REQUIRED 1: the held help measurement receives the caller's event, and a cancellation
    while it runs is the cancellation code whether the run still returns help or stops."""
    _local_candidate(world, "1.6.0")
    event = threading.Event()
    seen = []

    def help_while_cancelled(image, env, *, cancel_event=None):
        seen.append(cancel_event)
        event.set()
        if measured == "run_stopped":
            raise ValueError(q.SELF_QUALIFICATION_UNAVAILABLE)
        return HELP

    monkeypatch.setattr(q, "_run_help", help_while_cancelled)
    tracked = _track_images(monkeypatch)
    before = _open_fds()
    assert _outcome(lambda: _preflight(world, cancel_event=event)) == (ValueError, q.CANCELLED)
    assert seen == [event]
    assert _open_fds() == before and not tracked.live


def test_ec_hold_2_a_cancellation_before_measurement_runs_nothing(world, monkeypatch):
    _local_candidate(world, "1.6.0")
    event = threading.Event()
    real_predicate = q._hold_predicates

    def predicates(*args, **kwargs):
        excluded, cache_version, predicate, store_dir = real_predicate(*args, **kwargs)

        def cancel_then_judge(image, candidate):
            event.set()  # after streaming and the stage checks, before help
            return predicate(image, candidate)

        return excluded, cache_version, cancel_then_judge, store_dir

    monkeypatch.setattr(q, "_hold_predicates", predicates)
    assert _outcome(lambda: _preflight(world, cancel_event=event)) == (ValueError, q.CANCELLED)
    assert world.helps == []


@pytest.mark.parametrize("stopped", ["before_launch", "during_run", "not_cancelled"])
def test_the_held_help_run_carries_the_callers_cancellation_to_the_liveness_path(world, monkeypatch, stopped):
    """REQUIRED 1: the real ``_run_help`` gives the run's monitor the caller's event; the
    liveness path's two cancellation outcomes are ``CANCELLED``. An uncancelled failed run
    stays the measurement's own refusal."""
    monkeypatch.setattr(q, "_run_help", _REAL_RUN_HELP)
    image = gh.VerifiedImage.from_bytes(_image("local 1.6.0"))
    event = threading.Event()
    seen = []

    def liveness(cmd, *, review_monitor=None, **_kwargs):
        seen.append(review_monitor.cancel)
        if stopped == "before_launch":
            event.set()
            raise pi._ReviewOperationCancelled("review_operation_cancelled")
        if stopped == "during_run":
            event.set()
            return pi._LegRun(1, "", "review_operation_cancelled")
        return pi._LegRun(1, "", "synthetic failure")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", liveness)
    expected = q.SELF_QUALIFICATION_UNAVAILABLE if stopped == "not_cancelled" else q.CANCELLED
    try:
        with pytest.raises(ValueError, match=f"^{expected}$"):
            q._run_help(image, world.env, cancel_event=event)
    finally:
        image.close()
    assert seen == [event]


def _owned_profile(world):
    with gh.owned_profile(world.env, settings_bytes=b"{}", credential_path=world.token):
        pass


@pytest.mark.parametrize("side", ["candidate", "subject"])
@pytest.mark.parametrize("route", ["admit", "require_capability", "owned_profile"])
def test_ec_hold_2_typed_quiescence_keeps_its_type_at_the_heartbeat_boundary(world, monkeypatch, side, route):
    """REQUIRED 2: the public heartbeat path (route 2) keeps the typed process-group
    quiescence outcome of a held candidate's help measurement, and of the subject's own."""
    from phase_loop_runtime.panel_invoker import ProviderProcessGroupQuiescenceError

    if side == "candidate":
        _local_candidate(world, "1.6.0")
    else:
        world.seed_local(world.subject, "9.9.9")
    error = ProviderProcessGroupQuiescenceError("synthetic group quiescence")

    def refuse(image, env, **_kwargs):
        raise error

    monkeypatch.setattr(q, "_run_help", refuse)
    call = {"admit": lambda: gh.admit(world.env).close(),
            "require_capability": lambda: gh.require_capability(world.env),
            "owned_profile": lambda: _owned_profile(world)}[route]
    tracked = _track_images(monkeypatch)
    before = _open_fds()
    with pytest.raises(ProviderProcessGroupQuiescenceError) as caught:
        call()
    assert caught.value is error
    assert _open_fds() == before and not tracked.live


@pytest.mark.parametrize("kind", ["typed_quiescence", "seal_error"])
@pytest.mark.parametrize("path", ["preflight", "heartbeat", "spawn"])
def test_ec_hold_2_the_legacy_capability_mapping_keeps_only_the_seal_error(world, member, monkeypatch, path, kind):
    """REQUIRED 2, reconciled: the subject's help measurement in lookup raises either the
    typed quiescence outcome (§2.2: propagates with its type on every path) or the plain
    seal error (first use and the heartbeat keep today's capability code; the seat site keeps
    its typed refusal). Neither is held."""
    from phase_loop_runtime.panel_invoker import ProviderProcessGroupQuiescenceError

    world.seed_local(world.subject, "9.9.9")
    error = (ProviderProcessGroupQuiescenceError("synthetic group quiescence") if kind == "typed_quiescence"
             else AgyCanaryEvidenceError("synthetic seal error"))

    def refuse(image, env, **_kwargs):
        raise error

    monkeypatch.setattr(q, "_run_help", refuse)
    calls = _spy(monkeypatch, world)
    outcome = _outcome({"preflight": lambda: _preflight(world), "heartbeat": lambda: gh.admit(world.env),
                        "spawn": lambda: _spawn(world)}[path])
    if kind == "typed_quiescence":
        assert outcome == (ProviderProcessGroupQuiescenceError, str(error))
    elif path == "spawn":
        assert outcome == _UNQUALIFIED
    else:
        assert outcome == _CAPABILITY
    assert calls.anchors == [] and calls.candidates == []


@pytest.mark.parametrize("direction", ["standalone_then_managed", "managed_then_standalone"])
def test_ec_hold_6_the_subject_read_is_the_subject_classified(world, member, monkeypatch, direction):
    """REQUIRED 3: the PATH ``agy`` symlink is retargeted between the classification and the
    read. The read opens the name captured for the classification, so the bytes refused and
    the managed-or-standalone decision are about the same file."""
    standalone = world.tmp / "standalone" / "agy"
    standalone.parent.mkdir()
    standalone.write_bytes(world.subject)
    standalone.chmod(0o755)
    releases = world.tmp / "releases"
    managed = releases / "sync-0" / "native" / "agy"
    managed.parent.mkdir(parents=True)
    managed_bytes = _image("managed native 1.5.11")
    managed.write_bytes(managed_bytes)
    managed.chmod(0o755)
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", releases)
    first, second = (standalone, managed) if direction == "standalone_then_managed" else (managed, standalone)
    link = world.tmp / "linkbin" / "agy"
    link.parent.mkdir()
    link.symlink_to(first)
    real_read = q._read_subject

    def retarget_then_read(path, resolved):
        link.unlink()
        link.symlink_to(second)
        return real_read(path, resolved)

    monkeypatch.setattr(q, "_read_subject", retarget_then_read)
    calls = _spy(monkeypatch, world)
    evidence = {}
    if direction == "standalone_then_managed":
        _spawn(world, link, evidence).close()
        # The standalone file was read and refused, so holding is right, and it says so.
        assert evidence["provider_subject_image_sha256"] == _sha(world.subject) != _sha(managed_bytes)
        assert evidence["provider_image_sha256"] == member.digest
    else:
        with pytest.raises(agy_integrity.AgyImageUnqualified):
            _spawn(world, link, evidence)
        assert calls.anchors == []  # the managed image was read and is never held


@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_1_the_streaming_cap_is_detected_after_the_subject_shrinks(world, member, monkeypatch, path):
    """REQUIRED 4: the subject grows past the bound while it streams and shrinks back before
    anything could stat it again. The reader's own cap refusal classifies it."""
    bound = 8192
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", bound)
    world.subject = _image("subject 9.9.9", bound)
    world.agy.write_bytes(world.subject)  # within the bound when it is opened
    real_readv = os.readv
    target = os.path.realpath(world.agy)
    state = {}

    def readv(fd, buffers):
        mine = os.readlink(f"/proc/self/fd/{fd}") == target
        if mine and "grown" not in state:
            state["grown"] = True
            with open(world.agy, "ab") as handle:
                handle.write(b"#" * 4096)
        count = real_readv(fd, buffers)
        if mine and "shrunk" not in state:
            state["shrunk"] = True
            os.truncate(world.agy, bound)
        return count

    monkeypatch.setattr(os, "readv", readv)
    if path == "preflight":
        admission = _preflight(world)
        try:
            assert (admission.source, admission.hold_reason, admission.subject_sha256) == (
                "lkg", "subject_over_bound", None)
        finally:
            admission.close()
    else:
        evidence = {}
        _spawn(world, evidence=evidence).close()
        assert evidence["provider_hold_reason"] == "subject_over_bound"
    assert os.path.getsize(world.agy) == bound and state == {"grown": True, "shrunk": True}


@pytest.mark.parametrize("path", ["preflight", "spawn"])
def test_ec_hold_2_a_digest_mismatch_is_not_the_subjects_and_is_never_held(world, member, monkeypatch, path):
    """REQUIRED 4, the reverse race: the re-hash disagrees while the subject grows past the
    bound. That is not a subject-side reason: it propagates, and nothing is held."""
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", 8192)
    real = gh._fd_digest_into
    state = {}

    def mismatch(fd, buffer):
        if state:
            return real(fd, buffer)
        state["hit"] = True
        with open(world.agy, "ab") as handle:
            handle.write(b"#" * 8192)
        return "0" * 64

    monkeypatch.setattr(gh, "_fd_digest_into", mismatch)
    calls = _spy(monkeypatch, world)
    outcome = _outcome(lambda: _preflight(world) if path == "preflight" else _spawn(world))
    assert outcome == (_CAPABILITY if path == "preflight" else _UNQUALIFIED)
    assert state and calls.anchors == []


@pytest.mark.parametrize("held", [True, False])
def test_run_output_says_whether_the_admission_was_held(world, monkeypatch, capsys, held):
    """Recommendation: ``agy-qualification run`` says what it admitted; existing fields kept."""
    monkeypatch.setenv("PATH", world.env["PATH"])
    monkeypatch.setenv("HOME", world.env["HOME"])
    monkeypatch.setattr(seat_subject, "resolve_seat_subject",
                        lambda leg, env: seat_subject.SeatSubject(leg, "standalone", world.agy, None, None))
    data = _image("member 1.5.3")
    world.add_member(data if held else world.subject)
    world.vendor_dir(MEMBER_VERSION, data)
    assert q.cli_main(argparse.Namespace(action="run")) == 0
    printed = json.loads(capsys.readouterr().out)
    if held:
        assert printed == {"admission_class": "release_qualified", "image_sha256": _sha(data),
                           "help_sha256": _sha(HELP), "source": "lkg",
                           "hold_reason": "provenance_unverified",
                           "subject_image_sha256": _sha(world.subject)}
    else:
        assert printed == {"admission_class": "release_qualified", "image_sha256": _sha(world.subject),
                           "help_sha256": _sha(HELP), "source": "subject"}


def test_a_hint_that_grows_past_its_bound_after_the_stat_is_skipped_unparsed(world, monkeypatch):
    monkeypatch.setattr(agy_hold, "MAX_HINT_BYTES", 64)
    store = world.store()
    hint = store.host_dir / f"qualified-{'c' * 64}.json"
    hint.write_text(json.dumps({"payload": {"release_version": "1.6.0"}}))
    real_fstat = os.fstat
    parsed = []

    def fstat_then_grow(fd):
        info = real_fstat(fd)
        if os.readlink(f"/proc/self/fd/{fd}") == os.path.realpath(hint) and not parsed:
            parsed.append(True)
            hint.write_text(json.dumps({"payload": {"release_version": "1.6.0"}, "pad": "x" * 64}))
        return info

    monkeypatch.setattr(os, "fstat", fstat_then_grow)
    loads = []
    real_loads = json.loads
    monkeypatch.setattr(agy_hold.json, "loads", lambda data, **k: loads.append(data) or real_loads(data, **k))
    anchor = agy_hold.open_anchor(store.host_dir)
    try:
        assert agy_hold._hint_versions(anchor) == set()
    finally:
        os.close(anchor)
    assert parsed and loads == []


# ------------------------------------------- fix round 2: the re-review's REQUIRED items

@pytest.mark.parametrize("cancelled", [True, False])
def test_ec_hold_2_a_repeated_preflight_observes_the_callers_cancellation(world, member, monkeypatch, cancelled):
    """Re-review REQUIRED 1: the second preflight for one requalification key is lookup only
    (``gh.admit``) and can reach the hold; it carries the caller's event there."""
    first = q.requalify_once(world.env, subject_path=world.agy)
    try:
        assert (first.source, first.image.sha256) == ("lkg", member.digest)
    finally:
        first.close()
    event = threading.Event()
    if cancelled:
        event.set()
    calls = _spy(monkeypatch, world)
    tracked = _track_images(monkeypatch)
    before = _open_fds()
    outcome = _outcome(lambda: q.requalify_once(world.env, cancel_event=event, subject_path=world.agy))
    if cancelled:
        assert outcome == (ValueError, q.CANCELLED)
        assert calls.candidates == []  # no candidate is opened, let alone measured
    else:
        assert outcome is None and member.digest in calls.reads  # the repeat still holds
    assert _open_fds() == before and not tracked.live


def test_ec_hold_2_a_cancellation_during_predicate_setup_is_a_cancellation(world, member, monkeypatch):
    """Re-review REQUIRED 1: the deny list is read again as the hold sets up its predicate;
    the caller cancels meanwhile and that read fails. That early miss is the cancellation,
    not the subject's refusal. Without a cancellation it stays the subject's refusal."""
    event = threading.Event()

    def unreadable_after_cancel():
        event.set()
        return None

    monkeypatch.setattr(agy_hold, "hold_deny", unreadable_after_cancel)
    calls = _spy(monkeypatch, world)
    assert _outcome(lambda: _preflight(world, cancel_event=event)) == (ValueError, q.CANCELLED)
    assert calls.anchors == []
    monkeypatch.setattr(agy_hold, "hold_deny", lambda: None)
    assert _outcome(lambda: _preflight(world, cancel_event=threading.Event())) == PREFLIGHT_REFUSAL["no_record"]


@pytest.mark.parametrize("subject_kind", ["standalone", "managed"])
def test_ec_hold_6_the_captured_name_is_classified_not_what_replaces_it(world, member, monkeypatch, subject_kind):
    """Re-review REQUIRED 2: the resolved subject entry itself is replaced, during its read,
    by a symlink to the other side of the managed root. The classification is of the name
    captured and read, never of what the entry names afterwards."""
    size = 3 * 1024 * 1024
    releases = world.tmp / "releases"
    managed = releases / "sync-0" / "native" / "agy"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(_image("managed native 1.5.11", size))
    managed.chmod(0o755)
    monkeypatch.setattr(seat_subject, "MANAGED_RELEASES_ROOT", releases)
    standalone = world.tmp / "standalone" / "agy"
    standalone.parent.mkdir()
    standalone_bytes = _image("standalone subject 9.9.9", size)
    standalone.write_bytes(standalone_bytes)
    standalone.chmod(0o755)
    subject, other = (standalone, managed) if subject_kind == "standalone" else (managed, standalone)
    # The other side survives the swap as its own file: the link points at a copy.
    other_copy = other.with_name("agy-elsewhere")
    shutil.copyfile(other, other_copy)

    def replace_the_entry(_fd):
        subject.unlink()
        subject.symlink_to(other_copy)

    hit = _when_read(monkeypatch, subject, replace_the_entry)
    calls = _spy(monkeypatch, world)
    evidence = {}
    if subject_kind == "standalone":
        _spawn(world, subject, evidence).close()
        assert (evidence["provider_admission_source"], evidence["provider_subject_image_sha256"]) == (
            "lkg", _sha(standalone_bytes))
        assert evidence["provider_image_sha256"] == member.digest
    else:
        with pytest.raises(agy_integrity.AgyImageUnqualified):
            _spawn(world, subject, evidence)
        assert calls.anchors == []  # still a managed-release subject: nothing searched
    assert hit and subject.is_symlink()
