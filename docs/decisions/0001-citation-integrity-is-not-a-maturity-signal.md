# ADR 0001 — Citation integrity produces findings, never a maturity rung

Status: **accepted** (2026-07-27)
Deciders: cross-vendor advisory panel (codex, grok), operator
Supersedes: nothing. Constrains: `phase_loop_runtime.citation_audit` and any future
citation/traceability checking in the fleet.

## Context

`citation_audit` mechanically verifies source citations in prose documents — a cited path
resolves, a cited line exists, a cited **symbol** is actually defined. It was built after
seven citations drifted or were fabricated in **normative plan documents** in a single
session, every one caught by a reviewer and none by a check.

The question was whether it should participate in the fleet's shared maturity ladder:

```
presence-only < hash-checked < realized-edge-observed < parity-certified < authority-certified
```

That ladder is live contract across three repos — `consiliency_gates._CONFORMANCE_LADDER`,
`fleet_map.MATURITY_LABELS`, and the spec repo's cert semantics (`ec_reproducible` gates
`certified`). `realized-edge-observed` looked tempting: a resolving `path::symbol` is, in a
sense, a claimed edge observed against realized code.

## Decision

**The audit emits findings only. It MUST NOT emit or imply a maturity label.**
`realized-edge-observed` remains fleet-edge and declared-projection vocabulary.

If citation quality is ever allowed to touch document maturity, it may only act as a
**demotion of integrity evidence** — never as a positive grant.

## Why

1. **Applying a document-level rung is a category error.** The canonical loop is
   `N(S) = N(P(E(C), S))`, and `spec-graph` is desired-state only — §0 explicitly disclaims
   being `E(C)` or the projection engine. The contract's own document-class registry defines
   `proj-S` as a projection *from certified S* and `proj-code` as one from code facts —
   not "human prose containing links to code."

   A resolving citation proves none of: that the source supports the surrounding prose,
   that code conforms to `S`, that the document was projected from `S`/`E(C)`, or that
   normalization succeeded.

2. **Routing it through `spec_conformance` would launder a doc-lint into a spec gate** —
   and would miss the target anyway: that gate covers declared `proj-S`/`proj-code`
   documents, while every motivating incident happened in ordinary normative plans.

3. **Precedent already separates artifact maturity from edge evidence.** Whole `proj-code`
   artifacts cap at `hash-checked` while their individual edges may be
   `realized-edge-observed`. Artifact-level aggregation is not how the ladder works.

4. **The evidence bar is not met.** The spec side requires `ec_reproducible` for
   `certified`. This resolver is a *textual* definition search, not a semantic one. It is
   deliberately permissive and cannot distinguish overloads, re-exports or qualified
   identity. That is adequate for a lint and inadequate to carry a rung.

## Known limits of the detector (do not paper over these)

* **In-range line drift is NOT detected, and cannot be** from a bare `path:N` — the
  citation carries no expectation of what that line should contain. Detecting it needs a
  carried expectation or a content-digest baseline; neither is implemented. An earlier
  version of the module implied otherwise; that was false and is now pinned by a test.
* Symbol resolution is **lexical**, over comments/strings stripped. It catches a fabricated
  or renamed name. It does not prove semantic identity.

These limits are why the audit pushes toward `path::symbol`: a symbol anchor is
self-describing and drift-proof by construction, because the name IS the expectation.

## Consequences

* Ownership: agent-harness owns the detector; enforcement belongs with document/local
  integrity, not `spec_conformance`; a neutral evidence schema would live in the
  consiliency contract if fleet-wide inheritance is ever wanted.
* Scope by **normative surface** (plans, designs, ADRs), not by projection class — the bug
  class was plans.
* A future `citation_integrity` check family may carry its own gate-level status. It still
  does not grant document maturity.
