"""agent-harness#1392 — the interactive execute-phase publication mode.

The interactive path (an operator invokes ``<harness>-execute-phase`` directly) had no
equivalent of the runner's ``--closeout-mode``. ``phase-loop publication-mode`` resolves
none | draft-only | ready from the repo's committed ``.phase-loop-publication.toml`` and
the user's ``agent-harness/publication.toml`` (most restrictive wins), and prints the
action the executing agent must take.

The acceptance cells drive the skill's publication steps in a scratch repo with a bare
local remote and a recording ``gh`` on PATH, gated on the resolver's printed mode.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from phase_loop_runtime import publication_mode as pm
from phase_loop_runtime.cli import main as cli_main

CONFIG = pm.REPO_CONFIG


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("scratch\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _mode_toml(mode: str) -> str:
    return f'[interactive]\nmode = "{mode}"\n'


def _commit_config(repo: Path, text: str) -> None:
    (repo / CONFIG).write_text(text, encoding="utf-8")
    _git(repo, "add", CONFIG)
    _git(repo, "commit", "-q", "-m", "publication config")


def _user_env(root: Path, text: str | None) -> dict[str, str]:
    xdg = root / "xdg"
    if text is not None:
        path = xdg / pm.USER_CONFIG_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {"XDG_CONFIG_HOME": str(xdg)}


def _run_cli(repo: Path, env: dict[str, str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env), redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(["publication-mode", "--repo", str(repo)])
    return rc, out.getvalue(), err.getvalue()


class ModeCellsTest(unittest.TestCase):
    def test_no_config_resolves_ready_the_unchanged_default(self):
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            rc, out, _ = _run_cli(repo, _user_env(Path(td), None))
        self.assertEqual(rc, 0)
        self.assertIn("publication_mode=ready\n", out)
        self.assertIn("PUBLICATION_ACTION: push the feature branch", out)

    def test_each_repo_mode_resolves_and_states_its_action(self):
        expected = {
            "none": "do not run git push, gh pr create or gh pr ready",
            "draft-only": "Never run gh pr ready",
            "ready": "flip it to ready (gh pr ready)",
        }
        for mode, action in expected.items():
            with self.subTest(mode=mode), TemporaryDirectory() as td:
                repo = _init_repo(Path(td))
                _commit_config(repo, _mode_toml(mode))
                rc, out, _ = _run_cli(repo, _user_env(Path(td), None))
                self.assertEqual(rc, 0)
                self.assertIn(f"publication_mode={mode}\n", out)
                self.assertIn(action, out)
                self.assertEqual(out.count("PUBLICATION_ACTION:"), 1)

    def test_resolver_reads_the_repo_root_from_a_subdirectory(self):
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            _commit_config(repo, _mode_toml("none"))
            sub = repo / "pkg"
            sub.mkdir()
            rc, out, _ = _run_cli(sub, _user_env(Path(td), None))
        self.assertEqual((rc, "publication_mode=none\n" in out), (0, True))


class PrecedenceTest(unittest.TestCase):
    def _resolve(self, repo_mode: str | None, user_mode: str | None) -> str:
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            if repo_mode is not None:
                _commit_config(repo, _mode_toml(repo_mode))
            env = _user_env(Path(td), _mode_toml(user_mode) if user_mode else None)
            return pm.resolve(repo, env=env).mode

    def test_most_restrictive_layer_wins_in_both_directions(self):
        cells = {
            ("none", "ready"): "none",          # a user cannot widen the repo
            ("ready", "none"): "none",          # a user can withhold what the repo allows
            ("draft-only", "ready"): "draft-only",
            ("ready", "draft-only"): "draft-only",
            ("draft-only", "none"): "none",
            ("none", "draft-only"): "none",
            ("ready", "ready"): "ready",
            (None, "draft-only"): "draft-only",
            ("draft-only", None): "draft-only",
            (None, None): "ready",
        }
        for (repo_mode, user_mode), want in cells.items():
            with self.subTest(repo=repo_mode, user=user_mode):
                self.assertEqual(self._resolve(repo_mode, user_mode), want)

    def test_user_layer_resolves_from_the_given_env_only(self):
        with TemporaryDirectory() as td:
            home = Path(td) / "home"
            path = home / ".config" / pm.USER_CONFIG_RELATIVE_PATH
            path.parent.mkdir(parents=True)
            path.write_text(_mode_toml("none"), encoding="utf-8")
            self.assertEqual(pm.user_config_path({"HOME": str(home)}), path)
            self.assertIsNone(pm.user_config_path({}))
            repo = _init_repo(Path(td))
            self.assertEqual(pm.resolve(repo, env={"HOME": str(home)}).mode, "none")


class MalformedConfigTest(unittest.TestCase):
    BAD = {
        "invalid toml": "[interactive\nmode = 'none'\n",
        "unknown table": '[publish]\nmode = "none"\n',
        "unknown key": '[interactive]\nmode = "none"\npush = false\n',
        "bad value": '[interactive]\nmode = "manual"\n',
        "wrong type": "[interactive]\nmode = 0\n",
        "not a table": 'interactive = "none"\n',
    }

    def _assert_blocked(self, rc: int, out: str, err: str, needle: str) -> None:
        self.assertEqual(rc, 2)
        self.assertIn("publication_mode=error\n", out)
        self.assertNotIn("publication_mode=ready", out)
        self.assertIn("PUBLICATION_ACTION: blocked: do not run git push", out)
        self.assertIn(needle, err)

    def test_malformed_repo_config_is_a_visible_error_never_a_default(self):
        for name, text in self.BAD.items():
            with self.subTest(case=name), TemporaryDirectory() as td:
                repo = _init_repo(Path(td))
                _commit_config(repo, text)
                rc, out, err = _run_cli(repo, _user_env(Path(td), None))
                self._assert_blocked(rc, out, err, f"{CONFIG} at HEAD")

    def test_malformed_user_config_is_a_visible_error_never_a_default(self):
        for name, text in self.BAD.items():
            with self.subTest(case=name), TemporaryDirectory() as td:
                repo = _init_repo(Path(td))
                rc, out, err = _run_cli(repo, _user_env(Path(td), text))
                self._assert_blocked(rc, out, err, "publication.toml")

    def test_uncommitted_repo_config_is_refused_in_every_state(self):
        def untracked(repo: Path) -> None:
            (repo / CONFIG).write_text(_mode_toml("ready"), encoding="utf-8")

        def ignored(repo: Path) -> None:
            (repo / ".git" / "info" / "exclude").write_text(f"{CONFIG}\n", encoding="utf-8")
            untracked(repo)

        def staged(repo: Path) -> None:
            untracked(repo)
            _git(repo, "add", CONFIG)

        def modified(repo: Path) -> None:
            _commit_config(repo, _mode_toml("none"))
            (repo / CONFIG).write_text(_mode_toml("ready"), encoding="utf-8")

        def deleted(repo: Path) -> None:
            _commit_config(repo, _mode_toml("none"))
            (repo / CONFIG).unlink()

        for name, setup in {"untracked": untracked, "ignored": ignored, "staged": staged,
                            "modified": modified, "deleted": deleted}.items():
            with self.subTest(state=name), TemporaryDirectory() as td:
                repo = _init_repo(Path(td))
                setup(repo)
                rc, out, err = _run_cli(repo, _user_env(Path(td), None))
                self._assert_blocked(rc, out, err, "is not committed as it stands")

    def test_outside_a_git_work_tree_is_an_error(self):
        with TemporaryDirectory() as td:
            plain = Path(td) / "plain"
            plain.mkdir()
            rc, out, err = _run_cli(plain, _user_env(Path(td), None))
        self._assert_blocked(rc, out, err, "not inside a git work tree")

    def test_an_unexpected_failure_still_prints_the_blocking_action(self):
        out = io.StringIO()
        with TemporaryDirectory() as td, redirect_stdout(out), \
                mock.patch.object(pm, "resolve", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                pm.main(repo=td)
        self.assertIn("publication_mode=error\n", out.getvalue())
        self.assertEqual(out.getvalue().count("PUBLICATION_ACTION: blocked:"), 1)


# The skill's interactive publication steps ("Draft PR early" on the first commit, then
# Publication mode (b) at closeout), each gated on the resolver's printed mode. A
# non-zero resolver exit publishes nothing.
_DRIVER = textwrap.dedent("""\
    set -eu
    resolve() {
        out=$(phase-loop publication-mode --repo .) || { echo "$out" >&2; exit 3; }
        printf '%s\\n' "$out" | sed -n 's/^publication_mode=//p'
    }
    git checkout -q -b feature/phase-x
    echo one > feature.txt && git add feature.txt && git commit -q -m "lane 1"
    mode=$(resolve)
    if [ "$mode" != none ]; then
        git push -q -u origin feature/phase-x
        gh pr create --draft --fill
    fi
    echo two >> feature.txt && git commit -q -am "lane 2"
    mode=$(resolve)
    if [ "$mode" != none ]; then git push -q origin feature/phase-x; fi
    if [ "$mode" = ready ]; then gh pr ready; fi
    echo "completed mode=$mode"
""")


class InteractivePublicationAcceptanceTest(unittest.TestCase):
    """Scratch repo + bare local remote + recording ``gh``: what reaches the remote."""

    def _run_phase(self, repo_mode: str | None) -> tuple[subprocess.CompletedProcess, dict, str, dict]:
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        remote = root / "remote.git"
        subprocess.check_call(["git", "init", "-q", "--bare", str(remote)])
        repo = _init_repo(root)
        if repo_mode is not None:
            _commit_config(repo, _mode_toml(repo_mode))
        _git(repo, "remote", "add", "origin", str(remote))
        _git(repo, "push", "-q", "origin", "main")
        before = self._refs(remote)

        bin_dir = root / "bin"
        bin_dir.mkdir()
        gh_log = root / "gh.log"
        (bin_dir / "gh").write_text(
            f'#!/bin/sh\necho "$*" >> "{gh_log}"\necho https://example.invalid/pr/1\n',
            encoding="utf-8")
        (bin_dir / "phase-loop").write_text(
            f"#!/bin/sh\nexec {sys.executable} -c "
            "'import sys; from phase_loop_runtime.cli import main; sys.exit(main(sys.argv[1:]))'"
            ' "$@"\n', encoding="utf-8")
        for exe in ("gh", "phase-loop"):
            (bin_dir / exe).chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               "XDG_CONFIG_HOME": str(root / "xdg")}
        proc = subprocess.run(["sh", "-c", _DRIVER], cwd=repo, env=env, text=True,
                              capture_output=True, check=False)
        gh_calls = gh_log.read_text(encoding="utf-8") if gh_log.exists() else ""
        return proc, before, gh_calls, self._refs(remote)

    @staticmethod
    def _refs(remote: Path) -> dict[str, str]:
        out = subprocess.check_output(["git", "ls-remote", str(remote)], text=True)
        return {ref: sha for sha, ref in (line.split("\t") for line in out.splitlines())}

    def test_none_completes_the_phase_with_no_push_and_no_pr(self):
        proc, before, gh_calls, after = self._run_phase("none")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("completed mode=none", proc.stdout)
        self.assertEqual(after, before, "the remote gained or moved a ref under mode=none")
        self.assertNotIn("refs/heads/feature/phase-x", after)
        self.assertEqual(gh_calls, "", "gh was invoked under mode=none")

    def test_draft_only_pushes_and_opens_a_draft_never_flipped_ready(self):
        proc, before, gh_calls, after = self._run_phase("draft-only")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("refs/heads/feature/phase-x", after)
        self.assertEqual(gh_calls.splitlines(), ["pr create --draft --fill"])

    def test_ready_default_pushes_opens_a_draft_and_flips_it_ready(self):
        proc, before, gh_calls, after = self._run_phase(None)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("refs/heads/feature/phase-x", after)
        self.assertEqual(gh_calls.splitlines(), ["pr create --draft --fill", "pr ready"])

    def test_malformed_config_blocks_publication_before_any_push(self):
        # A committed config with a bad value: the resolver exits non-zero, nothing leaves.
        proc, before, gh_calls, after = self._run_phase("publish")
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertIn("publication_mode=error", proc.stderr)
        self.assertEqual(after, before)
        self.assertEqual(gh_calls, "")


def test_unreadable_committed_opt_out_blocks_publication(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    source.mkdir()

    def git(where, *args):
        return subprocess.check_output(
            ["git", "-C", str(where), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.name", "review")
    git(source, "config", "user.email", "review@example.invalid")
    git(source, "config", "commit.gpgsign", "false")
    (source / "README.md").write_text("baseline\n", encoding="utf-8")
    (source / pm.REPO_CONFIG).write_text(
        '[interactive]\nmode = "none"\n', encoding="utf-8"
    )
    git(source, "add", "README.md", pm.REPO_CONFIG)
    git(source, "commit", "-q", "-m", "opt out")
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(remote)], check=True)
    git(remote, "config", "uploadpack.allowFilter", "true")
    subprocess.run(
        ["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
         remote.as_uri(), str(repo)],
        check=True,
    )
    git(repo, "sparse-checkout", "init", "--no-cone")
    git(repo, "sparse-checkout", "set", "/README.md")
    git(repo, "checkout", "-q", "-b", "feature/test")
    assert not (repo / pm.REPO_CONFIG).exists()
    assert pm.REPO_CONFIG in git(repo, "ls-tree", "HEAD", "--", pm.REPO_CONFIG)
    git(repo, "config", "remote.origin.url", str(tmp_path / "fetch-unavailable.git"))
    git(repo, "config", "remote.origin.pushurl", str(remote))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert git(repo, "status", "--porcelain", "--", pm.REPO_CONFIG) == ""

    rc = pm.main(repo=str(repo))

    assert rc == 2, "an unreadable committed opt-out must block publication"
    assert "PUBLICATION_ACTION: blocked:" in capsys.readouterr().out


class UnconfirmedAbsenceTest(unittest.TestCase):
    """A layer is absent only when absence is confirmed: the ``HEAD`` tree lists no such
    path, or the user path itself does not exist. A read that fails is an error."""

    _assert_blocked = MalformedConfigTest._assert_blocked

    def test_committed_opt_out_with_a_missing_blob_blocks_publication(self):
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            _commit_config(repo, _mode_toml("none"))
            oid = _git(repo, "rev-parse", f"HEAD:{CONFIG}")
            loose = repo / ".git" / "objects" / oid[:2] / oid[2:]
            self.assertTrue(loose.is_file(), "the committed blob is not a loose object")
            loose.unlink()
            rc, out, err = _run_cli(repo, _user_env(Path(td), None))
        self._assert_blocked(rc, out, err, "committed at HEAD but unreadable")

    def test_unborn_head_is_an_error_not_an_absent_repo_layer(self):
        with TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q", "-b", "main")
            rc, out, err = _run_cli(repo, _user_env(Path(td), None))
        self._assert_blocked(rc, out, err, "HEAD has no commit")

    def test_dangling_user_config_symlink_blocks_publication(self):
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            env = _user_env(Path(td), None)
            path = Path(env["XDG_CONFIG_HOME"]) / pm.USER_CONFIG_RELATIVE_PATH
            path.parent.mkdir(parents=True)
            path.symlink_to(Path(td) / "dotfiles" / "publication.toml")
            rc, out, err = _run_cli(repo, env)
        self._assert_blocked(rc, out, err, "publication.toml: unreadable")

    def test_looping_user_config_symlink_blocks_publication(self):
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            env = _user_env(Path(td), None)
            path = Path(env["XDG_CONFIG_HOME"]) / pm.USER_CONFIG_RELATIVE_PATH
            path.parent.mkdir(parents=True)
            other = path.with_name("other.toml")
            path.symlink_to(other)
            other.symlink_to(path)
            rc, out, err = _run_cli(repo, env)
        self._assert_blocked(rc, out, err, "publication.toml: unreadable")

    @unittest.skipIf(os.geteuid() == 0, "root bypasses directory permissions")
    def test_unsearchable_user_config_dir_is_a_config_error_not_a_traceback(self):
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            env = _user_env(Path(td), _mode_toml("none"))
            parent = (Path(env["XDG_CONFIG_HOME"]) / pm.USER_CONFIG_RELATIVE_PATH).parent
            parent.chmod(0o000)
            try:
                rc, out, err = _run_cli(repo, env)
            finally:
                parent.chmod(0o700)
        self._assert_blocked(rc, out, err, "publication.toml: unreadable")
        self.assertNotIn("Traceback", err)

    def test_partial_clone_with_a_reachable_source_honours_the_committed_mode(self):
        with TemporaryDirectory() as td:
            source = _init_repo(Path(td))
            _commit_config(source, _mode_toml("none"))
            remote = Path(td) / "remote.git"
            subprocess.check_call(["git", "clone", "-q", "--bare", str(source), str(remote)])
            _git(remote, "config", "uploadpack.allowFilter", "true")
            clone = Path(td) / "clone"
            subprocess.check_call(["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
                                   remote.as_uri(), str(clone)])
            _git(clone, "sparse-checkout", "init", "--no-cone")
            _git(clone, "sparse-checkout", "set", "/README.md")
            _git(clone, "checkout", "-q", "-b", "feature/test")
            missing = "?" + _git(source, "rev-parse", f"HEAD:{CONFIG}")
            self.assertIn(missing, _git(clone, "rev-list", "--objects", "--missing=print", "HEAD"))
            rc, out, _ = _run_cli(clone, _user_env(Path(td), None))
            self.assertEqual((rc, "publication_mode=none\n" in out), (0, True))
            self.assertNotIn(
                missing, _git(clone, "rev-list", "--objects", "--missing=print", "HEAD"))

    def test_committed_config_that_is_not_a_regular_file_names_its_entry_type(self):
        def symlink(repo: Path) -> None:
            (repo / CONFIG).symlink_to("README.md")
            _git(repo, "add", CONFIG)

        def tree(repo: Path) -> None:
            (repo / CONFIG).mkdir()
            (repo / CONFIG / "publication.toml").write_text(_mode_toml("ready"), encoding="utf-8")
            _git(repo, "add", CONFIG)

        def gitlink(repo: Path) -> None:
            (repo / CONFIG).mkdir()
            _git(repo, "update-index", "--add", "--cacheinfo",
                 f"160000,{_git(repo, 'rev-parse', 'HEAD')},{CONFIG}")

        for name, setup in {"symlink": symlink, "tree": tree, "gitlink": gitlink}.items():
            with self.subTest(entry=name), TemporaryDirectory() as td:
                repo = _init_repo(Path(td))
                setup(repo)
                _git(repo, "commit", "-q", "-m", "publication config")
                rc, out, err = _run_cli(repo, _user_env(Path(td), None))
                self._assert_blocked(rc, out, err, f"{CONFIG} at HEAD")
                self.assertIn(f"is a {name}", err)

    def test_user_layer_is_absent_when_its_path_cannot_exist(self):
        with TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            not_a_dir = Path(td) / "xdg-is-a-file"
            not_a_dir.write_text("", encoding="utf-8")
            rc, out, _ = _run_cli(repo, {"XDG_CONFIG_HOME": str(not_a_dir)})
            self.assertEqual((rc, "publication_mode=ready\n" in out), (0, True))
            resolution = pm.resolve(repo, env={})
            self.assertEqual((resolution.mode, resolution.user_config), ("ready", None))


if __name__ == "__main__":
    unittest.main()
