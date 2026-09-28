#!/usr/bin/env python3
"""Observe the real brokered route and validate distinct qualification records.

A shim: the driver lives in the package (``phase_loop_runtime.agy_qualification``) so an
installed runtime can run it too (agent-harness#1076). Run it from the tree under
qualification (``PYTHONPATH=src``); the worker it spawns imports that same tree.
"""
from phase_loop_runtime.agy_qualification import main

if __name__ == "__main__":
    raise SystemExit(main())
