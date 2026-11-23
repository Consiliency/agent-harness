"""The LaneExec launch service: construction, prepare, status and cancel (LANEEXEC SL-3).

:func:`build_launch_service` is the one construction site (``x-in-process-api``). It stores
the captured client configuration (binding §7 E3-2: the ``PlacementClientConfig``) and every
injection seam the launch lanes use, with the landed functions as defaults:

* ``capped_popen``, ``load_caps`` and ``readiness_code`` (``seat_resource_caps``; its
  internals are never patched);
* ``route_state`` (binding §6 E2-2) and the clock;
* the admission bound (binding §7 E3-1, 300 s);
* the :class:`~phase_loop_runtime.sandbox_placement.PlacementLifecycle` that PLACECLI tests
  already inject, which holds the LaneExec journal hooks (prepare record, exec claim and its
  rollback, the local heartbeat, release and reap);
* the worker JOURNAL readers that status and cancel consume (``attempt_status`` and
  ``cancel_attempt``) and the worker state root they read.

Construction decodes no setting and consults no route table, so ``prepare``, ``status`` and
``cancel`` work on their own. ``launch`` is one call to ``launch_exec.launch_attempt``,
imported when it is called (binding §7 E3-3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
import threading
from typing import TYPE_CHECKING, Any, Callable, Mapping

from . import sandbox_policy
from .launch_process_contract import (
    CLIENTS,
    TERMINAL_STATUS_STATES,
    CancelResponse,
    LaunchRequest,
    LaunchResponse,
    StatusResponse,
)
from .launch_return import STATUS_UNCERTAIN_CODE, map_cancel, map_status
from .sandbox_placement import CANCEL_WAIT_S, LifecycleError, PlacementLifecycle

__all__ = [
    "ADMISSION_BOUND_S",
    "LaunchService",
    "LaneContext",
    "LaneUnits",
    "build_launch_service",
]

#: Binding §7 E3-1: the launch process kills the admission helper's group after this long.
ADMISSION_BOUND_S = 300.0


if TYPE_CHECKING:
    from .launch_supervisor import SupervisorHandoff


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value) is not None


def _strings(values: object) -> bool:
    return type(values) is tuple and all(type(s) is str and s for s in values)


@dataclass(frozen=True, slots=True)
class LaneUnits:
    target_unit_ids: tuple[str, ...]
    readonly_neighbor_unit_ids: tuple[str, ...]
    snapshot_ref: str
    crosswalk_ref: str

    def __post_init__(self) -> None:
        if not (self.target_unit_ids and _strings(self.target_unit_ids)
                and _strings(self.readonly_neighbor_unit_ids)
                and all(len(s) <= 200 for s in self.target_unit_ids + self.readonly_neighbor_unit_ids)
                and _digest(self.snapshot_ref) and _digest(self.crosswalk_ref)):
            raise ValueError("invalid lane units")


@dataclass(frozen=True, slots=True)
class LaneContext:
    assignment_digest: str
    units: LaneUnits
    repo_relative_locators: tuple[str, ...]
    definition_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (_digest(self.assignment_digest) and type(self.units) is LaneUnits
                and self.repo_relative_locators and _strings(self.repo_relative_locators)
                and all(all(part not in ("", ".", "..") for part in path.split("/"))
                        and not any(ord(c) < 32 or c in ":\\\x7f" for c in path)
                        for path in self.repo_relative_locators)
                and _strings(self.definition_digests) and all(map(_digest, self.definition_digests))):
            raise ValueError("invalid lane context")


def _landed_capped_popen() -> Callable[..., Any]:
    from . import seat_resource_caps

    return seat_resource_caps.capped_popen


def _landed_load_caps() -> Callable[[], object]:
    from . import seat_resource_caps

    return seat_resource_caps.load_caps


def _landed_readiness_code() -> Callable[[], str | None]:
    from . import seat_resource_caps

    return seat_resource_caps.readiness_code


def _landed_worker_state_root() -> Path:
    from .convergence.adapters.patch_return import default_state_root

    return default_state_root()


def _landed_attempt_status(state_root: Path, attempt_id: str) -> object:
    """The worker JOURNAL's ``attempt_status`` for ``attempt_id``, or None when there is no
    JOURNAL at all."""
    from . import run_status
    from .run_status_projection import attempt_status

    root = run_status.open_journal_root(Path(state_root) / "journal", create=False)
    if isinstance(root, run_status.JournalRefused):
        return None
    return attempt_status(root, attempt_id)


def _landed_cancel_attempt(state_root: Path, attempt_id: str, wait_s: float) -> str:
    from .convergence.adapters.patch_return import cancel_attempt

    return cancel_attempt(state_root=Path(state_root), attempt_id=attempt_id,
                          wait_seconds=wait_s)


class LaunchService:
    """``LaunchService.prepare|launch|status|cancel`` for one ``--client``.

    Built only by :func:`build_launch_service`. Every caller, the console entry included,
    uses the one service it returns (``x-in-process-api.rule``)."""

    def __init__(self, client: str, config: "sandbox_policy.PlacementClientConfig", *,
                 lifecycle: PlacementLifecycle, capped_popen: Callable[..., Any],
                 load_caps: Callable[[], object], readiness_code: Callable[[], str | None],
                 route_state: Callable[[], str], clock: Callable[[], float],
                 supervisor_runner: Callable[[SupervisorHandoff], None] | None,
                 admission_bound_s: float, worker_state_root: Path,
                 attempt_status: Callable[[Path, str], object],
                 cancel_attempt: Callable[[Path, str, float], str]) -> None:
        # None selects the SL-8 production detachment path. Only factory injection
        # may supply a callable for the in-process handoff.
        self.supervisor_runner = supervisor_runner
        self.client = client
        self.config = config
        self.lifecycle = lifecycle
        self.capped_popen = capped_popen
        self.load_caps = load_caps
        self.readiness_code = readiness_code
        self.route_state = route_state
        self.clock = clock
        self.admission_bound_s = admission_bound_s
        self.worker_state_root = worker_state_root
        self._attempt_status = attempt_status
        self._cancel_attempt = cancel_attempt

    # -- prepare -------------------------------------------------------------------------
    def caps_readable(self) -> bool:
        """Coordinator ruling 1: whether the caps record loads."""
        try:
            self.load_caps()
        except Exception:
            return False
        return True

    def prepare(self, request: Any) -> Any:
        """``LaunchService.prepare(request) -> PrepareResponse`` (``x-prepare``). An internal
        failure raises ``sandbox_placement.LifecycleError`` (exit class 70)."""
        return self.lifecycle.launch_prepare(request, caps_readable=self.caps_readable())

    # -- launch (late-bound, SL-8) -------------------------------------------------------
    def launch(self, request: Any, *, cancelled: threading.Event, pre_exec: Any = None,
               withhold: Any = None) -> Any:
        """``LaunchService.launch``: one call to the launch order, bound at call time."""
        from . import launch_exec  # late-bound seam (binding §7 E3-3)

        return launch_exec.launch_attempt(self, request, cancelled=cancelled,
                                          pre_exec=pre_exec, withhold=withhold)

    def launch_lane(self, request: LaunchRequest, *, lane_context: LaneContext,
                    cancelled: threading.Event, pre_exec: Any = None,
                    withhold: Any = None) -> LaunchResponse:
        from . import launch_exec

        return launch_exec.launch_attempt(self, request, origin="lane", lane_context=lane_context,
                                          cancelled=cancelled, pre_exec=pre_exec, withhold=withhold)

    # -- status and cancel (L-S4) ---------------------------------------------------------
    def _record(self, request: Any) -> dict[str, object] | None:
        """The launch record for ``launch_request_id`` in this client's inventory, when it
        belongs to the named reservation; another inventory is never read."""
        record = self.lifecycle.launch_record(request.launch_request_id)
        if record is None or record.get("reservation_id") != request.reservation_id:
            return None
        return record

    def _claim_held(self, record: Mapping[str, object], launch_request_id: str) -> bool:
        claim = self.lifecycle.launch_claim_record(str(record["reservation_id"]))
        return bool(claim is not None and claim.get("claimed") is True
                    and claim.get("request_id") == launch_request_id
                    and claim.get("generation") == record.get("generation"))

    def _journal(self, run_id: object) -> object:
        if not isinstance(run_id, str):
            return None
        try:
            return self._attempt_status(self.worker_state_root, run_id)
        except Exception:
            return None

    def status(self, request: Any) -> StatusResponse:
        """``LaunchService.status(request) -> StatusResponse``: read-only, the L-S4 table."""
        def response(state: str, launch: LaunchResponse | None, run_id: object,
                     scratch: object, tree: object) -> StatusResponse:
            return StatusResponse(request.request_id, request.reservation_id,
                                  request.launch_request_id, state, launch,
                                  run_id, scratch, tree, request.caller_context)  # type: ignore[arg-type]

        record = self._record(request)
        if record is None:
            return response("unknown_attempt", None, None, None, None)
        terminal = self.lifecycle.launch_terminal(request.launch_request_id)
        claim_held = self._claim_held(record, request.launch_request_id)
        journal = None if terminal is not None else self._journal(record.get("run_id"))
        mapping = map_status(record_present=True, terminal=terminal, journal=journal,  # type: ignore[arg-type]
                             claim_held=claim_held)
        if mapping.state in TERMINAL_STATUS_STATES:
            launch = mapping.launch or self._uncertain(record, request.launch_request_id, claim_held)
            return response(mapping.state, launch, launch.attempt_id, launch.scratch_path,
                            launch.tree_path)
        return response(mapping.state, None, record.get("run_id"), record.get("scratch_path"),
                        record.get("tree_path"))

    def _uncertain(self, record: Mapping[str, object], launch_request_id: str,
                   claim_held: bool) -> LaunchResponse:
        """The synthesized ``uncertain`` launch for a status LaneExec cannot settle: the
        attempt's paths while it holds a claim, else null (``x-scratch-path.presence``)."""
        invocations = record.get("worker_invocations")
        digest = record.get("envelope_digest")
        context = record.get("caller_context")
        held = claim_held is True
        return LaunchResponse(
            launch_request_id, str(record["reservation_id"]),
            record.get("run_id") if held else None,  # type: ignore[arg-type]
            "uncertain", STATUS_UNCERTAIN_CODE, None, None, None, None,
            invocations if type(invocations) is int and invocations >= 0 else 0,  # type: ignore[arg-type]
            digest if isinstance(digest, str) else None,
            record.get("scratch_path") if held else None,  # type: ignore[arg-type]
            record.get("tree_path") if held else None,  # type: ignore[arg-type]
            None, None, dict(context) if isinstance(context, Mapping) else {})

    def cancel(self, request: Any, *, cancelled: threading.Event) -> CancelResponse:
        """``LaunchService.cancel(request, *, cancelled) -> CancelResponse``: idempotent,
        through the verified owning launcher only (``cancel_attempt``), never a pgid taken
        from a journal. A zero-signal outcome is ``cancel_pending`` and is journaled in the
        LaneExec launch record (L-S4)."""
        def response(state: str) -> CancelResponse:
            return CancelResponse(request.request_id, request.reservation_id,
                                  request.launch_request_id, state, request.caller_context)  # type: ignore[arg-type]

        record = self._record(request)
        if record is None:
            return response(map_cancel(None, record_present=False, claim_held=False).state)
        if self.lifecycle.launch_terminal(request.launch_request_id) is not None:
            return response("already_terminal")
        claim_held = self._claim_held(record, request.launch_request_id)
        outcome: str | None = None
        run_id = record.get("run_id")
        if not cancelled.is_set() and isinstance(run_id, str):
            wait = min(CANCEL_WAIT_S, max(0.001, request.deadline_ms / 1000.0))
            try:
                if record.get("generation") is not None:
                    result = self.lifecycle.cancel_launch_owner(
                        request.reservation_id, request.launch_request_id, record["generation"],
                        deadline=time.monotonic() + wait)
                elif (self.lifecycle.launch_claim_record(request.reservation_id) or {}).get("generation"):
                    result = "owner_unverified"
                else:
                    result = self._cancel_attempt(self.worker_state_root, run_id, wait)
                outcome = result if isinstance(result, str) else None
            except LifecycleError as error:
                if error.code == "placement_control_socket_invariant":
                    raise
                outcome = None
            except Exception:
                outcome = None
        mapping = map_cancel(outcome, record_present=True, claim_held=claim_held)
        if mapping.local_outcome is not None:
            self.lifecycle.journal_local_cancel(request.launch_request_id, mapping.local_outcome)
        return response(mapping.state)


def build_launch_service(
    client: str, *, config: "sandbox_policy.PlacementClientConfig",
    lifecycle: PlacementLifecycle | None = None,
    capped_popen: Callable[..., Any] | None = None,
    load_caps: Callable[[], object] | None = None,
    readiness_code: Callable[[], str | None] | None = None,
    route_state: Callable[[], str] | None = None,
    clock: Callable[[], float] | None = None,
    supervisor_runner: Callable[[SupervisorHandoff], None] | None = None,
    admission_bound_s: float = ADMISSION_BOUND_S,
    worker_state_root: Path | None = None,
    attempt_status: Callable[[Path, str], object] | None = None,
    cancel_attempt: Callable[[Path, str, float], str] | None = None,
) -> LaunchService:
    """``build_launch_service(client, *, config: ClientConfig) -> LaunchService``.

    ``config`` is the captured ``PlacementClientConfig`` of ``client``. Every keyword after
    it is an injection seam whose default is the landed function. A ``lifecycle`` that is
    not supplied is built for ``client`` with the same caps loader, readiness check, clock
    and route state."""
    if client not in CLIENTS:
        raise ValueError("launch_client_unknown")
    if not isinstance(config, sandbox_policy.PlacementClientConfig) or config.client != client:
        raise ValueError("launch_config_invalid")
    if not (isinstance(admission_bound_s, (int, float)) and 0 < admission_bound_s <= ADMISSION_BOUND_S):
        raise ValueError("launch_admission_bound_invalid")
    load_caps = load_caps if load_caps is not None else _landed_load_caps()
    readiness_code = readiness_code if readiness_code is not None else _landed_readiness_code()
    worker_root = Path(worker_state_root) if worker_state_root is not None else _landed_worker_state_root()
    cancel_worker = cancel_attempt if cancel_attempt is not None else _landed_cancel_attempt
    if lifecycle is None:
        lifecycle = PlacementLifecycle(client, caps_loader=load_caps, caps_readiness=readiness_code,
                                      clock=clock, route_state=route_state,
                                      launch_cancel=lambda claim, wait: cancel_worker(
                                          worker_root, str(claim["run_id"]), wait))
    elif lifecycle.client != client:
        raise ValueError("launch_lifecycle_client_mismatch")
    return LaunchService(
        client, config, lifecycle=lifecycle,
        capped_popen=capped_popen if capped_popen is not None else _landed_capped_popen(),
        load_caps=load_caps, readiness_code=readiness_code,
        route_state=route_state if route_state is not None else lifecycle.route_state,
        clock=clock if clock is not None else lifecycle.clock,
        supervisor_runner=supervisor_runner,
        admission_bound_s=float(admission_bound_s),
        worker_state_root=worker_root,
        attempt_status=attempt_status if attempt_status is not None else _landed_attempt_status,
        cancel_attempt=cancel_worker,
    )
