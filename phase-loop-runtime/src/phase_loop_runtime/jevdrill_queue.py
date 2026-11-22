"""Durable delivery of already sanitized JEV Drill reports."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import threading
from contextlib import contextmanager, ExitStack
from pathlib import Path
from typing import Callable


class QueueCorruption(RuntimeError):
    """The queue is unavailable; preserve its files and restore verified state."""


class ReportQueue:
    MAX_BYTES = 16 * 1024 * 1024
    MAX_RECORDS = 10_000
    MAX_RECORD_BYTES = 1024 * 1024
    RETENTION_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, path: Path, *, sanitize: Callable[[dict], dict], clock=time.time):
        self.path = path
        self.sanitize = sanitize
        self.clock = clock
        self._objective_lock = threading.RLock()
        self._objective_storage = threading.local()
        self.corruption_marker = path.with_suffix(path.suffix + ".corrupt")
        if self.corruption_marker.exists():
            raise QueueCorruption("Report queue is blocked by recorded corruption")
        if os.name == "nt":
            from .windows_storage import BoundDirectory
            with BoundDirectory(path.parent, create_private=True) as bound:
                for name in (path.name, path.name + "-journal"):
                    fd = bound.open_record(name, create=True)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                bound.flush()
        else:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            path.chmod(0o600)
        with self._transaction() as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise QueueCorruption("Report queue failed integrity check")
            db.execute("PRAGMA secure_delete=ON")
            db.execute("""CREATE TABLE IF NOT EXISTS reports (
                project TEXT, workspace TEXT, event TEXT, task TEXT,
                payload TEXT, digest TEXT, created REAL, attempts INTEGER DEFAULT 0,
                retry_at REAL DEFAULT 0, state TEXT DEFAULT 'pending',
                PRIMARY KEY(project, workspace, event))""")
            db.execute("""CREATE TABLE IF NOT EXISTS tombstones (
                project TEXT, workspace TEXT, task TEXT,
                PRIMARY KEY(project, workspace, task))""")
            db.execute("""CREATE TABLE IF NOT EXISTS counters (
                reason TEXT PRIMARY KEY, count INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS objective_tombstones (
                project TEXT, workspace TEXT, objective TEXT,
                PRIMARY KEY(project, workspace, objective))""")
            db.execute("""CREATE TABLE IF NOT EXISTS objective_bindings (
                project TEXT, workspace TEXT, producer TEXT, objective TEXT,
                discovery TEXT, trace_digest TEXT,
                PRIMARY KEY(project, workspace, producer, discovery))""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_bindings (
                project TEXT, workspace TEXT, producer TEXT, objective TEXT,
                discovery TEXT, trace_digest TEXT, task TEXT, decision TEXT, run TEXT,
                PRIMARY KEY(project, workspace, task, decision, run))""")

    @contextmanager
    def objective_guard(self):
        from .file_lock import acquire_exclusive, release_exclusive
        lock_path = self.path.with_suffix(self.path.suffix + ".objective-lock")
        until = time.monotonic() + 5
        if not self._objective_lock.acquire(timeout=max(0, until - time.monotonic())):
            raise TimeoutError("Objective lifecycle lock deadline expired")
        with ExitStack() as stack:
            stack.callback(self._objective_lock.release)
            if os.name == "nt":
                from .windows_storage import BoundDirectory
                directory = stack.enter_context(BoundDirectory(self.path.parent, create_private=True, deadline=until))
                self._objective_storage.directory = directory
                stack.callback(delattr, self._objective_storage, "directory")
                fd = directory.open_record(lock_path.name, create=True)
            else:
                fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            stack.callback(os.close, fd)
            while True:
                try:
                    acquire_exclusive(fd, blocking=False)
                    break
                except BlockingIOError:
                    if time.monotonic() >= until:
                        raise TimeoutError("Objective lifecycle lock deadline expired")
                    time.sleep(0.01)
            try:
                yield
            finally:
                release_exclusive(fd)

    def bind_objective(self, envelope, ref):
        key = (envelope["project_id"], envelope["workspace_id"], envelope["harness_id"])
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM objective_tombstones WHERE project=? AND workspace=? AND objective=?",
                          (*key[:2], ref["work_objective_id"])).fetchone():
                raise ValueError("Objective is deleted")
            previous = db.execute("SELECT objective,trace_digest FROM objective_bindings WHERE project=? AND workspace=? AND producer=? AND discovery=?",
                                  (*key, ref["discovery_id"])).fetchone()
            if previous is not None and tuple(previous) != (ref["work_objective_id"], ref["trace_digest"]):
                raise ValueError("Discovery binding conflict")
            db.execute("INSERT OR IGNORE INTO objective_bindings VALUES (?,?,?,?,?,?)",
                       (*key, ref["work_objective_id"], ref["discovery_id"], ref["trace_digest"]))

    def objective_deleted(self, envelope, objective):
        with self._transaction() as db:
            return db.execute("SELECT 1 FROM objective_tombstones WHERE project=? AND workspace=? AND objective=?",
                              (envelope["project_id"], envelope["workspace_id"], objective)).fetchone() is not None

    def objective_bound(self, envelope, ref):
        with self._transaction() as db:
            key = (envelope["project_id"], envelope["workspace_id"])
            if db.execute("SELECT 1 FROM objective_tombstones WHERE project=? AND workspace=? AND objective=?",
                          (*key, ref["work_objective_id"])).fetchone():
                return False
            row = db.execute("SELECT objective,trace_digest FROM objective_bindings WHERE project=? AND workspace=? AND producer=? AND discovery=?",
                             (*key, envelope["harness_id"], ref["discovery_id"])).fetchone()
            return row is not None and tuple(row) == (ref["work_objective_id"], ref["trace_digest"])

    def bind_task(self, envelope, ref, task, decision, run):
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO task_bindings VALUES (?,?,?,?,?,?,?,?,?)",
                       (envelope["project_id"], envelope["workspace_id"], envelope["harness_id"],
                        ref["work_objective_id"], ref["discovery_id"], ref["trace_digest"],
                        task, decision, run))

    def delete_objective(self, project, workspace, objective):
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO objective_tombstones VALUES (?,?,?)",
                       (project, workspace, objective))
            db.execute("DELETE FROM objective_bindings WHERE project=? AND workspace=? AND objective=?",
                       (project, workspace, objective))

    def _mark_corrupt(self, bound=None):
        if os.name == "nt":
            from .windows_storage import BoundDirectory
            if bound is None:
                with BoundDirectory(self.path.parent, create_private=True) as binding:
                    return self._mark_corrupt(binding)
            try:
                bound.create_record(self.corruption_marker.name, b'{"status":"corrupt","automatic_action":"none"}\n')
            except FileExistsError:
                pass
            return
        try:
            fd = os.open(self.corruption_marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        with os.fdopen(fd, "w") as marker:
            marker.write('{"status":"corrupt","automatic_action":"none"}\n')
            marker.flush()
            os.fsync(marker.fileno())

    @contextmanager
    def _transaction(self):
        if self.corruption_marker.exists():
            raise QueueCorruption("Report queue is blocked by recorded corruption")
        storage = ExitStack()
        bound = None
        if os.name == "nt":
            from .windows_storage import BoundDirectory
            try:
                bound = getattr(self._objective_storage, "directory", None)
                if bound is None:
                    bound = storage.enter_context(BoundDirectory(self.path.parent, create_private=True))
                for name in (self.path.name, self.path.name + "-journal"):
                    storage.callback(os.close, bound.open_record(name, create=False))
            except BaseException:
                storage.close()
                raise
        try:
            db = sqlite3.connect(self.path, timeout=5)
        except BaseException:
            storage.close()
            raise
        db.row_factory = sqlite3.Row
        try:
            if bound is not None:
                if db.execute("PRAGMA journal_mode=PERSIST").fetchone()[0] != "persist":
                    raise QueueCorruption("Private persistent journal is unavailable")
                db.execute("PRAGMA synchronous=EXTRA")
                db.execute("PRAGMA temp_store=MEMORY")
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
            if bound is not None:
                bound.flush()
        except sqlite3.DatabaseError as error:
            db.rollback()
            code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                if not self.corruption_marker.exists():
                    self._mark_corrupt(bound)
                raise QueueCorruption("Report queue is corrupt; delivery stopped") from None
            raise
        except QueueCorruption:
            db.rollback()
            self._mark_corrupt(bound)
            raise
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
            storage.close()

    @staticmethod
    def _count(db, reason, count=1):
        db.execute("""INSERT INTO counters VALUES (?,?) ON CONFLICT(reason)
            DO UPDATE SET count=count+excluded.count""", (reason, count))

    def _expire(self, db):
        expired = db.execute("DELETE FROM reports WHERE created <= ?",
                             (self.clock() - self.RETENTION_SECONDS,)).rowcount
        if expired:
            self._count(db, "expired", expired)

    def enqueue(self, report: dict) -> str:
        # The caller's policy must remove secrets before any SQLite write.
        clean = self.sanitize(report)
        payload = json.dumps(clean, sort_keys=True, separators=(",", ":"), allow_nan=False)
        size = len(payload.encode("utf-8"))
        envelope, event = clean["envelope"], clean["event"]
        scope = (envelope["project_id"], envelope["workspace_id"])
        key = (*scope, event["event_id"])
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._transaction() as db:
            self._expire(db)
            if db.execute("SELECT 1 FROM tombstones WHERE project=? AND workspace=? AND task=?",
                          (*scope, event["task_id"])).fetchone():
                self._count(db, "deleted")
                return "deleted"
            previous = db.execute("SELECT digest FROM reports WHERE project=? AND workspace=? AND event=?", key).fetchone()
            if previous:
                result = "duplicate" if previous["digest"] == digest else "conflict"
                if result == "conflict":
                    self._count(db, result)
                return result
            count, used = db.execute("SELECT COUNT(*), COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM reports").fetchone()
            if size > self.MAX_RECORD_BYTES or count >= self.MAX_RECORDS or used + size > self.MAX_BYTES:
                self._count(db, "overflow")
                return "overflow"
            db.execute("""INSERT INTO reports(project,workspace,event,task,payload,digest,created)
                VALUES (?,?,?,?,?,?,?)""", (*key, event["task_id"], payload, digest, self.clock()))
            return "queued"

    def delete_task(self, project: str, workspace: str, task: str):
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO tombstones VALUES (?,?,?)", (project, workspace, task))
            count = db.execute("DELETE FROM reports WHERE project=? AND workspace=? AND task=?",
                               (project, workspace, task)).rowcount
            self._count(db, "deleted", count)

    def is_deleted(self, project: str, workspace: str, task: str) -> bool:
        with self._transaction() as db:
            return db.execute("SELECT 1 FROM tombstones WHERE project=? AND workspace=? AND task=?",
                              (project, workspace, task)).fetchone() is not None

    def deliver_one(self, send: Callable[[dict], dict]) -> str:
        # Serialize send with deletion: once deletion commits no producer can send
        # or enqueue this task. The bounded transport must finish within five seconds.
        with self._transaction() as db:
            self._expire(db)
            row = db.execute("""SELECT * FROM reports WHERE state='pending' AND retry_at<=?
                ORDER BY created, event LIMIT 1""", (self.clock(),)).fetchone()
            if row is None:
                return "empty"
            key = (row["project"], row["workspace"], row["event"])
            try:
                acknowledgment = send(json.loads(row["payload"]))
            except (OSError, TimeoutError, ValueError):
                acknowledgment = {}
            status = acknowledgment.get("status")
            matching = acknowledgment.get("event_id") == row["event"]
            if matching and status in ("accepted", "duplicate") and acknowledgment.get("durable") is True:
                db.execute("DELETE FROM reports WHERE project=? AND workspace=? AND event=?", key)
                return status
            if matching and status in ("conflict", "rejected") and acknowledgment.get("durable") is False:
                db.execute("UPDATE reports SET state=? WHERE project=? AND workspace=? AND event=?", (status, *key))
                self._count(db, status)
                return status
            attempts = row["attempts"] + 1
            delay = min(300, 2 ** min(attempts, 9))
            db.execute("""UPDATE reports SET attempts=?, retry_at=?
                WHERE project=? AND workspace=? AND event=?""", (attempts, self.clock() + delay, *key))
            return "retry"

    def status(self) -> dict:
        with self._transaction() as db:
            self._expire(db)
            return {
                "records": db.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
                "dispositions": dict(db.execute("SELECT reason,count FROM counters")),
            }
