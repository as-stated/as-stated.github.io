#!/usr/bin/env python3
"""As Stated: static site builder and release checker (Python standard library plus pinned build dependencies).

Commands
  python build.py build [--channel published] [--pretty-urls] [--out DIR]
                        [--private-denylist FILE] [--expect-trust none]
  python build.py check                            verify releases and statistics only

Publication rule enforced here: every released data file needs a release statement naming its exact
SHA-256, and any file flagged as not real is refused. Real releases use no separate signing key, so
--expect-trust accepts only 'none'. Tests generate their own data at run time (tests/fixtures.py).

Three record schemas. Schema 1 (no "schema" key) and schema 2 are frozen formats of records already released; their
data is never reinterpreted. Schema 2 adds Open/Confirmed status, per-claim evidence and mathematics written as
\\( ... \\) (inline) or \\[ ... \\] (display), converted at build time by mathml.py using the pinned latex2mathml.
Schema 3 adds same-paper unresolved context, public correction history and factual outreach state.
What this module checks is schema, truthful labels, manifests, privacy and math safety. Whether a finding meets the
research standard is decided upstream, and checked against the private ledger by the projection checker.
PDF privacy scanning uses pinned pypdf and fontTools to inspect searchable text, metadata, annotations, form fields, and embedded files.
"""
import argparse
import copy
import hashlib
import html
import io
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import mathml  # noqa: E402  (build-time math for schema 2 and 3; needs the pinned latex2mathml)
NAMESPACE = "as-stated-release"
CHANNEL = "published"


TRACKS = {
    "game_theory": "Game theory",
    "mechanism_design": "Mechanism design",
    "matching_social_choice": "Matching and social choice",
    "statistics": "Statistics",
    "econometrics": "Econometrics",
    "operations_research": "Operations research",
    "theoretical_computer_science": "Theoretical computer science",
}
KINDS = {"defect", "negative"}
# Evidence types (schema 2). Author agreement is not evidence on a case page: it is the author response, and it counts
# toward the optional Confirmed label only when the response says so.
SUPPORT_KINDS = {
    "hostile_ai_recheck": "Separate-session hostile AI recheck",
    "researcher_reproduction": "Reproduced by the researcher",
    "external_check": "External check",
    "author_agreement": "Written author agreement",
    "private_human_confirmation": "Human confirmation recorded privately (source not disclosed)",
}
EVIDENCE_SHORT = {
    "hostile_ai_recheck": "AI recheck", "researcher_reproduction": "researcher reproduction",
    "external_check": "external check", "author_agreement": "author agreement",
    "private_human_confirmation": "private human confirmation",
}
# Schema-1 check kinds, mapped to the names above.
V1_EVIDENCE = {"ai_recheck": "hostile_ai_recheck", "independent_reproduction": "researcher_reproduction",
               "external_human": "external_check", "author_agreement": "author_agreement",
               "private_human_confirmation": "private_human_confirmation"}
HUMAN_KINDS = {"researcher_reproduction", "external_check", "author_agreement", "private_human_confirmation"}
EVIDENCE_TYPES_V2 = {"hostile_ai_recheck", "researcher_reproduction", "external_check", "private_human_confirmation"}
DEFECT_CLASSES = {
    "statement_false": "Statement false as printed",
    "proof_invalid_statement_open": "Proof invalid; statement unresolved",
    "proof_gap_repairable": "Repairable proof gap",
    "definition_defect": "Definition defect",
    "missing_or_hidden_assumption": "Missing or hidden assumption",
    "construction_or_algorithm_fails": "Construction or algorithm fails",
    "citation_or_dependency_gap": "Citation or dependency gap",
}
AFFECTS = {
    "main_result": "Main result",
    "secondary_result": "Secondary result",
    "application_or_example": "Application or example",
    "lemma_or_proof_step": "Lemma or proof step",
}
VOR_LEVELS = {
    "full": "Full: every decisive element checked on rendered pages of the published version",
    "partial": "Partial: some decisive element checked only in extracted text, or not checked",
    "none": "None: checked against a preprint or working paper only",
}
POSITIONS = {
    "agrees": "Authors agreed",
    "partly_agrees": "Authors partly agreed",
    "disagrees": "Authors disagree",
    "none_yet": "No position yet",
    "not_disclosed": "Not disclosed",
    "not_contacted": "Not contacted",
    "previously_corrected": "Not contacted: already corrected before the audit",
}
# Author positions (schema 2). Position and whether it counts as verification support are separate fields.
POSITIONS_V2 = {"agrees": "Agrees", "partly_agrees": "Partly agrees", "disagrees": "Disagrees",
                "reviewing": "Reviewing; no substantive position yet", "no_reply": "No reply recorded",
                "not_contacted": "Not contacted"}
RESPONDERS = {"all": "The authors", "one": "One author", "one_of_two": "One of the two authors", "some": "Some of the authors"}
# (plural, singular) verb forms for an active response
RESPONSE_VERB = {"agrees": ("agree", "agrees"), "partly_agrees": ("partly agree", "partly agrees"),
                 "disagrees": ("disagree", "disagrees")}
RESPONSE_BASES = {"original": "from the authors' own written reply", "secondary_record": "from a secondary record of the reply",
                  "none": "no reply recorded"}
CORRECTION_STATES = {
    "announced": "Announced",
    "author_supplied": "Author-supplied correction",
    "public_revision_verified": "Public revision verified",
    "formal_correction_published": "Formal correction published",
}
UNRESOLVED_REASONS_V2 = {"source_limited", "disputed_reading"}
UNRESOLVED_REASONS_V3 = {"source_limited", "conflicting_checks", "mathematically_open"}
UNRESOLVED_REASON_LABELS = {"source_limited": "source not available", "disputed_reading": "reading of the source disputed",
                            "conflicting_checks": "technical checks conflict",
                            "mathematically_open": "the mathematical question remains open"}
UNRESOLVED_REASONS_V1 = {"source_limited", "disputed_reading"}
REPAIRS = {
    "none_proposed": "No repair proposed",
    "local_repair_proposed": "Local repair proposed",
    "repair_checked": "Repair checked on all cases examined",
    "repair_proved": "Repair proved",
}
NEGATIVE_CAVEAT = ("This record reports an unsuccessful attempt to find a defect within the stated scope. "
                   "It is not a proof that the result is correct.")
NEGATIVE_CAVEAT_GENERAL = ("A negative audit reports an unsuccessful attempt to find a defect within a stated scope. "
                           "It is not a proof that the result is correct.")
SELECTION_STATEMENT = ("Papers are chosen deliberately, not sampled at random. These counts describe this "
                       "programme's work and cannot be read as error rates in published research.")
RECORD_KEYS = {"public_id", "version", "released", "status", "sample", "kind", "track", "title", "headline", "work",
               "claims", "author_position", "correction", "evidence", "history", "challenges", "changelog",
               "statements"}
SNAPSHOT_KEYS = {"snapshot", "as_of", "released", "metrics_version", "sample", "programme", "totals",
                 "unresolved_reasons", "examined_by_track", "activity"}
# Generic patterns only. Project-specific private terms go in a denylist file kept outside this repository.
LEAK_PATTERNS = [r"Dropbox|OneDrive|Google Drive|iCloud Drive", r"[A-Za-z]:\\\\?Users", r"/Users/", r"/home/\w",
                 r"\.env\b", r"BEGIN [A-Z ]*PRIVATE KEY", r"\bgh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_\w{20,}",
                 r"\b[WK]-\d{4}\b", r"TA-PRIVATE"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]


class BuildError(Exception):
    pass


if sys.version_info < (3, 12):
    sys.exit("Python 3.12 or newer is required.")

E = html.escape
OUTPUT_MARKER = ".as-stated-build-output"


# ------------------------------------------------------------------ helpers
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fmt_date(s):
    if not s:
        return ""
    parts = s.split("-")
    if len(parts) == 2:
        return f"{MONTH_NAMES[int(parts[1]) - 1]} {parts[0]}"
    return f"{int(parts[2])} {MONTH_NAMES[int(parts[1]) - 1]} {parts[0]}"


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def release_statement(kind, rid, version, digest):
    return (f"{NAMESPACE} v1\nkind: {kind}\nid: {rid}\nversion: {version}\nsha256: {digest}\n").encode()


def statement_path(croot, kind, rid, version):
    return croot / "releases" / f"{kind}__{rid}__{version}.txt"


# ------------------------------------------------------------------ loading and release verification
class Content:
    def __init__(self, channel=CHANNEL, root=ROOT):
        if channel != CHANNEL:
            raise BuildError(f"unknown channel {channel!r}")
        self.channel = channel
        self.root = root
        self.croot = root / "content" / channel
        self.records = {}   # id -> list of record dicts sorted by version
        self.snapshots = []
        self.updates = {"items": []}
        self.verified = []  # (kind, id, version, sha256)
        self.empty = False

    def released(self, kind, rid, version, path):
        data = path.read_bytes()
        digest = sha256_bytes(data)
        st = statement_path(self.croot, kind, rid, version)
        if not st.exists():
            raise BuildError(f"not released: no release statement for {kind} {rid} {version}")
        if st.read_bytes() != release_statement(kind, rid, version, digest):
            raise BuildError(f"release statement does not match the file for {kind} {rid} {version} "
                             "(content changed after approval?)")
        self.verified.append((kind, rid, version, digest))
        return json.loads(data.decode("utf-8"))

    def content_files(self):
        return [f for sub in ("records", "snapshots", "releases") if (self.croot / sub).exists()
                for f in (self.croot / sub).rglob("*") if f.is_file()] +                [f for f in [self.croot / "updates.json"] if f.exists()]

    def load(self):
        # The channel may be empty when nothing has been released. Any content needs its exact manifest.
        self.empty = not self.content_files()
        if self.empty:
            return self
        rdir = self.croot / "records"
        for f in sorted(rdir.glob("*/v*.json")) if rdir.exists() else []:
            rid, version = f.parent.name, f.stem[1:]
            rec = self.released("record", rid, version, f)
            validate_any(rec, rid, version)
            self.records.setdefault(rid, []).append(rec)
        for rid in self.records:
            self.records[rid].sort(key=lambda r: vkey(r["version"]))
            validate_record_history(self.records[rid], self.verified)
        sdir = self.croot / "snapshots"
        for f in sorted(sdir.glob("*.json")) if sdir.exists() else []:
            snap = self.released("snapshot", f.stem, "1", f)
            validate_snapshot_shape(snap, f.stem)
            self.snapshots.append(snap)
        uf = self.croot / "updates.json"
        if uf.exists():
            self.updates = self.released("updates", "updates", "1", uf)
            if self.updates.get("sample"):
                raise BuildError("updates.json sample flag: only real content may be released")
        check_statistics(self)
        return self

    def latest(self, rid, as_of=None):
        versions = [r for r in self.records[rid] if as_of is None or r["released"] <= as_of]
        return versions[-1] if versions else None

    def latest_all(self, as_of=None):
        out = [self.latest(rid, as_of) for rid in sorted(self.records)]
        return [r for r in out if r]


# ------------------------------------------------------------------ validation
def _require(cond, msg):
    if not cond:
        raise BuildError(msg)


def support_kinds(claim):
    """Schema 1: the evidence kinds that confirm a claim, under the schema-2 names."""
    return {V1_EVIDENCE[c["kind"]] for c in claim.get("checks", []) if c.get("result") == "confirms"}


def validate_record(rec, rid, version):
    where = f"record {rid} v{version}"
    unknown = set(rec) - RECORD_KEYS
    _require(not unknown, f"{where}: unknown fields {sorted(unknown)}")
    missing = RECORD_KEYS - set(rec)
    _require(not missing, f"{where}: missing fields {sorted(missing)}")
    _require(rec["public_id"] == rid and rec["version"] == version, f"{where}: id or version does not match its path")
    _require(re.fullmatch(r"[A-Z]{2,4}-\d{4}-\d{3}", rid) is not None, f"{where}: malformed public id")
    _require(rec["sample"] is False, f"{where}: sample flag is {rec['sample']}: only real content may be released")
    _require(rec["kind"] in KINDS, f"{where}: bad kind")
    _require(rec["track"] in TRACKS, f"{where}: bad track")
    _require(rec["status"] in {"published", "withdrawn"}, f"{where}: bad status")
    _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec["released"]) is not None, f"{where}: bad release date")
    _require(rec["claims"], f"{where}: no claims")
    defect_claims = 0
    ids = [c.get("id") for c in rec["claims"]]
    _require(all(ids) and len(set(ids)) == len(ids), f"{where}: every claim needs a unique id")
    settled = [c for c in rec["claims"] if c["result"]["outcome"] in {"defect_found", "no_defect_found"}]
    for c in rec["claims"]:
        res = c["result"]
        _require(c.get("vor_check", {}).get("level") in VOR_LEVELS, f"{where}: {c['label']}: bad VOR level")
        if res["outcome"] == "unresolved":
            # Rule approved by the owner on 31 October 2026: an unresolved question may be shown only inside a record
            # that is released for its settled claims, never as the reason for naming a paper, and never as a defect.
            _require(settled, f"{where}: {c['label']}: an unresolved claim cannot be the only claim in a record")
            _require(res.get("unresolved_reason") in UNRESOLVED_REASONS_V1 and res.get("detail") and res.get("limits"),
                     f"{where}: {c['label']}: an unresolved claim needs a reason, a description and its limits")
            continue
        _require(c["vor_check"]["level"] in {"full", "partial"},
                 f"{where}: {c['label']}: named records need a full or partial version-of-record check")
        for k in c.get("checks", []):
            _require(k["kind"] in V1_EVIDENCE, f"{where}: {c['label']}: unknown check kind {k['kind']}")
        if res["outcome"] == "defect_found":
            defect_claims += 1
            _require(res.get("candidate_status") == "confirmed",
                     f"{where}: {c['label']}: only confirmed defects may appear in a public record")
            kinds = support_kinds(c)
            _require(len(kinds) >= 2 and kinds & HUMAN_KINDS,
                     f"{where}: {c['label']}: confirmation standard not met (two kinds of check, one by a human)")
            _require(res.get("defect_class") in DEFECT_CLASSES, f"{where}: {c['label']}: bad defect class")
            _require(res.get("affects") in AFFECTS, f"{where}: {c['label']}: bad 'affects'")
            _require(res.get("not_claimed"), f"{where}: {c['label']}: a defect needs a 'not claimed' list")
        elif res["outcome"] == "no_defect_found":
            _require(res.get("depth") == "deep_audit", f"{where}: {c['label']}: named negative audits must be deep audits")
            _require(res.get("search_scope") and res.get("limits"),
                     f"{where}: {c['label']}: a negative audit needs a search scope and limits")
        else:
            raise BuildError(f"{where}: {c['label']}: outcome {res['outcome']} cannot be published as a named record")
    _require((rec["kind"] == "defect") == (defect_claims > 0), f"{where}: kind does not match its claims")
    corr = rec.get("correction")
    if corr:
        _require(corr["relation"] in {"after_notification", "before_audit", "during_audit_before_notification"},
                 f"{where}: bad correction relation")
        _require(corr["attribution"] in {"credits_programme", "none_stated"}, f"{where}: bad correction attribution")
    _require(rec["author_position"]["position"] in POSITIONS, f"{where}: bad author position")


RECORD_KEYS_V2 = (RECORD_KEYS - {"author_position"}) | {"schema", "related", "technical_notes"}
CHANGELOG_KEYS_V2 = {"version", "date", "change", "our_correction"}
WORK_KEYS_V2 = {"authors", "title", "venue", "year", "volume", "pages", "doi"}
RESULT_KEYS_V2 = {
    "defect_found": {"outcome", "status", "defect_class", "affects", "depth", "summary", "witness", "argument",
                     "not_claimed", "repair", "repair_note", "previously_reported"},
    "no_defect_found": {"outcome", "depth", "summary", "search_scope", "limits"},
    "unresolved": {"outcome", "unresolved_reason", "summary", "detail", "limits"},
}


def _keys(obj, allowed, where):
    """Refuse keys the renderer does not know about: nothing unrecognised reaches the published JSON or the page."""
    unknown = set(obj) - allowed
    _require(not unknown, f"{where}: unknown fields {sorted(unknown)}")
CLAIM_KEYS_V2 = {"id", "label", "kind", "role", "page", "gist", "statement", "conditions", "quantifiers",
                 "result", "vor_check", "evidence", "author_response", "novelty"}
RECORD_KEYS_V3 = RECORD_KEYS_V2 | {"primary_claim_id", "outreach"}
CLAIM_KEYS_V3 = (CLAIM_KEYS_V2 - {"author_response"}) | {
    "author_response", "unresolved_context", "publication_revision", "status_provenance"}
OUTREACH_STATES = {
    "not_contacted": "Authors not contacted",
    "awaiting_substantive_response": "Awaiting a substantive author response",
    "substantive_response_received": "Substantive author response received",
}
PUBLICATION_REVISION_STATUSES = {"open", "confirmed", "unresolved", "rejected"}
REVISION_TYPES = {"error_correction", "superseding_evidence", "material_narrowing"}
RECORD_KINDS_V3 = KINDS | {"status_correction"}
EVIDENCE_KEYS_V2 = {"type", "date", "detail", "session", "identity"}
RESPONSE_KEYS_V2 = {"position", "responder", "basis", "counts", "covers", "assessment"}
PRIVATE_CONFIRMATION_PUBLIC_DETAIL = "The confirmation was recorded privately; correspondence and identifying details are not published."
DATE_RE = r"\d{4}-\d{2}(-\d{2})?"
DOI_RE = re.compile(r"10\.\d{4,9}/\S+")
TECH_NOTE_PATH_RE = re.compile(r"technical-notes/[a-z0-9]+(?:-[a-z0-9]+)*/v\d+(?:\.\d+)*\.pdf")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def validate_any(rec, rid, version):
    """Schemas 1 and 2 are frozen; schema 3 adds public lifecycle facts without changing prior bytes."""
    if "schema" not in rec:
        return validate_record(rec, rid, version)
    try:
        if rec["schema"] == 2:
            return validate_record_v2(rec, rid, version)
        if rec["schema"] == 3:
            return validate_record_v3(rec, rid, version)
        raise BuildError(f"record {rid} v{version}: unknown schema {rec['schema']!r}")
    except mathml.MathError as exc:  # malformed or unsafe mathematics refuses the build like any other error
        raise BuildError(str(exc)) from None
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise BuildError(f"record {rid} v{version}: malformed record ({type(exc).__name__}: {exc})") from None


def validate_record_v2(rec, rid, version, allow_unresolved_only_ids=None, allow_corrective_rejected_ids=None,
                       public_position_only=False, unresolved_reasons=None, skip_hostile_claim_ids=None):
    where = f"record {rid} v{version}"
    unknown = set(rec) - RECORD_KEYS_V2
    _require(not unknown, f"{where}: unknown fields {sorted(unknown)}")
    missing = (RECORD_KEYS_V2 - {"technical_notes"}) - set(rec)
    _require(not missing, f"{where}: missing fields {sorted(missing)}")
    _require(rec["public_id"] == rid and rec["version"] == version, f"{where}: id or version does not match its path")
    _require(re.fullmatch(r"[A-Z]{2,4}-\d{4}-\d{3}", rid) is not None, f"{where}: malformed public id")
    _require(rec["sample"] is False, f"{where}: sample flag is {rec['sample']}: only real content may be released")
    _require(rec["kind"] in KINDS, f"{where}: bad kind")
    _require(rec["track"] in TRACKS, f"{where}: bad track")
    _require(rec["status"] in {"published", "withdrawn"}, f"{where}: bad status")
    _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec["released"]) is not None, f"{where}: bad release date")
    _keys(rec["work"], WORK_KEYS_V2, f"{where}: work")
    _keys(rec["statements"], {"ai_use"}, f"{where}: statements")
    for h in rec["history"]:
        _keys(h, {"date", "type", "label"}, f"{where}: history item")
    for ch in rec["changelog"]:
        _keys(ch, {"version", "date", "change", "our_correction"}, f"{where}: changelog item")
    for ch in rec["challenges"]:
        _keys(ch, {"type", "date", "by", "outcome"}, f"{where}: challenge")
    mathml.check(rec["title"], f"{where}: title", math=False)
    mathml.check(rec["headline"], f"{where}: headline", math=False)
    for key, value in rec["work"].items():
        if isinstance(value, str):
            mathml.check(value, f"{where}: work.{key}", math=False)
    _require(rec["claims"], f"{where}: no claims")
    ids = [c.get("id") for c in rec["claims"]]
    _require(all(ids) and len(set(ids)) == len(ids), f"{where}: every claim needs a unique id")
    settled = [c for c in rec["claims"] if c["result"]["outcome"] in {"defect_found", "no_defect_found"}]
    allow_unresolved_only_ids = allow_unresolved_only_ids or set()
    allow_corrective_rejected_ids = allow_corrective_rejected_ids or set()
    unresolved_reasons = unresolved_reasons or UNRESOLVED_REASONS_V2
    skip_hostile_claim_ids = skip_hostile_claim_ids or set()
    defect_claims = 0
    for c in rec["claims"]:
        validate_claim_v2(c, where, settled,
                          allow_unresolved_only=c["id"] in allow_unresolved_only_ids,
                          corrective_rejected=c["id"] in allow_corrective_rejected_ids,
                          public_position_only=public_position_only,
                          unresolved_reasons=unresolved_reasons,
                          require_hostile=c["id"] not in skip_hostile_claim_ids)
        defect_claims += c["result"]["outcome"] == "defect_found"
    corrective_nonpositive = bool(allow_unresolved_only_ids or allow_corrective_rejected_ids)
    _require((rec["kind"] == "defect") == (defect_claims > 0) or (corrective_nonpositive and rec["kind"] == "defect"),
             f"{where}: kind does not match its claims")
    corr = rec.get("correction")
    if corr:
        state = corr.get("state", "formal_correction_published")
        _require(state in CORRECTION_STATES, f"{where}: bad correction state")
        _require(corr["relation"] in {"after_notification", "before_audit", "during_audit_before_notification"},
                 f"{where}: bad correction relation")
        _require(corr["attribution"] in {"credits_programme", "none_stated"}, f"{where}: bad correction attribution")
        mathml.check(corr["note"], f"{where}: correction note", math=False)
        _require(re.fullmatch(DATE_RE, corr["date"]) is not None, f"{where}: correction date must be YYYY-MM or YYYY-MM-DD")
        if state in {"announced", "author_supplied"}:
            _require(corr.get("doi") is None, f"{where}: non-public correction states must not carry a DOI")
        elif corr.get("doi") is not None:
            _require(DOI_RE.fullmatch(corr["doi"]), f"{where}: correction DOI is malformed")
    _keys(rec["evidence"], {"package_doi", "package_sha256", "licence", "files"}, f"{where}: evidence")
    for f in rec["evidence"]["files"]:
        _keys(f, {"name", "sha256"}, f"{where}: evidence file")
    if rec.get("correction"):
        _keys(rec["correction"], {"state", "type", "doi", "date", "relation", "attribution", "claims", "note"}, f"{where}: correction")
    for item in rec["related"]:
        _require(set(item) == {"type", "citation", "doi", "note"}, f"{where}: related item fields")
        _require(item["type"] == "related_work", f"{where}: bad related type")
        mathml.check(item["citation"], f"{where}: related citation", math=False)
        mathml.check(item["note"], f"{where}: related note", math=False)
        _require(item["doi"] is None or DOI_RE.fullmatch(item["doi"]), f"{where}: related DOI is missing or malformed")
    note_paths = set()
    technical_notes = rec.get("technical_notes", [])
    _require(isinstance(technical_notes, list), f"{where}: technical_notes must be a list")
    for note in technical_notes:
        required_note_keys = {"creator", "date", "version", "sha256", "rights", "path"}
        _require(required_note_keys <= set(note) and set(note) <= required_note_keys | {"pages"},
                 f"{where}: technical note needs creator, date, version, sha256, rights and path")
        for key in ("creator", "rights"):
            _require(isinstance(note[key], str) and note[key].strip(), f"{where}: technical note {key} is required")
            mathml.check(note[key], f"{where}: technical note {key}", math=False)
        _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", note["date"]) is not None,
                 f"{where}: technical note date must be YYYY-MM-DD")
        _require(re.fullmatch(r"\d+(?:\.\d+)*", note["version"]) is not None,
                 f"{where}: technical note version must be numeric, such as 1.0")
        _require(SHA256_RE.fullmatch(note["sha256"]) is not None,
                 f"{where}: technical note SHA-256 must be 64 lowercase hexadecimal characters")
        _require(TECH_NOTE_PATH_RE.fullmatch(note["path"]) is not None and not re.search(r"\b[WK]-\d{4}\b", note["path"]),
                 f"{where}: technical note path must be a stable public technical-notes path")
        _require(note["path"].endswith(f"/v{note['version']}.pdf"),
                 f"{where}: technical note path must include its matching immutable version")
        if "pages" in note:
            _require(type(note["pages"]) is int and note["pages"] > 0,
                     f"{where}: technical note pages must be a positive integer")
        _require(note["path"] not in note_paths, f"{where}: duplicate technical note path")
        note_paths.add(note["path"])
    mathml.check(rec["statements"]["ai_use"], f"{where}: ai_use", math=False)
    for author in rec["work"]["authors"]:
        mathml.check(author, f"{where}: author", math=False)
    for h in rec["history"]:
        mathml.check(h["label"], f"{where}: history label", math=False)
    for ch in rec["changelog"]:
        mathml.check(ch["change"], f"{where}: changelog entry", math=False)
    for ch in rec["challenges"]:
        mathml.check(ch["by"], f"{where}: challenge author", math=False)
        mathml.check(ch["outcome"], f"{where}: challenge outcome", math=False)


def validate_record_v3(rec, rid, version):
    """Validate public lifecycle facts. Authorization and readiness live in the private release record."""
    where = f"record {rid} v{version}"
    unknown = set(rec) - RECORD_KEYS_V3
    _require(not unknown, f"{where}: unknown fields {sorted(unknown)}")
    missing = (RECORD_KEYS_V3 - {"technical_notes", "outreach"}) - set(rec)
    _require(not missing, f"{where}: missing fields {sorted(missing)}")
    _require(rec["kind"] in RECORD_KINDS_V3, f"{where}: bad kind")
    for change in rec["changelog"]:
        _keys(change, set(CHANGELOG_KEYS_V2) | {"revision_type"}, f"{where}: changelog item")
        if "revision_type" in change:
            _require(change["revision_type"] in REVISION_TYPES,
                     f"{where}: changelog revision_type is not recognized")
    outreach = rec.get("outreach")
    if outreach is not None:
        _require(set(outreach) == {"status"} and outreach["status"] in OUTREACH_STATES,
                 f"{where}: outreach needs one supported status and no correspondence fields")
    claims = rec["claims"]
    claim_ids = {c.get("id") for c in claims}
    _require(rec["primary_claim_id"] in claim_ids, f"{where}: primary_claim_id must name a claim in this record")
    allow_unresolved = set()
    allow_rejected = set()
    corrective_positive = set()
    restored_positive = set()
    for c in claims:
        _keys(c, CLAIM_KEYS_V3, f"{where}: {c.get('label', '?')}")
        for evidence in c.get("evidence", []):
            if evidence.get("type") == "private_human_confirmation":
                _require(evidence.get("detail") == PRIVATE_CONFIRMATION_PUBLIC_DETAIL,
                         f"{where}: private human confirmation must use the fixed public wording")
        ar = c.get("author_response")
        if ar is not None:
            _require(set(ar) == {"position"},
                 f"{where}: schema 3 author responses may publish only a factual position, not identity or correspondence details")
            _require(ar.get("position") in {"agrees", "partly_agrees", "disagrees"},
                     f"{where}: schema 3 author_response is only for a substantive factual position; use outreach for contact lifecycle")
        revision = c.get("publication_revision")
        provenance = c.get("status_provenance")
        if revision is not None:
            _require(provenance is None,
                     f"{where}: {c['label']}: publication_revision and status_provenance cannot be combined")
            _require(isinstance(revision, dict) and bool(revision),
                     f"{where}: {c['label']}: publication_revision must be a non-empty object")
            _require(set(revision) == {"from_version", "from_status", "to_status", "prior_sha256", "reason"},
                     f"{where}: {c['label']}: publication_revision has unsupported or missing fields")
            _require(re.fullmatch(r"\d+(?:\.\d+)*", revision["from_version"]) is not None,
                     f"{where}: {c['label']}: malformed prior version")
            _require(revision["from_status"] in PUBLICATION_REVISION_STATUSES and
                     revision["to_status"] in PUBLICATION_REVISION_STATUSES,
                     f"{where}: {c['label']}: status correction has an unsupported prior or current status")
            _require(SHA256_RE.fullmatch(revision["prior_sha256"]) is not None,
                     f"{where}: {c['label']}: prior JSON SHA-256 must be 64 lowercase hexadecimal characters")
            _require(isinstance(revision["reason"], str) and revision["reason"].strip(),
                     f"{where}: {c['label']}: status correction needs a reason")
            mathml.check(revision["reason"], f"{where}: publication revision reason", math=False)
            if c["result"]["outcome"] == "unresolved":
                _require(revision["to_status"] == "unresolved", f"{where}: unresolved correction status does not match its finding")
                allow_unresolved.add(c["id"])
            elif c["result"]["outcome"] == "no_defect_found":
                _require(revision["to_status"] == "rejected", f"{where}: rejected correction status does not match its finding")
                allow_rejected.add(c["id"])
            elif c["result"]["outcome"] == "defect_found":
                _require(revision["to_status"] in {"open", "confirmed"} and
                         revision["to_status"] == c["result"].get("status"),
                         f"{where}: positive correction status does not match its finding")
                corrective_positive.add(c["id"])
                if revision["from_status"] in {"unresolved", "rejected"}:
                    restored_positive.add(c["id"])
            else:
                raise BuildError(f"{where}: {c['label']}: unsupported status correction outcome")
            _require(c.get("unresolved_context") is None,
                     f"{where}: a corrective unresolved finding is the former primary finding, not unresolved context")
        elif provenance is not None:
            _require(isinstance(provenance, dict) and set(provenance) == {"status", "revision_version"} and
                     provenance.get("status") in PUBLICATION_REVISION_STATUSES and
                     re.fullmatch(r"\d+(?:\.\d+)*", provenance.get("revision_version", "")) is not None,
                     f"{where}: {c['label']}: status_provenance needs a supported status and prior correction version")
            outcome = c["result"]["outcome"]
            matches = ((provenance["status"] in {"open", "confirmed"} and outcome == "defect_found" and
                        c["result"].get("status") == provenance["status"]) or
                       (provenance["status"] == "unresolved" and outcome == "unresolved") or
                       (provenance["status"] == "rejected" and outcome == "no_defect_found"))
            _require(matches and c.get("unresolved_context") is None,
                     f"{where}: {c['label']}: carried status does not match the finding or cannot be unresolved context")
            if provenance["status"] in {"open", "confirmed"}:
                corrective_positive.add(c["id"])
            elif provenance["status"] == "unresolved":
                allow_unresolved.add(c["id"])
            elif provenance["status"] == "rejected":
                allow_rejected.add(c["id"])
        elif c["result"]["outcome"] == "unresolved":
            context = c.get("unresolved_context")
            _require(isinstance(context, dict) and set(context) == {"anchor_claim_id"},
                     f"{where}: {c['label']}: unresolved material must be explicitly linked as context")
            _require(context["anchor_claim_id"] == rec["primary_claim_id"] and c["id"] != rec["primary_claim_id"],
                     f"{where}: {c['label']}: unresolved material cannot be the principal claim or support another claim")
            _require(c["role"] == "secondary", f"{where}: {c['label']}: unresolved context must be clearly secondary")
        else:
            _require(c.get("unresolved_context") is None,
                     f"{where}: only an unresolved claim can be labelled as context")

    # Reuse the strict v2 scientific/public-data validator without changing the old schemas.
    legacy = copy.deepcopy(rec)
    legacy["schema"] = 2
    legacy.pop("primary_claim_id", None)
    legacy.pop("outreach", None)
    for c in legacy["claims"]:
        c.pop("unresolved_context", None)
        c.pop("publication_revision", None)
        c.pop("status_provenance", None)
    for c in legacy["claims"]:
        if "author_response" not in c:
            c["author_response"] = {"position": "no_reply", "basis": "none", "counts": False}
        else:
            # Schema 3 deliberately publishes position only. Supply non-public compatibility fields
            # solely to the frozen schema-2 scientific validator.
            position = c["author_response"]["position"]
            c["author_response"] = {"position": position, "basis": "none", "counts": False}
            if position in {"agrees", "partly_agrees", "disagrees"}:
                c["author_response"]["responder"] = "some"
    for change in legacy["changelog"]:
        change.pop("revision_type", None)
    legacy["kind"] = "defect" if rec["kind"] == "status_correction" else rec["kind"]
    validate_record_v2(legacy, rid, version, allow_unresolved, allow_rejected,
                       public_position_only=True, unresolved_reasons=UNRESOLVED_REASONS_V3,
                       skip_hostile_claim_ids=corrective_positive - restored_positive)

    current_defect = any(c["result"]["outcome"] == "defect_found" for c in claims)
    current_negative = any(c["result"]["outcome"] == "no_defect_found" and
                           not c.get("publication_revision") and not c.get("status_provenance") for c in claims)
    expected_kind = "defect" if current_defect else ("negative" if current_negative else "status_correction")
    _require(rec["kind"] == expected_kind,
             f"{where}: kind must describe the current projection as {expected_kind!r}, not its former finding")

    primary = next(c for c in claims if c["id"] == rec["primary_claim_id"])
    if any(c["result"]["outcome"] == "unresolved" and not c.get("publication_revision") and
           not c.get("status_provenance") for c in claims):
        _require(primary["result"]["outcome"] == "defect_found" and
                 primary["result"].get("status") in {"open", "confirmed"} and primary["role"] == "main" and
                 sum(c["role"] == "main" for c in claims) == 1,
                 f"{where}: unresolved context requires a qualifying positive finding about the same paper")


def context_claims_retired_by_correction(prior, current):
    corrected_nonpositive = {claim["id"] for claim in current.get("claims", [])
                             if (claim.get("publication_revision") or {}).get("to_status") in {"unresolved", "rejected"}}
    return {claim["id"] for claim in prior.get("claims", [])
            if (claim.get("unresolved_context") or {}).get("anchor_claim_id") in corrected_nonpositive}


def validate_record_history(records, verified):
    """New versions preserve every prior claim and corrections retain an Open-origin lineage."""
    hashes = {(kind, rid, version): digest for kind, rid, version, digest in verified}
    by_version = {rec["version"]: rec for rec in records}
    for rec in records:
        if rec.get("schema") != 3:
            continue
        preceding = [item for item in records if vkey(item["version"]) < vkey(rec["version"])]
        if preceding:
            nearest = max(preceding, key=lambda item: vkey(item["version"]))
            prior_claim_ids = {item["id"] for item in nearest["claims"]}
            current_claim_ids = {item["id"] for item in rec["claims"]}
            retired_context = context_claims_retired_by_correction(nearest, rec)
            _require(prior_claim_ids - retired_context <= current_claim_ids,
                     f"record {rec['public_id']} v{rec['version']}: a previously public claim was removed from the current projection")
            versions = {item["version"] for item in preceding}
            changelog_versions = [item["version"] for item in rec["changelog"]]
            _require(len(changelog_versions) == len(set(changelog_versions)) and versions <= set(changelog_versions),
                     f"record {rec['public_id']} v{rec['version']}: changelog must retain a link for every prior public version")
            previous_by_id = {item["id"]: item for item in nearest["claims"]}
            current_by_id = {item["id"]: item for item in rec["claims"]}
            for claim_id in prior_claim_ids & current_claim_ids:
                old_claim, current_claim = previous_by_id[claim_id], current_by_id[claim_id]
                if public_claim_status(old_claim) != public_claim_status(current_claim):
                    _require(current_claim.get("publication_revision"),
                             f"record {rec['public_id']} v{rec['version']}: a public claim status changed without a visible publication_revision")
                old_correction = old_claim.get("publication_revision") or old_claim.get("status_provenance")
                if old_correction and not current_claim.get("publication_revision"):
                    origin_version = (old_correction.get("revision_version") if old_claim.get("status_provenance")
                                      else nearest["version"])
                    _require(current_claim.get("status_provenance") ==
                             {"status": public_claim_status(old_claim), "revision_version": origin_version},
                             f"record {rec['public_id']} v{rec['version']}: corrected status needs explicit carry-forward provenance")
                elif not old_correction:
                    _require(current_claim.get("status_provenance") is None,
                             f"record {rec['public_id']} v{rec['version']}: status provenance has no prior public correction")
                if not current_claim.get("publication_revision"):
                    lifecycle_fields = {"author_response", "evidence", "vor_check", "publication_revision", "status_provenance"}
                    old_content = {key: value for key, value in old_claim.items() if key not in lifecycle_fields}
                    current_content = {key: value for key, value in current_claim.items() if key not in lifecycle_fields}
                    _require(current_content == old_content,
                             f"record {rec['public_id']} v{rec['version']}: a previously public claim changed without publication_revision")
                change = next((item for item in rec["changelog"] if item["version"] == rec["version"]), None)
                if current_claim.get("publication_revision"):
                    _require(change and change.get("revision_type") in REVISION_TYPES,
                             f"record {rec['public_id']} v{rec['version']}: publication_revision needs a dated revision_type changelog entry")
                    _require(bool(change.get("our_correction")) == (change["revision_type"] == "error_correction"),
                             f"record {rec['public_id']} v{rec['version']}: our_correction must distinguish an error from a status update")
        for claim in rec["claims"]:
            revision = claim.get("publication_revision")
            provenance = claim.get("status_provenance")
            if provenance:
                origins = []
                for candidate in preceding:
                    origin_claim = next((item for item in candidate["claims"] if item["id"] == claim["id"]), None)
                    if origin_claim and origin_claim.get("publication_revision"):
                        origins.append((candidate, origin_claim))
                latest_origin = max(origins, key=lambda item: vkey(item[0]["version"])) if origins else None
                _require(latest_origin is not None and provenance["revision_version"] == latest_origin[0]["version"] and
                         provenance["status"] == public_claim_status(latest_origin[1]),
                         f"record {rec['public_id']} v{rec['version']}: carried status must point to its latest public correction")
            if not revision:
                continue
            rid, version = rec["public_id"], rec["version"]
            prior = by_version.get(revision["from_version"])
            preceding = [item for item in records if vkey(item["version"]) < vkey(version)]
            nearest = max(preceding, key=lambda item: vkey(item["version"])) if preceding else None
            _require(prior is not None and nearest is prior,
                     f"record {rid} v{version}: correction must refer to the immediately preceding public version")
            _require(prior.get("schema") in {2, 3},
                     f"record {rid} v{version}: correction prior version has no supported Open status")
            _require(prior["work"] == rec["work"],
                     f"record {rid} v{version}: correction must retain the same paper/work identity")
            prior_claim = next((item for item in prior["claims"] if item["id"] == claim["id"]), None)
            _require(prior_claim is not None and public_claim_status(prior_claim) == revision["from_status"],
                     f"record {rid} v{version}: correction prior status does not match its immediately preceding public version")
            prior_hash = hashes.get(("record", rid, revision["from_version"]))
            _require(prior_hash == revision["prior_sha256"],
                     f"record {rid} v{version}: correction does not match the exact prior public JSON hash")
            _require(rec["released"] > prior["released"],
                     f"record {rid} v{version}: correction release date must follow the prior version")
            correction_entry = next((ch for ch in rec["changelog"] if ch["version"] == version), None)
            _require(correction_entry and correction_entry.get("revision_type") in REVISION_TYPES,
                     f"record {rid} v{version}: correction needs a dated revision_type changelog entry")
            lineage = prior
            seen = set()
            while True:
                _require(lineage["version"] not in seen, f"record {rid} v{version}: correction lineage has a cycle")
                seen.add(lineage["version"])
                lineage_claim = next((item for item in lineage["claims"] if item["id"] == claim["id"]), None)
                _require(lineage_claim is not None and lineage.get("work") == rec.get("work"),
                         f"record {rid} v{version}: correction lineage changed paper or claim identity")
                provenance = lineage_claim.get("status_provenance")
                if provenance:
                    origin = by_version.get(provenance["revision_version"])
                    origin_claim = next((item for item in origin["claims"] if item["id"] == claim["id"]), None) if origin else None
                    _require(origin is not None and origin_claim is not None and
                             origin_claim.get("publication_revision") and
                             public_claim_status(origin_claim) == provenance["status"] == public_claim_status(lineage_claim),
                             f"record {rid} v{version}: carried correction status has no matching public correction origin")
                    lineage = origin
                    continue
                prior_revision = lineage_claim.get("publication_revision")
                if not prior_revision:
                    _require(lineage.get("schema") in {2, 3} and
                             lineage_claim["result"]["outcome"] == "defect_found" and
                             lineage_claim["result"].get("status") == "open",
                             f"record {rid} v{version}: correction lineage must lead to an originally public Open finding")
                    break
                lineage = by_version.get(prior_revision["from_version"])
                _require(lineage is not None,
                         f"record {rid} v{version}: correction lineage prior version is missing")


def public_claim_status(claim):
    revision = claim.get("publication_revision") or {}
    if revision:
        return revision["to_status"]
    provenance = claim.get("status_provenance") or {}
    if provenance:
        return provenance["status"]
    outcome = claim["result"]["outcome"]
    if outcome == "defect_found":
        return claim["result"].get("status")
    if outcome == "unresolved":
        return "unresolved"
    if outcome == "no_defect_found":
        return "negative_audit"
    return outcome


def validate_claim_v2(c, record_where, settled, allow_unresolved_only=False, corrective_rejected=False,
                      public_position_only=False, unresolved_reasons=None, require_hostile=True):
    where = f"{record_where}: {c.get('label', '?')}"
    unknown = set(c) - CLAIM_KEYS_V2
    _require(not unknown, f"{where}: unknown fields {sorted(unknown)}")
    missing = (CLAIM_KEYS_V2 - {"novelty"}) - set(c)
    _require(not missing, f"{where}: missing fields {sorted(missing)}")
    _require(c["kind"] in CLAIM_KINDS and c["role"] in ROLES, f"{where}: bad claim kind or role")
    mathml.check(c["label"], f"{where}: label", math=False)
    mathml.check(c["page"], f"{where}: page", math=False)
    for field in ("gist", "statement", "quantifiers"):
        mathml.check(c[field], f"{where}: {field}", math=True)
    _require(isinstance(c["conditions"], list), f"{where}: conditions must be a list")
    for x in c["conditions"]:
        mathml.check(x, f"{where}: condition", math=True)
    vor = c["vor_check"]
    _require(vor.get("level") in VOR_LEVELS, f"{where}: bad VOR level")
    _keys(vor, {"level", "pages", "detail"}, f"{where}: source check")
    mathml.check(vor["pages"], f"{where}: source pages", math=False)
    mathml.check(vor["detail"], f"{where}: source check", math=False)
    res = c["result"]
    _require(res.get("outcome") in RESULT_KEYS_V2, f"{where}: bad outcome {res.get('outcome')!r}")
    _keys(res, RESULT_KEYS_V2[res["outcome"]], f"{where}: result")
    mathml.check(res["summary"], f"{where}: summary", math=True)
    outcome = res["outcome"]
    if outcome == "unresolved":
        _require(settled or allow_unresolved_only,
                 f"{where}: an unresolved claim needs a qualifying positive context or a prior-public Open correction")
        _require(res.get("unresolved_reason") in (unresolved_reasons or UNRESOLVED_REASONS_V2) and res.get("detail") and res.get("limits"),
                 f"{where}: an unresolved claim needs a reason, a description and its limits")
        mathml.check(res["detail"], f"{where}: detail", math=True)
        mathml.check(res["limits"], f"{where}: limits", math=True)
    elif outcome == "no_defect_found":
        if corrective_rejected:
            _require(res.get("depth") in {"claim_check", "deep_audit"},
                     f"{where}: a rejected former Open finding needs a scoped refuting review")
        else:
            _require(res.get("depth") == "deep_audit", f"{where}: named negative audits must be deep audits")
        _require(res.get("search_scope") and res.get("limits"), f"{where}: a negative audit needs a search scope and limits")
        mathml.check(res["search_scope"], f"{where}: search scope", math=True)
        mathml.check(res["limits"], f"{where}: limits", math=True)
        _require(vor["level"] in {"full", "partial"}, f"{where}: named records need a full or partial source check")
    elif outcome == "defect_found":
        _require(res.get("status") in {"open", "confirmed"}, f"{where}: a defect's status must be open or confirmed")
        _require(res.get("defect_class") in DEFECT_CLASSES, f"{where}: bad defect class")
        _require(res.get("affects") in AFFECTS, f"{where}: bad 'affects'")
        _require(res.get("depth") == "deep_audit", f"{where}: named defects must come from a deep audit")
        for key in ("witness", "argument"):
            _require(res.get(key), f"{where}: a defect needs '{key}'")
            mathml.check(res[key], f"{where}: {key}", math=True)
        _require(res.get("not_claimed"), f"{where}: a defect needs a 'not claimed' list")
        for x in res["not_claimed"]:
            mathml.check(x, f"{where}: not claimed", math=True)
        _require(res.get("repair") in REPAIRS, f"{where}: bad repair value")
        if res.get("repair_note"):
            mathml.check(res["repair_note"], f"{where}: repair note", math=True)
        _require(vor["level"] in {"full", "partial"}, f"{where}: named records need a full or partial source check")
    else:
        raise BuildError(f"{where}: outcome {outcome!r} cannot be published as a named record")

    evidence = c["evidence"]
    _require(isinstance(evidence, list), f"{where}: evidence must be a list")
    for e in evidence:
        _require(set(e) <= EVIDENCE_KEYS_V2 and {"type", "date", "detail"} <= set(e),
                 f"{where}: evidence item needs type, date and detail")
        _require(e["type"] in EVIDENCE_TYPES_V2, f"{where}: evidence type {e['type']!r} is not recognised "
                 "(author agreement belongs in author_response)")
        _require(re.fullmatch(DATE_RE, e["date"]) is not None, f"{where}: evidence date must be YYYY-MM or YYYY-MM-DD")
        mathml.check(e["detail"], f"{where}: evidence detail", math=True)
        if e["type"] == "hostile_ai_recheck":
            _require(e.get("session") in {"blind", "informed"}, f"{where}: an AI recheck needs its session type")
        if e["type"] == "external_check":
            _require(e.get("identity") in {"named", "anonymous"}, f"{where}: an external check needs its identity")
    types = {e["type"] for e in evidence}

    ar = c["author_response"]
    _require(set(ar) <= RESPONSE_KEYS_V2 and {"position", "counts", "basis"} <= set(ar),
             f"{where}: author response needs position, basis and counts")
    _require(ar["position"] in POSITIONS_V2, f"{where}: bad author position {ar['position']!r}")
    _require(ar["basis"] in RESPONSE_BASES, f"{where}: bad author response basis")
    _require(isinstance(ar["counts"], bool), f"{where}: counts must be true or false")
    active = ar["position"] in {"agrees", "partly_agrees", "disagrees"}
    if active:
        _require(ar.get("responder") in RESPONDERS, f"{where}: an author response needs its responder")
    else:
        _require(not ({"responder", "covers", "assessment"} & set(ar)),
                 f"{where}: a {ar['position']} response has no responder, covers or assessment")
    if ar.get("covers") is not None:
        mathml.check(ar["covers"], f"{where}: covers", math=True)
    if ar["position"] in {"disagrees", "partly_agrees"} and not public_position_only:
        _require(ar.get("assessment"), f"{where}: a disagreeing or partly agreeing response needs our assessment of it")
    if ar.get("assessment") is not None:
        _require(ar["position"] in {"disagrees", "partly_agrees"}, f"{where}: an assessment is only for a disagreeing or partly agreeing response")
        mathml.check(ar["assessment"], f"{where}: assessment", math=True)
    _require(ar["counts"] == (ar["position"] == "agrees" and ar["basis"] == "original"),
             f"{where}: an author response counts only as an agreement recorded from the authors' own written reply")

    if outcome == "defect_found":
        if require_hostile:
            _require("hostile_ai_recheck" in types, f"{where}: a defect needs a separate-session hostile AI recheck")
        if res["status"] == "confirmed":
            kinds = types | ({"author_agreement"} if ar["counts"] else set())
            _require(len(kinds) >= 2 and kinds & HUMAN_KINDS,
                     f"{where}: confirmed needs two kinds of evidence, at least one by a human")


def validate_snapshot_shape(snap, stem):
    unknown = set(snap) - SNAPSHOT_KEYS
    _require(not unknown, f"snapshot {stem}: unknown fields {sorted(unknown)}")
    _require(snap["snapshot"] == stem, f"snapshot {stem}: name mismatch")
    _require(not snap.get("sample"), f"snapshot {stem}: sample flag: only real content may be released")
    for metric in snap.get("examined_by_track", {}):
        _require(metric in {"M01", "M02", "M03", "M04"},
                 f"snapshot {stem}: track breakdowns that include unreleased work are allowed only for M01-M04")


def released_stats(content, as_of, include_legacy_no_reply=False):
    """Counts computable from the records released on or before as_of, read through claim_view."""
    recs = content.latest_all(as_of)
    s = {"papers": len(recs), "claims": 0, "deep": 0, "confirmed": 0, "open": 0, "negative": 0, "rejected": 0, "candidates": 0,
         "ai_blind": 0, "ai_informed": 0, "indep": 0, "external": 0,
         "vor_conf": {"full": 0, "partial": 0, "none": 0}, "vor_neg": {"full": 0, "partial": 0, "none": 0},
         "positions": {"agreed": 0, "partly_agreed": 0, "disagreed": 0, "none_yet": 0}, "notified": 0,
         "unresolved": 0, "previously_reported": 0, "calibration": 0,
         "corrections": {"credits_programme": 0, "none_stated": 0}, "our_corrections": 0,
         "papers_by_track": {t: 0 for t in TRACKS}, "claims_by_track": {t: 0 for t in TRACKS},
         "outcome_by_track": {t: {"confirmed": 0, "open": 0, "negative": 0, "rejected": 0} for t in TRACKS},
         "defect_class": {}, "affects": {}}
    pos_map = {"agrees": "agreed", "partly_agrees": "partly_agreed", "disagrees": "disagreed",
               "reviewing": "none_yet", "no_reply": "none_yet", "none_yet": "none_yet"}
    for r in recs:
        s["papers_by_track"][r["track"]] += 1
        outreach = (r.get("outreach") or {}).get("status")
        paper_notified = outreach in {"awaiting_substantive_response", "substantive_response_received"}
        for c in r["claims"]:
            view = claim_view(r, c)
            pos = view["response"]["position"]
            if r.get("schema") != 3:
                paper_notified = paper_notified or pos in {"agrees", "partly_agrees", "disagrees", "reviewing"}
                if include_legacy_no_reply:
                    paper_notified = paper_notified or pos == "no_reply"
            s["claims"] += 1
            s["claims_by_track"][r["track"]] += 1
            s["deep"] += c["result"].get("depth") == "deep_audit"
            lvl = c["vor_check"]["level"]
            if view["outcome"] == "unresolved":
                s["unresolved"] += 1
            elif view["outcome"] == "rejected":
                s["rejected"] += 1
                s["outcome_by_track"][r["track"]]["rejected"] += 1
            elif view["outcome"] == "defect_found":
                s["candidates"] += 1
                dc = DEFECT_CLASSES[c["result"]["defect_class"]]
                s["defect_class"][dc] = s["defect_class"].get(dc, 0) + 1
                af = "Main result" if c["result"]["affects"] == "main_result" else "Other"
                s["affects"][af] = s["affects"].get(af, 0) + 1
                if view["status"] != "confirmed":
                    s["open"] += 1
                    s["outcome_by_track"][r["track"]]["open"] += 1
                    continue
                # Everything below describes confirmed findings only: Open findings are not counted as confirmed.
                s["confirmed"] += 1
                s["outcome_by_track"][r["track"]]["confirmed"] += 1
                if c["result"].get("previously_reported"):
                    s["previously_reported"] += 1
                    s["calibration"] += 1
                sessions = {e.get("session") for e in view["evidence"] if e["type"] == "hostile_ai_recheck"}
                s["ai_blind"] += "blind" in sessions
                s["ai_informed"] += ("informed" in sessions and "blind" not in sessions)
                types = {e["type"] for e in view["evidence"]}
                s["indep"] += "researcher_reproduction" in types
                s["external"] += "external_check" in types
                if pos in pos_map:
                    s["positions"][pos_map[pos]] += 1
                s["vor_conf"][lvl] += 1
            else:
                s["negative"] += 1
                s["outcome_by_track"][r["track"]]["negative"] += 1
                s["vor_neg"][lvl] += 1
        s["notified"] += paper_notified
        corr = r.get("correction")
        if (corr and corr.get("state", "formal_correction_published") in {"public_revision_verified", "formal_correction_published"}
                and corr["relation"] == "after_notification" and corr["date"] <= as_of):
            s["corrections"][corr["attribution"]] += 1
        s["our_corrections"] += sum(1 for ch in r["changelog"] if ch.get("our_correction"))
    return s


def feasible_intervals(cells, total, lower):
    """Attacker's feasible range for each suppressed (None) cell: zeros are shown, so a suppressed cell is >= 1."""
    sup = [k for k, v in cells.items() if v is None]
    rest = total - sum(v for v in cells.values() if v is not None)
    lo = {k: max(1, lower.get(k, 0)) for k in sup}
    hi = {k: rest for k in sup}
    out = {}
    for k in sup:
        others = [j for j in sup if j != k]
        out[k] = (max(lo[k], rest - sum(hi[j] for j in others)), min(hi[k], rest - sum(lo[j] for j in others)))
    return out


def check_statistics(content):
    """Consistency, subset and reconciliation checks, plus the small-cell reconstruction audit."""
    prev_intervals = {}
    prev_totals = {}
    for snap in sorted(content.snapshots, key=lambda s: s["as_of"]):
        t = snap["totals"]
        tag = f"snapshot {snap['snapshot']}"
        m06 = t["M06"]
        conf = m06["confirmed"]
        _require(m06["open"] + conf + m06["unresolved"] + m06["rejected"] == t["M05"], f"{tag}: M06 does not partition M05")
        _require(m06["open_ai_supported"] <= m06["open"] and m06["confirmed_previously_reported"] <= conf,
                 f"{tag}: M06 sub-counts exceed their status")
        _require(sum(snap["unresolved_reasons"].values()) == m06["unresolved"], f"{tag}: unresolved reasons do not sum")
        m07 = sum(t["M07"].values())
        _require(m07 <= t["M04"] <= t["M03"] and t["M02"] <= t["M01"] and t["M02"] <= t["M03"],
                 f"{tag}: examined counts are not nested (M07 <= M04 <= M03; M02 <= M01, M03)")
        _require(sum(t["M08"].values()) <= conf and t["M09"] <= conf and t["M10"] <= conf,
                 f"{tag}: support counts must be subsets of confirmed claims")
        _require(sum(t["M11"].values()) == conf, f"{tag}: M11 does not partition confirmed claims")
        _require(sum(t["M13"].values()) <= conf, f"{tag}: M13 population exceeds confirmed claims")
        _require(snap["metrics_version"] in {"1.1", "1.2"},
                 f"{tag}: unsupported metrics version {snap['metrics_version']!r}")
        rs = released_stats(content, snap["as_of"], include_legacy_no_reply=snap["metrics_version"] == "1.1")
        checks = [
            ("M01", t["M01"], rs["papers"]), ("M02", t["M02"], rs["papers"]), ("M03", t["M03"], rs["claims"]),
            ("M04", t["M04"], rs["deep"]), ("M05", t["M05"], rs["candidates"] + rs["unresolved"] + rs["rejected"]),
            ("M06 confirmed", conf, rs["confirmed"]), ("M06 open", m06["open"], rs["open"]), ("M06 unresolved", m06["unresolved"], rs["unresolved"]),
            ("M06 rejected", m06["rejected"], rs["rejected"]),
            ("M07", m07, rs["negative"]), ("M08 blind", t["M08"]["blind"], rs["ai_blind"]),
            ("M08 informed", t["M08"]["informed"], rs["ai_informed"]), ("M09", t["M09"], rs["indep"]),
            ("M10", t["M10"], rs["external"]), ("M12", t["M12"], rs["notified"]),
        ]
        checks += [(f"M11 {k}", t["M11"][k], rs["vor_conf"][k]) for k in VOR_LEVELS]
        checks += [(f"M07 {k}", t["M07"]["vor_" + k], rs["vor_neg"][k]) for k in VOR_LEVELS]
        checks += [(f"M13 {k}", t["M13"][k], v) for k, v in rs["positions"].items()]
        for name, public, released in checks:
            _require(public >= released, f"{tag}: {name} = {public} is below the {released} shown by released records")
        for metric, cells in snap.get("examined_by_track", {}).items():
            _require(set(cells) == set(TRACKS), f"{tag}: {metric} breakdown must list every track")
            for k, v in cells.items():
                _require(v is None or v == 0 or v >= 5,
                         f"{tag}: {metric} cell '{k}' = {v} is a small count and must be suppressed")
            lower = rs["papers_by_track"] if metric in {"M01", "M02"} else rs["claims_by_track"]
            iv = feasible_intervals(cells, t[metric], lower)
            prev = prev_intervals.get(metric)
            if prev is not None:
                d = t[metric] - prev_totals[metric]
                iv = {k: (max(a, prev[k][0]), min(b, prev[k][1] + d)) for k, (a, b) in iv.items()}
            for k, (a, b) in iv.items():
                _require(b - a + 1 >= 3, f"{tag}: {metric} cell '{k}' can be narrowed to [{a},{b}]; suppress more cells")
            known = {k: (v, v) for k, v in cells.items() if v is not None}
            known.update(iv)
            prev_intervals[metric] = known
            prev_totals[metric] = t[metric]


# ------------------------------------------------------------------ HTML rendering


class Site:
    def __init__(self, content, config, pretty):
        self.c = content
        self.cfg = config
        self.pretty = pretty
        self.pages = {}

    def href(self, page, target):
        """Relative link from a page path (e.g. 'cases/X/index.html') to a site path."""
        prefix = "../" * page.count("/")
        if target.endswith("/") or target == "":
            target = target + ("" if self.pretty else "index.html")
        out = prefix + target
        return out or "./"

    def add(self, path, html_text):
        self.pages[path] = html_text


NAV = [("cases/", "Cases"), ("statistics/", "Statistics"), ("methodology/", "Methodology"),
       ("definitions/", "Definitions"), ("updates/", "Updates"), ("about/", "About")]
OPTIONAL_PAGES = {"statistics/": "statistics", "updates/": "updates"}


def page_on(site, name):
    """Statistics and the updates log are built only when enabled in the site configuration."""
    return bool(site.cfg.get("pages", {}).get(name, False))


def nav_items(site):
    return [(t, n) for t, n in NAV if t not in OPTIONAL_PAGES or page_on(site, OPTIONAL_PAGES[t])]
TRACK_SHORT = {"game_theory": "Game theory", "mechanism_design": "Mechanism design",
               "matching_social_choice": "Matching and social choice", "statistics": "Statistics",
               "econometrics": "Econometrics", "operations_research": "Operations research",
               "theoretical_computer_science": "Theoretical computer science"}
CLAIM_KINDS = {"theorem": "Theorem", "proposition": "Proposition", "lemma": "Lemma", "corollary": "Corollary",
               "remark": "Remark", "algorithm": "Algorithm", "construction": "Construction", "application": "Application"}
ROLES = {"main": "main result", "supporting": "supporting result", "secondary": "secondary result",
         "auxiliary": "auxiliary result", "application": "application", "repair": "corrected version"}
FAMILIES = [
    ("none", "No defect found",
     "A deep audit within a stated scope found no defect. This is not a proof that the claim is correct."),
    ("rejected", "Rejected former finding",
     "New evidence showed that a previously public Open finding does not stand. This is a status correction, not a new negative audit."),
    ("false", "False as stated",
     "The claim, read exactly as printed with its stated assumptions, is false. A counterexample is given."),
    ("definition", "Definition defect",
     "A definition, notation or convention is stated or reused in a way that can materially change the claim's meaning; the intended result need not be false."),
    ("proof", "Proof incomplete",
     "The proof does not establish the claim as written. The claim itself is not shown to be false, and a repair may exist."),
    ("assumption", "Missing assumption", "The claim holds only under an assumption that the paper does not state."),
    ("construction", "Construction fails",
     "A mechanism, algorithm or other construction does not do what the paper says it does."),
    ("unresolved", "Unresolved",
     "The question could not be settled, usually because the relevant version of the source could not be obtained. "
     "Not counted as a defect."),
]
FAMILY_LABEL = {k: lbl for k, lbl, _ in FAMILIES}
DEFECT_FAMILY = {
    "statement_false": ("false", None), "definition_defect": ("definition", None),
    "proof_gap_repairable": ("proof", "repairable gap"), "proof_invalid_statement_open": ("proof", "statement open"),
    "citation_or_dependency_gap": ("proof", "unsupported citation"),
    "missing_or_hidden_assumption": ("assumption", None), "construction_or_algorithm_fails": ("construction", None),
}
POS_SHORT = {"agrees": "Author response agrees", "partly_agrees": "Author response partly agrees",
             "disagrees": "Author response disagrees", "reviewing": "Authors reviewing",
             "no_reply": "No author reply recorded", "none_yet": "No public author position",
             "not_contacted": "Not contacted"}
POS_LONG = {
    "agrees": "A written author response agrees with the finding.",
    "partly_agrees": "A written author response partly agrees with the finding.",
    "disagrees": "A written author response disagrees with the finding.",
    "none_yet": "No public author position is recorded.",
    "not_disclosed": "Not disclosed.",
    "not_contacted": "The authors were not contacted; author notification is not a publication requirement.",
    "previously_corrected": "The authors were not contacted: the error had already been corrected before this audit.",
}
VOR_SHORT = {"full": "full source check", "partial": "partial source check", "none": "source not obtained"}
METHOD_STEPS = [
    ("Select", "Papers are chosen deliberately. Many are screened from their metadata; fewer are investigated claim by claim."),
    ("State the claim exactly", "Every definition, assumption and quantifier is taken from the published version."),
    ("Try to break it", "A separate-session hostile AI recheck tries to refute the candidate finding."),
    ("Try to rescue it", "Look for the intended reading and for a repair before reporting a problem."),
    ("Check the source", "The decisive statement, definitions and proof step are checked against the published version."),
    ("Ask the authors", "A technical note may be sent. Their reply is recorded whatever it says; no reply does not block publication."),
    ("Publish and maintain", "Each finding is published as Open, or as Confirmed when that optional standard is met. Releases are immutable; corrections are new versions."),
]


def family(c):
    r = c["result"]
    revision = c.get("publication_revision") or {}
    provenance = c.get("status_provenance") or {}
    if revision.get("to_status") == "rejected" or provenance.get("status") == "rejected":
        return "rejected", FAMILY_LABEL["rejected"], None
    if r["outcome"] == "no_defect_found":
        return "none", FAMILY_LABEL["none"], None
    if r["outcome"] == "unresolved":
        return "unresolved", FAMILY_LABEL["unresolved"], UNRESOLVED_REASON_LABELS.get(r.get("unresolved_reason"))
    fam, q = DEFECT_FAMILY[r["defect_class"]]
    label = "Algorithm fails" if fam == "construction" and c.get("kind") == "algorithm" else FAMILY_LABEL[fam]
    if r.get("previously_reported"):
        q = ", ".join(x for x in (q, "previously reported") if x)
    return fam, label, q


def finding_badge(c, qualifier=True):
    fam, label, q = family(c)
    qh = f' <span class="fd-q">{E(q)}</span>' if q and qualifier else ""
    return f'<span class="fd fd-{fam}"><i class="mk" aria-hidden="true"></i>{E(label)}</span>{qh}'


def fmt_month(s):
    parts = s.split("-")
    if len(parts) == 1:
        return parts[0]
    return f"{MONTH_NAMES[int(parts[1]) - 1][:3]} {parts[0]}"


def author_list(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def venue_line(w):
    vol = f" {w['volume']}" if w.get("volume") else ""
    pages = f", {E(w['pages'])}" if w.get("pages") else ""
    return f"<i>{E(w['venue'])}</i>{E(vol)} ({w['year']}){pages}"


def citation_line(w):
    vol = f" {w['volume']}" if w.get("volume") else ""
    pages = f", {w['pages']}" if w.get("pages") else ""
    return f"{author_list(w['authors'])} ({w['year']}). {w['title']}. {w['venue']}{vol}{pages}."


def doi_html(site, doi):
    return f'<a class="mono" href="https://doi.org/{E(doi)}">doi:{E(doi)}</a>'



def development(rec, c):
    view = claim_view(rec, c)
    out = []
    corr = rec.get("correction")
    if corr and c["id"] in corr.get("claims", []):
        state = corr.get("state", "formal_correction_published")
        if corr["relation"] == "before_audit":
            out.append(f"Corrected in {fmt_month(corr['date'])}, before this audit")
        elif state == "announced":
            out.append(f"Correction announced {fmt_month(corr['date'])}")
        elif state == "author_supplied":
            out.append(f"Author-supplied correction {fmt_month(corr['date'])}")
        elif state == "public_revision_verified":
            out.append(f"Public revision verified {fmt_month(corr['date'])}")
        else:
            credit = ", credits this audit" if corr["attribution"] == "credits_programme" else ""
            out.append(f"{corr['type'].capitalize()} {fmt_month(corr['date'])}{credit}")
    if c.get("role") == "repair" and corr:
        out.append(f"Audit of the {corr['type']}")
    if view["outcome"] == "defect_found":
        p = POS_SHORT.get(view["response"]["position"])
        if p:
            out.append(p)
    return out


def dev_html(rec, c):
    items = development(rec, c)
    return "".join(f"<span>{E(x)}</span>" for x in items) or '<span class="muted">—</span>'


def latest_snapshot(content):
    return max(content.snapshots, key=lambda s: s["as_of"]) if content.snapshots else None


def paper_group(site, page, rec):
    rid, w = rec["public_id"], rec["work"]
    link = site.href(page, "cases/" + rid + "/")
    n = len(rec["claims"])
    group_text = f"{rid} {w['title']} {' '.join(w['authors'])} {w['venue']} {w['year']}".lower()
    head = (f'<tr class="ix-head"><th colspan="4" scope="colgroup"><div class="ix-head-in">'
            f'<div class="ix-paper"><a class="ix-title" href="{link}">{E(w["title"])}</a>'
            f'<span class="ix-by">{E(author_list(w["authors"]))} · {venue_line(w)}</span></div>'
            f'<div class="ix-upd">{n} claim{"s" if n != 1 else ""} · updated {E(fmt_date(rec["released"]))}</div>'
            f'</div></th></tr>')
    rows = []
    for c in rec["claims"]:
        view = claim_view(rec, c)
        fam = family(c)[0]
        status = view["status"] or (view["outcome"] if view["outcome"] in {"unresolved", "rejected"} else "")
        where = f"{rid} {c['id']}"
        text = f"{group_text} {c['label']} {mathml.plain(c['gist'])} {mathml.plain(c['result'].get('summary', ''))}".lower()
        rows.append(
            f'<tr class="ix-row" data-fam="{fam}" data-kind="{E(c["kind"])}" data-status="{status}" data-text="{E(text)}">'
            f'<td class="ix-claim" data-label="Claim"><a class="ix-label" href="{link}#{E(c["id"])}">{E(c["label"])}</a>'
            f'<span class="ix-kind">{E(CLAIM_KINDS[c["kind"]])} · {E(ROLES[c["role"]])}</span>'
            f'<span class="ix-gist">{rich(rec, c["gist"], where + " gist")}</span></td>'
            f'<td class="ix-find" data-label="Finding">{finding_badge(c)}'
            f'<span class="ix-sum">{rich(rec, c["result"]["summary"], where + " summary")}</span></td>'
            f'<td class="ix-ver" data-label="Status">{status_cell(site, page, rec, c)}</td>'
            f'<td class="ix-dev" data-label="Development">{dev_html(rec, c)}</td></tr>')
    return f'<tbody class="ix-group" data-track="{E(rec["track"])}">{head}{"".join(rows)}</tbody>'


def claim_index(site, page, recs):
    return ('<div class="ix-wrap"><table class="ix" id="case-index"><thead><tr>'
            '<th scope="col" class="c1">Claim</th><th scope="col" class="c2">Finding</th>'
            '<th scope="col" class="c3">Status</th><th scope="col" class="c4">Development</th></tr></thead>'
            + "".join(paper_group(site, page, r) for r in recs) + "</table></div>")


def counts(recs):
    k = {"papers": len(recs), "claims": 0, "none": 0, "defect": 0, "open": 0, "confirmed": 0,
         "unresolved": 0, "rejected": 0}
    for r in recs:
        for c in r["claims"]:
            k["claims"] += 1
            view = claim_view(r, c)
            if view["outcome"] == "no_defect_found":
                k["none"] += 1
            elif view["outcome"] == "rejected":
                k["rejected"] += 1
            elif view["outcome"] == "unresolved":
                k["unresolved"] += 1
            elif view["outcome"] == "defect_found":
                k["defect"] += 1
                k[view["status"]] += 1
    return k


def legend_html():
    return "".join(f'<li><span class="fd fd-{k}"><i class="mk" aria-hidden="true"></i>{E(lbl)}</span>'
                   f'<span class="lg-d">{E(d)}</span></li>' for k, lbl, d in FAMILIES)


def layout(site, page, title, body, active="", description="", indexable=False, cls=""):
    cfg = site.cfg
    h = lambda t: site.href(page, t)
    cur = ' aria-current="page"'
    nav = "".join(f'<a href="{h(t)}"{cur if active == t else ""}>{E(n)}</a>' for t, n in nav_items(site))
    feed_link = (f'<link rel="alternate" type="application/atom+xml" title="{E(cfg["name"])} updates" href="{h("feed.xml")}">'
                 if page_on(site, "updates") else "")
    feed_foot = f' · <a href="{h("feed.xml")}">Atom feed</a>' if page_on(site, "updates") else ""
    full_title = cfg["name"] if title == cfg["name"] else f"{title} · {cfg['name']}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(full_title)}</title>
<meta name="description" content="{E(description or cfg['descriptor'])}">

<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="{h('static/style.css')}">
<link rel="icon" href="{h('static/favicon.svg')}" type="image/svg+xml">
{feed_link}
</head>
<body class="{cls}">
<a class="skip" href="#main">Skip to content</a>

<header class="mast"><div class="wrap mast-in">
  <a class="brand" href="{h('')}"><span class="brand-mark" aria-hidden="true">⊢</span><span class="brand-name">{E(cfg['name'])}</span></a>
  <nav class="nav" aria-label="Main">{nav}</nav>
</div></header>
<main id="main">
{body}
</main>
<footer class="foot"><div class="wrap foot-in">
  <div class="foot-id"><p class="foot-name"><span class="brand-mark" aria-hidden="true">⊢</span> {E(cfg['name'])}</p>
  <p>{E(cfg['descriptor'])}<br><span class="foot-tag">{E(cfg['tagline'])}</span></p></div>
  <div><p>Human-led, AI-assisted, independent research by {E(cfg['owner'])}. Not affiliated with or commissioned by
  the journals, publishers or authors whose work is examined.</p>
  <p><a href="{h('about/')}#disclosure">Disclosure</a> · <a href="{h('methodology/')}#release">How releases are approved</a>{feed_foot} ·
  <a href="{E(cfg['repository_url'])}">Source</a></p></div>
  <div><p class="muted">Text and data CC BY 4.0; code MIT.<br>Methodology v{E(cfg['methodology_version'])}; metrics v{E(cfg['metrics_version'])}.</p></div>
</div></footer>
<script src="{h('static/app.js')}" defer></script>
</body>
</html>
"""


def render_home(site):
    page = "index.html"
    cfg = site.cfg
    recs = sorted(site.c.latest_all(), key=lambda r: r["released"], reverse=True)
    k = counts(recs)
    stats_link = f' <a href="{site.href(page, "statistics/")}">Statistics</a>' if page_on(site, "statistics") else ""
    plural = lambda n, w: f"{n} {w}{'s' if n != 1 else ''}"
    if recs:
        aside = f"""<p class="aside-k">Released so far</p>
    <p class="aside-v"><strong>{k['claims']}</strong> {'claim' if k['claims'] == 1 else 'claims'} in <strong>{k['papers']}</strong> {'paper' if k['papers'] == 1 else 'papers'}</p>
    <ul class="tally">
      <li><span class="fd fd-none"><i class="mk"></i>No defect found</span><span class="n">{k['none']}</span></li>
      <li><span class="fd fd-false"><i class="mk"></i>Defect found</span><span class="n">{k['defect']}</span></li>
      <li class="sub"><span>Open</span><span class="n">{k['open']}</span></li>
      <li class="sub"><span>Confirmed</span><span class="n">{k['confirmed']}</span></li>
      <li><span class="fd fd-unresolved"><i class="mk"></i>Unresolved</span><span class="n">{k['unresolved']}</span></li>
      <li><span class="fd fd-rejected"><i class="mk"></i>Rejected former finding</span><span class="n">{k['rejected']}</span></li>
    </ul>
    <p class="aside-note">Papers are chosen deliberately, not sampled at random. These are counts of this programme's work, not error rates.{stats_link}</p>"""
        recent = f"""<div class="sec-head"><h2>Recent case records</h2>
  <a class="more" href="{site.href(page, 'cases/')}">All {plural(k['papers'], 'paper')} and {plural(k['claims'], 'claim')}</a></div>
  <p class="sec-lede">Each paper is listed with every claim that was investigated in it. A paper can contain a claim that
  survived and another that did not, so there is no verdict on the paper as a whole.</p>
  {claim_index(site, page, recs[:4])}"""
    else:
        aside = f"""<p class="aside-k">Case records</p>
    <p class="aside-v">No case records have been released yet.</p>
    <p class="aside-note">Validated Open positives use the standing release rule after the full review; new Confirmed and negative records retain case-specific authorization. <a href="{site.href(page, 'methodology/')}">How this works</a></p>"""
        recent = f"""<div class="sec-head"><h2>Case records</h2></div>
  <p class="sec-lede">No case records have been released yet. Released records will be listed here and on the
  <a href="{site.href(page, 'cases/')}">Cases</a> page, one row per investigated claim, grouped by paper.</p>"""
    steps = "".join(f"<li><span class=\"st-n\">{i}</span><div><strong>{E(a)}</strong><p>{E(b)}</p></div></li>"
                    for i, (a, b) in enumerate(METHOD_STEPS[1:5], start=1))
    body = f"""
<section class="hero"><div class="wrap hero-in">
  <div class="hero-text">
    <h1>{E(cfg['descriptor'])}</h1>
    <p class="tagline">{E(cfg['tagline'])}</p>
    {''.join(f'<p class="hero-p">{E(x)}</p>' for x in cfg['home']['intro'])}
  </div>
  <aside class="hero-aside" aria-label="Current record">
    {aside}
  </aside>
</div></section>
<section class="wrap block">
  {recent}
</section>
<section class="wrap block two">
  <div><h2>Reading a finding</h2><ul class="legend">{legend_html()}</ul></div>
  <div><h2>How a claim is examined</h2><ol class="steps">{steps}</ol>
  <p><a href="{site.href(page, 'methodology/')}">Methodology and the Open and Confirmed statuses</a></p></div>
</section>
"""
    site.add(page, layout(site, page, cfg["name"], body, "", cfg["descriptor"], cls="home"))


def render_explorer(site):
    page = "cases/index.html"
    recs = sorted(site.c.latest_all(), key=lambda r: r["released"], reverse=True)
    k = counts(recs)
    fams = {family(c)[0] for r in recs for c in r["claims"]}
    kinds = sorted({c["kind"] for r in recs for c in r["claims"]}, key=list(CLAIM_KINDS).index)
    tracks = [t for t in TRACKS if any(r["track"] == t for r in recs)]
    o_f = "".join(f'<option value="{f}">{E(lbl)}</option>' for f, lbl, _ in FAMILIES if f in fams)
    o_k = "".join(f'<option value="{x}">{E(CLAIM_KINDS[x])}</option>' for x in kinds)
    o_t = "".join(f'<option value="{t}">{E(TRACK_SHORT[t])}</option>' for t in tracks)
    counted = (f'are counted in the <a href="{site.href(page, "statistics/")}">statistics</a> but not named'
               if page_on(site, "statistics") else "are not named")
    if not recs:
        body = f"""
<div class="wrap page-head">
  <h1>Cases</h1>
  <p class="lede">No case records have been released yet.</p>
  <p class="small muted">Validated Open positives use the standing release rule after the full review; new Confirmed and negative records retain case-specific authorization. Released records will appear here, one row per investigated claim, grouped by paper.
  See the <a href="{site.href(page, 'methodology/')}">methodology</a>.</p>
</div>
"""
        site.add(page, layout(site, page, "Cases", body, "cases/", "Index of investigated claims", cls="cases"))
        return
    body = f"""
<div class="wrap page-head">
  <h1>Cases</h1>
  <p class="lede">Every investigated claim, grouped by paper, most recently updated first. {k['claims']} claims in
  {k['papers']} papers.</p>
  <p class="small muted">Validated Open positives use the standing release rule after the full review; new Confirmed and negative records retain case-specific authorization. Candidates still under review and rejected candidates {counted}.</p>
</div>
<div class="wrap">
<form class="filters" id="filters" hidden>
  <label class="f-search"><span class="sr">Search</span><input type="search" id="f-text" placeholder="Search papers, authors, claims"></label>
  <label><span class="f-l">Finding</span><select id="f-fam"><option value="">All</option>{o_f}</select></label>
  <label><span class="f-l">Status</span><select id="f-status"><option value="">All</option><option value="open">Open</option><option value="confirmed">Confirmed</option><option value="unresolved">Unresolved</option><option value="rejected">Rejected</option></select></label>
  <label><span class="f-l">Claim type</span><select id="f-kind"><option value="">All</option>{o_k}</select></label>
  <label><span class="f-l">Field</span><select id="f-track"><option value="">All</option>{o_t}</select></label>
  <span class="count" id="f-count" aria-live="polite"></span>
</form>
{claim_index(site, page, recs)}
<p class="note">Finding labels are defined in <a href="{site.href(page, 'definitions/')}#findings">Definitions</a>.
Status is Open, Confirmed, Unresolved or a rejected former Open finding, as defined there; each case page states the basis for its status and lists only the checks that took place.
The authors' responses are recorded separately from those checks. {E(SELECTION_STATEMENT)}</p>
</div>
"""
    site.add(page, layout(site, page, "Cases", body, "cases/", "Index of investigated claims", cls="cases"))


def blk(label, html_text, cls=""):
    return f'<div class="blk {cls}"><h3 class="blk-l">{E(label)}</h3><div class="blk-c">{html_text}</div></div>'



def render_claim(site, page, rec, c, i, n):
    view = claim_view(rec, c)
    res = c["result"]
    where = f"{rec['public_id']} {c['id']}"
    fam = family(c)[0]
    meta = [f"Claim {i} of {n}" if n > 1 else "Claim", CLAIM_KINDS[c["kind"]].lower(), ROLES[c["role"]], f"p. {c['page']}"]
    stmt_meta = ""
    if c.get("conditions"):
        stmt_meta += f"<dt>Assumptions</dt><dd>{'; '.join(rich(rec, x, where + ' condition') for x in c['conditions'])}</dd>"
    if c.get("quantifiers"):
        stmt_meta += f"<dt>Scope of the claim</dt><dd>{rich(rec, c['quantifiers'], where + ' quantifiers')}</dd>"
    v = c["vor_check"]
    plural = "pp." if re.search(r"[\u2013,;]", v["pages"]) else "p."
    source = (f'<strong>{E(VOR_LEVELS[v["level"]].split(":")[0])}</strong> source check, {plural} {E(v["pages"])}. '
              f'{rich(rec, v["detail"], where + " source check")}')
    parts = [blk("Source check", f"<p>{source}</p>")]
    _, _, q = family(c)
    qh = f' <span class="fd-q">{E(q)}</span>' if q else ""
    badge = finding_badge(c, qualifier=False) + qh
    if view["status"]:
        badge += " " + status_html(site, page, view["status"])
    finding = f'<p class="verdict">{badge}</p>'
    revision = c.get("publication_revision")
    if revision:
        prior_url = site.href(page, f"cases/{rec['public_id']}/v{revision['from_version']}/")
        prior_status = status_html(site, page, revision["from_status"])
        current_status = status_html(site, page, revision["to_status"])
        finding += (f'<p class="revision-note"><strong>Corrective version.</strong> Current status: {current_status}. '
                    f'This version supersedes the prior {prior_status} finding in '
                    f'<a href="{prior_url}">version {E(revision["from_version"])}</a>. '
                    f'{rich(rec, revision["reason"], where + " correction reason")}</p>')
    elif c.get("status_provenance"):
        provenance = c["status_provenance"]
        current_status = status_html(site, page, provenance["status"])
        prior_url = site.href(page, f"cases/{rec['public_id']}/v{provenance['revision_version']}/")
        finding += (f'<p class="revision-note"><strong>Status carried forward.</strong> Current status: {current_status}. '
                    f'This status was established in <a href="{prior_url}">correction version '
                    f'{E(provenance["revision_version"])}</a> and remains current.</p>')
    elif c.get("unresolved_context"):
        anchor_id = c["unresolved_context"]["anchor_claim_id"]
        finding += (f'<p class="context-note"><strong>Context only.</strong> This unresolved claim does not support or '
                    f'determine the qualifying positive finding <a href="#{E(anchor_id)}">{E(anchor_id)}</a>.</p>')
    basis = basis_text(view)
    if basis:
        finding += f'<p class="basis">{E(basis)}</p>'
    finding += f"<p>{rich(rec, res['summary'], where + ' summary')}</p>"
    parts.append(blk("As Stated finding", finding))
    verdict_note = ""
    if res["outcome"] == "defect_found":
        parts.append(blk("Counterexample", f"<p>{rich(rec, res['witness'], where + ' witness')}</p>"))
        if res.get("argument"):
            parts.append(blk("Why it works", f"<p>{rich(rec, res['argument'], where + ' argument')}</p>"))
        parts.append(blk("What is not claimed", "<ul>" + "".join(
            f"<li>{rich(rec, x, where + ' not claimed')}</li>" for x in res["not_claimed"]) + "</ul>"))
        repair = E(REPAIRS.get(res.get("repair"), ""))
        if res.get("repair_note"):
            repair += ". " + rich(rec, res["repair_note"], where + " repair note")
        parts.append(blk("Repair", f"<p>{repair}</p>"))
        checked = ""
        if res.get("tested"):
            checked += f"<p>{rich(rec, res['tested'], where + ' tested')}</p>"
        checked += evidence_list(rec, view, where)
        if checked:
            parts.append(blk("How it was checked", checked))
    elif view["outcome"] == "rejected":
        parts.append(blk("Refuting review", f"<p>{rich(rec, res['search_scope'], where + ' refuting review')}</p>"))
        parts.append(blk("Limits of this status correction", f"<p>{rich(rec, res['limits'], where + ' limits')}</p>"))
        if view["evidence"]:
            parts.append(blk("How it was checked", evidence_list(rec, view, where)))
    elif res["outcome"] == "no_defect_found":
        verdict_note = f'<p class="caveat">{E(NEGATIVE_CAVEAT)}</p>'
        parts.append(blk("What was tested", f"<p>{rich(rec, res['search_scope'], where + ' search scope')}</p>"))
        parts.append(blk("Limits", f"<p>{rich(rec, res['limits'], where + ' limits')}</p>"))
        if view["evidence"]:
            parts.append(blk("How it was checked", evidence_list(rec, view, where)))
    else:
        if c.get("publication_revision") or c.get("status_provenance"):
            verdict_note = ('<p class="caveat caveat-open">The former Open finding is now Unresolved and is not counted as a defect. '
                            'The prior positive version remains available in the correction history.</p>')
        elif c.get("unresolved_context"):
            verdict_note = ('<p class="caveat caveat-open">This contextual question is not settled and is not counted as a defect. '
                            'It does not establish or support the record’s qualifying positive finding.</p>')
        else:
            verdict_note = '<p class="caveat caveat-open">This question is not settled. It is not counted as a defect.</p>'
        parts.append(blk("What is known", f"<p>{rich(rec, res['detail'], where + ' detail')}</p>"))
        parts.append(blk("Why unresolved", f"<p>{rich(rec, res['limits'], where + ' limits')}</p>"))
    rep = c.get("reproduction") or {}
    if rep:
        parts.append(blk("Evidence rerun", f"<p>{E(rep.get('result', '').capitalize())}. {E(rep.get('detail', ''))}</p>"))
    if c.get("novelty"):
        parts.append(blk("Earlier reports", f"<p>{rich(rec, c['novelty'], where + ' novelty')}</p>"))
    parts.append(blk("Author response", author_html(rec, view, where)))
    meta_dl = f'<dl class="stmt-meta">{stmt_meta}</dl>' if stmt_meta else ""
    stmt = (f'<figure class="stmt"><blockquote><p><span class="stmt-l">{E(c["label"])}.</span> '
            f'<span class="stmt-t">{rich(rec, c["statement"], where + " statement")}</span></p></blockquote>'
            f'{meta_dl}</figure>')
    return f"""
<section class="claim fam-{fam}" id="{E(c['id'])}">
  <header class="claim-head">
    <p class="claim-meta">{' · '.join(E(x) for x in meta)}</p>
    <h2>{E(c['label'])}</h2>
  </header>
  {stmt}
  {verdict_note}
  <div class="blks">{''.join(parts)}</div>
</section>"""


def latest_correction_descendant(versions, source_version, claim_id):
    by_version = {record["version"]: record for record in versions}
    latest_record = versions[-1]
    latest_claim = next((item for item in latest_record["claims"] if item["id"] == claim_id), None)

    def reaches_source(record):
        cursor = next((item for item in record["claims"] if item["id"] == claim_id), None)
        seen = set()
        while cursor:
            revision = cursor.get("publication_revision")
            provenance = cursor.get("status_provenance")
            if provenance:
                prior_version = provenance["revision_version"]
            elif revision:
                prior_version = revision["from_version"]
            else:
                return False
            if prior_version == source_version:
                return True
            if prior_version in seen:
                return False
            seen.add(prior_version)
            prior = by_version.get(prior_version)
            cursor = next((item for item in prior["claims"] if item["id"] == claim_id), None) if prior else None
        return False

    if latest_claim and any(reaches_source(record) for record in versions if record["version"] != source_version):
        return latest_claim
    return None


def render_record(site, rec, frozen=False):
    rid, ver = rec["public_id"], rec["version"]
    page = f"cases/{rid}/v{ver}/index.html" if frozen else f"cases/{rid}/index.html"
    cfg = site.cfg
    current = site.c.records[rid][-1]
    w = rec["work"]
    digest = next(d for k, i, v, d in site.c.verified if k == "record" and i == rid and v == ver)
    claims = rec["claims"]
    n = len(claims)
    corr = rec.get("correction")
    views = [claim_view(rec, c) for c in claims]
    overview = ""
    if n > 1:
        rows = "".join(
            f'<tr><td class="ov-n">{i}</td><td><a href="#{E(c["id"])}">{E(c["label"])}</a>'
            f'<span class="ov-kind">{E(CLAIM_KINDS[c["kind"]])} · {E(ROLES[c["role"]])}</span></td>'
            f'<td>{finding_badge(c)}</td><td class="ov-ver">{status_cell(site, page, rec, c)}</td></tr>'
            for i, c in enumerate(claims, start=1))
        overview = (f'<section class="overview" aria-label="Claims in this paper"><h2 class="ov-h">{n} claims investigated in this paper</h2>'
                    f'<table class="ov"><tbody>{rows}</tbody></table></section>')
    resp = []
    if corr:
        state = corr.get("state", "formal_correction_published")
        if state == "announced":
            ctext = (f"<strong>Announced.</strong> {E(fmt_date(corr['date']))}. {E(corr['note'])} "
                     "No public correction is represented here as completed or independently verified.")
        elif state == "author_supplied":
            ctext = (f"<strong>Author-supplied correction.</strong> {E(fmt_date(corr['date']))}. {E(corr['note'])} "
                     "This records material supplied privately by the authors; it is not presented as a public journal or arXiv correction.")
        elif state == "public_revision_verified":
            link = f" ({doi_html(site, corr['doi'])})" if corr.get("doi") else ""
            ctext = (f"<strong>Public revision verified.</strong> {E(fmt_date(corr['date']))}.{link} {E(corr['note'])}")
        elif corr["relation"] == "before_audit":
            link = f" ({doi_html(site, corr['doi'])})" if corr.get("doi") else ""
            ctext = (f"{E(corr['type'].capitalize())} published in {E(fmt_month(corr['date']))}, before this audit{link}. "
                     "Not an outcome of this audit.")
        else:
            link = f" ({doi_html(site, corr['doi'])})" if corr.get("doi") else ""
            attrib = ("It credits this audit." if corr["attribution"] == "credits_programme" else
                      "It does not mention this audit; we do not claim it resulted from our work.")
            ctext = (f"{E(corr['type'].capitalize())} published {E(fmt_date(corr['date']))}, after the authors were contacted"
                     f"{link}. {E(attrib)} {E(corr['note'])}")
        resp.append(f"<dt>Correction</dt><dd>{ctext}</dd>")
    else:
        resp.append("<dt>Correction</dt><dd>None recorded.</dd>")
    for item in rec.get("related", []):
        link = doi_html(site, item["doi"]) if item.get("doi") else ""
        note = f" {E(item['note'])}" if item.get("note") else ""
        resp.append(f"<dt>Related work</dt><dd>{E(item['citation'])} {link}.{note}</dd>")
    for ch in rec.get("challenges", []):
        resp.append(f"<dt>{E(ch['type'].capitalize())}</dt><dd>{E(fmt_date(ch['date']))}, by {E(ch['by'])}. {E(ch['outcome'])}.</dd>")
    hist = "".join(f'<li><span class="h-d">{E(fmt_date(x["date"]))}</span><span class="h-t">{E(x["label"])}</span></li>'
                   for x in sorted(rec["history"], key=lambda x: x["date"]))
    vers = "".join(
        f'<li><a href="{site.href(page, "cases/" + rid + "/v" + ch["version"] + "/")}">Version {E(ch["version"])}</a>'
        f'<span class="h-d">{E(fmt_date(ch["date"]))}</span><span class="h-t">{E(ch["change"])}'
        f'{" <strong>Our correction.</strong>" if ch.get("our_correction") else ""}</span></li>'
        for ch in rec["changelog"])
    files = "".join(f'<li class="mono">{E(f["name"])}</li>' for f in rec["evidence"]["files"])
    technical_notes = []
    note_entries = rec.get("technical_notes", [])
    for note in note_entries:
        pdf_url = site.href(page, note["path"])
        note_meta = fmt_date(note["date"])
        if note.get("pages"):
            note_meta += f" · {note['pages']} pages"
        if len(note_entries) > 1:
            note_meta += f" · Version {E(note['version'])}"
        technical_notes.append(f'''<article class="technical-note">
  <p class="technical-note-meta">{E(note_meta)}</p>
  <p><a class="pdf-link" href="{E(pdf_url)}">Read technical note (PDF)</a></p>
</article>''')
    technical_note_section = (f'<section class="after technical-notes" id="technical-notes"><h2>As Stated technical note</h2>'
                              f'{"".join(technical_notes)}</section>' if technical_notes else "")
    evidence_package = doi_html(site, rec["evidence"]["package_doi"]) if rec["evidence"].get("package_doi") else ""
    outreach_status = (rec.get("outreach") or {}).get("status")
    outreach_text = OUTREACH_STATES.get(outreach_status)
    outreach_section = (f'<section class="after" id="outreach"><h2>Author outreach</h2><p>{E(outreach_text)}. '
                        'This records contact lifecycle only; it does not determine the finding status.</p></section>'
                        if outreach_text else "")
    url = cfg["base_url"].rstrip("/") + f"/cases/{rid}/v{ver}/"
    cite = f"{cfg['owner']} ({rec['released'][:4]}). Case record {rid}, version {ver}: {rec['title']}. {cfg['name']}. {url}"
    bib = (f"@misc{{{rid.replace('-', '_')}_v{ver.replace('.', '_')},\n  author = {{{cfg['owner']}}},\n"
           f"  title = {{Case record {rid}, version {ver}: {rec['title']}}},\n  howpublished = {{{cfg['name']}}},\n"
           f"  year = {{{rec['released'][:4]}}},\n  url = {{{url}}}\n}}")
    notes = ""
    if frozen and ver != current["version"]:
        changed = []
        versions = site.c.records[rid]
        for old_claim in rec["claims"]:
            newest = latest_correction_descendant(versions, ver, old_claim["id"])
            if newest is not None:
                view = claim_view(current, newest)
                target = site.href(page, f"cases/{rid}/#{newest['id']}")
                changed.append(f'<li>Current status for claim <a href="{target}">{E(newest["id"])}</a>: '
                               f'{status_html(site, page, view["status"])}.</li>')
        status_note = f'<ul>{"".join(changed)}</ul>' if changed else ""
        notes += (f'<p class="notice">Archived version {E(ver)}. The current version is '
                  f'<a href="{site.href(page, "cases/" + rid + "/")}">{E(current["version"])}</a>.</p>{status_note}')
    fams = [family(c)[0] for c in claims]
    open_n = sum(1 for v in views if v["status"] == "open")
    conf_n = sum(1 for v in views if v["status"] == "confirmed")
    unresolved_n = sum(1 for v in views if v["outcome"] == "unresolved")
    rejected_n = sum(1 for v in views if v["outcome"] == "rejected")
    status_fact = " · ".join(x for x in [f"{open_n} Open" if open_n else "", f"{conf_n} Confirmed" if conf_n else "",
                                         f"{unresolved_n} Unresolved" if unresolved_n else "",
                                         f"{rejected_n} Rejected" if rejected_n else ""] if x)
    body = f"""
<div class="wrap case">
<nav class="crumbs" aria-label="Breadcrumb"><a href="{site.href(page, 'cases/')}">Cases</a><span aria-hidden="true">/</span><span>{E(rid)}</span></nav>
{notes}
<header class="case-head">
  <p class="eyebrow">Case record · {E(TRACKS[rec['track']])}</p>
  <h1>{E(w['title'])}</h1>
<p class="byline"><span class="source-kind">Original published paper</span><br>{E(author_list(w['authors']))} · {venue_line(w)} · {doi_html(site, w['doi'])}</p>
  <p class="lede">{rich(rec, rec['headline'], rid + ' headline')}</p>
  <ul class="case-facts">
    <li><span class="cf-k">Findings</span>{''.join(f'<i class="mk-dot fd-{f}" title="{E(FAMILY_LABEL[f])}"></i>' for f in fams)}<span class="cf-v">{n} claim{"s" if n != 1 else ""}</span></li>
    {f'<li><span class="cf-k">Status</span><span class="cf-v">{E(status_fact)}</span></li>' if status_fact else ''}
    <li><span class="cf-k">Updated</span><span class="cf-v">{E(fmt_date(rec['released']))} · version {E(ver)}</span></li>
  </ul>
</header>
<div class="case-grid">
<article class="case-main">
  {overview}
  {''.join(render_claim(site, page, rec, c, i, n) for i, c in enumerate(claims, start=1))}
  {technical_note_section}
  {outreach_section}
  <section class="after" id="corrections"><h2>Corrections and related record details</h2><dl class="rd">{''.join(resp)}</dl></section>
  <section class="after" id="history"><h2>History</h2><ol class="hist">{hist}</ol></section>
  <section class="after" id="versions"><h2>Versions</h2><ol class="hist">{vers}</ol>
  <p class="note">Released versions are never edited; each keeps its own address.</p></section>
  <section class="after" id="ai-use"><h2>Use of AI in this case</h2><p>{E(rec['statements']['ai_use'])}</p></section>
</article>
<aside class="case-aside" aria-label="Record details">
  <dl class="side">
    <dt>Record</dt><dd><span class="mono">{E(rid)}</span>, version {E(ver)}<br>released {E(fmt_date(rec['released']))}</dd>
    <dt>Evidence package</dt><dd>{evidence_package}{"<br>" if evidence_package else ""}
      <span class="small muted">{E(rec['evidence']['licence'])}</span>{f'<ul class="files">{files}</ul>' if files else ''}</dd>
    <dt id="verification">Release verification</dt><dd class="small">Release manifest. Record file SHA-256
      <span class="mono hash" title="{E(digest)}">{E(digest[:16])}…</span> verified when the site was built.
      The applicable publication authorization and release checks are recorded for each version. Automated tests and a privacy scan must pass before deployment.
      <a href="{site.href(page, f'data/records/{rid}/v{ver}.json')}">JSON</a> · <a href="{site.href(page, 'methodology/')}#release">How</a></dd>
    <dt>Cite this record</dt><dd><p class="cite" id="cite-text">{E(cite)}</p>
      <button class="btn" type="button" data-copy="cite-text">Copy citation</button>
      <details><summary>BibTeX</summary><pre class="bibtex" id="bibtex">{E(bib)}</pre>
      <button class="btn" type="button" data-copy="bibtex">Copy BibTeX</button></details></dd>
  </dl>
</aside>
</div>
</div>
"""
    site.add(page, layout(site, page, f"{w['title']} ({rid})", body, "cases/", rec["headline"], cls="record"))


METRIC_ROWS = [
    ("M01", "Papers considered", "paper", "Papers in the programme with any screening, including metadata-only screening.", "monthly"),
    ("M02", "Papers investigated at theorem level", "paper", "Papers with at least one claim checked against a source text or deeply audited.", "monthly"),
    ("M03", "Claims investigated", "claim", "Claims checked against a source text or deeply audited.", "monthly"),
    ("M04", "Claims deeply audited", "claim", "Claims that received a deep audit.", "monthly"),
    ("M05", "Candidate defects raised", "claim", "Claims for which any check ever reported a possible defect. Never decreases.", "monthly"),
    ("M06", "Status of candidate defects", "claim", "M05 split into open, confirmed, unresolved and rejected.", "monthly"),
    ("M07", "Deep audits that found no defect", "claim", "Deeply audited claims with no candidate defect ever raised, by source check.", "monthly"),
    ("M08", "Confirmed: rechecked by a separate AI session", "claim", "Confirmed claims with a confirming AI recheck in a separate session.", "monthly"),
    ("M09", "Confirmed: reproduced by the researcher", "claim", "Re-derived by hand or with separately written code. Package reruns do not count.", "monthly"),
    ("M10", "Confirmed: checked by an external human", "claim", "Checked by someone outside the programme.", "monthly"),
    ("M11", "Confirmed: source check", "claim", "Confirmed claims by full, partial or no check against the published version.", "monthly"),
    ("M12", "Papers with evidenced author contact", "paper", "Schema 3 uses explicit outreach state; legacy records use only supported contact evidence under their recorded metric version. Silence alone is not contact evidence.", "quarterly"),
    ("M13", "Authors' position on confirmed findings", "claim", "Confirmed claims in papers whose authors were contacted, by the authors' latest written position.", "quarterly"),
    ("M14", "Corrections published after author contact", "claim", "Released records only; credited to this audit only if the correction says so.", "monthly"),
    ("M15", "Records released", "record", "Records with status published.", "monthly"),
    ("M16", "Our corrections and withdrawals", "record version", "Released versions that correct our error or withdraw a record.", "monthly"),
    ("M17", "Calibration checks", "claim", "Claims whose error was already corrected in print before the audit, used to test the method.", "monthly"),
]


def render_definitions(site):
    page = "definitions/index.html"
    fams = "".join(f'<div class="def"><dt><span class="fd fd-{k}"><i class="mk" aria-hidden="true"></i>{E(lbl)}</span></dt>'
                   f'<dd>{E(d)}</dd></div>' for k, lbl, d in FAMILIES)
    quals = ("<li><strong>repairable gap</strong>: a short argument or condition closes the gap in the cases checked.</li>"
             "<li><strong>unsupported citation</strong>: the proof relies on a cited result that does not cover the case.</li>"
             "<li><strong>previously reported</strong>: the error was already corrected or reported in print before the audit.</li>"
             "<li><strong>source not available</strong>: the version of the source needed to settle the question could not be obtained.</li>")
    metrics = "".join(f'<tr id="m-{i.lower()}"><td class="mono">{i}</td><td>{E(lbl)}</td><td>{E(u)}</td><td>{E(d)}</td><td>{E(c)}</td></tr>'
                      for i, lbl, u, d, c in METRIC_ROWS)
    vor = "".join(f"<li>{E(v)}</li>" for v in VOR_LEVELS.values())
    kinds = [
        ("hostile_ai_recheck", "An AI model in a new session tries to refute the candidate. Never counted as a human check."),
        ("researcher_reproduction", "Re-derived by hand or with separately written code."),
        ("external_check", "Checked by someone outside the programme, named or anonymous."),
        ("author_agreement", "An author agrees in writing that the identified issue is correct. Under the confirmation standard this is a "
                             "human kind of support, but it is the authors' own statement about their paper, not an independent check. "
                             "It is shown as the author response and counts toward Confirmed only when the original written reply is on file."),
        ("private_human_confirmation", "A human confirmation recorded in the private research file, without disclosing its source."),
    ]
    kind_list = "".join(f'<div class="def"><dt>{E(SUPPORT_KINDS[k])}</dt><dd>{E(d)}</dd></div>' for k, d in kinds)
    body = f"""
<div class="wrap page-head"><h1>Definitions</h1>
<p class="lede">The vocabulary used in every record and statistic. Metric definitions version {E(site.cfg['metrics_version'])}.</p></div>
<div class="wrap reading">
<nav class="toc" aria-label="On this page"><a href="#findings">Findings</a><a href="#open-and-confirmed">Open and Confirmed</a><a href="#statuses">Statuses</a><a href="#checks">Checks</a>
<a href="#vor">Source check</a><a href="#authors">Author responses</a><a href="#corrections">Corrections</a><a href="#metrics">Metrics</a></nav>
<div class="prose">
<section id="findings"><h2>Findings</h2><p>Each investigated claim has one finding or a status correction to a previously public Open finding. A paper with several claims can have
several different findings; there is no verdict on a paper as a whole.</p><dl class="defs">{fams}</dl>
<p>A short qualifier sometimes follows the label:</p><ul>{quals}</ul>
<p>Records also say which result a defect affects and what the finding does <em>not</em> establish.</p></section>
<section id="open-and-confirmed"><h2>Open and Confirmed</h2>
<dl class="defs">
<div class="def"><dt id="open">Open</dt><dd>A published positive finding that has not received the optional, stronger Confirmed label. Open does not mean that the mathematical question is unresolved or that an author response is pending. Outreach is recorded separately. Each case page states the basis on which its finding was published.</dd></div>
<div class="def"><dt id="confirmed">Confirmed</dt><dd>An optional, stronger evidentiary label. It additionally requires at least two different kinds of check, at least one of them by a human, and no refuting check left unaddressed. It is not required for publication.</dd></div>
</dl></section>
<section id="statuses"><h2>Other statuses</h2><dl class="defs">
<div class="def"><dt id="candidate">Candidate</dt><dd>Any possible defect reported by any check. Most candidates come from AI-assisted discovery runs and are never published by name.</dd></div>
<div class="def"><dt id="unresolved">Unresolved</dt><dd>Checks could not settle the question. It is not counted as a defect. In a new record, unresolved material may appear only as clearly labelled context beside a qualifying positive finding about the same paper that independently meets the release standard. It cannot determine or support that finding, and it cannot be the record's principal proposition. A previously public Open finding may also be corrected to Unresolved, with the prior version preserved and linked.</dd></div>
<div class="def"><dt>Rejected</dt><dd>A refuting check showed that a previously public Open finding does not stand. It remains visible as a status correction, not as a new negative audit.</dd></div>
<div class="def"><dt id="withdrawn">Withdrawn</dt><dd>A released record we no longer stand behind. The page stays online with the reason.</dd></div></dl></section>
<section id="checks"><h2>Kinds of check</h2><p>A case page lists only the checks that actually took place. The kinds are:</p>
<dl class="defs">{kind_list}</dl><p>Rerunning the original evidence package shows the package works; it is reported separately and is not counted as a check.</p></section>
<section id="vor"><h2>Source check</h2><p>The decisive elements are the statement, every definition and assumption the finding relies on, the decisive step, and any supplement the claim depends on.</p><ul>{vor}</ul></section>
<section id="authors"><h2>Author responses and outreach</h2><p>Scientific status and outreach are independent. Open never means that a response is pending. When supported by the record, outreach may state that authors have not been contacted, are awaiting a substantive response, or have provided one. A factual author position may also be shown. These public facts never include private correspondence or attachments. Whether an author's written agreement counts toward Confirmed is recorded separately. Contact and reply are not publication requirements.</p></section>
<section id="corrections"><h2>Corrections</h2><p>Finding status, author correction status and our public status corrections are separate. Announced and author-supplied corrections are not presented as completed public corrections. A correction is described as crediting this audit only if its own text says so. When new evidence changes a previously public Open finding's status or material scope, a new immutable version states the current status and links the superseded version; the earlier version stays addressable. This standing correction rule does not authorize a new standalone unresolved finding. A correction published before the audit marks the finding as previously reported; it is not an outcome of this audit.</p></section>
</div></div>
<div class="wrap"><section id="metrics" class="block"><h2>Metrics</h2><div class="table-wrap"><table class="data rtable metrics"><thead><tr><th scope=col>ID</th><th scope=col>Label</th><th scope=col>Unit</th><th scope=col>Counting rule</th><th scope=col>Updated</th></tr></thead><tbody>{metrics}</tbody></table></div>
<p class="note">A ratio is shown only when its numerator is a subset of its denominator, as counts ("6 of 11"). No ratio uses papers or claims examined as its denominator. {E(SELECTION_STATEMENT)}</p></section></div>
"""
    site.add(page, layout(site, page, "Definitions", body, "definitions/", indexable=True, cls="definitions"))


def render_methodology(site):
    page = "methodology/index.html"
    keys_line = "Real releases use exact SHA-256 manifests."
    steps = "".join(f"<li><strong>{E(a)}.</strong> {E(b)}</li>" for a, b in METHOD_STEPS)
    toc = [("question", "The question"), ("process", "Process"), ("standard", "Open and Confirmed"),
           ("findings", "Findings"), ("verification", "Checks and evidence"), ("negative", "Negative audits"),
           ("source", "Source check"), ("authors", "Author responses"), ("ai", "How AI is used"),
           ("responses", "Author responses: policy"), ("corrections", "Corrections and withdrawals"),
           ("challenges", "Challenges and replications"), ("selection", "Selection and statistics"),
           ("release", "How releases are approved"), ("not", "What we do not do"), ("changes", "Changes")]
    body = f"""
<div class="wrap page-head"><p class="eyebrow">Methodology version {E(site.cfg['methodology_version'])}</p><h1>Methodology</h1>
<p class="lede">How a published claim becomes a case record, and what each part of a record means.</p></div>
<div class="wrap reading">
<nav class="toc" aria-label="On this page">{''.join(f'<a href="#{a}">{E(b)}</a>' for a, b in toc)}</nav>
<div class="prose">
<section id="question"><h2>The question</h2><p>Does a published theoretical claim follow from the assumptions stated with it?
The claim may be a theorem, proposition, lemma, corollary, remark, algorithm, construction or application, in game
theory, mechanism design, matching and social choice, or related fields. The unit of investigation is the single claim,
read exactly as stated. A paper is not given a verdict as a whole.</p></section>
<section id="process"><h2>Process</h2><ol class="proc">{steps}</ol></section>
<section id="standard"><h2>Open and Confirmed</h2><p class="callout">A positive finding is published as <strong>Open</strong> when it has survived a separate-session hostile AI recheck and a
source review of the published version. <strong>Confirmed</strong> is an optional, stronger evidentiary label: it also
requires at least two different kinds of check, at least one of them by a human, and no refuting check left unaddressed.</p>
<p>Human checking is not a condition of initial Open publication, and no publication waits for an author's reply. Open is not a
judgement that the mathematics is unsettled; a question that could not be settled is <em>Unresolved</em>, a separate status. An Open finding may later receive a corrective version that reports an unresolved or rejected status.</p></section>
<section id="findings"><h2>Findings</h2><p>Each investigated claim has one finding, or a status correction to a previously public Open finding.</p>
<ul class="legend">{legend_html()}</ul></section>
<section id="verification"><h2>Checks and evidence</h2><p>Each case page lists the checks that actually took place, and nothing
else. A check can be a separate-session hostile AI recheck, a reproduction by the researcher, an external check, a
human confirmation recorded privately, or an author's written agreement. Each record also states how far the finding was checked
against the published version of the paper.</p></section>
<section id="negative"><h2>Negative audits</h2><p>{E(NEGATIVE_CAVEAT_GENERAL)} Each negative audit states what was
tested and its limits. Only deep audits are published by name; lighter screens appear only in counts.</p></section>
<section id="source"><h2>Source check</h2><p>Findings are checked against the version of record. Each claim states whether every
decisive element was checked on rendered pages of the published version (full), only partly (partial), or whether the
needed version could not be obtained. A question that depends on an unobtainable version is reported as unresolved, not as
a defect. In a new record it may appear only as clearly labelled context beside a qualifying positive finding about the same paper; it cannot support that finding or be the record's principal proposition. A corrective version of a previously public Open finding may report its new unresolved status directly.</p></section>
<section id="authors"><h2>Author responses and outreach</h2><p>Scientific status and outreach are independent. Open never means that a response is pending. Where the public record supports it, outreach may be stated as not contacted, awaiting a substantive response, or substantive response received. A factual author position is separate. The page does not publish private correspondence or attachments. Whether a written agreement counts toward Confirmed is recorded separately. Author contact is not a publication requirement.</p></section>
<section id="ai"><h2>How AI is used</h2><p>AI models search for counterexamples, check candidate findings in separate sessions
and help write test code. They do not decide what is published. Each finding is checked against the published version, and the
researcher makes every editorial decision. Human checks are recorded when they happen; they are optional, not a condition of
publication. Each record states how AI was used in that case.</p></section>
<section id="responses"><h2>Author responses: policy</h2><ul>
<li>Author contact is optional and is not required before or after publication. Open is not an outreach state.</li>
<li>If a substantive written response already exists, it is considered in the record and may motivate further checking.</li>
<li>An author's disagreement is evidence to assess, not a veto over publication.</li>
<li>A reply is published only as the authors' own public statement, wording they separately approve for public use, or a link to their public statement.</li>
<li>Private correspondence is never quoted or summarized publicly without separate consent.</li></ul>
<p>When public author-response information exists, it is recorded in the history of the case it concerns.</p></section>
<section id="corrections"><h2>Corrections and withdrawals</h2><ul>
<li>Released versions are never edited. Every change is a new version with a dated change note; earlier versions stay online.</li>
<li>Our own errors are labelled as our corrections. If a finding changes, older versions point to the current one.</li>
<li>A finding we no longer stand behind is withdrawn: the record stays online with the reason.</li>
<li>A published correction by the authors or journal is added to the record, and described as crediting this audit only if it says so.</li>
<li>Material published by mistake is removed, and a short notice records the removal without repeating the content.</li></ul></section>
<section id="challenges"><h2>Challenges and replications</h2><p>Anyone may challenge or replicate a published record.
Substantive challenges are checked and their outcome is added to the record; replications are credited by name with
consent. Allegations about papers not on this site should not be sent through public channels.</p></section>
<section id="selection"><h2>Selection and statistics</h2><p>{E(SELECTION_STATEMENT)} Statistics are counts with stated
units; small counts that could identify an unpublished case are suppressed.</p></section>
<section id="release"><h2>How releases are approved</h2><p>Every real record version has a release manifest containing the
SHA-256 of its exact public data file. The site build refuses a missing or mismatched manifest. Public versions are
immutable: corrections use a new version. A validated positive finding with status Open is released by default after its case-specific scientific, source, evidence, scope, correction, novelty, rights, privacy and presentation checks pass. Author contact is not a gate. An active owner hold blocks an initial Open release. A previously public Open finding may receive a corrective or superseding version without a new per-case publish instruction when new evidence changes its status or material scope. A new Confirmed positive or named negative record retains its case-specific publish authorization. Automated tests, history checks and a privacy scan must pass before deployment.</p>
<p class="small muted">{keys_line}</p></section>
<section id="not"><h2>What we do not do</h2><ul><li>Publish anonymous or unchecked allegations.</li>
<li>Rank journals, fields or authors.</li><li>Report error rates for published research.</li>
<li>Name a paper solely because a new candidate was rejected or remains unresolved. A correction to a previously public Open finding remains visible as a status update.</li></ul></section>
<section id="changes"><h2>Changes</h2><p class="small">Version 2.1, 23 November 2026. Added the standing release rule for validated Open positives, the narrow same-paper unresolved-context rule, and the corrective-version path for previously public Open findings. Outreach is stated separately from scientific status. Historical releases remain immutable. Earlier versions of this page said that only confirmed defects are published, and that every published defect had been checked by a human. Those statements are withdrawn: neither is a requirement of publication.</p></section>
</div></div>
"""
    site.add(page, layout(site, page, "Methodology", body, "methodology/", indexable=True, cls="methodology"))


def activity_svg(activity):
    kinds = [("discovery", "Discovery runs", "a1"), ("hostile_validation", "Separate rechecks", "a2"),
             ("source_lock", "Source checks", "a3"), ("package_rerun", "Package reruns", "a4")]
    w, h, pl, pb, pt = 560, 170, 28, 22, 8
    n = len(activity)
    mx = max(sum(m[k] for k, _, _ in kinds) for m in activity) or 1
    step = (w - pl - 6) / n
    bw = step * 0.5
    ph = h - pb - pt
    els = []
    for tick in range(0, mx + 1, max(1, mx // 3)):
        y = pt + ph - ph * tick / mx
        els.append(f'<line x1="{pl}" x2="{w - 4}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{pl - 5}" y="{y + 4:.1f}" class="axis" text-anchor="end">{tick}</text>')
    for i, m in enumerate(activity):
        x = pl + step * i + (step - bw) / 2
        y = pt + ph
        for k, _, cls in kinds:
            hh = ph * m[k] / mx
            y -= hh
            els.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(hh - 1, 0):.1f}" class="{cls}"/>')
        els.append(f'<text x="{x + bw / 2:.1f}" y="{h - 6}" class="axis" text-anchor="middle">{MONTH_NAMES[int(m["month"][5:]) - 1][:3]}</text>')
    legend = "".join(f'<li><span class="sw {cls}"></span>{E(lbl)}</li>' for _, lbl, cls in kinds)
    rows = "".join(f"<tr><th scope=row>{E(fmt_date(m['month']))}</th>" + "".join(f'<td class="num">{m[k]}</td>' for k, _, _ in kinds) + "</tr>"
                   for m in activity)
    head = "".join(f'<th scope=col class="num">{E(lbl)}</th>' for _, lbl, _ in kinds)
    return (f'<figure class="chart"><svg viewBox="0 0 {w} {h}" role="img" aria-label="Research activity by month">{"".join(els)}</svg>'
            f'<ul class="chart-legend">{legend}</ul><details><summary>Data</summary><div class="table-wrap"><table class="data">'
            f'<thead><tr><th scope=col>Month</th>{head}</tr></thead><tbody>{rows}</tbody></table></div></details></figure>')


def render_statistics(site):
    snaps = sorted(site.c.snapshots, key=lambda s: s["as_of"])
    for i, snap in enumerate(snaps):
        latest = i == len(snaps) - 1
        page = "statistics/index.html" if latest else f"statistics/{snap['snapshot']}/index.html"
        t = snap["totals"]
        rs = released_stats(site.c, snap["as_of"], include_legacy_no_reply=snap["metrics_version"] == "1.1")
        m06 = t["M06"]
        conf = m06["confirmed"]
        m07 = sum(t["M07"].values())
        m13 = t["M13"]
        pop13 = sum(m13.values())
        corr = sum(rs["corrections"].values())
        d = site.href(page, "definitions/")

        def row(mid, label, value, detail=""):
            return (f'<tr><td class="mid"><a href="{d}#m-{mid.lower()}">{mid}</a></td><td>{E(label)}'
                    f'{f"<span class=\"m-d\">{detail}</span>" if detail else ""}</td><td class="num">{value}</td></tr>')

        def table(title, rows_html):
            return f'<section class="mgroup"><h2>{E(title)}</h2><table class="mt"><tbody>{rows_html}</tbody></table></section>'
        examined = "".join([
            row("M01", "Papers considered", t["M01"], "includes metadata-only screening"),
            row("M02", "Papers investigated at theorem level", t["M02"]),
            row("M03", "Claims investigated", t["M03"]),
            row("M04", "Claims deeply audited", t["M04"])])
        found = "".join([
            row("M05", "Candidate defects raised", t["M05"], "cumulative"),
            row("M06", "Confirmed", conf, f"of {t['M05']}; {m06['confirmed_previously_reported']} previously reported elsewhere"),
            row("M06", "Open", m06["open"], f"of {t['M05']}; {m06['open_ai_supported']} supported by AI only; not yet Confirmed"),
            row("M06", "Unresolved", m06["unresolved"], f"of {t['M05']}; " + E(", ".join(f"{v} {k.replace('_', ' ')}" for k, v in snap['unresolved_reasons'].items()))),
            row("M06", "Rejected after checking", m06["rejected"], f"of {t['M05']}"),
            row("M07", "Deep audits that found no defect", m07,
                f"source check: {t['M07']['vor_full']} full, {t['M07']['vor_partial']} partial, {t['M07']['vor_none']} not obtained")])
        survived = "".join([
            row("M08", "Rechecked by a separate AI session", f"{sum(t['M08'].values())} of {conf}", f"{t['M08']['blind']} blind, {t['M08']['informed']} informed; not a human check"),
            row("M09", "Reproduced by the researcher", f"{t['M09']} of {conf}"),
            row("M10", "Checked by an external human", f"{t['M10']} of {conf}"),
            row("M11", "Source check full / partial / none", f"{t['M11']['full']} / {t['M11']['partial']} / {t['M11']['none']}", f"of {conf}")])
        after = "".join([
            row("M12", "Papers whose authors were contacted", t["M12"], f"as of {E(fmt_date(snap['as_of']))}"),
            row("M13", "Authors agreed", f"{m13['agreed']} of {pop13}", "confirmed defects in papers whose authors were contacted"),
            row("M13", "Authors partly agreed", f"{m13['partly_agreed']} of {pop13}"),
            row("M13", "Authors disagree", f"{m13['disagreed']} of {pop13}"),
            row("M13", "No reply recorded", f"{m13['none_yet']} of {pop13}"),
            row("M14", "Corrections after author contact", corr,
                f"{rs['corrections']['credits_programme']} credit this audit, {rs['corrections']['none_stated']} state no attribution")])
        publ = "".join([
            row("M15", "Records released", len(site.c.latest_all(snap["as_of"]))),
            row("M16", "Our corrections and withdrawals", rs["our_corrections"]),
            row("M17", "Calibration claims", t["M17"]["checked"], f"{t['M17']['known_errors_refound']} known errors re-found")])
        ebt = snap.get("examined_by_track", {})
        cell = lambda m, k: "–" if ebt.get(m, {}).get(k) is None else ebt[m][k]
        trk = "".join(
            f"<tr><th scope=row>{E(TRACK_SHORT[k])}</th>"
            f"<td class=num data-label=\"Papers considered\">{cell('M01', k)}</td>"
            f"<td class=num data-label=\"Claims investigated\">{cell('M03', k)}</td>"
            f"<td class=num data-label=\"Defects confirmed*\">{rs['outcome_by_track'][k]['confirmed']}</td>"
            f"<td class=num data-label=\"No defect found*\">{rs['outcome_by_track'][k]['negative']}</td></tr>"
            for k in TRACKS)
        archive = " · ".join(
            f'<a href="{site.href(page, "statistics/" + ("" if j == len(snaps) - 1 else s["snapshot"] + "/"))}">{E(s["snapshot"])}</a>'
            for j, s in enumerate(snaps))
        notes = ""
        if not latest:
            notes += f'<p class="notice">Archived snapshot. <a href="{site.href(page, "statistics/")}">Latest</a>.</p>'
        body = f"""
<div class="wrap">{notes}</div>
<div class="wrap page-head"><p class="eyebrow">Snapshot {E(snap['snapshot'])} · as of {E(fmt_date(snap['as_of']))}</p><h1>Statistics</h1>
<p class="lede">Counts of this programme's work: what was examined, what was found, what survived challenge and what
happened afterwards.</p>
<p class="callout">{E(SELECTION_STATEMENT)} {E(snap['programme']['description'])}</p>
<p class="small muted">Released {E(fmt_date(snap['released']))}; metric definitions v{E(snap['metrics_version'])}.
Snapshots: {archive} · <a href="{site.href(page, f"data/snapshots/{snap['snapshot']}.json")}">JSON</a></p></div>
<div class="wrap mgrid">
{table("What was examined", examined)}{table("What was found", found)}
{table("What survived challenge", survived)}{table("What happened afterwards", after)}
{table("Publication and self-correction", publ)}
<section class="mgroup"><h2>By field</h2><div class="table-wrap"><table class="data rtable ftable"><thead><tr><th scope=col>Field</th>
<th scope=col class=num>Papers considered</th><th scope=col class=num>Claims investigated</th>
<th scope=col class=num>Defects confirmed*</th><th scope=col class=num>No defect found*</th></tr></thead>
<tbody>{trk}</tbody></table></div>
<p class="note">"–" marks a suppressed count. Columns marked * use released records only.</p></section>
<section class="mgroup wide"><h2>Activity by month</h2>{activity_svg(snap['activity'])}</section>
</div>
"""
        site.add(page, layout(site, page, "Statistics" if latest else f"Statistics {snap['snapshot']}", body,
                              "statistics/", "Programme statistics", cls="statistics"))


def render_updates(site):
    page = "updates/index.html"
    items = site.c.updates.get("items", [])

    def link_for(x):
        if x in site.c.records:
            return f'<a href="{site.href(page, "cases/" + x + "/")}">{E(site.c.records[x][-1]["work"]["title"])}</a>'
        if x in {"statistics", "methodology"}:
            return f'<a href="{site.href(page, x + "/")}">{E(x.capitalize())}</a>'
        return ""
    lis = "".join(f'<li><span class="h-d">{E(fmt_date(u["date"]))}<span class="u-type">{E(u["type"])}</span></span>'
                  f'<div class="h-t"><strong>{E(u["title"])}</strong><p>{E(u["body"])}</p>'
                  f'<p class="u-links">{" · ".join(filter(None, map(link_for, u.get("links", []))))}</p></div></li>'
                  for u in items)
    body = f"""
<div class="wrap page-head"><h1>Updates and policies</h1><p class="lede">Releases, revisions, corrections and statistics
snapshots, newest first, followed by the policies that govern them. <a href="{site.href(page, 'feed.xml')}">Atom feed</a>.</p></div>
<div class="wrap reading">
<nav class="toc" aria-label="On this page"><a href="#log">Updates</a><a href="#author-responses">Author responses</a>
<a href="#corrections">Corrections and withdrawals</a><a href="#challenges">Challenges and replications</a></nav>
<div class="prose">
<section id="log"><h2>Updates</h2><ol class="hist updates">{lis}</ol></section>
<section id="author-responses"><h2>Author responses</h2><ul>
<li>Author contact is optional and is not required before or after publication.</li>
<li>If a substantive written response already exists, it is considered in the record and may motivate further checking.</li>
<li>An author's disagreement is evidence to assess, not a veto over publication.</li>
<li>A reply is published only as the authors' own public statement, wording they separately approve for public use, or a link to their public statement.</li>
<li>Private correspondence is never quoted or summarized publicly without separate consent.</li></ul></section>
<section id="corrections"><h2>Corrections and withdrawals</h2><ul>
<li>Released versions are never edited. Every change is a new version with a dated change note; earlier versions stay online.</li>
<li>Our own errors are labelled as our corrections. If a finding changes, older versions point to the current one.</li>
<li>A finding we no longer stand behind is withdrawn: the record stays online with the reason.</li>
<li>A published correction by the authors or journal is added to the record, and described as crediting this audit only if it says so.</li>
<li>Material published by mistake is removed, and a short notice records the removal without repeating the content.</li></ul></section>
<section id="challenges"><h2>Challenges and replications</h2><p>Anyone may challenge or replicate a published record.
Substantive challenges are checked and their outcome is added to the record; replications are credited by name with
consent. Allegations about papers not on this site should not be sent through public channels.</p></section>
</div></div>
"""
    site.add(page, layout(site, page, "Updates and policies", body, "updates/", cls="updates"))
    entries = "".join(
        f"<entry><title>{E(u['title'])}</title><id>{E(site.cfg['base_url'])}updates/#{E(u['date'])}-{i}</id>"
        f"<updated>{E(u['date'])}T00:00:00Z</updated><summary>{E(u['body'])}</summary>"
        f"<link href=\"{E(site.cfg['base_url'])}updates/\"/></entry>" for i, u in enumerate(items))
    feed = (f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{E(site.cfg['name'])} updates</title><id>{E(site.cfg['base_url'])}</id>"
            f"<updated>{E(site.c.updates.get('updated', items[0]['date'] if items else '2026-01-01'))}T00:00:00Z</updated>"
            f"<author><name>{E(site.cfg['owner'])}</name></author>{entries}</feed>\n")
    site.add("feed.xml", feed)


def render_about(site):
    page = "about/index.html"
    cfg = site.cfg
    status = "No case records have been released yet." if not site.c.records else ""
    body = f"""
<div class="wrap page-head"><h1>About</h1><p class="lede">{E(cfg['name'])}: {E(cfg['descriptor'].rstrip('.').lower())}.
<em>{E(cfg['tagline'])}</em></p></div>
<div class="wrap reading">
<nav class="toc" aria-label="On this page"><a href="#purpose">Purpose</a><a href="#who">Who</a><a href="#disclosure">Disclosure</a>
<a href="#contact">Contact</a><a href="#licence">Licence and citation</a></nav>
<div class="prose">
{f'<p class="callout">{E(status)}</p>' if status else ''}
<section id="purpose"><h2>Purpose</h2><p>{E(cfg['name'])} investigates whether published theoretical claims follow from
their stated assumptions. Sometimes a claim is false as stated; sometimes a proof has a gap or an assumption is missing and
a repair exists; often the claim survives serious attempts to break it. All of these are recorded, claim by claim. Proofs
are hard, and correcting them is part of scholarship. A record is not a verdict on the people who wrote the paper.</p></section>
<section id="who"><h2>Who</h2><p>{E(cfg['owner'])}. {cfg['owner_bio']}</p></section>
<section id="disclosure"><h2>Disclosure</h2><p><strong>Human-led, AI-assisted, independent research.</strong> AI models
are used for discovery and for separate hostile rechecks. Each finding is checked against the published version of the source before
publication, and the researcher makes
every editorial decision. {E(cfg['name'])} is independent personal research. It is not conducted on behalf of any employer
and is not affiliated with, commissioned by or endorsed by the journals, publishers or authors whose work is examined.
Records are current assessments, not final authority.</p></section>
<section id="contact"><h2>Contact</h2><p>{cfg['contact_html']}</p></section>
<section id="licence"><h2>Licence, citation and source</h2><p>Text and data: CC BY 4.0. Code: MIT. Each record shows how
to cite it. Cite the project as: {E(cfg['owner'])}. <em>{E(cfg['name'])}: {E(cfg['descriptor'].rstrip('.').lower())}</em>.
{E(cfg['base_url'])}. Source code and release history:
<a href="{E(cfg['repository_url'])}">{E(cfg['repository_url'].replace('https://', ''))}</a>.</p></section>
</div></div>
"""
    site.add(page, layout(site, page, "About", body, "about/", indexable=True, cls="about"))


def render_404(site):
    page = "404.html"
    body = (f'<div class="wrap page-head"><h1>Page not found</h1><p class="lede">Released records keep their addresses. '
            f'Try the <a href="{site.href(page, "cases/")}">case index</a>.</p></div>')
    site.add(page, layout(site, page, "Page not found", body))


def rich(rec, text, where):
    """Text for one field. Schema-2 fields may hold \\( \\) and \\[ \\] mathematics; schema-1 text is escaped as written."""
    if rec.get("schema") in {2, 3}:
        return mathml.render(text, where, math=True)
    return E(text)


def claim_view(rec, c):
    """Facts about one claim: outcome, status, evidence that happened and the
    author response. Renderers and statistics read this. It records facts; it does not decide publication."""
    res = c["result"]
    v2 = rec.get("schema") in {2, 3}
    status = (res["status"] if v2 else "confirmed") if res["outcome"] == "defect_found" else None
    outcome = res["outcome"]
    revision = c.get("publication_revision") or {}
    if revision:
        status = revision["to_status"]
        if status == "rejected":
            outcome = "rejected"
    provenance = c.get("status_provenance") or {}
    if provenance:
        status = provenance["status"]
        if status == "rejected":
            outcome = "rejected"
    if v2:
        evidence = [dict(e) for e in c["evidence"]]
        ar = c.get("author_response")
        if rec.get("schema") == 3 and ar is None:
            response = {"position": None, "responder": None, "basis": "none", "counts": False,
                        "covers": None, "assessment": None, "legacy": False, "summary": None}
        else:
            response = {"position": ar["position"], "responder": ar.get("responder"), "basis": ar.get("basis", "none"),
                        "counts": ar.get("counts", False), "covers": ar.get("covers"), "assessment": ar.get("assessment"),
                        "legacy": False, "summary": None}
    else:
        evidence = [{"type": V1_EVIDENCE[k["kind"]], "date": k["date"], "session": k.get("session"),
                     "identity": None, "detail": k["detail"]}
                    for k in c.get("checks", []) if k.get("result") == "confirms" and k["kind"] != "author_agreement"]
        pos = rec["author_position"]
        counts = any(k["kind"] == "author_agreement" and k.get("result") == "confirms" for k in c.get("checks", []))
        response = {"position": pos["position"], "responder": None, "basis": "original" if counts else "none",
                    "counts": counts, "covers": None, "assessment": None, "legacy": True, "summary": pos.get("summary")}
    return {"outcome": outcome, "status": status, "evidence": evidence, "response": response}


AGREEMENT_SENTENCE = {
    "all": "The authors also agreed in writing with the identified defect.",
    "one_of_two": "One of the two authors also agreed in writing with the identified defect.",
    "some": "Some of the authors also agreed in writing with the identified defect.",
}


def basis_text(view):
    """The positive basis for a defect, in plain words, from what actually happened. Empty for other outcomes."""
    if view["outcome"] != "defect_found":
        return ""
    types = {e["type"] for e in view["evidence"]}
    parts = []
    if "hostile_ai_recheck" in types:
        parts.append("Survived a separate-session hostile AI recheck and a check against the published version.")
    else:
        parts.append("Checked against the published version.")
    if "researcher_reproduction" in types:
        parts.append("The researcher re-derived it independently.")
    if "external_check" in types:
        parts.append("An external check was made.")
    resp = view["response"]
    if resp["counts"]:
        parts.append(AGREEMENT_SENTENCE.get(resp["responder"], "An author also agreed in writing with the identified defect."))
    if "private_human_confirmation" in types:
        parts.append("A human confirmation is recorded privately; its source is not disclosed.")
    return " ".join(parts)


def status_html(site, page, status):
    label = {"open": "Open", "confirmed": "Confirmed", "unresolved": "Unresolved", "rejected": "Rejected"}[status]
    if status in {"open", "confirmed"}:
        return f'<a class="status status-{status}" href="{site.href(page, "definitions/")}#{status}">{label}</a>'
    return f'<span class="status status-{status}">{label}</span>'


def status_cell(site, page, rec, c):
    """Index cell: Open or Confirmed, the evidence that happened, and the source-check level. No empty slots."""
    view = claim_view(rec, c)
    src = VOR_SHORT[c["vor_check"]["level"]]
    if view["outcome"] == "no_defect_found":
        rerun = " · rerun passes" if (c.get("reproduction") or {}).get("result") == "pass" else ""
        return f'<span class="vt">Deep audit{rerun}</span><span class="vs-sub">{E(src)}</span>'
    if view["outcome"] == "unresolved":
        label = "Unresolved" if c.get("publication_revision") or c.get("status_provenance") else "Not settled"
        return f'<span class="vt status-unresolved">{label}</span><span class="vs-sub">{E(src)}</span>'
    if view["outcome"] == "rejected":
        return f'<span class="vt status-rejected">Rejected</span><span class="vs-sub">Former Open finding · {E(src)}</span>'
    names = [EVIDENCE_SHORT[e["type"]] for e in view["evidence"]]
    if view["response"]["counts"]:
        names.append(EVIDENCE_SHORT["author_agreement"])
    label = {"open": "Open", "confirmed": "Confirmed"}[view["status"]]
    detail = "; ".join(x for x in [" + ".join(dict.fromkeys(names)), src] if x)
    return f'<span class="vt status-{view["status"]}">{label}</span><span class="vs-sub">{E(detail)}</span>'


def evidence_list(rec, view, where):
    """The checks that actually took place, one line each. Nothing is listed for checks that did not happen."""
    items = []
    for i, e in enumerate(view["evidence"]):
        tags = [fmt_month(e["date"]) if e.get("date") else ""]
        tags.append({"blind": "blind session", "informed": "informed session"}.get(e.get("session"), ""))
        tags.append({"named": "named", "anonymous": "anonymous"}.get(e.get("identity"), ""))
        tags = ", ".join(t for t in tags if t)
        head = E(SUPPORT_KINDS[e["type"]]) + (f" · {E(tags)}" if tags else "")
        items.append(f'<li><span class="ev-k">{head}</span><span class="ev-d">'
                     f'{rich(rec, e["detail"], f"{where} evidence {i + 1}")}</span></li>')
    return f'<ul class="evidence">{"".join(items)}</ul>' if items else ""


def author_html(rec, view, where):
    """Render only the author-response facts allowed by the record schema."""
    resp = view["response"]
    if resp["legacy"]:
        out = f"<p>{E(POS_LONG[resp['position']])}</p>"
        if resp.get("summary"):
            out += (f'<blockquote class="resp">{E(resp["summary"])}</blockquote>'
                    '<p class="resp-src">Quoted with the authors\' approval.</p>')
        return out
    pos = resp["position"]
    if pos is None:
        return "<p>No substantive author position is recorded in this version.</p>"
    if pos in RESPONSE_VERB and resp.get("responder") in RESPONDERS:
        singular = resp["responder"] in {"one", "one_of_two"}
        line = f"{RESPONDERS[resp['responder']]} {RESPONSE_VERB[pos][1 if singular else 0]}."
    else:
        line = f"{POSITIONS_V2[pos]}."
    out = f"<p>{E(line)}</p>"
    if resp.get("covers"):
        out += f'<p class="covers">Covers: {rich(rec, resp["covers"], where + " covers")}</p>'
    if resp.get("assessment"):
        out += f'<p class="covers">Our assessment: {rich(rec, resp["assessment"], where + " assessment")}</p>'
    if resp["basis"] == "secondary_record":
        out += '<p class="small muted">Recorded from a secondary account of the reply. It does not count as written agreement.</p>'
    return out


def scan_output(out_dir, denylist):
    # Exact existing public PDF+attachment pairs. The embedded files are C2PA/JUMBF CBOR manifests;
    # raw bytes are checked below, and any changed or new opaque attachment fails closed.
    legacy_c2pa_attachments = {
        ("35788fcacfed91012f9f1f7449c02168abbd9588e75dd636a69876f996e39e4a",
         "b913370333b9a042564b8f5d6c3b5b4577f5b82f0e86bb9213ca50d4b9c8fb44"),
        ("5be28b879699ec9c99142add40ecb02f1ba53025cc93dd09d4c191df1524e3c3",
         "2f32c633312ab135e36ea1aa66c9c0d42c963c1790087117a73cebde8a3978f7"),
        ("8d5bb24abdeee4beb0d34c7c3648c342087be528110c51ca4e264bb5aec0196a",
         "e77d6304375e981468cb8b2c98244dc6585c16a6cb59d85935912f092e1749d6"),
        ("9ebbaea1081ce64e4d7af2c25538d93f0bd1dae5c280c579b21afb6251aa07b2",
         "a4bfed2d7f145630197f94cc05c18ef6db0bcf3fc62186afedf71d0cca83179b"),
        ("ecbb9b5b10f66741f50cec4307f7024ba046022863e02a9e0a33d15ba07a26fe",
         "39be431b783d7ddc04fb9da3fbddd985dca58ab5088ddf2802f975a848dc968d"),
    }
    text_attachment_suffixes = {".csv", ".html", ".htm", ".json", ".md", ".txt", ".xml"}
    problems = []
    pats = [re.compile(p) for p in LEAK_PATTERNS]
    deny = [d for d in denylist if d]
    for f in out_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix == ".pdf":
            try:
                from pypdf import PdfReader
                from pypdf.generic import ByteStringObject, IndirectObject, NameObject, TextStringObject

                def pdf_object_text(obj, depth=0, seen=None):
                    if depth > 64:
                        raise ValueError("PDF object nesting limit")
                    if seen is None:
                        seen = set()
                    if isinstance(obj, IndirectObject):
                        ref = (obj.idnum, obj.generation)
                        if ref in seen:
                            return ""
                        seen.add(ref)
                        obj = obj.get_object()
                    if isinstance(obj, ByteStringObject):
                        raw = bytes(obj)
                        parts = [raw.decode("latin-1"), raw.decode("utf-8", errors="replace")]
                        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                            parts.append(raw.decode("utf-16", errors="replace"))
                        return "\n".join(parts)
                    if isinstance(obj, (TextStringObject, NameObject)):
                        return str(obj)
                    if isinstance(obj, dict):
                        identity = id(obj)
                        if identity in seen:
                            return ""
                        seen.add(identity)
                        return "\n".join(pdf_object_text(value, depth + 1, seen)
                                         for value in obj.values())
                    if isinstance(obj, (list, tuple)):
                        identity = id(obj)
                        if identity in seen:
                            return ""
                        seen.add(identity)
                        return "\n".join(pdf_object_text(value, depth + 1, seen) for value in obj)
                    return ""

                def pdf_text(reader, pdf_digest, depth=0):
                    if depth > 4 or reader.is_encrypted or not reader.pages:
                        raise ValueError("PDF nesting, encryption or page limit")
                    parts = []
                    if reader.metadata:
                        parts.append(str(reader.metadata))
                    xmp = reader.xmp_metadata
                    if xmp:
                        stream = getattr(xmp, "stream", None)
                        if stream is None or not hasattr(stream, "get_data"):
                            raise ValueError("PDF XMP metadata could not be read")
                        xmp_bytes = stream.get_data()
                        parts.append(xmp_bytes.decode("latin-1"))
                        parts.append(xmp_bytes.decode("utf-8", errors="replace"))
                        if xmp_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
                            parts.append(xmp_bytes.decode("utf-16", errors="replace"))
                    page_text = []
                    for page in reader.pages:
                        extracted = page.extract_text() or ""
                        page_text.append(extracted)
                        parts.append(extracted)
                    if not any(value.strip() for value in page_text):
                        raise ValueError("PDF has no extractable page text")
                    # Covers nested annotation actions (/A -> /URI), additional/catalog actions,
                    # form values, and outline strings. Stream payloads are handled separately.
                    parts.append(pdf_object_text(reader.trailer))
                    fields = reader.get_fields()
                    if fields:
                        parts.append(str(fields))
                    for name, attachments in reader.attachments.items():
                        parts.append(str(name))
                        for attachment in attachments:
                            if not isinstance(attachment, bytes):
                                raise ValueError("invalid embedded file")
                            attachment_digest = sha256_bytes(attachment)
                            if attachment.startswith(b"%PDF-"):
                                parts.append(pdf_text(PdfReader(io.BytesIO(attachment), strict=True),
                                                      attachment_digest, depth + 1))
                            elif Path(str(name)).suffix.lower() in text_attachment_suffixes:
                                if attachment.startswith((b"\xff\xfe", b"\xfe\xff")):
                                    parts.append(attachment.decode("utf-16", errors="strict"))
                                else:
                                    parts.append(attachment.decode("utf-8-sig", errors="strict"))
                            elif (pdf_digest, attachment_digest) in legacy_c2pa_attachments:
                                # CBOR text strings are UTF-8; scanning raw bytes catches ASCII/UTF-8
                                # strings while the exact pair preserves the immutable legacy files.
                                parts.append(attachment.decode("latin-1"))
                                parts.append(attachment.decode("utf-8", errors="replace"))
                            else:
                                raise ValueError("unsupported opaque embedded file")
                    return "\n".join(parts)

                pdf_bytes = f.read_bytes()
                pdf_digest = sha256_bytes(pdf_bytes)
                text = pdf_text(PdfReader(io.BytesIO(pdf_bytes), strict=True), pdf_digest)
            except Exception:
                problems.append(f"{f.relative_to(out_dir)}: PDF privacy scan could not complete")
                continue
        elif f.suffix in {".html", ".json", ".xml", ".css", ".js", ".txt"}:
            text = f.read_text(encoding="utf-8", errors="replace")
        else:
            continue
        for p in pats:
            if p.search(text):
                problems.append(f"{f.relative_to(out_dir)}: matches {p.pattern}")
        for d in deny:
            if d.lower() in text.lower():
                problems.append(f"{f.relative_to(out_dir)}: contains a private-denylist term")
        for em in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
            problems.append(f"{f.relative_to(out_dir)}: contains an e-mail address")
    return problems


def load_config(root, config):
    path = Path(config) if Path(config).is_absolute() else root / config
    return json.loads(path.read_text(encoding="utf-8"))


def check_expected_trust(content, expected):
    # Real releases intentionally use no separate signing key.
    want = sorted(x.strip() for x in (expected or "").split(",") if x.strip())
    _require(want, "no expected trust setting given (set the TRUST_FINGERPRINTS repository variable)")
    _require(want == ["none"], f"expected fingerprints {want} do not match: the published channel has no signing key")


def build(channel=None, out=None, pretty=False, denylist_file=None, root=ROOT, config="site.json", expect_trust=None):
    cfg = load_config(root, config)
    channel = channel or cfg.get("channel", CHANNEL)
    content = Content(channel, root).load()
    if expect_trust is not None:
        check_expected_trust(content, expect_trust)
    prefix = cfg.get("id_prefix")
    if prefix:
        wrong = [rid for rid in content.records if not rid.startswith(prefix + "-")]
        _require(not wrong, f"records {wrong} do not use this site's identifier prefix {prefix}")
    site = Site(content, cfg, pretty)
    render_home(site)
    render_explorer(site)
    for rid, versions in content.records.items():
        render_record(site, versions[-1])
        for v in versions:
            render_record(site, v, frozen=True)
    if page_on(site, "statistics"):
        render_statistics(site)
    render_methodology(site)
    render_definitions(site)
    if page_on(site, "updates"):
        render_updates(site)
    render_about(site)
    render_404(site)
    out = Path(out) if out else root / cfg.get("out_dir", "dist")
    if out.exists() and any(out.iterdir()):
        if not (out / OUTPUT_MARKER).exists():
            raise BuildError(f"refusing to replace {out}: it is not a previous build output")
        # Remove files, then any directories left empty. Directories held open by a local preview
        # server or by sync software on Windows are kept and refilled rather than deleted.
        for f in sorted(out.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if f.is_file():
                f.unlink()
            else:
                try:
                    f.rmdir()
                except OSError:
                    pass
    out.mkdir(parents=True, exist_ok=True)
    (out / OUTPUT_MARKER).write_text("Created by build.py; safe to replace.\n", encoding="utf-8")
    for path, text in site.pages.items():
        p = out / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    shutil.copytree(root / "static", out / "static", dirs_exist_ok=True)
    for rid, versions in content.records.items():
        for v in versions:
            src = content.croot / "records" / rid / f"v{v['version']}.json"
            dst = out / "data" / "records" / rid / f"v{v['version']}.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            for note in v.get("technical_notes", []):
                note_src = content.croot / "files" / note["path"]
                _require(note_src.is_file(), f"record {rid} v{v['version']}: technical note PDF is missing")
                note_bytes = note_src.read_bytes()
                _require(note_bytes.startswith(b"%PDF-"), f"record {rid} v{v['version']}: technical note is not a PDF")
                _require(sha256_bytes(note_bytes) == note["sha256"],
                         f"record {rid} v{v['version']}: technical note SHA-256 does not match its immutable file")
                note_dst = out / note["path"]
                note_dst.parent.mkdir(parents=True, exist_ok=True)
                if note_dst.exists():
                    _require(note_dst.read_bytes() == note_bytes, f"technical note path reused with different bytes: {note['path']}")
                else:
                    note_dst.write_bytes(note_bytes)
    for s in content.snapshots:
        dst = out / "data" / "snapshots" / f"{s['snapshot']}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(content.croot / "snapshots" / f"{s['snapshot']}.json", dst)
    listed = sorted(p for p in site.pages if p.endswith(".html") and p != "404.html")
    robots = f"User-agent: *\nAllow: /\nSitemap: {cfg['base_url']}sitemap.xml\n"
    (out / "robots.txt").write_text(robots, encoding="utf-8", newline="\n")
    urls = "".join(f"<url><loc>{E(cfg['base_url'] + p.replace('index.html', ''))}</loc></url>" for p in listed)
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/'
                                     f'schemas/sitemap/0.9">{urls}</urlset>\n', encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    deny = []
    if denylist_file:
        deny = [ln.strip() for ln in Path(denylist_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
    problems = scan_output(out, deny)
    if problems:
        raise BuildError("leak scan failed:\n  " + "\n  ".join(problems[:20]))
    return site, content, out


# ------------------------------------------------------------------ command line
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--config", default="site.json", help="site configuration file (default site.json)")
    b.add_argument("--channel", help="content channel; defaults to the one named in the configuration")
    b.add_argument("--out")
    b.add_argument("--pretty-urls", action="store_true", help="links without index.html (for the hosted site)")
    b.add_argument("--private-denylist", help="file of private terms that must not appear (never commit it)")
    b.add_argument("--expect-trust", help="must be 'none': real releases use no signing key (used by CI)")
    c = sub.add_parser("check")
    c.add_argument("--channel", default=CHANNEL)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            site, content, out = build(a.channel, a.out, a.pretty_urls, a.private_denylist, config=a.config,
                                       expect_trust=a.expect_trust)
            print(f"built {len(site.pages)} pages ({site.cfg['name']}) into {out} from channel '{content.channel}'; "
                  f"{len(content.verified)} release manifests verified; leak scan passed")
        elif a.cmd == "check":
            content = Content(a.channel).load()
            print(f"channel '{a.channel}': {len(content.verified)} release manifests verified; statistics checks passed")
    except BuildError as e:
        print(f"BUILD REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
