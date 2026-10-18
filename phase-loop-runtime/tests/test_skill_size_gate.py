"""Size gate for the canonical skill sources (agent-harness#1358).

The Agent Skills specification asks for a ``SKILL.md`` body under about 5,000
tokens and 500 lines, with detail moved into ``references/`` or ``assets/`` and
loaded on demand. Every ``skills-src/<harness>/<skill>/SKILL.md`` is measured on
three axes:

- ``tokens``: whole-file characters / 4 (the estimate the issue's table uses),
  limit ``MAX_TOKENS``.
- ``lines``: line count, limit ``MAX_LINES``.
- ``long_line``: the longest single line in characters, limit ``MAX_LINE_CHARS``.
  Line counts alone understate the size: ``codex-execute-phase`` is under 300
  lines but over 9,000 tokens because single paragraphs run past 2,000 chars.

Ratchet. ``ALLOWLIST`` records each current offender with the value it had when
it was recorded. An allowlisted offender warns. An allowlisted offender that has
dropped under the limit fails, so the entry is deleted in the PR that fixed it.
An offender missing from the allowlist (new, or grown past its recorded value)
warns while ``STRICT`` is ``False`` and fails once it is ``True``; flipping
``STRICT`` is the one-line change that turns this into a hard gate.

Print the current measurements with::

    python phase-loop-runtime/tests/test_skill_size_gate.py
"""
from __future__ import annotations

import tempfile
import unittest
import warnings
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS_SRC = REPO / "skills-src"

MAX_TOKENS = 5_000
MAX_LINES = 500
MAX_LINE_CHARS = 1_000
CHARS_PER_TOKEN = 4

# Warn-first rollout: unlisted offenders warn today. Set to True to make them fail.
STRICT = False

# (repo-relative SKILL.md path, check) -> value recorded when the entry was added.
# Delete an entry when its skill drops under the limit; the gate fails until you do.
ALLOWLIST: dict[tuple[str, str], int] = {
    ("skills-src/claude/claude-advisor-board/SKILL.md", "long_line"): 1530,
    # execute-phase / execute-detailed: recorded after agent-harness#1548; split in a follow-up (agent-harness#1358).
    ("skills-src/claude/claude-execute-phase/SKILL.md", "tokens"): 6386,
    ("skills-src/claude/claude-execute-phase/SKILL.md", "long_line"): 1019,
    ("skills-src/claude/claude-phase-roadmap-builder/SKILL.md", "tokens"): 6048,
    # Split in agent-harness#1358; what remains is test-pinned normative text.
    ("skills-src/claude/claude-plan-phase/SKILL.md", "tokens"): 7783,
    # Interactive procedures split; runner/governance/closeout and pinned text stay inline.
    ("skills-src/codex/codex-execute-phase/SKILL.md", "tokens"): 8023,
    ("skills-src/codex/codex-plan-phase/SKILL.md", "tokens"): 6675,
    ("skills-src/codex/codex-plan-phase/SKILL.md", "long_line"): 1065,
    ("skills-src/gemini/gemini-plan-phase/SKILL.md", "long_line"): 1066,
    ("skills-src/opencode/opencode-plan-phase/SKILL.md", "long_line"): 1068,
}


@dataclass(frozen=True)
class SizeFinding:
    path: str
    check: str
    value: int
    limit: int
    line: int | None = None

    def describe(self) -> str:
        where = f":{self.line}" if self.line is not None else ""
        return f"{self.path}{where}: {self.check} {self.value} > {self.limit}"


def measure(text: str) -> dict[str, tuple[int, int | None]]:
    """Return ``{check: (value, line_number_or_None)}`` for one SKILL.md text."""
    lines = text.splitlines()
    longest, longest_at = 0, None
    for number, line in enumerate(lines, start=1):
        if len(line) > longest:
            longest, longest_at = len(line), number
    return {
        "tokens": (len(text) // CHARS_PER_TOKEN, None),
        "lines": (len(lines), None),
        "long_line": (longest, longest_at),
    }


LIMITS = {"tokens": MAX_TOKENS, "lines": MAX_LINES, "long_line": MAX_LINE_CHARS}


def skill_findings(path: Path, label: str) -> list[SizeFinding]:
    findings = []
    for check, (value, line) in measure(path.read_text(encoding="utf-8")).items():
        if value > LIMITS[check]:
            findings.append(SizeFinding(label, check, value, LIMITS[check], line))
    return findings


def canonical_skill_files(root: Path = SKILLS_SRC) -> list[Path]:
    return sorted(root.glob("*/*/SKILL.md"))


def evaluate(
    findings: list[SizeFinding],
    allowlist: dict[tuple[str, str], int],
    *,
    strict: bool,
) -> tuple[list[str], list[str]]:
    """Split findings into ``(warnings, errors)`` under the ratchet rules."""
    warned: list[str] = []
    errors: list[str] = []
    seen = set()
    for finding in findings:
        key = (finding.path, finding.check)
        seen.add(key)
        recorded = allowlist.get(key)
        if recorded is not None and finding.value <= recorded:
            warned.append(f"{finding.describe()} (allowlisted at {recorded})")
            continue
        reason = "not allowlisted" if recorded is None else f"grew past allowlisted {recorded}"
        message = f"{finding.describe()} ({reason})"
        (errors if strict else warned).append(message)
    for key in sorted(set(allowlist) - seen):
        errors.append(f"{key[0]}: {key[1]} is now within the limit; delete its ALLOWLIST entry")
    return warned, errors


def all_findings() -> list[SizeFinding]:
    findings = []
    for path in canonical_skill_files():
        findings.extend(skill_findings(path, path.relative_to(REPO).as_posix()))
    return findings


# Key the skip on the layout, not on the files: the standalone Gate A tree runs the
# installed wheel against a sparse skills-src, while a source checkout imports this
# tree's src/, where the full skills-src is present and must be measured.
def _source_checkout() -> bool:
    import phase_loop_runtime

    return Path(phase_loop_runtime.__file__).resolve().is_relative_to(REPO / "phase-loop-runtime" / "src")


_NEEDS_SOURCE_TREE = unittest.skipUnless(
    _source_checkout(), "measures the full skills-src tree; the standalone tree carries a sparse copy"
)


class SkillSizeGateTest(unittest.TestCase):
    @_NEEDS_SOURCE_TREE
    def test_canonical_skills_within_size_guidance_or_allowlisted(self):
        self.assertTrue(canonical_skill_files(), "no skills-src/*/*/SKILL.md found")
        warned, errors = evaluate(all_findings(), ALLOWLIST, strict=STRICT)
        for message in warned:
            warnings.warn(f"skill size: {message}", UserWarning, stacklevel=1)
        self.assertEqual(errors, [], "\n".join(errors))

    @_NEEDS_SOURCE_TREE
    def test_allowlist_paths_exist(self):
        for path, check in ALLOWLIST:
            self.assertTrue((REPO / path).is_file(), f"ALLOWLIST names a missing file: {path}")
            self.assertIn(check, LIMITS)

    def test_negative_control_over_limit_fixture_trips_every_check(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "claude" / "claude-oversize" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            body = ["---", "name: claude-oversize", "description: fixture", "---"]
            body += [f"line {n}: " + "x" * 40 for n in range(600)]
            body.insert(10, "y" * (MAX_LINE_CHARS + 1))
            skill.write_text("\n".join(body) + "\n", encoding="utf-8")

            self.assertEqual(canonical_skill_files(Path(td)), [skill])
            findings = skill_findings(skill, "fixture/SKILL.md")
            by_check = {finding.check: finding for finding in findings}
            self.assertEqual(set(by_check), {"tokens", "lines", "long_line"})
            self.assertEqual(by_check["long_line"].line, 11)

            # Unlisted: warns while not strict, fails once strict.
            warned, errors = evaluate(findings, {}, strict=False)
            self.assertEqual((len(warned), errors), (3, []))
            warned, errors = evaluate(findings, {}, strict=True)
            self.assertEqual((warned, len(errors)), ([], 3))

            # Allowlisted at its current size: warns even when strict.
            recorded = {("fixture/SKILL.md", f.check): f.value for f in findings}
            warned, errors = evaluate(findings, recorded, strict=True)
            self.assertEqual((len(warned), errors), (3, []))

            # Grown past the recorded value: treated as unlisted.
            shrunk = {key: value - 1 for key, value in recorded.items()}
            _, errors = evaluate(findings, shrunk, strict=True)
            self.assertEqual(len(errors), 3)

    def test_negative_control_stale_allowlist_entry_fails(self):
        _, errors = evaluate([], {("fixture/SKILL.md", "tokens"): 9000}, strict=False)
        self.assertEqual(len(errors), 1)
        self.assertIn("delete its ALLOWLIST entry", errors[0])

    def test_within_limit_fixture_is_clean(self):
        text = "---\nname: small\n---\n" + "short line\n" * 50
        self.assertTrue(all(value <= LIMITS[check] for check, (value, _) in measure(text).items()))


def _report() -> int:
    print(f"{'tokens':>7} {'lines':>6} {'longest':>8}  path")
    for path in canonical_skill_files():
        sizes = measure(path.read_text(encoding="utf-8"))
        print(
            f"{sizes['tokens'][0]:>7} {sizes['lines'][0]:>6} {sizes['long_line'][0]:>8}  "
            f"{path.relative_to(REPO).as_posix()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_report())
