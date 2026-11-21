"""The grok release catalog, its gate file, the signature check and ``check_tree``
(GROKROLL §1, §2.4, §2.5; lane SL-0).

Contract: ``plans/artifacts/grokroll-v1-contract.md``. The signature test uses the one real
registry signature vector of GROKROLL §0 and imports ``cryptography`` unconditionally: it has
no skip path, so an environment without the ``grok-catalog`` extra fails it.
"""

from __future__ import annotations

import base64
import builtins
import copy
import json
import shutil
import sys
from hashlib import sha256, sha512
from pathlib import Path

import cryptography  # noqa: F401 - no skip path: a missing extra fails this module
import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime.grok_roll import catalog as rc

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "grok_roll" / "trees"
SIGNED = json.loads((FIXTURES / "signed_entry.json").read_text())
KEYID = "SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U"
PACKAGE_DATA = Path(rc.__file__).resolve().parents[1] / "data"


def entry(version: str, *, pinned: bool = False, **overrides) -> dict:
    """A well-formed entry for ``version`` (its signature is not a real one)."""
    value = {
        "version": version, "package": rc.PACKAGE,
        "tarball_integrity": "sha512-" + base64.b64encode(sha512(version.encode()).digest()).decode(),
        "registry_keyid": KEYID, "registry_signature": SIGNED["registry_signature"],
        "member": rc.MEMBER, "binary_sha256": sha256(version.encode()).hexdigest(),
        "binary_bytes": 208487936, "pinned": pinned,
    }
    value.update(overrides)
    return value


def document(releases) -> dict:
    return {"schema": rc.RELEASE_CATALOG_SCHEMA, "platform": rc.PLATFORM, "releases": list(releases)}


def encode(value) -> bytes:
    return json.dumps(value).encode()


def versions(count: int) -> list[str]:
    return [f"1.0.{index}" for index in range(1, count + 1)]


# ----------------------------------------------------------------------- the loader

def test_ec_grokroll_4_the_shipped_catalog_is_empty_and_loads():
    catalog = rc.load_releases()
    assert catalog is not None and catalog.releases == () and catalog.platform == "linux-x64"
    assert rc.load_releases(PACKAGE_DATA) == catalog


def _set(path, value):
    def change(doc):
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


def _drop(path):
    def change(doc):
        target = doc
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return change


def _raw(text):
    return lambda _doc: text


#: One refusal per loader rule of GROKROLL §1. Every case breaks one entry of three, or
#: the document, and must void the whole file.
REFUSALS = {
    "over 256 KiB": lambda doc: json.dumps(doc) + " " * rc.CATALOG_MAX_BYTES,
    "invalid JSON": _raw('{"schema": '),
    "NaN": _set(("releases", 1, "binary_bytes"), float("nan")),
    "duplicate top-level key": lambda doc: json.dumps(doc)[:-1] + ', "platform": "linux-x64"}',
    "duplicate entry key": lambda doc: json.dumps(doc).replace(
        '"pinned": false}', '"pinned": false, "pinned": false}', 1),
    "wrong schema": _set(("schema",), "grok_release_catalog.v2"),
    "wrong platform": _set(("platform",), "linux-arm64"),
    "missing top-level key": _drop(("platform",)),
    "unknown top-level key": _set(("generated_at",), "2026-11-21T00:00:00Z"),
    "missing entry key": _drop(("releases", 1, "member")),
    "unknown entry key": _set(("releases", 1, "published_at"), "2026-11-21T00:00:00Z"),
    "releases not a list": _set(("releases",), {}),
    "entry not an object": _set(("releases", 1), ["1.0.2"]),
    "binary_bytes a string": _set(("releases", 1, "binary_bytes"), "208487936"),
    "binary_bytes a boolean": _set(("releases", 1, "binary_bytes"), True),
    "pinned a string": _set(("releases", 1, "pinned"), "false"),
    "pinned null": _set(("releases", 1, "pinned"), None),
    "version two parts": _set(("releases", 1, "version"), "1.0"),
    "version leading zero": _set(("releases", 1, "version"), "1.0.02"),
    "version pre-release": _set(("releases", 1, "version"), "1.0.2-alpha"),
    "version padded": _set(("releases", 1, "version"), " 1.0.2"),
    "version a number": _set(("releases", 1, "version"), 1.02),
    "another package": _set(("releases", 1, "package"), "@xai-official/grok"),
    "another member": _set(("releases", 1, "member"), "package/bin/grok"),
    "digest upper case": _set(("releases", 1, "binary_sha256"), "A" * 64),
    "digest short": _set(("releases", 1, "binary_sha256"), "a" * 63),
    "integrity sha256": _set(("releases", 1, "tarball_integrity"),
                             "sha256-" + base64.b64encode(b"x" * 32).decode()),
    "integrity short": _set(("releases", 1, "tarball_integrity"),
                            "sha512-" + base64.b64encode(b"x" * 63).decode()),
    "integrity not base64": _set(("releases", 1, "tarball_integrity"), "sha512-" + "!" * 86 + "=="),
    "binary_bytes zero": _set(("releases", 1, "binary_bytes"), 0),
    "binary_bytes over the bound": _set(("releases", 1, "binary_bytes"), rc.MAX_BINARY_BYTES + 1),
    "unknown key id": _set(("releases", 1, "registry_keyid"), "SHA256:" + "A" * 43),
    "signature not a string": _set(("releases", 1, "registry_signature"), None),
    "signature empty": _set(("releases", 1, "registry_signature"), ""),
    "duplicate version": _set(("releases", 1, "version"), "1.0.1"),
    "duplicate digest": _set(("releases", 1, "binary_sha256"), sha256(b"1.0.1").hexdigest()),
    "not sorted": lambda doc: json.dumps(document([doc["releases"][1], doc["releases"][0],
                                                   doc["releases"][2]])),
    "sorted as text, not as numbers": lambda doc: json.dumps(document(
        [entry("1.0.10"), entry("1.0.9")])),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_ec_grokroll_4_each_loader_rule_voids_the_whole_file(case):
    base = document(entry(version) for version in versions(3))
    mutated = copy.deepcopy(base)
    result = REFUSALS[case](mutated)
    raw = result.encode() if isinstance(result, str) else encode(mutated)
    assert rc.parse_releases(encode(base)).releases  # the base itself loads
    with pytest.raises(rc.CatalogRefused):
        rc.parse_releases(raw)


def test_ec_grokroll_4_twenty_five_entries_refuse_and_twenty_four_load():
    with pytest.raises(rc.CatalogRefused) as refused:
        rc.parse_releases(encode(document(entry(version) for version in versions(25))))
    assert refused.value.code == "grok_catalog_too_many_releases"
    catalog = rc.parse_releases(encode(document(entry(version) for version in versions(24))))
    assert len(catalog.releases) == rc.MAX_RELEASES == 24


def test_ec_grokroll_4_load_releases_is_none_on_refusal(tmp_path):
    (tmp_path / rc.RELEASES_NAME).write_text('{"schema": "grok_release_catalog.v1"}')
    assert rc.load_releases(tmp_path) is None
    assert rc.load_releases(tmp_path / "missing") is None


def test_versions_order_as_integer_triples():
    assert rc.version_key("1.0.10") > rc.version_key("1.0.9")
    assert rc.version_key("2.0.0") > rc.version_key("1.99.99")
    with pytest.raises(rc.CatalogRefused):
        rc.version_key("1.0")


# ------------------------------------------------------------------------------ aging

def test_ec_grokroll_7_pinned_and_surfaced_entries_beyond_the_newest_twelve_survive_aging():
    entries = [entry(version, pinned=index in (0, 3, 5)) for index, version in
               enumerate(versions(24))]
    catalog = rc.parse_releases(encode(document(entries)))
    surfaced = {entries[1]["binary_sha256"], entries[7]["binary_sha256"]}
    kept = rc.aging(catalog, surfaced)
    kept_versions = [item["version"] for item in kept]
    newest = versions(24)[-rc.RELEASE_KEEP:]
    assert set(newest) <= set(kept_versions)
    for index in (0, 3, 5, 1, 7):  # pinned, then surfaced, all beyond the newest twelve
        assert entries[index]["version"] in kept_versions
    assert len(kept) == rc.RELEASE_KEEP + 5
    assert [item["version"] for item in rc.aging(catalog)] == [
        entries[index]["version"] for index in (0, 3, 5)] + newest


# --------------------------------------------------------------------------- the gate

SHIPPED_GATE = {"schema": "grok_catalog_gate.v1", "attested": False, "ruleset_scope": None,
                "ruleset_id": None, "workflow_ref": None, "attested_at": None}
ATTESTED_GATE = {"schema": "grok_catalog_gate.v1", "attested": True,
                 "ruleset_scope": "organization", "ruleset_id": 4242,
                 "workflow_ref": "refs/heads/main", "attested_at": "2026-11-21T12:00:00Z"}


def test_ec_grokroll_4_the_shipped_gate_is_well_formed_and_unattested():
    assert json.loads((PACKAGE_DATA / rc.GATE_NAME).read_text()) == SHIPPED_GATE
    gate = rc.load_gate()
    assert gate is not None and gate.attested is False
    assert rc.load_gate(PACKAGE_DATA) == gate
    assert rc.parse_gate(encode(ATTESTED_GATE)).ruleset_id == 4242


GATE_REFUSALS = [
    ("missing key", lambda gate: gate.pop("attested_at")),
    ("unknown key", lambda gate: gate.update(note="x")),
    ("wrong schema", lambda gate: gate.update(schema="grok_catalog_gate.v2")),
    ("attested a string", lambda gate: gate.update(attested="false")),
    ("attested a number", lambda gate: gate.update(attested=0)),
    *[(f"unattested with {key}", (lambda key: lambda gate: gate.update({key: value}))(key))
      for key, value in (("ruleset_scope", "organization"), ("ruleset_id", 1),
                         ("workflow_ref", "refs/heads/main"),
                         ("attested_at", "2026-11-21T12:00:00Z"))],
]
ATTESTED_REFUSALS = [
    *[(f"attested missing {key}", (lambda key: lambda gate: gate.update({key: None}))(key))
      for key in ("ruleset_scope", "ruleset_id", "workflow_ref", "attested_at")],
    ("repository scope", lambda gate: gate.update(ruleset_scope="repository")),
    ("ruleset id zero", lambda gate: gate.update(ruleset_id=0)),
    ("ruleset id boolean", lambda gate: gate.update(ruleset_id=True)),
    ("ruleset id text", lambda gate: gate.update(ruleset_id="4242")),
    ("short ref", lambda gate: gate.update(workflow_ref="main")),
    ("pull ref", lambda gate: gate.update(workflow_ref="refs/pull/1/head")),
    ("local time", lambda gate: gate.update(attested_at="2026-11-21T12:00:00+01:00")),
]


@pytest.mark.parametrize("base,case,change", [
    *[(SHIPPED_GATE, case, change) for case, change in GATE_REFUSALS],
    *[(ATTESTED_GATE, case, change) for case, change in ATTESTED_REFUSALS],
], ids=[case for case, _change in (*GATE_REFUSALS, *ATTESTED_REFUSALS)])
def test_ec_grokroll_4_each_malformed_gate_shape_refuses(base, case, change):
    gate = copy.deepcopy(base)
    change(gate)
    with pytest.raises(rc.CatalogRefused):
        rc.parse_gate(encode(gate))
    assert rc.parse_gate(encode(base))  # the base itself is well formed


def test_a_gate_with_a_duplicate_key_or_bad_json_refuses():
    with pytest.raises(rc.CatalogRefused):
        rc.parse_gate(json.dumps(SHIPPED_GATE)[:-1].encode() + b', "attested": true}')
    with pytest.raises(rc.CatalogRefused):
        rc.parse_gate(b"{")


# ------------------------------------------------------------------ the signature check

def test_ec_grokroll_4_the_real_vector_verifies_under_the_pinned_key():
    assert set(rc.REGISTRY_KEYS) == {KEYID}
    assert rc.verify_entry_signature(SIGNED) is True


@pytest.mark.parametrize("field,index", [("tarball_integrity", 20), ("version", 5),
                                         ("package", 3), ("registry_signature", 12)])
def test_ec_grokroll_4_one_changed_byte_fails_the_vector(field, index):
    changed = dict(SIGNED)
    value = changed[field]
    replacement = "A" if value[index] != "A" else "B"
    changed[field] = value[:index] + replacement + value[index + 1:]
    assert rc.verify_entry_signature(changed) is False


def test_ec_grokroll_4_a_key_id_the_constant_lacks_is_unknown():
    assert rc.verify_entry_signature(dict(SIGNED, registry_keyid="SHA256:" + "B" * 43)) is False
    assert rc.verify_entry_signature(dict(SIGNED, registry_keyid=None)) is False


def test_the_signature_check_names_the_missing_extra(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "cryptography" or name.startswith("cryptography."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    for name in [name for name in sys.modules if name.startswith("cryptography")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(rc.CatalogDependencyMissing) as missing:
        rc.verify_entry_signature(SIGNED)
    assert missing.value.code == "grok_catalog_dependency_missing"


# --------------------------------------------------------------------- the tree check

def _tree(tmp_path, *, gate=None, releases=None, surfaces=None) -> Path:
    tree = tmp_path / "data"
    tree.mkdir(parents=True)
    for name in (rc.GATE_NAME, rc.RELEASES_NAME, rc.SURFACES_NAME):
        shutil.copyfile(PACKAGE_DATA / name, tree / name)
    for name, value in ((rc.GATE_NAME, gate), (rc.RELEASES_NAME, releases),
                        (rc.SURFACES_NAME, surfaces)):
        if value is not None:
            (tree / name).write_bytes(value if isinstance(value, bytes) else encode(value))
    return tree


def _surface(binary_sha256: str, version: str = "grok 1.0.89 (28be5bb1bf65)") -> dict:
    return {"binary_sha256": binary_sha256, "version": version,
            "version_sha256": "1" * 64, "help_sha256": "2" * 64, "model": "grok-4.7",
            "effort": "high", "context": gts.GROK_SEAT_CONTEXT, "context_digest": "3" * 64,
            "measured_at": "2026-11-20T12:00:00Z", "routes": []}


def _surfaces(*surfaces) -> dict:
    return {"schema": gts.CATALOG_SCHEMA, "revoked": [], "surfaces": list(surfaces)}


def test_ec_grokroll_4_check_tree_holds_on_the_shipped_package_data(tmp_path):
    assert rc.check_tree() == rc.TreeCheck(True)
    assert rc.check_tree(PACKAGE_DATA) == rc.TreeCheck(True)
    assert rc.check_tree(_tree(tmp_path)) == rc.TreeCheck(True)
    assert rc.repository_data_dir("/x") == Path("/x") / rc.DATA_RELATIVE


def test_ec_grokroll_4_an_attested_tree_with_parity_passes(tmp_path):
    tree = _tree(tmp_path, gate=ATTESTED_GATE, releases=document([SIGNED]),
                 surfaces=_surfaces(_surface(SIGNED["binary_sha256"])))
    assert rc.check_tree(tree) == rc.TreeCheck(True)


@pytest.mark.parametrize("case,step,code", [
    ("gate malformed", 1, "grok_catalog_gate_invalid"),
    ("gate missing", 1, "grok_catalog_gate_invalid"),
    ("gate a link", 1, "grok_catalog_gate_invalid"),
    ("catalog unloadable", 2, "grok_catalog_invalid"),
    ("catalog over the bound", 2, "grok_catalog_too_many_releases"),
    ("unattested catalog not empty", 3, "grok_catalog_unattested_not_empty"),
    ("stored signature fails", 4, "grok_release_unverified"),
    ("surface lacking a member", 5, "grok_surface_without_member"),
    ("surface version differs", 5, "grok_surface_without_member"),
    ("surface catalog corrupt", 5, "grok_surface_catalog_invalid"),
])
def test_ec_grokroll_4_each_check_tree_step_fails_alone(tmp_path, case, step, code):
    bad_signature = dict(SIGNED, registry_signature=SIGNED["registry_signature"][:-8] + "AAAAAA==")
    trees = {
        "gate malformed": dict(gate=dict(SHIPPED_GATE, ruleset_id=7)),
        "gate missing": {},
        "gate a link": {},
        "catalog unloadable": dict(releases=b'{"schema": '),
        "catalog over the bound": dict(gate=ATTESTED_GATE, releases=document(
            entry(version) for version in versions(25))),
        "unattested catalog not empty": dict(releases=document([SIGNED])),
        "stored signature fails": dict(gate=ATTESTED_GATE, releases=document([bad_signature])),
        "surface lacking a member": dict(gate=ATTESTED_GATE, releases=document([SIGNED]),
                                         surfaces=_surfaces(_surface("4" * 64))),
        "surface version differs": dict(gate=ATTESTED_GATE, releases=document([SIGNED]),
                                        surfaces=_surfaces(_surface(SIGNED["binary_sha256"],
                                                                    "grok 1.0.90 (aaaa)"))),
        "surface catalog corrupt": dict(gate=ATTESTED_GATE, releases=document([SIGNED]),
                                        surfaces=b"{"),
    }
    tree = _tree(tmp_path, **trees[case])
    if case == "gate missing":
        (tree / rc.GATE_NAME).unlink()
    if case == "gate a link":
        (tree / rc.GATE_NAME).rename(tree / "real.json")
        (tree / rc.GATE_NAME).symlink_to(tree / "real.json")
    assert rc.check_tree(tree) == rc.TreeCheck(False, step, code)


def test_ec_grokroll_4_a_gate_only_flip_fails_while_a_surface_lacks_a_member(tmp_path):
    """The unattested tree passes with a surface no member names (``release: unknown``);
    flipping only the gate to attested fails step 5 on that same tree."""
    surfaces = _surfaces(_surface("4" * 64))
    assert rc.check_tree(_tree(tmp_path / "before", surfaces=surfaces)).passed
    assert rc.check_tree(_tree(tmp_path / "after", gate=ATTESTED_GATE, surfaces=surfaces)) == \
        rc.TreeCheck(False, 5, "grok_surface_without_member")


def test_the_version_token_is_the_single_triple():
    assert rc.surface_version_token("grok 1.0.89 (28be5bb1bf65)") == "1.0.89"
    assert rc.surface_version_token("grok 1.0.89 built on 1.0.88") is None
    assert rc.surface_version_token("grok") is None
    assert rc.surface_version_token("1.0.89.1") is None
