"""agent-harness#2092 follow-up: the structural private-ACL check and the Windows
changed-paths guard.

The ACL policy is checked on constructed binary DACLs on every platform, and on real
descriptors built by the Windows security APIs on native Windows.
"""
from __future__ import annotations

import ctypes
import os

import pytest

from phase_loop_runtime import launcher
from phase_loop_runtime.windows_storage import _private_dacl_problem

PRESENT, PROTECTED, AUTO_INHERITED, SELF_RELATIVE = 0x0004, 0x1000, 0x0400, 0x8000
CONTROL = PRESENT | PROTECTED
FILE_ALL_ACCESS = 0x001F01FF


def sid(*subs, authority=5):
    return (bytes((1, len(subs))) + authority.to_bytes(6, "big")
            + b"".join(value.to_bytes(4, "little") for value in subs))


SYSTEM = sid(18)
USER = sid(21, 111, 222, 333, 1001)
OTHER_USER = sid(21, 111, 222, 333, 1002)
EVERYONE = sid(0, authority=1)


def ace(trustee, *, kind=0, flags=0, mask=FILE_ALL_ACCESS):
    body = mask.to_bytes(4, "little") + trustee
    return bytes((kind, flags)) + (4 + len(body)).to_bytes(2, "little") + body


def acl(*entries, count=None):
    body = b"".join(entries)
    count = len(entries) if count is None else count
    return (bytes((2, 0)) + (8 + len(body)).to_bytes(2, "little")
            + count.to_bytes(2, "little") + b"\0\0" + body)


PRIVATE = acl(ace(SYSTEM), ace(USER))


@pytest.mark.parametrize("control, dacl", [
    pytest.param(CONTROL, PRIVATE, id="protected"),
    pytest.param(CONTROL | AUTO_INHERITED | SELF_RELATIVE, PRIVATE, id="auto_inherited_PAI"),
    pytest.param(CONTROL, acl(ace(USER), ace(SYSTEM)), id="user_first"),
])
def test_private_dacl_is_accepted(control, dacl):
    assert _private_dacl_problem(control, dacl, USER) is None


@pytest.mark.parametrize("control, dacl, user", [
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER), ace(EVERYONE, mask=0x120089)), USER, id="extra_ace"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER, flags=0x10)), USER, id="inherited_ace"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER), ace(EVERYONE, kind=1)), USER, id="extra_deny_ace"),
    pytest.param(CONTROL, acl(ace(USER, kind=1), ace(USER)), USER, id="deny_in_place_of_system"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER, flags=0x03)), USER, id="inheritable_ace"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER, flags=0x0B)), USER, id="inherit_only_ace"),
    pytest.param(PRESENT, PRIVATE, USER, id="dacl_not_protected"),
    pytest.param(PRESENT | AUTO_INHERITED, PRIVATE, USER, id="dacl_auto_inherited_not_protected"),
    pytest.param(PROTECTED, PRIVATE, USER, id="dacl_absent"),
    pytest.param(CONTROL, None, USER, id="null_dacl"),
    pytest.param(CONTROL, acl(ace(SYSTEM)), USER, id="system_only"),
    pytest.param(CONTROL, acl(), USER, id="empty_dacl"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER, mask=0x1200A9)), USER, id="reduced_mask"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER, mask=0x10000000)), USER, id="generic_all_mask"),
    pytest.param(CONTROL, PRIVATE, OTHER_USER, id="other_user"),
    pytest.param(CONTROL, acl(ace(USER), ace(USER)), USER, id="user_twice"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(EVERYONE)), USER, id="everyone_in_place_of_user"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(USER), count=3), USER, id="count_beyond_acl"),
    pytest.param(CONTROL, PRIVATE[:-4], USER, id="truncated"),
    pytest.param(CONTROL, acl(ace(SYSTEM), ace(bytes((1, 6)) + USER[2:])), USER, id="sid_length_mismatch"),
])
def test_anything_else_is_refused_without_naming_a_sid(control, dacl, user):
    problem = _private_dacl_problem(control, dacl, user)
    assert problem is not None
    assert "S-1-" not in problem


def test_malformed_ace_size_is_refused():
    broken = bytearray(PRIVATE)
    broken[8 + 2:8 + 4] = (len(ace(SYSTEM)) - 4).to_bytes(2, "little")
    assert _private_dacl_problem(CONTROL, bytes(broken), USER) == "malformed ACL"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows security descriptors")
@pytest.mark.parametrize("template, accepted", [
    ("D:P(A;;FA;;;SY)(A;;FA;;;{sid})", True),
    ("D:PAI(A;;FA;;;SY)(A;;FA;;;{sid})", True),
    ("D:P(A;;FA;;;SY)(A;;FA;;;{sid})(A;;FR;;;WD)", False),
    ("D:P(A;;FA;;;SY)(A;ID;FA;;;{sid})", False),
    ("D:P(D;;FA;;;WD)(A;;FA;;;SY)(A;;FA;;;{sid})", False),
    ("D:(A;;FA;;;SY)(A;;FA;;;{sid})", False),
])
def test_real_descriptors_through_the_production_reader(template, accepted):
    from ctypes import wintypes
    from phase_loop_runtime.windows_storage import PrivateSecurity, _descriptor_dacl_problem

    security = PrivateSecurity()
    get_dacl = security.security.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    get_dacl.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    try:
        assert security.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            template.format(sid=security.sid), 1, ctypes.byref(descriptor), None)
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        assert get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
        problem = _descriptor_dacl_problem(security.security, descriptor, dacl, security.sid_bytes)
        assert (problem is None) is accepted, problem
    finally:
        if descriptor:
            security.kernel.LocalFree(descriptor)
        security.close()


def test_native_windows_change_snapshot_never_reaches_host_git(tmp_path, monkeypatch):
    import phase_loop_runtime.review_stage as review_stage

    def refuse(*args, **kwargs):
        raise AssertionError("host_git reached on native Windows")

    monkeypatch.setattr(review_stage, "host_git", refuse)
    monkeypatch.setattr(launcher, "_native_windows", lambda: True)
    assert launcher._worktree_change_snapshot(tmp_path) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX path is unchanged")
def test_posix_change_snapshot_still_consults_host_git(tmp_path, monkeypatch):
    import phase_loop_runtime.review_stage as review_stage

    calls = []

    def record(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("stop after the first call")

    monkeypatch.setattr(review_stage, "host_git", record)
    with pytest.raises(RuntimeError, match="stop after"):
        launcher._worktree_change_snapshot(tmp_path)
    assert calls and calls[0][0] == tmp_path
