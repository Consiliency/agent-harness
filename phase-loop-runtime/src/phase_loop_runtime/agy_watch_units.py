"""Install and check the upstream watch's hourly user timer (AGYROLL ROLLJOB, SL-1).

``phase-loop agy-qualification watch --install-units`` copies the two unit files from the
checkout's ``docs/ops/agy-upstream-watch/`` into the user's systemd directory and enables the
timer; ``--check`` reports, as one JSON line, whether the timer is installed, enabled and
current, and whether the last tick passed. Neither creates a key, a login or a credential.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from . import agy_catalog_policy as policy

UNIT_DIR = Path("docs/ops/agy-upstream-watch")
SERVICE = "agy-upstream-watch.service"
TIMER = "agy-upstream-watch.timer"
UNITS = (SERVICE, TIMER)
#: A last tick older than this makes ``--check`` report ``stale`` (the timer is hourly).
CHECK_FRESH_S = 3 * 3_600
_SYSTEMCTL_TIMEOUT_S = 60


def user_unit_dir(environ=None) -> Path:
    """``$XDG_CONFIG_HOME/systemd/user``, else ``~/.config/systemd/user``."""
    environ = os.environ if environ is None else environ
    base = environ.get("XDG_CONFIG_HOME") or str(Path(environ.get("HOME") or Path.home()) / ".config")
    return Path(base) / "systemd" / "user"


def _checkout_units(repo: Path) -> dict[str, bytes]:
    return {name: (repo / UNIT_DIR / name).read_bytes() for name in UNITS}


def _systemctl(runner, *args):
    return runner(["systemctl", "--user", *args], capture_output=True, text=True, check=False,
                  timeout=_SYSTEMCTL_TIMEOUT_S)


def install_units(repo, *, runner=subprocess.run, environ=None, dry_run=False, out=print) -> int:
    """Copy both units (0644), reload the user manager and enable the timer now. Idempotent:
    a unit that already has the checkout's bytes is not rewritten. ``dry_run`` prints the
    actions and changes nothing."""
    repo = Path(repo or ".").resolve()
    try:
        units = _checkout_units(repo)
    except OSError:
        out(json.dumps({"agy_watch_install": "units_not_in_checkout", "repo": str(repo)}))
        return 2
    target = user_unit_dir(environ)
    changed = []
    for name, data in units.items():
        path = target / name
        try:
            current = path.read_bytes()
        except OSError:
            current = None
        if current != data:
            changed.append(name)
    actions = [f"copy {name} -> {target / name}" for name in changed]
    actions += ["systemctl --user daemon-reload", f"systemctl --user enable --now {TIMER}"]
    if dry_run:
        out(json.dumps({"agy_watch_install": "dry_run", "actions": actions}))
        return 0
    target.mkdir(parents=True, exist_ok=True)
    for name in changed:
        temporary = target / f".{name}.tmp"
        temporary.write_bytes(units[name])
        os.chmod(temporary, 0o644)
        os.replace(temporary, target / name)
    for args in (("daemon-reload",), ("enable", "--now", TIMER)):
        done = _systemctl(runner, *args)
        if done.returncode != 0:
            out(json.dumps({"agy_watch_install": "systemctl_failed", "step": " ".join(args)}))
            return 2
    out(json.dumps({"agy_watch_install": "installed", "changed": changed}))
    return 0


def check_state(repo, *, runner=subprocess.run, environ=None, now=None) -> tuple[str, str | None]:
    """``(state, last tick status or None)``; the first state that applies:

    1. ``absent``: either unit file is not installed;
    2. ``failed: <status>``: the last tick exited non-zero;
    3. ``stale``: an installed unit differs from the checkout's, the timer is not enabled,
       or no valid last-tick status is newer than ``CHECK_FRESH_S`` (a missing or malformed
       status file is ``stale``, never ``installed``);
    4. ``installed``."""
    repo = Path(repo or ".").resolve()
    target = user_unit_dir(environ)
    installed = {}
    for name in UNITS:
        try:
            installed[name] = (target / name).read_bytes()
        except OSError:
            last = policy.read_tick_status(environ)
            return "absent", (last or {}).get("status")
    last = policy.read_tick_status(environ)
    status = last["status"] if last else None
    if last is not None and last["exit"] != 0:
        return f"failed: {status}", status
    try:
        current = _checkout_units(repo) == installed
    except OSError:
        current = False
    enabled = _systemctl(runner, "is-enabled", TIMER)
    at = policy.parse_instant(last["at"]) if last else None
    now = time.time() if now is None else now
    if (not current or enabled.returncode != 0 or (enabled.stdout or "").strip() != "enabled"
            or at is None or now - at > CHECK_FRESH_S):
        return "stale", status
    return "installed", status


def main(args, *, runner=subprocess.run, environ=None, out=print, now=None) -> int:
    """``agy-qualification watch --install-units`` or ``--check`` (mutually exclusive)."""
    if getattr(args, "action", "watch") != "watch":
        out(json.dumps({"agy_watch": "units_flags_need_watch"}))
        return 2
    if getattr(args, "install_units", False):
        dry_run = bool(getattr(args, "watch_dry_run", False) or getattr(args, "dry_run", False))
        return install_units(getattr(args, "repo", None), runner=runner, environ=environ, dry_run=dry_run, out=out)
    state, last = check_state(getattr(args, "repo", None), runner=runner, environ=environ, now=now)
    out(json.dumps({"agy_watch_check": state, "last_tick": last}))
    return 0 if state == "installed" else 1
