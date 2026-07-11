# Verification: task-message persistence compatibility

Summary: PASSED — focused resolver suite 24/24; standalone runtime suite 2,244 passed, 35 skipped, 592 deselected, 551 subtests passed; 0.7.0 sdist and wheel built successfully; live owner-socket initialize passed on ai and claw; exact two-message claw round trip passed at `2e0cc16939b5010f04cdc5ab78f43a6da6e94df7`.

- `uv run --with pytest python -m pytest tests/test_task_message_resolver.py -q` — PASS (`24 passed in 0.26s`).
- `uv run --with pytest python -m pytest -m 'not dotfiles_integration' -q` — PASS (`2244 passed, 35 skipped, 592 deselected, 551 subtests passed in 97.72s`).
- `uv run --with build python -m build` — PASS (`phase_loop_runtime-0.7.0.tar.gz` and `phase_loop_runtime-0.7.0-py3-none-any.whl`).
- `git diff --check` — PASS.

Live transport evidence passed on both ai and claw against the real Codex Desktop-managed app-server 0.144.1 owner socket using WebSocket-over-Unix with compression disabled. The divergent secondary WebSocket listener remains disabled and port 8765 remains closed.

The terminal live gate passed on claw in disposable archived task `019f52a0-8dda-7e11-b0bf-f8e73206af45`: separate source and approval messages persisted as distinct `item-1` / `item-3` records with exact client IDs and source-before-approval ordering. The branch-local resolver verified exact source and approval bytes, source SHA-256 `bb1df0ecf76cdd76914fc3e45154f332777268b338bbe8406950c0071b30b8d9`, raw approval SHA-256 `ed460097bb62cb00e3a82404abdf2712efe70bbc450921fde52c71da75455c9a`, and the same RFC 8785 canonical digest. An immediate post-terminal read briefly raced client-ID materialization; a subsequent raw owner-socket read and the resolver both observed the complete persisted state. No retry messages or second task were created.

Review evidence: Grok AGREE; Gemini AGREE; Fabel AGREE after a supported headless subscription review. Sol's post-fix re-review is AGREE: the duplicate stored-ID and initialize-failure lifecycle defects are fixed and covered, and the live round trip has now passed.
