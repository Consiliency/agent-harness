"""Retractable teeth -- gate enforcement posture resolution.

Reads the merge-gated ``gate_posture_registry`` (consiliency-contract >= 0.6.2) and
resolves the *effective* posture for a finding class from three layers -- the contract
``default_posture``, then a per-repo ``.consiliency/manifest.json`` override -- clamped
to the class's non-retractable ``min_posture`` FLOOR and optional ``max_posture`` cap.

Posture rungs: ``observe`` < ``warn`` < ``enforce``. A per-repo override may RAISE any
class freely but may LOWER it only to (never below) its floor -- ``invariant`` classes
(never-delete-human-refs, write-footprint, hash-drift) carry a real floor; ``advisory``
classes retract freely to ``observe``. The operator's ``PHASE_LOOP_CONSILIENCY_GATES``
= off | warn | hard remains the MASTER switch: ``enforce`` blocks ONLY under ``hard``;
``human_required`` is NEVER set at any posture. A per-repo *downward* move is surfaced
via the non-retractable ``posture_retracted`` note so de-fanging is always fleet-visible.

Contract-absent degrade: if the installed contract predates the registry (< 0.6.2),
:func:`available` is False and callers keep their legacy status logic unchanged.

Design ratified by advisory panel (Fable + Codex 5.5 + Gemini 3.1 Pro, unanimous).
"""
from __future__ import annotations

from typing import Any, Mapping

_RUNG = {"observe": 0, "warn": 1, "enforce": 2}
# Optional per-repo overrides live under this manifest key: {finding_code: posture}.
MANIFEST_OVERRIDE_KEY = "gate_posture_overrides"
_DEFAULT_UNLISTED = {"category": "advisory", "default_posture": "warn", "min_posture": "observe"}


def _rank(posture: str) -> int:
    return _RUNG.get(posture, _RUNG["warn"])


_REGISTRY_CACHE: dict[str, Any] | None = None
_REGISTRY_LOADED = False


def _registry() -> dict[str, Any] | None:
    global _REGISTRY_CACHE, _REGISTRY_LOADED
    if _REGISTRY_LOADED:
        return _REGISTRY_CACHE
    try:
        from consiliency_contract import load_registry

        reg = load_registry("gate_posture_registry")
        _REGISTRY_CACHE = reg if isinstance(reg, Mapping) else None
    except Exception:
        _REGISTRY_CACHE = None  # contract predates the registry (< 0.6.2)
    _REGISTRY_LOADED = True
    return _REGISTRY_CACHE


def available() -> bool:
    """True when the installed contract ships the posture registry (>= 0.6.2)."""
    return _registry() is not None


def _class_entry(reg: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    for fc in reg.get("finding_classes", []):
        if isinstance(fc, Mapping) and fc.get("code") == code:
            return fc
    unlisted = reg.get("default_unlisted")
    return unlisted if isinstance(unlisted, Mapping) else _DEFAULT_UNLISTED


def _overrides(manifest: Mapping[str, Any] | None) -> dict[str, str]:
    if isinstance(manifest, Mapping):
        raw = manifest.get(MANIFEST_OVERRIDE_KEY)
        if isinstance(raw, Mapping):
            return {str(k): str(v) for k, v in raw.items()}
    return {}


def resolve_posture(code: str, *, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve the effective posture for a finding ``code``.

    Returns a dict with the effective ``posture`` plus provenance (``default``, ``floor``,
    ``cap``, ``requested`` per-repo value, ``retracted`` = a real downward move below the
    default, ``clamped_to_floor`` = an override that tried to go below the floor and was
    denied, ``category``). ``available`` is False when the contract lacks the registry.
    """
    reg = _registry()
    if reg is None:
        return {"posture": "warn", "default": "warn", "floor": "observe", "cap": None,
                "requested": None, "retracted": False, "clamped_to_floor": False,
                "category": "advisory", "available": False}
    entry = _class_entry(reg, code)
    default = str(entry.get("default_posture", "warn"))
    floor = str(entry.get("min_posture", "observe"))
    cap = entry.get("max_posture")
    cap = str(cap) if cap in _RUNG else None

    requested = _overrides(manifest).get(code)
    chosen = requested if requested in _RUNG else default

    effective = chosen
    clamped_to_floor = requested in _RUNG and _rank(requested) < _rank(floor)
    if cap and _rank(effective) > _rank(cap):
        effective = cap
    if _rank(effective) < _rank(floor):
        # NON-RETRACTABLE floor: a repo can never weaken below it -- and the floor wins
        # even over a mis-configured max_posture < min_posture registry entry.
        effective = floor

    # `retracted` reflects an ACTUAL downward move of the effective posture below the
    # default -- a floor-clamped attempt (effective unchanged) is NOT a retraction; it is
    # surfaced via `clamped_to_floor` instead.
    retracted = requested in _RUNG and _rank(effective) < _rank(default)
    return {"posture": effective, "default": default, "floor": floor, "cap": cap,
            "requested": requested, "retracted": bool(retracted),
            "clamped_to_floor": bool(clamped_to_floor),
            "category": str(entry.get("category", "advisory")), "available": True}


def retracting_overrides(manifest: Mapping[str, Any] | None) -> list[str]:
    """The finding codes whose per-repo override LOWERS the effective posture below its
    default -- de-fanging that must be surfaced even when that class fired no finding this
    scan. A floor-clamped attempt (effective unchanged) is not counted (see resolve_posture)."""
    if _registry() is None:
        return []
    out = [code for code in _overrides(manifest) if resolve_posture(code, manifest=manifest)["retracted"]]
    return sorted(set(out))


def posture_status(posture: str, *, mode: str) -> str:
    """Map a resolved posture + operator mode to a gate-status contribution:
    ``observe`` -> ``note`` (recorded, never warns/blocks); ``warn`` -> ``warn``;
    ``enforce`` -> ``warn`` unless the operator opted into ``hard`` -> ``blocked``.
    ``human_required`` is never implied at any rung."""
    if posture == "observe":
        return "note"
    if posture == "enforce" and mode == "hard":
        return "blocked"
    return "warn"
