# placement-cli black-box fixtures (v13 PLACECLI)

Language-neutral vectors for `agent-harness-placement`, run as separate processes by
`tests/test_placement_cli.py` through `run_cli.py` against `fake_coordinator.py`.

- `cases.json`: one case per agent-toolkit live step L0 to L9, plus coordinator
  unavailable, deadline, lost reply, snapshot expiry and duplicate binding. Each case maps a
  live step to the closed placement outcome a shim observes offline. None of it is live
  evidence.
- `fake_coordinator.py`: a generic fake backend. Its behaviour comes only from the knobs in
  the behaviour file (`admit`, `kill`). It never reads a case identifier.
- `fake_cred_proxy.py`: a behavioural fake of agent-toolkit's `cred-proxy.mjs`, used by
  `tests/test_placement_bridge.py`. The guest holds placeholders; the credential never
  crosses back.
