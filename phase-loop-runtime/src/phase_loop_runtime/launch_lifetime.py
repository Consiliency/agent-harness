"""Monotonic deadlines and local lease renewal for one elected generation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .sandbox_placement import ANSWER_BOUND_S, PlacementLifecycle


@dataclass
class LaunchLifetime:
    generation: str
    ttl_s: int
    last_confirmed: float
    timeout_s: int
    return_allowance: int
    clock: Callable[[], float] = time.monotonic
    confirmation_clock: Callable[[], float | None] | None = None
    confirmed_count: int = 0
    first_start: float | None = None
    execution_deadline: float | None = None
    return_deadline: float | None = None
    release_deadline: float | None = None
    fenced: threading.Event = field(default_factory=threading.Event)

    def started(self):
        if self.first_start is None:
            self.first_start = self.clock()
            self.execution_deadline = self.first_start + self.timeout_s

    def terminated(self):
        if self.return_deadline is None:
            self.return_deadline = self.clock() + self.return_allowance
            self.release_deadline = self.return_deadline + ANSWER_BOUND_S

    def renew(
        self,
        lifecycle: PlacementLifecycle,
        reservation_id: str,
        request_id: str,
        stop: threading.Event,
        on_loss: Callable[[], None],
    ):
        ids = reservation_id, request_id, self.generation
        third = self.ttl_s / 3
        while not stop.is_set() and not self.fenced.is_set():
            cutoff = self.last_confirmed + 2 * third
            if stop.wait(max(0, self.last_confirmed + third - self.clock())):
                break
            while not stop.is_set() and not self.fenced.is_set():
                now = self.clock()
                if now >= cutoff:
                    self.fenced.set()
                    on_loss()
                    lifecycle.fence_launch(
                        *ids, cause="renewal_lost", deadline=self.last_confirmed + self.ttl_s
                    )
                    return
                try:
                    ok = lifecycle.renew_launch(*ids, deadline=min(now + third, cutoff)) is True
                except Exception:
                    ok = False
                confirmed_at = self.clock()
                if ok and confirmed_at < cutoff:
                    selected = self.confirmation_clock() if self.confirmation_clock else confirmed_at
                    if selected is not None and self.last_confirmed < selected <= confirmed_at:
                        self.last_confirmed = selected
                        self.confirmed_count += 1
                        break
                # Bound observations of an immediately rejected call, without
                # sleeping past the original last-confirmation boundary.
                stop.wait(min(0.1, max(0, cutoff - confirmed_at)))


def budget_permits(*, ttl_s, maximum, snapshot_s, timeout_s, return_s, template_timeout):
    return (
        type(ttl_s) is int
        and ttl_s >= 45
        and 0 < timeout_s <= template_timeout
        and (maximum is None or snapshot_s + timeout_s + return_s + ANSWER_BOUND_S <= maximum)
    )
