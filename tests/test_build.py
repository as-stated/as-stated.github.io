"""Tests for build.py. Run from the project folder:  python -m unittest discover -s tests -v

The layout tests need Microsoft Edge or Google Chrome; they are skipped when neither is installed."""
import copy
import functools
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

INDEXABLE = {"methodology/index.html", "definitions/index.html", "about/index.html"}
OLD_BRANDS = re.compile(r"Theorem Audit|Second Referee|Reviewer\s*(#\s*2|2|Two)|TA-20\d\d|SR-20\d\d", re.I)


def copy_project(dst):
    dst.mkdir(parents=True)
    for name in ["build.py", "site.json"]:
        shutil.copy2(ROOT / name, dst / name)
    for name in ["content", "trust", "static"]:
        shutil.copytree(ROOT / name, dst / name)
    return dst


def new_key(directory, name="k"):
    key = Path(directory) / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(key)], check=True)
    return key


def trust_line(key):
    pub = Path(str(key) + ".pub").read_text().split()
    return f'{build.PRINCIPAL} namespaces="{build.NAMESPACE}" {pub[0]} {pub[1]}\n'


def resign_all(root, channel, key):
    croot = root / "content" / channel
    rel = croot / "releases"
    if rel.exists():
        shutil.rmtree(rel)
    for f in sorted((croot / "records").glob("*/v*.json")):
        build.sign(channel, key, "record", f.parent.name, f.stem[1:], f, root)
    for f in sorted((croot / "snapshots").glob("*.json")):
        build.sign(channel, key, "snapshot", f.stem, "1", f, root)
    if (croot / "updates.json").exists():
        build.sign(channel, key, "updates", "updates", "1", croot / "updates.json", root)


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
        cls.site, cls.content, cls.out = build.build(None, cls.tmp / "dist")
        cls.site_p, cls.content_p, cls.out_p = build.build(None, cls.tmp / "site", pretty=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def html_files(self, out=None):
        return sorted((out or self.out).rglob("*.html"))

    def rel(self, f, out=None):
        return f.relative_to(out or self.out).as_posix()

    def test_brand_and_demo_identifiers(self):
        self.assertEqual(self.site.cfg["name"], "As Stated")
        self.assertEqual(self.content.channel, "sample")
        self.assertTrue(self.content.records)
        self.assertTrue(all(r.startswith("DEMO-") for r in self.content.records))
        home = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("As Stated", home)
        self.assertIn("Independent scrutiny of published mathematical and theoretical claims.", home)
        self.assertIn("What was claimed. What was tested. What survived.", home)

    def test_no_earlier_brand_names_or_identifiers_in_output(self):
        for f in sorted(p for p in self.out_p.rglob("*") if p.is_file()):
            found = OLD_BRANDS.search(f.read_text(encoding="utf-8", errors="replace"))
            self.assertIsNone(found, f"{self.rel(f, self.out_p)}: {found and found.group(0)}")

    def test_content_prefix_must_match_site(self):
        root = copy_project(self.tmp / "prefix_proj")
        edit_json(root / "site.json", lambda c: c.update(id_prefix="XYZ"))
        with self.assertRaisesRegex(build.BuildError, "identifier prefix"):
            build.build("sample", self.tmp / "dist_prefix", root=root)

    def test_expected_pages_exist(self):
        for p in ["index.html", "cases/index.html", "statistics/index.html", "statistics/2027-03/index.html",
                  "methodology/index.html", "definitions/index.html", "updates/index.html", "about/index.html",
                  "404.html", "feed.xml", "cases/DEMO-2027-001/index.html", "cases/DEMO-2027-001/v1.0/index.html",
                  "data/records/DEMO-2027-001/v1.2.json", "data/snapshots/2027-06.json", "robots.txt",
                  "sitemap.xml", ".nojekyll", "static/style.css", "static/app.js", "static/favicon.svg"]:
            self.assertTrue((self.out_p / p).exists(), p)

    def test_every_page_is_well_formed_and_carries_the_demo_notice(self):
        for out in (self.out, self.out_p):
            for f in self.html_files(out):
                text = f.read_text(encoding="utf-8")
                c = Collector()
                c.feed(text)
                self.assertEqual(c.lang, "en", f)
                self.assertTrue(c.title, f)
                self.assertEqual(c.h1, 1, f"{f}: expected exactly one h1")
                self.assertIn('class="demo-banner"', text, f)
                self.assertIn("is fictional", text, f)
                self.assertEqual(len(c.stylesheets), 1, f)
                self.assertEqual(len(c.scripts), 1, f)

    def test_only_genuine_project_pages_are_indexable(self):
        for f in self.html_files(self.out_p):
            rel = self.rel(f, self.out_p)
            robots = parse(f).robots
            if rel in INDEXABLE:
                self.assertIsNone(robots, f"{rel} should be indexable")
            else:
                self.assertEqual(robots, "noindex", f"{rel} is demonstration content and must carry noindex")
        robots_txt = (self.out_p / "robots.txt").read_text()
        self.assertIn("Allow: /", robots_txt)
        self.assertIn("Sitemap: https://as-stated.github.io/sitemap.xml", robots_txt)
        locs = re.findall(r"<loc>([^<]+)</loc>", (self.out_p / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertEqual(sorted(locs), sorted("https://as-stated.github.io/" + p.replace("index.html", "")
                                              for p in INDEXABLE))

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
        for label in ["False as printed", "Proof incomplete", "Repairable gap", "Missing assumption",
                      "No defect found", "Unresolved", "Rejected candidate"]:
            self.assertIn(label, defs)
        self.assertIn("not a proof of correctness", defs.replace("Not a proof", "not a proof"))

    def test_negative_audits_carry_the_caveat_and_defects_the_non_claims(self):
        for rid, versions in self.content.records.items():
            page = (self.out / "cases" / rid / "index.html").read_text(encoding="utf-8")
            if versions[-1]["kind"] == "negative":
                self.assertIn(build.NEGATIVE_CAVEAT, page, rid)
            else:
                self.assertIn("Not claimed", page, rid)

    def test_archived_versions_point_to_current(self):
        page = (self.out_p / "cases/DEMO-2027-001/v1.0/index.html").read_text(encoding="utf-8")
        self.assertIn("Archived version 1.0. The current version is", page)
        current = (self.out_p / "cases/DEMO-2027-001/index.html").read_text(encoding="utf-8")
        self.assertNotIn("Archived version", current)

    def test_selection_statement_on_number_pages(self):
        for p in ["index.html", "statistics/index.html", "cases/index.html"]:
            self.assertIn("not sampled at random", (self.out / p).read_text(encoding="utf-8"), p)

    def test_suppressed_counts_are_shown_as_dashes(self):
        stats = (self.out_p / "statistics/index.html").read_text(encoding="utf-8")
        snap = max(self.content.snapshots, key=lambda s: s["as_of"])
        suppressed = [k for k, v in snap["examined_by_track"]["M01"].items() if v is None]
        self.assertTrue(suppressed)
        self.assertEqual(stats.count('data-label="Papers considered">–<'), len(suppressed))

    def test_methodology_publishes_the_trusted_fingerprint(self):
        page = (self.out_p / "methodology/index.html").read_text(encoding="utf-8")
        for fp in build.key_fingerprints(self.content.trust):
            self.assertIn(fp, page)

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
        deny.write_text("Jane Doe\n", encoding="utf-8")
        with self.assertRaises(build.BuildError):
            build.build("sample", self.tmp / "dist_deny", denylist_file=deny)

    def test_expected_trust_pins_the_signing_key(self):
        fps = ",".join(build.key_fingerprints(self.content.trust))
        build.build("sample", self.tmp / "dist_trust_ok", expect_trust=fps)
        with self.assertRaisesRegex(build.BuildError, "do not match"):
            build.build("sample", self.tmp / "dist_trust_bad", expect_trust="SHA256:not-the-key")
        with self.assertRaisesRegex(build.BuildError, "no expected trust"):
            build.build("sample", self.tmp / "dist_trust_none", expect_trust=" ")


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="as_gate_"))
        self.root = copy_project(self.tmp / "proj")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def load(self, channel="sample"):
        return build.Content(channel, self.root).load()

    def test_untouched_copy_loads(self):
        self.assertEqual(len(self.load().verified), 12)

    def test_edited_record_is_refused(self):
        f = self.root / "content/sample/records/DEMO-2027-003/v1.0.json"
        f.write_bytes(f.read_bytes().replace(b"partly agree", b"fully agree"))
        with self.assertRaisesRegex(build.BuildError, "does not match"):
            self.load()

    def test_missing_signature_is_refused(self):
        next((self.root / "content/sample/releases").glob("record__DEMO-2027-002*.sig")).unlink()
        with self.assertRaisesRegex(build.BuildError, "signature"):
            self.load()

    def test_unreleased_record_is_refused(self):
        src = self.root / "content/sample/records/DEMO-2027-002/v1.0.json"
        dst = self.root / "content/sample/records/DEMO-2027-009/v1.0.json"
        dst.parent.mkdir(parents=True)
        shutil.copyfile(src, dst)
        with self.assertRaisesRegex(build.BuildError, "not released"):
            self.load()

    def test_signature_from_untrusted_key_is_refused(self):
        other = new_key(self.tmp, "other")
        (self.root / "trust/sample_allowed_signers").write_text(trust_line(other), encoding="utf-8")
        with self.assertRaisesRegex(build.BuildError, "untrusted"):
            self.load()

    def test_published_channel_needs_owner_key(self):
        with self.assertRaisesRegex(build.BuildError, "no release key"):
            self.load("published")

    def test_published_channel_refuses_demonstration_key(self):
        sample_line = (self.root / "trust/sample_allowed_signers").read_text().splitlines()[-1]
        (self.root / "trust/allowed_signers").write_text(sample_line + "\n", encoding="utf-8")
        with self.assertRaisesRegex(build.BuildError, "demonstration key"):
            self.load("published")

    def test_published_channel_refuses_sample_content_even_if_owner_signed(self):
        owner = new_key(self.tmp, "owner")
        (self.root / "trust/allowed_signers").write_text(trust_line(owner), encoding="utf-8")
        pub = self.root / "content/published"
        for sub in ["records", "snapshots"]:
            shutil.copytree(self.root / "content/sample" / sub, pub / sub)
        shutil.copyfile(self.root / "content/sample/updates.json", pub / "updates.json")
        resign_all(self.root, "published", owner)
        with self.assertRaisesRegex(build.BuildError, "sample flag"):
            self.load("published")

    def _resign_sample(self):
        key = new_key(self.tmp, "resign")
        (self.root / "trust/sample_allowed_signers").write_text(trust_line(key), encoding="utf-8")
        resign_all(self.root, "sample", key)

    def test_statistics_partition_error_is_refused_even_when_signed(self):
        edit_json(self.root / "content/sample/snapshots/2027-06.json",
                  lambda s: s["totals"]["M06"].update(open=3))
        self._resign_sample()
        with self.assertRaisesRegex(build.BuildError, "M06 does not partition"):
            self.load()

    def test_statistics_below_released_records_is_refused(self):
        edit_json(self.root / "content/sample/snapshots/2027-06.json",
                  lambda s: s["totals"].update(M10=0))
        self._resign_sample()
        with self.assertRaisesRegex(build.BuildError, "below the"):
            self.load()

    def test_published_small_cell_is_refused(self):
        def fn(s):
            s["examined_by_track"]["M01"]["probability"] = 3
            s["examined_by_track"]["M01"]["econometrics"] = None
        edit_json(self.root / "content/sample/snapshots/2027-06.json", fn)
        self._resign_sample()
        with self.assertRaisesRegex(build.BuildError, "small count"):
            self.load()

    def test_reconstructable_suppression_is_refused(self):
        def fn(s):
            cells = s["examined_by_track"]["M01"]
            cells["game_theory"] = 27     # leaves 2 for the two suppressed cells, so both must be 1
        edit_json(self.root / "content/sample/snapshots/2027-06.json", fn)
        self._resign_sample()
        with self.assertRaisesRegex(build.BuildError, "can be narrowed"):
            self.load()

    def test_confirmation_standard_enforced(self):
        def fn(r):
            r["claims"][0]["checks"] = [k for k in r["claims"][0]["checks"] if k["kind"] == "ai_recheck"]
        edit_json(self.root / "content/sample/records/DEMO-2027-003/v1.0.json", fn)
        self._resign_sample()
        with self.assertRaisesRegex(build.BuildError, "confirmation standard"):
            self.load()

    def test_unresolved_claim_cannot_be_named(self):
        def fn(r):
            r["claims"][0]["result"]["outcome"] = "inconclusive"
        edit_json(self.root / "content/sample/records/DEMO-2027-002/v1.0.json", fn)
        self._resign_sample()
        with self.assertRaisesRegex(build.BuildError, "cannot be published"):
            self.load()

    def test_build_refuses_to_overwrite_unknown_folder(self):
        other = self.tmp / "not_a_build"
        other.mkdir()
        (other / "keep.txt").write_text("x")
        with self.assertRaisesRegex(build.BuildError, "refusing to replace"):
            build.build("sample", other, root=self.root)
        self.assertTrue((other / "keep.txt").exists())


def find_browser():
    candidates = [os.environ.get("BROWSER_BIN", ""),
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  shutil.which("google-chrome") or "", shutil.which("chromium") or "",
                  shutil.which("chromium-browser") or "", shutil.which("microsoft-edge") or ""]
    return next((c for c in candidates if c and Path(c).exists()), None)


LAYOUT_PAGES = ["", "cases/", "cases/DEMO-2027-001/", "cases/DEMO-2027-001/v1.0/", "cases/DEMO-2027-005/",
                "statistics/", "statistics/2027-03/", "methodology/", "definitions/", "updates/", "about/", "404.html"]
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
      styled: f.contentWindow.getComputedStyle(d.querySelector(".top")).borderBottomStyle === "solid",
      js: html.getAttribute("data-js") === "1"});
    if (p === "cases/" && w === 390) {
      const sel = d.getElementById("f-outcome"); sel.value = "o-false"; sel.dispatchEvent(new Event("change"));
      const shown = [...d.querySelectorAll("#case-index tbody tr")].filter(r => !r.hidden).length;
      out.push({filter: "o-false", shown: shown, count: d.getElementById("f-count").textContent,
                formVisible: !d.getElementById("filters").hidden});
    }
    f.remove();
  }
  document.getElementById("result").textContent = JSON.stringify(out);
})();
</script>"""


@unittest.skipUnless(find_browser(), "Edge or Chrome is needed for the layout tests")
class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="as_layout_"))
        build.build(None, cls.tmp / "site", pretty=True)
        (cls.tmp / "site" / "__harness.html").write_text(
            HARNESS % (json.dumps(LAYOUT_PAGES), json.dumps(WIDTHS)), encoding="utf-8")
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
        self.assertEqual(len([r for r in self.results if "page" in r]), len(LAYOUT_PAGES) * len(WIDTHS))

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
        self.assertEqual(f["shown"], 1)
        self.assertTrue(f["count"].startswith("1 of "))


if __name__ == "__main__":
    unittest.main()
