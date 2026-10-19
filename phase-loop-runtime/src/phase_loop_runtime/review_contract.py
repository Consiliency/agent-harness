"""Coordinator-owned typed review intake. No provider dispatch or admission issuer.

The injected policy and this database belong to the trusted coordinator. They
must not be exposed as a reviewer-writable CLI. OS isolation and policy admission
are external prerequisites, not properties conferred by constructing this class.
All content-bearing values and the SQLite database are private.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Protocol
import uuid

from jsonschema import Draft202012Validator, validators

from . import baml_modular as baml

CONTRACT_VERSION = "typed_review.v1"
VALIDATOR_VERSION = "review_validator.v1"
RUNTIME_VERSION = "0.20.1"
MAX_BYTES = 1_048_576
# One JSON string encoding of any bounded UTF-8 body, plus bounded host metadata.
MAX_TRANSPORT_BYTES = 6 * MAX_BYTES + 65_536
MAX_DEPTH = 32
MAX_TEXT = 20_000
MAX_FINDINGS = MAX_QUESTIONS = 200
MAX_EVIDENCE = 100
REJECTION_CODES = frozenset({
    "invalid_json", "schema_mismatch", "binding_mismatch", "semantic_mismatch",
    "baml_unavailable", "baml_parse_failed", "baml_changed_value",
    "result_incomplete", "result_unavailable", "delivery_conflict", "limit_exceeded",
})
_FUNCTIONS = {"EmitReviewReply": "parse_review_reply", "EmitReviewDecision": "parse_review_decision"}
_PROVENANCE = frozenset({"HOST_ATTESTED", "TRANSPORT_CAPTURED"})
_StrictValidator = validators.extend(Draft202012Validator, type_checker=
    Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda _, v: type(v) is int))


class ReviewRefused(ValueError):
    """Closed, content-free diagnostic. Never wrap a model/worker exception."""

    def __init__(self, code: str):
        self.code = code if code in REJECTION_CODES else "result_unavailable"
        super().__init__(self.code)


def _require(ok: bool, code: str = "binding_mismatch") -> None:
    if not ok:
        raise ReviewRefused(code)


def canonical_json(value: Any) -> bytes:
    """Sorted object keys; ordered arrays; literal UTF-8; no normalization/floats.

    The supported canonical domain is JSON null/bool/int/string/list/object.
    BAML source-map fingerprints deliberately retain the upstream ASCII encoding.
    """
    def check(v):
        if type(v) is dict:
            _require(all(type(k) is str for k in v))
            for k, item in v.items():
                check(k)
                check(item)
        elif type(v) is list:
            for item in v:
                check(item)
        elif type(v) is str:
            v.encode("utf-8")
        else:
            _require(v is None or type(v) in (bool, int))
    try:
        check(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise ReviewRefused("binding_mismatch") from None


def canonical_digest(domain: str, value: Any) -> str:
    _require(domain in {"request", "receipt", "ledger", "finding", "delivery", "registration", "subjects", "policy", "carry"})
    return hashlib.sha256(b"phase-loop/typed-review/v1/" + domain.encode("ascii") + b"\0" + canonical_json(value)).hexdigest()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _text(value: Any) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_TEXT


@dataclass(frozen=True)
class Admission:
    """Decision from existing coordinator policy, NOT a credential or new waiver."""

    eligibility: str = "NON_GATING"
    permitted_provenance: tuple[str, ...] = ("HOST_ATTESTED",)
    correction_allowed: bool = False
    unusable_seat_blocks: bool = True
    governed_provenance: tuple[str, ...] = ()


class CoordinatorPolicy(Protocol):
    """Implemented by the admitted host, never supplied by reviewer content.

    identity is a digest of the existing versioned policy/brief interpretation.
    authorize sees a private copy of the frozen input context. Registration and
    deferred-blocker admission must consult existing authority. No default policy
    manufactures host identity, governed eligibility, or a waiver.
    """

    identity: str

    def authorize(self, context: dict[str, Any]) -> Admission: ...

    def admit_transport(self, request: "FrozenRequest", registration: dict[str, Any]) -> bool: ...

    def allow_deferred(self, request: "FrozenRequest", finding_key: str) -> bool: ...


@dataclass(frozen=True)
class FrozenRequest:
    """Private immutable JSON; accessors return detached copies."""

    _json: str = field(repr=False)

    @property
    def value(self) -> dict[str, Any]:
        return json.loads(self._json)

    @property
    def binding(self) -> str:
        return canonical_digest("request", self.value)

    @property
    def attempt_id(self) -> str:
        return self.value["attempt_id"]

    @property
    def lineage_id(self) -> str:
        return self.value["lineage_id"]


@dataclass(frozen=True)
class ContentRecord:
    """Only closed codes, generated IDs, digests, versions, booleans and counts."""

    record_id: str
    request_binding: str
    attempt_id: str
    lineage_id: str
    source_manifest_digest: str
    contract_fingerprint: str
    contract_version: str
    validator_version: str
    runtime_version: str | None
    operation: str | None
    ipc_id: int | None
    registration_digest: str
    transport_digest: str
    body_digest: str
    parsed_digest: str | None
    provenance: str
    host_digest: str
    outcome: str
    rejection_code: str | None
    content_valid: bool
    usable: bool
    governed_eligible: bool
    finding_count: int
    unverified_evidence_count: int
    replaces_record_id: str | None

    @property
    def usable_vote(self) -> bool:
        return self.usable and self.outcome == "usable_review"

    @property
    def usable_ruling(self) -> bool:
        return self.usable and self.outcome == "usable_decision"


def decode_original(raw: bytes, byte_limit: int = MAX_BYTES) -> tuple[str, dict[str, Any]]:
    """One original JSON object; container nesting counts root as depth one."""
    _require(type(raw) is bytes, "invalid_json")
    _require(0 < byte_limit <= MAX_BYTES and len(raw) <= byte_limit, "limit_exceeded")

    def pairs(items):
        result = {}
        for k, v in items:
            _require(k not in result, "invalid_json")
            result[k] = v
        return result

    def constant(_):
        raise ReviewRefused("invalid_json")

    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        _require(type(value) is dict, "invalid_json")
        stack = [(value, 1, ())]
        while stack:
            v, depth, path = stack.pop()
            if type(v) in (dict, list):
                _require(depth <= MAX_DEPTH, "limit_exceeded")
                entries = v.items() if type(v) is dict else enumerate(v)
                for key, item in entries:
                    if type(key) is str:
                        key.encode("utf-8")
                    stack.append((item, depth + 1, (*path, key)))
            elif type(v) is str:
                v.encode("utf-8")
                exempt = len(path) >= 2 and path[-2:] == ("falsifier", "diff")
                _require(exempt or len(v) <= MAX_TEXT, "limit_exceeded")
            elif type(v) is float:
                # json.loads accepts overflowing exponents as infinity.
                import math
                _require(math.isfinite(v), "invalid_json")
        return text, value
    except RecursionError:
        raise ReviewRefused("limit_exceeded") from None
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, ReviewRefused):
            raise
        raise ReviewRefused("invalid_json") from None


def strict_tree_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(strict_tree_equal(v, right[k]) for k, v in left.items())
    if type(left) is list:
        return len(left) == len(right) and all(strict_tree_equal(a, b) for a, b in zip(left, right))
    return left == right


def strict_precheck(raw: bytes, snapshot: baml.BamlSourceSnapshot, function: str, byte_limit: int = MAX_BYTES):
    """Shape/enum authority comes solely from this bound saved BAML map."""
    _require(function in _FUNCTIONS, "schema_mismatch")
    text, original = decode_original(raw, byte_limit)
    try:
        schema = baml.export_function_schema(function, source_snapshot=snapshot)
        _require(_StrictValidator(schema).is_valid(original), "schema_mismatch")
    except baml.BamlValidationError:
        raise ReviewRefused("baml_unavailable") from None
    return text, original


def _semantics(request: FrozenRequest, value: dict, evidence_digests: dict) -> tuple[str, int]:
    r = request.value
    decision = r["function"] == "EmitReviewDecision"
    _require(value["request_binding"] == request.binding)
    _require(value["schema_version"] == ("review_decision.v1" if decision else "review_reply.v1"), "semantic_mismatch")
    # Source enums define the vocabulary; these comparisons implement cross-field policy.
    _require(_text(value["summary"]) and all(_text(s) for s in value["limitations"]), "semantic_mismatch")
    complete = value["review_status"] == "COMPLETE"
    unverified = 0
    permitted = {e["handle"]: e["sha256"] for e in r["evidence"]}

    def evidence(items):
        nonlocal unverified
        _require(len(items) <= MAX_EVIDENCE, "limit_exceeded")
        for e in items:
            _require(_text(e["description"]), "semantic_mismatch")
            ref = e["reference"]
            _require(ref is None or _text(ref), "semantic_mismatch")
            if ref is None or ref not in permitted or evidence_digests.get(ref) != permitted[ref]:
                unverified += 1

    if decision:
        _require((value["decision"] is not None) == complete, "semantic_mismatch")
        entries = {e["key"]: e for e in r["ledger"]["entries"]}
        seen = set()
        for d in value["dispositions"]:
            key = d["finding_key"]
            _require(key in entries and key not in seen and _text(d["rationale"]), "semantic_mismatch")
            seen.add(key)
            evidence(d["evidence"])
            if value["decision"] == "ACCEPT" and entries[key]["blocking"]:
                _require(d["status"] != "OPEN", "semantic_mismatch")
                _require(d["status"] != "DEFERRED" or key in r["deferred_authorized_keys"], "semantic_mismatch")
        _require(seen == entries.keys(), "semantic_mismatch")
    else:
        findings = value["findings"]
        _require(len(findings) <= MAX_FINDINGS, "limit_exceeded")
        _require(len(value["coverage"]) <= MAX_QUESTIONS, "limit_exceeded")
        ids = set()
        blockers = 0
        for f in findings:
            _require(_text(f["id"]) and f["id"] not in ids, "semantic_mismatch")
            ids.add(f["id"])
            _require(all(_text(f[k]) for k in ("title", "explanation", "requested_change")), "semantic_mismatch")
            _require(all(_text(s) for s in f["obligation_refs"]), "semantic_mismatch")
            blocking = f["severity"] == "BLOCKING"
            blockers += blocking
            _require(not blocking or bool(f["obligation_refs"]), "semantic_mismatch")
            _require(f["severity"] != "NON_BLOCKING" or f["falsifier"] is None, "semantic_mismatch")
            # N9-R3: node/diff/identifier structural validity belongs to governed gate.
            evidence(f["evidence"])
        questions = {q["id"] for q in r["questions"]}
        seen = set()
        for c in value["coverage"]:
            _require(c["question_id"] in questions and c["question_id"] not in seen, "semantic_mismatch")
            seen.add(c["question_id"])
            _require(_text(c["answer"]) and all(fid in ids for fid in c["finding_ids"]), "semantic_mismatch")
            _require(not complete or c["status"] == "ANSWERED", "semantic_mismatch")
        _require(seen == questions, "semantic_mismatch")
        _require(all(_text(s) for s in value["scope_reviewed"]), "semantic_mismatch")
        _require(not complete or bool(value["scope_reviewed"]), "semantic_mismatch")
        verdict = value["verdict"]
        if r["purpose"] == "advisory":
            _require(verdict is None and blockers == 0, "semantic_mismatch")
        else:
            _require((verdict is not None) == complete, "semantic_mismatch")
            _require(verdict != "AGREE" or blockers == 0, "semantic_mismatch")
            _require(verdict != "DISAGREE" or blockers > 0, "semantic_mismatch")
            _require(verdict != "PARTIALLY_AGREE" or bool(findings), "semantic_mismatch")
    _require(complete or bool(value["limitations"]), "semantic_mismatch")
    return ("usable_decision" if decision else "valid_advisory" if r["purpose"] == "advisory" else "usable_review") if complete else "incomplete_review", unverified


class ReviewCoordinator:
    """Private durable state; BEGIN IMMEDIATE serializes across processes/restarts.

    No soft lease, provider call, automatic retry dispatch, or auth bootstrap.
    SQLite FULL synchronization and rollback journals commit bytes before parsing.
    Parsing holds the write lock. Other operations have a 60-second busy timeout
    and may refuse result_unavailable; retry local coordination, never dispatch.
    Store on a local filesystem supporting SQLite locking, outside reviewer writes.
    """

    def __init__(self, private_directory: Path, *, policy: CoordinatorPolicy):
        self.policy = policy
        _require(_digest(policy.identity))
        self.directory = Path(private_directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require(not self.directory.is_symlink(), "result_unavailable")
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "reviews.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self._transaction() as db:
            schema = """
                CREATE TABLE IF NOT EXISTS sources (fingerprint TEXT PRIMARY KEY, files TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS briefs (digest TEXT PRIMARY KEY, raw BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS request_keys (key TEXT PRIMARY KEY, binding TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS carries (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (binding TEXT PRIMARY KEY, attempt TEXT UNIQUE NOT NULL,
                    lineage TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lineages (id TEXT PRIMARY KEY, original TEXT NOT NULL,
                    correction TEXT UNIQUE, standing TEXT);
                CREATE TABLE IF NOT EXISTS registrations (binding TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (binding TEXT PRIMARY KEY, identity TEXT NOT NULL,
                    raw BLOB, transport BLOB, evidence TEXT NOT NULL, latest TEXT, omitted TEXT);
                CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                    metadata TEXT NOT NULL, parsed TEXT);
                CREATE TABLE IF NOT EXISTS validations (sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    binding TEXT NOT NULL, result_record_id TEXT NOT NULL, invocation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intake_refusals (sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    binding TEXT NOT NULL, metadata TEXT NOT NULL);
            """
            # executescript would commit BEGIN IMMEDIATE before the DDL. Keep
            # initialization and the pre-freeze storage migration atomic too.
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            if "omitted" not in {row["name"] for row in db.execute("PRAGMA table_info(deliveries)")}:
                db.execute("ALTER TABLE deliveries RENAME TO retained_deliveries")
                db.execute("""CREATE TABLE deliveries (binding TEXT PRIMARY KEY, identity TEXT NOT NULL,
                    raw BLOB, transport BLOB, evidence TEXT NOT NULL, latest TEXT, omitted TEXT)""")
                db.execute("INSERT INTO deliveries SELECT *, NULL FROM retained_deliveries")
                db.execute("DROP TABLE retained_deliveries")

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=60, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except sqlite3.Error:
            db.rollback()
            raise ReviewRefused("result_unavailable") from None
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _save_source(self, db, source):
        files = json.dumps(dict(source.files), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        _require(_sha(files.encode("ascii")) == source.fingerprint)
        db.execute("INSERT OR IGNORE INTO sources VALUES (?, ?)", (source.fingerprint, files))
        _require(db.execute("SELECT files FROM sources WHERE fingerprint=?", (source.fingerprint,)).fetchone()[0] == files)

    def _source(self, db, request):
        r = request.value
        _require(r["contract_version"] == CONTRACT_VERSION and r["validator_version"] == VALIDATOR_VERSION
                 and r["runtime_version"] == RUNTIME_VERSION, "baml_unavailable")
        row = db.execute("SELECT files FROM sources WHERE fingerprint=?", (r["contract_fingerprint"],)).fetchone()
        _require(row is not None, "baml_unavailable")
        try:
            source = baml.snapshot_baml_sources(json.loads(row[0]))
            _require(source.fingerprint == r["contract_fingerprint"], "baml_unavailable")
            return source
        except (ValueError, baml.BamlValidationError):
            raise ReviewRefused("baml_unavailable") from None

    def _load(self, db, binding):
        row = db.execute("SELECT body FROM requests WHERE binding=?", (binding,)).fetchone()
        _require(row is not None)
        request = FrozenRequest(row[0])
        _require(request.binding == binding and request.value["policy_digest"] == self.policy.identity)
        # Pre-freeze requests cannot acquire an inferred provenance admission.
        _require("governed_provenance" in request.value["admission"], "result_unavailable")
        return request

    def load_request(self, binding: str) -> FrozenRequest:
        with self._transaction() as db:
            request = self._load(db, binding)
            self._source(db, request)
            return request

    def create_request(self, *, coordinator_key: str, brief: bytes, subjects: list[dict], seat: str,
                       purpose: str = "review", lens: str | None = None,
                       questions: list[dict] | None = None, evidence: list[dict] | None = None,
                       source_snapshot: baml.BamlSourceSnapshot,
                       function: str = "EmitReviewReply", byte_limit: int = MAX_BYTES,
                       ledger: dict | None = None) -> FrozenRequest:
        """Freeze ordered inputs. Subject descriptors require immutable digests.

        Subjects: {kind: document|git|snapshot, sha256, paths: [str], revision: str|null}.
        Git revisions are full commit/tree hashes; snapshot/document sha256 binds
        the frozen byte manifest. Availability/confinement remains host-owned.
        Evidence: {handle, sha256}; questions: {id, text}. No evidence is fetched.
        """
        _require(type(brief) is bytes and _text(seat) and (lens is None or _text(lens)) and _text(coordinator_key))
        try:
            brief.decode("utf-8")
        except UnicodeError:
            raise ReviewRefused("binding_mismatch") from None
        _require(purpose in ("review", "advisory") and function in _FUNCTIONS)
        _require(type(byte_limit) is int and 0 < byte_limit <= MAX_BYTES, "limit_exceeded")
        inputs = json.loads(canonical_json({"subjects": subjects, "questions": questions or [], "evidence": evidence or [], "ledger": ledger}))
        _require(bool(inputs["subjects"]))
        for s in inputs["subjects"]:
            _require(set(s) == {"kind", "sha256", "paths", "revision"})
            _require(s["kind"] in ("document", "git", "snapshot") and _digest(s["sha256"]))
            _require(type(s["paths"]) is list and bool(s["paths"]) and all(_text(p) for p in s["paths"]))
            _require(s["revision"] is None if s["kind"] != "git" else type(s["revision"]) is str and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", s["revision"]) is not None)
        _require(len(inputs["questions"]) <= MAX_QUESTIONS, "limit_exceeded")
        for name, fields in (("questions", {"id", "text"}), ("evidence", {"handle", "sha256"})):
            seen = set()
            for item in inputs[name]:
                _require(type(item) is dict and set(item) == fields)
                key = item["id" if name == "questions" else "handle"]
                _require(_text(key) and key not in seen)
                seen.add(key)
                _require(_text(item["text"]) if name == "questions" else _digest(item["sha256"]))
        _require((function == "EmitReviewDecision") == (ledger is not None))
        _require(function != "EmitReviewDecision" or (purpose == "review" and not inputs["questions"]))
        r = {"coordinator_key_digest": _sha(coordinator_key.encode()),
             "request_id": uuid.uuid4().hex, "attempt_id": uuid.uuid4().hex, "lineage_id": uuid.uuid4().hex,
             "purpose": purpose, "function": function, "contract_version": CONTRACT_VERSION,
             "validator_version": VALIDATOR_VERSION, "runtime_version": RUNTIME_VERSION,
             "contract_fingerprint": source_snapshot.fingerprint, "brief_digest": _sha(brief),
             "seat": seat, "lens": lens, "byte_limit": byte_limit, "policy_digest": self.policy.identity,
             **inputs, "ledger_digest": canonical_digest("ledger", inputs["ledger"]) if ledger is not None else None,
             "replaces_record_id": None}
        admission = self.policy.authorize(json.loads(canonical_json(r)))
        _require(type(admission) is Admission and admission.eligibility in ("NON_GATING", "GOVERNED"))
        _require(type(admission.correction_allowed) is bool and type(admission.unusable_seat_blocks) is bool)
        for classes in (admission.permitted_provenance, admission.governed_provenance):
            _require(type(classes) is tuple and all(type(item) is str for item in classes))
            _require(len(set(classes)) == len(classes) and set(classes) <= _PROVENANCE)
        _require(bool(admission.permitted_provenance)
                 and set(admission.governed_provenance) <= set(admission.permitted_provenance))
        _require(purpose != "advisory" or admission.eligibility == "NON_GATING")
        r["admission"] = {**asdict(admission), "permitted_provenance": list(admission.permitted_provenance),
                          "governed_provenance": list(admission.governed_provenance)}
        r["deferred_authorized_keys"] = []
        provisional = FrozenRequest(canonical_json(r).decode())
        if ledger is not None:
            r["deferred_authorized_keys"] = [e["key"] for e in ledger["entries"] if e["blocking"] and self.policy.allow_deferred(provisional, e["key"])]
        request = FrozenRequest(canonical_json(r).decode())
        with self._transaction() as db:
            previous = db.execute("SELECT binding FROM request_keys WHERE key=?", (r["coordinator_key_digest"],)).fetchone()
            if previous:
                saved = self._load(db, previous[0])
                comparison = {**r, **{k: saved.value[k] for k in ("request_id", "attempt_id", "lineage_id")}}
                _require(strict_tree_equal(comparison, saved.value), "delivery_conflict")
                self._source(db, saved)
                return saved
            if ledger is not None:
                _require(strict_tree_equal(inputs["ledger"], self._ledger(db, ledger["lineages"], ledger["carried"])))
            self._save_source(db, source_snapshot)
            db.execute("INSERT OR IGNORE INTO briefs VALUES (?, ?)", (r["brief_digest"], brief))
            db.execute("INSERT INTO requests VALUES (?, ?, ?, ?)", (request.binding, r["attempt_id"], r["lineage_id"], request._json))
            db.execute("INSERT INTO lineages VALUES (?, ?, NULL, NULL)", (r["lineage_id"], request.binding))
            db.execute("INSERT INTO request_keys VALUES (?, ?)", (r["coordinator_key_digest"], request.binding))
        return request

    def _brief(self, db, request):
        digest = request.value["brief_digest"]
        row = db.execute("SELECT raw FROM briefs WHERE digest=?", (digest,)).fetchone()
        _require(row is not None and _sha(bytes(row[0])) == digest)
        return bytes(row[0])

    def build_request(self, binding: str) -> baml.BamlRequest:
        """Local prompt construction from persisted request and source; no inference."""
        with self._transaction() as db:
            request = self._load(db, binding)
            source = self._source(db, request)
            try:
                context = {"request": request.value, "request_binding": binding, "brief": self._brief(db, request).decode("utf-8")}
                if request.value["replaces_record_id"] is not None:
                    correction = self._correction_context(db, request)
                    original = correction.pop("original_body")
                    correction.pop("original_brief")  # Already included losslessly above.
                    # Preserve non-UTF-8 invalid originals losslessly for the host.
                    import base64
                    context["correction"] = {**correction, "original_body_base64":
                        base64.b64encode(original).decode("ascii") if original is not None else None,
                        "kind": "substantive_replacement"}
                    if original is None:
                        context["correction"]["notice"] = "The over-limit original bytes were not retained; only their digest and length are available."
                return baml.build_baml_request(request.value["function"], {"request_json": canonical_json(context).decode()}, source_snapshot=source)
            except (baml.BamlWorkerError, baml.BamlValidationError):
                raise ReviewRefused("baml_unavailable") from None

    def register_transport(self, binding: str, *, host_identity: str, provenance: str, identity: dict[str, str]) -> str:
        """Host binds actual task/run/operation IDs, after dispatch, once only."""
        _require(provenance in _PROVENANCE and _text(host_identity))
        _require(type(identity) is dict and bool(identity) and all(_text(k) and _text(v) for k, v in identity.items()))
        registration = {"host_identity": host_identity, "provenance": provenance, "identity": identity}
        encoded = canonical_json(registration).decode()
        with self._transaction() as db:
            request = self._load(db, binding)
            _require(provenance in request.value["admission"]["permitted_provenance"])
            _require(self.policy.admit_transport(request, json.loads(encoded)) is True)
            old = db.execute("SELECT body FROM registrations WHERE binding=?", (binding,)).fetchone()
            _require(old is None or old[0] == encoded, "delivery_conflict")
            db.execute("INSERT OR IGNORE INTO registrations VALUES (?, ?)", (binding, encoded))
        return canonical_digest("registration", registration)

    def ingest(self, binding: str, *, body: bytes, transport: bytes,
               evidence_digests: dict[str, str] | None = None, captured_body: bytes | None = None) -> ContentRecord:
        """Trusted complete terminal bytes. TRANSPORT_CAPTURED requires channel bytes.

        The admitted programmatic channel supplies captured_body independently of
        any relay. This function does not authenticate an arbitrary Python caller.
        Envelope completeness/identity checks belong to that admitted adapter.
        """
        _require(type(body) is bytes and type(transport) is bytes, "invalid_json")
        observed = {} if evidence_digests is None else evidence_digests
        _require(type(observed) is dict)
        _require(all(_text(handle) and _digest(digest) for handle, digest in observed.items()))
        observed = json.loads(canonical_json(observed))
        with self._transaction() as db:
            request = self._load(db, binding)
            row = db.execute("SELECT body FROM registrations WHERE binding=?", (binding,)).fetchone()
            _require(row is not None, "result_unavailable")
            registration = json.loads(row[0])
            _require(self.policy.admit_transport(request, registration) is True)
            _require(registration["provenance"] != "TRANSPORT_CAPTURED" or (type(captured_body) is bytes and captured_body == body))
            permitted = {e["handle"]: e["sha256"] for e in request.value["evidence"]}
            _require(all(handle in permitted and digest == permitted[handle] for handle, digest in observed.items()))
            omitted = self._byte_facts(body, transport) if len(body) > request.value["byte_limit"] else None
            identity = self._delivery_identity(registration, body, transport, observed, omitted)
            old = db.execute("SELECT identity FROM deliveries WHERE binding=?", (binding,)).fetchone()
            # A consumed attempt conflicts before either size outcome is considered.
            _require(old is None or old[0] == identity, "delivery_conflict")
            # A host-only repair must retain the authentic original reviewer body.
            prior = db.execute("SELECT metadata FROM intake_refusals WHERE binding=? ORDER BY sequence LIMIT 1", (binding,)).fetchone()
            if prior:
                facts = json.loads(prior[0])
                _require(facts["body_digest"] == _sha(body) and facts["body_bytes"] == len(body), "delivery_conflict")
            exhausted = omitted is None and len(transport) > MAX_TRANSPORT_BYTES
            if exhausted:
                # Host envelope refusal binds the original body without consuming it.
                observation = {"request_binding": binding, "rejection_code": "limit_exceeded",
                    **self._byte_facts(body, transport)}
                db.execute("INSERT INTO intake_refusals(binding, metadata) VALUES (?, ?)",
                           (binding, canonical_json(observation).decode()))
            else:
                self._store_delivery(db, binding, identity, body, transport, observed, omitted)
                if omitted is not None:
                    # Claim, deterministic rejection, history and standing commit
                    # together. No omitted/fabricated bytes ever reach BAML.
                    return self._validate(binding, revalidate=False, db=db)
        if exhausted:
            raise ReviewRefused("limit_exceeded")
        # Claim/bytes survive a worker outage or process crash before validation.
        return self._validate(binding, revalidate=False)

    def _byte_facts(self, body, transport):
        return {"body_digest": _sha(body), "transport_digest": _sha(transport),
                "body_bytes": len(body), "transport_bytes": len(transport)}

    def _delivery_identity(self, registration, body, transport, observed, omitted=None):
        identity = {"registration": canonical_digest("registration", registration),
            "body": omitted["body_digest"] if omitted is not None else _sha(body),
            "transport": omitted["transport_digest"] if omitted is not None else _sha(transport), "evidence": observed}
        if omitted is not None:
            identity["omitted"] = omitted  # Bind lengths and explicit absence too.
        return canonical_digest("delivery", identity)

    def _stored_facts(self, d, request):
        if d["omitted"] is None:
            _require(type(d["raw"]) is bytes and type(d["transport"]) is bytes, "result_unavailable")
            return self._byte_facts(d["raw"], d["transport"])
        try:
            facts = json.loads(d["omitted"])
            _require(type(facts) is dict and set(facts) == {"body_digest", "transport_digest", "body_bytes", "transport_bytes"}, "result_unavailable")
            _require(all(_digest(facts[k]) for k in ("body_digest", "transport_digest")), "result_unavailable")
            _require(type(facts["body_bytes"]) is int and facts["body_bytes"] > request.value["byte_limit"]
                     and type(facts["transport_bytes"]) is int and facts["transport_bytes"] >= 0
                     and d["raw"] is None and d["transport"] is None, "result_unavailable")
            return facts
        except (ValueError, TypeError):
            raise ReviewRefused("result_unavailable") from None

    def _check_delivery(self, d, registration, facts):
        _require(d["identity"] == self._delivery_identity(registration, d["raw"], d["transport"],
                 json.loads(d["evidence"]), facts if d["omitted"] is not None else None), "result_unavailable")

    def _store_delivery(self, db, binding, identity, body, transport, observed, omitted):
        db.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, ?, ?, NULL, ?)",
                   (binding, identity, body if omitted is None else None, transport if omitted is None else None,
                    canonical_json(observed).decode(), canonical_json(omitted).decode() if omitted is not None else None))

    def revalidate(self, binding: str) -> ContentRecord:
        """Reparse retained bytes or verify a digest-only rejection; never dispatch."""
        return self._validate(binding, revalidate=True)

    def _validate(self, binding, *, revalidate, db=None):
        with self._transaction() if db is None else nullcontext(db) as db:
            request = self._load(db, binding)
            r = request.value
            d = db.execute("SELECT * FROM deliveries WHERE binding=?", (binding,)).fetchone()
            _require(d is not None, "result_unavailable")
            registration = json.loads(db.execute("SELECT body FROM registrations WHERE binding=?", (binding,)).fetchone()[0])
            _require(self.policy.admit_transport(request, registration) is True)
            facts = self._stored_facts(d, request)
            if d["latest"] and not revalidate:
                self._check_delivery(d, registration, facts)
                self._source(db, request)
                return self._record(db, d["latest"])
            parsed = None
            outcome, code, count, unverified = "invalid_content", None, 0, 0
            operation = ipc_id = runtime = parsed_digest = None
            try:
                self._check_delivery(d, registration, facts)
                source = self._source(db, request)
                _require(d["omitted"] is None, "limit_exceeded")
                text, original = strict_precheck(bytes(d["raw"]), source, r["function"], r["byte_limit"])
                reply = baml.parse_review_response(r["function"], text, source_snapshot=source)
                _require(type(reply) is baml.ReviewParseResult, "baml_unavailable")
                _require(reply.function_name == r["function"] and reply.operation == _FUNCTIONS[r["function"]]
                         and type(reply.request_id) is int and reply.request_id > 0
                         and reply.fingerprint == source.fingerprint and reply.runtime_version == r["runtime_version"], "baml_unavailable")
                operation, ipc_id, runtime = reply.operation, reply.request_id, reply.runtime_version
                _require(strict_tree_equal(original, reply.value), "baml_changed_value")
                if r["ledger"] is not None:
                    try:
                        current_ledger = self._ledger(db, r["ledger"]["lineages"], r["ledger"]["carried"])
                    except ReviewRefused:
                        raise ReviewRefused("result_unavailable") from None
                    _require(strict_tree_equal(r["ledger"], current_ledger), "result_unavailable")
                outcome, unverified = _semantics(request, reply.value, json.loads(d["evidence"]))
                parsed = reply.value  # Consume the actual matched worker reply, never reconstruct input.
                parsed_digest = _sha(canonical_json(parsed))
                count = len(parsed.get("findings", []))
                if outcome == "incomplete_review":
                    code = "result_incomplete"
            except baml.BamlWorkerError:
                code, outcome = "baml_unavailable", "transport_failure"
            except baml.BamlValidationError:
                code = "baml_parse_failed"
            except ReviewRefused as exc:
                code = exc.code
                if code in ("baml_unavailable", "result_unavailable"):
                    outcome = "transport_failure"
            except (KeyError, TypeError):
                # A saved declaration with incompatible semantic fields is not
                # permission to use the current package schema or leak content.
                code = "schema_mismatch"
            valid = parsed is not None
            usable = valid and outcome != "incomplete_review"
            metadata = dict(request_binding=binding, attempt_id=r["attempt_id"], lineage_id=r["lineage_id"],
                source_manifest_digest=canonical_digest("subjects", r["subjects"]), contract_fingerprint=r["contract_fingerprint"],
                contract_version=r["contract_version"], validator_version=VALIDATOR_VERSION, runtime_version=runtime,
                operation=operation, ipc_id=ipc_id, registration_digest=canonical_digest("registration", registration),
                transport_digest=facts["transport_digest"], body_digest=facts["body_digest"], parsed_digest=parsed_digest,
                provenance=registration["provenance"], host_digest=_sha(registration["host_identity"].encode()),
                outcome=outcome, rejection_code=code, content_valid=valid, usable=usable,
                governed_eligible=usable and r["purpose"] == "review" and r["admission"]["eligibility"] == "GOVERNED"
                    and registration["provenance"] in r["admission"]["governed_provenance"],
                finding_count=count, unverified_evidence_count=unverified, replaces_record_id=r["replaces_record_id"])
            record = ContentRecord(record_id=canonical_digest("receipt", metadata), **metadata)
            # Keep matching valid AND deterministic invalid identities after resume.
            # Every invocation still has its own durable evidence below.
            if valid or outcome == "invalid_content":
                stable = {k: v for k, v in metadata.items() if k != "ipc_id"}
                for previous in db.execute("SELECT id FROM records WHERE binding=? ORDER BY rowid", (binding,)):
                    candidate = self._record(db, previous[0])
                    prior = {k: v for k, v in asdict(candidate).items() if k not in ("record_id", "ipc_id")}
                    if strict_tree_equal(stable, prior):
                        record = candidate
                        break
            db.execute("INSERT OR IGNORE INTO records VALUES (?, ?, ?, ?)",
                       (record.record_id, binding, canonical_json(asdict(record)).decode(), canonical_json(parsed).decode() if valid else None))
            db.execute("INSERT INTO validations(binding, result_record_id, invocation) VALUES (?, ?, ?)",
                       (binding, record.record_id, canonical_json(metadata).decode()))
            db.execute("UPDATE deliveries SET latest=? WHERE binding=?", (record.record_id, binding))
            lineage = db.execute("SELECT * FROM lineages WHERE id=?", (r["lineage_id"],)).fetchone()
            if binding == (lineage["correction"] or lineage["original"]):
                # Failed current validation cannot erase historical accepted content.
                previous = self._record(db, lineage["standing"]) if lineage["standing"] else None
                if valid or previous is None or not previous.content_valid:
                    db.execute("UPDATE lineages SET standing=? WHERE id=?", (record.record_id, r["lineage_id"]))
            return record

    def validation_history(self, binding: str) -> list[dict]:
        """Ordered metadata-only local validation observations, including failures.

        A returned stable ContentRecord retains its original IPC identity. Each
        history entry binds the actual later invocation to that result identity.
        Idempotent delivery lookup does not append a fictitious reparse.
        """
        with self._transaction() as db:
            self._load(db, binding)
            return [{"sequence": row["sequence"], "result_record_id": row["result_record_id"],
                     "invocation": json.loads(row["invocation"])}
                    for row in db.execute("SELECT * FROM validations WHERE binding=? ORDER BY sequence", (binding,))]

    def _record(self, db, record_id):
        row = db.execute("SELECT metadata FROM records WHERE id=?", (record_id,)).fetchone()
        _require(row is not None)
        fields = json.loads(row[0])
        _require(fields.pop("record_id") == record_id and canonical_digest("receipt", fields) == record_id)
        return ContentRecord(record_id=record_id, **fields)

    def private_body(self, record_id: str) -> dict:
        """Content-bearing accessor for admitted consumers; never public telemetry."""
        with self._transaction() as db:
            record = self._record(db, record_id)
            _require(record.content_valid)
            raw = db.execute("SELECT parsed FROM records WHERE id=?", (record_id,)).fetchone()[0]
            value = json.loads(raw)
            _require(_sha(canonical_json(value)) == record.parsed_digest)
            return value

    def reserve_correction(self, original_binding: str) -> FrozenRequest:
        """One durable reservation BEFORE dispatch. Unknown outcome stays reserved."""
        with self._transaction() as db:
            original = self._load(db, original_binding)
            r = original.value
            lineage = db.execute("SELECT * FROM lineages WHERE id=?", (r["lineage_id"],)).fetchone()
            _require(lineage["original"] == original_binding and lineage["correction"] is None, "result_unavailable")
            _require(r["admission"]["correction_allowed"] and lineage["standing"] is not None, "result_unavailable")
            failure = self._record(db, lineage["standing"])
            current = db.execute("SELECT latest FROM deliveries WHERE binding=?", (original_binding,)).fetchone()
            _require(current is not None and current[0] == failure.record_id, "result_unavailable")
            _require(not failure.content_valid and failure.rejection_code not in ("baml_unavailable", "result_unavailable"), "result_unavailable")
            r.update(request_id=uuid.uuid4().hex, attempt_id=uuid.uuid4().hex, replaces_record_id=failure.record_id)
            correction = FrozenRequest(canonical_json(r).decode())
            db.execute("INSERT INTO requests VALUES (?, ?, ?, ?)", (correction.binding, r["attempt_id"], r["lineage_id"], correction._json))
            db.execute("UPDATE lineages SET correction=?, standing=NULL WHERE id=?", (correction.binding, r["lineage_id"]))
            return correction

    def correction_request(self, original_binding: str) -> FrozenRequest | None:
        """Recover an existing reservation without creating another dispatch budget."""
        with self._transaction() as db:
            original = self._load(db, original_binding)
            row = db.execute("SELECT correction FROM lineages WHERE id=?", (original.lineage_id,)).fetchone()
            return self._load(db, row[0]) if row[0] else None

    def correction_context(self, binding: str) -> dict:
        """PRIVATE original bytes (None when omitted), digest/length and failure.

        Adapter supplies the original brief (digest checked against the request)
        and all unresolved objections. No format-only equivalence is certified.
        """
        with self._transaction() as db:
            return self._correction_context(db, self._load(db, binding))

    def _correction_context(self, db, request):
        failure = self._record(db, request.value["replaces_record_id"])
        original = self._load(db, failure.request_binding)
        self._source(db, original)
        d = db.execute("SELECT * FROM deliveries WHERE binding=?", (failure.request_binding,)).fetchone()
        _require(d is not None, "result_unavailable")
        facts = self._stored_facts(d, original)
        registration = json.loads(db.execute("SELECT body FROM registrations WHERE binding=?", (failure.request_binding,)).fetchone()[0])
        self._check_delivery(d, registration, facts)
        _require(facts["body_digest"] == failure.body_digest and facts["transport_digest"] == failure.transport_digest, "result_unavailable")
        return {"original_body": d["raw"], "original_body_retained": d["omitted"] is None,
                "original_body_absence_reason": "limit_exceeded" if d["omitted"] is not None else None,
                "original_body_digest": facts["body_digest"], "original_body_bytes": facts["body_bytes"],
                "failure": asdict(failure), "brief_digest": request.value["brief_digest"],
                "original_brief": self._brief(db, original)}

    def _ledger(self, db, lineages, carried):
        _require(type(lineages) is list and len(set(lineages)) == len(lineages))
        _require(type(carried) is list and len(set(carried)) == len(carried))
        entries, records, carry_records = [], [], []
        for lineage_id in lineages:
            row = db.execute("SELECT * FROM lineages WHERE id=?", (lineage_id,)).fetchone()
            _require(row is not None and row["standing"] is not None, "result_unavailable")
            records.append(row["standing"])
        for carry_id in carried:
            row = db.execute("SELECT body FROM carries WHERE id=?", (carry_id,)).fetchone()
            _require(row is not None)
            carry = json.loads(row[0])
            _require(canonical_digest("carry", carry) == carry_id and carry["policy_digest"] == self.policy.identity)
            records.append(carry["record_id"])
            carry_records.append(carry)
        _require(len(set(records)) == len(records))
        for record_id in records:
            record = self._record(db, record_id)
            request = self._load(db, record.request_binding)
            r = request.value
            _require(r["function"] == "EmitReviewReply")
            self._source(db, request)
            current = db.execute("SELECT latest FROM deliveries WHERE binding=?", (record.request_binding,)).fetchone()
            _require(current is not None and current[0] == record_id, "result_unavailable")
            if record.content_valid:
                body = json.loads(db.execute("SELECT parsed FROM records WHERE id=?", (record_id,)).fetchone()[0])
                _require(_sha(canonical_json(body)) == record.parsed_digest)
                for f in body["findings"]:
                    entries.append({"key": canonical_digest("finding", [record_id, f["id"]]), "record_id": record_id,
                        "seat": r["seat"], "kind": "finding", "blocking": f["severity"] == "BLOCKING", "body": f})
            if not record.usable:
                entries.append({"key": canonical_digest("finding", [record_id, None]), "record_id": record_id,
                    "seat": r["seat"], "kind": "status", "blocking": r["admission"]["unusable_seat_blocks"],
                    "body": {"outcome": record.outcome, "rejection_code": record.rejection_code}})
        return {"lineages": lineages, "carried": carried, "carry_records": carry_records, "records": records, "entries": entries}

    def register_carry(self, record_id: str, *, reviewed_delta_digest: str, current_applicability_digest: str) -> str:
        """Coordinator's explicit delta applicability record; no vote upgrade.

        Host supplies digests of the reviewed delta and its current applicability
        decision under existing policy. This retains original source/body identity.
        """
        _require(_digest(reviewed_delta_digest) and _digest(current_applicability_digest))
        with self._transaction() as db:
            record = self._record(db, record_id)
            _require(record.content_valid)
            original = self._load(db, record.request_binding)
            self._source(db, original)
            carry = {"record_id": record_id, "old_request_binding": record.request_binding,
                "old_input_digest": record.source_manifest_digest, "reviewed_delta_digest": reviewed_delta_digest,
                "current_applicability_digest": current_applicability_digest, "policy_digest": self.policy.identity}
            carry_id = canonical_digest("carry", carry)
            db.execute("INSERT OR IGNORE INTO carries VALUES (?, ?)", (carry_id, canonical_json(carry).decode()))
            return carry_id

    def build_ledger(self, lineage_ids: list[str], *, carry_ids: list[str] | None = None) -> dict:
        """Private complete ledger for the coordinator's full seat roster.

        Includes incomplete findings/statuses, preserves distinct seats' local IDs,
        and explicitly carried records. Host owns roster completeness and delta
        applicability; callers cannot invent ledger bodies at president intake.
        """
        with self._transaction() as db:
            return self._ledger(db, lineage_ids, carry_ids or [])
