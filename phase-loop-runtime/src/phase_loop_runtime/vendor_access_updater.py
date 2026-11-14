"""Unregistered synthetic publication tick with injected bounded operations.

No production transport, activation loader, account reader or scheduler. The
publisher must authenticate its gateway and preserve request correlation. Local
flock is cooperative only; cross-host principal enforcement remains unresolved.
Only durably acknowledged publications allow fresh-source restart reconciliation.
Ambiguous and known-not-sent prepared attempts block without retry or reset.
"""
from dataclasses import dataclass, replace
import hashlib
import secrets
import time
import uuid

from .vendor_access_pending import load_pending, record_pending
from .vendor_access_preflight import activation_refusal, binding_digest, preflight
from .vendor_access_publication import publication_decision
from .vendor_access_publication_journal import (
    PublicationRecord, load_publication, transition_publication)
from .vendor_access_response import DecodedMutation
from .vendor_access_wire_response import decode_mutation_wire
from .vendor_access_writer import private_directory_writer


@dataclass(frozen=True)
class UpdateTickResult:
    code: str
    desired_mutation: DecodedMutation | None = None


class VendorAccessUpdater:
    """Process-local acknowledged comparison state for a single frozen binding.

    The immutable first-request barrier remains for downgrade safety: older code
    refuses instead of treating journal-only state as virgin. A separate minimal
    journal permits ACK-only restart reconciliation from fresh metadata/source.
    Prepared attempts remain blocked even if encoding or setup prevented a send.
    Restart loses the comparison fingerprint and may republish once per restart.
    Successful metadata decoding acknowledges storage only, never application.
    All injected operations are synchronous and must enforce bounded deadlines.
    """
    def __init__(self, binding, *, clock=time.time):
        self._binding = binding
        self._digest = binding_digest(binding)
        self._publication_digest = hashlib.sha256(
            ('vendor-access-publication-barrier-v1:' + self._digest).encode('ascii')).hexdigest()
        self._publication_marker = None
        self._initialized = False
        self._expected = None
        self._key = secrets.token_bytes(32)
        self._acknowledged = None
        self._uncertain = False
        self._clock = clock

    def tick_encoded(self, activation, directory, inspect_provider, read_source, invoke):
        """Encode after durable barrier; invoke receives sensitive bytes once.

        invoke(binding, payload) must enforce deadlines, authenticate the gateway
        and return the correlated bounded ProviderResponse bytes. It must never
        log/persist the request. Encoding rechecks expiry with a fresh clock read.
        A refusal leaves the barrier intact and requires reconciliation, without
        invoking the gateway or treating a captured value as acknowledged.
        """
        from .vendor_access_update_wire import serialize_access_update

        def publish(binding, snapshot, request_id, resource_version):
            payload = serialize_access_update(binding, snapshot, request_id,
                                               resource_version, now=self._clock())
            return invoke(binding, payload)

        return self.tick(activation, directory, inspect_provider, read_source, publish)

    def tick(self, activation, directory, inspect_provider, read_source, publish):
        if activation_refusal(self._binding, activation) is not None:
            return UpdateTickResult('held')
        acquired = False
        try:
            with private_directory_writer(directory) as locked:
                acquired = True
                return self._locked_tick(activation, locked, inspect_provider, read_source, publish)
        except BlockingIOError:
            if not acquired:
                return UpdateTickResult('writer_busy')
            self._uncertain = True
            return UpdateTickResult('journal_unavailable')
        except (OSError, ValueError):
            self._uncertain = True
            return UpdateTickResult('journal_unavailable')

    def _locked_tick(self, activation, directory, inspect_provider, read_source, publish):
        if load_pending(directory, self._digest) is not None:
            return UpdateTickResult('revocation_pending')
        barrier = load_pending(directory, self._publication_digest)
        journal = load_publication(directory, self._digest)
        if self._uncertain:
            return UpdateTickResult('publication_reconciliation_required')
        if self._initialized:
            matches = barrier == self._publication_marker and journal == self._expected
        else:
            matches = ((barrier is None and journal is None) or (
                journal is not None and journal.barrier_id == barrier
                and journal.phase == 'acknowledged'))
        if not matches:
            self._uncertain = True  # retire superseded instances before suppression
            return UpdateTickResult('publication_reconciliation_required')
        if not self._initialized:
            if journal is not None:
                if load_publication(directory, self._digest, durable=True) != journal:
                    raise ValueError('publication_record_changed')
            self._publication_marker = barrier
            self._expected = journal
            self._initialized = True
        checked = preflight(self._binding, activation, inspect_provider)
        if checked.state != 'eligible':
            return UpdateTickResult(checked.code)
        try:
            captured = read_source(self._binding)
            current = read_source(self._binding)
            # Recheck even though cooperative writers are excluded: the injected
            # source may discover and persist revocation while reading.
            pending = load_pending(directory, self._digest) is not None
            decision = publication_decision(self._binding, captured, current,
                key=self._key, now=self._clock(), revocation_pending=pending,
                acknowledged_fingerprint=self._acknowledged)
        except Exception:
            return UpdateTickResult('source_unverified')
        if decision.action != 'publish':
            return UpdateTickResult(decision.code)
        # Mark uncertain BEFORE crossing the mutation boundary. BaseException
        # also leaves this instance blocked; no captured credential is replayed.
        request_id = str(uuid.uuid4())
        self._uncertain = True
        # Reuse the private journal's fsync/link safety. This is a distinct key
        # from the revocation tombstone and cannot satisfy or clear revocation.
        marker = self._publication_marker or request_id
        record_pending(directory, self._publication_digest, marker)
        prepared = PublicationRecord(1, self._digest, marker, request_id, 'prepared')
        transition_publication(directory, self._digest, self._expected, prepared,
                               barrier_created=barrier is None)
        self._publication_marker = marker
        self._expected = prepared
        if load_pending(directory, self._digest) is not None:
            return UpdateTickResult('revocation_pending')
        try:
            response = publish(self._binding, current, request_id, checked.resource_version)
            desired = decode_mutation_wire(self._binding, response)
        except Exception:
            return UpdateTickResult('publication_reconciliation_required')
        acknowledged = replace(prepared, phase='acknowledged')
        transition_publication(directory, self._digest, prepared, acknowledged)
        self._expected = acknowledged
        self._acknowledged = decision.fingerprint
        self._uncertain = False
        return UpdateTickResult('persisted_pending_application', desired)
