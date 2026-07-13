import phase_loop_runtime.convergence as convergence


def test_runtime_import_surface_exposes_runtime_gate():
    for name in ("default_convergence_event_log_path", "record_intent", "record_outcome", "read_convergence_events", "recover_train_state", "reconcile_train_state"):
        assert hasattr(convergence, name)
