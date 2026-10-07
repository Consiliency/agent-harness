"""The agy login's expiry is read the same on every supported Python (agent-harness#1282).

agy writes ``token.expiry`` with nanosecond fractions (``...:18.406993494+00:00``). Python
3.10's ``datetime.fromisoformat`` refuses more than six fractional digits, so on 3.10 every
agy login read as near expiry: the owned Gemini seat refreshed it, still could not read it,
and refused with ``gemini_credential_near_expiry``. The agy qualification run then never saw
its provider start."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from phase_loop_runtime import panel_invoker as pi


def _home(tmp_path, expiry: str):
    token = tmp_path / ".gemini/antigravity-cli/antigravity-oauth-token"
    token.parent.mkdir(parents=True)
    token.write_text(json.dumps({"auth_method": "oauth", "token": {
        "access_token": "synthetic", "token_type": "Bearer", "expiry": expiry}}))
    token.chmod(0o600)
    return tmp_path


def _iso(delta: timedelta, fraction: str, zone: str) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%S") + fraction + zone


@pytest.mark.parametrize("fraction", ["", ".4", ".406993", ".406993494"])
@pytest.mark.parametrize("zone", ["+00:00", "Z"])
def test_a_fresh_agy_login_reads_fresh_whatever_its_precision(tmp_path, fraction, zone):
    assert pi._gemini_credential_fresh(_home(tmp_path, _iso(timedelta(hours=1), fraction, zone)))


@pytest.mark.parametrize("fraction", [".406993494", ""])
def test_a_login_close_to_expiry_still_reads_near_expiry(tmp_path, fraction):
    assert not pi._gemini_credential_fresh(
        _home(tmp_path, _iso(timedelta(seconds=60), fraction, "+00:00")))


def test_an_unreadable_expiry_is_never_fresh(tmp_path):
    assert not pi._gemini_credential_fresh(_home(tmp_path, "not a time"))
