from contextlib import contextmanager
import json
import subprocess
import sys

import pytest

from phase_loop_runtime import panel_invoker as pi

@pytest.mark.parametrize("shape", ["replaced-directory", "symlinked-directory"])
def test_collection_requires_original_project_directory(tmp_path, shape):
    project = tmp_path / "expected-project"
    project.mkdir()
    journal = project / "session.jsonl"
    collected = tmp_path / "collected.jsonl"
    collected.touch()
    record = {"type": "assistant", "message": {"id": "answer", "role": "assistant",
              "content": [{"type": "text", "text": "REVIEW END\nAGREE"}],
              "stop_reason": "end_turn"}}
    source = (
        "import pathlib\n"
        f"project=pathlib.Path({str(project)!r})\n"
        "project.rename(project.with_name('old-project'))\n"
        + ("project.mkdir()\n" if shape == "replaced-directory" else
           "target=project.with_name('other-project')\n"
           "target.mkdir()\n"
           "project.symlink_to(target,target_is_directory=True)\n") +
        f"(project/'session.jsonl').write_text({(json.dumps(record) + chr(10))!r})\n"
    )
    command = pi._claude_journal_collector_command(
        [sys.executable, "-I", "-S", "-c", source],
        expected_journal=str(journal), output=collected,
    )
    result = subprocess.run(command, cwd=tmp_path, timeout=5)
    assert result.returncode != 0, "collector accepted a replaced project directory"
    assert collected.read_bytes() == b""


@pytest.mark.parametrize("shape", ["new-turn", "max-token-continuation"])
def test_collection_requires_single_complete_turn(tmp_path, shape):
    project = tmp_path / "project"
    project.mkdir()
    journal = project / "session.jsonl"
    collected = tmp_path / "collected.jsonl"
    collected.touch()
    first_user = {"type": "user", "uuid": "u1",
                  "message": {"role": "user", "content": "Review the supplied change."}}
    first_answer = {"type": "assistant", "uuid": "a1", "message": {
        "id": "m1", "role": "assistant", "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "First answer."}]}}
    second_user = {"type": "user", "uuid": "u2",
                   "message": {"role": "user", "content": "A different request."}}
    if shape == "max-token-continuation":
        first_answer["message"]["stop_reason"] = "max_tokens"
        second_user["isMeta"] = True
        second_user["message"]["content"] = pi._CLAUDE_RESUME_PROMPT
    last_answer = {"type": "assistant", "uuid": "a2", "message": {
        "id": "m2", "role": "assistant", "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "REVIEW END\nAGREE"}]}}
    data = "".join(json.dumps(r) + "\n" for r in
                   (first_user, first_answer, second_user, last_answer))
    source = f"from pathlib import Path; Path({str(journal)!r}).write_text({data!r})"
    command = pi._claude_journal_collector_command(
        [sys.executable, "-I", "-S", "-c", source],
        expected_journal=str(journal), output=collected,
    )
    result = subprocess.run(command, cwd=tmp_path, timeout=5)
    final = pi._final_assistant_text_from_jsonl(collected, require_terminal=True)
    assert result.returncode != 0 or not final, (shape, result.returncode, final)




@pytest.mark.parametrize("pathway", ["running-broker", "refused-canonical"])
def test_completion_requires_final_collection(tmp_path, monkeypatch, pathway):
    project = tmp_path / "private-project"
    project.mkdir()
    journal = project / "session.jsonl"
    collected = tmp_path / "collected.jsonl"
    collected.touch()
    answer = tmp_path / "answer.txt"
    record = {"type": "assistant", "message": {"id": "answer", "role": "assistant",
              "content": [{"type": "text", "text": "REVIEW END\nAGREE"}],
              "stop_reason": "end_turn"}}
    source = (
        "import os,pathlib,time,tty\n"
        "tty.setraw(0)\n"
        "print('Claude Code ready for your message',flush=True)\n"
        "wire=b''\n"
        "while not wire.endswith(b'\\x1bOM'): wire+=os.read(0,65536)\n"
        f"pathlib.Path({str(journal)!r}).write_text({(json.dumps(record) + chr(10))!r})\n"
        + ("time.sleep(2)\n" if pathway == "running-broker" else
           f"pathlib.Path({str(answer)!r}).write_text('REVIEW END\\nAGREE\\n')\n") +
        f"pathlib.Path({str(project / 'unexpected.jsonl')!r}).write_text('{{}}\\n')\n"
    )

    @contextmanager
    def profile(command, **kwargs):
        yield pi._claude_journal_collector_command(
            command, expected_journal=str(journal), output=collected,
        ), pi.SeatProfile(env={"PATH": "/usr/bin:/bin"})

    # Exercise the real collector and TUI; replace only the unavailable namespace transport.
    def transport(command, *, profile, **kwargs):
        return subprocess.Popen(command, cwd=kwargs["cwd"], env=dict(profile.env),
                                stdin=profile.terminal_fd, stdout=profile.terminal_fd,
                                stderr=profile.terminal_fd, start_new_session=True)

    monkeypatch.setattr(pi, "_seat_command_profile", profile)
    monkeypatch.setattr(pi, "launch_owned", transport)
    for name in ("_CLAUDE_TUI_SUBMIT_DELAY_S", "_CLAUDE_TUI_READY_QUIESCENCE_S",
                 "_CLAUDE_TUI_TRANSCRIPT_INTERVAL_S", "_CLAUDE_TUI_READ_INTERVAL_S"):
        monkeypatch.setattr(pi, name, 0.01)
    rc, text, detail, _ = pi._run_claude_tui_session(
        command=[sys.executable, "-I", "-S", "-c", source], cwd=tmp_path,
        prompt="synthetic review", output_file=answer,
        timeout_s=5, backstop_s=5, env={"PATH": "/usr/bin:/bin"},
        allow_transcript_final=True, broker_transcript_path=collected,
    )
    assert rc != 0, (rc, text, detail)
    assert text == ""


@pytest.mark.parametrize("shape", ["complete", "symlink", "hardlink", "directory", "replaced", "alias", "sibling"])
def test_host_collection_checks_original_handles_after_provider_exit(tmp_path, shape):
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "output.jsonl"
    output.touch()
    record = {"type": "assistant", "uuid": "final", "message": {
        "id": "final", "role": "assistant", "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "REVIEW END\nAGREE"}]}}
    data = json.dumps(record) + "\n"
    script = (
        "import os,pathlib\n"
        f"project=pathlib.Path({str(project)!r})\n"
        f"data={data!r}\n"
        "journal=project/'session.jsonl'\n"
    )
    if shape == "symlink":
        script += f"target=pathlib.Path({str(tmp_path / 'other.jsonl')!r})\ntarget.write_text(data)\njournal.symlink_to(target)\n"
    elif shape == "hardlink":
        script += f"journal.write_text(data)\nos.link(journal,{str(tmp_path / 'other.jsonl')!r})\n"
    elif shape == "directory":
        script += "journal.mkdir()\n"
    elif shape == "replaced":
        script += "project.rename(project.with_name('original'))\nproject.mkdir()\njournal.write_text(data)\n"
    elif shape == "alias":
        script += "original=project.with_name('original')\nproject.rename(original)\nproject.symlink_to(original,target_is_directory=True)\njournal.write_text(data)\n"
    else:
        script += "journal.write_text(data)\n"
        if shape == "sibling":
            script += "(project/'extra.jsonl').write_text('{}\\n')\n"
    journal = pi._SeatClaudeJournal()
    try:
        command = pi._claude_journal_collector_command(
            [sys.executable, "-I", "-S", "-c", script],
            expected_journal=str(project / "session.jsonl"), output=output,
            export_fd=journal.writer.fileno(),
        )
        result = subprocess.run(command, pass_fds=(journal.writer.fileno(),), timeout=5)
        assert result.returncode == 0
        assert output.read_bytes() == b""
        if shape == "complete":
            collected = journal.read()
            assert all(not pi.os.get_inheritable(fd) for fd in journal.handles)
            assert collected == data.encode()
            assert pi._validated_claude_journal(collected) == "REVIEW END\nAGREE"
        else:
            with pytest.raises((OSError, pi.AgyCanaryEvidenceError)):
                journal.read()
    finally:
        journal.close()
    assert not journal.handles


@pytest.mark.parametrize("stop_reason", [None, "max_tokens", "tool_use"])
def test_host_collection_requires_terminal_final_message(stop_reason):
    record = {"type": "assistant", "message": {
        "role": "assistant", "stop_reason": stop_reason,
        "content": [{"type": "text", "text": "REVIEW END\nAGREE"}]}}
    assert pi._validated_claude_journal((json.dumps(record) + "\n").encode()) == ""


def test_host_collection_accepts_completed_tool_cycle():
    records = [
        {"type": "user", "uuid": "request", "message": {"role": "user", "content": "Review input."}},
        {"type": "assistant", "uuid": "call", "message": {"id": "tool", "role": "assistant",
            "stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "read", "name": "Read", "input": {}}]}},
        {"type": "user", "uuid": "result", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "read", "content": "Source inspected."}]}},
        {"type": "assistant", "uuid": "final", "message": {"id": "answer", "role": "assistant",
            "stop_reason": "end_turn", "content": [{"type": "text", "text": "REVIEW END\nAGREE"}]}},
    ]
    data = "".join(json.dumps(record) + "\n" for record in records).encode()
    assert pi._validated_claude_journal(data) == "REVIEW END\nAGREE"
    assert pi._validated_claude_journal(data.replace(b'"tool_use_id": "read"', b'"tool_use_id": "other"')) == ""
    assert pi._validated_claude_journal("".join(json.dumps(record) + "\n" for record in
                                      (records[0], records[1], records[3])).encode()) == ""


def test_canonical_file_waits_for_final_journal(tmp_path, monkeypatch):
    from phase_loop_runtime import sandbox_egress

    for name in ("_CLAUDE_TUI_SUBMIT_DELAY_S", "_CLAUDE_TUI_READY_QUIESCENCE_S",
                 "_CLAUDE_TUI_TRANSCRIPT_INTERVAL_S", "_CLAUDE_TUI_READ_INTERVAL_S"):
        monkeypatch.setattr(pi, name, 0.01)
    output = tmp_path / "answer.txt"
    event = {"type": "assistant", "message": {"role": "assistant", "id": "final",
             "content": [{"type": "text", "text": "Completed output.\nAGREE"}], "stop_reason": "end_turn"}}
    source = (
        "import json,os,pathlib,re,sys,time,tty\n"
        "tty.setraw(0)\nprint('Claude Code ready for your message',flush=True)\n"
        "wire=b''\nwhile not wire.endswith(b'\\x1bOM'): wire+=os.read(0,65536)\n"
        f"pathlib.Path({str(output)!r}).write_text('Completed output.\\nAGREE\\n')\n"
        "time.sleep(.4)\n"
        "project=pathlib.Path(os.environ['CLAUDE_CONFIG_DIR'])/'projects'/re.sub(r'[^A-Za-z0-9.-]','-',os.getcwd())\n"
        "session=sys.argv[sys.argv.index('--session-id')+1]\n"
        f"(project/(session+'.jsonl')).write_text({(json.dumps(event) + chr(10))!r})\n"
    )
    with sandbox_egress.isolated_network(required=True, timeout_s=None) as prefix:
        token = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
        try:
            result = pi._run_claude_tui_session(
                command=["/usr/bin/python3", "-I", "-S", "-c", source], cwd=tmp_path,
                prompt="Fixture output ordering.", output_file=output,
                env={"PATH": "/usr/bin:/bin"}, timeout_s=5, backstop_s=5,
                broker_transcript_path=tmp_path / "collected.jsonl",
            )
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)
    assert result[:3] == (0, "Completed output.\nAGREE", "claude_tui_file_output")
    assert json.loads((tmp_path / "collected.jsonl").read_text()) == event
