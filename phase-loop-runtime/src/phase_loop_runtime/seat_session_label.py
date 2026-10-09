"""A readable name for the Claude session a panel seat runs in.

Claude Code titles an unnamed session by asking a model to summarise its first message and
pushing that title to the app's session list. A panel seat's first message is the whole review
prompt, so the title is a summary of it: not the repo, not the seat, not the round, and
indistinguishable from its neighbours once a few boards have run. Measured on Claude Code 2.1.295
with throwaway sessions: an unnamed seat made two `generate_session_title` calls and derived its
title from message 1; a seat started with `--name` made none, so nothing overwrites the name.

The label is built by the runtime from facts it already holds, so it works in a client repo with
no cooperation from the driving agent: `<repo> · <mode> · [<topic> ·] <seat> · <UTC date time>`.
The seat part is the board's seat key without its leading harness segment (the label already
says it is a Claude seat), e.g. `claude-opus-5-5:high:correctness`, so two Claude seats that
differ only in their lens get different names. It comes from runtime metadata, never from the
review material.

The label is at most `MAX_LABEL` characters and always ends with the time. The mode and the
time are reserved; when the parts do not fit, the topic gives way first, then the repo, then the
seat part (from its front, so the lens, which is what tells seats apart, is the last thing to go).

The topic is deliberately NOT scraped from the review bundle or brief. The label is part of the
seat's command line, which any local user can read in the process list on a shared host, and an
advisory board's material can be sensitive (legal, HR, finance). A topic appears only when the
operator sets `PHASE_LOOP_SEAT_TOPIC`. Set `PHASE_LOOP_SEAT_SESSION_NAMES=0` to turn naming off.

Never raises: a label is a convenience and must not fail a review. A launch does still depend
on the CLI accepting `--name`: the argv already carries `--ax-screen-reader` ahead of it, and the
one measured CLI that lacks `--name` (2.1.174) also rejects `--ax-screen-reader`, so `--name` is
never the first flag an unsupported CLI fails on (2.1.295 accepts both).
"""

from __future__ import annotations

import datetime
import os
import re
from collections.abc import Mapping
from pathlib import Path

ENV_SWITCH = "PHASE_LOOP_SEAT_SESSION_NAMES"
ENV_TOPIC = "PHASE_LOOP_SEAT_TOPIC"
#: The separator between parts. A part never contains it, so the parts stay distinguishable.
SEPARATOR = " · "
MAX_LABEL = 80
_MAX_TOPIC = 40
_MAX_PART = 40
_MAX_MODE = 12
_MAX_SEAT = 120      # generous before the budget; the budget is what trims it
_FALSE = frozenset({"0", "false", "no", "off"})
_SPACES = re.compile(r"\s+")


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """On unless the operator turned it off."""
    env = os.environ if environ is None else environ
    return str(env.get(ENV_SWITCH, "")).strip().lower() not in _FALSE


def sanitize(text: object, limit: int = _MAX_PART) -> str:
    """Printable text only, one line, bounded, never starting with a flag-like character.

    Control characters (including ESC, so no terminal escape reaches a title), the separator and
    anything non-printable are removed; the result starts with a letter or digit so it can never
    be read as an option when it is passed to a CLI."""
    try:
        cleaned = "".join(ch if ch.isprintable() else " " for ch in str(text))
    except Exception:  # noqa: BLE001 - a label never raises
        return ""
    cleaned = _SPACES.sub(" ", cleaned.replace(SEPARATOR.strip(), " ")).strip()
    cleaned = re.sub(r"^[^0-9A-Za-z]+", "", cleaned)
    return cleaned[:limit].rstrip()


def _seat_part(seat: str | None) -> str:
    """The seat key without its leading harness segment (`claude:claude-opus-5-5:high:x` ->
    `claude-opus-5-5:high:x`). A key with nothing after the first colon, or none, is kept."""
    head, separator, rest = str(seat or "").partition(":")
    chosen = rest if separator and sanitize(rest, _MAX_SEAT) else head
    return sanitize(chosen, _MAX_SEAT)


def _shrink(text: str, over: int, *, keep_tail: bool = False) -> str:
    """``text`` made ``over`` characters shorter (to nothing at most), from the end, or from the
    front when ``keep_tail`` is set; sanitised again so it still starts with a letter or digit."""
    room = len(text) - over
    if room <= 0:
        return ""
    return sanitize(text[-room:] if keep_tail else text[:room], room)


def _fit(repo: str, mode: str, topic: str, seat: str, stamp: str) -> str:
    """The parts joined within ``MAX_LABEL``: the mode and the stamp are reserved, and the topic,
    then the repo, then the seat part give way, in that order."""
    def join() -> str:
        return SEPARATOR.join(part for part in (repo, mode, topic, seat, stamp) if part)

    over = len(join()) - MAX_LABEL
    if over > 0 and topic:
        topic = _shrink(topic, over)
        over = len(join()) - MAX_LABEL
    if over > 0 and repo:
        repo = _shrink(repo, over)
        over = len(join()) - MAX_LABEL
    if over > 0 and seat:
        seat = _shrink(seat, over, keep_tail=True)
    # No further cap is needed or kept: with the topic, repo and seat gone, what is left is the
    # mode (at most `_MAX_MODE`) and the stamp, which together are far under `MAX_LABEL`.
    return join()


def build_label(
    *,
    repo: str | os.PathLike[str] | None,
    mode: str,
    seat: str | None,
    environ: Mapping[str, str] | None = None,
    now: datetime.datetime | None = None,
) -> str | None:
    """The session name for a seat, or ``None`` when naming is off or nothing usable remains."""
    try:
        env = os.environ if environ is None else environ
        if not enabled(env):
            return None
        repo_name = sanitize(Path(os.fspath(repo)).name) if repo is not None else ""
        topic = sanitize(env.get(ENV_TOPIC, ""), _MAX_TOPIC)
        stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%m-%d %H:%MZ")
        label = _fit(repo_name, sanitize(mode, _MAX_MODE), topic, _seat_part(seat), stamp)
        return label if label[:1].isalnum() else None
    except Exception:  # noqa: BLE001 - a label never raises
        return None
