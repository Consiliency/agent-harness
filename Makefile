# Local pre-PR checks (agent-harness#1029). See phase-loop-runtime/scripts/local_check.py.
.PHONY: check check-full
check:
	python3 phase-loop-runtime/scripts/local_check.py
check-full:
	python3 phase-loop-runtime/scripts/local_check.py --full
