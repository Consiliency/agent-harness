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

**Prereqs:** git, `curl` (the installer uses it to resolve the release pin, and the one-liner
form is delivered by it), and your harness CLI already installed (Claude Code / Codex / Gemini
/ OpenCode). The installer brings everything else (it installs `uv` if you don't have it).

> **On the `curl … | bash` one-liner:** a pipeline reports the exit status of its *last*
> command, so if the download fails, `bash` receives empty input and exits `0`. The
> installer's own `set -euo pipefail` never gets to run, because it was never fetched. If you
> are scripting this, prefer the clone-then-run form, or fetch to a file and check that fetch
> before executing it. A mid-transfer drop is worse than a failed one: bash receives a
> **prefix** of the script and partially executes it.

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

- `schema == "phase-loop-doctor.v1"` — **the CLI runs.** Assert it rather than grepping the
  installer's output. It does *not* prove the whole install: the installer places a CLI
  **and** your harness's skills, and this field speaks only for the CLI.
- **`install_surfaces[]` is the skills half.** Find the entry with
  `surface == "interactive-harness-skills"` for your harness and require
  `status == "present"` (`partial` / `missing` mean the skill files aren't where the
  harness will look). Without this an install whose skill links dangle — say the clone
  they pointed at was deleted — still reports `schema` and exit 0.
- **Never infer the verdict from `schema` alone.** Stdout stays pure, parseable JSON *even
  when the command fails*, so the payload still carries `schema == "phase-loop-doctor.v1"`
  alongside a non-zero exit (diagnostic on stderr). For the plain command shown above the two
  agree, so checking both is merely redundant — but the moment you add a flag that can fail,
  such as `--fail-on-stale`, `schema` stops tracking the verdict and an installer asserting
  only `schema` reports success over a failure. Check the exit code because it is the verdict,
  not because `schema` is unreliable.
- Exit `0` from a plain `doctor --json` means the report was produced. It is **not** a claim
  that every tool is present — read `tools[]` for that.
- `--fail-on-stale` exits non-zero **only** on a `stale` verdict among the *gating*
  (repo-owned) targets.
- **Do not treat `unknown` as failure.** The BOM degrades every unreachable registry to
  `unknown` by design, so an offline or network-restricted host reports `unknown` and still
  exits `0`. Failing on `unknown` will make your installer red on a healthy machine.

**The whole pass condition, in one place** — copy this rather than assembling it from the
bullets above. **It depends on which install you ran**, so pick the matching surface line:

> **installed** = the installer itself exited `0`
> *(under the `curl … | bash` one-liner the pipeline's exit is **bash's**, not the
> installer's — see the caveat above; scripted installs should clone-then-run)*
> **and** `phase-loop doctor --json` exited `0`
> **and** `schema == "phase-loop-doctor.v1"`
> **and** the matching `install_surfaces[]` entry has `status == "present"`:
>
> | how you installed | required surface |
> |---|---|
> | `pip install` / `uv tool install` only | `wheel-bundled-skills` |
> | `install-agent-harness.sh --harness <one>` | `interactive-harness-skills` for **that** harness |
> | `install-agent-harness.sh --harness all` | `interactive-harness-skills` for **all four** |
>
> `unknown` BOM verdicts are **not** failures.
>
> **Custom skill roots — the two env vars behave differently, and conflating them will
> make you dismiss a real failure.**
>
> - `AGENT_HARNESS_SKILL_DEST` is **installer-only, and only honored for a SINGLE
>   harness** — `--harness all` ignores it and installs to the default roots. `doctor`
>   never reads it either, so a good single-harness install to a custom destination reads
>   `missing` / `partial`. That one *is* a false red. Bridge it **only for a
>   single-harness install**, passing the **literal path** you installed to:
>   `PHASE_LOOP_SKILL_BUNDLE=/your/custom/root phase-loop doctor --json`, then assert your
>   harness's entry. Do **not** write `"$AGENT_HARNESS_SKILL_DEST"` unless it is still
>   set in *this* shell — a command-scoped assignment on the installer line does not
>   persist, and an empty value is ignored by the resolver, which silently drops you back
>   to the default roots. After `--harness all`, do **not** bridge — but if
>   `PHASE_LOOP_SKILL_BUNDLE` is already exported in your shell it redirects **all four**
>   harness probes to that one path regardless of how you installed, so clear it for the
>   check: `PHASE_LOOP_SKILL_BUNDLE= phase-loop doctor --json` (an empty value is ignored
>   by the resolver, which is exactly what restores the defaults; works in `sh`, `bash`
>   and `zsh`).
> - `PHASE_LOOP_SKILL_BUNDLE` is **honored by `doctor`** — it probes *that* path, not the
>   defaults. So `missing` / `partial` under it is a **true finding about the root you
>   pointed at**, and must not be waved away as a default-root artifact.

**Two things the pass condition deliberately does not include.**

- **Pin currency is not install success.** `--fail-on-stale` compares gating pins against the
  registry's *latest*; a floor legitimately lags latest, so a healthy install can exit
  non-zero under that flag. Run it if you want to know whether your pins are current — that
  is a **separate question** from whether the install worked, and treating it as install
  failure will red a working machine.
- **`doctor` inspects state, not the run that produced it.** It cannot tell a fresh install
  from a stale one that was already there, so a *failed upgrade* over a working older install
  still satisfies every clause above. That is why the installer's own exit code is the first
  conjunct, and why you should verify the version you asked for actually landed
  (`phase-loop --version`) on **any update or re-run**, not only when you pinned a
  `--ref`. The silent case: an unpinned one-liner update whose download fails exits `0`,
  doctor stays green against the *old* install, and nothing was updated.

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

- **Update:** `git pull` in your clone **first**, then re-run the installer. Re-running a
  stale clone does **not** update you: `resolve_ref` trusts the clone's own sibling
  `RELEASE_PIN` before consulting the remote, so it re-installs the same old ref. (The
  `curl … | bash` one-liner has no local pin and does resolve the current release — but
  see the pipeline-exit caveat above before scripting it.)
- **Update (only if you installed with `pip` / `uv` YOURSELF, not via the installer
  script):** `uv tool upgrade phase-loop-runtime` — or `pip install -U
  phase-loop-runtime`. Name the **engine**, not `consiliency-harness`: that shim pins a
  floor (`phase-loop-runtime>=0.6.1`), so upgrading the shim can leave the old engine in
  place and report success.
  **If the installer script put it there, `uv tool upgrade` will NOT move you.** The
  script installs from a tag-pinned URL, so uv stores that exact spec in its receipt and
  re-resolving it reinstalls the same version — a silent non-update. Re-run the installer
  instead (see the two bullets above for which form actually advances the ref).
- **Pin a version:** `--ref vX.Y.Z` (everyone on the same release).
- **Uninstall:** `uv tool uninstall phase-loop-runtime` and remove the
  `*-phase-*` skill symlinks from your skill root.

## Troubleshooting

- **`phase-loop: command not found`** — make sure `~/.local/bin` is on your `PATH`
  (the installer puts the CLI there); open a new shell or `hash -r`.
- **Already have a `phase-loop` on PATH?** Check which one wins with
  `command -v phase-loop` and `phase-loop --version`.

Repo + issues: <https://github.com/Consiliency/agent-harness> · Apache-2.0.
