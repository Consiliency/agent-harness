"""Host Git uses trusted helpers and neutral review settings."""

import os
from pathlib import Path
import subprocess

from phase_loop_runtime import review_stage
from phase_loop_runtime.panel_invoker import _govlean_authority_switched as govlean_check


def _git(repo, *args):
    return subprocess.run(["/usr/bin/git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True).stdout


def _repository(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Review fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "a.txt").write_text("before\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def test_host_git_scrubs_inherited_settings_and_driver_commands(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    marker = tmp_path / "helper-ran"
    command = f"/bin/sh -c 'printf called > {marker}'"
    for key in ("core.fsmonitor", "diff.external", "diff.fixture.textconv",
                "filter.fixture.clean", "filter.fixture.smudge", "filter.fixture.process",
                "merge.fixture.driver"):
        _git(repo, "config", key, command)
    (repo / ".gitattributes").write_text("*.txt diff=fixture filter=fixture merge=fixture\n")
    (repo / "a.txt").write_text("after\n")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.external")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", command)
    result = review_stage.host_git(repo, "diff", "--binary", capture_output=True, text=True, check=True)
    assert "after" in result.stdout
    assert not marker.exists()
    env = review_stage.host_git_env()
    assert "GIT_CONFIG_COUNT" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_ATTR_NOSYSTEM"] == "1"


def test_review_checkout_has_no_project_hooks_or_filters(tmp_path):
    repo = _repository(tmp_path)
    marker = tmp_path / "checkout-helper-ran"
    command = f"/bin/sh -c 'printf called > {marker}'"
    hook = repo / ".git/hooks/post-checkout"
    hook.write_text("#!/bin/sh\n" + command + "\n")
    hook.chmod(0o700)
    _git(repo, "config", "core.hooksPath", str(hook.parent))
    _git(repo, "config", "filter.fixture.smudge", command)
    _git(repo, "config", "filter.fixture.clean", command)
    (repo / ".gitattributes").write_text("*.txt filter=fixture\n")
    stage = review_stage.stage_review_tree(repo, parent=tmp_path)
    try:
        assert (stage / "a.txt").read_text() == "before\n"
        assert not marker.exists()
    finally:
        review_stage.remove_review_stage(stage)


def test_host_helper_ignores_cwd_and_relative_path_entries(tmp_path, monkeypatch):
    planted = tmp_path / "git"
    planted.write_text("#!/bin/sh\nexit 42\n")
    planted.chmod(0o700)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f".:{tmp_path}:/usr/bin:/bin")
    executable = review_stage.trusted_host_executable("git")
    assert Path(executable).is_absolute()
    assert executable != str(planted)


def test_conformance_merge_tree_requires_the_supported_git_version(tmp_path, monkeypatch):
    import pytest

    def executable(name, *, require_conform=False):
        assert name == 'git'
        if require_conform:
            raise ValueError('host_git_version_unavailable')
        return '/usr/bin/git'

    monkeypatch.setattr(review_stage, 'trusted_host_executable', executable)
    monkeypatch.setattr(review_stage.subprocess, 'run', lambda *a, **k: pytest.fail('ran an unsupported merge-tree'))
    with pytest.raises(ValueError, match='host_git_version_unavailable'):
        review_stage.host_git(tmp_path, 'merge-tree', '--write-tree', 'base', 'head')


def test_sandbox_facts_record_the_selected_git_and_its_version(tmp_path):
    from types import SimpleNamespace
    from phase_loop_runtime import panel_invoker

    choice = SimpleNamespace(host=None, path=tmp_path, fell_back=False, reason=None)
    token = panel_invoker._record_sandbox_facts(choice, {}, staged_at=tmp_path / 'stage')
    try:
        facts = panel_invoker._sandbox_evidence()
        executable = review_stage.trusted_host_executable('git')
        assert facts['host_git_executable'] == executable
        assert facts['host_git_version'] == '.'.join(map(str, review_stage._HOST_HELPER_VERSIONS[executable]))
    finally:
        panel_invoker._SANDBOX_ROUND_FACTS.reset(token)


def test_undefined_attribute_driver_is_a_noop(tmp_path):
    repo = _repository(tmp_path)
    (repo / ".gitattributes").write_text("*.txt filter=undefined diff=undefined\n")
    (repo / "a.txt").write_text("changed\n")
    result = review_stage.host_git(repo, "diff", capture_output=True, text=True, check=True)
    assert "+changed" in result.stdout


def test_executor_review_inventory_does_not_run_a_project_helper(tmp_path):
    from phase_loop_runtime import launcher
    repo = _repository(tmp_path)
    marker = tmp_path / 'inventory-helper-ran'
    helper = tmp_path / 'inventory-helper'
    helper.write_text('#!/bin/sh\nprintf called > ' + str(marker) + '\nprintf "token\\0"\n')
    helper.chmod(0o700)
    _git(repo, 'config', 'core.fsmonitor', str(helper))
    assert 'a.txt' in launcher._git_review_tree_paths(repo)
    assert not marker.exists()


def test_review_provider_lookup_uses_the_frozen_host_search(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker
    planted = tmp_path / 'claude'
    planted.write_text('#!/bin/sh\nexit 42\n')
    planted.chmod(0o700)
    search = panel_invoker._PROVIDER_SEARCH_PATH
    monkeypatch.setattr(panel_invoker.shutil, 'which',
                        lambda name, path: '/usr/bin/true' if path == search else str(planted))
    harness, source = panel_invoker._seat_provider_source('claude', {'PATH': str(tmp_path)})
    assert harness == 'claude'
    assert source == '/usr/bin/true'


def test_review_authority_uses_the_base_manifest(tmp_path):
    from phase_loop_runtime import panel_invoker
    repo = _repository(tmp_path)
    _git(repo, 'branch', '-M', 'main')
    manifest = repo / 'plans/manifest.json'
    manifest.parent.mkdir()
    manifest.write_text('{"plans":[{"slug":"v10-GOVLEAN","lifecycle":[]}]}')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'base controls')
    _git(repo, 'checkout', '-qb', 'candidate')
    manifest.write_text('{"plans":[{"slug":"v10-GOVLEAN","lifecycle":[{"transition":"authority_switch"}]}]}')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'candidate data')
    assert panel_invoker._govlean_authority_switched(repo) is False


def test_review_ladder_uses_base_configuration(tmp_path):
    from phase_loop_runtime.advisor_board.config import load_president_ladder
    repo = _repository(tmp_path)
    _git(repo, 'branch', '-M', 'main')
    config = repo / '.agent-harness/advisor-boards.toml'
    config.parent.mkdir()
    config.write_text('[president]\nladder = ["fable", "sol"]\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'base configuration')
    _git(repo, 'checkout', '-qb', 'candidate')
    config.write_text('[president]\nladder = ["gemini"]\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'candidate configuration')
    assert load_president_ladder(repo, path=tmp_path / 'absent', review_base=True) == ('fable', 'sol')


def test_review_base_refuses_unproved_authority(tmp_path):
    import pytest
    repo = _repository(tmp_path)
    _git(repo, 'branch', '-M', 'candidate')
    with pytest.raises(ValueError, match='review_base_unavailable'):
        review_stage.trusted_review_control(repo, 'plans/manifest.json')


def test_review_control_reads_objects_without_opening_candidate_paths(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    _git(repo, 'branch', '-M', 'main')
    config = repo / '.agent-harness/advisor-boards.toml'
    config.parent.mkdir()
    config.write_text('[president]\nladder = ["fable"]\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'base configuration')
    config.unlink()
    config.symlink_to(tmp_path / 'operator-file')
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != config
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded)
    assert review_stage.trusted_review_control(repo, '.agent-harness/advisor-boards.toml') == (
        b'[president]\nladder = ["fable"]\n'
    )


def test_broker_repository_digests_use_the_trusted_helper(tmp_path, monkeypatch):
    from phase_loop_runtime.advisor_board import backing
    repo = _repository(tmp_path)
    expected = backing._canonical_repo_digest(repo)
    marker = tmp_path / 'unselected-helper-ran'
    planted = tmp_path / 'git'
    planted.write_text('#!/bin/sh\nprintf called > ' + str(marker) + '\nexit 42\n')
    planted.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path))
    assert backing._canonical_repo_digest(repo) == expected
    assert backing._staged_tree_digest(repo) == review_stage.review_tree_manifest_sha256(repo)
    assert not marker.exists()


def test_standalone_advisory_has_a_trusted_control_base(tmp_path):
    from phase_loop_runtime import cli

    authority = cli._advisory_review_authority(tmp_path)
    assert review_stage.trusted_review_control(authority, 'plans/manifest.json') is None


def test_non_repository_scratch_keeps_the_trusted_cwd_controls(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    _git(repo, 'branch', '-M', 'main')
    manifest = repo / 'plans/manifest.json'
    manifest.parent.mkdir()
    manifest.write_text('{"plans":[{"slug":"v10-GOVLEAN","lifecycle":[{"transition":"authority_switch"}]}]}')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'Frozen controls')
    scratch = tmp_path / 'private-scratch'
    scratch.mkdir()
    monkeypatch.chdir(repo)
    assert govlean_check(scratch) is True


def test_host_checkout_neutralizes_drivers_on_supported_older_git(tmp_path, monkeypatch):
    git='/usr/bin/git'
    repo=tmp_path/'repo'; repo.mkdir()
    def run(*args):
        return subprocess.run([git,'-C',str(repo),*args],check=True,capture_output=True,text=True)
    run('init','-q')
    run('config','user.name','Fixture');run('config','user.email','fixture@example.invalid')
    (repo/'.gitattributes').write_text('a.txt filter=fixture\n')
    (repo/'a.txt').write_text('declared source\n')
    run('add','.');run('commit','-qm','fixture')
    marker=tmp_path/'driver-ran'
    run('config','filter.fixture.smudge',f'/bin/sh -c "printf called > {marker}; cat"')
    (repo/'a.txt').unlink()
    run('checkout-index','-af')
    assert marker.read_text()=='called'
    marker.unlink()
    (repo/'a.txt').unlink()
    monkeypatch.setattr(review_stage,'trusted_host_executable',lambda name,**kwargs:git)
    monkeypatch.setitem(review_stage._HOST_HELPER_VERSIONS,git,(2,34,1))
    result=review_stage.host_git(repo,'checkout-index','-af',capture_output=True,text=True,check=True)
    assert result.returncode==0 and not marker.exists()
    assert (repo/'a.txt').read_text()=='declared source\n'


def test_governed_diff_does_not_run_repository_drivers(tmp_path):
    from phase_loop_runtime import governed_bundle

    repo=tmp_path/'repo';repo.mkdir()
    def git(*args):
        return subprocess.run(['/usr/bin/git','-C',str(repo),*args],check=True,capture_output=True,text=True)
    git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
    (repo/'a.txt').write_text('before\n');(repo/'.gitattributes').write_text('*.txt diff=fixture\n')
    git('add','.');git('commit','-qm','fixture')
    (repo/'a.txt').write_text('after\n');git('add','a.txt')
    marker=tmp_path/'driver-ran'
    git('config','diff.fixture.textconv',f'/bin/sh -c "printf called > {marker}; cat"')
    git('diff','--cached')
    assert marker.read_text()=='called';marker.unlink()
    text=governed_bundle.staged_index_diff(repo,['a.txt'])
    assert '+after' in text and not marker.exists()
