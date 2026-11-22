"""The window kit's closed supplier table and its dispatch ledger (K-1 contract §4, §9).

A supplier is one module per vendor, named in :data:`SUPPLIERS`. :func:`load` is the only
dynamic import in the kit, and it imports nothing outside the table. The ledger enforces a
row window's launch envelope BEFORE each start: every start inside a window reserves one
unit of a named item, appended and fsynced to the window's ledger file first, so a partial
run keeps its counts and a refused reservation starts nothing.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import importlib
import json
import os
from pathlib import Path
import threading
from types import MappingProxyType, ModuleType
from typing import Callable, Iterator, Mapping

#: IF-K1-2 §4.2: the closed vendor → module table. Parsing ``--vendor`` reads only its keys.
SUPPLIERS: Mapping[str, str] = MappingProxyType({
    "gemini": "seat_window_supply_gemini",
    "codex": "seat_window_supply_codex",
    "claude": "seat_window_supply_claude",
    "grok": "seat_window_supply_grok",
})

#: IF-K1-2 §4.1: every name a supplier module provides.
REQUIRED_NAMES: tuple[str, ...] = (
    "plant_layout", "build_qualification_input", "definition_probe",
    "ContextBinding", "ContainmentInputs", "reduce_containment",
    "arm_watch", "seed_runtime_plants", "host_path_map",
    "launch_command", "credential_mode", "copy_transform",
    "stream_facts", "terminal",
    "scan_secrets", "measure_credential_scope", "refresh_detected",
    "token_endpoint", "bracket_steps", "plugin_forms",
)

#: §5.5: the closed terminal classes ``supplier.terminal(observation)`` returns.
TERMINAL_CLASSES = frozenset({
    "completed", "refused_intended", "auth_refused", "not_ready", "stream_incomplete",
    "jail_failure", "proxy_failure", "timeout", "other_failure",
})
#: §5.1: the credential modes a prepare seam accepts.
CREDENTIAL_MODES = frozenset({"none", "live", "expired"})


def load(vendor: str) -> ModuleType | None:
    """Import the table's supplier for ``vendor``; ``None`` when it is not in the table or
    the module has not landed. Imports only a module named by :data:`SUPPLIERS`."""
    name = SUPPLIERS.get(vendor)
    if name is None:
        return None
    try:
        return importlib.import_module("." + name, "phase_loop_runtime")
    except ModuleNotFoundError as exc:
        if exc.name == f"phase_loop_runtime.{name}":
            return None
        raise


def missing_names(module: ModuleType | None) -> tuple[str, ...]:
    if module is None:
        return REQUIRED_NAMES
    return tuple(name for name in REQUIRED_NAMES if not hasattr(module, name))


def available(vendor: str) -> ModuleType | None:
    """The vendor's landed supplier with every protocol name, else ``None``."""
    module = load(vendor)
    return module if module is not None and not missing_names(module) else None


def load_all() -> dict[str, ModuleType]:
    """§4.3: every table supplier that exists, loaded before any record is classified."""
    loaded = {}
    for vendor in SUPPLIERS:
        module = available(vendor)
        if module is not None:
            loaded[vendor] = module
    return loaded


# --------------------------------------------------------------------------------------
# §9: the launch envelope and its dispatch ledger.
# --------------------------------------------------------------------------------------

#: §9.2 model-capable start items, then ancillary items A1–A7.
MODEL_ITEMS = ("subject", "claude_seat", "fable_president", "codex_seat", "gemini_seat",
               "grok_seat", "agy_first_use")
ANCILLARY_ITEMS = ("auth_probe", "claude_login_proof", "agy_cold_help", "agy_renewal",
                   "gemini_issuer", "codex_admission_gate", "credential_free_subject")
ENVELOPE_ITEMS = (*MODEL_ITEMS, *ANCILLARY_ITEMS)

_SEAT_ITEMS = {"claude": "claude_seat", "codex": "codex_seat", "gemini": "gemini_seat",
               "grok": "grok_seat"}
_SEAT_CAPS = {"claude_seat": 1, "codex_seat": 1, "gemini_seat": 1, "grok_seat": 2}


def required_envelope(vendor: str, *, plugin_forms: int = 0) -> dict[str, int]:
    """§9.2's per-context caps for ``vendor``'s row window (14 model-capable starts for
    Gemini, Codex or Claude, 13 for Grok)."""
    if vendor not in _SEAT_ITEMS:
        raise ValueError("window_vendor_unavailable")
    caps = {"subject": 5, "fable_president": 2, "agy_first_use": 3}
    caps.update({item: cap for item, cap in _SEAT_CAPS.items() if item != _SEAT_ITEMS[vendor]})
    caps.update({"auth_probe": 8, "claude_login_proof": 5 if vendor == "claude" else 1,
                 "agy_cold_help": 1, "agy_renewal": 5 if vendor == "gemini" else 1,
                 "gemini_issuer": 1 if vendor == "gemini" else 0,
                 "codex_admission_gate": 16 if vendor == "codex" else 2,
                 "credential_free_subject": 3 + (plugin_forms if vendor == "gemini" else 0)})
    return {item: caps.get(item, 0) for item in ENVELOPE_ITEMS}


def model_capable_starts(envelope: Mapping[str, int]) -> int:
    return sum(int(envelope.get(item, 0)) for item in MODEL_ITEMS)


def seat_item(leg: str, subject: str) -> str:
    """The ledger item a board leg's starts debit: the subject's own board leg is a subject
    start (its board leg is in its subject count), every other leg its seat item."""
    if leg == subject:
        return "subject"
    item = _SEAT_ITEMS.get(leg)
    if item is None:
        raise WindowRefused("window_unbudgeted_start")
    return item


class WindowRefused(RuntimeError):
    """A typed window refusal; ``code`` is a closed slug and never carries a value."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat()


def _instant(value):
    if value is None:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed if parsed.tzinfo is not None else False


#: Which resolved modes a snapshot entry's exception permits for a seat launch.
_ENTRY_MODES = {None: frozenset({"jailed"}), "open egress": frozenset({"jailed"}),
                "unconfined": frozenset({"unconfined"})}


def route_agrees(route_id: str, entry: Mapping[str, object] | None,
                 actual: Mapping[str, object] | None) -> bool:
    """R6 at launch: the route this start actually resolved (its mode, exception and
    exclusive expiry) agrees with the composition-bound snapshot entry for it."""
    if entry is None or not isinstance(actual, Mapping):
        return False
    if actual.get("exception") != entry.get("exception"):
        return False
    expected, observed = _instant(entry.get("expiry")), _instant(actual.get("expiry"))
    if expected is False or observed is False or expected != observed:
        return False
    if route_id.startswith("president:"):
        # The transport the adapter actually selected must be this entry's route.
        return (actual.get("mode") == "president"
                and actual.get("transport") == route_id.split(":", 2)[-1])
    return actual.get("mode") in _ENTRY_MODES.get(entry.get("exception"), frozenset())


class WindowLedger:
    """One row window's dispatch ledger (``window-ledger-<vendor>-<context>.jsonl``).

    ``reserve`` debits units with no dispatch (a bulk reservation, such as agy first-use);
    ``dispatch`` debits one unit for an actual start, checks its route against the
    potential-route snapshot first, and records the route and exact launch time. Both are
    atomic across threads and fsynced before they return, so a refused reservation writes
    nothing and starts nothing.
    """

    def __init__(self, path: Path, envelope: Mapping[str, int], *,
                 snapshot: Mapping[str, Mapping[str, object]] | None = None,
                 routes: Mapping[str, str | None] | None = None,
                 clock: Callable[[], dt.datetime] | None = None):
        if set(envelope) != set(ENVELOPE_ITEMS) or not all(
                type(value) is int and value >= 0 for value in envelope.values()):
            raise WindowRefused("window_envelope_invalid")
        self.path = Path(path)
        self.envelope = MappingProxyType(dict(envelope))
        self.snapshot = MappingProxyType({key: dict(value)
                                          for key, value in (snapshot or {}).items()})
        self.routes = MappingProxyType(dict(routes or {}))
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.composition: str | None = None
        self.board: object | None = None
        self._lock = threading.Lock()
        self._counts = {item: 0 for item in ENVELOPE_ITEMS}
        self._seq = 0
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600)
        os.close(fd)

    def bind(self, snapshot: Mapping[str, Mapping[str, object]],
             routes: Mapping[str, str | None], *, composition: str | None = None,
             board: object | None = None) -> None:
        """Bind the potential-route snapshot once, after composition and before the first
        credential-bearing dispatch, with the composed board it was written for (``board``
        is that board itself, which the window's board launch reuses)."""
        with self._lock:
            if self.snapshot or self.routes:
                raise WindowRefused("window_contract_bug")
            self.snapshot = MappingProxyType({key: dict(value) for key, value in snapshot.items()})
            self.routes = MappingProxyType(dict(routes))
            self.composition = composition
            self.board = board

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def _append(self, entry: dict) -> None:
        line = (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _debit(self, item: str, units: int) -> None:
        if item not in self._counts:
            raise WindowRefused("window_unbudgeted_start")
        if self._counts[item] + units > self.envelope[item]:
            raise WindowRefused("window_envelope_exceeded")

    def reserve(self, item: str, units: int = 1) -> None:
        """A bulk reservation: debits ``units`` and records no dispatch."""
        if type(units) is not int or units < 1:
            raise WindowRefused("window_envelope_invalid")
        with self._lock:
            self._debit(item, units)
            self._seq += 1
            self._append({"schema": "seat_window_ledger.v1", "seq": self._seq,
                          "op": "reserve", "item": item, "units": units, "route": None,
                          "exception": None, "expiry": None, "launch_time": None,
                          "stage_sha256": None})
            self._counts[item] += units

    def dispatch(self, item: str, *, route: str | None = None,
                 actual: Mapping[str, object] | None = None,
                 stage_sha256: str | None = None, units: int = 1) -> dict:
        """An actual start: R6's route check, then one debited, recorded unit. The route
        this start actually resolved must agree with its snapshot entry, and that
        exception must be unexpired at this launch time; otherwise nothing is debited and
        nothing starts."""
        with self._lock:
            self._debit(item, units)
            route = route if route is not None else self.routes.get(item)
            launch = self._clock()
            exception = expiry = mode = transport = None
            if route is not None:
                entry = self.snapshot.get(route)
                if not route_agrees(route, entry, actual):
                    raise WindowRefused("window_exception_expired")
                exception, expiry = entry.get("exception"), entry.get("expiry")
                mode, transport = actual.get("mode"), actual.get("transport")
                if expiry is not None:
                    try:
                        bound = dt.datetime.fromisoformat(str(expiry))
                    except ValueError as exc:
                        raise WindowRefused("window_exception_expired") from exc
                    if bound.tzinfo is None or not launch < bound:
                        raise WindowRefused("window_exception_expired")
            self._seq += 1
            line = {"schema": "seat_window_ledger.v1", "seq": self._seq, "op": "dispatch",
                    "item": item, "units": units, "route": route, "exception": exception,
                    "expiry": expiry, "launch_time": _iso(launch),
                    "stage_sha256": stage_sha256, "resolved_mode": mode,
                    "resolved_transport": transport}
            self._append(line)
            self._counts[item] += units
            return line

    def start(self, item: str, *, route: str | None = None,
              actual: Mapping[str, object] | None = None) -> dict:
        """A start a call site already debited (a prepaid unit). R6 is checked again at
        the actual start, with no second debit: the route this start resolved must still
        agree with its snapshot entry and its exception must be unexpired at this launch
        time, or the start is refused and nothing is recorded."""
        with self._lock:
            if route is None and isinstance(actual, Mapping):
                route = actual.get("route_id")
            route = route if route is not None else self.routes.get(item)
            launch = self._clock()
            exception = expiry = mode = transport = None
            if route is not None:
                entry = self.snapshot.get(route)
                if not route_agrees(route, entry, actual):
                    raise WindowRefused("window_exception_expired")
                exception, expiry = entry.get("exception"), entry.get("expiry")
                mode, transport = actual.get("mode"), actual.get("transport")
                bound = _instant(expiry)
                if bound is False or (bound is not None and not launch < bound):
                    raise WindowRefused("window_exception_expired")
            self._seq += 1
            line = {"schema": "seat_window_ledger.v1", "seq": self._seq, "op": "start",
                    "item": item, "units": 0, "route": route, "exception": exception,
                    "expiry": expiry, "launch_time": _iso(launch), "stage_sha256": None,
                    "resolved_mode": mode, "resolved_transport": transport}
            self._append(line)
            return line


_LEDGER: contextvars.ContextVar[WindowLedger | None] = contextvars.ContextVar(
    "seat_window_ledger", default=None)


class _Scope:
    __slots__ = ("item", "prepaid", "lock", "route")

    def __init__(self, item: str, prepaid: int, route=None):
        self.item = item
        self.prepaid = prepaid
        self.lock = threading.Lock()
        #: The route this scope's starts actually resolved (``note_route``).
        self.route = route


_SCOPE: contextvars.ContextVar[_Scope | None] = contextvars.ContextVar(
    "seat_window_scope", default=None)
#: Set while ``run_provider`` holds its reservation, so the ``launch_provider`` it reaches
#: does not debit the same start twice.
_BOUNDARY_HELD: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "seat_window_boundary_held", default=False)


def active_ledger() -> WindowLedger | None:
    return _LEDGER.get()


@contextlib.contextmanager
def ledger_scope(ledger: WindowLedger | None) -> Iterator[WindowLedger | None]:
    token = _LEDGER.set(ledger)
    try:
        yield ledger
    finally:
        _LEDGER.reset(token)


@contextlib.contextmanager
def item_scope(item: str, *, prepaid: int = 0) -> Iterator[None]:
    """Name the item the provider boundary debits inside this block. ``prepaid`` starts
    were already debited by the caller; the boundary consumes them without a second debit."""
    outer = _SCOPE.get()
    # A nested scope keeps the route its enclosing scope resolved.
    token = _SCOPE.set(_Scope(item, prepaid, outer.route if outer is not None else None))
    try:
        yield
    finally:
        _SCOPE.reset(token)


@contextlib.contextmanager
def no_scope() -> Iterator[None]:
    token = _SCOPE.set(None)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def note_route(evidence: Mapping[str, object]) -> None:
    """Record the route the current window scope's starts actually resolved, at the
    resolver, before any of them starts. Outside a window it does nothing."""
    scope = _SCOPE.get()
    if scope is not None and _LEDGER.get() is not None:
        scope.route = dict(evidence)


def current_route() -> Mapping[str, object] | None:
    scope = _SCOPE.get()
    return scope.route if scope is not None else None


def call_site_dispatch(item: str, *, route: str | None = None,
                       actual: Mapping[str, object] | None = None,
                       stage_sha256: str | None = None) -> dict | None:
    """A kit call site's reservation (§9.1's table), for a start that may bypass the
    provider boundary, checked against the route the start actually resolved (the
    scope's, unless the call site supplies it). ``None`` outside a window."""
    ledger = _LEDGER.get()
    if ledger is None:
        return None
    return ledger.dispatch(item, route=route, stage_sha256=stage_sha256,
                           actual=actual if actual is not None else current_route())


def _names_provider(argv) -> bool:
    from . import panel_invoker
    return panel_invoker._names_provider(argv)


def provider_start(argv, *, boundary: str = "launch") -> contextlib.AbstractContextManager:
    """§9.1 provider boundary. Outside a window this does nothing. Inside one, a provider
    start debits one unit of the scoped item before it happens (or consumes a prepaid
    unit), and a start with no scoped item is refused ``window_unbudgeted_start``.
    Starts that name no provider (trusted helpers, observers) are not provider starts."""
    ledger = _LEDGER.get()
    if ledger is None or _BOUNDARY_HELD.get() or not _names_provider(argv):
        return contextlib.nullcontext()
    scope = _SCOPE.get()
    if scope is None:
        raise WindowRefused("window_unbudgeted_start")
    with scope.lock:
        if scope.prepaid > 0:
            ledger.start(scope.item, actual=scope.route)  # refuses before it is consumed
            scope.prepaid -= 1
        else:
            ledger.dispatch(scope.item, actual=scope.route)
    if boundary != "run":
        return contextlib.nullcontext()
    token = _BOUNDARY_HELD.set(True)

    @contextlib.contextmanager
    def _held():
        try:
            yield
        finally:
            _BOUNDARY_HELD.reset(token)
    return _held()
