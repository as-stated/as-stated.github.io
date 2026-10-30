# As Stated

Independent scrutiny of published mathematical and theoretical claims.
*What was claimed. What was tested. What survived.*

Source for the public website at <https://as-stated.github.io/>.

**Current status: production, no records released yet.** The site is built from the `published` channel,
which is empty: the Cases page says that no case records have been released. Pages: home, Cases, Methodology,
Definitions, About. The fictional sample corpus in `content/sample/` is used only by the tests and never
appears on the site.

## Contents

| Path | Purpose |
| --- | --- |
| `build.py` | Static site builder and release checker (Python 3.12+, standard library only). |
| `site.json` | Production configuration: name, descriptor, URLs, owner, channel, optional pages. |
| `tests/site.sample.json` | Test configuration that builds the fictional sample channel with every page enabled. |
| `static/` | Stylesheet, script (filters and copy buttons; every page works without it), favicon. |
| `content/sample/` | Fictional test fixtures: records, statistics snapshots, updates and their signed release statements. Not deployed. |
| `content/published/` | Real, owner-approved content. Empty: nothing has been released. |
| `trust/allowed_signers` | Owner's public release key for the published channel. Empty on purpose. |
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

1. **Signed releases.** A record version, statistics snapshot or updates list is built only if a release
   statement naming its exact SHA-256 exists and carries a valid SSH signature (`ssh-keygen -Y`, namespace
   `as-stated-release`) from a key in the channel's trust file. Editing a signed file, adding an unsigned
   one or signing with another key makes the build fail.
2. **Channels.** `sample` holds fictional content signed with the demonstration key. `published` trusts
   only `trust/allowed_signers`, refuses the demonstration key and refuses anything marked as sample.
3. **Pinned trust.** The workflow passes the `TRUST_FINGERPRINTS` repository variable to
   `--expect-trust`. The build fails unless the trusted keys are exactly those fingerprints, so a commit
   that swaps in a different key cannot deploy. Only repository administrators can change the variable.
4. **Statistics checks.** Snapshots must satisfy the metric partitions and subset relations, must not fall
   below what the released records show, and suppressed cells must not be recoverable to fewer than three
   values from everything published, including earlier snapshots.
5. **Leak scan.** Every build scans its output for local paths, sync-folder names, e-mail addresses and
   credential patterns. `--private-denylist FILE` adds a list of private terms kept outside this repository.
6. **Deployment approval.** The `deploy` job runs in the `github-pages` environment, which requires the
   owner's approval for each deployment and accepts only the `main` branch.

Points 1–5 check the content of every build. Point 6 is a repository setting. None of them stops someone
who holds the owner's GitHub login, including an automated tool running with that login: such a person or
tool can push to `main` and change settings. The approval step can be removed under Settings → Environments
→ `github-pages` → Required reviewers; deployments then start automatically after each push to `main`.

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

1. The owner adds their public release key to `trust/allowed_signers` (one line; format in the file), and an
   administrator sets `TRUST_FINGERPRINTS` to that key's fingerprint. While no key exists and nothing is released,
   the variable is `none`.
2. The approved record goes into `content/published/records/<ID>/vX.Y.json`, signed by the owner:
   `python build.py sign --key PATH --kind record --id ID --version V --file FILE --channel published`.
3. Build with `--private-denylist`, review the diff, push, and approve the deployment.

Nothing in the private research archive is copied here by any automated step.

## Licence

Code: MIT (see `LICENSE`). Text and data on the site: CC BY 4.0.
