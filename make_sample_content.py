#!/usr/bin/env python3
"""Write the FICTIONAL demonstration content used by the site.

Every paper, author, journal, DOI, date and number written by this script is invented. DOIs use the
Crossref test prefix 10.5555. Author surnames are deliberately placeholder words (Template, Proxy, ...).

The corpus mirrors the *structure* of a real research programme (18 papers, 36 investigated claims, papers
with several claims and different outcomes, author agreement and disagreement, published and pre-existing
corrections, source-limited questions) without reproducing any real claim, paper or finding.

Run:   python make_sample_content.py          (writes content/sample with DEMO- identifiers)
Then:  python build.py sign-sample            (signs the sample channel with a new throwaway demonstration key)
       and update the TRUST_FINGERPRINTS repository variable to the new key's fingerprint (see README).
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "content" / "sample"

AI_USE = ("Discovery and the separate rechecks used AI models in separate sessions. The independent reproduction, "
          "the version-of-record check and every editorial decision were done by the researcher.")
NEG_AI_USE = ("The search was designed with AI assistance and rerun by the researcher; the version-of-record check "
              "and every editorial decision were done by the researcher.")
JAT = "Journal of Allocation Theory"
GDQ = "Games and Decisions Quarterly"
RMD = "Review of Market Design"
SCC = "Studies in Collective Choice"
JSA = "Journal of Strategic Analysis"
ACAC = "Proceedings of the Conference on Algorithmic Choice (ACAC 2025)"


def fake_sha(label):
    return hashlib.sha256(("sample:" + label).encode()).hexdigest()


def work(authors, title, venue, year, volume, pages, n):
    return {"authors": authors, "title": title, "venue": venue, "year": year, "volume": volume, "pages": pages,
            "doi": f"10.5555/sample.{n:04d}"}


def evidence(n, files):
    return {"package_doi": f"10.5555/sample-evidence.{n:04d}", "package_sha256": fake_sha(f"package-{n}"),
            "licence": "CC BY 4.0 (text); MIT (code)",
            "files": [{"name": f, "sha256": fake_sha(f"{n}-{f}")} for f in files]}


def chk(kind, date, detail, session=None):
    c = {"kind": kind, "date": date, "result": "confirms", "detail": detail}
    if session:
        c["session"] = session
    return c


def vor(level, pages, detail):
    return {"level": level, "pages": pages, "detail": detail}


VOR_FULL = "Statement, definitions and the decisive step checked on rendered pages of the published version."
VOR_PART = "Statement and definitions checked on rendered pages; the proof compared in extracted text only."


def claim(cid, label, kind, role, page, gist, statement, conditions, quantifiers, result, vor_check, checks=(),
          rerun="pass", rerun_detail="The evidence package reruns with one command (Python 3.12, standard library only).",
          novelty="No earlier report found in the searched literature."):
    return {"id": cid, "label": label, "kind": kind, "role": role, "page": page, "gist": gist,
            "statement": statement, "conditions": list(conditions), "quantifiers": quantifiers, "result": result,
            "vor_check": vor_check, "checks": list(checks),
            "reproduction": {"result": rerun, "detail": rerun_detail}, "novelty": novelty}


def defect(cls, affects, summary, witness, tested, not_claimed, repair="none_proposed", repair_note=None,
           previously_reported=False):
    r = {"outcome": "defect_found", "candidate_status": "confirmed", "defect_class": cls, "affects": affects,
         "depth": "deep_audit", "summary": summary, "witness": witness, "tested": tested,
         "not_claimed": list(not_claimed), "repair": repair}
    if repair_note:
        r["repair_note"] = repair_note
    if previously_reported:
        r["previously_reported"] = True
    return r


def negative(summary, scope, limits):
    return {"outcome": "no_defect_found", "depth": "deep_audit", "summary": summary, "search_scope": scope,
            "limits": limits}


def unresolved(reason, summary, detail, limits):
    return {"outcome": "unresolved", "depth": "deep_audit", "unresolved_reason": reason, "summary": summary,
            "detail": detail, "limits": limits}


def record(n, released, track, short, headline, wk, claims, position, history, files, version="1.0",
           summary=None, correction=None, changelog=None, ai_use=AI_USE, challenges=()):
    kind = "defect" if any(c["result"]["outcome"] == "defect_found" for c in claims) else "negative"
    return {
        "public_id": f"DEMO-2027-{n:03d}", "version": version, "released": released, "status": "published",
        "sample": True, "kind": kind, "track": track, "title": short, "headline": headline, "work": wk,
        "claims": claims, "author_position": {"position": position, "summary": summary},
        "correction": correction, "evidence": evidence(n, files), "history": history,
        "challenges": list(challenges),
        "changelog": changelog or [{"version": "1.0", "date": released, "change": "First release."}],
        "statements": {"ai_use": ai_use},
    }


def H(date, typ, label):
    return {"date": date, "type": typ, "label": label}


# ======================================================================== 001: four claims, one paper
r1 = record(
    1, "2027-05-20", "mechanism_design", "Template and Proxy (2021)",
    "Two supporting lemmas are false as stated, and two applications hold only under an assumption the paper "
    "does not state. The main theorem (Theorem 1) was not examined.",
    work(["Clara Template", "Jonas Proxy"], "Serial Cost Sharing on Networks", JAT, 2021, "196", "105301", 1),
    [
        claim("c1", "Lemma 4", "lemma", "supporting", "9",
              "Serial shares are monotone in every user's demand.",
              "On every tree network, each user's serial cost share is non-decreasing in every other user's demand.",
              ["tree network", "concave edge costs", "demands in a finite grid"],
              "for every tree network and every demand profile",
              defect("statement_false", "lemma_or_proof_step",
                     "A three-user path where one user's share falls when another's demand rises.",
                     "On a path with three users and concave edge costs, raising the middle user's demand lowers the "
                     "first user's share. The costs and both demand profiles are listed in the evidence package.",
                     "All paths and stars with up to four users, integer demands up to five, exact rational arithmetic.",
                     ["Theorem 1 is not claimed to be false; its proof uses Lemma 4 only for linear costs, where the lemma holds.",
                      "The lemma is not claimed to fail for linear edge costs."]),
              vor("partial", "9–11", VOR_PART),
              [chk("ai_recheck", "2027-01", "A separate AI session, not given the earlier result, rebuilt the example.", "blind"),
               chk("independent_reproduction", "2027-02", "The researcher recomputed both cost shares with separately written code.")]),
        claim("c2", "Lemma 12", "lemma", "supporting", "31",
              "Merging two users never raises their combined share.",
              "If two users on the same branch are merged into one user with their combined demand, their total cost "
              "share does not increase.",
              ["users on the same branch", "concave edge costs"], "for every pair of users on a branch",
              defect("statement_false", "lemma_or_proof_step",
                     "Merging two users on a four-edge branch raises their combined share.",
                     "On a branch with four edges, merging the two outermost users raises their combined share from 7 to 8 "
                     "because the merged demand crosses a cost breakpoint.",
                     "All branches with up to five edges and two to four users.",
                     ["The lemma is not claimed to fail when the cost function has no breakpoints."]),
              vor("partial", "31–33", VOR_PART),
              [chk("ai_recheck", "2027-02", "A separate AI session, given the earlier result, checked the example against the printed definitions.", "informed"),
               chk("independent_reproduction", "2027-02", "The researcher verified both totals by hand.")]),
        claim("c3", "Application to airport games (Section 6.1)", "application", "application", "24",
              "The serial rule coincides with the nucleolus in airport games.",
              "In every airport game, the serial cost-sharing rule selects the nucleolus.",
              ["airport game: costs nested along a single runway"], "for every airport game",
              defect("missing_or_hidden_assumption", "application_or_example",
                     "Holds only when no two planes have equal runway needs; the paper does not say so.",
                     "With two planes that need the same runway length, the serial rule and the nucleolus split their "
                     "segment differently. With distinct needs, no counterexample exists in the cases checked.",
                     "All airport games with up to six planes and integer runway lengths up to five.",
                     ["The application is not claimed to fail when runway needs are distinct."],
                     "local_repair_proposed", "Requiring distinct runway needs restores the application in all cases checked."),
              vor("partial", "24–26", VOR_PART),
              [chk("independent_reproduction", "2027-02", "The researcher computed both allocations with separate code."),
               chk("ai_recheck", "2027-02", "A separate AI session confirmed the example.", "blind")]),
        claim("c4", "Application to irrigation networks (Section 6.2)", "application", "application", "27",
              "The serial rule is consistent on irrigation networks.",
              "On irrigation networks, the serial rule is consistent: removing a user and their share leaves the others' shares unchanged.",
              ["irrigation network: a rooted tree with costs on edges"], "for every irrigation network",
              defect("missing_or_hidden_assumption", "application_or_example",
                     "Consistency needs every edge cost to be strictly positive; zero-cost edges break it.",
                     "A four-user network with one zero-cost edge, where removing a leaf user changes another user's share.",
                     "Networks with up to five users, with and without zero-cost edges.",
                     ["The application is not claimed to fail when every edge cost is positive."],
                     "local_repair_proposed", "Requiring strictly positive edge costs restores consistency in all cases checked."),
              vor("partial", "27–28", VOR_PART),
              [chk("independent_reproduction", "2027-03", "The researcher reproduced the example with separate code."),
               chk("ai_recheck", "2027-03", "A separate AI session confirmed the example.", "blind")]),
    ],
    "none_yet",
    [H("2027-01", "audit", "Discovery audit of Lemmas 4 and 12 completed"), H("2027-02", "audit", "Applications in Section 6 audited"),
     H("2027-02", "check", "All four findings reproduced by the researcher"), H("2027-02", "source", "Checked against the published version: partial"),
     H("2027-02", "authors", "Authors notified and offered the opportunity to respond"),
     H("2027-05", "authors", "No substantive reply within 90 days"), H("2027-05-20", "release", "Record version 1.0 released")],
    ["README.md", "lemma4_paths.py", "lemma12_merge.py", "applications.py", "certificates.json"])

# ======================================================================== 002: construction failure, corrigendum, repair audited
r2_c1 = claim("c1", "Theorem 2: club mechanism, Rules (a)–(c)", "construction", "main", "14",
              "The three-rule mechanism implements every efficient club structure.",
              "For at least three agents, the mechanism defined by Rules (a)–(c) implements in Nash equilibrium every "
              "efficient club structure satisfying conditions E1 and E2.",
              ["at least three agents", "conditions E1 and E2", "complete information among agents"],
              "for every number of agents and every structure satisfying E1 and E2",
              defect("construction_or_algorithm_fails", "main_result",
                     "An unwanted equilibrium survives the printed rules; Theorem 2 itself is not refuted.",
                     "With three agents and two clubs, a message profile in which agents name different club sizes is an "
                     "equilibrium whose outcome is not efficient. Rule (b) does not penalise it.",
                     "All message profiles for three to five agents with up to three clubs and announced sizes up to six.",
                     ["Theorem 2 asserts that some implementing mechanism exists; that statement is not refuted.",
                      "Conditions E1 and E2 are not claimed to be insufficient."],
                     "repair_checked", "Requiring agents to agree on the announced size removes the equilibrium in all cases checked."),
              vor("full", "13–16", VOR_FULL),
              [chk("ai_recheck", "2027-01", "A separate AI session, not given the earlier result, found the same equilibrium.", "blind"),
               chk("independent_reproduction", "2027-01", "The researcher enumerated the message profiles with separate code."),
               chk("author_agreement", "2027-02", "The authors agreed in writing that the printed rules admit the equilibrium.")])
r2_v10 = record(
    2, "2027-02-18", "mechanism_design", "Sample and Variant (2025)",
    "The mechanism used to prove Theorem 2 does not work as printed. The authors agreed; Theorem 2 itself is not refuted.",
    work(["Ines Sample", "Marek Variant"], "Implementing Club Formation with Simple Messages", RMD, 2025, "20(3)", "911–948", 2),
    [r2_c1], "agrees",
    [H("2027-01", "audit", "Discovery audit completed"), H("2027-01", "check", "Reproduced by the researcher"),
     H("2027-01", "source", "Checked against the published version: full"),
     H("2027-01", "authors", "Authors notified"), H("2027-02", "authors", "Authors agreed in writing"),
     H("2027-02-18", "release", "Record version 1.0 released")],
    ["README.md", "enumerate_messages.py", "equilibrium.json"],
    summary="The authors agreed that the printed rules admit an unwanted equilibrium and said they would publish a correction.")

r2_v11 = copy.deepcopy(r2_v10)
r2_v11.update({"version": "1.1", "released": "2027-04-30",
               "headline": ("The mechanism used to prove Theorem 2 did not work as printed. The authors agreed and published a "
                            "corrigendum crediting this audit; the corrected rules were audited and no defect was found.")})
r2_v11["claims"].append(claim(
    "c2", "Corrected Rules (a)–(c) (corrigendum)", "construction", "repair", "C1",
    "The corrected mechanism implements every efficient club structure.",
    "With Rule (b) amended to require agreement on the announced club size, the mechanism implements every efficient "
    "club structure satisfying E1 and E2.",
    ["as Theorem 2", "Rule (b) as amended in the corrigendum"], "as Theorem 2",
    negative("No unwanted equilibrium among all profiles checked; the amended proof read line by line.",
             "All message profiles for three to six agents with up to three clubs and sizes up to eight, including the "
             "profiles that broke the original rules. The corrigendum's proof read line by line.",
             "Larger message spaces are covered by the proof reading only."),
    vor("full", "C1–C3", "The corrigendum's statement and proof checked on rendered pages."),
    novelty=None))
r2_v11["correction"] = {"type": "corrigendum", "doi": "10.5555/sample.0002c", "date": "2027-04-14",
                        "relation": "after_notification", "attribution": "credits_programme",
                        "claims": ["c1"],
                        "note": "The corrigendum amends Rule (b) and thanks this audit for the counterexample."}
r2_v11["history"] += [H("2027-04-14", "correction", "Corrigendum published (credits this audit)"),
                      H("2027-04", "audit", "Corrected rules audited: no defect found"),
                      H("2027-04-30", "release", "Record version 1.1 released")]
r2_v11["changelog"].append({"version": "1.1", "date": "2027-04-30",
                            "change": "Added the published corrigendum and an audit of the corrected rules."})
r2_v12 = copy.deepcopy(r2_v11)
r2_v12.update({"version": "1.2", "released": "2027-06-09"})
r2_v12["claims"][0]["checks"].append(
    chk("external_human", "2027-06", "Nadia Instance (fictional outside researcher) reproduced the equilibrium independently."))
r2_v12["challenges"] = [{"type": "replication", "date": "2027-06-02", "by": "Nadia Instance (fictional)",
                         "outcome": "Confirms the finding", "response": None}]
r2_v12["history"] += [H("2027-06-02", "contribution", "External replication by Nadia Instance (fictional)"),
                      H("2027-06-09", "release", "Record version 1.2 released")]
r2_v12["changelog"].append({"version": "1.2", "date": "2027-06-09", "change": "Added an external human verification."})

# ======================================================================== 003: authors disagree
r3 = record(
    3, "2027-06-24", "game_theory", "Stand and Model (2025)",
    "Proposition 1 is false as stated and Algorithm 1 can cycle. The authors disagree; their position is summarised below.",
    work(["Ravi Stand", "Elena Model"], "Fee Adjustment on Two-Sided Platforms", GDQ, 2025, "13", "52211", 3),
    [
        claim("c1", "Proposition 1", "proposition", "main", "5",
              "Platform profit is concave in the buyer fee.",
              "For every fixed seller fee, the platform's equilibrium profit is a concave function of the buyer fee.",
              ["linear demand on each side", "cross-side benefits below one"], "for every fixed seller fee",
              defect("statement_false", "main_result",
                     "A parameter choice where profit has two local maxima in the buyer fee.",
                     "With cross-side benefits 0.6 and 0.3 and seller fee 2, profit as a function of the buyer fee has two "
                     "local maxima, so it is not concave.",
                     "A grid of cross-side benefits and fees; profit computed in closed form at every grid point.",
                     ["It is not claimed that an optimal buyer fee fails to exist.",
                      "Results that use only the existence of an optimum are not affected."]),
              vor("partial", "4–6", VOR_PART),
              [chk("ai_recheck", "2027-03", "A separate AI session, not given the earlier result, recomputed the profit curve.", "blind"),
               chk("independent_reproduction", "2027-03", "The researcher derived the profit function by hand."),
               chk("external_human", "2027-06", "After the authors' reply, an outside researcher (fictional) checked the example against the printed model.")]),
        claim("c2", "Algorithm 1", "algorithm", "supporting", "9",
              "Simultaneous fee updating converges to the optimal fees.",
              "Starting from any fees, simultaneous best-response updating of the two fees (Algorithm 1) converges to the "
              "profit-maximising fees.",
              ["both fees updated in the same round", "step size one"], "from every initial pair of fees",
              defect("construction_or_algorithm_fails", "secondary_result",
                     "Oscillates between two fee pairs from a symmetric start.",
                     "From equal initial fees, the two updates overshoot in opposite directions and alternate between two "
                     "fee pairs indefinitely.",
                     "Initial fees on a grid for the parameter range of Proposition 1.",
                     ["Sequential updating of one fee at a time is not claimed to fail."]),
              vor("partial", "9–10", VOR_PART),
              [chk("ai_recheck", "2027-03", "A separate AI session reproduced the oscillation.", "informed"),
               chk("independent_reproduction", "2027-03", "The researcher traced the updates by hand.")]),
    ],
    "disagrees",
    [H("2027-03", "audit", "Discovery audit completed"), H("2027-03", "check", "Both findings reproduced by the researcher"),
     H("2027-03", "authors", "Authors notified"), H("2027-04", "authors", "Authors replied and disagreed"),
     H("2027-06", "check", "Additional outside check after the dispute: confirms"),
     H("2027-06-24", "release", "Record version 1.0 released")],
    ["README.md", "profit_curve.py", "fee_updates.py"],
    summary=("The authors consider the intended model to bound cross-side benefits more tightly, which would exclude both "
             "examples. The record reports the model as printed; the tighter bound does not appear in the paper."))

# ======================================================================== 004: negative main theorem, dependency gap
r4 = record(
    4, "2027-04-08", "matching_social_choice", "Placeholder (2025)",
    "No defect was found in the main theorem. Lemma 5 relies on a cited result that does not cover its case, so its "
    "proof is incomplete; the lemma is not claimed to be false.",
    work(["Oskar Placeholder"], "Course Allocation with Prerequisite Chains", JAT, 2025, "221", "105894", 4),
    [
        claim("c1", "Theorem 2", "theorem", "main", "7",
              "Serial dictatorship with prerequisites is the only efficient, non-bossy rule.",
              "When prerequisites form chains, serial dictatorship respecting prerequisites is the unique rule that is "
              "efficient, non-bossy and strategy-proof.",
              ["prerequisites form chains", "strict preferences over schedules", "fixed priority order"],
              "for every chain structure",
              negative("No counterexample among all small instances checked; the proof read line by line.",
                       "All instances with up to four students, four courses and chains of length up to three; uniqueness "
                       "checked against every rule with the three properties. The proof read line by line.",
                       "Larger instances are covered by the proof reading only. The proof uses Lemma 5 (below)."),
              vor("full", "7–12", VOR_FULL), novelty=None),
        claim("c2", "Lemma 5", "lemma", "supporting", "18",
              "Efficient schedules are unique under weak preferences.",
              "With weak preferences broken by the fixed order, the efficient schedule that respects prerequisites is unique.",
              ["weak preferences", "ties resolved by a fixed order"], "for every instance",
              defect("citation_or_dependency_gap", "lemma_or_proof_step",
                     "The cited uniqueness result covers strict preferences only; the proof needs weak ones.",
                     "The proof cites a uniqueness theorem proved for strict preferences. The step that would "
                     "carry it over to weak preferences is not given, and the cited argument does not cover it.",
                     "The proof and the cited source read line by line; small instances searched for a counterexample (none found).",
                     ["Lemma 5 is not claimed to be false; no counterexample was found.",
                      "Theorem 2 is not claimed to be false."]),
              vor("partial", "18–19", VOR_PART),
              [chk("independent_reproduction", "2027-02", "The researcher compared the cited theorem's hypotheses with the lemma's."),
               chk("ai_recheck", "2027-02", "A separate AI session reached the same reading of the cited result.", "blind")],
              rerun_detail="The small-instance search reruns with one command."),
    ],
    "partly_agrees",
    [H("2027-01", "audit", "Deep audit of Theorem 2 completed: no defect found"), H("2027-02", "audit", "Gap in Lemma 5 identified"),
     H("2027-02", "check", "Reproduced by the researcher"), H("2027-02", "authors", "Author notified"),
     H("2027-03", "authors", "Author partly agreed"), H("2027-04-08", "release", "Record version 1.0 released")],
    ["README.md", "small_instances.py", "uniqueness_check.py"],
    summary="The author agreed that the citation does not cover weak preferences and believes a short argument closes the gap.")

# ======================================================================== 005: two negatives, our correction
r5_v10 = record(
    5, "2027-03-02", "matching_social_choice", "Instance (2023)",
    "No defect was found in Theorem 3 or Lemma 8 within the stated scope. This is not a proof that they are correct.",
    work(["Hanna Instance"], "Seeding Rules for Knockout Tournaments", SCC, 2023, "18", "331–362", 5),
    [
        claim("c1", "Theorem 3", "theorem", "main", "12",
              "Only the balanced seeding rule satisfies the three fairness axioms.",
              "For knockout tournaments with 2^k players, balanced seeding is the unique seeding rule satisfying "
              "monotonicity, symmetry and the stronger-player axiom.",
              ["2^k players", "the three axioms of Section 3"], "for every k ≥ 2",
              negative("No other rule satisfies the axioms for up to sixteen players; the proof read line by line.",
                       "Every seeding rule for four, eight and sixteen players, checked against the three axioms. "
                       "The proof read line by line.",
                       "Thirty-two or more players are covered by the proof reading only."),
              vor("full", "12–15", VOR_FULL), novelty=None),
        claim("c2", "Lemma 8", "lemma", "supporting", "21",
              "Monotone rules never pair the two strongest players in round one.",
              "Every monotone seeding rule keeps the two strongest players in different halves of the bracket.",
              ["as Theorem 3"], "for every k ≥ 2",
              negative("No counterexample for up to sixteen players.",
                       "All monotone rules for four, eight and sixteen players.",
                       "The search is finite; the general case rests on the proof."),
              vor("full", "21–22", VOR_FULL), novelty=None),
    ],
    "courtesy_notice",
    [H("2027-02", "audit", "Deep audit completed: no defect found"), H("2027-02", "reproduction", "Evidence package rerun: pass"),
     H("2027-03", "authors", "Courtesy notice sent"), H("2027-03-02", "release", "Record version 1.0 released")],
    ["README.md", "brackets.py", "results.json"], ai_use=NEG_AI_USE)
r5_v10["claims"][0]["result"]["search_scope"] = ("Every seeding rule for four, eight, sixteen and thirty-two players, checked "
                                                 "against the three axioms. The proof read line by line.")
r5_v11 = copy.deepcopy(r5_v10)
r5_v11.update({"version": "1.1", "released": "2027-03-29"})
r5_v11["claims"][0]["result"]["search_scope"] = (
    "Every seeding rule for four, eight and sixteen players, checked against the three axioms. The proof read line by line.")
r5_v11["history"] += [H("2027-03-29", "release", "Record version 1.1 released (our correction)")]
r5_v11["changelog"].append({"version": "1.1", "date": "2027-03-29", "our_correction": True,
                            "change": "Version 1.0 overstated the search for Theorem 3 (thirty-two players instead of sixteen). Findings unchanged."})

# ======================================================================== 006: two negatives
r6 = record(
    6, "2027-01-26", "matching_social_choice", "Proxy and Surrogate (2018)",
    "No defect was found in either theorem within the stated scope. This is not a proof that they are correct.",
    work(["Leila Proxy", "Tom Surrogate"], "Shift Assignment with Seniority Ranks", SCC, 2018, "13", "455–490", 6),
    [
        claim("c1", "Theorem 1", "theorem", "main", "8",
              "Nested seniority classes guarantee a fair, strategy-proof assignment.",
              "If seniority classes are nested, there is an assignment rule that is fair to seniority and strategy-proof for workers.",
              ["seniority classes are nested", "strict preferences over shifts"], "for every nested class structure",
              negative("A fair, strategy-proof rule found for every structure checked.",
                       "Every nested structure over up to five shifts; rules constructed by the paper's algorithm and checked exhaustively.",
                       "Larger structures rest on the constructive proof."),
              vor("partial", "8–11", VOR_PART), novelty=None),
        claim("c2", "Theorem 3", "theorem", "main", "13",
              "Without nesting, some preference profile defeats every such rule.",
              "If seniority classes are not nested, some preference profile admits no assignment rule that is fair and strategy-proof.",
              ["seniority classes are not nested"], "for every non-nested structure",
              negative("A defeating profile found for every non-nested structure checked.",
                       "Every non-nested structure over up to four shifts.",
                       "Structures over five or more shifts rest on the proof."),
              vor("partial", "13–17", VOR_PART), novelty=None),
    ],
    "courtesy_notice",
    [H("2027-01", "audit", "Deep audit completed: no defect found"), H("2027-01", "reproduction", "Evidence package rerun: pass"),
     H("2027-01", "authors", "Courtesy notice sent"), H("2027-01-26", "release", "Record version 1.0 released")],
    ["README.md", "shift_rules.py", "profiles.json"], ai_use=NEG_AI_USE)

# ======================================================================== 007: negative main theorem, unresolved appendix claim
r7 = record(
    7, "2027-05-06", "game_theory", "Pattern and Specimen (2019)",
    "No defect was found in Theorem 2. A claim in the online appendix could not be settled because the final version of "
    "the appendix was not available; it is reported as unresolved, not as a defect.",
    work(["Ana Pattern", "Felix Specimen"], "Bidding Rings in Repeated Procurement", JSA, 2019, "87(4)", "1201–1240", 7),
    [
        claim("c1", "Theorem 2", "theorem", "main", "6",
              "A bidding ring is stable only if the discount factor exceeds the stated bound.",
              "In the repeated procurement game, a bidding ring is sustainable in equilibrium if and only if the "
              "discount factor exceeds δ*(n, c).",
              ["identical costs c", "n bidders", "observable winning bids"], "for every n ≥ 2",
              negative("No counterexample among the games checked; the proof read line by line.",
                       "Two to five bidders, cost grids up to eight points, discount factors on a fine grid; all stage "
                       "deviations checked. The proof read line by line.",
                       "Unobservable bids are outside the claim."),
              vor("full", "6–10", VOR_FULL), novelty=None),
        claim("c2", "Claim B.4 (online appendix)", "remark", "supporting", "B7",
              "The bound δ*(n, c) is strictly increasing in n.",
              "The threshold discount factor δ*(n, c) is strictly increasing in the number of bidders.",
              ["as Theorem 2"], "for every cost level c",
              unresolved("source_limited",
                         "A boundary cost level appears to give equal thresholds in the 2019 appendix; the final appendix was not available.",
                         "In the 2019 working-paper appendix, at the boundary cost level the threshold is the same for three "
                         "and four bidders. The journal's final appendix may restrict the cost range; it could not be "
                         "obtained, so the question is not settled.",
                         "Not counted as a defect. Will be revisited if the final appendix becomes available."),
              vor("none", "B6–B8", "Only the 2019 working-paper appendix was available; the final appendix could not be obtained."),
              novelty=None),
    ],
    "courtesy_notice",
    [H("2027-03", "audit", "Deep audit of Theorem 2 completed: no defect found"),
     H("2027-04", "source", "Final online appendix requested; not obtained"),
     H("2027-04", "authors", "Courtesy notice sent"), H("2027-05-06", "release", "Record version 1.0 released")],
    ["README.md", "ring_stability.py", "boundary_case.json"], ai_use=NEG_AI_USE)

# ======================================================================== 008: two negatives
r8 = record(
    8, "2027-02-10", "mechanism_design", "Draft and Mock (2026)",
    "No defect was found in Theorem 1 or Corollary 2 within the stated scope. This is not a proof that they are correct.",
    work(["Ruth Draft", "Paolo Mock"], "Collusion-Proof Posted Prices", JSA, 2026, "94(1)", "88–121", 8),
    [
        claim("c1", "Theorem 1", "theorem", "main", "5",
              "Anonymous posted prices resist collusion by any pair of buyers.",
              "Every anonymous posted-price mechanism is pairwise collusion-proof when buyers cannot transfer money.",
              ["anonymous prices", "no side payments"], "for every number of buyers and goods",
              negative("No profitable pairwise deviation in any mechanism checked.",
                       "All posted-price mechanisms with up to four buyers and three goods on a price grid; every pair and joint deviation.",
                       "Side payments are outside the claim, as stated in the paper."),
              vor("full", "5–9", VOR_FULL), novelty=None),
        claim("c2", "Corollary 2", "corollary", "supporting", "10",
              "The same holds when goods are offered sequentially.",
              "Offering the goods one at a time at the same prices preserves pairwise collusion-proofness.",
              ["as Theorem 1"], "as Theorem 1",
              negative("No counterexample among the sequential versions checked.",
                       "Every order of offering the goods in the mechanisms above.",
                       "Price changes between offers are outside the search."),
              vor("full", "10", VOR_FULL), novelty=None),
    ],
    "courtesy_notice",
    [H("2027-01", "audit", "Deep audit completed: no defect found"), H("2027-02", "reproduction", "Evidence package rerun: pass"),
     H("2027-02", "authors", "Courtesy notice sent"), H("2027-02-10", "release", "Record version 1.0 released")],
    ["README.md", "pair_deviations.py"], ai_use=NEG_AI_USE)

# ======================================================================== 009: two negatives with supplement limits
r9 = record(
    9, "2027-03-17", "game_theory", "Token (2021)",
    "No defect was found in Propositions 3 and 6 within the stated scope. Parts of the proofs rely on a supplement that "
    "was checked only in its working-paper form.",
    work(["Mina Token"], "Persuading Receivers One at a Time", JSA, 2021, "89(2)", "640–679", 9),
    [
        claim("c1", "Proposition 3", "proposition", "main", "11",
              "Public signals are optimal for sequential receivers with aligned payoffs.",
              "When receivers act in sequence and their payoffs are aligned, a public signal achieves the sender's "
              "optimal value among all private signal structures.",
              ["receivers act in a fixed order", "aligned receiver payoffs"], "for every finite state space",
              negative("The optimality argument checked step by step; no defect found.",
                       "The construction in Appendix A, checked on games with two receivers, three states and binary actions.",
                       "Does not cover misaligned receivers. Supplement steps checked in the working-paper version only."),
              vor("partial", "11–13", VOR_PART), novelty=None),
        claim("c2", "Proposition 6", "proposition", "supporting", "19",
              "The optimal public signal needs at most as many messages as actions.",
              "Some optimal public signal uses no more messages than the number of action profiles.",
              ["as Proposition 3"], "as Proposition 3",
              negative("No instance required more messages among those checked.",
                       "Two receivers, up to four states and binary actions; optimal signals computed by linear programming.",
                       "The general argument relies on Supplement S1, checked in the working-paper version only."),
              vor("partial", "19–20", VOR_PART), novelty=None),
    ],
    "courtesy_notice",
    [H("2027-02", "audit", "Deep audit completed: no defect found"), H("2027-03", "authors", "Courtesy notice sent"),
     H("2027-03-17", "release", "Record version 1.0 released")],
    ["README.md", "signals_lp.py"], ai_use=NEG_AI_USE)

# ======================================================================== 010: two negatives and a repairable proof gap
r10 = record(
    10, "2027-04-22", "mechanism_design", "Fictive and Example (2022)",
    "No defect was found in Theorems 1 and 2. The proof of the Exit Lemma skips a case; the authors agreed and supplied "
    "a short argument that closes it.",
    work(["Sara Fictive", "Daniel Example"], "Ascending Auctions for Complementary Bundles", JAT, 2022, "205", "105511", 10),
    [
        claim("c1", "Theorem 1", "theorem", "main", "9",
              "The bundle clock ends at a Walrasian price whenever one exists.",
              "If a Walrasian equilibrium exists, the ascending bundle clock terminates at a Walrasian price vector.",
              ["gross substitutes within bundles", "integer price increments"], "for every valuation profile",
              negative("No counterexample among the auctions checked; the proof read line by line.",
                       "Up to three bidders and four goods with integer valuations up to six. The proof read line by line.",
                       "Larger auctions rest on the proof."),
              vor("full", "9–12", VOR_FULL),
              [chk("ai_recheck", "2027-02", "A separate AI session reran the search independently.", "blind")], novelty=None),
        claim("c2", "Theorem 2", "theorem", "main", "15",
              "Truthful bidding is an ex post equilibrium of the clock.",
              "Under the conditions of Theorem 1, truthful bidding is an ex post equilibrium of the bundle clock.",
              ["as Theorem 1"], "as Theorem 1",
              negative("No profitable deviation found in any auction checked.",
                       "Same auctions as Theorem 1; all single-bidder deviations.", "Larger auctions rest on the proof."),
              vor("full", "15–17", VOR_FULL),
              [chk("ai_recheck", "2027-02", "A separate AI session reran the search independently.", "blind")], novelty=None),
        claim("c3", "Exit Lemma", "lemma", "supporting", "22",
              "A bidder who exits never re-enters at a higher price.",
              "Along every run of the clock, a bidder who drops out of a bundle does not bid on it again at a higher price.",
              ["as Theorem 1"], "along every run of the clock",
              defect("proof_gap_repairable", "lemma_or_proof_step",
                     "The proof omits re-entry after a tie between bundles; a short argument closes it.",
                     "The proof's induction does not treat rounds that follow a tie between two bundles. No counterexample "
                     "to the lemma exists in the cases checked, and the authors' added argument handles the tie case.",
                     "The proof read line by line; all runs in auctions with up to three bidders checked.",
                     ["The Exit Lemma is not claimed to be false.", "Theorems 1 and 2 are not affected once the gap is closed."],
                     "repair_proved", "The authors supplied a short argument for the tie case; the researcher checked it."),
              vor("full", "22–23", VOR_FULL),
              [chk("independent_reproduction", "2027-03", "The researcher checked the missing case by hand."),
               chk("author_agreement", "2027-04", "The authors agreed that the case was missing and supplied the argument.")]),
    ],
    "agrees",
    [H("2027-02", "audit", "Deep audit completed"), H("2027-03", "check", "Gap reproduced by the researcher"),
     H("2027-03", "authors", "Authors notified"), H("2027-04", "authors", "Authors agreed and supplied a repair"),
     H("2027-04-22", "release", "Record version 1.0 released")],
    ["README.md", "clock_runs.py", "tie_case.md"],
    summary="The authors agreed that the tie case was missing and supplied the argument now summarised in the record.")

# ======================================================================== 011: authors agree, correction not yet published
r11_v10 = record(
    11, "2027-03-24", "game_theory", "Sample and Stand (2019)",
    "Theorem 2(a) is false as stated, and a step in Lemma B2 needs an assumption the paper does not state.",
    work(["Ines Sample", "Ravi Stand"], "Equilibrium with Endogenous Entry", GDQ, 2019, "7", "301–329", 11),
    [
        claim("c1", "Theorem 2(a)", "theorem", "main", "6",
              "Every entry game in the class has a symmetric pure equilibrium.",
              "Every entry game satisfying Assumptions A1–A3 has a symmetric equilibrium in pure strategies.",
              ["Assumptions A1–A3", "identical potential entrants"], "for every game satisfying the assumptions",
              defect("statement_false", "main_result",
                     "An entry game satisfying A1–A3 whose pure equilibria are all asymmetric.",
                     "With three potential entrants and a market that is profitable for exactly two, every pure equilibrium "
                     "has two entrants and one stays out, so none is symmetric.",
                     "Games with two to four entrants and profit functions on a grid, solved exactly.",
                     ["Part (b) of Theorem 2, on mixed equilibria, is not claimed to be false.",
                      "The theorem is not claimed to fail when entry is profitable for every number of entrants."],
                     "local_repair_proposed", "Allowing mixed strategies restores the conclusion in all cases checked."),
              vor("partial", "6–8", VOR_PART),
              [chk("ai_recheck", "2027-01", "A separate AI session, not given the earlier result, rebuilt the game.", "blind"),
               chk("independent_reproduction", "2027-02", "The researcher solved the game exactly with separate code.")]),
        claim("c2", "Lemma B2", "lemma", "supporting", "B3",
              "The entry best-reply map has a closed graph.",
              "The best-reply correspondence of the entry game has a closed graph in the space of entry probabilities.",
              ["Assumptions A1–A3"], "for every game satisfying the assumptions",
              defect("missing_or_hidden_assumption", "lemma_or_proof_step",
                     "A closed graph needs profits to be continuous in the number of entrants; this is not stated.",
                     "The limit step uses continuity of profits in the number of entrants; without it the graph is not "
                     "closed in a three-entrant game with a profit jump.",
                     "The proof read line by line; the three-entrant game used as a test case.",
                     ["The lemma is not claimed to fail when profits are continuous in the number of entrants."],
                     "local_repair_proposed", "Adding continuity of profits closes the step."),
              vor("partial", "B3–B4", VOR_PART),
              [chk("ai_recheck", "2027-02", "A separate AI session identified the same missing condition.", "informed"),
               chk("independent_reproduction", "2027-02", "The researcher checked the step by hand.")]),
    ],
    "none_yet",
    [H("2027-01", "audit", "Discovery audit completed"), H("2027-02", "check", "Both findings reproduced by the researcher"),
     H("2027-02", "source", "Checked against the published version: partial"), H("2027-02", "authors", "Authors notified"),
     H("2027-03", "authors", "Authors' agreement to a public record received"), H("2027-03-24", "release", "Record version 1.0 released")],
    ["README.md", "entry_game.py", "closed_graph_note.md"])
r11_v11 = copy.deepcopy(r11_v10)
r11_v11.update({"version": "1.1", "released": "2027-05-27"})
r11_v11["author_position"] = {"position": "agrees",
                              "summary": "The authors agreed with both findings and are preparing a correction; it has not been published."}
for c in r11_v11["claims"]:
    c["checks"].append(chk("author_agreement", "2027-05", "The authors agreed in writing with the finding."))
r11_v11["history"] += [H("2027-05", "authors", "Authors agreed in writing; correction in preparation"),
                       H("2027-05-27", "release", "Record version 1.1 released")]
r11_v11["changelog"].append({"version": "1.1", "date": "2027-05-27", "change": "Added the authors' written agreement."})

# ======================================================================== 012: corrigendum published before the audit
r12 = record(
    12, "2027-02-24", "game_theory", "Variant (2003)",
    "Corollary 5.2 is false as originally printed. A corrigendum published in 2022, before this audit, already corrects "
    "it; the record documents a known error re-found by the method.",
    work(["Marek Variant"], "Bargaining with Outside Options and Deadlines", JSA, 2003, "71(2)", "455–489", 12),
    [
        claim("c1", "Corollary 5.2 (as originally printed)", "corollary", "secondary", "478",
              "Agreement is immediate whenever the deadline is long enough.",
              "If the deadline exceeds T*, every subgame-perfect equilibrium reaches agreement in the first period.",
              ["alternating offers", "outside options below the pie", "deadline longer than T*"], "for every such game",
              defect("statement_false", "secondary_result",
                     "A game with a long deadline and delayed agreement, as the 2022 corrigendum notes.",
                     "With outside options close to half the pie, an equilibrium delays agreement to the second period even "
                     "when the deadline exceeds T*.",
                     "Re-derived from the original statement without using the corrigendum, then compared with it.",
                     ["The paper's main characterization is not claimed to be false.",
                      "The corrected corollary is not claimed to be false."],
                     previously_reported=True),
              vor("partial", "478", "The original statement checked on rendered pages; the corrigendum read in full."),
              [chk("independent_reproduction", "2027-01", "The researcher re-derived the counterexample before reading the corrigendum."),
               chk("ai_recheck", "2027-01", "A separate AI session confirmed the counterexample.", "blind")],
              novelty="Previously reported: the 2022 corrigendum corrects this corollary."),
    ],
    "previously_corrected",
    [H("2027-01", "audit", "Calibration audit completed"), H("2027-01", "check", "Re-derived by the researcher"),
     H("2027-02-24", "release", "Record version 1.0 released")],
    ["README.md", "delay_example.py"],
    correction={"type": "corrigendum", "doi": "10.5555/sample.0012c", "date": "2022", "relation": "before_audit",
                "attribution": "none_stated", "claims": ["c1"],
                "note": "Published by the author in 2022, before this audit."})

# ======================================================================== 013: confirmed gap and an unresolved later version
r13 = record(
    13, "2027-06-17", "mechanism_design", "Prototype (2024)",
    "The proof of Remark 3 has a gap that a short argument repairs. A related gap in Lemma 4(b) is confirmed for the "
    "2024 appendix but unresolved for the revised appendix, which could not be obtained.",
    work(["Yara Prototype"], "Dynamic Pricing with Patient Buyers", RMD, 2024, "19(2)", "415–452", 13),
    [
        claim("c1", "Remark 3", "remark", "supporting", "17",
              "Price paths that are optimal for finite horizons stay optimal in the limit.",
              "If a price path is optimal for every finite horizon, its limit is optimal for the infinite-horizon problem.",
              ["patient buyers with discount factor below one", "bounded valuations"], "for every price path",
              defect("proof_gap_repairable", "secondary_result",
                     "The proof assumes the limit path exists; a short compactness argument supplies it.",
                     "The argument passes to the limit without showing that the finite-horizon paths converge. A "
                     "compactness argument on bounded paths closes the gap.",
                     "The proof read line by line; horizons up to twelve periods checked numerically.",
                     ["Remark 3 is not claimed to be false."],
                     "repair_checked", "A compactness argument closes the gap in all cases checked."),
              vor("partial", "17–18", VOR_PART),
              [chk("independent_reproduction", "2027-04", "The researcher checked the limit argument by hand."),
               chk("ai_recheck", "2027-04", "A separate AI session confirmed the missing step.", "blind")]),
        claim("c2", "Lemma 4(b) (online appendix)", "lemma", "supporting", "A4",
              "Optimal prices never rise after the first sale.",
              "In every optimal price path, the price never increases after the first period with a sale.",
              ["as Remark 3"], "for every optimal path",
              unresolved("source_limited",
                         "Same gap as Remark 3 in the 2024 appendix; the revised appendix could not be obtained.",
                         "In the 2024 online appendix the proof has the same missing limit step as Remark 3. The journal "
                         "posted a revised appendix in 2026, which could not be obtained; it may already address the gap.",
                         "Not counted as a defect until the revised appendix has been checked."),
              vor("none", "A4", "Only the 2024 appendix was available; the 2026 revision could not be obtained."),
              novelty=None),
    ],
    "none_yet",
    [H("2027-03", "audit", "Deep audit completed"), H("2027-03", "authors", "Author notified"),
     H("2027-04", "check", "Gap in Remark 3 reproduced by the researcher"),
     H("2027-04", "source", "Revised appendix requested; not obtained"),
     H("2027-06", "authors", "No substantive reply within 90 days"), H("2027-06-17", "release", "Record version 1.0 released")],
    ["README.md", "price_paths.py"])

# ======================================================================== 014: two negatives
r14 = record(
    14, "2027-01-26", "matching_social_choice", "Mock and Pattern (2018)",
    "No defect was found in Theorems 1 and 2 within the stated scope. This is not a proof that they are correct.",
    work(["Paolo Mock", "Ana Pattern"], "Exchange Cycles with Compatibility Classes", SCC, 2018, "13", "211–248", 14),
    [
        claim("c1", "Theorem 1", "theorem", "main", "7",
              "With four or more classes, two-way exchanges achieve the maximum number of transplants.",
              "If there are at least four compatibility classes, some maximum exchange uses only two-way cycles.",
              ["at least four classes", "class-based compatibility"], "for every pool",
              negative("No pool needed a longer cycle among those checked.",
                       "Exact search over all pools with four and five classes and up to twelve pairs.",
                       "Pools with three or fewer classes are outside the claim."),
              vor("partial", "7–9", VOR_PART), novelty=None),
        claim("c2", "Theorem 2", "theorem", "main", "10",
              "The maximum can be found by a greedy pass over classes.",
              "Processing compatibility classes in the stated order and matching greedily yields a maximum two-way exchange.",
              ["as Theorem 1"], "for every pool",
              negative("The greedy pass matched the maximum in every pool checked.",
                       "All pools in the search for Theorem 1.",
                       "Larger pools rest on the constructive proof."),
              vor("partial", "10–12", VOR_PART), novelty=None),
    ],
    "courtesy_notice",
    [H("2027-01", "audit", "Deep audit completed: no defect found"), H("2027-01", "authors", "Courtesy notice sent"),
     H("2027-01-26", "release", "Record version 1.0 released")],
    ["README.md", "exchange_pools.py"], ai_use=NEG_AI_USE)

# ======================================================================== 015: single false proposition
r15 = record(
    15, "2027-05-13", "game_theory", "Model (2026)",
    "The only-if direction of Proposition 4 is false as stated.",
    work(["Elena Model"], "Stable Alliances in Contest Networks", GDQ, 2026, "14", "60104", 15),
    [
        claim("c1", "Proposition 4 (only-if direction)", "proposition", "main", "4",
              "An alliance network is stable only if every alliance passes the effort test.",
              "If an alliance network is stable, then every alliance in it satisfies the effort condition (E).",
              ["symmetric contests", "alliance costs as in (E)"], "for every stable alliance network",
              defect("statement_false", "main_result",
                     "A four-player stable network with an alliance that fails condition (E).",
                     "A four-player network with two overlapping alliances is stable for the stated parameters, but one "
                     "alliance fails (E).",
                     "All networks with up to five players over a grid of cost parameters.",
                     ["The if direction is not claimed to be false."]),
              vor("full", "4–5", VOR_FULL),
              [chk("ai_recheck", "2027-02", "A separate AI session, not given the earlier result, found the same network.", "blind"),
               chk("independent_reproduction", "2027-02", "The researcher verified stability by hand.")]),
    ],
    "none_yet",
    [H("2027-01", "audit", "Discovery audit completed"), H("2027-02", "check", "Reproduced by the researcher"),
     H("2027-02", "authors", "Author notified"), H("2027-05", "authors", "No substantive reply within 90 days"),
     H("2027-05-13", "release", "Record version 1.0 released")],
    ["README.md", "alliances.py"])

# ======================================================================== 016: three false statements
r16 = record(
    16, "2027-06-03", "game_theory", "Surrogate, Token and Draft (2024)",
    "Theorems 2 and 4 and Lemma 3 are false as stated; each fails on a small instance.",
    work(["Tom Surrogate", "Mina Token", "Ruth Draft"], "Rent Division with Budget Limits", JSA, 2024, "92(3)", "777–812", 16),
    [
        claim("c1", "Theorem 2", "theorem", "main", "8",
              "Every rent-division problem with budgets has an envy-free solution.",
              "Every rent-division problem in which each tenant's budget covers the average rent has an envy-free allocation of rooms and rent.",
              ["budgets cover the average rent", "quasi-linear utilities"], "for every problem",
              defect("statement_false", "main_result",
                     "A three-tenant problem with no envy-free solution within budgets.",
                     "With three tenants and one tenant's budget exactly at the average rent, every envy-free price vector "
                     "charges that tenant more than the budget.",
                     "All problems with up to three tenants and integer values up to six.",
                     ["The theorem is not claimed to fail for two tenants."]),
              vor("partial", "8–9", VOR_PART),
              [chk("ai_recheck", "2027-04", "A separate AI session confirmed the instance.", "blind"),
               chk("independent_reproduction", "2027-04", "The researcher checked every envy-free price vector of the instance.")]),
        claim("c2", "Lemma 3", "lemma", "supporting", "9",
              "Lowering one room's rent never creates envy.",
              "Starting from an envy-free solution, lowering the rent of one room does not create envy toward that room.",
              ["as Theorem 2"], "for every envy-free solution",
              defect("statement_false", "lemma_or_proof_step",
                     "A rent reduction that creates envy in a two-tenant problem.",
                     "With two tenants, lowering the rent of the cheaper room makes the other tenant prefer it.",
                     "All solutions with up to three tenants and integer rents.", ["Nothing about Theorem 4 follows from this alone."]),
              vor("partial", "9", VOR_PART),
              [chk("ai_recheck", "2027-04", "A separate AI session confirmed the example.", "informed"),
               chk("independent_reproduction", "2027-04", "The researcher computed both utilities by hand.")]),
        claim("c3", "Theorem 4", "theorem", "main", "11",
              "The rent-adjustment procedure ends at an envy-free solution.",
              "The rent-adjustment procedure of Section 4 terminates at an envy-free solution within budgets.",
              ["as Theorem 2"], "from every initial rent vector",
              defect("statement_false", "main_result",
                     "The procedure stops at a solution where one tenant is envious.",
                     "In the instance for Theorem 2, the procedure from equal rents stops at a solution where one tenant envies another.",
                     "All initial rent vectors for the instances above.",
                     ["Termination itself is not disputed."]),
              vor("partial", "11–12", VOR_PART),
              [chk("ai_recheck", "2027-04", "A separate AI session confirmed the final solution.", "blind"),
               chk("independent_reproduction", "2027-05", "The researcher traced the procedure by hand.")]),
    ],
    "none_yet",
    [H("2027-02", "audit", "Discovery audit completed"), H("2027-02", "authors", "Authors notified"),
     H("2027-04", "check", "All three findings reproduced by the researcher"),
     H("2027-05", "authors", "No substantive reply within 90 days"),
     H("2027-06-03", "release", "Record version 1.0 released")],
    ["README.md", "rent_instances.py", "instances.json"])

# ======================================================================== 017: algorithm fails, authors agree
r17 = record(
    17, "2027-04-15", "game_theory", "Example and Instance (2025)",
    "Algorithm 1 does not always meet its stated approximation guarantee. The authors agreed.",
    work(["Daniel Example", "Hanna Instance"], "Greedy Scheduling with Machine Preferences", ACAC, 2025, "", "1132–1140", 17),
    [
        claim("c1", "Algorithm 1 (steps 3 and 4)", "algorithm", "main", "5",
              "Greedy assignment is within a factor of two of the optimal makespan.",
              "For identical jobs and machines with preferences, Algorithm 1 returns a schedule whose makespan is at most "
              "twice the optimum.",
              ["identical jobs", "each machine ranks jobs"], "for every instance",
              defect("construction_or_algorithm_fails", "main_result",
                     "A three-machine instance where the makespan is three times the optimum.",
                     "Step 3 can assign every job to the machine that ranks it highest even when that machine is already "
                     "full, and step 4 never rebalances. The instance and the trace are in the evidence package.",
                     "All instances with three machines and up to nine jobs.",
                     ["Termination is not disputed.", "A factor-two schedule is not claimed to be impossible."]),
              vor("full", "4–6", VOR_FULL),
              [chk("independent_reproduction", "2027-02", "The researcher traced the algorithm by hand on the instance."),
               chk("author_agreement", "2027-03", "The authors agreed that step 3 needs a capacity check.")]),
    ],
    "agrees",
    [H("2027-02", "audit", "Discovery audit completed"), H("2027-02", "check", "Reproduced by the researcher"),
     H("2027-02", "authors", "Authors notified"), H("2027-03", "authors", "Authors agreed"),
     H("2027-04-15", "release", "Record version 1.0 released")],
    ["README.md", "schedule_trace.py"],
    summary="The authors agreed and plan to post a revised version with a capacity check in step 3.")

# ======================================================================== 018: single negative
r18 = record(
    18, "2027-03-10", "game_theory", "Specimen (2025)",
    "No defect was found in Theorem 5 within the stated scope. This is not a proof that it is correct.",
    work(["Felix Specimen"], "Price of Anarchy in Congestion Games with Priorities", ACAC, 2025, "", "1141–1149", 18),
    [
        claim("c1", "Theorem 5", "theorem", "main", "7",
              "The price of anarchy is at most 5/2 with priorities.",
              "For congestion games with affine costs and priority classes, the pure price of anarchy is at most 5/2.",
              ["affine costs", "priority classes"], "for every such game",
              negative("No instance above 5/2 among those checked; the proof read line by line.",
                       "Games with up to four players and three resources, affine costs with integer coefficients up to 4.",
                       "Tightness of the bound was not examined."),
              vor("full", "7–8", VOR_FULL), novelty=None),
    ],
    "courtesy_notice",
    [H("2027-02", "audit", "Deep audit completed: no defect found"), H("2027-03", "authors", "Courtesy notice sent"),
     H("2027-03-10", "release", "Record version 1.0 released")],
    ["README.md", "poa_search.py"], ai_use=NEG_AI_USE)

RECORDS = [r1, r2_v10, r2_v11, r2_v12, r3, r4, r5_v10, r5_v11, r6, r7, r8, r9, r10, r11_v10, r11_v11, r12, r13, r14,
           r15, r16, r17, r18]


# ======================================================================== statistics snapshots (derived)
def _build_module():
    spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    return b


class _Records:
    """Just enough of build.Content for released_stats."""
    def __init__(self, records):
        self.records = {}
        for r in records:
            self.records.setdefault(r["public_id"], []).append(r)
        for v in self.records.values():
            v.sort(key=lambda r: tuple(int(x) for x in r["version"].split(".")))

    def latest_all(self, as_of=None):
        out = []
        for rid in sorted(self.records):
            vs = [r for r in self.records[rid] if as_of is None or r["released"] <= as_of]
            if vs:
                out.append(vs[-1])
        return out


PROGRAMME = {"id": "targeted-2026",
             "description": ("Current selection: recent articles in leading theory journals, and results "
                             "with features where errors often hide.")}
EXTRA = {  # unreleased work, added on top of what released records show
    "2027-03": dict(screened=24, papers=4, claims=7, deep=5, open=5, open_ai=4, rejected=3, unres=1, neg_full=1, neg_part=2, notified=3),
    "2027-06": dict(screened=31, papers=5, claims=9, deep=6, open=8, open_ai=7, rejected=4, unres=2, neg_full=1, neg_part=3, notified=4),
}
ACTIVITY = [
    {"month": "2027-01", "discovery": 7, "hostile_validation": 4, "source_lock": 3, "package_rerun": 4},
    {"month": "2027-02", "discovery": 6, "hostile_validation": 6, "source_lock": 4, "package_rerun": 3},
    {"month": "2027-03", "discovery": 5, "hostile_validation": 4, "source_lock": 2, "package_rerun": 3},
    {"month": "2027-04", "discovery": 6, "hostile_validation": 5, "source_lock": 3, "package_rerun": 2},
    {"month": "2027-05", "discovery": 4, "hostile_validation": 4, "source_lock": 2, "package_rerun": 2},
    {"month": "2027-06", "discovery": 3, "hostile_validation": 3, "source_lock": 2, "package_rerun": 2},
]


def make_snapshot(b, name, as_of, released):
    rs = b.released_stats(_Records(RECORDS), as_of)
    x = EXTRA[name]
    conf = rs["confirmed"]
    totals = {
        "M01": rs["papers"] + x["screened"], "M02": rs["papers"] + x["papers"], "M03": rs["claims"] + x["claims"],
        "M04": rs["deep"] + x["deep"],
        "M05": conf + rs["unresolved"] + x["unres"] + x["open"] + x["rejected"],
        "M06": {"open": x["open"], "confirmed": conf, "unresolved": rs["unresolved"] + x["unres"],
                "rejected": x["rejected"], "open_ai_supported": x["open_ai"],
                "confirmed_previously_reported": rs["previously_reported"]},
        "M07": {"vor_full": rs["vor_neg"]["full"] + x["neg_full"], "vor_partial": rs["vor_neg"]["partial"] + x["neg_part"],
                "vor_none": rs["vor_neg"]["none"]},
        "M08": {"blind": rs["ai_blind"], "informed": rs["ai_informed"]}, "M09": rs["indep"], "M10": rs["external"],
        "M11": dict(rs["vor_conf"]), "M12": rs["notified"] + x["notified"],
        "M13": {"agreed": rs["positions"]["agreed"], "partly_agreed": rs["positions"]["partly_agreed"],
                "disagreed": rs["positions"]["disagreed"], "none_yet": rs["positions"]["none_yet"]},
        "M17": {"checked": rs["calibration"], "known_errors_refound": rs["calibration"]},
    }
    by_track = {}
    m01 = {t: rs["papers_by_track"][t] for t in b.TRACKS}
    share = [x["screened"] // 2, x["screened"] // 4]
    keys = list(b.TRACKS)
    m01[keys[0]] += share[0]
    m01[keys[1]] += share[1]
    m01[keys[2]] += x["screened"] - share[0] - share[1]
    by_track["M01"] = m01
    m03 = {t: rs["claims_by_track"][t] for t in b.TRACKS}
    m03[keys[0]] += x["claims"] // 2
    m03[keys[1]] += x["claims"] - x["claims"] // 2
    if all(v >= 5 for v in m03.values()):
        by_track["M03"] = m03
    months = [a for a in ACTIVITY if a["month"] <= as_of[:7]]
    return {"snapshot": name, "as_of": as_of, "released": released, "metrics_version": "1.1", "sample": True,
            "programme": PROGRAMME, "totals": totals,
            "unresolved_reasons": {"source_limited": rs["unresolved"] + x["unres"]},
            "examined_by_track": by_track, "activity": months}


def make_updates():
    items = []
    rel_title = {"1.0": "released"}
    for r in RECORDS:
        last = r["changelog"][-1]
        if last["version"] != r["version"]:
            continue
        if r["version"] == "1.0":
            n = len(r["claims"])
            items.append({"date": r["released"], "type": "release",
                          "title": f"{r['public_id']} released: {r['title']}, {n} claim{'s' if n > 1 else ''}",
                          "body": r["headline"], "links": [r["public_id"]]})
        else:
            typ = "correction" if last.get("our_correction") else "revision"
            items.append({"date": r["released"], "type": typ,
                          "title": f"{r['public_id']} version {r['version']}" + (" (our correction)" if last.get("our_correction") else ""),
                          "body": last["change"], "links": [r["public_id"]]})
    items += [{"date": "2027-04-05", "type": "snapshot", "title": "Statistics snapshot for March 2027",
               "body": "Programme-wide counts under metric definitions version 1.1.", "links": ["statistics"]},
              {"date": "2027-07-05", "type": "snapshot", "title": "Statistics snapshot for June 2027",
               "body": "Quarterly figures on author positions were refreshed.", "links": ["statistics"]}]
    items.sort(key=lambda u: u["date"], reverse=True)
    del rel_title
    return {"sample": True, "updated": items[0]["date"], "items": items}


def write_json(path, obj, prefix):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False).replace("DEMO-2027-", f"{prefix}-2027-")
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def main():
    import argparse
    import shutil
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="DEMO", help="record identifier prefix for demonstration records")
    ap.add_argument("--channel", default="sample", help="content/<channel> to write (default sample)")
    a = ap.parse_args()
    out = ROOT / "content" / a.channel
    for sub in ("records", "snapshots"):
        if (out / sub).exists():
            shutil.rmtree(out / sub)
    b = _build_module()
    for r in RECORDS:
        rid = r["public_id"].replace("DEMO-", a.prefix + "-")
        write_json(out / "records" / rid / f"v{r['version']}.json", r, a.prefix)
    snaps = [make_snapshot(b, "2027-03", "2027-03-31", "2027-04-05"), make_snapshot(b, "2027-06", "2027-06-30", "2027-07-05")]
    for s in snaps:
        write_json(out / "snapshots" / f"{s['snapshot']}.json", s, a.prefix)
    write_json(out / "updates.json", make_updates(), a.prefix)
    n_claims = sum(len(r["claims"]) for r in _Records(RECORDS).latest_all())
    print(f"wrote {len(RECORDS)} record versions ({len(_Records(RECORDS).records)} papers, {n_claims} claims), "
          f"{len(snaps)} snapshots and updates to {out} (prefix {a.prefix})")


if __name__ == "__main__":
    main()
