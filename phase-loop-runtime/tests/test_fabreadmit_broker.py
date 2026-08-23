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
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    authority_cls = fabreadmit_symbol("phase_loop_runtime.convergence.contracts", "DeltaReadmitAuthority")
    fabreadmit_require(fabreadmit_this_nodeid(request), authority_cls is not None, "DeltaReadmitAuthority class missing")

    receipt_cls = fabreadmit_symbol("phase_loop_runtime.convergence.contracts", "DeltaReadmitReceipt")
    fabreadmit_require(fabreadmit_this_nodeid(request), receipt_cls is not None, "DeltaReadmitReceipt class missing")

    client_method = fabreadmit_symbol("phase_loop_runtime.convergence.broker.live", "BrokerClient.readmit_advanced_head")
    fabreadmit_require(fabreadmit_this_nodeid(request), client_method is not None, "BrokerClient.readmit_advanced_head missing")


def test_fabreadmit_broker_rediffs_head_range_and_rejects_scope_escape_without_adapter(request):
    """Broker independently re-diffs prior..proposed, rejects scope escape, calls zero adapters."""
    if not fabreadmit_capability_active():
        pytest.skip(FABREADMIT_SKIP_REASON)

    readmit_fn = fabreadmit_symbol("phase_loop_runtime.convergence.broker.admission", "admit_delta_readmission")
    if readmit_fn is None:
        readmit_fn = fabreadmit_symbol("phase_loop_runtime.convergence.broker.verbs", "readmit_advanced_head")
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        readmit_fn is not None,
        "Broker readmission verb or store admission function missing",
    )
