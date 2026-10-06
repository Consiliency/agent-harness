"""Skip guards for the seat-jail tests (agent-harness#1132).

One literal per missing prerequisite, so every gated test says the same thing and a skip
can never be mistaken for a pass. The D8 host prerequisite is run once per host by the
maintainer, as root; these tests never run it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache

import pytest

SEAT_UID_PREREQUISITE = (
    "D8 host prerequisite missing: newuidmap/newgidmap absent or no /etc/subuid and "
    "/etc/subgid range for the operator; maintainer prerequisite (root, once per host): "
    "apt install uidmap + usermod --add-subuids/--add-subgids <operator>"
)
SEAT_TOKEN_PREREQUISITE = (
    "no Claude seat credential: run `claude auth login`, or store a `claude setup-token` token "
    "owner-only at $XDG_STATE_HOME/phase-loop/seat-credentials/claude"
)
USERNS_UNAVAILABLE = "unprivileged bwrap user namespaces unavailable on this host"


@lru_cache(maxsize=1)
def unprivileged_bwrap_ok() -> bool:
    if not os.access("/usr/bin/bwrap", os.X_OK):
        return False
    try:
        done = subprocess.run(
            ["/usr/bin/bwrap", "--unshare-user", "--ro-bind", "/", "/", "true"],
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def seat_uid_ready() -> bool:
    from phase_loop_runtime import seat_uid

    return seat_uid.seat_uid_available()


requires_userns = pytest.mark.skipif(not unprivileged_bwrap_ok(), reason=USERNS_UNAVAILABLE)


def require_seat_uid() -> None:
    if not seat_uid_ready():
        pytest.skip(SEAT_UID_PREREQUISITE)


def require_seat_token() -> None:
    """A Claude seat credential: a stored override that applies to this session (plan
    amendment A4), or the user's Claude login (plan amendment A1)."""
    from phase_loop_runtime import seat_credentials

    if seat_credentials.override_decision().applies:
        return
    if seat_credentials.read_login_token() is None:
        pytest.skip(SEAT_TOKEN_PREREQUISITE)


def have(tool: str) -> bool:
    return shutil.which(tool) is not None
