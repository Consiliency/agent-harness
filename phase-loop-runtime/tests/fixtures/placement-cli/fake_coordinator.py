"""A fake OpenShell coordinator for placement black-box process tests (v13 PLACECLI SL-2).

It is a generic backend: every behaviour comes from knobs in a behaviour file (``admit``,
``kill``), never from a case identifier, and what it holds persists in a state file so that
one CLI process can reserve and another release or reap. It exposes the ForwardTcp
stream's local end as the ``upstream`` path the behaviour file names.
"""

from __future__ import annotations

import json
from pathlib import Path

from phase_loop_runtime import sandbox_placement as sp

#: Coordinator error codes this fake passes on as the far end's own refusal.
COORDINATOR_CODES = {
    "duplicate_binding": "the binding is already used by another lease",
    "snapshot_expired": "the snapshot expired; send a new one",
    "deadline_exceeded": "the coordinator's deadline passed",
}


class FakeCoordinator:
    name = "openshell-fake"

    def __init__(self, behaviour_path: Path) -> None:
        self.behaviour = json.loads(Path(behaviour_path).read_text())
        self.state_path = Path(self.behaviour["state"])

    # -- persistent state ---------------------------------------------------------------
    def _load(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"held": {}, "calls": []}

    def _save(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, sort_keys=True))

    def _note(self, call: str) -> dict:
        state = self._load()
        state["calls"].append(call)
        self._save(state)
        return state

    def _hold(self, lease_id: str, owner: str) -> None:
        state = self._load()
        state["held"][lease_id] = owner
        self._save(state)

    # -- the backend protocol -------------------------------------------------------------
    def capabilities(self):
        return frozenset()

    def declaration(self):
        return sp.Declaration()

    def available(self, request):
        return True

    def endpoint(self, root):
        return None

    def admit(self, request, bound):
        self._note("admit")
        mode = self.behaviour.get("admit", "ok")
        if mode == "ok":
            self._hold(request.lease_id, request.owner_id)
        elif mode == "at_capacity":
            raise sp.PlacementUnavailable("sandbox_placement_at_capacity")
        elif mode == "unavailable":
            raise sp.PlacementUnavailable("sandbox_placement_unreachable", "recovering", uncertain=False)
        elif mode == "lost_reply":
            self._hold(request.lease_id, request.owner_id)
            raise sp.PlacementUnavailable("sandbox_placement_operation_timeout", uncertain=True)
        elif mode == "deadline":
            raise sp.PlacementUnavailable("deadline_exceeded")
        else:
            raise sp.PlacementUnavailable(mode)

    def kill(self, lease_id, bound):
        self._note("kill")
        if self.behaviour.get("kill", "ok") != "ok":
            raise OSError("kill not acknowledged")
        state = self._load()
        state["held"].pop(lease_id, None)
        self._save(state)

    def list_owned(self, owner_id, bound):
        state = self._note("list_owned")
        return [(f"sbx-{lease[:8]}", lease) for lease, owner in state["held"].items()
                if owner == owner_id]

    def forward_exposure(self, lease_id, bound):
        self._note("forward_exposure")
        return {"service_name": "pi-link", "upstream": self.behaviour["upstream"]}

    def commit(self, *args):
        self._note("commit")
        raise sp.PlacementUnavailable("sandbox_placement_refused")

    def execute(self, *args):
        self._note("execute")
        raise sp.PlacementUnavailable("sandbox_placement_refused")

    def wait(self, *args):
        self._note("wait")
        raise sp.PlacementUnavailable("sandbox_placement_lost_after_launch")

    def cancel(self, *args):
        self._note("cancel")

    def renew(self, *args):
        self._note("renew")

    def release(self, *args):
        self._note("release")


def register(behaviour_path: Path) -> FakeCoordinator:
    backend = FakeCoordinator(behaviour_path)
    sp.register_backend("openshell", backend, COORDINATOR_CODES)
    return backend

