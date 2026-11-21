"""Typed evidence for the measured-build query (GROKROLL §3.1, §3.2).

The launch-path readers fold every failure into absence: ``load_host_record`` returns
``None`` for a missing record and for a corrupt one alike, and ``host_route_current``
returns ``False`` for a withdrawn route and for an unreadable register alike. This module
reads each source itself and returns one of three results:

- ``ok``: read and valid;
- ``absent``: positively absent: ``ENOENT`` inside a directory that passed its checks, or
  the record directory itself does not exist;
- ``invalid``: anything else.

``grok_tool_surface.py`` and ``panel_invoker.py`` are not edited. Their record validators
are reused, and three conformance tests hold these readers to the launch-path oracles
(``frozen_surface``, ``_read_grok_receipt`` and ``grok_tool_gate``), with the intended
differences stated there.

Nothing here writes, creates a directory, opens a socket or launches a process.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .. import grok_tool_surface as gts
from . import catalog as releases

OK, ABSENT, INVALID = "ok", "absent", "invalid"

#: Route ``evidence`` values (§3.2 step 3: seven rows, six values) and the build ``state``
#: values (§3.2).
EVIDENCE = ("invalid", "usable", "refused", "withdrawn", "stale", "absent")
STATES = ("unresolved", "invalid", "revoked", "measured", "partial", "stale_context",
          "unmeasured")
BASES = ("frozen_measurement", "list_tools", "none")
SOURCES = ("catalog", "host_local", "receipt")
REQUIRED_ROUTES = ("review",)
#: The receipt bound, one byte stricter than the gate's read of 16385 (§3.1).
RECEIPT_MAX_BYTES = 16384
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


@dataclass(frozen=True)
class Read:
    """One typed read: ``result`` is ``ok``, ``absent`` or ``invalid``; ``value`` is the
    validated content when ``ok``."""

    result: str
    value: Any = None
    #: A receipt whose JSON repeats a key at any level (its decoded value is the last one,
    #: as the gate decodes it); classified ``invalid`` (GROKROLL E2).
    ambiguous: bool = False


_ABSENT = Read(ABSENT)
_INVALID = Read(INVALID)


def surface_catalog() -> Read:
    """The shipped tool-surface catalog: ``ok`` or ``invalid``. A corrupt catalog hides its
    ``revoked`` list. Read through the query's own package-data reader (no link, regular
    file, non-blocking, bounded), then validated by ``grok_tool_surface.parse_catalog``."""
    try:
        return Read(OK, gts.parse_catalog(
            releases.read_data(releases.SURFACES_NAME, gts.CATALOG_MAX_BYTES)))
    except (OSError, ValueError, TypeError, RecursionError):
        return _INVALID


def release_catalog() -> Read:
    """The shipped release catalog: ``ok`` or ``invalid``."""
    catalog = releases.load_releases()
    return _INVALID if catalog is None else Read(OK, catalog)


def _private_dir(descriptor: int) -> bool:
    info = os.fstat(descriptor)
    return info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700


def open_record_directory(path: str | os.PathLike[str] | None = None) -> tuple[str, int | None]:
    """``(result, descriptor)`` for the private record directory, opened as the gate opens
    it: no final link, ours and 0700. ``absent`` (no descriptor) when it does not exist."""
    if path is None:
        from ..president_adapter import private_record_root

        path = private_record_root()
    try:
        descriptor = os.open(path, _DIR_FLAGS)
    except FileNotFoundError:
        return ABSENT, None
    except OSError:
        return INVALID, None
    try:
        if _private_dir(descriptor):
            return OK, descriptor
    except OSError:
        pass
    os.close(descriptor)
    return INVALID, None


def _walk(path: str | os.PathLike[str]) -> int:
    """``path`` opened component by component from ``/`` with no link anywhere, as
    ``grok_tool_surface`` opens the record root for its attempt register."""
    parts = os.path.abspath(os.fspath(path)).split(os.sep)[1:]
    descriptor = os.open("/", _DIR_FLAGS)
    try:
        for part in parts:
            if not part:
                continue
            child = os.open(part, _DIR_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def host_record(directory: int, digest: str) -> Read:
    """The host-local record for ``digest`` (tool-surface §3.2): a private regular 0600 file
    of ours, no link, bounded, ``grok_tool_surface_measurement.v1``, written for this host,
    for this digest. The value is the record's surface."""
    from ..seat_window import _host_digest

    if not releases.is_digest(digest):
        return _INVALID
    try:
        raw = gts._read_file(directory, gts.host_record_name(digest), gts.HOST_RECORD_MAX_BYTES)
    except FileNotFoundError:
        return _ABSENT
    except (OSError, ValueError):
        return _INVALID
    try:
        document = gts._loads(raw)
        gts._require(type(document) is dict
                     and set(document) == {"schema", "host_digest", "surface"})
        assert isinstance(document, dict)
        gts._require(document["schema"] == gts.HOST_RECORD_SCHEMA)
        gts._require(gts._hex64(document["host_digest"])
                     and document["host_digest"] == _host_digest())
        surface = document["surface"]
        gts._check_surface(surface)
        gts._require(surface["binary_sha256"] == digest)
    except (ValueError, TypeError, RecursionError, AssertionError):
        return _INVALID
    return Read(OK, surface)


def attempt_register(directory: int, digest: str) -> Read:
    """The attempt register ``grok-surface-<digest>.attempts.json``: the same file checks,
    and the structure ``grok_tool_surface._read_register`` requires. The value is a
    :class:`grok_tool_surface.Register`."""
    from ..seat_window import _host_digest

    try:
        document = gts._read_doc(directory, gts.attempts_name(digest))
    except FileNotFoundError:
        return _ABSENT
    except (OSError, ValueError, TypeError, RecursionError):
        return _INVALID
    try:
        gts._require(set(document) == {"schema", "binary_sha256", "host_digest", "attempts",
                                       "published"}
                     and document["schema"] == gts.ATTEMPTS_SCHEMA
                     and document["binary_sha256"] == digest
                     and document["host_digest"] == _host_digest()
                     and type(document["attempts"]) is dict
                     and type(document["published"]) is dict)
        for table, keys in ((document["attempts"], gts._ATTEMPT_KEYS),
                            (document["published"], gts._PUBLISHED_KEYS)):
            for argv_digest, entry in table.items():
                gts._require(gts._hex64(argv_digest) and type(entry) is dict
                             and set(entry) == keys
                             and all(type(value) is str for value in entry.values()))
    except (ValueError, TypeError):
        return _INVALID
    return Read(OK, gts.Register(attempts=document["attempts"], published=document["published"]))


def receipt_name(digest: str, argv_digest: str) -> str:
    return "grok-probe-" + digest + "-" + argv_digest + ".json"


def receipt(directory: int, digest: str, argv_digest: str) -> Read:
    """A ``tool_probe.v1`` receipt, read with the descriptor checks of
    ``panel_invoker._read_grok_receipt`` and decoded as it decodes, with one stricter rule:
    a file over ``RECEIPT_MAX_BYTES`` is ``invalid``. No field is checked here."""
    if not (releases.is_digest(digest) and releases.is_digest(argv_digest)):
        return _INVALID
    try:
        descriptor = os.open(receipt_name(digest, argv_digest), _FILE_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return _ABSENT
    except OSError:
        return _INVALID
    try:
        info = os.fstat(descriptor)
        if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                or not stat.S_ISREG(info.st_mode)):
            return _INVALID
        raw = gts._read_bounded(descriptor, RECEIPT_MAX_BYTES)
    except OSError:
        return _INVALID
    finally:
        os.close(descriptor)
    if len(raw) > RECEIPT_MAX_BYTES:
        return _INVALID
    repeated = []

    def pairs(items):
        keys = [key for key, _value in items]
        if len(keys) != len(set(keys)):
            repeated.append(True)
        return dict(items)

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError):
        return _INVALID
    return Read(OK, value, bool(repeated))


# ---------------------------------------------------------------- route and build states

@dataclass(frozen=True)
class Frozen:
    """A route's frozen result (§3.2 step 1): ``usable``, ``refused``, ``stale``,
    ``withdrawn``, ``none`` or ``invalid``, and the record route it rests on."""

    result: str
    source: str | None = None
    surface: Mapping[str, Any] | None = None
    surface_digest: str | None = None


@dataclass(frozen=True)
class RouteEvidence:
    route: str
    argv_digest: str
    evidence: str
    basis: str
    source: str | None
    surface_digest: str | None
    frozen: Frozen = field(compare=False)
    receipt_class: str = field(compare=False, default="none")

    def as_dict(self) -> dict[str, Any]:
        return {"route": self.route, "argv_digest": self.argv_digest,
                "evidence": self.evidence, "basis": self.basis, "source": self.source,
                "surface_digest": self.surface_digest}


@dataclass(frozen=True)
class Build:
    digest: str | None
    state: str
    routes: tuple[RouteEvidence, ...]
    context_digest: str | None
    measured_at: str | None

    @property
    def measured(self) -> bool:
        return self.state == "measured"


class Sources:
    """Every evidence source the query reads, each read at most once per digest."""

    def __init__(self, *, context_digest: str, forms: Mapping[str, list[str]],
                 record_root: str | os.PathLike[str] | None = None) -> None:
        self.gate = releases.gate_state()
        if record_root is None:
            from ..president_adapter import private_record_root

            record_root = private_record_root()
        self.record_root = record_root
        self.context_digest = context_digest
        self.forms = dict(forms)
        self.surfaces = surface_catalog()
        self.releases = release_catalog()
        self.host_records, self._directory = open_record_directory(record_root)
        self._register_root: str | None = None
        self._records: dict[str, Read] = {}
        self._registers: dict[str, Read] = {}
        self._receipts: dict[tuple[str, str], Read] = {}

    def close(self) -> None:
        if self._directory is not None:
            os.close(self._directory)
            self._directory = None

    def __enter__(self) -> "Sources":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def inputs(self) -> dict[str, str]:
        return {"surface_catalog": self.surfaces.result, "release_catalog": self.releases.result,
                "host_records": self.host_records, "catalog_gate": self.gate}

    @property
    def inputs_invalid(self) -> bool:
        """Decision row 1. The gate state is reported but is not a row-1 input: a gate that
        is missing, malformed or unattested only withholds catalog membership (E1)."""
        return INVALID in (self.surfaces.result, self.releases.result, self.host_records)

    @property
    def members(self):
        """The release catalog as a membership authority: only when it loads and the gate
        reads attested (GROKROLL E1). ``None`` otherwise: no version resolves and no build is
        a ``member`` or a target."""
        if self.releases.result == OK and self.gate == "attested":
            return self.releases.value
        return None

    def record(self, digest: str) -> Read:
        if self.host_records != OK:
            return _ABSENT if self.host_records == ABSENT else _INVALID
        if digest not in self._records:
            assert self._directory is not None
            self._records[digest] = host_record(self._directory, digest)
        return self._records[digest]

    def _register_directory_ok(self) -> bool:
        """The register is read as the launch path reads it: through a walk with no link
        anywhere, to this same directory. A record root the walk cannot reach makes every
        register ``invalid``, where ``host_route_current`` would admit nothing."""
        if self._register_root is None:
            assert self._directory is not None
            try:
                walked = _walk(self.record_root)
            except OSError:
                self._register_root = INVALID
            else:
                try:
                    mine, theirs = os.fstat(self._directory), os.fstat(walked)
                    same = (mine.st_dev, mine.st_ino) == (theirs.st_dev, theirs.st_ino)
                finally:
                    os.close(walked)
                self._register_root = OK if same else INVALID
        return self._register_root == OK

    def register(self, digest: str) -> Read:
        if self.host_records != OK:
            return _ABSENT if self.host_records == ABSENT else _INVALID
        if digest not in self._registers:
            assert self._directory is not None
            self._registers[digest] = (attempt_register(self._directory, digest)
                                       if self._register_directory_ok() else _INVALID)
        return self._registers[digest]

    def receipt(self, digest: str, argv_digest: str) -> Read:
        if self.host_records != OK:
            return _ABSENT if self.host_records == ABSENT else _INVALID
        key = (digest, argv_digest)
        if key not in self._receipts:
            assert self._directory is not None
            self._receipts[key] = receipt(self._directory, digest, argv_digest)
        return self._receipts[key]

    def revoked(self, digest: str) -> bool:
        return self.surfaces.result == OK and digest in self.surfaces.value.revoked


def _admitted(form: list[str], tools: object) -> bool:
    from .. import panel_invoker as panel

    return panel._grok_tools_admitted(form, tools)


def _argv_digest(form: list[str]) -> str:
    from .. import panel_invoker as panel

    return panel._grok_argv_digest(form)


def _classify(sources: Sources, form: list[str], surface: Mapping[str, Any],
              route: Mapping[str, Any], source: str) -> Frozen:
    digest = gts.surface_digest(surface, route)
    if surface["context_digest"] != sources.context_digest:
        result = "stale"
    else:
        result = "usable" if _admitted(form, route["tools"]) else "refused"
    return Frozen(result, source, surface, digest)


def frozen_result(sources: Sources, digest: str, form: list[str]) -> Frozen:
    """§3.2 step 1, following tool-surface §3.2 precedence: a catalog route decides alone;
    otherwise the host record, then the attempt register. Revocation is not applied here:
    it is a build state, and it precedes all evidence."""
    if sources.surfaces.result != OK:
        return Frozen(INVALID)
    argv_digest = _argv_digest(form)
    shipped = sources.surfaces.value.surfaces.get(digest)
    shipped_route = gts._route_for(shipped, argv_digest)
    if shipped is not None and shipped_route is not None:
        return _classify(sources, form, shipped, shipped_route, "catalog")
    record = sources.record(digest)
    if record.result == INVALID:
        return Frozen(INVALID)
    host_route = gts._route_for(record.value, argv_digest) if record.result == OK else None
    if host_route is None:
        return Frozen("none")
    register = sources.register(digest)
    if register.result == INVALID:
        return Frozen(INVALID)
    if register.result == OK:
        published = register.value.published.get(argv_digest)
        latest = register.value.attempts.get(argv_digest)
        current = (published is not None and latest is not None
                   and published["grant"] == latest["grant"]
                   and published["reservation"] == latest["reservation"]
                   and published["surface_digest"] == gts.surface_digest(record.value, host_route))
    else:
        current = False
    if not current:
        return Frozen("withdrawn", "host_local", record.value,
                      gts.surface_digest(record.value, host_route))
    return _classify(sources, form, record.value, host_route, "host_local")


def _sha256_text(value: object) -> bool:
    return releases.is_digest(value)


#: The keys ``panel_invoker.record_tool_probe`` writes: a failed receipt, and a passing one
#: before its optional ``basis`` and, for the frozen basis, ``RECEIPT_FIELDS``.
_FAILED_KEYS = frozenset({"schema", "binary_digest", "argv_digest", "passed", "public_code"})
_PASSED_KEYS = _FAILED_KEYS | {"tools", "version_digest"}


def receipt_class(read: Read, digest: str, argv_digest: str, form: list[str]) -> str:
    """§3.2 step 2: ``invalid``, ``none``, ``listing`` or ``frozen_cache``."""
    if read.result == ABSENT:
        return "none"
    if read.result != OK:
        return INVALID
    record = read.value
    if read.ambiguous:
        return INVALID
    if not (type(record) is dict and record.get("schema") == "tool_probe.v1"
            and record.get("binary_digest") == digest and record.get("argv_digest") == argv_digest
            and type(record.get("passed")) is bool):
        return INVALID
    if record["passed"] is False:
        # A failed receipt is positive absence only in exactly the shape the writer leaves.
        well_formed = (set(record) == _FAILED_KEYS and type(record["public_code"]) is str
                       and bool(record["public_code"]))
        return "none" if well_formed else INVALID
    allowed = _PASSED_KEYS | {"basis"}
    if record.get("basis") == "frozen_measurement":
        allowed |= frozenset(gts.RECEIPT_FIELDS)
    if not (_PASSED_KEYS <= set(record) and set(record) - allowed <= set(gts.RECEIPT_FIELDS)
            and record["public_code"] is None):
        return INVALID  # an unknown key, or a missing one (GROKROLL E2)
    if not (_admitted(form, record.get("tools")) and _sha256_text(record.get("version_digest"))):
        return INVALID
    frozen_fields = [key for key in gts.RECEIPT_FIELDS if key in record]
    if "basis" not in record or record["basis"] == "list_tools":  # a legacy or listing receipt
        return INVALID if frozen_fields else "listing"
    if record["basis"] == "frozen_measurement":
        well_formed = (_sha256_text(record.get("surface_digest"))
                       and _sha256_text(record.get("context_digest"))
                       and record.get("surface_source") in gts.SURFACE_SOURCES
                       and record.get("context") == gts.GROK_SEAT_CONTEXT)
        return "frozen_cache" if well_formed else INVALID
    return INVALID


def route_evidence(sources: Sources, digest: str, route: str) -> RouteEvidence:
    """§3.2 step 3, first match."""
    form = sources.forms[route]
    argv_digest = _argv_digest(form)
    frozen = frozen_result(sources, digest, form)
    klass = receipt_class(sources.receipt(digest, argv_digest), digest, argv_digest, form)

    def made(evidence: str, basis: str = "none", source: str | None = None,
             surface_digest: str | None = None) -> RouteEvidence:
        return RouteEvidence(route, argv_digest, evidence, basis, source, surface_digest,
                             frozen, klass)

    if INVALID in (frozen.result, klass):
        return made(INVALID)
    if klass == "listing":
        return made("usable", "list_tools", "receipt")
    if frozen.result == "usable":
        return made("usable", "frozen_measurement", frozen.source, frozen.surface_digest)
    if frozen.result == "refused":
        return made("refused", surface_digest=frozen.surface_digest)
    if frozen.result == "withdrawn":
        return made("withdrawn")
    if frozen.result == "stale":
        return made("stale", surface_digest=frozen.surface_digest)
    if klass == "frozen_cache":
        return made("stale")  # a receipt whose backing route is gone
    return made("absent")


def build_state(sources: Sources, digest: str | None, routes: Iterable[RouteEvidence],
                required: Iterable[str]) -> str:
    """A build's ``state`` (§3.2), the first that applies."""
    if digest is None:
        return "unresolved"
    required = tuple(required)
    chosen = [route for route in routes if route.route in required]
    if sources.inputs_invalid or any(route.evidence == INVALID for route in chosen):
        return INVALID
    if sources.revoked(digest):
        return "revoked"
    evidence = [route.evidence for route in chosen]
    if all(value == "usable" for value in evidence):
        return "measured"
    if any(value in ("usable", "refused", "withdrawn") for value in evidence):
        return "partial"
    if any(value == "stale" for value in evidence):
        return "stale_context"
    return "unmeasured"


def evaluate(sources: Sources, digest: str | None, required: Iterable[str]) -> Build:
    """The full §3.2 evaluation of one build, register and receipts included."""
    required = tuple(required)
    if digest is None:
        routes = tuple(RouteEvidence(route, _argv_digest(sources.forms[route]), "absent", "none",
                                     None, None, Frozen("none"))
                       for route in gts.MEASURED_ROUTES)
        return Build(None, "unresolved", routes, None, None)
    routes = tuple(route_evidence(sources, digest, route) for route in gts.MEASURED_ROUTES)
    state = build_state(sources, digest, routes, required)
    record = _record_surface(sources, digest)
    return Build(digest, state, routes,
                 None if record is None else record["context_digest"],
                 None if record is None else record["measured_at"])


def _record_surface(sources: Sources, digest: str) -> Mapping[str, Any] | None:
    """The surface record the build's frozen evidence rests on: the catalog's when it has
    one for the digest, else the host-local record when it reads ``ok``."""
    if sources.surfaces.result != OK:
        return None
    shipped = sources.surfaces.value.surfaces.get(digest)
    if shipped is not None:
        return shipped
    record = sources.record(digest)
    return record.value if record.result == OK else None
