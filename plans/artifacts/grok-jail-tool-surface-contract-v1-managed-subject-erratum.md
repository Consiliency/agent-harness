# Grok jail contract managed-subject erratum

Owner decision, 2026-11-24. “Use pinned fingerprint.”

This erratum applies to the frozen jail contract
`plans/artifacts/grok-jail-tool-surface-contract-v1.md` at sha256
`f2fc6c88471dd88f52168136cec0f770fa7c286cd1ce71a1fd8b341878ea8b66` and jail contract revision r8,
`plans/artifacts/grok-jail-tool-surface-contract-v1-erratum-r8.md` at sha256
`6fbad698480d1ba3391888bd2a31350a954051c684b5489047f488a7c8468490` (agent-harness#2176).
The active GROK phase plan and the GROK manifest's `frozen_inputs` record this erratum's raw SHA-256.

This erratum governs managed binary identity in §2.1 and §4.4 and supplies the replacement
§7 Image bullet. R8 governs conditions 3 and 4, measurement admission, accounting, and
resumption. The other §7 terms apply cumulatively with r8, including the grant blockers
in r8-4 and r8-5.

## §2.1 Managed binary identity

The `managed_image` source in agent-harness#2178 is Grok-only. The guarded Dotfiles
frontdoor must resolve to the exact `<managed root>/<release ID>/native/grok` path. A
direct or malformed managed hit refuses. Existing lease selection takes precedence
and a Grok dependency lease refuses.

Read the Dotfiles pin at `/etc/consiliency/tooling/grok-subject-pin.json` as bounded,
stable RFC 8785 JSON with unique keys. The pin has exactly `schema`
(`grok_subject_pin.v1`) and `releases`. Each release ID matches
`[A-Za-z0-9][A-Za-z0-9._-]{0,254}`. Each entry has exactly `binary_sha256`,
`platform`, and `version`. Require a lowercase 64-digit hexadecimal digest in
`seat_profile_grok.JAIL_PROTECTION` for **every** entry, including unselected entries,
with platform `linux-x64` and version `1.0.92`. The host must be Linux x86-64.

Require the entry for the frontdoor's exact release ID. Walk the pin path and the
native image path from `/` without following symlinks. Every component must be UID-0
owned and free of group or other write permission. Hash the regular native executable
through its opened descriptor and check stability across the read. The observed
SHA-256 must equal the exact-release pin. Another release's entry conveys no authority
for this release, even when the bytes match.

Carry the verified canonical path, release ID, and digest on the subject. Admission
requires the registered Grok profile with `projection="none"` and a null dependency
requirement. The jail binds that path read-only at `/seat/bin/grok`. The path bind
relies on trusted root to preserve the verified file between the descriptor check and
the bind.

## §4.4 Final verification of managed identity

Resolve and verify the managed path, release pin, and fingerprint before composing
the jail. In both board and measurement modes, the final verifier repeats the root
walk, exact-release pin check, and descriptor hash for the actual bind source.
Require the digest to match the board record or the measurement reservation's grant
image. A missing, unsafe, or changed path or pin, or a digest mismatch, refuses. The other
§4.4 checks and the r8 admission and settlement rules continue to apply.

## §7 Replacement Image bullet

- **Image.** Use Grok 1.0.92 with SHA-256
  `add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb`, the image
  pinned by TS erratum 8 and keyed in `JAIL_PROTECTION`. Install it root-owned as
  `grok` on the seat host under the exact Dotfiles release pin (`grok_subject_pin.v1`)
  defined above. Require the one-time npm-signature provenance receipt below,
  including independent review of its derivation, before the grant.

OD-3 and GROKROLL SL-1 and SL-2 are separate from this grant. Runtime image admission
uses the release pin and fingerprint checks and requires no receipt, release catalog,
catalog gate, or registry access. Any successor image requires a jail erratum and a
`JAIL_PROTECTION` entry.

## One-time npm provenance

`plans/evidence/seat-grok/image-provenance-1.0.92.json` at sha256
`398f019cc3709a745bb6d8173e0b7d78ae0441f999ac19bb513f22e779f43c36`
is the RFC 8785 receipt for the public npm package `@xai-official/grok-linux-x64@1.0.92`.
It has exactly `schema` (`grok_image_provenance.v1`), `package`, `version`,
`tarball_integrity`, `registry_keyid`, `registry_signature`, `member`
(`package/bin/grok.br`), `binary_bytes` (a positive integer), and `binary_sha256`.

The derivation used the exact-version metadata and tarball from the public npm
registry. Both published signatures verified using `grok_roll/catalog.py`'s
`verify_entry_signature` and its existing ECDSA P-256 key. The receipt retains the
first verified signature in the metadata. The signature covers the UTF-8 bytes of
`<package>@<version>:<tarball_integrity>`. The fetched tarball's SHA-512 matched
that integrity. Reading its regular `package/bin/grok.br` member and streaming it
through Brotli produced 208487936 bytes with the contract's SHA-256. The executable
was never run. A missing or failing receipt or an outstanding independent review
blocks the §7 grant.
