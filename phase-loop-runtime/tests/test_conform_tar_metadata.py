import importlib
import io
import stat
import tarfile
from pathlib import Path

import pytest


@pytest.mark.parametrize("module_name", ("_outside_agent_canonical", "test_outside_agent_conform_evidence"), ids=("canonical", "evidence"))
@pytest.mark.parametrize("kind,mode", ((tarfile.REGTYPE, 0o664), (tarfile.REGTYPE, 0o775), (tarfile.DIRTYPE, 0o775)))
def test_conform_extraction_preserves_archive_permissions(module_name: str, kind: bytes, mode: int, tmp_path: Path) -> None:
    buffer = io.BytesIO()
    member = tarfile.TarInfo("member")
    member.type = kind
    member.mode = mode
    payload = b"historical package member"
    member.size = len(payload) if member.isfile() else 0
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        archive.addfile(member, io.BytesIO(payload) if member.isfile() else None)
    buffer.seek(0)
    destination = tmp_path / "destination"
    destination.mkdir()
    with tarfile.open(fileobj=buffer, mode="r") as archive:
        importlib.import_module(module_name)._extract_tar_archive(archive, destination)
    extracted = destination / "member"
    assert stat.S_IMODE(extracted.stat().st_mode) == mode
    if member.isfile():
        assert extracted.read_bytes() == payload
    else:
        assert extracted.is_dir()


@pytest.mark.parametrize("module_name", ("_outside_agent_canonical", "test_outside_agent_conform_evidence"), ids=("canonical", "evidence"))
@pytest.mark.parametrize("unsafe", ("absolute", "parent", "symlink", "hardlink", "character", "block", "fifo"))
def test_conform_extraction_rejects_unsafe_members_before_writing(module_name: str, unsafe: str, tmp_path: Path) -> None:
    buffer = io.BytesIO()
    invalid = tarfile.TarInfo("invalid")
    if unsafe == "absolute":
        invalid.name = str(tmp_path / "escaped")
    elif unsafe == "parent":
        invalid.name = "../escaped"
    else:
        invalid.type = {
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "character": tarfile.CHRTYPE,
            "block": tarfile.BLKTYPE,
            "fifo": tarfile.FIFOTYPE,
        }[unsafe]
        invalid.linkname = "../escaped"
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        archive.addfile(tarfile.TarInfo("valid"), io.BytesIO())
        archive.addfile(invalid)
    buffer.seek(0)
    destination = tmp_path / "destination"
    destination.mkdir()
    with tarfile.open(fileobj=buffer, mode="r") as archive:
        with pytest.raises(AssertionError):
            importlib.import_module(module_name)._extract_tar_archive(archive, destination)
    assert not any(destination.iterdir())
    assert not (tmp_path / "escaped").exists()
