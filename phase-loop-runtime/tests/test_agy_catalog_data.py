"""The shipped agy catalog as package data (AGYROLL §3.1; RECBIND SL-1, EC-RECBIND-1).

``gemini_heartbeat.QUALIFIED_IMAGES`` loads from ``phase_loop_runtime/data/agy_catalog.json``.
The loader is strict and offline; any defect is an empty catalog, so the release fast path
admits nothing.
"""
from __future__ import annotations

import copy
import json
import os
import tomllib
from hashlib import sha256
from pathlib import Path

import pytest

from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import gemini_heartbeat as gh

DATA = Path(gh.__file__).resolve().parent / "data" / "agy_catalog.json"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _member(image="a" * 64, version="9.9.9", **extra):
    return {"release_version": version, "image_sha256": image, "help_sha256": "b" * 64,
            "asset_sha256": "c" * 64, "qci": "d" * 64, "published_at": "2026-11-07T08:38:26Z",
            "pinned": False, "record": f"agy-{version}-linux-x64-qualification.json", **extra}


def _catalog(*members):
    return {"schema": "qualified_agy_catalog.v3", "routes": {"linux-x64": list(members)}}


def test_the_shipped_catalog_loads_and_is_the_runtime_set():
    assert gh.load_catalog() == gh.QUALIFIED_IMAGES and gh.QUALIFIED_IMAGES
    assert gh.CATALOG_STATUS == "ok"
    members = gh.parse_catalog(DATA.read_text())
    assert {m["image_sha256"]: m["help_sha256"] for m in members} == gh.QUALIFIED_IMAGES
    # Every shipped member is bound to the QCI of this tree (the verifier enforces it too).
    assert {m["qci"] for m in members} == {q.seat_qci()}


def test_the_catalog_ships_as_package_data():
    declared = tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]["package-data"]["phase_loop_runtime"]
    assert "data/agy_catalog.json" in declared


def _bad(change):
    value = _catalog(_member())
    change(value)
    return json.dumps(value)


BAD = {
    "malformed_json": "{not json",
    "not_an_object": "[]",
    "wrong_schema": _bad(lambda v: v.update(schema="qualified_agy_catalog.v2")),
    "extra_top_key": _bad(lambda v: v.update(extra=1)),
    "wrong_route": _bad(lambda v: v.update(routes={"linux-arm64": v["routes"]["linux-x64"]})),
    "extra_route": _bad(lambda v: v["routes"].update({"linux-arm64": []})),
    "extra_member_key": _bad(lambda v: v["routes"]["linux-x64"][0].update(capture_surface_sha256="e" * 64)),
    "missing_member_key": _bad(lambda v: v["routes"]["linux-x64"][0].pop("asset_sha256")),
    "short_digest": _bad(lambda v: v["routes"]["linux-x64"][0].update(image_sha256="a" * 63)),
    "upper_digest": _bad(lambda v: v["routes"]["linux-x64"][0].update(qci="D" * 64)),
    "pinned_not_bool": _bad(lambda v: v["routes"]["linux-x64"][0].update(pinned="false")),
    "bad_version": _bad(lambda v: v["routes"]["linux-x64"][0].update(release_version="1.5")),
    "bad_published_at": _bad(lambda v: v["routes"]["linux-x64"][0].update(published_at="yesterday")),
    "record_mismatch": _bad(lambda v: v["routes"]["linux-x64"][0].update(record="agy-1.0.0-linux-x64-qualification.json")),
    "duplicate_image": json.dumps(_catalog(_member(), _member(version="9.9.8"))),
    "duplicate_version": json.dumps(_catalog(_member(), _member(image="f" * 64))),
    "duplicate_json_key": '{"schema": "qualified_agy_catalog.v3", "schema": "qualified_agy_catalog.v3", "routes": {}}',
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_a_malformed_catalog_is_empty(tmp_path, name):
    path = tmp_path / "agy_catalog.json"
    path.write_text(BAD[name])
    assert gh.load_catalog(path) == {}
    assert gh.CATALOG_STATUS == "malformed"


def test_a_missing_catalog_is_empty(tmp_path):
    assert gh.load_catalog(tmp_path / "absent.json") == {}
    assert gh.CATALOG_STATUS == "missing"


def test_an_empty_catalog_is_empty(tmp_path):
    path = tmp_path / "agy_catalog.json"
    path.write_text(json.dumps(_catalog()))
    assert gh.load_catalog(path) == {}
    assert gh.CATALOG_STATUS == "empty"


def test_the_loader_never_raises_at_import(tmp_path, monkeypatch):
    """A broken shipped file must not break importing the runtime."""
    from importlib import resources

    class Broken:
        def joinpath(self, *parts):
            raise OSError("unreadable")

    monkeypatch.setattr(resources, "files", lambda package: Broken())
    assert gh.load_catalog() == {} and gh.CATALOG_STATUS == "missing"


needs_memfd = pytest.mark.skipif(not hasattr(os, "memfd_create") or not hasattr(os, "pidfd_open"),
                                 reason="admission needs sealed memfds and pidfds")


@pytest.fixture
def subject(tmp_path):
    path = tmp_path / "agy"
    path.write_bytes(b"\x7fELF stand-in image bytes for the release fast path\n")
    path.chmod(0o755)
    return path, sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def no_lookup(monkeypatch):
    """Prove the fast path decides alone: any fall-through to lookup (store, network) is a miss."""
    calls = []

    def lookup(env, data, path, **kwargs):
        calls.append(path)
        raise ValueError(gh._CAPABILITY)

    monkeypatch.setattr(q, "lookup", lookup)
    return calls


@needs_memfd
def test_a_data_file_member_is_admitted_release_qualified_offline(tmp_path, monkeypatch, subject, no_lookup):
    path, digest = subject
    catalog = tmp_path / "agy_catalog.json"
    catalog.write_text(json.dumps(_catalog(_member(image=digest))))
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", gh.load_catalog(catalog))
    admission = gh.admit({"PATH": str(path.parent)}, subject_path=path)
    try:
        assert admission.admission_class == "release_qualified" and admission.image.sha256 == digest
        assert admission.help_sha256 == "b" * 64
    finally:
        admission.close()
    assert no_lookup == []


@needs_memfd
@pytest.mark.parametrize("name", ["malformed_json", "extra_member_key", "wrong_route", "duplicate_image"])
def test_a_malformed_catalog_admits_nothing_by_the_release_fast_path(tmp_path, monkeypatch, subject, no_lookup, name):
    path, digest = subject
    good = _catalog(_member(image=digest))
    text = BAD[name] if name != "duplicate_image" else json.dumps(
        _catalog(_member(image=digest), _member(image=digest, version="9.9.8")))
    if name == "extra_member_key":
        broken = copy.deepcopy(good)
        broken["routes"]["linux-x64"][0]["extra"] = True
        text = json.dumps(broken)
    catalog = tmp_path / "agy_catalog.json"
    catalog.write_text(text)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", gh.load_catalog(catalog))
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        gh.admit({"PATH": str(path.parent)}, subject_path=path)
    assert no_lookup == [str(path)]  # it fell through to lookup, which refuses
