# ROLLJOB contract amendment r6: R9′, two GitHub Apps split by trust boundary

Frozen amendment text for `plans/phase-plan-v1-agyroll-ROLLJOB.md`, lane SL-5. It is applied
verbatim, in one pull request, to `plans/artifacts/agyroll-v1-contract.md` (AGYROLL),
`plans/artifacts/agyfresh-contract.md` (AGYFRESH) and `specs/phase-plans-agyroll-v1.md` (the
roadmap). The lane then recomputes the roadmap's External Inputs digests from the committed
files; no digest is written here.

r3 replaced r2 of this file, which proposed a machine user and a fork; that design needed a
new GitHub user account. r4 added what the r3 re-review required: an author-agnostic catalog
check, an attestation file for settings no token can read, and the definition of what proves
EC-ACTIVATE-2. r5 applies the owner's decision of 2026-11-20, "no extra review": r4's
code-owner rule is withdrawn, and the wording about who merges is corrected throughout. r6
limits the job signature and the diff-class restrictions to the promotion path in every
place the contracts state them, so that this text can be applied verbatim.

## 0. Status and the confirmation record

**R9′ is proposed, not confirmed.** R9 is an owner ruling. SL-5 does not start until the owner
has confirmed the text below. When it applies the text, the lane:

1. fills the one placeholder in §3, `<owner confirmation: date and words>`, with the date and
   the owner's words as the coordinator relays them;
2. quotes the same confirmation in the pull request description;
3. stops and reports if no confirmation has been supplied. It never writes R9′ as confirmed
   on its own authority.

## Why

R9 gave the job a repository identity with contents and pull-requests write. R6′ then says a
compromised job identity "cannot promote non-upstream bytes, and it cannot promote a `pinned`
flag or a policy change without a maintainer merge". With write access and no review
requirement on `main`, that holds for the promotion path only.

Three constraints shape the replacement (owner, 2026-11-20):

- no new GitHub user account per use case;
- the organization's existing automation account has write on every organization repository and keeps it, so
  its token must not sit on the qualification host beside a parser of untrusted input;
- nothing may require the owner to sign or approve each catalog update.

**What the owner is asked to confirm, in one list.**

1. Two organization-owned GitHub Apps with the permissions in §1 (§6.2), and no user account.
2. Catalog updates are submitted as issues and promoted by a workflow on `main`.
3. A required check on every pull request that touches the catalog, whoever wrote it. It
   passes when every added or changed member is upstream's.
4. **No review rule is added, and CODEOWNERS is not changed.** The workflows, signer list,
   policy and verifier code and the attestation file change through ordinary pull requests
   by repository writers. The residual risk is accepted as stated, and it includes two
   specific things:
   - the required check runs from a workflow file that a pull request can itself edit;
   - a repository writer keeps GitHub's ordinary authority to merge, and to enable
     auto-merge on, any pull request that meets `main`'s ruleset. "Never auto-merges" in
     R6′ limits this automation, not writers.

   So a rogue or compromised writer can change those files, or land a catalog change by
   hand, as with any code. A compromised qualification host or job identity still cannot promote
   bytes that are not upstream's.
5. The existing automation account's access is unchanged.

**Design.** Two organization-owned GitHub Apps, installed on this repository only. The job
on the qualification host holds the INTAKE App's key, which can only write issues, and uses it to submit the
signed record as data. A workflow on `main` verifies the record, authors the catalog pull
request itself with the PROMOTION App, whose key exists only as an Actions environment
secret, and arms the merge for that one commit.

## 1. AGYROLL

**Header, "AGYFRESH amendment" paragraph.** Append:

> **R9′ amendment (2026-11-20).** §6.1's promotion path, §6.2's identity and §6.3's lag rule
> are amended: the job submits a signed record through an issues-only GitHub App, a trusted
> workflow authors the catalog pull request with a second App, and the lag rule is
> report-only until ACTIVATE.

**§6.1, "Promotion path", the introductory sentence** ("This keeps Q10's draft promotion PR,
its signer quorum and its publisher digest, and (G)'s base-branch rule … (see Merge below):").
Replace with:

> - **Promotion path.** This keeps Q10's publisher digest and (G)'s base-branch rule
>   (`.consiliency/plans/detailed-lkg-cli-qualification-1602-20261014-0359.md`). Under R6′
>   and R9′ the signer quorum is the job's signature plus the hosted provenance check, there
>   is no owner signer, and there is no draft pull request: the pull request is opened by the
>   trusted workflow, already verified. R6 replaces Q10/(G)'s "a maintainer merges" only
>   conditionally (see Merge below):

**§6.1, "Promotion path", steps 1 to 4.** Replace with:

> 1. The job signs the record with its enrolled key and **submits it as data**: one issue,
>    created with the INTAKE App's installation token. The job makes no git write and opens
>    no pull request.
> 2. A workflow on `main`, running `main`'s own code at its own commit, accepts only an issue
>    created by the INTAKE App. It verifies the job signature against `main`'s
>    `agy-allowed-signers`, re-fetches the release by tag, re-derives the member digest, and
>    builds the catalog change itself, aging included.
> 3. The change is one new non-`pinned` member newer than every existing member, plus
>    removals that aging allows. A record that is genuine and signed but is anything else
>    (a requalified existing member, an older version) opens no pull request; a repository
>    writer takes it into an ordinary pull request.
> 4. With the PROMOTION App's short-lived installation token, limited to this repository and
>    to contents and pull-requests write, the workflow creates a branch under `agy-catalog/`,
>    commits exactly the catalog and the new record, and opens a pull request labelled
>    `agy-catalog-auto`. `main`'s required checks run on it.

**§6.1, after the promotion-path steps.** Add:

> - **Every catalog pull request, whoever wrote it.** A required check,
>   `agy catalog provenance`, runs `main`'s verifier on every pull request to `main`. If the
>   pull request changes the catalog, every member it adds or changes must be re-derived
>   from the upstream repository, which is fixed in trusted configuration and never taken
>   from the pull request. A change that is upstream's passes; nothing else is asked. The
>   check reports on every pull request, and passes at once on one that leaves the catalog
>   alone. The job signature and the R6′ diff class are required only on the promotion path.
> - **The files this trusts.** The intake and provenance workflows, `qualified-agy-image.yml`,
>   `ci/agy_catalog_promote.py`, `ci/agy-lag-issue.sh`, `config/agy-rollout-attestation.json`,
>   `plans/evidence/agy-allowed-signers`, `scripts/verify_qualified_agy_image.py` and
>   `agy_catalog_policy.py` are read from `main` at run time, with one exception: GitHub takes
>   a `pull_request` workflow's YAML from the pull request's test merge commit, so the
>   provenance workflow file is whatever the pull request makes it. They change through ordinary
>   pull requests merged by a repository writer under the `main` ruleset; no review rule is
>   added. The automated path never changes them. A rogue or compromised writer can, as with
>   any code.
> - **Attestation.** A ruleset's bypass list cannot be read by the workflow's tokens, and the
>   promoter is given no ruleset access. `config/agy-rollout-attestation.json` records the
>   ruleset ids, targets and exact bypass lists, the App identities and the
>   environment's settings. Auto-merge is armed only when that file is attested and the
>   rules that can be read live agree with it. A missing field is a refusal, never an empty
>   list.

**§6.1, "Merge [R6]", the bullet "Two distinct signers (Q10)".** Replace its last sentence,
"A PR without a valid job signature and a passing provenance check never merges.", with:

> On the promotion path, a record without a valid job signature and a passing provenance
> check is never promoted. This binds the automation. A pull request by a repository writer
> needs the passing provenance check and no signature.

**§6.1, "Merge [R6]", the bullet "Base-branch policy".** Replace with:

> - **Base-branch policy.** The signer list, verifier and merge rule are `main`'s, read at
>   the commit the workflow runs from. The submission supplies the record only.

**§6.1, "R6′".** After the sentence ending "re-derives the member digest.", insert:

> Under R9′ the diff class is enforced by construction: the trusted workflow writes exactly
> `data/agy_catalog.json` and one new record file, and re-derives the changed paths from the
> commit it created before arming the merge.

**§6.1, "Auto-merge".** Append:

> Under R9′ the workflow enables auto-merge with the expected head commit set to the commit
> it authored. A ruleset on `refs/heads/agy-catalog/**` lets only the PROMOTION App create,
> update or delete those branches. `main` requires strict, up-to-date status checks; a
> pending pull request whose base has moved is closed and rebuilt from current `main`, never
> updated in place. The switch that enables auto-merge is a variable of the Actions
> environment limited to `main`, not a repository variable.

**§6.1, "R6′", and wherever §6.1 or §6.2 says a diff "is merged by a maintainer" or "a
maintainer merges it through the ordinary reviewed pull request under the non-bypassable
`main` ruleset".** Replace the phrase with:

> a repository writer merges it under the `main` ruleset

The same replacement applies to "Every other diff, and every PR opened before that ruleset
exists, is still merged by a maintainer" in the "Auto-merge" bullet. No review is implied
anywhere in §6.

**§6.1, "R6′".** Append:

> **Scope of R6′ under R9′.** "Auto-merges" and "never auto-merges" describe what the
> promotion automation does: it arms a merge only for the diff class above, with a valid job
> signature. They are not a limit on repository writers, who keep GitHub's ordinary authority
> to merge, or to enable auto-merge on, any pull request that meets the `main` ruleset.

**§6.1, "What a compromised job identity can promote under R6′".** In its first sentence,
replace "without a maintainer merge" with "without a merge by a repository writer". Then
append:

> This holds because of what the job identity is (R9′, §6.2). The key on the qualification host can create,
> edit, label and close issues and comments in this repository, and nothing else: no code,
> ref, pull request, workflow, variable or setting.
>
> **What this does not cover.** Organization members have write access, and no review is
> required. A rogue or compromised writer can change the workflows, the signer list, the
> verifier or the attestation file, as with any code, and could then land a catalog change
> this mechanism would refuse. R6′ and R9′ bound the job on the qualification host, not a writer.

**§6.1, "Unchanged".** Replace with:

> - **Changed by R9′.** The job no longer pushes a branch or opens a pull request, so the
>   push-destination checks and create-only ref writes of `docs/ops/agy-upstream-watch.md`
>   are retired with them. Idempotence stays: a version and QCI with a pending submission is
>   not qualified again, and a refused one is not retried for 24 h.

**§6.2, "Identity [R9]".** Replace the bullet and its sub-bullets with:

> - **Identity [R9, amended as R9′ on 2026-11-20].** All in place before ACTIVATE. No GitHub
>   user account is created.
>   - **INTAKE App.** Organization-owned, installed on this repository only. Permissions:
>     issues read and write, metadata read (and contents read only if the repository is
>     private). Its private key is on the qualification host with the job.
>   - **PROMOTION App.** Organization-owned, installed on this repository only. Permissions:
>     contents and pull-requests read and write, metadata read; no `workflows`,
>     administration, secrets or variables. Its private key is a secret of an Actions
>     environment limited to `main`, and is stored nowhere else.
>   - `main` has a non-bypassable ruleset that requires strict status checks. A second
>     ruleset limits `refs/heads/agy-catalog/**` to the PROMOTION App.
>   - An issue or pull request is treated as an App's only when its author's immutable user
>     id and the attached App id both match the attestation file; a missing field refuses.
>   - agent-harness#1138 is closed by that setup.
>
>   R9 as ruled on 2026-11-08 gave one identity contents and pull-requests write with no
>   `workflows` permission. R9′ splits that grant: the half that can write code never leaves
>   GitHub Actions.

**§6.3, "Lag rule".** After the "Warn" bullet, add:

> - **Mode.** The rule is report-only until ACTIVATE. The status is always computed and
>   recorded. It fails the nightly run, and the `agy-lag` issue is opened, updated or closed,
>   only once `AGY_LAG_ENFORCE` is `true` in a `main`-only Actions environment that holds no
>   secret. ACTIVATE sets it after EC-ACTIVATE-2 is proven.
> - A pull request "for `L`" is one the PROMOTION App opened on `agy-catalog/<L>-…` less than
>   24 h ago. An intake issue does not count, so a stranded submission cannot hold the
>   status at warn.

## 2. AGYFRESH

**§5.1, R6′ and EC-ROLLJOB-4′.** In both, replace "a maintainer merges it through the
ordinary reviewed pull request under the non-bypassable `main` ruleset" and "is merged by a
maintainer under the non-bypassable `main` ruleset" with:

> a repository writer merges it under the `main` ruleset

**§5.1, R6′.** Append the "Scope of R6′ under R9′" paragraph given for AGYROLL §6.1 above,
verbatim.

**§5.1, EC-ROLLJOB-4′.** Replace "for every catalog PR" with "for every promotion by the
automation", and append:

> The job signature and the diff-class limits bind the promotion path only. Separately, the
> required check `agy catalog provenance` reports on every pull request to `main` and, where
> one changes the catalog, re-derives each added or changed member from upstream; a writer's
> pull request needs that check and no signature.

**§5.1, the paragraph beginning "What a compromised job identity can promote".** Replace
"without a maintainer merge" with "without a merge by a repository writer", and after that
sentence insert:

> That depends on the job identity being able to write issues only (R9′, AGYROLL §6.2). It
> is a statement about the job on the qualification host. It is not a statement about repository writers, who
> can change the trusted files as they can any code.

**§5, "ROLLJOB adds", EC-ROLLJOB-7.** Append: "This applies once the lag rule is enforced
(AGYROLL §6.3, Mode)."

**§5.1, the sentence "The verifier, signer list and merge rule are read from the **base**
branch; the PR head supplies data only."** Replace with:

> The verifier, signer list and merge rule are `main`'s. Under R9′ the submitted record
> supplies data only, and the pull request head is written by the trusted workflow.

**§5.1, the mapping table's "Lane L6" cell for D8-B.** Append: "as amended by R9′ (AGYROLL
§6.1, §6.2)".

Nothing else in AGYFRESH changes.

## 3. Roadmap

**Owner Rulings, R9.** After the three conditions, add:

> - **Amended 2026-11-20, as R9′.** No GitHub user account is created. The job on the qualification host holds
>   an issues-only GitHub App and submits its signed record as data. A workflow on `main`
>   verifies it and authors the catalog pull request with a second App whose key exists only
>   in GitHub Actions (AGYROLL §6.1, §6.2). The non-bypassable `main` ruleset condition
>   stands, and now also requires strict status checks. No review rule is added and
>   CODEOWNERS is unchanged: the files this mechanism trusts change through ordinary pull
>   requests by repository writers, who are trusted for them as for any code. A required
>   check re-derives upstream provenance for every catalog change, whoever wrote it.
>   The existing automation account's access is unchanged. Reason: with write access on the qualification host, R6′'s statement about a compromised job
>   identity would hold for the promotion path only. Confirmed by the owner:
>   `<owner confirmation: date and words>`.

**Owner Rulings, R6′, and EC-ROLLJOB-4.** Replace "a maintainer merges it through the
ordinary reviewed pull request under the non-bypassable `main` ruleset" and "is merged by a
maintainer under the non-bypassable `main` ruleset" with "a repository writer merges it under
the `main` ruleset". In EC-ROLLJOB-4, also replace "for every catalog PR" with "for every
promotion by the automation". After the R6′ bullet, add the "Scope of R6′ under R9′"
paragraph given for AGYROLL §6.1 above, verbatim.

**Owner Decisions, D7.** Replace "bot identity" with "the two GitHub Apps (R9′)".

**Architecture North Star, the watch line of the diagram.** Replace "one member/tick --> draft PR ->
base-branch policy CI" with "one member/tick --> intake issue -> `main` workflow verifies,
authors the PR".

**Exit criteria.** Each keeps its ID and its text, with one sentence appended:

- **EC-ROLLJOB-1:** "Under R9′, 'opens a draft `agy-catalog-auto` PR' reads 'submits the
  signed record through the INTAKE App; the trusted workflow opens the `agy-catalog-auto`
  PR'."
- **EC-ROLLJOB-3:** "Under R9′ the rule is report-only until ACTIVATE sets
  `AGY_LAG_ENFORCE`; before that a failing status is recorded and warned, and the run's exit
  is unaffected by lag."
- **EC-ROLLJOB-4:** "Under R9′, 'reads only the catalog and agy records from the PR head'
  reads 'reads only the submitted record, as data', and 'a PR touching any other path or the
  policy fails' is enforced, for promotion by the automation, by the trusted workflow
  writing exactly those two paths. The job signature and the diff-class limits bind that
  path only. Separately, the required check `agy catalog provenance` reports on every pull
  request to `main`, passes at once when the catalog is untouched, and otherwise re-derives
  each added or changed member from upstream. 'Never auto-merges' limits this automation;
  repository writers keep GitHub's ordinary merge and auto-merge authority."
- **EC-ROLLJOB-6:** "The final clause, about nightly `--upstream-only` passing, applies once
  the lag rule is enforced."
- **EC-ROLLJOB-7:** "This applies once the lag rule is enforced; in report-only mode the
  workflow creates, updates and closes no issue."
- **EC-ACTIVATE-2:** "This is proven only by a pull request opened after auto-merge was
  enabled and merged by the PROMOTION App, with no review and no human merge or branch
  update. A pull request created while auto-merge was off is superseded by a fresh verified
  one; a hand merge never counts."
- **EC-ACTIVATE-1:** "Under R9′, 'the R9 identity (non-admin, no `workflows` permission)'
  reads 'the two R9′ Apps with their stated permissions, each installed on this repository
  only', and both rulesets are recorded in the attested `config/agy-rollout-attestation.json`."

**ROLLJOB scope notes.** Append:

> Under R9′ the job submits through the INTAKE App and makes no git write; the `main`
> workflow builds the catalog change, aging included, and opens the pull request with the
> PROMOTION App. The lag rule is report-only until ACTIVATE.

**ROLLJOB key files.** Add `.github/workflows/agy-catalog-intake.yml`,
`.github/workflows/agy-catalog-provenance.yml`, `ci/agy_catalog_promote.py`,
`config/agy-rollout-attestation.json` and
`phase-loop-runtime/src/phase_loop_runtime/agy_intake.py`.

**External Inputs.** Recompute both contract digests from the committed files and note
"(repinned for R9′)" on each row.
