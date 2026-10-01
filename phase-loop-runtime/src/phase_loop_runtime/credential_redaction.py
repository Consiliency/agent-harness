"""One shared redaction pipeline: credential shapes plus known identity values, span-union.

Every place that removes credential values from text uses `redact_text`, so the same input
gives the same output everywhere. That covers review-leg details, PTY tails, private leg logs,
run-metadata stderr excerpts and hotfix reasons.

The pipeline:
  1. Normalize without destroying separation. Every control character and every character of
     an escape sequence becomes ONE space, so offsets and word breaks survive.
  2. Every detector runs over that same normalized text and reports spans.
  3. Overlapping or adjacent spans merge, and each merged span is replaced ONCE, so a value
     is never half-substituted.
  4. The closeout metadata gate's forbidden shapes run last, over the redacted text.

Every pattern is linear in the input length: quantifiers that follow an alternation are
bounded, and there is no nested optional repetition. Unbounded runs use a single character
class with nothing after it that could force backtracking.
"""
from __future__ import annotations

import os
import re
from collections.abc import Sequence

PLACEHOLDER = "<redacted>"
# An excerpt keeps only a prefix of its input, so the input is capped at this many characters
# before redaction (well beyond any excerpt length, so no value is cut at the excerpt edge).
EXCERPT_INPUT_CAP = 8192
_QUOTED_MAX = 4096

# Names that mark the next value as a credential. Matched with no left word boundary, so glued
# and prefixed names (`dbPassword`, `GITHUB_TOKEN`, `mysecret`) are covered.
_SECRET_WORDS = (
    r"api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"auth[_-]?token|client[_-]?secret|secret[_-]?key|private[_-]?key|access[_-]?key|"
    r"credentials?|signature|passphrase|password|passwd|token|secret"
)
# A value: a double- or single-quoted string (escapes allowed, bounded) that ends the token,
# i.e. is followed by a delimiter or the end of the text; otherwise the whole unquoted run up
# to whitespace (so `"A"B` is redacted whole).
_QUOTED_END = r"(?=[\s,;:)\]}]|$)"
_DQ = r'"(?:[^"\\\n]|\\.){0,' + str(_QUOTED_MAX) + r'}"' + _QUOTED_END
_SQ = r"'(?:[^'\\\n]|\\.){0," + str(_QUOTED_MAX) + r"}'" + _QUOTED_END
_VALUE = _DQ + "|" + _SQ + r"|\S+"

# Shapes whose WHOLE match is the credential.
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # a bearer token, of any 8+ token characters
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    # a token/negotiate scheme and its token: here the token must contain a digit or token
    # punctuation, so ordinary prose after those words ("token validation") is left alone
    re.compile(
        r"(?i)\b(?:token|negotiate)\s+(?=[A-Za-z]{0,64}[0-9._~+/=-])[A-Za-z0-9._~+/=-]{8,}"
    ),
    # prefixed API keys / tokens
    re.compile(
        r"\b(?:sk-(?:ant-)?|sk_live_|sess-|xai-|gh[pousr]_|github_pat_|glpat-|hf_|"
        r"xox[abceoprs]-|AIza|ya29\.|AKIA)[A-Za-z0-9_.-]{8,}"
    ),
    re.compile(r"(?<![\w/])1//[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"),
    # a PEM or PGP private-key block, to its END line (or to the end of the text when cut)
    re.compile(
        r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----.*?"
        r"(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----|\Z)",
        re.S,
    ),
)

# Shapes whose named ``value`` group is the credential, so the key name stays readable. A
# quoted value is narrowed to the inside of its quotes, which keeps structured text valid.
VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # key=value / key: value, quoted or bare key, optional auth-scheme word before the value
    re.compile(
        r"(?i)(?:" + _SECRET_WORDS + r")[\"']?\s*[:=]\s*"
        r"(?:(?:bearer|basic|token|digest|negotiate)\s+)?(?P<value>" + _VALUE + r")"
    ),
    # a command-line flag followed by its value: --api-key VALUE / -token 'VALUE' / --db-password=V
    re.compile(
        r"(?i)(?<![\w-])--?[A-Za-z0-9_-]{0,48}?(?:" + _SECRET_WORDS + r")(?:\s+|=)"
        r"(?![a-z]{1,5}(?:\s|$))(?P<value>(?!-)(?:" + _VALUE + r"))"
    ),
    # URL userinfo: scheme://user:VALUE@host or scheme://VALUE@host (the whole userinfo)
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]{0,31}://(?P<value>[^\s/@:]{1,256}(?::[^\s/@]{0,256})?)@"),
    # Cookie / Set-Cookie: a quoted value (JSON/dict form) or the rest of the header line
    re.compile(
        r"(?i)\b(?:set-)?cookie[\"']?\s*:\s*(?P<value>" + _DQ + "|" + _SQ + r"|[^\r\n]+)"
    ),
)

_SGR_RE = re.compile(r"\x1b\[[0-9;:]*m")
_ESCAPE_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b.")
_CTRL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A known path starts at the text start, after whitespace, a quote, `=`, `:`, `(`, or right
# after a `file://` scheme — never after `~` or `/` (so `~/app` is not re-matched for
# HOME=/app). It ends at a path boundary: anything but a name character, and a `.` only
# when no name character follows it ("… /Users/Jane Doe." ends the path).
_PATH_START = r"(?:(?<=^)|(?<=[\s\"'=:(])|(?<=file://))"
_PATH_END = r"(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9_-])"
_USERNAME_WORD = "A-Za-z0-9_"
PLACEHOLDERS = ("<redacted>", "<user>", "<email>", "<path>", "~")
_PLACEHOLDER_RE = re.compile(r"<redacted>|<user>|<email>|<path>|~")
_PLACEHOLDER_FOR = (
    ("credential", "<redacted>"), ("email", "<email>"), ("path", "<path>"),
    ("home", "~"), ("user", "<user>"),
)


def redaction_identity() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The running user's real home directories and names — the KNOWN values text must not
    carry. Both the environment's view and the password database's, since they can differ
    (a seat's rebuilt environment, a mapped uid)."""
    homes: set[str] = set()
    users: set[str] = set()
    home = os.path.expanduser("~")
    if home and home != "~":
        homes.add(home)
    try:
        import pwd

        entry = pwd.getpwuid(os.getuid())
        homes.add(entry.pw_dir)
        users.add(entry.pw_name)
    except (ImportError, KeyError, AttributeError, OSError):
        pass
    for key in ("USER", "LOGNAME"):
        if os.environ.get(key):
            users.add(os.environ[key])
    return (
        tuple(h.rstrip("/") for h in homes if h and h.rstrip("/") not in ("", "/")),
        tuple(u for u in users if u),
    )


def normalize(text: str) -> str:
    """Colour and attribute sequences (SGR) are removed, so a value wrapped in colour stays one
    token next to its key. Every other escape sequence becomes ONE space, and every other
    control character (newline kept) becomes one space, so `Bearer\\t<tok>` and
    `Bearer\\x1b[1C<tok>` stay two words."""
    text = _SGR_RE.sub("", text or "")
    text = _ESCAPE_RE.sub(" ", text)
    return _CTRL_RE.sub(" ", text)


def _unquote(text: str, start: int, end: int) -> tuple[int, int]:
    if end - start >= 2 and text[start] in "\"'" and text[end - 1] == text[start]:
        return start + 1, end - 1
    return start, end


def credential_spans(text: str) -> list[tuple[int, int]]:
    """Every credential span recognised in ``text``, unmerged, as (start, end)."""
    spans: list[tuple[int, int]] = []
    for pattern in CREDENTIAL_PATTERNS:
        spans += [(m.start(), m.end()) for m in pattern.finditer(text)]
    for pattern in VALUE_PATTERNS:
        spans += [_unquote(text, m.start("value"), m.end("value")) for m in pattern.finditer(text)]
    return [(s, e) for s, e in spans if e > s]


def _spans(
    text: str,
    known: Sequence[str | os.PathLike[str]],
    identity: tuple[tuple[str, ...], tuple[str, ...]],
) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = [(s, e, "credential") for s, e in credential_spans(text)]
    spans += [(m.start(), m.end(), "email") for m in _EMAIL_RE.finditer(text)]
    homes, users = identity
    seat = [str(p).rstrip("/") for p in known if str(p).rstrip("/") not in ("", "/")]
    for value, kind in [(p, "path") for p in seat] + [(h, "home") for h in homes]:
        pattern = re.compile(_PATH_START + re.escape(value) + _PATH_END)
        spans += [(m.start(), m.end(), kind) for m in pattern.finditer(text)]
    for user in users:
        w = _USERNAME_WORD
        pattern = re.compile(rf"(?<![{w}]){re.escape(user)}(?![{w}])")
        spans += [(m.start(), m.end(), "user") for m in pattern.finditer(text)]
    # A match wholly inside a generated placeholder is the placeholder, not a new finding.
    inside = [(m.start(), m.end()) for m in _PLACEHOLDER_RE.finditer(text)]
    return [
        (s, e, k) for s, e, k in spans
        if e > s and not any(ps <= s and e <= pe for ps, pe in inside)
    ]


def redact_text(
    text: str,
    known: Sequence[str | os.PathLike[str]] = (),
    *,
    identity: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
) -> str:
    """Span-union redaction of a WHOLE, UNCUT, multi-line text (line structure kept). Run
    this BEFORE selecting or cutting an excerpt. ``known`` are extra paths to replace, and
    ``identity`` defaults to `redaction_identity()`."""
    from .redaction import _FORBIDDEN_METADATA_PATTERNS

    normalized = normalize(text)
    spans = sorted(_spans(normalized, known, redaction_identity() if identity is None else identity))
    merged: list[list[object]] = []
    for start, end, kind in spans:
        if merged and start <= merged[-1][1]:  # overlapping or adjacent
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].add(kind)
        else:
            merged.append([start, end, {kind}])
    out: list[str] = []
    cursor = 0
    for start, end, kinds in merged:
        placeholder = next(p for k, p in _PLACEHOLDER_FOR if k in kinds)
        out += [normalized[cursor:start], placeholder]
        cursor = end
    redacted = "".join(out) + normalized[cursor:]
    for _name, pattern in _FORBIDDEN_METADATA_PATTERNS:
        redacted = pattern.sub(PLACEHOLDER, redacted)
    return redacted
