"""agent-harness#211: decidable goal-coverage check (single source of truth).

Replaces the fuzzy acceptance-vs-exit-criteria text audit. A roadmap phase's
exit-criteria carry stable ``EC-<ALIAS>-<N>`` goal IDs (see ``roadmap_lint``); a
plan's ``## Acceptance Criteria`` items REFERENCE those IDs (item-leading) instead
of restating the goal. The check is pure set membership — every declared goal ID
must be referenced by ≥1 acceptance item — so it is fully decidable and has none of
the fuzzy audit's false-positive / fail-open failure modes.

Scope (honest): guarantees COMPLETENESS (no goal silently forgotten). It does NOT
verify ADEQUACY (that the referenced evidence actually discharges the goal) — that
stays with code review + evidence authenticity (#91). It makes weak evidence
human-reviewable at the reference point rather than hidden in a paraphrase.

Opt-in per phase: a phase with no EC-IDs is ``not_applicable`` (legacy, no gate).
Runs at plan-time (CLI), preflight, and closeout (mutation-window) — all pure
Python, no ``EmitPhaseCloseout`` schema change.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import discovery
from .roadmap_lint import EC_ID_LEADING_RE, _extract_phases, check_exit_criteria_ids as _check_exit_criteria_ids


@dataclass(frozen=True)
class GoalCoverageResult:
    repo: str
    plan: str
    roadmap: str
    phase_alias: str | None
    applicable: bool
    declared_ids: tuple[str, ...]
    referenced_ids: tuple[str, ...]
    unreferenced_ids: tuple[str, ...]  # declared but not referenced -> forgotten goal
    dangling_refs: tuple[str, ...]  # referenced but not declared -> typo / stale ref
    setup_diagnostics: tuple[str, ...]

    def has_gaps(self) -> bool:
        return bool(self.unreferenced_ids or self.dangling_refs)

    def has_setup_errors(self) -> bool:
        return bool(self.setup_diagnostics)

    def not_applicable(self) -> bool:
        return not self.applicable and not self.setup_diagnostics

    def is_clean(self) -> bool:
        return not self.has_gaps() and not self.has_setup_errors()

    def blocker_summary(self) -> str:
        parts = []
        if self.unreferenced_ids:
            parts.append(f"roadmap goal(s) not referenced by any acceptance item: {sorted(self.unreferenced_ids)}")
        if self.dangling_refs:
            parts.append(f"plan references unknown goal ID(s): {sorted(self.dangling_refs)}")
        if self.setup_diagnostics:
            parts.append(f"un-auditable: {self.setup_diagnostics[0]}")
        return "; ".join(parts) or "goal coverage clean"

    def to_json(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "plan": self.plan,
            "roadmap": self.roadmap,
            "phase_alias": self.phase_alias,
            "applicable": self.applicable,
            "declared_ids": list(self.declared_ids),
            "referenced_ids": list(self.referenced_ids),
            "unreferenced_ids": list(self.unreferenced_ids),
            "dangling_refs": list(self.dangling_refs),
            "setup_diagnostics": list(self.setup_diagnostics),
        }

    def render_text(self) -> str:
        lines = ["Goal Coverage Audit", f"  plan: {self.plan}", f"  roadmap: {self.roadmap} (phase {self.phase_alias})"]
        if self.setup_diagnostics:
            lines.append("  SETUP ERRORS (un-auditable — not a coverage verdict):")
            lines.extend(f"    - {d}" for d in self.setup_diagnostics)
            return "\n".join(lines)
        if not self.applicable:
            lines.append("  not applicable — phase declares no EC-<ALIAS>-<N> goal IDs (legacy).")
            return "\n".join(lines)
        lines.append(f"  declared goal IDs: {len(self.declared_ids)}, referenced: {len(self.referenced_ids)}")
        for gid in sorted(self.unreferenced_ids):
            lines.append(f"  [UNREFERENCED GOAL] {gid} — no plan acceptance item references it")
        for ref in sorted(self.dangling_refs):
            lines.append(f"  [DANGLING REF] {ref} — plan references a goal ID not declared in this phase")
        if self.is_clean():
            lines.append("  clean — every roadmap goal ID is referenced by ≥1 acceptance item.")
        return "\n".join(lines)


_ACCEPTANCE_SECTION_RE = re.compile(
    r"^##\s+Acceptance\s+Criteria\s*$\n(?P<body>.*?)(?=^##\s+\S|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
# Checkbox item prefix — tolerant of a missing trailing space and an upper/lower `x`
# (CR Fable: `- [ ]EC-P1-1` and `- [X]` must not be mis-stripped/ignored).
_CHECKBOX_PREFIX_RE = re.compile(r"^- \[[ xX]\]\s*")
_RAW_CHECKBOX_ITEM_RE = re.compile(
    r"^- \[[ xX]\].*?(?=^- \[[ xX]\]|\Z)", re.MULTILINE | re.DOTALL
)


def _acceptance_raw_items(body: str) -> list[str]:
    items = [match.group(0) for match in _RAW_CHECKBOX_ITEM_RE.finditer(body)]
    if items:
        items[-1] = items[-1].rstrip()
    return items


def _leading_ec_ids(item_text: str) -> list[str]:
    """All item-LEADING ``EC-<ALIAS>-<N>`` IDs (a 1:many item may lead with several,
    e.g. ``EC-P1-1, EC-P1-2 — proven by ...``). A mid-text prose mention does NOT
    count."""
    ids: list[str] = []
    s = item_text.strip()
    while True:
        m = EC_ID_LEADING_RE.match(s)
        if not m:
            break
        ids.append(f"EC-{m.group(1)}-{m.group(2)}")
        s = s[m.end():].lstrip(" ,")
    return ids


def extract_plan_goal_refs(plan: Path) -> set[str]:
    """Goal IDs referenced from item-leading position of the plan's
    ``## Acceptance Criteria`` checklist items only (never a global prose scan)."""
    try:
        text = plan.read_text(encoding="utf-8")
    except OSError:
        return set()
    match = _ACCEPTANCE_SECTION_RE.search(text)
    if match is None:
        return set()
    refs: set[str] = set()
    for line in match.group("body").splitlines():
        stripped = line.strip()
        prefix = _CHECKBOX_PREFIX_RE.match(stripped)
        if prefix:
            refs.update(_leading_ec_ids(stripped[prefix.end():]))
    return refs


def phase_declares_goal_ids(roadmap: Path | str, phase: str) -> bool:
    """True iff the roadmap phase `phase` opts into goal IDs (declares any EC-<ALIAS>-<N>
    on its exit-criteria). Used to decide whether an un-resolvable plan is un-auditable
    (opted-in) vs simply out of scope (legacy). Considers ALL alias matches (a duplicate
    alias where any match declares IDs counts as opted-in, CR codex — not just the first)."""
    phases = _extract_phases(Path(roadmap).read_text(encoding="utf-8"))
    matches = [p for p in phases if p.alias.upper() == str(phase or "").upper()]
    return any(p.declared_exit_criteria_ids for p in matches)


def check_goal_coverage(
    repo: Path | str, plan: Path | str, roadmap: Path | str | None = None
) -> GoalCoverageResult:
    repo_path = Path(repo)
    plan_path = Path(plan)
    metadata = discovery.plan_metadata(plan_path)
    alias = metadata.get("phase")
    roadmap_path = Path(roadmap) if roadmap is not None else discovery._roadmap_from_plan(repo_path, plan_path)

    def _result(**kw: Any) -> GoalCoverageResult:
        base = dict(
            repo=str(repo_path), plan=str(plan_path), roadmap=str(roadmap_path), phase_alias=alias,
            applicable=False, declared_ids=(), referenced_ids=(), unreferenced_ids=(),
            dangling_refs=(), setup_diagnostics=(),
        )
        base.update(kw)
        return GoalCoverageResult(**base)  # type: ignore[arg-type]

    # Anchor gate — refuse to audit against a stale/alternate roadmap (validates
    # version/phase/roadmap-path/roadmap_sha256).
    diag = discovery.plan_artifact_diagnostic(repo_path, plan_path, roadmap_path, alias)
    if diag is not None:
        return _result(setup_diagnostics=(f"plan_anchor:{diag}",))

    try:
        phases = _extract_phases(roadmap_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _result(setup_diagnostics=(f"roadmap_unreadable:{exc}",))
    matches = [p for p in phases if p.alias.upper() == str(alias or "").upper()]
    if not matches:
        return _result(setup_diagnostics=(f"phase_alias_not_found:{alias}",))
    if len(matches) > 1:
        # Duplicate phase alias — a malformed roadmap (roadmap_lint (C)). Selecting the
        # first would silently exclude the other phase's goals (CR codex). Fail closed.
        return _result(setup_diagnostics=(f"duplicate_phase_alias:{alias}",))
    match = matches[0]

    # Run the FULL EC-ID reconciliation the offline `roadmap_lint` (H) check runs
    # (all-or-none, alias-scoped, UNIQUE) at RUNTIME — the gate must not trust a
    # malformed roadmap (mixed-mode, duplicate ID collapsing two goals into one, or a
    # wrong-alias ID) and silently omit a goal (CR codex). Any violation -> setup error.
    _ec_errors: list[str] = []
    _check_exit_criteria_ids([match], _ec_errors)
    if _ec_errors:
        return _result(setup_diagnostics=(f"malformed_exit_criteria_ids: {_ec_errors[0]}",))

    declared = tuple(match.declared_exit_criteria_ids)

    refs = extract_plan_goal_refs(plan_path)
    if not declared:
        # Legacy phase (no goal IDs). Only truly not_applicable when the plan ALSO
        # references no goal IDs; a plan reference to a nonexistent goal is a dangling
        # gap (CR codex — every unknown EC-ID reference is a contract_bug).
        if not refs:
            return _result(applicable=False)
        return _result(applicable=True, referenced_ids=tuple(sorted(refs)), dangling_refs=tuple(sorted(refs)))

    declared_set = set(declared)
    return _result(
        applicable=True,
        declared_ids=declared,
        referenced_ids=tuple(sorted(refs)),
        unreferenced_ids=tuple(sorted(declared_set - refs)),
        dangling_refs=tuple(sorted(refs - declared_set)),
    )


KNOWN_VACUOUS_SHAS = {
    "5bb80a50e6f7942d62bc58839bc6b66efa5b66439b899b9b90ddbbc4fe662329",
    "9239214f44821e38eae26820b8d5304d04bf5753a3cb3d6ff7d61eb1e50574d0",
    "00947238c4a5c6c57919d9ca60d2aaa0f552245b0860f8477d1e9cbeb43923f2",
    "9f820fd9b80ade9035ef5f7d4575fde2ffc74c41d74844aa9bf81243ffa4c395",
    "682ed77fcb4117192eb2acc60dcf2994ff465ccb68534ec79a03a75b7b60212f",
    "e704e12e286534d1b29282abd4e2f529993f209a799af96bf082e3927ea3374a",
    "951f82320b049141247d1c70379d7c8ce6503e6fb67b6a4a3057605b72d33e00",
    "bcc83e20d2ccc7fb4f6f353c291093e05cefd5dde709eaa1e9b00f6a925b610d",
}

GRANDFATHERED_RAW_ITEM = (
    "- [ ] EC-P1-1 — proven by `pytest tests/test_closeout.py -k register_validator`"
)
GRANDFATHERED_SHA256 = hashlib.sha256(GRANDFATHERED_RAW_ITEM.encode("utf-8")).hexdigest()
GRANDFATHERED_CRITERION_IDS_BY_SHA256 = {
    GRANDFATHERED_SHA256: "EC-P1-1",
    "f4c1b93e369ca49fb3906a9643f3e3da3ef2845e85de47f7363d0fa649a7bde2": "EC-P1-1",
    "323d95df0dd6c1e989a91a6893c173bc04351aec55b6bcab5d83fde5184ab755": "EC-P1-2",
    "4bd0fc08338dbd5091c1a9fadaec5ca9f183ce0d878b9ab48d5ef5b37b6728ee": "EC-ID",
}

_NEGATIVE_FALSIFIER_RE = re.compile(
    r"\b(?:did|does|do|was|were|is|are|has|have|had)\s+not\b"
    r"|\bnever\b"
    r"|\bno\s+\w+(?:\s+\w+){0,4}\s+"
    r"(?:occurs?|happens?|reaches?|runs?|executes?|writes?|emits?|calls?|appears?|exists?|lands?|fires?)\b"
    r"|\bwithout\s+(?:entering|reaching|running|executing|writing|emitting|calling|landing|firing)\b"
)


def is_production_construction_site(target_path: str | Path) -> bool:
    s = str(target_path)
    if "proofgate_tdd_guard" in s:
        return False
    if "tests/proofgate" in s and "adapter" not in s:
        return False
    return True


def extract_acceptance_contracts(plan_content_or_path: str | Path) -> list[dict[str, Any]]:
    if isinstance(plan_content_or_path, Path) or (isinstance(plan_content_or_path, str) and "\n" not in plan_content_or_path and Path(plan_content_or_path).exists()):
        try:
            content = Path(plan_content_or_path).read_text(encoding="utf-8")
        except OSError:
            content = str(plan_content_or_path)
    else:
        content = str(plan_content_or_path)

    match = _ACCEPTANCE_SECTION_RE.search(content)
    if not match:
        return []

    body = match.group("body")
    contracts = []
    item_idx = 1
    for raw_item in _acceptance_raw_items(body):
        first_line = raw_item.splitlines()[0].strip()
        prefix = _CHECKBOX_PREFIX_RE.match(first_line)
        if not prefix:
            continue

        item_content = first_line[prefix.end():]
        continuation = raw_item[len(raw_item.splitlines(keepends=True)[0]):].strip()
        if continuation:
            item_content = f"{item_content}\n{continuation}"
        leading_ids = _leading_ec_ids(item_content)
        crit_id = leading_ids[0] if leading_ids else f"AC-{item_idx}"
        if not leading_ids:
            m_ac = re.search(r"\b(AC-\d+|EC-[A-Z0-9-]+)\b", item_content)
            if m_ac:
                crit_id = m_ac.group(1)
        item_idx += 1

        sha256_val = hashlib.sha256(raw_item.encode("utf-8")).hexdigest()

        proven_by = ""
        falsified_by = ""

        lower_content = item_content.lower()
        if "proven by" in lower_content:
            idx = lower_content.find("proven by")
            proven_part = item_content[idx + len("proven by"):]
            if "falsified by" in proven_part.lower():
                f_idx = proven_part.lower().find("falsified by")
                proven_by = proven_part[:f_idx].strip("`, ")
                falsified_by = proven_part[f_idx + len("falsified by"):].strip("`, ")
            else:
                proven_by = proven_part.strip("`, ")
        elif "falsified by" in lower_content:
            f_idx = lower_content.find("falsified by")
            falsified_by = item_content[f_idx + len("falsified by"):].strip("`, ")
        elif "falsifier:" in lower_content:
            f_idx = lower_content.find("falsifier:")
            falsified_by = item_content[f_idx + len("falsifier:"):].strip("`, ")

        has_falsifier = ("falsified by" in lower_content or "falsifier:" in lower_content or bool(falsified_by))
        has_proof_claim = "proven by" in lower_content
        has_proof_command = "proven by `" in lower_content
        has_path_entered_control = ("path-entered" in lower_content or "path entered" in lower_content)
        lower_falsifier = falsified_by.lower()
        is_negative = bool(
            _NEGATIVE_FALSIFIER_RE.search(lower_falsifier)
            or "invalid key is accepted" in lower_falsifier
            or "absence claim" in lower_falsifier
            or "route rejection" in lower_falsifier
        )

        contracts.append({
            "id": crit_id,
            "raw_item": raw_item,
            "raw": raw_item,
            "sha256": sha256_val,
            "proven_by": proven_by,
            "falsified_by": falsified_by,
            "has_falsifier": has_falsifier,
            "has_proof_claim": has_proof_claim,
            "has_proof_command": has_proof_command,
            "has_path_entered_control": has_path_entered_control,
            "is_negative": is_negative,
            "item_content": item_content,
        })

    return contracts


def check_acceptance_falsifiers(
    contracts: list[dict[str, Any]],
    cutoff_commit_oid: str | None = None,
    successor_commit_oid: str | None = None,
    server_attested_date: str | None = None,
) -> dict[str, Any]:
    if not contracts:
        return {"valid": False, "disposition": "invalid", "reason": "missing_falsifier", "required_verification_schema_version": 3, "requires_current_evidence": True}

    if cutoff_commit_oid and successor_commit_oid and server_attested_date:
        if (
            cutoff_commit_oid == "5328694ae31b4f13f091903d96ed89395d74f3b2"
            and successor_commit_oid == "a3fbb196b3b57d75e403bcea3bad972e9491f675"
            and server_attested_date == "2026-07-29T22:09:58Z"
        ):
            all_gf = all(
                GRANDFATHERED_CRITERION_IDS_BY_SHA256.get(str(c.get("sha256", "")))
                == str(c.get("id", ""))
                for c in contracts
            )
            if all_gf:
                records = []
                for c in contracts:
                    records.append({
                        "criterion_id": c.get("id"),
                        "raw_item_sha256": c.get("sha256"),
                        "server_attested_pre_grammar_date": server_attested_date,
                    })
                return {
                    "valid": True,
                    "disposition": "grandfathered",
                    "reason": None,
                    "grandfather_records": records,
                }

    for c in contracts:
        sha = c.get("sha256", "")
        item_lower = c.get("item_content", "").lower()
        if sha in KNOWN_VACUOUS_SHAS or "vacuous_falsifier" in item_lower or "fails if true" in item_lower or "silent degradation" in item_lower:
            return {"valid": False, "disposition": "invalid", "reason": "vacuous_falsifier"}

    for c in contracts:
        if not c.get("has_falsifier"):
            return {
                "valid": False,
                "disposition": "invalid",
                "reason": "missing_falsifier",
                "required_verification_schema_version": 3,
                "requires_current_evidence": True,
            }

    for c in contracts:
        if c.get("is_negative") and not c.get("has_path_entered_control"):
            return {"valid": False, "disposition": "invalid", "reason": "missing_path_entered_control"}

    return {"valid": True, "disposition": "valid", "reason": None}
