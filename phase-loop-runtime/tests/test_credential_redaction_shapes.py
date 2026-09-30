"""The shared credential redactor covers every listed credential shape at every redaction site.

Each shape carries a synthetic placeholder value. A site passes a shape only if NO four-character
fragment of that value survives in its output, so a redaction that replaces part of a value and
leaves the rest counts as a miss.
"""
from __future__ import annotations

import pytest

from phase_loop_runtime import credential_redaction, panel_invoker, redaction, runner

# Synthetic placeholder: mixed case, digits and several letter-s characters.
VALUE = "Plc3sHolder7sValue9s"
_PEM_LABEL = " ".join(("PRIVATE", "KEY"))

SHAPES = {
    "key_equals": f"password={VALUE}",
    "key_colon_space": f"password: {VALUE}",
    "authorization_bearer": f"Authorization: Bearer {VALUE}",
    "json_quoted_key": f'{{"token": "{VALUE}"}}',
    "flag_space_value": f"--api-key {VALUE}",
    "env_style_name": f"GITHUB_TOKEN={VALUE}",
    "access_token_key": f"access_token={VALUE}",
    "client_secret_key": f"client_secret={VALUE}",
    "url_userinfo": f"https://user:{VALUE}@example.invalid/path",
    "cookie_header": f"Cookie: session={VALUE}",
    "x_api_key_header": f"x-api-key: {VALUE}",
    # The PEM armour is assembled here so the literal header never appears in the source.
    "pem_private_key": f"-----BEGIN {_PEM_LABEL}-----\n{VALUE}\n-----END {_PEM_LABEL}-----",
}


def _fragments(value: str, width: int = 4) -> set[str]:
    return {value[i:i + width] for i in range(len(value) - width + 1)}


def _surviving(output: str) -> list[str]:
    return sorted(fragment for fragment in _fragments(VALUE) if fragment in output)


SITES = {
    "shared": credential_redaction.redact_credentials,
    "runner_stderr_excerpt": lambda text: runner._redacted_stderr_excerpt(text, max_chars=10_000),
    "leg_text": lambda text: panel_invoker._redact_leg_text(text),
    "pty_tail": lambda text: panel_invoker._sanitized_pty_tail(text.encode(), max_chars=10_000),
}


@pytest.mark.parametrize("site", sorted(SITES))
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_site_removes_every_fragment_of_every_shape(site, shape):
    text = f"prefix line\n{SHAPES[shape]}\nsuffix line"
    output = SITES[site](text)
    assert _surviving(output) == [], (site, shape, output)


@pytest.mark.parametrize("site", sorted(SITES))
def test_ordinary_text_is_left_readable(site):
    text = "The review found no blocking issues in module alpha."
    output = SITES[site](text)
    assert "review found no blocking issues" in output


def test_key_names_stay_readable_for_value_shapes():
    output = credential_redaction.redact_credentials(f"password={VALUE} and --api-key {VALUE}")
    assert "password=" in output and "--api-key" in output
    assert output.count(credential_redaction.PLACEHOLDER) == 2


def test_redaction_sites_share_one_implementation():
    # No site keeps its own credential patterns: the shapes live in one module.
    assert not hasattr(redaction, "STDERR_SECRET_KV_RE")
    assert not hasattr(runner, "_STDERR_SECRET_KV_RE")
    assert not hasattr(panel_invoker, "_LEG_DETAIL_CREDENTIAL_RES")
    assert not hasattr(panel_invoker, "_LEG_DETAIL_KV_RE")
