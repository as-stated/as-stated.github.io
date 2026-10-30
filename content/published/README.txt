Published channel: approved public content only.

Nothing is here yet. Files arrive here only after the owner approves a release:
  records/<ID>/vX.Y.json          one immutable file per released version
  snapshots/YYYY-MM.json          statistics snapshots
  updates.json                    the public updates list
  releases/*.txt and *.txt.sig    release statements signed with the owner's key

The build refuses any file in this channel that lacks a valid owner signature, was changed after
signing, or is marked as sample content.
