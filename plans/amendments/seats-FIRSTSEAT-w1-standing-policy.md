# FIRSTSEAT amendment for standing Gemini W1 policy

**Owner approval recorded on 2026-11-24** for standing signed Gemini W1
admission, unattended execution, the debit and trigger rules, the accepted
lapse, and the designated owner-operated board context. This amends the
[FIRSTSEAT phase plan](../phase-plan-v1-seats-FIRSTSEAT.md).
The [implementation plan](../detailed-w1-standing-policy-20261124.md) owns the
work. The [Gemini proxy amendment](seats-FIRSTSEAT-gemini-proxy.md) still governs
the proxy fix and its live proof.

## Owner decisions

- One standing policy signed with a passphrase-protected software Ed25519 SSH
  key kept on the owner's own machine. Enroll only the public key on the primary
  board host. Each policy is valid for 90 days, with explicit quarterly renewal.
- The signed schedule counts as attendance and W1 runs unattended. The owner
  reviews the passing evidence before public export and the records PR.
- Debit one attempt for the combination of K1 release identity, Gemini
  qualification key including architecture, and admitted agy image digest.
  Skip W1 when the Gemini key and image are unchanged. Routine updates,
  reinstall and renewal cannot retry a claimed change.
- Accept that after 30 days an unchanged-input W1 can lapse to `candidate`
  without a rerun or a block on any other work. In the owner's words, “A failed
  W1 leaves the Gemini row unqualified and blocks nothing else.” Each launching
  account still needs its own current provider-free EC-EXECFIND-2 pass.
- Use dev0 under the owner account as the primary board host. For OD-12 this
  one operator context is `standard` and its passing W1 is `done-local`.
  Collaborators qualify independently under their own accounts.
- Retirement ends new claims and preserves historical verification.
  Compromise revocation immediately stops new claims on that key and rejects
  claims at or after the root-admin `revoked_after` boundary.

O-2 (2026-11-21) said “Same binding, 1 attempt (Recommended)” and “a second
needs the owner's explicit OK”. The 2026-11-24 directive was “This should be
happening automatically. Not waiting for approval. We can't keep stopping
everything each time a harness updates.” Standing Gemini W1 uses the signed
policy in place of concrete packet approval and presence, with one attempt
per eligible tuple. The bridge retains its O-2 approval.

## Frozen inputs and interface

| Artifact | SHA-256 |
| --- | --- |
| [FIRSTSEAT containment contract](../seats-firstseat-containment-contract.md) | `a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6` |
| [FIRSTSEAT interfaces](../artifacts/seats-firstseat-interfaces.md) | `b50a3a85e2f89d47b0d83f7a7cea117fc52ad04616e6616a7c4064816654ec79` |
| [K1 window-kit contract r5.2](../artifacts/seats-window-kit-k1-contract.md) | `aa30ce0a2f947fd004476ac62f1c964c57a1e6554cc273e16366c92a2088e967` |
| [IF-0-FIRSTSEAT-7 standing W1 contract](../artifacts/seats-w1-standing-policy-contract.md) | `7b27e6e65f4279c8a2518cb52d3de6ae17db1a3ad5a6ac1621adb3dddf3ef6d0` |

IF-0-FIRSTSEAT-7 gates runtime and installer implementation. Verify these four
digests and their references before either lane starts. Keep the first three
artifacts byte-identical and preserve their historical evidence bindings.

## Standing-path overrides

These overrides apply to standing Gemini W1 and its versioned evidence.

| Prior rule | Standing rule |
| --- | --- |
| IF-0-FIRSTSEAT-2 and I-15 admission and evidence | Signed attendance and a durable debit precede I-15. Use the standing evidence version with contemporaneous linkage. Keep I-15 order and containment producer interfaces. |
| K1 §8 grants and F8 | Admit a verified installed tuple under signed standing authority and claim it once. The row grant flow and bridge pins, journal and witnesses retain their existing rules. Standing builds disable legacy W1 starts. |
| K1 §9.1 ledger | Apply the standing debit and the K1 §9.2 Gemini dispatch envelope, with reservation and route expiry enforced at actual dispatch. |
| K1 §11 pins | Use the enrolled trust store's active digest for standing authority and the installed release for tuple derivation. Keep the legacy pins, frozen inputs and F10 golden. |
| K1 §7 R3 | Partition standing records by authenticated tuple and keep legacy W1 separate. Reduce the installed tuple first for unscoped matrix selection. Only a recorded unchanged-input skip can reuse independently valid W1 with proven equivalent inputs. Apply duplicate and unreadable failures within the attributed partition. Where both W1 and row qualify, latest completion wins with row winning ties. |
| K1 §7 R6–R9 | Require the current subject inputs and exception, dispatch-time route authority, versioned source and claim bindings, and the 30-day age limit. Only the Gemini row can advance. Retain K1-T2 and conservative legacy verification. |
| K1 §7 R10 | Export the reviewed, passing, closed-field standing result for Gemini only. Keep raw evidence and findings private under OD-10. |

Ordinary row grants and EC-FIRSTSEAT-7 remain binding.

## Bridge sequencing

The runtime lane may merge and dev0 may install a standing build only after the
[agent-harness#2157](https://github.com/Consiliency/agent-harness/issues/2157)
Option A bridge run completes or **2026-12-04T00:00Z** passes, whichever comes
first. The bridge uses its attended, owner-approved packet and legacy cutoff.
A later standing attempt requires the installed proxy fix and current route
authority.
