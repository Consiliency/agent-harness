# JEVHOST amendment S5-W1: the native-Windows runtime fixes beyond a platform guard

Status: **Proposal for review.** It records the follow-up to agent-harness#2092 (after the
import fix, agent-harness#2123). It does not edit the frozen contract
`plans/artifacts/jevhost-v1-contract.md` (sha256
`1fa957afc8f7b3a324a8f048695b3d2ebf1009336a1d49407d33dfc1b36f4e1d` at this amendment's base).
JEV Drill drafted the files it touches, so JEV Drill's agreement is requested. Until it
is accepted, these changes are disclosed under JEVHOST S5 "Otherwise" and §8 as
not-yet-agreed edits to verbatim files.

## Why an amendment

JEVHOST §2 classes `src/phase_loop_runtime/windows_storage.py`,
`tests/test_jevdrill_input.py` and `tests/test_jevdrill_usage.py` as "New, verbatim". S5
allows a fix there only when it is a platform guard with no change on POSIX. The first
`windows-2025` run of the companion workflow failed on four causes. One fix (A) is more
than a platform guard, and two (C, D) edit verbatim test files. The diagnosis is the
coordinator's review record for agent-harness#2092. Its cause letters are used here.

## Changes recorded

| # | File | Change | Kind |
| --- | --- | --- | --- |
| A | `windows_storage.py` `PrivateSecurity.verify` | The exact-SDDL string comparison becomes a structural DACL check (below). The creation descriptor is unchanged. | Beyond a platform guard. The module refuses to load off native Windows, so POSIX is unaffected. |
| B | `launcher.py` `_worktree_change_snapshot` | Returns `None` on native Windows before `host_git`, whose trusted-helper resolution is POSIX-only. Changed paths stay unknown there. | Platform guard. `launcher.py` is a §2 "Modified, conflicting" file, not the S5 owned file, so it is recorded here. |
| C | `tests/test_jevdrill_input.py` `input_spec` | Prefixes `sys.executable` on Windows, as `synthetic_spec` in `test_jevdrill_usage.py` already does. | Test portability, POSIX command unchanged. |
| D | `tests/test_jevdrill_usage.py` `test_permanent_invalidation` | The 1 MiB parameter gets `id="oversized_line"`. Its auto-generated id overflowed the Windows 32767-character environment limit for `PYTEST_CURRENT_TEST`, and printing it stalled the run. | Test id only. [C7] compares names without parametrize ids (`tests/data/jevdrill_test_names.json`), so name stability is unaffected. |

The workflow change (a 20-minute step timeout on both "Run the twelve files" steps, so
the `always()` junit upload survives a hang) is within §8's workflow shape and needs no
amendment. It is listed here for completeness.

## A: the structural check and why it is at least as strict

**Before.** `verify` rendered the object's DACL as SDDL and required it to equal
`D:P(A;;FA;;;SY)(A;;FA;;;<user SID string>)` byte for byte. On `windows-2025` it refused
directories this same code had just created with that descriptor. NTFS stores a
protected DACL created under an auto-inherited parent with `SE_DACL_AUTO_INHERITED` set
as well, which renders `D:PAI(…)`. The SDDL converter may also render the user as an
alias, for example `LA`, where the expected string has the numeric SID.

**After.** The owner check is unchanged. The DACL must satisfy all of the following:

1. it is present and not null, and `SE_DACL_PROTECTED` is set;
2. it holds exactly two ACEs;
3. each ACE is `ACCESS_ALLOWED_ACE_TYPE` with ACE flags zero, so no inherited,
   object-inherit, container-inherit, no-propagate or inherit-only entry;
4. each mask equals `FILE_ALL_ACCESS` (`0x1F01FF`);
5. the two trustees, compared as binary SIDs, are exactly SYSTEM (`S-1-5-18`) and the
   current user's token SID;
6. the ACL and every ACE are well formed (sizes and SID lengths agree).

**Strictness argument.** The old check accepted one rendering of the policy. The new one
accepts exactly the DACLs that grant the same access:

- Every refusal the intended policy needs is still a refusal. An extra ACE fails (2). A
  deny entry fails (3), whether added or in place of an allow. An inherited or inheritable
  ACE fails (3). A DACL that is not protected fails (1). A null or absent DACL fails (1). A
  different trustee, a different mask, or a duplicated user ACE fails (4) or (5).
- The only inputs newly accepted differ from the policy in ways that grant no access:
  - the `SE_DACL_AUTO_INHERITED` and `SE_SELF_RELATIVE` control bits, which describe how
    the system stored the descriptor;
  - the SDDL spelling of a SID (alias or numeric), since SIDs are now compared in binary;
  - the order of the two allow ACEs. In an allow-only DACL, order does not change the
    effective access.
- The comparison is in binary, so no rendering, localisation or alias table is involved.
- Refusal messages name the failing property, never a SID or the SDDL.

**Proof.** `tests/test_windows_runtime_guards.py` checks the policy on constructed binary
DACLs on every platform. It accepts the `D:P`, `D:PAI` and swapped-order forms. It refuses
an extra ACE, an inherited ACE, an extra deny ACE, a deny ACE in place of SYSTEM,
inheritable and inherit-only ACEs, an unprotected DACL, an absent or null DACL, a reduced
or generic mask, another user, the user twice, and malformed ACLs. On native Windows the
same file builds real descriptors through the Windows SDDL parser, including an extra
`Everyone` ACE, an `ID` ACE, a deny ACE and an unprotected DACL. It runs them through the
production reader `_descriptor_dacl_problem`. The existing `tests/test_windows_storage.py`
tests are the positive proof on `windows-2025`, and their names are unchanged.

## Out of scope

- A Windows-aware `trusted_host_executable` (with `PATHEXT` and an ACL or owner trust
  check) that would let changed paths be reported on Windows. Cause B only guards it.
- Any further Windows-only failure that appears once A–D stop masking the storage and
  lease paths. Such a failure is recorded under §8 as not done until fixed.
