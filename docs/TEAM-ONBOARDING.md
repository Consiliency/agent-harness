# Agent Harness — Team Onboarding

The **agent-harness** gives you our phase-loop workflow skills (roadmap → plan → execute,
plus one-off detailed planning and a skill editor) on your own machine. It's public and
standalone — **no VPN/tailnet, no 1Password, no shared pipeline, nothing from anyone's fleet.**

## Install (pick your harness)

Cross-platform (macOS / Linux). Replace `claude` with `codex`, `gemini`, or `opencode`:

```sh
# clone-then-run (you can read the script first):
git clone https://github.com/Consiliency/agent-harness
agent-harness/install-agent-harness.sh --harness all   # all four harnesses (or claude|codex|gemini|opencode)

# …or the one-liner:
curl -fsSL https://raw.githubusercontent.com/Consiliency/agent-harness/main/install-agent-harness.sh | bash -s -- --harness claude
```

Pin a specific release for the whole team with `--ref vX.Y.Z` — take the version from the
[releases page](https://github.com/Consiliency/agent-harness/releases/latest). Omit `--ref`
and the installer resolves the current release itself.

**Prereqs:** git, and your harness CLI already installed (Claude Code / Codex / Gemini /
OpenCode). The installer brings everything else (it installs `uv` if you don't have it).

## Verify the install (agents: parse this)

The harness is usually installed **by an agent**, so the success signal is a machine-readable
payload, not the installer's console output:

```sh
phase-loop doctor --json
```

It emits the versioned `phase-loop-doctor.v1` schema:

```json
{"schema": "phase-loop-doctor.v1",
 "summary": "18/18 tools present; BOM 3 current / 1 stale / 2 unknown (0 gating-stale)",
 "tools": [{"name": "git", "present": true, "authed": null, "unlocks": "version control"}]}
```

**What to assert, and what not to.**

- `schema == "phase-loop-doctor.v1"` — the install is present and the CLI runs. This is the
  success signal; assert it rather than grepping the installer's output.
- Exit `0` from a plain `doctor --json` means the report was produced. It is **not** a claim
  that every tool is present — read `tools[]` for that.
- `--fail-on-stale` exits non-zero **only** on a `stale` verdict among the *gating*
  (repo-owned) targets.
- **Do not treat `unknown` as failure.** The BOM degrades every unreachable registry to
  `unknown` by design, so an offline or network-restricted host reports `unknown` and still
  exits `0`. Failing on `unknown` will make your installer red on a healthy machine.

A missing `phase-loop` on `PATH` is the one failure that surfaces before any of this — see
Troubleshooting below.

## What next

`phase-loop run` needs a roadmap to run; in a fresh repo with none, it exits with an error
rather than doing nothing. Author one first — either by hand at `specs/phase-plans-v1.md`, or
by invoking the roadmap skill in your harness (`/claude-phase-roadmap-builder`, or the
`codex-` / `gemini-` / `opencode-` prefixed equivalent). Then plan and execute a phase as
shown under **Use it** below.

## What you get

- The `phase-loop` runtime CLI (and `codex-phase-loop`).
- These workflow skills installed into your harness's skill root
  (`~/.claude/skills`, `~/.codex/skills`, `~/.gemini/skills`, or
  `~/.config/opencode/skills`):
  - **phase-roadmap-builder** — turn a plan/conversation into a phased roadmap
  - **plan-phase** — architect one phase into parallel swim-lanes
  - **execute-phase** — run a phase's lanes to completion
  - **plan-detailed** — a single bounded change, no roadmap overhead
  - **phase-loop** — drive the loop end-to-end
  - **skill-editor** / **skill-improvement-planner** — author/refine skills

## Use it (standalone — no pipeline required)

In your harness, invoke the skills like any other slash-command/skill, e.g. in Claude Code:

```
/claude-phase-roadmap-builder   # → produces specs/phase-plans-v1.md
/claude-plan-phase P1           # → plans/phase-plan-v1-P1.md
/claude-execute-phase P1        # → runs the lanes
```

(Codex/Gemini/OpenCode use the same skills with their own prefixes.) For a small one-off
change, skip the roadmap and use `…-plan-detailed`. The runtime is harness-neutral and makes
no external calls — it just orchestrates phases on whatever harness you chose. Governed-pipeline
integration exists but is entirely optional; you don't need it.

## Update / pin / uninstall

- **Update:** re-run the installer (it fetches the pinned ref and re-applies).
- **Pin a version:** `--ref vX.Y.Z` (everyone on the same release).
- **Uninstall:** `uv tool uninstall phase-loop-runtime` and remove the
  `*-phase-*` skill symlinks from your skill root.

## Troubleshooting

- **`phase-loop: command not found`** — make sure `~/.local/bin` is on your `PATH`
  (the installer puts the CLI there); open a new shell or `hash -r`.
- **Already have a `phase-loop` on PATH?** Check which one wins with
  `command -v phase-loop` and `phase-loop --version`.

Repo + issues: <https://github.com/Consiliency/agent-harness> · Apache-2.0.
