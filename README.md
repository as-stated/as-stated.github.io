# As Stated

Independent scrutiny of published mathematical and theoretical claims.
*What was claimed. What was tested. What survived.*

Source for the public website at <https://as-stated.github.io/>.

**Current status: production with real released records.** The site is built from the `published` channel.
The first real record is `TA-2026-001`, a negative deep audit of Kamada and Kojima (2018). The fictional
sample corpus in `content/sample/` remains test-only and never appears on the production site.

## Contents

| Path | Purpose |
| --- | --- |
| `build.py` | Static site builder and release checker (Python 3.12+, standard library only). |
| `site.json` | Production configuration: name, descriptor, URLs, owner, channel, optional pages. |
| `tests/site.sample.json` | Test configuration that builds the fictional sample channel with every page enabled. |
| `static/` | Stylesheet, script (filters and copy buttons; every page works without it), favicon. |
| `content/sample/` | Fictional test fixtures: records, statistics snapshots, updates and their signed release statements. Not deployed. |
| `content/published/` | Real, owner-approved records, each with an exact SHA-256 release manifest. |
| `trust/allowed_signers` | Not used by the published channel, which relies on release manifests and deployment approval. |
| `trust/sample_allowed_signers` | Public half of the demonstration key. Its private half was deleted after signing. |
| `make_sample_content.py` | Writes the fictional test fixtures. |
| `tests/` | Unit, release-gate, statistics, link, leak and layout tests. |
| `.github/workflows/deploy.yml` | Tests, builds and deploys to GitHub Pages after the owner approves. |

## Local use

Requirements: Python 3.12 or later and OpenSSH `ssh-keygen` (included with Windows 10+, macOS and Linux).
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
2. **Channels.** `sample` holds fictional test fixtures. `published` holds only owner-approved real public content
   and refuses anything marked as sample.
3. **Private approval record.** The owner's exact release decision is retained in the private As Stated publication
   layer; private registry material is not copied into this repository.
4. **Leak scan.** Every build scans output for local paths, sync-folder names, e-mail addresses and credential patterns.
   A release-specific private denylist can add terms that must remain private.
5. **Deployment approval.** The `deploy` job runs in the protected `github-pages` environment and requires the owner's
   approval before a new build becomes live.

The fictional sample channel still uses its throwaway SSH signatures to exercise signature-verification tests. Real
published records do not require a separate release-signing key.

## Deployment workflow

1. Make changes locally. Run the tests and build locally; inspect the pages.
2. Commit and push to `main`.
3. GitHub Actions runs the tests, builds the site (verifying every signature and the pinned keys) and
   uploads the result.
4. While the `github-pages` environment requires a reviewer, approve the deployment on the run page in
   the Actions tab (Review deployments → `github-pages` → Approve and deploy).
5. Check <https://as-stated.github.io/> and a nested page (for example a case record) over HTTPS.

Pull requests run the tests and build but never deploy.

## Optional pages

`site.json` → `pages` switches on pages that are kept but not shown:

- `"statistics": true` builds the Statistics page from signed snapshots and adds it to the navigation. Leave it
  off until enough real records are released for the counts to be useful.
- `"updates": true` builds a project-wide updates log and Atom feed. Case-specific revisions, author responses and
  corrections live in each case's history instead.

## Test fixtures

```
python make_sample_content.py
python build.py sign-sample
python build.py build --config tests/site.sample.json --channel sample --pretty-urls --out _sample
```

The fixtures are fictional and signed with a throwaway key that the published channel refuses. Regenerating them
does not affect the production site.

## Publishing a real record

Only after the owner decides to publish a specific record:

1. Add the exact public record under `content/published/records/<ID>/vX.Y.json`.
2. Add the matching SHA-256 release statement under `content/published/releases/`.
3. Run tests and a production build with the release-specific private denylist.
4. Review the diff, commit and push to `main`.
5. Approve the resulting `github-pages` deployment in GitHub.

Nothing in the private research archive is copied here automatically.

## Licence

Code: MIT (see `LICENSE`). Text and data on the site: CC BY 4.0.
