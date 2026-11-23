"""Synthetic fixtures for current publication, outreach, correction and safety-gate behavior."""
import json
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build  # noqa: E402
import release_safety  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))
import fixtures  # noqa: E402

TEST_ARTIFACT_BYTES = b"Synthetic source-locked evidence for tests.\n"
TEST_ARTIFACT_SHA = hashlib.sha256(TEST_ARTIFACT_BYTES).hexdigest()
TEST_ARTIFACT_ID = "sha256:" + TEST_ARTIFACT_SHA


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def deployment_marker(directory, source_commit, live_audit="PASS", verified_at="2026-11-23T12:00:00+11:00", run_id="SYNTHETIC-DEPLOY"):
    evidence_path = directory / "audits" / f"{run_id}.txt"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_bytes = f"synthetic live audit {run_id}\nRESULT: {live_audit}\n".encode()
    evidence_path.write_bytes(evidence_bytes)
    return {"source_commit": source_commit, "live_audit": live_audit, "verified_at": verified_at,
            "run_id": run_id, "audit_evidence": {"path": evidence_path.relative_to(directory).as_posix(),
                                                   "sha256": release_safety.sha256(evidence_bytes)},
            "release_records_inventory": release_safety.release_records_inventory(directory.parents[1])}


def marker_note(marker, value):
    return "<!-- " + marker + "\n" + json.dumps(value, sort_keys=True) + "\n" + marker + " -->\n"


def make_v3(record, primary=None):
    record["schema"] = 3
    record["primary_claim_id"] = primary or record["claims"][0]["id"]
    record.pop("outreach", None)
    for claim in record["claims"]:
        claim.pop("author_response", None)
    return record


def event(event_id, subject, dimension, value, effective="2026-11-22"):
    recorded = {"finding": "2026-11-22T08:00:00+11:00", "source_lock": "2026-11-22T10:00:00+11:00",
                "check": "2026-11-22T11:00:00+11:00"}.get(
        dimension, "2026-11-22T12:00:00+11:00")
    return {"event": event_id, "recorded_at": recorded, "effective_at": effective,
            "actor": "owner", "subject": subject, "dimension": dimension, "value": value,
            "evidence": [TEST_ARTIFACT_ID], "corrects": None, "reconstructed": False, "note": "Synthetic test event."}


class SyntheticProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="as_policy_"))
        self.root = fixtures.make_project(build, self.tmp / "project")
        cfg_path = self.root / "site.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["pages"]["statistics"] = False
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
        shutil.rmtree(self.root / "content" / "published" / "snapshots")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def record_path(self, rid, version="1.0"):
        return self.root / "content" / "published" / "records" / rid / f"v{version}.json"

    def read_record(self, rid, version="1.0"):
        return json.loads(self.record_path(rid, version).read_text(encoding="utf-8"))

    def save_record(self, record):
        dump(self.record_path(record["public_id"], record["version"]), record)
        fixtures.write_manifests(build, self.root)

    def build_out(self, name="out"):
        return build.build(None, self.tmp / name, pretty=True, root=self.root)[2]

    def test_open_positive_without_outreach_renders_open_and_omits_outreach(self):
        record = make_v3(self.read_record("TEST-2000-019"))
        self.save_record(record)
        out = self.build_out()
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn('class="status status-open"', page)
        self.assertNotIn('id="outreach"', page)
        self.assertNotIn("Awaiting a substantive author response", page)

    def test_not_contacted_and_awaiting_states_render_only_when_explicit(self):
        record = make_v3(self.read_record("TEST-2000-019"))
        record["outreach"] = {"status": "not_contacted"}
        self.save_record(record)
        out = self.build_out("not_contacted")
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn("Authors not contacted", page)
        record["outreach"] = {"status": "awaiting_substantive_response"}
        self.save_record(record)
        out = self.build_out("awaiting")
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn("Awaiting a substantive author response", page)

    def test_outreach_states_and_author_position_are_public_facts_without_correspondence(self):
        record = make_v3(self.read_record("TEST-2000-019"))
        record["outreach"] = {"status": "substantive_response_received"}
        record["claims"][0]["author_response"] = {"position": "disagrees"}
        self.save_record(record)
        out = self.build_out()
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn("Substantive author response received", page)
        self.assertIn("Disagrees.", page)
        self.assertNotIn("private email", page.lower())
        self.assertNotIn("correspondence text", page.lower())

    def test_schema3_rejects_correspondence_summaries(self):
        record = make_v3(self.read_record("TEST-2000-019"))
        record["claims"][0]["author_response"] = {"position": "disagrees", "basis": "private correspondence text"}
        self.save_record(record)
        with self.assertRaisesRegex(build.BuildError, "not identity or correspondence details"):
            build.Content("published", self.root).load()

    def test_schema3_private_human_confirmation_uses_public_safe_text(self):
        record = make_v3(self.read_record("TEST-2000-019"))
        record["claims"][0]["evidence"] = [{"type": "private_human_confirmation", "date": "2000-01",
                                             "detail": "The author wrote that the audit was right."}]
        self.save_record(record)
        with self.assertRaisesRegex(build.BuildError, "fixed public wording"):
            build.Content("published", self.root).load()

    def test_no_reply_does_not_count_as_contact_in_current_metric(self):
        record = self.read_record("TEST-2000-019")
        stats = build.released_stats(fixtures._Records([record]), "2099-12-31")
        self.assertEqual(stats["notified"], 0)
        legacy = build.released_stats(fixtures._Records([record]), "2099-12-31", include_legacy_no_reply=True)
        self.assertEqual(legacy["notified"], 1)
        record["outreach"] = {"status": "awaiting_substantive_response"}
        stats = build.released_stats(fixtures._Records([record]), "2099-12-31")
        self.assertEqual(stats["notified"], 1)

    def test_unresolved_context_with_same_paper_open_positive_builds(self):
        positive = self.read_record("TEST-2000-019")["claims"][0]
        unresolved = self.read_record("TEST-2000-023")["claims"][1]
        positive.pop("author_response", None)
        unresolved.pop("author_response", None)
        unresolved["role"] = "secondary"
        unresolved["unresolved_context"] = {"anchor_claim_id": positive["id"]}
        record = make_v3(self.read_record("TEST-2000-019"))
        record["claims"] = [positive, unresolved]
        record["primary_claim_id"] = positive["id"]
        record["kind"] = "defect"
        self.save_record(record)
        out = self.build_out()
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn("Context only.", page)
        self.assertIn("does not support or determine the qualifying positive finding", page)

    def test_context_companion_is_retired_when_its_only_anchor_is_corrected_nonpositive(self):
        prior = make_v3(self.read_record("TEST-2000-019"))
        context = json.loads(json.dumps(prior["claims"][0]))
        context["id"] = "c2"
        context["label"] = "Previously contextual question"
        context["role"] = "secondary"
        context["result"] = {"outcome": "unresolved", "unresolved_reason": "conflicting_checks",
                             "summary": "A separate contextual question.",
                             "detail": "Synthetic unresolved context.", "limits": "Not settled."}
        context["unresolved_context"] = {"anchor_claim_id": "c1"}
        prior["claims"].append(context)
        self.save_record(prior)
        self.build_out("context_prior")
        prior_bytes = self.record_path("TEST-2000-019", "1.0").read_bytes()

        corrected = json.loads(json.dumps(prior))
        corrected["version"] = "1.1"
        corrected["released"] = "2000-06-06"
        corrected["claims"] = [corrected["claims"][0]]
        corrected["claims"][0]["publication_revision"] = {
            "from_version": "1.0", "from_status": "open", "to_status": "unresolved",
            "prior_sha256": release_safety.sha256(prior_bytes),
            "reason": "New evidence makes the previously public positive unresolved.",
        }
        corrected["claims"][0]["result"] = {
            "outcome": "unresolved", "unresolved_reason": "conflicting_checks",
            "summary": "The former Open finding is now unresolved.",
            "detail": "New technical evidence leaves the precise claim unsettled.",
            "limits": "This correction does not establish the former positive finding.",
        }
        corrected["kind"] = "status_correction"
        corrected["changelog"].append({"version": "1.1", "date": "2000-06-06", "our_correction": False,
                                       "revision_type": "superseding_evidence",
                                       "change": "Retired unresolved context whose only positive anchor was corrected."})
        corrected["history"].append({"date": "2000-06-06", "type": "release", "label": "Record version 1.1 released"})
        self.save_record(corrected)
        out = self.build_out("context_retired")
        current = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        archived = (out / "cases/TEST-2000-019/v1.0/index.html").read_text(encoding="utf-8")
        self.assertIn("Current status:", current)
        self.assertNotIn("Previously contextual question", current)
        self.assertIn("Previously contextual question", archived)
        self.assertIn("Context only.", archived)

    def test_unresolved_context_cannot_anchor_on_negative_audit(self):
        record = make_v3(self.read_record("TEST-2000-023"), primary="c1")
        record["claims"][1]["role"] = "secondary"
        record["claims"][1]["unresolved_context"] = {"anchor_claim_id": "c1"}
        self.save_record(record)
        with self.assertRaisesRegex(build.BuildError, "requires a qualifying positive finding"):
            build.Content("published", self.root).load()

    def test_unresolved_context_cannot_be_the_principal_claim(self):
        positive = self.read_record("TEST-2000-019")["claims"][0]
        unresolved = self.read_record("TEST-2000-023")["claims"][1]
        positive.pop("author_response", None)
        unresolved.pop("author_response", None)
        unresolved["role"] = "main"
        unresolved["unresolved_context"] = {"anchor_claim_id": positive["id"]}
        record = make_v3(self.read_record("TEST-2000-019"))
        record["claims"] = [positive, unresolved]
        record["primary_claim_id"] = positive["id"]
        self.save_record(record)
        with self.assertRaisesRegex(build.BuildError, "must be clearly secondary"):
            build.Content("published", self.root).load()

    def test_unresolved_context_cannot_name_a_secondary_positive_beside_another_main_claim(self):
        positive = self.read_record("TEST-2000-019")["claims"][0]
        unresolved = self.read_record("TEST-2000-023")["claims"][1]
        other_main = self.read_record("TEST-2000-023")["claims"][0]
        for claim in (positive, unresolved, other_main):
            claim.pop("author_response", None)
        positive["role"] = "secondary"
        other_main["id"] = "c3"
        unresolved["role"] = "secondary"
        unresolved["unresolved_context"] = {"anchor_claim_id": positive["id"]}
        record = make_v3(self.read_record("TEST-2000-019"))
        record["claims"] = [positive, other_main, unresolved]
        record["primary_claim_id"] = positive["id"]
        self.save_record(record)
        with self.assertRaisesRegex(build.BuildError, "qualifying positive finding about the same paper"):
            build.Content("published", self.root).load()

    def correction_record(self, to_status):
        prior_path = self.record_path("TEST-2000-019")
        prior_bytes = prior_path.read_bytes()
        record = self.read_record("TEST-2000-019")
        record["version"] = "1.1"
        record["released"] = "2000-06-06"
        record = make_v3(record)
        claim = record["claims"][0]
        reason = {"from_version": "1.0", "from_status": "open", "to_status": to_status,
                  "prior_sha256": release_safety.sha256(prior_bytes), "reason": "New evidence changes the public status or scope."}
        claim["publication_revision"] = reason
        if to_status == "unresolved":
            record["kind"] = "status_correction"
            claim["result"] = {"outcome": "unresolved", "unresolved_reason": "conflicting_checks",
                               "summary": "The prior Open finding is now unresolved.",
                               "detail": "New technical evidence leaves the precise claim unsettled.",
                               "limits": "This correction does not establish the former positive finding."}
        elif to_status == "rejected":
            record["kind"] = "status_correction"
            claim["result"] = {"outcome": "no_defect_found", "depth": "claim_check", "summary": "The former candidate does not stand.",
                               "search_scope": "The previously identified counterexample was checked against the exact assumptions.",
                               "limits": "This is a correction of the former Open finding, not a new negative audit."}
        else:
            claim["result"]["summary"] = "The current positive finding is narrowed to the stated scope."
        record["changelog"].append({"version": "1.1", "date": "2000-06-06", "our_correction": False,
                                    "revision_type": "material_narrowing" if to_status == "open" else "superseding_evidence",
                                    "change": "Corrected the status or scope after new evidence."})
        record["history"].append({"date": "2000-06-06", "type": "release", "label": "Record version 1.1 released"})
        return record

    def test_previously_public_open_can_be_corrected_to_unresolved_and_history_stays_linked(self):
        self.save_record(self.correction_record("unresolved"))
        out = self.build_out()
        current = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        prior = (out / "cases/TEST-2000-019/v1.0/index.html").read_text(encoding="utf-8")
        self.assertIn("Current status: <span class=\"status status-unresolved\">Unresolved", current)
        self.assertIn("supersedes the prior", current)
        self.assertIn("cases/TEST-2000-019/v1.0/", current)
        self.assertIn("Archived version 1.0", prior)
        self.assertIn("cases/TEST-2000-019/", prior)
        self.assertIn("Current status for claim", prior)
        self.assertIn("Unresolved", prior)

    def test_open_to_open_narrowing_does_not_repeat_initial_hostile_gate(self):
        corrected = self.correction_record("open")
        corrected["claims"][0]["evidence"] = []
        self.save_record(corrected)
        out = self.build_out("open_narrowing_without_repeat_hostile")
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn("Corrective version.", page)
        self.assertIn('class="status status-open"', page)
        self.assertNotIn("Separate-session hostile AI recheck", page)

    def test_restoring_open_after_unresolved_requires_current_hostile_evidence(self):
        unresolved = self.correction_record("unresolved")
        self.save_record(unresolved)
        self.build_out("prior_unresolved")
        prior_bytes = self.record_path("TEST-2000-019", "1.1").read_bytes()
        original_claim = self.read_record("TEST-2000-019", "1.0")["claims"][0]

        restored = self.read_record("TEST-2000-019", "1.1")
        restored["version"] = "1.2"
        restored["released"] = "2000-06-07"
        claim = restored["claims"][0]
        claim["publication_revision"] = {"from_version": "1.1", "from_status": "unresolved",
                                         "to_status": "open", "prior_sha256": release_safety.sha256(prior_bytes),
                                         "reason": "Later evidence restores the former positive status."}
        claim["result"] = json.loads(json.dumps(original_claim["result"]))
        claim["evidence"] = []
        restored["kind"] = "defect"
        restored["changelog"].append({"version": "1.2", "date": "2000-06-07", "our_correction": False,
                                      "revision_type": "superseding_evidence",
                                      "change": "Restored the status after new positive validation."})
        restored["history"].append({"date": "2000-06-07", "type": "release", "label": "Record version 1.2 released"})
        self.save_record(restored)
        with self.assertRaisesRegex(build.BuildError, "separate-session hostile AI recheck"):
            build.Content("published", self.root).load()

        claim["evidence"] = json.loads(json.dumps(original_claim["evidence"]))
        self.save_record(restored)
        out = self.build_out("restored_open_with_hostile")
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn("Current status:", page)
        self.assertIn('class="status status-open"', page)

    def test_correction_chain_can_continue_after_open_becomes_unresolved(self):
        first = self.correction_record("unresolved")
        self.save_record(first)
        first_bytes = self.record_path("TEST-2000-019", "1.1").read_bytes()
        second = json.loads(json.dumps(first))
        second["version"] = "1.2"
        second["released"] = "2000-06-07"
        claim = second["claims"][0]
        claim["publication_revision"] = {
            "from_version": "1.1", "from_status": "unresolved", "to_status": "rejected",
            "prior_sha256": release_safety.sha256(first_bytes),
            "reason": "A later check resolves the formerly unresolved question.",
        }
        claim["result"] = {"outcome": "no_defect_found", "depth": "claim_check",
                           "summary": "The former candidate does not stand.",
                           "search_scope": "The new check addresses the formerly unresolved point.",
                           "limits": "This corrects the formerly public Open finding."}
        second["changelog"].append({"version": "1.2", "date": "2000-06-07", "our_correction": False,
                                    "revision_type": "superseding_evidence",
                                    "change": "Superseded the unresolved status after later evidence."})
        second["history"].append({"date": "2000-06-07", "type": "release", "label": "Record version 1.2 released"})
        self.save_record(second)
        out = self.build_out()
        current = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        prior = (out / "cases/TEST-2000-019/v1.0/index.html").read_text(encoding="utf-8")
        self.assertIn("Current status: <span class=\"status status-rejected\">Rejected", current)
        self.assertIn("v1.1/", current)
        self.assertIn("Current status for claim", prior)
        self.assertIn("Rejected", prior)

    def test_corrected_unresolved_and_rejected_statuses_carry_forward_on_later_versions(self):
        for status in ("open", "unresolved", "rejected"):
            with self.subTest(status=status):
                record_dir = self.record_path("TEST-2000-019", "1.0").parent
                for old in record_dir.glob("v*.json"):
                    if old.name != "v1.0.json":
                        old.unlink()
                release_dir = self.root / "content" / "published" / "releases"
                for old in release_dir.glob("record__TEST-2000-019__*.txt"):
                    if old.name != "record__TEST-2000-019__1.0.txt":
                        old.unlink()
                first = self.correction_record(status)
                self.save_record(first)
                carried = json.loads(json.dumps(first))
                carried["version"] = "1.2"
                carried["released"] = "2000-06-07"
                claim = carried["claims"][0]
                claim.pop("publication_revision")
                claim["status_provenance"] = {"status": status, "revision_version": "1.1"}
                if status == "open":
                    claim["evidence"] = []
                claim["author_response"] = {"position": "disagrees"}
                carried["outreach"] = {"status": "substantive_response_received"}
                carried["changelog"].append({"version": "1.2", "date": "2000-06-07",
                                              "our_correction": False, "change": "Updated factual outreach state."})
                carried["history"].append({"date": "2000-06-07", "type": "release",
                                            "label": "Record version 1.2 released"})
                self.save_record(carried)
                out = self.build_out("carried_" + status)
                page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
                self.assertIn("Status carried forward", page)
                self.assertIn("correction version 1.1", page)
                self.assertIn("cases/TEST-2000-019/v1.1/", page)
                self.assertIn("Substantive author response received", page)
                self.assertNotIn("Corrective version.", page)
                if status == "unresolved":
                    self.assertIn('class="status status-unresolved">Unresolved', page)
                    self.assertNotIn("Context only.", page)
                elif status == "rejected":
                    self.assertIn('class="status status-rejected">Rejected', page)
                    self.assertNotIn(build.NEGATIVE_CAVEAT, page)
                else:
                    self.assertIn('class="status status-open"', page)
                if status == "unresolved":
                    carried_bytes = self.record_path("TEST-2000-019", "1.2").read_bytes()
                    revised = json.loads(json.dumps(carried))
                    revised["version"] = "1.3"
                    revised["released"] = "2000-06-08"
                    revised_claim = revised["claims"][0]
                    revised_claim.pop("status_provenance")
                    revised_claim["publication_revision"] = {
                        "from_version": "1.2", "from_status": "unresolved", "to_status": "rejected",
                        "prior_sha256": release_safety.sha256(carried_bytes),
                        "reason": "A later check resolves the formerly unresolved question.",
                    }
                    revised_claim["result"] = {"outcome": "no_defect_found", "depth": "claim_check",
                                                "summary": "The former candidate does not stand.",
                                                "search_scope": "The new check addresses the formerly unresolved point.",
                                                "limits": "This corrects the formerly public Open finding."}
                    revised["changelog"].append({"version": "1.3", "date": "2000-06-08",
                                                 "our_correction": False, "revision_type": "superseding_evidence",
                                                 "change": "Superseded the unresolved status after later evidence."})
                    revised["history"].append({"date": "2000-06-08", "type": "release",
                                                "label": "Record version 1.3 released"})
                    self.save_record(revised)
                    revised_out = self.build_out("second_correction_after_carry")
                    revised_page = (revised_out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
                    archived = (revised_out / "cases/TEST-2000-019/v1.1/index.html").read_text(encoding="utf-8")
                    self.assertIn('class="status status-rejected">Rejected', revised_page)
                    self.assertIn("Corrective version.", revised_page)
                    self.assertIn("Current status for claim", archived)
                    self.assertIn("Rejected", archived)

    def test_archived_open_page_tracks_latest_status_through_correction_chain(self):
        versions = [
            {"version": "1.0", "claims": [{"id": "c1", "result": {"outcome": "defect_found", "status": "open"}}]},
            {"version": "1.1", "claims": [{"id": "c1", "publication_revision": {"from_version": "1.0"},
                                              "result": {"outcome": "unresolved"}}]},
            {"version": "1.2", "claims": [{"id": "c1", "publication_revision": {"from_version": "1.1"},
                                              "result": {"outcome": "no_defect_found"}}]},
            {"version": "1.3", "claims": [{"id": "c1", "result": {"outcome": "no_defect_found"}}]},
        ]
        current = build.latest_correction_descendant(versions, "1.0", "c1")
        self.assertIs(current, versions[-1]["claims"][0])

    def test_prior_public_claim_cannot_be_removed_from_new_projection(self):
        record = self.read_record("TEST-2000-019")
        record["version"] = "1.1"
        record["released"] = "2000-06-06"
        record = make_v3(record, primary="c2")
        record["claims"][0]["id"] = "c2"
        record["primary_claim_id"] = "c2"
        record["changelog"].append({"version": "1.1", "date": "2000-06-06", "our_correction": False,
                                    "change": "Added another record version."})
        record["history"].append({"date": "2000-06-06", "type": "release", "label": "Record version 1.1 released"})
        self.save_record(record)
        with self.assertRaisesRegex(build.BuildError, "previously public claim was removed"):
            build.Content("published", self.root).load()

    def test_open_claim_cannot_be_relabelled_as_unresolved_context_without_correction(self):
        record = self.read_record("TEST-2000-019")
        record["version"] = "1.1"
        record["released"] = "2000-06-06"
        record = make_v3(record)
        open_claim = record["claims"][0]
        anchor = json.loads(json.dumps(open_claim))
        anchor["id"] = "c2"
        anchor["label"] = "Synthetic anchor claim"
        anchor["role"] = "main"
        record["primary_claim_id"] = "c2"
        open_claim["role"] = "secondary"
        open_claim["result"] = {"outcome": "unresolved", "unresolved_reason": "conflicting_checks",
                                 "summary": "The formerly Open claim is unsettled.",
                                 "detail": "Synthetic unresolved context.", "limits": "It is not a positive finding."}
        open_claim["unresolved_context"] = {"anchor_claim_id": "c2"}
        record["claims"].append(anchor)
        record["changelog"].append({"version": "1.1", "date": "2000-06-06", "our_correction": False,
                                    "change": "Added unresolved context."})
        record["history"].append({"date": "2000-06-06", "type": "release", "label": "Record version 1.1 released"})
        self.save_record(record)
        with self.assertRaisesRegex(build.BuildError, "status changed without a visible publication_revision"):
            build.Content("published", self.root).load()

    def test_schema2_keeps_its_original_unresolved_reason_enum(self):
        record = self.read_record("TEST-2000-019")
        record["claims"][0]["result"] = {"outcome": "unresolved", "unresolved_reason": "conflicting_checks",
                                           "summary": "Synthetic.", "detail": "Synthetic.", "limits": "Synthetic."}
        anchor = json.loads(json.dumps(record["claims"][0]))
        anchor["id"] = "c2"
        anchor["result"] = {"outcome": "defect_found", "status": "open", "defect_class": "definition_defect",
                             "affects": "main_result", "depth": "deep_audit", "summary": "Synthetic positive.",
                             "witness": "Synthetic witness.", "argument": "Synthetic argument.",
                             "not_claimed": ["Synthetic limit."], "repair": "none_proposed"}
        record["claims"].append(anchor)
        with self.assertRaisesRegex(build.BuildError, "unresolved claim needs a reason"):
            build.validate_any(record, record["public_id"], record["version"])

    def test_previously_public_open_can_be_narrowed_without_losing_open_gate(self):
        record = self.correction_record("open")
        self.save_record(record)
        out = self.build_out()
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        prior = (out / "cases/TEST-2000-019/v1.0/index.html").read_text(encoding="utf-8")
        self.assertIn("Current status:", page)
        self.assertIn('class="status status-open"', page)
        self.assertIn("Counterexample", page)
        self.assertIn("Archived version 1.0", prior)
        self.assertIn("cases/TEST-2000-019/", prior)

    def test_previously_public_open_can_be_corrected_to_rejected_without_becoming_a_new_negative_audit(self):
        self.save_record(self.correction_record("rejected"))
        out = self.build_out()
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn('class="status status-rejected">Rejected', page)
        self.assertIn("Refuting review", page)
        self.assertNotIn(build.NEGATIVE_CAVEAT, page)
        cases = (out / "cases/index.html").read_text(encoding="utf-8")
        self.assertIn('data-status="rejected"', cases)
        serialized = json.loads((out / "data/records/TEST-2000-019/v1.1.json").read_text(encoding="utf-8"))
        self.assertEqual(serialized["kind"], "status_correction")

    def test_narrowed_open_correction_does_not_repeat_initial_hostile_gate(self):
        record = self.correction_record("open")
        record["claims"][0]["evidence"] = []
        self.save_record(record)
        out = self.build_out()
        page = (out / "cases/TEST-2000-019/index.html").read_text(encoding="utf-8")
        self.assertIn('class="status status-open"', page)
        self.assertIn("Current status:", page)


class ReleaseControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="as_guard_"))
        self.control = self.tmp / "control"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        (self.control / "01_Registry" / "events").mkdir(parents=True)
        evidence_path = self.control / "synthetic_evidence.txt"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(TEST_ARTIFACT_BYTES)
        self.registry = {"works": [{"id": "W-0001", "title": "Synthetic work", "authors": ["Author A", "Author B"],
                                    "year": 2000, "venue": "Synthetic Journal", "doi": "10.0000/synthetic"}],
                         "sources": [{"id": "S-0001", "work": "W-0001", "kind": "vor"}],
                         "claims": [{"id": "W-0001.C1", "work": "W-0001", "kind": "lemma", "role": "main"}],
                         "cases": [{"id": "K-0001", "work": "W-0001"}],
                         "artifacts": [{"id": TEST_ARTIFACT_ID,
                                        "locations": [{"root": "GTA_ROOT", "relpath": "synthetic_evidence.txt"}]}]}
        dump(self.control / "01_Registry" / "records.json", self.registry)
        self.write_event(event("e-finding", "W-0001.C1", "finding", {"outcome": "defect_found"}, "2026-11-20"))
        self.write_event(event("e-status", "W-0001.C1", "candidate_status", {"status": "open", "reason": None}, "2026-11-20"))
        self.write_event(event("e-source", "W-0001.C1", "source_lock",
                               {"version_checked": "S-0001", "vor_level": "partial", "pages": "p. 1",
                                "elements": {"statement": "rendered_pages"}}, "2026-11-20"))
        self.write_event(event("e-hostile", "W-0001.C1", "check",
                               {"run": "SYNTHETIC_HOSTILE", "checker": "ai", "session": "fresh_informed",
                                "method": "independent_code", "result": "confirms", "report": TEST_ARTIFACT_ID},
                               "2026-11-21"))
        self.write_event(event("e-novelty", "W-0001.C1", "novelty",
                               {"status": "no_prior_report_found", "searched": "Synthetic exact-title and DOI search.",
                                "as_of": "2026-11-22"}, "2026-11-22"))
        self.record = {"public_id": "TA-TEST-001", "version": "1.0", "schema": 3,
                       "primary_claim_id": "c1", "work": {"title": "Synthetic work", "authors": ["Author A", "Author B"],
                                                             "year": 2000, "venue": "Synthetic Journal",
                                                             "doi": "10.0000/synthetic"},
                       "claims": [{"id": "c1", "kind": "lemma", "role": "main", "vor_check": {"level": "partial"},
                                   "evidence": [],
                                   "result": {"outcome": "defect_found", "status": "open"}}]}
        self.data = {"public_id": "TA-TEST-001", "record_version": "1.0", "case_ids": ["W-0001"],
                     "registry_case_ids": ["K-0001"], "canonical_claims": {"c1": {"id": "W-0001.C1"}},
                     "claim_authorizations": {"c1": "standing_open"},
                     "claim_reviews": {"c1": {"finding_event_id": "e-finding", "status_event_id": "e-status",
                                                "source_lock_event_id": "e-source", "check_event_ids": ["e-hostile"],
                                                "reviewed_event_ids": [], "author_position_event_id": None,
                                                "evidence_artifacts": [{"id": TEST_ARTIFACT_ID, "sha256": TEST_ARTIFACT_SHA}],
                                                "evidence_event_ids": [],
                                                "readiness": {"witness_and_counterexample_complete": True,
                                                              "scope_and_nonclaims_complete": True,
                                                              "correction_search_complete": True,
                                                              "novelty_event_id": "e-novelty",
                                                              "source_correction_event_ids": [],
                                                              "hostile_check_event_id": "e-hostile",
                                                              "refuting_check_event_ids": []}}},
                     "canonical_snapshot": {},
                     "release_checks": {"canonical_review_complete": True, "rights_privacy_clear": True,
                                        "public_presentation_ready": True, "initial_open_gates_complete": True}}
        self.refresh_snapshot()

    def tearDown(self):
        def clear_readonly(func, path, exc):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        shutil.rmtree(self.tmp, onexc=clear_readonly)

    def write_event(self, value):
        dump(self.control / "01_Registry" / "events" / f"{value['event']}.json", value)

    def refresh_snapshot(self):
        records_bytes = (self.control / "01_Registry" / "records.json").read_bytes()
        event_values = [json.loads(path.read_bytes()) for path in
                        sorted((self.control / "01_Registry" / "events").glob("*.json"))]
        claim_events = [item for item in event_values if item.get("subject") == "W-0001.C1"]
        active = release_safety.active_events(claim_events)
        checks = [item for item in active if item.get("dimension") == "check"]
        current_ids = [item["event"] for item in checks]
        for dimension in ("finding", "candidate_status", "source_lock", "author_position", "reproduction",
                          "novelty", "source_correction", "manuscript"):
            value = release_safety.latest_event(claim_events, "W-0001.C1", dimension)
            if value:
                current_ids.append(value["event"])
        source_corrections = release_safety.source_corrections_for_claim(event_values, "W-0001.C1")
        current_ids.extend(item["event"] for item in source_corrections)
        review = self.data["claim_reviews"]["c1"]
        review["check_event_ids"] = sorted(item["event"] for item in checks)
        review["reviewed_event_ids"] = sorted(current_ids)
        review["readiness"]["source_correction_event_ids"] = sorted(item["event"] for item in source_corrections)
        if "readiness" in review and "refuting_check_event_ids" in review["readiness"]:
            review["readiness"]["refuting_check_event_ids"] = sorted(
                item["event"] for item in checks if item.get("value", {}).get("result") == "refutes")
        event_digest = release_safety.event_file_digest(self.control / "01_Registry")
        receipt = {"format": "as-stated-applied-changeset/1", "sequence": 1, "id": "CS-SYNTHETIC",
                   "before": {"records_sha256": "0" * 64, "events_sha256": "0" * 64},
                   "after": {"records_sha256": release_safety.sha256(records_bytes), "events_sha256": event_digest},
                   "validation": {"errors": 0, "warnings": 0}}
        receipt_path = self.control / "01_Registry" / "changesets" / "applied" / "CS-SYNTHETIC.json"
        dump(receipt_path, receipt)
        inv = []
        for path in sorted((self.control / "01_Registry" / "events").glob("*.json")):
            raw = path.read_bytes()
            ev = json.loads(raw)
            case_ids = {item["id"] for item in self.registry.get("cases", [])}
            if ev.get("subject") in {"W-0001", "W-0001.C1", *case_ids}:
                inv.append({"path": path.relative_to(self.control).as_posix(), "sha256": release_safety.sha256(raw)})
        self.data["canonical_snapshot"] = {"records_json_sha256": release_safety.sha256(records_bytes), "event_files": inv,
                                            "applied_receipt_id": receipt["id"],
                                            "applied_receipt_sha256": release_safety.sha256(receipt_path.read_bytes())}

    def test_raw_discovery_without_canonical_work_or_claim_is_blocked(self):
        self.data["case_ids"] = ["W-9999"]
        with self.assertRaisesRegex(release_safety.GuardError, "not present in the canonical registry"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_open_positive_with_no_outreach_passes_standing_authorization(self):
        release_safety.validate_release_checks(self.data, self.record)
        release_safety.validate_canonical(self.control, self.data, self.record)

    def test_negative_audit_conflicting_with_open_canonical_status_is_blocked(self):
        self.record["claims"][0]["result"] = {"outcome": "no_defect_found", "depth": "deep_audit",
                                                "search_scope": "Synthetic bounded search.",
                                                "limits": "Not proof of correctness."}
        self.write_event(event("e-finding", "W-0001.C1", "finding",
                               {"outcome": "no_defect_found", "depth": "deep_audit"}))
        self.refresh_snapshot()
        with self.assertRaisesRegex(release_safety.GuardError, "conflicts with a negative audit"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_author_agreement_without_evidence_cannot_count_as_human_confirmation(self):
        author_position = event("e-author", "W-0001.C1", "author_position", {"position": "agrees"})
        author_position["evidence"] = []
        claim = {"id": "c1", "evidence": [{"type": "private_human_confirmation", "date": "2026-11-22"}]}
        review = {"evidence_event_ids": ["e-author"]}
        with self.assertRaisesRegex(release_safety.GuardError, "does not match its cited canonical event"):
            release_safety.validate_public_evidence(claim, review, {"author_position": author_position}, [])

    def test_initial_hostile_check_must_follow_source_lock(self):
        claim = self.record["claims"][0]
        readiness = self.data["claim_reviews"]["c1"]["readiness"]
        hostile = event("e-hostile", "W-0001.C1", "check",
                        {"checker": "ai", "session": "fresh_blind", "method": "independent_code",
                         "result": "confirms"})
        hostile["recorded_at"] = "2026-11-22T09:00:00+11:00"
        current = {"novelty": event("e-novelty", "W-0001.C1", "novelty",
                                     {"status": "no_prior_report_found"}),
                   "source_correction_events": [],
                   "source_lock": event("e-source", "W-0001.C1", "source_lock", {}),
                   "finding": event("e-finding", "W-0001.C1", "finding", {"outcome": "defect_found"})}
        with self.assertRaisesRegex(release_safety.GuardError, "fresh hostile technical check"):
            release_safety.validate_claim_readiness(claim, {"readiness": readiness}, current, [hostile])

    def test_initial_open_allows_finding_event_after_fresh_hostile_check(self):
        claim = self.record["claims"][0]
        readiness = json.loads(json.dumps(self.data["claim_reviews"]["c1"]["readiness"]))
        hostile = event("e-hostile", "W-0001.C1", "check",
                        {"checker": "ai", "session": "fresh_blind", "method": "independent_code",
                         "result": "confirms"})
        finding = event("e-finding", "W-0001.C1", "finding", {"outcome": "defect_found"})
        current = {"novelty": event("e-novelty", "W-0001.C1", "novelty",
                                     {"status": "no_prior_report_found"}),
                   "source_correction_events": [],
                   "source_lock": event("e-source", "W-0001.C1", "source_lock", {}),
                   "finding": finding}
        release_safety.validate_claim_readiness(claim, {"readiness": readiness}, current, [hostile])

    def test_restored_positive_requires_hostile_after_exact_prior_public_nonpositive_status(self):
        claim = json.loads(json.dumps(self.record["claims"][0]))
        claim["publication_revision"] = {"from_status": "unresolved", "to_status": "open"}
        readiness = json.loads(json.dumps(self.data["claim_reviews"]["c1"]["readiness"]))
        readiness["correction_status_review_complete"] = True
        readiness["hostile_check_event_id"] = "e-hostile-restoration"
        hostile = event("e-hostile-restoration", "W-0001.C1", "check",
                        {"checker": "ai", "session": "fresh_blind", "method": "independent_code",
                         "result": "confirms"})
        prior_status = event("e-prior-unresolved", "W-0001.C1", "candidate_status",
                             {"status": "unresolved"})
        prior_status["recorded_at"] = "2026-11-22T10:30:00+11:00"
        current = {"novelty": event("e-novelty", "W-0001.C1", "novelty",
                                     {"status": "no_prior_report_found"}),
                   "source_correction_events": [],
                   "source_lock": event("e-source", "W-0001.C1", "source_lock", {}),
                   "finding": event("e-finding", "W-0001.C1", "finding", {"outcome": "defect_found"}),
                   "prior_nonpositive_status": prior_status}
        release_safety.validate_claim_readiness(claim, {"readiness": readiness}, current, [hostile])
        hostile["recorded_at"] = "2026-11-22T10:20:00+11:00"
        with self.assertRaisesRegex(release_safety.GuardError, "fresh hostile technical check"):
            release_safety.validate_claim_readiness(claim, {"readiness": readiness}, current, [hostile])

    def test_paper_only_canonical_artifact_fails_closed_without_reading_pointer_bytes(self):
        pointer = self.control / "opaque.paper"
        pointer.touch()
        self.registry["artifacts"][0]["locations"] = [{"root": "GTA_ROOT", "relpath": "opaque.paper"}]
        dump(self.control / "01_Registry" / "records.json", self.registry)
        self.refresh_snapshot()
        with self.assertRaisesRegex(release_safety.GuardError, "no verifiable non-.paper location"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_researcher_reproduction_evidence_requires_a_qualifying_human_check(self):
        human_check = event("e-researcher", "W-0001.C1", "check",
                            {"run": "SYNTHETIC_HUMAN", "checker": "programme_researcher",
                             "method": "independent_code", "result": "confirms", "report": TEST_ARTIFACT_ID},
                            "2026-11-21")
        self.record["claims"][0]["evidence"] = [{"type": "researcher_reproduction", "date": "2026-11-21",
                                                   "detail": "Synthetic independent check."}]
        self.data["claim_reviews"]["c1"]["evidence_event_ids"] = ["e-researcher"]
        release_safety.validate_public_evidence(self.record["claims"][0], self.data["claim_reviews"]["c1"],
                                                {}, [human_check])

    def test_researcher_package_rerun_cannot_count_as_independent_reproduction(self):
        rerun = event("e-rerun", "W-0001.C1", "check",
                      {"run": "SYNTHETIC_RERUN", "checker": "programme_researcher",
                       "method": "rerun_original_package", "result": "confirms", "report": TEST_ARTIFACT_ID},
                      "2026-11-21")
        self.record["claims"][0]["evidence"] = [{"type": "researcher_reproduction", "date": "2026-11-21",
                                                   "detail": "Synthetic package rerun."}]
        self.data["claim_reviews"]["c1"]["evidence_event_ids"] = ["e-rerun"]
        with self.assertRaisesRegex(release_safety.GuardError, "does not match its cited canonical event"):
            release_safety.validate_public_evidence(self.record["claims"][0], self.data["claim_reviews"]["c1"],
                                                    {}, [rerun])

    def test_private_human_confirmation_requires_confirming_nonpackage_evidence(self):
        claim = {"id": "c1", "evidence": [{"type": "private_human_confirmation", "date": "2026-11-21",
                                             "detail": "Synthetic private human check."}]}
        review = {"evidence_event_ids": ["e-private-human"]}
        for result, method in (("partially_confirms", "independent_code"),
                               ("confirms", "rerun_original_package")):
            human_check = event("e-private-human", "W-0001.C1", "check",
                                {"run": "SYNTHETIC_HUMAN", "checker": "external_human", "method": method,
                                 "result": result, "report": TEST_ARTIFACT_ID}, "2026-11-21")
            with self.subTest(result=result, method=method):
                with self.assertRaisesRegex(release_safety.GuardError, "does not match its cited canonical event"):
                    release_safety.validate_public_evidence(claim, review, {}, [human_check])

    def test_partial_external_check_cannot_be_public_support_for_confirmed_status(self):
        claim = {"id": "c1", "result": {"status": "confirmed"},
                 "evidence": [{"type": "external_check", "date": "2026-11-21",
                               "detail": "Synthetic partial external review."}]}
        review = {"evidence_event_ids": ["e-external"]}
        external = event("e-external", "W-0001.C1", "check",
                         {"checker": "external_human", "method": "hand_proof_check",
                          "result": "partially_confirms"}, "2026-11-21")
        with self.assertRaisesRegex(release_safety.GuardError, "does not match its cited canonical event"):
            release_safety.validate_public_evidence(claim, review, {}, [external])
        qualifying = event("e-external", "W-0001.C1", "check",
                           {"run": "SYNTHETIC_HUMAN", "checker": "external_human", "method": "independent_code",
                            "result": "confirms", "report": TEST_ARTIFACT_ID}, "2026-11-21")
        release_safety.validate_public_evidence(claim, review, {}, [qualifying])

    def test_partial_hostile_check_cannot_be_projected_as_survived(self):
        partial = event("e-partial", "W-0001.C1", "check",
                        {"run": "SYNTHETIC_PARTIAL", "checker": "ai", "session": "fresh_informed",
                         "method": "independent_code", "result": "partially_confirms", "report": TEST_ARTIFACT_ID},
                        "2026-11-21")
        self.record["claims"][0]["evidence"] = [{"type": "hostile_ai_recheck", "date": "2026-11-21",
                                                   "session": "informed", "detail": "Synthetic partial check."}]
        self.data["claim_reviews"]["c1"]["evidence_event_ids"] = ["e-partial"]
        with self.assertRaisesRegex(release_safety.GuardError, "does not match its cited canonical event"):
            release_safety.validate_public_evidence(self.record["claims"][0], self.data["claim_reviews"]["c1"],
                                                    {}, [partial])

    def test_corrected_open_claim_uses_status_scope_review_without_initial_hostile_gate(self):
        claim = self.record["claims"][0]
        claim["publication_revision"] = {"to_status": "open"}
        claim["evidence"] = []
        readiness = self.data["claim_reviews"]["c1"]["readiness"]
        readiness.clear()
        readiness.update({"correction_status_review_complete": True, "refuting_check_event_ids": []})
        self.data["claim_reviews"]["c1"]["evidence_event_ids"] = []
        checks = [json.loads(path.read_text(encoding="utf-8")) for path in
                  sorted((self.control / "01_Registry" / "events").glob("*.json"))
                  if json.loads(path.read_text(encoding="utf-8")).get("dimension") == "check"]
        current = {"candidate_status": json.loads((self.control / "01_Registry" / "events" / "e-status.json")
                                                       .read_text(encoding="utf-8"))}
        release_safety.validate_claim_readiness(claim, self.data["claim_reviews"]["c1"], current, checks)
        readiness.pop("correction_status_review_complete")
        with self.assertRaisesRegex(release_safety.GuardError, "corrective status and scope review"):
            release_safety.validate_claim_readiness(claim, self.data["claim_reviews"]["c1"], current, checks)

    def test_public_claim_role_and_kind_are_bound_to_canonical_metadata(self):
        self.registry["claims"][0]["role"] = "secondary"
        dump(self.control / "01_Registry" / "records.json", self.registry)
        self.refresh_snapshot()
        with self.assertRaisesRegex(release_safety.GuardError, "kind or role differs"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_public_claims_cannot_duplicate_one_canonical_claim_mapping(self):
        duplicate = json.loads(json.dumps(self.record["claims"][0]))
        duplicate["id"] = "c2"
        self.record["claims"].append(duplicate)
        self.data["canonical_claims"]["c2"] = {"id": "W-0001.C1"}
        with self.assertRaisesRegex(release_safety.GuardError, "one-to-one to distinct canonical claims"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_work_subject_source_correction_is_inventoried_and_bound_to_public_projection(self):
        correction_value = {"document": "corrigendum", "doi_or_url": "10.0000/correction",
                            "date": "2026-11-20", "addresses_claims": ["W-0001.C1"],
                            "relation": "after_notification", "attribution": "credits_programme"}
        self.write_event(event("e-correction", "W-0001", "source_correction", correction_value, "2026-11-20"))
        self.refresh_snapshot()
        self.record["correction"] = {"state": "formal_correction_published", "type": "corrigendum",
                                      "doi": "10.0000/correction", "date": "2026-11-20",
                                      "relation": "after_notification", "attribution": "credits_programme",
                                      "claims": ["c1"], "note": "Synthetic public correction."}
        release_safety.validate_canonical(self.control, self.data, self.record)
        self.record["correction"]["date"] = "2026-11-21"
        with self.assertRaisesRegex(release_safety.GuardError, "metadata differs from canonical source-correction"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_public_correction_without_canonical_event_is_blocked(self):
        self.record["correction"] = {"state": "announced", "type": "author_note", "doi": None,
                                      "date": "2026-11-20", "relation": "after_notification",
                                      "attribution": "none_stated", "claims": ["c1"], "note": "Synthetic note."}
        with self.assertRaisesRegex(release_safety.GuardError, "no active canonical source-correction event"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_historical_source_correction_for_retired_context_keeps_exact_prior_projection(self):
        prior = {"state": "formal_correction_published", "type": "corrigendum", "doi": "10.0000/correction",
                 "date": "2026-11-20", "relation": "after_notification", "attribution": "credits_programme",
                 "claims": ["c2"], "note": "Synthetic public correction."}
        record = {"correction": json.loads(json.dumps(prior))}
        correction_event = event("e-retired-correction", "W-0001", "source_correction",
                                 {"document": "corrigendum", "doi_or_url": "10.0000/correction",
                                  "date": "2026-11-20", "addresses_claims": ["W-0001.C2"],
                                  "relation": "after_notification", "attribution": "credits_programme"})
        release_safety.validate_public_correction_projection(
            record, {"c1": {"id": "W-0001.C1"}}, [correction_event], {"c2"}, prior)
        record["correction"]["note"] = "New unsupported metadata."
        with self.assertRaisesRegex(release_safety.GuardError, "byte-for-byte unchanged"):
            release_safety.validate_public_correction_projection(
                record, {"c1": {"id": "W-0001.C1"}}, [correction_event], {"c2"}, prior)

    def test_retired_claim_cannot_be_added_to_source_correction_projection(self):
        prior = {"claims": ["c1"]}
        correction = {"type": "corrigendum", "doi": "10.0000/correction", "date": "2026-11-20",
                      "relation": "after_notification", "attribution": "credits_programme",
                      "claims": ["c1", "c2"]}
        record = {"correction": correction}
        correction_event = event("e-current-correction", "W-0001", "source_correction",
                                 {"document": "corrigendum", "doi_or_url": "10.0000/correction",
                                  "date": "2026-11-20", "addresses_claims": ["W-0001.C1"],
                                  "relation": "after_notification", "attribution": "credits_programme"})
        with self.assertRaisesRegex(release_safety.GuardError, "cannot be added"):
            release_safety.validate_public_correction_projection(
                record, {"c1": {"id": "W-0001.C1"}}, [correction_event], {"c2"}, prior)

    def test_explicit_not_contacted_outreach_projects_as_a_factual_state(self):
        self.write_event(event("e-outreach", "K-0001", "outreach", {"status": "not_contacted"}, "2026-11-20"))
        self.refresh_snapshot()
        self.record["outreach"] = {"status": "not_contacted"}
        self.data["outreach_events"] = [{"case_id": "K-0001", "event_id": "e-outreach"}]
        release_safety.validate_canonical(self.control, self.data, self.record)

    def test_current_canonical_outreach_may_be_omitted_from_public_record(self):
        self.write_event(event("e-outreach", "K-0001", "outreach", {"status": "contacted"}, "2026-11-20"))
        self.refresh_snapshot()
        release_safety.validate_canonical(self.control, self.data, self.record)

    def test_note_drafted_projects_as_not_contacted(self):
        self.write_event(event("e-outreach", "K-0001", "outreach", {"status": "note_drafted"}, "2026-11-20"))
        self.refresh_snapshot()
        self.record["outreach"] = {"status": "not_contacted"}
        self.data["outreach_events"] = [{"case_id": "K-0001", "event_id": "e-outreach"}]
        release_safety.validate_canonical(self.control, self.data, self.record)

    def test_unsupported_canonical_outreach_can_be_omitted(self):
        self.write_event(event("e-outreach", "K-0001", "outreach",
                               {"status": "correction_in_preparation"}, "2026-11-20"))
        self.refresh_snapshot()
        release_safety.validate_canonical(self.control, self.data, self.record)

    def test_reply_and_author_position_project_independently_without_correspondence(self):
        self.write_event(event("e-outreach", "K-0001", "outreach", {"status": "reply_received"}, "2026-11-20"))
        self.write_event(event("e-position", "W-0001.C1", "author_position", {"position": "disagrees"}, "2026-11-20"))
        self.refresh_snapshot()
        self.record["outreach"] = {"status": "substantive_response_received"}
        self.record["claims"][0]["author_response"] = {"position": "disagrees"}
        self.data["outreach_events"] = [{"case_id": "K-0001", "event_id": "e-outreach"}]
        self.data["claim_reviews"]["c1"]["author_position_event_id"] = "e-position"
        release_safety.validate_canonical(self.control, self.data, self.record)

    def test_multi_case_outreach_cannot_be_projected_as_one_conflicting_state(self):
        self.registry["cases"].append({"id": "K-0002", "work": "W-0001"})
        dump(self.control / "01_Registry" / "records.json", self.registry)
        self.data["registry_case_ids"] = ["K-0001", "K-0002"]
        self.write_event(event("e-outreach-1", "K-0001", "outreach", {"status": "not_contacted"}, "2026-11-20"))
        self.write_event(event("e-outreach-2", "K-0002", "outreach", {"status": "reply_received"}, "2026-11-20"))
        self.refresh_snapshot()
        self.record["outreach"] = {"status": "not_contacted"}
        self.data["outreach_events"] = [{"case_id": "K-0001", "event_id": "e-outreach-1"},
                                        {"case_id": "K-0002", "event_id": "e-outreach-2"}]
        with self.assertRaisesRegex(release_safety.GuardError, "conflicts across its canonical cases"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_release_control_lists_every_registered_case_for_the_paper(self):
        self.registry["cases"].append({"id": "K-0002", "work": "W-0001"})
        dump(self.control / "01_Registry" / "records.json", self.registry)
        self.refresh_snapshot()
        with self.assertRaisesRegex(release_safety.GuardError, "must list every registered K case"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_new_open_record_integrates_manifest_canonical_hold_and_deployment_checks(self):
        subprocess.run(["git", "init", str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "guard-test@example.invalid"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Guard Test"], cwd=self.repo, check=True, capture_output=True)
        (self.repo / "README.md").write_text("synthetic baseline\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "synthetic deployed baseline"], cwd=self.repo, check=True, capture_output=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True,
                              capture_output=True, check=True).stdout.strip()

        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, base)
        (deployment_dir / "deployed.md").write_text(
            "<!-- ASSTATED_DEPLOYMENT_V1\n" + json.dumps(marker) + "\nASSTATED_DEPLOYMENT_V1 -->\n", encoding="utf-8")
        (self.control / "02_Cases" / "W-0001__synthetic" / "Publication").mkdir(parents=True)
        self.data["hold_review"] = {"checked_at": "2026-11-23T12:00:00+11:00", "inventory": []}

        synthetic_site = fixtures.make_project(build, self.tmp / "synthetic_site")
        config = json.loads((synthetic_site / "site.json").read_text(encoding="utf-8"))
        config["pages"]["statistics"] = False
        (synthetic_site / "site.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(synthetic_site / "content" / "published" / "snapshots")
        (synthetic_site / "content" / "published" / "updates.json").unlink()
        fixture_record_path = synthetic_site / "content" / "published" / "records" / "TEST-2000-019" / "v1.0.json"
        site_record = make_v3(json.loads(fixture_record_path.read_text(encoding="utf-8")))
        site_record["work"] = {"title": "Synthetic work", "authors": ["Author A", "Author B"],
                                "year": 2000, "venue": "Synthetic Journal", "volume": "1", "pages": "1-2",
                                "doi": "10.0000/synthetic"}
        site_record["claims"][0]["evidence"][0]["date"] = "2026-11-21"
        site_record["claims"][0]["evidence"][0]["session"] = "informed"
        build.validate_any(site_record, site_record["public_id"], site_record["version"])
        dump(fixture_record_path, site_record)
        fixtures.write_manifests(build, synthetic_site)
        build.Content("published", synthetic_site).load()
        record = dict(site_record)
        record["public_id"] = "TST-2000-001"
        build.validate_any(record, record["public_id"], record["version"])
        canonical_finding = {key: record["claims"][0]["result"][key]
                             for key in ("outcome", "defect_class", "affects", "depth")
                             if key in record["claims"][0]["result"]}
        finding_path = self.control / "01_Registry" / "events" / "e-finding.json"
        finding_event = json.loads(finding_path.read_text(encoding="utf-8"))
        finding_event["value"] = canonical_finding
        dump(finding_path, finding_event)
        self.registry["claims"][0]["kind"] = record["claims"][0]["kind"]
        self.registry["claims"][0]["role"] = record["claims"][0]["role"]
        dump(self.control / "01_Registry" / "records.json", self.registry)
        self.refresh_snapshot()
        self.data["claim_reviews"]["c1"]["evidence_event_ids"] = ["e-hostile"]
        record_path = self.repo / "content/published/records/TST-2000-001/v1.0.json"
        dump(record_path, record)
        manifest = self.repo / "content/published/releases/record__TST-2000-001__1.0.txt"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("\n".join(["as-stated-release v1", "kind: record", "id: TST-2000-001",
                                         "version: 1.0", f"sha256: {release_safety.sha256(record_path.read_bytes())}"]) + "\n",
                            encoding="utf-8")
        self.data["public_id"] = record["public_id"]
        self.data["record_version"] = record["version"]
        self.data["control_schema"] = 1
        self.data["record_sha256"] = release_safety.sha256(record_path.read_bytes())
        private_path = self.control / "04_Publication" / "Release_Records" / "TST-2000-001.md"
        private_path.parent.mkdir(parents=True)
        private_path.write_text("<!-- ASSTATED_RELEASE_CONTROL_V1\n" + json.dumps(self.data) +
                                "\nASSTATED_RELEASE_CONTROL_V1 -->\n", encoding="utf-8")

        release_safety.validate_new_records(
            self.repo, base,
            ["content/published/records/TST-2000-001/v1.0.json",
             "content/published/releases/record__TST-2000-001__1.0.txt"],
            self.control, deployment_dir)

        record["headline"] += " Edited after the release review."
        dump(record_path, record)
        manifest.write_text("\n".join(["as-stated-release v1", "kind: record", "id: TST-2000-001",
                                         "version: 1.0", f"sha256: {release_safety.sha256(record_path.read_bytes())}"]) + "\n",
                            encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "does not lock the exact public record bytes"):
            release_safety.validate_new_records(
                self.repo, base,
                ["content/published/records/TST-2000-001/v1.0.json",
                 "content/published/releases/record__TST-2000-001__1.0.txt"],
                self.control, deployment_dir)

    def test_active_owner_hold_blocks_standing_open_release(self):
        self.hold_root()
        hold = self.make_hold("discretionary")
        with self.assertRaisesRegex(release_safety.GuardError, "active owner hold blocks"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_status_provenance_only_does_not_bypass_active_hold(self):
        self.hold_root()
        self.make_hold("privacy")
        carried = {"public_id": "TA-TEST-001", "claims": [{"id": "c1",
                   "status_provenance": {"status": "unresolved", "revision_version": "1.1"},
                   "result": {"outcome": "unresolved"}}]}
        with self.assertRaisesRegex(release_safety.GuardError, "non-discretionary owner hold blocks"):
            release_safety.validate_holds(self.control, self.data, carried)

    def test_active_nondiscretionary_hold_blocks_an_initial_release(self):
        self.hold_root()
        self.make_hold("privacy")
        with self.assertRaisesRegex(release_safety.GuardError, "non-discretionary owner hold"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_owner_hold_marker_requires_reason_and_future_review_date(self):
        path = self.control / "02_Cases" / "W-0001__synthetic" / "Publication" / "hold.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {"actor": "owner", "action": "hold", "date": "2026-11-22", "work_ids": ["W-0001"],
                 "category": "discretionary"}
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value), encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "invalid shape or work scope"):
            release_safety.read_owner_note_marker(path, release_safety.OWNER_HOLD_MARKER,
                                                  release_safety.OWNER_HOLD_RE, "owner hold")
        value.update({"reason": "Synthetic hold reason.", "review_date": "2026-11-22"})
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value), encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "review date must follow"):
            release_safety.read_owner_note_marker(path, release_safety.OWNER_HOLD_MARKER,
                                                  release_safety.OWNER_HOLD_RE, "owner hold")

    def test_multi_case_owner_hold_applies_to_each_listed_case(self):
        self.hold_root()
        hold = self.make_hold("discretionary")
        path = self.control / Path(hold["path"])
        value = {"actor": "owner", "action": "hold", "date": "2026-11-22",
                 "work_ids": ["W-0001", "W-0002"], "category": "discretionary",
                 "reason": "Synthetic review hold.", "review_date": "2026-11-30"}
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value), encoding="utf-8")
        hold["sha256"] = release_safety.sha256(path.read_bytes())
        with self.assertRaisesRegex(release_safety.GuardError, "active owner hold blocks"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_explicit_case_publish_can_override_discretionary_hold(self):
        self.hold_root()
        hold = self.make_hold("discretionary")
        self.add_resolution(hold, "override_discretionary", "2026-11-23")
        self.data["claim_authorizations"]["c1"] = "case_publish"
        self.add_publish_instruction(self.record)
        self.data["release_checks"]["case_publish_instruction_verified"] = True
        release_safety.validate_release_checks(self.data, self.record)
        release_safety.validate_holds(self.control, self.data, self.record)

    def test_owner_cannot_override_a_nondiscretionary_hold(self):
        self.hold_root()
        hold = self.make_hold("privacy")
        self.add_resolution(hold, "override_discretionary", "2026-11-23")
        self.data["claim_authorizations"]["c1"] = "case_publish"
        self.add_publish_instruction(self.record)
        self.data["release_checks"]["case_publish_instruction_verified"] = True
        with self.assertRaisesRegex(release_safety.GuardError, "only a discretionary hold"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_unresolved_technical_refutation_blocks_initial_open(self):
        self.write_event(event("e-refutes", "W-0001.C1", "check",
                               {"run": "SYNTHETIC_REFUTATION", "checker": "ai", "session": "fresh_blind",
                                "method": "independent_code", "result": "refutes", "report": TEST_ARTIFACT_ID},
                               "2026-11-22"))
        self.refresh_snapshot()
        with self.assertRaisesRegex(release_safety.GuardError, "unreconciled technical refutation"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_status_correction_uses_standing_correction_without_publish_instruction(self):
        rec = {"public_id": "TA-TEST-001", "claims": [{"id": "c1", "publication_revision": {"to_status": "unresolved"},
                                                         "result": {"outcome": "unresolved"}}]}
        self.data["claim_authorizations"]["c1"] = "standing_correction"
        self.data["release_checks"] = {"canonical_review_complete": True, "rights_privacy_clear": True,
                                        "public_presentation_ready": True, "correction_evidence_reviewed": True,
                                        "current_status_and_scope_checked": True}
        self.assertNotIn("publish_instruction", self.data)
        release_safety.validate_release_checks(self.data, rec)

    def test_restored_confirmed_finding_keeps_standing_correction_authorization_but_needs_positive_gates(self):
        rec = {"public_id": "TA-TEST-001", "claims": [{"id": "c1",
               "publication_revision": {"from_version": "1.1", "from_status": "unresolved",
                                         "to_status": "confirmed", "prior_sha256": "a" * 64,
                                         "reason": "New evidence restores the former positive status."},
               "result": {"outcome": "defect_found", "status": "confirmed"}}]}
        self.data["claim_authorizations"]["c1"] = "standing_correction"
        self.data["release_checks"] = {"canonical_review_complete": True, "rights_privacy_clear": True,
                                        "public_presentation_ready": True, "correction_evidence_reviewed": True,
                                        "current_status_and_scope_checked": True,
                                        "initial_open_gates_complete": True}
        release_safety.validate_release_checks(self.data, rec)
        self.data["release_checks"].pop("initial_open_gates_complete")
        with self.assertRaisesRegex(release_safety.GuardError, "missing a required release check"):
            release_safety.validate_release_checks(self.data, rec)

    def test_noncorrective_carried_status_requires_case_specific_authorization(self):
        rec = {"public_id": "TA-TEST-001", "claims": [{"id": "c1",
                 "status_provenance": {"status": "rejected", "revision_version": "1.1"},
                 "result": {"outcome": "no_defect_found"}}]}
        self.data["claim_authorizations"]["c1"] = "standing_correction"
        self.data["release_checks"] = {"canonical_review_complete": True, "rights_privacy_clear": True,
                                        "public_presentation_ready": True}
        self.assertNotIn("publish_instruction", self.data)
        with self.assertRaisesRegex(release_safety.GuardError, "needs case-specific authorization"):
            release_safety.validate_release_checks(self.data, rec)
        self.data["claim_authorizations"]["c1"] = "case_publish"
        self.add_publish_instruction(rec)
        self.data["release_checks"]["case_publish_instruction_verified"] = True
        release_safety.validate_release_checks(self.data, rec)

    def test_confirmed_positive_keeps_case_publish_authorization(self):
        rec = {"public_id": "TA-TEST-002", "claims": [{"id": "c1", "result": {"outcome": "defect_found", "status": "confirmed"}}]}
        self.data["public_id"] = "TA-TEST-002"
        self.data["claim_authorizations"]["c1"] = "case_publish"
        self.add_publish_instruction(rec)
        self.data["release_checks"]["case_publish_instruction_verified"] = True
        release_safety.validate_release_checks(self.data, rec)
        self.data["claim_authorizations"]["c1"] = "standing_open"
        with self.assertRaisesRegex(release_safety.GuardError, "new Confirmed positives"):
            release_safety.validate_release_checks(self.data, rec)

    def test_negative_audit_keeps_case_publish_authorization(self):
        rec = {"public_id": "TA-TEST-003", "claims": [{"id": "c1", "result": {"outcome": "no_defect_found"}}]}
        self.data["public_id"] = "TA-TEST-003"
        self.data["claim_authorizations"]["c1"] = "case_publish"
        self.add_publish_instruction(rec)
        self.data["release_checks"]["case_publish_instruction_verified"] = True
        release_safety.validate_release_checks(self.data, rec)
        self.data["claim_authorizations"]["c1"] = "standing_open"
        with self.assertRaisesRegex(release_safety.GuardError, "new Confirmed positives and negative audits"):
            release_safety.validate_release_checks(self.data, rec)

    def test_canonical_snapshot_change_after_review_blocks_release(self):
        changed = event("e-status-2", "W-0001.C1", "candidate_status", {"status": "rejected"}, "2026-11-23")
        self.write_event(changed)
        with self.assertRaisesRegex(release_safety.GuardError, "differ from the latest applied changeset receipt"):
            release_safety.validate_canonical(self.control, self.data, self.record)

    def test_conflicting_current_canonical_status_events_fail_closed(self):
        first = event("e-status-open", "W-0001.C1", "candidate_status", {"status": "open"})
        second = event("e-status-rejected", "W-0001.C1", "candidate_status", {"status": "rejected"})
        with self.assertRaisesRegex(release_safety.GuardError, "canonical events conflict"):
            release_safety.latest_event([first, second], "W-0001.C1", "candidate_status")

    def test_hold_inventory_covers_case_and_global_review_notes(self):
        self.hold_root()
        review = self.data["hold_review"]
        review["inventory"] = review["inventory"][:1]
        with self.assertRaisesRegex(release_safety.GuardError, "added, removed or left unclassified"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_global_hold_for_another_paper_is_explicitly_not_applicable(self):
        self.hold_root()
        path = self.control / "04_Publication" / "Reviews" / "review.md"
        value = {"actor": "owner", "action": "hold", "date": "2026-11-22", "work_ids": ["W-0002"],
                 "category": "privacy", "reason": "Synthetic hold for another paper.", "review_date": "2026-11-30"}
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value), encoding="utf-8")
        item = next(entry for entry in self.data["hold_review"]["inventory"]
                    if entry["path"] == "04_Publication/Reviews/review.md")
        item.update({"disposition": "not_applicable", "category": "privacy",
                     "sha256": release_safety.sha256(path.read_bytes())})
        release_safety.validate_holds(self.control, self.data, self.record)

    def test_not_applicable_note_cannot_add_broad_free_text_hold(self):
        self.hold_root()
        path = self.control / "04_Publication" / "Reviews" / "review.md"
        value = {"actor": "owner", "action": "hold", "date": "2026-11-22", "work_ids": ["W-0002"],
                 "category": "privacy", "reason": "Synthetic hold for another paper.", "review_date": "2026-11-30"}
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value) +
                        "Hold W-0002 and all other paper releases.\n", encoding="utf-8")
        item = next(entry for entry in self.data["hold_review"]["inventory"]
                    if entry["path"] == "04_Publication/Reviews/review.md")
        item.update({"disposition": "not_applicable", "category": "privacy",
                     "sha256": release_safety.sha256(path.read_bytes())})
        with self.assertRaisesRegex(release_safety.GuardError, "broader than its disjoint owner scope"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_not_applicable_hold_must_exclude_the_current_paper(self):
        self.hold_root()
        path = self.control / "04_Publication" / "Reviews" / "review.md"
        value = {"actor": "owner", "action": "hold", "date": "2026-11-22", "work_ids": ["W-0001", "W-0002"],
                 "category": "privacy", "reason": "Synthetic hold for two papers.", "review_date": "2026-11-30"}
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value), encoding="utf-8")
        item = next(entry for entry in self.data["hold_review"]["inventory"]
                    if entry["path"] == "04_Publication/Reviews/review.md")
        item.update({"disposition": "not_applicable", "category": "privacy",
                     "sha256": release_safety.sha256(path.read_bytes())})
        with self.assertRaisesRegex(release_safety.GuardError, "scoped to different papers"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_lifted_hold_needs_a_later_same_work_resolution_note(self):
        self.hold_root()
        hold = self.make_hold("discretionary", disposition="lifted")
        self.add_resolution(hold, "lift", "2026-11-23")
        release_safety.validate_holds(self.control, self.data, self.record)
        hold["resolution_work_ids"] = ["W-9999"]
        with self.assertRaisesRegex(release_safety.GuardError, "same public paper"):
            release_safety.validate_holds(self.control, self.data, self.record)

    def test_unresolved_only_new_record_is_not_authorized_as_context(self):
        rec = {"public_id": "TA-TEST-004", "claims": [{"id": "c1", "result": {"outcome": "unresolved"}}]}
        self.data["claim_authorizations"]["c1"] = "standing_open"
        with self.assertRaisesRegex(release_safety.GuardError, "explicitly authorized as context only"):
            release_safety.validate_release_checks(self.data, rec)

    def test_current_deployment_requires_the_latest_passing_live_audit_record(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        with self.assertRaisesRegex(release_safety.GuardError, "no machine-readable deployment record"):
            release_safety.current_deployment(deployment_dir)
        marker = deployment_marker(deployment_dir, "a" * 40, live_audit="FAIL")
        body = "<!-- ASSTATED_DEPLOYMENT_V1\n" + json.dumps(marker) + "\nASSTATED_DEPLOYMENT_V1 -->\n"
        (deployment_dir / "deployment.md").write_text(body, encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "does not have a passing live-site audit"):
            release_safety.current_deployment(deployment_dir)

    def test_deployment_evidence_must_use_the_selected_control_root(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        other_root = self.tmp / "other-control"
        other_root.mkdir()
        with self.assertRaisesRegex(release_safety.GuardError, "exactly the selected control root"):
            release_safety.current_deployment(deployment_dir, other_root)

    def test_deployment_marker_requires_audit_evidence_to_say_pass(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, "a" * 40, live_audit="PASS")
        evidence_path = deployment_dir / marker["audit_evidence"]["path"]
        evidence_bytes = b"synthetic audit\nRESULT: FAIL\n"
        evidence_path.write_bytes(evidence_bytes)
        marker["audit_evidence"]["sha256"] = release_safety.sha256(evidence_bytes)
        (deployment_dir / "deployment.md").write_text(
            marker_note(release_safety.DEPLOYMENT_MARKER, marker), encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "exactly RESULT: PASS"):
            release_safety.current_deployment(deployment_dir)

    def test_duplicate_deployment_marker_blocks(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, "a" * 40)
        block = marker_note(release_safety.DEPLOYMENT_MARKER, marker)
        (deployment_dir / "deployment.md").write_text(block + block, encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "duplicate marker blocks"):
            release_safety.current_deployment(deployment_dir)

    def test_unexpected_private_release_record_invalidates_release_control_freshness(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, "a" * 40)
        private_records = self.control / "04_Publication" / "Release_Records"
        private_records.mkdir(parents=True)
        (private_records / "new-review.md").write_text("synthetic private review\n", encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "changes do not match"):
            release_safety.validate_release_control_freshness(self.control, marker, [])

    def test_conflicting_latest_deployment_evidence_fails_closed(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        for name, commit, run_id in (("first.md", "a" * 40, "SYNTHETIC-ONE"), ("second.md", "b" * 40, "SYNTHETIC-TWO")):
            marker = deployment_marker(deployment_dir, commit, run_id=run_id)
            body = "<!-- ASSTATED_DEPLOYMENT_V1\n" + json.dumps(marker) + "\nASSTATED_DEPLOYMENT_V1 -->\n"
            (deployment_dir / name).write_text(body, encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "deployment evidence is ambiguous"):
            release_safety.current_deployment(deployment_dir)

    def test_deployment_requires_unchanged_hashed_audit_evidence(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, "a" * 40)
        (deployment_dir / "deployment.md").write_text(
            "<!-- ASSTATED_DEPLOYMENT_V1\n" + json.dumps(marker) + "\nASSTATED_DEPLOYMENT_V1 -->\n", encoding="utf-8")
        (deployment_dir / "audits" / "SYNTHETIC-DEPLOY.txt").write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "changed after the deployment record"):
            release_safety.current_deployment(deployment_dir)

    def test_deployment_requires_unchanged_private_release_control_inventory(self):
        private_root = self.control / "04_Publication" / "Release_Records"
        private_root.mkdir(parents=True)
        private_note = private_root / "synthetic-review.md"
        private_note.write_text("synthetic release review\n", encoding="utf-8")
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, "a" * 40)
        (deployment_dir / "deployment.md").write_text(
            marker_note(release_safety.DEPLOYMENT_MARKER, marker), encoding="utf-8")
        private_note.write_text("changed synthetic release review\n", encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "private release record used by the deployment changed"):
            release_safety.current_deployment(deployment_dir)

    def test_newer_unmarked_deployment_report_invalidates_current_state(self):
        deployment_dir = self.control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, "a" * 40, verified_at="2026-11-22T12:00:00+11:00")
        (deployment_dir / "2026-11-22__DEPLOYMENT_VERIFIED.md").write_text(
            "<!-- ASSTATED_DEPLOYMENT_V1\n" + json.dumps(marker) + "\nASSTATED_DEPLOYMENT_V1 -->\n", encoding="utf-8")
        (deployment_dir / "2026-11-23__DEPLOYMENT_FAILED.md").write_text("Deployment did not complete.\n", encoding="utf-8")
        with self.assertRaisesRegex(release_safety.GuardError, "newer dated deployment or live-audit report"):
            release_safety.current_deployment(deployment_dir)

    def test_generic_hold_does_not_suppress_a_required_correction(self):
        self.hold_root()
        self.make_hold("privacy")
        correction = {"public_id": "TA-TEST-001", "claims": [{"id": "c1", "publication_revision": {"to_status": "unresolved"},
                                                                   "result": {"outcome": "unresolved"}}]}
        self.data["claim_authorizations"]["c1"] = "standing_correction"
        release_safety.validate_holds(self.control, self.data, correction)

    def test_mixed_correction_and_new_open_claim_does_not_bypass_an_active_hold(self):
        self.hold_root()
        self.make_hold("discretionary")
        record = {"public_id": "TA-TEST-001", "claims": [
            {"id": "c1", "publication_revision": {"to_status": "unresolved"},
             "result": {"outcome": "unresolved"}},
            {"id": "c2", "result": {"outcome": "defect_found", "status": "open"}},
        ]}
        with self.assertRaisesRegex(release_safety.GuardError, "active owner hold blocks"):
            release_safety.validate_holds(self.control, self.data, record)

    def test_mixed_correction_and_new_open_claim_needs_publish_to_override_hold(self):
        self.hold_root()
        hold = self.make_hold("discretionary", disposition="overridden_for_this_release")
        self.add_resolution(hold, "override_discretionary", "2026-11-23")
        record = {"public_id": "TA-TEST-001", "claims": [
            {"id": "c1", "publication_revision": {"to_status": "unresolved"},
             "result": {"outcome": "unresolved"}},
            {"id": "c2", "result": {"outcome": "defect_found", "status": "open"}},
        ]}
        with self.assertRaisesRegex(release_safety.GuardError, "case-specific owner publish instruction"):
            release_safety.validate_holds(self.control, self.data, record)

    def test_correction_suppression_requires_a_later_owner_instruction(self):
        self.hold_root()
        hold = self.make_hold("correction_suppression", disposition="correction_suppression")
        correction = {"public_id": "TA-TEST-001", "claims": [{"id": "c1", "publication_revision": {"to_status": "unresolved"},
                                                                   "result": {"outcome": "unresolved"}}]}
        self.data["claim_authorizations"]["c1"] = "standing_correction"
        with self.assertRaisesRegex(release_safety.GuardError, "later owner instruction"):
            release_safety.validate_holds(self.control, self.data, correction)
        self.add_resolution(hold, "authorize_correction", "2026-11-23")
        release_safety.validate_holds(self.control, self.data, correction)

    def hold_root(self):
        pub = self.control / "02_Cases" / "W-0001__synthetic" / "Publication"
        reviews = self.control / "04_Publication" / "Reviews"
        pub.mkdir(parents=True, exist_ok=True)
        reviews.mkdir(parents=True, exist_ok=True)
        (pub / "hold.md").write_text("Synthetic case publication review.\n", encoding="utf-8")
        (reviews / "review.md").write_text("Synthetic global review note.\n", encoding="utf-8")
        inventory = []
        for path in sorted([pub / "hold.md", reviews / "review.md"]):
            inventory.append({"path": path.relative_to(self.control).as_posix(),
                              "sha256": release_safety.sha256(path.read_bytes()), "disposition": "no_hold"})
        self.data["hold_review"] = {"checked_at": "2026-11-23T12:00:00+11:00", "inventory": inventory}

    def inventory_note(self, path, disposition="no_hold"):
        rel = path.relative_to(self.control).as_posix()
        item = {"path": rel, "sha256": release_safety.sha256(path.read_bytes()), "disposition": disposition}
        inventory = self.data["hold_review"]["inventory"]
        existing = next((entry for entry in inventory if entry["path"] == rel), None)
        if existing is None:
            inventory.append(item)
        else:
            existing.clear()
            existing.update(item)
        return next(entry for entry in inventory if entry["path"] == rel)

    def make_hold(self, category, disposition="active_hold"):
        path = self.control / "02_Cases" / "W-0001__synthetic" / "Publication" / "hold.md"
        action = "correction_suppression" if category == "correction_suppression" else "hold"
        value = {"actor": "owner", "action": action, "date": "2026-11-22", "work_ids": ["W-0001"],
                 "category": category, "reason": "Synthetic review hold.", "review_date": "2026-11-30"}
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value), encoding="utf-8")
        item = self.inventory_note(path, disposition)
        item.update({"recorded_date": "2026-11-22"})
        if action == "hold":
            item["category"] = category
        return item

    def add_resolution(self, hold, action, date):
        path = self.control / "04_Publication" / "Reviews" / "review.md"
        value = {"actor": "owner", "action": action, "date": date, "work_ids": ["W-0001"],
                 "target_path": hold["path"], "target_sha256": hold["sha256"]}
        path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, value), encoding="utf-8")
        self.inventory_note(path)
        if action == "override_discretionary":
            hold["disposition"] = "overridden_for_this_release"
        elif action == "lift":
            hold["disposition"] = "lifted"
        hold.update({"resolution_path": path.relative_to(self.control).as_posix(), "resolution_date": date,
                     "resolution_work_ids": ["W-0001"]})

    def add_publish_instruction(self, record):
        path = self.control / "02_Cases" / "W-0001__synthetic" / "Publication" / "publish.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.data.setdefault("hold_review", {"checked_at": "2026-11-23T12:00:00+11:00", "inventory": []})
        self.data.setdefault("record_sha256", "a" * 64)
        value = {"actor": "owner", "instruction": "publish", "date": "2026-11-23",
                 "public_id": record["public_id"], "version": record.get("version", self.record["version"]),
                 "case_ids": ["K-0001"], "record_sha256": self.data["record_sha256"]}
        path.write_text(marker_note(release_safety.OWNER_PUBLISH_MARKER, value), encoding="utf-8")
        rel = path.relative_to(self.control).as_posix()
        digest = release_safety.sha256(path.read_bytes())
        self.data["publish_instruction"] = {"date": "2026-11-23", "source_path": rel, "source_sha256": digest}
        self.inventory_note(path)

    def test_negated_text_cannot_be_used_as_owner_publish_authorization(self):
        self.data["claim_authorizations"]["c1"] = "case_publish"
        self.data["public_id"] = self.record["public_id"]
        self.add_publish_instruction(self.record)
        path = self.control / Path(self.data["publish_instruction"]["source_path"])
        path.write_text(path.read_text(encoding="utf-8") + "Owner note: do not publish.\n", encoding="utf-8")
        self.data["publish_instruction"]["source_sha256"] = release_safety.sha256(path.read_bytes())
        with self.assertRaisesRegex(release_safety.GuardError, "conflicting hold or negation"):
            release_safety.validate_owner_publish_instruction(
                self.control, self.data, self.record, release_safety.current_hold_notes(self.control, ["W-0001"]))

    def test_owner_publish_instruction_binds_exact_public_record_bytes(self):
        self.hold_root()
        self.data["record_sha256"] = "a" * 64
        self.add_publish_instruction(self.record)
        actual = release_safety.current_hold_notes(self.control, ["W-0001"])
        release_safety.validate_owner_publish_instruction(self.control, self.data, self.record, actual)
        self.data["record_sha256"] = "b" * 64
        with self.assertRaisesRegex(release_safety.GuardError, "exact record and cases"):
            release_safety.validate_owner_publish_instruction(self.control, self.data, self.record, actual)


class GitSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="as_git_guard_"))
        self.repo = self.tmp / "repo"
        self.remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", str(self.repo)], check=True, capture_output=True)
        self.git("config", "user.email", "guard-test@example.invalid")
        self.git("config", "user.name", "Guard Test")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "base")
        self.git("branch", "-M", "main")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        subprocess.run(["git", "--git-dir", str(self.remote), "symbolic-ref", "HEAD", "refs/heads/main"],
                       check=True, capture_output=True)
        self.base = self.git("rev-parse", "HEAD")

    def tearDown(self):
        def clear_readonly(func, path, exc):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        shutil.rmtree(self.tmp, onexc=clear_readonly)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, text=True, capture_output=True, check=True).stdout.strip()

    def test_stale_checkout_cannot_pass_pre_push(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", str(self.remote), str(other)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "guard-test@example.invalid"], cwd=other, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Guard Test"], cwd=other, check=True, capture_output=True)
        (other / "README.md").write_text("advanced\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=other, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "advance remote"], cwd=other, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=other, check=True, capture_output=True)
        with self.assertRaisesRegex(release_safety.GuardError, "stale or divergent"):
            release_safety.pre_push(self.repo, "origin", "main", None, None)

    def test_pre_push_requires_verified_deployment_for_code_only_change(self):
        old_history_check = release_safety.check_public_history
        release_safety.check_public_history = lambda repo, head: None
        control = self.tmp / "control"
        deployment_dir = control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        try:
            with self.assertRaisesRegex(release_safety.GuardError, "no machine-readable deployment record"):
                release_safety.pre_push(self.repo, "origin", "main", control, deployment_dir)
        finally:
            release_safety.check_public_history = old_history_check

    def test_pre_push_runs_a_fresh_live_audit_for_code_only_changes(self):
        old_history_check = release_safety.check_public_history
        release_safety.check_public_history = lambda repo, head: None
        control = self.tmp / "control"
        deployment_dir = control / "05_Website" / "Deployment"
        deployment_dir.mkdir(parents=True)
        marker = deployment_marker(deployment_dir, self.base)
        (deployment_dir / "deployment.md").write_text(
            marker_note(release_safety.DEPLOYMENT_MARKER, marker), encoding="utf-8")
        audit_script = deployment_dir / "live_site_audit.py"
        audit_script.write_text("print('RESULT: PASS')\n", encoding="utf-8")
        try:
            self.assertEqual(release_safety.pre_push(self.repo, "origin", "main", control, deployment_dir), self.base)
            audit_script.write_text("print('RESULT: FAIL')\n", encoding="utf-8")
            with self.assertRaisesRegex(release_safety.GuardError, "on-demand live-site audit did not return"):
                release_safety.pre_push(self.repo, "origin", "main", control, deployment_dir)
        finally:
            release_safety.check_public_history = old_history_check

    def test_existing_public_json_and_manifest_cannot_be_rewritten_together(self):
        json_path = self.repo / "content/published/records/TA-TEST-001/v1.0.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text("{}\n", encoding="utf-8")
        manifest = self.repo / "content/published/releases/record__TA-TEST-001__1.0.txt"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("old\n", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "public base")
        base = self.git("rev-parse", "HEAD")
        json_path.write_text("{\"changed\": true}\n", encoding="utf-8")
        manifest.write_text("new manifest\n", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "attempt rewrite")
        with self.assertRaisesRegex(release_safety.GuardError, "public path is immutable"):
            release_safety.check_append_only(self.repo, base)

    def test_unrecognized_public_path_is_refused(self):
        path = self.repo / "content/published/records/TA-TEST-001/private-note.txt"
        path.parent.mkdir(parents=True)
        path.write_text("synthetic", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "unrecognized public path")
        with self.assertRaisesRegex(release_safety.GuardError, "unrecognized path under content/published"):
            release_safety.check_append_only(self.repo, self.base)

    def test_published_channel_operational_readme_is_not_a_release_artifact(self):
        path = self.repo / "content/published/README.txt"
        path.parent.mkdir(parents=True)
        path.write_text("Operational instructions only; not copied by the site builder.\n", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "add operational readme for synthetic test")
        base = self.git("rev-parse", "HEAD")
        path.write_text("Updated operational instructions.\n", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "update operational readme")
        changes = release_safety.check_append_only(self.repo, base)
        self.assertEqual(changes, ["content/published/README.txt"])

    def test_public_version_must_advance_latest_published_version(self):
        path = self.repo / "content/published/records/TA-TEST-001/v2.0.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "published version two")
        base = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(release_safety.GuardError, "must advance the latest published version"):
            release_safety.validate_version_monotonicity(self.repo, base, [("TA-TEST-001", "1.9")])
        release_safety.validate_version_monotonicity(self.repo, base, [("TA-TEST-001", "2.1")])

    def test_duplicate_versions_in_one_publication_batch_are_blocked(self):
        with self.assertRaisesRegex(release_safety.GuardError, "repeats a version"):
            release_safety.validate_version_monotonicity(
                self.repo, self.base, [("TA-TEST-001", "1.0"), ("TA-TEST-001", "1.0")])

    def test_statistics_snapshot_addition_fails_closed(self):
        path = self.repo / "content/published/snapshots/2026-11.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "unsupported snapshot release")
        with self.assertRaisesRegex(release_safety.GuardError, "statistics snapshots are fail-closed"):
            release_safety.check_append_only(self.repo, self.base)

    def test_history_guard_catches_failed_rewrite_after_harmless_followup(self):
        public = self.repo / "content/published/records/TA-TEST-001/v1.0.json"
        manifest = self.repo / "content/published/releases/record__TA-TEST-001__1.0.txt"
        public.parent.mkdir(parents=True)
        manifest.parent.mkdir(parents=True)
        data = b'{"public_id":"TA-TEST-001","version":"1.0"}\n'
        public.write_bytes(data)
        manifest.write_text("\n".join(["as-stated-release v1", "kind: record", "id: TA-TEST-001",
                                         "version: 1.0", f"sha256: {release_safety.sha256(data)}"]) + "\n",
                            encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "public release")
        public.write_bytes(b'{"public_id":"TA-TEST-001","version":"1.0","rewritten":true}\n')
        manifest.write_text("rewritten\n", encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "bad rewrite that fails CI")
        (self.repo / "README.md").write_text("harmless follow-up\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "harmless follow-up")
        with self.assertRaisesRegex(release_safety.GuardError, "public path is immutable"):
            release_safety.check_public_history(self.repo, self.git("rev-parse", "HEAD"), self.base)

    def test_correction_requires_exact_prior_version_in_verified_deployment(self):
        public_id, version = "TA-TEST-001", "1.0"
        prior = {"public_id": public_id, "version": version, "schema": 2, "work": {"doi": "10.0000/test"},
                 "claims": [{"id": "c1", "result": {"outcome": "defect_found", "status": "open"}}]}
        prior_path = self.repo / "content/published/records" / public_id / "v1.0.json"
        dump(prior_path, prior)
        prior_bytes = prior_path.read_bytes()
        manifest = self.repo / "content/published/releases" / f"record__{public_id}__{version}.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("\n".join(["as-stated-release v1", "kind: record", f"id: {public_id}",
                                         f"version: {version}", f"sha256: {release_safety.sha256(prior_bytes)}"]) + "\n",
                            encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "verified public baseline")
        baseline = self.git("rev-parse", "HEAD")
        current = {"public_id": public_id, "version": "1.1", "work": prior["work"],
                   "claims": [{"id": "c1", "publication_revision": {"from_version": "1.0", "from_status": "open",
                                                                       "to_status": "unresolved",
                                                                       "prior_sha256": release_safety.sha256(prior_bytes)},
                               "result": {"outcome": "unresolved"}}]}
        release_safety.validate_correction_bases(self.repo, baseline, {"source_commit": baseline}, current)

    def test_corrective_version_with_unchanged_prior_claims_uses_correction_hold_exception(self):
        public_id, version = "TA-TEST-001", "1.0"
        work = {"doi": "10.0000/test"}
        prior = {"public_id": public_id, "version": version, "schema": 2, "work": work,
                 "kind": "defect", "headline": "The paper contains the stated defect.",
                 "outreach": {"status": "not_contacted"},
                 "history": [{"version": "1.0", "change": "Initial release."}],
                 "versions": [{"version": "1.0", "change": "Initial release."}],
                 "changelog": [{"version": "1.0", "change": "Initial release."}],
                 "claims": [{"id": "c1", "result": {"outcome": "defect_found", "status": "open"}},
                            {"id": "c2", "statement": "Lemma B as originally published.",
                             "result": {"outcome": "defect_found", "status": "open"}}]}
        prior_path = self.repo / "content/published/records" / public_id / "v1.0.json"
        dump(prior_path, prior)
        prior_bytes = prior_path.read_bytes()
        manifest = self.repo / "content/published/releases" / f"record__{public_id}__{version}.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("\n".join(["as-stated-release v1", "kind: record", f"id: {public_id}",
                                         f"version: {version}", f"sha256: {release_safety.sha256(prior_bytes)}"]) + "\n",
                            encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "verified public baseline")
        baseline = self.git("rev-parse", "HEAD")
        current = {"public_id": public_id, "version": "1.1", "schema": 3, "work": work,
                   "kind": "status_correction", "headline": "The former defect finding is now unresolved.",
                   "outreach": {"status": "not_contacted"},
                   "history": prior["history"] + [{"version": "1.1", "change": "Corrected status."}],
                   "versions": prior["versions"] + [{"version": "1.1", "change": "Corrected status."}],
                   "changelog": prior["changelog"] + [{"version": "1.1", "revision_type": "superseding_evidence",
                                                       "change": "Corrected status."}],
                   "claims": [{"id": "c1", "publication_revision": {"from_version": "1.0", "from_status": "open",
                                                                           "to_status": "unresolved",
                                                                           "prior_sha256": release_safety.sha256(prior_bytes)},
                               "result": {"outcome": "unresolved"}},
                              prior["claims"][1]]}
        prior_claim_ids = release_safety.validate_correction_bases(
            self.repo, baseline, {"source_commit": baseline}, current)
        self.assertEqual(prior_claim_ids, {"c1", "c2"})
        materially_changed = json.loads(json.dumps(current))
        materially_changed["claims"][1]["statement"] = "Lemma B with a materially narrower condition."
        with self.assertRaisesRegex(release_safety.GuardError, "changed scientific content without publication_revision"):
            release_safety.validate_correction_bases(
                self.repo, baseline, {"source_commit": baseline}, materially_changed)
        with_updated_author_position = json.loads(json.dumps(current))
        with_updated_author_position["claims"][1]["author_response"] = {"position": "disagrees"}
        self.assertEqual(release_safety.validate_correction_bases(
            self.repo, baseline, {"source_commit": baseline}, with_updated_author_position), {"c1", "c2"})

        control = self.tmp / "control"
        hold_path = control / "02_Cases" / "W-0001" / "Publication" / "hold.md"
        hold = {"actor": "owner", "action": "hold", "date": "2026-11-22", "work_ids": ["W-0001"],
                "category": "privacy", "reason": "Synthetic general hold.", "review_date": "2026-11-30"}
        hold_path.parent.mkdir(parents=True)
        hold_path.write_text(marker_note(release_safety.OWNER_HOLD_MARKER, hold), encoding="utf-8")
        inventory = [{"path": hold_path.relative_to(control).as_posix(),
                      "sha256": release_safety.sha256(hold_path.read_bytes()), "disposition": "active_hold",
                      "category": "privacy", "recorded_date": "2026-11-22"}]
        release_control = {"case_ids": ["W-0001"],
                           "hold_review": {"checked_at": "2026-11-23T12:00:00+11:00", "inventory": inventory}}
        held_data = {"record_sha256": "a" * 64,
                     "held_correction_review": {"review_complete": True, "record_sha256": "a" * 64,
                                                "necessary_fields": ["headline", "kind"],
                                                "rationale": "The prior public headline and derived record kind do not state the corrected unresolved status."}}
        current_claim_ids = {claim["id"] for claim in current["claims"]}
        self.assertTrue(release_safety.validate_holds(
            control, release_control, current, current_claim_ids - prior_claim_ids))
        release_safety.validate_held_correction_projection(self.repo, {"source_commit": baseline}, current, held_data)
        for field, value in (("author_response", {"position": "disagrees"}),
                             ("evidence", ["synthetic-new-evidence"]),
                             ("vor_check", {"result": "complete"})):
            changed = json.loads(json.dumps(current))
            changed["claims"][1][field] = value
            with self.assertRaisesRegex(release_safety.GuardError, "active owner hold blocks a bundled"):
                release_safety.validate_held_correction_projection(
                    self.repo, {"source_commit": baseline}, changed, held_data)
        changed_outreach = json.loads(json.dumps(current))
        changed_outreach["outreach"] = {"status": "awaiting_substantive_response"}
        with self.assertRaisesRegex(release_safety.GuardError, "active owner hold blocks a bundled outreach"):
            release_safety.validate_held_correction_projection(
                self.repo, {"source_commit": baseline}, changed_outreach, held_data)
        factual_correction = json.loads(json.dumps(current))
        self.assertIsNone(release_safety.validate_held_correction_projection(
            self.repo, {"source_commit": baseline}, factual_correction, held_data))
        changed_history = json.loads(json.dumps(current))
        changed_history["changelog"][0]["change"] = "Rewritten prior history."
        with self.assertRaisesRegex(release_safety.GuardError, "edits to the prior public changelog"):
            release_safety.validate_held_correction_projection(
                self.repo, {"source_commit": baseline}, changed_history, held_data)
        changed_headline = json.loads(json.dumps(current))
        changed_headline["headline"] = "A broader new public claim."
        with self.assertRaisesRegex(release_safety.GuardError, "updated headline under an active hold"):
            release_safety.validate_held_correction_projection(
                self.repo, {"source_commit": baseline}, changed_headline, held_data)
        changed_correction_note = json.loads(json.dumps(current))
        changed_correction_note["correction"] = {"note": "Unreviewed source text."}
        with self.assertRaisesRegex(release_safety.GuardError, "fixed public wording"):
            release_safety.validate_held_correction_projection(
                self.repo, {"source_commit": baseline}, changed_correction_note, held_data)

    def test_correction_bases_allow_retiring_context_only_when_its_anchor_turns_nonpositive(self):
        public_id = "TA-TEST-001"
        work = {"doi": "10.0000/test"}
        prior = {"public_id": public_id, "version": "1.0", "schema": 3, "work": work,
                 "claims": [{"id": "c1", "result": {"outcome": "defect_found", "status": "open"}},
                            {"id": "c2", "role": "secondary", "unresolved_context": {"anchor_claim_id": "c1"},
                             "result": {"outcome": "unresolved"}}]}
        prior_path = self.repo / "content/published/records" / public_id / "v1.0.json"
        dump(prior_path, prior)
        prior_bytes = prior_path.read_bytes()
        manifest = self.repo / "content/published/releases" / f"record__{public_id}__1.0.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("\n".join(["as-stated-release v1", "kind: record", f"id: {public_id}",
                                         "version: 1.0", f"sha256: {release_safety.sha256(prior_bytes)}"]) + "\n",
                            encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "verified baseline with contextual claim")
        deployed = self.git("rev-parse", "HEAD")
        current = {"public_id": public_id, "version": "1.1", "schema": 3, "work": work,
                   "claims": [{"id": "c1", "publication_revision": {
                       "from_version": "1.0", "from_status": "open", "to_status": "unresolved",
                       "prior_sha256": release_safety.sha256(prior_bytes)},
                       "result": {"outcome": "unresolved"}}]}
        result = release_safety.validate_correction_bases(
            self.repo, deployed, {"source_commit": deployed}, current)
        self.assertEqual(result, {"c1", "c2"})
        still_positive = json.loads(json.dumps(current))
        still_positive["claims"][0]["publication_revision"]["to_status"] = "open"
        still_positive["claims"][0]["result"] = {"outcome": "defect_found", "status": "open"}
        with self.assertRaisesRegex(release_safety.GuardError, "cannot remove a previously public claim"):
            release_safety.validate_correction_bases(
                self.repo, deployed, {"source_commit": deployed}, still_positive)

    def test_corrected_claim_can_carry_forward_after_a_later_correction(self):
        public_id = "TA-TEST-001"
        work = {"doi": "10.0000/test"}
        prior = {"public_id": public_id, "version": "1.0", "schema": 2, "work": work,
                 "claims": [{"id": "c1", "statement": "Claim A.",
                             "result": {"outcome": "defect_found", "status": "open"}},
                            {"id": "c2", "statement": "Claim B.",
                             "result": {"outcome": "defect_found", "status": "open"}}]}

        def add_public_version(record):
            path = self.repo / "content/published/records" / public_id / f"v{record['version']}.json"
            dump(path, record)
            raw = path.read_bytes()
            manifest = self.repo / "content/published/releases" / f"record__{public_id}__{record['version']}.txt"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text("\n".join(["as-stated-release v1", "kind: record", f"id: {public_id}",
                                             f"version: {record['version']}",
                                             f"sha256: {release_safety.sha256(raw)}"]) + "\n", encoding="utf-8")
            self.git("add", "content")
            self.git("commit", "-m", f"public version {record['version']}")
            return raw

        prior_bytes = add_public_version(prior)
        first_correction = {"public_id": public_id, "version": "1.1", "schema": 3, "work": work,
                            "claims": [{"id": "c1", "statement": "Claim A.",
                                        "publication_revision": {"from_version": "1.0", "from_status": "open",
                                                                 "to_status": "unresolved",
                                                                 "prior_sha256": release_safety.sha256(prior_bytes)},
                                        "result": {"outcome": "unresolved"}},
                                       prior["claims"][1]]}
        first_correction_bytes = add_public_version(first_correction)
        baseline = self.git("rev-parse", "HEAD")
        second_correction = {"public_id": public_id, "version": "1.2", "schema": 3, "work": work,
                             "claims": [
                                 {"id": "c1", "statement": "Claim A.",
                                  "status_provenance": {"status": "unresolved", "revision_version": "1.1"},
                                  "result": {"outcome": "unresolved"}},
                                 {"id": "c2", "statement": "Claim B.",
                                  "publication_revision": {"from_version": "1.1", "from_status": "open",
                                                           "to_status": "unresolved",
                                                           "prior_sha256": release_safety.sha256(first_correction_bytes)},
                                  "result": {"outcome": "unresolved"}},
                             ]}
        self.assertEqual(release_safety.validate_correction_bases(
            self.repo, baseline, {"source_commit": baseline}, second_correction), {"c1", "c2"})

    def test_correction_prior_only_in_base_but_not_live_deployment_is_blocked(self):
        deployed = self.base
        public_id = "TA-TEST-001"
        prior = {"public_id": public_id, "version": "1.0", "schema": 2, "work": {"doi": "10.0000/test"},
                 "claims": [{"id": "c1", "result": {"outcome": "defect_found", "status": "open"}}]}
        prior_path = self.repo / "content/published/records" / public_id / "v1.0.json"
        dump(prior_path, prior)
        prior_bytes = prior_path.read_bytes()
        manifest = self.repo / "content/published/releases" / f"record__{public_id}__1.0.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("\n".join(["as-stated-release v1", "kind: record", f"id: {public_id}",
                                         "version: 1.0", f"sha256: {release_safety.sha256(prior_bytes)}"]) + "\n",
                            encoding="utf-8")
        self.git("add", "content")
        self.git("commit", "-m", "not yet deployed public version")
        base = self.git("rev-parse", "HEAD")
        current = {"public_id": public_id, "version": "1.1", "work": prior["work"],
                   "claims": [{"id": "c1", "publication_revision": {"from_version": "1.0", "from_status": "open",
                                                                       "to_status": "unresolved",
                                                                       "prior_sha256": release_safety.sha256(prior_bytes)},
                               "result": {"outcome": "unresolved"}}]}
        with self.assertRaisesRegex(release_safety.GuardError, "latest public version in the verified live deployment"):
            release_safety.validate_correction_bases(self.repo, base, {"source_commit": deployed}, current)


if __name__ == "__main__":
    unittest.main()
