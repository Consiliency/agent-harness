# W0 bake-off records (SEATS CLAUDE, EC-CLAUDE-5)

One `claude-bakeoff-record.v1` record per W0 run, `<run_id>.json`, written by
`python -m phase_loop_runtime.claude_bakeoff run` in the owner's W0 window and landed in a
reviewed records PR (G2). The schema is closed and metadata-only: meter readings and raw
request captures stay in the operator's private storage, and a record carries their
digests. `python -m phase_loop_runtime.claude_bakeoff validate` is the shape check (V7);
`python -m phase_loop_runtime.claude_bakeoff digest` is the evidence digest an OD-3b
section cites. V7 never runs a W0 head's code: each record's head must be on `main`, and
the TUI jail digest is computed by the validating runtime itself, for a head whose jail
source is byte-identical to its own. For any other head, validate from a checkout at that
head or pass `--tui-digest`. Native observations travel only over the launching parent's
inherited descriptor, and capture-twin descendants are gone before a native run begins. That
boundary is against the jailed seat: a process of the owner's own uid stays outside it, so an
observation is sound only if no such process misbehaved in the window, and a record names its
unconfined co-seats in `co_seats_unconfined`.
No record is here until W0 runs.
