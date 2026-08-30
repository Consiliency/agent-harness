#!/bin/bash
cd /mnt/workspace/worktrees/ah-633-preflight/phase-loop-runtime
PYTHONPATH=src:tests python3 -u -m pytest tests/ -q --no-header
