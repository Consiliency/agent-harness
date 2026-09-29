# Outside-Agent Release Handoff

This handoff records release-preparation and post-publication evidence for the
outside-agent conformance runtime. It is metadata-only: the document itself did
not publish a package, create a tag, dispatch a workflow, edit governed-pipeline,
or make production merge enforcement live.

## Package Identity

- Package: `phase-loop-runtime`
- Version: `0.7.21`
- Runtime `phase_loop_runtime.__version__`: `0.7.21`
- Version pin prepared for downstream pinning: `phase-loop-runtime==0.7.21`
- Console scripts: `phase-loop`, `codex-phase-loop`, `phase-loop-closeout-audit`, `roadmap-ownership`

## Validator Identity

- Governed-pipeline validator authority: `governed_pipeline_validator`
- Validator version: `0.7.21`
- Validator command: `phase-loop outside-agent-validate`
- Advisory preflight command: `phase-loop outside-agent-preflight`
- Advisory output remains supporting evidence only; governed-pipeline remains
  the authoritative acceptance boundary.

## Contract Pin

These values are authoritative as stated here and were verified in-repo by re-hashing
the raw contract bytes at tag `v0.2.1`. `plans/oapack/RELEASE-ANCHOR.md` in
Consiliency/spec is cited as *provenance* for which release is canonical, not as the
authority these values are read from — so this section stays correct even if that
document is momentarily inconsistent (it currently is: its repin-instruction section
still names the superseded `v0.2.0`, reported upstream on `Consiliency/spec#118`).

- `contract_package`: `consiliency-spec`
- `contract_version`: `0.2.1`
- `contract_git_tag`: `v0.2.1` (immutable release anchor). `v0.2.0` is superseded — its
  wheel-shipped router laundered validation-error values into route verdicts; do not pin
  it. The three pinned contract artifacts are byte-identical between the two tags.
- `contract_git_sha`: `b862f977897a7b87c4419680a3e83735d4ff07b0` (commit the tag derefs to)
- `schema_version`: `outside_agent_submission.v0.1`
- `verdict_schema_version`: `outside_agent_route_verdict.v0.1`
- `submission_schema_sha256`: `5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a`
- `verdict_schema_sha256`: `86169277d3a0823db1a6c9fa4d20a838b0bc2820818ad00ebd53dcdd03c2b1c2`
- `vector_manifest_name`: `test-vectors/outside-agent/manifest.json`
- `vector_manifest_hash`: `78858828e9eace93eaf31d90717666ddce54ccb3666113df9d033d67c20cfca0`
- `source_owner`: `Consiliency/spec`
- `redaction_posture`: `metadata_only`

## Release-Check Evidence

- `publication_status=prepared`
- `0.7.21` is an interim maintenance release. It does not claim `EC-RELEASE-1`,
  `EC-RELEASE-5` or `EC-RELEASE-6`: no pilot trains are claimed and the v10 RELEASE phase
  remains `committed`. It does not declare `production-ready`.
- Content above the `v0.7.20` tag commit (`7866b6e2`):
  - `gpt-6-sol` is a registered advisor-board model on the `codex` lane, answering to the
    `sol` alias, so a user or ad-hoc board can seat it explicitly; it is not a governed grok
    substitute (agent-harness#1152). This is what the fleet needs while the Grok
    subscription is out;
  - agy first-use self-qualification of genuine upstream releases, admitted as
    `locally_qualified`; release-qualified images are unchanged (agent-harness#1130,
    agent-harness#1076). The release-qualified set is still exactly 1.2.11 and 1.2.12, and
    both members were requalified live on this release tree (validated 3 and
    `route_qualified` true for each; all 218 source pins verified), with no observer or
    route change. Each series ran from its member's official release archive,
    digest-checked against the committed record (1.2.11 asset
    `c91c62c5e6fa954f5a7e1d7b9ad417d749db4aa60a4ba0b3d604dec1b645d190`, 1.2.12 asset
    `26c7c4c661d6c9beda734fcf305031056a6ea46e697c4533e8151179724e2950`));
  - the v10 roadmap's EXECFIND seat clauses scoped to the sealed route (agent-harness#1134,
    agent-harness#1132; roadmap and reseal only);
  - the per-seat jail plan (agent-harness#1133, agent-harness#1132), the BAML v1 migration
    plan (agent-harness#1136, agent-harness#1135) and two PANEL SL-1 plan amendments
    (agent-harness#1145, agent-harness#1148, agent-harness#1078); planning only;
  - the 0.7.20 published record (agent-harness#1128).
- Release tracking: agent-harness#1154; the appended plan-authority rows cite it.
- Tag: not yet created. The signed `v0.7.21` tag push, which publishes to PyPI, is
  maintainer-gated.

### Previous release: 0.7.20 (published)

- `publication_status=published`
- `0.7.20` is an interim maintenance release. It does not claim `EC-RELEASE-1`,
  `EC-RELEASE-5` or `EC-RELEASE-6`: no pilot trains are claimed and the v10 RELEASE phase
  remains `committed`. It does not declare `production-ready`.
- Content above the `v0.7.19` tag commit (`18a324a4`):
  - `fabpub-bootstrap` accepts the empty run-train writer-lock residue and excludes a live
    train (agent-harness#1116, agent-harness#1115). This is the agent-harness side of
    Consiliency/treesitter-chunker#97 on dev0;
  - the qualified agy image SET: 1.2.11 and 1.2.12 are both admitted, and any other digest
    refuses before launch (agent-harness#1119, agent-harness#1008). Both members were
    requalified live on this release tree (validated 3 and `route_qualified` true for each;
    all 215 source pins verified), with no observer or route change. The 1.2.11 series ran
    from the official 1.2.11 archive member (asset
    `c91c62c5e6fa954f5a7e1d7b9ad417d749db4aa60a4ba0b3d604dec1b645d190`, member
    `ec7cf797ecb0e1d91ddf3b6d9d6c1d616bb89f78a5b0e43536b72a7fce695f56`);
  - Claude Agent View dispatch binds, waits for and reduces the session it launched
    (agent-harness#1101, agent-harness#409, agent-harness#1099);
  - `advisor-board --advisory`, a non-gating review of a standalone document
    (agent-harness#1103, agent-harness#802);
  - several accounts on one host can run advisor boards at the same time: every seat runs
    as the operator's real uid and gid (agent-harness#1109, agent-harness#1098 item 2);
  - board legs take their outcome only from a success artifact, and `detail` only from the
    runtime's own vocabulary (agent-harness#1102, agent-harness#1096);
  - Claude answers continued past the output cap are extracted whole (agent-harness#1088,
    agent-harness#1077);
  - the v10 PANEL phase plan and its amendments, and the SL-0 tests-first corpus
    (agent-harness#1083, agent-harness#1100, agent-harness#1111, agent-harness#1092; planning
    and tests only);
  - the agy first-use self-qualification plan (agent-harness#1118, agent-harness#1076;
    planning only);
  - the 0.7.19 published record (agent-harness#1095).
- Release tracking: agent-harness#1122; the appended plan-authority rows cite it.
- Tag: signed `v0.7.20` (tag object `e57dc8bf514ce3e38ed4a22b8e9479bf51f95925`, tagger date
  2026-09-27T18:33:57Z; verified: good ED25519 signature for the maintainer's key; GitHub
  verification `valid`) → `7866b6e29fe6e819a8fcfd6f34541d755a688796` (agent-harness#1125's
  landing on `main`, whose tree is identical to the reviewed head `4f73aa81`).
- Publication: trusted-publish workflow run `36341122951` (workflow `publish-pypi`, event
  `push`, head branch `v0.7.20`, head SHA `7866b6e29fe6e819a8fcfd6f34541d755a688796`; job
  `108681285179` build + verify wheel + sdist; job `108691814711` publish to PyPI, trusted
  publishing); both succeeded. PyPI reports exactly the `SHA256SUMS` digests recorded under
  Sealed Implementation Evidence below (the run's `SHA256SUMS` artifact was downloaded and
  compared).
- Fresh installs, each into a new Python 3.10 venv:
  - The published wheel, fetched from its PyPI file URL and sha256-checked, imports `0.7.20`.
    Its `gemini_heartbeat.QUALIFIED_IMAGES` holds exactly the agy 1.2.11
    (`ec7cf797ecb0e1d91ddf3b6d9d6c1d616bb89f78a5b0e43536b72a7fce695f56`) and 1.2.12
    (`ce6fdd9e7621ee9ac6eedaa337731ca1f235e412ff57cf9eabcd2aa23b3576ca`) images, each with help
    digest `83e3a0c36269f23972ba33d0013b9a6b2933ddb07cde268fa40e0fb1a5f33755`
    (agent-harness#1119). `phase-loop --help` loads.
  - `uv pip install --no-cache --refresh --index-url https://pypi.org/simple
    phase-loop-runtime==0.7.20` resolves `0.7.20` and imports it. Its distribution metadata
    lists the same entry points as the sha256-checked published wheel's install; they are
    recorded under Package Surface Inventory below.
- GitHub release: `v0.7.20`, published 2026-09-27T19:35:22Z, not a draft and not a
  prerelease (`gh release view`): https://github.com/Consiliency/agent-harness/releases/tag/v0.7.20.
- Consumer confirmation: dev0's use of `fabpub-bootstrap` for Consiliency/treesitter-chunker#97
  is not claimed here; it had not been reported when this record was written.
- Fleet adoption: the dotfiles pin bump to `v0.7.20` is a separate client-repo change and is
  not claimed here.

### Previous release: 0.7.19 (published)

- `publication_status=published`
- `0.7.19` is an interim maintenance release. It does not claim `EC-RELEASE-1`,
  `EC-RELEASE-5` or `EC-RELEASE-6`: no pilot trains are claimed and the v10 RELEASE phase
  remains `committed`. It does not declare `production-ready`.
- Content above the `v0.7.18` tag commit (`20c602a2`):
  - the qualified agy 1.2.11 entry image (agent-harness#1074); the 1.2.10 image now refuses
    before launch. This removed the harness-side blocker for the dotfiles consumer
    (agent-harness#1008), as reported by Dev0 after publication (cited below). The route was
    requalified live on this release tree (validated 3, `route_qualified` true; all 214
    source pins verified), with no observer or route change;
  - Claude final-message extraction (agent-harness#1002, agent-harness#960) and the president
    format re-ask on a completed nonconforming turn (agent-harness#1017, agent-harness#1016);
  - the closeout audit's recognition of the skill handoff root (agent-harness#1085,
    agent-harness#1084);
  - test hardening from the 0.7.18 president rulings (agent-harness#1073);
  - the v10 roadmap PANEL phase (agent-harness#1079; roadmap only);
  - the 0.7.18 published record (agent-harness#1072).
- Release tracking: agent-harness#1087; the appended plan-authority rows cite it.
- Tag: signed `v0.7.19` (tag object `6c7e41c64081755b029118dd291f30572df9ce0c`, verified: good
  ED25519 signature; GitHub verification `valid`) → `18a324a4daf42f55160fc625ceac702a09825c11`
  (agent-harness#1089's landing on `main`). Created and pushed by the maintainer's agent on the
  maintainer's explicit instruction to push the signed tag (2026-09-26).
- Publication: trusted-publish workflow run `36219660271` (workflow `publish-pypi`, event
  `push`, head branch `v0.7.19`, head SHA `18a324a4daf42f55160fc625ceac702a09825c11`; job
  `108342384869` build + verify wheel + sdist; job `108350468813` publish to PyPI, trusted
  publishing); completed successfully. PyPI reports exactly the `SHA256SUMS` digests recorded
  under Sealed Implementation Evidence below.
- Fresh installs, each into a new Python 3.10 venv:
  - The published wheel, fetched from its PyPI file URL and sha256-checked, imports `0.7.19`.
    Its `gemini_heartbeat.QUALIFIED_IMAGE_SHA256` is
    `ec7cf797ecb0e1d91ddf3b6d9d6c1d616bb89f78a5b0e43536b72a7fce695f56` and its
    `QUALIFIED_HELP_SHA256` is `83e3a0c36269f23972ba33d0013b9a6b2933ddb07cde268fa40e0fb1a5f33755`:
    the agy 1.2.11 qualification (agent-harness#1074). `phase-loop --help` loads.
  - A first `uv pip install phase-loop-runtime==0.7.19` minutes after the publish did not
    resolve `0.7.19`. A later `uv pip install --no-cache --refresh
    --index-url https://pypi.org/simple phase-loop-runtime==0.7.19` did, and imports `0.7.19`.
    The later install's distribution metadata lists the same console scripts and plugin entry
    points as the sha256-checked published wheel's install; they are recorded under Package
    Surface Inventory below.
- GitHub release: `v0.7.19`, published 2026-09-26T06:04:24Z, not a draft and not a
  prerelease (`gh release view`): https://github.com/Consiliency/agent-harness/releases/tag/v0.7.19.
- Consumer confirmation: on 2026-09-26 Dev0 reported, for both of its users, `0.7.19`
  installed, an agy 1.2.11 entry image hashing exactly to `QUALIFIED_IMAGE_SHA256`, and the
  provider-free `gemini_heartbeat.require_capability` check passing (agent-harness#940, closed;
  agent-harness#1008). This record cites that report; it was not measured here. Keeping the
  qualified image current as agy releases (the image catalog) remains open on agent-harness#1008.
- Fleet adoption: the dotfiles pin bump to `v0.7.19` is a separate client-repo change and is
  not claimed here.

### Previous release: 0.7.18 (published)

- `publication_status=published`
- `0.7.18` is an interim maintenance release. It does not claim `EC-RELEASE-1`,
  `EC-RELEASE-5` or `EC-RELEASE-6`: no pilot trains are claimed and the v10 RELEASE phase
  remains `committed`. It does not declare `production-ready`.
- Content above the `v0.7.17` tag commit (`374efd11`):
  - the governed train review packet and `run-train --governed --review-only --preview-review`
    (agent-harness#978), and `run-train --monitoring-policy heartbeat_only` (agent-harness#1061).
    Together these are the agent-harness side of the treesitter-chunker#97 supplier review
    (agent-harness#906);
  - review sandbox isolation for owned providers where Bubblewrap drops `CAP_SETPCAP`
    (agent-harness#1052), and the requalification observer that follows it (this cut);
  - the review board's `repo_dir` authority and the structural git work-tree probes
    (agent-harness#1054, agent-harness#1055), plus the #1053 leftovers (agent-harness#1060);
  - TUI readiness and trust-modal fixes (agent-harness#1049), and test-race fixes
    (agent-harness#1045, agent-harness#1051, agent-harness#1040);
  - the EXECFIND tests-first corpus, advisory falsifier contract and promotion-guard plan
    amendment (agent-harness#1041, agent-harness#1056, agent-harness#1069; planning and tests only);
  - PRESROUTE receipt-proof maintenance (agent-harness#1035);
  - CI slimming and `make check` (agent-harness#1030, agent-harness#1031, agent-harness#1032,
    agent-harness#1037, agent-harness#1043, agent-harness#1044, agent-harness#1048,
    agent-harness#1059);
  - the 0.7.17 published record (agent-harness#1046).
- Release tracking: agent-harness#1066; the appended plan-authority rows cite it.
- Tag: signed `v0.7.18` (tag object `a8fc8cd88f138d9109850a6054ef0de8a8e44e6d`, verified: good
  ED25519 signature) → `20c602a2e6fe762c2ec14a4de3f38ac3d348fb2e` (agent-harness#1067's landing on
  `main`). Created and pushed by the maintainer's agent on the maintainer's explicit
  instruction to publish (2026-09-25).
- Publication: trusted-publish workflow run `36137860560` (job `108080177612` build + verify
  wheel + sdist; job `108095997920` publish to PyPI, trusted publishing), triggered by that tag
  push; completed successfully. PyPI reports exactly the `SHA256SUMS` digests recorded under
  Sealed Implementation Evidence below; a fresh isolated install (`uv pip install --no-cache
  phase-loop-runtime==0.7.18` from pypi.org into a new Python 3.10 venv) imports `0.7.18`, and `phase-loop run-train --help` offers `--preview-review` and
  `--monitoring-policy`. GitHub release:
  https://github.com/Consiliency/agent-harness/releases/tag/v0.7.18.
- Fleet adoption: the dotfiles pin bump to `v0.7.18` is a separate client-repo change and is
  not claimed here.

### Previous release: 0.7.17 (published)

- `publication_status=published`
- `0.7.17` is an interim maintenance release. It does not claim `EC-RELEASE-1`,
  `EC-RELEASE-5` or `EC-RELEASE-6`: no pilot trains are claimed and the v10 RELEASE phase
  remains `committed`. It does not declare `production-ready`.
- Content above the `v0.7.16` tag commit (`1390a13c`): the v10 PRESROUTE president execution
  route (agent-harness#998, with its plan agent-harness#952 and frozen corpus agent-harness#961)
  and its follow-ups — configurable president ladder (agent-harness#1004) and heartbeat/broker
  isolation for president launches (agent-harness#1009); heartbeat-only review hardening — the
  owner wrapper's own `/proc` (agent-harness#1012), the sandboxed codex seat
  (agent-harness#999), qualified Gemini heartbeat reviews (agent-harness#944) and the qualified
  `agy` 1.2.10 image (agent-harness#1024, superseding the interim 1.2.9 image of
  agent-harness#1010); Opus 5.5 replacing the Fable defaults
  (agent-harness#991, agent-harness#994); grok-4.7 and the `xhigh` effort ceiling
  (agent-harness#982, agent-harness#974); the xAI/Grok API-key scrub (agent-harness#1005); the
  settings write-lease signal guard (agent-harness#953); `validate-roadmap` phase-heading
  integrity (agent-harness#975); the reconciled LEGIBLE assumption 2 (agent-harness#981); the
  installer's single-commit pin resolution (agent-harness#1022); CI xdist adoption and offload
  lock sizing (agent-harness#956, agent-harness#946) with small fixes (agent-harness#997); the
  v10 concurrency ruling (agent-harness#949) and the 0.7.16 published record
  (agent-harness#954). The EXECFIND plan (agent-harness#964, agent-harness#1021) is planning
  only. The release-tracking issue is agent-harness#1025; the appended plan-authority rows
  cite it.
- Tag: signed `v0.7.17` (tag object `74353e228e4a8b7400d09bfee817d16ae347e7fc`, verified: good
  ED25519 signature) → `374efd1129d4b954d9d65a574f67f4202d16dc2f` (agent-harness#1026's landing on
  `main`). Created and pushed by the maintainer's agent on the maintainer's explicit
  instruction to publish (2026-09-25), not from this handoff.
- Publication: trusted-publish workflow run `36078445981` (job `107894801065` build + verify
  wheel + sdist; job `107907776228` publish to PyPI, trusted publishing), triggered by that tag
  push; completed successfully. PyPI reports exactly the `SHA256SUMS` digests recorded under
  Sealed Implementation Evidence below; a fresh isolated `pip install phase-loop-runtime==0.7.17`
  imports `0.7.17`. GitHub release:
  https://github.com/Consiliency/agent-harness/releases/tag/v0.7.17.
- Fleet adoption: the dotfiles pin bump to `v0.7.17` is a separate client-repo change and is
  not claimed here.

### Previous release: 0.7.16 (published)

- `publication_status=published`
- `0.7.16` is an interim maintenance release. It does not claim `EC-RELEASE-1`,
  `EC-RELEASE-5` or `EC-RELEASE-6`: no pilot trains are claimed and the v10 RELEASE phase
  remains `committed`. It does not declare `production-ready`.
- Content above the `v0.7.15` tag commit (`a024d987`, which is agent-harness#933's landing and
  therefore already in 0.7.15): agent-harness#937 (typed review request before the sealed paste
  for brokered Claude TUI seats), #908 (explicit heartbeat-only review monitoring with sandbox
  ownership), #936 (v10 roadmap phases 14–17), #938 (the 0.7.15 published record). Source
  issue: agent-harness#942.
- Tag: signed `v0.7.16` (tag object `275e391dd8bc64e98d45fbe160da61ccc9ad75b0`, verified) →
  `1390a13c1d203f88d0cd8af484427b5de0df729d` (agent-harness#943's landing on `main`).
- Publication: trusted-publish workflow run `35642420908` (job `106474692100` build + verify
  wheel + sdist; job `106502320354` publish to PyPI, trusted publishing), triggered by the
  maintainer's tag push; completed successfully. PyPI reports exactly the `SHA256SUMS` digests
  recorded under Sealed Implementation Evidence below; a fresh isolated
  `pip install phase-loop-runtime==0.7.16` imports `0.7.16`. GitHub release:
  https://github.com/Consiliency/agent-harness/releases/tag/v0.7.16.
- Fleet adoption: the dotfiles pin bump to `v0.7.16` is a separate client-repo change and is
  not claimed here.

### Previous release: 0.7.15 (published)

- `publication_status=published`
- `0.7.15` is an interim maintenance release. It does not claim `EC-RELEASE-1`,
  `EC-RELEASE-5` or `EC-RELEASE-6`: no pilot trains are claimed and the v10 RELEASE phase
  remains `committed`. It does not declare `production-ready`.
- Release PRs: `Consiliency/agent-harness#928` (cut, merged `a68c380d`), `#929` (onboarding,
  merged `8d87ccf1`) and `#933` (publish-workflow tag-path timeout, merged `a024d987`); each
  under the cross-vendor gate. Release head (tag target): `a024d9878739043d27d015a36a0553cba8449e5c`.
  PR-level suite on `#933`'s head: run `35565456939`, success; the main test run on the tag
  target (`35570673600`) was still in progress when this record was written.
- Signed annotated tag `v0.7.15`: tag object `59100b814e4c186f0bf573956e09721950407394`,
  target `a024d987`, GitHub verification `valid`. History: a first tag object (`177e03df`,
  unsigned, at `8d87ccf1`) was pushed on 2026-09-21 and its publish run `35563072987` was
  cancelled by the build job's then 25-minute timeout at 50% of the Gate A suite (nothing
  reached PyPI); after `#933` landed the tag was deleted and re-created, signed, at `a024d987`.
- Trusted-publish workflow `35570678898`: build/Gate A job `106241466216` (106 min, under the
  140-minute tag-path bound) and publish job `106268485619` completed successfully. The publish
  job downloaded the build artifacts, verified both entries in `SHA256SUMS`, and published without
  rebuilding.
- PyPI publication: `phase-loop-runtime==0.7.15`, wheel and sdist both present and not yanked;
  the PyPI-reported digests equal the workflow's `SHA256SUMS`. A fresh public-PyPI Python 3.10
  install resolved 0.7.15 from site-packages and `phase-loop --version` reported 0.7.15.
- GitHub Release: `https://github.com/Consiliency/agent-harness/releases/tag/v0.7.15`.
- Fleet adoption: not claimed by this record; the pinned agent-harness clone is refreshed by the
  dotfiles bootstrap separately.
- Not in this release: `Consiliency/agent-harness#908` (heartbeat-only review monitoring) and
  `#936` (roadmap phases 14–17) landed on `main` after the tag target and ship in `0.7.16`.

### Previous release: 0.7.14 (published)

- `publication_status=published`
- Release PR: `Consiliency/agent-harness#649`; reviewed head
  `8d6332d66bbf5ebe2fc1f4466acd6250008c661f`; base
  `6981ba6fe4d9a3abf0947c7791af1dbc7fad9a4a`; native GPT-5.6 Sol exact-head
  verdict: `AGREE`.
- Exact-head PR gates: publish workflow `32776585825`, build/Gate A job
  `97588926177`, offloaded suite job `97588950399`, and aggregate suite-gate job
  `97606897017`; all completed successfully.
- Merge commit: `0c4d3a89054efa80a1f7663bd65e70d0f547c76e`.
- Signed annotated tag: `v0.7.14`; tag object
  `2de6c06973b84890b62184fa023d387f6044a43c`; GitHub verification: `valid`.
- Trusted-publish workflow `32783112944`: build/Gate A job `97609245453` and
  publish job `97625905153` completed successfully. The publish job downloaded
  the build artifacts, verified both entries in `SHA256SUMS`, and published
  without rebuilding.
- PyPI publication: `phase-loop-runtime==0.7.14`, wheel and sdist both present
  and not yanked. A fresh public-PyPI Python 3.10 install resolved 0.7.14 from
  site-packages and `phase-loop --version` reported 0.7.14.
- GitHub Release: `https://github.com/Consiliency/agent-harness/releases/tag/v0.7.14`.
- Fleet adoption: the supported installer refreshed Claude, Codex, Gemini, and
  OpenCode skill roots from `v0.7.14`. All eight installed advisor-board/panel
  skill bodies contain `claude-fable-5`, `gpt-5.6-sol`, `grok-4.6`, and
  `gemini-3.7-flash`, and contain none of `Harness Fable`, `Harness 3.7 Flash`,
  or `<harness>-3.7-flash`.
- Installed behavior: president order is Fable, Sol, Grok 4.6, then Gemini 3.7
  Flash. A blocking Fable ruling did not fall back; typed
  `president_unavailable` traversed all four rungs; untyped unavailability failed
  at Fable. General executor defaults were not changed by the release PR.

## Sealed Implementation Evidence

### This release: 0.7.21 (prepared)

The digests below are from the pre-tag local build of the release candidate, produced by
`uv build` under `umask 022` (archive member modes are umask-dependent,
`Consiliency/agent-harness#519`) from an export of the release commit's tree. They are a
preparation measurement, not a publication record: the publishing workflow rebuilds from the
tagged commit and verifies `SHA256SUMS`, and the published digests are recorded here after the
tag push. As for `0.7.15`–`0.7.20`, the published digests are expected to differ, because
archive bytes are timestamp/toolchain-dependent.

- prepared direct-wheel sha256: `5541f167d1b00b669d2943d04b74f76c25eb4b51a67defdb4eddcc96f25c80be`
- prepared direct-sdist sha256: `e84b9589ba825f043dca1b6be94e012d62d61d338eaa172deab5d4d2c117c3c6`
- sdist-derived-wheel sha256: not claimed, for the reason recorded for `0.7.14` below.

### Previous release: 0.7.20 (published)

The published digests are the `SHA256SUMS` tuples recorded by trusted-publish workflow
`36341122951` from its build of the tagged commit `7866b6e2`, verified by the publish job
without rebuilding, and equal to the digests PyPI reports.

The pre-tag local build of the candidate (`uv build` under `umask 022`,
`Consiliency/agent-harness#519`, from an export of the reviewed head `4f73aa81`, whose tree is
the tagged commit's) remains a preparation measurement:

- prepared direct-wheel sha256: `a66cb501c7f4f9a4eae3537dde0930eeef15baba6ef650d4727c51e8bb919f1d`
- prepared direct-sdist sha256: `e2964bfe3c8d1a4d15879c57751433e2fc92b6ffbe1a9a3af4e1711c16aebf56`

The published tuples differ from the prepared ones. Content equivalence was MEASURED, not
inferred from counts. The prepared archives were retained, and the tagged commit `7866b6e2` was
also rebuilt locally the same way (wheel
`b2237216b5110a9798d80047c90d0dbda2ce62b8d1370305a38a7d94ba8d8e97`, sdist
`a2a7192dc807ab7a0353a42239b11dac9c6eec4d7a55f242826b0e7ddb2ff1c7`; also different from the
published digests). Both the prepared and the rebuilt archives were compared with the
published archives by per-member sha256 over the union of member paths. In each comparison
all 472 wheel files and all 975 sdist regular files match, with none added or missing. The
digest differences are therefore not in file contents; which archive-level bytes differ
(timestamps, ordering or compression) was not measured.

- direct-wheel sha256: `b547ae2a60133c928a1089e1d0935c547b8c04f1f6c0e76cffce888e88fa0bee`
- direct-sdist sha256: `e1848e6c055190cf3858f175a640cc43b082efad46d0db817d4fd399d9b1545b`
- sdist-derived-wheel sha256: not claimed, for the reason recorded for `0.7.14` below.

### Previous release: 0.7.19 (published)

The published digests are the `SHA256SUMS` tuples recorded by trusted-publish workflow
`36219660271` from its build of the tagged commit `18a324a4`, verified by the publish job
without rebuilding, and equal to the digests PyPI reports. The pre-tag local build of the
candidate (`uv build` under `umask 022`, `Consiliency/agent-harness#519`) measured wheel
`c4b99457bd1973b917b3ec9be45ec1fa05304b6c9ac9d1b49509ca4870621ce7` and sdist
`4553444e025e92d5ca0640064c1df78334a9984969c233a8c65a977a2f4db0bc`. The published tuples differ.
The prepared archives were not retained, so their members were not compared. To test whether a
digest difference implies a content difference, the tagged commit `18a324a4` was rebuilt locally
(`uv build` under `umask 022`). The rebuild's digests also differ from the published ones: wheel
`bb3e6121d954382e10ab4ba0d8876041b87f44ac1581daee8d4900188f2db5d9`, sdist `cbde38b05e12c3b1d5a23dc48067c28ec16778e357e706c3ac444cb41623dc7f`. Yet every regular-file member's content is byte-identical to the published
archives: per-member sha256, compared over the union of member paths, so all 471 wheel files
and all 965 sdist regular files match, with none added or missing. The rebuild's digest
difference is therefore not in file contents; which archive-level bytes differ was not
measured.

- direct-wheel sha256: `291d7d95fd9c02f73253675d6baaf4739ea29bfb81d6312d5c5db6812f1e643a`
- direct-sdist sha256: `a42184a7df40c79b53775c32ff688e794a20786303cf23027106adfa9ed99a3a`
- sdist-derived-wheel sha256: not claimed, for the reason recorded for `0.7.14` below.

### Previous release: 0.7.18 (published)

The published digests are the `SHA256SUMS` tuples recorded by trusted-publish workflow
`36137860560` from its build of the tagged commit `20c602a2`, verified by the publish job
without rebuilding, and equal to the digests PyPI reports. The pre-tag local build of the
candidate (`uv build` under `umask 022`, `Consiliency/agent-harness#519`) measured wheel
`504298b115a1553132fc9b7ceca73b9da400d94a9011a1c4f12e546841586972` and sdist
`6f2888d794b6d4e1698ec823ff5706f40987e310c89f624846118d1383ec9564`; the published tuples differ
because archive bytes are timestamp/toolchain-dependent — a preparation measurement, not a
content discrepancy in the runtime (the package surface inventory below was re-measured on
the published artifacts and is identical to the prepared measurement).

- direct-wheel sha256: `d73c5e31ad38152f97de5a24bf334cac4c93efb391bdbc1d13b884f76dc0bdf0`
- direct-sdist sha256: `c950fd1ef00ff96bee663429e13ee6ea3bf2f0c1d55d76b9fd6477852a16d8da`
- sdist-derived-wheel sha256: not claimed, for the reason recorded for `0.7.14` below.

### Previous release: 0.7.17 (published)

The published digests are the `SHA256SUMS` tuples recorded by trusted-publish workflow
`36078445981` from its build of the tagged commit `374efd11`, verified by the publish job
without rebuilding, and equal to the digests PyPI reports. The pre-tag local build of the
candidate at `3bdd5ef7` (`uv build` under `umask 022`, `Consiliency/agent-harness#519`)
measured wheel `04a7b8fe5d7b6ece03a327a2c0612c305e6338ce798c61a0076e7b6c193a3d72` and sdist
`08125bfab4288117a3c31efc5d32b3a2e60d03b86f84e71fe72179c6985fb105`; the published tuples differ
because archive bytes are timestamp/toolchain-dependent — a preparation measurement, not a
content discrepancy in the runtime (the package surface inventory below was re-measured on
the published artifacts and is identical to the prepared measurement).

- direct-wheel sha256: `462cefa01121a485f072ce0ce107fd003e28ee99848b490d23f5ea9c9d1f0b79`
- direct-sdist sha256: `98a1b7838f3db15b9172ff7a72c8281e4b6678bdfc135c2bd09c8148339bdbb9`
- sdist-derived-wheel sha256: not claimed, for the reason recorded for `0.7.14` below.

### Previous release: 0.7.16 (published)

The published digests are the `SHA256SUMS` tuples recorded by trusted-publish workflow
`35642420908` from its build of the tagged commit `1390a13c`, verified by the publish job
without rebuilding, and equal to the digests PyPI reports. The pre-tag local build of the
candidate at `a5d03e22` (`python -m build` under `umask 022`, `Consiliency/agent-harness#519`)
measured wheel `8ad6fb71a1c29afa6553d94028bb8d325bcf6d837c6130607f88c2d10ff6568f` and sdist
`fe727482cbf5a5544cf2a4545533b5af3c898d4555b8cd85dcc7673a22d96f19`; the published tuples differ
because archive bytes are timestamp/toolchain-dependent — a preparation measurement, not a
content discrepancy in the runtime (the package surface inventory below was re-measured on
the published artifacts and is identical to the prepared measurement).

- direct-wheel sha256: `617821374c2029a819b2d2799f6e01c77bd0eeafeaa625a5953499dc8fd2f853`
- direct-sdist sha256: `8ee174376e4d60833cb75f2fb39a085c3d34b489245c4193b499d3879f621bd3`
- sdist-derived-wheel sha256: not claimed, for the reason recorded for `0.7.14` below.

### Previous release: 0.7.15 (published)

The published digests are the `SHA256SUMS` tuples recorded by trusted-publish workflow
`35570678898` from its build of the tagged commit `a024d987`, verified by the publish job
without rebuilding, and equal to the digests PyPI reports. The pre-tag local build of the
candidate at `8d87ccf1` (`python -m build` under `umask 022`, `Consiliency/agent-harness#519`)
measured wheel `09d7e9420f6b747b70120b9fa2cb34c872dfa4e8b15351e65b7cd8a6493bddef` and sdist
`80913168481ad8e19b452c8ae681451be29a49d6ea8c9bfb445c0e064d1bd538`; the published tuples differ
because archive bytes are timestamp/toolchain-dependent (the sdist carries no repository-root
CHANGELOG, docs or workflow files, so `#933` contributes no packaged content) — a preparation
measurement, not a content discrepancy in the runtime.

- direct-wheel sha256: `b4b95fd1453425403d1cd94c02640fe8ec39cb543d7507e127e09862bcbf82ef`
- direct-sdist sha256: `1c5cbe0f96f40ba402674bba8e851c07f8babd8a9c83269b10e6e6669d1906e5`
- sdist-derived-wheel sha256: not claimed, for the reason recorded for `0.7.14` below.

### Previous release: 0.7.14

This release handoff covers phase-loop-runtime 0.7.14 with a digest-enumerated
contract mirror. Publication, tag creation, workflow dispatch, and downstream
adoption remained maintainer-owned and were not published or not dispatched by
this metadata document.

- candidate implementation commit: `8d6332d66bbf5ebe2fc1f4466acd6250008c661f`
- candidate implementation tree: `80ad6aaf8925977d3202d1e841963be24aa9e3b9`
- release merge commit: `0c4d3a89054efa80a1f7663bd65e70d0f547c76e`
- release merge tree: `80ad6aaf8925977d3202d1e841963be24aa9e3b9`
- pre-publication package evidence: exact-head workflow `32776585825`, job
  `97588926177`, success

### Package Archive Digests

- direct-wheel sha256: `08ec0e61c91b95ccd822a6c6dafc47f607455c594ea1d8a253c7c0b1f7ab4fa7`
- direct-sdist sha256: `d6731f120f694c8046eb5a1d77ad49d68e356edad672c41790ef4c72b5583c37`
- sdist-derived-wheel sha256: not claimed. A raw wheel rebuilt from the published
  sdist is timestamp/toolchain-dependent, and the release workflow did not retain
  a normalized derived-wheel artifact. Release identity is bound only to the
  direct wheel and sdist verified by `SHA256SUMS` and published without rebuilding.

## Package Surface Inventory

Measured on the prepared `0.7.21` build described above.

- Wheel artifact: `phase_loop_runtime-0.7.21-py3-none-any.whl`
- Sdist artifact: `phase_loop_runtime-0.7.21.tar.gz`
- Wheel top-level entries: `phase_loop_runtime`, `phase_loop_runtime-0.7.21.data`, `phase_loop_runtime-0.7.21.dist-info`
- Wheel file count: `475`
- Sdist top-level entries: `MANIFEST.in`, `PKG-INFO`, `README.md`, `protocol`, `pyproject.toml`, `setup.cfg`, `src`, `tests`
- Sdist file count: `979` regular files (`1114` archive members including directories)
- Wheel console entry points: `phase-loop = phase_loop_runtime.cli:main`; `codex-phase-loop = phase_loop_runtime.cli:main`; `phase-loop-closeout-audit = phase_loop_runtime.closeout_classifier:console_main`; `roadmap-ownership = phase_loop_runtime.roadmap_ownership:console_main` (plus the `phase_loop_runtime.profile_commands` and `phase_loop_runtime.skill_sources` plugin groups)
- Runtime plugin entry points: `dotfiles = phase_loop_runtime.dotfiles_profile_plugin:register_profile_commands`; `dotfiles = phase_loop_runtime.skill_sources_plugin:register_skill_sources`

## Governed-Pipeline Pinning

`0.7.20` is published (PyPI, trusted-publish workflow `36341122951`), so governed-pipeline
may consume it as an authoritative validator by pinning `phase-loop-runtime==0.7.20`. Once
`0.7.21` is published (tag push → PyPI; this document records it as `prepared` until then),
the pin may move to `phase-loop-runtime==0.7.21`. In either case, call:

```bash
phase-loop outside-agent-validate path/to/outside-agent-submission.json \
  --output outside-agent-verdict.json \
  --submitted-ref src/agent.py \
  --submitted-ref docs/evidence.md
```

The governed-pipeline side should also pin the Consiliency/spec contract fields
listed above, including `contract_version`, `contract_git_tag`,
`contract_git_sha`, `schema_version`, `verdict_schema_version`,
`submission_schema_sha256`, `verdict_schema_sha256`, and `vector_manifest_hash`.
The per-source `sha256` digests are verified over the raw contract bytes, so a
byte change that preserves the manifest hash no longer slips past this pin.

## Outside-Agent Advisory Preflight

Outside-agent producers can run local advisory preflight before submitting work:

```bash
phase-loop outside-agent-preflight path/to/outside-agent-submission.json \
  --output outside-agent-advisory.json
```

The advisory result can catch metadata-only schema, redaction, provenance, and
digest issues early. It is not acceptance authority and must not be treated as a
merge verdict.

## Release Step — bump `RELEASE_PIN` in lockstep (PUSHFLOW)

- When cutting a release, bump the checked-in `RELEASE_PIN` to the new
  `vX.Y.Z` **in the same release commit** as the `phase-loop-runtime` package
  version (they are kept equal by the release-consistency guard in
  `tests/test_release_pin_autotrack.py`).
- `install-agent-harness.sh` pins the persistent clone at
  `~/.local/share/agent-harness` (or `$AGENT_HARNESS_HOME`) to `RELEASE_PIN`. If
  `RELEASE_PIN` is not bumped, previously installed clones stay behind (the live
  gap where clones sat at `0.6.0` under `RELEASE_PIN=v0.7.0`).
- `phase-loop doctor` surfaces a `stale` BOM verdict for
  `pinned agent clone (~/.local/share/agent-harness)` when a local clone is behind
  `RELEASE_PIN`. The remediation is to re-run `install-agent-harness.sh` (which
  runs `git -C ~/.local/share/agent-harness fetch + checkout $REF`). The check is
  advisory (WARN, never gating).

## Maintainer Dispatch Boundary

- For `0.7.20`: the package was not published from this handoff; trusted workflow
  `36341122951` published it from the signed `v0.7.20` tag (verified tag object
  `e57dc8bf514ce3e38ed4a22b8e9479bf51f95925`, signed with the maintainer's key).
- For `0.7.19`: the package was not published from this handoff; trusted workflow
  `36219660271` published it from the signed `v0.7.19` tag (verified tag object
  `6c7e41c64081755b029118dd291f30572df9ce0c`), pushed on the maintainer's explicit
  instruction.
- For `0.7.18`: the package was not published from this handoff; trusted workflow
  `36137860560` published it from the signed `v0.7.18` tag (verified tag object
  `a8fc8cd88f138d9109850a6054ef0de8a8e44e6d`), pushed on the maintainer's explicit
  instruction.
- For `0.7.17`: the package was not published from this handoff; trusted workflow
  `36078445981` published it from the signed `v0.7.17` tag (verified tag object
  `74353e228e4a8b7400d09bfee817d16ae347e7fc`), pushed on the maintainer's explicit
  instruction. The tag push remains the only trigger (`EC-RELEASE-4`).
- For `0.7.16`: the package was not published from this handoff; trusted workflow
  `35642420908` published it from the signed `v0.7.16` tag (verified tag object
  `275e391dd8bc64e98d45fbe160da61ccc9ad75b0`).
- For `0.7.15`: the package was not published from this handoff; trusted workflow
  `35570678898` published it from the signed `v0.7.15` tag (verified tag object
  `59100b814e4c186f0bf573956e09721950407394`).
- For `0.7.14`: the package was not published from this handoff; trusted workflow
  `32783112944` published it from the signed `v0.7.14` tag (verified tag object
  `2de6c06973b84890b62184fa023d387f6044a43c`).
- For `0.7.20`, `0.7.19`, `0.7.18`, `0.7.17`, `0.7.16`, `0.7.15` and `0.7.14` a maintainer-authorised tag push triggered the
  workflow and it completed successfully; none was
  dispatched from a handoff.
- Production governed-pipeline enforcement is not claimed by this handoff.
- Maintainers retain ownership of future publishing, tagging, workflow dispatch,
  and downstream production pin rollout.
