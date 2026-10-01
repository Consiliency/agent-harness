"""Unified seat-launch owner: namespace, identity and capability composition."""

import os
import sys

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat-owner contract")


HOLDER = (
    "nsenter", "--net", "--mount", "-t", "1", "-U", "--preserve-credentials",
    "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--",
)
OWNER = (
    "/usr/bin/bwrap", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
    "--unshare-cgroup-try", "--new-session", "--die-with-parent",
    "--proc", "/proc", "--tmpfs", "/tmp", "--remount-ro", "/",
)


@pytest.mark.parametrize("retain_caps", [(), ("setfcap",)])
def test_mapping_capability_preserves_the_same_namespace_owner(retain_caps, tmp_path):
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(HOLDER)
    try:
        prefix = panel_invoker._compose_launch_prefix(tmp_path, OWNER, retain_caps)
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)

    assert prefix.count("/usr/bin/bwrap") == 1
    for option in (
        "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--unshare-cgroup-try", "--new-session", "--die-with-parent",
    ):
        assert option in prefix
    assert prefix[prefix.index("--uid") + 1] == str(os.getuid())
    assert prefix[prefix.index("--gid") + 1] == str(os.getgid())
    assert prefix[prefix.index("--cap-drop") + 1] == "ALL"
    assert "--unshare-net" not in prefix
    assert "--fork" not in prefix
    assert "--mount-proc" not in prefix


@pytest.mark.parametrize("retain_caps", [(), ("setfcap",)])
def test_owned_provider_identity_has_no_retained_mapping_capability(retain_caps, tmp_path):
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(HOLDER)
    try:
        prefix = panel_invoker._compose_launch_prefix(tmp_path, OWNER, retain_caps)
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)

    facts = panel_invoker._expected_seat_identity(prefix, retain_caps)
    assert "CapPrm:\t0000000000000000" in facts
    assert "CapEff:\t0000000000000000" in facts
    assert "CapBnd:\t0000000000000000" in facts
    assert "NoNewPrivs:\t1" in facts


def test_real_root_operator_is_refused_before_owner_composition(monkeypatch, tmp_path):
    monkeypatch.setattr(panel_invoker.os, "getuid", lambda: 0)
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(HOLDER)
    try:
        with pytest.raises(sandbox_egress.SeatIdentityUnverified):
            panel_invoker._compose_launch_prefix(tmp_path, OWNER)
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)


def test_unapproved_mapping_capability_is_refused(tmp_path):
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(HOLDER)
    try:
        with pytest.raises(ValueError):
            panel_invoker._compose_launch_prefix(tmp_path, OWNER, ("net_admin",))
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
