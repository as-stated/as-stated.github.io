#!/usr/bin/env python3
"""As Stated: static site builder and release checker (Python standard library only).

Commands
  python build.py build [--channel sample|published] [--pretty-urls] [--out DIR]
                        [--private-denylist FILE] [--expect-trust FPR[,FPR...]]
  python build.py check [--channel ...]            verify releases and statistics only
  python build.py sign  --key KEY --kind KIND --id ID --version V --file FILE [--channel ...]
  python build.py sign-sample                      sign the fictional sample content with a
                                                   throwaway demonstration key (never trusted in production)

Publication rule enforced here: a record version, statistics snapshot or updates file is
built only if (1) a release statement naming its exact SHA-256 exists and (2) that statement
carries a valid SSH signature from a key listed in the channel's allowed_signers file.
The 'published' channel trusts only trust/allowed_signers (the owner's key) and refuses
any content marked as sample. --expect-trust makes the build fail unless the trusted keys
are exactly the given fingerprints, so a commit that swaps in another key cannot deploy.
"""
import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAMESPACE = "as-stated-release"
PRINCIPAL = "release-approver"
CHANNELS = {
    "sample": {"trust": "trust/sample_allowed_signers", "sample": True},
    "published": {"trust": "trust/allowed_signers", "sample": False},
}


def channel_conf(name):
    """'published' is the only real channel. Any 'sample' or 'sample-<brand>' channel holds fictional content
    signed with the throwaway demonstration key."""
    if name == "published":
        return CHANNELS["published"]
    if re.fullmatch(r"sample(-[a-z]+)?", name or ""):
        return CHANNELS["sample"]
    raise BuildError(f"unknown channel {name!r}")
TRACKS = {
    "game_theory": "Game theory",
    "mechanism_design": "Mechanism design",
    "matching_social_choice": "Matching and social choice",
}
KINDS = {"defect", "negative"}
SUPPORT_KINDS = {
    "ai_recheck": "Rechecked by a separate AI session",
    "independent_reproduction": "Independently reproduced by the researcher",
    "external_human": "Verified by an external human",
    "author_agreement": "Written agreement by the authors",
}
HUMAN_KINDS = {"independent_reproduction", "external_human", "author_agreement"}
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
    "courtesy_notice": "Courtesy notice sent",
    "not_disclosed": "Not disclosed",
    "previously_corrected": "Not contacted: already corrected before the audit",
}
UNRESOLVED_REASONS = {"source_limited": "source not available", "disputed_reading": "reading of the source disputed"}
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
                 r"\.env\b", r"BEGIN [A-Z ]*PRIVATE KEY", r"\bgh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_\w{20,}"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]


class BuildError(Exception):
    pass


if sys.version_info < (3, 12):
    sys.exit("Python 3.12 or newer is required.")

E = html.escape
OUTPUT_MARKER = ".as-stated-build-output"


def key_of(line):
    """Return 'type base64' from an allowed_signers line, ignoring principals, options and comments."""
    parts = line.split()
    for i, p in enumerate(parts):
        if (p.startswith("ssh-") or p.startswith("sk-ssh-") or p.startswith("ecdsa-")) and i + 1 < len(parts):
            return f"{p} {parts[i + 1]}"
    return None


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


def statement_paths(croot, kind, rid, version):
    base = croot / "releases" / f"{kind}__{rid}__{version}.txt"
    return base, Path(str(base) + ".sig")


def verify_signature(statement_file, sig_file, allowed_signers):
    if not sig_file.exists():
        return False, "signature file missing"
    r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed_signers), "-I", PRINCIPAL,
                        "-n", NAMESPACE, "-s", str(sig_file)],
                       input=statement_file.read_bytes(), capture_output=True)
    return r.returncode == 0, (r.stdout + r.stderr).decode(errors="replace").strip()


def key_fingerprints(allowed_signers):
    fps = []
    for line in allowed_signers.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not key_of(line):
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".pub", delete=False) as tf:
            tf.write(key_of(line) + "\n")
        r = subprocess.run(["ssh-keygen", "-l", "-f", tf.name], capture_output=True, text=True)
        Path(tf.name).unlink()
        if r.returncode == 0:
            fps.append(r.stdout.split()[1])
    return fps


# ------------------------------------------------------------------ loading and release verification
class Content:
    def __init__(self, channel, root=ROOT):
        conf = channel_conf(channel)
        self.channel = channel
        self.root = root
        self.croot = root / "content" / channel
        self.trust = root / conf["trust"]
        self.is_sample = conf["sample"]
        self.records = {}   # id -> list of record dicts sorted by version
        self.snapshots = []
        self.updates = {"items": []}
        self.verified = []  # (kind, id, version, sha256)

    def check_trust(self):
        if not self.trust.exists():
            raise BuildError(f"trust file missing: {self.trust.relative_to(self.root)}")
        keys = [key_of(ln) for ln in self.trust.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#") and key_of(ln)]
        if not keys:
            raise BuildError(f"no release key configured in {self.trust.relative_to(self.root)}; "
                             "the owner must add their public key before anything can be published")
        if not self.is_sample:
            sample_file = self.root / CHANNELS["sample"]["trust"]
            sample_keys = set()
            if sample_file.exists():
                sample_keys = {key_of(ln) for ln in sample_file.read_text(encoding="utf-8").splitlines()
                               if ln.strip() and not ln.startswith("#") and key_of(ln)}
            if set(keys) & sample_keys:
                raise BuildError("the published channel trusts the demonstration key; remove it")
        return keys

    def released(self, kind, rid, version, path):
        data = path.read_bytes()
        digest = sha256_bytes(data)
        st, sig = statement_paths(self.croot, kind, rid, version)
        if not st.exists():
            raise BuildError(f"not released: no release statement for {kind} {rid} {version}")
        if st.read_bytes() != release_statement(kind, rid, version, digest):
            raise BuildError(f"release statement does not match the file for {kind} {rid} {version} "
                             "(content changed after approval?)")
        ok, msg = verify_signature(st, sig, self.trust)
        if not ok:
            raise BuildError(f"invalid or untrusted signature for {kind} {rid} {version}: {msg}")
        self.verified.append((kind, rid, version, digest))
        return json.loads(data.decode("utf-8"))

    def load(self):
        self.check_trust()
        rdir = self.croot / "records"
        for f in sorted(rdir.glob("*/v*.json")) if rdir.exists() else []:
            rid, version = f.parent.name, f.stem[1:]
            rec = self.released("record", rid, version, f)
            validate_record(rec, rid, version, self.is_sample)
            self.records.setdefault(rid, []).append(rec)
        for rid in self.records:
            self.records[rid].sort(key=lambda r: vkey(r["version"]))
        sdir = self.croot / "snapshots"
        for f in sorted(sdir.glob("*.json")) if sdir.exists() else []:
            snap = self.released("snapshot", f.stem, "1", f)
            validate_snapshot_shape(snap, f.stem, self.is_sample)
            self.snapshots.append(snap)
        uf = self.croot / "updates.json"
        if uf.exists():
            self.updates = self.released("updates", "updates", "1", uf)
            if bool(self.updates.get("sample")) != self.is_sample:
                raise BuildError("updates.json sample flag does not match the channel")
        if not self.records and not self.snapshots:
            raise BuildError(f"channel '{self.channel}' has no released content")
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
    return {c["kind"] for c in claim.get("checks", []) if c.get("result") == "confirms"}


def validate_record(rec, rid, version, is_sample):
    where = f"record {rid} v{version}"
    unknown = set(rec) - RECORD_KEYS
    _require(not unknown, f"{where}: unknown fields {sorted(unknown)}")
    missing = RECORD_KEYS - set(rec)
    _require(not missing, f"{where}: missing fields {sorted(missing)}")
    _require(rec["public_id"] == rid and rec["version"] == version, f"{where}: id or version does not match its path")
    _require(re.fullmatch(r"[A-Z]{2,4}-\d{4}-\d{3}", rid) is not None, f"{where}: malformed public id")
    _require(bool(rec["sample"]) == is_sample,
             f"{where}: sample flag is {rec['sample']} but channel requires {is_sample}")
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
            _require(res.get("unresolved_reason") in UNRESOLVED_REASONS and res.get("detail") and res.get("limits"),
                     f"{where}: {c['label']}: an unresolved claim needs a reason, a description and its limits")
            continue
        _require(c["vor_check"]["level"] in {"full", "partial"},
                 f"{where}: {c['label']}: named records need a full or partial version-of-record check")
        for k in c.get("checks", []):
            _require(k["kind"] in SUPPORT_KINDS, f"{where}: {c['label']}: unknown check kind {k['kind']}")
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


def validate_snapshot_shape(snap, stem, is_sample):
    unknown = set(snap) - SNAPSHOT_KEYS
    _require(not unknown, f"snapshot {stem}: unknown fields {sorted(unknown)}")
    _require(snap["snapshot"] == stem, f"snapshot {stem}: name mismatch")
    _require(bool(snap.get("sample")) == is_sample, f"snapshot {stem}: sample flag does not match the channel")
    for metric in snap.get("examined_by_track", {}):
        _require(metric in {"M01", "M02", "M03", "M04"},
                 f"snapshot {stem}: track breakdowns that include unreleased work are allowed only for M01-M04")


def released_stats(content, as_of):
    """Counts computable from the records released on or before as_of."""
    recs = content.latest_all(as_of)
    s = {"papers": len(recs), "claims": 0, "deep": 0, "confirmed": 0, "negative": 0, "candidates": 0,
         "ai_blind": 0, "ai_informed": 0, "indep": 0, "external": 0,
         "vor_conf": {"full": 0, "partial": 0, "none": 0}, "vor_neg": {"full": 0, "partial": 0, "none": 0},
         "positions": {"agreed": 0, "partly_agreed": 0, "disagreed": 0, "none_yet": 0}, "notified": 0,
         "unresolved": 0, "previously_reported": 0, "calibration": 0,
         "corrections": {"credits_programme": 0, "none_stated": 0}, "our_corrections": 0,
         "papers_by_track": {t: 0 for t in TRACKS}, "claims_by_track": {t: 0 for t in TRACKS},
         "outcome_by_track": {t: {"confirmed": 0, "negative": 0} for t in TRACKS},
         "defect_class": {}, "affects": {}}
    pos_map = {"agrees": "agreed", "partly_agrees": "partly_agreed", "disagrees": "disagreed", "none_yet": "none_yet"}
    for r in recs:
        s["papers_by_track"][r["track"]] += 1
        notified = r["author_position"]["position"] in {"agrees", "partly_agrees", "disagrees", "none_yet"}
        s["notified"] += notified
        for c in r["claims"]:
            s["claims"] += 1
            s["claims_by_track"][r["track"]] += 1
            s["deep"] += c["result"].get("depth") == "deep_audit"
            lvl = c["vor_check"]["level"]
            if c["result"]["outcome"] == "unresolved":
                s["unresolved"] += 1
            elif c["result"]["outcome"] == "defect_found":
                s["candidates"] += 1
                s["confirmed"] += 1
                if c["result"].get("previously_reported"):
                    s["previously_reported"] += 1
                    s["calibration"] += 1
                s["outcome_by_track"][r["track"]]["confirmed"] += 1
                s["vor_conf"][lvl] += 1
                dc = DEFECT_CLASSES[c["result"]["defect_class"]]
                s["defect_class"][dc] = s["defect_class"].get(dc, 0) + 1
                af = "Main result" if c["result"]["affects"] == "main_result" else "Other"
                s["affects"][af] = s["affects"].get(af, 0) + 1
                sessions = {k.get("session") for k in c["checks"] if k["kind"] == "ai_recheck" and k["result"] == "confirms"}
                s["ai_blind"] += "blind" in sessions
                s["ai_informed"] += ("informed" in sessions and "blind" not in sessions)
                kinds = support_kinds(c)
                s["indep"] += "independent_reproduction" in kinds
                s["external"] += "external_human" in kinds
                if notified:
                    p = r["author_position"]["position"]
                    if p in pos_map:
                        s["positions"][pos_map[p]] += 1
                corr = r.get("correction")
                if corr and corr["relation"] == "after_notification" and corr["date"] <= as_of:
                    s["corrections"][corr["attribution"]] += 1
            else:
                s["negative"] += 1
                s["outcome_by_track"][r["track"]]["negative"] += 1
                s["vor_neg"][lvl] += 1
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
        rs = released_stats(content, snap["as_of"])
        checks = [
            ("M01", t["M01"], rs["papers"]), ("M02", t["M02"], rs["papers"]), ("M03", t["M03"], rs["claims"]),
            ("M04", t["M04"], rs["deep"]), ("M05", t["M05"], rs["candidates"] + rs["unresolved"]),
            ("M06 confirmed", conf, rs["confirmed"]), ("M06 unresolved", m06["unresolved"], rs["unresolved"]),
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
NOINDEX = '<meta name="robots" content="noindex">'


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
TRACK_SHORT = {"game_theory": "Game theory", "mechanism_design": "Mechanism design",
               "matching_social_choice": "Matching and social choice"}
CLAIM_KINDS = {"theorem": "Theorem", "proposition": "Proposition", "lemma": "Lemma", "corollary": "Corollary",
               "remark": "Remark", "algorithm": "Algorithm", "construction": "Construction", "application": "Application"}
ROLES = {"main": "main result", "supporting": "supporting result", "secondary": "secondary result",
         "application": "application", "repair": "corrected version"}
FAMILIES = [
    ("none", "No defect found",
     "A deep audit within a stated scope found no defect. This is not a proof that the claim is correct."),
    ("false", "False as stated",
     "The claim, read exactly as printed with its stated assumptions, is false. A counterexample is given."),
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
    "statement_false": ("false", None), "definition_defect": ("false", "definition"),
    "proof_gap_repairable": ("proof", "repairable gap"), "proof_invalid_statement_open": ("proof", "statement open"),
    "citation_or_dependency_gap": ("proof", "unsupported citation"),
    "missing_or_hidden_assumption": ("assumption", None), "construction_or_algorithm_fails": ("construction", None),
}
HUMAN_ORDER = [("independent_reproduction", "Researcher"), ("external_human", "External"),
               ("author_agreement", "Authors")]
LADDER = [
    ("ai_recheck", "Separate AI recheck", "Not done", "An AI model in a new session. Never counted as a human check."),
    ("independent_reproduction", "Reproduced by the researcher", "Not done",
     "Re-derived by hand or with separately written code."),
    ("external_human", "External human verification", "Not done", "Someone outside the programme, in their own name."),
    ("author_agreement", "Written author agreement", "Not given", "The authors agreed in writing."),
]
POS_SHORT = {"agrees": "Authors agree", "partly_agrees": "Authors partly agree", "disagrees": "Authors disagree",
             "none_yet": "No reply within 90 days"}
POS_LONG = {
    "agrees": "The authors agreed with the finding in writing.",
    "partly_agrees": "The authors partly agreed with the finding in writing.",
    "disagrees": "The authors disagree with the finding.",
    "none_yet": "The authors were notified and gave no substantive reply within 90 days.",
    "courtesy_notice": "The authors received a courtesy notice when the record was approved.",
    "not_disclosed": "Not disclosed.",
    "previously_corrected": "The authors were not contacted: the error had already been corrected before this audit.",
}
VOR_SHORT = {"full": "full source check", "partial": "partial source check", "none": "source not obtained"}
METHOD_STEPS = [
    ("Select", "Papers are chosen deliberately. Many are screened from their metadata; fewer are investigated claim by claim."),
    ("State the claim exactly", "Every definition, assumption and quantifier is taken from the published version."),
    ("Try to break it", "Search for counterexamples and for steps in the proof that fail."),
    ("Try to rescue it", "Look for the intended reading and for a repair before reporting a problem."),
    ("Confirm", "A defect counts only after two different kinds of check, at least one of them by a human."),
    ("Authors first", "Authors are told before anything is published, and their reply is published with the record."),
    ("Release and maintain", "Each release is signed. Responses, corrections and our own errors become new, dated versions."),
]


def family(c):
    r = c["result"]
    if r["outcome"] == "no_defect_found":
        return "none", FAMILY_LABEL["none"], None
    if r["outcome"] == "unresolved":
        return "unresolved", FAMILY_LABEL["unresolved"], UNRESOLVED_REASONS.get(r.get("unresolved_reason"))
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
    return f"<i>{E(w['venue'])}</i>{E(vol)} ({w['year']}), {E(w['pages'])}"


def citation_line(w):
    vol = f" {w['volume']}" if w.get("volume") else ""
    return f"{author_list(w['authors'])} ({w['year']}). {w['title']}. {w['venue']}{vol}, {w['pages']}."


def doi_html(site, doi):
    if site.c.is_sample:
        return f'<span class="mono">doi:{E(doi)}</span> <span class="muted">(fictional)</span>'
    return f'<a class="mono" href="https://doi.org/{E(doi)}">doi:{E(doi)}</a>'


def vstrip(c):
    """Compact verification summary for the index: four slots (AI separated from the three human kinds) plus words."""
    r = c["result"]
    src = VOR_SHORT[c["vor_check"]["level"]]
    if r["outcome"] == "no_defect_found":
        rerun = " · rerun passes" if (c.get("reproduction") or {}).get("result") == "pass" else ""
        return f'<span class="vt">Deep audit{rerun}</span><span class="vs-sub">{E(src)}</span>'
    if r["outcome"] == "unresolved":
        return f'<span class="vt">Not settled</span><span class="vs-sub">{E(src)}</span>'
    kinds = support_kinds(c)
    humans = [lbl for k, lbl in HUMAN_ORDER if k in kinds]
    aria = "; ".join(f"{SUPPORT_KINDS[k].lower()}: {'yes' if k in kinds else 'no'}"
                     for k in ["ai_recheck"] + [k for k, _ in HUMAN_ORDER])
    boxes = (f'<span class="vs" role="img" aria-label="{E("Checks. " + aria)}">'
             f'<i class="vb-ai{" on" if "ai_recheck" in kinds else ""}" title="Separate AI recheck (not a human check)">AI</i>'
             + "".join(f'<i class="vb{" on" if k in kinds else ""}" title="{E(SUPPORT_KINDS[k])}"></i>' for k, _ in HUMAN_ORDER)
             + "</span>")
    return (f'<span class="vline">{boxes}<span class="vt">{E(" + ".join(humans))}</span></span>'
            f'<span class="vs-sub">{E(src)}</span>')


def development(rec, c):
    out = []
    corr = rec.get("correction")
    if corr and c["id"] in corr.get("claims", []):
        if corr["relation"] == "before_audit":
            out.append(f"Corrected in {fmt_month(corr['date'])}, before this audit")
        else:
            credit = ", credits this audit" if corr["attribution"] == "credits_programme" else ""
            out.append(f"{corr['type'].capitalize()} {fmt_month(corr['date'])}{credit}")
    if c.get("role") == "repair" and corr:
        out.append(f"Audit of the {corr['type']}")
    if c["result"]["outcome"] == "defect_found":
        p = POS_SHORT.get(rec["author_position"]["position"])
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
        fam = family(c)[0]
        text = f"{group_text} {c['label']} {c['gist']} {c['result'].get('summary', '')}".lower()
        rows.append(
            f'<tr class="ix-row" data-fam="{fam}" data-kind="{E(c["kind"])}" data-text="{E(text)}">'
            f'<td class="ix-claim" data-label="Claim"><a class="ix-label" href="{link}#{E(c["id"])}">{E(c["label"])}</a>'
            f'<span class="ix-kind">{E(CLAIM_KINDS[c["kind"]])} · {E(ROLES[c["role"]])}</span>'
            f'<span class="ix-gist">{E(c["gist"])}</span></td>'
            f'<td class="ix-find" data-label="Finding">{finding_badge(c)}<span class="ix-sum">{E(c["result"]["summary"])}</span></td>'
            f'<td class="ix-ver" data-label="Verification">{vstrip(c)}</td>'
            f'<td class="ix-dev" data-label="Development">{dev_html(rec, c)}</td></tr>')
    return f'<tbody class="ix-group" data-track="{E(rec["track"])}">{head}{"".join(rows)}</tbody>'


def claim_index(site, page, recs):
    return ('<div class="ix-wrap"><table class="ix" id="case-index"><thead><tr>'
            '<th scope="col" class="c1">Claim</th><th scope="col" class="c2">Finding</th>'
            '<th scope="col" class="c3">Verification</th><th scope="col" class="c4">Development</th></tr></thead>'
            + "".join(paper_group(site, page, r) for r in recs) + "</table></div>")


def counts(recs):
    k = {"papers": len(recs), "claims": 0, "none": 0, "defect": 0, "unresolved": 0}
    for r in recs:
        for c in r["claims"]:
            k["claims"] += 1
            o = c["result"]["outcome"]
            k["none" if o == "no_defect_found" else "unresolved" if o == "unresolved" else "defect"] += 1
    return k


def legend_html():
    return "".join(f'<li><span class="fd fd-{k}"><i class="mk" aria-hidden="true"></i>{E(lbl)}</span>'
                   f'<span class="lg-d">{E(d)}</span></li>' for k, lbl, d in FAMILIES)


def layout(site, page, title, body, active="", description="", indexable=False, cls=""):
    cfg = site.cfg
    h = lambda t: site.href(page, t)
    cur = ' aria-current="page"'
    nav = "".join(f'<a href="{h(t)}"{cur if active == t else ""}>{E(n)}</a>' for t, n in NAV)
    banner = f'<div class="demo-banner" role="note">{cfg["demo_notice"]}</div>' if site.c.is_sample else ""
    robots = "" if indexable or not site.c.is_sample else NOINDEX
    full_title = cfg["name"] if title == cfg["name"] else f"{title} · {cfg['name']}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(full_title)}</title>
<meta name="description" content="{E(description or cfg['descriptor'])}">
{robots}
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="{h('static/style.css')}">
<link rel="icon" href="{h('static/favicon.svg')}" type="image/svg+xml">
<link rel="alternate" type="application/atom+xml" title="{E(cfg['name'])} updates" href="{h('feed.xml')}">
</head>
<body class="{cls}">
<a class="skip" href="#main">Skip to content</a>
{banner}
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
  <p><a href="{h('about/')}#disclosure">Disclosure</a> · <a href="{h('methodology/')}#release">How releases are approved</a> ·
  <a href="{h('feed.xml')}">Atom feed</a> · <a href="{E(cfg['repository_url'])}">Source</a></p></div>
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
    demo = " (demonstration)" if site.c.is_sample else ""
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
    <p class="aside-k">Released so far{demo}</p>
    <p class="aside-v"><strong>{k['claims']}</strong> claims in <strong>{k['papers']}</strong> papers</p>
    <ul class="tally">
      <li><span class="fd fd-none"><i class="mk"></i>No defect found</span><span class="n">{k['none']}</span></li>
      <li><span class="fd fd-false"><i class="mk"></i>Defect confirmed</span><span class="n">{k['defect']}</span></li>
      <li><span class="fd fd-unresolved"><i class="mk"></i>Unresolved</span><span class="n">{k['unresolved']}</span></li>
    </ul>
    <p class="aside-note">Papers are chosen deliberately, not sampled at random. These are counts of this programme's work, not error rates.
    <a href="{site.href(page, 'statistics/')}">Statistics</a></p>
  </aside>
</div></section>
<section class="wrap block">
  <div class="sec-head"><h2>Recent case records</h2>
  <a class="more" href="{site.href(page, 'cases/')}">All {k['papers']} papers and {k['claims']} claims</a></div>
  <p class="sec-lede">Each paper is listed with every claim that was investigated in it. A paper can contain a claim
  that survived and another that did not, so there is no verdict on the paper as a whole.</p>
  {claim_index(site, page, recs[:4])}
</section>
<section class="wrap block two">
  <div><h2>Reading a finding</h2><ul class="legend">{legend_html()}</ul></div>
  <div><h2>How a claim is examined</h2><ol class="steps">{steps}</ol>
  <p><a href="{site.href(page, 'methodology/')}">Methodology and confirmation standard</a></p></div>
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
    demo = " All records shown are fictional demonstrations." if site.c.is_sample else ""
    body = f"""
<div class="wrap page-head">
  <h1>Cases</h1>
  <p class="lede">Every investigated claim, grouped by paper, most recently updated first. {k['claims']} claims in
  {k['papers']} papers.{demo}</p>
  <p class="small muted">A record is published only after the confirmation standard is met, the authors have been contacted
  and the release has been signed. Candidates still under review and rejected candidates are counted in the
  <a href="{site.href(page, 'statistics/')}">statistics</a> but not named.</p>
</div>
<div class="wrap">
<form class="filters" id="filters" hidden>
  <label class="f-search"><span class="sr">Search</span><input type="search" id="f-text" placeholder="Search papers, authors, claims"></label>
  <label><span class="f-l">Finding</span><select id="f-fam"><option value="">All</option>{o_f}</select></label>
  <label><span class="f-l">Claim type</span><select id="f-kind"><option value="">All</option>{o_k}</select></label>
  <label><span class="f-l">Field</span><select id="f-track"><option value="">All</option>{o_t}</select></label>
  <span class="count" id="f-count" aria-live="polite"></span>
</form>
{claim_index(site, page, recs)}
<p class="note">Finding labels are defined in <a href="{site.href(page, 'definitions/')}#findings">Definitions</a>.
Verification shows which kinds of check confirmed a defect: the dashed "AI" tag is a separate AI recheck, which never
counts as a human check; the three squares are the researcher, an external person and the authors. {E(SELECTION_STATEMENT)}</p>
</div>
"""
    site.add(page, layout(site, page, "Cases", body, "cases/", "Index of investigated claims", cls="cases"))


def blk(label, html_text, cls=""):
    return f'<div class="blk {cls}"><h3 class="blk-l">{E(label)}</h3><div class="blk-c">{html_text}</div></div>'


def ladder(c):
    by_kind = {}
    for k in c.get("checks", []):
        if k.get("result") == "confirms":
            by_kind.setdefault(k["kind"], []).append(k)
    items = []
    for kind, label, absent, note in LADDER:
        got = by_kind.get(kind)
        if got:
            det = "".join(f'<span class="ld">{E(fmt_month(x["date"]))}{(" · " + E(x["session"])) if x.get("session") else ""}. '
                          f'{E(x["detail"])}</span>' for x in got)
            items.append(f'<li class="on{" ai" if kind == "ai_recheck" else ""}"><span class="lk">{E(label)}</span>{det}</li>')
        else:
            items.append(f'<li class="off{" ai" if kind == "ai_recheck" else ""}"><span class="lk">{E(label)}</span><span class="ld">{E(absent)}.</span></li>')
    kinds = support_kinds(c)
    humans = len(kinds & HUMAN_KINDS)
    note = (f"Confirmed: {len(kinds)} kinds of check, {humans} by a human. The standard requires two kinds, at least one by a human."
            if c["result"]["outcome"] == "defect_found" else "")
    return f'<ul class="ladder">{"".join(items)}</ul>' + (f'<p class="ladder-note">{E(note)}</p>' if note else "")


def render_claim(site, page, rec, c, i, n):
    res = c["result"]
    fam = family(c)[0]
    meta = [f"Claim {i} of {n}" if n > 1 else "Claim", CLAIM_KINDS[c["kind"]].lower(), ROLES[c["role"]], f"p. {c['page']}"]
    stmt_meta = ""
    if c.get("conditions"):
        stmt_meta += f"<dt>Assumptions</dt><dd>{'; '.join(E(x) for x in c['conditions'])}</dd>"
    if c.get("quantifiers"):
        stmt_meta += f"<dt>Scope of the claim</dt><dd>{E(c['quantifiers'])}</dd>"
    parts = []
    v = c["vor_check"]
    vor_html = f'<strong>{E(VOR_LEVELS[v["level"]].split(":")[0])} check</strong>, pp. {E(v["pages"])}. {E(v["detail"])}'
    rep = c.get("reproduction") or {}
    rep_html = f'{E(rep.get("result", "").capitalize())}. {E(rep.get("detail", ""))}' if rep else ""
    if res["outcome"] == "defect_found":
        parts.append(blk("What was found", f"<p>{E(res['witness'])}</p>"))
        parts.append(blk("What was tested", f"<p>{E(res['tested'])}</p>"))
        parts.append(blk("Does not establish", "<ul>" + "".join(f"<li>{E(x)}</li>" for x in res["not_claimed"]) + "</ul>"))
        repair = E(REPAIRS.get(res.get("repair"), ""))
        if res.get("repair_note"):
            repair += ". " + E(res["repair_note"])
        parts.append(blk("Repair", f"<p>{repair}</p>"))
        parts.append(blk("Verification", ladder(c)))
        parts.append(blk("Source", f"<p>{vor_html}</p>"))
        if rep_html:
            parts.append(blk("Evidence rerun", f"<p>{rep_html}</p>"))
        if c.get("novelty"):
            parts.append(blk("Earlier reports", f"<p>{E(c['novelty'])}</p>"))
        verdict_note = ""
    elif res["outcome"] == "no_defect_found":
        verdict_note = f'<p class="caveat">{E(NEGATIVE_CAVEAT)}</p>'
        parts.append(blk("What was tested", f"<p>{E(res['search_scope'])}</p>"))
        parts.append(blk("Limits", f"<p>{E(res['limits'])}</p>"))
        parts.append(blk("Source", f"<p>{vor_html}</p>"))
        if rep_html:
            parts.append(blk("Evidence rerun", f"<p>{rep_html}</p>"))
        if c.get("checks"):
            parts.append(blk("Other checks", "<ul>" + "".join(
                f"<li>{E(SUPPORT_KINDS[k['kind']])}, {E(fmt_month(k['date']))}. {E(k['detail'])}</li>" for k in c["checks"]) + "</ul>"))
    else:
        verdict_note = ('<p class="caveat caveat-open">This question is not settled. It is not counted as a defect, and the '
                        'record will be revised if the missing source becomes available.</p>')
        parts.append(blk("What is known", f"<p>{E(res['detail'])}</p>"))
        parts.append(blk("Why unresolved", f"<p>{E(res['limits'])}</p>"))
        parts.append(blk("Source", f"<p>{vor_html}</p>"))
    _, label, q = family(c)
    qh = f'<span class="fd-q">{E(q)}</span>' if q else ""
    return f"""
<section class="claim fam-{fam}" id="{E(c['id'])}">
  <header class="claim-head">
    <p class="claim-meta">{' · '.join(E(x) for x in meta)}</p>
    <h2>{E(c['label'])}</h2>
    <p class="verdict">{finding_badge(c, qualifier=False)}{qh}</p>
    <p class="verdict-sum">{E(res['summary'])}</p>
  </header>
  <figure class="stmt"><blockquote><p><span class="stmt-l">{E(c['label'])}.</span> <span class="stmt-t">{E(c['statement'])}</span></p></blockquote>
  {f'<dl class="stmt-meta">{stmt_meta}</dl>' if stmt_meta else ''}</figure>
  {verdict_note}
  <div class="blks">{''.join(parts)}</div>
</section>"""


def render_record(site, rec, frozen=False):
    rid, ver = rec["public_id"], rec["version"]
    page = f"cases/{rid}/v{ver}/index.html" if frozen else f"cases/{rid}/index.html"
    cfg = site.cfg
    current = site.c.records[rid][-1]
    w = rec["work"]
    digest = next(d for k, i, v, d in site.c.verified if k == "record" and i == rid and v == ver)
    claims = rec["claims"]
    n = len(claims)
    pos = rec["author_position"]
    corr = rec.get("correction")
    # Overview of claims in this paper
    overview = ""
    if n > 1:
        rows = "".join(
            f'<tr><td class="ov-n">{i}</td><td><a href="#{E(c["id"])}">{E(c["label"])}</a>'
            f'<span class="ov-kind">{E(CLAIM_KINDS[c["kind"]])} · {E(ROLES[c["role"]])}</span></td>'
            f'<td>{finding_badge(c)}</td><td class="ov-ver">{vstrip(c)}</td></tr>'
            for i, c in enumerate(claims, start=1))
        overview = (f'<section class="overview" aria-label="Claims in this paper"><h2 class="ov-h">{n} claims investigated in this paper</h2>'
                    f'<table class="ov"><tbody>{rows}</tbody></table></section>')
    # Responses and corrections: compact
    resp = [f"<dt>Authors</dt><dd>{E(POS_LONG[pos['position']])}"
            + (f'<blockquote class="resp">{E(pos["summary"])}</blockquote><span class="resp-src">Summary published with the authors\' consent.</span>'
               if pos.get("summary") else "") + "</dd>"]
    if corr:
        if corr["relation"] == "before_audit":
            ctext = (f"{corr['type'].capitalize()} published in {fmt_month(corr['date'])}, before this audit "
                     f"({doi_html(site, corr['doi'])}). Not an outcome of this audit.")
        else:
            attrib = ("It credits this audit." if corr["attribution"] == "credits_programme" else
                      "It does not mention this audit; we do not claim it resulted from our work.")
            ctext = (f"{corr['type'].capitalize()} published {E(fmt_date(corr['date']))}, after the authors were notified "
                     f"({doi_html(site, corr['doi'])}). {E(attrib)}")
        resp.append(f"<dt>Correction</dt><dd>{ctext}</dd>")
    else:
        resp.append("<dt>Correction</dt><dd>None published.</dd>")
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
    url = cfg["base_url"].rstrip("/") + f"/cases/{rid}/v{ver}/"
    cite = f"{cfg['owner']} ({rec['released'][:4]}). Case record {rid}, version {ver}: {rec['title']}. {cfg['name']}. {url}"
    bib = (f"@misc{{{rid.replace('-', '_')}_v{ver.replace('.', '_')},\n  author = {{{cfg['owner']}}},\n"
           f"  title = {{Case record {rid}, version {ver}: {rec['title']}}},\n  howpublished = {{{cfg['name']}}},\n"
           f"  year = {{{rec['released'][:4]}}},\n  url = {{{url}}}\n}}")
    notes = ""
    if frozen and ver != current["version"]:
        notes += (f'<p class="notice">Archived version {E(ver)}. The current version is '
                  f'<a href="{site.href(page, "cases/" + rid + "/")}">{E(current["version"])}</a>.</p>')
    if site.c.is_sample:
        notes += '<p class="notice">Fictional demonstration record.</p>'
    fams = [family(c)[0] for c in claims]
    status = []
    if pos["position"] in POS_SHORT:
        status.append(POS_SHORT[pos["position"]])
    if corr:
        status.append(development(rec, next(c for c in claims if c["id"] in corr.get("claims", [c["id"]])))[0])
    body = f"""
<div class="wrap case">
<nav class="crumbs" aria-label="Breadcrumb"><a href="{site.href(page, 'cases/')}">Cases</a><span aria-hidden="true">/</span><span>{E(rid)}</span></nav>
{notes}
<header class="case-head">
  <p class="eyebrow">Case record · {E(TRACKS[rec['track']])}</p>
  <h1>{E(w['title'])}</h1>
  <p class="byline">{E(author_list(w['authors']))} · {venue_line(w)} · {doi_html(site, w['doi'])}</p>
  <p class="lede">{E(rec['headline'])}</p>
  <ul class="case-facts">
    <li><span class="cf-k">Findings</span>{''.join(f'<i class="mk-dot fd-{f}" title="{E(FAMILY_LABEL[f])}"></i>' for f in fams)}<span class="cf-v">{n} claim{"s" if n != 1 else ""}</span></li>
    <li><span class="cf-k">Updated</span><span class="cf-v">{E(fmt_date(rec['released']))} · version {E(ver)}</span></li>
    {''.join(f'<li><span class="cf-k">Authors</span><span class="cf-v">{E(s)}</span></li>' for s in status[:1])}
    {''.join(f'<li><span class="cf-k">Correction</span><span class="cf-v">{E(s)}</span></li>' for s in status[1:2])}
  </ul>
</header>
<div class="case-grid">
<article class="case-main">
  {overview}
  {''.join(render_claim(site, page, rec, c, i, n) for i, c in enumerate(claims, start=1))}
  <section class="after" id="responses"><h2>Authors and corrections</h2><dl class="rd">{''.join(resp)}</dl></section>
  <section class="after" id="history"><h2>History</h2><ol class="hist">{hist}</ol></section>
  <section class="after" id="versions"><h2>Versions</h2><ol class="hist">{vers}</ol>
  <p class="note">Released versions are never edited; each keeps its own address.</p></section>
  <section class="after" id="ai-use"><h2>Use of AI in this case</h2><p>{E(rec['statements']['ai_use'])}</p></section>
</article>
<aside class="case-aside" aria-label="Record details">
  <dl class="side">
    <dt>Record</dt><dd><span class="mono">{E(rid)}</span>, version {E(ver)}<br>released {E(fmt_date(rec['released']))}</dd>
    <dt>Evidence package</dt><dd>{doi_html(site, rec['evidence']['package_doi'])}<br>
      <span class="small muted">{E(rec['evidence']['licence'])}</span><ul class="files">{files}</ul></dd>
    <dt id="verification">Release verification</dt><dd class="small">Signed release. Record file SHA-256
      <span class="mono hash" title="{E(digest)}">{E(digest[:16])}…</span> verified when the site was built.
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
    ("M10", "Confirmed: verified by an external human", "claim", "Verified by someone outside the programme.", "monthly"),
    ("M11", "Confirmed: source check", "claim", "Confirmed claims by full, partial or no check against the published version.", "monthly"),
    ("M12", "Papers whose authors were notified", "paper", "Courtesy notices for negative audits are not counted.", "quarterly"),
    ("M13", "Authors' position on confirmed findings", "claim", "Confirmed claims in notified papers, by the authors' latest written position.", "quarterly"),
    ("M14", "Corrections published after notification", "claim", "Released records only; credited to this audit only if the correction says so.", "monthly"),
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
    lad = "".join(f"<div class=\"def\"><dt>{E(lbl)}</dt><dd>{E(note)}</dd></div>" for _, lbl, _, note in LADDER)
    body = f"""
<div class="wrap page-head"><h1>Definitions</h1>
<p class="lede">The vocabulary used in every record and statistic. Metric definitions version {E(site.cfg['metrics_version'])}.</p></div>
<div class="wrap reading">
<nav class="toc" aria-label="On this page"><a href="#findings">Findings</a><a href="#statuses">Statuses</a><a href="#checks">Checks</a>
<a href="#vor">Source check</a><a href="#authors">Author positions</a><a href="#corrections">Corrections</a><a href="#metrics">Metrics</a></nav>
<div class="prose">
<section id="findings"><h2>Findings</h2><p>Each investigated claim has exactly one finding. A paper with several claims can have
several different findings; there is no verdict on a paper as a whole.</p><dl class="defs">{fams}</dl>
<p>A short qualifier sometimes follows the label:</p><ul>{quals}</ul>
<p>Records also say which result a defect affects and what the finding does <em>not</em> establish.</p></section>
<section id="statuses"><h2>Statuses of a candidate defect</h2><dl class="defs">
<div class="def"><dt id="candidate">Candidate</dt><dd>Any possible defect reported by any check. Most candidates come from AI-assisted discovery runs and are never published by name.</dd></div>
<div class="def"><dt>Open</dt><dd>Not yet settled. A candidate supported only by AI rechecks stays open until a human has checked it.</dd></div>
<div class="def"><dt id="confirmed">Confirmed</dt><dd>At least two confirming checks of different kinds, at least one by a human, and no refuting check left unaddressed. Only confirmed defects are published as defects.</dd></div>
<div class="def"><dt>Unresolved</dt><dd>Checks were completed but could not settle the question. Never counted as a defect or as rejected. An unresolved
question appears by name only inside a record that is released for other, settled claims in the same paper; a paper is
never named because of an unresolved question alone.</dd></div>
<div class="def"><dt>Rejected</dt><dd>A check showed the suspected defect does not exist. Counted, never named.</dd></div>
<div class="def"><dt id="withdrawn">Withdrawn</dt><dd>A released record we no longer stand behind. The page stays online with the reason.</dd></div></dl></section>
<section id="checks"><h2>Kinds of check</h2><p>Verification is shown as four kinds of check. Only the last three are human checks.</p>
<dl class="defs">{lad}</dl><p>Rerunning the original evidence package shows the package works; it is reported separately and is not counted as a check.</p></section>
<section id="vor"><h2>Source check</h2><p>The decisive elements are the statement, every definition and assumption the finding relies on, the decisive step, and any supplement the claim depends on.</p><ul>{vor}</ul></section>
<section id="authors"><h2>Author positions</h2><p>Recorded only from written statements: agreed, partly agreed, disagree, or no substantive reply within 90 days (a reply that only acknowledges receipt is not a position). Summaries of a reply are published only with the authors' consent.</p></section>
<section id="corrections"><h2>Corrections</h2><p>A correction is described as crediting this audit only if its own text says so. A correction published before the audit marks the finding as previously reported; it is not an outcome of this audit.</p></section>
</div></div>
<div class="wrap"><section id="metrics" class="block"><h2>Metrics</h2><div class="table-wrap"><table class="data rtable metrics"><thead><tr><th scope=col>ID</th><th scope=col>Label</th><th scope=col>Unit</th><th scope=col>Counting rule</th><th scope=col>Updated</th></tr></thead><tbody>{metrics}</tbody></table></div>
<p class="note">A ratio is shown only when its numerator is a subset of its denominator, as counts ("6 of 11"). No ratio uses papers or claims examined as its denominator. {E(SELECTION_STATEMENT)}</p></section></div>
"""
    site.add(page, layout(site, page, "Definitions", body, "definitions/", indexable=True, cls="definitions"))


def render_methodology(site):
    page = "methodology/index.html"
    fps = key_fingerprints(site.c.trust)
    keys = ", ".join(f'<span class="mono">{E(f)}</span>' for f in fps)
    preview = (" The cases on this site are fictional demonstrations signed with a throwaway demonstration key; real "
               "records will be signed with the researcher's own release key.") if site.c.is_sample else ""
    steps = "".join(f"<li><strong>{E(a)}.</strong> {E(b)}</li>" for a, b in METHOD_STEPS)
    toc = [("question", "The question"), ("process", "Process"), ("standard", "Confirmation standard"),
           ("findings", "Findings"), ("verification", "Verification"), ("negative", "Negative audits"),
           ("source", "Source check"), ("authors", "Authors first"), ("ai", "How AI is used"),
           ("selection", "Selection and statistics"), ("release", "How releases are approved"), ("not", "What we do not do")]
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
<section id="standard"><h2>Confirmation standard</h2><p class="callout">A suspected defect is <strong>confirmed</strong> only
after at least two confirming checks of different kinds, at least one of them by a human, and with no refuting check left
unaddressed. Rerunning the original evidence package does not count as a check.</p>
<p>Only confirmed defects are published as defects. Candidates supported only by AI rechecks are counted in the statistics
as open, not named.</p></section>
<section id="findings"><h2>Findings</h2><p>Each investigated claim receives one of six findings.</p>
<ul class="legend">{legend_html()}</ul></section>
<section id="verification"><h2>Verification</h2><p>Each confirmed defect lists the kinds of check that confirmed it:
a separate AI recheck, a reproduction by the researcher, an external human verification, and written agreement by the
authors. The case index shows the AI recheck as a small dashed "AI" tag, set apart from three squares for the human
checks, because AI agreement is not independent human confirmation. Each record also states how far the finding was checked against the
published version of the paper.</p></section>
<section id="negative"><h2>Negative audits</h2><p>{E(NEGATIVE_CAVEAT_GENERAL)} Each negative audit states what was
tested and its limits. Only deep audits are published by name; lighter screens appear only in counts.</p></section>
<section id="source"><h2>Source check</h2><p>Findings are checked against the version of record. Each claim states whether every
decisive element was checked on rendered pages of the published version (full), only partly (partial), or whether the
needed version could not be obtained. A question that depends on an unobtainable version is reported as unresolved, not as
a defect. It is shown only inside a record released for other, settled claims in the same paper, and the record is
revised if the missing version becomes available.</p></section>
<section id="authors"><h2>Authors first</h2><p>Authors are contacted privately before anything about their paper is published.
A finding becomes eligible for publication after a published correction, after the authors agree to a public record, or
90 days after contact without a substantive reply. Eligibility is not a deadline: each release also needs the
confirmation standard, a final source check, consideration of any reply, and the researcher's approval. Disputed findings
wait for an additional check. Where a finding may become a journal comment, the journal's policies come first.</p></section>
<section id="ai"><h2>How AI is used</h2><p>AI models search for counterexamples, write test code and recheck results in
separate sessions. They do not decide what is published. Every published defect has also been checked by a human, and the
researcher makes every editorial decision. Each record states how AI was used in that case.</p></section>
<section id="selection"><h2>Selection and statistics</h2><p>{E(SELECTION_STATEMENT)} Statistics are counts with stated
units; small counts that could identify an unpublished case are suppressed.</p></section>
<section id="release"><h2>How releases are approved</h2><p>Every record version, statistics snapshot and update list is
published only if the researcher has signed a short release statement containing the SHA-256 of its exact data file. The
site build verifies each signature and refuses anything unsigned, altered after signing, or signed by another key.{E(preview)}</p>
<p class="small muted">Trusted key fingerprint: {keys}</p></section>
<section id="not"><h2>What we do not do</h2><ul><li>Publish anonymous or unchecked allegations.</li>
<li>Rank journals, fields or authors.</li><li>Report error rates for published research.</li>
<li>Name a paper because a candidate was rejected or remains unresolved.</li></ul></section>
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
        rs = released_stats(site.c, snap["as_of"])
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
            row("M06", "Open", m06["open"], f"of {t['M05']}; {m06['open_ai_supported']} supported by AI only, awaiting a human check"),
            row("M06", "Unresolved", m06["unresolved"], f"of {t['M05']}; " + E(", ".join(f"{v} {k.replace('_', ' ')}" for k, v in snap['unresolved_reasons'].items()))),
            row("M06", "Rejected after checking", m06["rejected"], f"of {t['M05']}"),
            row("M07", "Deep audits that found no defect", m07,
                f"source check: {t['M07']['vor_full']} full, {t['M07']['vor_partial']} partial, {t['M07']['vor_none']} not obtained")])
        survived = "".join([
            row("M08", "Rechecked by a separate AI session", f"{sum(t['M08'].values())} of {conf}", f"{t['M08']['blind']} blind, {t['M08']['informed']} informed; not a human check"),
            row("M09", "Reproduced by the researcher", f"{t['M09']} of {conf}"),
            row("M10", "Verified by an external human", f"{t['M10']} of {conf}"),
            row("M11", "Source check full / partial / none", f"{t['M11']['full']} / {t['M11']['partial']} / {t['M11']['none']}", f"of {conf}")])
        after = "".join([
            row("M12", "Papers whose authors were notified", t["M12"], f"as of {E(fmt_date(snap['as_of']))}"),
            row("M13", "Authors agreed", f"{m13['agreed']} of {pop13}", "confirmed defects in notified papers"),
            row("M13", "Authors partly agreed", f"{m13['partly_agreed']} of {pop13}"),
            row("M13", "Authors disagree", f"{m13['disagreed']} of {pop13}"),
            row("M13", "No substantive reply within 90 days", f"{m13['none_yet']} of {pop13}"),
            row("M14", "Corrections after notification", corr,
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
        if site.c.is_sample:
            notes += '<p class="notice">Demonstration statistics. All figures are fictional.</p>'
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
    demo = '<p class="notice">The updates listed are fictional demonstrations. The policies are real.</p>' if site.c.is_sample else ""
    body = f"""
<div class="wrap page-head"><h1>Updates and policies</h1><p class="lede">Releases, revisions, corrections and statistics
snapshots, newest first, followed by the policies that govern them. <a href="{site.href(page, 'feed.xml')}">Atom feed</a>.</p>{demo}</div>
<div class="wrap reading">
<nav class="toc" aria-label="On this page"><a href="#log">Updates</a><a href="#author-responses">Author responses</a>
<a href="#corrections">Corrections and withdrawals</a><a href="#challenges">Challenges and replications</a></nav>
<div class="prose">
<section id="log"><h2>Updates</h2><ol class="hist updates">{lis}</ol></section>
<section id="author-responses"><h2>Author responses</h2><ul>
<li>Authors are contacted privately before anything about their paper is published, and are offered space for a reply.</li>
<li>A reply is published as the authors' own words, a summary they approve, or a link to their own statement. Nothing from
private correspondence is published without written consent.</li>
<li>If the authors dispute a finding, it is not published until an additional independent check has been done.</li>
<li>Positions are recorded only from written statements; a reply that only acknowledges receipt is not a position.</li>
<li>Authors of a paper with a negative deep audit receive a courtesy notice when the record is approved.</li></ul></section>
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
    site.add(page, layout(site, page, "Updates and policies", body, "updates/", indexable=not site.c.is_sample, cls="updates"))
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
    status = ("This site currently shows fictional demonstration cases and statistics only. No real findings have been "
              "published. Real records will appear only after the steps described in the methodology, including the "
              "researcher's signed approval.") if site.c.is_sample else ""
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
are used for discovery and for separate rechecks. A defect is published only after a human check, and the researcher makes
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


def scan_output(out_dir, denylist):
    problems = []
    pats = [re.compile(p) for p in LEAK_PATTERNS]
    deny = [d for d in denylist if d]
    for f in out_dir.rglob("*"):
        if f.is_file() and f.suffix in {".html", ".json", ".xml", ".css", ".js", ".txt"}:
            text = f.read_text(encoding="utf-8", errors="replace")
            for p in pats:
                if p.search(text):
                    problems.append(f"{f.relative_to(out_dir)}: matches {p.pattern}")
            for d in deny:
                if d.lower() in text.lower():
                    problems.append(f"{f.relative_to(out_dir)}: contains a private-denylist term")
            for em in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
                problems.append(f"{f.relative_to(out_dir)}: e-mail address {em}")
    return problems


def load_config(root, config):
    path = Path(config) if Path(config).is_absolute() else root / config
    return json.loads(path.read_text(encoding="utf-8"))


def check_expected_trust(content, expected):
    """Pin the channel's trusted keys to fingerprints held outside the repository (a GitHub repository variable
    that only an administrator can change), so a commit cannot quietly swap in a different signing key."""
    want = sorted(x.strip() for x in (expected or "").split(",") if x.strip())
    _require(want, "no expected trust fingerprints given (set the TRUST_FINGERPRINTS repository variable)")
    have = sorted(key_fingerprints(content.trust))
    _require(have == want, f"trusted keys {have} do not match the expected fingerprints {want}")


def build(channel=None, out=None, pretty=False, denylist_file=None, root=ROOT, config="site.json", expect_trust=None):
    cfg = load_config(root, config)
    channel = channel or cfg.get("channel", "sample")
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
    render_statistics(site)
    render_methodology(site)
    render_definitions(site)
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
    for s in content.snapshots:
        dst = out / "data" / "snapshots" / f"{s['snapshot']}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(content.croot / "snapshots" / f"{s['snapshot']}.json", dst)
    # Demonstration pages carry a noindex tag; only genuine project pages are listed for search engines.
    listed = sorted(p for p, text in site.pages.items() if p.endswith(".html") and p != "404.html"
                    and NOINDEX not in text)
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


# ------------------------------------------------------------------ signing
def sign(channel, key, kind, rid, version, file, root=ROOT):
    croot = root / "content" / channel
    digest = sha256_bytes(Path(file).read_bytes())
    st, sig = statement_paths(croot, kind, rid, version)
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_bytes(release_statement(kind, rid, version, digest))
    if sig.exists():
        sig.unlink()
    r = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", NAMESPACE, str(st)], capture_output=True)
    if r.returncode != 0:
        raise BuildError("signing failed: " + (r.stdout + r.stderr).decode(errors="replace"))
    return st, sig


def sign_sample(root=ROOT):
    """Create a throwaway demonstration key OUTSIDE the project, sign every sample file, keep only the public key."""
    keydir = Path(tempfile.mkdtemp(prefix="as_demo_key_"))
    key = keydir / "demo_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "DEMONSTRATION KEY - never trust for published content",
                    "-f", str(key)], check=True)
    n = 0
    for croot in sorted(p for p in (root / "content").iterdir() if p.is_dir() and re.fullmatch(r"sample(-[a-z]+)?", p.name)):
        ch = croot.name
        rel = croot / "releases"
        if rel.exists():
            shutil.rmtree(rel)
        for f in sorted((croot / "records").glob("*/v*.json")):
            sign(ch, key, "record", f.parent.name, f.stem[1:], f, root)
            n += 1
        for f in sorted((croot / "snapshots").glob("*.json")):
            sign(ch, key, "snapshot", f.stem, "1", f, root)
            n += 1
        if (croot / "updates.json").exists():
            sign(ch, key, "updates", "updates", "1", croot / "updates.json", root)
            n += 1
    pub = (keydir / "demo_key.pub").read_text(encoding="utf-8").strip()
    (root / "trust" / "sample_allowed_signers").write_text(
        "# DEMONSTRATION KEY. Signs the fictional sample content only; its private half was deleted after signing.\n"
        "# Never add it to trust/allowed_signers.\n"
        f'{PRINCIPAL} namespaces="{NAMESPACE}" {" ".join(pub.split()[:2])}\n', encoding="utf-8", newline="\n")
    shutil.rmtree(keydir)
    return n


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
    b.add_argument("--expect-trust", help="comma-separated key fingerprints the channel must trust (used by CI)")
    c = sub.add_parser("check")
    c.add_argument("--channel", default="sample")
    s = sub.add_parser("sign")
    s.add_argument("--channel", default="published")
    s.add_argument("--key", required=True)
    s.add_argument("--kind", required=True, choices=["record", "snapshot", "updates"])
    s.add_argument("--id", required=True)
    s.add_argument("--version", required=True)
    s.add_argument("--file", required=True)
    sub.add_parser("sign-sample")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            site, content, out = build(a.channel, a.out, a.pretty_urls, a.private_denylist, config=a.config,
                                       expect_trust=a.expect_trust)
            print(f"built {len(site.pages)} pages ({site.cfg['name']}) into {out} from channel '{content.channel}'; "
                  f"{len(content.verified)} signed releases verified; leak scan passed")
        elif a.cmd == "check":
            content = Content(a.channel).load()
            print(f"channel '{a.channel}': {len(content.verified)} signed releases verified; statistics checks passed")
        elif a.cmd == "sign":
            st, sig = sign(a.channel, a.key, a.kind, a.id, a.version, a.file)
            print(f"wrote {st.name} and {sig.name}")
        elif a.cmd == "sign-sample":
            print(f"signed {sign_sample()} sample files with a new throwaway demonstration key")
    except BuildError as e:
        print(f"BUILD REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
