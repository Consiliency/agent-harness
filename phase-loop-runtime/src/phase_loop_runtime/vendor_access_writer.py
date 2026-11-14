"""POSIX cooperative writer exclusion for one trusted private journal directory.

This does not authenticate source_host or exclude writers using another directory
or host. Deployment still needs the reviewed machine/principal binding. Every
journal mutation/recovery caller must use this same directory lock protocol.
"""
from contextlib import contextmanager
import fcntl
import os
import stat


@contextmanager
def private_directory_writer(directory: int):
    """Nonblocking flock on the directory inode; never create/unlink a lock file.

    Open a new file description so nested calls cannot silently share/release a
    lock through dup(). The supplied descriptor must already name a trusted root.
    """
    fd = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError('unsafe_writer_directory')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        # Closing this independent description releases its lock even on error.
        os.close(fd)
