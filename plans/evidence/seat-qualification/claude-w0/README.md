# W0 bake-off records (SEATS CLAUDE, EC-CLAUDE-5)

One `claude-bakeoff-record.v1` record per W0 run, `<run_id>.json`, written by
`python -m phase_loop_runtime.claude_bakeoff run` in the owner's W0 window and landed in a
reviewed records PR (G2). The schema is closed and metadata-only: meter readings and raw
request captures stay in the operator's private storage, and a record carries their
digests. `python -m phase_loop_runtime.claude_bakeoff validate` is the shape check (V7);
`python -m phase_loop_runtime.claude_bakeoff digest` is the evidence digest an OD-3b
section cites. No record is here until W0 runs.
