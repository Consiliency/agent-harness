# JEVHOST amendment S5-W1: native-Windows runtime fixes to verbatim files

Status: **Proposal for review. JEV Drill's agreement is pending.** This amendment records
the follow-up to agent-harness#2092, which came after the import fix,
agent-harness#2123. It does not edit the frozen contract
`plans/artifacts/jevhost-v1-contract.md`. At this amendment's base, that file's sha256 is
`1fa957afc8f7b3a324a8f048695b3d2ebf1009336a1d49407d33dfc1b36f4e1d`.

Until JEV Drill agrees, the following hold:
- these changes are disclosed as not-yet-agreed edits to files that §2 classes as
  verbatim;
- the S5 Windows proof stays **pending** under §8/R3 until JEV Drill agrees to the
  exception and the native `windows-2025` proof is recorded.

## Why an amendment

The JEVHOST §2 table classes four of the changed files as "New, verbatim", copied from
JEV Drill's draft:
- `src/phase_loop_runtime/windows_storage.py`;
- `src/phase_loop_runtime/windows_process.py` (row E);
- `tests/test_jevdrill_input.py`;
- `tests/test_jevdrill_usage.py`.

S5 permits a fix that is only a platform guard, but only within its owned file,
`convergence/broker/live.py`. That permission does not extend to the files above. JEV
Drill's agreement is therefore requested, under §2, for these changes:
- the structural rewrite of the ACL check (A);
- the edit to `test_jevdrill_input.py` (C);
- the edit to `test_jevdrill_usage.py` (D);
- the byte-exact stdin of the Windows admitted child in `windows_process.py` (E);
- the Windows branches in six `test_jevdrill_usage.py` tests (F).

The launcher changes (B and G) are disclosed separately below.

The first `windows-2025` run of the companion workflow failed on four causes. They are
diagnosed in the coordinator's review record for agent-harness#2092, and this amendment
uses its cause letters.

Rows E and F come from the second `windows-2025` run, made on the code of rows A to D.
Both legs finished with no stall, and the same eleven tests failed in each. Rows E and F
are in a separate pull request stacked on the one for rows A to D.

## Changes recorded

| # | File | Change | Kind |
| --- | --- | --- | --- |
| A | `windows_storage.py` `PrivateSecurity.verify` | The exact comparison of SDDL strings becomes a structural check of the DACL (see below). The creation descriptor is unchanged. | More than a platform guard, in a verbatim file, so JEV Drill's agreement is requested. POSIX is unaffected: the native API initializer rejects non-Windows use. |
| B | `launcher.py` `_worktree_change_snapshot` | On native Windows it returns `None` before calling `host_git`, whose trusted-helper resolution is POSIX-only. Changed paths stay unknown on Windows. | A platform guard, disclosed separately. `launcher.py` is a §2 "Modified, conflicting" file. It is the only JEV-pinned adapter module this change touches. |
| C | `tests/test_jevdrill_input.py` `input_spec` | On Windows, prefixes `sys.executable` to the child command, as `synthetic_spec` in `test_jevdrill_usage.py` already does. | Test portability, in a verbatim file, so JEV Drill's agreement is requested. The POSIX command is unchanged. |
| D | `tests/test_jevdrill_usage.py` `test_permanent_invalidation` | The 1 MiB parameter gets `id="oversized_line"`. The generated ID was longer than the 32767-character limit for a Windows environment variable, and pytest stores the node ID in `PYTEST_CURRENT_TEST`. Both Windows logs stop where pytest would begin reporting the oversized node ID. This strongly implicates the ID. Runner output backpressure remains unconfirmed. | Changes only the test ID, in a verbatim file, so JEV Drill's agreement is requested. [C7] compares names without parametrize ids (`tests/data/jevdrill_test_names.json`), so name stability is unaffected. |
| E | `windows_process.py` `_admitted_child` | The executor's stdin is written as UTF-8 bytes. Before, it was written through a text-mode pipe (`text=True, encoding="utf-8"`). On Windows that pipe writes each `\n` as `\r\n`, so, for example, the executor got 40 bytes for a 37-byte payload. That caused the five `test_jevdrill_input.py` failures: both `test_manifest_matches_child_bytes_and_preserves_context` cases and all three `test_delivery_modes_use_the_resolved_payload` cases. The UTF-8 guarantee of agent-harness#2123 is kept, because bytes need no code page. | A product fix in a verbatim file, so JEV Drill's agreement is requested. Only native Windows runs this code: `run_owned` and the leased guardian both spawn it, and both are Windows-only. `windows_process` has no module digest in the JEV handoff. `tests/test_windows_runtime_guards.py` simulates the Windows newline translation on every platform. |
| F | `tests/test_jevdrill_usage.py`, six tests | Each test gets a Windows branch. On POSIX each test runs and asserts as before; the two fork tails gain only a `hasattr(os, "fork")` guard that is true there. `test_late_pipe_records_are_drained` and `test_incomplete_drain_is_unknown_and_bounded`: Windows has no `os.fork`, so the child skips the fork. The off-Linux branch asserts only the root's output. `test_observer_survives_lease_recursion`: the `fcntl` lock is taken on POSIX only. On Windows the bare lease authority is refused, and the existing `assert_disabled` branch applies. `test_cancel_drains_valid_observation`: no POSIX signal reaches the launcher from a job-owned child. The test therefore raises the interrupt in the launcher with `_thread.interrupt_main` once the child has started, and expects 130. `test_adapter_observed_failure_retains_identity[timeout]` and `[stall]`: the job object ends the tree, and no SIGTERM handler runs. The test therefore expects the Windows path's 124 for a timeout and 1 for a stall. | Test portability, in a verbatim file, so JEV Drill's agreement is requested. No test is skipped, because the receipt classifier allows only its four skip reasons. No test is renamed or reparametrized, so `tests/data/jevdrill_test_names.json` is unchanged. |
| G | `launcher.py` `launch`, the streaming path with no usage observer | When the child exits, the loop now waits, for at most one second, for the line reader's end-of-file marker. Before, it stopped after the lines already queued. The text pipe now decodes with `errors="replace"`, so invalid UTF-8 no longer kills the reader thread. Both bugs were in place before agent-harness#2127, whose launcher change is inactive off Windows. The macOS receipt leg exposed the first one in `test_stdout_only_and_final_drain`: the captured output held only the first stdout record. The second one was the run's `PytestUnhandledThreadExceptionWarning` in `test_real_decode_failure_stays_unknown`. | A product fix, disclosed separately like B. The observer path, which carries JEV usage capture on Linux, is unchanged. `launcher.py` is a §2 "Modified, conflicting" file and JEV-pinned, so adopting this follow-up would also re-pin it. `tests/test_launcher_reader_drain.py` reproduces both bugs deterministically. |

**JEV Drill's pin on `launcher.py`.**
- JEV Drill's current handoff pins the module digest of `launcher.py` at the previously
  accepted harness commit.
- If JEV Drill adopts this follow-up, it would need to re-pin `launcher.py`.
- `windows_storage.py` has no module digest in the handoff; §2 classes it as verbatim.

**The workflow change** needs no amendment, because §8's workflow shape covers it. It is
listed here for completeness. Both "Run the twelve files" steps get a 20-minute step
timeout. The step timeout leaves time for the always() upload if pytest has already
written the junit and the job still has time remaining.

## A: the structural check and why it is at least as strict

**Before.** `verify` rendered the object's DACL as SDDL. It required that string to equal
`D:P(A;;FA;;;SY)(A;;FA;;;<user SID string>)` byte for byte. On `windows-2025` it refused
directories that this same code had just created with that descriptor.

Two explanations are possible. Neither is confirmed until the returned descriptor is
inspected:
- NTFS may store a protected DACL created under an auto-inherited parent with
  `SE_DACL_AUTO_INHERITED` also set. That DACL renders as `D:PAI(…)`.
- The SDDL converter may render the user as an alias such as `LA`, where the expected
  string has the numeric SID.

**After.** The owner check is unchanged. The DACL must satisfy all of the following:

1. it is present and not null, and `SE_DACL_PROTECTED` is set;
2. it holds exactly two ACEs;
3. each ACE is of type `ACCESS_ALLOWED_ACE_TYPE` and has zero ACE flags, so it is not an
   inherited, object-inherit, container-inherit, no-propagate or inherit-only entry;
4. each access mask equals `FILE_ALL_ACCESS` (`0x1F01FF`);
5. the two trustees are exactly SYSTEM (`S-1-5-18`) and the SID in the current user's
   token, compared as binary SIDs;
6. the bounds of the ACL and of each ACE, and the lengths of the trustee SIDs, are
   checked on the DACL that the OS returns. The parser does not validate the ACL
   revision or the reserved fields. Trailing allocation space in the ACL does not add
   ACEs.

**Strictness argument.** The old check accepted only one rendering of the policy. The new
check accepts exactly the DACLs that grant the same access.

Every refusal the intended policy needs is still a refusal:
- an extra ACE fails rule 2;
- a deny entry fails rule 3, whether it is added or replaces an allow entry;
- an inherited or inheritable ACE fails rule 3;
- a DACL that is not protected fails rule 1;
- a null or absent DACL fails rule 1;
- a different trustee, a different mask, or a duplicated user ACE fails rule 4 or rule 5.

The only newly accepted inputs differ from the policy in ways that grant no access:
- the `SE_DACL_AUTO_INHERITED` and `SE_SELF_RELATIVE` control bits, which describe how the
  system stored the descriptor;
- how a SID is written in SDDL (an alias or the numeric form), because SIDs are now
  compared in binary;
- the order of the two allow ACEs, because in an allow-only DACL the order does not change
  the effective access.

Two further properties hold:
- the comparison is binary, so no rendering, localisation or alias table is involved;
- refusal messages name the property that failed, never a SID or the SDDL.

**Proof.** `tests/test_windows_runtime_guards.py` tests the policy in two ways.

On every platform it runs on binary DACLs constructed by the test.
- It accepts the `D:P` form, the `D:PAI` form and the form with the two ACEs swapped.
- It refuses each of these:
  - an extra ACE;
  - an inherited ACE;
  - an extra deny ACE;
  - a deny ACE in place of SYSTEM;
  - inheritable and inherit-only ACEs;
  - an unprotected DACL;
  - an absent or null DACL;
  - a reduced mask or a generic mask;
  - another user;
  - the user twice;
  - malformed ACLs.

On native Windows the same file also builds real descriptors through the Windows SDDL
parser. They include an extra `Everyone` ACE, an `ID` ACE, a deny ACE and an unprotected
DACL. It runs them through the production reader, `_descriptor_dacl_problem`.

On `windows-2025`, the existing tests in `tests/test_windows_storage.py` are the positive
proof. Their names are unchanged. That native proof is pending, as stated in the status
above.

## Out of scope

- A Windows-aware `trusted_host_executable`, with `PATHEXT` support and an ACL or owner
  trust check, so that changed paths could be reported on Windows. Cause B only guards
  the call.
- Any further Windows-only failure that appears once fixes A–D stop masking the storage and
  lease paths. Such a failure is recorded under §8 as not done until it is fixed.
