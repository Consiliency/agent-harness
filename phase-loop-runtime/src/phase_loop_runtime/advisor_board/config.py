"""User-editable board config loader (ABDREG, Phase 2 — lane 4).

Loads ``$XDG_CONFIG_HOME/agent-harness/advisor-boards.toml`` (the FROZEN location,
``schema.board_config_path``; format frozen by
``fixtures/advisor-boards.example.toml``) and layers user boards on top of the
built-in ``presets``. Contract:

* The four built-in presets are always present (base layer); a user ``[[boards]]``
  with the same ``name`` overrides its preset.
* ``allow_api_key_fallback`` defaults ``False`` — a board with an ``api_key`` seat
  and no opt-in is rejected by the ``Board`` schema (never-silent-key).
* **Unknown keys are a hard error, never a silent drop** — an unrecognised
  top-level, board, or seat key raises ``BoardConfigError`` naming the key.
* Every board (presets AND user boards) is validated through the compatibility
  matrix at load time, so an invalid ``(model, harness)`` pairing (e.g.
  ``claude:gpt-6-astra``) or an over-ceiling effort is rejected at CONFIG TIME with an
  actionable message (``validation.validate_board``).

A missing config file is not an error: the built-in presets load on their own.

The same user file may carry a ``[president]`` table whose ``ladder`` sets the
president fallback order; a repository may set its own in
``<repo>/.agent-harness/advisor-boards.toml`` (``[president]`` only). The effective
order is resolved by ``load_president_ladder``: built-in ``PRESIDENT_LADDER`` < user
< repo.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:  # Python 3.11+
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # Python 3.10 — the requires-python floor
    import tomli as tomllib  # type: ignore[no-redef]

from .validation import SeatValidationError, validate_board
from . import composition
from .composition import compose_review_board, default_board_auth_ok
from .presets import DEFAULT_BOARD_NAME, PRESETS
from .schema import (
    AUTH_LANES,
    PROVIDER_BACKINGS,
    Board,
    ResearchPolicy,
    Seat,
    board_config_path,
)

import hashlib as _hashlib
import json as _json
import os as _os
import subprocess as _subprocess
from dataclasses import fields as _fields
from dataclasses import is_dataclass as _is_dataclass

from .presets import (  # PANEL lane tables
    BUILTIN_LENS_TEXT,
    BUILTIN_PANEL_TABLES,
    PANEL_VENDORS,
    PRESET_NAMES,
    PanelLane,
    PanelTable,
    ResolvedLens,
)


# Recognised keys — anything else is a hard error (no silent drop).
_KNOWN_TOP_KEYS: frozenset[str] = frozenset({"default_board", "boards", "president", "agy", "panel"})
# A repository file configures the president ladder only: repo-level boards are not a
# feature, so a ``[[boards]]`` there is refused rather than silently ignored.
_KNOWN_REPO_TOP_KEYS: frozenset[str] = frozenset({"president", "panel"})
_KNOWN_PRESIDENT_KEYS: frozenset[str] = frozenset({"ladder"})
# agent-harness#1076 D3: the USER file's ``[agy] self_qualification = false`` restores the
# hard refusal of a non-release agy image. A repository file cannot carry it.
_KNOWN_AGY_KEYS: frozenset[str] = frozenset({"self_qualification"})
# Repository-level config, relative to the repository root.
REPO_CONFIG_RELATIVE_PATH = ".agent-harness/advisor-boards.toml"
_KNOWN_BOARD_KEYS: frozenset[str] = frozenset(
    {"name", "purpose", "allow_api_key_fallback", "research_enabled", "seats"}
)
_KNOWN_SEAT_KEYS: frozenset[str] = frozenset(
    {"model", "effort", "harness", "lens", "auth", "backing", "host_leg"}
)


class BoardConfigError(ValueError):
    """The board config is malformed: an unknown key, a wrong-typed value, a
    missing required field, or a board that fails matrix validation."""


@dataclass(frozen=True)
class BoardConfig:
    """Resolved board set: the built-in presets overlaid with the user's boards,
    plus the resolved ``default_board`` name."""

    boards: dict[str, Board]
    default_board: str

    def get(self, name: str | None = None) -> Board:
        """Resolve a board by name; a bare ``advisor-board`` (``name is None``)
        resolves to ``default_board``. Raises ``BoardConfigError`` naming the
        available boards for an unknown name."""
        key = name or self.default_board
        try:
            return self.boards[key]
        except KeyError as exc:
            available = ", ".join(sorted(self.boards))
            raise BoardConfigError(
                f"unknown board {key!r}; available boards: {available}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.boards))


def _reject_unknown(keys, allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(keys) - allowed)
    if unknown:
        raise BoardConfigError(
            f"unknown config key(s) {unknown} in {where}; "
            f"recognised keys: {sorted(allowed)}"
        )


def _require_bool(raw: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    """Read a boolean config key STRICTLY: an absent key yields ``default``, a
    present key MUST be a literal TOML boolean. Never coerce a non-bool scalar —
    ``bool("false")`` is ``True``, so coercion would silently flip an opt-in gate
    (e.g. a quoted ``allow_api_key_fallback = "false"`` would enable the api-key
    fallback). A wrong-typed value is a hard ``BoardConfigError`` naming the key."""
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise BoardConfigError(
            f"{where}: {key!r} must be a boolean (true/false), got "
            f"{type(value).__name__} {value!r}"
        )
    return value


def _parse_seat(raw: Mapping[str, Any], where: str) -> Seat:
    if not isinstance(raw, Mapping):
        raise BoardConfigError(f"{where} must be a table, got {type(raw).__name__}")
    _reject_unknown(raw.keys(), _KNOWN_SEAT_KEYS, where)
    if "model" not in raw:
        raise BoardConfigError(f"{where} is missing the required 'model' key")
    if "effort" not in raw:
        raise BoardConfigError(
            f"{where} (model={raw['model']!r}) is missing the required 'effort' key"
        )
    auth = raw.get("auth", AUTH_LANES[0])
    backing = raw.get("backing", PROVIDER_BACKINGS[0])
    try:
        return Seat(
            model=str(raw["model"]),
            effort=str(raw["effort"]),
            harness=(str(raw["harness"]) if raw.get("harness") is not None else None),
            lens=(str(raw["lens"]) if raw.get("lens") is not None else None),
            auth=str(auth),
            backing=str(backing),
            host_leg=_require_bool(raw, "host_leg", False, where),
        )
    except (ValueError, TypeError) as exc:
        # Seat.__post_init__ fail-closed validation (bad effort/auth/backing) ->
        # surface as a config error at load time.
        raise BoardConfigError(f"{where}: {exc}") from exc


def _parse_board(raw: Mapping[str, Any], index: int) -> Board:
    where = f"boards[{index}]"
    if not isinstance(raw, Mapping):
        raise BoardConfigError(f"{where} must be a table, got {type(raw).__name__}")
    _reject_unknown(raw.keys(), _KNOWN_BOARD_KEYS, where)
    if "name" not in raw:
        raise BoardConfigError(f"{where} is missing the required 'name' key")
    name = str(raw["name"])
    seats_raw = raw.get("seats", [])
    if not isinstance(seats_raw, list):
        raise BoardConfigError(f"board {name!r} 'seats' must be a list of seat tables")
    seats = tuple(
        _parse_seat(seat, f"board {name!r} seats[{i}]")
        for i, seat in enumerate(seats_raw)
    )
    try:
        return Board(
            name=name,
            purpose=str(raw.get("purpose", "")),
            seats=seats,
            allow_api_key_fallback=_require_bool(
                raw, "allow_api_key_fallback", False, where
            ),
            research_policy=ResearchPolicy(
                enabled=_require_bool(raw, "research_enabled", False, where)
            ),
        )
    except (ValueError, TypeError) as exc:
        # Board.__post_init__ (e.g. api_key seat without opt-in) -> config error.
        raise BoardConfigError(f"board {name!r}: {exc}") from exc


def _load_toml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise BoardConfigError(f"{path} is not valid TOML: {exc}") from exc
    except (OSError, UnicodeError) as exc:
        raise BoardConfigError(f"{path} is unreadable: {exc}") from exc


def _parse_president(data: Mapping[str, Any], where: str) -> tuple[str, ...] | None:
    """The ``[president] ladder`` of one config file, validated; ``None`` when unset."""
    from ..panel_invoker import PresidentPolicyError, validate_president_ladder

    raw = data.get("president")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise BoardConfigError(f"{where}: 'president' must be a table")
    _reject_unknown(raw.keys(), _KNOWN_PRESIDENT_KEYS, f"{where} [president]")
    if "ladder" not in raw:
        return None
    try:
        return validate_president_ladder(raw["ladder"])
    except PresidentPolicyError as exc:
        raise BoardConfigError(f"{where} [president] ladder: {exc}") from exc


def _parse_agy(data: Mapping[str, Any], where: str) -> bool:
    """The user file's ``[agy] self_qualification`` (default ``True``), validated."""
    raw = data.get("agy")
    if raw is None:
        return True
    if not isinstance(raw, Mapping):
        raise BoardConfigError(f"{where}: 'agy' must be a table")
    _reject_unknown(raw.keys(), _KNOWN_AGY_KEYS, f"{where} [agy]")
    return _require_bool(raw, "self_qualification", True, f"{where} [agy]")


def load_agy_self_qualification(*, path: Path | None = None) -> bool:
    """D3 (agent-harness#1076): whether first-use self-qualification is enabled.

    Reads the user file only (this process's ``board_config_path()``). A malformed file
    raises; the admission caller treats any error as opted out (today's refusal).
    """
    user_path = path if path is not None else board_config_path(None)
    user = _load_toml(user_path)
    if user is None:
        return True
    _reject_unknown(user.keys(), _KNOWN_TOP_KEYS, str(user_path))
    return _parse_agy(user, str(user_path))


def _user_config_path(env: Mapping[str, str] | None) -> Path | None:
    """The user file for ``env``: resolved from the GIVEN environment only.

    ``env=None`` means this process (``board_config_path()``). A passed environment is
    authoritative -- its ``XDG_CONFIG_HOME``, else its ``HOME`` -- and one that names
    neither has no user layer; the process HOME is never consulted for it.
    """
    if env is None:
        return board_config_path(None)
    if env.get("XDG_CONFIG_HOME"):
        return board_config_path(dict(env))
    if env.get("HOME"):
        return Path(env["HOME"]) / ".config" / "agent-harness" / "advisor-boards.toml"
    return None


def repo_board_config_path(repo_dir: Path | str) -> Path:
    return Path(repo_dir) / REPO_CONFIG_RELATIVE_PATH


def load_president_ladder(
    repo_dir: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> tuple[str, ...]:
    """The effective president fallback order, first rung first.

    Layers, lowest to highest: the built-in ``PRESIDENT_LADDER``; the user file's
    ``[president] ladder`` (``path``, default: resolved from ``env`` only -- see
    ``_user_config_path``); the
    repository's ``<repo_dir>/.agent-harness/advisor-boards.toml``. A layer that sets
    no ladder leaves the one below it in force. A malformed ladder or an unknown key
    is a ``BoardConfigError`` -- never a silent fallback to the built-in order.
    """
    from ..panel_invoker import PRESIDENT_LADDER

    ladder: tuple[str, ...] = PRESIDENT_LADDER
    user_path = path if path is not None else _user_config_path(env)
    user = _load_toml(user_path) if user_path is not None else None
    if user is not None:
        _reject_unknown(user.keys(), _KNOWN_TOP_KEYS, str(user_path))
        ladder = _parse_president(user, str(user_path)) or ladder
    if repo_dir is not None:
        repo_path = repo_board_config_path(repo_dir)
        repo = _load_toml(repo_path)
        if repo is not None:
            _reject_unknown(repo.keys(), _KNOWN_REPO_TOP_KEYS, str(repo_path))
            ladder = _parse_president(repo, str(repo_path)) or ladder
    return ladder


def load_boards(
    path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    matrix: Any | None = None,
    validate: bool = True,
    is_available: "Callable[[str], bool] | None" = None,
    auth_ok: "Callable[[str], bool] | None" = None,
) -> BoardConfig:
    """Load the board config, layering user boards over the built-in presets.

    ``path`` defaults to ``board_config_path(env)``. A missing file yields just the
    presets. ``matrix`` defaults to ``matrix.default_matrix()``; pass ``validate=
    False`` only for shape-parsing without availability (kept for tests). Raises
    ``BoardConfigError`` for any unknown key, malformed value, or matrix-invalid
    board — never a silent drop.

    The ``code-review`` board is composed AVAILABILITY-AWARE (down vendors are
    backfilled with distinct lenses onto available vendors, so a convened panel
    never collapses to 1–2 reviewers) via ``composition.compose_review_board``.
    ``is_available(vendor) -> bool`` decides which vendors are up; when omitted it
    is taken from a probe-backed ``matrix`` (its harness registry probe, so the
    availability view is single-sourced) and otherwise defaults to the advisor-
    board PATH probe. Composition happens BEFORE the user overlay, so a
    user-defined ``code-review`` board still wins.

    ``auth_ok(vendor) -> bool`` (REVIEWGOV-W1 / #151) additionally gates the
    composed ``code-review`` board on AUTHENTICATION so a PATH-present-but-unauthed
    vendor is dropped and backfilled. When omitted it defaults to
    ``composition.default_board_auth_ok`` — the cached, timeout-bounded, fail-closed
    ``auth_ok_for`` gate — so the LIVE convening path is genuinely auth-aware (the
    real fix for #151). The gate only runs for vendors that pass the availability
    (PATH) probe, so a host with no vendor CLI installed short-circuits without
    shelling out. Inject ``auth_ok`` (e.g. ``lambda _v: True``) to isolate the
    availability dimension in a test.
    """
    boards: dict[str, Board] = dict(PRESETS)
    default_board = DEFAULT_BOARD_NAME

    # Availability-aware code-review (before the user overlay so a user override wins).
    compose_probe = is_available
    if compose_probe is None and matrix is not None:
        compose_probe = getattr(
            getattr(matrix, "harnesses", None), "is_available", None
        )
    # #151: the LIVE convening path is auth-aware by DEFAULT — a PATH-present but
    # unauthenticated vendor is dropped and backfilled. Pass an explicit ``auth_ok``
    # so the composer never falls through to its is_available-injected pass-through
    # affordance (which exists only for the static presets / simulation tests). The
    # gate short-circuits for vendors that fail the availability probe, so a host
    # with no vendor CLI never shells out.
    compose_auth = auth_ok if auth_ok is not None else default_board_auth_ok
    # ``load_boards`` is the production board-loading entry, so EVERY probe it is
    # about to run -- the default PATH/auth gates or a caller-injected callable
    # whose purity the runtime cannot verify -- executes behind fresh,
    # operation-bound composition authority.  Only ``compose_review_board``
    # itself, when handed two injected probes directly, remains the hermetic
    # static-composition control (import-time presets).
    composition_authorization = composition.prepare_review_composition_authorization()
    try:
        composition.revalidate_review_composition_authorization(
            composition_authorization
        )
        composed_review = compose_review_board(
            is_available=compose_probe, auth_ok=compose_auth
        )
    finally:
        composition._clear_composition_authorization()
    boards[composed_review.name] = composed_review

    cfg_path = path if path is not None else board_config_path(env)
    if cfg_path.exists():
        with open(cfg_path, "rb") as fh:
            try:
                data = tomllib.load(fh)
            except tomllib.TOMLDecodeError as exc:
                raise BoardConfigError(f"{cfg_path} is not valid TOML: {exc}") from exc
        _reject_unknown(data.keys(), _KNOWN_TOP_KEYS, str(cfg_path))
        _parse_president(data, str(cfg_path))  # a bad [president] fails at load too
        _parse_agy(data, str(cfg_path))  # and a bad [agy] (agent-harness#1076)
        raw_boards = data.get("boards", [])
        if not isinstance(raw_boards, list):
            raise BoardConfigError(f"{cfg_path}: 'boards' must be an array of tables")
        for i, raw in enumerate(raw_boards):
            board = _parse_board(raw, i)
            boards[board.name] = board  # user board overrides a same-named preset
        if "default_board" in data:
            default_board = str(data["default_board"])

    if default_board not in boards:
        available = ", ".join(sorted(boards))
        raise BoardConfigError(
            f"default_board {default_board!r} is not a defined board; "
            f"available boards: {available}"
        )

    if validate:
        if matrix is None:
            from .matrix import default_matrix

            matrix = default_matrix(env=env)
        # Seat validation is the SAME probe class as composition: ``matrix.is_valid``
        # reaches the harness PATH probe and the vendor key-var scan for every seat,
        # and a caller-injected ``matrix`` is a callable whose purity the runtime
        # cannot verify.  It therefore runs behind its own fresh, revalidated
        # composition authority rather than after the composition grant was cleared.
        validation_authorization = composition.prepare_review_composition_authorization()
        try:
            composition.revalidate_review_composition_authorization(
                validation_authorization
            )
            for board in boards.values():
                try:
                    validate_board(board, matrix=matrix)
                except SeatValidationError as exc:
                    # Surface matrix-level rejections under the config error type so a
                    # caller catches one exception for any load-time failure.
                    raise BoardConfigError(str(exc)) from exc
        finally:
            composition._clear_composition_authorization()

    return BoardConfig(boards=boards, default_board=default_board)


# --- PANEL: lane tables, sources and the gate-time context (v10 Phase 18, agent-harness#1078) ---
#
# IF-0-PANEL-1. ``[panel.<task>]`` tables come from the built-in presets, the user file
# (read ONCE at run start, by content digest) and the repository file (read ONLY at the
# gate's base revision, and only its ``[panel.*]``). Precedence is built-in < user <
# repository, table by table; an invalid base table is replaced by its BUILT-IN table.
# ``snapshot_panel_run`` and ``build_panel_context`` are the only sources of the objects
# ``invoke_board`` trusts: each is recorded here by identity plus a content digest.

PANEL_TABLE_KEYS: frozenset[str] = frozenset({"lanes", "lenses", "min_distinct_vendors"})
PANEL_LANE_KEYS: frozenset[str] = frozenset({"lens", "vendors"})
REPLACED_SOURCE = "repository table invalid at base, replaced"
GOVERNANCE_RELATIVE_PATH = ".phase-loop/governance.toml"
GOVERNANCE_USER_RELATIVE_PATH = "agent-harness/governance.toml"
PROFILE_SEAT_ALIASES: frozenset[str] = frozenset({"fable", "sol", "grok", "gemini"})
_SEAT_REQUIRED_TIERS: frozenset[str] = frozenset({"plan", "production_code"})
_PROFILE_TIERS: frozenset[str] = frozenset({"plan", "production_code", "tests_only", "docs_only"})
PANEL_MONITORING_POLICIES: frozenset[str] = frozenset({"bounded", "heartbeat_only"})


@dataclass(frozen=True)
class TableSource:
    """Where a resolved table (or its minimum) came from: ``built-in``, ``user`` (path +
    content digest), ``repository`` (path + base revision), or the replaced label."""

    kind: str
    path: str | None = None
    digest: str | None = None
    base_revision: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"kind": self.kind, "path": self.path, "digest": self.digest, "base_revision": self.base_revision}

    def __str__(self) -> str:
        detail = self.digest or self.base_revision
        return f"{self.kind} {self.path}@{detail}" if self.path else self.kind


_BUILTIN_SOURCE = TableSource(kind="built-in")


@dataclass(frozen=True)
class ResolvedPanelTable:
    table: PanelTable
    source: TableSource
    provenance: str


@dataclass(frozen=True)
class ExplicitProfileSeats:
    """The seats an explicit governance profile names for one tier, with its path and
    provenance (a content digest for the user file, the base revision for the repository)."""

    seats: tuple[str, ...]
    path: str
    provenance: str


@dataclass(frozen=True)
class PanelProbes:
    """The one injectable probe seam of ``build_panel_context``; each is ``(vendor) -> bool``."""

    is_available: Callable[[str], bool]
    auth_ok: Callable[[str], bool]
    preflight: Callable[[str], bool]


@dataclass(frozen=True)
class PanelRunSnapshot:
    """User-side inputs, taken once at run start."""

    user_table: Mapping[str, PanelTable]
    user_digest: str | None
    user_profile: ExplicitProfileSeats | None


@dataclass(frozen=True)
class PanelContext:
    """The gate-time context: every landing's panel inputs, bound to its base revision."""

    snapshot: PanelRunSnapshot
    resolved_table: ResolvedPanelTable
    explicit_profile: ExplicitProfileSeats | None
    composed: Any
    gated_revision: str | None


# --- the registry ------------------------------------------------------------------------
#
# Identity plus a digest of the canonical content, with strong references (a collected
# object's id() is never reused). ``invoke_board`` and ``merge_guard`` verify through
# ``verify_panel_object``; only the snapshot and context builders register.

_PANEL_REGISTRY: dict[int, tuple[object, str, dict[str, Any]]] = {}


def _canonical(value: Any) -> Any:
    if _is_dataclass(value) and not isinstance(value, type):
        return {"__type__": type(value).__name__,
                **{f.name: _canonical(getattr(value, f.name)) for f in _fields(value)}}
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return {"__type__": type(value).__name__, **{k: _canonical(v) for k, v in value._asdict().items()}}
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if callable(value):
        return f"<callable {getattr(value, '__qualname__', type(value).__name__)} {id(value)}>"
    if isinstance(value, Path):
        return str(value)
    return value


def panel_content_digest(value: object) -> str:
    return _hashlib.sha256(
        _json.dumps(_canonical(value), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _register_panel_object(obj: object, facts: dict[str, Any]) -> None:
    _PANEL_REGISTRY[id(obj)] = (obj, panel_content_digest(obj), dict(facts))


def verify_panel_object(obj: object) -> dict[str, Any] | None:
    """The registered facts for ``obj`` when it is the builder's own, unmodified object;
    ``None`` for a hand-built object, a copy, or one whose content changed."""
    entry = _PANEL_REGISTRY.get(id(obj))
    if entry is None or entry[0] is not obj:
        return None
    if panel_content_digest(obj) != entry[1]:
        return None
    return dict(entry[2])


# --- parsing -------------------------------------------------------------------------------


def _parse_panel_table(task: object, raw: object, where: str) -> PanelTable:
    if task not in PRESET_NAMES:
        raise BoardConfigError(f"{where}: unknown panel task {task!r}; known tasks: {list(PRESET_NAMES)}")
    if not isinstance(raw, Mapping):
        raise BoardConfigError(f"{where}: [panel.{task}] must be a table")
    _reject_unknown(raw.keys(), PANEL_TABLE_KEYS, where)
    lenses_raw = raw.get("lenses", {})
    if not isinstance(lenses_raw, Mapping):
        raise BoardConfigError(f"{where}: 'lenses' must be a table of lens name -> instruction text")
    declared: dict[str, str] = {}
    for name, text in lenses_raw.items():
        if name in BUILTIN_LENS_TEXT:
            raise BoardConfigError(f"{where}: declared lens {name!r} reuses a built-in lens name")
        if not isinstance(text, str):
            raise BoardConfigError(f"{where}: lens {name!r} text must be a string, got {type(text).__name__}")
        if not text.strip():
            raise BoardConfigError(f"{where}: lens {name!r} text is empty")
        declared[str(name)] = text
    if "lanes" not in raw:
        raise BoardConfigError(f"{where}: 'lanes' is required")
    lanes_raw = raw["lanes"]
    if not isinstance(lanes_raw, list):
        raise BoardConfigError(f"{where}: 'lanes' must be an array of {{lens, vendors}} tables")
    if not lanes_raw:
        raise BoardConfigError(f"{where}: 'lanes' is empty")
    lanes: list[PanelLane] = []
    seen: set[str] = set()
    for index, lane in enumerate(lanes_raw):
        lane_where = f"{where} lanes[{index}]"
        if not isinstance(lane, Mapping):
            raise BoardConfigError(f"{lane_where}: each entry of 'lanes' must be a table")
        _reject_unknown(lane.keys(), PANEL_LANE_KEYS, lane_where)
        if "lens" not in lane:
            raise BoardConfigError(f"{lane_where}: missing 'lens'")
        lens = lane["lens"]
        if not isinstance(lens, str):
            raise BoardConfigError(f"{lane_where}: 'lens' must be a string, got {type(lens).__name__}")
        if lens not in BUILTIN_LENS_TEXT and lens not in declared:
            raise BoardConfigError(f"{lane_where}: unknown lens {lens!r} (neither built-in nor declared)")
        if lens in seen:
            raise BoardConfigError(f"{lane_where}: lens {lens!r} has two lanes")
        seen.add(lens)
        if "vendors" not in lane:
            raise BoardConfigError(f"{lane_where}: missing 'vendors'")
        vendors = lane["vendors"]
        if not isinstance(vendors, list):
            raise BoardConfigError(f"{lane_where}: 'vendors' must be a list, got {type(vendors).__name__}")
        if not vendors:
            raise BoardConfigError(f"{lane_where}: 'vendors' is empty")
        for vendor in vendors:
            if not isinstance(vendor, str):
                raise BoardConfigError(f"{lane_where}: 'vendors' entries must be strings, got {vendor!r}")
            if vendor not in PANEL_VENDORS:
                raise BoardConfigError(f"{lane_where}: unknown vendor {vendor!r}; board vendors: {list(PANEL_VENDORS)}")
        if len(set(vendors)) != len(vendors):
            raise BoardConfigError(f"{lane_where}: 'vendors' has a duplicate entry: {vendors}")
        lanes.append(PanelLane(lens=lens, vendors=tuple(vendors)))
    minimum = None
    if "min_distinct_vendors" in raw:
        if task != "code-review":
            raise BoardConfigError(f"{where}: 'min_distinct_vendors' is allowed only in [panel.code-review]")
        value = raw["min_distinct_vendors"]
        if type(value) is not int or not 1 <= value <= len(PANEL_VENDORS):
            raise BoardConfigError(
                f"{where}: 'min_distinct_vendors' must be an integer from 1 to {len(PANEL_VENDORS)}, got {value!r}"
            )
        minimum = value
    return PanelTable(task=str(task), lanes=tuple(lanes), lenses=declared, min_distinct_vendors=minimum)


def _parse_panel_section(data: Mapping[str, Any], where: str) -> dict[str, PanelTable]:
    """Every ``[panel.*]`` table in ``data``, validated; raises on the first invalid one."""
    panel = data.get("panel")
    if panel is None:
        return {}
    if not isinstance(panel, Mapping):
        raise BoardConfigError(f"{where}: 'panel' must be a table of [panel.<task>] tables")
    return {str(task): _parse_panel_table(task, raw, f"{where} [panel.{task}]") for task, raw in panel.items()}


def _parse_toml_bytes(data: bytes, where: str) -> dict[str, Any]:
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise BoardConfigError(f"{where} is not valid TOML: {exc}") from exc


def _read_user_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except (OSError, IsADirectoryError) as exc:
        raise BoardConfigError(f"{path} is unreadable: {exc}") from exc


def _user_tables(path: Path | None) -> tuple[dict[str, PanelTable], str | None]:
    if path is None:
        return {}, None
    data = _read_user_bytes(Path(path))
    if data is None:
        return {}, None
    digest = _hashlib.sha256(data).hexdigest()
    return _parse_panel_section(_parse_toml_bytes(data, str(path)), str(path)), digest


# --- git reads at a revision (local subcommands only) --------------------------------------

_GIT_READ_C = ("-c", "core.hooksPath=/dev/null")


def _git_read(repo_dir: Path | str, *args: str) -> _subprocess.CompletedProcess:
    env = {k: v for k, v in _os.environ.items() if not k.startswith("GIT_")}
    return _subprocess.run(
        ["git", *_GIT_READ_C, "-C", str(repo_dir), *args], capture_output=True, env=env, check=False,
    )


def _resolve_revision(repo_dir: Path | str, revision: str) -> str:
    done = _git_read(repo_dir, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
    if done.returncode != 0:
        raise BoardConfigError(f"base revision {revision!r} cannot be read in {repo_dir}")
    return done.stdout.decode("utf-8").strip()


def _blob_at(repo_dir: Path | str, revision: str, rel: str) -> bytes | None:
    """The file ``rel`` at ``revision``: ``None`` when the revision has no such file."""
    commit = _resolve_revision(repo_dir, revision)
    listed = _git_read(repo_dir, "ls-tree", commit, "--", rel)
    if listed.returncode != 0:
        raise BoardConfigError(f"revision {revision!r} cannot be listed in {repo_dir}")
    if not listed.stdout.strip():
        return None
    shown = _git_read(repo_dir, "cat-file", "blob", f"{commit}:{rel}")
    if shown.returncode != 0:
        raise BoardConfigError(f"{rel} at {revision!r} cannot be read")
    return shown.stdout


def _repo_tables(repo_dir: Path | str, revision: str) -> tuple[dict[str, PanelTable], set[str] | None]:
    """The valid ``[panel.*]`` tables at ``revision`` and the set of tasks whose base table
    is invalid (``None`` = the whole section is invalid, e.g. a TOML parse error)."""
    raw = _blob_at(repo_dir, revision, REPO_CONFIG_RELATIVE_PATH)
    if raw is None:
        return {}, set()
    where = f"{REPO_CONFIG_RELATIVE_PATH}@{revision}"
    try:
        data = _parse_toml_bytes(raw, where)
    except BoardConfigError:
        return {}, None
    panel = data.get("panel")
    if panel is None:
        return {}, set()
    if not isinstance(panel, Mapping):
        return {}, None
    tables: dict[str, PanelTable] = {}
    invalid: set[str] = set()
    for task, table in panel.items():
        try:
            tables[str(task)] = _parse_panel_table(task, table, f"{where} [panel.{task}]")
        except BoardConfigError:
            invalid.add(str(task))
    return tables, invalid


def _resolve(task: str, *, user_tables: Mapping[str, PanelTable], user_source: TableSource,
             repo_dir: Path | str | None, base_revision: str | None) -> ResolvedPanelTable:
    if task not in BUILTIN_PANEL_TABLES:
        raise BoardConfigError(f"unknown panel task {task!r}; known tasks: {list(PRESET_NAMES)}")
    builtin = BUILTIN_PANEL_TABLES[task]
    if repo_dir is not None and base_revision is not None:
        commit = _resolve_revision(repo_dir, base_revision)
        repo_tables, invalid = _repo_tables(repo_dir, commit)
        repo_source = TableSource(kind="repository", path=REPO_CONFIG_RELATIVE_PATH, base_revision=base_revision)
        if task in repo_tables:
            return ResolvedPanelTable(repo_tables[task], repo_source, str(repo_source))
        if invalid is None or task in invalid:
            replaced = TableSource(kind=REPLACED_SOURCE, path=REPO_CONFIG_RELATIVE_PATH, base_revision=base_revision)
            return ResolvedPanelTable(builtin, replaced, str(replaced))
    if task in user_tables:
        return ResolvedPanelTable(user_tables[task], user_source, str(user_source))
    return ResolvedPanelTable(builtin, _BUILTIN_SOURCE, str(_BUILTIN_SOURCE))


def resolve_panel_table(
    task: str,
    *,
    user_path: Path | str | None = None,
    repo_dir: Path | str | None = None,
    base_revision: str | None = None,
) -> ResolvedPanelTable:
    """Resolve ``task``'s table: built-in < the user file at ``user_path`` < the repository
    file at ``base_revision`` (``git show``; only ``[panel.*]`` is read). A malformed user
    table, or a base revision that cannot be read at all, raises ``BoardConfigError``."""
    tables, digest = _user_tables(Path(user_path) if user_path is not None else None)
    source = TableSource(kind="user", path=str(user_path) if user_path is not None else None, digest=digest)
    return _resolve(task, user_tables=tables, user_source=source, repo_dir=repo_dir, base_revision=base_revision)


def _panel_section_of(raw: bytes | None, where: str) -> dict[str, Any]:
    """The raw ``[panel]`` mapping of a file (for change detection); a parse failure raises."""
    if raw is None:
        return {}
    panel = _parse_toml_bytes(raw, where).get("panel", {})
    if not isinstance(panel, Mapping):
        raise BoardConfigError(f"{where}: 'panel' must be a table")
    return dict(panel)


def _merged_file(repo_dir: Path | str, base: str, head: str) -> bytes | None:
    """The repository file of the change applied onto ``base`` (a three-way merge from
    their merge base); a conflict raises."""
    merge_base = _git_read(repo_dir, "merge-base", base, head)
    if merge_base.returncode != 0:
        raise BoardConfigError(f"no merge base between {base!r} and {head!r}")
    mb = merge_base.stdout.decode().strip()
    contents = {rev: _blob_at(repo_dir, rev, REPO_CONFIG_RELATIVE_PATH) for rev in (mb, base, head)}
    if contents[head] == contents[mb]:
        return contents[base]
    if contents[base] == contents[mb]:
        return contents[head]
    import tempfile

    with tempfile.TemporaryDirectory(prefix="panel-merge-") as td:
        paths = {}
        for name, rev in (("current", base), ("ancestor", mb), ("other", head)):
            path = Path(td) / name
            path.write_bytes(contents[rev] or b"")
            paths[name] = path
        merged = _git_read(repo_dir, "merge-file", "-p", str(paths["current"]), str(paths["ancestor"]),
                           str(paths["other"]))
        if merged.returncode != 0:
            raise BoardConfigError(f"the change's {REPO_CONFIG_RELATIVE_PATH} does not apply cleanly onto {base!r}")
        return merged.stdout


def validate_panel_change(repo_dir: Path | str, *, base_revision: str, head_revision: str | None) -> None:
    """Refuse a change whose added or edited ``[panel.*]`` table is invalid once applied onto
    the target head ``base_revision``. Tables the change does not touch are not its concern,
    so an invalid base table the change leaves alone never blocks it."""
    if head_revision is None:
        return
    base = _resolve_revision(repo_dir, base_revision)
    head = _resolve_revision(repo_dir, head_revision)
    merge_base = _git_read(repo_dir, "merge-base", base, head)
    if merge_base.returncode != 0:
        raise BoardConfigError(f"no merge base between {base_revision!r} and {head_revision!r}")
    mb = merge_base.stdout.decode().strip()
    head_raw = _blob_at(repo_dir, head, REPO_CONFIG_RELATIVE_PATH)
    mb_raw = _blob_at(repo_dir, mb, REPO_CONFIG_RELATIVE_PATH)
    if head_raw == mb_raw:
        return
    head_panel = _panel_section_of(head_raw, f"{REPO_CONFIG_RELATIVE_PATH}@{head_revision}")
    try:
        mb_panel = _panel_section_of(mb_raw, f"{REPO_CONFIG_RELATIVE_PATH}@{mb}")
    except BoardConfigError:
        mb_panel = {}
    touched = {task for task in set(head_panel) | set(mb_panel) if head_panel.get(task) != mb_panel.get(task)}
    if not touched:
        return
    merged = _merged_file(repo_dir, base, head)
    where = f"{REPO_CONFIG_RELATIVE_PATH} (the change applied onto {base_revision})"
    merged_panel = _panel_section_of(merged, where)
    for task in sorted(touched):
        if task in merged_panel:
            _parse_panel_table(task, merged_panel[task], f"{where} [panel.{task}]")


def _governance_panel_lists(raw: bytes | None) -> Any:
    if raw is None:
        return None
    try:
        data = _parse_toml_bytes(raw, GOVERNANCE_RELATIVE_PATH)
    except BoardConfigError:
        return ("unparseable", _hashlib.sha256(raw).hexdigest())
    tiers = data.get("tiers")
    if not isinstance(tiers, Mapping):
        return {}
    return {str(tier): (spec.get("panel") if isinstance(spec, Mapping) else ("malformed", repr(spec)))
            for tier, spec in tiers.items()}


def panel_regate_required(repo_dir: Path | str, *, gated_revision: str, target_head: str) -> bool:
    """True when the target head changed ``[panel.*]`` or the repository governance
    profile's ``panel`` lists since ``gated_revision``."""
    gated = _resolve_revision(repo_dir, gated_revision)
    target = _resolve_revision(repo_dir, target_head)
    if gated == target:
        return False
    before = _blob_at(repo_dir, gated, REPO_CONFIG_RELATIVE_PATH)
    after = _blob_at(repo_dir, target, REPO_CONFIG_RELATIVE_PATH)
    if before != after:
        try:
            changed = _panel_section_of(before, "gated") != _panel_section_of(after, "target")
        except BoardConfigError:
            changed = True
        if changed:
            return True
    return _governance_panel_lists(_blob_at(repo_dir, gated, GOVERNANCE_RELATIVE_PATH)) != \
        _governance_panel_lists(_blob_at(repo_dir, target, GOVERNANCE_RELATIVE_PATH))


# --- explicit governance profiles (the corpus layout; IF-0-GOVSETUP-1 builds on it) -------


def _profile_from(raw: bytes, *, tier: str, path: str, provenance: str) -> ExplicitProfileSeats | None:
    data = _parse_toml_bytes(raw, path)
    tiers = data.get("tiers", {})
    if not isinstance(tiers, Mapping):
        raise BoardConfigError(f"{path}: 'tiers' must be a table")
    spec = tiers.get(tier)
    if spec is None:
        return None
    if not isinstance(spec, Mapping):
        raise BoardConfigError(f"{path}: [tiers.{tier}] must be a table")
    if "panel" not in spec:
        return None
    seats = spec["panel"]
    if seats == "none":
        if tier in _SEAT_REQUIRED_TIERS:
            raise BoardConfigError(f"{path}: [tiers.{tier}] panel = \"none\" is refused at {tier}")
        return None
    if not isinstance(seats, list) or not seats:
        raise BoardConfigError(f"{path}: [tiers.{tier}] 'panel' must be a non-empty list of seat aliases")
    for seat in seats:
        if not isinstance(seat, str) or seat not in PROFILE_SEAT_ALIASES:
            raise BoardConfigError(
                f"{path}: [tiers.{tier}] unknown panel seat {seat!r}; seats: {sorted(PROFILE_SEAT_ALIASES)}"
            )
    return ExplicitProfileSeats(seats=tuple(seats), path=path, provenance=provenance)


def load_repository_profile(repo_dir: Path | str, *, base_revision: str, tier: str) -> ExplicitProfileSeats | None:
    """The repository profile's seats for ``tier``, read at ``base_revision``. An absent file
    means no explicit seats; a malformed one raises ``BoardConfigError``."""
    raw = _blob_at(repo_dir, base_revision, GOVERNANCE_RELATIVE_PATH)
    if raw is None:
        return None
    return _profile_from(raw, tier=tier, path=GOVERNANCE_RELATIVE_PATH, provenance=base_revision)


def user_profile_path() -> Path:
    base = _os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / GOVERNANCE_USER_RELATIVE_PATH


def load_user_profile(*, tier: str, path: Path | str | None = None) -> ExplicitProfileSeats | None:
    """The user profile's seats for ``tier``, labelled with its path and content digest."""
    target = Path(path) if path is not None else user_profile_path()
    raw = _read_user_bytes(target)
    if raw is None:
        return None
    return _profile_from(raw, tier=tier, path=str(target), provenance=_hashlib.sha256(raw).hexdigest())


# --- the run-start snapshot and the gate-time context --------------------------------------


def snapshot_panel_run(*, user_profile: ExplicitProfileSeats | None = None) -> PanelRunSnapshot:
    """Read the user file ONCE, at run start, and record it by content digest."""
    path = board_config_path()
    tables, digest = _user_tables(path)
    snapshot = PanelRunSnapshot(user_table=tables, user_digest=digest, user_profile=user_profile)
    _register_panel_object(snapshot, {"kind": "snapshot", "user_path": str(path)})
    return snapshot


def read_user_file_digest(path: Path | str) -> str | None:
    """A fresh read and hash of the user file (``None`` when absent)."""
    data = _read_user_bytes(Path(path))
    return None if data is None else _hashlib.sha256(data).hexdigest()


def _default_probes(monitoring_policy: str) -> PanelProbes:
    """The production probes, looked up by module attribute at call time: CLI presence
    (``DEFAULT_HARNESS_REGISTRY.probe``), the cached subscription auth gate (which reaches
    ``executor_availability._probes_pass``) and, under ``heartbeat_only`` only, the agy
    capability (``gemini_heartbeat.require_capability``)."""

    def is_available(vendor: str) -> bool:
        from . import registries

        registry = registries.DEFAULT_HARNESS_REGISTRY
        try:
            return bool(registry.probe(registry.get(vendor).cli))
        except Exception:
            return False

    def auth_ok(vendor: str) -> bool:
        return composition.default_board_auth_ok(vendor)

    def preflight(vendor: str) -> bool:
        if monitoring_policy != "heartbeat_only" or vendor != "gemini":
            return True
        from .. import gemini_heartbeat

        try:
            gemini_heartbeat.require_capability(dict(_os.environ))
        except Exception:
            return False
        return True

    return PanelProbes(is_available=is_available, auth_ok=auth_ok, preflight=preflight)


def _git_common_dir(repo_dir: Path | str) -> str | None:
    done = _git_read(repo_dir, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return done.stdout.decode().strip() if done.returncode == 0 else None


def build_panel_context(
    task: str,
    snapshot: PanelRunSnapshot,
    *,
    repo_dir: Path | str,
    base_revision: str,
    head_revision: str | None,
    monitoring_policy: str,
    repository_profile: ExplicitProfileSeats | None = None,
    probes: PanelProbes | None = None,
) -> PanelContext:
    """Build a landing's context at gate time: ``[panel.*]`` at ``base_revision`` (the
    fetched target head), the change validated onto it when ``head_revision`` is given,
    the explicit profile, and the board composed under the policy's probes."""
    facts = verify_panel_object(snapshot)
    if facts is None or facts.get("kind") != "snapshot":
        raise BoardConfigError("the panel snapshot is not the run-start snapshot (unregistered or changed)")
    if monitoring_policy not in PANEL_MONITORING_POLICIES:
        raise BoardConfigError(f"unknown review monitoring policy {monitoring_policy!r}")
    validate_panel_change(repo_dir, base_revision=base_revision, head_revision=head_revision)
    user_path = facts.get("user_path")
    user_source = TableSource(kind="user", path=user_path, digest=snapshot.user_digest)
    resolved = _resolve(task, user_tables=snapshot.user_table, user_source=user_source,
                        repo_dir=repo_dir, base_revision=base_revision)
    explicit = repository_profile if repository_profile is not None else snapshot.user_profile
    injected = probes is not None
    effective = probes if probes is not None else _default_probes(monitoring_policy)
    composer = composition.compose_panel_board
    authorization = None
    if not injected:
        authorization = composition.prepare_review_composition_authorization()
    try:
        if authorization is not None:
            composition.revalidate_review_composition_authorization(authorization)
        composed = composer(resolved.table, is_available=effective.is_available,
                            auth_ok=effective.auth_ok, preflight=effective.preflight)
    finally:
        if authorization is not None:
            composition._clear_composition_authorization()
    context = PanelContext(snapshot=snapshot, resolved_table=resolved, explicit_profile=explicit,
                           composed=composed, gated_revision=base_revision)
    _register_panel_object(context, {
        "kind": "context",
        "task": task,
        "repo_dir": str(Path(repo_dir).resolve()),
        "git_common_dir": _git_common_dir(repo_dir),
        "validated_head": head_revision,
        "probes_injected": injected,
        "monitoring_policy": monitoring_policy,
        "user_path": user_path,
    })
    return context

# --- gate-time helpers shared by the landing entries (runner, run-train, gate, CLI) -------


@dataclass(frozen=True)
class GateTarget:
    """The target an entry gated against: ``origin``'s default branch, fetched at gate time."""

    branch: str
    head: str


def fetch_gate_target(repo_dir: Path | str, *, remote: str = "origin") -> GateTarget:
    """Fetch ``remote``'s default branch now and return its head (never a stale ref)."""
    listed = _git_read(repo_dir, "ls-remote", "--symref", remote, "HEAD")
    if listed.returncode != 0:
        raise BoardConfigError(f"the target of {remote!r} cannot be read")
    branch = None
    for line in listed.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            branch = line[len("ref: refs/heads/"):-len("\tHEAD")]
    if not branch:
        raise BoardConfigError(f"the default branch of {remote!r} cannot be read")
    fetched = _git_read(repo_dir, "fetch", "--no-tags", "--quiet", remote,
                        f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}")
    if fetched.returncode != 0:
        raise BoardConfigError(f"the target {remote}/{branch} cannot be fetched")
    head = _resolve_revision(repo_dir, f"refs/remotes/{remote}/{branch}")
    return GateTarget(branch=branch, head=head)


def gate_panel_context(
    snapshot: PanelRunSnapshot,
    *,
    repo_dir: Path | str,
    head_revision: str | None,
    tier: str | None,
    monitoring_policy: str,
    task: str = "code-review",
) -> tuple[PanelContext, GateTarget]:
    """Build the gate's context: fetch the target head, read the repository profile at it,
    and build through ``build_panel_context`` (looked up at call time)."""
    target = fetch_gate_target(repo_dir)
    profile = load_repository_profile(repo_dir, base_revision=target.head, tier=tier) if tier else None
    context = build_panel_context(task, snapshot, repo_dir=repo_dir, base_revision=target.head,
                                  head_revision=head_revision, monitoring_policy=monitoring_policy,
                                  repository_profile=profile)
    return context, target


def regate_panel_context(
    context: PanelContext,
    snapshot: PanelRunSnapshot,
    *,
    repo_dir: Path | str,
    head_revision: str | None,
    tier: str | None,
    monitoring_policy: str,
    task: str = "code-review",
) -> PanelContext | None:
    """Re-read the target; when it changed ``[panel.*]`` or the profile's ``panel`` lists
    since the gate, rebuild the context at the new head (``None`` when no re-gate is due)."""
    target = fetch_gate_target(repo_dir)
    if not panel_regate_required(repo_dir, gated_revision=str(context.gated_revision), target_head=target.head):
        return None
    rebuilt, _target = gate_panel_context(snapshot, repo_dir=repo_dir, head_revision=head_revision, tier=tier,
                                          monitoring_policy=monitoring_policy, task=task)
    return rebuilt


def current_user_digest(context: PanelContext) -> str | None:
    """A fresh read and hash of the user file the context's snapshot was taken from."""
    facts = verify_panel_object(context) or {}
    path = facts.get("user_path")
    return read_user_file_digest(path) if path else None


def snapshot_for_tier(tier: str | None) -> PanelRunSnapshot:
    """The run-start snapshot with the user governance profile for ``tier``."""
    return snapshot_panel_run(user_profile=load_user_profile(tier=tier) if tier else None)

__all__ = [
    "BoardConfig",
    "BoardConfigError",
    "REPO_CONFIG_RELATIVE_PATH",
    "load_boards",
    "load_president_ladder",
    "repo_board_config_path",
    "ResolvedLens",
    "PanelLane",
    "PanelTable",
    "ResolvedPanelTable",
    "TableSource",
    "ExplicitProfileSeats",
    "PanelProbes",
    "PanelRunSnapshot",
    "PanelContext",
    "resolve_panel_table",
    "validate_panel_change",
    "panel_regate_required",
    "snapshot_panel_run",
    "build_panel_context",
    "load_repository_profile",
    "load_user_profile",
    "GateTarget",
    "fetch_gate_target",
    "gate_panel_context",
    "regate_panel_context",
    "snapshot_for_tier",
]
