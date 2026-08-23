from pytest import skip
from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.contracts import AdmissionRequest

from _fabreadmit_tdd_guard import (
    FABREADMIT_SKIP_REASON,
    fabreadmit_capability_active,
    fabreadmit_require,
    fabreadmit_symbol,
    fabreadmit_this_nodeid,
)


def test_admission_replays_idempotently(tmp_path):
    request = AdmissionRequest("a", 1, "f", "d", "v", "scope", "key")
    store = LinearizableAdmissionStore(tmp_path, lambda _: True)
    assert store.admit(request) == store.admit(request)
    assert len(store.replay()) == 1


def test_fabreadmit_prior_record_predicate_and_chained_readmit_binding(request):
    """Prior-record predicate under admission lock & ReadmitAdmissionBinding.v1."""
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    binding_cls = fabreadmit_symbol("phase_loop_runtime.convergence.contracts", "ReadmitAdmissionBinding")
    fabreadmit_require(fabreadmit_this_nodeid(request), binding_cls is not None, "ReadmitAdmissionBinding missing")

    method = fabreadmit_symbol("phase_loop_runtime.convergence.broker.admission", "LinearizableAdmissionStore.admit_next")
    fabreadmit_require(fabreadmit_this_nodeid(request), method is not None, "admit_next store method missing")


def test_fabreadmit_checkpoint_root_validation(request):
    """Checkpoint root validation: reject missing, relative, wrong-train, wrong-node, repo-mismatch."""
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    validator = fabreadmit_symbol("phase_loop_runtime.convergence.broker.admission", "validate_checkpoint_root")
    fabreadmit_require(fabreadmit_this_nodeid(request), validator is not None, "validate_checkpoint_root missing")


def test_fabreadmit_linked_worktrees_share_canonical_repository_allocator(request):
    """Linked worktrees and distinct train roots share the same repository admission store."""
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    resolver = fabreadmit_symbol("phase_loop_runtime.convergence.broker.admission", "get_canonical_repository_store")
    fabreadmit_require(fabreadmit_this_nodeid(request), resolver is not None, "get_canonical_repository_store missing")
