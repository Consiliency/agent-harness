"""Governed planning-review gate (model-routing-v1 P2, IF-0-P2-1).

This is the **plan-stage** gate. It is deliberately NOT the closeout
`_VALIDATORS` registry: that hook fires at closeout time on every closeout and
is warn-gated by `PHASE_LOOP_REVIEW` — the wrong host for a run_mode-aware,
fail-closed, planning-stage gate (panel finding, verified). This module reuses
only the `ReviewFinding` / `block` / `nit` vocabulary.

Run modes (the second orthogonal axis; the first is `model_policy`):
- `autonomous` (default): the gate does NOT run — it returns immediately and
  **never invokes the panel** (no CLI spawn, no cost, no `human_required`).
- `governed` (opt-in): the panel reviews the artifact; `block` findings hold
  promotion, `nit` findings are recorded but non-gating.

Reviewer ≠ author: the panel pool must differ from the author in vendor. If the
only authed reviewer is the author's vendor — or none are authed — the gate
holds fail-closed with a non-human review-gate blocker rather than rubber-
stamping a same-vendor self-review as a pass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from .advisor_board.schema import vendor_family, vendor_of_harness
from .closeout_validators import ReviewFinding
from pathlib import Path

from .panel_invoker import PanelResult, available_panel_legs, invoke_panel, terminal_verdict


RUN_MODES: tuple[str, ...] = ("autonomous", "governed")
DEFAULT_RUN_MODE = "autonomous"
RUN_MODE_ENV = "PHASE_LOOP_RUN_MODE"


def _leg_blocks(text: str) -> bool:
    """True iff a usable leg's review signals a blocking concern.

    A usable leg is conforming by construction (``_classify_leg`` only returns
    ``ok`` when ``terminal_verdict`` is non-None), so this is a pure read of the
    structured terminal verdict — only a bare ``DISAGREE`` blocks. No substring /
    negation guessing (that whack-a-mole mis-blocked "I cannot AGREE or DISAGREE"
    and mis-passed junk containing the words — advisor-panel reconciliation).
    """
    return terminal_verdict(text) == "DISAGREE"

# Reviewer≠author disjointness is keyed on VENDOR FAMILY, and the ONE canonical
# model-first projection lives in ``advisor_board.schema`` (ABDFREEZE IF-0-1). These
# are thin wrappers onto it — NOT a parallel copy — so a custom/model-first board
# can never drift the executor→vendor and model→vendor mappings out of sync with the
# seat projection (the drift this fix exists to kill). ``vendor_of_harness`` mirrors
# the old ``_EXECUTOR_VENDOR`` table exactly; ``vendor_family`` reproduces the old
# ``author_vendor_for_model`` (family, or the bare lowercased model when
# inconclusive). See tests/test_advisor_board_schema.py for the byte-consistency.


def author_vendor_for_executor(executor: str) -> str:
    return vendor_of_harness(executor)


def author_vendor_for_model(model_id: str) -> str:
    """Map a concrete model id to its panel-leg vendor family (codex/gemini/claude/…).

    Fallback author signal for reviewer≠author when no recorded executor is
    available: the implementing model's vendor must be excluded from the pool.
    Delegates to the frozen ``vendor_family`` projection (model-first, harness
    unknown here), which returns the family or the bare lowercased model.
    """
    return vendor_family(model_id)


def resolve_run_mode(env: Mapping[str, str] | None = None, explicit: str | None = None) -> str:
    if explicit:
        value = str(explicit).strip().lower()
        return value if value in RUN_MODES else DEFAULT_RUN_MODE
    value = str((env or {}).get(RUN_MODE_ENV) or "").strip().lower()
    return value if value in RUN_MODES else DEFAULT_RUN_MODE


def select_reviewer_pool(
    author_vendor: str | Iterable[str],
    available_legs: Sequence[str],
) -> tuple[tuple[str, ...], str | None]:
    """Return (pool, degraded_reason). The pool excludes EVERY author vendor.

    ``author_vendor`` may be a single vendor or a set of them — under
    rotation/repair a phase can be authored by more than one vendor (e.g. codex
    executes, claude repairs), and ALL of them must be excluded so no author
    reviews its own work (advisor-panel reconciliation, verified).
    ``degraded_reason`` is set when no disjoint reviewer is available.

    ABDHOME (model-first fix): the disjointness compares VENDOR FAMILY to VENDOR
    FAMILY, not leg-name to family. Each available leg is projected through the
    frozen ``vendor_of_harness`` before exclusion, so a same-vendor breadth lane
    (e.g. an ``opencode`` reviewer over a ``codex``-authored artifact — both the
    ``codex`` family) is correctly excluded. For the built-3 / default panel the
    leg name IS its family, so this is byte-neutral. The returned pool keeps the
    original leg NAMES (``invoke_panel`` dispatches on those).
    """
    authors = {author_vendor} if isinstance(author_vendor, str) else set(author_vendor)
    authors = {a for a in authors if a}
    pool = tuple(leg for leg in available_legs if vendor_of_harness(leg) not in authors)
    if pool:
        return pool, None
    return (), ("no_reviewers" if not available_legs else "author_vendor_only")


@dataclass(frozen=True)
class GateResult:
    ran: bool                       # did the governed gate actually evaluate?
    promoted: bool                  # may the artifact advance? (False only on unresolved block)
    findings: tuple[ReviewFinding, ...] = ()
    degraded: bool = False          # Legacy field; governed gate holds fail-closed.
    reason: str | None = None
    panel: PanelResult | None = None


def _findings_from_panel(panel: PanelResult, reviewed_sha: str | None = None) -> tuple[ReviewFinding, ...]:
    """Fail-closed translation of panel leg outputs into findings. A leg that is
    not usable (empty/timeout/degraded/unavailable) becomes a `warn` finding so
    the reduced confidence is recorded; a usable leg whose verdict signals a
    blocking concern becomes a `block` finding.

    #80: a leg that carries SUBSTANTIVE review text (a block or a non-conforming
    review) stamps that text onto the finding's ``body`` so the concrete, actionable
    review survives the panel-scratch teardown and reaches durable artifacts — the
    generic ``reason`` alone is not enough for a non-human repair. #88: every finding
    is bound to ``reviewed_sha`` (the exact reviewed commit) when known."""
    findings: list[ReviewFinding] = []
    for leg in panel.legs:
        if not leg.usable:
            # A leg with SUBSTANTIVE text but no conforming terminal verdict is a
            # review that violated the contract — we cannot confirm it approved, so
            # fail closed (BLOCK), never downgrade a possible objection to a
            # non-gating warn (CR finding). A leg with no usable text
            # (empty / timeout / unavailable / auth error) is "no review happened"
            # → a recorded warn (reduced confidence), not a block.
            if leg.text.strip():
                findings.append(ReviewFinding(
                    code="panel_nonconforming",
                    reason=(
                        f"panel leg {leg.leg} produced a review with no conforming "
                        f"terminal verdict ({leg.status}); holding fail-closed"
                    ),
                    severity="block",
                    blocker_class="review_gate_block",
                    body=leg.text,
                    reviewed_sha=reviewed_sha,
                ))
            else:
                # agent-harness#906: keep the leg's DETAIL, not only its status. Without it
                # a launch-boundary refusal ("missing HARDEN review authorization") could
                # never reach the coordinator's diagnostic; four such refusals read only
                # as `no_usable_review`.
                detail = f": {leg.detail}" if leg.detail else ""
                findings.append(ReviewFinding(
                    code="panel_leg_degraded",
                    reason=f"panel leg {leg.leg} unusable ({leg.status}{detail})",
                    severity="warn",
                    reviewed_sha=reviewed_sha,
                ))
            continue
        if _leg_blocks(leg.text):
            findings.append(ReviewFinding(
                code="panel_block",
                reason=f"panel leg {leg.leg} raised a blocking concern",
                severity="block",
                blocker_class="review_gate_block",
                # #80: the actual blocking review text, not just the generic reason.
                body=leg.text,
                reviewed_sha=reviewed_sha,
            ))
        else:
            # A "nit" is non-blocking; recorded at `warn` severity (the rigor-v1
            # model has no separate nit literal — block vs not-block).
            findings.append(ReviewFinding(
                code="panel_nit",
                reason=f"panel leg {leg.leg} reviewed with non-blocking notes",
                severity="warn",
            ))
    return tuple(findings)


def _block_result(
    reason: str,
    code: str,
    detail: str,
    *,
    extra_findings: tuple[ReviewFinding, ...] = (),
) -> GateResult:
    """A fail-closed governed result: held (not promoted), non-degraded block.

    ``extra_findings`` (agent-harness#906) carries the per-leg diagnostics behind a
    structural hold so the reason each leg was unusable survives. ``panel`` stays
    ``None`` on purpose: ``run_governed_premerge_loop``'s reviewer-floor guard keys on
    ``gate.panel``, and attaching a zero-usable panel here would relabel the hold
    ``below_reviewer_floor`` with the wrong remedy.
    """
    return GateResult(
        ran=True,
        promoted=False,
        degraded=False,
        reason=reason,
        findings=(ReviewFinding(
            code=code,
            reason=detail,
            severity="block",
            blocker_class="review_gate_block",
        ),) + tuple(extra_findings),
    )


def governed_planning_gate(
    *,
    artifact: str,
    author_executor: str | None = None,
    author_vendors: Iterable[str] | None = None,
    run_mode: str,
    available_legs: Sequence[str] | None = None,
    invoke: Callable[..., PanelResult] = invoke_panel,
    spawn=None,
    repo_dir=None,
    max_concurrency: int | None = None,
    reviewed_sha: str | None = None,
) -> GateResult:
    """Evaluate a governed gate (plan-stage or pre-merge).

    AUTONOMOUS SHORT-CIRCUIT: when `run_mode != "governed"` this returns BEFORE
    selecting a pool or touching `invoke` — the panel is never spawned. This is
    the zero-panel-call guarantee for the default path.

    FAIL-CLOSED (governed is the opt-in enforcement mode): if there is no reviewer
    disjoint from the author vendor(s), or every selected leg is unusable / non-
    conforming, the gate HOLDS (non-human ``review_gate_block``) rather than
    advisory-passing a review that never really happened (advisor-panel
    reconciliation, verified — the prior advisory-pass was a fail-open).

    ``reviewed_sha`` (#88): the exact commit under review — stamped onto every
    emitted finding so a consumer can bind the verdict to that commit
    (``closeout_validators.verdict_binds_to``) and reject a stale verdict.
    """
    if run_mode != "governed":
        return GateResult(ran=False, promoted=True)

    if author_vendors is not None:
        authors = frozenset(v for v in author_vendors if v)
    else:
        authors = frozenset({author_vendor_for_executor(author_executor or "")} - {""})
    if not authors:
        # Unknown author → CANNOT establish reviewer≠author. Fail closed (CR
        # finding): an empty author set otherwise excluded nothing and ran the
        # FULL panel including the author's own vendor (a silent self-review).
        return _block_result(
            "unknown_author",
            "governed_unknown_author",
            "governed mode could not determine the authoring vendor(s) for "
            "reviewer≠author exclusion; holding (non-human) rather than risk a "
            "self-review",
        )
    legs = tuple(available_legs) if available_legs is not None else available_panel_legs()
    pool, degraded_reason = select_reviewer_pool(authors, legs)
    if not pool:
        return _block_result(
            degraded_reason or "no_disjoint_reviewer",
            "governed_no_disjoint_reviewer",
            (
                f"governed mode requires a reviewer disjoint from author vendor(s) "
                f"{sorted(authors)} but none is available ({degraded_reason}); "
                f"holding (non-human). Authenticate or install at least one available "
                f"non-author panel leg; the Claude TUI leg can satisfy this when its "
                f"local Claude Code subscription route is available."
            ),
        )

    invoke_kwargs = {"spawn": spawn}
    if repo_dir is not None:
        invoke_kwargs["repo_dir"] = repo_dir
    # Parallel by default; a caller can force sequential (max_concurrency=1). Passed
    # ONLY when set so a custom ``invoke`` with a strict signature stays unaffected
    # (byte-neutral for the default governed path).
    if max_concurrency is not None:
        invoke_kwargs["max_concurrency"] = max_concurrency
    panel = invoke(artifact, pool, **invoke_kwargs)
    return _gate_result_from_panel(panel, reviewed_sha=reviewed_sha)


def _gate_result_from_panel(panel: PanelResult, *, reviewed_sha: str | None) -> GateResult:
    findings = _findings_from_panel(panel, reviewed_sha=reviewed_sha)
    if not panel.usable_legs:
        # Pool existed but no leg produced a usable, conforming review → the review
        # did not actually happen. Fail closed, never silent-pass. The per-leg
        # findings ride along (agent-harness#906) so the hold names each refusal.
        return _block_result(
            "no_usable_review",
            "governed_no_usable_review",
            f"no disjoint reviewer produced a usable verdict ({len(panel.legs)} leg(s) unusable); holding (non-human)",
            extra_findings=findings,
        )
    has_block = any(f.severity == "block" for f in findings)
    return GateResult(
        ran=True,
        promoted=not has_block,
        findings=findings,
        degraded=False,
        panel=panel,
    )


_UNSET: object = object()  # "no digest bound" — distinct from any token value


def governed_board_gate(
    *,
    artifact: str,
    author_executor: str | None = None,
    author_vendors: Iterable[str] | None = None,
    run_mode: str,
    available_legs: Sequence[str] | None = None,
    spawn=None,
    repo_dir=None,
    max_concurrency: int | None = None,
    reviewed_sha: str | None = None,
    canonical_repo_authority: "Path | str | None" = None,
    brief_ref: str | None = None,
    compose: Callable[[], object] | None = None,
    invoke: Callable[..., PanelResult] | None = None,
    native_leg_fills: Sequence[object] | None = None,
    emit_native_request: bool = False,
    native_fill_dir: "Path | str | None" = None,
    monitoring_policy: str = "bounded",
) -> "GateResult | dict[str, object]":
    """A governed gate backed by the broker-AUTHORIZED review board (agent-harness#906).

    ``monitoring_policy="heartbeat_only"`` (agent-harness#906, ``run-train
    --monitoring-policy``) runs the review the way ``advisor-board --monitoring-policy
    heartbeat_only`` does: the frozen default four-vendor board (any other composition is
    refused, even from an injected ``compose``), no model deadline, and no native host seat.
    It is checked here, before minting or any launch, and forwarded to both the
    authorization and ``invoke_board``, which refuse a mismatch between the two.

    REVIEWTRUTH early slice (EC-REVIEWTRUTH-14, plan agent-harness#918): ``emit_native_request``
    performs the same composition, author exclusion, floor and staging the invoke arm will
    redo, writes ``request.json`` / ``artifact.md`` / ``instructions.md`` under
    ``native_fill_dir`` (or a caller-owned scratch) and returns WITHOUT minting an
    authorization or invoking any seat. ``native_leg_fills`` are preflighted against the
    staged artifact, the resolved brief and the composed board BEFORE any launch (typed
    refusal, zero launches) and then handed to ``invoke_board`` to be bound onto the deferred
    seat after every seat has returned and before the president rules.

    Same ``GateResult`` contract and same keyword surface as ``governed_planning_gate``
    (``run_governed_premerge_loop`` forwards ``available_legs``/``spawn``/``repo_dir``/
    ``max_concurrency`` unconditionally), but the review is dispatched through
    ``invoke_board`` with the typed HARDEN isolation authorization the review-mode
    launch boundary requires -- the sequence the ``advisor-board`` CLI runs
    (``cli.py``), verbatim and tierless:

    composition authority -> ``compose_review_board()`` -> clear -> drop author-vendor
    seats -> composition floor -> bind the instruction digest -> mint the isolation
    authorization over the EXACT artifact bytes staged for the invoker -> ``invoke_board``
    with a throwaway scratch ``repo_dir`` -> reset the digest on every exit.

    Never passes ``landing_tier``/``president_invoke``/``mode``: ``invoke_board`` decides
    the authority switch over ``repo_dir`` (scratch here, exactly as the CLI), so a
    tierless call is never refused, while forcing a tier onto a live-composed board
    would demand seats the composition may have backfilled (board PR #913 r1).
    ``spawn`` is forwarded as received: production passes ``None``; a hermetic test
    passes a callback that the invoker accepts only under the sanctioned
    factory-replacement seam. The backing factory is resolved DYNAMICALLY at call time
    for the same reason. ``available_legs`` is accepted for the loop's contract and
    ignored: composition is the board's, not a leg list. Nothing here constructs a
    leg authorization, a lease, a claim, or the seal.
    """
    import shutil
    import subprocess
    import tempfile
    from dataclasses import replace as _replace

    if run_mode != "governed":
        return GateResult(ran=False, promoted=True)
    if author_vendors is not None:
        authors = frozenset(v for v in author_vendors if v)
    else:
        authors = frozenset({author_vendor_for_executor(author_executor or "")} - {""})
    if not authors:
        return _block_result(
            "unknown_author",
            "governed_unknown_author",
            "governed mode could not determine the authoring vendor(s) for "
            "reviewer≠author exclusion; holding (non-human) rather than risk a "
            "self-review",
        )
    if canonical_repo_authority is None:
        return _block_result(
            "review_isolation_unavailable",
            "governed_board_no_canonical_authority",
            "authorized train review requires a canonical repository authority "
            "(the coordinator's git toplevel or the first node's workspace); none was "
            "resolved; holding (non-human)",
        )
    heartbeat_only = monitoring_policy == "heartbeat_only"
    if monitoring_policy not in ("bounded", "heartbeat_only"):
        return _block_result(
            "review_isolation_unavailable", "governed_board_monitoring_policy_refused",
            f"review monitoring policy {monitoring_policy!r} is not supported; holding (non-human)",
        )
    if heartbeat_only and (native_leg_fills or emit_native_request):
        # CONTRACTS.md, review monitoring policy v1: heartbeat-only has no native host seat.
        return _block_result(
            "review_isolation_unavailable", "governed_board_monitoring_policy_refused",
            "review_monitoring_unsupported_route:native_fill: heartbeat_only review has no "
            "native host seat; holding (non-human)",
        )
    from . import panel_invoker as _pi
    from .advisor_board import backing as _backing
    from .advisor_board.composition import FLOOR_SEATS, compose_review_board
    from .advisor_board.fixtures import DEFAULT_BOARD

    # heartbeat_only seats the frozen default board, as the advisor-board CLI does: an
    # unavailable vendor then fails its own seat instead of being silently backfilled.
    compose_fn = compose if compose is not None else (
        (lambda: DEFAULT_BOARD) if heartbeat_only else compose_review_board
    )
    try:
        _backing.prepare_review_composition_authorization()
        try:
            board = compose_fn()
        finally:
            _backing.clear_review_composition_authorization()
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        return _block_result(
            "review_isolation_unavailable",
            "governed_board_composition_unavailable",
            f"review board composition unavailable: {exc}; holding (non-human)",
        )
    seats = tuple(s for s in board.seats if getattr(s, "harness", None) not in authors)
    dropped = tuple(s for s in board.seats if getattr(s, "harness", None) in authors)
    if len(seats) < FLOOR_SEATS:
        composed = sorted({getattr(s, "harness", "?") for s in seats})
        excluded = sorted({getattr(s, "harness", "?") for s in dropped})
        return _block_result(
            "below_reviewer_floor" if seats else "no_disjoint_reviewer",
            "governed_board_below_floor",
            (
                f"authorized review board composed {len(seats)} seat(s) {composed} "
                f"disjoint from author vendor(s) {sorted(authors)} (excluded {excluded}); "
                f"the composition floor is {FLOOR_SEATS}. Authenticate or install the "
                f"missing vendor CLIs; holding (non-human)"
            ),
        )
    if dropped:
        board = _replace(board, seats=seats)
    if heartbeat_only:
        if board != DEFAULT_BOARD:
            # Frozen composition, whatever produced it: an injected composer or author
            # exclusion that changes the seats is refused, never reviewed (agent-harness#1061 r1).
            return _block_result(
                "review_isolation_unavailable", "governed_board_monitoring_policy_refused",
                "heartbeat_only review requires the frozen four-vendor default board; "
                f"composed {sorted(getattr(s, 'harness', '?') for s in board.seats)}; holding (non-human)",
            )
        try:
            _backing.resolve_review_monitoring_policy(monitoring_policy, board)
            _pi._preflight_gemini_heartbeat(board, monitoring_policy)
        except (OSError, ValueError) as exc:
            return _block_result(
                "review_isolation_unavailable", "governed_board_monitoring_policy_refused",
                f"review monitoring policy refused before any launch: {exc}; holding (non-human)",
            )
    policy_kwargs: dict[str, object] = {"monitoring_policy": monitoring_policy} if heartbeat_only else {}
    invoke_fn = invoke if invoke is not None else _pi.invoke_board
    from .advisor_board.composition import composition_digest

    if artifact.startswith("# Train review packet v1\n"):
        try:
            from .train_review_packet import preflight_packet
            preflight_packet(artifact, instructions=_pi._resolve_brief("review", brief_ref), board=board)
        except (OSError, UnicodeError, ValueError) as exc:
            return _block_result(
                "review_isolation_unavailable", "governed_board_packet_preflight_failed",
                f"review packet transport preflight failed: {exc}; holding (non-human)",
            )

    if emit_native_request:
        # Emit arm: no authorization, no seat, no digest binding beyond the read-back bytes.
        try:
            brief_text = _pi._resolve_brief("review", brief_ref)
            out_root = Path(native_fill_dir) if native_fill_dir is not None else Path(tempfile.mkdtemp(prefix="native-fill-"))
            payload = _pi.native_fill_request_payload(board, artifact, brief_ref=brief_ref)
            out_dir = out_root / "native-fill" / str(payload["request_id"])
            out_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = out_dir / _pi.NATIVE_FILL_ARTIFACT_FILE
            artifact_path.write_text(artifact, encoding="utf-8")
            # Digest the READ-BACK text (universal newlines), exactly as the invoke arm stages it.
            payload["artifact_sha256"] = _pi.content_sha256(artifact_path.read_text(encoding="utf-8"))
            instructions_path = out_dir / _pi.NATIVE_FILL_INSTRUCTIONS_FILE
            instructions_path.write_text(brief_text, encoding="utf-8")
            payload["artifact_path"] = str(artifact_path)
            payload["instructions_path"] = str(instructions_path)
            request_path = out_dir / _pi.NATIVE_FILL_REQUEST_FILE
            request_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            payload["request_path"] = str(request_path)
        except (OSError, UnicodeError, ValueError) as exc:
            return _block_result(
                "native_fill_request_unavailable",
                "governed_board_native_fill_request_unavailable",
                f"native fill request could not be emitted: {exc}; holding (non-human)",
            )
        # The emit arm's result is the request envelope itself (a Mapping); ``GateResult``
        # gains nothing (plan r8). Callers branch on ``emit_native_request``.
        return payload
    # Board r1 (agent-harness#914, codex): brief resolution, scratch allocation and the
    # digest binding are PREPARATION and can fail like everything after them — an
    # unreadable brief, a full tmpdir, a refused digest. They run inside the same
    # guarded scope so every failure holds as ``review_isolation_unavailable`` and the
    # ``finally`` undoes exactly what was set up (a digest bound without a scratch, a
    # scratch allocated without a digest).
    scratch: Path | None = None
    token: object = _UNSET
    try:
        brief_text = _pi._resolve_brief("review", brief_ref)
        scratch = Path(tempfile.mkdtemp(prefix="train-review-"))
        token = _backing.set_review_instruction_digest(brief_text)
        provider_scratch = scratch / "provider"
        provider_scratch.mkdir()
        artifact_path = scratch / "train-review-bundle.md"
        artifact_path.write_text(artifact, encoding="utf-8")
        # Mint over the READ-BACK staged text, as the CLI does: ``invoke_board`` resolves
        # ``artifact_ref`` through ``read_text`` (universal newlines), so minting over the
        # in-memory string would diverge on any CR and fail closed for no reason (board
        # r1, agent-harness#914, claude). This is the "exact staged bytes" promise.
        staged_artifact = artifact_path.read_text(encoding="utf-8")
        if native_leg_fills:
            # D2 refusal timing: preflight BEFORE minting or launching anything.
            refusal = _pi.preflight_native_leg_fills(
                board, tuple(native_leg_fills),
                artifact_sha256=_pi.content_sha256(staged_artifact),
                brief_sha256=_pi.content_sha256(brief_text),
                composition_sha256=composition_digest(board),
            )
            if refusal is not None:
                return _block_result(
                    "native_fill_refused", refusal.reason,
                    f"native fill refused before any reviewer launch: {refusal.detail} (seat {refusal.seat_key}); holding (non-human)",
                )
        # Dynamic lookup on purpose: the sanctioned hermetic seam replaces this factory
        # and requires the invoker's own lookup to return the identical object.
        authorization = _backing.prepare_review_isolation_authorization(
            board,
            staged_artifact,
            mode="review",
            canonical_repo_authority=canonical_repo_authority,
            **policy_kwargs,
        )
        invoke_kwargs: dict[str, object] = {
            "repo_dir": provider_scratch,
            "artifact_ref": str(artifact_path),
            "review_authorization": authorization,
            "canonical_repo_authority": canonical_repo_authority,
            "spawn": spawn,
            **policy_kwargs,
        }
        if brief_ref is not None:
            invoke_kwargs["brief_ref"] = brief_ref
        if max_concurrency is not None:
            invoke_kwargs["max_concurrency"] = max_concurrency
        if native_leg_fills:
            invoke_kwargs["native_leg_fills"] = tuple(native_leg_fills)
        panel = invoke_fn(board, staged_artifact, **invoke_kwargs)
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        return _block_result(
            "review_isolation_unavailable",
            "governed_board_isolation_unavailable",
            f"review isolation unavailable: {exc}; holding (non-human)",
        )
    finally:
        if token is not _UNSET:
            _backing.reset_review_instruction_digest(token)
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    return _gate_result_from_panel(panel, reviewed_sha=reviewed_sha)
