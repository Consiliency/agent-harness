"""Typed evidence for the grok measured-build query (GROKROLL §3.1, §3.2; lane SL-0).

Contract: ``plans/artifacts/grokroll-v1-contract.md``. Every source is read into ``ok``,
``absent`` or ``invalid``, so a corrupt record, register or receipt is never reported as
absent or as measured. Three conformance tests hold the typed readers to the launch-path
oracles. Each oracle's domain is scoped where the query is deliberately stricter; the
divergences are named in the tests that assert them:

- conformance 1 (``frozen_surface``) leaves revoked digests out: the oracle returns
  nothing for them, and the query applies revocation at the build level instead;
- conformance 2 (``_read_grok_receipt``) leaves files over 16384 bytes out of the "ok
  exactly when" direction: the oracle reads 16385 bytes and may decode one;
- conformance 3 (``grok_tool_gate``) has two intended differences: a frozen route is
  ``usable`` from the record alone, and a listing receipt beside an ``invalid`` frozen
  result (a corrupt record, register or catalog) is ``invalid``, where the gate, which
  reads no host record, admits it.

No test runs grok, opens a socket or contacts the vendor; the binary is a stand-in.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime.grok_roll import evidence as ev
from phase_loop_runtime.grok_roll import status as st

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "grok_1_0_89"
VERSION = (FIXTURES / "version.out").read_bytes()
HELP = (FIXTURES / "help.out").read_bytes()
#: A stand-in for the ``grok-review`` allow-list digest, so the context digest is fixed.
ALLOWLIST = "a" * 64
ROUTES = gts.MEASURED_ROUTES
GRANT, RESERVATION = "fixture-grant", "0001-" + "0" * 16


# ---------------------------------------------------------------------------- fixtures

@pytest.fixture
def seat(tmp_path, monkeypatch):
    """A grok stand-in binary on the provider search path, an empty private record root
    location (not created) and a fixed running context digest."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "grok"
    binary.write_bytes(b"\x7fELF grok 1.0.89 stand-in, never executed\n")
    binary.chmod(0o755)
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bin_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setattr(gts, "egress_allowlist_digest", lambda: ALLOWLIST)
    from phase_loop_runtime import president_adapter as pa
    return SimpleNamespace(binary=binary, digest=sha256(binary.read_bytes()).hexdigest(),
                           env={"PATH": f"{bin_dir}:/usr/bin:/bin"}, root=pa.private_record_root(),
                           bin=bin_dir, tmp=tmp_path)


def forms() -> dict[str, list[str]]:
    return st._forms()


def argv_digest(route: str) -> str:
    return pi._grok_argv_digest(forms()[route])


def ensure_root(seat) -> Path:
    seat.root.mkdir(parents=True, exist_ok=True)
    seat.root.chmod(0o700)
    return seat.root


def put(seat, name: str, data: bytes | dict, mode: int = 0o600) -> Path:
    """A file in the record root, written as given (bypassing the record writer)."""
    root = ensure_root(seat)
    path = root / name
    if path.exists() or path.is_symlink():
        path.unlink()
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    path.chmod(mode)
    return path


def tools_for(route: str) -> list[str]:
    form = forms()[route]
    return sorted(pi._grok_allowed_tools(form)) if "--tools" in form else ["read_file"]


def route_entry(route: str, tools: list[str] | None = None) -> dict:
    return {"route": route, "argv_digest": argv_digest(route),
            "tools": tools_for(route) if tools is None else tools,
            "definitions_sha256": sha256(route.encode()).hexdigest()}


def surface(digest: str, routes=ROUTES, *, refused=(), **overrides) -> dict:
    value = {
        "binary_sha256": digest, "version": VERSION.decode().rstrip("\n"),
        "version_sha256": sha256(VERSION).hexdigest(), "help_sha256": sha256(HELP).hexdigest(),
        "model": gts.MEASUREMENT_MODEL, "effort": gts.MEASUREMENT_EFFORT,
        "context": gts.GROK_SEAT_CONTEXT, "context_digest": gts.context_digest(),
        "measured_at": "2026-11-20T12:00:00Z",
        "routes": [route_entry(route, ["bash_exec", "read_file"] if route in refused else None)
                   for route in routes],
    }
    value.update(overrides)
    return value


def catalog(monkeypatch, surfaces=(), revoked=(), raw: bytes | None = None) -> None:
    document = {"schema": gts.CATALOG_SCHEMA, "revoked": list(revoked), "surfaces": list(surfaces)}
    data = raw if raw is not None else json.dumps(document).encode()
    monkeypatch.setattr(gts, "_catalog_bytes", lambda: data)


def host_digest() -> str:
    from phase_loop_runtime import seat_window

    return seat_window._host_digest()


def publish(seat, value: dict, *, register: str = "current", host: str | None = None) -> None:
    """The host-local record for ``value`` and its attempt register: ``current`` (as
    ``--aggregate`` leaves it), ``superseded`` (a newer attempt), ``unpublished``,
    ``missing`` or ``invalid``."""
    digest = value["binary_sha256"]
    put(seat, gts.host_record_name(digest), {"schema": gts.HOST_RECORD_SCHEMA,
                                             "host_digest": host or host_digest(),
                                             "surface": value})
    name = gts.attempts_name(digest)
    if register == "missing":
        (seat.root / name).unlink(missing_ok=True)
        return
    if register == "invalid":
        put(seat, name, b'{"schema": "grok_tool_surface_attempts.v1"')
        return
    document = {"schema": gts.ATTEMPTS_SCHEMA, "binary_sha256": digest,
                "host_digest": host_digest(), "attempts": {}, "published": {}}
    for route in value["routes"]:
        document["attempts"][route["argv_digest"]] = {
            "route": route["route"], "grant": GRANT, "reservation": RESERVATION,
            "at": "2026-11-20T12:00:00Z"}
        if register != "unpublished":
            document["published"][route["argv_digest"]] = {
                "grant": GRANT, "reservation": RESERVATION,
                "surface_digest": gts.surface_digest(value, route)}
        if register == "superseded":
            document["attempts"][route["argv_digest"]]["reservation"] = "0002-" + "1" * 16
    put(seat, name, document)


def listing_receipt(digest: str, route: str, **overrides) -> dict:
    value = {"schema": "tool_probe.v1", "binary_digest": digest,
             "argv_digest": argv_digest(route), "passed": True, "public_code": None,
             "tools": tools_for(route), "version_digest": sha256(VERSION).hexdigest(),
             "basis": "list_tools"}
    value.update(overrides)
    return {key: item for key, item in value.items() if item is not _DROP}


def frozen_receipt(digest: str, route: str, record: dict, source: str = "host_local",
                   **overrides) -> dict:
    entry = next(item for item in record["routes"] if item["route"] == route)
    value = listing_receipt(digest, route, basis="frozen_measurement",
                            tools=list(entry["tools"]),
                            version_digest=record["version_sha256"],
                            surface_digest=gts.surface_digest(record, entry),
                            surface_source=source, context=gts.GROK_SEAT_CONTEXT,
                            context_digest=record["context_digest"])
    value.update(overrides)
    return {key: item for key, item in value.items() if item is not _DROP}


_DROP = object()


def write_receipt(seat, digest: str, route: str, document: dict | bytes, mode: int = 0o600) -> Path:
    return put(seat, ev.receipt_name(digest, argv_digest(route)), document, mode)


def sources(**kwargs) -> ev.Sources:
    return ev.Sources(context_digest=gts.context_digest(), forms=forms(), **kwargs)


def evidence_of(digest: str, route: str = "review") -> ev.RouteEvidence:
    with sources() as found:
        return ev.route_evidence(found, digest, route)


# --------------------------------------------------------------------- typed reads

def test_ec_grokroll_1_the_catalogs_are_ok_or_invalid(seat, monkeypatch):
    assert ev.surface_catalog().result == ev.OK and ev.release_catalog().result == ev.OK
    catalog(monkeypatch, raw=b"{")
    assert ev.surface_catalog() == ev.Read(ev.INVALID)
    from phase_loop_runtime.grok_roll import catalog as rc

    monkeypatch.setattr(rc, "_read_package_data", lambda name, limit: b'{"schema": 1}')
    assert ev.release_catalog() == ev.Read(ev.INVALID)


def test_the_record_directory_states(seat):
    assert ev.open_record_directory(seat.root) == (ev.ABSENT, None)
    ensure_root(seat).chmod(0o755)
    assert ev.open_record_directory(seat.root) == (ev.INVALID, None)
    seat.root.chmod(0o700)
    result, descriptor = ev.open_record_directory(seat.root)
    assert result == ev.OK
    os.close(descriptor)
    seat.root.rename(seat.tmp / "elsewhere")
    seat.root.symlink_to(seat.tmp / "elsewhere")
    assert ev.open_record_directory(seat.root) == (ev.INVALID, None)


def _host_bytes(seat, **overrides) -> dict:
    document = {"schema": gts.HOST_RECORD_SCHEMA, "host_digest": host_digest(),
                "surface": surface(seat.digest)}
    document.update(overrides)
    return document


def _register_bytes(seat, **overrides) -> dict:
    document = {"schema": gts.ATTEMPTS_SCHEMA, "binary_sha256": seat.digest,
                "host_digest": host_digest(), "attempts": {}, "published": {}}
    document.update(overrides)
    return document


SOURCE_NAMES = {
    "record": lambda seat: gts.host_record_name(seat.digest),
    "register": lambda seat: gts.attempts_name(seat.digest),
    "receipt": lambda seat: ev.receipt_name(seat.digest, argv_digest("review")),
}
VALID = {
    "record": lambda seat: _host_bytes(seat),
    "register": lambda seat: _register_bytes(seat),
    "receipt": lambda seat: listing_receipt(seat.digest, "review"),
}
LIMITS = {"record": gts.HOST_RECORD_MAX_BYTES, "register": 1024 * 1024, "receipt": 16384}


def _typed(source: str, seat) -> ev.Read:
    result, directory = ev.open_record_directory(seat.root)
    if directory is None:
        return ev.Read(result)
    try:
        if source == "record":
            return ev.host_record(directory, seat.digest)
        if source == "register":
            return ev.attempt_register(directory, seat.digest)
        return ev.receipt(directory, seat.digest, argv_digest("review"))
    finally:
        os.close(directory)


class _DeniedOpen:
    def __init__(self, name: str, real) -> None:
        self.name, self.real = name, real

    def __call__(self, path, flags, *args, **kwargs):
        if os.fspath(path) == self.name:
            raise PermissionError(13, "denied")
        return self.real(path, flags, *args, **kwargs)


def _foreign_owner(monkeypatch, path: Path) -> None:
    """``fstat`` of the descriptor open on ``path`` reports another owner."""
    real = os.fstat
    target = os.path.realpath(path)

    def fstat(descriptor):
        info = real(descriptor)
        try:
            opened = os.readlink(f"/proc/self/fd/{descriptor}")
        except OSError:
            return info
        if opened == target:
            values = list(info)
            values[4] = info.st_uid + 1
            return os.stat_result(values)
        return info
    monkeypatch.setattr(os, "fstat", fstat)


@pytest.mark.parametrize("source", sorted(SOURCE_NAMES))
@pytest.mark.parametrize("case", ["ok", "missing file", "missing directory", "denied read",
                                  "wrong owner", "wrong directory mode", "wrong file mode",
                                  "a link", "a FIFO", "over-size", "bad JSON"])
def test_ec_grokroll_1_typed_reads_per_source(seat, monkeypatch, source, case):
    name = SOURCE_NAMES[source](seat)
    if case != "missing directory":
        put(seat, name, VALID[source](seat))
    path = seat.root / name
    if case == "missing file":
        path.unlink()
    elif case == "denied read":
        monkeypatch.setattr(os, "open", _DeniedOpen(name, os.open))
    elif case == "wrong owner":
        _foreign_owner(monkeypatch, path)
    elif case == "wrong directory mode":
        seat.root.chmod(0o750)
    elif case == "wrong file mode":
        path.chmod(0o640)
    elif case == "a link":
        path.rename(seat.root / "target.json")
        path.symlink_to(seat.root / "target.json")
    elif case == "a FIFO":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif case == "over-size":
        body = json.dumps(VALID[source](seat))
        put(seat, name, (body + " " * (LIMITS[source] + 1 - len(body))).encode())
    elif case == "bad JSON":
        put(seat, name, b'{"schema": ')
    expected = {"ok": ev.OK, "missing file": ev.ABSENT, "missing directory": ev.ABSENT}.get(
        case, ev.INVALID)
    assert _typed(source, seat).result == expected


@pytest.mark.parametrize("source,change", [
    ("record", lambda seat: _host_bytes(seat, schema="grok_tool_surface_measurement.v2")),
    ("record", lambda seat: dict(_host_bytes(seat), note="x")),
    ("record", lambda seat: _host_bytes(seat, host_digest="f" * 64)),
    ("record", lambda seat: _host_bytes(seat, surface=surface("e" * 64))),
    ("record", lambda seat: _host_bytes(seat, surface=dict(surface(seat.digest), extra=1))),
    ("register", lambda seat: _register_bytes(seat, schema="grok_tool_surface_attempts.v2")),
    ("register", lambda seat: dict(_register_bytes(seat), note="x")),
    ("register", lambda seat: _register_bytes(seat, host_digest="f" * 64)),
    ("register", lambda seat: _register_bytes(seat, binary_sha256="e" * 64)),
    ("register", lambda seat: _register_bytes(seat, attempts={"a" * 64: {"route": "review"}})),
], ids=["record schema", "record unknown key", "record another host", "record another digest",
        "record surface unknown key", "register schema", "register unknown key",
        "register another host", "register another digest", "register entry shape"])
def test_ec_grokroll_1_content_checks_make_a_source_invalid(seat, source, change):
    put(seat, SOURCE_NAMES[source](seat), change(seat))
    assert _typed(source, seat).result == ev.INVALID


# ---------------------------------------------------------------- the frozen result

def _frozen(seat, digest, route="review") -> ev.Frozen:
    with sources() as found:
        return ev.frozen_result(found, digest, forms()[route])


@pytest.mark.parametrize("register,expected", [("current", "usable"), ("superseded", "withdrawn"),
                                                ("unpublished", "withdrawn"),
                                                ("missing", "withdrawn"), ("invalid", "invalid")])
def test_ec_grokroll_1_the_attempt_register_decides_a_host_local_route(seat, register, expected):
    publish(seat, surface(seat.digest), register=register)
    frozen = _frozen(seat, seat.digest)
    assert frozen.result == expected
    assert (frozen.source == "host_local") is (expected != "invalid")


def test_ec_grokroll_1_a_catalog_route_decides_alone_beside_a_corrupt_record(seat, monkeypatch):
    catalog(monkeypatch, [surface(seat.digest)])
    put(seat, gts.host_record_name(seat.digest), b"{ corrupt")
    put(seat, gts.attempts_name(seat.digest), b"{ corrupt")
    frozen = _frozen(seat, seat.digest)
    assert (frozen.result, frozen.source) == ("usable", "catalog")
    assert gts.frozen_surface(seat.digest, argv_digest("review")).source == "catalog"


def test_a_frozen_route_is_refused_or_stale_by_its_own_fields(seat, monkeypatch):
    catalog(monkeypatch, [surface(seat.digest, refused=("review",))])
    assert _frozen(seat, seat.digest).result == "refused"
    catalog(monkeypatch, [surface(seat.digest, context_digest="c" * 64)])
    assert _frozen(seat, seat.digest).result == "stale"
    catalog(monkeypatch, raw=b"{")
    assert _frozen(seat, seat.digest).result == "invalid"
    catalog(monkeypatch)
    assert _frozen(seat, seat.digest).result == "none"


def _scenario(seat, monkeypatch, name: str) -> None:
    """One conformance-1 world. None of them revokes the digest (the oracle returns
    nothing for a revoked digest; the query handles revocation at the build level)."""
    other = surface(seat.digest, context_digest="d" * 64)
    worlds = {
        "nothing": lambda: None,
        "catalog current": lambda: catalog(monkeypatch, [surface(seat.digest)]),
        "catalog stale": lambda: catalog(monkeypatch, [other]),
        "catalog refused": lambda: catalog(monkeypatch, [surface(seat.digest, refused=ROUTES)]),
        "catalog one route": lambda: catalog(monkeypatch, [surface(seat.digest, ("sealed",))]),
        "catalog corrupt": lambda: (catalog(monkeypatch, raw=b"{"),
                                    publish(seat, surface(seat.digest))),
        "catalog over a host record": lambda: (catalog(monkeypatch, [surface(seat.digest)]),
                                               publish(seat, other)),
        "catalog over a corrupt record": lambda: (
            catalog(monkeypatch, [surface(seat.digest)]),
            put(seat, gts.host_record_name(seat.digest), b"{")),
        "host current": lambda: publish(seat, surface(seat.digest)),
        "host stale": lambda: publish(seat, other),
        "host refused": lambda: publish(seat, surface(seat.digest, refused=ROUTES)),
        "host superseded": lambda: publish(seat, surface(seat.digest), register="superseded"),
        "host unpublished": lambda: publish(seat, surface(seat.digest), register="unpublished"),
        "host register missing": lambda: publish(seat, surface(seat.digest), register="missing"),
        "host register invalid": lambda: publish(seat, surface(seat.digest), register="invalid"),
        "host record corrupt": lambda: put(seat, gts.host_record_name(seat.digest), b"{"),
        "host record another host": lambda: publish(seat, surface(seat.digest), host="f" * 64),
        "host directory wrong mode": lambda: (publish(seat, surface(seat.digest)),
                                              seat.root.chmod(0o755)),
    }
    worlds[name]()


CONFORMANCE_1 = ["nothing", "catalog current", "catalog stale", "catalog refused",
                 "catalog one route", "catalog corrupt", "catalog over a host record",
                 "catalog over a corrupt record", "host current", "host stale", "host refused",
                 "host superseded", "host unpublished", "host register missing",
                 "host register invalid", "host record corrupt", "host record another host",
                 "host directory wrong mode"]


#: The worlds where the oracle returns a record (for "catalog one route", only on sealed).
ORACLE_RECORD = {"catalog current", "catalog stale", "catalog refused", "catalog one route",
                 "catalog over a host record", "catalog over a corrupt record", "host current",
                 "host stale", "host refused"}


@pytest.mark.parametrize("world", CONFORMANCE_1)
def test_ec_grokroll_1_conformance_1_frozen_resolution(seat, monkeypatch, world):
    """Oracle ``frozen_surface``: a record exactly when the frozen result is ``usable``,
    ``refused`` or ``stale``, with the same source and surface digest."""
    _scenario(seat, monkeypatch, world)
    for route in ROUTES:
        oracle = gts.frozen_surface(seat.digest, argv_digest(route))
        frozen = _frozen(seat, seat.digest, route)
        assert (oracle is not None) is (world in ORACLE_RECORD and (
            world != "catalog one route" or route == "sealed")), (world, route)
        if oracle is None:
            assert frozen.result in ("withdrawn", "none", "invalid"), (world, route, frozen)
        else:
            assert frozen.result in ("usable", "refused", "stale"), (world, route, frozen)
            assert (frozen.source, frozen.surface_digest) == (oracle.source, oracle.surface_digest)


def test_conformance_1_scopes_out_revoked_digests(seat, monkeypatch):
    """Named divergence: the oracle returns nothing for a revoked digest; the frozen result
    still reads the route, and the build state applies revocation ahead of it."""
    catalog(monkeypatch, [], revoked=[seat.digest])
    publish(seat, surface(seat.digest))
    assert gts.frozen_surface(seat.digest, argv_digest("review")) is None
    assert _frozen(seat, seat.digest).result == "usable"
    with sources() as found:
        build = ev.evaluate(found, seat.digest, ev.REQUIRED_ROUTES)
    assert build.state == "revoked" and not build.measured


# -------------------------------------------------------------- receipts: conformance 2

def _oracle_receipt(seat, route="review"):
    try:
        return "content", pi._read_grok_receipt(forms()[route], seat.env)
    except Exception:  # noqa: BLE001 - the oracle raises for a missing file or directory
        return "raised", None


RECEIPT_CASES = ["listing", "legacy", "failing", "missing file", "missing directory",
                 "bad JSON", "wrong file mode", "wrong directory mode", "a link", "a FIFO",
                 "denied read", "exactly 16384 bytes", "a JSON list", "duplicate keys"]


@pytest.mark.parametrize("case", RECEIPT_CASES)
def test_ec_grokroll_1_conformance_2_receipt_reading(seat, monkeypatch, case):
    """Oracle ``_read_grok_receipt``: ``ok`` with equal content exactly when it returns
    content; ``absent`` for a missing file and ``invalid`` otherwise. Descriptor cases
    only: this conformance says nothing about fields."""
    name = ev.receipt_name(seat.digest, argv_digest("review"))
    body = listing_receipt(seat.digest, "review")
    if case != "missing directory":
        put(seat, name, body)
    path = seat.root / name
    if case == "legacy":
        put(seat, name, listing_receipt(seat.digest, "review", basis=_DROP))
    elif case == "failing":
        put(seat, name, listing_receipt(seat.digest, "review", passed=False))
    elif case == "missing file":
        path.unlink()
    elif case == "bad JSON":
        put(seat, name, b"{")
    elif case == "wrong file mode":
        path.chmod(0o644)
    elif case == "wrong directory mode":
        seat.root.chmod(0o711)
    elif case == "a link":
        path.rename(seat.root / "target.json")
        path.symlink_to(seat.root / "target.json")
    elif case == "a FIFO":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif case == "denied read":
        monkeypatch.setattr(os, "open", _DeniedOpen(name, os.open))
    elif case == "exactly 16384 bytes":
        text = json.dumps(body)
        put(seat, name, (text + " " * (16384 - len(text))).encode())
    elif case == "a JSON list":
        put(seat, name, b"[1, 2]")
    elif case == "duplicate keys":
        put(seat, name, b'{"schema": "tool_probe.v1", "schema": "tool_probe.v1"}')
    kind, oracle = _oracle_receipt(seat)
    typed = _typed("receipt", seat)
    if oracle is not None:
        assert typed == ev.Read(ev.OK, oracle[2]), case
    else:
        missing = case in ("missing file", "missing directory")
        assert typed.result == (ev.ABSENT if missing else ev.INVALID), (case, kind)


def test_conformance_2_scopes_out_files_over_16384_bytes(seat):
    """Named divergence: the oracle reads 16385 bytes and decodes a 16385-byte file; the
    typed reader's stricter bound makes it ``invalid``."""
    text = json.dumps(listing_receipt(seat.digest, "review"))
    write_receipt(seat, seat.digest, "review", (text + " " * (16385 - len(text))).encode())
    kind, oracle = _oracle_receipt(seat)
    assert oracle is not None  # the oracle decodes it
    assert _typed("receipt", seat).result == ev.INVALID


# ------------------------------------------------------------- receipts: their classes

def _class(seat, document, route="review") -> str:
    write_receipt(seat, seat.digest, route, document)
    with sources() as found:
        return ev.receipt_class(found.receipt(seat.digest, argv_digest(route)), seat.digest,
                                argv_digest(route), forms()[route])


def test_receipt_classes(seat):
    record = surface(seat.digest)
    assert _class(seat, listing_receipt(seat.digest, "review", basis=_DROP)) == "listing"
    assert _class(seat, listing_receipt(seat.digest, "review")) == "listing"
    assert _class(seat, listing_receipt(seat.digest, "review", passed=False,
                                        public_code="grok_tool_surface_unverified",
                                        tools=_DROP, version_digest=_DROP, basis=_DROP)) == "none"
    assert _class(seat, frozen_receipt(seat.digest, "review", record)) == "frozen_cache"
    with sources() as found:
        assert ev.receipt_class(ev.Read(ev.ABSENT), seat.digest, argv_digest("review"),
                                forms()["review"]) == "none"


@pytest.mark.parametrize("change", [
    {"surface_digest": "x"}, {"context_digest": None}, {"surface_source": "elsewhere"},
    {"context": "grok_seat_context.v2"}, {"surface_digest": _DROP},
], ids=["surface digest", "context digest", "source", "context", "a frozen field missing"])
def test_malformed_frozen_fields_are_invalid(seat, change):
    assert _class(seat, frozen_receipt(seat.digest, "review", surface(seat.digest),
                                       **change)) == "invalid"


@pytest.mark.parametrize("document", [
    lambda seat: listing_receipt(seat.digest, "review", surface_digest="a" * 64),
    lambda seat: listing_receipt(seat.digest, "review", basis=_DROP, context=gts.GROK_SEAT_CONTEXT),
    lambda seat: listing_receipt(seat.digest, "review", basis="help_text"),
    lambda seat: listing_receipt(seat.digest, "review", basis=None),
    lambda seat: listing_receipt(seat.digest, "review", tools=["bash_exec"]),
    lambda seat: listing_receipt(seat.digest, "review", version_digest="nope"),
    lambda seat: listing_receipt(seat.digest, "review", schema="tool_probe.v2"),
    lambda seat: listing_receipt(seat.digest, "review", binary_digest="f" * 64),
    lambda seat: listing_receipt(seat.digest, "review", argv_digest="f" * 64),
    lambda seat: listing_receipt(seat.digest, "review", passed="yes"),
], ids=["listing with a frozen field", "legacy with a frozen field", "unknown basis",
        "null basis", "tools not admitted", "version digest malformed", "wrong schema",
        "another binary", "another form", "passed not a boolean"])
def test_receipts_failing_a_field_check_are_invalid(seat, document):
    assert _class(seat, document(seat)) == "invalid"


# ----------------------------------------------------------- admission: conformance 3

def _gate(seat, route="review") -> tuple[bool, str | None]:
    return pi._grok_gate_with_basis(forms()[route], seat.env)


ADMISSION = {
    "legacy listing": lambda seat, mp: write_receipt(
        seat, seat.digest, "review", listing_receipt(seat.digest, "review", basis=_DROP)),
    "list_tools": lambda seat, mp: write_receipt(
        seat, seat.digest, "review", listing_receipt(seat.digest, "review")),
    "listing with a frozen field": lambda seat, mp: write_receipt(
        seat, seat.digest, "review", listing_receipt(seat.digest, "review",
                                                     surface_source="catalog")),
    "failing": lambda seat, mp: write_receipt(
        seat, seat.digest, "review", listing_receipt(seat.digest, "review", passed=False)),
    "frozen, record current": lambda seat, mp: (
        publish(seat, surface(seat.digest)),
        write_receipt(seat, seat.digest, "review",
                      frozen_receipt(seat.digest, "review", surface(seat.digest)))),
    "frozen, catalog current": lambda seat, mp: (
        catalog(mp, [surface(seat.digest)]),
        write_receipt(seat, seat.digest, "review",
                      frozen_receipt(seat.digest, "review", surface(seat.digest), "catalog"))),
    "frozen, context went stale": lambda seat, mp: (
        publish(seat, surface(seat.digest, context_digest="d" * 64)),
        write_receipt(seat, seat.digest, "review", frozen_receipt(
            seat.digest, "review", surface(seat.digest, context_digest="d" * 64)))),
    "frozen, backing route gone": lambda seat, mp: write_receipt(
        seat, seat.digest, "review", frozen_receipt(seat.digest, "review", surface(seat.digest))),
    "frozen, route withdrawn": lambda seat, mp: (
        publish(seat, surface(seat.digest), register="superseded"),
        write_receipt(seat, seat.digest, "review",
                      frozen_receipt(seat.digest, "review", surface(seat.digest)))),
    "frozen fields malformed": lambda seat, mp: write_receipt(
        seat, seat.digest, "review",
        frozen_receipt(seat.digest, "review", surface(seat.digest), context_digest="x")),
    "unknown basis": lambda seat, mp: write_receipt(
        seat, seat.digest, "review", listing_receipt(seat.digest, "review", basis="help_text")),
    "listing beside a current host record": lambda seat, mp: (
        publish(seat, surface(seat.digest)),
        write_receipt(seat, seat.digest, "review", listing_receipt(seat.digest, "review"))),
    "listing beside a stale catalog route": lambda seat, mp: (
        catalog(mp, [surface(seat.digest, context_digest="d" * 64)]),
        write_receipt(seat, seat.digest, "review", listing_receipt(seat.digest, "review"))),
    "listing beside a withdrawn route": lambda seat, mp: (
        publish(seat, surface(seat.digest), register="superseded"),
        write_receipt(seat, seat.digest, "review", listing_receipt(seat.digest, "review"))),
    "listing beside a refused route": lambda seat, mp: (
        publish(seat, surface(seat.digest, refused=ROUTES)),
        write_receipt(seat, seat.digest, "review", listing_receipt(seat.digest, "review"))),
    "no receipt": lambda seat, mp: None,
}
#: The cases the gate admits.
GATE_ADMITS = {"legacy listing", "list_tools", "frozen, record current", "frozen, catalog current",
               "listing beside a current host record", "listing beside a stale catalog route",
               "listing beside a withdrawn route", "listing beside a refused route"}
#: Intended differences from the gate (GROKROLL §3.1, conformance 3), by name.
FROZEN_WITHOUT_RECEIPT = "a frozen route is usable from the record alone"
LISTING_BESIDE_INVALID = "a listing receipt beside an invalid frozen result is invalid"


@pytest.mark.parametrize("case", sorted(ADMISSION))
def test_ec_grokroll_1_conformance_3_admission(seat, monkeypatch, case):
    """Oracle ``grok_tool_gate`` at its provisional step: whenever it admits a form, the
    route is ``usable`` with the same basis; whenever the route is ``usable`` with basis
    ``list_tools``, the gate admits."""
    ADMISSION[case](seat, monkeypatch)
    admitted, basis = _gate(seat)
    route = evidence_of(seat.digest)
    assert admitted is (case in GATE_ADMITS), case  # the oracle's own answer, pinned
    if admitted:
        assert (route.evidence, route.basis) == ("usable", basis), case
    if (route.evidence, route.basis) == ("usable", "list_tools"):
        assert admitted, case


def test_conformance_3_intended_difference_frozen_without_receipt(seat):
    """Named difference: the gate also needs the receipt ``probe-tools`` writes."""
    publish(seat, surface(seat.digest))
    assert _gate(seat) == (False, None)
    route = evidence_of(seat.digest)
    assert (route.evidence, route.basis, route.source) == (
        "usable", "frozen_measurement", "host_local"), FROZEN_WITHOUT_RECEIPT


@pytest.mark.parametrize("corrupt", ["record", "register", "catalog"])
def test_conformance_3_intended_difference_listing_beside_invalid_evidence(seat, monkeypatch, corrupt):
    """Named divergence: the gate admits a listing receipt without reading catalogs,
    records or registers; the query reports the route ``invalid`` when that receipt sits
    beside a corrupt record, register or catalog (§3.2 step 3, row 1, first match)."""
    if corrupt == "record":
        put(seat, gts.host_record_name(seat.digest), b"{")
    elif corrupt == "register":
        publish(seat, surface(seat.digest), register="invalid")
    else:
        catalog(monkeypatch, raw=b"{")
    write_receipt(seat, seat.digest, "review", listing_receipt(seat.digest, "review"))
    assert _gate(seat) == (True, "list_tools")
    assert evidence_of(seat.digest).evidence == "invalid", LISTING_BESIDE_INVALID


# ------------------------------------------------------------ route evidence: step 3

@pytest.mark.parametrize("case,expected", [
    ("invalid frozen", ("invalid", "none", None)),
    ("invalid receipt", ("invalid", "none", None)),
    ("listing alone", ("usable", "list_tools", "receipt")),
    ("listing beside frozen usable", ("usable", "list_tools", "receipt")),
    ("listing beside frozen refused", ("usable", "list_tools", "receipt")),
    ("listing beside frozen stale", ("usable", "list_tools", "receipt")),
    ("listing beside withdrawn", ("usable", "list_tools", "receipt")),
    ("frozen usable, catalog", ("usable", "frozen_measurement", "catalog")),
    ("frozen usable, host", ("usable", "frozen_measurement", "host_local")),
    ("frozen usable beside a frozen cache", ("usable", "frozen_measurement", "host_local")),
    ("refused", ("refused", "none", None)),
    ("withdrawn", ("withdrawn", "none", None)),
    ("stale", ("stale", "none", None)),
    ("frozen cache, route gone", ("stale", "none", None)),
    ("absent", ("absent", "none", None)),
    ("failing receipt alone", ("absent", "none", None)),
])
def test_ec_grokroll_1_every_route_evidence_row(seat, monkeypatch, case, expected):
    record = surface(seat.digest)
    listing = listing_receipt(seat.digest, "review")
    setups = {
        "invalid frozen": lambda: put(seat, gts.host_record_name(seat.digest), b"{"),
        "invalid receipt": lambda: write_receipt(seat, seat.digest, "review", b"{"),
        "listing alone": lambda: write_receipt(seat, seat.digest, "review", listing),
        "listing beside frozen usable": lambda: (publish(seat, record),
                                                 write_receipt(seat, seat.digest, "review", listing)),
        "listing beside frozen refused": lambda: (
            publish(seat, surface(seat.digest, refused=ROUTES)),
            write_receipt(seat, seat.digest, "review", listing)),
        "listing beside frozen stale": lambda: (
            publish(seat, surface(seat.digest, context_digest="d" * 64)),
            write_receipt(seat, seat.digest, "review", listing)),
        "listing beside withdrawn": lambda: (publish(seat, record, register="superseded"),
                                             write_receipt(seat, seat.digest, "review", listing)),
        "frozen usable, catalog": lambda: catalog(monkeypatch, [record]),
        "frozen usable, host": lambda: publish(seat, record),
        "frozen usable beside a frozen cache": lambda: (
            publish(seat, record),
            write_receipt(seat, seat.digest, "review", frozen_receipt(seat.digest, "review", record))),
        "refused": lambda: publish(seat, surface(seat.digest, refused=ROUTES)),
        "withdrawn": lambda: publish(seat, record, register="superseded"),
        "stale": lambda: publish(seat, surface(seat.digest, context_digest="d" * 64)),
        "frozen cache, route gone": lambda: write_receipt(
            seat, seat.digest, "review", frozen_receipt(seat.digest, "review", record)),
        "absent": lambda: ensure_root(seat),
        "failing receipt alone": lambda: write_receipt(
            seat, seat.digest, "review", listing_receipt(seat.digest, "review", passed=False)),
    }
    setups[case]()
    route = evidence_of(seat.digest)
    assert (route.evidence, route.basis, route.source) == expected
    assert route.evidence in ev.EVIDENCE and route.basis in ev.BASES


# ------------------------------------------------------------------- build states

def _state(seat, required=ev.REQUIRED_ROUTES) -> str:
    with sources() as found:
        return ev.evaluate(found, seat.digest, required).state


@pytest.mark.parametrize("case,required,expected", [
    ("all usable", ROUTES, "measured"),
    ("review usable, others absent", ("review",), "measured"),
    ("one usable, one absent", ("review", "sealed"), "partial"),
    ("one refused", ("review",), "partial"),
    ("one withdrawn", ("review",), "partial"),
    ("stale", ("review",), "stale_context"),
    ("stale and absent", ("review", "sealed"), "stale_context"),
    ("absent", ROUTES, "unmeasured"),
    ("corrupt receipt", ("review",), "invalid"),
    ("corrupt record", ("review",), "invalid"),
    ("invalid register", ("review",), "invalid"),
    ("corrupt catalog", ("review",), "invalid"),
    ("bad record directory", ("review",), "invalid"),
    ("revoked beside a listing receipt", ("review",), "revoked"),
    ("revoked beside a host record", ("review",), "revoked"),
    ("another host's record", ("review",), "invalid"),
    ("help text advertises a listing", ("review",), "unmeasured"),
])
def test_ec_grokroll_1_every_build_state(seat, monkeypatch, case, required, expected):
    record = surface(seat.digest)
    listing = listing_receipt(seat.digest, "review")
    setups = {
        "all usable": lambda: publish(seat, record),
        "review usable, others absent": lambda: publish(seat, surface(seat.digest, ("review",))),
        "one usable, one absent": lambda: publish(seat, surface(seat.digest, ("review",))),
        "one refused": lambda: publish(seat, surface(seat.digest, refused=("review",))),
        "one withdrawn": lambda: publish(seat, record, register="superseded"),
        "stale": lambda: publish(seat, surface(seat.digest, context_digest="d" * 64)),
        "stale and absent": lambda: publish(seat, surface(seat.digest, ("review",),
                                                          context_digest="d" * 64)),
        "absent": lambda: ensure_root(seat),
        "corrupt receipt": lambda: (publish(seat, record),
                                    write_receipt(seat, seat.digest, "review", b"{")),
        "corrupt record": lambda: put(seat, gts.host_record_name(seat.digest), b"{"),
        "invalid register": lambda: publish(seat, record, register="invalid"),
        "corrupt catalog": lambda: catalog(monkeypatch, raw=b"{"),
        "bad record directory": lambda: (ensure_root(seat), seat.root.chmod(0o777)),
        "revoked beside a listing receipt": lambda: (
            catalog(monkeypatch, revoked=[seat.digest]),
            write_receipt(seat, seat.digest, "review", listing)),
        "revoked beside a host record": lambda: (catalog(monkeypatch, revoked=[seat.digest]),
                                                 publish(seat, record)),
        "another host's record": lambda: publish(seat, record, host="f" * 64),
        "help text advertises a listing": lambda: ensure_root(seat),
    }
    if case == "help text advertises a listing":
        seat.binary.write_bytes(b"\x7fELF  --list-tools  List the tools this build offers\n")
        seat.digest = sha256(seat.binary.read_bytes()).hexdigest()
    setups[case]()
    state = _state(seat, required)
    assert state == expected
    assert state in ev.STATES


def test_ec_grokroll_1_an_ordinary_context_change_is_stale_never_invalid(seat):
    publish(seat, surface(seat.digest))
    assert _state(seat) == "measured"
    publish(seat, surface(seat.digest, context_digest="d" * 64))
    assert _state(seat) == "stale_context"


def test_partial_from_a_refused_and_from_a_withdrawn_required_route(seat):
    publish(seat, surface(seat.digest, refused=("sealed",)))
    assert _state(seat, ("review", "sealed")) == "partial"
    publish(seat, surface(seat.digest), register="superseded")
    assert _state(seat, ("review",)) == "partial"
