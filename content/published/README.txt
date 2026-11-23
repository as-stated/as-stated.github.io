Published channel: immutable, versioned public record data. This README is repository guidance and is not copied into the built site.

Real records live here:
  records/<ID>/vX.Y.json          one immutable file per released version
  releases/*.txt                  exact SHA-256 release manifests
  files/technical-notes/...       versioned public PDFs referenced by records

Statistics snapshots are currently fail-closed by the release guard. Do not add them until their release controls are implemented.

Initial Open positive findings use the standing publication authorization only after the full case-specific review passes. New Confirmed positives and negative audits still need their case-specific publish instruction. Corrective versions of a previously public Open finding use the standing correction authorization and preserve every prior version.

The private release record binds the exact public JSON bytes to canonical claims and events, per-claim readiness, evidence hashes, author holds and the verified deployed source. The build checks each public manifest and scans public PDF text and metadata; release and deployment checks are documented in the repository README and the project publication procedure.
