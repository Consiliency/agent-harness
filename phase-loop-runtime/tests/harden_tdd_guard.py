"""HARDEN SL-0 tests-only guard: frozen inventory and deterministic RED anchors.

The guard is deliberately test-only.  Before production exposes the exact
``HARDEN_CAPABILITY_VERSION = 1`` marker, mapped capability assertions skip in
the ordinary suite and fail at their one named anchor only when the explicit
HARDEN TDD switch is active.  Each case first resolves the production symbol it
will exercise, so an import or collection problem is never accepted as RED
evidence.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import stat
import subprocess
import sysconfig
import tempfile
from unittest import mock

import pytest


HARDEN_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_HARDEN"
HARDEN_MARKER_MODULE = "phase_loop_runtime.capability_registry"
HARDEN_MARKER_ATTRIBUTE = "HARDEN_CAPABILITY_VERSION"
HARDEN_SKIP_REASON = (
    "HARDEN production capability is absent (SL-0 tests-only boundary): "
    "set PHASE_LOOP_TDD_EXPECT_HARDEN=1 to record the deterministic RED anchors"
)
_UNSET = object()

HARDEN_TEST_PATHS = (
    "phase-loop-runtime/tests/harden_tdd_guard.py",
    "phase-loop-runtime/tests/test_advisor_board_advisory_mode.py",
    "phase-loop-runtime/tests/test_advisor_board_backcompat.py",
    "phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py",
    "phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py",
    "phase-loop-runtime/tests/test_advisor_board_cli_legacy.py",
    "phase-loop-runtime/tests/test_advisor_board_composition.py",
    "phase-loop-runtime/tests/test_advisor_board_config.py",
    "phase-loop-runtime/tests/test_advisor_board_golden.py",
    "phase-loop-runtime/tests/test_advisor_board_integration.py",
    "phase-loop-runtime/tests/test_advisor_board_live_research.py",
    "phase-loop-runtime/tests/test_advisor_board_observability.py",
    "phase-loop-runtime/tests/test_advisor_board_presets.py",
    "phase-loop-runtime/tests/test_advisor_board_research.py",
    "phase-loop-runtime/tests/test_advisor_board_resolver.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_harden_evidence_verifier.py",
    "phase-loop-runtime/tests/test_panel_invoker.py",
    "phase-loop-runtime/tests/test_panel_leg_failure_diagnostic.py",
    "phase-loop-runtime/tests/test_panel_native_fill_183.py",
    "phase-loop-runtime/tests/test_panel_streaming_verdicts.py",
    "phase-loop-runtime/tests/test_phase_loop_injection.py",
    "phase-loop-runtime/tests/test_ratification_policy.py",
    "phase-loop-runtime/tests/test_reconcile_portability_85c.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
    "phase-loop-runtime/tests/test_verification_interpreter_guard_221.py",
)

HARDEN_RED_ANCHORS = {
    "staged-tree-containment": "HARDEN-RED-ANCHOR::staged-tree-containment",
    "cwd-independent-reconcile": "HARDEN-RED-ANCHOR::cwd-independent-reconcile",
    "non-vacuous-goal-coverage": "HARDEN-RED-ANCHOR::non-vacuous-goal-coverage",
    "login-shell-interpreter": "HARDEN-RED-ANCHOR::login-shell-interpreter",
    "review-leg-isolation": "HARDEN-RED-ANCHOR::review-leg-isolation",
}


@dataclass(frozen=True)
class HardenCase:
    nodeid: str
    production_path: str
    symbol: str


HARDEN_CASES = {
    "staged-tree-containment": HardenCase(
        "phase-loop-runtime/tests/test_review_leg_sandbox.py::"
        "test_review_stage_rejects_every_escape_form_before_launch",
        "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
        "_stage_review_tree",
    ),
    "cwd-independent-reconcile": HardenCase(
        "phase-loop-runtime/tests/test_reconcile_portability_85c.py::"
        "test_cwd_independent_reconcile_is_repo_anchored",
        "phase-loop-runtime/src/phase_loop_runtime/reconcile.py",
        "reconcile",
    ),
    "non-vacuous-goal-coverage": HardenCase(
        "phase-loop-runtime/tests/test_goal_coverage.py::"
        "test_enforce_blocks_every_zero_declared_and_all_bare_legacy_is_distinct",
        "phase-loop-runtime/src/phase_loop_runtime/runner.py",
        "_execute_goal_coverage_preflight",
    ),
    "login-shell-interpreter": HardenCase(
        "phase-loop-runtime/tests/test_verification_interpreter_guard_221.py::"
        "test_argument_consuming_bash_options_and_profile_patch_version_fail_closed",
        "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
        "run_verification",
    ),
    "review-leg-isolation": HardenCase(
        "phase-loop-runtime/tests/test_advisor_board_composition.py::"
        "test_review_leg_isolation_refuses_unbound_direct_invocation",
        "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
        "invoke_board",
    ),
}


def _repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent,
    )
    return Path(completed.stdout.strip()).resolve()


def _replicate_test_repository(source: Path | str, destination: Path) -> None:
    """Copy caller state through pinned descriptors into an owner-only scratch."""

    nofollow = os.O_NOFOLLOW | os.O_CLOEXEC

    def snapshot(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
        return (
            info.st_dev,
            info.st_ino,
            stat.S_IFMT(info.st_mode),
            stat.S_IMODE(info.st_mode),
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def copy_file(source_fd: int, destination_fd: int, name: str) -> None:
        destination_file = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=destination_fd,
        )
        try:
            os.fchmod(destination_file, 0o600)
            assert stat.S_IMODE(os.fstat(destination_file).st_mode) == 0o600
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                remaining = memoryview(chunk)
                while remaining:
                    written = os.write(destination_file, remaining)
                    if written <= 0:
                        raise AssertionError("repository projection made no write progress")
                    remaining = remaining[written:]
        finally:
            os.close(destination_file)

    def copy_tree(source_fd: int, destination_fd: int, label: str) -> None:
        directory_before = os.fstat(source_fd)
        if not stat.S_ISDIR(directory_before.st_mode):
            raise AssertionError(f"repository projection source is not a directory: {label}")
        with os.scandir(source_fd) as entries:
            names = tuple(sorted(entry.name for entry in entries))
        for name in names:
            if name.casefold() == ".git":
                continue
            try:
                opened_source = os.open(
                    name,
                    os.O_RDONLY | os.O_NONBLOCK | nofollow,
                    dir_fd=source_fd,
                )
            except OSError as exc:
                raise AssertionError(
                    f"repository projection entry changed or is unsafe: {label}/{name}"
                ) from exc
            try:
                entry_before = os.fstat(opened_source)
                if stat.S_ISDIR(entry_before.st_mode):
                    os.mkdir(name, mode=0o700, dir_fd=destination_fd)
                    opened_destination = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | nofollow,
                        dir_fd=destination_fd,
                    )
                    try:
                        os.fchmod(opened_destination, 0o700)
                        assert (
                            stat.S_IMODE(os.fstat(opened_destination).st_mode) == 0o700
                        )
                        copy_tree(
                            opened_source,
                            opened_destination,
                            f"{label}/{name}",
                        )
                    finally:
                        os.close(opened_destination)
                elif stat.S_ISREG(entry_before.st_mode):
                    copy_file(opened_source, destination_fd, name)
                else:
                    raise AssertionError(
                        f"repository projection refuses special entry: {label}/{name}"
                    )
                if snapshot(os.fstat(opened_source)) != snapshot(entry_before):
                    raise AssertionError(
                        f"repository projection source changed while copied: {label}/{name}"
                    )
            finally:
                os.close(opened_source)
        if snapshot(os.fstat(source_fd)) != snapshot(directory_before):
            raise AssertionError(
                f"repository projection directory changed while copied: {label}"
            )

    try:
        source_fd = os.open(
            os.fspath(source),
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
        )
    except OSError as exc:
        raise AssertionError("repository projection source root is unsafe") from exc
    try:
        destination_fd = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
        )
        try:
            destination_info = os.fstat(destination_fd)
            if stat.S_IMODE(destination_info.st_mode) != 0o700:
                raise AssertionError(
                    "repository projection destination must remain owner-only"
                )
            if (destination_info.st_dev, destination_info.st_ino) == (
                os.fstat(source_fd).st_dev,
                os.fstat(source_fd).st_ino,
            ):
                raise AssertionError("repository projection source and destination match")
            with os.scandir(destination_fd) as entries:
                if next(entries, None) is not None:
                    raise AssertionError("repository projection destination is not empty")
            copy_tree(source_fd, destination_fd, ".")
            if stat.S_IMODE(os.fstat(destination_fd).st_mode) != 0o700:
                raise AssertionError(
                    "repository projection destination permission changed"
                )
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def _dotted_module(production_path: str) -> str:
    relative = production_path.split("phase-loop-runtime/src/", 1)[1]
    return relative.removesuffix(".py").replace("/", ".")


def _marker_version() -> int | None:
    try:
        spec = importlib.util.find_spec(HARDEN_MARKER_MODULE)
    except ModuleNotFoundError:
        return None
    if spec is None:
        return None
    module = importlib.import_module(HARDEN_MARKER_MODULE)
    return getattr(module, HARDEN_MARKER_ATTRIBUTE, None)


def harden_capability_active() -> bool:
    """Return true for the exact forced mode or the final production marker."""

    return os.environ.get(HARDEN_ACTIVATION_ENV) == "1" or _marker_version() == 1


def _resolve_production_symbol(case_id: str) -> None:
    case = HARDEN_CASES[case_id]
    module = importlib.import_module(_dotted_module(case.production_path))
    obj: object = module
    for part in case.symbol.split("."):
        obj = getattr(obj, part)
    source_file = inspect.getsourcefile(obj)
    assert source_file is not None, f"{case_id}: {case.symbol} has no source file"
    relative = Path(case.production_path.split("phase-loop-runtime/src/", 1)[1])
    checkout_path = (_repo_root() / case.production_path).resolve()
    expected = {checkout_path}
    for scheme_path in ("purelib", "platlib"):
        root = sysconfig.get_path(scheme_path)
        if root:
            expected.add((Path(root) / relative).resolve())
    resolved = Path(source_file).resolve()
    assert resolved in expected, (
        f"{case_id}: {case.symbol} resolves to {resolved}, not {case.production_path}"
    )
    if resolved != checkout_path:
        assert resolved.read_bytes() == checkout_path.read_bytes(), (
            f"{case_id}: installed {case.symbol} differs from the reviewed checkout"
        )


def harden_require(case_id: str) -> None:
    """Enter a case's production seam, then skip or emit its one RED anchor."""

    assert case_id in HARDEN_CASES, f"unmapped HARDEN case: {case_id}"
    _resolve_production_symbol(case_id)
    marker = _marker_version()
    assert marker in (None, 1), (
        f"{HARDEN_MARKER_MODULE}.{HARDEN_MARKER_ATTRIBUTE} must be absent or equal 1"
    )
    if marker == 1:
        return
    if os.environ.get(HARDEN_ACTIVATION_ENV) == "1":
        raise AssertionError(HARDEN_RED_ANCHORS[case_id])
    pytest.skip(HARDEN_SKIP_REASON)


def harden_finish_probe(case_id: str, *, satisfied: bool, detail: str) -> None:
    """Finish a real production probe before applying the capability gate.

    Unlike :func:`harden_require`, this gate is intentionally called only after a
    test has exercised the production seam and recorded its effects.  That keeps
    a known pre-marker ordering defect visible to the activated corpus without
    making the ordinary corpus fail before production publishes the marker.
    """

    assert case_id in HARDEN_CASES, f"unmapped HARDEN case: {case_id}"
    _resolve_production_symbol(case_id)
    marker = _marker_version()
    assert marker in (None, 1), (
        f"{HARDEN_MARKER_MODULE}.{HARDEN_MARKER_ATTRIBUTE} must be absent or equal 1"
    )
    if marker == 1:
        assert satisfied, detail
        return
    if os.environ.get(HARDEN_ACTIVATION_ENV) == "1":
        raise AssertionError(HARDEN_RED_ANCHORS[case_id])
    pytest.skip(HARDEN_SKIP_REASON)


def assert_exact_unavailable(board, result) -> None:
    """Pin one unusable UNAVAILABLE result to each configured board seat in order."""

    from phase_loop_runtime.advisor_board import vendor_family

    seats = board.seats
    legs = result.legs
    expected_legs = tuple(
        (seat.harness or vendor_family(seat.model, seat.harness)).lower()
        for seat in seats
    )
    assert len(legs) == len(seats)
    assert tuple(leg.leg for leg in legs) == expected_legs
    assert tuple(leg.seat_key for leg in legs) == tuple(seat.seat_key for seat in seats)
    assert all(leg.status == "UNAVAILABLE" and not leg.usable for leg in legs)


def invoke_sanctioned_board_control(
    board: object,
    artifact: str,
    *,
    spawn: object | None = None,
    mode: str | None = None,
    factory_authorization: object = _UNSET,
    require_live_matrix_probe: bool = False,
    forbid_pre_authorization_effects: bool = False,
    expect_static_refusal_before_effects: bool = False,
    mutate_artifact_after_factory: object | None = None,
    observe_protocol_step: object | None = None,
    **kwargs: object,
) -> object:
    """Run one explicit executable-board control without changing pre-marker semantics.

    This is deliberately an explicit helper, not a fixture installed globally: a
    test must opt in at the exact execution boundary.  Before production exposes
    the marker it calls the historical direct path verbatim, so legacy semantic
    assertions remain part of the default and activated corpora.  Once the marker
    exists, every control supplies a separate private scratch root and temporarily
    replaces the backing factory.  Caller-owned repository state is replicated
    there without Git authority before production receives it.  Review controls
    retain their pre-minted review authorization; advisory controls deliberately
    carry no review authorization.
    ``factory_authorization`` is reserved for marked negative controls: it makes
    the patched factory return and the invocation supply that exact value, so a
    forged or stale review authority cannot be rejected merely for lacking the
    dynamic factory marker.
    In both cases the production invoker must dynamically look up and call the
    replacement exactly once with the effective mode and canonical checkout before
    trusting the control.  Guards at every injected execution, completion, and
    event seam make that ordering assertion non-vacuous.  A control may also opt
    into the default-matrix canary, which proves that authorization precedes the
    live availability/auth probe rather than only downstream execution effects.
    Enabled research and streaming controls additionally guard their materialization
    and verdict-publication seams before either can touch filesystem or PMCP state.
    ``forbid_pre_authorization_effects`` makes a marked negative control retain all
    those guards but require zero consumption after its revalidation refusal.
    ``expect_static_refusal_before_effects`` retains the same complete effect
    boundary around an authorized control that must raise at a static invariant;
    the expected exception is re-raised only after every guarded effect is proven
    untouched.
    ``mutate_artifact_after_factory`` lets a control prove that a post-authorization
    reference-file substitution cannot change the already bound artifact.
    """

    if observe_protocol_step is not None and not callable(observe_protocol_step):
        raise TypeError("observe_protocol_step must be callable")

    def record_protocol_step(step: str) -> None:
        if observe_protocol_step is not None:
            observe_protocol_step(step)

    invoker = importlib.import_module("phase_loop_runtime.panel_invoker")
    call_kwargs = dict(kwargs)
    if forbid_pre_authorization_effects and expect_static_refusal_before_effects:
        raise AssertionError("a refusal control must select exactly one refusal mode")
    guard_live_matrix_probe = (
        require_live_matrix_probe
        or forbid_pre_authorization_effects
        or expect_static_refusal_before_effects
    )
    if guard_live_matrix_probe and "matrix" in call_kwargs:
        raise AssertionError("the live-matrix control must not inject a matrix")
    if mode is not None:
        call_kwargs["mode"] = mode
    if spawn is not None:
        call_kwargs["spawn"] = spawn

    marker = _marker_version()
    assert marker in (None, 1), (
        f"{HARDEN_MARKER_MODULE}.{HARDEN_MARKER_ATTRIBUTE} must be absent or equal 1"
    )
    if marker != 1:
        if expect_static_refusal_before_effects:
            raise AssertionError(
                "static-refusal controls require the explicit production marker"
            )
        return invoker.invoke_board(board, artifact, **call_kwargs)

    effective_mode = mode if mode is not None else invoker._mode_for_purpose(board.purpose)
    if "review_authorization" in call_kwargs or "canonical_repo_authority" in call_kwargs:
        raise AssertionError("the sanctioned control owns authority binding")

    backing = importlib.import_module("phase_loop_runtime.advisor_board.backing")
    canonical_repo = _repo_root()
    prepare_review_isolation_authorization = (
        backing.prepare_review_isolation_authorization
    )
    artifact_ref = call_kwargs.get("artifact_ref")
    context_refs = call_kwargs.get("context_refs")
    context_refs_soft_warn = bool(call_kwargs.get("context_refs_soft_warn", False))
    original_resolve_artifact = invoker._resolve_artifact
    original_apply_context_refs = invoker._apply_context_refs
    resolved_inline_artifact = original_resolve_artifact(artifact, artifact_ref)
    resolved_artifact = original_apply_context_refs(
        resolved_inline_artifact,
        context_refs,
        soft_warn=context_refs_soft_warn,
    )
    authorization = None
    if effective_mode == "review":
        pre_minted_authorization = prepare_review_isolation_authorization(
            board,
            resolved_artifact,
            mode=effective_mode,
            canonical_repo_authority=canonical_repo,
        )
        authorization = (
            pre_minted_authorization
            if factory_authorization is _UNSET
            else factory_authorization
        )
    elif factory_authorization is not _UNSET:
        raise AssertionError("only review controls may override factory authorization")

    caller_repo_dir = call_kwargs.pop("repo_dir", None)
    call_kwargs["canonical_repo_authority"] = canonical_repo
    if authorization is not None:
        call_kwargs["review_authorization"] = authorization
    research_policy = call_kwargs.get("research_policy")
    if research_policy is None:
        research_policy = getattr(board, "research_policy", None)
    requires_research_materialization = bool(
        getattr(research_policy, "enabled", False)
    )
    requires_incremental_verdict_write = call_kwargs.get("stream_dir") is not None
    with tempfile.TemporaryDirectory(prefix="harden-review-scratch-") as td:
        scratch = Path(td).resolve()
        assert scratch != canonical_repo
        assert stat.S_IMODE(scratch.stat().st_mode) == 0o700
        if caller_repo_dir is not None:
            _replicate_test_repository(caller_repo_dir, scratch)
        assert stat.S_IMODE(scratch.stat().st_mode) == 0o700
        call_kwargs["repo_dir"] = scratch
        factory_marker = authorization if authorization is not None else object()
        authorization_canary = mock.Mock(return_value=factory_marker)
        original_govlean_authority_switched = invoker._govlean_authority_switched
        original_validate_review_board_policy = invoker._validate_review_board_policy
        landing_tier = call_kwargs.get("landing_tier")
        supplied_review_policy = call_kwargs.get("review_policy")
        review_seat_aliases = call_kwargs.get("review_seat_aliases")
        policy_validation_required = (
            landing_tier is not None or supplied_review_policy is not None
        )
        expected_review_policy = supplied_review_policy
        if expected_review_policy is None and landing_tier is not None:
            expected_review_policy = invoker.review_policy_for_tier(
                invoker._coerce_review_landing_tier(landing_tier)
            )
        policy_switch_attempts: list[object] = []
        completed_policy_switches: list[bool] = []
        policy_validation_attempts: list[object] = []
        completed_policy_validations: list[object] = []

        def guarded_govlean_authority_switched(repo_dir: object) -> bool:
            if authorization_canary.called:
                raise AssertionError(
                    "sanctioned control reached repository policy after its "
                    "invocation-time backing factory"
                )
            if repo_dir is None or Path(repo_dir).resolve() != scratch:
                raise AssertionError(
                    "sanctioned control checked policy against a repository other "
                    "than its exact private projection"
                )
            if policy_switch_attempts:
                raise AssertionError(
                    "sanctioned control checked the authority switch more than once"
                )
            policy_switch_attempts.append(repo_dir)
            switched = original_govlean_authority_switched(repo_dir)
            completed_policy_switches.append(switched)
            record_protocol_step("policy:switch")
            return switched

        def guarded_validate_review_board_policy(
            review_board: object,
            policy: object,
            seat_aliases: object,
        ) -> object:
            if completed_policy_switches == []:
                raise AssertionError(
                    "sanctioned control validated landing policy before checking "
                    "the repository authority switch"
                )
            if authorization_canary.called:
                raise AssertionError(
                    "sanctioned control validated landing policy after its "
                    "invocation-time backing factory"
                )
            if policy_validation_attempts:
                raise AssertionError(
                    "sanctioned control validated landing policy more than once"
                )
            if review_board is not board or seat_aliases is not review_seat_aliases:
                raise AssertionError(
                    "sanctioned control validated a different board or seat aliases"
                )
            if supplied_review_policy is not None:
                policy_matches = policy is supplied_review_policy
            else:
                policy_matches = policy == expected_review_policy
            if not policy_matches:
                raise AssertionError(
                    "sanctioned control validated a different landing policy"
                )
            policy_validation_attempts.append(policy)
            result = original_validate_review_board_policy(
                review_board, policy, seat_aliases
            )
            completed_policy_validations.append(policy)
            record_protocol_step("policy:validate")
            return result

        def require_completed_policy_before_factory_or_resolution() -> None:
            if len(policy_switch_attempts) != 1 or len(completed_policy_switches) != 1:
                raise AssertionError(
                    "sanctioned control requires one successful repository policy "
                    "check before artifact resolution or dynamic factory lookup"
                )
            if policy_validation_required:
                if (
                    len(policy_validation_attempts) != 1
                    or len(completed_policy_validations) != 1
                ):
                    raise AssertionError(
                        "sanctioned control requires successful landing-policy "
                        "validation before artifact resolution or dynamic factory lookup"
                    )
            elif policy_validation_attempts or completed_policy_validations:
                raise AssertionError(
                    "sanctioned control performed an unrequested landing-policy validation"
                )
            elif completed_policy_switches != [False]:
                raise AssertionError(
                    "a switched repository reached the dynamic factory without an "
                    "explicit landing tier or policy"
                )

        expected_call = mock.call(
            board,
            resolved_artifact,
            mode=effective_mode,
            canonical_repo_authority=canonical_repo,
        )
        expected_resolve_artifact_call = mock.call(artifact, artifact_ref)
        expected_apply_context_refs_call = mock.call(
            resolved_inline_artifact,
            context_refs,
            soft_warn=context_refs_soft_warn,
        )

        def guarded_resolve_artifact(*args: object, **resolve_kwargs: object) -> object:
            require_completed_policy_before_factory_or_resolution()
            return original_resolve_artifact(*args, **resolve_kwargs)

        def guarded_apply_context_refs(
            *args: object, **context_kwargs: object
        ) -> object:
            require_completed_policy_before_factory_or_resolution()
            if resolve_artifact_spy.call_args_list != [expected_resolve_artifact_call]:
                raise AssertionError(
                    "sanctioned control applied context before exact artifact resolution"
                )
            return original_apply_context_refs(*args, **context_kwargs)

        def require_resolved_artifact_before_factory() -> None:
            if resolve_artifact_spy.call_args_list != [expected_resolve_artifact_call]:
                raise AssertionError(
                    "sanctioned board control requires production artifact resolution "
                    "before its invocation-time backing-factory lookup"
                )
            if apply_context_refs_spy.call_args_list != [
                expected_apply_context_refs_call
            ]:
                raise AssertionError(
                    "sanctioned board control requires production context-manifest "
                    "resolution before its invocation-time backing-factory lookup"
                )

        def resolved_authorization_factory(*args: object, **factory_kwargs: object) -> object:
            require_completed_policy_before_factory_or_resolution()
            require_resolved_artifact_before_factory()
            record_protocol_step("factory")
            return factory_marker

        authorization_canary.side_effect = resolved_authorization_factory

        def require_factory_before_effect() -> None:
            if authorization_canary.call_args_list != [expected_call]:
                raise AssertionError(
                    "sanctioned board control requires its invocation-time "
                    "backing-factory lookup before execution or observable effects"
                )

        original_revalidate_review_authorization = (
            invoker.revalidate_review_isolation_authorization
        )
        revalidation_attempts: list[object] = []
        completed_revalidations: list[object] = []
        artifact_mutated_after_factory = False

        def guarded_revalidate_review_authorization(
            supplied_authorization: object,
            review_board: object,
            review_artifact: object,
            *args: object,
            **revalidation_kwargs: object,
        ) -> object:
            nonlocal artifact_mutated_after_factory
            require_factory_before_effect()
            if effective_mode != "review":
                raise AssertionError("advisory control must not revalidate review authority")
            if (
                supplied_authorization is not authorization
                or review_board is not board
                or review_artifact != resolved_artifact
                or revalidation_kwargs.get("mode") != effective_mode
                or Path(revalidation_kwargs["canonical_repo_authority"]).resolve()
                != canonical_repo
            ):
                raise AssertionError(
                    "sanctioned review control revalidated a different authorization, "
                    "board, artifact, mode, or canonical repository"
                )
            if mutate_artifact_after_factory is not None and not artifact_mutated_after_factory:
                mutate_artifact_after_factory()
                artifact_mutated_after_factory = True
            revalidation_attempts.append(supplied_authorization)
            result = original_revalidate_review_authorization(
                supplied_authorization,
                review_board,
                review_artifact,
                *args,
                **revalidation_kwargs,
            )
            if result is not False:
                completed_revalidations.append(supplied_authorization)
                record_protocol_step("revalidation")
            return result

        def require_review_revalidation_before_effect() -> None:
            if effective_mode == "review" and completed_revalidations != [authorization]:
                raise AssertionError(
                    "sanctioned review control requires successful independent "
                    "revalidation before staging or downstream effects"
                )

        def require_authorized_before_effect() -> None:
            require_factory_before_effect()
            require_review_revalidation_before_effect()

        observable_ordering_violations: list[str] = []

        def guard_observable_effect() -> bool:
            try:
                require_authorized_before_effect()
                require_completed_capture_seal_before_downstream()
            except AssertionError as exc:
                observable_ordering_violations.append(str(exc))
                return False
            return True

        matrix_module = importlib.import_module("phase_loop_runtime.advisor_board.matrix")
        static_capture_matrix_factory = matrix_module.default_matrix
        capture_enabled = call_kwargs.get("agy_canary_capture") is not None
        expected_capture_identities: tuple[tuple[str, str], ...] = ()
        if capture_enabled:
            # Reuse the board invoker's own static capture-resolution path: capture
            # validates lane identity without touching the live registry or ambient
            # authentication, then freezes its launch order by resolved board index.
            capture_board = invoker._resolve_and_validate_board(
                board,
                static_capture_matrix_factory(
                    env={}, probe=invoker._LEG_CLI.__contains__
                ),
            )
            expected_capture_identities = tuple(
                ((seat.harness or "").lower(), str(seat.seat_key))
                for seat in capture_board.seats
                if (seat.harness or "").lower() in invoker._LEG_CLI
            )
            if len(expected_capture_identities) != len(capture_board.seats):
                raise AssertionError(
                    "capture control must retain one native provider identity for "
                    "every resolved board seat"
                )

        def require_capture_preparation_before_seal() -> None:
            if capture_enabled and not cleanup_root_allocations:
                raise AssertionError(
                    "capture reached launch sealing before owned cleanup-root "
                    "allocation completed"
                )
            if capture_enabled and not staged_input_chains:
                raise AssertionError(
                    "capture reached launch sealing before its allocated review "
                    "stage was bound"
                )
            if capture_enabled and not provider_authority_chains:
                raise AssertionError(
                    "capture reached launch sealing before provider authority "
                    "preparation completed"
                )
            if capture_enabled:
                if len(cleanup_root_allocations) != len(expected_capture_identities):
                    raise AssertionError(
                        "capture sealing requires one ordered cleanup allocation per "
                        "resolved board seat"
                    )
                if len(staged_input_chains) != 1:
                    raise AssertionError(
                        "capture sealing requires exactly the production first-stage "
                        "evidence binding"
                    )
                first_root, first_stage, first_authority = staged_input_chains[0]
                if (first_root, first_stage, first_authority) != (
                    cleanup_root_allocations[0][0],
                    cleanup_root_allocations[0][0] / "review",
                    cleanup_root_allocations[0][1],
                ):
                    raise AssertionError(
                        "capture staging did not bind the first exact allocated root"
                    )
                if len(provider_authority_chains) != len(expected_capture_identities):
                    raise AssertionError(
                        "capture sealing requires one ordered provider authority "
                        "per resolved board seat"
                    )
                for index, (provider, root, stage, _authority) in enumerate(
                    provider_authority_chains
                ):
                    expected_provider, _expected_seat_key = expected_capture_identities[
                        index
                    ]
                    allocated_root, _cleanup_authority = cleanup_root_allocations[index]
                    if (
                        provider != expected_provider
                        or root != allocated_root
                        or stage != allocated_root / "review"
                    ):
                        raise AssertionError(
                            "capture provider authority order did not preserve the "
                            "exact allocation-stage-provider chain"
                        )

        def require_completed_capture_seal_before_downstream() -> None:
            if capture_enabled and len(provider_launch_seal_calls) != 1:
                raise AssertionError(
                    "capture reached a downstream effect before exactly one successful "
                    "provider-launch seal"
                )

        if spawn is not None:
            original_spawn = spawn
            spawn_calls: list[object] = []

            def guarded_spawn(*args: object, **spawn_kwargs: object) -> object:
                require_authorized_before_effect()
                require_completed_capture_seal_before_downstream()
                if len(args) < 2 or args[1] != resolved_artifact:
                    raise AssertionError("spawn did not receive the factory-bound artifact")
                spawn_calls.append((args, spawn_kwargs))
                record_protocol_step(f"spawn:{args[0]}")
                return original_spawn(*args, **spawn_kwargs)

            call_kwargs["spawn"] = guarded_spawn

        on_leg_complete = call_kwargs.get("on_leg_complete")
        completion_calls: list[object] = []
        if on_leg_complete is not None:
            def guarded_on_leg_complete(*args: object, **callback_kwargs: object) -> object:
                completion_calls.append((args, callback_kwargs))
                if not guard_observable_effect():
                    return None
                record_protocol_step("completion")
                return on_leg_complete(*args, **callback_kwargs)

            call_kwargs["on_leg_complete"] = guarded_on_leg_complete

        sink = call_kwargs.get("sink")
        sink_calls: list[object] = []
        if sink is not None:
            class GuardedSink:
                def emit(self, event: object) -> object:
                    sink_calls.append(event)
                    if not guard_observable_effect():
                        return None
                    record_protocol_step("sink")
                    return sink.emit(event)

            call_kwargs["sink"] = GuardedSink()

        original_provider = invoker._default_spawn_via_provider
        provider_calls: list[object] = []
        provider_launch_chains: list[tuple[str, str, Path, Path, object]] = []

        def guarded_provider(*args: object, **provider_kwargs: object) -> object:
            require_authorized_before_effect()
            require_completed_capture_seal_before_downstream()
            sealed_chain = require_sealed_capture_launch_identity(
                args[0] if args else None, provider_kwargs
            )
            if len(args) < 2 or args[1] != resolved_artifact:
                raise AssertionError("provider did not receive the factory-bound artifact")
            if sealed_chain is not None:
                provider_launch_chains.append(sealed_chain)
            provider_calls.append((args, provider_kwargs))
            record_protocol_step(f"provider:{args[0]}")
            return original_provider(*args, **provider_kwargs)

        original_default_spawn = invoker._default_spawn
        direct_child_calls: list[object] = []
        direct_child_launch_chains: list[tuple[str, str, Path, Path, object]] = []

        def guarded_default_spawn(*args: object, **child_kwargs: object) -> object:
            require_authorized_before_effect()
            require_completed_capture_seal_before_downstream()
            sealed_chain = require_sealed_capture_launch_identity(
                args[0] if args else None, child_kwargs
            )
            if len(args) < 2 or args[1] != resolved_artifact:
                raise AssertionError(
                    "direct child did not receive the factory-bound artifact"
                )
            if sealed_chain is not None:
                direct_child_launch_chains.append(sealed_chain)
            direct_child_calls.append((args, child_kwargs))
            record_protocol_step(f"child:{args[0]}")
            return original_default_spawn(*args, **child_kwargs)

        original_create_owned_cleanup_root = invoker._create_owned_cleanup_root
        cleanup_root_allocation_calls: list[object] = []
        cleanup_root_allocations: list[tuple[Path, object]] = []

        def guarded_create_owned_cleanup_root(
            *args: object, **cleanup_kwargs: object
        ) -> object:
            require_authorized_before_effect()
            result = original_create_owned_cleanup_root(*args, **cleanup_kwargs)
            if not isinstance(result, tuple) or len(result) != 2:
                raise AssertionError("cleanup-root factory returned an invalid allocation")
            root, authority = result
            if not isinstance(root, Path):
                raise AssertionError("cleanup-root factory did not return a Path root")
            resolved_root = root.resolve()
            if any(existing_root == resolved_root for existing_root, _ in cleanup_root_allocations):
                raise AssertionError("cleanup-root factory reused an allocated root")
            cleanup_root_allocation_calls.append((args, cleanup_kwargs))
            cleanup_root_allocations.append((resolved_root, authority))
            record_protocol_step("allocation")
            return result

        original_bind_staged_review_inputs = invoker.bind_staged_review_inputs
        staged_input_calls: list[object] = []
        staged_input_chains: list[tuple[Path, Path, object]] = []

        def allocation_for_stage(stage: object) -> tuple[Path, object]:
            if not isinstance(stage, Path):
                raise AssertionError("capture stage was not a Path")
            resolved_stage = stage.resolve()
            for root, authority in cleanup_root_allocations:
                if resolved_stage == root / "review":
                    return root, authority
            raise AssertionError(
                "capture stage is not the production review descendant of an "
                "allocated cleanup root"
            )

        def guarded_bind_staged_review_inputs(
            *args: object, **stage_kwargs: object
        ) -> object:
            require_authorized_before_effect()
            root, authority = allocation_for_stage(stage_kwargs.get("review_dir"))
            if stage_kwargs.get("bundle_bytes") != resolved_artifact.encode("utf-8"):
                raise AssertionError(
                    "staged review bundle did not preserve the factory-bound artifact bytes"
                )
            result = original_bind_staged_review_inputs(*args, **stage_kwargs)
            staged_input_calls.append((args, stage_kwargs))
            staged_input_chains.append((root, (root / "review"), authority))
            record_protocol_step("stage")
            return result

        original_prepare_provider_launch_authorities = (
            invoker.prepare_provider_launch_authorities
        )
        provider_authority_calls: list[object] = []
        provider_authority_chains: list[tuple[str, Path, Path, object]] = []

        def guarded_prepare_provider_launch_authorities(
            *args: object, **authority_kwargs: object
        ) -> object:
            require_authorized_before_effect()
            if not staged_input_chains:
                raise AssertionError(
                    "capture provider authority was prepared before staged inputs bound"
                )
            root, _cleanup_authority = allocation_for_stage(
                authority_kwargs.get("stage")
            )
            stage = root / "review"
            if (stage / "review-bundle.md").read_bytes() != resolved_artifact.encode(
                "utf-8"
            ):
                raise AssertionError(
                    "capture provider authority did not use the factory-bound staged bundle"
                )
            providers = authority_kwargs.get("providers")
            if not isinstance(providers, tuple) or not providers:
                raise AssertionError("capture provider authority was not scoped to providers")
            if capture_enabled:
                index = len(provider_authority_chains)
                if index >= len(expected_capture_identities):
                    raise AssertionError(
                        "capture prepared more provider authorities than resolved seats"
                    )
                expected_provider, _expected_seat_key = expected_capture_identities[index]
                if providers != (expected_provider,):
                    raise AssertionError(
                        "capture provider authority did not preserve the resolved "
                        "board provider order"
                    )
            result = original_prepare_provider_launch_authorities(*args, **authority_kwargs)
            for provider in providers:
                if not isinstance(provider, str):
                    raise AssertionError("capture provider authority provider was malformed")
                try:
                    authority = result[provider]
                except (KeyError, TypeError) as exc:
                    raise AssertionError(
                        "capture provider authority result omitted its requested provider"
                    ) from exc
                provider_authority_chains.append((provider, root, stage, authority))
                record_protocol_step(f"authority:{provider}")
            provider_authority_calls.append((args, authority_kwargs))
            return result

        original_seal_provider_launches = invoker.seal_provider_launches
        provider_launch_seal_calls: list[object] = []

        def guarded_seal_provider_launches(
            *args: object, **seal_kwargs: object
        ) -> object:
            require_authorized_before_effect()
            require_capture_preparation_before_seal()
            launches = seal_kwargs.get("launches")
            if not isinstance(launches, tuple) or not launches:
                raise AssertionError("capture launch seal did not receive launch authorities")
            if len(launches) != len(expected_capture_identities):
                raise AssertionError(
                    "capture launch seal did not preserve resolved board cardinality"
                )
            if len(provider_authority_chains) != len(expected_capture_identities):
                raise AssertionError(
                    "capture launch seal did not receive every prepared authority"
                )
            sealed_chains: list[tuple[str, str, Path, Path, object]] = []
            for index, launch in enumerate(launches):
                if not isinstance(launch, tuple) or len(launch) != 3:
                    raise AssertionError("capture launch seal entry was malformed")
                provider, seat_key, launch_authority = launch
                expected_provider, expected_seat_key = expected_capture_identities[index]
                chain_provider, chain_root, chain_stage, chain_authority = (
                    provider_authority_chains[index]
                )
                if (
                    provider != expected_provider
                    or seat_key != expected_seat_key
                    or chain_provider != expected_provider
                    or launch_authority is not chain_authority
                ):
                    raise AssertionError(
                        "capture launch seal did not preserve the exact ordered "
                        "provider-seat-authority chain"
                    )
                sealed_chains.append(
                    (provider, seat_key, chain_root, chain_stage, chain_authority)
                )
            result = original_seal_provider_launches(*args, **seal_kwargs)
            provider_launch_seal_calls.append((args, seal_kwargs, tuple(sealed_chains)))
            record_protocol_step("seal")
            return result

        def require_sealed_capture_launch_identity(
            leg: object, launch_kwargs: dict[str, object]
        ) -> tuple[str, str, Path, Path, object] | None:
            if not capture_enabled:
                return None
            authority = launch_kwargs.get("provider_authority")
            stage = launch_kwargs.get("capture_stage")
            scratch = launch_kwargs.get("capture_scratch")
            if not isinstance(stage, Path) or not isinstance(scratch, Path):
                raise AssertionError(
                    "capture downstream launch omitted its staged-root identity"
                )
            resolved_stage = stage.resolve()
            resolved_scratch = scratch.resolve()
            sealed_chains = provider_launch_seal_calls[0][2]
            if not isinstance(leg, str):
                raise AssertionError("capture downstream launch omitted its provider leg")
            seat_key = launch_kwargs.get("seat_key")
            if not isinstance(seat_key, str):
                raise AssertionError("capture downstream launch omitted its exact seat key")
            matching = [
                chain
                for chain in sealed_chains
                if chain[0] == leg
                and chain[1] == seat_key
                and chain[2] == resolved_scratch
                and chain[3] == resolved_stage
                and chain[4] is authority
            ]
            if len(matching) != 1:
                raise AssertionError(
                    "capture downstream launch did not use its exact sealed "
                    "provider-seat-allocation-stage-authority chain"
                )
            return matching[0]

        def assert_exact_sealed_chain_consumption(
            label: str,
            consumed: list[tuple[str, str, Path, Path, object]],
        ) -> None:
            if len(provider_launch_seal_calls) != 1:
                raise AssertionError(
                    f"capture {label} cardinality requires exactly one successful seal"
                )
            sealed = provider_launch_seal_calls[0][2]
            if len(consumed) != len(sealed):
                raise AssertionError(
                    f"capture {label} cardinality did not match every sealed launch"
                )
            remaining = list(sealed)
            for chain in consumed:
                matches = [
                    index
                    for index, expected in enumerate(remaining)
                    if chain[:4] == expected[:4] and chain[4] is expected[4]
                ]
                if len(matches) != 1:
                    raise AssertionError(
                        f"capture {label} duplicated or substituted a sealed launch"
                    )
                remaining.pop(matches[0])
            if remaining:
                raise AssertionError(
                    f"capture {label} omitted a sealed launch"
                )

        live_matrix_calls: list[object] = []
        live_availability_calls: list[object] = []
        registry = matrix_module.DEFAULT_HARNESS_REGISTRY
        original_default_matrix = invoker.default_matrix

        def guarded_default_matrix(*args: object, **matrix_kwargs: object) -> object:
            require_authorized_before_effect()
            require_completed_capture_seal_before_downstream()
            live_matrix_calls.append((args, matrix_kwargs))
            record_protocol_step("matrix:start")
            deterministic_kwargs = dict(matrix_kwargs)
            deterministic_kwargs["env"] = {}
            result = original_default_matrix(*args, **deterministic_kwargs)
            record_protocol_step("matrix:complete")
            return result

        def guarded_live_availability(*args: object, **availability_kwargs: object) -> bool:
            require_authorized_before_effect()
            require_completed_capture_seal_before_downstream()
            live_availability_calls.append((args, availability_kwargs))
            record_protocol_step("availability")
            return True

        research_materialization_calls: list[object] = []
        original_materialize_research_run = invoker.materialize_research_run

        def guarded_materialize_research_run(
            *args: object, **research_kwargs: object
        ) -> object:
            require_authorized_before_effect()
            require_completed_capture_seal_before_downstream()
            research_materialization_calls.append((args, research_kwargs))
            record_protocol_step("research")
            return original_materialize_research_run(*args, **research_kwargs)

        incremental_verdict_calls: list[object] = []
        original_write_incremental_verdict = invoker._write_incremental_verdict

        def guarded_write_incremental_verdict(
            *args: object, **verdict_kwargs: object
        ) -> object:
            require_authorized_before_effect()
            require_completed_capture_seal_before_downstream()
            incremental_verdict_calls.append((args, verdict_kwargs))
            record_protocol_step("writer")
            return original_write_incremental_verdict(*args, **verdict_kwargs)

        omnigent = call_kwargs.get("omnigent")
        omnigent_calls: list[object] = []
        if omnigent is not None:
            class GuardedOmnigent:
                def catalog_harnesses(self) -> object:
                    require_authorized_before_effect()
                    require_completed_capture_seal_before_downstream()
                    omnigent_calls.append("catalog")
                    record_protocol_step("omnigent:catalog")
                    return omnigent.catalog_harnesses()

                def run_seat(
                    self, *args: object, **omnigent_kwargs: object
                ) -> object:
                    require_authorized_before_effect()
                    require_completed_capture_seal_before_downstream()
                    if len(args) < 2 or args[1] != resolved_artifact:
                        raise AssertionError(
                            "Omnigent did not receive the factory-bound artifact"
                        )
                    omnigent_calls.append("run")
                    record_protocol_step("omnigent:run")
                    return omnigent.run_seat(*args, **omnigent_kwargs)

            call_kwargs["omnigent"] = GuardedOmnigent()

        caught_static_refusal: Exception | None = None
        result: object = _UNSET
        stack = ExitStack()
        try:
            resolve_artifact_spy = stack.enter_context(mock.patch.object(
                invoker,
                "_resolve_artifact",
                side_effect=guarded_resolve_artifact,
            ))
            apply_context_refs_spy = stack.enter_context(mock.patch.object(
                invoker,
                "_apply_context_refs",
                side_effect=guarded_apply_context_refs,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "_govlean_authority_switched",
                side_effect=guarded_govlean_authority_switched,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "_validate_review_board_policy",
                side_effect=guarded_validate_review_board_policy,
            ))
            stack.enter_context(mock.patch.object(
                backing,
                "prepare_review_isolation_authorization",
                authorization_canary,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "revalidate_review_isolation_authorization",
                side_effect=guarded_revalidate_review_authorization,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "_default_spawn_via_provider",
                side_effect=guarded_provider,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "_default_spawn",
                side_effect=guarded_default_spawn,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "_create_owned_cleanup_root",
                side_effect=guarded_create_owned_cleanup_root,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "bind_staged_review_inputs",
                side_effect=guarded_bind_staged_review_inputs,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "prepare_provider_launch_authorities",
                side_effect=guarded_prepare_provider_launch_authorities,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "seal_provider_launches",
                side_effect=guarded_seal_provider_launches,
            ))
            leg_auth_calls: list[object] = []
            claude_auth_calls: list[object] = []
            claude_support_calls: list[object] = []
            original_leg_auth_ok = invoker._leg_auth_ok
            original_claude_subscription_auth_ok = invoker._claude_subscription_auth_ok
            original_claude_code_support_status = invoker._claude_code_support_status

            def guarded_leg_auth_ok(
                *args: object, **auth_kwargs: object
            ) -> object:
                require_authorized_before_effect()
                require_completed_capture_seal_before_downstream()
                leg_auth_calls.append((args, auth_kwargs))
                record_protocol_step("auth:leg")
                return original_leg_auth_ok(*args, **auth_kwargs)

            def guarded_claude_subscription_auth_ok(
                *args: object, **auth_kwargs: object
            ) -> object:
                require_authorized_before_effect()
                require_completed_capture_seal_before_downstream()
                claude_auth_calls.append((args, auth_kwargs))
                record_protocol_step("auth:claude")
                return original_claude_subscription_auth_ok(*args, **auth_kwargs)

            def guarded_claude_code_support_status(
                *args: object, **support_kwargs: object
            ) -> object:
                require_authorized_before_effect()
                require_completed_capture_seal_before_downstream()
                claude_support_calls.append((args, support_kwargs))
                record_protocol_step("auth:claude-support")
                return original_claude_code_support_status(*args, **support_kwargs)

            stack.enter_context(mock.patch.object(
                invoker,
                "_leg_auth_ok",
                side_effect=guarded_leg_auth_ok,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "_claude_subscription_auth_ok",
                side_effect=guarded_claude_subscription_auth_ok,
            ))
            stack.enter_context(mock.patch.object(
                invoker,
                "_claude_code_support_status",
                side_effect=guarded_claude_code_support_status,
            ))
            if guard_live_matrix_probe:
                stack.enter_context(mock.patch.object(
                    invoker,
                    "default_matrix",
                    side_effect=guarded_default_matrix,
                ))
                stack.enter_context(mock.patch.object(
                    registry,
                    "is_available",
                    side_effect=guarded_live_availability,
                ))
            if requires_research_materialization:
                stack.enter_context(mock.patch.object(
                    invoker,
                    "materialize_research_run",
                    side_effect=guarded_materialize_research_run,
                ))
            if requires_incremental_verdict_write:
                stack.enter_context(mock.patch.object(
                    invoker,
                    "_write_incremental_verdict",
                    side_effect=guarded_write_incremental_verdict,
                ))
            result = invoker.invoke_board(board, artifact, **call_kwargs)
        except Exception as exc:
            if not expect_static_refusal_before_effects:
                raise
            caught_static_refusal = exc
        finally:
            stack.close()

        require_completed_policy_before_factory_or_resolution()
        if authorization_canary.call_args_list != [expected_call]:
            raise AssertionError(
                "sanctioned board control requires exactly one invocation-time "
                "backing-factory lookup bound to its explicit control marker"
            )
        if resolve_artifact_spy.call_args_list != [expected_resolve_artifact_call]:
            raise AssertionError(
                "sanctioned board control did not preserve the exact production "
                "artifact resolution call"
            )
        if apply_context_refs_spy.call_args_list != [expected_apply_context_refs_call]:
            raise AssertionError(
                "sanctioned board control did not preserve the exact production "
                "context-manifest resolution call"
            )
        if observable_ordering_violations:
            raise AssertionError(observable_ordering_violations[0])
        if effective_mode == "review" and not forbid_pre_authorization_effects:
            assert revalidation_attempts == [authorization]
            assert completed_revalidations == [authorization]
        if effective_mode == "advisory":
            assert not revalidation_attempts
        if require_live_matrix_probe and not expect_static_refusal_before_effects:
            assert live_matrix_calls, "sanctioned control did not construct a default matrix"
        if require_live_matrix_probe and not expect_static_refusal_before_effects:
            assert live_availability_calls, (
                "sanctioned control did not consume the live availability/auth probe"
            )
        if (
            requires_research_materialization
            and not forbid_pre_authorization_effects
            and not expect_static_refusal_before_effects
        ):
            assert research_materialization_calls, (
                "sanctioned research control did not materialize its research run"
            )
        if (
            requires_incremental_verdict_write
            and not forbid_pre_authorization_effects
            and not expect_static_refusal_before_effects
        ):
            assert incremental_verdict_calls, (
                "sanctioned streaming control did not publish an incremental verdict"
            )
        if (
            capture_enabled
            and not forbid_pre_authorization_effects
            and not expect_static_refusal_before_effects
        ):
            assert cleanup_root_allocation_calls, (
                "sanctioned capture did not allocate its owned cleanup root"
            )
            assert_exact_sealed_chain_consumption(
                "provider", provider_launch_chains
            )
            assert_exact_sealed_chain_consumption(
                "direct child", direct_child_launch_chains
            )
        if forbid_pre_authorization_effects or expect_static_refusal_before_effects:
            assert not live_matrix_calls
            assert not live_availability_calls
            assert not research_materialization_calls
            assert not incremental_verdict_calls
            assert not direct_child_calls
            assert not cleanup_root_allocation_calls
            assert not staged_input_calls
            assert not provider_authority_calls
            assert not provider_launch_seal_calls
            assert not provider_calls
            assert not omnigent_calls
            assert not leg_auth_calls
            assert not claude_auth_calls
            assert not claude_support_calls
            if effective_mode == "review" and forbid_pre_authorization_effects:
                assert revalidation_attempts == [authorization]
                assert not completed_revalidations
            if spawn is not None:
                assert not spawn_calls
            assert not completion_calls
            assert not sink_calls
        if expect_static_refusal_before_effects:
            if caught_static_refusal is None:
                raise AssertionError(
                    "sanctioned static-refusal control returned instead of refusing"
                )
            raise caught_static_refusal
        if result is _UNSET:
            raise AssertionError("sanctioned board control produced no result")
        return result


def invoke_sanctioned_review_transport(
    board: object,
    artifact: str,
    *,
    spawn: object | None = None,
    mode: str | None = None,
    **kwargs: object,
) -> object:
    """Compatibility name for the explicit board-control protocol."""

    return invoke_sanctioned_board_control(
        board, artifact, spawn=spawn, mode=mode, **kwargs
    )
