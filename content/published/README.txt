Published channel: owner-approved public content only.

Real releases live here:
  records/<ID>/vX.Y.json          one immutable file per released version
  snapshots/YYYY-MM.json          optional statistics snapshots
  updates.json                    optional public updates list
  releases/*.txt                  exact SHA-256 release manifests

The build refuses a released data file with no matching release manifest or with a mismatched SHA-256.
The private publication layer records the owner's approval. Automated tests and a privacy scan must pass
before a build deploys.
