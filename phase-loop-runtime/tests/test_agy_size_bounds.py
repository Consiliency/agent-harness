"""The agy size bounds and the streaming seat reader (AGYFRESH §1; EC-RESTORE-2).

Three bounds are defined once, in ``agy_provenance``, and every reader looks them up there
when it runs. So every test here patches the module attribute (never an alias) to a small
value and checks the exact boundary: N-1 and N pass, N+1 refuses.

The archive reader also counts the decompressed bytes it hands to the tar parser
(headers, extension records, padding and skipped members included) and bounds what the
parser keeps: header blocks, extension-record bytes, extension chains, and no sparse maps.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import tracemalloc

import pytest

q = pytest.importorskip("phase_loop_runtime.agy_qualification")

from phase_loop_runtime import agy_integrity  # noqa: E402
from phase_loop_runtime import agy_provenance as prov  # noqa: E402
from phase_loop_runtime import gemini_heartbeat as gh  # noqa: E402

PACKAGE = Path(prov.__file__).resolve().parent
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_qualified_agy_image.py"
HOST = prov.HostPlatform("linux", "x64", "glibc")
F_GET_SEALS = 1034

linux_memfd = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(os, "memfd_create") or not hasattr(os, "pidfd_open"),
    reason="seat admission needs sealed memfds and pidfds")

# N-1, N and N+1 bytes, as the offset of the patched bound from the image size.
BOUNDARY = [pytest.param(1, True, id="N-1"), pytest.param(0, True, id="N"),
            pytest.param(-1, False, id="N+1")]


def _image(size):
    head = b"#!/bin/sh\nexit 0\n"
    return head + b"\0" * (size - len(head))


def _archive(members, *, format=tarfile.GNU_FORMAT, pax_headers=None):
    """A tar.gz of ``members``: (name, bytes, type) triples, or ready ``TarInfo`` pairs."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=format, pax_headers=pax_headers) as bundle:
        for entry in members:
            if isinstance(entry[0], tarfile.TarInfo):
                info, data = entry
            else:
                name, data, kind = entry
                info = tarfile.TarInfo(name)
                info.type = kind
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _asset(archive):
    return prov.ReleaseAsset("1.2.99", HOST.asset, "u", sha256(archive).hexdigest())


def _read(archive):
    return prov.read_member(io.BytesIO(archive), _asset(archive))


class _Recorder:
    """Records the ``_ExpandedReader`` each ``read_member`` call makes."""

    def __init__(self, monkeypatch):
        self.readers, real = [], prov._ExpandedReader
        recorder = self

        class Recording(real):
            def __init__(self, compressed):
                super().__init__(compressed)
                recorder.readers.append(self)

        monkeypatch.setattr(prov, "_ExpandedReader", Recording)


# ------------------------------------------------------------------ the bounds themselves

def test_the_three_bounds_have_the_ruled_values():
    assert prov.MAX_MEMBER_BYTES == 512_000_000
    assert prov.MAX_ARCHIVE_BYTES == 256_000_000
    assert prov.MAX_EXPANDED_BYTES == 1_024_000_000


def _verifier():
    spec = importlib.util.spec_from_file_location("verify_qualified_agy_image_bounds", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_verifier_literals_equal_the_module_bounds():
    verifier = _verifier()
    assert verifier.MAX_MEMBER_BYTES == prov.MAX_MEMBER_BYTES
    assert verifier.MAX_ARCHIVE_BYTES == prov.MAX_ARCHIVE_BYTES


def _sources():
    return [*sorted(PACKAGE.glob("agy_*.py")), PACKAGE / "gemini_heartbeat.py", SCRIPT]


@pytest.mark.parametrize("literal", ["250_000_000", "300_000_000", "300_000_001", "128_000_000",
                                     "_MAX_IMAGE_BYTES"])
def test_no_reader_keeps_a_retired_bound_or_alias(literal):
    offenders = [path.name for path in _sources() if literal in path.read_text()]
    assert offenders == []


@pytest.mark.parametrize("literal", ["512_000_000", "256_000_000", "1_024_000_000"])
def test_each_bound_value_is_written_only_where_it_is_defined(literal):
    """The module defines each bound once; only the standalone verifier repeats two of them."""
    holders = sorted(path.name for path in _sources() if literal in path.read_text())
    expected = ["agy_provenance.py"] + ([SCRIPT.name] if literal != "1_024_000_000" else [])
    assert holders == sorted(expected)


def test_no_module_imports_a_bound_by_name():
    """``from .agy_provenance import MAX_...`` would freeze an alias that a patch cannot move."""
    pattern = re.compile(r"from\s+(\.|phase_loop_runtime\.)agy_provenance\s+import[^\n]*MAX_")
    offenders = [path.name for path in sorted(PACKAGE.rglob("*.py")) if pattern.search(path.read_text())]
    assert offenders == []


# ------------------------------------------------------------- read_member: the member

@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_read_member_member_boundary(monkeypatch, offset, passes):
    image = _image(4096)
    archive = _archive([("antigravity", image, tarfile.REGTYPE)])
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", len(image) + offset)
    if passes:
        assert _read(archive) == (sha256(image).hexdigest(), None)
    else:
        with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
            _read(archive)


# ------------------------------------------------------------ read_member: the archive

@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_read_member_compressed_archive_boundary(monkeypatch, offset, passes):
    image = _image(4096)
    archive = _archive([("antigravity", image, tarfile.REGTYPE)])
    monkeypatch.setattr(prov, "MAX_ARCHIVE_BYTES", len(archive) + offset)
    if passes:
        assert _read(archive)[0] == sha256(image).hexdigest()
    else:
        with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
            _read(archive)


def _expanded_size(archive):
    """The decompressed bytes ``read_member`` hands the tar parser for ``archive``."""
    reader = prov._ExpandedReader(prov._HashingReader(io.BytesIO(archive)))
    with tarfile.open(fileobj=reader, mode="r|", bufsize=prov._CHUNK_BYTES,
                      tarinfo=prov._bounded_tarinfo()) as bundle:
        for member in bundle:
            handle = bundle.extractfile(member)
            if handle is not None:
                while handle.read(prov._CHUNK_BYTES):
                    pass
    return reader.size


@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_read_member_expanded_boundary(monkeypatch, offset, passes):
    image = _image(64 * 1024)
    archive = _archive([("README", b"r" * 3000, tarfile.REGTYPE), ("antigravity", image, tarfile.REGTYPE)])
    expanded = _expanded_size(archive)
    assert expanded > len(image) + 3000  # headers and padding count, not only payloads
    monkeypatch.setattr(prov, "MAX_EXPANDED_BYTES", expanded + offset)
    if passes:
        assert _read(archive)[0] == sha256(image).hexdigest()
    else:
        with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
            _read(archive)


def test_declared_sizes_of_unrelated_members_over_the_budget_refuse_before_their_bytes(monkeypatch):
    """The declared sum is checked as each member is announced, before its bytes are read."""
    recorder = _Recorder(monkeypatch)
    two_mib = 2 * 1024 * 1024
    archive = _archive([("a", os.urandom(two_mib), tarfile.REGTYPE),
                        ("b", os.urandom(two_mib), tarfile.REGTYPE),
                        ("antigravity", _image(4096), tarfile.REGTYPE)])
    budget = 3 * 1024 * 1024 + 512 * 1024
    monkeypatch.setattr(prov, "MAX_EXPANDED_BYTES", budget)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)
    reader, = recorder.readers
    assert reader.size <= budget  # the declared sum refused, not the byte count


def test_many_empty_members_spend_the_expanded_budget(monkeypatch):
    """Zero-length members declare nothing, but their header blocks are decompressed bytes."""
    recorder = _Recorder(monkeypatch)
    archive = _archive([(f"empty-{index}", b"", tarfile.REGTYPE) for index in range(600)]
                       + [("antigravity", _image(4096), tarfile.REGTYPE)])
    budget = 128 * 1024
    monkeypatch.setattr(prov, "MAX_EXPANDED_BYTES", budget)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)
    reader, = recorder.readers
    assert reader.size > budget  # the decompressed-byte count refused


def test_an_extension_record_spends_the_expanded_budget(monkeypatch):
    """A PAX record is read by the parser before its member is yielded; it still counts."""
    recorder = _Recorder(monkeypatch)
    info = tarfile.TarInfo("antigravity")
    info.pax_headers = {"comment": "c" * (256 * 1024)}
    archive = _archive([(info, _image(4096))], format=tarfile.PAX_FORMAT)
    monkeypatch.setattr(prov, "MAX_ARCHIVE_METADATA_BYTES", 1 << 30)
    budget = 128 * 1024
    monkeypatch.setattr(prov, "MAX_EXPANDED_BYTES", budget)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)
    reader, = recorder.readers
    assert reader.size > budget


def test_a_highly_compressible_archive_is_bounded_by_its_expanded_bytes(monkeypatch):
    """A small compressed asset that would inflate far past the budget is never inflated
    much beyond it: decompression stops within one chunk of the budget."""
    recorder = _Recorder(monkeypatch)
    archive = _archive([("padding", b"\0" * (8 * 1024 * 1024), tarfile.REGTYPE),
                        ("antigravity", _image(4096), tarfile.REGTYPE)])
    assert len(archive) < 64 * 1024
    monkeypatch.setattr(prov, "MAX_EXPANDED_BYTES", 1024 * 1024)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)
    reader, = recorder.readers
    assert reader.size <= 1024 * 1024 + prov._CHUNK_BYTES


# ----------------------------------------------------- read_member: parser metadata bounds

def test_extension_record_bytes_boundary(monkeypatch):
    """A GNU long name's record is ``len(name) + 1`` bytes; the metadata bound is exact."""
    name = "n" * 300
    archive = _archive([(name, b"x", tarfile.REGTYPE), ("antigravity", _image(4096), tarfile.REGTYPE)])
    record = len(name) + 1
    for limit, passes in ((record + 1, True), (record, True), (record - 1, False)):
        monkeypatch.setattr(prov, "MAX_ARCHIVE_METADATA_BYTES", limit)
        if passes:
            assert _read(archive)[0] == sha256(_image(4096)).hexdigest()
        else:
            with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
                _read(archive)


def test_extension_records_are_summed_across_the_archive(monkeypatch):
    names = ["a" * 200, "b" * 200, "c" * 200]
    archive = _archive([*((name, b"x", tarfile.REGTYPE) for name in names),
                        ("antigravity", _image(4096), tarfile.REGTYPE)])
    total = sum(len(name) + 1 for name in names)
    monkeypatch.setattr(prov, "MAX_ARCHIVE_METADATA_BYTES", total)
    assert _read(archive)[0]
    monkeypatch.setattr(prov, "MAX_ARCHIVE_METADATA_BYTES", total - 1)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)


def test_header_entries_boundary(monkeypatch):
    archive = _archive([*((f"f{index}", b"x", tarfile.REGTYPE) for index in range(4)),
                        ("antigravity", _image(4096), tarfile.REGTYPE)])
    for limit, passes in ((6, True), (5, True), (4, False)):
        monkeypatch.setattr(prov, "MAX_ARCHIVE_ENTRIES", limit)
        if passes:
            assert _read(archive)[0]
        else:
            with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
                _read(archive)


def test_extension_headers_count_as_entries(monkeypatch):
    archive = _archive([("e" * 300, b"x", tarfile.REGTYPE), ("antigravity", _image(4096), tarfile.REGTYPE)])
    monkeypatch.setattr(prov, "MAX_ARCHIVE_ENTRIES", 3)  # long-name header, its member, agy
    assert _read(archive)[0]
    monkeypatch.setattr(prov, "MAX_ARCHIVE_ENTRIES", 2)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)


def test_consecutive_extension_headers_are_bounded(monkeypatch):
    """A global PAX header, then a member's own PAX header: a chain of two before it."""
    info = tarfile.TarInfo("antigravity")
    info.pax_headers = {"comment": "member"}
    archive = _archive([(info, _image(4096))], format=tarfile.PAX_FORMAT,
                       pax_headers={"comment": "global"})
    monkeypatch.setattr(prov, "MAX_EXTENSION_CHAIN", 2)
    assert _read(archive)[0]
    monkeypatch.setattr(prov, "MAX_EXTENSION_CHAIN", 1)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)


def test_a_long_run_of_empty_extension_headers_refuses_rather_than_recursing():
    """The parser recurses once per extension header; zero-length ones cost no metadata."""
    blocks = []
    for _ in range(4000):
        info = tarfile.TarInfo("././@LongLink")
        info.type = tarfile.GNUTYPE_LONGNAME
        info.size = 0
        blocks.append(info.tobuf(tarfile.GNU_FORMAT))
    member = tarfile.TarInfo("antigravity")
    member.size = 4
    raw = b"".join(blocks) + member.tobuf(tarfile.GNU_FORMAT) + b"img!" + b"\0" * (508 + 1024)
    import gzip
    archive = gzip.compress(raw)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)


def test_a_gnu_sparse_member_is_refused():
    info = tarfile.TarInfo("README")
    info.type = tarfile.GNUTYPE_SPARSE
    archive = _archive([(info, b"x"), ("antigravity", _image(4096), tarfile.REGTYPE)])
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)


@pytest.mark.parametrize("version", [("0", "1"), ("1", "0")])
def test_a_pax_sparse_member_is_refused(version):
    major, minor = version
    info = tarfile.TarInfo("README")
    info.pax_headers = {"GNU.sparse.major": major, "GNU.sparse.minor": minor,
                        "GNU.sparse.name": "README", "GNU.sparse.realsize": "1",
                        "GNU.sparse.map": "0,1"}
    archive = _archive([(info, b"1\n0\n1\n" + b"\0" * 506 + b"x"), ("antigravity", _image(4096), tarfile.REGTYPE)],
                       format=tarfile.PAX_FORMAT)
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        _read(archive)


def test_the_parser_hooks_exist_on_this_python():
    """The metadata bounds override these ``TarInfo`` methods; a rename must turn this red."""
    for name in ("_proc_member", "_proc_gnusparse_00", "_proc_gnusparse_01", "_proc_gnusparse_10"):
        assert callable(getattr(tarfile.TarInfo, name, None)), name


def test_a_truncated_or_corrupt_stream_is_unverified():
    archive = _archive([("antigravity", os.urandom(64 * 1024), tarfile.REGTYPE)])
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        prov.read_member(io.BytesIO(archive[: len(archive) // 2]), _asset(archive))
    broken = archive[:20] + bytes(b ^ 0xFF for b in archive[20:40]) + archive[40:]
    with pytest.raises(prov.ProvenanceError, match=prov.UNVERIFIED):
        prov.read_member(io.BytesIO(broken), _asset(broken))


def test_an_ordinary_archive_still_reads_and_hashes_every_compressed_byte():
    image = os.urandom(300 * 1024)
    archive = _archive([("README", b"readme", tarfile.REGTYPE), ("./antigravity", image, tarfile.REGTYPE)])
    assert prov.read_member(io.BytesIO(archive + b"trailing"), _asset(archive + b"trailing")) == (
        sha256(image).hexdigest(), None)
    assert prov.read_member(io.BytesIO(archive), _asset(archive), keep_bytes=True) == (
        sha256(image).hexdigest(), image)


# ----------------------------------------------------------------------- the verifier

@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_verifier_archive_member_boundary(tmp_path, monkeypatch, offset, passes):
    verifier = _verifier()
    image = _image(4096)
    path = tmp_path / "asset.tar.gz"
    path.write_bytes(_archive([("antigravity", image, tarfile.REGTYPE)]))
    record = {"upstream_asset_sha256": verifier.digest_file(path), "image_sha256": sha256(image).hexdigest()}
    monkeypatch.setattr(verifier, "MAX_MEMBER_BYTES", len(image) + offset)
    if passes:
        verifier.verify_archive(record, path)
    else:
        with pytest.raises(ValueError, match="archive member invalid"):
            verifier.verify_archive(record, path)


class _Body:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, size):
        return self.stream.read(min(size, 1000))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_verifier_download_boundary(tmp_path, monkeypatch, offset, passes):
    verifier = _verifier()
    body = b"a" * 5000
    monkeypatch.setattr(verifier, "MAX_ARCHIVE_BYTES", len(body) + offset)
    target = tmp_path / "asset"
    opener = lambda request, timeout: _Body(body)  # noqa: E731
    if passes:
        verifier.download_asset("https://example.invalid/a", target, opener=opener, sleep=lambda s: None)
        assert target.read_bytes() == body
    else:
        with pytest.raises(ValueError, match="release asset exceeds expected size"):
            verifier.download_asset("https://example.invalid/a", target, opener=opener, sleep=lambda s: None)


# ------------------------------------------------------------- the seat readers

def _subject(tmp_path, image):
    path = tmp_path / "bin" / "agy"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(image)
    path.chmod(0o755)
    return path


def _member(monkeypatch, image):
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {sha256(image).hexdigest(): "e" * 64})


@linux_memfd
@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_gh_admit_boundary(tmp_path, monkeypatch, offset, passes):
    image = _image(8192)
    path = _subject(tmp_path, image)
    _member(monkeypatch, image)
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", len(image) + offset)
    if passes:
        admission = gh.admit({"PATH": str(path.parent)}, subject_path=path)
        try:
            assert (admission.admission_class, admission.image.sha256) == (
                "release_qualified", sha256(image).hexdigest())
        finally:
            admission.close()
    else:
        with pytest.raises(ValueError, match=gh._CAPABILITY):
            gh.admit({"PATH": str(path.parent)}, subject_path=path)


@linux_memfd
@pytest.mark.parametrize("with_env", [False, True], ids=["release-only", "seat"])
@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_agy_integrity_check_boundary(tmp_path, monkeypatch, offset, passes, with_env):
    image = _image(8192)
    path = _subject(tmp_path, image)
    _member(monkeypatch, image)
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", len(image) + offset)
    env = {"PATH": str(path.parent)} if with_env else None
    if passes:
        admitted = agy_integrity.check(path, env)
        try:
            assert admitted.sha256 == sha256(image).hexdigest()
        finally:
            admitted.close()
    else:
        with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
            agy_integrity.check(path, env)


def _open_fds():
    return set(os.listdir("/proc/self/fd"))


@linux_memfd
@pytest.mark.parametrize("offset,passes", BOUNDARY)
def test_from_fd_streaming_boundary_without_an_fstat_precheck(tmp_path, monkeypatch, offset, passes):
    """``from_fd`` itself refuses past the bound, however the descriptor was checked."""
    image = _image(8192)
    path = _subject(tmp_path, image)
    monkeypatch.setattr(prov, "MAX_MEMBER_BYTES", len(image) + offset)
    before = _open_fds()
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        if passes:
            verified = gh.VerifiedImage.from_fd(fd, path=path)
            assert verified.sha256 == sha256(image).hexdigest()
            verified.close()
        else:
            with pytest.raises(ValueError, match=gh._CAPABILITY):
                gh.VerifiedImage.from_fd(fd, path=path)
    finally:
        os.close(fd)
    assert _open_fds() == before  # a refused image's memfd is closed


@linux_memfd
def test_from_fd_has_the_seals_mode_and_digest_of_from_bytes(tmp_path):
    import fcntl

    image = os.urandom(3 * 1024 * 1024 + 17)
    path = _subject(tmp_path, image)
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        streamed = gh.VerifiedImage.from_fd(fd, path=path)
    finally:
        os.close(fd)
    joined = gh.VerifiedImage.from_bytes(image, path)
    try:
        assert streamed.sha256 == joined.sha256 == sha256(image).hexdigest()
        assert streamed.path == path
        assert fcntl.fcntl(streamed.fd, F_GET_SEALS) == fcntl.fcntl(joined.fd, F_GET_SEALS)
        assert (stat.S_IMODE(os.fstat(streamed.fd).st_mode)
                == stat.S_IMODE(os.fstat(joined.fd).st_mode) == 0o500)
        assert os.fstat(streamed.fd).st_size == len(image)
        assert os.pread(streamed.fd, len(image) + 1, 0) == image
        assert gh._fd_digest(streamed.reopen()) == streamed.sha256
        with pytest.raises(OSError):
            os.pwrite(streamed.fd, b"x", 0)
    finally:
        streamed.close()
        joined.close()


@linux_memfd
def test_from_fd_rejects_a_memfd_whose_content_differs_from_what_was_hashed(tmp_path, monkeypatch):
    """The memfd is re-hashed after sealing; a mismatch refuses and closes it."""
    image = _image(8192)
    path = _subject(tmp_path, image)
    real_seal = gh._seal_image_memfd

    def tamper_then_seal(fd):
        os.pwrite(fd, b"!", 0)
        real_seal(fd)

    monkeypatch.setattr(gh, "_seal_image_memfd", tamper_then_seal)
    before = _open_fds()
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        with pytest.raises(ValueError, match=gh._CAPABILITY):
            gh.VerifiedImage.from_fd(fd, path=path)
    finally:
        os.close(fd)
    assert _open_fds() == before


def _peak(fn):
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        result = fn()
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


IMAGE_MIB = 24
# AGYFRESH §1.2: one sealed image plus at most 2 MiB per seat admission. The image lives in
# the memfd (shared memory, untraced); everything Python allocates must stay within 2 MiB.
# The streaming buffer is one 1 MiB chunk, and the re-hash reuses it.
OVERHEAD_CEILING = 2 * 1024 * 1024


@linux_memfd
def test_from_fd_peak_allocation_is_one_chunk_not_the_image(tmp_path):
    """Streaming and the sealed re-hash share one 1 MiB buffer (AGYFRESH §1.2)."""
    image = os.urandom(IMAGE_MIB * 1024 * 1024)
    path = _subject(tmp_path, image)
    del image
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        verified, peak = _peak(lambda: gh.VerifiedImage.from_fd(fd, path=path))
    finally:
        os.close(fd)
    verified.close()
    assert peak < OVERHEAD_CEILING, peak


@linux_memfd
@pytest.mark.parametrize("reader", ["gh.admit", "agy_integrity.check"])
def test_the_seat_readers_peak_allocation_stays_within_the_overhead_ceiling(tmp_path, monkeypatch, reader):
    """EC-RESTORE-2 and the §1.2 frozen peak: the seat reader holds no image copy in Python
    memory, and its overhead (stream buffer plus re-hash) stays within 2 MiB."""
    image = os.urandom(IMAGE_MIB * 1024 * 1024)
    path = _subject(tmp_path, image)
    _member(monkeypatch, image)
    del image
    if reader == "gh.admit":
        admission, peak = _peak(lambda: gh.admit({"PATH": str(path.parent)}, subject_path=path))
        admission.close()
    else:
        admitted, peak = _peak(lambda: agy_integrity.check(path, {"PATH": str(path.parent)}))
        admitted.close()
    assert peak < OVERHEAD_CEILING, peak


@linux_memfd
def test_a_non_member_reaches_lookup_as_the_one_sealed_image(tmp_path, monkeypatch):
    """The lookup path receives the sealed image of the single read, not a second copy."""
    image = _image(8192)
    path = _subject(tmp_path, image)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGES", {})
    seen = []

    def lookup(env, data, path_, **_kwargs):
        seen.append(data)
        raise gh.AdmissionMiss(data, path_)

    monkeypatch.setattr(q, "lookup", lookup)
    before = _open_fds()
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        gh.admit({"PATH": str(path.parent)}, subject_path=path)
    with pytest.raises(agy_integrity.AgyImageUnqualified):
        agy_integrity.check(path, {"PATH": str(path.parent)})
    assert [type(item) for item in seen] == [gh.VerifiedImage, gh.VerifiedImage]
    assert all(item.sha256 == sha256(image).hexdigest() and item.fd is None for item in seen)
    assert _open_fds() == before


@linux_memfd
def test_lookup_closes_an_image_it_was_given_when_self_qualification_is_off(tmp_path, monkeypatch):
    image = _image(8192)
    path = _subject(tmp_path, image)
    monkeypatch.setattr(q, "self_qualification_enabled", lambda: False)
    before = _open_fds()
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        verified = gh.VerifiedImage.from_fd(fd, path=path)
    finally:
        os.close(fd)
    with pytest.raises(ValueError, match=gh._CAPABILITY):
        q.lookup({}, verified, str(path))
    assert verified.fd is None
    assert _open_fds() == before
