"""Review-supplied cases: every redaction site removes these credential values.

Each case is a credential the previous implementation removed at one or more sites. Every site
must remove it now, including after a long escape-heavy prefix and in the private leg log's
kept tail.
"""
from types import SimpleNamespace

from phase_loop_runtime import cli, credential_redaction, observability, panel_invoker, runner
from phase_loop_runtime.pipeline_adapter import branch_ops

_LONG_PREFIX = 8192


def test_main_coverage_and_long_inputs_do_not_expose_credentials(tmp_path):
    value = "Plc3sHolder7sValue9s"
    jwt = "eyJabcdefgh.ijklmnop.signature"
    cases = {
        "scheme_word_password": ("password=Basic rejected by service", "Basic"),
        "short_flag_password": ("--password admin", "admin"),
        "quoted_delimiter_tail": (f'password="Qz7m",{value}', value),
        "sgr_scheme_boundary": (f"Bearer\x1b[0m{value}", value),
        "sgr_token_boundary": (f"error\x1b[0msk-{value}", value),
        "dash_before_jwt": (f"-{jwt}", jwt),
        "long_escape_prefix": ("\x1b[0m" * ((_LONG_PREFIX - 8) // 4) + f"sk-{value}", value),
    }
    leaks = []
    for shape, (text, secret) in cases.items():
        metadata = {}
        runner._commit_failure_closeout(metadata, stage="commit", returncode=1, stderr=text)
        outputs = {
            "shared": credential_redaction.redact_text(text),
            "runner": runner._redacted_stderr_excerpt(text),
            "commit_failure": metadata["closeout"]["commit_failure"]["stderr_excerpt"],
            "leg": panel_invoker._redact_leg_text(text),
            "pty": panel_invoker._sanitized_pty_tail(text.encode()),
            "hotfix_cli": cli._redact_hotfix_reason(text),
            "hotfix_observability": observability._redact_hotfix_reason(text),
            "branch_ops": branch_ops._stderr_excerpt(SimpleNamespace(stderr=text, stdout="")),
        }
        ref = panel_invoker._write_private_leg_log(tmp_path, "codex", text)
        assert ref is not None
        outputs["private_log"] = (tmp_path / ref).read_text()
        fragments = {secret[i:i + 4] for i in range(len(secret) - 3)}
        leaks.extend(
            (shape, site, output[-80:])
            for site, output in outputs.items()
            if any(fragment in output for fragment in fragments)
        )
    text = "password=" + " " * (4 * panel_invoker._LEG_LOG_MAX_BYTES) + value
    assert value not in credential_redaction.redact_text(text)
    ref = panel_invoker._write_private_leg_log(tmp_path, "codex", text)
    assert ref is not None
    stored = (tmp_path / ref).read_text()
    if value in stored:
        leaks.append(("long_whitespace", "private_log", stored[-80:]))
    assert not leaks, leaks
