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


def test_the_REAL_production_helper_carries_the_context():
    """Execute the actual function production uses. Not a replica, not its source text.

    The previous version of this test asserted that the literal ``copy_context()``
    appeared on the line building the thread. Board round 6 defeated it in one line while
    fully restoring the defect::

        threading.Thread(target=(lambda _ctx=copy_context(): serve()), daemon=False)

    Four of four tests passed; the serve thread's prefix was ``()``. That is the second
    time on this branch a source-text check certified a mechanism that did not work, so
    the mechanism is now a callable and this RUNS it.
    """
    from phase_loop_runtime.advisor_board.backing import start_context_carrying_thread

    seen: dict[str, tuple[str, ...]] = {}
    token = _EGRESS_LAUNCH_PREFIX.set(PREFIX)
    try:
        thread = start_context_carrying_thread(
            lambda: seen.__setitem__("prefix", _EGRESS_LAUNCH_PREFIX.get()), daemon=True,
        )
        thread.join(timeout=10)
    finally:
        _EGRESS_LAUNCH_PREFIX.reset(token)

    assert seen.get("prefix") == PREFIX, (
        "the production helper does NOT carry the caller's context; every brokered seat "
        f"would launch unprefixed: {seen.get('prefix')!r}"
    )


def test_nothing_in_the_broker_bypasses_that_helper():
    """The helper being correct is worthless if the launch path stops calling it.

    This is the one assertion here that must read source, so it is framed as a NEGATIVE:
    no raw thread construction anywhere in the module except inside the helper itself.
    A bypass has to be written in, visibly, rather than merely slipping past a grep.
    """
    import inspect
    from phase_loop_runtime.advisor_board import backing

    module_source = inspect.getsource(backing)
    helper_source = inspect.getsource(backing.start_context_carrying_thread)
    outside = module_source.replace(helper_source, "")

    assert "threading.Thread(" not in outside, (
        "a raw threading.Thread is constructed outside start_context_carrying_thread; "
        "anything it runs begins with a FRESH context and loses the egress prefix"
    )
    assert "start_context_carrying_thread(" in inspect.getsource(
        backing.ParentUnixBroker.run_credentialless_client
    ), "the brokered launch no longer routes through the context-carrying helper"


def test_the_prefix_is_not_silently_global():
    """A module-level tuple would make the tests above pass for the wrong reason."""
    assert _EGRESS_LAUNCH_PREFIX.get() == (), (
        "the prefix leaked out of a previous test's context"
    )
