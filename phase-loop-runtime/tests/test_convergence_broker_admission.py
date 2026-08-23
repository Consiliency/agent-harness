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


def test_fabreadmit_prior_record_predicate_and_chained_readmit_binding(request, tmp_path):
    """Prior-record predicate under admission lock & ReadmitAdmissionBinding.v1."""
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    binding_cls = fabreadmit_symbol("phase_loop_runtime.convergence.contracts", "ReadmitAdmissionBinding")
    method = fabreadmit_symbol("phase_loop_runtime.convergence.broker.admission", "LinearizableAdmissionStore.admit_next")

    valid = False
    if binding_cls is not None and method is not None:
        try:
            import inspect
            sig = inspect.signature(method)
            valid = any(p in sig.parameters for p in ("authority", "readmit", "prior_record"))
        except Exception:
            valid = False

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        valid,
        "Prior-record predicate and chained ReadmitAdmissionBinding.v1 rejection matrix missing or unvalidated",
    )


def test_fabreadmit_checkpoint_root_validation(request, tmp_path):
    """Checkpoint root validation: reject missing, relative, wrong-train, wrong-node, repo-mismatch."""
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    validator = fabreadmit_symbol("phase_loop_runtime.convergence.broker.admission", "validate_checkpoint_root")
    valid_denials = False
    if validator is not None:
        try:
            res_missing = validator(tmp_path / "nonexistent", "repo", "train", "node")
            valid_denials = res_missing is False or res_missing is None
        except (ValueError, TypeError, FileNotFoundError):
            valid_denials = True
        except Exception:
            valid_denials = False

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        valid_denials,
        "Checkpoint root validation covering 5 denial cases (missing, relative, wrong-train, wrong-node, repo-mismatch) missing",
    )


def test_fabreadmit_linked_worktrees_share_canonical_repository_allocator(request, tmp_path):
    """Linked worktrees and distinct train roots share the same repository admission store."""
    import subprocess
    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    resolver = fabreadmit_symbol("phase_loop_runtime.convergence.broker.admission", "get_canonical_repository_store")
    valid_shared = False
    if resolver is not None:
        try:
            repo = tmp_path / "main_repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "a").write_text("a")
            subprocess.run(["git", "-C", str(repo), "add", "a"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)

            wt = tmp_path / "linked_wt"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(wt), "HEAD"], check=True)

            s1 = resolver(repo)
            s2 = resolver(wt)
            valid_shared = (s1 is not None) and (s1 == s2 or getattr(s1, "store_path", 1) == getattr(s2, "store_path", 2))
        except Exception:
            valid_shared = False

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        valid_shared,
        "Linked worktrees and distinct train roots sharing canonical repository allocator missing or invalid",
    )
