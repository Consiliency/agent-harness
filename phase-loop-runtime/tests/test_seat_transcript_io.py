"""Transcript ingestion uses bounded, no-follow seat I/O."""

import os

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress
from phase_loop_runtime.agy_canary_evidence import AgyCanaryEvidenceError


def test_missing_in_progress_output_is_empty(tmp_path):
    assert panel_invoker._read_review_output(tmp_path / "absent") == ""


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink", "oversized"])
def test_review_output_refuses_an_unsupported_file(tmp_path, kind):
    path = tmp_path / "output"
    other = tmp_path / "host-input"
    other.write_text("synthetic host input")
    if kind == "symlink":
        path.symlink_to(other)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "hardlink":
        os.link(other, path)
    else:
        with path.open("wb") as target:
            target.truncate(32 * 1024 * 1024 + 1)
    with pytest.raises((AgyCanaryEvidenceError, sandbox_egress.SeatIdentityUnverified)):
        panel_invoker._read_review_output(path)


def test_transcript_listing_refuses_a_linked_project_root(tmp_path, monkeypatch):
    real = tmp_path / "other-project"
    real.mkdir()
    (real / "neighbor.jsonl").write_text('{"message":{"role":"assistant","content":[{"type":"text","text":"synthetic unrelated text"}]}}\n')
    project = tmp_path / "project"
    project.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(panel_invoker, "_claude_project_dir_for_cwd", lambda _: project)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        panel_invoker._latest_claude_transcript_text("fixture", since=0)


@pytest.mark.parametrize("kind", ["parent-link", "hardlink", "oversized"])
def test_transcript_cleanup_refuses_unsupported_files(tmp_path, kind):
    project = tmp_path / "project"
    project.mkdir()
    transcript = project / "session.jsonl"
    transcript.write_bytes(b"synthetic transcript")
    if kind == "parent-link":
        alias = tmp_path / "alias"
        alias.symlink_to(project, target_is_directory=True)
        path = alias / transcript.name
    elif kind == "hardlink":
        os.link(transcript, tmp_path / "second-name")
        path = transcript
    else:
        with transcript.open("wb") as stream:
            stream.truncate(32 * 1024 * 1024 + 1)
        path = transcript
    evidence = {}
    assert panel_invoker._cleanup_broker_claude_transcript(path, evidence) is False
    assert evidence["claude_transcript_cleanup_verified"] is False
    assert transcript.exists()


def test_transcript_cleanup_removes_only_the_regular_owned_file(tmp_path):
    from hashlib import sha256

    transcript = tmp_path / "session.jsonl"
    transcript.write_bytes(b"synthetic transcript")
    evidence = {}
    assert panel_invoker._cleanup_broker_claude_transcript(transcript, evidence) is True
    assert not transcript.exists()
    assert evidence["claude_transcript_sha256"] == sha256(b"synthetic transcript").hexdigest()
    assert evidence["claude_transcript_bytes"] == len(b"synthetic transcript")


def test_host_write_remembers_the_precreated_output_identity(tmp_path):
    path = tmp_path / "answer.txt"
    panel_invoker._precreate_seat_output(path)
    replacement = tmp_path / "replacement"
    replacement.write_text("replacement content")
    replacement.replace(path)
    with pytest.raises(AgyCanaryEvidenceError):
        panel_invoker._write_seat_text(path, "final answer")
    assert path.read_text() == "replacement content"


def test_host_write_uses_the_retained_regular_output(tmp_path):
    path = tmp_path / "answer.txt"
    panel_invoker._precreate_seat_output(path)
    panel_invoker._write_seat_text(path, "final answer")
    assert path.read_text() == "final answer"


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'oversized', 'fifo'])
def test_codex_review_caller_refuses_unsupported_output(tmp_path, monkeypatch, kind):
    review = tmp_path / 'review'
    output = tmp_path / 'out'
    review.mkdir()
    output.mkdir()
    canary = tmp_path / 'host-input'
    canary.write_text('synthetic host input')
    monkeypatch.setattr(panel_invoker, '_leg_auth_ok', lambda *a, **k: (True, ''))

    def complete(*args, **kwargs):
        path = output / 'panel-codex.txt'
        if kind == 'symlink':
            path.symlink_to(canary)
        elif kind == 'hardlink':
            os.link(canary, path)
        elif kind == 'fifo':
            os.mkfifo(path)
        else:
            with path.open('wb') as stream:
                stream.truncate(32 * 1024 * 1024 + 1)
        return panel_invoker._LegRun(0, '', '')

    monkeypatch.setattr(panel_invoker, '_run_leg_with_liveness', complete)
    with pytest.raises(AgyCanaryEvidenceError):
        panel_invoker._exec_leg('codex', review, output, 60, artifact='synthetic review input')


def test_tui_session_retains_the_cli_named_transcript(tmp_path, owned_review_network):
    import json
    import re
    import uuid

    session_id = str(uuid.uuid4())
    transcript = tmp_path / ('claude-' + session_id + '.jsonl')
    output = tmp_path / 'answer.txt'
    slug = re.sub(r'[^A-Za-z0-9.-]', '-', str(tmp_path))
    event = {'type': 'assistant', 'message': {'role': 'assistant',
             'content': [{'type': 'text', 'text': 'Session transcript retained.'}],
             'stop_reason': 'end_turn'}}
    source = (
        'import os,pathlib\n'
        'project=pathlib.Path(os.environ["HOME"])/".claude/projects"/' + repr(slug) + '\n'
        '(project/' + repr(session_id + '.jsonl') + ').write_text(' + repr(json.dumps(event) + '\n') + ')\n'
        'pathlib.Path(' + repr(str(output)) + ').write_text("Reviewed.\\nAGREE\\n")\n'
    )
    rc, _text, detail, _tail = panel_invoker._run_claude_tui_session(
        command=['/usr/bin/python3', '-I', '-S', '-c', source, '--session-id', session_id],
        cwd=tmp_path, prompt='synthetic session', output_file=output,
        timeout_s=10, backstop_s=10, env={'PATH': '/usr/bin:/bin'},
        broker_transcript_path=transcript,
    )
    assert rc == 0 and detail == 'claude_tui_file_output'
    assert json.loads(transcript.read_text()) == event


def test_direct_tui_salvage_uses_its_explicit_session_only(tmp_path, owned_review_network, monkeypatch):
    import json
    import re

    monkeypatch.setattr(panel_invoker, '_latest_claude_transcript_text',
                        lambda *a, **k: pytest.fail('read a neighboring session'))
    slug = re.sub(r'[^A-Za-z0-9.-]', '-', str(tmp_path))
    event = {'type': 'assistant', 'message': {'role': 'assistant',
             'content': [{'type': 'text', 'text': 'Complete direct session.'},
                         {'type': 'text', 'text': 'AGREE'}], 'stop_reason': 'end_turn'}}
    source = (
        'import os,pathlib,sys,time\n'
        'session=sys.argv[sys.argv.index("--session-id")+1]\n'
        'project=pathlib.Path(os.environ["HOME"])/".claude/projects"/' + repr(slug) + '\n'
        '(project/(session+".jsonl")).write_text(' + repr(json.dumps(event) + '\n') + ')\n'
        'time.sleep(.3)\n'
    )
    retained = []
    original = panel_invoker._precreate_seat_output

    def remember(path):
        if str(path).endswith('.jsonl'):
            retained.append(path)
        return original(path)

    monkeypatch.setattr(panel_invoker, '_precreate_seat_output', remember)
    rc, text, detail, _tail = panel_invoker._run_claude_tui_session(
        command=['/usr/bin/python3', '-I', '-S', '-c', source],
        cwd=tmp_path, prompt='synthetic direct session', output_file=tmp_path / 'answer.txt',
        timeout_s=10, backstop_s=10, env={'PATH': '/usr/bin:/bin'},
    )
    assert rc != 0
    assert detail in {'claude_tui_pty_eof_no_output', 'claude_tui_missing_canonical_output'}
    assert text == 'Complete direct session.\nAGREE'
    assert retained and all(not path.exists() for path in retained)


def test_exact_session_pending_tools_are_reconciled_in_order(tmp_path):
    import json

    path = tmp_path / 'owned.jsonl'
    events = [
        {'message': {'content': [{'type': 'tool_use', 'id': 'finished'},
                                {'type': 'tool_use', 'id': 'pending'}]}},
        {'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'finished'}]}},
    ]
    path.write_text(''.join(json.dumps(event) + '\n' for event in events))
    assert panel_invoker._claude_pending_tool_uses(path) == ('pending',)
