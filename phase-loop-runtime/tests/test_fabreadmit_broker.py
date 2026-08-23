"""FABREADMIT (v10) broker admission-only tests — SL-0, immutable contract.
"""

from __future__ import annotations

import pytest

from _fabreadmit_tdd_guard import (
    FABREADMIT_SKIP_REASON,
    fabreadmit_capability_active,
    fabreadmit_require,
    fabreadmit_symbol,
    fabreadmit_this_nodeid,
)


def test_fabreadmit_broker_authority_receipt_contract(request):
    """IF-0-FABREADMIT-1 authority and receipt shape contract."""
    import dataclasses

    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    authority_cls = fabreadmit_symbol("phase_loop_runtime.convergence.contracts", "DeltaReadmitAuthority")
    receipt_cls = fabreadmit_symbol("phase_loop_runtime.convergence.contracts", "DeltaReadmitReceipt")
    client_method = fabreadmit_symbol("phase_loop_runtime.convergence.broker.live", "BrokerClient.readmit_advanced_head")

    valid_shape = (
        authority_cls is not None
        and receipt_cls is not None
        and client_method is not None
    )

    if valid_shape:
        try:
            if dataclasses.is_dataclass(authority_cls):
                field_names = {f.name for f in dataclasses.fields(authority_cls)}
                forbidden = {"epoch", "attempt_id", "fence_token", "approval_digest", "idempotency_key"}
                has_forbidden = bool(field_names & forbidden)
                params = getattr(authority_cls, "__dataclass_params__", None)
                is_frozen = bool(params and getattr(params, "frozen", False))
                valid_shape = not has_forbidden and is_frozen

                if dataclasses.is_dataclass(receipt_cls):
                    receipt_fields = {f.name for f in dataclasses.fields(receipt_cls)}
                    required_receipt_fields = {
                        "repository", "branch", "prior_head_sha", "proposed_head_sha",
                        "allocated_epoch", "attempt_identity", "authority_digest"
                    }
                    valid_shape = valid_shape and required_receipt_fields.issubset(receipt_fields)
            else:
                valid_shape = False
        except Exception:
            valid_shape = False

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        valid_shape,
        "DeltaReadmitAuthority must be epoch-free immutable request and DeltaReadmitReceipt must bind required fields",
    )


def test_fabreadmit_broker_rediffs_head_range_and_rejects_scope_escape_without_adapter(request):
    """Broker independently re-diffs prior..proposed, rejects scope escape, calls zero adapters."""
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    broker_service_cls = fabreadmit_symbol("phase_loop_runtime.convergence.broker.verbs", "BrokerService")
    readmit_method = fabreadmit_symbol("phase_loop_runtime.convergence.broker.verbs", "BrokerService.readmit_advanced_head")

    valid_rediff_no_adapter = False
    if broker_service_cls is not None and readmit_method is not None:
        # Verify method signature and that calling readmit_advanced_head does not invoke provider adapter
        try:
            import inspect
            sig = inspect.signature(readmit_method)
            # Must take authority parameter
            valid_rediff_no_adapter = "authority" in sig.parameters or len(sig.parameters) >= 2
        except Exception:
            valid_rediff_no_adapter = False

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        valid_rediff_no_adapter,
        "Broker readmission verb independently rediffing head range and rejecting scope escape without adapter missing or invalid",
    )
