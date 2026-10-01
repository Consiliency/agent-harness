"""The shared redaction pipeline covers every listed credential shape at every redaction site.

Each shape is filled with synthetic placeholder values of several character classes. A site
passes a case only if NO four-character fragment of the value, as written into the text,
survives in its output. So a redaction that replaces part of a value and leaves the rest counts
as a miss. A second table requires at least as much redaction as the previous single-pattern
stderr excerpt gave. A timing table requires every pattern to stay linear on long adversarial
input.
"""
from __future__ import annotations

import json
import re
import time

import pytest

from phase_loop_runtime import cli, credential_redaction, observability, panel_invoker, redaction, runner

_PEM_LABEL = " ".join(("PRIVATE", "KEY"))
_PGP_LABEL = " ".join(("PGP", "PRIVATE", "KEY", "BLOCK"))

# Synthetic placeholder values, one per character class.
VALUES = {
    "alnum_with_s": "Plc3sHolder7sValue9s",
    "comma": "Qz7m,Xw4Rt9Kp",
    "semicolon": "Ab3d;Ef5g9Hjk",
    "single_quote": "Mn4p'Qr8sT2vw",
    "space": "Vw6x Yz1a3Bcq",
    "backslash": "Kl2m\\No5pQrs",
    "unicode": "Ünï7cödeVal9x",
    "base64": "YWJjZGVm+/Z9Qx==",
    "letters_only": "abcdefghijklmnopqrstuvwx",
}


def _json_str(value: str) -> str:
    return json.dumps(value)[1:-1]


# Each shape: (template, how the value is embedded, which value classes it can carry).
# Embedding: "bare" (as is), "json" (JSON string escaping), "single" (inside '…').
_BARE = {"alnum_with_s", "comma", "semicolon", "single_quote", "backslash", "unicode", "base64"}
_ANY = set(VALUES)
_NO_SQ = _ANY - {"single_quote"}
SHAPES = {
    "key_equals": ("password={v}", "bare", _BARE),
    "key_colon_space": ("password: {v}", "bare", _BARE),
    "glued_camel_key": ("dbPassword={v}", "bare", _BARE),
    "glued_lower_key": ("mysecret={v}", "bare", _BARE),
    "prefixed_env_key": ("GITHUB_TOKEN={v}", "bare", _BARE),
    "access_token_key": ("access_token={v}", "bare", _BARE),
    "client_secret_key": ("client_secret={v}", "bare", _BARE),
    "aws_secret_key": ("AWS_SECRET_ACCESS_KEY={v}", "bare", _BARE),
    "authorization_bearer": ("Authorization: Bearer {v}", "bare", _BARE - {"unicode"}),
    "bearer_letters_only": ("auth Bearer {v}", "bare", {"letters_only"}),
    "json_quoted": ('{{"token": "{v}", "n": 1}}', "json", _ANY),
    "dict_single_quoted": ("{{'password': '{v}'}}", "single", _NO_SQ),
    "flag_space_value": ("--api-key {v}", "bare", _BARE),
    "flag_double_quoted": ('--api-key "{v}"', "json", _ANY),
    "flag_single_quoted": ("--token '{v}'", "single", _NO_SQ),
    "flag_equals_prefixed": ("--db-password={v}", "bare", _BARE),
    "url_userinfo": ("https://user:{v}@example.invalid/path", "bare", {"alnum_with_s", "comma", "semicolon", "unicode"}),
    "url_token_userinfo": ("https://{v}@example.invalid/path", "bare", {"alnum_with_s", "comma", "semicolon", "unicode"}),
    "cookie_header": ("Cookie: session={v}", "bare", _ANY),
    "cookie_json": ('{{"Cookie": "sid={v}"}}', "json", _ANY),
    "x_api_key_header": ("x-api-key: {v}", "bare", _BARE),
    "aws_signature_header": (
        "Authorization: AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20260101/us-east-1/s3/aws4_request, "
        "SignedHeaders=host, Signature={v}", "bare", _BARE,
    ),
    "pem_private_key": (f"-----BEGIN {_PEM_LABEL}-----\n{{v}}\n-----END {_PEM_LABEL}-----", "bare", _ANY),
    "pgp_private_key": (f"-----BEGIN {_PGP_LABEL}-----\n{{v}}\n-----END {_PGP_LABEL}-----", "bare", _ANY),
}


def _embed(value: str, how: str) -> str:
    if how == "json":
        return _json_str(value)
    if how == "single":
        return value.replace("\\", "\\\\")
    return value


def _cases():
    for shape, (template, how, classes) in sorted(SHAPES.items()):
        for cls in sorted(classes):
            yield shape, cls


def _fragments(value: str, width: int = 4) -> set[str]:
    return {value[i:i + width] for i in range(len(value) - width + 1)}


def _surviving(embedded: str, output: str) -> list[str]:
    return sorted(fragment for fragment in _fragments(embedded) if fragment in output)


SITES = {
    "shared": credential_redaction.redact_text,
    "runner_stderr_excerpt": lambda text: runner._redacted_stderr_excerpt(text, max_chars=100_000),
    "leg_text": lambda text: panel_invoker._redact_leg_text(text),
    "pty_tail": lambda text: panel_invoker._sanitized_pty_tail(text.encode(), max_chars=100_000),
    "hotfix_reason_observability": lambda text: observability._redact_hotfix_reason(text)[:200],
    "hotfix_reason_cli": lambda text: cli._redact_hotfix_reason(text),
}


@pytest.mark.parametrize("site", sorted(SITES))
@pytest.mark.parametrize("shape,value_class", list(_cases()))
def test_every_site_removes_every_fragment(site, shape, value_class):
    template, how, _ = SHAPES[shape]
    embedded = _embed(VALUES[value_class], how)
    line = template.format(v=embedded)
    # hotfix reasons keep only 200 characters, so the shape goes first for them
    text = line if site.startswith("hotfix") else f"prefix line\n{line}\nsuffix line"
    output = SITES[site](text)
    assert _surviving(embedded, output) == [], (site, shape, value_class, output)


# The previous stderr excerpt redacted `(api[_-]?key|authorization|token|secret|password)`
# followed by `\s*[:=]\s*\S+`. Every input it fully redacted must still be fully redacted.
_PREVIOUS_EXCERPT_RE = re.compile(r"(?i)(api[_-]?key|authorization|token|secret|password)(\s*[:=]\s*)\S+")
REGRESSION_INPUTS = [
    "dbPassword={v}", "userPassword={v}", "githubToken: {v}", "apiToken={v}", "mysecret={v}",
    "password={v}", "PASSWORD = {v}", "api-key:{v}", "authorization={v}",
]


@pytest.mark.parametrize("template", REGRESSION_INPUTS)
@pytest.mark.parametrize("value_class", sorted(_BARE))
def test_excerpt_redacts_at_least_as_much_as_before(template, value_class):
    value = VALUES[value_class]
    text = template.format(v=value)
    previous = _PREVIOUS_EXCERPT_RE.sub(r"\1\2<redacted>", text)
    now = runner._redacted_stderr_excerpt(text, max_chars=100_000)
    assert len(_surviving(value, now)) <= len(_surviving(value, previous)), (text, previous, now)


ORDINARY_TEXT = [
    "The review found no blocking issues in module alpha.",
    "token validation failed for the request",
    "basic authentication is disabled",
    "digest 3f2a9c1b7e4d5a6f8091",
    "max_tokens: 4096 and token_count=12",
    "the tokens were counted",
]


@pytest.mark.parametrize("site", sorted(SITES))
@pytest.mark.parametrize("text", ORDINARY_TEXT)
def test_ordinary_diagnostics_stay_readable(site, text):
    output = SITES[site](text)
    assert credential_redaction.PLACEHOLDER not in output, (site, text, output)
    assert " ".join(output.split()) == " ".join(text.split()), (site, text, output)


def test_key_names_stay_readable_and_quoted_values_keep_structure():
    output = credential_redaction.redact_text('{"password": "Plc3sHolder7s", "n": 1} --api-key Plc3sHolder7s')
    assert '"password": "<redacted>"' in output and "--api-key <redacted>" in output
    assert json.loads(credential_redaction.redact_text('{"token": "Qz7m,Xw4Rt9Kp", "n": 1}')) == {
        "token": "<redacted>", "n": 1,
    }


def test_every_site_uses_the_one_pipeline():
    assert not hasattr(redaction, "STDERR_SECRET_KV_RE")
    assert not hasattr(runner, "_STDERR_SECRET_KV_RE")
    for name in ("_LEG_DETAIL_CREDENTIAL_RES", "_LEG_DETAIL_KV_RE", "_LEG_DETAIL_EMAIL_RE", "_normalize_leg_text"):
        assert not hasattr(panel_invoker, name), name
    text = "\x1b[31mpassword=Plc3sHolder7s\x1b[0m mail jane@example.invalid"
    outputs = {
        runner._redacted_stderr_excerpt(text, max_chars=100_000),
        " ".join(panel_invoker._redact_leg_text(text).split()),
        " ".join(credential_redaction.redact_text(text).split()),
    }
    assert len(outputs) == 1, outputs


# Long adversarial inputs: every pattern must stay linear.
_TIMING_INPUTS = {
    "underscore_run": "a_" * 32_000,
    "dash_run": "a-" * 32_000,
    "dot_run": "a." * 32_000,
    "scheme_like_run": "a.b-c+" * 11_000,
    "open_quote_after_key": 'password="' + "a" * 64_000,
    "many_keys": "password=" * 7_000,
    "many_flags": "--token " * 8_000,
    "bearer_run": "bearer " * 9_000,
    "at_run": "a@" * 32_000,
    "begin_armour_run": ("-----BEGIN " + _PEM_LABEL + "-----") * 2_000,
    "cookie_run": "cookie:" * 9_000,
}


@pytest.mark.parametrize("name", sorted(_TIMING_INPUTS))
def test_patterns_stay_linear_on_long_adversarial_input(name):
    text = _TIMING_INPUTS[name]
    started = time.perf_counter()
    credential_redaction.redact_text(text, identity=((), ()))
    assert time.perf_counter() - started < 2.0, name
