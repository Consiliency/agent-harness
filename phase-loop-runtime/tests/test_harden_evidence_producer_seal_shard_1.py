"""Shard 1 of 4 of the HARDEN producer seal attack table.

The table lives in tests/test_harden_evidence_producer.py, which also checks
this file's exact text (see HARDEN_ATTACK_SHARDS there).
"""

from tests import test_harden_evidence_producer as producer


def test_harden_producer_prepare_then_seal_binds_one_canonical_event_shard_1(tmp_path):
    producer._seal_attack_table(tmp_path, shard=1)
