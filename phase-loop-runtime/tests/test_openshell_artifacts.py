"""Source-only fixtures; no provider, endpoint, SSH, or deployment."""
import base64
from dataclasses import asdict, replace
import os
import time
import zlib

import pytest

from phase_loop_runtime.openshell_artifacts import (
    Bound, Identity, Limits, Refused, SourceFile, canonical, digest,
    git, init_tree, native_witness, prepare_source, scan, stage_files, validate_result,
)


@pytest.fixture
def bound():
    return Bound(time.monotonic() + 20, lambda: False)


@pytest.fixture
def limits():
    return Limits(source_bytes=100000, file_bytes=50000, files=20,
                  patch_bytes=100000, output_bytes=300000)


@pytest.fixture
def repository(tmp_path, bound, limits):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--template=", bound=bound, cap=limits.output_bytes)
    (root / "owned.txt").write_bytes(b"before\n")
    (root / "other.txt").write_bytes(b"unchanged\n")
    git(root, "add", ".", bound=bound, cap=limits.output_bytes)
    git(root, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "commit", "-m", "fixture", bound=bound, cap=limits.output_bytes)
    base = git(root, "rev-parse", "HEAD", bound=bound, cap=limits.output_bytes).decode().strip()
    return root, base


@pytest.fixture
def bundle(repository, limits, bound):
    root, base = repository
    return prepare_source(root, base, ("owned.txt", "new.bin"), limits, bound)


def identity_for(bundle):
    return Identity("1" * 64, bundle.base, bundle.tree, bundle.sha256, "2" * 32,
                    "generation-one", "3" * 64, "4" * 64,
                    digest(canonical(asdict(bundle.limits))))


def native(text="done"):
    return canonical({"type": "system", "subtype": "init", "apiKeySource": "none",
                      "session_id": "native-session"}) + b"\n" + canonical({
        "type": "result", "subtype": "success", "is_error": False,
        "session_id": "native-session", "result": text}) + b"\n"


def result(bundle, patch, witness=None):
    witness = native() if witness is None else witness
    return {"identity": asdict(identity_for(bundle)), "patch": base64.b64encode(patch).decode(),
            "patch_sha256": digest(patch), "patch_size": len(patch),
            "native": base64.b64encode(witness).decode(), "native_sha256": digest(witness),
            "test_claim": "passed", "exit_status": 0, "truncated": False}


def patch_for(bundle, tmp_path, bound, files):
    root = tmp_path / "patch-tree"
    init_tree(root, bundle, bound)
    stage_files(root, files, bundle.limits, bound)
    return git(root, "diff", "--cached", "--binary", "--full-index", "--no-renames",
               bundle.tree, bound=bound, cap=bundle.limits.patch_bytes)


def test_clean_bundle_binary_quarantine(bundle, repository, tmp_path, bound):
    files = tuple(replace(f, data=b"after\0binary\xff\n") if f.path == "owned.txt" else f
                  for f in bundle.files) + (SourceFile("new.bin", 0o100644, b"\0\xff"),)
    patch = patch_for(bundle, tmp_path, bound, files)
    receipt = validate_result(identity_for(bundle), canonical(result(bundle, patch)), bundle,
                              tmp_path / "quarantine", bound)
    assert receipt.path.read_bytes() == patch
    assert receipt.sha256 == digest(patch)
    assert "isolated_same_base_retest" in receipt.required_next_step
    assert (repository[0] / "owned.txt").read_bytes() == b"before\n"
    assert not (repository[0] / "new.bin").exists()


@pytest.mark.parametrize("kind", ["working", "index", "untracked", "ignored"])
def test_dirty_source_refused(repository, limits, bound, kind):
    root, base = repository
    if kind in ("working", "index"):
        (root / "owned.txt").write_text("dirty")
        if kind == "index":
            git(root, "add", ".", bound=bound, cap=limits.output_bytes)
            (root / "owned.txt").write_text("before\n")
    else:
        (root / ".git/info").mkdir()
        (root / ".git/info/exclude").write_text("extra\n")
        (root / "extra").write_text("ignored is not clean")
    with pytest.raises(Refused):
        prepare_source(root, base, ("owned.txt",), limits, bound)


@pytest.mark.parametrize("path", ["../escape", "/absolute", ".git/config", "x/.GiT/a", "x//a",
                                  "x/../a", "a\\b", ".gitmodules", ".gitattributes", "-bad/../a"])
def test_bundle_paths_refused(bundle, path):
    with pytest.raises(Refused):
        replace(bundle, files=(SourceFile(path, 0o100644, b"x"),)).validate()


@pytest.mark.parametrize("mode", [0o120000, 0o160000, 0o100664, 0o104755])
def test_bundle_modes_refused(bundle, mode):
    with pytest.raises(Refused):
        replace(bundle, files=(SourceFile("owned.txt", mode, b"x"),)).validate()


def test_lfs_and_limits(bundle):
    for entry in (SourceFile("owned.txt", 0o100644, b"version https://git-lfs.github.com/spec/v1\n"),
                  SourceFile("owned.txt", 0o100644, b"x" * (bundle.limits.file_bytes + 1))):
        with pytest.raises(Refused):
            replace(bundle, files=(entry,)).validate()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "mode"])
def test_materialized_special_files_refused(tmp_path, bound, limits, kind):
    root = tmp_path / "unsafe"
    root.mkdir()
    path = root / "file"
    if kind == "symlink":
        path.symlink_to("/etc/passwd")
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.write_bytes(b"x")
        if kind == "hardlink":
            os.link(path, root / "another")
        else:
            path.chmod(0o4777)
    with pytest.raises(Refused):
        scan(root, limits, bound)


@pytest.mark.parametrize("field", list(Identity.__dataclass_fields__))
def test_forged_identity_refused(bundle, tmp_path, bound, field):
    value = result(bundle, b"")
    value["identity"][field] = "forged"
    with pytest.raises(Refused):
        validate_result(identity_for(bundle), canonical(value), bundle, tmp_path / "q", bound)
    assert not (tmp_path / "q").exists()


@pytest.mark.parametrize("header", [
    b"new file mode 160000 100644", b"new file mode 120000 100644",
    b"index a..b 160000 x", b"index a..b 120000 x",
    b"index a..b 100644 x", b"index a..b 100664", b"index a..b ",
    b"index", b"index a", b"index a..z", b"index a..b 0100644",
] + [prefix + suffix for prefix in
     (b"new file mode", b"deleted file mode", b"old mode", b"new mode")
     for suffix in (b"", b" 100644 x", b" 100664", b" 0100644", b" 100644 ")])
def test_mode_header_grammar(bundle, tmp_path, bound, monkeypatch, header):
    import phase_loop_runtime.openshell_artifacts as artifacts
    def forbidden_git(*args, **kwargs):
        pytest.fail("invalid header reached Git")
    monkeypatch.setattr(artifacts, "git", forbidden_git)
    with pytest.raises(Refused, match="patch_mode_unsupported"):
        validate_result(identity_for(bundle), canonical(result(bundle, header + b"\n")),
                        bundle, tmp_path / "q", bound)


@pytest.mark.parametrize("form", ["mode", "index"])
def test_nonregular_patch_refused(bundle, tmp_path, bound, form):
    oid = "a" * 40
    mode = "new file mode 160000 100644" if form == "mode" else "new file mode 100644"
    index_mode = "" if form == "mode" else " 160000 x"
    patch = (f"diff --git a/new.bin b/new.bin\n{mode}\n"
             f"index {'0' * 40}..{oid}{index_mode}\n"
             f"--- /dev/null\n+++ b/new.bin\n@@ -0,0 +1 @@\n"
             f"+Subproject commit {oid}\n").encode()
    with pytest.raises(Refused):
        validate_result(identity_for(bundle), canonical(result(bundle, patch)),
                        bundle, tmp_path / "q", bound)
    assert not (tmp_path / "q").exists()


@pytest.mark.parametrize("kind", ["gitlink", "symlink", "stage", "path", "content", "mode"])
def test_index_independently_checked(bundle, tmp_path, bound, monkeypatch, kind):
    import phase_loop_runtime.openshell_artifacts as artifacts
    original = artifacts.init_tree
    def altered(root, bundle, bound):
        original(root, bundle, bound)
        data = (root / "other.txt").read_bytes() if kind == "mode" else b"different"
        oid = git(root, "hash-object", "-w", "--stdin", data=data,
                  bound=bound, cap=bundle.limits.output_bytes).decode().strip()
        mode = {"gitlink": "160000", "symlink": "120000", "mode": "100755"}.get(kind, "100644")
        path = ".gitattributes" if kind == "path" else "other.txt"
        stage = "2" if kind == "stage" else "0"
        git(root, "update-index", "--index-info", data=f"{mode} {oid} {stage}\t{path}\n".encode(),
            bound=bound, cap=bundle.limits.output_bytes)
    monkeypatch.setattr(artifacts, "init_tree", altered)
    with pytest.raises(Refused, match="index_|path_unsupported"):
        validate_result(identity_for(bundle), canonical(result(bundle, b"")),
                        bundle, tmp_path / "q", bound)
    assert not (tmp_path / "q").exists()


@pytest.mark.parametrize("kind", ["copy", "rename"])
def test_transfer_headers_refused(bundle, tmp_path, bound, kind):
    patch = (f"diff --git a/other.txt b/new.bin\nsimilarity index 100%\n"
             f"{kind} from other.txt\n{kind} to new.bin\n").encode()
    with pytest.raises(Refused, match="patch_transfer_unsupported"):
        validate_result(identity_for(bundle), canonical(result(bundle, patch)),
                        bundle, tmp_path / "q", bound)


@pytest.mark.parametrize("reason", ["cancelled", "end_reached"])
def test_late_refusal_removes_quarantine(bundle, tmp_path, reason):
    q = tmp_path / "q"
    class LateBound:
        end = time.monotonic() + 20
        def check(self):
            if (q / "untrusted.patch").exists():
                raise Refused(reason)
            return self.end - time.monotonic()
    with pytest.raises(Refused, match=reason):
        validate_result(identity_for(bundle), canonical(result(bundle, b"")), bundle, q, LateBound())
    assert not q.exists()


def test_existing_quarantine_preserved(bundle, tmp_path, bound):
    q = tmp_path / "q"
    q.mkdir()
    (q / "untrusted.patch").write_bytes(b"user data")
    with pytest.raises(FileExistsError):
        validate_result(identity_for(bundle), canonical(result(bundle, b"")), bundle, q, bound)
    assert (q / "untrusted.patch").read_bytes() == b"user data"


@pytest.mark.parametrize("kind", ["text", "executable", "mode-only", "delete"])
def test_supported_file_changes(bundle, tmp_path, bound, kind):
    files = tuple(replace(f, data=f.data if kind == "mode-only" else b"after\n",
                          mode=0o100755 if kind in ("executable", "mode-only") else f.mode)
                  if f.path == "owned.txt" else f for f in bundle.files
                  if kind != "delete" or f.path != "owned.txt")
    patch = patch_for(bundle, tmp_path, bound, files)
    receipt = validate_result(identity_for(bundle), canonical(result(bundle, patch)),
                              bundle, tmp_path / "q", bound)
    assert receipt.path.read_bytes() == patch


@pytest.mark.parametrize("field,value", [("patch_sha256", "0" * 64), ("patch_size", 4),
                                        ("truncated", True), ("test_claim", "not_run"),
                                        ("exit_status", False), ("command", "touch /tmp/no")])
def test_malformed_result_refused(bundle, tmp_path, bound, field, value):
    envelope = result(bundle, b"")
    envelope[field] = value
    with pytest.raises(Refused):
        validate_result(identity_for(bundle), canonical(envelope), bundle, tmp_path / "q", bound)


@pytest.mark.parametrize("witness", [b"", native()[:-1], native() + native(),
                                    native().replace(b'"success"', b'"error"'),
                                    native().replace(b'"none"', b'"api_key"'),
                                    native().replace(b'"is_error":false', b'"is_error":true'),
                                    b'not json\n', native() + b'{}\n'])
def test_native_witness_refused(witness):
    with pytest.raises(Refused):
        native_witness(witness)


def test_wrong_native_session():
    witness = native().splitlines()
    witness[1] = witness[1].replace(b"native-session", b"other-session")
    with pytest.raises(Refused):
        native_witness(b"\n".join(witness) + b"\n")


def test_ownership_refused(bundle, tmp_path, bound):
    files = tuple(replace(f, data=b"escape\n") if f.path == "other.txt" else f for f in bundle.files)
    patch = patch_for(bundle, tmp_path, bound, files)
    with pytest.raises(Refused, match="ownership_escape"):
        validate_result(identity_for(bundle), canonical(result(bundle, patch)), bundle, tmp_path / "q", bound)


def test_traversal_patch_refused(bundle, tmp_path, bound):
    patch = b"diff --git a/../outside b/../outside\nnew file mode 100644\n--- /dev/null\n+++ b/../outside\n@@ -0,0 +1 @@\n+bad\n"
    with pytest.raises(Refused):
        validate_result(identity_for(bundle), canonical(result(bundle, patch)), bundle, tmp_path / "q", bound)
    assert not (tmp_path / "outside").exists()


def test_bounds_and_oversize(bundle, tmp_path, bound):
    for bad_bound in (Bound(time.monotonic() - 1, lambda: False), Bound(bound.end, lambda: True)):
        with pytest.raises(Refused):
            validate_result(identity_for(bundle), canonical(result(bundle, b"")), bundle, tmp_path / "q", bad_bound)
    with pytest.raises(Refused):
        validate_result(identity_for(bundle), b" " * (bundle.limits.output_bytes + 1), bundle, tmp_path / "q", bound)
    patch = b"x" * (bundle.limits.patch_bytes + 1)
    with pytest.raises(Refused):
        validate_result(identity_for(bundle), canonical(result(bundle, patch)), bundle, tmp_path / "q", bound)


def test_host_config_hooks_filters_not_loaded(repository, limits, bound, tmp_path, monkeypatch):
    root, base = repository
    marker = tmp_path / "should-not-exist"
    hook = root / ".git/hooks/query-fsmonitor"
    hook.parent.mkdir()
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    with (root / ".git/config").open("a") as stream:
        stream.write(f"\n[core]\n fsmonitor = {hook}\n[include]\n path = /nonexistent\n")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hook))
    assert prepare_source(root, base, ("owned.txt",), limits, bound).base == base
    assert not marker.exists()


def test_duplicate_json_fields_rejected(bundle, tmp_path, bound):
    wire = canonical(result(bundle, b""))
    wire = b'{"truncated":false,' + wire[1:]
    with pytest.raises(Refused):
        validate_result(identity_for(bundle), wire, bundle, tmp_path / "q", bound)


@pytest.mark.parametrize("header", [b"delta 10", b"literal 50001", b"new file mode 120000",
                                   b"new mode 100664", b"index a..b 160000"])
def test_unsupported_patch_expansion_or_modes(bundle, tmp_path, bound, header):
    with pytest.raises(Refused, match="binary_|patch_mode"):
        validate_result(identity_for(bundle), canonical(result(bundle, header + b"\n")),
                        bundle, tmp_path / "q", bound)


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_committed_link_or_submodule_refused(repository, limits, bound, mode):
    root, base = repository
    oid = base if mode == "160000" else git(root, "hash-object", "-w", "--stdin",
                                            data=b"owned.txt", bound=bound, cap=limits.output_bytes).decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", f"{mode},{oid},unsupported",
        bound=bound, cap=limits.output_bytes)
    git(root, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "commit", "-m", "unsupported fixture", bound=bound, cap=limits.output_bytes)
    base = git(root, "rev-parse", "HEAD", bound=bound, cap=limits.output_bytes).decode().strip()
    with pytest.raises(Refused, match="entry_unsupported"):
        prepare_source(root, base, ("owned.txt",), limits, bound)


def test_native_truncation_claim_and_token_stop():
    for extra in ({"truncated": True}, {"stop_reason": "max_tokens"}):
        import json
        lines = native().splitlines()
        terminal = json.loads(lines[-1])
        terminal.update(extra)
        with pytest.raises(Refused):
            native_witness(lines[0] + b"\n" + canonical(terminal) + b"\n")


@pytest.mark.parametrize("kind", ["expansion", "truncated", "trailing", "bad-length"])
def test_binary_literal_payload_checked_before_git(bundle, tmp_path, bound, monkeypatch, kind):
    import phase_loop_runtime.openshell_artifacts as artifacts
    data = b"\0" * 40000
    compressed = zlib.compress(data)
    if kind == "truncated":
        compressed = compressed[:-1]
    elif kind == "trailing":
        compressed += b"extra"
    lines = []
    for offset in range(0, len(compressed), 52):
        chunk = compressed[offset:offset + 52]
        length = len(chunk)
        prefix = length + 64 if length <= 26 else length + 70
        lines.append(bytes([prefix]) + base64.b85encode(chunk.ljust((length + 3) // 4 * 4, b"\0")))
    if kind == "bad-length":
        lines[0] = b"A" + lines[0][1:]
    size = 1 if kind == "expansion" else len(data)
    patch = f"literal {size}\n".encode() + b"\n".join(lines) + b"\n\n"
    def forbidden_git(*args, **kwargs):
        pytest.fail("invalid binary data reached Git")
    monkeypatch.setattr(artifacts, "git", forbidden_git)
    with pytest.raises(Refused, match="binary_"):
        validate_result(identity_for(bundle), canonical(result(bundle, patch)), bundle, tmp_path / "q", bound)
    assert not (tmp_path / "q").exists()
