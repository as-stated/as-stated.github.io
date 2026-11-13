"""Generate test data at run time. Nothing here is real, and none of it is ever written to the repository.

make_project() builds a throwaway copy of the site in a temporary folder, with records that exercise every
kind of finding, author position, correction and version through the real published channel. Output is
deterministic: the same code always produces the same bytes.
"""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AI, REPRO, EXTERNAL, AUTHORS = "ai_recheck", "independent_reproduction", "external_human", "author_agreement"
FALSE, BUILD, ASSUME, GAP, CITE = ("statement_false", "construction_or_algorithm_fails", "missing_or_hidden_assumption",
                                   "proof_gap_repairable", "citation_or_dependency_gap")
MAIN, LEMMA, APP, SECOND = "main_result", "lemma_or_proof_step", "application_or_example", "secondary_result"
MD, GT, MS = "mechanism_design", "game_theory", "matching_social_choice"


def digest(label):
    return hashlib.sha256(("test:" + label).encode()).hexdigest()


def check(kind, session=None, month="2000-01"):
    c = {"kind": kind, "date": month, "result": "confirms", "detail": f"Test check of kind {kind}."}
    if session:
        c["session"] = session
    return c


def defect(defect_class, affects, checks, repair="none_proposed", previously_reported=False):
    result = {"outcome": "defect_found", "candidate_status": "confirmed", "defect_class": defect_class, "affects": affects,
              "depth": "deep_audit", "summary": "Test finding summary.", "witness": "Test witness.", "tested": "Test scope.",
              "not_claimed": ["Test statement of what is not claimed."], "repair": repair}
    if repair != "none_proposed":
        result["repair_note"] = "Test repair note."
    if previously_reported:
        result["previously_reported"] = True
    return result, checks


def negative(checks=()):
    return {"outcome": "no_defect_found", "depth": "deep_audit", "summary": "Test negative summary.",
            "search_scope": "Test search scope.", "limits": "Test limits."}, list(checks)


def unresolved():
    return {"outcome": "unresolved", "depth": "deep_audit", "unresolved_reason": "source_limited", "summary": "Test open question.",
            "detail": "Test description of why it is open.", "limits": "Test limits. Not counted as a defect."}, []


def claim(n, index, label, kind, role, level, spec, novelty="No earlier report found."):
    result, checks = spec
    return {"id": f"c{index}", "label": f"{label} {n}.{index}", "kind": kind, "role": role, "page": str(index),
            "gist": f"Test gist {n}.{index}.", "statement": f"Test statement {n}.{index}.", "conditions": [f"Test condition {n}.{index}."],
            "quantifiers": "Test quantifiers.", "result": result,
            "vor_check": {"level": level, "pages": str(index), "detail": "Test source check."}, "checks": list(checks),
            "reproduction": {"result": "pass", "detail": "Test reproduction."}, "novelty": novelty}


def record(n, released, track, claims, position="none_yet", version="1.0", correction=None, changelog=None, challenges=(), position_summary=None):
    kind = "defect" if any(c["result"]["outcome"] == "defect_found" for c in claims) else "negative"
    work = {"authors": [f"Author A{n}", f"Author B{n}"], "title": f"Test work {n}", "venue": "Test Venue", "year": 2000,
            "volume": "1", "pages": "1-2", "doi": f"10.0000/test.{n:04d}"}
    files = ["README.md", "check.py"]
    return {
        "public_id": f"TEST-2000-{n:03d}", "version": version, "released": released, "status": "published", "sample": False,
        "kind": kind, "track": track, "title": f"Test paper {n}", "headline": f"Test headline {n}.", "work": work, "claims": claims,
        "author_position": {"position": position, "summary": position_summary}, "correction": correction,
        "evidence": {"package_doi": f"10.0000/test-evidence.{n:04d}", "package_sha256": digest(f"package-{n}"), "licence": "CC BY 4.0",
                     "files": [{"name": f, "sha256": digest(f"{n}-{f}")} for f in files]},
        "history": [{"date": "2000-01", "type": "audit", "label": "Test audit completed"},
                    {"date": released, "type": "release", "label": f"Record version {version} released"}],
        "challenges": list(challenges),
        "changelog": changelog or [{"version": "1.0", "date": released, "change": "First release."}],
        "statements": {"ai_use": "Test statement of how AI was used."},
    }


def records():
    blind, informed = check(AI, "blind"), check(AI, "informed")
    repro, ext, auth = check(REPRO), check(EXTERNAL), check(AUTHORS)
    correction = {"type": "corrigendum", "doi": "10.0000/test.0002c", "date": "2000-04-14", "relation": "after_notification",
                  "attribution": "credits_programme", "claims": ["c1"], "note": "Test correction note."}
    c2 = lambda ch: claim(2, 1, "Theorem", "construction", "main", "full", defect(BUILD, MAIN, ch, "repair_checked"))
    c2_neg = claim(2, 2, "Repair", "construction", "repair", "full", negative())
    log2 = [{"version": "1.0", "date": "2000-02-18", "change": "First release."},
            {"version": "1.1", "date": "2000-04-30", "change": "Added the correction."},
            {"version": "1.2", "date": "2000-06-09", "change": "Added an external check."}]
    c5 = lambda: [claim(5, 1, "Theorem", "theorem", "main", "full", negative()), claim(5, 2, "Lemma", "lemma", "supporting", "full", negative())]
    log5 = [{"version": "1.0", "date": "2000-03-02", "change": "First release."},
            {"version": "1.1", "date": "2000-03-29", "our_correction": True, "change": "Test correction of our own record."}]
    c11 = lambda ch1, ch2: [claim(11, 1, "Theorem", "theorem", "main", "partial", defect(FALSE, MAIN, ch1, "local_repair_proposed")),
                            claim(11, 2, "Lemma", "lemma", "supporting", "partial", defect(ASSUME, LEMMA, ch2, "local_repair_proposed"))]
    log11 = [{"version": "1.0", "date": "2000-03-24", "change": "First release."}, {"version": "1.1", "date": "2000-05-27", "change": "Added the authors' position."}]
    return [
        record(1, "2000-05-20", MD, [claim(1, 1, "Lemma", "lemma", "supporting", "partial", defect(FALSE, LEMMA, [blind, repro])),
                                     claim(1, 2, "Lemma", "lemma", "supporting", "partial", defect(FALSE, LEMMA, [informed, repro])),
                                     claim(1, 3, "Application", "application", "application", "partial", defect(ASSUME, APP, [repro, blind], "local_repair_proposed")),
                                     claim(1, 4, "Application", "application", "application", "partial", defect(ASSUME, APP, [repro, blind], "local_repair_proposed"))]),
        record(2, "2000-02-18", MD, [c2([blind, repro, auth])], "agrees", changelog=log2[:1], position_summary="Test author position."),
        record(2, "2000-04-30", MD, [c2([blind, repro, auth]), c2_neg], "agrees", "1.1", correction, log2[:2], position_summary="Test author position."),
        record(2, "2000-06-09", MD, [c2([blind, repro, auth, ext]), c2_neg], "agrees", "1.2", correction, log2,
               [{"type": "replication", "date": "2000-06-02", "by": "Test Person", "outcome": "Confirms the finding", "response": None}], "Test author position."),
        record(3, "2000-06-24", GT, [claim(3, 1, "Proposition", "proposition", "main", "partial", defect(FALSE, MAIN, [blind, repro, ext])),
                                     claim(3, 2, "Algorithm", "algorithm", "supporting", "partial", defect(BUILD, SECOND, [informed, repro]))], "disagrees", position_summary="Test author position."),
        record(4, "2000-04-08", MS, [claim(4, 1, "Theorem", "theorem", "main", "full", negative()),
                                     claim(4, 2, "Lemma", "lemma", "supporting", "partial", defect(CITE, LEMMA, [repro, blind]))], "partly_agrees", position_summary="Test author position."),
        record(5, "2000-03-02", MS, c5(), "not_contacted", changelog=log5[:1]),
        record(5, "2000-03-29", MS, c5(), "not_contacted", "1.1", changelog=log5),
        record(6, "2000-01-26", MS, [claim(6, 1, "Theorem", "theorem", "main", "partial", negative()), claim(6, 2, "Theorem", "theorem", "main", "partial", negative())], "not_contacted"),
        record(7, "2000-05-06", GT, [claim(7, 1, "Theorem", "theorem", "main", "full", negative()), claim(7, 2, "Remark", "remark", "supporting", "none", unresolved())], "not_contacted"),
        record(8, "2000-02-10", MD, [claim(8, 1, "Theorem", "theorem", "main", "full", negative()), claim(8, 2, "Corollary", "corollary", "supporting", "full", negative())], "not_contacted"),
        record(9, "2000-03-17", GT, [claim(9, 1, "Proposition", "proposition", "main", "partial", negative()), claim(9, 2, "Proposition", "proposition", "supporting", "partial", negative())], "not_contacted"),
        record(10, "2000-04-22", MD, [claim(10, 1, "Theorem", "theorem", "main", "full", negative([blind])), claim(10, 2, "Theorem", "theorem", "main", "full", negative([blind])),
                                      claim(10, 3, "Lemma", "lemma", "supporting", "full", defect(GAP, LEMMA, [repro, auth], "repair_proved"))], "agrees", position_summary="Test author position."),
        record(11, "2000-03-24", GT, c11([blind, repro], [informed, repro]), changelog=log11[:1]),
        record(11, "2000-05-27", GT, c11([blind, repro, auth], [informed, repro, auth]), "agrees", "1.1", changelog=log11, position_summary="Test author position."),
        record(12, "2000-02-24", GT, [claim(12, 1, "Corollary", "corollary", "secondary", "partial", defect(FALSE, SECOND, [repro, blind], previously_reported=True), novelty="Previously reported.")],
               "previously_corrected", correction={"type": "corrigendum", "doi": "10.0000/test.0012c", "date": "1999", "relation": "before_audit",
                                                   "attribution": "none_stated", "claims": ["c1"], "note": "Test earlier correction."}),
        record(13, "2000-06-17", MD, [claim(13, 1, "Remark", "remark", "supporting", "partial", defect(GAP, SECOND, [repro, blind], "repair_checked")),
                                      claim(13, 2, "Lemma", "lemma", "supporting", "none", unresolved())]),
        record(14, "2000-01-26", MS, [claim(14, 1, "Theorem", "theorem", "main", "partial", negative()), claim(14, 2, "Theorem", "theorem", "main", "partial", negative())], "not_contacted"),
        record(15, "2000-05-13", GT, [claim(15, 1, "Proposition", "proposition", "main", "full", defect(FALSE, MAIN, [blind, repro]))]),
        record(16, "2000-06-03", GT, [claim(16, 1, "Theorem", "theorem", "main", "partial", defect(FALSE, MAIN, [blind, repro])),
                                      claim(16, 2, "Lemma", "lemma", "supporting", "partial", defect(FALSE, LEMMA, [informed, repro])),
                                      claim(16, 3, "Theorem", "theorem", "main", "partial", defect(FALSE, MAIN, [blind, repro]))]),
        record(17, "2000-04-15", GT, [claim(17, 1, "Algorithm", "algorithm", "main", "full", defect(BUILD, MAIN, [repro, auth]))], "agrees", position_summary="Test author position."),
        record(18, "2000-03-10", GT, [claim(18, 1, "Theorem", "theorem", "main", "full", negative())], "not_contacted"),
    ]


# ---------------------------------------------------------------- schema 2 (open and confirmed findings, math, responses)
def ev(kind, date="2000-01", session=None, identity=None):
    e = {"type": kind, "date": date, "detail": f"Test detail for {kind}, with \\(y_1\\) checked."}
    if session:
        e["session"] = session
    if identity:
        e["identity"] = identity
    return e


def response(position, counts=False, basis="none", responder=None, covers=None, assessment=None):
    r = {"position": position, "counts": counts, "basis": basis}
    if position in {"agrees", "partly_agrees", "disagrees"}:
        r["responder"] = responder or "all"
        r["covers"] = covers or "Test covers statement with \\(P_i\\)."
    if assessment:
        r["assessment"] = assessment
    return r


def defect2(n, index, status, evidence, response_, defect_class=FALSE, affects=MAIN, repair="none_proposed", level="partial"):
    result = {"outcome": "defect_found", "status": status, "defect_class": defect_class, "affects": affects,
              "depth": "deep_audit", "summary": f"Test summary {n}.{index} with \\(P_{index}\\) failing.",
              "witness": f"Test witness \\(x_{index} = 1\\) and \\[\\frac{{1}}{{1+|y_2|}} < 1.\\]",
              "argument": f"Test argument {n}.{index}: \\(\\mathbb{{R}}^n\\) is not compact.",
              "not_claimed": [f"Test non-claim {n}.{index} about \\(T\\)."], "repair": repair}
    if repair != "none_proposed":
        result["repair_note"] = f"Test repair note \\(\\varnothing\\)."
    return {"id": f"c{index}", "label": f"Theorem {n}.{index}", "kind": "theorem", "role": "main", "page": str(index),
            "gist": f"Test gist with \\(P_{index}\\).", "statement": f"If \\(P_{index}\\) has open graph, then \\(X\\) holds.",
            "conditions": [f"Test condition \\(x_{index} \\ge 0\\)."], "quantifiers": "Test quantifiers.",
            "result": result, "vor_check": {"level": level, "pages": str(index), "detail": "Test source check."},
            "evidence": list(evidence), "author_response": response_}


def record2(n, released, track, claims, related=(), changelog=None):
    kind = "defect" if any(c["result"]["outcome"] == "defect_found" for c in claims) else "negative"
    work = {"authors": [f"Author A{n}", f"Author B{n}"], "title": f"Test work {n}", "venue": "Test Venue", "year": 2000,
            "volume": "1", "pages": "1-2", "doi": f"10.0000/test.{n:04d}"}
    return {
        "public_id": f"TEST-2000-{n:03d}", "version": "1.0", "schema": 2, "released": released, "status": "published",
        "sample": False, "kind": kind, "track": track, "title": f"Test paper {n}", "headline": f"Test headline {n}.",
        "work": work, "claims": claims, "correction": None, "related": list(related),
        "evidence": {"package_doi": None, "package_sha256": None, "licence": "No public evidence package released.", "files": []},
        "history": [{"date": "2000-01", "type": "audit", "label": "Test audit completed"},
                    {"date": released, "type": "release", "label": "Record version 1.0 released"}],
        "challenges": [], "changelog": changelog or [{"version": "1.0", "date": released, "change": "First release."}],
        "statements": {"ai_use": "Test statement of how AI was used."},
    }


def records_v2():
    """Schema-2 records: an Open finding on AI evidence alone with no reply, a Confirmed finding with a counted written
    agreement, an Open finding the authors disagree with, an Open finding with an agreement that does not count, and a
    negative audit beside an unresolved claim. Every math field contains \\( \\) or \\[ \\] mathematics."""
    related = [{"type": "related_work", "citation": "Test follow-up paper (2001).", "doi": "10.0000/followup.0001",
                "note": "Test note."}]
    return [
        record2(19, "2000-06-01", GT, [defect2(19, 1, "open", [ev("hostile_ai_recheck", session="informed")], response("no_reply"))]),
        record2(20, "2000-06-02", MD, [defect2(20, 1, "confirmed",
                                               [ev("hostile_ai_recheck", session="blind"), ev("researcher_reproduction")],
                                               response("agrees", True, "original", "one_of_two"), BUILD, MAIN, "local_repair_proposed")],
                related=related),
        record2(21, "2000-06-03", GT, [defect2(21, 1, "open", [ev("hostile_ai_recheck", session="informed")],
                                               response("disagrees", responder="all", assessment="The counterargument fails at \\(p=1/2\\)."))]),
        record2(22, "2000-06-04", MS, [defect2(22, 1, "open", [ev("hostile_ai_recheck", session="blind")],
                                               response("agrees", False, "secondary_record", "some"), FALSE, SECOND)]),
        record2(23, "2000-06-05", MS, [
            {"id": "c1", "label": "Theorem 23.1", "kind": "theorem", "role": "main", "page": "1", "gist": "Negative gist.",
             "statement": "For every \\(n\\), \\(\\sum_{i=1}^n i = n(n+1)/2\\).", "conditions": [], "quantifiers": "Test quantifiers.",
             "result": {"outcome": "no_defect_found", "depth": "deep_audit", "summary": "No defect in the stated scope.",
                        "search_scope": "Test scope \\(n \\le 10\\).", "limits": "Test limits."},
             "vor_check": {"level": "full", "pages": "1", "detail": "Test source check."}, "evidence": [],
             "author_response": response("reviewing")},
            {"id": "c2", "label": "Lemma 23.2", "kind": "lemma", "role": "supporting", "page": "2", "gist": "Unresolved gist.",
             "statement": "Test unresolved statement \\(Y\\).", "conditions": [], "quantifiers": "Test quantifiers.",
             "result": {"outcome": "unresolved", "unresolved_reason": "source_limited", "summary": "Not settled.",
                        "detail": "The needed version is not available.", "limits": "Not counted as a defect."},
             "vor_check": {"level": "none", "pages": "2", "detail": "Test source check."}, "evidence": [],
             "author_response": response("not_contacted")},
        ]),
    ]


class _Records:
    """Just enough of build.Content for released_stats."""

    def __init__(self, items):
        self.records = {}
        for r in items:
            self.records.setdefault(r["public_id"], []).append(r)
        for versions in self.records.values():
            versions.sort(key=lambda r: tuple(int(x) for x in r["version"].split(".")))

    def latest_all(self, as_of=None):
        out = []
        for rid in sorted(self.records):
            versions = [r for r in self.records[rid] if as_of is None or r["released"] <= as_of]
            if versions:
                out.append(versions[-1])
        return out


UNRELEASED = {  # work on top of what released records show, so snapshots exceed the released counts
    "2000-03": dict(screened=24, papers=4, claims=7, deep=5, open=5, open_ai=4, rejected=3, unres=1, neg_full=1, neg_part=2, notified=3),
    "2000-06": dict(screened=31, papers=5, claims=9, deep=6, open=8, open_ai=7, rejected=4, unres=2, neg_full=1, neg_part=3, notified=4),
}
ACTIVITY = [{"month": f"2000-{m:02d}", "discovery": 7 - m, "hostile_validation": 4, "source_lock": 2, "package_rerun": 2} for m in range(1, 7)]


def snapshot(build, items, name, as_of, released):
    rs = build.released_stats(_Records(items), as_of)
    x = UNRELEASED[name]
    conf = rs["confirmed"]
    totals = {
        "M01": rs["papers"] + x["screened"], "M02": rs["papers"] + x["papers"], "M03": rs["claims"] + x["claims"], "M04": rs["deep"] + x["deep"],
        "M05": conf + rs["open"] + rs["unresolved"] + x["unres"] + x["open"] + x["rejected"],
        "M06": {"open": rs["open"] + x["open"], "confirmed": conf, "unresolved": rs["unresolved"] + x["unres"], "rejected": x["rejected"],
                "open_ai_supported": x["open_ai"], "confirmed_previously_reported": rs["previously_reported"]},
        "M07": {"vor_full": rs["vor_neg"]["full"] + x["neg_full"], "vor_partial": rs["vor_neg"]["partial"] + x["neg_part"], "vor_none": rs["vor_neg"]["none"]},
        "M08": {"blind": rs["ai_blind"], "informed": rs["ai_informed"]}, "M09": rs["indep"], "M10": rs["external"], "M11": dict(rs["vor_conf"]),
        "M12": rs["notified"] + x["notified"],
        "M13": {"agreed": rs["positions"]["agreed"], "partly_agreed": rs["positions"]["partly_agreed"],
                "disagreed": rs["positions"]["disagreed"], "none_yet": rs["positions"]["none_yet"]},
        "M17": {"checked": rs["calibration"], "known_errors_refound": rs["calibration"]},
    }
    keys = list(build.TRACKS)
    m01 = {t: rs["papers_by_track"][t] for t in keys}
    shares = [x["screened"] // 2, x["screened"] // 4]
    m01[keys[0]] += shares[0]
    m01[keys[1]] += shares[1]
    m01[keys[2]] += x["screened"] - sum(shares)
    by_track = {"M01": m01}
    m03 = {t: rs["claims_by_track"][t] for t in keys}
    m03[keys[0]] += x["claims"] // 2
    m03[keys[1]] += x["claims"] - x["claims"] // 2
    if all(v >= 5 for v in m03.values()):
        by_track["M03"] = m03
    return {"snapshot": name, "as_of": as_of, "released": released, "metrics_version": "1.1", "sample": False,
            "programme": {"id": "test-programme", "description": "Test programme description."}, "totals": totals,
            "unresolved_reasons": {"source_limited": rs["unresolved"] + x["unres"]}, "examined_by_track": by_track,
            "activity": [a for a in ACTIVITY if a["month"] <= as_of[:7]]}


def updates(items):
    log = [{"date": r["released"], "type": "release", "title": f"{r['public_id']} version {r['version']}", "body": r["headline"], "links": [r["public_id"]]} for r in items]
    log.append({"date": "2000-07-05", "type": "snapshot", "title": "Test snapshot", "body": "Test snapshot note.", "links": ["statistics"]})
    log.sort(key=lambda u: (u["date"], u["title"]), reverse=True)
    return {"sample": False, "updated": log[0]["date"], "items": log}


def _dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def write_manifests(build, root):
    """Write the exact release manifest for every data file in a test project."""
    croot = root / "content" / "published"
    releases = croot / "releases"
    if releases.exists():
        shutil.rmtree(releases)
    releases.mkdir(parents=True)
    entries = [("record", f.parent.name, f.stem[1:], f) for f in sorted((croot / "records").glob("*/v*.json"))]
    entries += [("snapshot", f.stem, "1", f) for f in sorted((croot / "snapshots").glob("*.json"))]
    if (croot / "updates.json").exists():
        entries.append(("updates", "updates", "1", croot / "updates.json"))
    for kind, rid, version, path in entries:
        statement = build.release_statement(kind, rid, version, build.sha256_bytes(path.read_bytes()))
        (releases / f"{kind}__{rid}__{version}.txt").write_bytes(statement)
    return len(entries)


def make_project(build, dst):
    """Create a complete test project at dst: real code and styles, generated content, every page on."""
    dst = Path(dst)
    dst.mkdir(parents=True)
    shutil.copy2(ROOT / "build.py", dst / "build.py")
    shutil.copytree(ROOT / "static", dst / "static")
    config = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    config["id_prefix"] = "TEST"
    config["pages"] = {"statistics": True, "updates": True}
    (dst / "site.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    croot = dst / "content" / "published"
    shutil.copy2(ROOT / "mathml.py", dst / "mathml.py")
    items = records() + records_v2()
    for r in items:
        _dump(croot / "records" / r["public_id"] / f"v{r['version']}.json", r)
    _dump(croot / "snapshots" / "2000-03.json", snapshot(build, items, "2000-03", "2000-03-31", "2000-04-05"))
    _dump(croot / "snapshots" / "2000-06.json", snapshot(build, items, "2000-06", "2000-06-30", "2000-07-05"))
    _dump(croot / "updates.json", updates(items))
    write_manifests(build, dst)
    return dst
