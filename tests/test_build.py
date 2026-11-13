"""Tests for build.py. Run from the project folder:  python -m unittest discover -s tests -v

Tests generate their data at run time with tests/fixtures.py, so a fresh clone needs nothing else.

The layout tests need Microsoft Edge or Google Chrome; they are skipped when neither is installed."""
import functools
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
sys.path.insert(0, str(ROOT / "tests"))
import fixtures  # noqa: E402

PUBLISHED = "content/published"
LATEST_SNAPSHOT = PUBLISHED + "/snapshots/2000-06.json"
# Assembled so that this file itself passes the public-tree check below.
RETIRED_PREFIX = "DE" + "MO"
BANNED_OUTPUT = (RETIRED_PREFIX + r"[-_]\d|\b" + RETIRED_PREFIX.lower() + r"\b|[Ff]ict" + "ional|[Dd]emon" + "stration|10\\.5555|"
                 + r"\"sample\": true|sample-banner|the authors have been\s+contacted|release has been signed|authors were notified|"
                 + r"[Cc]ourtesy notice|notified papers|after notification")
BANNED_TREE = RETIRED_PREFIX + r"-20\d\d|[Ff]ict" + "ional|[Dd]emon" + r"stration|10\.5555|content/sam" + "ple|sample_allowed_" + "signers"
OLD_BRANDS = re.compile(r"Theorem Audit|Second Referee|Reviewer\s*(#\s*2|2|Two)|TA-20\d\d|SR-20\d\d", re.I)


def edit_json(path, fn):
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.h1 = [], set(), 0
        self.lang = None
        self.title = False
        self.robots = None
        self.stylesheets, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "h1":
            self.h1 += 1
        if tag == "title":
            self.title = True
        if tag == "meta" and a.get("name") == "robots":
            self.robots = a.get("content")
        if tag == "link" and a.get("rel") == "stylesheet":
            self.stylesheets.append(a.get("href"))
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        if "id" in a:
            self.ids.add(a["id"])
        for attr in ("href", "src"):
            if a.get(attr):
                self.links.append(a[attr])


def parse(path):
    c = Collector()
    c.feed(path.read_text(encoding="utf-8"))
    return c


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="as_test_"))
        cls.proj = fixtures.make_project(build, cls.tmp / "proj")
        cls.site, cls.content, cls.out = build.build(None, cls.tmp / "dist", root=cls.proj)
        cls.site_p, cls.content_p, cls.out_p = build.build(None, cls.tmp / "site", pretty=True, root=cls.proj)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def html_files(self, out=None):
        return sorted((out or self.out).rglob("*.html"))

    def rel(self, f, out=None):
        return f.relative_to(out or self.out).as_posix()

    def test_brand_and_channel(self):
        self.assertEqual(self.site.cfg["name"], "As Stated")
        self.assertEqual(self.content.channel, "published")
        self.assertTrue(self.content.records)
        home = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("As Stated", home)
        self.assertIn("Independent scrutiny of published mathematical and theoretical claims.", home)
        self.assertIn("What was claimed. What was tested. What survived.", home)

    def test_no_earlier_brand_names_or_identifiers_in_output(self):
        for f in sorted(p for p in self.out_p.rglob("*") if p.is_file()):
            found = OLD_BRANDS.search(f.read_text(encoding="utf-8", errors="replace"))
            self.assertIsNone(found, f"{self.rel(f, self.out_p)}: {found and found.group(0)}")

    def test_content_prefix_must_match_site(self):
        root = fixtures.make_project(build, self.tmp / "prefix_proj")
        edit_json(root / "site.json", lambda c: c.update(id_prefix="XYZ"))
        with self.assertRaisesRegex(build.BuildError, "identifier prefix"):
            build.build(None, self.tmp / "dist_prefix", root=root)

    def test_expected_pages_exist(self):
        for p in ["index.html", "cases/index.html", "statistics/index.html", "statistics/2000-03/index.html",
                  "methodology/index.html", "definitions/index.html", "updates/index.html", "about/index.html",
                  "404.html", "feed.xml", "cases/TEST-2000-001/index.html", "cases/TEST-2000-002/v1.0/index.html",
                  "data/records/TEST-2000-002/v1.2.json", "data/snapshots/2000-06.json", "robots.txt",
                  "sitemap.xml", ".nojekyll", "static/style.css", "static/app.js", "static/favicon.svg"]:
            self.assertTrue((self.out_p / p).exists(), p)

    def test_every_page_is_well_formed(self):
        for out in (self.out, self.out_p):
            for f in self.html_files(out):
                text = f.read_text(encoding="utf-8")
                c = Collector()
                c.feed(text)
                self.assertEqual(c.lang, "en", f)
                self.assertTrue(c.title, f)
                self.assertEqual(c.h1, 1, f"{f}: expected exactly one h1")
                self.assertEqual(len(c.stylesheets), 1, f)
                self.assertEqual(len(c.scripts), 1, f)

    def test_every_page_is_indexable_and_listed(self):
        pages = []
        for f in self.html_files(self.out_p):
            self.assertIsNone(parse(f).robots, self.rel(f, self.out_p))
            if self.rel(f, self.out_p) != "404.html":
                pages.append(self.rel(f, self.out_p))
        robots_txt = (self.out_p / "robots.txt").read_text()
        self.assertIn("Allow: /", robots_txt)
        self.assertIn("Sitemap: https://as-stated.github.io/sitemap.xml", robots_txt)
        locs = re.findall(r"<loc>([^<]+)</loc>", (self.out_p / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertEqual(sorted(locs), sorted("https://as-stated.github.io/" + p.replace("index.html", "") for p in pages))

    def test_no_external_scripts_styles_or_fonts(self):
        for f in self.html_files(self.out_p):
            c = parse(f)
            for ref in c.stylesheets + c.scripts:
                self.assertFalse(re.match(r"^(https?:)?//", ref), f"{f}: external resource {ref}")
        css = (self.out_p / "static/style.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"@import|url\(\s*['\"]?(https?:)?//")

    def check_links(self, out):
        ids = {f.resolve(): parse(f).ids for f in self.html_files(out)}
        for f in self.html_files(out):
            for link in parse(f).links:
                if re.match(r"^(https?:|mailto:)", link):
                    continue
                path, _, anchor = link.partition("#")
                target = (f.parent / path).resolve() if path else f.resolve()
                if target.is_dir():
                    target = target / "index.html"
                self.assertTrue(target.exists(), f"{f.relative_to(out)} links to missing {link}")
                if anchor and target.suffix == ".html":
                    self.assertIn(anchor, ids[target], f"{f.relative_to(out)}: missing anchor {link}")

    def test_internal_links_and_anchors_resolve(self):
        self.check_links(self.out)

    def test_internal_links_resolve_with_pretty_urls(self):
        self.check_links(self.out_p)
        for f in self.html_files(self.out_p):
            for link in parse(f).links:
                self.assertNotRegex(link, r"(^|/)index\.html", f"{self.rel(f, self.out_p)}: {link}")

    def test_outcome_distinctions_are_defined(self):
        defs = (self.out_p / "definitions/index.html").read_text(encoding="utf-8")
        for label in ["No defect found", "False as stated", "Proof incomplete", "Missing assumption",
                      "Construction fails", "Unresolved"]:
            self.assertIn(label, defs)
        self.assertIn("not a proof that the claim is correct", defs)

    def test_negative_audits_carry_the_caveat_and_defects_the_non_claims(self):
        for rid, versions in self.content.records.items():
            page = (self.out / "cases" / rid / "index.html").read_text(encoding="utf-8")
            if versions[-1]["kind"] == "negative":
                self.assertIn(build.NEGATIVE_CAVEAT, page, rid)
            else:
                self.assertIn("What is not claimed", page, rid)

    def test_archived_versions_point_to_current(self):
        page = (self.out_p / "cases/TEST-2000-002/v1.0/index.html").read_text(encoding="utf-8")
        self.assertIn("Archived version 1.0. The current version is", page)
        current = (self.out_p / "cases/TEST-2000-002/index.html").read_text(encoding="utf-8")
        self.assertNotIn("Archived version", current)

    def test_selection_statement_on_number_pages(self):
        for p in ["index.html", "statistics/index.html", "cases/index.html"]:
            self.assertIn("not sampled at random", (self.out / p).read_text(encoding="utf-8"), p)

    def test_index_has_one_row_per_claim_grouped_by_paper(self):
        page = (self.out_p / "cases/index.html").read_text(encoding="utf-8")
        recs = self.content.latest_all()
        self.assertEqual(page.count('class="ix-group"'), len(recs))
        self.assertEqual(page.count('<tr class="ix-row"'), sum(len(r["claims"]) for r in recs))

    def test_index_omits_private_fields(self):
        for f in ["cases/index.html", "index.html"]:
            text = (self.out_p / f).read_text(encoding="utf-8").lower()
            for word in ["eligib", "owner approval", "evidence_path", "correspondence"]:
                self.assertNotIn(word, text, f)

    def test_ai_recheck_is_never_presented_as_a_human_check(self):
        page = (self.out_p / "cases/index.html").read_text(encoding="utf-8")
        for vt in re.findall(r'<span class="vt">([^<]*)</span>', page):
            self.assertNotIn("AI", vt)

    def test_unresolved_claims_are_not_counted_as_defects(self):
        recs = self.content.latest_all()
        unresolved = [c for r in recs for c in r["claims"] if c["result"]["outcome"] == "unresolved"]
        self.assertTrue(unresolved)
        rs = build.released_stats(self.content, "2099-12-31")
        self.assertEqual(rs["unresolved"], len(unresolved))
        defects = sum(c["result"]["outcome"] == "defect_found" for r in recs for c in r["claims"])
        self.assertEqual(rs["candidates"], defects)
        self.assertEqual(rs["confirmed"] + rs["open"], defects)

    def test_methodology_states_how_releases_are_controlled(self):
        page = (self.out_p / "methodology/index.html").read_text(encoding="utf-8")
        self.assertIn("exact SHA-256 manifests", page)
        self.assertIn("The owner approves each release.", page)
        self.assertNotIn("protected", page)

    def test_every_author_position_renders(self):
        seen = set()
        for r in self.content.latest_all():
            page = (self.out / "cases" / r["public_id"] / "index.html").read_text(encoding="utf-8")
            for c in r["claims"]:
                pos = build.claim_view(r, c)["response"]["position"]
                seen.add(pos)
                if r.get("schema") != 2:
                    label = build.POS_LONG[pos]
                elif pos in build.RESPONSE_VERB:
                    label = build.RESPONSE_VERB[pos][0]
                else:
                    label = build.POSITIONS_V2[pos]
                self.assertIn(label, page, (r["public_id"], pos))
        self.assertTrue({"agrees", "partly_agrees", "disagrees", "reviewing", "no_reply", "not_contacted"} <= seen)

    # ------------------------------------------------------------ schema 2: status, evidence, responses, math, privacy
    def load_with_edit(self, rid, fn, expect):
        """Edit one schema-2 record in a fresh copy of the test project, refresh its manifests, and expect a refusal."""
        root = self.tmp / ("edit_" + re.sub(r"\W", "_", rid + expect)[:60])
        if root.exists():
            shutil.rmtree(root)
        proj = fixtures.make_project(build, root)
        edit_json(proj / PUBLISHED / "records" / rid / "v1.0.json", fn)
        fixtures.write_manifests(build, proj)
        with self.assertRaisesRegex(build.BuildError, re.escape(expect)):
            build.Content("published", proj).load()

    def build_with_edit(self, rid, fn, expect):
        """As load_with_edit, but through the whole build, so the leak scan runs too."""
        root = self.tmp / ("bedit_" + re.sub(r"\W", "_", rid + expect)[:60])
        if root.exists():
            shutil.rmtree(root)
        proj = fixtures.make_project(build, root)
        edit_json(proj / PUBLISHED / "records" / rid / "v1.0.json", fn)
        fixtures.write_manifests(build, proj)
        with self.assertRaisesRegex(build.BuildError, re.escape(expect)):
            build.build(None, self.tmp / ("bout_" + root.name), root=proj)

    def page_text(self, rid):
        return (self.out / "cases" / rid / "index.html").read_text(encoding="utf-8")

    def test_open_findings_are_publishable_and_labelled_open(self):
        page = self.page_text("TEST-2000-019")
        self.assertIn('class="status status-open"', page)
        self.assertIn("Survived a separate-session hostile AI recheck", page)
        cases = (self.out / "cases" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="vt status-open">Open<', cases)
        self.assertNotIn("Not done", cases)

    def test_confirmed_is_optional_and_needs_two_kinds_with_one_human(self):
        page = self.page_text("TEST-2000-020")
        self.assertIn('class="status status-confirmed"', page)
        self.assertIn("The researcher re-derived it independently.", page)
        self.assertIn("One of the two authors also agreed in writing", page)

        def only_ai(r):
            r["claims"][0]["evidence"] = [e for e in r["claims"][0]["evidence"] if e["type"] == "hostile_ai_recheck"]
            r["claims"][0]["author_response"] = {"position": "no_reply", "counts": False, "basis": "none"}
        self.load_with_edit("TEST-2000-020", only_ai, "confirmed needs two kinds")

    def test_only_checks_that_happened_are_listed(self):
        for rid in ["TEST-2000-019", "TEST-2000-021"]:
            page = self.page_text(rid)
            for absent in ["Not done", "Not given", "Not recorded", "External check", "Written author agreement"]:
                self.assertNotIn(absent, page, (rid, absent))
            self.assertIn('<ul class="evidence">', page)
        evidence = self.page_text("TEST-2000-020").split('<ul class="evidence">')[1].split("</ul>")[0]
        self.assertIn("Separate-session hostile AI recheck", evidence)
        self.assertIn("Reproduced by the researcher", evidence)
        self.assertNotIn("Written author agreement", evidence)

    def test_author_position_is_independent_of_whether_it_counts(self):
        page = self.page_text("TEST-2000-022")
        self.assertIn("Some of the authors agree.", page)
        self.assertIn("Recorded from a secondary account of the reply. It does not count as written agreement.", page)
        self.assertIn('class="status status-open"', page)
        self.assertNotIn("agreed in writing", page)
        page = self.page_text("TEST-2000-021")
        self.assertIn("Our assessment:", page)
        self.assertIn("The authors disagree.", page)

    def test_author_agreement_cannot_be_evidence_or_count_from_a_secondary_record(self):
        def as_evidence(r):
            r["claims"][0]["evidence"].append({"type": "author_agreement", "date": "2000-01", "detail": "x"})
        self.load_with_edit("TEST-2000-022", as_evidence, "not recognised")

        def counted_secondary(r):
            r["claims"][0]["author_response"]["counts"] = True
        self.load_with_edit("TEST-2000-022", counted_secondary, "counts only as an agreement")

    def test_math_is_native_mathml_with_a_tex_annotation_and_no_script(self):
        page = self.page_text("TEST-2000-019")
        self.assertIn('<math display="inline"><semantics>', page)
        self.assertIn('<annotation encoding="application/x-tex">P_1</annotation>', page)
        self.assertIn('<span class="math-display" tabindex="0"><math display="block">', page)
        self.assertNotIn("\\(", page)
        self.assertNotIn("\\[", page)
        self.assertNotRegex(page, r'<script[^>]*src="https?:')
        self.assertNotIn("mathjax", page.lower())
        self.assertNotIn("katex", page.lower())

    def test_malformed_math_fails_the_build_naming_the_record(self):
        def bad(r):
            r["claims"][0]["statement"] = "If \\(P_1 holds then done."
        self.load_with_edit("TEST-2000-019", bad, "Theorem 19.1: statement: '\\(' is never closed")

    def test_private_identifiers_are_refused_by_the_leak_scan(self):
        def leak(r):
            r["claims"][0]["result"]["witness"] = "Taken from W-0034 in the private ledger."
        self.build_with_edit("TEST-2000-019", leak, "leak scan failed")

    def test_schema_one_text_is_never_read_as_mathematics(self):
        text = "The sum is \\(x\\) in schema one prose."
        self.assertEqual(build.rich({"schema": 1}, text, "x"), build.E(text))

    def test_unknown_schema_is_refused(self):
        def unknown(r):
            r["schema"] = 3
        self.load_with_edit("TEST-2000-019", unknown, "unknown schema")

    def test_related_work_needs_a_real_doi(self):
        def fake(r):
            r["related"][0]["doi"] = "VERIFY"
        self.load_with_edit("TEST-2000-020", fake, "related DOI is missing or malformed")

    def test_methodology_and_definitions_state_open_and_confirmed_without_old_policy(self):
        for name in ["methodology/index.html", "definitions/index.html", "about/index.html"]:
            text = (self.out / name).read_text(encoding="utf-8")
            for banned in ["Only confirmed defects", "every published defect has also", "awaiting a human",
                           "within 90 days", "stays open until", "A defect is published only after a human check"]:
                self.assertNotIn(banned, text, (name, banned))
        d = (self.out / "definitions/index.html").read_text(encoding="utf-8")
        self.assertIn("does not mean that the mathematical question is unresolved", d)
        self.assertIn("optional, stronger evidentiary label", d)
        self.assertIn("It is not required for publication.", d)

    def test_author_response_without_covers_builds(self):
        """The public response records position and responder; a paraphrase of the correspondence is optional."""
        root = self.tmp / "no_covers"
        if root.exists():
            shutil.rmtree(root)
        proj = fixtures.make_project(build, root)
        path = proj / PUBLISHED / "records" / "TEST-2000-022" / "v1.0.json"
        edit_json(path, lambda r: r["claims"][0]["author_response"].pop("covers"))
        fixtures.write_manifests(build, proj)
        build.Content("published", proj).load()
        page = (self.out / "cases" / "TEST-2000-022" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Some of the authors agree.", page)

    def test_missing_nested_field_is_refused_with_a_message_not_a_traceback(self):
        def no_ai_use(r):
            del r["statements"]["ai_use"]
        self.load_with_edit("TEST-2000-019", no_ai_use, "malformed record")

    def test_math_delimiters_in_a_plain_history_field_are_refused(self):
        def plain(r):
            r["changelog"][0]["change"] = "First release with \\(x\\)."
        self.load_with_edit("TEST-2000-019", plain, "math delimiters are allowed only in mathematical fields")

    def test_external_checks_are_checked_not_verified(self):
        d = (self.out / "definitions/index.html").read_text(encoding="utf-8")
        self.assertNotIn("Verified by an external human", d)
        self.assertIn("checked by an external human", d)
        self.assertIn("not an independent check", d)
        for name in ["index.html", "cases/index.html"]:
            text = (self.out / name).read_text(encoding="utf-8")
            self.assertNotIn("applicable research standard", text, name)

    def test_response_fields_belong_only_to_the_positions_that_use_them(self):
        def covers_on_reviewing(r):
            r["claims"][0]["author_response"] = {"position": "reviewing", "counts": False, "basis": "none", "covers": "x"}
        self.load_with_edit("TEST-2000-022", covers_on_reviewing, "has no responder, covers or assessment")

        def assessment_on_agreement(r):
            r["claims"][0]["author_response"]["assessment"] = "Our view."
        self.load_with_edit("TEST-2000-022", assessment_on_agreement, "an assessment is only for a disagreeing")

    def test_unrecognised_nested_fields_are_refused_not_published(self):
        def stray(r):
            r["claims"][0]["result"]["private_note"] = "Taken from correspondence."
        self.load_with_edit("TEST-2000-019", stray, "unknown fields ['private_note']")

        def stray_work(r):
            r["work"]["secret"] = "x"
        self.load_with_edit("TEST-2000-019", stray_work, "work: unknown fields")

    def test_pages_have_no_duplicate_anchors(self):
        for name in ["definitions/index.html", "methodology/index.html", "cases/TEST-2000-020/index.html"]:
            text = (self.out / name).read_text(encoding="utf-8")
            ids = re.findall(r'\sid="([^"]+)"', text)
            self.assertEqual(len(ids), len(set(ids)), (name, sorted({i for i in ids if ids.count(i) > 1})))

    def test_index_status_states_what_confirmed_rests_on(self):
        """A Confirmed label must show the counted human support; an Open finding must not list agreement it does not count."""
        cases = (self.out / "cases" / "index.html").read_text(encoding="utf-8")
        cells = re.findall(r'<td class="ix-ver"[^>]*>(.*?)</td>', cases, re.S)
        self.assertTrue(cells)
        confirmed = [c for c in cells if ">Confirmed<" in c]
        opened = [c for c in cells if ">Open<" in c]
        self.assertTrue(any("author agreement" in c.lower() for c in confirmed), confirmed)
        for cell in opened:
            self.assertNotIn("author agreement", cell.lower())
        self.assertTrue(any("AI recheck + researcher reproduction + author agreement" in c for c in confirmed), confirmed)
        self.assertTrue(any("AI recheck" in cell for cell in cells))

    def test_challenge_text_and_stray_evidence_or_correction_fields_are_refused(self):
        def challenge_with_text(r):
            r["challenges"] = [{"type": "challenge", "date": "2000-06", "by": "A reader", "outcome": "Under review",
                                "response": "Private rebuttal text."}]
        self.load_with_edit("TEST-2000-019", challenge_with_text, "challenge: unknown fields ['response']")

        def stray_evidence(r):
            r["evidence"]["secret"] = "x"
        self.load_with_edit("TEST-2000-019", stray_evidence, "evidence: unknown fields ['secret']")

        def stray_correction(r):
            r["correction"] = {"type": "corrigendum", "doi": "10.0000/x", "date": "2000-06", "relation": "after_notification",
                               "attribution": "none_stated", "claims": ["c1"], "note": "Note.", "private": "y"}
        self.load_with_edit("TEST-2000-019", stray_correction, "correction: unknown fields ['private']")

    def test_unknown_outcome_is_named_as_such(self):
        def unknown(r):
            r["claims"][0]["result"]["outcome"] = "maybe"
        self.load_with_edit("TEST-2000-019", unknown, "bad outcome 'maybe'")

    def test_status_filter_is_offered_and_rows_carry_it(self):
        cases = (self.out_p / "cases/index.html").read_text(encoding="utf-8")
        self.assertIn('id="f-status"', cases)
        self.assertIn('data-status="open"', cases)
        self.assertIn('data-status="confirmed"', cases)

    def test_generated_data_is_deterministic(self):
        again = fixtures.make_project(build, self.tmp / "again")
        for f in sorted((self.proj / PUBLISHED).rglob("*")):
            if f.is_file():
                self.assertEqual(f.read_bytes(), (again / f.relative_to(self.proj)).read_bytes(), f.name)

    def test_leak_scan_is_clean_and_catches_leaks(self):
        self.assertEqual(build.scan_output(self.out, []), [])
        self.assertEqual(build.scan_output(self.out_p, []), [])
        bad = self.tmp / "bad"
        bad.mkdir()
        (bad / "x.html").write_text("see C:\\Users\\someone\\Dropbox and mail a@b.org", encoding="utf-8")
        problems = build.scan_output(bad, ["secret term"])
        self.assertTrue(any("Dropbox" in p for p in problems))
        self.assertTrue(any("e-mail" in p for p in problems))

    def test_private_denylist_blocks_build(self):
        deny = self.tmp / "deny.txt"
        deny.write_text("Author A1\n", encoding="utf-8")
        with self.assertRaises(build.BuildError):
            build.build(None, self.tmp / "dist_deny", denylist_file=deny, root=self.proj)

    def test_expected_trust_must_be_none(self):
        build.build(None, self.tmp / "dist_trust_ok", expect_trust="none", root=self.proj)
        with self.assertRaisesRegex(build.BuildError, "do not match"):
            build.build(None, self.tmp / "dist_trust_bad", expect_trust="SHA256:not-the-key", root=self.proj)
        with self.assertRaisesRegex(build.BuildError, "no expected trust"):
            build.build(None, self.tmp / "dist_trust_none", expect_trust=" ", root=self.proj)


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="as_gate_"))
        self.root = fixtures.make_project(build, self.tmp / "proj")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def load(self):
        return build.Content("published", self.root).load()

    def test_untouched_copy_loads(self):
        self.assertEqual(len(self.load().verified), len(list((self.root / PUBLISHED / "releases").glob("*.txt"))))

    def test_edited_record_is_refused(self):
        f = self.root / PUBLISHED / "records/TEST-2000-004/v1.0.json"
        f.write_bytes(f.read_bytes().replace(b"partly_agrees", b"agrees"))
        with self.assertRaisesRegex(build.BuildError, "does not match"):
            self.load()

    def test_missing_manifest_is_refused(self):
        next((self.root / PUBLISHED / "releases").glob("record__TEST-2000-002*.txt")).unlink()
        with self.assertRaisesRegex(build.BuildError, "not released"):
            self.load()

    def test_unreleased_record_is_refused(self):
        src = self.root / PUBLISHED / "records/TEST-2000-002/v1.0.json"
        dst = self.root / PUBLISHED / "records/TEST-2000-099/v1.0.json"
        dst.parent.mkdir(parents=True)
        shutil.copyfile(src, dst)
        with self.assertRaisesRegex(build.BuildError, "not released"):
            self.load()

    def test_manifest_for_different_content_is_refused(self):
        f = next((self.root / PUBLISHED / "releases").glob("record__TEST-2000-018*.txt"))
        f.write_bytes(build.release_statement("record", "TEST-2000-018", "1.0", "0" * 64))
        with self.assertRaisesRegex(build.BuildError, "does not match"):
            self.load()

    def _add_record(self, *, sample=False, manifest=True):
        src = self.root / PUBLISHED / "records/TEST-2000-018/v1.0.json"
        dst = self.root / PUBLISHED / "records/TEST-2000-098/v1.0.json"
        dst.parent.mkdir(parents=True)
        data = json.loads(src.read_text(encoding="utf-8"))
        data["sample"] = sample
        data["public_id"] = "TEST-2000-098"
        dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if manifest:
            digest = build.sha256_bytes(dst.read_bytes())
            rel = self.root / PUBLISHED / "releases/record__TEST-2000-098__1.0.txt"
            rel.write_bytes(build.release_statement("record", "TEST-2000-098", "1.0", digest))
        return dst

    def test_empty_channel_loads_without_a_key(self):
        shutil.rmtree(self.root / "content")
        (self.root / PUBLISHED).mkdir(parents=True)
        content = self.load()
        self.assertTrue(content.empty)
        self.assertEqual(content.records, {})

    def test_record_without_manifest_is_refused(self):
        self._add_record(manifest=False)
        with self.assertRaisesRegex(build.BuildError, "no release statement"):
            self.load()

    def test_record_with_matching_manifest_is_accepted(self):
        self._add_record()
        self.assertIn("TEST-2000-098", self.load().records)

    def test_content_flagged_as_not_real_is_refused(self):
        self._add_record(sample=True)
        with self.assertRaisesRegex(build.BuildError, "sample flag"):
            self.load()

    def _refresh_manifests(self):
        fixtures.write_manifests(build, self.root)

    def test_statistics_partition_error_is_refused_even_when_signed(self):
        edit_json(self.root / LATEST_SNAPSHOT,
                  lambda s: s["totals"]["M06"].update(open=3))
        self._refresh_manifests()
        with self.assertRaisesRegex(build.BuildError, "M06 does not partition"):
            self.load()

    def test_statistics_below_released_records_is_refused(self):
        edit_json(self.root / LATEST_SNAPSHOT,
                  lambda s: s["totals"].update(M10=0))
        self._refresh_manifests()
        with self.assertRaisesRegex(build.BuildError, "below the"):
            self.load()

    def test_published_small_cell_is_refused(self):
        def fn(s):
            cells = s["examined_by_track"]["M01"]
            cells["mechanism_design"] = 3
            cells["game_theory"] = None
        edit_json(self.root / LATEST_SNAPSHOT, fn)
        self._refresh_manifests()
        with self.assertRaisesRegex(build.BuildError, "small count"):
            self.load()

    def test_reconstructable_suppression_is_refused(self):
        def fn(s):
            cells = s["examined_by_track"]["M01"]
            known = cells["game_theory"]
            cells["mechanism_design"] = None
            cells["matching_social_choice"] = None
            cells["game_theory"] = s["totals"]["M01"] - 2   # leaves 2 for two suppressed cells, so both must be 1
            del known
        edit_json(self.root / LATEST_SNAPSHOT, fn)
        self._refresh_manifests()
        with self.assertRaisesRegex(build.BuildError, "can be narrowed"):
            self.load()

    def test_confirmation_standard_enforced(self):
        def fn(r):
            r["claims"][0]["checks"] = [k for k in r["claims"][0]["checks"] if k["kind"] == "ai_recheck"]
        edit_json(self.root / PUBLISHED / "records/TEST-2000-015/v1.0.json", fn)
        self._refresh_manifests()
        with self.assertRaisesRegex(build.BuildError, "confirmation standard"):
            self.load()

    def test_unresolved_claim_cannot_be_named(self):
        def fn(r):
            r["claims"][0]["result"]["outcome"] = "inconclusive"
        edit_json(self.root / PUBLISHED / "records/TEST-2000-018/v1.0.json", fn)
        self._refresh_manifests()
        with self.assertRaisesRegex(build.BuildError, "cannot be published"):
            self.load()

    def test_unresolved_claim_cannot_stand_alone(self):
        def fn(r):
            r["claims"] = [c for c in r["claims"] if c["result"]["outcome"] == "unresolved"]
            r["kind"] = "negative"
        edit_json(self.root / PUBLISHED / "records/TEST-2000-007/v1.0.json", fn)
        self._refresh_manifests()
        with self.assertRaisesRegex(build.BuildError, "cannot be the only claim"):
            self.load()

    def test_build_refuses_to_overwrite_unknown_folder(self):
        other = self.tmp / "not_a_build"
        other.mkdir()
        (other / "keep.txt").write_text("x")
        with self.assertRaisesRegex(build.BuildError, "refusing to replace"):
            build.build(None, other, root=self.root)
        self.assertTrue((other / "keep.txt").exists())


def find_browser():
    candidates = [os.environ.get("BROWSER_BIN", ""),
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  shutil.which("google-chrome") or "", shutil.which("chromium") or "",
                  shutil.which("chromium-browser") or "", shutil.which("microsoft-edge") or ""]
    return next((c for c in candidates if c and Path(c).exists()), None)


LAYOUT_PAGES = ["", "cases/", "cases/TEST-2000-001/", "cases/TEST-2000-002/v1.0/", "cases/TEST-2000-007/",
                "statistics/", "statistics/2000-03/", "methodology/", "definitions/", "updates/", "about/", "404.html"]
WIDTHS = [360, 390, 768, 1280]

# Loads every page in same-origin iframes at fixed widths and reports horizontal overflow, whether the
# stylesheet and script took effect, and whether the case filters work. Written next to the built site.
HARNESS = """<!doctype html><meta charset="utf-8"><body><pre id="result">pending</pre><script>
const pages = %s, widths = %s, out = [];
function load(src, w) { return new Promise(res => { const f = document.createElement("iframe");
  f.style.width = w + "px"; f.style.height = "800px"; f.style.border = "0"; f.onload = () => res(f); f.src = src;
  document.body.appendChild(f); }); }
(async () => {
  for (const p of pages) for (const w of widths) {
    const f = await load("/" + p, w), d = f.contentDocument, html = d.documentElement;
    const wide = [...d.body.querySelectorAll("*")].filter(e => e.getBoundingClientRect().right > w + 1)
      .slice(0, 3).map(e => e.tagName.toLowerCase() + "." + e.className);
    out.push({page: p, width: w, scrollWidth: html.scrollWidth, wide: wide,
      styled: f.contentWindow.getComputedStyle(d.querySelector(".mast")).borderBottomStyle === "solid",
      js: html.getAttribute("data-js") === "1"});
    if (p === "cases/" && w === 390 && d.getElementById("f-fam")) {
      const sel = d.getElementById("f-fam"); sel.value = [...sel.options].some(o => o.value === "construction") ? "construction" : "none"; sel.dispatchEvent(new Event("change"));
      const shown = [...d.querySelectorAll("#case-index tr.ix-row")].filter(r => !r.hidden && !r.parentElement.hidden).length;
      out.push({filter: sel.value, shown: shown, count: d.getElementById("f-count").textContent,
                formVisible: !d.getElementById("filters").hidden});
    }
    f.remove();
  }
  document.getElementById("result").textContent = JSON.stringify(out);
})();
</script>"""


@unittest.skipUnless(find_browser(), "Edge or Chrome is needed for the layout tests")
class LayoutTests(unittest.TestCase):
    """Layout of a build from generated data, which exercises every component."""
    PAGES = LAYOUT_PAGES

    @classmethod
    def project_root(cls):
        return fixtures.make_project(build, cls.tmp / "proj")

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="as_layout_"))
        build.build(None, cls.tmp / "site", pretty=True, root=cls.project_root())
        (cls.tmp / "site" / "__harness.html").write_text(
            HARNESS % (json.dumps(cls.PAGES), json.dumps(WIDTHS)), encoding="utf-8")
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        handler = functools.partial(Quiet, directory=str(cls.tmp / "site"))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{cls.server.server_address[1]}/__harness.html"
        profile = cls.tmp / "profile"
        # Ubuntu 24.04 CI runners block Chrome's sandbox; the page loaded is this repository's own built site.
        sandbox = ["--no-sandbox"] if os.environ.get("CI") and os.name != "nt" else []
        r = subprocess.run([find_browser(), "--headless=new", "--disable-gpu", "--no-first-run", *sandbox,
                            f"--user-data-dir={profile}", "--virtual-time-budget=60000", "--dump-dom", url],
                           capture_output=True, text=True, encoding="utf-8", timeout=300)
        m = re.search(r'<pre id="result">(.*?)</pre>', r.stdout, re.S)
        raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") if m else ""
        cls.results = json.loads(raw) if raw.startswith("[") else None
        cls.raw = raw or r.stdout[-2000:] + r.stderr[-2000:]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_harness_ran(self):
        self.assertIsNotNone(self.results, self.raw)
        self.assertEqual(len([r for r in self.results if "page" in r]), len(self.PAGES) * len(WIDTHS))

    def test_no_horizontal_overflow_at_phone_tablet_and_desktop_widths(self):
        self.assertIsNotNone(self.results, self.raw)
        for r in (x for x in self.results if "page" in x):
            self.assertLessEqual(r["scrollWidth"], r["width"], f"/{r['page']} at {r['width']}px: {r['wide']}")

    def test_stylesheet_and_script_load_on_nested_pages(self):
        self.assertIsNotNone(self.results, self.raw)
        for r in (x for x in self.results if "page" in x):
            self.assertTrue(r["styled"], f"/{r['page']}: stylesheet not applied")
            self.assertTrue(r["js"], f"/{r['page']}: script did not run")

    def test_case_filters_work(self):
        self.assertIsNotNone(self.results, self.raw)
        f = next(x for x in self.results if "filter" in x)
        self.assertTrue(f["formVisible"])
        # Four fixture claims have a construction defect: TEST-2000-002, -003, -017 and the schema-2 TEST-2000-020.
        self.assertEqual(f["shown"], 4)
        self.assertTrue(f["count"].startswith("4 of "))


class ProductionLayoutTests(LayoutTests):
    """Layout of the production build (published channel, optional pages off)."""
    PAGES = ["", "cases/", "cases/TA-2026-001/", "cases/TA-2026-002/", "cases/TA-2026-003/", "methodology/", "definitions/", "about/", "404.html"]

    @classmethod
    def project_root(cls):
        return ROOT

    def test_case_filters_work(self):
        self.assertIsNotNone(self.results, self.raw)
        f = next(x for x in self.results if "filter" in x)
        self.assertTrue(f["formVisible"])
        self.assertEqual(f["filter"], "construction")
        self.assertEqual(f["shown"], 1)


class ProductionTests(unittest.TestCase):
    """The deployed configuration: published channel only, real records, no test data."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="as_prod_"))
        cls.site, cls.content, cls.out = build.build(None, cls.tmp / "site", pretty=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def pages(self):
        return {p.relative_to(self.out).as_posix(): p.read_text(encoding="utf-8")
                for p in self.out.rglob("*") if p.is_file() and p.suffix in {".html", ".xml", ".txt", ".json"}}

    def test_builds_from_the_published_channel_only(self):
        self.assertEqual(self.content.channel, "published")
        self.assertEqual(set(self.content.records), {"TA-2026-001", "TA-2026-002", "TA-2026-003", "TA-2026-004"})
        for rid in self.content.records:
            self.assertTrue((self.out / f"data/records/{rid}/v1.0.json").exists())

    def test_navigation_is_cases_methodology_definitions_about(self):
        nav = re.search(r'<nav class="nav"[^>]*>(.*?)</nav>', (self.out / "index.html").read_text(encoding="utf-8")).group(1)
        self.assertEqual(re.findall(r">([^<]+)</a>", nav), ["Cases", "Methodology", "Definitions", "About"])

    def test_statistics_and_updates_are_not_built_or_linked(self):
        for path in ["statistics/index.html", "updates/index.html", "feed.xml"]:
            self.assertFalse((self.out / path).exists(), path)
        for name, text in self.pages().items():
            self.assertNotRegex(text, r'href="[^"]*(statistics|updates)/|feed\.xml', name)

    def test_no_generated_test_data_in_production(self):
        items = fixtures.records()
        names = {a for r in items for a in r["work"]["authors"]} | {r["work"]["title"] for r in items}
        for name, text in self.pages().items():
            self.assertNotRegex(text, r"TEST-2000|noindex", name)
            for n in names:
                self.assertNotIn(n, text, name)

    def test_no_retired_or_superseded_wording_in_any_output_file(self):
        for path in sorted(p for p in self.out.rglob("*") if p.is_file() and p.suffix in {".html", ".css", ".js", ".json", ".xml", ".txt"}):
            self.assertNotRegex(path.read_text(encoding="utf-8"), BANNED_OUTPUT, str(path))

    def test_public_tree_holds_only_production_code_and_real_data(self):
        self.assertEqual(sorted(p.name for p in (ROOT / "content").iterdir() if p.is_dir()), ["published"])
        for rid in self.content.records:
            self.assertRegex(rid, r"^TA-\d{4}-\d{3}$")
        ignored = {".git", "_site", "dist", "__pycache__"}
        for path in ROOT.rglob("*"):
            if path.is_file() and not ignored & set(path.relative_to(ROOT).parts):
                self.assertNotRegex(path.read_text(encoding="utf-8", errors="replace"), BANNED_TREE, str(path))

    def test_cases_page_contains_the_real_records(self):
        cases = (self.out / "cases/index.html").read_text(encoding="utf-8")
        home = (self.out / "index.html").read_text(encoding="utf-8")
        for rid, title, author in [
            ("TA-2026-001", "Stability and strategy-proofness for matching with constraints", "Kamada"),
            ("TA-2026-002", "Safe implementation", "Gavan"),
            ("TA-2026-003", "A Qualitative Theory of Large Games with Strategic Complementarities", "Balbus"),
        ]:
            self.assertIn(rid, cases)
            self.assertIn(title, cases)
            self.assertIn(author, cases)
            self.assertIn(title, home)
        self.assertNotIn("No case records have been released yet.", cases)

    def test_policies_live_on_the_methodology_page(self):
        m = (self.out / "methodology/index.html").read_text(encoding="utf-8")
        for anchor in ["responses", "corrections", "challenges", "release", "standard"]:
            self.assertIn(f'id="{anchor}"', m)
        self.assertIn("exact SHA-256 manifests", m)
        self.assertIn("Author notification, a waiting period and author consent are not publication gates", m)

    def test_links_resolve(self):
        BuildTests.check_links(self, self.out)

    def html_files(self, out=None):
        return sorted((out or self.out).rglob("*.html"))

    def test_trust_pin_none_for_real_published_channel(self):
        build.check_expected_trust(self.content, "none")
        with self.assertRaisesRegex(build.BuildError, "do not match"):
            build.check_expected_trust(self.content, "SHA256:some-key")


if __name__ == "__main__":
    unittest.main()
