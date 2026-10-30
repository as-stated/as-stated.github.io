#!/usr/bin/env python3
"""Write the FICTIONAL sample content used by the preview build.

Every paper, author, journal, DOI, date and number written by this script is
invented. DOIs use the Crossref test prefix 10.5555. Topics were chosen so that
no sample case resembles a real investigation.

Run:   python make_sample_content.py          (writes content/sample with DEMO- identifiers)
Then:  python build.py sign-sample            (signs the sample channel with a new throwaway demonstration key)
       and update the TRUST_FINGERPRINTS repository variable to the new key's fingerprint (see README).
"""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "content" / "sample"

JOURNAL = "Journal of Hypothetical Economic Theory (fictional)"
AI_USE = ("Discovery and one separate recheck used AI models in separate sessions. "
          "The independent reproduction, the version-of-record check and the editorial "
          "decision were done by the researcher.")
NEGATIVE_AI_USE = ("The search was run with AI assistance and rerun by the researcher; "
                   "the version-of-record check and the editorial decision were done by the researcher.")


def fake_sha(label):
    return hashlib.sha256(("sample:" + label).encode()).hexdigest()


def evidence(n, files):
    return {
        "package_doi": f"10.5555/sample-evidence.{n:04d}",
        "package_sha256": fake_sha(f"package-{n}"),
        "licence": "CC BY 4.0 (text); MIT (code)",
        "files": [{"name": f, "sha256": fake_sha(f"{n}-{f}")} for f in files],
    }


# ------------------------------------------------------------------ DEMO-2027-001
r1_v10 = {
    "public_id": "DEMO-2027-001",
    "version": "1.0",
    "released": "2027-03-15",
    "status": "published",
    "sample": True,
    "kind": "defect",
    "track": "game_theory",
    "title": "Proposition 4 and Theorem 2 in Doe and Roe (2025)",
    "headline": ("Proposition 4 is false as printed (an application). Theorem 2, the main result, "
                 "is not affected; a deep audit found no defect in it."),
    "work": {"authors": ["Jane Doe", "Richard Roe"], "title": "Monotone Allocation Rules in Finite Contests",
             "venue": JOURNAL, "year": 2025, "volume": "41", "pages": "105912",
             "doi": "10.5555/sample.0001"},
    "claims": [
        {
            "label": "Proposition 4", "page": "19", "kind": "application", "role": "secondary",
            "statement": ("In every two-prize contest with n ≥ 3 contestants, the rank-order rule is the "
                          "unique allocation rule that is monotone, anonymous and budget-balanced."),
            "conditions": ["two prizes", "n ≥ 3 contestants", "budget balance with equality"],
            "quantifiers": "for every n ≥ 3; uniqueness among monotone, anonymous, budget-balanced rules",
            "result": {
                "outcome": "defect_found", "candidate_status": "confirmed",
                "defect_class": "statement_false", "affects": "application_or_example",
                "depth": "deep_audit",
                "witness": ("For n = 3 and prize vector (1, ½), a second rule satisfies every stated "
                            "condition. The full allocation table is in the evidence package."),
                "repair": "local_repair_proposed",
                "repair_note": "Requiring strict monotonicity restores uniqueness in all cases checked.",
                "not_claimed": ["Theorem 2, the paper's main characterization, is not refuted.",
                                "The proposition is not claimed to fail for n = 2."],
            },
            "vor_check": {"level": "full", "pages": "18–19",
                          "detail": "Statement, definitions and the decisive example checked on rendered pages of the published version."},
            "checks": [
                {"kind": "ai_recheck", "session": "blind", "date": "2027-02", "result": "confirms",
                 "detail": "A separate AI session, not given the earlier result, rebuilt the example from the printed definitions."},
                {"kind": "independent_reproduction", "date": "2027-02", "result": "confirms",
                 "detail": "The researcher verified the example with separately written code in exact rational arithmetic."},
                {"kind": "author_agreement", "date": "2027-03", "result": "confirms",
                 "detail": "The authors agreed in writing that the proposition is false as printed."},
            ],
            "reproduction": {"result": "pass", "detail": "The evidence package reruns with one command (Python 3.12, standard library only)."},
            "novelty": "No earlier report found in the searched record as of February 2027.",
        },
        {
            "label": "Theorem 2", "page": "11", "kind": "theorem", "role": "main",
            "statement": "A monotone, anonymous allocation rule on a finite contest is implementable by single-crossing payments.",
            "conditions": ["finite contest", "strictly ordered types"],
            "quantifiers": "for every finite contest and every monotone, anonymous rule",
            "result": {
                "outcome": "no_defect_found", "depth": "deep_audit",
                "search_scope": ("All monotone, anonymous rules for n = 2 to 5 on a seven-point type grid; "
                                 "the proof read line by line."),
                "limits": "Infinite type spaces are covered by the proof reading only.",
            },
            "vor_check": {"level": "partial", "pages": "11–14",
                          "detail": "Statement and definitions checked on rendered pages; the proof compared in extracted text only."},
            "checks": [],
            "reproduction": {"result": "pass", "detail": "Search code rerun from the archived package."},
            "novelty": None,
        },
    ],
    "author_position": {"position": "agrees",
                        "summary": "The authors confirmed the counterexample and said they would submit a corrigendum."},
    "correction": None,
    "evidence": evidence(1, ["README.md", "certificate.json", "run_all.py", "search_theorem2.py"]),
    "history": [
        {"date": "2027-01", "type": "audit", "label": "Discovery audit completed"},
        {"date": "2027-02", "type": "check", "label": "Rechecked by a separate AI session: confirms"},
        {"date": "2027-02", "type": "check", "label": "Independently reproduced by the researcher: confirms"},
        {"date": "2027-02", "type": "source", "label": "Checked against the version of record: full"},
        {"date": "2027-02", "type": "authors", "label": "Authors notified and offered the opportunity to respond"},
        {"date": "2027-03", "type": "authors", "label": "Authors agreed that the proposition is false as printed"},
        {"date": "2027-03-15", "type": "release", "label": "Record version 1.0 released"},
    ],
    "challenges": [],
    "changelog": [{"version": "1.0", "date": "2027-03-15", "change": "First release."}],
    "statements": {"ai_use": AI_USE},
}

r1_v11 = copy.deepcopy(r1_v10)
r1_v11.update({"version": "1.1", "released": "2027-05-10"})
r1_v11["correction"] = {"type": "corrigendum", "doi": "10.5555/sample.0001c", "date": "2027-05-02",
                        "relation": "after_notification", "attribution": "credits_programme",
                        "note": "The corrigendum states that the error was reported by this audit."}
r1_v11["history"] += [{"date": "2027-05-02", "type": "correction", "label": "Corrigendum published (credits this audit)"},
                      {"date": "2027-05-10", "type": "release", "label": "Record version 1.1 released"}]
r1_v11["changelog"].append({"version": "1.1", "date": "2027-05-10", "change": "Added the published corrigendum. Findings unchanged."})

r1_v12 = copy.deepcopy(r1_v11)
r1_v12.update({"version": "1.2", "released": "2027-06-12"})
r1_v12["claims"][0]["checks"].append(
    {"kind": "external_human", "date": "2027-06", "result": "confirms",
     "detail": "Alex Example (fictional outside researcher) reproduced the example independently and published a short report."})
r1_v12["challenges"] = [{"type": "replication", "date": "2027-06-05", "by": "Alex Example (fictional)",
                         "outcome": "Confirms the finding", "response": None}]
r1_v12["history"] += [{"date": "2027-06-05", "type": "contribution", "label": "External replication by Alex Example (fictional)"},
                      {"date": "2027-06-12", "type": "release", "label": "Record version 1.2 released"}]
r1_v12["changelog"].append({"version": "1.2", "date": "2027-06-12", "change": "Added an external human verification."})

# ------------------------------------------------------------------ DEMO-2027-002 (negative)
r2 = {
    "public_id": "DEMO-2027-002", "version": "1.0", "released": "2027-03-15", "status": "published", "sample": True,
    "kind": "negative", "track": "game_theory",
    "title": "Theorem 1 in Sample (2024)",
    "headline": "No defect found in Theorem 1 within the stated scope (deep audit). This is not a proof that the theorem is correct.",
    "work": {"authors": ["Ada Sample"], "title": "Equilibrium Uniqueness in Linear-Quadratic Network Games",
             "venue": JOURNAL, "year": 2024, "volume": "38", "pages": "105233", "doi": "10.5555/sample.0002"},
    "claims": [{
        "label": "Theorem 1", "page": "7", "kind": "theorem", "role": "main",
        "statement": ("If the spectral radius of the interaction matrix is below the stated bound, "
                      "the network game has a unique Nash equilibrium, and it is interior."),
        "conditions": ["linear-quadratic payoffs", "symmetric interaction matrix", "spectral radius below the stated bound"],
        "quantifiers": "for every network satisfying the spectral condition",
        "result": {
            "outcome": "no_defect_found", "depth": "deep_audit",
            "search_scope": ("All networks with up to six players on a grid of interaction weights, with boundary "
                             "cases of the spectral condition; the proof read line by line."),
            "limits": "Networks with more than six players are covered by the proof reading only.",
        },
        "vor_check": {"level": "full", "pages": "6–9",
                      "detail": "Statement, assumptions and proof checked on rendered pages of the published version."},
        "checks": [],
        "reproduction": {"result": "pass", "detail": "Search code rerun by the researcher from the archived package."},
        "novelty": None,
    }],
    "author_position": {"position": "courtesy_notice", "summary": None},
    "correction": None,
    "evidence": evidence(2, ["README.md", "search_networks.py", "results.json"]),
    "history": [
        {"date": "2027-01", "type": "audit", "label": "Deep audit completed: no defect found"},
        {"date": "2027-02", "type": "reproduction", "label": "Evidence package rerun: pass"},
        {"date": "2027-03", "type": "authors", "label": "Courtesy notice sent to the author"},
        {"date": "2027-03-15", "type": "release", "label": "Record version 1.0 released"},
    ],
    "challenges": [],
    "changelog": [{"version": "1.0", "date": "2027-03-15", "change": "First release."}],
    "statements": {"ai_use": NEGATIVE_AI_USE},
}

# ------------------------------------------------------------------ DEMO-2027-003
r3 = {
    "public_id": "DEMO-2027-003", "version": "1.0", "released": "2027-05-28", "status": "published", "sample": True,
    "kind": "defect", "track": "optimization",
    "title": "Lemma 3 in Placeholder and Fictive (2023)",
    "headline": ("A step in the proof of Lemma 3 needs an extra condition (a repairable proof gap). "
                 "Theorem 1 is not refuted. An erratum was published after the authors were notified."),
    "work": {"authors": ["Kim Placeholder", "Lee Fictive"],
             "title": "Optimal Base-Stock Policies under Lost Sales with Random Yield",
             "venue": "Review of Hypothetical Operations (fictional)", "year": 2023, "volume": "17", "pages": "211–240",
             "doi": "10.5555/sample.0003"},
    "claims": [{
        "label": "Lemma 3", "page": "222", "kind": "lemma", "role": "auxiliary",
        "statement": "The expected one-period cost is convex in the order-up-to level for every yield distribution with finite mean.",
        "conditions": ["lost sales", "yield distribution with finite mean"],
        "quantifiers": "for every yield distribution with finite mean",
        "result": {
            "outcome": "defect_found", "candidate_status": "confirmed",
            "defect_class": "proof_gap_repairable", "affects": "lemma_or_proof_step", "depth": "deep_audit",
            "witness": ("The interchange of differentiation and expectation in the proof needs a bounded density, "
                        "which the lemma does not assume. A two-point yield distribution shows the step fails."),
            "repair": "repair_checked",
            "repair_note": "Adding a bounded-density assumption restores the step; the conclusion holds in all cases checked.",
            "not_claimed": ["Theorem 1 (optimality of base-stock policies) is not refuted.",
                            "The convexity conclusion is not claimed to be false; only the proof step is incomplete."],
        },
        "vor_check": {"level": "full", "pages": "221–223",
                      "detail": "Statement, assumptions and the proof step checked on rendered pages of the published version."},
        "checks": [
            {"kind": "ai_recheck", "session": "informed", "date": "2027-03", "result": "confirms",
             "detail": "A separate AI session, given the earlier report, rechecked the proof step."},
            {"kind": "independent_reproduction", "date": "2027-03", "result": "confirms",
             "detail": "The researcher checked the step by hand and reproduced the two-point example."},
        ],
        "reproduction": {"result": "pass", "detail": "Example computation rerun from the archived package."},
        "novelty": "No earlier report found in the searched record as of March 2027.",
    }],
    "author_position": {"position": "partly_agrees",
                        "summary": ("The authors accept that the step needs an extra condition and consider the main "
                                    "result unaffected, which this record also states.")},
    "correction": {"type": "erratum", "doi": "10.5555/sample.0003e", "date": "2027-05-20",
                   "relation": "after_notification", "attribution": "none_stated",
                   "note": "The erratum does not mention this audit. We do not claim that it resulted from our work."},
    "evidence": evidence(3, ["README.md", "two_point_example.py", "proof_step_note.pdf"]),
    "history": [
        {"date": "2027-02", "type": "audit", "label": "Discovery audit completed"},
        {"date": "2027-03", "type": "check", "label": "Rechecked by a separate AI session: confirms"},
        {"date": "2027-03", "type": "check", "label": "Independently reproduced by the researcher: confirms"},
        {"date": "2027-03", "type": "source", "label": "Checked against the version of record: full"},
        {"date": "2027-03", "type": "authors", "label": "Authors notified and offered the opportunity to respond"},
        {"date": "2027-04", "type": "authors", "label": "Authors partly agreed"},
        {"date": "2027-05-20", "type": "correction", "label": "Erratum published (no attribution stated)"},
        {"date": "2027-05-28", "type": "release", "label": "Record version 1.0 released"},
    ],
    "challenges": [],
    "changelog": [{"version": "1.0", "date": "2027-05-28", "change": "First release."}],
    "statements": {"ai_use": AI_USE},
}

# ------------------------------------------------------------------ DEMO-2027-004 (disputed)
r4 = {
    "public_id": "DEMO-2027-004", "version": "1.0", "released": "2027-06-24", "status": "published", "sample": True,
    "kind": "defect", "track": "probability",
    "title": "Theorem 2 in Sample (2026)",
    "headline": ("The upper bound in Theorem 2 fails for claim-size distributions that the stated assumptions allow "
                 "(a missing assumption). The authors disagree; their reply is summarised below."),
    "work": {"authors": ["Morgan Sample"], "title": "Bounds on Ruin Probabilities for Compound Renewal Processes",
             "venue": "Journal of Hypothetical Probability (fictional)", "year": 2026, "volume": "12", "pages": "1–29",
             "doi": "10.5555/sample.0004"},
    "claims": [{
        "label": "Theorem 2", "page": "9", "kind": "theorem", "role": "main",
        "statement": ("For every claim-size distribution with a finite second moment, the ruin probability is "
                      "bounded above by the stated exponential expression."),
        "conditions": ["compound renewal process", "claim sizes with finite second moment", "positive safety loading"],
        "quantifiers": "for every claim-size distribution with a finite second moment",
        "result": {
            "outcome": "defect_found", "candidate_status": "confirmed",
            "defect_class": "missing_or_hidden_assumption", "affects": "main_result", "depth": "deep_audit",
            "witness": ("A claim-size distribution with a finite second moment but an infinite third moment "
                        "violates the bound; the calculation is in the evidence package."),
            "repair": "local_repair_proposed",
            "repair_note": "Assuming a finite third moment restores the bound in all cases checked.",
            "not_claimed": ["The bound is not claimed to fail for distributions with a finite third moment.",
                            "The paper's other results are not examined here."],
        },
        "vor_check": {"level": "partial", "pages": "8–10",
                      "detail": "Statement and assumptions checked on rendered pages; the decisive step compared in extracted text only."},
        "checks": [
            {"kind": "ai_recheck", "session": "blind", "date": "2027-03", "result": "confirms",
             "detail": "A separate AI session, not given the earlier result, found the same failure."},
            {"kind": "independent_reproduction", "date": "2027-03", "result": "confirms",
             "detail": "The researcher reproduced the calculation with separately written code."},
            {"kind": "independent_reproduction", "date": "2027-06", "result": "confirms",
             "detail": "After the authors disagreed, the researcher checked their argument by hand; the counterexample stands."},
        ],
        "reproduction": {"result": "pass", "detail": "Calculation rerun from the archived package."},
        "novelty": "No earlier report found in the searched record as of March 2027.",
    }],
    "author_position": {"position": "disagrees",
                        "summary": ("The authors hold that a convention in Section 2 excludes such distributions. "
                                    "This record quotes that convention and explains why, as printed, it does not "
                                    "exclude them. The authors were offered space for a full reply."),
                        "reply_link": None},
    "correction": None,
    "evidence": evidence(4, ["README.md", "counterexample.py", "convention_note.md"]),
    "history": [
        {"date": "2027-02", "type": "audit", "label": "Discovery audit completed"},
        {"date": "2027-03", "type": "check", "label": "Rechecked by a separate AI session: confirms"},
        {"date": "2027-03", "type": "check", "label": "Independently reproduced by the researcher: confirms"},
        {"date": "2027-03", "type": "authors", "label": "Authors notified and offered the opportunity to respond"},
        {"date": "2027-05", "type": "authors", "label": "Authors disagreed"},
        {"date": "2027-06", "type": "check", "label": "Additional check by the researcher after the dispute: confirms"},
        {"date": "2027-06-24", "type": "release", "label": "Record version 1.0 released"},
    ],
    "challenges": [],
    "changelog": [{"version": "1.0", "date": "2027-06-24", "change": "First release, after the additional check."}],
    "statements": {"ai_use": AI_USE},
}

# ------------------------------------------------------------------ DEMO-2027-005 (negative, corrected by us)
r5_v10 = {
    "public_id": "DEMO-2027-005", "version": "1.0", "released": "2027-04-20", "status": "published", "sample": True,
    "kind": "negative", "track": "mechanism_design",
    "title": "Proposition 2 in Specimen (2023)",
    "headline": "No defect found in Proposition 2 within the stated scope (deep audit). This is not a proof that the result is correct.",
    "work": {"authors": ["Riley Specimen"], "title": "Revenue Equivalence with Budget-Constrained Bidders",
             "venue": JOURNAL, "year": 2023, "volume": "36", "pages": "104812", "doi": "10.5555/sample.0005"},
    "claims": [{
        "label": "Proposition 2", "page": "12", "kind": "proposition", "role": "main",
        "statement": ("With symmetric, independent budgets, the first-price and second-price auctions yield the same "
                      "expected revenue."),
        "conditions": ["symmetric independent private values", "symmetric independent budgets", "risk-neutral bidders"],
        "quantifiers": "for every number of bidders and every symmetric budget distribution",
        "result": {
            "outcome": "no_defect_found", "depth": "deep_audit",
            "search_scope": ("Discretised value and budget distributions for up to five bidders; "
                             "the proof read line by line."),
            "limits": "The online supplement was not obtained and was not examined.",
        },
        "vor_check": {"level": "partial", "pages": "10–14",
                      "detail": "Main text checked on rendered pages; the online supplement was not obtained."},
        "checks": [],
        "reproduction": {"result": "pass", "detail": "Search code rerun by the researcher."},
        "novelty": None,
    }],
    "author_position": {"position": "courtesy_notice", "summary": None},
    "correction": None,
    "evidence": evidence(5, ["README.md", "auction_search.py", "results.csv"]),
    "history": [
        {"date": "2027-03", "type": "audit", "label": "Deep audit completed: no defect found"},
        {"date": "2027-04", "type": "authors", "label": "Courtesy notice sent to the author"},
        {"date": "2027-04-20", "type": "release", "label": "Record version 1.0 released"},
    ],
    "challenges": [],
    "changelog": [{"version": "1.0", "date": "2027-04-20", "change": "First release."}],
    "statements": {"ai_use": NEGATIVE_AI_USE},
}
r5_v11 = copy.deepcopy(r5_v10)
r5_v11.update({"version": "1.1", "released": "2027-05-02"})
r5_v11["claims"][0]["result"]["search_scope"] = ("Discretised value and budget distributions for up to four bidders; "
                                                 "the proof read line by line.")
r5_v11["history"].append({"date": "2027-05-02", "type": "release",
                          "label": "Record version 1.1 released (our correction to the scope statement)"})
r5_v11["changelog"].append({"version": "1.1", "date": "2027-05-02", "our_correction": True,
                            "change": "Corrected our error: the search covered up to four bidders, not five as version 1.0 stated."})

# ------------------------------------------------------------------ DEMO-2027-006 (proof incomplete)
r6 = {
    "public_id": "DEMO-2027-006", "version": "1.0", "released": "2027-06-28", "status": "published", "sample": True,
    "kind": "defect", "track": "econometrics",
    "title": "Corollary 2 in Example and Instance (2025)",
    "headline": ("The proof of Corollary 2 does not establish it: a step applies Lemma 4 uniformly, but the lemma is only "
                 "pointwise. No counterexample was found, so the corollary itself remains open (proof incomplete)."),
    "work": {"authors": ["Casey Example", "Jordan Instance"],
             "title": "Identification of Random Coefficients in Binary Choice with a Special Regressor",
             "venue": "Journal of Hypothetical Econometrics (fictional)", "year": 2025, "volume": "9", "pages": "77–102",
             "doi": "10.5555/sample.0006"},
    "claims": [{
        "label": "Corollary 2", "page": "88", "kind": "corollary", "role": "secondary",
        "statement": ("Under Assumptions 1–3, the distribution of the random coefficients is identified from the "
                      "conditional choice probabilities."),
        "conditions": ["special regressor with large support", "special regressor conditionally independent of the coefficients",
                       "Assumptions 1–3 of Section 2"],
        "quantifiers": "for every coefficient distribution satisfying Assumptions 1–3",
        "result": {
            "outcome": "defect_found", "candidate_status": "confirmed",
            "defect_class": "proof_invalid_statement_open", "affects": "secondary_result", "depth": "deep_audit",
            "witness": ("The proof applies Lemma 4 uniformly over the support of the special regressor, but Lemma 4 is stated "
                        "pointwise. A bounded example shows the uniform version of Lemma 4 fails under Assumptions 1–3."),
            "repair": "none_proposed",
            "repair_note": "A uniform version of Lemma 4 under an added tail condition may complete the proof; we have not checked this.",
            "not_claimed": ["Corollary 2 is not claimed to be false.",
                            "Theorem 1, the paper's main identification result, is not affected."],
        },
        "vor_check": {"level": "full", "pages": "86–89",
                      "detail": "Statement, assumptions, Lemma 4 and the proof step checked on rendered pages of the published version."},
        "checks": [
            {"kind": "ai_recheck", "session": "informed", "date": "2027-02", "result": "confirms",
             "detail": "A separate AI session, given the earlier report, rechecked the proof step and the example."},
            {"kind": "independent_reproduction", "date": "2027-03", "result": "confirms",
             "detail": "The researcher checked the step by hand and verified the example."},
        ],
        "reproduction": {"result": "pass", "detail": "Example computation rerun from the archived package."},
        "novelty": "No earlier report found in the searched record as of March 2027.",
    }],
    "author_position": {"position": "none_yet", "summary": None},
    "correction": None,
    "evidence": evidence(6, ["README.md", "pointwise_vs_uniform.py", "proof_step_note.pdf"]),
    "history": [
        {"date": "2027-02", "type": "audit", "label": "Discovery audit completed"},
        {"date": "2027-02", "type": "check", "label": "Rechecked by a separate AI session: confirms"},
        {"date": "2027-03", "type": "check", "label": "Independently reproduced by the researcher: confirms"},
        {"date": "2027-03", "type": "source", "label": "Checked against the version of record: full"},
        {"date": "2027-03", "type": "authors", "label": "Authors notified and offered the opportunity to respond"},
        {"date": "2027-06-28", "type": "release", "label": "Record version 1.0 released, 90 days after notification without a substantive reply"},
    ],
    "challenges": [],
    "changelog": [{"version": "1.0", "date": "2027-06-28", "change": "First release."}],
    "statements": {"ai_use": AI_USE},
}

RECORDS = [r1_v10, r1_v11, r1_v12, r2, r3, r4, r5_v10, r5_v11, r6]

# ------------------------------------------------------------------ snapshots (fictional numbers)
PROGRAMME = {"id": "targeted-2026",
             "description": ("Current selection: recent articles in leading theory journals, and results "
                             "with features where errors often hide.")}

SNAPSHOTS = [
    {
        "snapshot": "2027-03", "as_of": "2027-03-31", "released": "2027-04-05", "metrics_version": "1.1", "sample": True,
        "programme": PROGRAMME,
        "totals": {"M01": 30, "M02": 12, "M03": 16, "M04": 11, "M05": 6,
                   "M06": {"open": 1, "confirmed": 3, "unresolved": 1, "rejected": 1,
                           "open_ai_supported": 0, "confirmed_previously_reported": 0},
                   "M07": {"vor_full": 4, "vor_partial": 2, "vor_none": 0},
                   "M08": {"blind": 2, "informed": 1}, "M09": 3, "M10": 0,
                   "M11": {"full": 2, "partial": 1, "none": 0},
                   "M12": 3, "M13": {"agreed": 1, "partly_agreed": 0, "disagreed": 0, "none_yet": 2},
                   "M17": {"checked": 1, "known_errors_refound": 1}},
        "unresolved_reasons": {"source_limited": 1},
        "examined_by_track": {
            "M01": {"game_theory": 12, "mechanism_design": 8, "matching_social_choice": 6, "optimization": None,
                    "econometrics": 0, "probability": None},
            "M03": {"game_theory": 7, "mechanism_design": None, "matching_social_choice": None, "optimization": None,
                    "econometrics": 0, "probability": None},
        },
        "activity": [
            {"month": "2027-01", "discovery": 6, "hostile_validation": 3, "source_lock": 1, "package_rerun": 2},
            {"month": "2027-02", "discovery": 5, "hostile_validation": 4, "source_lock": 2, "package_rerun": 3},
            {"month": "2027-03", "discovery": 4, "hostile_validation": 3, "source_lock": 2, "package_rerun": 2},
        ],
    },
    {
        "snapshot": "2027-06", "as_of": "2027-06-30", "released": "2027-07-05", "metrics_version": "1.1", "sample": True,
        "programme": PROGRAMME,
        "totals": {"M01": 61, "M02": 23, "M03": 31, "M04": 21, "M05": 11,
                   "M06": {"open": 2, "confirmed": 6, "unresolved": 1, "rejected": 2,
                           "open_ai_supported": 1, "confirmed_previously_reported": 1},
                   "M07": {"vor_full": 8, "vor_partial": 3, "vor_none": 1},
                   "M08": {"blind": 4, "informed": 2}, "M09": 6, "M10": 1,
                   "M11": {"full": 4, "partial": 2, "none": 0},
                   "M12": 5, "M13": {"agreed": 1, "partly_agreed": 1, "disagreed": 1, "none_yet": 2},
                   "M17": {"checked": 2, "known_errors_refound": 2}},
        "unresolved_reasons": {"source_limited": 1},
        "examined_by_track": {
            "M01": {"game_theory": 22, "mechanism_design": 15, "matching_social_choice": 11, "optimization": 6,
                    "econometrics": None, "probability": None},
            "M03": {"game_theory": 11, "mechanism_design": 7, "matching_social_choice": 5, "optimization": None,
                    "econometrics": None, "probability": None},
        },
        "activity": [
            {"month": "2027-01", "discovery": 6, "hostile_validation": 3, "source_lock": 1, "package_rerun": 2},
            {"month": "2027-02", "discovery": 5, "hostile_validation": 4, "source_lock": 2, "package_rerun": 3},
            {"month": "2027-03", "discovery": 4, "hostile_validation": 3, "source_lock": 2, "package_rerun": 2},
            {"month": "2027-04", "discovery": 5, "hostile_validation": 3, "source_lock": 1, "package_rerun": 2},
            {"month": "2027-05", "discovery": 4, "hostile_validation": 4, "source_lock": 2, "package_rerun": 1},
            {"month": "2027-06", "discovery": 3, "hostile_validation": 3, "source_lock": 1, "package_rerun": 2},
        ],
    },
]

UPDATES = {"sample": True, "updated": "2027-07-05", "items": [
    {"date": "2027-07-05", "type": "snapshot", "title": "Statistics snapshot for June 2027",
     "body": "Quarterly figures on author positions were refreshed. Six records are now public.", "links": ["statistics"]},
    {"date": "2027-06-28", "type": "release", "title": "DEMO-2027-006 released: proof incomplete",
     "body": "Released 90 days after the authors were notified, without a substantive reply. The corollary is not claimed to be false.",
     "links": ["DEMO-2027-006"]},
    {"date": "2027-06-24", "type": "release", "title": "DEMO-2027-004 released: the authors disagree",
     "body": "Released after an additional check by the researcher. The authors' position is summarised in the record.",
     "links": ["DEMO-2027-004"]},
    {"date": "2027-06-12", "type": "revision", "title": "DEMO-2027-001 version 1.2: external replication",
     "body": "An outside researcher reproduced the counterexample independently.", "links": ["DEMO-2027-001"]},
    {"date": "2027-05-28", "type": "release", "title": "DEMO-2027-003 released after a published erratum",
     "body": "The erratum does not mention this audit; the record says so.", "links": ["DEMO-2027-003"]},
    {"date": "2027-05-10", "type": "revision", "title": "DEMO-2027-001 version 1.1: corrigendum published",
     "body": "The journal published a corrigendum that credits this audit.", "links": ["DEMO-2027-001"]},
    {"date": "2027-05-02", "type": "correction", "title": "Our correction to DEMO-2027-005",
     "body": "Version 1.0 overstated the search scope (five bidders instead of four). Version 1.1 corrects it.",
     "links": ["DEMO-2027-005"]},
    {"date": "2027-04-20", "type": "release", "title": "DEMO-2027-005 released: a negative deep audit",
     "body": "No defect found within the stated scope.", "links": ["DEMO-2027-005"]},
    {"date": "2027-04-05", "type": "snapshot", "title": "First statistics snapshot (March 2027)",
     "body": "Programme-wide counts under metric definitions version 1.1.", "links": ["statistics"]},
    {"date": "2027-03-15", "type": "release", "title": "First records released",
     "body": "DEMO-2027-001 (a confirmed defect in an application) and DEMO-2027-002 (a negative deep audit). Methodology version 1.0 published.",
     "links": ["DEMO-2027-001", "DEMO-2027-002", "methodology"]},
]}


def write_json(path, obj, prefix):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False).replace("DEMO-2027-", f"{prefix}-2027-")
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="DEMO", help="record identifier prefix for demonstration records")
    ap.add_argument("--channel", default="sample", help="content/<channel> to write (default sample)")
    a = ap.parse_args()
    out = ROOT / "content" / a.channel
    for r in RECORDS:
        rid = r["public_id"].replace("DEMO-", a.prefix + "-")
        write_json(out / "records" / rid / f"v{r['version']}.json", r, a.prefix)
    for s in SNAPSHOTS:
        write_json(out / "snapshots" / f"{s['snapshot']}.json", s, a.prefix)
    write_json(out / "updates.json", UPDATES, a.prefix)
    print(f"wrote {len(RECORDS)} record versions, {len(SNAPSHOTS)} snapshots and updates to {out} (prefix {a.prefix})")


if __name__ == "__main__":
    main()
