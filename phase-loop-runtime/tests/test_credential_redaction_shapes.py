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
import random
import re
import time

import pytest

from phase_loop_runtime import cli, credential_redaction, observability, panel_invoker, redaction, runner
from phase_loop_runtime.pipeline_adapter import branch_ops

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
    "key_split_by_colour": ("pass\x1b[1mword={v}", "bare", _BARE),
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
    "branch_ops_git_excerpt": lambda text: branch_ops._stderr_excerpt(
        type("Result", (), {"stderr": text, "stdout": ""})()),
}


@pytest.mark.parametrize("site", sorted(SITES))
@pytest.mark.parametrize("shape,value_class", list(_cases()))
def test_every_site_removes_every_fragment(site, shape, value_class):
    template, how, _ = SHAPES[shape]
    embedded = _embed(VALUES[value_class], how)
    line = template.format(v=embedded)
    # hotfix reasons keep only 200 characters, so the shape goes first for them
    short = site.startswith(("hotfix", "branch_ops"))
    text = line if short else f"prefix line\n{line}\nsuffix line"
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
    # A scheme word (bearer/basic/token/digest/negotiate) followed by 8+ token characters is
    # redacted as it was before, even in prose: parity with main takes precedence.
    "max_tokens: 4096 and token_count=12",
    "the tokens were counted",
]


@pytest.mark.parametrize("site", sorted(SITES))
@pytest.mark.parametrize("text", ORDINARY_TEXT)
def test_ordinary_diagnostics_stay_readable(site, text):
    output = SITES[site](text)
    assert credential_redaction.PLACEHOLDER not in output, (site, text, output)
    assert " ".join(output.split()) == " ".join(text.split()), (site, text, output)


def test_flag_names_stay_readable():
    # The value span starts after the flag name. (A key=value pair can also be matched whole by
    # the closeout gate's forbidden shapes, which run over the previous redaction's output and
    # over this one's, so key names there are not guaranteed to survive.)
    output = credential_redaction.redact_text("--api-key Plc3s")
    assert output == "--api-key <redacted>", output


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
    "jwt_prefix_run": "eyJ-" * 64_000,
    "wide_separator_run": "password" + " " * 64_000,
}


@pytest.mark.parametrize("name", sorted(_TIMING_INPUTS))
def test_patterns_stay_linear_on_long_adversarial_input(name):
    text = _TIMING_INPUTS[name]
    started = time.perf_counter()
    credential_redaction.redact_text(text, identity=((), ()))
    assert time.perf_counter() - started < 2.0, name


# Parity with main, end to end per site. Each site's main-era function (a frozen copy in
# `_redaction_main_reference`) and its current function run on the same raw input, including the
# input cap and the cut, and the current output must keep no value fragment that main's output
# had removed.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _redaction_main_reference as _main  # noqa: E402

_KEYS = ["password", "passwd", "token", "api_key", "api-key", "apiKey", "secret", "authorization",
         "dbPassword", "GITHUB_TOKEN", "access_token", "client_secret", "mysecret"]
_KEY_QUOTES = ["", '"', "'"]
# Escaped separators (`\=`, `\":`) are what the closeout gate's forbidden key=value shape
# tolerates and the other detectors do not.
_SEPARATORS = [":", "=", "\\=", '\\"=', "\\':", '"\\:']
_SPACES = ["", " ", "\t", " " * 17, "\t" * 20, " " * 40]
_TRUECOLOR = "\x1b[38;2;255;100;0m"
_WRAPS = ["plain", "truecolor", "bold_truecolor", "dq_then_tail", "sq_then_tail", "colour_inside"]
_TAILS = ["", " next", ",x", ";", " and more"]
# Synthetic; assembled so the literal does not read as a stored credential.
_SECRET = "".join(("Qz7mXw4R", "t9Kp2Lv8", "Hn3c"))


# "" and "_" glue a key onto the previous value (`token\=long_password\=…`).
_JOINS = [",", ";", " ", ", ", " & ", "|", "\n", ",\t", "", "_"]


def _one_pair(rng):
    value = VALUES[rng.choice(sorted(_BARE - {"single_quote"}))]
    key, quote = rng.choice(_KEYS), rng.choice(_KEY_QUOTES)
    wrap = rng.choice(_WRAPS)
    half = len(value) // 2
    shown = {
        "plain": value,
        "truecolor": f"{_TRUECOLOR}{value}\x1b[0m",
        "bold_truecolor": f"\x1b[1m{_TRUECOLOR}{value}\x1b[0m",
        "dq_then_tail": f'"{value[:half]}"{value[half:]}',
        "sq_then_tail": f"'{value[:half]}'{value[half:]}",
        "colour_inside": f"{value[:half]}\x1b[0m{value[half:]}",
    }[wrap]
    text = (f"{quote}{key}{quote}{rng.choice(_SPACES)}{rng.choice(_SEPARATORS)}"
            f"{rng.choice(_SPACES)}{shown}")
    return text, value


# Text glued in front of the first key: a scheme word whose token swallows that key, or a
# private path the previous final pass ran on from.
_LEADS = ["", "", "Bearer ABCD", "token ABCD", "open /home/u/", "x"]


def _generated_cases(count: int = 1500, seed: int = 20261001):
    """1 to 3 key/value pairs per line, joined by random punctuation, so a value grammar that
    runs over a following key is caught."""
    rng = random.Random(seed)
    for _ in range(count):
        pairs = [_one_pair(rng) for _ in range(rng.randint(1, 3))]
        text = rng.choice(_LEADS) + "".join(
            (rng.choice(_JOINS) if i else "") + pair_text for i, (pair_text, _) in enumerate(pairs)
        ) + rng.choice(_TAILS)
        yield text, tuple(value for _, value in pairs)


# Fixed cases from review probes: scheme words, escape codes next to scheme words, quoting
# edges, and inputs that are long or escape-heavy so a cap or a pre-cut would matter.
_FIXED_CASES = [
    (f"Bearer\x1b[1m{_SECRET}\x1b[0m", _SECRET),
    (f"Authorization: Bearer\x1b[1m{_SECRET}", _SECRET),
    (f"token\x1b[1m{_SECRET}", _SECRET),
    ("Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
    ('{"auth": "Basic dXNlcjpwYXNzd29yZA=="}', "dXNlcjpwYXNzd29yZA"),
    ('AUTH_HEADER="Basic dXNlcjpwYXNzd29yZA=="', "dXNlcjpwYXNzd29yZA"),
    (f"Digest {_SECRET}", _SECRET),
    ("token AbCdEfGhIjKlMnOp", "AbCdEfGhIjKlMnOp"),
    (f'password: "{_SECRET[:8]} {_SECRET[8:]}".', _SECRET[8:]),
    (f'<input password="{_SECRET[:8]} {_SECRET[8:]}">', _SECRET[8:]),
    (f"password={_SECRET[:10]}\x1b[1C{_SECRET[10:]}", _SECRET),
    (f"password=\x1b]0;title\x07{_SECRET}", _SECRET),
    (f"password:{_TRUECOLOR}{' ' * 30}{_SECRET[:7]},{_SECRET[7:]}\x1b[0m", _SECRET),
    ("password=" + "\x1b[1m" * 70_000 + _SECRET, _SECRET),
    ("password=" + " " * 9_000 + _SECRET, _SECRET),
    ("x" * 300_000 + " password=" + _SECRET, _SECRET),
    ("password=Basic rejected by service", "rejected"),
    (f'password="Qz7m",{_SECRET}', _SECRET),
    (f"error\x1b[0msk-{_SECRET}", _SECRET),
    ("-eyJabcdefgh.ijklmnop.signature", "eyJabcdefgh.ijklmnop.signature"),
    ('{"token":"abc","password": "Pl4c3!h0ld"}', "Pl4c3!h0ld"),
    ("token=abc,password = Pl4c3!h0ld", "Pl4c3!h0ld"),
    ("{token: abc,password: Pl4c3!h0ld}", "Pl4c3!h0ld"),
    ("TOKEN=abc;PASSWORD: Pl4c3!h0ld", "Pl4c3!h0ld"),
    ("credentials:aws_secret : Pl4c3!h0ld", "Pl4c3!h0ld"),
    ("x (token'::Token =Pl4c3!h0ld,x", "Pl4c3!h0ld"),
    ('password=" ' + VALUES["alnum_with_s"], VALUES["alnum_with_s"]),
    ("password=' " + VALUES["alnum_with_s"], VALUES["alnum_with_s"]),
    ('password=" \n' + VALUES["alnum_with_s"] + '"', VALUES["alnum_with_s"]),
    ('password=" ' + VALUES["alnum_with_s"] + "a" * 4096 + '"', VALUES["alnum_with_s"]),
    ("x-" + ".".join(("eyJ" + "SyntheticHdr0", "eyJ" + "SyntheticBody1", "SyntheticSig2")), "SyntheticSig2"),
    # A shape the previous redaction caught only in its final forbidden-shape pass, after its
    # own replacements: the earlier key must not be merged away before that pass sees it.
    ("Bearer ABCDtoken\\=long_password\\=" + VALUES["alnum_with_s"], VALUES["alnum_with_s"]),
    ('Bearer ABCDtoken\\"=long_password\\"=' + VALUES["alnum_with_s"], VALUES["alnum_with_s"]),
    ("Bearer ABCDtoken\\=long_password\\=" + _SECRET + " eyJ" + "SyntheticHdr0.SyntheticBody1", _SECRET),
    # The previous final pass's private-path shape ran on across a placeholder to the next space.
    ("open /home/u/Bearer abcdefgh123:" + _SECRET, _SECRET),
    ("credentials:/home/u/Bearer abcdefgh123:" + _SECRET, _SECRET),
]


def _site_pairs(tmp_path):
    def head_log(text):
        ref = panel_invoker._write_private_leg_log(tmp_path, "codex", text)
        return (tmp_path / ref).read_text()

    return {
        "shared": (credential_redaction.redact_text, _main._redact_leg_text),
        "runner_stderr_excerpt": (runner._redacted_stderr_excerpt, _main._redacted_stderr_excerpt),
        "leg_text": (panel_invoker._redact_leg_text, _main._redact_leg_text),
        "pty_tail": (lambda t: panel_invoker._sanitized_pty_tail(t.encode()),
                     lambda t: _main._sanitized_pty_tail(t.encode())),
        "private_leg_log": (head_log, _main._private_leg_log_payload),
        "hotfix_reason_observability": (observability._redact_hotfix_reason, _main._hotfix_reason),
        "hotfix_reason_cli": (cli._redact_hotfix_reason, _main._hotfix_reason),
        "branch_ops_git_excerpt": (
            lambda t: branch_ops._stderr_excerpt(type("Result", (), {"stderr": t, "stdout": ""})()),
            _main._branch_ops_excerpt),
    }


@pytest.fixture
def no_identity(monkeypatch):
    monkeypatch.setattr(credential_redaction, "redaction_identity", lambda: ((), ()))
    monkeypatch.setattr(panel_invoker, "_redaction_identity", lambda: ((), ()))


def _parity_failures(pairs, cases):
    failures = []
    for text, values in cases:
        values = (values,) if isinstance(values, str) else values
        for site, (head_fn, main_fn) in pairs.items():
            head_out, main_out = head_fn(text), main_fn(text)
            for value in values:
                kept_by_head = set(_surviving(value, head_out))
                removed_by_main = _fragments(value) - set(_surviving(value, main_out))
                regressed = sorted(kept_by_head & removed_by_main)
                if regressed:
                    failures.append((site, text[:80], regressed[:3]))
    return failures


def test_parity_with_main_on_fixed_cases(tmp_path, no_identity):
    assert _parity_failures(_site_pairs(tmp_path), _FIXED_CASES) == []


def test_parity_with_main_on_generated_cases(tmp_path, no_identity):
    pairs = _site_pairs(tmp_path)
    assert _parity_failures(pairs, list(_generated_cases())) == []


def test_parity_with_main_on_the_shape_table(tmp_path, no_identity):
    cases = []
    for shape, (template, how, classes) in SHAPES.items():
        for cls in classes:
            embedded = _embed(VALUES[cls], how)
            cases.append((template.format(v=embedded), embedded))
    assert _parity_failures(_site_pairs(tmp_path), cases) == []


@pytest.mark.parametrize("site", ["runner_stderr_excerpt", "hotfix_reason_observability",
                                  "hotfix_reason_cli", "branch_ops_git_excerpt"])
@pytest.mark.parametrize("offset", [510, 8_182, 70_000])
def test_redaction_runs_before_any_cut(site, offset):
    # Whitespace collapses in the excerpt, so a token far into the input can still reach the
    # output. Redaction must see the whole input, not a prefix that cuts the token short.
    token = "ghp_" + "Rt9Kp2Lv8Hn3cQz7m"
    text = " " * offset + token + " tail"
    output = SITES[site](text)
    assert _surviving(token[4:], output) == [], (site, offset, output[:80])



@pytest.mark.parametrize("site", sorted(SITES))
def test_placeholder_rich_input_stays_linear(site):
    # e-mail addresses and "~" both produce placeholders; the containment check must not be
    # quadratic in their number
    text = "a@b.co ~ " * (131_072 // 9)
    started = time.perf_counter()
    SITES[site](text)
    assert time.perf_counter() - started < 2.0, site


def test_placeholder_rich_stderr_excerpt_finishes_promptly():
    import subprocess
    import sys as _system

    script = ("from phase_loop_runtime.runner import _redacted_stderr_excerpt; "
              "_redacted_stderr_excerpt('password=x <redacted> ' * 50000)")
    result = subprocess.run([_system.executable, "-c", script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("text", [
    "Bearer ABCDtoken\\=long_password\\=" + VALUES["alnum_with_s"],
    'Bearer ABCDtoken\\"=long_password\\"=' + VALUES["alnum_with_s"],
])
def test_previous_final_pass_matches_are_kept(tmp_path, no_identity, text):
    secret = VALUES["alnum_with_s"]
    assert secret not in _main._redact_leg_text(text)
    assert secret not in _main._sanitized_pty_tail(text.encode())
    assert secret not in _main._private_leg_log_payload(text)
    ref = panel_invoker._write_private_leg_log(tmp_path, "codex", text)
    outputs = {
        "shared": credential_redaction.redact_text(text),
        "leg": panel_invoker._redact_leg_text(text),
        "pty": panel_invoker._sanitized_pty_tail(text.encode()),
        "private_log": (tmp_path / ref).read_text(),
    }
    assert [site for site, output in outputs.items() if secret in output] == [], outputs


# The previous leg-detail redaction is replayed exactly: its output, built by the replay, equals
# the frozen main-era function's output. The guarantee that head never keeps what main removed
# rests on this equality.
_ADVERSARIAL_CASES = [
    "process.env[" * 40,
    "PROCESS.ENV[a] =x process.env[b]= process.env[] = process.env[[c]]=",
    "process.env[a] = process.env[b]\n= local env value .ENV.LOCAL VALUE .env value",
    "éeyJabcdefghij.klmnopqrst.uv x-eyJabcdefghij.klmnopqrst. _eyJabcdefghij.klmnopqrst",
    "eyJaaaaaaaaa.bbbbbbbbb.eyJcccccccc.ddddtoken=" + _SECRET,
    "eyJaaaaaaaaa.eyJbbbbbbbbb.eyJcccccccc.eyJdddddddd.eyJeeeeeeee",
    "a@b.co ~ <redacted> <user> jane@example.invalid token: <email>",
    "diff --git a/x b/x @@ -1,2 +3,4 @@ raw transcript /home/someone/x private key",
    "api_key\\\\\\\" :  \\'" + _SECRET + " secret=short token=" + _SECRET,
]


def _replayed_previous_output(text: str) -> str:
    normalized = credential_redaction.normalize(text)
    spans = credential_redaction._previous_leg_spans(normalized, (), ((), ()))
    return credential_redaction._previous_leg_redaction(normalized, spans)[0]


def test_replay_of_the_previous_redaction_is_exact():
    cases = [text for text, _ in _FIXED_CASES] + [text for text, _ in _generated_cases()]
    cases += [template.format(v=_embed(VALUES[cls], how))
              for template, how, classes in SHAPES.values() for cls in sorted(classes)]
    cases += _ADVERSARIAL_CASES
    different = [text[:80] for text in cases if _replayed_previous_output(text) != _main._redact_leg_text(text)]
    assert different == []


def _random_text(rng, alphabet, size):
    return "".join(rng.choice(alphabet) for _ in range(size))


def test_linear_matchers_return_the_regex_matches():
    local_env = dict(redaction._FORBIDDEN_METADATA_PATTERNS)["local_env_value"]
    jwt = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?")
    rng = random.Random(20261002)
    env_parts = ["process.env[", "PROCESS.ENV[", "]", "=", " ", " ", "\n", "a", "[",
                 ".env value", ".env.local value", "local env value", "x"]
    jwt_parts = ["eyJ", "abcdefgh", "a", ".", "-", "_", "é", " ", "x"]
    env_cases = [_random_text(rng, env_parts, rng.randint(1, 30)) for _ in range(3000)] + _ADVERSARIAL_CASES
    jwt_cases = [_random_text(rng, jwt_parts, rng.randint(1, 30)) for _ in range(3000)] + _ADVERSARIAL_CASES
    for text in env_cases:
        expected = [(m.start(), m.end()) for m in local_env.finditer(text)]
        assert credential_redaction._local_env_matches(text) == expected, text
    for text in jwt_cases:
        expected = [(m.start(), m.end()) for m in jwt.finditer(text)]
        assert credential_redaction._jwt_spans(text, overlapping=False) == expected, text


def test_local_env_prefixes_redact_promptly():
    import subprocess
    import sys as _system

    script = ("from phase_loop_runtime.runner import _redacted_stderr_excerpt; "
              "_redacted_stderr_excerpt('process.env[' * 50000)")
    result = subprocess.run([_system.executable, "-c", script], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("unit", ["process.env[", "process.env[a] ", "eyJ-", "token\\=long_"])
def test_runner_stderr_excerpt_time_grows_linearly(unit):
    def seconds(count):
        text = unit * count
        started = time.perf_counter()
        runner._redacted_stderr_excerpt(text)
        return time.perf_counter() - started

    small, large = seconds(16_000), seconds(64_000)
    # four times the input: linear work takes about four times as long, quadratic about sixteen
    assert large < max(10 * small, 0.5), (unit, small, large)
