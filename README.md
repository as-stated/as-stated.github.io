# As Stated

Independent scrutiny of published mathematical and theoretical claims.
*What was claimed. What was tested. What survived.*

Source for the public website at <https://as-stated.github.io/>.

**Current status: demonstration.** Every case, paper, author, date and statistic on the site is fictional
and marked as such. The project description, methodology, definitions and policies are real. No real
findings have been published.

## Contents

| Path | Purpose |
| --- | --- |
| `build.py` | Static site builder and release checker (Python 3.12+, standard library only). |
| `site.json` | Name, descriptor, URLs, owner, demonstration notice. |
| `static/` | Stylesheet, script (filters and copy buttons; every page works without it), favicon. |
| `content/sample/` | Fictional demonstration records, statistics snapshots, updates and their signed release statements. |
| `content/published/` | Real, owner-approved content. Empty. |
| `trust/allowed_signers` | Owner's public release key for the published channel. Empty on purpose. |
| `trust/sample_allowed_signers` | Public half of the demonstration key. Its private half was deleted after signing. |
| `make_sample_content.py` | Writes the fictional demonstration content. |
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

These controls depend on GitHub settings and on who holds credentials. They do not stop someone who holds
the owner's GitHub session or an administrator token. Automated assistants working on this project must
not hold credentials that can push to this repository, change its settings or approve deployments; they
prepare changes locally for the owner to review and push.

## Deployment workflow

1. Make changes on a local branch. Run the tests and build locally; inspect the pages.
2. The owner reviews the diff, merges to `main` and pushes with their own credentials.
3. GitHub Actions runs the tests, builds the site (verifying every signature and the pinned keys) and
   uploads the result.
4. The owner approves the deployment in the repository's Actions tab (environment `github-pages`).
5. Check <https://as-stated.github.io/> and a nested page (for example a case record) over HTTPS.

Pull requests run the tests and build but never deploy.

## Regenerating the demonstration content

```
python make_sample_content.py
python build.py sign-sample
```

`sign-sample` creates a new demonstration key, signs every sample file and deletes the private key. The
fingerprint changes, so an administrator must set `TRUST_FINGERPRINTS` to the new value (shown on the
Methodology page and by `ssh-keygen -l -f` on the key in `trust/sample_allowed_signers`) before the next
deployment can pass.

## Moving to real content

Only after the owner decides to publish a real record:

1. The owner adds their public release key to `trust/allowed_signers` (one line; format in the file).
2. Approved files go into `content/published/`, each signed by the owner:
   `python build.py sign --key PATH --kind record --id ID --version V --file FILE --channel published`.
3. Set `SITE_CHANNEL: published` in the workflow, set `TRUST_FINGERPRINTS` to the owner key's fingerprint,
   and update `site.json` (identifier prefix, notices).

Nothing in the private research archive is copied here by any automated step.

## Licence

Code: MIT (see `LICENSE`). Text and data on the site: CC BY 4.0.
