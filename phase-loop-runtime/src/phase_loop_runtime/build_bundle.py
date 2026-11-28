from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .skill_install import REQUIRED_SKILLS


ACTIVE_HARNESSES: tuple[str, ...] = ("claude", "codex", "gemini", "opencode")

# Harness-agnostic auxiliary subdirectories carried verbatim into the neutral
# bundle so that `install` (which copytrees the whole skill dir) propagates them
# to every harness root. Without this, the SKILL Step 8 helper
# `scripts/validate_roadmap.py` never leaves the canonical source tree.
AUX_SUBDIRS: tuple[str, ...] = ("scripts", "assets")
# `references/` holds the prose a SKILL.md links for progressive disclosure
# (agent-harness#1358). A reference file is shared only when it is shared in fact:
# it goes into the neutral base when another harness's SKILL.md links it by its
# `references/<path>` without shipping its own copy, and otherwise into `_overrides/<harness>/references/`, so it
# reaches only the harness whose SKILL.md uses it. First-harness-wins into the base
# shipped Claude-only prose to every harness and would silently drop a second
# harness's own copy of the same file.
HARNESS_AUX_SUBDIRS: tuple[str, ...] = ("references",)
# Shared link grammar for `references/` and `assets/` links in a SKILL.md
# (agent-harness#1649). Used by both `build_bundle` (references placement) and
# `test_skills_canon_parity` (installed-bundle verification) so placement and
# parity checks always agree. Explicit Markdown inline destinations (`[doc](...)`
# including `<...>` with spaces and balanced `(...)` in filenames) and inline
# code spans (`` `...` ``) are parsed as complete tokens before bare prose
# scanning, so a partial filename prefix can never match inside an explicit link.
# Leading `./` / `../` segments are captured so parity rejects escaping or
# mixed-dot links (`.././references/../SKILL.md`) while
# `canonical_direct_aux_path` keeps them ineligible for shared placement.
_AUX_TARGET_PREFIX_RE = re.compile(r"^(?:\.\.?/)*(?:references|assets)/")
_INSTALLED_OWNER_FOLLOW_RE = re.compile(r"[ \t\r\n]+from the installed `([\w-]+)` directory")
SKILL_AUX_LINK_RE = re.compile(
    r"(?<![\w./+@~%-])((?:\.\.?/)*(?:references|assets)/[\w./+@~%-]*[\w+@~%-])"
    r"(?![\w/+@~%*<-]|\.[A-Za-z0-9_+@~%-])"
    r"(?:#[^\s`'\"<>()\[\]]+)?"
    r"`?(?:\s+from the installed `([\w-]+)` directory)?"
)


def _normalize_aux_target(raw: str) -> str | None:
    target = raw.split("#", 1)[0].strip()
    if not target or not _AUX_TARGET_PREFIX_RE.match(target):
        return None
    if target.endswith("/") or any(ch in target for ch in ("*", "<", ">", "\r", "\n")):
        return None
    # Strip a single benign leading `./` (`./references/a.md` -> `references/a.md`)
    # while keeping escaping or mixed-dot prefixes (`.././references/...`,
    # `./../references/...`, `././references/...`) intact for parity rejection.
    if target.startswith(("./references/", "./assets/")):
        target = target[2:]
    return target


def _skip_inline_ws(text: str, pos: int) -> int:
    n = len(text)
    while pos < n and text[pos] in " \t\r\n":
        pos += 1
    return pos


def _find_inline_code_close(text: str, start: int) -> tuple[int, int] | None:
    """Given ``text[start] == '`'``, return ``(content_start, end_after_ticks)`` or ``None``."""
    n = len(text)
    run_end = start
    while run_end < n and text[run_end] == "`":
        run_end += 1
    run_len = run_end - start
    line_start = text.rfind("\n", 0, start) + 1
    if run_len >= 3 and text[line_start:start].strip() == "":
        return None
    ticks = "`" * run_len
    close = text.find(ticks, run_end)
    while close != -1 and (
        (close > 0 and text[close - 1] == "`")
        or (close + run_len < n and text[close + run_len] == "`")
    ):
        close = text.find(ticks, close + 1)
    if close == -1 or "\n" in text[run_end:close] or "\x00" in text[run_end:close]:
        return None
    return run_end, close + run_len


def _find_matching_bracket(text: str, start: int) -> int | None:
    n = len(text)
    depth = 1
    pos = start + 1
    while pos < n:
        ch = text[pos]
        if ch == "\\" and pos + 1 < n:
            pos += 2
            continue
        if ch == "\n" and pos + 1 < n and text[pos + 1] == "\n":
            return None
        if ch == "`":
            span = _find_inline_code_close(text, pos)
            if span is not None:
                pos = span[1]
                continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return None


def _parse_inline_dest(text: str, open_paren: int) -> tuple[str, int] | None:
    n = len(text)
    pos = _skip_inline_ws(text, open_paren + 1)
    if pos >= n:
        return None
    if text[pos] == "<":
        pos += 1
        start = pos
        while pos < n and text[pos] not in ">\n<":
            if text[pos] == "\\" and pos + 1 < n and text[pos + 1] != "\n":
                pos += 2
            else:
                pos += 1
        if pos >= n or text[pos] != ">":
            return None
        dest = text[start:pos]
        pos += 1
    else:
        start = pos
        depth = 0
        while pos < n:
            ch = text[pos]
            if ch in " \t\r\n":
                break
            if ch == "\\" and pos + 1 < n and text[pos + 1] != "\n":
                pos += 2
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            pos += 1
        if depth != 0 or pos == start:
            return None
        dest = text[start:pos]
    ws_start = pos
    pos = _skip_inline_ws(text, pos)
    if pos < n and text[pos] == ")":
        return dest, pos + 1
    if pos == ws_start or pos >= n:
        return None
    quote = text[pos]
    if quote in ("\"", "'"):
        pos += 1
        while pos < n and text[pos] != quote:
            if text[pos] == "\\" and pos + 1 < n:
                pos += 2
            elif text[pos] == "\n":
                return None
            else:
                pos += 1
        if pos >= n:
            return None
        pos += 1
    elif quote == "(":
        pos += 1
        while pos < n and text[pos] != ")":
            if text[pos] == "\\" and pos + 1 < n:
                pos += 2
            elif text[pos] in "(\n":
                return None
            else:
                pos += 1
        if pos >= n:
            return None
        pos += 1
    else:
        return None
    pos = _skip_inline_ws(text, pos)
    if pos >= n or text[pos] != ")":
        return None
    return dest, pos + 1


def iter_skill_aux_links(text: str) -> list[tuple[str, str]]:
    """Return sorted unique `(rel_path, owner)` pairs for `references/` and `assets/` links."""
    links: set[tuple[str, str]] = set()
    chars = list(text)
    n = len(text)

    # Pass 1: explicit Markdown inline links `[label](dest [title])`, skipping
    # inline code spans so a `[` inside backticks cannot start a link.
    i = 0
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == "`":
            span = _find_inline_code_close(text, i)
            if span is not None:
                i = span[1]
                continue
            run_end = i
            while run_end < n and text[run_end] == "`":
                run_end += 1
            i = run_end
            continue
        if text[i] == "[":
            close_bracket = _find_matching_bracket(text, i)
            if close_bracket is not None and close_bracket + 1 < n and text[close_bracket + 1] == "(":
                parsed = _parse_inline_dest(text, close_bracket + 1)
                if parsed is not None:
                    dest, end = parsed
                    owner_m = _INSTALLED_OWNER_FOLLOW_RE.match(text, end)
                    owner = owner_m.group(1) if owner_m else ""
                    rel = _normalize_aux_target(dest)
                    if rel is not None:
                        links.add((rel, owner))
                    for k in range(i, end):
                        chars[k] = "\x00"
                    i = end
                    continue
        i += 1

    masked = "".join(chars)

    # Pass 2: standalone inline code spans whose content begins with an aux path
    # prefix (e.g. `` `references/foo bar.md` ``, `` `references/foo(bar).md` ``,
    # `` `references/<file>` ``). Leave non-aux spans (such as skill names in
    # ``from the installed `<skill>` directory`` and shell command spans like
    # `` `cat references/foo.md` ``) unmasked for Pass 3.
    chars = list(masked)
    i = 0
    while i < n:
        if masked[i] == "`":
            span = _find_inline_code_close(masked, i)
            if span is not None:
                content_start, end = span
                run_len = content_start - i
                content = masked[content_start : end - run_len]
                if _AUX_TARGET_PREFIX_RE.match(content.strip()):
                    owner_m = _INSTALLED_OWNER_FOLLOW_RE.match(masked, end)
                    owner = owner_m.group(1) if owner_m else ""
                    rel = _normalize_aux_target(content)
                    if rel is not None:
                        links.add((rel, owner))
                    for k in range(i, end):
                        chars[k] = "\x00"
                i = end
                continue
            run_end = i
            while run_end < n and masked[run_end] == "`":
                run_end += 1
            i = run_end
            continue
        i += 1

    masked = "".join(chars)

    # Pass 3: remaining bare prose paths outside explicit Markdown/code tokens.
    for rel, owner in SKILL_AUX_LINK_RE.findall(masked):
        norm = _normalize_aux_target(rel)
        if norm is not None:
            links.add((norm, owner))

    return sorted(links)


def canonical_direct_aux_path(rel: str) -> str | None:
    """Return `rel` if it names a direct child of `references/` or `assets/` in canonical form.

    Rejects backslashes, `.` / `..` segments, empty segments (`//`), and nested
    subdirectories so placement (`build_bundle`) and parity verification
    (`test_skills_canon_parity`) interpret paths identically (agent-harness#1649).
    """
    if "\\" in rel:
        return None
    parts = rel.split("/")
    if len(parts) != 2 or parts[0] not in ("references", "assets") or parts[1] in ("", ".", ".."):
        return None
    return rel


def linked_own_aux_paths(text: str, *, skill_name: str) -> set[str]:
    """Return canonical direct `references/` / `assets/` paths in `text` owned by `skill_name`.

    Links qualified with ``from the installed `<other-skill>` directory`` belong to
    `<other-skill>` rather than `skill_name` (unless `<other-skill> == skill_name`).
    Non-canonical or escaping paths (e.g. `references/./a.md`, `references//a.md`,
    `../references/a.md`) are excluded.
    """
    owned: set[str] = set()
    for rel, owner in iter_skill_aux_links(text):
        if owner and owner != skill_name:
            continue
        canonical = canonical_direct_aux_path(rel)
        if canonical is not None:
            owned.add(canonical)
    return owned
# IF-0-CANON-1: the canonical phase-loop skill sources now live IN this repo
# under `skills-src/<harness>/` (one tree per active harness, each holding
# `<harness>-<skill>/` dirs). `build_bundle` consumes these to produce the
# committed `phase-loop-skills/` bundle with NO dotfiles checkout required.
# The fleet's `bootstrap.sh` may still override these with an explicit
# `--source <dotfiles-root>` during the cutover; that path keeps working.
DEFAULT_SOURCES: dict[str, str] = {
    "claude": "skills-src/claude",
    "codex": "skills-src/codex",
    "gemini": "skills-src/gemini",
    "opencode": "skills-src/opencode",
}
OVERRIDE_README = "Harness-specific overlay files for this workflow skill.\n"

# Concrete, harness-SPECIFIC literals that must survive neutralization verbatim.
# `_neutralize_skill` collapses every `<harness>-`/`<harness> `/`<harness>_`/
# `<harness>.`/`Harness` token so the shared base + per-harness overrides read
# the same across harnesses. That is correct for harness-VARIANT tokens (skill
# names like `claude-execute-phase`, config dirs like `claude-config`, install
# paths) — they genuinely change per harness. It is WRONG for concrete Claude
# identifiers that name one real thing and have no per-harness variant: an Opus
# model id is `claude-opus-4-8` for every harness, and `<harness>-in-chrome`
# denotes nothing (the tool is `claude-in-chrome`; no `codex-in-chrome` exists).
# Membership test: "if this skill installed for codex, would the token need to
# become `codex-X`?" Yes -> collapse (NOT here). No, it's Claude-specific by
# nature -> preserve (here). These are masked to a sentinel before the collapse
# regexes run and restored after, so the literal ships intact into the installed
# bundle. Applied uniformly to base + overrides so cross-vendor advisor-board
# identities remain concrete regardless of which harness supplied the base.
PRESERVE_LITERALS: tuple[str, ...] = (
    # claude-opus-4-8 RETIRED from the skill bundle (design-model-tier-taxonomy.md):
    # the skills now name claude-opus-5 (frontier + planning) / claude-opus-5-5 (review;
    # replaced Fable as every default 2026-09-23, Fable remaining an explicit id). The
    # install-output gate requires every entry here to actually appear in the bundle,
    # so a retired id must leave this tuple.
    # Order between these two is NOT load-bearing (executed over every skills-src
    # SKILL.md: swapping them is byte-identical, because the `claude-opus-5` sentinel
    # masks the prefix and no collapse regex touches the trailing `-5`). Dropping BOTH
    # corrupts output. `claude-opus-5-5` is listed for the presence gate and literal lint.
    "claude-opus-5-5",  # model-id-source: verbatim literal preserved through brand-collapse (ultra tier + review default)
    "claude-opus-5",  # model-id-source: verbatim literal preserved through brand-collapse (heavy tier)
    "claude-fable-5-1",  # model-id-source: verbatim literal preserved through brand-collapse (explicit, non-default id)
    "claude-sonnet-5",  # model-id-source: verbatim literal preserved through brand-collapse
    "claude-haiku-4-5-20251001",  # model-id-source: verbatim literal preserved through brand-collapse (lite tier, DATED pin)
    "gemini-4-neon",  # model-id-source: cross-vendor advisor-board default, never a harness placeholder
    "gemini-4-argon",  # model-id-source: cross-vendor advisor-board explicit seat (the prior default)
    "gemini-3.8-flash",  # model-id-source: cross-vendor advisor-board explicit seat (an earlier default)
    "claude-in-chrome",
    # Cross-vendor advisor-board display names are concrete model identities, not
    # prose about the harness currently installing the skill. Preserve them so a
    # Claude/Gemini source cannot become the nonexistent "Harness Opus/Flash".
    "Claude Opus 5.5",
    "Gemini 4 NEON",
    "Gemini 4 Argon",
    # Display-name model form as it appears in the `Co-Authored-By:` git trailer.
    # Without this the brand collapse (`Claude` -> `Harness`) rewrites the trailer
    # to `Harness Opus 4.8` — a concrete model attribution corrupted into a name
    # that denotes nothing. One real model, no per-harness variant -> preserve.
    "Claude Opus 4.8",
    # The host product name. Without this the brand collapse rewrites every
    # "under Claude Code" / "Claude Code -> claude cell" in the Claude-authored
    # skills to "Harness Code", which denotes nothing on any harness.
    "Claude Code",
)
_PRESERVE_SENTINEL = "\x00PRESERVE{index}\x00"


@dataclass(frozen=True)
class BuildWarning:
    skill: str
    message: str
    harness: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class SkippedSkill:
    skill: str
    missing_harnesses: tuple[str, ...]


@dataclass(frozen=True)
class BuildResult:
    skills_regenerated: list[str] = field(default_factory=list)
    overrides_written: list[str] = field(default_factory=list)
    skills_skipped: list[SkippedSkill] = field(default_factory=list)
    warnings: list[BuildWarning] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    dry_run: bool = False
    applied: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "skills_regenerated": self.skills_regenerated,
            "overrides_written": self.overrides_written,
            "skills_skipped": [asdict(skill) for skill in self.skills_skipped],
            "warnings": [asdict(warning) for warning in self.warnings],
            "files_written": self.files_written,
            "dry_run": self.dry_run,
            "applied": self.applied,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def build_bundle(
    sources: Sequence[Path | str] | Mapping[str, Path | str] | None,
    destination: Path | str,
    *,
    dry_run: bool,
    apply: bool,
    force: bool = False,
) -> BuildResult:
    source_roots = _normalize_sources(sources)
    destination_root = Path(destination)
    effective_apply = bool(apply and not dry_run)

    skills_regenerated: list[str] = []
    overrides_written: list[str] = []
    skills_skipped: list[SkippedSkill] = []
    warnings: list[BuildWarning] = []
    files_written: list[str] = []

    for skill in REQUIRED_SKILLS:
        canonical_paths = {
            harness: root / f"{harness}-{skill}" / "SKILL.md"
            for harness, root in source_roots.items()
        }
        missing = tuple(
            harness for harness in ACTIVE_HARNESSES if not canonical_paths[harness].is_file()
        )
        if missing:
            skills_skipped.append(SkippedSkill(skill=skill, missing_harnesses=missing))
            warnings.append(
                BuildWarning(
                    skill=skill,
                    message=f"missing canonical SKILL.md for {', '.join(missing)}",
                )
            )
            continue

        neutral_base = _neutralize_skill(
            canonical_paths["codex"].read_text(encoding="utf-8"),
            harness="codex",
            skill=skill,
        )
        skill_dir = destination_root / skill
        base_path = skill_dir / "SKILL.md"
        if _record_write(base_path, neutral_base, dry_run=dry_run, apply=effective_apply, force=force):
            skills_regenerated.append(skill)
            files_written.append(base_path.as_posix())

        # Carry harness-agnostic auxiliary subdirs (scripts/, assets/) into the
        # neutral bundle. Source from the first harness whose
        # canonical dir provides each subdir (ACTIVE_HARNESSES order), since the
        # content is shared, not harness-specific.
        for aux in AUX_SUBDIRS:
            source_aux = next(
                (
                    canonical_paths[harness].parent / aux
                    for harness in ACTIVE_HARNESSES
                    if (canonical_paths[harness].parent / aux).is_dir()
                ),
                None,
            )
            if source_aux is None:
                continue
            for src_file in _aux_files(source_aux):
                target = skill_dir / aux / src_file.relative_to(source_aux)
                files_written.append(target.as_posix())
                if effective_apply:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, target)

        skill_texts = {harness: path.read_text(encoding="utf-8") for harness, path in canonical_paths.items()}
        linked_aux_by_harness = {
            harness: linked_own_aux_paths(text, skill_name=f"{harness}-{skill}")
            for harness, text in skill_texts.items()
        }
        shared_refs: set[str] = set()
        if effective_apply:
            # Only this loop writes these dirs. Clear them so a file whose placement
            # flips (shared <-> override) leaves no stale copy behind.
            for aux in HARNESS_AUX_SUBDIRS:
                for generated in [skill_dir / aux] + [skill_dir / "_overrides" / h / aux for h in ACTIVE_HARNESSES]:
                    shutil.rmtree(generated, ignore_errors=True)
        for harness in ACTIVE_HARNESSES:
            for aux in HARNESS_AUX_SUBDIRS:
                source_aux = canonical_paths[harness].parent / aux
                for src_file in _aux_files(source_aux):
                    rel = src_file.relative_to(source_aux).as_posix()
                    link = f"{aux}/{rel}"
                    # Only a harness that links the file (as its own skill's reference
                    # under the shared link grammar) but ships no copy of its own needs
                    # the shared one.
                    linked_elsewhere = any(
                        link in linked_aux_by_harness[other]
                        and not (canonical_paths[other].parent / link).is_file()
                        for other in ACTIVE_HARNESSES
                        if other != harness
                    )
                    if linked_elsewhere and link not in shared_refs:
                        shared_refs.add(link)
                        target = skill_dir / aux / rel
                    else:
                        target = skill_dir / "_overrides" / harness / aux / rel
                    files_written.append(target.as_posix())
                    if effective_apply:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_file, target)

        for harness in ACTIVE_HARNESSES:
            readme_path = skill_dir / "_overrides" / harness / "README.md"
            if _record_write(readme_path, OVERRIDE_README, dry_run=dry_run, apply=effective_apply, force=force):
                files_written.append(readme_path.as_posix())

        for harness in ACTIVE_HARNESSES:
            if harness == "codex":
                override_text = None
            else:
                candidate = _neutralize_skill(
                    canonical_paths[harness].read_text(encoding="utf-8"),
                    harness=harness,
                    skill=skill,
                )
                override_text = candidate if candidate != neutral_base else None
            override_path = skill_dir / "_overrides" / harness / "SKILL.md"
            if override_text is None:
                if override_path.exists() and (dry_run or effective_apply):
                    overrides_written.append(override_path.as_posix())
                    files_written.append(override_path.as_posix())
                    if effective_apply:
                        override_path.unlink()
                continue
            if _record_write(override_path, override_text, dry_run=dry_run, apply=effective_apply, force=force):
                overrides_written.append(override_path.as_posix())
                files_written.append(override_path.as_posix())

    return BuildResult(
        skills_regenerated=skills_regenerated,
        overrides_written=overrides_written,
        skills_skipped=skills_skipped,
        warnings=warnings,
        files_written=files_written,
        dry_run=bool(dry_run),
        applied=effective_apply,
    )


def _aux_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


def _normalize_sources(
    sources: Sequence[Path | str] | Mapping[str, Path | str] | None,
) -> dict[str, Path]:
    if sources is None:
        return {harness: Path(path) for harness, path in DEFAULT_SOURCES.items()}
    if isinstance(sources, Mapping):
        roots = {str(harness): Path(path) for harness, path in sources.items()}
    else:
        roots = {}
        for raw in sources:
            path = Path(raw)
            harness = _infer_harness(path)
            if harness in roots:
                raise ValueError(f"duplicate source root for {harness}: {path}")
            roots[harness] = path
    missing = [harness for harness in ACTIVE_HARNESSES if harness not in roots]
    if missing:
        raise ValueError(f"missing source root for {', '.join(missing)}")
    unknown = [harness for harness in roots if harness not in ACTIVE_HARNESSES]
    if unknown:
        raise ValueError(f"unknown source harness {', '.join(sorted(unknown))}")
    return {harness: roots[harness] for harness in ACTIVE_HARNESSES}


def _infer_harness(path: Path) -> str:
    text = path.as_posix()
    for harness in ACTIVE_HARNESSES:
        if re.search(rf"(^|[-_/]){re.escape(harness)}($|[-_/])", text):
            return harness
    raise ValueError(f"cannot infer harness from source root: {path}")


def _neutralize_skill(text: str, *, harness: str, skill: str) -> str:
    output = text
    # Mask concrete harness-specific literals so the collapse regexes below cannot
    # corrupt them (e.g. `claude-opus-4-8` -> `<harness>-opus-4-8`). Restored verbatim
    # at the end. See PRESERVE_LITERALS.
    for index, literal in enumerate(PRESERVE_LITERALS):
        output = output.replace(literal, _PRESERVE_SENTINEL.format(index=index))
    output = re.sub(
        rf"(?m)^name:\s+{re.escape(harness)}-{re.escape(skill)}\s*$",
        f"name: {skill}",
        output,
        count=1,
    )
    output = re.sub(rf"\b{re.escape(harness)}-", "<harness>-", output)
    output = re.sub(rf"\b{re.escape(harness)} ", "<harness> ", output)
    output = re.sub(rf"\b{re.escape(harness)}_", "<harness>_", output)
    output = re.sub(rf"\b{re.escape(harness)}\.", "<harness>.", output)
    title = harness.capitalize()
    output = re.sub(rf"\b{re.escape(title)}\b", "Harness", output)
    output = output.replace(
        "Executes one detailed plan artifact produced by `<harness>-plan-detailed`. Use this\n"
        "when one Harness thread should implement a bounded plan end to end without phase\n"
        "lanes or cross-harness dispatch.",
        "Executes one detailed plan artifact produced by `<harness>-plan-detailed`. Use\n"
        "this when one Harness thread should implement a bounded plan end to end without\n"
        "phase lanes or cross-harness dispatch.",
    )
    output = output.replace(
        "- Optionally read `.dev-skills/handoffs/<harness>-plan-detailed/latest.md` when no\n"
        "  explicit plan path is supplied, and only trust it if `from:` is",
        "- Optionally read `.dev-skills/handoffs/<harness>-plan-detailed/latest.md`\n"
        "  when no explicit plan path is supplied, and only trust it if `from:` is",
    )
    # Restore the masked harness-specific literals verbatim.
    for index, literal in enumerate(PRESERVE_LITERALS):
        output = output.replace(_PRESERVE_SENTINEL.format(index=index), literal)
    return output


def _record_write(path: Path, content: str, *, dry_run: bool, apply: bool, force: bool) -> bool:
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    changed = current != content
    should_write = changed or (force and apply)
    if dry_run:
        return changed or force
    if not apply or not should_write:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True
