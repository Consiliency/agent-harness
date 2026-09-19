"""The prefix must survive the thread the brokered provider actually launches on.

Board round 5 of `agent-harness#890`: every brokered seat -- codex, gemini, grok, and
claude outside Claude Code -- launched OUTSIDE the network namespace while its evidence
recorded ``network_filtered: true``. The wiring expression was present at all three
`_popen` seams and correct. The activation was severed by a thread boundary:
``backing.py`` starts the broker's ``serve`` thread, ``serve`` calls ``adapter.invoke()``,
and a plain ``threading.Thread`` begins with a FRESH context, so ``_EGRESS_LAUNCH_PREFIX``
read back as ``()`` there. ``applied=bool(egress_prefix)`` was computed on the parent
thread, where it was populated.

**Why the round's own instrument could not see it.** 79 sandbox/egress/broker tests passed
with the defect fully present. The two "reach" assertions were a source-text grep for
``_EGRESS_LAUNCH_PREFIX.get()`` and a ContextVar set-and-read in the SAME thread. Neither
crosses the boundary production crosses. An AST walk proves a spawn *mentions* the prefix;
only running it proves the prefix *arrives*.

So these tests assert behaviour at the boundary, and the last one pins the mechanism in
the real module rather than in a replica of it.
"""

from __future__ import annotations

import threading

from phase_loop_runtime.panel_invoker import _EGRESS_LAUNCH_PREFIX


PREFIX = (
    "nsenter", "--net", "-t", "12345", "-U", "--preserve-credentials",
    "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--",
)


def _argv_seen_on(thread_factory) -> list[str]:
    """Build the launch argv the way a seam does, on whatever thread is handed to us."""
    seen: dict[str, list[str]] = {}

    def serve() -> None:                       # backing.py: the broker's serve thread
        seen["argv"] = [*_EGRESS_LAUNCH_PREFIX.get(), "codex", "exec"]

    thread = thread_factory(serve)
    thread.start()
    thread.join(timeout=10)
    return seen["argv"]


def test_a_plain_thread_LOSES_the_prefix(monkeypatch):
    """The falsifier. If this ever passes, the test below proves nothing."""
    token = _EGRESS_LAUNCH_PREFIX.set(PREFIX)
    try:
        argv = _argv_seen_on(lambda fn: threading.Thread(target=fn))
        assert argv == ["codex", "exec"], (
            "a plain thread inheriting the prefix would make this whole file vacuous"
        )
    finally:
        _EGRESS_LAUNCH_PREFIX.reset(token)


def test_a_context_carrying_thread_KEEPS_the_prefix():
    from contextvars import copy_context

    token = _EGRESS_LAUNCH_PREFIX.set(PREFIX)
    try:
        argv = _argv_seen_on(
            lambda fn: threading.Thread(target=copy_context().run, args=(fn,))
        )
        assert argv[:2] == ["nsenter", "--net"], (
            f"the provider launched unprefixed on the serve thread: {argv[:3]}"
        )
        assert argv[-2:] == ["codex", "exec"]
    finally:
        _EGRESS_LAUNCH_PREFIX.reset(token)


def test_the_REAL_broker_starts_its_serve_thread_under_a_copied_context():
    """Pin the mechanism where production uses it, not in a replica.

    Executing `run_credentialless_client` end to end needs bwrap, a broker socket and a
    real provider, so this drives the one thing a replica cannot establish: that the
    module actually building that thread carries the context. It is deliberately paired
    with the behavioural tests above -- neither alone is sufficient, and the behavioural
    pair alone was what let round 5 ship.
    """
    import inspect
    from phase_loop_runtime.advisor_board import backing

    source = inspect.getsource(backing.ParentUnixBroker.run_credentialless_client)
    assert "threading.Thread(" in source, "the serve thread moved; re-target this test"
    started = [
        line for line in source.splitlines()
        if "threading.Thread(" in line and "start()" in line
    ]
    assert started, "could not locate the serve-thread construction"
    assert all("copy_context()" in line for line in started), (
        "the broker's serve thread starts with a FRESH context, so every ContextVar the "
        "parent set -- including the egress launch prefix -- reads back as its default "
        f"on the thread that launches the provider: {started}"
    )


def test_the_prefix_is_not_silently_global():
    """A module-level tuple would make the tests above pass for the wrong reason."""
    assert _EGRESS_LAUNCH_PREFIX.get() == (), (
        "the prefix leaked out of a previous test's context"
    )
