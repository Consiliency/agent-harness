"""agent-harness#2078: the Codex seat profile copies the login the CLI resolves.

The board-composition probe (``codex login status``) runs in ``seat_profile`` under the
provider-admin role. Its private copy of ``auth.json`` must come from
``seat_codex_credential.auth_path(env)`` -- ``$CODEX_HOME`` first, else ``~/.codex`` --
the same login the seat's admission gate reads, not from ``$HOME/.codex`` alone.
"""

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from phase_loop_runtime import gemini_heartbeat, panel_invoker, seat_codex_credential
SeatLaunchRole = panel_invoker.SeatLaunchRole

pytestmark = [
    pytest.mark.skipif(sys.platform != "linux", reason="Linux seat profiles"),
    pytest.mark.usefixtures("live_seat_attempt"),
]


def _login(directory: Path, account_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "auth.json"
    path.write_text(json.dumps({"tokens": {
        "id_token": f"synthetic-id-{account_id}",
        "access_token": f"synthetic-access-{account_id}",
        "refresh_token": f"synthetic-refresh-{account_id}",
        "account_id": account_id,
    }}))
    path.chmod(0o600)


def _projected_auth(profile):
    args = profile.mount_args
    files = {args[index + 2]: os.pread(int(args[index + 1]), 1_000_000, 0)
             for index, item in enumerate(args) if item == "--file"}
    return [data for path, data in files.items() if path.endswith("/.codex/auth.json")]


@pytest.fixture
def homes(tmp_path, monkeypatch):
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES,
                        hashlib.sha256(Path("/usr/bin/true").read_bytes()).hexdigest(),
                        "synthetic-help")
    home = tmp_path / "operator"
    (home / ".codex").mkdir(parents=True)
    return home, tmp_path / "codex-home"


def _probe_profile(env, cwd):
    return panel_invoker.seat_profile(harness="codex", executable="/usr/bin/true", env=env,
                                      cwd=cwd, role=SeatLaunchRole.PROVIDER_ADMIN)


def _account(raw: bytes) -> str:
    return json.loads(raw)["tokens"]["account_id"]


@pytest.mark.parametrize("case", ["a_codex_home_unset", "b_codex_home_only", "c_both_differ"])
def test_codex_profile_copies_the_login_auth_path_resolves(homes, tmp_path, case):
    home, codex_home = homes
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    if case == "a_codex_home_unset":
        _login(home / ".codex", "acct-home")
    elif case == "b_codex_home_only":
        # ~/.codex is logged out; the login lives in $CODEX_HOME.
        _login(codex_home, "acct-codex-home")
        env["CODEX_HOME"] = str(codex_home)
    else:
        _login(home / ".codex", "acct-home")
        _login(codex_home, "acct-codex-home")
        env["CODEX_HOME"] = str(codex_home)
    expected = _account(seat_codex_credential.read_auth(env))
    assert seat_codex_credential.auth_path(env).parent == (
        home / ".codex" if case == "a_codex_home_unset" else codex_home)

    with _probe_profile(env, tmp_path) as (_, profile):
        copied = _projected_auth(profile)
        # Projected, not skipped as a missing source.
        assert len(copied) == 1, "the Codex login copy was skipped"
        assert _account(copied[0]) == expected
        tokens = json.loads(copied[0])["tokens"]
        assert tokens["refresh_token"] == ""  # the seat shape is unchanged
        assert profile.env["CODEX_HOME"] == profile.env["HOME"] + "/.codex"


def test_logged_out_everywhere_is_still_skipped_for_provider_admin(homes, tmp_path):
    home, codex_home = homes
    codex_home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CODEX_HOME": str(codex_home)}
    with _probe_profile(env, tmp_path) as (_, profile):
        assert _projected_auth(profile) == []


@pytest.mark.parametrize("codex_home_set", [False, True])
def test_missing_login_directory_is_still_skipped_for_provider_admin(homes, tmp_path,
                                                                     codex_home_set):
    # Neither ~/.codex nor $CODEX_HOME exists: the probe sees "not logged in", as before.
    home, codex_home = homes
    (home / ".codex").rmdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    if codex_home_set:
        env["CODEX_HOME"] = str(codex_home)
    with _probe_profile(env, tmp_path) as (_, profile):
        assert _projected_auth(profile) == []


def test_linked_codex_home_login_is_refused(homes, tmp_path):
    home, codex_home = homes
    _login(home / ".codex", "acct-home")
    codex_home.mkdir()
    (codex_home / "auth.json").symlink_to(home / ".codex/auth.json")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CODEX_HOME": str(codex_home)}
    with pytest.raises(Exception, match="seat_output|seat_profile"):
        with _probe_profile(env, tmp_path):
            pytest.fail("profile accepted a linked CODEX_HOME login")
