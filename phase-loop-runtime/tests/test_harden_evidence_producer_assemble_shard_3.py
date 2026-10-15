"""Shard 3 of 4 of the HARDEN producer assemble attack table.

The table lives in tests/test_harden_evidence_producer.py, which also checks
this file's exact text (see HARDEN_ATTACK_SHARDS there).
"""

from tests import test_harden_evidence_producer as producer


def test_harden_producer_assembles_only_contained_retained_evidence_shard_3(tmp_path):
    producer._assemble_attack_table(tmp_path, shard=3)
