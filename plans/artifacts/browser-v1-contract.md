# BROWSER v1 contract: browser and UI visibility for review seats

Frozen planning artifact for `specs/phase-plans-browser-v1.md`. Sections 1–7 are
**frozen** for VISART (IF-0-VISART-1..3). Section 8 is **informative**: it records the
design the later phases start from, and each part freezes only when its phase is planned.
A change to a frozen section needs a reviewed repin of this file's sha256 in the roadmap.

## 1. Scope and owner rulings this contract implements

Rulings of 2026-11-08 (recorded in the roadmap's Owner Rulings):

- **OR-1.** The seats' browser is our own broker, outside the jail. T3's preview is never a
  seat backend, and no browser ever runs inside a seat.
- **OR-2.** The human viewer is T3 or a standard desktop or mobile Chrome. Every artifact
  here is a plain file (PNG, JPEG, WebP, WebM, MP4, YAML, JSON, script-free HTML) that T3
  shows inline by absolute path and Chrome opens directly. No viewer service is required.
- **OR-3.** Executors (non-sandboxed agents) may capture screenshot evidence with T3
  preview on the `incognito` profile only.
- **OR-4.** Seat artifacts on `ai` are viewed through the linked `ai` T3 environment;
  copying them to the viewer's host is the fallback.
- **OR-5.** No T3 delegation inside seats. T3 sandboxing is left alone.

## 2. `browser_observation.v1`

An observation is one directory. Its manifest, `observation.json`, conforms to
`plans/artifacts/browser-v1-observation.schema.json`. The runtime ships a byte-identical
copy as package data.

### 2.1 Layout

```
<observation-dir>/
  observation.json          required, the manifest, at most 256 KiB
  index.html                required, generated from the manifest (section 3)
  shots/NN[-tag...].png     1..32 screenshots (.png, .jpg or .webp)
  a11y/NN.yaml              optional, Playwright aria-snapshot YAML for capture NN
  console.json              optional, console and failed-request summary
  video/NN.webm             optional, 0..4 recordings (.webm or .mp4)
  journal.jsonl             broker only (VISBROKER); absent for executor observations
```

### 2.2 File rules

Every file the manifest names, and no other file, is present. Each one:

- has a relative POSIX path matching the schema pattern for its slot; no `..`, no
  absolute path, no empty component;
- is a regular, single-link file opened with `O_NOFOLLOW` under a directory descriptor;
  no symlink anywhere in the directory;
- matches the manifest's `sha256` and `bytes`;
- starts with the magic number of its declared `media_type` (PNG, JPEG, WebP, WebM/EBML,
  MP4 `ftyp`); YAML and JSON files are UTF-8 and JSON files parse;
- is within its cap: image 8 MiB, a11y YAML 1 MiB, `console.json` 256 KiB, video 64 MiB,
  `journal.jsonl` 4 MiB, `index.html` 256 KiB.

The whole directory is at most 128 MiB. A review takes at most 4 observations.

### 2.3 Manifest rules beyond the schema

- `captures[].index` values are unique, and each `a11y` path's `NN` equals its capture's
  `index`.
- `target.url` and `captures[].url` are `http` or `https` only. `file:`, `data:`,
  `javascript:`, `blob:` and `chrome:` are refused (`observation_target_forbidden`).
  Credentials in the URL userinfo are refused the same way.
- `producer` rules (schema-enforced): an executor observation names
  `claude_in_chrome`, `playwright_pmcp` or `t3_preview`; `t3_preview` requires
  `profile: "incognito"` (OR-3); a broker observation names `browser_broker` with
  `profile: "ephemeral"`, a non-null `egress_allowlist_sha256` and a journal.
- `host` is a short host label (the host's short name, lowercase). It never carries an
  address, a domain or an account name.
- An executor observation is a **claim by the executor**. Nothing in VISART treats it as
  an independent observation; the bundle appendix (4.4) says so.

## 3. `index.html`

Generated deterministically by the runtime from the manifest, so two writers of the same
manifest produce the same bytes. It must:

- contain no `<script>`, no `on*` attribute, no `<iframe>`, `<object>`, `<embed>`,
  `<form>`, `<base>` or `<link>` element, and no `javascript:` URL;
- carry `<meta http-equiv="Content-Security-Policy" content="default-src 'none';
  img-src 'self'; media-src 'self'; style-src 'unsafe-inline'">`;
- reference only files inside the observation directory, by relative path;
- show every capture (image, viewport, colour scheme, URL as text), link each a11y YAML,
  the console summary and each video, and show the producer, host and target as text;
- escape every manifest string as HTML text.

It opens in desktop and mobile Chrome from a local or synced copy of the directory. T3
shows the image and video files inline by absolute path.

## 4. Seat staging (review-input root)

### 4.1 Stage

The board validates each observation (section 2), then copies it, never the live
directory, to `<review_dir>/visual/<observation_id>/`, revalidates the copy, and computes:

`visual_stage_sha256 = sha256( for each staged file, sorted by logical path:
"<logical path>\t<sha256>\t<bytes>\n" )`, where the logical path is
`visual/<observation_id>/<path>`.

The digest is recorded in each seat's evidence and in the board report. If the staged
bytes differ from it at launch, the launch refuses `seat_visual_stage_changed`.

### 4.2 Delivery by route

Each local route exposes its **review-input root**, the directory that holds the bundle as
the seat sees it. The stage appears at `<review-input-root>/visual/`, read-only:

| Route | Review-input root | Delivery |
| --- | --- | --- |
| Jailed seat (`seat_jail_v1`) | `/seat/review` | Projection (4.3) |
| Sandbox-profile seat (`SeatProfile`) | The staged review directory | Read-only bind of `<review_dir>/visual` |
| Brokered parent seat | The staged review directory | Read from `<review_dir>/visual` |
| Native-fill request | `native-fill/<request_id>/` | Copy beside `artifact.md`; `request.json` unchanged |
| Remote seat route | none in v1 | Not delivered; seat evidence records `visual_delivered: false` and the seat's instructions say the files are unavailable |

### 4.3 Jail projection

- Each staged file is copied into a memfd sealed with `F_SEAL_SEAL`, `F_SEAL_SHRINK`,
  `F_SEAL_GROW` and `F_SEAL_WRITE`, and bound `--perms 0444 --ro-bind-data <fd>
  /seat/review/visual/<observation_id>/<path>`. Directories are created with
  `--perms 0555 --dir`.
- The visual arguments form one contiguous block in the owner argv, emitted after the
  bundle and instructions binds.
- The jail parses that block with its own grammar (no other flag is accepted inside it),
  requires every destination to be under `/seat/review/visual/` and to match section 2's
  path patterns, requires every descriptor to be a sealed memfd whose bytes match the
  stage, and enforces the caps.
- After those checks the block is removed before the profile comparison, as dependency
  projection mounts already are. `jail_profile_digest(leg)` is therefore unchanged for
  every leg, and `actual_profile_digest` of a jail with visuals equals that of the same jail
  without them.
- Any defect refuses `seat_sandbox_refused:identity` with detail `visual projection`.
- If this cannot hold without changing `jail_profile_digest`, the phase stops and routes a
  roadmap amendment; it never ships a changed digest without requalification.

### 4.4 Bundle appendix

When at least one observation is staged, the board appends one deterministic section to
the staged review bundle, at most 16 KiB:

```
## Visual evidence (browser_observation.v1)

Read-only files under your review-input root, at visual/. These are executor claims,
not independent observations. Stage digest: <visual_stage_sha256>.

### <observation_id> — <producer.kind>/<producer.tool>[/<profile>] on <host>
- Target: <target.url or "not recorded">
- 01 <viewport or "viewport not recorded"> <color_scheme or ""> — visual/<id>/shots/01….png (sha256 <12 hex>)
- a11y: visual/<id>/a11y/01.yaml …
- Console: <error_count> errors, <warning_count> warnings, <failed_request_count> failed requests
- Video: visual/<id>/video/01.webm …
```

Strings from the manifest appear only after section 2's validation and are rendered as
Markdown inline code where they are free text (URL, tool version). The appendix counts
toward the existing bundle transport cap.

## 5. Board CLI and report

- `phase-loop observation validate <dir>` exits 0 for a valid observation and 2 with one
  closed code per finding otherwise; JSON with `--json`.
- `phase-loop observation import --out <dir> --tool claude_in_chrome|playwright_pmcp|t3_preview
  [--profile incognito] [--url <url>] [--viewport WxH] [--color-scheme light|dark]
  [--source-commit <sha>] <image>...` builds an executor observation from screenshot files,
  such as a closeout's `visual_evidence_path`. Each image passes the existing
  `resolve_visual_evidence_artifact` checks against the repo root. It writes the manifest
  and `index.html`. `--tool t3_preview` without `--profile incognito` refuses
  `observation_profile_forbidden`. It never launches or connects to a browser.
- `phase-loop advisor-board <artifact> --observation <dir>` (repeatable, at most 4)
  validates every observation before composition. Any invalid observation exits 2 with its
  code, and no seat is launched or spent.
- The `advisor-board` result (the `--json` payload and the text summary) adds a top-level
  `visual_evidence` block with `visual_stage_sha256` and, per observation, the host label,
  the absolute paths of the source directory, the staged copy and its `index.html`, the
  manifest sha256 and the producer. Each entry in `legs` adds `visual_delivered` (true or
  false). The owner's T3 handback shows these paths; T3 renders image paths inline (OR-2).
- On `ai` the owner opens the paths through the linked `ai` T3 environment (OR-4). When the
  board's uid differs from that environment's user, or the environment is not linked, the
  documented fallback copies the observation directory to the viewer's host.

## 6. Executor capture sources

The execute skills' visual-evidence guidance names three capture sources:
claude-in-chrome, Playwright via PMCP, and T3 `preview_*` opened with
`profileId: "incognito"` only (OR-3; never the default or any named profile). After the
capture, the executor runs `phase-loop observation import` and passes `--observation` to
the board. The closeout keeps `visual_evidence_path` unchanged.

## 7. Closed refusal codes (VISART)

| Code | When |
| --- | --- |
| `observation_schema_invalid` | Manifest missing, not JSON, over cap or failing the schema |
| `observation_path_invalid` | Pattern mismatch, escape, symlink, multi-link, missing or extra file |
| `observation_media_invalid` | Empty file, wrong magic number, invalid UTF-8 or JSON |
| `observation_digest_mismatch` | File bytes differ from the manifest's sha256 or size |
| `observation_cap_exceeded` | Any per-file, per-directory or per-review cap |
| `observation_profile_forbidden` | Producer, tool and profile combination outside 2.3 |
| `observation_target_forbidden` | A URL scheme or userinfo outside 2.3 |
| `observation_index_invalid` | `index.html` differs from the deterministic rendering |
| `seat_visual_stage_changed` | Staged bytes differ from `visual_stage_sha256` at launch |

Jail projection defects use the existing `seat_sandbox_refused:identity`.

## 8. Informative: later phases (frozen at each phase's planning)

### 8.1 Observe-only broker (VISBROKER)

- **Placement.** One broker process per seat session, outside the jail, in its own bwrap,
  under `seat_resource_caps` limits. It runs `@playwright/mcp` with `--headless --isolated
  --browser chromium`, `PLAYWRIGHT_BROWSERS_PATH=/opt/consiliency/browsers` (root-owned,
  read-only, the revision pinned by the tooling release's `playwright-core`),
  `--output-dir` in broker-private storage, and `--proxy-server` pointing at a broker-side
  proxy. CDP stays on a pipe; there is no TCP listener.
- **Seat channel.** A filtering shim owns a 0600 unix socket in a 0700 directory, one per
  seat, and speaks stdio MCP to Playwright MCP. The sandbox-profile route binds it through
  `SeatProfile.broker_socket`. The `seat_jail_v1` owner argv has no socket slot, so the
  jailed route needs either a digest-bound projection like 4.3 or a requalified profile;
  VISBROKER's plan chooses, under maintainer review.
- **Allowed tools.** `browser_navigate` (URL checked against the session's origin list by
  the shim, and again by the proxy), `browser_snapshot`, `browser_take_screenshot`,
  `browser_resize`, `browser_wait_for`, `browser_console_messages`,
  `browser_network_requests`. Verbs and `aria-ref` locators stay aligned with Playwright's
  aria-snapshot engine, which T3's preview tools also use.
- **Denied.** `browser_evaluate`, `browser_run_code`, `browser_file_upload`,
  `browser_install`, tab creation, every input tool until a tier allows it, `--caps
  vision|pdf|devtools`, `--allow-unrestricted-file-access`, `--cdp-endpoint`, and any
  `file:`, `data:`, `javascript:` or `chrome:` target. Downloads are denied.
- **Egress.** A new review-target allowlist kind for the existing srt proxy machinery,
  separate from every seat's provider allowlist. Private ranges and host loopback are
  denied after DNS resolution, including NAT64, 6to4 and the host's own addresses. The
  seat's own egress digest never changes.
- **Never.** The shared PMCP gateway, any host browser that holds operator logins, T3's
  preview or `/mcp`, raw CDP, `launchServer` endpoints.
- **Output.** The broker writes a broker observation (section 2) into the seat's
  `/seat/out`, with a `journal.jsonl` line per tool call (tool name, argument digest,
  outcome code, timing; no page content).
- **Targets.** `review_target.kind: url` only. Other kinds wait for OD-1.

### 8.2 Hardening and tiers (VISHARDEN)

- Dedicated broker uid; Chromium's own sandbox enabled, with an AppArmor profile where
  unprivileged user namespaces are restricted; refuse rather than fall back to
  `--no-sandbox`.
- One browser process per seat session; contexts only among seats of one review.
- Review-profile field `browser: none|observe|replay|interactive`, default `none`, mapped
  to `browser_automation`. `replay` runs a declarative step list (navigate, click, type,
  press, select by `aria-ref` or role and name, wait, assert, screenshot) with no seat in
  the loop and no script execution. `interactive` refuses `browser_policy_tier_unavailable`
  until OD-2 is ruled.

### 8.3 Remote (VISREMOTE)

A pooled broker on `ai` with its own image digest on the allowlist, reached by each runner
reservation through a PLACECLI-style 0700/0600 per-reservation bridge, counted in PLACECLI
headroom gates, journalled through v12 JOURNAL/WORKER records. The `pi-runner` image stays
browser-free.

### 8.4 Native UI (after v1)

Electron through Playwright's `_electron` first, then headless Wayland (`cage`, or `sway`
with `WLR_BACKENDS=headless`) with `grim` screenshots and virtual input, then mobile through
`agent-device` (Callstack, MIT) on device hosts with the broker holding the session. KVM,
displays and VNC never enter a seat; VNC is only an operator watch window.
