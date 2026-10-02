"""One shared redaction pipeline: credential shapes plus known identity values, span-union.

Every place that removes credential values from text uses `redact_text`, so the same input
gives the same output everywhere. That covers review-leg details, PTY tails, private leg logs,
run-metadata stderr excerpts and hotfix reasons.

The pipeline:
  1. Normalize without destroying separation. Every control character and every character of
     an escape sequence becomes ONE space, so offsets and word breaks survive.
  2. The previous leg-detail redaction runs exactly as it ran before (its detectors, its merge,
     then the closeout gate's forbidden shapes over its own redacted text), and every raw
     offset it replaced is recorded. Those offsets are always redacted, so this pipeline never
     removes less than the previous one did, whatever the other detectors add.
  3. Every other detector reports spans over the normalized text; credential shapes also run
     over the raw text with colour codes removed. A span found in any view is redacted.
  4. Overlapping or adjacent spans merge, and each merged span is replaced ONCE, so a value
     is never half-substituted.
  5. The closeout metadata gate's forbidden shapes run last, over the redacted text.

Every step is linear in the input length: quantifiers that follow an alternation are bounded,
there is no nested optional repetition, and the two shapes a regex would match in quadratic
time (a JWT, and the forbidden `process.env[...] =` shape) are found by linear scans that
return exactly the regex's matches.
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

# Shapes whose WHOLE match is the credential. The first three are the previous leg-detail
# detectors, unchanged.
_SCHEME_RE = re.compile(r"(?i)\b(?:bearer|basic|token|digest|negotiate)\s+[A-Za-z0-9._~+/=-]{8,}")
_PREFIXED_RE = re.compile(
    r"\b(?:sk-(?:ant-)?|sk_live_|sess-|xai-|gh[pousr]_|github_pat_|glpat-|hf_|"
    r"xox[abceoprs]-|AIza|ya29\.|AKIA)[A-Za-z0-9_.-]{8,}"
)
_ONE_SLASH_RE = re.compile(r"(?<![\w/])1//[A-Za-z0-9_-]{16,}")
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # an auth scheme and its token, across whitespace/newlines (as before)
    _SCHEME_RE,
    # prefixed API keys / tokens
    _PREFIXED_RE,
    _ONE_SLASH_RE,
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

# A JWT (header.payload[.signature]) is found by a linear scan of dotted token runs; the regex
# `\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?` (the previous detector) is
# quadratic on long `eyJ-eyJ-…` runs.
_TOKEN_RUN_RE = re.compile(r"[A-Za-z0-9_.-]+")
_WORD_CHAR_RE = re.compile(r"\w")
_JWT_SEGMENT_MIN = 8


def _jwt_spans(text: str, *, overlapping: bool = True) -> list[tuple[int, int]]:
    """JWT spans. ``overlapping`` reports one from every `eyJ` start; otherwise exactly the
    regex's ``finditer`` matches (leftmost, non-overlapping)."""
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
            resume = k + 1
            # `\b` before "eyJ": the character before it (in the whole text) is not a word character
            if base + k == 0 or not _WORD_CHAR_RE.match(text, base + k - 1):
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
                        if not overlapping:
                            resume = end
            k = segment.find("eyJ", resume)
    return spans


# The closeout gate's `local_env_value` shape ends in `process\.env\[[^\]]+\]\s*=`, which a regex
# matches in quadratic time when many `process.env[` prefixes share one missing `]`. Its matches
# are found by a linear scan instead; every other forbidden shape is linear as a regex.
_LOCAL_ENV_PREFIX_RE = re.compile(r"local env value|\.env(?:\.local)? value|process\.env\[", re.I)
_LOCAL_ENV_TAIL_RE = re.compile(r"\s*=")


def _local_env_matches(text: str) -> list[tuple[int, int]]:
    """Exactly ``finditer`` of the `local_env_value` pattern. Its three alternatives start with
    different characters, so at most one applies at a position. The first `]` after a prefix
    and the `\s*=` after that `]` are each looked up once and reused by later prefixes."""
    matches: list[tuple[int, int]] = []
    close = -1  # the first "]" at or after the last lookup position, or len(text) for none
    tails: dict[int, int | None] = {}
    pos = 0
    while True:
        m = _LOCAL_ENV_PREFIX_RE.search(text, pos)
        if m is None:
            return matches
        if not m.group().endswith("["):
            matches.append((m.start(), m.end()))
            pos = m.end()
            continue
        inner = m.end()
        if close < inner:
            close = text.find("]", inner)
            if close == -1:
                close = len(text)
        if inner < close < len(text):
            if close not in tails:
                tail = _LOCAL_ENV_TAIL_RE.match(text, close + 1)
                tails[close] = tail.end() if tail else None
            if tails[close] is not None:
                matches.append((m.start(), tails[close]))
                pos = tails[close]
                continue
        pos = m.start() + 1


def _forbidden_matches(name: str, pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    if name == "local_env_value":
        return _local_env_matches(text)
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def _forbidden_pass(text: str) -> str:
    """The closeout gate's forbidden shapes, each replaced in turn (as `pattern.sub`)."""
    from .redaction import _FORBIDDEN_METADATA_PATTERNS

    for name, pattern in _FORBIDDEN_METADATA_PATTERNS:
        matches = _forbidden_matches(name, pattern, text)
        if matches:
            out: list[str] = []
            cursor = 0
            for start, end in matches:
                out += [text[cursor:start], PLACEHOLDER]
                cursor = end
            text = "".join(out) + text[cursor:]
    return text


# The previous key/value detectors, verbatim: the leg-detail one is part of the previous
# leg-detail redaction (run on the normalized text), the stderr-excerpt one runs on the raw text
# as the excerpt did.
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


def _without_sgr(text: str) -> tuple[str, list[int], list[int]]:
    """``text`` with colour/attribute sequences removed, so a coloured value is one token next
    to its key, plus the start of each kept run in that view and in ``text`` (see `_to_raw`)."""
    kept: list[str] = []
    view_starts: list[int] = []
    raw_starts: list[int] = []
    cursor = size = 0
    for m in _SGR_RE.finditer(text):
        kept.append(text[cursor:m.start()])
        view_starts.append(size)
        raw_starts.append(cursor)
        size += m.start() - cursor
        cursor = m.end()
    kept.append(text[cursor:])
    view_starts.append(size)
    raw_starts.append(cursor)
    return "".join(kept), view_starts, raw_starts


def _to_raw(offset: int, view_starts: list[int], raw_starts: list[int]) -> int:
    """The index in the raw text of the character at ``offset`` in the colour-free view."""
    i = bisect.bisect_right(view_starts, offset) - 1
    return raw_starts[i] + offset - view_starts[i]


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


def _placeholder_filter(text: str, spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Drop empty spans and every span wholly inside a placeholder already in ``text`` (it is
    the placeholder, not a new finding). Placeholder matches do not overlap, so the only
    candidate is the last one starting at or before the span (bisect)."""
    starts: list[int] = []
    ends: list[int] = []
    for m in _PLACEHOLDER_RE.finditer(text):
        starts.append(m.start())
        ends.append(m.end())

    def inside(start: int, end: int) -> bool:
        i = bisect.bisect_right(starts, start) - 1
        return i >= 0 and end <= ends[i]

    return [(s, e, k) for s, e, k in spans if e > s and not inside(s, e)]


def _previous_leg_spans(
    text: str,
    known: Sequence[str | os.PathLike[str]],
    identity: tuple[tuple[str, ...], tuple[str, ...]],
) -> list[tuple[int, int, str]]:
    """The previous leg-detail detectors over the normalized ``text``, with their exact matches."""
    spans: list[tuple[int, int, str]] = []
    for pattern in (_SCHEME_RE, _PREFIXED_RE, _ONE_SLASH_RE):
        spans += [(m.start(), m.end(), "credential") for m in pattern.finditer(text)]
    spans += [(s, e, "credential") for s, e in _jwt_spans(text, overlapping=False)]
    spans += [(m.start("value"), m.end("value"), "credential") for m in _PREVIOUS_LEG_KV_RE.finditer(text)]
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
    return _placeholder_filter(text, spans)


def _merge(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Merge overlapping or adjacent spans; each merged span gets one placeholder."""
    merged: list[list[object]] = []
    for start, end, kind in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].add(kind)
        else:
            merged.append([start, end, {kind}])
    return [(start, end, next(p for k, p in _PLACEHOLDER_FOR if k in kinds))
            for start, end, kinds in merged]


def _previous_leg_redaction(
    text: str, spans: list[tuple[int, int, str]]
) -> tuple[str, list[tuple[int, int]]]:
    """The previous leg-detail redaction of the normalized ``text`` given its ``spans``: merge
    and replace, then each forbidden shape replaced in turn over the result. Returns that output
    and the ``text`` offsets (start, end) behind every placeholder the forbidden shapes added.

    The output is tracked as segments (out_start, out_end, src_start, src_end, literal): a
    literal segment's characters are ``text[src_start:src_end]``; a placeholder segment stands
    for all of ``text[src_start:src_end]``. A forbidden match is mapped back through them, so
    its source offsets cover everything the previous redaction hid behind it."""
    from .redaction import _FORBIDDEN_METADATA_PATTERNS

    segments: list[tuple[int, int, int, int, bool]] = []
    pieces: list[str] = []
    size = cursor = 0
    for start, end, placeholder in _merge(spans):
        if start > cursor:
            segments.append((size, size + start - cursor, cursor, start, True))
            pieces.append(text[cursor:start])
            size += start - cursor
        segments.append((size, size + len(placeholder), start, end, False))
        pieces.append(placeholder)
        size += len(placeholder)
        cursor = end
    if cursor < len(text):
        segments.append((size, size + len(text) - cursor, cursor, len(text), True))
        pieces.append(text[cursor:])
    output = "".join(pieces)
    hidden: list[tuple[int, int]] = []  # the merged spans themselves are the caller's ``spans``

    for name, pattern in _FORBIDDEN_METADATA_PATTERNS:
        matches = _forbidden_matches(name, pattern, output)
        if not matches:
            continue
        index = 0

        def at(offset: int) -> tuple[int, int, int, int, bool]:
            nonlocal index
            while segments[index][1] <= offset:
                index += 1
            return segments[index]

        def source(offset: int) -> tuple[int, int]:
            out_start, _out_end, src_start, src_end, literal = at(offset)
            if literal:
                return src_start + offset - out_start, src_start + offset - out_start + 1
            return src_start, src_end

        new_segments: list[tuple[int, int, int, int, bool]] = []
        pieces = []
        size = 0

        def copy(lo: int, hi: int) -> None:
            nonlocal size
            while lo < hi:
                out_start, out_end, src_start, src_end, literal = at(lo)
                part = min(hi, out_end) - lo
                if literal:
                    shifted = src_start + lo - out_start
                    new_segments.append((size, size + part, shifted, shifted + part, True))
                else:
                    new_segments.append((size, size + part, src_start, src_end, False))
                pieces.append(output[lo:lo + part])
                size += part
                lo += part

        cursor = 0
        for start, end in matches:
            copy(cursor, start)
            src = (source(start)[0], source(end - 1)[1])
            hidden.append(src)
            new_segments.append((size, size + len(PLACEHOLDER), src[0], src[1], False))
            pieces.append(PLACEHOLDER)
            size += len(PLACEHOLDER)
            cursor = end
        copy(cursor, len(output))
        segments, output = new_segments, "".join(pieces)
    return output, hidden


def _spans(raw: str, text: str) -> list[tuple[int, int, str]]:
    """The detectors beyond the previous leg-detail ones: the credential shapes over the
    normalized ``text`` and over the raw text without colour codes, and the previous
    stderr-excerpt detector over the raw text."""
    spans: list[tuple[int, int, str]] = [(s, e, "credential") for s, e in credential_spans(text)]
    spans += [(m.start("value"), m.end("value"), "credential") for m in _PREVIOUS_EXCERPT_KV_RE.finditer(raw)]
    sgr_free, view_starts, raw_starts = _without_sgr(raw)
    for view_start, view_end in credential_spans(sgr_free):
        spans.append((_to_raw(view_start, view_starts, raw_starts),
                      _to_raw(view_end - 1, view_starts, raw_starts) + 1, "credential"))
    return _placeholder_filter(text, spans)


def redact_text(
    text: str,
    known: Sequence[str | os.PathLike[str]] = (),
    *,
    identity: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
) -> str:
    """Span-union redaction of a WHOLE, UNCUT, multi-line text (line structure kept). Run
    this BEFORE selecting or cutting an excerpt, over the whole input (every step is
    linear). ``known`` are extra paths to replace, and
    ``identity`` defaults to `redaction_identity()`."""
    raw = text or ""
    normalized = normalize(raw)
    previous = _previous_leg_spans(normalized, known, redaction_identity() if identity is None else identity)
    # Everything the previous leg-detail redaction replaced, including what its final
    # forbidden-shape pass replaced, is always replaced here, so no other detector can make
    # this output keep a character the previous output had removed.
    _output, hidden = _previous_leg_redaction(normalized, previous)
    spans = previous + [(s, e, "credential") for s, e in hidden] + _spans(raw, normalized)
    out: list[str] = []
    cursor = 0
    for start, end, placeholder in _merge(spans):
        out += [normalized[cursor:start], placeholder]
        cursor = end
    return _forbidden_pass("".join(out) + normalized[cursor:])
