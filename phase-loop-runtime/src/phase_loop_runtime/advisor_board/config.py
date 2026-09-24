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

# Recognised keys — anything else is a hard error (no silent drop).
_KNOWN_TOP_KEYS: frozenset[str] = frozenset({"default_board", "boards", "president"})
# A repository file configures the president ladder only: repo-level boards are not a
# feature, so a ``[[boards]]`` there is refused rather than silently ignored.
_KNOWN_REPO_TOP_KEYS: frozenset[str] = frozenset({"president"})
_KNOWN_PRESIDENT_KEYS: frozenset[str] = frozenset({"ladder"})
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


__all__ = [
    "BoardConfig",
    "BoardConfigError",
    "REPO_CONFIG_RELATIVE_PATH",
    "load_boards",
    "load_president_ladder",
    "repo_board_config_path",
]
