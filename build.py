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
    "optimization": "Optimization and mathematical economics",
    "econometrics": "Econometrics",
    "probability": "Probability and stochastic processes",
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
}
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
    for c in rec["claims"]:
        res = c["result"]
        _require(c.get("vor_check", {}).get("level") in VOR_LEVELS, f"{where}: {c['label']}: bad VOR level")
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
         "positions": {"agreed": 0, "partly_agreed": 0, "disagreed": 0}, "notified": 0,
         "corrections": {"credits_programme": 0, "none_stated": 0}, "our_corrections": 0,
         "papers_by_track": {t: 0 for t in TRACKS}, "claims_by_track": {t: 0 for t in TRACKS},
         "outcome_by_track": {t: {"confirmed": 0, "negative": 0} for t in TRACKS},
         "defect_class": {}, "affects": {}}
    pos_map = {"agrees": "agreed", "partly_agrees": "partly_agreed", "disagrees": "disagreed"}
    for r in recs:
        s["papers_by_track"][r["track"]] += 1
        notified = r["author_position"]["position"] in {"agrees", "partly_agrees", "disagrees", "none_yet"}
        s["notified"] += notified
        for c in r["claims"]:
            s["claims"] += 1
            s["claims_by_track"][r["track"]] += 1
            s["deep"] += c["result"].get("depth") == "deep_audit"
            lvl = c["vor_check"]["level"]
            if c["result"]["outcome"] == "defect_found":
                s["candidates"] += 1
                s["confirmed"] += 1
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
            ("M04", t["M04"], rs["deep"]), ("M05", t["M05"], rs["candidates"]), ("M06 confirmed", conf, rs["confirmed"]),
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
TRACK_SHORT = {
    "game_theory": "Game theory", "mechanism_design": "Mechanism design",
    "matching_social_choice": "Matching & social choice", "optimization": "Optimization",
    "econometrics": "Econometrics", "probability": "Probability",
}
OUTCOMES = {
    "statement_false": ("False as printed", "o-false"),
    "construction_or_algorithm_fails": ("Construction fails", "o-false"),
    "proof_invalid_statement_open": ("Proof incomplete", "o-incomplete"),
    "proof_gap_repairable": ("Repairable gap", "o-repair"),
    "citation_or_dependency_gap": ("Repairable gap", "o-repair"),
    "missing_or_hidden_assumption": ("Missing assumption", "o-assump"),
    "definition_defect": ("Definition defect", "o-assump"),
    "no_defect": ("No defect found", "o-none"),
}
AFTER_LABELS = {
    "agrees": "Authors agreed", "partly_agrees": "Authors partly agreed", "disagrees": "Authors disagree",
    "none_yet": "No substantive reply", "courtesy_notice": "Courtesy notice", "not_disclosed": "",
}


def claim_outcome(c):
    r = c["result"]
    return OUTCOMES["no_defect"] if r["outcome"] == "no_defect_found" else OUTCOMES[r["defect_class"]]


def outcome_span(c):
    lbl, cls = claim_outcome(c)
    return f'<span class="o {cls}">{E(lbl)}</span>'


def outcome_list(r, sep="<br>"):
    return sep.join(f'<span class="cl">{E(c["label"])}:</span> {outcome_span(c)}' for c in r["claims"])


def after_items(r):
    items = []
    lbl = AFTER_LABELS.get(r["author_position"]["position"], "")
    if lbl:
        items.append(lbl)
    corr = r.get("correction")
    if corr and corr["relation"] == "after_notification":
        items.append("Corrected" + (" (credits audit)" if corr["attribution"] == "credits_programme" else ""))
    if any(k["kind"] == "external_human" for c in r["claims"] for k in c["checks"]):
        items.append("Externally verified")
    return items


def after_keys(r):
    keys = [r["author_position"]["position"]]
    if r.get("correction") and r["correction"]["relation"] == "after_notification":
        keys.append("corrected")
    return " ".join(keys)


def citation_line(w):
    return f"{', '.join(w['authors'])} ({w['year']}). {w['title']}. {w['venue']} {w['volume']}, {w['pages']}."


def citation_html(w):
    return (f"{E(', '.join(w['authors']))} ({w['year']}). {E(w['title'])}. <i>{E(w['venue'])}</i> "
            f"{E(w['volume'])}, {E(w['pages'])}.")


def doi_html(site, doi):
    if site.c.is_sample:
        return f'<span class="mono">doi:{E(doi)}</span> <span class="muted">(fictional)</span>'
    return f'<a class="mono" href="https://doi.org/{E(doi)}">doi:{E(doi)}</a>'


def layout(site, page, title, body, active="", description="", indexable=False):
    cfg = site.cfg
    h = lambda t: site.href(page, t)
    cur = ' aria-current="page"'
    nav = "".join(f'<a href="{h(t)}"{cur if active == t else ""}>{E(n)}</a>' for t, n in NAV)
    banner = ""
    if site.c.is_sample:
        banner = f'<div class="demo-banner" role="note">{cfg["demo_notice"]}</div>'
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
<body>
<a class="skip" href="#main">Skip to content</a>
{banner}
<header class="top"><div class="wrap top-in">
  <a class="brand" href="{h('')}"><span class="turnstile" aria-hidden="true">⊢</span>{E(cfg['name'])}</a>
  <span class="descriptor">{E(cfg['descriptor'])}</span>
  <nav class="nav" aria-label="Main">{nav}</nav>
</div></header>
<main id="main" class="wrap">
{body}
</main>
<footer class="foot"><div class="wrap foot-in">
  <p><strong>{E(cfg['name'])}</strong>. {E(cfg['descriptor'])} {E(cfg['tagline'])}</p>
  <p>Human-led, AI-assisted, independent research by {E(cfg['owner'])}. Not affiliated with or commissioned by the
  journals, publishers or authors whose work is examined. <a href="{h('about/')}#disclosure">Disclosure</a> ·
  <a href="{h('methodology/')}#release">How releases are approved</a> · <a href="{h('feed.xml')}">Atom</a> ·
  <a href="{E(cfg['repository_url'])}">Source</a></p>
  <p class="muted">Text and data CC BY 4.0; code MIT. Methodology v{E(cfg['methodology_version'])}; metrics v{E(cfg['metrics_version'])}.</p>
</div></footer>
<script src="{h('static/app.js')}" defer></script>
</body>
</html>
"""


def case_rows(site, page, recs):
    rows = []
    for r in recs:
        w = r["work"]
        outcomes = " ".join(claim_outcome(c)[1] for c in r["claims"])
        text = (r["public_id"] + " " + r["title"] + " " + citation_line(w) + " " + r["headline"]).lower()
        link = site.href(page, "cases/" + r["public_id"] + "/")
        after = "<br>".join(E(x) for x in after_items(r)) or '<span class="muted">–</span>'
        rows.append(
            f'<tr data-outcomes="{E(outcomes)}" data-track="{E(r["track"])}" data-after="{E(after_keys(r))}" data-text="{E(text)}">'
            f'<td class="c-id" data-label="Record"><a class="mono" href="{link}">{E(r["public_id"])}</a></td>'
            f'<td class="c-claim" data-label="Claim and paper"><a class="title" href="{link}">{E(r["title"])}</a>'
            f'<div class="sub">{citation_html(w)}</div></td>'
            f'<td class="c-field" data-label="Field">{E(TRACK_SHORT[r["track"]])}</td>'
            f'<td class="c-out" data-label="Outcome">{outcome_list(r)}</td>'
            f'<td class="c-after" data-label="After">{after}</td>'
            f'<td class="c-ver nowrap" data-label="Version">v{E(r["version"])}<br><span class="muted">{E(fmt_date(r["released"]))}</span></td></tr>')
    return ("<div class=\"table-wrap\"><table class=\"cases rtable\"><thead><tr><th scope=col>Record</th>"
            "<th scope=col>Claim and paper</th><th scope=col>Field</th><th scope=col>Outcome by claim</th>"
            "<th scope=col>Afterwards</th><th scope=col>Version</th></tr></thead><tbody>" + "".join(rows) +
            "</tbody></table></div>")


def latest_snapshot(content):
    return max(content.snapshots, key=lambda s: s["as_of"]) if content.snapshots else None


def glance_table(site, page, snap):
    t = snap["totals"]
    rs = released_stats(site.c, snap["as_of"])
    m06 = t["M06"]
    corr = sum(rs["corrections"].values())
    d = site.href(page, "definitions/")
    rows = [
        ("Papers investigated at theorem level", f"{t['M02']}", f"{t['M03']} claims; {t['M04']} deep audits; {t['M01']} papers considered", "m-m02"),
        ("Candidate defects raised", f"{t['M05']}",
         f"{m06['confirmed']} confirmed · {m06['rejected']} rejected · {m06['unresolved']} unresolved · {m06['open']} open", "m-m05"),
        ("Deep audits that found no defect", f"{sum(t['M07'].values())}", "within their stated scope", "m-m07"),
        ("Authors notified", f"{t['M12']}", f"as of {fmt_date(snap['as_of'])}", "m-m12"),
        ("Corrections after notification", f"{corr}", "released records only", "m-m14"),
    ]
    trs = "".join(f'<tr><th scope=row><a href="{d}#{a}">{E(k)}</a></th><td class="num">{v}</td><td class="muted">{E(n)}</td></tr>'
                  for k, v, n, a in rows)
    demo = "Demonstration figures (fictional). " if site.c.is_sample else ""
    return (f'<table class="kv">{trs}</table><p class="note">{demo}Snapshot {E(snap["snapshot"])}. {E(SELECTION_STATEMENT)} '
            f'<a href="{site.href(page, "statistics/")}">All statistics</a></p>')


def render_home(site):
    page = "index.html"
    cfg = site.cfg
    home = cfg["home"]
    snap = latest_snapshot(site.c)
    recs = sorted(site.c.latest_all(), key=lambda r: r["released"], reverse=True)
    steps = "".join(f"<li><strong>{E(a)}.</strong> {E(b)}</li>" for a, b in METHOD_STEPS)
    outs = "".join(f'<li><span class="o {cls}">{E(lbl)}</span> {E(desc)}</li>' for lbl, cls, desc, _ in OUTCOME_DEFS)
    ups = "".join(f'<li><span class="date">{E(fmt_date(u["date"]))}</span> {E(u["title"])}</li>'
                  for u in site.c.updates.get("items", [])[:6])
    paras = "".join(f"<p>{E(x)}</p>" for x in home["intro"])
    paras += (f'<p class="small">Human-led, AI-assisted, independent research by {E(cfg["owner"])}. Authors are contacted '
              f'before anything about their paper is published. <a href="{site.href(page, "about/")}#disclosure">Disclosure</a> · '
              f'<a href="{site.href(page, "methodology/")}#standard">Confirmation standard</a></p>')
    demo_count = " (demonstration)" if site.c.is_sample else ""
    body = f"""
<section class="intro">
  <div class="intro-text">
    <h1>{E(cfg['descriptor'].rstrip('.'))}</h1>
    <p class="tagline">{E(cfg['tagline'])}</p>
    {paras}
  </div>
  <aside class="glance" aria-label="Programme at a glance">
    <h2>At a glance</h2>
    {glance_table(site, page, snap) if snap else '<p class="muted">No statistics released yet.</p>'}
  </aside>
</section>
<section>
  <div class="sec-head"><h2>Cases</h2><span class="muted">{len(recs)} released records{demo_count}, newest first</span>
  <a href="{site.href(page, 'cases/')}">Index with search and filters →</a></div>
  {case_rows(site, page, recs[:10])}
</section>
<section class="cols3">
  <div><h2>Method</h2><ol class="compact">{steps}</ol><p><a href="{site.href(page, 'methodology/')}">Methodology →</a></p></div>
  <div><h2>Outcomes</h2><ul class="compact outcomes">{outs}</ul><p><a href="{site.href(page, 'definitions/')}">Definitions →</a></p></div>
  <div><h2>Updates</h2><ul class="compact dated">{ups}</ul><p><a href="{site.href(page, 'updates/')}">Updates and policies →</a></p></div>
</section>
"""
    site.add(page, layout(site, page, cfg["name"], body, "", cfg["descriptor"], indexable=False))


METHOD_STEPS = [
    ("Select", "Papers are chosen deliberately; many are screened from metadata, fewer are investigated claim by claim."),
    ("State the claim exactly", "Every definition, assumption and quantifier is taken from the published version."),
    ("Try to break it", "Search for counterexamples and proof failures."),
    ("Try to rescue it", "Look for the intended reading and a repair before reporting a problem."),
    ("Confirm", "A defect counts only after two different kinds of check, one of them by a human."),
    ("Authors first", "Authors are told before anything is published; their reply is published with the record."),
    ("Release and maintain", "The researcher signs each release; responses, corrections and our own errors become new versions."),
]
OUTCOME_DEFS = [
    ("False as printed", "o-false", "the claim, read exactly as printed with its stated assumptions, is false; a counterexample is given.", "Yes, once confirmed"),
    ("Proof incomplete", "o-incomplete", "the proof does not establish the claim; no counterexample was found, so the claim itself is open.", "Yes, once confirmed"),
    ("Repairable gap", "o-repair", "a step needs an extra condition or argument; a repair restores the claim in the cases checked.", "Yes, once confirmed"),
    ("Missing assumption", "o-assump", "the claim holds only under an assumption the paper does not state.", "Yes, once confirmed"),
    ("No defect found", "o-none", "a deep audit within a stated scope found no defect. Not a proof of correctness.", "Yes (deep audits only)"),
    ("Unresolved", "o-open", "checks could not settle the question, for example because the published version could not be obtained.", "No; counted only"),
    ("Rejected candidate", "o-open", "a suspected defect that checking showed does not exist.", "No; counted only"),
]


def render_explorer(site):
    page = "cases/index.html"
    recs = sorted(site.c.latest_all(), key=lambda r: r["released"], reverse=True)
    tracks = "".join(f'<option value="{k}">{E(v)}</option>' for k, v in TRACK_SHORT.items())
    outs = "".join(f'<option value="{cls}">{E(lbl)}</option>' for lbl, cls, _, pub in OUTCOME_DEFS if pub.startswith("Yes"))
    demo = " All records shown are fictional demonstrations." if site.c.is_sample else ""
    body = f"""
<div class="page-head"><h1>Cases</h1>
<p>Released case records, newest first. A record is published only after the confirmation standard is met, the authors
have been contacted under the disclosure policy, and the researcher has signed the release. Candidates under review,
unresolved questions and rejected candidates are counted in the <a href="{site.href(page, 'statistics/')}">statistics</a>
but never named.{demo}</p></div>
<form class="filters" id="filters" hidden>
  <input type="search" id="f-text" aria-label="Search" placeholder="Search paper, author, claim, record">
  <select id="f-outcome" aria-label="Outcome"><option value="">Any outcome</option>{outs}</select>
  <select id="f-track" aria-label="Field"><option value="">Any field</option>{tracks}</select>
  <select id="f-after" aria-label="Afterwards"><option value="">Any follow-up</option>
    <option value="agrees">Authors agreed</option><option value="partly_agrees">Authors partly agreed</option>
    <option value="disagrees">Authors disagree</option><option value="none_yet">No substantive reply</option>
    <option value="corrected">Correction published</option></select>
  <span class="count" id="f-count" aria-live="polite"></span>
</form>
<div id="case-index">{case_rows(site, page, recs)}</div>
<p class="note">Outcome labels are defined in <a href="{site.href(page, 'definitions/')}#outcomes">Definitions</a>. {E(SELECTION_STATEMENT)}</p>
"""
    site.add(page, layout(site, page, "Cases", body, "cases/", "Index of released case records"))


def render_claim(site, page, c):
    res = c["result"]
    rows = [("As stated", f'<span class="statement">{E(c["statement"])}</span>')]
    if c.get("conditions"):
        rows.append(("Assumptions", "; ".join(E(x) for x in c["conditions"])))
    if c.get("quantifiers"):
        rows.append(("Quantifiers", E(c["quantifiers"])))
    if res["outcome"] == "defect_found":
        rows.append(("Outcome", f'{outcome_span(c)} · affects {E(AFFECTS[res["affects"]].lower())} · '
                                f'<a href="{site.href(page, "definitions/")}#confirmed">confirmed</a>'))
        rows.append(("Finding", E(res["witness"])))
        rep = E(REPAIRS.get(res.get("repair"), ""))
        if res.get("repair_note"):
            rep += ". " + E(res["repair_note"])
        rows.append(("Repair", rep))
        rows.append(("Not claimed", "<ul>" + "".join(f"<li>{E(x)}</li>" for x in res["not_claimed"]) + "</ul>"))
    else:
        rows.append(("Outcome", f'{outcome_span(c)} · deep audit'))
        rows.append(("Search scope", E(res["search_scope"])))
        rows.append(("Limits", E(res["limits"])))
        rows.append(("Caveat", f'<strong>{E(NEGATIVE_CAVEAT)}</strong>'))
    v = c["vor_check"]
    rows.append(("Published version", f'<strong>{E(v["level"].capitalize())} check</strong>, pp. {E(v["pages"])}. {E(v["detail"])}'))
    rep = c.get("reproduction") or {}
    if rep:
        rows.append(("Reproduction", f'{E(rep.get("result", "").capitalize())}. {E(rep.get("detail", ""))}'))
    if c.get("novelty"):
        rows.append(("Earlier reports", E(c["novelty"])))
    dl = "".join(f"<dt>{E(k)}</dt><dd>{v_}</dd>" for k, v_ in rows)
    checks = ""
    if c.get("checks"):
        trs = "".join(
            f'<tr><td data-label="Check">{E(SUPPORT_KINDS[k["kind"]])}{(" (" + E(k["session"]) + ")") if k.get("session") else ""}</td>'
            f'<td data-label="What was done">{E(k["detail"])}</td><td data-label="When" class="nowrap">{E(fmt_date(k["date"]))}</td>'
            f'<td data-label="Result">{E(k["result"])}</td></tr>' for k in c["checks"])
        checks = ('<h3>Checks</h3><div class="table-wrap"><table class="rtable"><thead><tr><th scope=col>Check</th>'
                  '<th scope=col>What was done</th><th scope=col>When</th><th scope=col>Result</th></tr></thead>'
                  f'<tbody>{trs}</tbody></table></div>')
    meta = f'p. {E(c["page"])} · {E(c["kind"])} · {E(c["role"])} result'
    return f'<section class="claim"><h2>{E(c["label"])} <span class="meta">{meta}</span></h2><dl class="kv2">{dl}</dl>{checks}</section>'


def render_record(site, rec, frozen=False):
    rid, ver = rec["public_id"], rec["version"]
    page = f"cases/{rid}/v{ver}/index.html" if frozen else f"cases/{rid}/index.html"
    cfg = site.cfg
    current = site.c.records[rid][-1]
    w = rec["work"]
    digest = next(d for k, i, v, d in site.c.verified if k == "record" and i == rid and v == ver)
    pos = rec["author_position"]
    pos_text = {
        "agrees": "Agreed in writing that the claim as printed is erroneous.",
        "partly_agrees": "Partly agreed.",
        "disagrees": "Disagree with the finding.",
        "courtesy_notice": "Sent a courtesy notice when the record was approved.",
        "none_yet": "Notified; no substantive reply received within 90 days.",
        "not_disclosed": "Not disclosed.",
    }[pos["position"]]
    if pos.get("summary"):
        pos_text += " " + pos["summary"]
    corr = rec.get("correction")
    corr_html = "None known."
    if corr:
        attrib = ("It credits this audit." if corr["attribution"] == "credits_programme" else
                  "It does not mention this audit; we do not claim that it resulted from our work.")
        corr_html = (f"{E(corr['type'].capitalize())} published {E(fmt_date(corr['date']))}, after the authors were notified "
                     f"({doi_html(site, corr['doi'])}). {E(attrib)}")
    hist = "".join(f'<tr><td class="nowrap">{E(fmt_date(x["date"]))}</td><td>{E(x["label"])}</td></tr>' for x in rec["history"])
    vers = "".join(
        f'<tr><td class="nowrap"><a href="{site.href(page, "cases/" + rid + "/v" + ch["version"] + "/")}">v{E(ch["version"])}</a></td>'
        f'<td class="nowrap">{E(fmt_date(ch["date"]))}</td><td>{E(ch["change"])}{" <strong>Our correction.</strong>" if ch.get("our_correction") else ""}</td></tr>'
        for ch in rec["changelog"])
    chal = "".join(f"<li>{E(fmt_date(x['date']))}: {E(x['type'])} by {E(x['by'])}. {E(x['outcome'])}.</li>" for x in rec.get("challenges", []))
    files = "".join(f'<li><span class="mono">{E(f["name"])}</span></li>' for f in rec["evidence"]["files"])
    url = cfg["base_url"].rstrip("/") + f"/cases/{rid}/v{ver}/"
    cite = f"{cfg['owner']} ({rec['released'][:4]}). Case record {rid}, version {ver}: {rec['title']}. {cfg['name']}. {url}"
    bib = (f"@misc{{{rid.replace('-', '_')}_v{ver.replace('.', '_')},\n  author = {{{cfg['owner']}}},\n"
           f"  title = {{Case record {rid}, version {ver}: {rec['title']}}},\n  howpublished = {{{cfg['name']}}},\n"
           f"  year = {{{rec['released'][:4]}}},\n  url = {{{url}}}\n}}")
    frozen_note = ""
    if frozen and ver != current["version"]:
        frozen_note = (f'<p class="notice">Archived version {E(ver)}. The current version is '
                       f'<a href="{site.href(page, "cases/" + rid + "/")}">{E(current["version"])}</a>.</p>')
    demo = '<p class="notice">Fictional demonstration record.</p>' if site.c.is_sample else ""
    body = f"""
<nav class="crumbs" aria-label="Breadcrumb"><a href="{site.href(page, 'cases/')}">Cases</a> / <span class="mono">{E(rid)}</span></nav>
{frozen_note}{demo}
<div class="record">
<article class="rec-main">
  <p class="rec-id"><span class="mono">{E(rid)}</span> · version {E(ver)} · released {E(fmt_date(rec['released']))} · {E(TRACKS[rec['track']])}</p>
  <h1>{E(rec['title'])}</h1>
  <p class="lede">{E(rec['headline'])}</p>
  {''.join(render_claim(site, page, c) for c in rec['claims'])}
  <section><h2>Afterwards</h2><dl class="kv2">
    <dt>Authors</dt><dd>{E(pos_text)}</dd>
    <dt>Corrections</dt><dd>{corr_html}</dd>
    {f'<dt>Challenges and replications</dt><dd><ul>{chal}</ul></dd>' if chal else ''}
  </dl></section>
  <section><h2>History</h2><div class="table-wrap"><table class="hist"><tbody>{hist}</tbody></table></div></section>
  <section><h2>Versions</h2><div class="table-wrap"><table class="hist"><tbody>{vers}</tbody></table></div>
  <p class="note">Released versions are never edited; each keeps its own address.</p></section>
  <section><h2>AI use in this case</h2><p>{E(rec['statements']['ai_use'])}</p></section>
</article>
<aside class="rec-side" aria-label="Record details">
  <dl class="side">
    <dt>Paper</dt><dd>{citation_html(w)} {doi_html(site, w['doi'])}</dd>
    <dt>Outcome by claim</dt><dd>{outcome_list(rec)}</dd>
    <dt>Afterwards</dt><dd>{E(' · '.join(after_items(rec))) or '–'}</dd>
    <dt>Evidence package</dt><dd>{doi_html(site, rec['evidence']['package_doi'])}<br>
      <span class="small">SHA-256 <span class="mono hash" title="{E(rec['evidence']['package_sha256'])}">{E(rec['evidence']['package_sha256'][:16])}…</span>
      · {E(rec['evidence']['licence'])}</span><ul class="files">{files}</ul></dd>
    <dt id="verification">Release verification</dt><dd class="small">Signed release; record file SHA-256
      <span class="mono hash" title="{E(digest)}">{E(digest[:16])}…</span> verified at build.
      <a href="{site.href(page, f'data/records/{rid}/v{ver}.json')}">JSON</a> ·
      <a href="{site.href(page, 'methodology/')}#release">how</a></dd>
    <dt>Cite</dt><dd><p class="cite" id="cite-text">{E(cite)}</p>
      <button class="btn" type="button" data-copy="cite-text">Copy citation</button>
      <details><summary>BibTeX</summary><pre class="bibtex" id="bibtex">{E(bib)}</pre>
      <button class="btn" type="button" data-copy="bibtex">Copy BibTeX</button></details></dd>
  </dl>
</aside>
</div>
"""
    site.add(page, layout(site, page, f"{rid}: {rec['title']}", body, "cases/", rec["headline"]))


METRIC_ROWS = [
    ("M01", "Papers considered", "paper", "Papers in the programme with any screening, including metadata-only screening.", "monthly"),
    ("M02", "Papers investigated at theorem level", "paper", "Papers with at least one claim checked against a source text or deeply audited.", "monthly"),
    ("M03", "Claims investigated", "claim", "Claims checked against a source text or deeply audited.", "monthly"),
    ("M04", "Claims deeply audited", "claim", "Claims that received a deep audit.", "monthly"),
    ("M05", "Candidate defects raised", "claim", "Claims for which any check ever reported a possible defect. Never decreases.", "monthly"),
    ("M06", "Status of candidate defects", "claim", "M05 split into open, confirmed, unresolved and rejected.", "monthly"),
    ("M07", "Deep audits that found no defect", "claim", "Deeply audited claims with no candidate defect ever raised, by published-version check.", "monthly"),
    ("M08", "Confirmed: rechecked by a separate AI session", "claim", "Confirmed claims with a confirming AI recheck in a separate session.", "monthly"),
    ("M09", "Confirmed: independently reproduced by the researcher", "claim", "Re-derived by hand or with separately written code. Package reruns do not count.", "monthly"),
    ("M10", "Confirmed: verified by an external human", "claim", "Verified by someone outside the programme.", "monthly"),
    ("M11", "Confirmed: published-version check", "claim", "Confirmed claims by full, partial or no check against the published version.", "monthly"),
    ("M12", "Papers whose authors were notified", "paper", "Courtesy notices for negative audits are not counted.", "quarterly"),
    ("M13", "Authors' position on confirmed findings", "claim", "Confirmed claims in notified papers, by the authors' latest written position.", "quarterly"),
    ("M14", "Corrections published after notification", "claim", "Released records only; credited to this audit only if the correction says so.", "monthly"),
    ("M15", "Records released", "record", "Records with status published.", "monthly"),
    ("M16", "Our corrections and withdrawals", "record version", "Released versions that correct our error or withdraw a record.", "monthly"),
    ("M17", "Calibration checks", "claim", "Claims in papers with known published corrections, used to test the method. Never in totals.", "monthly"),
]


def render_definitions(site):
    page = "definitions/index.html"
    outs = "".join(f'<tr><th scope=row><span class="o {cls}">{E(lbl)}</span></th><td>{E(desc[0].upper() + desc[1:])}</td><td>{E(pub)}</td></tr>'
                   for lbl, cls, desc, pub in OUTCOME_DEFS)
    metrics = "".join(f'<tr id="m-{i.lower()}"><td class="mono">{i}</td><td>{E(l)}</td><td>{E(u)}</td><td>{E(d)}</td><td>{E(c)}</td></tr>'
                      for i, l, u, d, c in METRIC_ROWS)
    vor = "".join(f"<li>{E(v)}</li>" for v in VOR_LEVELS.values())
    body = f"""
<div class="page-head"><h1>Definitions</h1>
<p>Vocabulary used in every record and statistic. Metric definitions version {E(site.cfg['metrics_version'])}.
<a href="#outcomes">Outcomes</a> · <a href="#statuses">Statuses</a> · <a href="#checks">Checks</a> ·
<a href="#vor">Published-version check</a> · <a href="#authors">Author positions</a> · <a href="#corrections">Corrections</a> ·
<a href="#metrics">Metrics</a> · <a href="#ratios">Ratios</a></p></div>
<section id="outcomes"><h2>Outcomes</h2>
<div class="table-wrap"><table class="rtable defs"><thead><tr><th scope=col>Outcome</th><th scope=col>Meaning</th><th scope=col>Published by name</th></tr></thead><tbody>{outs}</tbody></table></div>
<p class="note">Records also say which result a defect affects (main result, secondary result, application or example, lemma or proof step) and what is explicitly <em>not</em> claimed.</p></section>
<section id="statuses"><h2>Statuses of a candidate defect</h2><dl class="kv2">
<dt id="candidate">Candidate</dt><dd>Any possible defect reported by any check. Most candidates come from AI-assisted discovery runs and are never published by name.</dd>
<dt>Open</dt><dd>Not yet settled. A candidate supported by an AI recheck but not yet checked by a human stays open.</dd>
<dt id="confirmed">Confirmed</dt><dd>At least two confirming checks of different kinds, at least one by a human, and no refuting check left unaddressed. Only confirmed defects appear in named records.</dd>
<dt>Unresolved</dt><dd>Checks were completed but did not settle the question. Never counted as rejected.</dd>
<dt>Rejected</dt><dd>A check showed the suspected defect does not exist. Counted, never named.</dd>
<dt id="withdrawn">Withdrawn</dt><dd>A released record we no longer stand behind. The page stays online with the reason.</dd></dl></section>
<section id="checks"><h2>Kinds of check</h2><dl class="kv2">
<dt>Separate AI recheck</dt><dd>An AI model in a new session re-examined the claim; <em>blind</em> if it was not given the earlier result, <em>informed</em> if it was.</dd>
<dt>Independent reproduction</dt><dd>The researcher re-derived the decisive step by hand or with separately written code. Rerunning the original package shows the package works; it is not counted as a check.</dd>
<dt id="external-human">External human verification</dt><dd>Someone outside the programme checked the finding and reported in their own name.</dd>
<dt>Written author agreement</dt><dd>The authors stated in writing that the claim as printed is erroneous.</dd>
<dt>Published correction</dt><dd>A corrigendum, erratum or public note by the authors addressing the claim.</dd></dl></section>
<section id="vor"><h2>Published-version check</h2><p>The decisive elements are the statement, every definition and assumption the finding relies on, the decisive step, and any supplement the claim depends on.</p><ul class="compact">{vor}</ul></section>
<section id="authors"><h2>Author positions</h2><p>Recorded only from written statements: agreed (the claim as printed is erroneous), partly agreed, disagree, or no substantive reply (including replies that only acknowledge receipt). Summaries are published only with the authors' consent.</p></section>
<section id="corrections"><h2>Corrections</h2><p>A correction counts as an outcome only if it was published after the authors were notified, and is described as crediting this audit only if its own text says so. Corrections published before our audit mark a finding as previously reported.</p></section>
<section id="metrics"><h2>Metrics</h2><div class="table-wrap"><table class="rtable metrics"><thead><tr><th scope=col>ID</th><th scope=col>Label</th><th scope=col>Unit</th><th scope=col>Counting rule</th><th scope=col>Updated</th></tr></thead><tbody>{metrics}</tbody></table></div>
<p class="note" id="m-m02-note">Rows linked from summary tables: <a href="#m-m02">M02</a>, <a href="#m-m05">M05</a>, <a href="#m-m07">M07</a>, <a href="#m-m12">M12</a>, <a href="#m-m14">M14</a>.</p></section>
<section id="ratios"><h2>Ratios and their limits</h2><p>A ratio is shown only when its numerator is a subset of its denominator, always as counts ("6 of 11"). No ratio uses papers or claims examined as its denominator. {E(SELECTION_STATEMENT)}</p></section>
"""
    site.add(page, layout(site, page, "Definitions", body, "definitions/", indexable=True))


def render_methodology(site):
    page = "methodology/index.html"
    fps = key_fingerprints(site.c.trust)
    keys = ", ".join(f'<span class="mono">{E(f)}</span>' for f in fps)
    preview = (" The cases on this site are fictional demonstrations signed with a throwaway demonstration key; real "
               "records will be signed with the researcher's own release key.") if site.c.is_sample else ""
    steps = "".join(f"<li><strong>{E(a)}.</strong> {E(b)}</li>" for a, b in METHOD_STEPS)
    body = f"""
<div class="page-head"><h1>Methodology</h1>
<p>How a published claim becomes a case record. Methodology version {E(site.cfg['methodology_version'])}.</p></div>
<div class="cols2">
<section><h2>Question</h2><p>Does a published theoretical claim follow from the assumptions stated with it? The claim may be
a theorem, proposition, lemma, corollary, equilibrium characterization, algorithmic guarantee or another mathematical
result in economics and related fields: game theory, mechanism design, matching and social choice, optimization,
econometric theory and probability.</p>
<h2>Process</h2><ol class="compact">{steps}</ol></section>
<section><h2 id="standard">Confirmation standard</h2><p class="box">A suspected defect is <strong>confirmed</strong> only
after at least two confirming checks of different kinds (a separate AI recheck, an independent reproduction by the
researcher, an external human verification, written agreement by the authors), at least one of them by a human, and no
refuting check left unaddressed. Rerunning the original evidence package does not count.</p>
<h2>Outcomes</h2><p>Confirmed defects are classified as <span class="o o-false">false as printed</span>,
<span class="o o-incomplete">proof incomplete</span>, <span class="o o-repair">repairable gap</span> or
<span class="o o-assump">missing assumption</span>, with the result they affect and an explicit list of what is not
claimed. Deep audits that find nothing are published as <span class="o o-none">no defect found</span>.
<a href="{site.href(page, 'definitions/')}#outcomes">Definitions</a>.</p>
<h2>Published version</h2><p>Findings are checked against the version of record. Each record states whether every
decisive element was checked on rendered pages (full), only partly (partial), or only in a preprint.</p></section>
</div>
<div class="cols2">
<section><h2 id="negative">Negative audits</h2><p>{E(NEGATIVE_CAVEAT_GENERAL)} Each states its search scope and limits.
Only deep audits are published by name; lighter screens appear only in counts.</p>
<h2 id="ai">How AI is used</h2><p>AI models search for counterexamples, write test code and recheck results in separate
sessions. They do not decide what is published. Every published finding has also been checked by a human, and the
researcher makes every editorial decision. Each record states how AI was used in that case.</p>
<h2>Selection and statistics</h2><p>{E(SELECTION_STATEMENT)} Statistics are pipeline counts with stated units; small counts
that could identify an unpublished case are suppressed, and breakdowns of findings by field use released records only.</p></section>
<section><h2 id="authors">Authors first</h2><p>Authors are contacted privately before anything about their paper is published.
A named finding becomes eligible for publication after a published correction, after the authors agree to a public
record, or 90 days after contact without a substantive reply. Eligibility is not a deadline: each release also needs
the confirmation standard, a final check against the published version, consideration of any reply, and the
researcher's approval. Disputed findings wait for an additional check. Where a finding may become a journal comment,
the journal's policies come first.</p>
<h2 id="release">How releases are approved</h2><p>Every record version, statistics snapshot and update list is published
only if the researcher has signed a short release statement containing the SHA-256 of its exact data file. The site
build verifies each signature and refuses anything unsigned, altered after signing, or signed by another key.{E(preview)}</p>
<p class="small">Trusted key fingerprint(s): {keys}</p>
<h2>What we do not do</h2><ul class="compact"><li>Publish anonymous or unchecked allegations.</li>
<li>Rank journals, fields or authors.</li><li>Report error rates for published research.</li>
<li>Name papers whose candidates were rejected or remain unresolved.</li></ul></section>
</div>
"""
    site.add(page, layout(site, page, "Methodology", body, "methodology/", indexable=True))


def activity_svg(activity):
    kinds = [("discovery", "Discovery runs", "a1"), ("hostile_validation", "Separate rechecks", "a2"),
             ("source_lock", "Published-version checks", "a3"), ("package_rerun", "Package reruns", "a4")]
    w, h, pl, pb, pt = 560, 170, 28, 22, 8
    n = len(activity)
    mx = max(sum(m[k] for k, _, _ in kinds) for m in activity) or 1
    step = (w - pl - 6) / n
    bw = step * 0.55
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
            els.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{hh:.1f}" class="{cls}"/>')
        els.append(f'<text x="{x + bw / 2:.1f}" y="{h - 6}" class="axis" text-anchor="middle">{MONTH_NAMES[int(m["month"][5:]) - 1][:3]}</text>')
    legend = "".join(f'<li><span class="sw {cls}"></span>{E(lbl)}</li>' for _, lbl, cls in kinds)
    rows = "".join(f"<tr><th scope=row>{E(fmt_date(m['month']))}</th>" + "".join(f'<td class="num">{m[k]}</td>' for k, _, _ in kinds) + "</tr>"
                   for m in activity)
    head = "".join(f'<th scope=col class="num">{E(lbl)}</th>' for _, lbl, _ in kinds)
    return (f'<figure class="chart"><svg viewBox="0 0 {w} {h}" role="img" aria-label="Research activity by month">{"".join(els)}</svg>'
            f'<ul class="legend">{legend}</ul><details><summary>Data</summary><div class="table-wrap"><table class="rtable">'
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
            return (f'<tr><td class="mono"><a href="{d}#m-{mid.lower()}">{mid}</a></td><td>{E(label)}</td>'
                    f'<td class="num">{value}</td><td class="muted">{detail}</td></tr>')
        examined = "".join([
            row("M01", "Papers considered", t["M01"], "includes metadata-only screening"),
            row("M02", "Papers investigated at theorem level", t["M02"]),
            row("M03", "Claims investigated", t["M03"]),
            row("M04", "Claims deeply audited", t["M04"])])
        found = "".join([
            row("M05", "Candidate defects raised", t["M05"], "cumulative"),
            row("M06", "Confirmed", conf, f"of {t['M05']} candidates; {m06['confirmed_previously_reported']} previously reported elsewhere"),
            row("M06", "Rejected after checking", m06["rejected"], f"of {t['M05']}"),
            row("M06", "Unresolved", m06["unresolved"], f"of {t['M05']}; " + E(", ".join(f"{v} {k.replace('_', ' ')}" for k, v in snap['unresolved_reasons'].items()))),
            row("M06", "Open", m06["open"], f"of {t['M05']}; {m06['open_ai_supported']} AI-supported, awaiting a human check"),
            row("M07", "Deep audits that found no defect", m07,
                f"published-version check: {t['M07']['vor_full']} full, {t['M07']['vor_partial']} partial, {t['M07']['vor_none']} preprint only")])
        survived = "".join([
            row("M08", "Rechecked by a separate AI session", f"{sum(t['M08'].values())} of {conf}", f"{t['M08']['blind']} blind, {t['M08']['informed']} informed"),
            row("M09", "Independently reproduced by the researcher", f"{t['M09']} of {conf}"),
            row("M10", "Verified by an external human", f"{t['M10']} of {conf}"),
            row("M11", "Published-version check", f"{t['M11']['full']} / {t['M11']['partial']} / {t['M11']['none']}", f"full / partial / none, of {conf}")])
        after = "".join([
            row("M12", "Papers whose authors were notified", t["M12"], f"as of {E(fmt_date(snap['as_of']))}"),
            row("M13", "Authors agreed", f"{m13['agreed']} of {pop13}", "confirmed defects in notified papers"),
            row("M13", "Authors partly agreed", f"{m13['partly_agreed']} of {pop13}"),
            row("M13", "Authors disagree", f"{m13['disagreed']} of {pop13}"),
            row("M13", "No substantive reply yet", f"{m13['none_yet']} of {pop13}", "includes receipt-only replies"),
            row("M14", "Corrections after notification", corr,
                f"released records only; {rs['corrections']['credits_programme']} credit this audit, {rs['corrections']['none_stated']} state no attribution")])
        publ = "".join([
            row("M15", "Records released", len(site.c.latest_all(snap["as_of"]))),
            row("M16", "Our corrections and withdrawals", rs["our_corrections"]),
            row("M17", "Calibration claims checked", t["M17"]["checked"], f"{t['M17']['known_errors_refound']} known errors re-found; not in totals")])
        ebt = snap.get("examined_by_track", {})
        trk = "".join(
            f"<tr><th scope=row>{E(TRACK_SHORT[k])}</th>"
            f"<td class=num data-label=\"Papers considered\">{'–' if ebt.get('M01', {}).get(k) is None else ebt['M01'][k]}</td>"
            f"<td class=num data-label=\"Claims investigated\">{'–' if ebt.get('M03', {}).get(k) is None else ebt['M03'][k]}</td>"
            f"<td class=num data-label=\"Confirmed defects*\">{rs['outcome_by_track'][k]['confirmed']}</td>"
            f"<td class=num data-label=\"No defect found*\">{rs['outcome_by_track'][k]['negative']}</td></tr>"
            for k in TRACKS)
        archive = " · ".join(
            f'<a href="{site.href(page, "statistics/" + ("" if j == len(snaps) - 1 else s["snapshot"] + "/"))}">{E(s["snapshot"])}</a>'
            for j, s in enumerate(snaps))
        demo = '<p class="notice">Demonstration statistics. All figures are fictional.</p>' if site.c.is_sample else ""
        older = "" if latest else f'<p class="notice">Archived snapshot. <a href="{site.href(page, "statistics/")}">Latest</a>.</p>'
        thead = "<thead><tr><th scope=col>ID</th><th scope=col>Measure</th><th scope=col class=num>Value</th><th scope=col>Detail</th></tr></thead>"

        def table(rows_html):
            return f'<div class="table-wrap"><table class="rtable stats mtable">{thead}<tbody>{rows_html}</tbody></table></div>'
        body = f"""
{older}{demo}
<div class="page-head"><h1>Statistics</h1>
<p>Snapshot {E(snap['snapshot'])}, as of {E(fmt_date(snap['as_of']))}, released {E(fmt_date(snap['released']))};
metric definitions v{E(snap['metrics_version'])}. Snapshots: {archive} · <a href="{site.href(page, f"data/snapshots/{snap['snapshot']}.json")}">JSON</a></p>
<p class="box"><strong>How to read these numbers.</strong> {E(SELECTION_STATEMENT)} {E(snap['programme']['description'])}</p></div>
<div class="cols2">
<section><h2>What we examined</h2>{table(examined)}<h2>What we found</h2>{table(found)}</section>
<section><h2>What survived challenge</h2>{table(survived)}<h2>What happened afterwards</h2>{table(after)}
<h2>Publication and self-correction</h2>{table(publ)}</section>
</div>
<div class="cols2">
<section><h2>By field</h2><div class="table-wrap"><table class="rtable stats ftable"><thead><tr><th scope=col>Field</th>
<th scope=col class=num>Papers considered</th><th scope=col class=num>Claims investigated</th>
<th scope=col class=num>Confirmed defects*</th><th scope=col class=num>No defect found*</th></tr></thead>
<tbody>{trk}</tbody></table></div>
<p class="note">"–" marks a suppressed count: counts that include unreleased work are suppressed until no suppressed value
can be narrowed to fewer than three possibilities using everything published, including earlier snapshots. Findings by
field (*) use released records only. Papers and claims considered are recomputed quarterly.</p></section>
<section><h2>Activity by month</h2>{activity_svg(snap['activity'])}</section>
</div>
"""
        site.add(page, layout(site, page, "Statistics" if latest else f"Statistics {snap['snapshot']}", body,
                              "statistics/", "Programme statistics"))


def render_updates(site):
    page = "updates/index.html"
    items = site.c.updates.get("items", [])

    def link_for(x):
        if x in site.c.records:
            return f'<a class="mono" href="{site.href(page, "cases/" + x + "/")}">{E(x)}</a>'
        if x in {"statistics", "methodology"}:
            return f'<a href="{site.href(page, x + "/")}">{E(x.capitalize())}</a>'
        return ""
    trs = "".join(f'<tr><td class="nowrap">{E(fmt_date(u["date"]))}</td><td class="nowrap muted">{E(u["type"])}</td>'
                  f'<td><strong>{E(u["title"])}</strong>. {E(u["body"])} {" · ".join(filter(None, map(link_for, u.get("links", []))))}</td></tr>'
                  for u in items)
    demo = '<p class="notice">The updates listed are fictional demonstrations. The policies below are real.</p>' if site.c.is_sample else ""
    body = f"""
<div class="page-head"><h1>Updates and policies</h1><p>Releases, revisions, corrections and statistics snapshots, newest first
(<a href="{site.href(page, 'feed.xml')}">Atom feed</a>), followed by the policies that govern them.</p></div>
{demo}
<section><h2>Updates</h2><div class="table-wrap"><table class="rtable hist"><tbody>{trs}</tbody></table></div></section>
<div class="cols2">
<section><h2 id="author-responses">Author responses</h2><ul class="compact">
<li>Authors are contacted privately before anything about their paper is published, and are offered space for a reply.</li>
<li>A reply is published as the authors' own words, a summary they approve, or a link to their own statement. Nothing from
private correspondence is published without written consent.</li>
<li>If the authors dispute a finding, it is not published until an additional independent check has been done.</li>
<li>Authors' positions are recorded only from written statements; a reply that only acknowledges receipt is not a position.</li>
<li>Authors of a paper with a negative deep audit receive a courtesy notice when the record is approved.</li></ul></section>
<section><h2 id="corrections">Corrections and withdrawals</h2><ul class="compact">
<li>Released versions are never edited. Every change is a new version with a dated change note; earlier versions stay online.</li>
<li>Our own errors are labelled as our corrections. If the headline finding changes, the major version number changes and
older versions point to the current one.</li>
<li>A finding we no longer stand behind is withdrawn: the record stays online with the reason, and the evidence archive
records the withdrawal.</li>
<li>A published correction by the authors or journal is added to the record. It is described as crediting this audit only if
it says so.</li>
<li>Material published by mistake (for example, private information) is removed, any exposed credential is revoked, and a short
notice records the removal without repeating the content.</li></ul>
<h2 id="challenges">Challenges and replications</h2><p>Anyone may challenge or replicate a published record. Substantive
challenges are checked and their outcome is added to the record; replications are credited by name with consent.
Allegations about papers not on this site should not be sent through public channels.</p></section>
</div>
"""
    site.add(page, layout(site, page, "Updates and policies", body, "updates/", indexable=not site.c.is_sample))
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
              "published. Real records will appear here only after the steps described in the methodology, including the "
              "researcher's signed approval.") if site.c.is_sample else ""
    body = f"""
<div class="page-head"><h1>About</h1><p>{E(cfg['name'])}: {E(cfg['descriptor'].rstrip('.').lower())}. {E(cfg['tagline'])}</p></div>
<div class="cols2">
<section><h2>Purpose</h2><p>{E(cfg['name'])} investigates whether published theoretical claims actually follow from their
stated assumptions. Sometimes we find errors, sometimes missing assumptions or proof gaps that can be repaired, and
sometimes the published claim survives serious attempts to challenge it. All of these are recorded. Proofs are hard,
and correcting them is part of scholarship; a record is not a verdict on the people who wrote the paper.</p>
{f'<h2>Status</h2><p class="box">{E(status)}</p>' if status else ''}
<h2>Who</h2><p>{E(cfg['owner'])}. {cfg['owner_bio']}</p></section>
<section><h2 id="disclosure">Disclosure</h2><p><strong>Human-led, AI-assisted, independent research.</strong> AI models are
used for discovery and for separate rechecks. A finding is published only after a human check, and the researcher makes
every editorial decision. {E(cfg['name'])} is independent personal research: it is not conducted on behalf of any
employer, and it is not affiliated with, commissioned by or endorsed by the journals, publishers or authors whose work is
examined. Records are current assessments, not final authority.</p>
<h2>Contact</h2><p>{cfg['contact_html']}</p>
<h2>Licence, citation and source</h2><p>Text and data: CC BY 4.0. Code: MIT. Each record shows how to cite it. Cite the
project as: {E(cfg['owner'])}. <em>{E(cfg['name'])}: {E(cfg['descriptor'].rstrip('.').lower())}</em>. {E(cfg['base_url'])}.
Source code and release history: <a href="{E(cfg['repository_url'])}">{E(cfg['repository_url'].replace('https://', ''))}</a>.</p></section>
</div>
"""
    site.add(page, layout(site, page, "About", body, "about/", indexable=True))


def render_404(site):
    page = "404.html"
    body = (f'<div class="page-head"><h1>Page not found</h1><p>Released records keep their addresses. Try the '
            f'<a href="{site.href(page, "cases/")}">case index</a>.</p></div>')
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
