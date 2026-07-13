"""Opt-in construction of a live, credential-capable GitHub broker client.

This is the *only* helper that assembles a broker able to perform a real GitHub
mutation.  It is never auto-instantiated: legacy ``run_train`` callers that pass
no ``coordinator_runtime`` (or a runtime with ``broker_client=None``) publish
exactly as before.  A caller wanting broker-mediated publication builds a client
here and attaches it to :class:`CoordinatorRuntime.broker_client`.

The wired client enforces every already-merged safety property: linearizable
admission, permanent fail-closed ``outcome_ambiguous_blocked`` evidence, canonical
``(repo, branch, head_sha)`` idempotency, and the adapter's exact-published-head
verification.  Only the ``publish_committed_branch``/``github`` verb is SUPPORTED
(see ``provider_contracts``); the service refuses every other verb.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from phase_loop_runtime.convergence.contracts import AdmissionRequest
from phase_loop_runtime.convergence.provider_contracts import PROVIDER_COMPLETION_CLASSIFICATIONS

from .admission import BrokerAdmissionPolicy, LinearizableAdmissionStore
from .credsep import GitHubBrokerAdapter
from .evidence import BrokerEvidenceStore
from .verbs import BrokerClient, BrokerService


def _default_admission_policy(_request: AdmissionRequest) -> bool:
    """Admit any structurally-valid admission request.

    ``AdmissionRequest.__post_init__`` already rejects a request missing any
    fencing field, so a request that reaches the policy is well-formed.  Epoch
    staleness and idempotency-key conflicts are enforced inside
    ``LinearizableAdmissionStore.admit`` regardless of this policy.
    """
    return True


def build_github_broker_client(
    repo_path: Path,
    *,
    broker_root: Path,
    admission_policy: BrokerAdmissionPolicy | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> BrokerClient:
    """Wire a live GitHub broker client.

    Parameters
    ----------
    repo_path:
        Worktree the :class:`GitHubBrokerAdapter` runs git/gh against.
    broker_root:
        Durable directory for the admission log + terminal-evidence log.  MUST
        live OUTSIDE ``repo_path`` (e.g. ``CoordinatorRuntime.coordinator_root``)
        so broker state never dirties the worktree being published — a dirty
        worktree trips the publish staged-diff audit and the train clean-worktree
        preflight.
    admission_policy:
        Optional admission gate; defaults to admitting any well-formed request.
    run:
        Injectable subprocess runner (tests pass a fake to mock the git/gh seam).

    Returns
    -------
    BrokerClient
        A :class:`BrokerService` bound to the global (verb-gated) contracts, so
        only ``publish_committed_branch``/``github`` can execute.
    """
    admission_store = LinearizableAdmissionStore(
        Path(broker_root),
        admission_policy or _default_admission_policy,
    )
    evidence_store = BrokerEvidenceStore(Path(broker_root))
    adapter = GitHubBrokerAdapter(Path(repo_path), run=run)
    return BrokerService(
        admission_store,
        evidence_store,
        adapter,
        contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,
    )
