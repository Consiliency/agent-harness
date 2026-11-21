"""The grok release catalog and the measured-build query (GROKROLL).

The rules are frozen in ``plans/artifacts/grokroll-v1-contract.md`` ("GROKROLL"); each
module names the sections it implements.

- :mod:`.catalog` (§1, §2.4, §2.5): the release catalog loader, the gate file, the
  offline signature check and the tree invariant ``check_tree``.
- :mod:`.evidence` (§3.1, §3.2): typed reads of every evidence source, which tell a
  corrupt source from an absent one, and the route and build states over them.
- :mod:`.status` (§3, §5.1): ``phase-loop seat-window status --vendor grok`` and its
  ``grok_seat_status.v1`` object.

Nothing here executes a provider binary, opens a socket or writes a file. The package lives
outside ``seat_window.runtime_digest()``. The CLI is the supported surface; these Python
functions are not.
"""
