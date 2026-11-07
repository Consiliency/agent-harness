"""Board-level seat preflight for pointer briefs (agent-harness#1204).

A *pointer brief* tells the reviewers to open files in the staged exact-head tree instead
of carrying their content inline. The caller declares it (``invoke_board(pointer_brief=True)``,
``advisor-board --pointer-brief``); nothing here guesses it from the brief's text.

Before ANY seat launches, :func:`pointer_brief_preflight` decides for every seat whether its
route gives it file access to the staged tree. A seat without file access gets the typed
notice :data:`POINTER_BRIEF_UNREADABLE`, which is published before launch. The seat still
runs (maintainer ruling, policy (ii)), but its verdict is **not source-grounded**: it never
counts as a passing grounded seat. :func:`counts_as_grounded_vote` is the landing rule and
:func:`uncounted_president_items` the president-input rule. Both mirror the existing D1 rule
for uncounted legs (``agy_qualification``): a non-blocking verdict is not counted, while a
blocking ``DISAGREE`` is kept as a review, so marking a seat never removes an objection.

This module decides policy only. It launches nothing and never changes a seat's route; the
route facts are passed in by the invoker.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .cli_qualification import CLASSES as CLI_ADMISSION_CLASSES

POINTER_BRIEF_UNREADABLE = "seat_pointer_brief_unreadable"

#: The notice's rendered text: (what happens, why, how to fix it). Literals only.
NOTICE_TEXT: Mapping[str, tuple[str, str, str]] = {
    POINTER_BRIEF_UNREADABLE: (
        "seat runs, but its verdict is not counted as source-grounded",
        "the brief points at files in the staged tree and this seat's route gives it no "
        "file access",
        "inline the referenced content into the review bundle, or fill this seat through "
        "a route with file access (e.g. native fill)"),
}

#: The file a stream directory receives before the first seat launches.
PREFLIGHT_FILE = "seat-preflight.json"
PREFLIGHT_SCHEMA = "seat_preflight.v1"


@dataclass(frozen=True)
class SeatPreflightNotice:
    code: str
    seat_key: str
    leg: str
    #: The seat's position on the board. Seat keys are labels, not identities (two
    #: identical seats share one), so a notice is attached by position.
    position: int = -1

    def __post_init__(self) -> None:
        if self.code not in NOTICE_TEXT:
            raise ValueError(f"unknown seat preflight notice {self.code!r}")

    @property
    def what(self) -> str:
        return NOTICE_TEXT[self.code][0]

    @property
    def why(self) -> str:
        return NOTICE_TEXT[self.code][1]

    @property
    def fix(self) -> str:
        return NOTICE_TEXT[self.code][2]

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "seat_key": self.seat_key, "leg": self.leg,
                "what": self.what, "why": self.why, "fix": self.fix}

    def render(self) -> str:
        return f"seat {self.seat_key} ({self.leg}): {self.code}: {self.what} -- {self.why}; fix: {self.fix}"


def seat_has_file_access(leg: str, *, staged_tree: bool, brokered: bool,
                         native_fill: bool, sandbox_usable_by: Callable[..., bool]) -> bool:
    """Does this seat's route let it open files in the staged tree?

    A seat deferred to a native fill is reviewed by the host agent, which has file access.
    Otherwise it needs a staged tree AND a route that can act on it
    (``sandbox_usable_by``, the invoker's own capability rule)."""
    if native_fill:
        return True
    return staged_tree and bool(sandbox_usable_by(leg, brokered=brokered))


def pointer_brief_preflight(
    seats: Iterable[object], *, staged_tree: bool,
    brokered: Callable[[str], bool], native_fill: Callable[[object, str], bool],
    sandbox_usable_by: Callable[..., bool],
) -> tuple[SeatPreflightNotice, ...]:
    """One notice per seat that cannot open the pointer brief's files, in seat order."""
    notices = []
    for position, seat in enumerate(seats):
        leg = (getattr(seat, "harness", None) or "").lower()
        if not seat_has_file_access(leg, staged_tree=staged_tree, brokered=brokered(leg),
                                    native_fill=native_fill(seat, leg),
                                    sandbox_usable_by=sandbox_usable_by):
            notices.append(SeatPreflightNotice(POINTER_BRIEF_UNREADABLE,
                                               str(getattr(seat, "seat_key", "") or leg), leg,
                                               position))
    return tuple(notices)


def write_preflight_record(stream_dir: Path, notices: Sequence[SeatPreflightNotice]) -> Path:
    """Publish the notices to the stream directory before any seat launches."""
    Path(stream_dir).mkdir(parents=True, exist_ok=True)
    path = Path(stream_dir) / PREFLIGHT_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema": PREFLIGHT_SCHEMA, "pointer_brief": True,
                               "notices": [n.as_json() for n in notices]},
                              indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


# --------------------------------------------------------------------------------------
# Policy (ii): a marked seat is not source-grounded and never counts as a passing seat.
# --------------------------------------------------------------------------------------

def leg_record_marks(leg: object) -> dict[str, list[str]]:
    """What a persisted leg record carries so a resume restores the marks (inside the
    record's digest). Empty -- the record is byte-identical -- for an unmarked leg."""
    codes = [n.code for n in leg_notices(leg)]
    return {"seat_preflight": codes} if codes else {}


def notices_from_record(item: Mapping[str, object], position: int
                        ) -> tuple[SeatPreflightNotice, ...]:
    """The marks a persisted leg record carries. Raises ``ValueError`` when malformed."""
    if "seat_preflight" not in item:
        return ()
    codes = item["seat_preflight"]
    if not isinstance(codes, list) or not codes or not all(isinstance(c, str) for c in codes):
        raise ValueError("malformed seat_preflight marks in a persisted leg record")
    return tuple(SeatPreflightNotice(code, str(item.get("seat_key") or item.get("leg") or ""),
                                     str(item.get("leg") or ""), position) for code in codes)


def leg_notices(leg: object) -> tuple[SeatPreflightNotice, ...]:
    return tuple(getattr(leg, "_seat_preflight_notices", ()) or ())


def source_grounded(leg: object) -> bool:
    """False only for a leg the preflight marked (its seat could not open the brief's files)."""
    return not any(n.code == POINTER_BRIEF_UNREADABLE for n in leg_notices(leg))


def grounded_usable_legs(panel: object) -> tuple[object, ...]:
    """The usable legs a reviewer floor may count: usable AND source-grounded."""
    return tuple(leg for leg in getattr(panel, "usable_legs", ()) if source_grounded(leg))


def counts_as_grounded_vote(leg: object, counts_toward_landing: Callable[[object], bool]) -> bool:
    """The landing rule: the existing D1 rule AND the leg is source-grounded."""
    return counts_toward_landing(leg) and source_grounded(leg)


def uncounted_president_items(leg: object, terminal_verdict: Callable[[str], str | None]
                              ) -> list[str] | None:
    """The president's input for a usable leg that is NOT source-grounded: one synthetic item,
    so it can never stand as a seat's review. ``None`` (the builder's own rule) for every
    other leg, and for a blocking ``DISAGREE``, which is kept as its findings."""
    if not getattr(leg, "usable", False) or source_grounded(leg):
        return None
    if terminal_verdict(getattr(leg, "text", "")) == "DISAGREE":
        return None
    return [f"not counted (not source-grounded: {POINTER_BRIEF_UNREADABLE})"]


# --------------------------------------------------------------------------------------
# agent-harness#1132 (plan amendment A1): every seat's launch MODE, published before any seat
# launches, so a seat is never silently left without tools.
# --------------------------------------------------------------------------------------

MODE_JAILED = "jailed"          # full tools inside its per-seat jail
MODE_UNCONFINED = "unconfined"  # tools on the staged tree, not jailed (codex, grok)
MODE_SEALED = "sealed"          # no tools: the bundle is inlined
MODE_DEGRADED = "degraded"      # refused before launch
MODE_NATIVE = "native"          # filled by the driving session
MODE_REMOTE = "remote"          # placed by an activated remote rung
SEAT_MODES = (MODE_JAILED, MODE_UNCONFINED, MODE_SEALED, MODE_DEGRADED, MODE_NATIVE,
              MODE_REMOTE)

MODES_FILE = "seat-modes.json"
MODES_SCHEMA = "seat_modes.v1"


@dataclass(frozen=True)
class SeatMode:
    seat_key: str
    leg: str
    mode: str
    #: The notice code behind a non-jailed mode (rendered from the notice table), or ``None``.
    code: str | None
    why: str
    fix: str
    #: For a jailed Claude seat: ``login`` or ``seat_token``.
    credential: str | None = None
    position: int = -1
    #: Plan amendment A2: the jail was qualified on this host just before this board.
    qualified_now: bool = False
    #: Notice codes beside ``code`` that the operator must also see (plan amendment A4: an
    #: ignored seat-token override, whatever the login's own state).
    also: tuple[str, ...] = ()
    #: agent-harness#1333: the CLI admission class the seat launches with (one of
    #: ``cli_qualification.CLASSES``), or ``None`` where no CLI qualification applies yet.
    cli_admission_class: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in SEAT_MODES:
            raise ValueError(f"unknown seat mode {self.mode!r}")
        if self.cli_admission_class is not None and self.cli_admission_class not in CLI_ADMISSION_CLASSES:
            raise ValueError(f"unknown CLI admission class {self.cli_admission_class!r}")

    def as_json(self) -> dict[str, object]:
        return {"seat_key": self.seat_key, "leg": self.leg, "mode": self.mode,
                "code": self.code, "why": self.why, "fix": self.fix,
                "credential": self.credential, "qualified_now": self.qualified_now,
                "also": list(self.also), "cli_admission_class": self.cli_admission_class}

    def render(self) -> str:
        code = f" [{self.code}]" if self.code else ""
        fix = f"; fix: {self.fix}" if self.fix else ""
        also = "".join(f"; also [{extra}]" for extra in self.also)
        if self.mode == MODE_DEGRADED:
            # Plan amendment A3b: said before the board starts, so the operator can act.
            return (f"seat {self.seat_key} ({self.leg}): degraded \u2014 will not run{code}: "
                    f"{self.why}{fix}{also}")
        mode = f"{self.mode} (qualified now)" if self.qualified_now else self.mode
        return f"seat {self.seat_key} ({self.leg}): {mode}{code} -- {self.why}{fix}{also}"


def write_modes_record(stream_dir: Path, modes: Sequence[SeatMode]) -> Path:
    """Publish the modes to the stream directory before any seat launches."""
    Path(stream_dir).mkdir(parents=True, exist_ok=True)
    path = Path(stream_dir) / MODES_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema": MODES_SCHEMA, "modes": [m.as_json() for m in modes]},
                              indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


#: How long a republish waits for another writer's lock before it gives up. A republish is
#: best effort for its caller, so a held lock costs a bounded wait, never a hung seat.
MODES_LOCK_WAIT_S = 5.0
_MODES_LOCK_POLL_S = 0.05


@contextlib.contextmanager
def _modes_lock(stream_dir: Path):
    """An exclusive lock on the stream directory itself, held across a whole republish, so
    seat workers in any thread or process of the board serialize their read-modify-replace
    (an advisory ``flock`` on the directory: no lock file is left behind). A lock still held
    after :data:`MODES_LOCK_WAIT_S` raises ``ValueError``."""
    import fcntl

    try:
        descriptor = os.open(stream_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError("no published seat modes to republish") from exc
    try:
        deadline = time.monotonic() + MODES_LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("the seat modes record stayed locked by another "
                                     "writer") from None
                time.sleep(_MODES_LOCK_POLL_S)
        yield
    finally:
        os.close(descriptor)


def _read_modes(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def republish_seat_mode(stream_dir: Path, mode: SeatMode) -> Path:
    """Replace ONE seat's row in the published ``seat-modes.json`` (agent-harness#1255).

    A seat whose mode changes after publication (a login wait that ended short, a refused
    transport) is republished, so the record never shows a seat as running that did not.
    The row is the one at ``mode.position`` when that is set (its seat key and leg must
    match), else the rows of that seat key and leg. A missing or malformed record, or no
    matching row, raises ``ValueError``; every other row is kept byte for byte.

    Concurrent seats republish one at a time: the read, the edit and the replace run under
    one lock on the stream directory, through a uniquely named temporary file."""
    with _modes_lock(Path(stream_dir)):
        return _republish_locked(Path(stream_dir), mode)


def _republish_locked(stream_dir: Path, mode: SeatMode) -> Path:
    path = stream_dir / MODES_FILE
    try:
        record = _read_modes(path)
    except (OSError, ValueError) as exc:
        raise ValueError("no published seat modes to republish") from exc
    if not isinstance(record, dict) or record.get("schema") != MODES_SCHEMA:
        raise ValueError("malformed seat modes record")
    rows = record.get("modes")
    if not isinstance(rows, list):
        raise ValueError("malformed seat modes record")

    def matches(row: object) -> bool:
        return (isinstance(row, dict) and row.get("seat_key") == mode.seat_key
                and row.get("leg") == mode.leg)

    if mode.position >= 0:
        if mode.position >= len(rows) or not matches(rows[mode.position]):
            raise ValueError("no published row at that seat position")
        targets = [mode.position]
    else:
        targets = [index for index, row in enumerate(rows) if matches(row)]
    if not targets:
        raise ValueError("no published row for that seat")
    for index in targets:
        rows[index] = mode.as_json()
    # The replacement keeps the published record's permission bits: a republish never widens
    # (or narrows) who can read the record.
    try:
        permissions = stat.S_IMODE(os.stat(path).st_mode) & 0o777
    except OSError as exc:
        raise ValueError("no published seat modes to republish") from exc
    descriptor, name = tempfile.mkstemp(prefix=f".{MODES_FILE}.", suffix=".tmp", dir=stream_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"schema": MODES_SCHEMA, "modes": rows}, indent=2,
                                    sort_keys=True) + "\n")
        os.chmod(name, permissions)
        os.replace(name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
    return path
