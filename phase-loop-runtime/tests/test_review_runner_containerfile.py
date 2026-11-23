"""Static audit of the review-runner Containerfile (RRIMAGE contract §3.5-§3.8).

The checks read the checked-in Containerfile as text. Nothing here builds,
pulls or runs an image. Each check is also run against mutated copies, so a
check that stops detecting its rule fails the suite.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

CONTAINERFILE = Path(__file__).parents[1] / "images/review-runner/Containerfile"

# The installed-wheel Gate A layout copies tests/ without images/.
pytestmark = pytest.mark.skipif(not CONTAINERFILE.is_file(), reason="the Containerfile is repository source")

# The `notices` block of the hash-checked BUILD.lock (contract §3.6).
LICENSE_NOTICES = {
    "GPL-2.0": "8780e78a1a737e127f25a65f6d95269bffd36158dc261114de7859b490bfc5aa",
    "Linux-syscall-note": "8e378ab93586eb55135d3bc119cce787f7324f48394777d00c34fa3d0be3303f",
}
LICENSE_SEGMENTS = [
    *(f"echo '{digest}  LICENSES/{name}' | sha256sum -c -" for name, digest in LICENSE_NOTICES.items()),
    "test \"$(find LICENSES -mindepth 1 -printf '%P\\n' | LC_ALL=C sort | tr '\\n' ' ')\" = '"
    + "".join(f"{name} " for name in sorted(LICENSE_NOTICES)) + "'",
]
# The builder's verification RUN, as a pure `&&` chain: these steps in this order, nothing else.
BUILDER_SEGMENTS = [
    "echo 'ccb26a3d7078ca1ab6d6dab0bdbf7a0bf44d8cc22250d193094d6425ae1a1a6c  BUILD.lock' | sha256sum -c -",
    "echo '689b41cdd017f7df6e0246bddfb0f9b5913802001c6c0421ec076908ad0066fa  LICENSE' | sha256sum -c -",
    "echo 'a83ec097b90a11c711493f2ace37ded50970c416fa7d71e5b280a171712e7b94  build.sh' | sha256sum -c -",
    "echo 'dff311f80f0b30d6961a3f6d0644df71fbd42f8e7935e38d3689254f0f49eea5  exec.c' | sha256sum -c -",
    "echo 'b58873117c841859537f9f4aef2ec2d7ae5c67ed57973f1961063858ac68055e  uapi.h' | sha256sum -c -",
    *LICENSE_SEGMENTS,
    "sh build.sh /landlock-exec",
    "echo '775d4f7af61dff58e5094eeac56fcda2fdb7e56d3f05fbf008b1caf1f84500aa  /landlock-exec' | sha256sum -c -",
]
LICENSE_COPY = "--from=landlock /src/LICENSES /usr/share/doc/landlock-exec/LICENSES"
# The scan's exit status is checked on its own, so a find error fails the step.
SETUID_SEGMENTS = [
    "set -eu",
    "find / -xdev -perm /6000 -type f -exec chmod ug-s {} +",
    'remaining="$(find / -xdev -perm /6000 -type f -print)"',
    'test -z "$remaining"',
]
PIP_SEGMENTS = [
    re.compile(r"printf '%s\\n' '[A-Za-z0-9._-]+==[A-Za-z0-9._-]+ --hash=sha256:[0-9a-f]{64}' > (/tmp/[a-z-]+\.txt)"),
    re.compile(r"pip install --no-cache-dir --only-binary=:all: --require-hashes -r (/tmp/[a-z-]+\.txt)"),
    re.compile(r"rm (/tmp/[a-z-]+\.txt)"),
]
DIGEST_IMAGE = re.compile(r"[a-z0-9][a-z0-9._-]*(?::[0-9]+)?(?:/[a-z0-9._-]+)*@sha256:[0-9a-f]{64}")
# Instructions that change no file in the image once the setuid strip has run.
AFTER_STRIP = {"USER", "WORKDIR", "ENTRYPOINT", "CMD", "ENV", "LABEL", "EXPOSE", "STOPSIGNAL"}
FETCH_TOOLS = re.compile(r"\b(curl|wget|apt-get|apt|apk|aptitude|git\s+clone|git\s+fetch|gh\s+api)\b")


HEREDOC_INSTRUCTIONS = {"RUN", "COPY", "ADD"}
HEREDOC_MARKER = re.compile(r"(?<!\S)<<(-?)(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2(?!\S)")


@dataclass(frozen=True)
class Instruction:
    keyword: str
    text: str  # everything after the opcode, continuations joined
    heredoc: str
    stage: int
    unterminated: bool = False

    @property
    def options(self) -> dict[str, str]:
        return split_flags(self.text)[0]

    @property
    def command(self) -> str:
        return split_flags(self.text)[1]

    @property
    def segments(self) -> list[str]:
        return [s.strip() for s in re.split(r"\s&&\s", self.command)]


def parse(source: str) -> list[Instruction]:
    """Split a Dockerfile into instructions.

    Comment and blank lines inside a continuation are dropped, as BuildKit does. The
    opcode is case-insensitive and delimited by any whitespace. A heredoc ends only at
    a line equal to its delimiter (leading tabs removed for ``<<-``). Heredocs are read
    only for RUN, COPY and ADD, and only from a whole marker word. An unterminated
    heredoc is flagged, and parsing resumes after its instruction.
    """
    lines = source.splitlines()
    out: list[Instruction] = []
    stage = -1
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [line]
        while re.search(r"\\\s*$", parts[-1]) and i < len(lines):
            nxt = lines[i]
            i += 1
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            parts[-1] = re.sub(r"\\\s*$", "", parts[-1])
            parts.append(nxt)
        joined = " ".join(p.strip() for p in parts)
        match = re.match(r"(\S+)\s*(.*)", joined, re.S)
        keyword, rest = match[1].upper(), match[2].strip()
        body: list[str] = []
        unterminated = False
        markers = HEREDOC_MARKER.findall(rest) if keyword in HEREDOC_INSTRUCTIONS else []
        for dash, _, marker in markers:
            start = i
            while i < len(lines) and (lines[i].lstrip("\t") if dash else lines[i]) != marker:
                body.append(lines[i])
                i += 1
            if i == len(lines):
                unterminated, i, body = True, start, []
                break
            i += 1  # the delimiter line
        if keyword == "FROM":
            stage += 1
        out.append(Instruction(keyword, rest, "\n".join(body), stage, unterminated))
    return out


def split_flags(text: str) -> tuple[dict[str, str], str]:
    found: dict[str, str] = {}
    rest = text
    while (m := re.match(r"--([A-Za-z-]+)(?:=(\S+))?\s*", rest)):
        found[m[1].lower()] = m[2] or ""
        rest = rest[m.end():]
    return found, rest.strip()


def is_pinned_pip_step(ins: Instruction) -> bool:
    """The networked step is exactly: write a hash-pinned requirement, install it, remove it."""
    segments = ins.segments
    if len(segments) != len(PIP_SEGMENTS):
        return False
    files = set()
    for segment, pattern in zip(segments, PIP_SEGMENTS):
        m = pattern.fullmatch(segment)
        if not m:
            return False
        files.add(m[1])
    return len(files) == 1 and not ins.heredoc


def runtime(instructions: list[Instruction]) -> list[Instruction]:
    last = max(i.stage for i in instructions)
    return [i for i in instructions if i.stage == last]


# -- checks: each returns a list of violations --------------------------------

def check_heredocs(source: str) -> list[str]:
    return [f"unterminated heredoc in {i.keyword}" for i in parse(source) if i.unterminated]


def check_from_digests(source: str) -> list[str]:
    bad = []
    for ins in parse(source):
        if ins.keyword == "FROM":
            ref = ins.command.split()[0] if ins.command else ""
            if not DIGEST_IMAGE.fullmatch(ref):
                bad.append(ref)
    return bad


def check_parser_directives(source: str) -> list[str]:
    bad = []
    for line in source.splitlines():
        if re.match(r"^\s*#\s*syntax\s*=", line, re.I) and not re.search(r"@sha256:[0-9a-f]{64}\b", line):
            bad.append(line)
        if re.match(r"^\s*#\s*escape\s*=", line, re.I):
            bad.append(line)
    return bad


def check_no_shell_override(source: str) -> list[str]:
    return [i.keyword for i in parse(source) if i.keyword in {"SHELL", "ONBUILD"}]


def check_run_network(source: str) -> list[str]:
    bad = []
    networked = 0
    for ins in parse(source):
        if ins.keyword != "RUN":
            continue
        if ins.options.get("network") == "none":
            continue
        if "network" in ins.options or not is_pinned_pip_step(ins):
            bad.append(ins.text[:60])
        else:
            networked += 1
    if networked > 1:
        bad.append("more than one networked RUN")
    return bad


def check_no_fetch_tool(source: str) -> list[str]:
    bad = []
    for ins in parse(source):
        payload = ins.text + "\n" + ins.heredoc
        if ins.keyword == "ADD":
            bad.append("ADD")
        if FETCH_TOOLS.search(payload) or re.search(r"https?://", payload):
            bad.append(ins.text[:60])
        if ins.keyword == "RUN" and re.search(r"\bpip3?\b", payload) and not is_pinned_pip_step(ins):
            bad.append("unpinned pip")
    return bad


def check_licenses(source: str) -> list[str]:
    instructions = parse(source)
    builder = [i for i in instructions if i.stage == 0 and i.keyword == "RUN"]
    bad = []
    if len(builder) != 1 or builder[0].segments != BUILDER_SEGMENTS or builder[0].heredoc:
        bad.append("builder verification RUN differs from the audited && chain")
    copies = [i for i in instructions if i.keyword in {"COPY", "ADD"} and "LICENSES" in i.text]
    if [i.text for i in copies] != [LICENSE_COPY] or copies[0] not in runtime(instructions):
        bad.append("runtime stage must copy exactly the checked LICENSES/")
    return bad


def check_no_provenance_copy(source: str) -> list[str]:
    return [i.text for i in parse(source) if i.keyword in {"COPY", "ADD"} and "PROVENANCE" in i.text]


def check_source_date_epoch(source: str) -> list[str]:
    stage = runtime(parse(source))
    args = [n for n, i in enumerate(stage) if i.keyword == "ARG" and i.text.split("=")[0] == "SOURCE_DATE_EPOCH"]
    users = [n for n, i in enumerate(stage) if i.keyword == "RUN" and "useradd" in i.text]
    if not args:
        return ["no ARG SOURCE_DATE_EPOCH in runtime stage"]
    if not users or args[0] > users[0]:
        return ["ARG SOURCE_DATE_EPOCH after useradd"]
    return []


def check_setuid_strip(source: str) -> list[str]:
    instructions = parse(source)
    bad = []
    for i in instructions:
        if i.keyword in {"COPY", "ADD"}:
            mode = i.options.get("chmod")
            if mode is not None and (not re.fullmatch(r"[0-7]{3,4}", mode) or int(mode, 8) & 0o6000):
                bad.append(f"COPY --chmod={mode}")
    stage = runtime(instructions)
    strips = [n for n, i in enumerate(stage)
              if i.keyword == "RUN" and i.segments == SETUID_SEGMENTS and i.options == {"network": "none"}]
    if not strips:
        return bad + ["no setuid/setgid strip with an exit-checked scan"]
    created = [s for i in stage[:strips[-1]] if i.keyword == "RUN" for s in i.segments]
    for i in stage[strips[-1] + 1:]:
        if i.keyword not in AFTER_STRIP:
            bad.append(f"{i.keyword} after setuid strip")
        elif i.keyword == "WORKDIR" and not any(
                re.fullmatch(rf"install -d( -[ogm] \S+)* {re.escape(i.text)}", s) for s in created):
            bad.append("WORKDIR creates a directory after setuid strip")
    return bad


CHECKS = {
    "heredocs": check_heredocs,
    "from_digests": check_from_digests,
    "parser_directives": check_parser_directives,
    "no_shell_override": check_no_shell_override,
    "run_network": check_run_network,
    "no_fetch_tool": check_no_fetch_tool,
    "licenses": check_licenses,
    "no_provenance_copy": check_no_provenance_copy,
    "source_date_epoch": check_source_date_epoch,
    "setuid_strip": check_setuid_strip,
}


@pytest.fixture(scope="module")
def source() -> str:
    return CONTAINERFILE.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_checked_in_containerfile_passes(source, name):
    assert CHECKS[name](source) == []


def _replace(old: str, new: str):
    def mutate(text: str) -> str:
        assert old in text, old
        return text.replace(old, new, 1)
    return mutate


def _append_before_user(line: str):
    return _replace("USER sandbox:sandbox", f"{line}\nUSER sandbox:sandbox")


STRIP_TAIL = ' \\\n    && remaining="$(find / -xdev -perm /6000 -type f -print)" \\\n    && test -z "$remaining"'

MUTATIONS = [
    ("from_digests", _replace("FROM docker.io/library/python@sha256:", "FROM docker.io/library/python:3.12-slim-bookworm\n# was @sha256:")),
    ("from_digests", _replace(" AS landlock", " AS landlock\nFROM busybox AS extra")),
    ("from_digests", _replace(" AS landlock", " AS landlock\nfrom\tbusybox AS extra")),
    ("parser_directives", lambda t: "# syntax=docker/dockerfile:1\n" + t),
    ("parser_directives", lambda t: "# escape=`\n" + t),
    ("no_shell_override", _append_before_user('SHELL ["/bin/bash", "-c"]')),
    ("no_shell_override", _append_before_user("onbuild RUN true")),
    ("run_network", _replace("RUN --network=none chown", "RUN chown")),
    ("run_network", _replace("RUN --network=none /usr/local/bin/python3", "RUN /usr/local/bin/python3")),
    ("run_network", _replace("RUN --network=none chown", "RUN --network=host chown")),
    ("run_network", _replace("--require-hashes", "")),
    ("run_network", _replace("    && rm /tmp/worker-requirements.txt\n",
                             "    && rm /tmp/worker-requirements.txt \\\n    && sh /tmp/extra.sh\n")),
    ("run_network", _replace("&& rm /tmp/worker-requirements.txt", "&& rm /tmp/worker-requirements.txt; sh /tmp/extra.sh")),
    ("run_network", _append_before_user("rUn\ttrue")),
    ("no_fetch_tool", _append_before_user("RUN --network=none curl -fsSL https://example.invalid/x")),
    ("no_fetch_tool", _append_before_user("RUN --network=none apt-get install -y gcc")),
    ("no_fetch_tool", _append_before_user("ADD https://example.invalid/x /x")),
    ("no_fetch_tool", _append_before_user("add\thttps://example.invalid/x /x")),
    ("no_fetch_tool", _append_before_user("RUN --network=none git clone x")),
    ("no_fetch_tool", _append_before_user("RUN --network=none pip install rfc8785")),
    ("licenses", _replace(LICENSE_NOTICES["GPL-2.0"], "0" * 64)),
    ("licenses", _replace("= 'GPL-2.0 Linux-syscall-note '", "= 'GPL-2.0 Linux-syscall-note extra '")),
    ("licenses", _replace("LC_ALL=C sort", "sort")),
    ("licenses", _replace(f"COPY {LICENSE_COPY}\n", "")),
    ("licenses", _replace(f"COPY {LICENSE_COPY}\n", "COPY --from=landlock-source /LICENSES /usr/share/doc/landlock-exec/LICENSES\n")),
    ("licenses", _replace("    && echo '8780e78a", "    && printf '%s\\n' \"echo '8780e78a")),
    ("licenses", _replace("RUN --network=none echo 'ccb26a3d", "RUN --network=none false && echo 'ccb26a3d")),
    ("licenses", _replace("/landlock-exec' | sha256sum -c -\n", "/landlock-exec' | sha256sum -c - || true\n")),
    ("heredocs", _append_before_user("RUN --network=none sh <<'NEVER_ENDS'")),
    ("setuid_strip", _append_before_user('ENV REVIEW_NOTE="<<EOF"\nCOPY --from=landlock /src/LICENSE /tmp/late')),
    ("no_provenance_copy", _append_before_user("COPY --from=landlock /src/PROVENANCE.md /usr/share/doc/landlock-exec/")),
    ("source_date_epoch", _replace("ARG SOURCE_DATE_EPOCH\n", "")),
    ("setuid_strip", _replace("--chmod=0755", "--chmod=4755")),
    ("setuid_strip", _replace("--chmod=0755", "--chmod=u+s")),
    # The scan result fed straight to test: a find error would still pass.
    ("setuid_strip", _replace(STRIP_TAIL, ' \\\n    && test -z "$(find / -xdev -perm /6000 -type f -print -quit)"')),
    ("setuid_strip", _replace(STRIP_TAIL, STRIP_TAIL + " || true")),
    ("setuid_strip", _replace("RUN --network=none set -eu \\\n", "RUN --network=none true \\\n")),
    ("setuid_strip", _replace("RUN --network=none set -eu \\\n    && find /", "RUN --network=none set -eu \\\n    && printf '%s' find /")),
    ("setuid_strip", _append_before_user("COPY --from=landlock /src/LICENSE /tmp/late")),
    ("setuid_strip", _append_before_user("RUN --network=none true")),
    ("setuid_strip", _append_before_user("rUn\ttrue")),
    ("setuid_strip", _append_before_user("rUn\t--network=none \\\n\n    true")),
    ("setuid_strip", _replace("WORKDIR /work", "WORKDIR /elsewhere")),
]


@pytest.mark.parametrize("name,mutate", MUTATIONS, ids=[f"{n}-{k}" for k, (n, _) in enumerate(MUTATIONS)])
def test_mutation_is_detected(source, name, mutate):
    assert CHECKS[name](mutate(source)), f"{name} accepted a mutated Containerfile"


def test_parser_sees_every_instruction(source):
    instructions = parse(source)
    keywords = [i.keyword for i in instructions]
    assert keywords.count("FROM") == 2
    assert keywords[-3:] == ["USER", "WORKDIR", "ENTRYPOINT"]
    heredoc = next(i for i in instructions if i.heredoc)
    assert "PT_INTERP" in heredoc.heredoc and "CHECK_RUNTIME" not in heredoc.heredoc


def test_parser_opcode_whitespace_case_and_continuation():
    parsed = parse("FROM a@sha256:" + "0" * 64 + "\nrUn\t--network=none \\\n# note\n\n  echo x \\\n  && true\n")
    assert [(i.keyword, i.options, i.segments) for i in parsed[1:]] == [("RUN", {"network": "none"}, ["echo x", "true"])]


def test_parser_heredoc_ends_only_at_exact_delimiter():
    parsed = parse("FROM a\nRUN python3 - <<'EOF'\n  EOF\nRUN true\nEOF\nUSER x\n")
    assert [i.keyword for i in parsed] == ["FROM", "RUN", "USER"]
    assert parsed[1].heredoc == "  EOF\nRUN true"
    dashed = parse("FROM a\nRUN sh <<-EOF\n\t\tEOF\nUSER x\n")
    assert [i.keyword for i in dashed] == ["FROM", "RUN", "USER"]


def test_env_literal_does_not_hide_a_late_copy(source):
    mutated = _append_before_user('ENV REVIEW_NOTE="<<EOF"\nCOPY --from=landlock /src/LICENSE /tmp/late')(source)
    assert "COPY after setuid strip" in check_setuid_strip(mutated)
    assert [i.keyword for i in parse(mutated)][-5:] == ["ENV", "COPY", "USER", "WORKDIR", "ENTRYPOINT"]


def test_parser_flags_unterminated_heredoc_and_keeps_parsing():
    parsed = parse("FROM a\nRUN sh <<EOF\necho x\nUSER x\n")
    assert [(i.keyword, i.unterminated) for i in parsed] == [("FROM", False), ("RUN", True), ("ECHO", False), ("USER", False)]
