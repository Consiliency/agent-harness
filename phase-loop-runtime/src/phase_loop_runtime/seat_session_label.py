"""A readable name for the Claude session a panel seat runs in.

Claude Code titles an unnamed session by asking a model to summarise its first message and
pushing that title to the app's session list. A panel seat's first message is the whole review
prompt, so the title is a summary of it: not the repo, not the seat, not the round, and
indistinguishable from its neighbours once a few boards have run. Measured on Claude Code 2.1.295
with throwaway sessions: an unnamed seat made two `generate_session_title` calls and derived its
title from message 1; a seat started with `--name` made none, so nothing overwrites the name.

The label is built by the runtime from facts it already holds, so it works in a client repo with
no cooperation from the driving agent: `<repo> · <mode> · [<topic> ·] <seat> · <UTC date time>`.

The topic is deliberately NOT scraped from the review bundle or brief. The label is part of the
seat's command line, which any local user can read in the process list on a shared host, and an
advisory board's material can be sensitive (legal, HR, finance). A topic appears only when the
operator sets `PHASE_LOOP_SEAT_TOPIC`. Set `PHASE_LOOP_SEAT_SESSION_NAMES=0` to turn naming off.

Never raises: a label is a convenience and must not fail a review.
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
        parts = [repo_name, sanitize(mode), topic, sanitize(seat or ""), stamp]
        label = SEPARATOR.join(part for part in parts if part)
        if len(label) > MAX_LABEL and topic:
            # The topic is the only elastic part: shrink it before anything else is cut.
            room = max(0, _MAX_TOPIC - (len(label) - MAX_LABEL))
            parts[2] = sanitize(topic, room) if room else ""
            label = SEPARATOR.join(part for part in parts if part)
        label = label[:MAX_LABEL].rstrip()
        return label if sanitize(label, MAX_LABEL) and label[:1].isalnum() else None
    except Exception:  # noqa: BLE001 - a label never raises
        return None
