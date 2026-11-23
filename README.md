# As Stated

Independent scrutiny of published mathematical and theoretical claims.
*What was claimed. What was tested. What survived.*

Source for the public website at <https://as-stated.github.io/>.

**Current status: production with real released records.** The site is built from the `published` channel.
The first real record is `TA-2026-001`, a negative deep audit of Kamada and Kojima (2018). This repository
holds production code and real approved public data only.

## Contents

| Path | Purpose |
| --- | --- |
| `build.py` | Static site builder and release checker (Python 3.12+; standard library plus pinned build dependencies). |
| `release_safety.py` | CI and local pre-push checks for immutable history, live-source freshness, private authorization, canonical status, and owner holds. |
| `mathml.py` | Build-time mathematics for schema-2 and schema-3 records: delimiter checks and validation of the converted MathML. |
| `requirements.txt` | Build dependencies, pinned to exact versions and SHA-256 hashes. |
| `site.json` | Production configuration: name, descriptor, URLs, owner, channel, optional pages. |
| `static/` | Stylesheet, script (filters and copy buttons; every page works without it), favicon. |
| `content/published/` | Public records allowed by the current operating model, each with an exact SHA-256 release manifest. |
| `tests/` | Unit, release-gate, statistics, link, leak and layout tests. `tests/fixtures.py` generates their data in a temporary folder at run time; none of it is stored here. |
| `.github/workflows/deploy.yml` | Tests, builds and deploys to GitHub Pages. |

## Local use

Requirements: Python 3.12 or later, and the pinned build dependencies:

```
python -m pip install --require-hashes -r requirements.txt
```
The layout tests also need Microsoft Edge or Google Chrome; they are skipped if neither is installed.

```
python -m unittest discover -s tests -v
python build.py build --pretty-urls --out _site
python -m http.server 8000 --directory _site
```

`python build.py build` without `--pretty-urls` writes `dist/` with links that also work when the files
are opened directly from disk. `python build.py check` verifies releases and statistics without writing pages.

## How publication is controlled

1. **Exact release manifests.** Every real record version is built only if a release statement names its exact
   SHA-256. Statistics snapshots are currently blocked by the release guard. Editing a released file without a matching
   new version makes the build fail.
2. **Real content only.** The build reads only `content/published` and refuses anything flagged as not real.
3. **Private release control.** The existing private release record binds the exact JSON bytes to canonical claim and
   event evidence, per-claim readiness, the applicable authorization, and a complete hash inventory of owner-hold notes.
   It is not copied here.
4. **Leak scan.** Every build scans generated text and PDF searchable text, metadata, annotations, form fields, and
   embedded file names and supported contents for local paths, sync-folder names, e-mail addresses and credential patterns.
   Unsupported opaque attachments are refused; the five exact existing C2PA manifest pairs are retained by hash and raw-byte
   scanned. Raster-only image text is not OCR scanned. A release-specific private denylist can add terms that must remain private.
   The public operator README files are also checked by tests so local control paths stay out of this repository.
5. **Deployment freshness.** Before any push, the local guard compares the checkout with the real remote and requires a
   hashed live-audit marker. It validates every public addition since that deployed source. GitHub Actions separately
   checks the full immutable history and confirms that a deployment commit is still the real remote `main`. Actions
   cannot read the private project-control release files.

## Deployment workflow

1. Stage and review the intended changes. Run the tests and build locally; inspect the pages.
2. Commit locally so the worktree is clean, then run `python release_safety.py pre-push --control-root "<project-control-root>" --deployment-dir "<project-control-root>\05_Website\Deployment"`.
   The guard fetches the actual remote, rejects stale or ambiguous state, requires current hashed live-audit evidence,
   checks every unpublished public addition since that audited commit, and validates private release and hold controls.
3. Push only after the guard passes. If the live-state marker is missing or the audit fails, leave the commit local.
4. GitHub Actions runs the tests, checks immutable public history, builds the site (verifying every release manifest) and
   uploads the result. Only a push to `main` deploys; `workflow_dispatch` runs checks but does not deploy.
5. Immediately before deployment, the workflow confirms that the built commit is still the real remote `main`.
6. Check <https://as-stated.github.io/> and a nested page (for example a case record) over HTTPS, run the live audit, and
   record the source commit, run ID and hashed audit evidence.

Pull requests run the tests and build but never deploy.

## Optional pages

`site.json` → `pages` switches on pages that are kept but not shown:

- `"statistics": true` builds the Statistics page from released snapshots and adds it to the navigation. Leave it
  off until enough real records are released for the counts to be useful.
- `"updates": true` builds a project-wide updates log and Atom feed. Case-specific revisions, author responses and
  corrections live in each case's history instead.

## Test data

Tests call `tests/fixtures.py`, which builds a temporary project with generated records, statistics and
manifests, and runs them through the same published channel the site uses. It stores nothing in this repository.

## Schema 2 and 3 records and mathematics

Released schema-1 and schema-2 records are never reinterpreted. New public versions use `"schema": 3`, which retains the
schema-2 claim checks and adds:

- **Primary claim and unresolved context.** `primary_claim_id` identifies the record's principal claim. An unresolved
  claim in a new record needs `unresolved_context.anchor_claim_id` pointing to that same-paper primary positive claim.
  The contextual claim must be secondary; it cannot determine or support the positive finding. A prior-public correction
  uses `publication_revision` instead of the context field.
- **Status corrections.** `publication_revision` records the immediate prior version and status, current status, exact
  prior JSON SHA-256 and reason. Every correction chain must trace to an originally public Open finding and keep each
  prior version and manifest unchanged. Changelog `revision_type` distinguishes programme error correction, superseding
  evidence and material narrowing; only an actual programme error sets `our_correction`. Rejected former findings render
  as status corrections, not new negative audits.
- **Carried corrected status.** When a later version leaves a corrected claim unchanged, `status_provenance` records its
  current status and the version that established it. The builder verifies that pointer against the immutable correction
  history and renders the status as carried forward, not as a new correction or an unresolved context claim.
- **Outreach.** Record-level `outreach.status` may state `not_contacted`,
  `awaiting_substantive_response`, and `substantive_response_received`. Absence is omitted, and `Open` never implies an
  outreach state. Canonical outreach is optional in the public record: omission never gates release. If included, its
  status must match the latest canonical event for each case; `note_drafted` supports `not_contacted`, while states
  without a safe public equivalent must be omitted. Schema-3 author responses carry factual position fields only; they
  cannot contain correspondence summaries, identities, or correspondence text. A private-human-confirmation evidence
  item uses fixed public wording.

- **Status.** Each defect is `open` or `confirmed`. Open is a published finding that has not received the optional
  Confirmed label. Confirmed needs at least two kinds of evidence, one of them human. The build checks that label is
  backed by the evidence; whether a finding meets the research standard is decided upstream, not here.
- **Evidence and author responses.** `evidence` lists only checks that took place. A written author agreement is never
  evidence: it is the claim's `author_response`, and `counts` is true only for an original written agreement.
- **Mathematics.** Write `\( ... \)` for inline and `\[ ... \]` for display formulas in mathematical fields (statement,
  conditions, quantifiers, gist, summary, witness, argument, not_claimed, repair_note, covers, assessment, evidence
  detail). Other fields are plain text. Dollar signs are refused: write money in words. Formulas are converted at build
  time by the pinned latex2mathml into MathML, with the TeX kept in an annotation. The build refuses delimiters that do not
  balance, line breaks, unknown environments, links, styling, and any output outside MathML Core.

Schema-2 records may also list versioned As Stated technical-note PDFs. Each entry gives its creator, date, version,
SHA-256, rights statement, stable `technical-notes/.../vX.Y.pdf` path and optional page count. The build verifies the
exact PDF bytes and renders one direct-open `Read technical note (PDF)` link with the date and, when known, page count.
Other integrity and rights metadata remains in the record JSON and release manifest. The page remains useful without an
inline PDF viewer; corrections use a new version and path.

## Publishing a real record

For an initial Open positive, the standing release authorization applies after the complete case-specific release review
passes; no separate `publish` instruction is required. An active owner hold blocks that default. New Confirmed positives
and named negative audits retain their case-specific `publish` instruction. A correction to a previously public Open
finding uses the standing correction authorization and must match the verified deployed version.

For any new public record version:

1. Add the exact public record under `content/published/records/<ID>/vX.Y.json`.
2. Add the matching SHA-256 release statement under `content/published/releases/`.
3. Add the machine-readable `ASSTATED_RELEASE_CONTROL_V1` block to the same private release record. It binds
   `record_sha256` to the exact JSON bytes, maps every public claim and evidence item to current canonical IDs/events,
   records per-claim readiness and authorization, and inventories every Markdown note under the case's `Publication/`
   and `04_Publication/Reviews/`. A changed or unclassified note blocks a push. A lifted hold needs a later dated
   resolution note tied to this paper.
4. Run tests and a production build with the release-specific private denylist; inspect generated pages.
5. Review and commit locally, then run the pre-push guard above. Push only if source, canonical state, live deployment,
   exact release bytes and holds pass.
6. Verify deployment, run the live-site audit and record the source commit, run ID, and audit-evidence hash in
   `05_Website/Deployment/`. A corrective version requires every predecessor in its lineage to remain in the verified
   live deployment; prior versions stay addressable.

Nothing in the private research archive is copied here automatically.

## Licence

Code: MIT (see `LICENSE`). Text and data on the site: CC BY 4.0.
