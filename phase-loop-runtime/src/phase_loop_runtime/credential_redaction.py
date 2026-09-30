"""One shared credential redactor: credential-shape spans and their span-union redaction.

Every place that removes credential values from text (review-leg details and PTY tails,
private leg logs, run-metadata stderr excerpts) uses these spans, so a shape recognised in
one place is recognised in all of them.

Redaction is span-based: every detector reports the span of the VALUE it recognises over the
same input, overlapping spans are merged, and each merged span is replaced once. A value is
never half-substituted by a later rewrite of an earlier rewrite's output.
"""
from __future__ import annotations

import re

PLACEHOLDER = "<redacted>"

_SECRET_WORDS = (
    r"api[_-]?key|x-api-key|authorization|proxy-authorization|access[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|auth[_-]?token|client[_-]?secret|token|secret|"
    r"password|passwd"
)

# Credential shapes whose WHOLE match is the credential (values we cannot know in advance).
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # an auth scheme and its token, across whitespace/newlines
    re.compile(r"(?i)\b(?:bearer|basic|token|digest|negotiate)\s+[A-Za-z0-9._~+/=-]{8,}"),
    # prefixed API keys / tokens
    re.compile(
        r"\b(?:sk-(?:ant-)?|sk_live_|sess-|xai-|gh[pousr]_|github_pat_|glpat-|hf_|"
        r"xox[abceoprs]-|AIza|ya29\.|AKIA)[A-Za-z0-9_.-]{8,}"
    ),
    re.compile(r"(?<![\w/])1//[A-Za-z0-9_-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"),
    # a PEM private-key block, to its END line (or to the end of the text when cut off)
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
        re.S,
    ),
)

# Shapes whose named ``value`` group is the credential, so the key name stays readable.
VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # key=value / key: value, quoted keys and values allowed, optional scheme word; the key
    # may carry a name prefix (GITHUB_TOKEN, db-password)
    re.compile(
        r"(?i)[\"']?(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*(?:" + _SECRET_WORDS + r")[\"']?"
        r"\s*[:=]\s*(?P<value>[\"']?(?:(?:bearer|basic|token|digest)\s+)?[^\s\"',;]+[\"']?)"
    ),
    # a command-line flag followed by its value: --api-key VALUE / -token VALUE
    re.compile(
        r"(?i)(?<![\w-])--?(?:" + _SECRET_WORDS + r")(?:\s+|=)(?P<value>(?!-)[^\s\"',;]+)"
    ),
    # URL userinfo: scheme://user:VALUE@host
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:(?P<value>[^\s/@]+)@"),
    # Cookie / Set-Cookie header: the whole header value
    re.compile(r"(?im)\b(?:set-)?cookie\s*:\s*(?P<value>[^\r\n]+)"),
)


def credential_spans(text: str) -> list[tuple[int, int]]:
    """Every credential span recognised in ``text``, unmerged, as (start, end)."""
    spans: list[tuple[int, int]] = []
    for pattern in CREDENTIAL_PATTERNS:
        spans += [(m.start(), m.end()) for m in pattern.finditer(text)]
    for pattern in VALUE_PATTERNS:
        spans += [(m.start("value"), m.end("value")) for m in pattern.finditer(text)]
    return [(s, e) for s, e in spans if e > s]


def redact_credentials(text: str, placeholder: str = PLACEHOLDER) -> str:
    """Replace every merged credential span in ``text`` with ``placeholder``."""
    text = text or ""
    merged: list[list[int]] = []
    for start, end in sorted(credential_spans(text)):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out: list[str] = []
    cursor = 0
    for start, end in merged:
        out += [text[cursor:start], placeholder]
        cursor = end
    return "".join(out) + text[cursor:]
