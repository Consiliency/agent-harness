from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest

from phase_loop_runtime import seat_jail_qualification as qualification


def _step(exit_code: int | None, stdout: bytes = b"", *, timed_out: bool = False):
    return qualification.JailedStep(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout,
    )


PROXY_REFUSED = _step(56, b"\nPHASE_LOOP_CURL 000 403\n")
FILTER_REFUSED = _step(
    0,
    b"HTTP/1.1 403 Forbidden\r\nX-Proxy-Error: blocked-by-sandbox-runtime\r\n"
    b"\r\n\nPHASE_LOOP_CURL 403 200\n",
)
HANDSHAKE_REFUSED = _step(35, b"\nPHASE_LOOP_CURL 000 200\n")
ORDINARY_REPLY = _step(0, b"HTTP/1.1 200 OK\r\n\r\n\nPHASE_LOOP_CURL 200 200\n")
CERTIFICATE_FAILURE = _step(60, b"\nPHASE_LOOP_CURL 000 200\n")
MALFORMED_RESULT = _step(56, b"HTTP/1.1 403 Forbidden\r\n\r\n")
RESOLVE_REFUSED = _step(6, b"\nPHASE_LOOP_CURL 000 000\n")
CONNECT_REFUSED = _step(7, b"\nPHASE_LOOP_CURL 000 000\n")
TIMED_OUT = _step(None, timed_out=True)

CONFIG_REFUSED = _step(
    0,
    b"rename-refused\nmkdir-refused\nwrite-refused\n"
    b"writable:bin\nwritable:cache\nwritable:log\n",
)
CONFIG_CHANGED = _step(
    0,
    b"RENAMED\nmkdir-refused\nwrite-refused\n"
    b"writable:bin\nwritable:cache\nwritable:log\n",
)


@dataclass(frozen=True)
class RecordedCall:
    argv: tuple[str, ...]
    env: Mapping[str, str]
    use_proxy: bool
    timeout_s: float


class FakeJailedRun:
    def __init__(self, outcomes: Sequence[qualification.JailedStep]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[RecordedCall] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        use_proxy: bool,
        timeout_s: float,
    ) -> qualification.JailedStep:
        self.calls.append(RecordedCall(tuple(argv), env, use_proxy, timeout_s))
        assert self.outcomes, "step made more calls than recorded"
        return self.outcomes.pop(0)


CASES = (
    ("token_post", (PROXY_REFUSED,), "proxy_connect_refused", "positive"),
    ("token_post", (FILTER_REFUSED,), None, "negative"),
    ("token_post", (CERTIFICATE_FAILURE,), None, "ambiguous"),
    ("b_forbidden_hosts", (PROXY_REFUSED,) * 4, "proxy_connect_refused", "positive"),
    ("b_forbidden_hosts", (PROXY_REFUSED,) * 3 + (ORDINARY_REPLY,), None, "negative"),
    ("b_forbidden_hosts", (PROXY_REFUSED,) * 3 + (MALFORMED_RESULT,), None, "ambiguous"),
    ("b_forbidden_paths", (PROXY_REFUSED, FILTER_REFUSED), "request_filter_refused", "positive"),
    ("b_forbidden_paths", (PROXY_REFUSED, ORDINARY_REPLY), None, "negative"),
    ("b_forbidden_paths", (PROXY_REFUSED, CERTIFICATE_FAILURE), None, "ambiguous"),
    ("b_tunnel_inner_host", (FILTER_REFUSED,), "request_filter_refused", "positive"),
    ("b_tunnel_inner_host", (ORDINARY_REPLY,), None, "negative"),
    ("b_tunnel_inner_host", (MALFORMED_RESULT,), None, "ambiguous"),
    ("b_tunnel_inner_sni_and_host", (PROXY_REFUSED,), "proxy_connect_refused", "positive"),
    ("b_tunnel_inner_sni_and_host", (ORDINARY_REPLY,), None, "negative"),
    ("b_tunnel_inner_sni_and_host", (CERTIFICATE_FAILURE,), None, "ambiguous"),
    ("b_tunnel_inner_sni_only", (HANDSHAKE_REFUSED,), "handshake_refused", "positive"),
    ("b_tunnel_inner_sni_only", (ORDINARY_REPLY,), None, "negative"),
    ("b_tunnel_inner_sni_only", (TIMED_OUT,), None, "ambiguous"),
    ("b_fail_closed_front", (_step(0, b"UPSTREAM_BYTES 0 0\n"),),
     "no_upstream_bytes", "positive"),
    ("b_fail_closed_front", (_step(0, b"UPSTREAM_BYTES 0 4\n"),), None, "negative"),
    ("b_fail_closed_front", (TIMED_OUT,), None, "ambiguous"),
    ("b_direct_without_proxy", (CONNECT_REFUSED, RESOLVE_REFUSED), "resolve_refused", "positive"),
    ("b_direct_without_proxy", (CONNECT_REFUSED, ORDINARY_REPLY), None, "negative"),
    ("b_direct_without_proxy", (CONNECT_REFUSED, TIMED_OUT), None, "ambiguous"),
    ("f006_config_ancestor", (CONFIG_REFUSED,), "config_ancestor_read_only", "positive"),
    ("f006_config_ancestor", (CONFIG_CHANGED,), None, "negative"),
    ("f006_config_ancestor", (TIMED_OUT,), None, "ambiguous"),
)


@pytest.mark.parametrize(
    ("name", "outcomes", "expected", "kind"),
    CASES,
    ids=[f"{name}-{kind}" for name, _outcomes, _expected, kind in CASES],
)
def test_bracket_step_uses_only_recorded_refusal_evidence(name, outcomes, expected, kind):
    run = FakeJailedRun(outcomes)

    assert qualification.BRACKET_STEPS[name](run) == expected
    assert not run.outcomes


POSITIVE_OUTCOMES = {
    name: outcomes
    for name, outcomes, _expected, kind in CASES
    if kind == "positive"
}


@pytest.mark.parametrize(
    ("name", "expected_urls", "expected_proxy"),
    (
        ("token_post", ("https://oauth2.googleapis.com/token",), (True,)),
        ("b_forbidden_hosts", (
            "https://storage.googleapis.com/",
            "https://cloudresourcemanager.googleapis.com/",
            "https://compute.googleapis.com/",
            "https://iam.googleapis.com/",
        ), (True,) * 4),
        ("b_forbidden_paths", (
            "https://www.googleapis.com/storage/v1/b",
            "https://www.googleapis.com/compute/v1/projects",
        ), (True, True)),
        ("b_tunnel_inner_host", (
            "https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
        ), (True,)),
        ("b_tunnel_inner_sni_and_host", (
            "https://storage.googleapis.com/v1internal:loadCodeAssist",
        ), (True,)),
        ("b_tunnel_inner_sni_only", (
            "https://storage.googleapis.com/v1internal:loadCodeAssist",
        ), (True,)),
        ("b_fail_closed_front", (), (True,)),
        ("b_direct_without_proxy", (
            "https://1.1.1.1/",
            "https://daily-cloudcode-pa.googleapis.com/",
        ), (False, False)),
        ("f006_config_ancestor", (), (False,)),
    ),
)
def test_bracket_step_invocation_is_fixed(name, expected_urls, expected_proxy):
    run = FakeJailedRun(POSITIVE_OUTCOMES[name])

    qualification.BRACKET_STEPS[name](run)

    assert tuple(call.use_proxy for call in run.calls) == expected_proxy
    assert all(call.env is qualification.BRACKET_STEP_ENV for call in run.calls)
    assert all(call.timeout_s == 60.0 for call in run.calls)
    curl_calls = [call for call in run.calls if call.argv[0] == "/usr/bin/curl"]
    assert tuple(call.argv[-1] for call in curl_calls) == expected_urls
    for call in curl_calls:
        assert call.argv[1] == "-q"
        assert "--proxy" not in call.argv
        assert "--noproxy" not in call.argv
        assert "-x" not in call.argv


def test_bracket_step_table_and_specialized_argv_are_frozen():
    assert tuple(qualification.BRACKET_STEPS) == (
        qualification.TOKEN_POST_STEP,
        *qualification.BRACKET_ROW_NAMES,
    )

    runs = {}
    for name in qualification.BRACKET_STEPS:
        run = FakeJailedRun(POSITIVE_OUTCOMES[name])
        qualification.BRACKET_STEPS[name](run)
        runs[name] = run.calls

    assert runs["token_post"][0].argv[-3:] == (
        "--request", "POST", "https://oauth2.googleapis.com/token")
    assert runs["b_tunnel_inner_host"][0].argv[-5:] == (
        "--request", "POST", "--header", "Host: storage.googleapis.com",
        "https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
    )
    assert runs["b_tunnel_inner_sni_and_host"][0].argv[-5:] == (
        "--request", "POST", "--connect-to",
        "storage.googleapis.com:443:daily-cloudcode-pa.googleapis.com:443",
        "https://storage.googleapis.com/v1internal:loadCodeAssist",
    )
    assert runs["b_tunnel_inner_sni_only"][0].argv[-7:] == (
        "--request", "POST", "--header", "Host: daily-cloudcode-pa.googleapis.com",
        "--connect-to", "storage.googleapis.com:443:daily-cloudcode-pa.googleapis.com:443",
        "https://storage.googleapis.com/v1internal:loadCodeAssist",
    )

    front_argv = runs["b_fail_closed_front"][0].argv
    assert front_argv[:3] == ("/usr/bin/python3", "-I", "-c")
    assert "HTTPS_PROXY" in front_argv[3]
    assert "daily-cloudcode-pa.googleapis.com" in front_argv[3]
    assert "storage.googleapis.com" in front_argv[3]
    assert all("http://" not in arg for arg in front_argv)
    compile(front_argv[3], "<bracket-front>", "exec")

    config_argv = runs["f006_config_ancestor"][0].argv
    assert config_argv[:2] == ("/bin/sh", "-c")
    assert "/seat/home/.gemini" in config_argv[2]
    assert "antigravity-oauth-token" in config_argv[2]
    assert all(name in config_argv[2] for name in ("bin", "cache", "log"))


def test_curl_refusal_requires_matching_exit_and_response_fields():
    assert qualification._curl_refusal(_step(0, PROXY_REFUSED.stdout)) is None
    assert qualification._curl_refusal(_step(56, FILTER_REFUSED.stdout)) is None
    assert qualification._curl_refusal(_step(35, b"\nPHASE_LOOP_CURL 000 000\n")) is None
    assert qualification._curl_refusal(CERTIFICATE_FAILURE) is None


def test_multi_attempt_steps_report_each_supported_refusal_exit():
    path_run = FakeJailedRun((PROXY_REFUSED, PROXY_REFUSED))
    assert qualification.BRACKET_STEPS["b_forbidden_paths"](path_run) == "proxy_connect_refused"

    direct_run = FakeJailedRun((CONNECT_REFUSED, CONNECT_REFUSED))
    assert qualification.BRACKET_STEPS["b_direct_without_proxy"](direct_run) == "connect_refused"


def test_non_curl_steps_require_successful_client_exit():
    front_run = FakeJailedRun((_step(1, b"UPSTREAM_BYTES 0 0\n"),))
    assert qualification.BRACKET_STEPS["b_fail_closed_front"](front_run) is None

    config_run = FakeJailedRun((_step(1, CONFIG_REFUSED.stdout),))
    assert qualification.BRACKET_STEPS["f006_config_ancestor"](config_run) is None
