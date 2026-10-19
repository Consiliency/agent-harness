"""Durable local T3 orchestration around the sole ReviewCoordinator authority.

No provider or MCP execution. Private state must be outside the dispatched
checkout, on a local filesystem with SQLite locking, and excluded from reviewer
writes by the deploying host. Same-UID trust is not OS isolation/authentication.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import stat

from . import review_t3 as t
from .review_contract import Admission, CoordinatorPolicy, FrozenRequest, ReviewCoordinator, ReviewRefused, canonical_digest, canonical_json

JOURNAL_VERSION = "t3_journal.v1"
LOCK_TIMEOUT_SECONDS = 60
_POLICY_RULES = {"version": "t3_non_gating_policy.v1", "eligibility": "NON_GATING",
                 "provenance": ["HOST_ATTESTED"], "governed_provenance": [],
                 "correction": "digest_bound_charter", "unusable_seat_blocks": True,
                 "deferred": False, "host_scope": "digest_bound_charter"}


class T3NonGatingPolicy:
    """Shipped structural same-UID host policy; never governed admission."""

    identity = canonical_digest("policy", _POLICY_RULES)

    def __init__(self, charter_lookup):
        self._charter = charter_lookup

    def authorize(self, context: dict) -> Admission:
        charter = self._charter(context["brief_digest"])
        return Admission(correction_allowed=charter["allow_correction"])

    def admit_transport(self, request: FrozenRequest, registration: dict) -> bool:
        charter = self._charter(request.value["brief_digest"])
        identity = registration.get("identity")
        return (registration.get("provenance") == "HOST_ATTESTED" and
                registration.get("host_identity") == charter["host_scope"]["parent_thread_id"] and
                type(identity) is dict and set(identity) == set(t.IDENTITY_KEYS) and
                all(t.text_id(v) for v in identity.values()))

    def allow_deferred(self, request: FrozenRequest, finding_key: str) -> bool:
        return False


class _RestrictedPolicy:
    """Enforce RT3 restrictions before coordinator request persistence."""

    def __init__(self, injected, structural):
        self.identity = injected.identity
        self.injected, self.structural = injected, structural

    def authorize(self, context):
        permitted = self.structural.authorize(context)
        decision = self.injected.authorize(json.loads(canonical_json(context)))
        t.require(type(decision) is Admission and decision.eligibility == "NON_GATING" and
                  decision.governed_provenance == () and decision.permitted_provenance == ("HOST_ATTESTED",) and
                  decision.unusable_seat_blocks is True and
                  (not decision.correction_allowed or permitted.correction_allowed))
        return decision

    def admit_transport(self, request, registration):
        return self.structural.admit_transport(request, registration) and self.injected.admit_transport(request, registration) is True

    def allow_deferred(self, request, finding_key):
        return False


class T3ReviewService:
    """One journal beside reviews.sqlite3; coordinator commits precede intents.

    Every HostAction is private data for the trusted driving host. An offered
    action without registration is unresolved, even if the caller never received
    it. Production never re-emits it. Local retries preserve the saved request.
    """

    def __init__(self, private_directory: Path, *, host_scope: dict, policy: CoordinatorPolicy | None = None):
        self.host_scope = t.host_scope(host_scope)
        self.directory = Path(private_directory).resolve()
        self._outside_checkout()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "t3-journal.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self._transaction() as db:
            for statement in (
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS charters (digest TEXT PRIMARY KEY, raw BLOB NOT NULL)",
                "CREATE TABLE IF NOT EXISTS intents (binding TEXT PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL, capabilities BLOB NOT NULL, profile TEXT NOT NULL, state TEXT NOT NULL, registration BLOB, registration_observation BLOB)",
                "CREATE TABLE IF NOT EXISTS deliveries (binding TEXT PRIMARY KEY, body BLOB NOT NULL, envelope BLOB NOT NULL, observations BLOB NOT NULL, evidence BLOB NOT NULL, digest TEXT NOT NULL)",
            ):
                db.execute(statement)
            for key, value in (("version", JOURNAL_VERSION), ("host_scope", canonical_json(self.host_scope).decode())):
                db.execute("INSERT OR IGNORE INTO metadata VALUES (?, ?)", (key, value))
                t.require(db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()[0] == value)
        structural = T3NonGatingPolicy(self.charter)
        self.coordinator = ReviewCoordinator(self.directory, policy=_RestrictedPolicy(policy or structural, structural))

    def _outside_checkout(self):
        t.require(not self.directory.is_relative_to(Path(self.host_scope["checkout"])), "binding_mismatch")

    @contextmanager
    def _transaction(self):
        self._outside_checkout()
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=LOCK_TIMEOUT_SECONDS, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except sqlite3.Error:
            if db is not None:
                db.rollback()
            raise ReviewRefused("result_unavailable") from None
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    def charter(self, digest: str) -> dict:
        with self._transaction() as db:
            row = db.execute("SELECT raw FROM charters WHERE digest=?", (digest,)).fetchone()
        t.require(row is not None and t.sha(row[0]) == digest)
        value = t.validate_charter(json.loads(row[0]))
        t.require(canonical_json(value) == row[0] and value["host_scope"] == self.host_scope)
        return value

    def _request(self, binding):
        request = self.coordinator.load_request(binding)
        self.charter(request.value["brief_digest"])
        admission = request.value["admission"]
        t.require(admission["eligibility"] == "NON_GATING" and admission["governed_provenance"] == [] and
                  admission["permitted_provenance"] == ["HOST_ATTESTED"])
        return request

    def request(self, *, charter: dict, **request_inputs) -> FrozenRequest:
        charter = t.validate_charter(charter)
        t.require(charter["host_scope"] == self.host_scope and "brief" not in request_inputs)
        raw = canonical_json(charter)
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO charters VALUES (?, ?)", (t.sha(raw), raw))
            t.require(db.execute("SELECT raw FROM charters WHERE digest=?", (t.sha(raw),)).fetchone()[0] == raw)
        # Orphan charters cannot dispatch. create_request is the authority and
        # must commit before prepare can persist/offer an intent.
        return self.coordinator.create_request(brief=raw, **request_inputs)

    def _intent(self, db, binding):
        row = db.execute("SELECT * FROM intents WHERE binding=?", (binding,)).fetchone()
        t.require(row is not None, "result_unavailable")
        t.require(t.sha(row["payload"]) == row["digest"] and row["profile"] == t.PROFILE_VERSION, "result_unavailable")
        payload = json.loads(row["payload"])
        t.require(payload.get("clientRequestId") == "typed-review-v1-" + binding and
                  row["state"] in ("prepared", "offered", "registered"), "result_unavailable")
        return row, payload

    def prepare(self, binding: str, *, target: dict, capabilities: dict) -> t.HostAction:
        self._request(binding)
        prompt = self.coordinator.build_request(binding).prompt
        payload = t.dispatch_payload(binding, prompt, target, capabilities)
        encoded = canonical_json(payload)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM intents WHERE binding=?", (binding,)).fetchone()
            if row is None:
                db.execute("INSERT INTO intents VALUES (?, ?, ?, ?, ?, 'prepared', NULL, NULL)",
                           (binding, encoded, t.sha(encoded), t.relay_json(capabilities), t.PROFILE_VERSION))
            else:
                t.require(row["payload"] == encoded, "delivery_conflict")
        return self._offer(binding)

    def _offer(self, binding):
        with self._transaction() as db:
            row, payload = self._intent(db, binding)
            if row["state"] == "prepared":
                db.execute("UPDATE intents SET state='offered' WHERE binding=?", (binding,))
                return t.HostAction("dispatch", binding, "delegate_task", payload, row["digest"])
            if row["registration"] is not None:
                identity = json.loads(row["registration"])
                return t.HostAction("recover", binding, "task_status", {"taskId": identity["taskId"]}, row["digest"])
            # This constant is false in the production profile. A test may patch
            # it to model an established fake host guarantee; no caller JSON,
            # policy, CLI flag or environment can establish such a guarantee.
            if t.REDISPATCH_CAPABLE:
                return t.HostAction("dispatch", binding, "delegate_task", payload, row["digest"])
            return t.HostAction("unresolved", binding, payload_digest=row["digest"])

    def register(self, binding: str, registration: dict) -> dict:
        self._request(binding)
        t.require(type(registration) is dict and set(registration) == {
            "schema", "request_binding", "client_request_id", "payload_digest", "host_scope", "observation"})
        with self._transaction() as db:
            row, payload = self._intent(db, binding)
            t.require(row["state"] in ("offered", "registered"))
            t.require(registration["schema"] == t.REGISTRATION_VERSION and registration["request_binding"] == binding and
                      registration["host_scope"] == self.host_scope and registration["payload_digest"] == row["digest"] and
                      registration["client_request_id"] == payload["clientRequestId"])
            wrapper = registration["observation"]
            t.require(type(wrapper) is dict and wrapper.get("tool") in ("delegate_task", "task_status"))
            args, result = t.observation(wrapper, wrapper["tool"])
            identity = t.registered_identity(result, payload["target"])
            t.require(args == (payload if wrapper["tool"] == "delegate_task" else {"taskId": identity["taskId"]}))
            encoded = canonical_json(identity)
            t.require(row["registration"] is None or row["registration"] == encoded, "delivery_conflict")
            # Commit the immutable original identity before coordinator registration;
            # any interrupted coordinator call is repaired idempotently on intake.
            if row["registration"] is None:
                db.execute("UPDATE intents SET state='registered', registration=?, registration_observation=? WHERE binding=?",
                           (encoded, t.relay_json(registration), binding))
        digest = self._register_coordinator(binding, identity)
        return {"request_binding": binding, "registration_digest": digest, "provenance": "HOST_ATTESTED"}

    def _register_coordinator(self, binding, identity):
        return self.coordinator.register_transport(binding, host_identity=self.host_scope["parent_thread_id"],
                provenance="HOST_ATTESTED", identity={k: identity[k] for k in t.IDENTITY_KEYS})

    def _delivery(self, db, binding):
        row = db.execute("SELECT * FROM deliveries WHERE binding=?", (binding,)).fetchone()
        if row is not None:
            t.require(row["digest"] == self._delivery_digest(row["body"], row["envelope"], row["evidence"]), "result_unavailable")
        return row

    @staticmethod
    def _delivery_digest(body, envelope, evidence):
        return t.sha(canonical_json([t.sha(body), t.sha(envelope), t.sha(evidence)]))

    def intake(self, binding: str, package: dict):
        request = self._request(binding)
        with self._transaction() as db:
            row, _ = self._intent(db, binding)
            t.require(row["registration"] is not None, "result_unavailable")
            identity = json.loads(row["registration"])
        recovered = t.recover(binding, identity, self.host_scope, package)
        evidence = recovered.evidence_digests
        # Host evidence is validated before journal persistence, just as the
        # coordinator validates it before claiming delivery. No review validation
        # or receipt logic lives here.
        permitted = {e["handle"]: e["sha256"] for e in request.value["evidence"]}
        t.require(type(evidence) is dict and all(type(k) is str and k in permitted and
                  type(v) is str and v == permitted[k] for k, v in evidence.items()))
        encoded_evidence = canonical_json(evidence)
        digest = self._delivery_digest(recovered.body, recovered.envelope, encoded_evidence)
        self._register_coordinator(binding, identity)
        with self._transaction() as db:
            previous = self._delivery(db, binding)
            t.require(previous is None or previous["digest"] == digest, "delivery_conflict")
            db.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, ?, ?, ?)",
                       (binding, recovered.body, recovered.envelope, recovered.observations, encoded_evidence, digest))
        return self._accept(binding, revalidate=previous is not None)

    def _accept(self, binding, *, revalidate):
        with self._transaction() as db:
            row = self._delivery(db, binding)
            t.require(row is not None, "result_unavailable")
        record = self.coordinator.ingest(binding, body=row["body"], transport=row["envelope"],
                                         evidence_digests=json.loads(row["evidence"]))
        return self.coordinator.revalidate(binding) if revalidate else record

    def resume(self, binding: str):
        self._request(binding)
        with self._transaction() as db:
            row, _ = self._intent(db, binding)
            identity = json.loads(row["registration"]) if row["registration"] is not None else None
            delivery = self._delivery(db, binding)
        if identity is not None:
            self._register_coordinator(binding, identity)
        if delivery is not None:
            return self._accept(binding, revalidate=True)
        return self._offer(binding)

    def correction(self, original_binding: str, *, capabilities: dict) -> t.HostAction:
        original = self._request(original_binding)
        t.require(original.value["replaces_record_id"] is None, "result_unavailable")
        with self._transaction() as db:
            row, payload = self._intent(db, original_binding)
        # Fresh host-observed capabilities must support the unchanged target.
        t.dispatch_payload(original_binding, "capability preflight", payload["target"], capabilities)
        correction = self.coordinator.correction_request(original_binding)
        if correction is None:
            current = self.coordinator.revalidate(original_binding)
            t.require(not current.content_valid and current.outcome == "invalid_content" and
                      current.rejection_code in {"invalid_json", "schema_mismatch", "binding_mismatch",
                                                 "semantic_mismatch", "limit_exceeded"}, "result_unavailable")
            try:
                correction = self.coordinator.reserve_correction(original_binding)
            except ReviewRefused:
                # A concurrent reserver may have won; recover only its request.
                correction = self.coordinator.correction_request(original_binding)
                if correction is None:
                    raise
        with self._transaction() as db:
            t.require(self._delivery(db, correction.binding) is None, "result_unavailable")
        return self.prepare(correction.binding, target=payload["target"], capabilities=capabilities)


def read_private_json(path: Path):
    """Bounded private JSON; duplicate keys and lossy surrogate substitution refuse."""
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        t.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                  info.st_mode & 0o077 == 0 and info.st_size <= t.MAX_RETAINED_BYTES, "result_unavailable")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(t.MAX_RETAINED_BYTES + 1)
        t.require(len(raw) <= t.MAX_RETAINED_BYTES, "result_unavailable")
        def pairs(items):
            result = {}
            for key, value in items:
                t.require(key not in result, "result_unavailable")
                result[key] = value
            return result
        def constant(_):
            raise ReviewRefused("result_unavailable")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise ReviewRefused("result_unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)


def write_private_action(directory: Path, action: t.HostAction) -> str:
    """Explicit private export, deterministic name, exclusive create, fsync.

    A failed write leaves an offered intent unresolved; it never renews launch.
    Existing exact payload is reusable as an artifact, not permission to dispatch.
    """
    payload = t.relay_json(action.private_payload())
    name = "action-" + t.sha(payload) + ".json"
    path = directory / name
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        t.require(read_private_json(path) == action.private_payload(), "delivery_conflict")
        return name
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise ReviewRefused("result_unavailable") from None
    return name


def cli_main(args) -> int:
    """Private file in, metadata out. No dynamic policy or authority flags."""
    try:
        inputs = read_private_json(Path(args.input)) if args.input else {}
        t.require(type(inputs) is dict)
        scope = {"parent_thread_id": args.parent_thread, "checkout": args.checkout}
        service = T3ReviewService(Path(args.state), host_scope=scope)
        operation = args.typed_review_operation
        if operation == "request":
            from .baml_modular import snapshot_baml_sources
            t.require(set(inputs) <= {"charter", "coordinator_key", "subjects", "seat", "purpose", "lens", "questions", "evidence", "function", "byte_limit", "ledger"})
            request = service.request(source_snapshot=snapshot_baml_sources(), **inputs)
            result = {"request_binding": request.binding, "attempt_id": request.attempt_id, "lineage_id": request.lineage_id}
        elif operation == "prepare":
            t.require(set(inputs) == {"target", "capabilities"})
            result = service.prepare(args.binding, **inputs)
        elif operation == "register":
            result = service.register(args.binding, inputs)
        elif operation == "intake":
            result = service.intake(args.binding, inputs)
        elif operation == "resume":
            result = service.resume(args.binding)
        else:
            t.require(set(inputs) == {"capabilities"})
            result = service.correction(args.binding, **inputs)
        if isinstance(result, t.HostAction):
            name = write_private_action(service.directory, result)
            result = {**result.metadata(), "private_action_file": name}
        elif not isinstance(result, dict):
            result = asdict(result)
        print(json.dumps({**result, "schema": "t3_cli_result.v1", "ok": True}, sort_keys=True))
        return 0
    except ReviewRefused as exc:
        code = exc.code
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        code = "result_unavailable"
    print(json.dumps({"schema": "t3_cli_result.v1", "ok": False, "rejection_code": code}, sort_keys=True))
    return 1
