"""One shared redaction pipeline: credential shapes plus known identity values, span-union.

Every place that removes credential values from text uses `redact_text`, so the same input
gives the same output everywhere. That covers review-leg details, PTY tails, private leg logs,
run-metadata stderr excerpts and hotfix reasons.

The pipeline:
  1. Normalize without destroying separation. Every control character and every character of
     an escape sequence becomes ONE space, so offsets and word breaks survive.
  2. Every detector runs over that normalized text and reports spans. Credential shapes also
     run over the raw text with colour codes removed, and a span found in either view is
     redacted, so normalization can only add coverage.
  3. Overlapping or adjacent spans merge, and each merged span is replaced ONCE, so a value
     is never half-substituted.
  4. The closeout metadata gate's forbidden shapes run last, over the redacted text.

Every pattern is linear in the input length: quantifiers that follow an alternation are
bounded, and there is no nested optional repetition. Unbounded runs use a single character
class with nothing after it that could force backtracking.
"""
from __future__ import annotations

import bisect
import os
import re
from collections.abc import Sequence

PLACEHOLDER = "<redacted>"
_QUOTED_MAX = 4096

# Names that mark the next value as a credential. Matched with no left word boundary, so glued
# and prefixed names (`dbPassword`, `GITHUB_TOKEN`, `mysecret`) are covered.
_SECRET_WORDS = (
    r"api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"auth[_-]?token|client[_-]?secret|secret[_-]?key|private[_-]?key|access[_-]?key|"
    r"credentials?|signature|passphrase|password|passwd|token|secret"
)
# A value: a double- or single-quoted string (escapes allowed, bounded, so a quoted value may
# contain spaces) together with any non-space run glued after its closing quote; otherwise the
# whole run up to whitespace. Never shorter than a whitespace-delimited run.
_DQ = r'"(?:[^"\\\n]|\\.){0,' + str(_QUOTED_MAX) + r'}"\S*'
_SQ = r"'(?:[^'\\\n]|\\.){0," + str(_QUOTED_MAX) + r"}'\S*"
_VALUE = _DQ + "|" + _SQ + r"|\S+"

# Shapes whose WHOLE match is the credential.
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # an auth scheme and its token, across whitespace/newlines (as before)
    re.compile(r"(?i)\b(?:bearer|basic|token|digest|negotiate)\s+[A-Za-z0-9._~+/=-]{8,}"),
    # prefixed API keys / tokens
    re.compile(
        r"\b(?:sk-(?:ant-)?|sk_live_|sess-|xai-|gh[pousr]_|github_pat_|glpat-|hf_|"
        r"xox[abceoprs]-|AIza|ya29\.|AKIA)[A-Za-z0-9_.-]{8,}"
    ),
    re.compile(r"(?<![\w/])1//[A-Za-z0-9_-]{16,}"),
    # a PEM or PGP private-key block, to its END line (or to the end of the text when cut)
    re.compile(
        r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----.*?"
        r"(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----|\Z)",
        re.S,
    ),
)

# Shapes whose named ``value`` group is the credential, so the key name stays readable. A value
# that is exactly one quoted string is narrowed to the inside of its quotes.
VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # key=value / key: value, quoted or bare key, optional auth-scheme word before the value
    re.compile(
        r"(?i)(?:" + _SECRET_WORDS + r")[\"']?\s*[:=]\s*"
        r"(?P<value>(?:(?:bearer|basic|token|digest|negotiate)\s+)?(?:" + _VALUE + r"))"
    ),
    # a command-line flag followed by its value: --api-key VALUE / -token 'VALUE' / --db-password=V
    re.compile(
        r"(?i)(?<![\w-])--?[A-Za-z0-9_-]{0,48}?(?:" + _SECRET_WORDS + r")(?:\s+|=)"
        r"(?P<value>(?!-)(?:" + _VALUE + r"))"
    ),
    # URL userinfo: scheme://user:VALUE@host or scheme://VALUE@host (the whole userinfo)
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]{0,31}://(?P<value>[^\s/@:]{1,256}(?::[^\s/@]{0,256})?)@"),
    # Cookie / Set-Cookie: a quoted value (JSON/dict form) or the rest of the header line
    re.compile(
        r"(?i)\b(?:set-)?cookie[\"']?\s*:\s*(?P<value>" + _DQ + "|" + _SQ + r"|[^\r\n]+)"
    ),
)

# A JWT (header.payload[.signature]) is found by a linear scan of dotted token runs; a single
# regex with a backtracking first segment is quadratic on long `eyJ-eyJ-…` runs.
_TOKEN_RUN_RE = re.compile(r"[A-Za-z0-9_.-]+")
_JWT_SEGMENT_MIN = 8


def _jwt_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for run in _TOKEN_RUN_RE.finditer(text):
        segment = run.group()
        if "eyJ" not in segment:
            continue
        base = run.start()
        dots = [i for i, ch in enumerate(segment) if ch == "."]
        next_dot = []  # next_dot[k]: index of the first "." at or after k, else len(segment)
        pointer = 0
        for k in range(len(segment) + 1):
            while pointer < len(dots) and dots[pointer] < k:
                pointer += 1
            next_dot.append(dots[pointer] if pointer < len(dots) else len(segment))
        k = segment.find("eyJ")
        while k != -1:
            # word boundary before "eyJ": start of the run, or a non-word character ("-" or ".")
            if k == 0 or not (segment[k - 1].isalnum() or segment[k - 1] == "_"):
                first_end = next_dot[k]
                if first_end - (k + 3) >= _JWT_SEGMENT_MIN and first_end < len(segment):
                    second_end = next_dot[first_end + 1]
                    if second_end - (first_end + 1) >= _JWT_SEGMENT_MIN:
                        end = second_end
                        if second_end < len(segment):
                            third_end = next_dot[second_end + 1]
                            if third_end > second_end + 1:
                                end = third_end
                        spans.append((base + k, base + end))
            k = segment.find("eyJ", k + 1)
    return spans


# The previous key/value detectors, verbatim, run on the same views they ran on before: the
# leg-detail detector on the normalized text and the stderr-excerpt detector on the raw text.
# The union therefore removes at least what they removed; the shapes above only add coverage.
_PREVIOUS_LEG_KV_RE = re.compile(
    r"(?i)[\"']?\b(?:api[_-]?key|authorization|proxy-authorization|access[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|client[_-]?secret|token|secret|password|passwd)[\"']?"
    r"\s*[:=]\s*(?P<value>[\"']?(?:(?:bearer|basic|token|digest)\s+)?[^\s\"',;]+[\"']?)"
)
_PREVIOUS_EXCERPT_KV_RE = re.compile(
    r"(?i)(?:api[_-]?key|authorization|token|secret|password)\s*[:=]\s*(?P<value>\S+)"
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
    """Every escape-sequence byte and every control character (newline kept) becomes ONE
    space, so offsets are preserved (the output has the input's length) and `Bearer\\t<tok>`
    / `Bearer\\x1b[1C<tok>` stay two words."""
    text = _ESCAPE_RE.sub(lambda m: " " * len(m.group(0)), text or "")
    return _CTRL_RE.sub(" ", text)


def _without_sgr(text: str) -> tuple[str, list[int]]:
    """``text`` with colour/attribute sequences removed, and each kept character's index in
    ``text``, so a coloured value is one token next to its key and its spans map back."""
    kept: list[str] = []
    index: list[int] = []
    cursor = 0
    for m in _SGR_RE.finditer(text):
        kept.append(text[cursor:m.start()])
        index.extend(range(cursor, m.start()))
        cursor = m.end()
    kept.append(text[cursor:])
    index.extend(range(cursor, len(text)))
    return "".join(kept), index


def _unquote(text: str, start: int, end: int) -> tuple[int, int]:
    """Narrow a value that is one quoted string, optionally followed only by structural
    delimiters (`",` / `"}` / `")`), to the inside of its quotes; otherwise keep it whole."""
    if end - start < 2 or text[start] not in "\"'":
        return start, end
    quote, k = text[start], start + 1
    while k < end:
        if text[k] == "\\":
            k += 2
            continue
        if text[k] == quote:
            break
        k += 1
    if k < end and all(ch in ",;:)]}" for ch in text[k + 1:end]):
        return start + 1, k
    return start, end


def credential_spans(text: str) -> list[tuple[int, int]]:
    """Every credential span recognised in ``text``, unmerged, as (start, end)."""
    spans: list[tuple[int, int]] = []
    for pattern in CREDENTIAL_PATTERNS:
        spans += [(m.start(), m.end()) for m in pattern.finditer(text)]
    for pattern in VALUE_PATTERNS:
        spans += [_unquote(text, m.start("value"), m.end("value")) for m in pattern.finditer(text)]
    spans += _jwt_spans(text)
    return [(s, e) for s, e in spans if e > s]


def _spans(
    raw: str,
    text: str,
    known: Sequence[str | os.PathLike[str]],
    identity: tuple[tuple[str, ...], tuple[str, ...]],
) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = [(s, e, "credential") for s, e in credential_spans(text)]
    spans += [(m.start("value"), m.end("value"), "credential") for m in _PREVIOUS_LEG_KV_RE.finditer(text)]
    spans += [(m.start("value"), m.end("value"), "credential") for m in _PREVIOUS_EXCERPT_KV_RE.finditer(raw)]
    # The closeout gate's forbidden shapes also run as detectors over the unredacted normalized
    # text, so a shape the final pass would have matched before any replacement still counts.
    from .redaction import _FORBIDDEN_METADATA_PATTERNS

    for _name, pattern in _FORBIDDEN_METADATA_PATTERNS:
        spans += [(m.start(), m.end(), "credential") for m in pattern.finditer(text)]
    sgr_free, index = _without_sgr(raw)
    for view_start, view_end in credential_spans(sgr_free):
        spans.append((index[view_start], index[view_end - 1] + 1, "credential"))
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
    # Placeholder matches do not overlap, so the only candidate is the last one starting at or
    # before the span (bisect), which keeps this linear-logarithmic.
    starts: list[int] = []
    ends: list[int] = []
    for m in _PLACEHOLDER_RE.finditer(text):
        starts.append(m.start())
        ends.append(m.end())

    def inside(start: int, end: int) -> bool:
        i = bisect.bisect_right(starts, start) - 1
        return i >= 0 and end <= ends[i]

    return [(s, e, k) for s, e, k in spans if e > s and not inside(s, e)]


def redact_text(
    text: str,
    known: Sequence[str | os.PathLike[str]] = (),
    *,
    identity: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
) -> str:
    """Span-union redaction of a WHOLE, UNCUT, multi-line text (line structure kept). Run
    this BEFORE selecting or cutting an excerpt, over the whole input (every pattern is
    linear). ``known`` are extra paths to replace, and
    ``identity`` defaults to `redaction_identity()`."""
    from .redaction import _FORBIDDEN_METADATA_PATTERNS

    raw = text or ""
    normalized = normalize(raw)
    # Credential shapes are detected over the normalized text and over the raw text with colour
    # codes removed (which keeps every other byte of the raw text); a span found in either view
    # is redacted. Both views map to the raw offsets, so normalization only adds coverage.
    spans = sorted(_spans(raw, normalized, known,
                          redaction_identity() if identity is None else identity))
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
