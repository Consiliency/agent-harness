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
from .credsep import ALLOWED_ORIGIN_HOSTS, GitHubBrokerAdapter
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


class _RoutingGitHubAdapter:
    """Bind a fresh :class:`GitHubBrokerAdapter` to each request's repo path.

    ``build_github_broker_client`` fixes ONE ``repo_path`` at construction, so a
    single broker client can only faithfully serve one repo — a multi-repo
    ``run_train`` that threads one ``coordinator_runtime.broker_client`` across every
    node would run ``git -C <wrong-repo>`` and trip the branch/head guard on node 2+.
    ``publish_from_worktree`` sets ``BrokerRequest.repo`` to the node's resolved
    workspace path, so routing on ``request.repo`` binds the adapter to the correct
    worktree per call.  The per-repo adapter's origin-host allow-list still guards
    ``request.repo``, so per-request binding is safe.
    """

    def __init__(
        self,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        allowed_hosts=ALLOWED_ORIGIN_HOSTS,
    ) -> None:
        self.run = run
        self.allowed_hosts = allowed_hosts

    def execute(self, request):
        return GitHubBrokerAdapter(
            Path(request.repo), run=self.run, allowed_hosts=self.allowed_hosts
        ).execute(request)


def build_routing_broker_client(
    *,
    broker_root: Path,
    admission_policy: BrokerAdmissionPolicy | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    allowed_hosts=ALLOWED_ORIGIN_HOSTS,
) -> BrokerClient:
    """Wire a live GitHub broker client that serves a MULTI-repo train.

    Identical to :func:`build_github_broker_client` except the git/gh adapter is bound
    per request to ``BrokerRequest.repo`` (via :class:`_RoutingGitHubAdapter`) instead
    of to one fixed ``repo_path``.  This is what a cross-repo ``run_train`` needs: one
    coordinator, one durable ``broker_root`` (admission + evidence), and correct
    ``git -C <that node's workspace>`` binding for every node.

    Sharing the admission + evidence stores across repos is safe: the
    ``publish_committed_branch`` de-dup key is ``sha256(repo\\0branch\\0head)`` (the repo
    is in the key), so cross-repo requests never collide.

    Parameters
    ----------
    broker_root:
        Durable directory for the admission + terminal-evidence logs.  MUST live
        OUTSIDE every node's worktree (e.g. ``CoordinatorRuntime.coordinator_root``).
    admission_policy:
        Optional admission gate; defaults to admitting any well-formed request.
    run:
        Injectable subprocess runner (tests pass a fake to mock the git/gh seam).
    allowed_hosts:
        Origin-host allow-list applied to every per-request adapter (github.com-only
        by default); a self-hosted/GHE fleet passes its own set.
    """
    admission_store = LinearizableAdmissionStore(
        Path(broker_root),
        admission_policy or _default_admission_policy,
    )
    evidence_store = BrokerEvidenceStore(Path(broker_root))
    adapter = _RoutingGitHubAdapter(run=run, allowed_hosts=allowed_hosts)
    return BrokerService(
        admission_store,
        evidence_store,
        adapter,
        contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,
    )
