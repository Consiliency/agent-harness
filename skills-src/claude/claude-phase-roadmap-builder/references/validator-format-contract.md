# claude-phase-roadmap-builder — validator format contract

Reference for `claude-phase-roadmap-builder` (linked from its `SKILL.md`, Step 8).
Phase-loop adapter runs read this file too: it is not preloaded with the skill.

**Validator Format Contract** — the checks above are regex-based on stable headings, not a full Markdown parse, so these formatting rules are load-bearing; a violation drops the phase, mis-parses a field, or trips a structural check rather than warning politely:

- Phase heading shape is `### Phase N — <Name> (<ALIAS>)`. The alias must match `[A-Za-z0-9]+` — letters and digits only, no spaces, hyphens, underscores, or punctuation — and nothing may follow the closing `)` on that line. Trailing decoration after `(ALIAS)` makes the heading malformed. Use UPPERCASE aliases (`SKILLREF`, `P2A`), the convention every roadmap follows: a lowercase alias parses in the heading but its `Depends on` references will not resolve, because the dependency parser uppercases the tokens it reads while the phase's own alias is compared as written.
- A malformed heading cascades — fix the heading first. A heading that fails the phase regex is not parsed as a phase at all, so its fields, alias, `Depends on`, and produced gates disappear and downstream checks (unknown-alias, IF-gate reconciliation, DAG acyclicity) light up with secondary errors. When a heading error appears, correct it and re-run before chasing the rest.
- Each `**Field**` label sits on its own line, with the field body on the following lines. `**Objective** text on the same line` is not recognized and reads as a missing field.
- Lists are bulleted: `Key files` uses `- ` bullets and `Exit criteria` uses `- [ ]` / `- [x]` checkboxes. Prose in place of bullets reads as empty.
- Every implementation phase declares a lane hint in `Scope notes` (or a `**Lanes**` block): a literal such as `decompose into N lanes`, `Single lane` (with justification), or partition words (`disjoint`, `owns`, `partition`, `lane A`/`lane B`), unless the phase is marked preamble/interface-only.

