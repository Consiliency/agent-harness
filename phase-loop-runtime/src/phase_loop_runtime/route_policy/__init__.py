"""Packaged Claude route-selection policy fixtures.

This package marker makes ``fixtures/route_selection.golden.json`` available
through ``importlib.resources``. ``tests/test_route_policy_conformance.py`` checks
the Python launcher's route selection, billing posture, and fallback posture
against these fixtures.
"""
