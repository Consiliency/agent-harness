"""Static audit of the review-runner Containerfile (RRIMAGE contract §3.5-§3.8).

The checks read the checked-in Containerfile as text. Nothing here builds,
pulls or runs an image. Each check is also run against a mutated copy, so a
check that stops detecting its rule fails the suite.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

CONTAINERFILE = Path(__file__).parents[1] / "images/review-runner/Containerfile"

# The `notices` block of the hash-checked BUILD.lock (contract §3.6).
LICENSE_NOTICES = {
    "GPL-2.0": "8780e78a1a737e127f25a65f6d95269bffd36158dc261114de7859b490bfc5aa",
    "Linux-syscall-note": "8e378ab93586eb55135d3bc119cce787f7324f48394777d00c34fa3d0be3303f",
}
SETUID_STRIP = "find / -xdev -perm /6000 -type f -exec chmod ug-s {} +"
SETUID_FAIL = 'test -z "$(find / -xdev -perm /6000 -type f -print -quit)"'
DIGEST_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[0-9]+)?(?:/[a-z0-9._-]+)*@sha256:[0-9a-f]{64}$")
FILE_ADDING = {"COPY", "ADD", "RUN"}
FETCH_TOOLS = re.compile(r"\b(curl|wget|apt-get|apt|apk|aptitude|git\s+clone|git\s+fetch|gh\s+api)\b")


@dataclass(frozen=True)
class Instruction:
    keyword: str
    text: str  # the instruction after the keyword, continuations joined
    heredoc: str
    stage: int


def parse(source: str) -> list[Instruction]:
    """Split a Dockerfile into instructions, skipping comments and keeping heredoc bodies."""
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
        while parts[-1].rstrip().endswith("\\") and i < len(lines):
            nxt = lines[i]
            i += 1
            if nxt.lstrip().startswith("#"):
                continue
            parts[-1] = parts[-1].rstrip()[:-1]
            parts.append(nxt)
        joined = " ".join(p.strip() for p in parts)
        keyword, _, rest = joined.partition(" ")
        keyword = keyword.upper()
        body: list[str] = []
        for marker in re.findall(r"<<-?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", rest):
            while i < len(lines) and lines[i].strip() != marker:
                body.append(lines[i])
                i += 1
            i += 1  # terminator
        if keyword == "FROM":
            stage += 1
        out.append(Instruction(keyword, rest.strip(), "\n".join(body), stage))
    return out


def flags(text: str) -> tuple[dict[str, str], str]:
    found: dict[str, str] = {}
    rest = text
    while (m := re.match(r"--([a-z-]+)(?:=(\S+))?\s*", rest)):
        found[m[1]] = m[2] or ""
        rest = rest[m.end():]
    return found, rest


def is_pinned_pip_step(ins: Instruction) -> bool:
    _, command = flags(ins.text)
    installs = re.findall(r"pip3?\s+install\b[^&;|]*", command)
    if not installs:
        return False
    if not all("--require-hashes" in s and "--only-binary=:all:" in s for s in installs):
        return False
    requirements = re.findall(r"'([^']*==[^']*)'", command)
    return bool(requirements) and all(re.search(r"--hash=sha256:[0-9a-f]{64}", r) for r in requirements)


# -- checks: each returns a list of violations --------------------------------

def check_from_digests(source: str) -> list[str]:
    bad = []
    for ins in parse(source):
        if ins.keyword == "FROM":
            _, image = flags(ins.text)
            ref = image.split()[0]
            if not DIGEST_IMAGE.match(ref):
                bad.append(ref)
    return bad


def check_syntax_directive(source: str) -> list[str]:
    return [line for line in source.splitlines()
            if re.match(r"^\s*#\s*syntax\s*=", line, re.I) and not re.search(r"@sha256:[0-9a-f]{64}\b", line)]


def check_run_network(source: str) -> list[str]:
    bad = []
    networked = 0
    for ins in parse(source):
        if ins.keyword != "RUN":
            continue
        opts, _ = flags(ins.text)
        if opts.get("network") == "none":
            continue
        if "network" in opts or not is_pinned_pip_step(ins):
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
        if ins.keyword == "RUN" and re.search(r"\bpip3?\s+install\b", payload) and not is_pinned_pip_step(ins):
            bad.append("unpinned pip")
    return bad


def check_licenses(source: str) -> list[str]:
    instructions = parse(source)
    builder = [i for i in instructions if i.stage == 0 and i.keyword == "RUN"]
    text = " ".join(i.text for i in builder)
    bad = []
    for name, digest in LICENSE_NOTICES.items():
        if f"{digest}  LICENSES/{name}" not in text:
            bad.append(f"hash check missing: {name}")
    exact = re.search(r"test \"\$\(find LICENSES -mindepth 1 -printf '%P\\n' \| LC_ALL=C sort \| tr '\\n' ' '\)\" = '([^']*)'", text)
    if not exact:
        bad.append("exact-set check missing")
    elif exact[1].split() != sorted(LICENSE_NOTICES):
        bad.append("exact-set differs from BUILD.lock notices")
    runtime_copies = [i.text for i in instructions if i.keyword == "COPY" and "LICENSES" in i.text]
    if any(not re.search(r"--from=landlock\b.*\s/src/LICENSES\s", t) for t in runtime_copies):
        bad.append("LICENSES copied from an unchecked source")
    return bad


def check_no_provenance_copy(source: str) -> list[str]:
    return [i.text for i in parse(source) if i.keyword in {"COPY", "ADD"} and "PROVENANCE" in i.text]


def check_source_date_epoch(source: str) -> list[str]:
    instructions = parse(source)
    last = max(i.stage for i in instructions)
    runtime = [i for i in instructions if i.stage == last]
    args = [n for n, i in enumerate(runtime) if i.keyword == "ARG" and i.text.split("=")[0] == "SOURCE_DATE_EPOCH"]
    users = [n for n, i in enumerate(runtime) if i.keyword == "RUN" and "useradd" in i.text]
    if not args:
        return ["no ARG SOURCE_DATE_EPOCH in runtime stage"]
    if not users or args[0] > users[0]:
        return ["ARG SOURCE_DATE_EPOCH after useradd"]
    return []


def check_setuid_strip(source: str) -> list[str]:
    instructions = parse(source)
    last = max(i.stage for i in instructions)
    bad = []
    for i in instructions:
        if i.keyword in {"COPY", "ADD"}:
            mode = flags(i.text)[0].get("chmod")
            if mode is not None and (not re.fullmatch(r"[0-7]{3,4}", mode) or int(mode, 8) & 0o6000):
                bad.append(f"COPY --chmod={mode}")
    runtime = [i for i in instructions if i.stage == last]
    strips = [n for n, i in enumerate(runtime)
              if i.keyword == "RUN" and SETUID_STRIP in i.text and SETUID_FAIL in i.text
              and i.text.index(SETUID_STRIP) < i.text.index(SETUID_FAIL)
              and flags(i.text)[0].get("network") == "none"]
    if not strips:
        return bad + ["no setuid/setgid strip with fail check"]
    created = " ".join(i.text for i in runtime[:strips[-1]] if i.keyword == "RUN")
    for i in runtime[strips[-1] + 1:]:
        if i.keyword in FILE_ADDING:
            bad.append(f"{i.keyword} after setuid strip")
        elif i.keyword == "WORKDIR" and not re.search(rf"install -d\b[^&]*\s{re.escape(i.text)}(\s|$)", created):
            bad.append("WORKDIR creates a directory after setuid strip")
    return bad


CHECKS = {
    "from_digests": check_from_digests,
    "syntax_directive": check_syntax_directive,
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


MUTATIONS = [
    ("from_digests", _replace("FROM docker.io/library/python@sha256:", "FROM docker.io/library/python:3.12-slim-bookworm\n# was @sha256:")),
    ("from_digests", _replace(" AS landlock", " AS landlock\nFROM busybox AS extra")),
    ("syntax_directive", lambda t: "# syntax=docker/dockerfile:1\n" + t),
    ("run_network", _replace("RUN --network=none chown", "RUN chown")),
    ("run_network", _replace("RUN --network=none /usr/local/bin/python3", "RUN /usr/local/bin/python3")),
    ("run_network", _replace("RUN --network=none chown", "RUN --network=host chown")),
    ("run_network", _replace("--require-hashes", "")),
    ("no_fetch_tool", _append_before_user("RUN --network=none curl -fsSL https://example.invalid/x")),
    ("no_fetch_tool", _append_before_user("RUN --network=none apt-get install -y gcc")),
    ("no_fetch_tool", _append_before_user("ADD https://example.invalid/x /x")),
    ("no_fetch_tool", _append_before_user("RUN --network=none git clone x")),
    ("no_fetch_tool", _append_before_user("RUN --network=none pip install rfc8785")),
    ("licenses", _replace(LICENSE_NOTICES["GPL-2.0"], "0" * 64)),
    ("licenses", _replace("= 'GPL-2.0 Linux-syscall-note '", "= 'GPL-2.0 Linux-syscall-note extra '")),
    ("licenses", _replace("LC_ALL=C sort", "sort")),
    ("no_provenance_copy", _append_before_user("COPY --from=landlock /src/PROVENANCE.md /usr/share/doc/landlock-exec/")),
    ("source_date_epoch", _replace("ARG SOURCE_DATE_EPOCH\n", "")),
    ("setuid_strip", _replace("--chmod=0755", "--chmod=4755")),
    ("setuid_strip", _replace("--chmod=0755", "--chmod=u+s")),
    ("setuid_strip", _replace(" \\\n    && " + SETUID_FAIL, "")),
    ("setuid_strip", _append_before_user("COPY --from=landlock /src/LICENSE /tmp/late")),
    ("setuid_strip", _append_before_user("RUN --network=none true")),
    ("setuid_strip", _replace("WORKDIR /work", "WORKDIR /elsewhere")),
]


@pytest.mark.parametrize("name,mutate", MUTATIONS, ids=[f"{n}-{k}" for k, (n, _) in enumerate(MUTATIONS)])
def test_mutation_is_detected(source, name, mutate):
    assert CHECKS[name](mutate(source)), f"{name} accepted a mutated Containerfile"


def test_parser_sees_every_instruction(source):
    keywords = [i.keyword for i in parse(source)]
    assert keywords.count("FROM") == 2
    assert keywords[-3:] == ["USER", "WORKDIR", "ENTRYPOINT"]
    heredoc = next(i for i in parse(source) if i.heredoc)
    assert "PT_INTERP" in heredoc.heredoc and "CHECK_RUNTIME" not in heredoc.heredoc
