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
| `build.py` | Static site builder and release checker (Python 3.12+, standard library only). |
| `site.json` | Production configuration: name, descriptor, URLs, owner, channel, optional pages. |
| `static/` | Stylesheet, script (filters and copy buttons; every page works without it), favicon. |
| `content/published/` | Real, owner-approved records, each with an exact SHA-256 release manifest. |
| `tests/` | Unit, release-gate, statistics, link, leak and layout tests. `tests/fixtures.py` generates their data in a temporary folder at run time; none of it is stored here. |
| `.github/workflows/deploy.yml` | Tests, builds and deploys to GitHub Pages. |

## Local use

Requirements: Python 3.12 or later. A fresh clone needs nothing else.
The layout tests also need Microsoft Edge or Google Chrome; they are skipped if neither is installed.

```
python -m unittest discover -s tests -v
python build.py build --pretty-urls --out _site
python -m http.server 8000 --directory _site
```

`python build.py build` without `--pretty-urls` writes `dist/` with links that also work when the files
are opened directly from disk. `python build.py check` verifies releases and statistics without writing pages.

## How publication is controlled

1. **Exact release manifests.** Every real record version, statistics snapshot or updates file is built only if a
   release statement names its exact SHA-256. Editing a released file without a matching new version makes the build fail.
2. **Real content only.** The build reads only `content/published` and refuses anything flagged as not real.
3. **Private approval record.** The owner's exact release decision is retained in the private As Stated publication
   layer; private registry material is not copied into this repository.
4. **Leak scan.** Every build scans output for local paths, sync-folder names, e-mail addresses and credential patterns.
   A release-specific private denylist can add terms that must remain private.
5. **Automatic deployment.** The `deploy` job needs the `build` job, so a failed test, manifest check or leak scan stops
   it. A push to `main` that passes deploys with no further click, so a push to `main` is publication.

## Deployment workflow

1. Make changes locally. Run the tests and build locally; inspect the pages.
2. Commit and push to `main`.
3. GitHub Actions runs the tests, builds the site (verifying every release manifest) and
   uploads the result.
4. If those pass, the `deploy` job publishes the build to the `github-pages` environment.
5. Check <https://as-stated.github.io/> and a nested page (for example a case record) over HTTPS.

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

## Publishing a real record

Only after the owner decides to publish a specific record:

1. Add the exact public record under `content/published/records/<ID>/vX.Y.json`.
2. Add the matching SHA-256 release statement under `content/published/releases/`.
3. Run tests and a production build with the release-specific private denylist.
4. Review the diff, commit and push to `main`.
5. Check that the resulting deployment succeeded and that the record is live.

Nothing in the private research archive is copied here automatically.

## Licence

Code: MIT (see `LICENSE`). Text and data on the site: CC BY 4.0.
