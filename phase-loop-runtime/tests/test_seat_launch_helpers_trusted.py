"""agent-harness#1132: the seat launch helpers run from the trusted installation.

The helpers that run before and around a jailed seat (the session-keyring step, the seat-uid
handoff and the in-namespace helpers) are this package's own modules. They resolve from the
installation the parent imported, whatever the launch's working directory holds, so they
behave the same from any directory, a reviewed repository included.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail, seat_uid

SRC = Path(pi.__file__).resolve().parent


def _package_named_like_ours(directory: Path, module: str, body: str) -> None:
    package = directory / "phase_loop_runtime"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / f"{module}.py").write_text(body)


@pytest.mark.parametrize("module", ["seat_keyring_exec", "seat_uid"])
def test_a_helper_resolves_from_the_trusted_installation_in_any_cwd(tmp_path, module):
    cwd = tmp_path / "cwd"
    marker = tmp_path / "ran-from-cwd"
    _package_named_like_ours(cwd, module, f"open({str(marker)!r}, 'w').write('x')\n")
    argv = seat_uid.trusted_module_argv(f"phase_loop_runtime.{module}", "--help")
    subprocess.run(argv, cwd=cwd, capture_output=True, timeout=60,
                   env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(cwd)})
    assert not marker.exists()


def test_the_trusted_argv_runs_the_installed_module_as_main(tmp_path):
    done = subprocess.run(
        seat_uid.trusted_module_argv("phase_loop_runtime.seat_keyring_exec", "--",
                                     "/bin/echo", "ran"),
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout == "ran\n"
    argv = seat_uid.trusted_module_argv("phase_loop_runtime.seat_uid", "teardown", "x")
    assert argv[:2] == [sys.executable, "-I"] and "-m" not in argv
    assert argv[argv.index("phase_loop_runtime.seat_uid") - 1] == str(SRC.parent)
    with pytest.raises(ValueError):
        seat_uid.trusted_module_argv("somewhere_else.module")


def test_the_pre_jail_helpers_ignore_a_package_in_the_launch_cwd(monkeypatch, tmp_path):
    from test_seat_sandbox_permissions import _fake_jail

    jail = _fake_jail(tmp_path / "jail")
    repository = tmp_path / "repository"
    marker = tmp_path / "ran-from-cwd"
    expected = "\n".join(seat_jail.expected_probe_lines(jail))
    for module in ("seat_keyring_exec", "seat_uid"):
        _package_named_like_ours(
            repository, module,
            f"open({str(marker)!r}, 'w').write('x')\nprint({expected!r})\n")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(seat_jail, "pass_record_verdict", lambda digest: (True, "pass"))
    token = pi._EGRESS_LAUNCH_PREFIX.set((
        "nsenter", "-t", "99999999", "-U", "--net", "--mount",
        "--preserve-credentials", "setpriv", "--bounding-set=-all",
    ))
    try:
        try:
            process = pi.launch_provider(
                [jail.provider_argv0], process_owner=jail, probe_owner=jail,
                cwd=seat_jail.SEAT_TREE, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            process.communicate(timeout=10)
        except seat_jail.SeatSandboxRefused:
            pass
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(token)
        seat_jail.close_jail_fds(jail)
    assert not marker.exists()


def test_the_in_namespace_helpers_ignore_a_package_in_the_launch_cwd(monkeypatch, tmp_path):
    argv = seat_uid.in_h_argv(4242, "teardown", "/x")
    python = argv[argv.index("--preserve-credentials") + 1:]
    assert python == seat_uid.trusted_module_argv("phase_loop_runtime.seat_uid", "teardown", "/x")


# --------------------------------------------------------------------------------------
# Inventory: no package helper is started with `python -m` anywhere in the runtime.
# --------------------------------------------------------------------------------------

# `python -m <tool>` for third-party tooling that is MEANT to run in the repository it is
# pointed at (installing it, running its own tests). These are not this package's helpers.
_REPOSITORY_TOOLING = {("verification_evidence.py", "pip"), ("runner.py", "pytest")}


_PACKAGE_MODULE_IN_TEXT = re.compile(r"(?:^|\s)-m\s+phase_loop_runtime(?:\.|\s|$)")


def _text_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return []


def _module_launches(tree: ast.AST) -> list[tuple[int, str]]:
    """Every argv literal (list or tuple) that runs a module with ``-m``:

    * ``"-m"`` followed by ``phase_loop_runtime...``, whatever the interpreter spelling
      (``sys.executable``, ``"/usr/bin/python3"``, ``"python3"``, a variable);
    * ``sys.executable, "-m", <module>`` for any module (third-party tooling is listed);
    * an element whose text runs ``-m phase_loop_runtime...`` (a shell command string)."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = node.elts
        for i, item in enumerate(items):
            for text in _text_parts(item):
                if _PACKAGE_MODULE_IN_TEXT.search(text):
                    found.append((node.lineno, text.strip()))
            if not (isinstance(item, ast.Constant) and item.value == "-m" and i + 1 < len(items)):
                continue
            target = items[i + 1]
            module = target.value if (isinstance(target, ast.Constant)
                                      and isinstance(target.value, str)) else None
            head = items[i - 1] if i else None
            by_executable = (isinstance(head, ast.Attribute) and head.attr == "executable"
                             and isinstance(head.value, ast.Name) and head.value.id == "sys")
            if module is not None and (module == "phase_loop_runtime"
                                       or module.startswith("phase_loop_runtime.")
                                       or by_executable):
                found.append((node.lineno, module))
    return found


def test_no_package_helper_is_launched_with_dash_m():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, module in _module_launches(tree):
            if (path.name, module) in _REPOSITORY_TOOLING:
                continue
            offenders.append(f"{path.relative_to(SRC)}:{line} -m {module}")
    assert offenders == [], (
        "launch this package's helpers with seat_uid.trusted_module_argv: " + "; ".join(offenders))


def test_the_inventory_scan_sees_a_dash_m_launch():
    sample = ast.parse('argv = [sys.executable, "-m", "phase_loop_runtime.seat_uid", "x"]\n')
    assert _module_launches(sample) == [(1, "phase_loop_runtime.seat_uid")]
    # Any interpreter spelling, and a shell command string, is seen too.
    for spelling in ('"/usr/bin/python3"', '"python3"', "python", "sys.executable"):
        sample = ast.parse(f'a = ({spelling}, "-m", "phase_loop_runtime.seat_uid", "handoff")\n')
        assert _module_launches(sample) == [(1, "phase_loop_runtime.seat_uid")], spelling
    sample = ast.parse('a = ["/bin/sh", "-c", f"cd {d} && python3 -m phase_loop_runtime.seat_uid x"]\n')
    assert len(_module_launches(sample)) == 1
    # nsenter's own `-m` (its mount namespace flag) is not a Python launch.
    assert _module_launches(ast.parse('a = ["/usr/bin/nsenter", "-t", "1", "-U", "-m", "--x"]\n')) == []


def test_the_handoff_segment_is_the_trusted_launch(monkeypatch, tmp_path):
    """The seat-uid handoff runs under nsenter with the parent's working directory: its
    segment of the jail prefix is exactly the trusted launch, nothing else."""
    from test_seat_sandbox_permissions import _fake_jail

    jail = _fake_jail(tmp_path / "jail")
    enter_h = ("nsenter", "-t", "4242", "-U", "--net", "--mount", "--preserve-credentials")
    token = pi._EGRESS_LAUNCH_PREFIX.set((*enter_h, "setpriv", "--bounding-set=-all"))
    try:
        prefix = pi._compose_seat_jail_prefix(jail)
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(token)
        seat_jail.close_jail_fds(jail)
    keyring = seat_uid.trusted_module_argv("phase_loop_runtime.seat_keyring_exec", "--")
    handoff = seat_uid.trusted_module_argv(
        "phase_loop_runtime.seat_uid", "handoff", jail.review_dir, jail.tree_dir,
        str(jail.seat_ids[0]), "--")
    assert prefix[:len(keyring)] == keyring
    rest = prefix[len(keyring):]
    assert tuple(rest[:len(enter_h)]) == enter_h
    rest = rest[len(enter_h):]
    assert rest[:len(handoff)] == handoff
    assert rest[len(handoff):len(handoff) + len(jail.process_owner)] == list(jail.process_owner)
    assert "-m" not in prefix[:len(keyring) + len(enter_h) + len(handoff)]


# --------------------------------------------------------------------------------------
# agent-harness#1147 scratch decision on the jailed launch (merged with agent-harness#1161).
# --------------------------------------------------------------------------------------

def test_the_jailed_probe_and_launch_get_the_same_decided_env(monkeypatch, tmp_path):
    from phase_loop_runtime import sandbox_policy
    from test_seat_sandbox_permissions import _fake_jail

    jail = _fake_jail(tmp_path / "jail")
    probe = _fake_jail(tmp_path / "probe")
    seen: list = []
    monkeypatch.setattr(pi, "_require_qualified_jail", lambda owner: None)
    monkeypatch.setattr(pi, "_compose_launch_prefix", lambda *a: ["prefix"])
    monkeypatch.setattr(pi, "_compose_seat_jail_prefix", lambda owner, *a: ["probe-prefix"])
    monkeypatch.setattr(pi, "_require_jailed_seat_identity",
                        lambda prefix, owner, fds=(), env=None: seen.append(env))
    monkeypatch.setattr(pi.subprocess, "Popen", lambda argv, **kw: seen.append(kw["env"]))
    try:
        pi.launch_provider([jail.provider_argv0], process_owner=jail, probe_owner=probe,
                           env={"HOME": "/operator"}, stdin=subprocess.DEVNULL)
    finally:
        seat_jail.close_jail_fds(jail)
        seat_jail.close_jail_fds(probe)
    assert len(seen) == 2 and seen[0] is seen[1]
    assert sandbox_policy.decided_scratch(seen[0]) == sandbox_policy.CHILD_SCRATCH_RELOCATE
    # The caller's env is not the helper chain's: the jail clears it and sets the seat's own.
    assert "HOME" not in seen[0]


def test_the_seat_scratch_is_its_disk_backed_home_never_the_jail_tmpfs(tmp_path):
    from test_seat_sandbox_permissions import _fake_jail

    for leg in ("claude", "gemini"):
        env = seat_jail.seat_env(leg, token_fd=None)
        assert env["TMPDIR"] == seat_jail.SEAT_TMP
        assert seat_jail.SEAT_TMP.startswith(seat_jail.SEAT_HOME + "/")
    assert seat_jail.seat_env("claude", token_fd=None)["CLAUDE_CODE_TMPDIR"] == seat_jail.SEAT_TMP
    jail = _fake_jail(tmp_path)
    try:
        owner = list(jail.process_owner)
        setenv = {owner[i + 1]: owner[i + 2] for i, item in enumerate(owner) if item == "--setenv"}
        assert setenv["TMPDIR"] == setenv["CLAUDE_CODE_TMPDIR"] == seat_jail.SEAT_TMP
        home = Path(jail.review_dir) / seat_jail.HOST_HOME_DIRNAME
        assert owner[owner.index(str(home)) + 1] == seat_jail.SEAT_HOME
        assert (home / seat_jail.SEAT_TMP_DIRNAME).is_dir()
    finally:
        seat_jail.close_jail_fds(jail)


def test_the_qualification_probe_gets_a_decided_env(monkeypatch, tmp_path):
    """Non-live: the EC-EXECFIND-2 probe launch takes the jailed launch's decided env."""
    import contextlib

    from phase_loop_runtime import sandbox_egress, sandbox_policy, seat_jail_qualification as sq

    seen: list = []

    def _run(argv, **kwargs):
        seen.append(kwargs.get("env"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(sq.seat_uid, "subordinate_range", lambda _f: (100000, 65536))
    monkeypatch.setattr(sq.seat_uid, "seat_id_count", lambda *a: 1)
    monkeypatch.setattr(sq.seat_uid, "lease_seat_id", lambda _n: contextlib.nullcontext(7))
    monkeypatch.setattr(sq.seat_uid, "teardown_in_h", lambda *a, **k: None)
    monkeypatch.setattr(sandbox_egress, "isolated_network",
                        lambda **k: contextlib.nullcontext(
                            ["nsenter", "-t", "4242", "-U", "--net", "setpriv"]))
    monkeypatch.setattr(pi, "_require_canonical_jail", lambda jail: None)
    monkeypatch.setattr(pi, "_compose_seat_jail_prefix", lambda jail, *a: ["prefix"])
    monkeypatch.setattr(sq.subprocess, "run", _run)
    with contextlib.suppress(Exception):
        sq._run_probe_in_jail("claude", tmp_path, {}, Path("/usr/bin/true"), None)
    assert len(seen) == 1
    assert sandbox_policy.decided_scratch(seen[0]) == sandbox_policy.CHILD_SCRATCH_RELOCATE
