#!/usr/bin/env python3
"""Run, locally and in a CI-like environment, the checks your change can affect (agent-harness#1029).

    python3 phase-loop-runtime/scripts/local_check.py [--base REF] [--full] [--with-chronology] [--host-env] [--dry-run]
    make check            # same, from the repository root
    make check-full       # the whole standalone suite, CI's flags

Default: lint (ruff, CI's pinned version and config) plus the tests your diff can reach:

- every changed `phase-loop-runtime/tests/test_*.py`;
- every test that imports a changed `phase_loop_runtime` module (by dotted name);
- the CI guard tests when workflows, `ci/`, or the Gate A script changed;
- the whole suite when a shared fixture/config file changed (conftest, pyproject).

The diff is against `git merge-base HEAD <base>` (default `origin/main`) plus uncommitted and
untracked files. Tests run under `env -i` with a throwaway HOME and a bare PATH, which is how
CI-only failures (a test leaning on this host's login, config or PATH) reproduce locally.

What this does NOT cover, so CI still matters: tests that consume a changed module
without importing it by name (golden files, subprocess CLIs, string-keyed lookups), the
3.11/3.12 interpreters, and Gate A's install-from-wheel clean room. `--full` closes the first.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUFF_PIN = "ruff==0.15.5"  # .github/workflows/test.yml `lint (pyflakes)` job
PKG = "phase-loop-runtime"
CI_GUARD_GLOBS = ("tests/test_ci_*.py", "tests/test_*workflow*.py")
CI_TRIGGERS = (".github/workflows/", "ci/", f"{PKG}/scripts/gate_a_cleanroom.sh")
FULL_TRIGGERS = (f"{PKG}/tests/conftest.py", f"{PKG}/pyproject.toml", f"{PKG}/tests/phase_loop_test_utils.py")
SUITE_IGNORES = ("tests/test_legible_roadmap_contract.py", "tests/test_legible_evidence.py")
# The hosted lane's suite-environment install (test.yml), so local runs resolve what CI does.
CI_TEST_DEPS = ("./phase-loop-runtime[visual]", "pytest", "pytest-xdist==3.8.0", "build==1.6.1", "setuptools>=70.1")
VENV_DIR = ".local-check-venv"
VENV_PYTHON = "3.10"  # the CI floor lane pull requests run


def changed_files(repo: Path, base: str) -> list[str]:
    def git(*args: str) -> list[str]:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
        if done.returncode:
            sys.exit(f"local_check: git {' '.join(args)} failed: {done.stderr.strip()}\n"
                     f"  (fetch the base with `git fetch origin main`, or pass --base <ref>)")
        return [entry for entry in done.stdout.split("\0") if entry]

    merge_base = git("merge-base", "HEAD", base)[0].strip()
    # --no-renames: a rename is reported as delete + add, so importers of the OLD
    # module path are still selected (#1031 r1). -z: paths with quotes/non-ASCII verbatim.
    files = set(git("diff", "--name-only", "--no-renames", "-z", merge_base))
    files |= set(git("ls-files", "-z", "--others", "--exclude-standard"))
    return sorted(files)


def module_name(path: str) -> str | None:
    """`phase-loop-runtime/src/phase_loop_runtime/a/b.py` -> `phase_loop_runtime.a.b`."""
    prefix = f"{PKG}/src/"
    if not (path.startswith(prefix) and path.endswith(".py")):
        return None
    dotted = path[len(prefix):-3].replace("/", ".")
    return dotted.removesuffix(".__init__")


def imported_modules(text: str) -> set[str]:
    """Every module a source imports, by dotted name, anywhere in the file (parsed, so
    parenthesised multi-line imports count). `from a import b` yields both `a` and `a.b`,
    since `b` may be a submodule."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def imports_module(text: str, dotted: str) -> bool:
    """Does this source import `dotted` or one of its submodules?"""
    return any(name == dotted or name.startswith(dotted + ".") for name in imported_modules(text))


def select(pkg_root: Path, files: list[str]) -> tuple[list[str] | None, list[str]]:
    """(test paths relative to pkg_root, or None for the whole suite; the reasons)."""
    reasons: list[str] = []
    if any(f in FULL_TRIGGERS for f in files):
        return None, [f"shared test config changed ({', '.join(f for f in files if f in FULL_TRIGGERS)})"]
    tests: set[str] = set()
    for f in files:
        if f.startswith(f"{PKG}/tests/test_") and f.endswith(".py") and (pkg_root.parent / f).is_file():
            tests.add(f[len(PKG) + 1:])
    if tests:
        reasons.append(f"{len(tests)} changed test file(s)")
    modules = [m for m in (module_name(f) for f in files) if m]
    if modules:
        hits = set()
        for test in sorted((pkg_root / "tests").glob("test_*.py")):
            text = test.read_text(encoding="utf-8", errors="replace")
            if any(imports_module(text, m) for m in modules):
                hits.add(f"tests/{test.name}")
        reasons.append(f"{len(hits)} test file(s) importing {len(modules)} changed module(s)")
        tests |= hits
    if any(f.startswith(CI_TRIGGERS) for f in files):
        guards = {f"tests/{p.name}" for g in CI_GUARD_GLOBS for p in pkg_root.glob(g)}
        reasons.append(f"CI plumbing changed: {len(guards)} CI guard file(s)")
        tests |= guards
    return sorted(tests), reasons


def check_python(repo: Path) -> str:
    """$LOCAL_CHECK_PYTHON if set; otherwise a cached venv built with CI's install line (via uv).

    The clean environment drops HOME, so user-site packages a bare `python3` relies on
    vanish -- a dedicated venv is the only interpreter that behaves the same inside it.
    """
    override = os.environ.get("LOCAL_CHECK_PYTHON")
    if override:
        # Absolute, so the probe and the clean-env run use the SAME interpreter (#1031 r1).
        resolved = shutil.which(override)
        if resolved is None:
            sys.exit(f"local_check: LOCAL_CHECK_PYTHON={override} is not an executable")
        return str(Path(resolved).absolute())
    venv = repo / PKG / VENV_DIR
    python = venv / "bin" / "python"
    stamp = venv / ".deps"
    wanted = cache_key(repo)
    if python.is_file() and stamp.is_file() and stamp.read_text() == wanted:
        return str(python)
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("local_check: set LOCAL_CHECK_PYTHON to an interpreter with the test deps, or install uv")
    print(f"local_check: provisioning {venv.relative_to(repo)} (CI's test deps; rebuilt when they change)")
    # From scratch: layering onto an old venv would keep packages CI no longer installs.
    shutil.rmtree(venv, ignore_errors=True)
    subprocess.run([uv, "venv", "-q", "--python", VENV_PYTHON, str(venv)], cwd=repo, check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), *CI_TEST_DEPS], cwd=repo, check=True)
    stamp.write_text(wanted)
    return str(python)


def cache_key(repo: Path) -> str:
    """The cached venv is reused only for the same deps, project metadata and Python."""
    pyproject = hashlib.sha256((repo / PKG / "pyproject.toml").read_bytes()).hexdigest()
    return "\n".join((*CI_TEST_DEPS, f"pyproject.toml sha256 {pyproject}", f"python {VENV_PYTHON}"))


def clean_env(python: str) -> dict[str, str]:
    home = tempfile.mkdtemp(prefix="local-check-home-")
    import atexit
    atexit.register(shutil.rmtree, home, True)
    env = {
        "HOME": home,
        "PATH": f"{Path(python).parent}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONPATH": "src:tests",
        "TMPDIR": tempfile.gettempdir(),
    }
    for keep in ("TERM", "USER", "LOGNAME"):  # a CI runner has these too
        if keep in os.environ:
            env[keep] = os.environ[keep]
    return env


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--full", action="store_true", help="run the whole standalone suite")
    ap.add_argument("--with-chronology", action="store_true",
                    help="keep the ~50-minute CONFORM chronology node (CI runs it on py3.10/Gate A)")
    ap.add_argument("--host-env", action="store_true", help="keep this shell's environment")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)

    pkg_root = Path(__file__).resolve().parents[1]
    repo = pkg_root.parent
    if args.full:
        tests, reasons = None, ["--full"]
        print("local_check: whole standalone suite")
    else:
        files = changed_files(repo, args.base)
        tests, reasons = select(pkg_root, files)
        print(f"local_check: {len(files)} changed file(s) vs {args.base}")
    for reason in reasons:
        print(f"  - {reason}")

    python = sys.executable if args.dry_run and not os.environ.get("LOCAL_CHECK_PYTHON") else check_python(repo)
    version = subprocess.run([python, "-c", "import sys; print(sys.version.split()[0])"],
                             capture_output=True, text=True).stdout.strip()
    print(f"  python: {python} ({version})")
    has_xdist = subprocess.run([python, "-c", "import xdist"], capture_output=True).returncode == 0
    pytest_cmd = [python, "-m", "pytest", "-m", "not dotfiles_integration", "-q", "-p", "no:cacheprovider"]
    if has_xdist:
        pytest_cmd += ["-n", "auto", "--dist", "loadfile", "--max-worker-restart=0"]
    if tests is None:
        pytest_cmd += [arg for ignore in SUITE_IGNORES for arg in ("--ignore", ignore)]
    elif tests:
        pytest_cmd += tests
    if tests != [] and not args.with_chronology:
        # CI runs the ~50-minute CONFORM chronology node on py3.10/Gate A only; so does this
        # only with --with-chronology, in either mode.
        node = subprocess.run(["bash", str(repo / "ci" / "chronology-scope.sh"), "--node"],
                              cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
        pytest_cmd.append(f"--deselect={node}")

    uvx = shutil.which("uvx")
    lint_cmd = [uvx, RUFF_PIN.replace("==", "@"), "check", "."] if uvx else None
    print(f"  lint : {' '.join(lint_cmd) if lint_cmd else 'UNAVAILABLE (install uv for uvx; CI pins ' + RUFF_PIN + ')'}")
    print(f"  tests: {'none selected' if tests == [] else ' '.join(pytest_cmd[3:])}")
    print(f"  env  : {'host' if args.host_env else 'clean (env -i, throwaway HOME, bare PATH)'}"
          f"{'' if has_xdist else '; pytest-xdist absent, running serially'}")
    if args.dry_run:
        return 0

    # A check that could not lint is not a PASS (#1031 r1).
    status = 0 if lint_cmd else 1
    if lint_cmd:
        status |= subprocess.run(lint_cmd, cwd=repo).returncode
    if tests != []:
        env = dict(os.environ, PYTHONPATH="src:tests") if args.host_env else clean_env(python)
        code = subprocess.run(pytest_cmd, cwd=pkg_root, env=env).returncode
        status |= 0 if code == 5 else code  # 5: every selected test was deselected by marker
    print("local_check: " + ("PASS" if status == 0 else "FAIL") +
          " (CI still runs Gate A and, on main, 3.11/3.12)")
    return 1 if status else 0


if __name__ == "__main__":
    sys.exit(main())
