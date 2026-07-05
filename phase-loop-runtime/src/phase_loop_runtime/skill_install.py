from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .skill_paths import HARNESS_DEFAULT_SKILL_ROOTS, current_harness, resolve_skill_bundle_root


REQUIRED_SKILLS: tuple[str, ...] = (
    "advisor-board",
    "execute-detailed",
    "execute-phase",
    "plan-phase",
    "plan-detailed",
    "phase-roadmap-builder",
    "phase-loop",
    "run-train",
    "skill-editor",
    "skill-improvement-planner",
    "task-contextualizer",
)

# Prior skill names kept resolvable as ALIASES so existing agent instructions do
# not break across a rename (ABDRESOLVE: advisor-panel -> advisor-board). The
# canonical installed skill is ``<harness>-<canonical>``; the alias installs the
# SAME skill under the historical prefixed name ``<harness>-<alias>`` so a
# maintainer's ``/<harness>-advisor-panel`` invocation resolves to the CURRENT
# canonical skill. The alias is installed FROM the canonical source on every run,
# so a reinstall refreshes it (and overwrites a stale pre-rename dir) rather than
# leaving it dangling. ``canonical_skill_name`` maps a typed alias back to the
# canonical name for callers that resolve by string.
SKILL_ALIASES: dict[str, str] = {
    "advisor-panel": "advisor-board",
}


def canonical_skill_name(name: str) -> str:
    """Map a (possibly aliased, possibly harness-prefixed) skill name to its
    canonical unprefixed skill name. ``advisor-panel`` and any
    ``<harness>-advisor-panel`` resolve to ``advisor-board``."""
    raw = (name or "").strip()
    for harness in ("claude", "codex", "gemini", "opencode"):
        prefix = f"{harness}-"
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return SKILL_ALIASES.get(raw, raw)


@dataclass(frozen=True)
class InstallAction:
    harness: str
    skill_name: str
    installed_name: str
    source: str
    destination: str
    mode: str
    action: str
    overlay: str | None = None


def install_skills(
    *,
    harness: str,
    source: Path,
    destination: Path | None = None,
    mode: str = "symlink",
    apply: bool = False,
    expand_body: bool = True,
) -> list[InstallAction]:
    normalized = current_harness(harness)
    if mode not in {"symlink", "copy"}:
        raise ValueError("mode must be 'symlink' or 'copy'")

    source_root = Path(source).expanduser().resolve()
    destination_root = Path(destination).expanduser() if destination else resolve_skill_bundle_root(normalized)
    _validate_bundle(source_root)

    actions: list[InstallAction] = []

    def _install_one(skill_name: str, source_skill: str, installed_name: str) -> None:
        source_dir = source_root / source_skill
        destination_dir = destination_root / installed_name
        overlay_dir = source_dir / "_overrides" / normalized
        overlay = str(overlay_dir) if overlay_dir.exists() else None
        action = _planned_action(source_dir, destination_dir, mode, overlay_dir if overlay else None)
        record = InstallAction(
            harness=normalized,
            skill_name=skill_name,
            installed_name=installed_name,
            source=str(source_dir),
            destination=str(destination_dir),
            mode=mode,
            action=action,
            overlay=overlay,
        )
        actions.append(record)
        if apply:
            _apply_action(source_dir, destination_dir, mode, installed_name, normalized, overlay_dir if overlay else None, expand_body=expand_body)

    for skill_name in REQUIRED_SKILLS:
        _install_one(skill_name, skill_name, f"{normalized}-{skill_name}")

    # Historical-name aliases: install the canonical skill a second time under the
    # prefixed alias name so ``/<harness>-advisor-panel`` resolves to today's
    # advisor-board. Installed FROM the canonical source, so each run refreshes the
    # alias (a stale pre-rename dir is overwritten, not orphaned).
    for alias, canonical in SKILL_ALIASES.items():
        _install_one(alias, canonical, f"{normalized}-{alias}")

    return actions


def actions_to_json(actions: list[InstallAction]) -> str:
    return json.dumps([asdict(action) for action in actions], indent=2, sort_keys=True)


def _validate_bundle(source_root: Path) -> None:
    missing = [name for name in REQUIRED_SKILLS if not (source_root / name / "SKILL.md").is_file()]
    if missing:
        raise FileNotFoundError(f"missing required phase-loop skills: {', '.join(missing)}")


def _planned_action(source_dir: Path, destination_dir: Path, mode: str, overlay_dir: Path | None) -> str:
    if destination_dir.is_symlink() and destination_dir.resolve() == source_dir and mode == "symlink" and overlay_dir is None:
        return "unchanged"
    if destination_dir.exists() or destination_dir.is_symlink():
        return "replace"
    return "create"


def _apply_action(source_dir: Path, destination_dir: Path, mode: str, installed_name: str, harness: str, overlay_dir: Path | None, *, expand_body: bool = True) -> None:
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    if destination_dir.is_symlink() or destination_dir.exists():
        if destination_dir.is_dir() and not destination_dir.is_symlink():
            shutil.rmtree(destination_dir)
        else:
            destination_dir.unlink()

    shutil.copytree(source_dir, destination_dir, ignore=shutil.ignore_patterns("_overrides"))
    if overlay_dir is not None:
        _copy_overlay(overlay_dir, destination_dir)
    _rewrite_skill_name(destination_dir / "SKILL.md", installed_name, harness, expand_body=expand_body)


def _copy_overlay(overlay_dir: Path, destination_dir: Path) -> None:
    for path in overlay_dir.rglob("*"):
        relative = path.relative_to(overlay_dir)
        target = destination_dir / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _rewrite_skill_name(path: Path, installed_name: str, harness: str, *, expand_body: bool = True) -> None:
    text = path.read_text(encoding="utf-8")
    # #26 item 2: the canonical bundle keeps skill-name references harness-neutral
    # as the ``<harness>-<skill>`` placeholder in prose (so the base collapses and
    # avoids per-harness override bloat). On the FINAL install to a harness's skill
    # root, re-expand it to the concrete per-harness form so the installed body
    # references its real sibling skills (e.g. ``claude-execute-phase``), not the
    # literal ``<harness>-execute-phase``. The package-data bundle build
    # (``sync_skills_bundle``) passes ``expand_body=False`` so the shipped bundle
    # stays harness-neutral (and the #12 drift guard stays byte-identical).
    if expand_body:
        text = text.replace("<harness>-", f"{harness}-")
    lines = text.splitlines()
    for index, line in enumerate(lines[:8]):
        if line.startswith("name: "):
            lines[index] = f"name: {installed_name}"
            break
    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
