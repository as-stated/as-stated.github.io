import json
import copy
import tempfile
import unittest
from pathlib import Path

import build
import release_safety


ROOT = Path(__file__).resolve().parents[1]


class HistoricalMigrationTests(unittest.TestCase):
    def load_records(self, rid):
        directory = ROOT / "content" / "published" / "records" / rid
        return [json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(directory.glob("v*.json"))]

    def verified(self, rid):
        items = []
        for path in sorted((ROOT / "content" / "published" / "records" / rid).glob("v*.json")):
            items.append(("record", rid, path.stem[1:], build.sha256_bytes(path.read_bytes())))
        return items

    def verified_for(self, rid, records):
        return [("record", rid, record["version"], build.sha256_bytes(
            (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))
                for record in records]

    def test_exact_ta016_bridge_accepts_pinned_predecessors(self):
        records = self.load_records("TA-2026-016")
        self.assertTrue(build.validate_historical_schema2_bridge(
            records, self.verified("TA-2026-016"), ROOT / "content" / "published"))

    def test_exact_ta018_bridge_accepts_secondary_role_correction(self):
        records = self.load_records("TA-2026-018")
        self.assertTrue(build.validate_historical_schema2_bridge(
            records, self.verified("TA-2026-018"), ROOT / "content" / "published"))

    def test_hash_mismatch_is_rejected(self):
        records = self.load_records("TA-2026-018")
        verified = self.verified("TA-2026-018")
        verified = [(kind, rid, version, "0" * 64) if version == "1.2" else item
                    for item in verified for kind, rid, version in [item[:3]]]
        with self.assertRaises(build.BuildError):
            build.validate_historical_schema2_bridge(records, verified, ROOT / "content" / "published")

    def test_changed_v10_v11_or_v12_bytes_are_rejected(self):
        for version, field in (("1.0", "released"), ("1.1", "kind"), ("1.2", "track")):
            records = self.load_records("TA-2026-016")
            target = next(item for item in records if item["version"] == version)
            target[field] = "2099-01-01" if field == "released" else ("negative" if field == "kind" else "other")
            with self.assertRaises(build.BuildError):
                build.validate_historical_schema2_bridge(records, self.verified_for("TA-2026-016", records))

    def test_unscoped_v13_claim_mutation_is_rejected(self):
        records = self.load_records("TA-2026-018")
        records[-1]["claims"][0]["statement"] = "unscoped mutation"
        with self.assertRaises(build.BuildError):
            build.validate_historical_schema2_bridge(records, self.verified_for("TA-2026-018", records))

    def test_claim_mutation_and_missing_v13_control_fail_closed(self):
        records = self.load_records("TA-2026-018")
        records[-1]["claims"][1]["result"]["finding"] = "unscoped mutation"
        with self.assertRaises(build.BuildError):
            build.validate_record_history(records, self.verified_for("TA-2026-018", records))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "04_Publication" / "Release_Records").mkdir(parents=True)
            with self.assertRaises(release_safety.GuardError):
                release_safety.find_release_record_control(root, "TA-2026-018", "1.3")

    def test_skipped_schema2_version_is_rejected(self):
        records = [record for record in self.load_records("TA-2026-016") if record["version"] != "1.2"]
        with self.assertRaises(build.BuildError):
            build.validate_historical_schema2_bridge(records, self.verified("TA-2026-016"), ROOT / "content" / "published")

    def test_unrecognized_public_id_does_not_enter_bridge(self):
        records = self.load_records("TA-2026-016")
        for record in records:
            record["public_id"] = "TA-2026-999"
        self.assertFalse(build.validate_historical_schema2_bridge(
            records, self.verified("TA-2026-016"), ROOT / "content" / "published"))

    def test_later_ta016_carry_uses_only_pinned_legacy_origin(self):
        records = self.load_records("TA-2026-016")
        later = copy.deepcopy(records[-1])
        later["version"] = "1.4"
        later["released"] = "2026-11-26"
        later["changelog"] = later["changelog"] + [{
            "version": "1.4", "date": "2026-11-26",
            "change": "Carry-forward of the unchanged Open finding and its historical status provenance."
        }]
        records.append(later)
        verified = self.verified("TA-2026-016") + [("record", "TA-2026-016", "1.4",
            build.sha256_bytes((json.dumps(later, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))]
        self.assertIsNone(build.validate_record_history(records, verified))

    def test_later_ta016_correction_traces_c1_through_pinned_schema2_origin(self):
        records = self.load_records("TA-2026-016")
        later = copy.deepcopy(records[-1])
        later["version"] = "1.4"
        later["released"] = "2026-11-26"
        c1 = next(claim for claim in later["claims"] if claim["id"] == "c1")
        c1.pop("status_provenance", None)
        c1["publication_revision"] = {
            "from_version": "1.3", "from_status": "open", "to_status": "open",
            "prior_sha256": "006c5d029974a7c528e7da0b79d98a09401bd3c33e13a545ac776cf62ab8e9dd",
            "reason": "A later exact correction retains the Open status while updating its presentation."
        }
        later["changelog"] = later["changelog"] + [{
            "version": "1.4", "date": "2026-11-26",
            "change": "Issued a later exact correction while retaining the Open status.",
            "revision_type": "error_correction", "our_correction": True
        }]
        records.append(later)
        verified = self.verified("TA-2026-016") + [("record", "TA-2026-016", "1.4",
            build.sha256_bytes((json.dumps(later, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))]
        self.assertIsNone(build.validate_record_history(records, verified))

    def test_later_ta018_correction_traces_through_pinned_v13_and_v12_nodes(self):
        records = self.load_records("TA-2026-018")
        later = copy.deepcopy(records[-1])
        later["version"] = "1.4"
        later["released"] = "2026-11-26"
        c2 = next(claim for claim in later["claims"] if claim["id"] == "c2")
        c2["publication_revision"] = {
            "from_version": "1.3", "from_status": "confirmed", "to_status": "confirmed",
            "prior_sha256": "4b55265755d93692a8090c02e0bdf75b5d951743bdfe1c1be527ecaa8ba7e6f9",
            "reason": "A later exact correction retains the secondary Algorithm 6 classification and Confirmed status."
        }
        later["changelog"] = later["changelog"] + [{
            "version": "1.4", "date": "2026-11-26",
            "change": "Issued a later exact correction while retaining the Confirmed secondary-result classification.",
            "revision_type": "error_correction", "our_correction": True
        }]
        records.append(later)
        verified = self.verified("TA-2026-018") + [("record", "TA-2026-018", "1.4",
            build.sha256_bytes((json.dumps(later, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))]
        self.assertIsNone(build.validate_record_history(records, verified))

    def test_later_ta018_c1_correction_traces_through_pinned_schema2_origin(self):
        records = self.load_records("TA-2026-018")
        later = copy.deepcopy(records[-1])
        later["version"] = "1.4"
        later["released"] = "2026-11-26"
        c1 = next(claim for claim in later["claims"] if claim["id"] == "c1")
        c1.pop("status_provenance", None)
        c1["publication_revision"] = {
            "from_version": "1.3", "from_status": "confirmed", "to_status": "confirmed",
            "prior_sha256": "4b55265755d93692a8090c02e0bdf75b5d951743bdfe1c1be527ecaa8ba7e6f9",
            "reason": "A later exact correction retains the Confirmed Algorithm 2 finding."
        }
        c2 = next(claim for claim in later["claims"] if claim["id"] == "c2")
        c2.pop("publication_revision", None)
        c2["status_provenance"] = {"status": "confirmed", "revision_version": "1.3"}
        later["changelog"] = later["changelog"] + [{
            "version": "1.4", "date": "2026-11-26",
            "change": "Issued a later exact correction while retaining the Confirmed Algorithm 2 finding.",
            "revision_type": "error_correction", "our_correction": True
        }]
        records.append(later)
        verified = self.verified("TA-2026-018") + [("record", "TA-2026-018", "1.4",
            build.sha256_bytes((json.dumps(later, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))]
        self.assertIsNone(build.validate_record_history(records, verified))

    def test_later_legacy_origin_hash_tamper_is_rejected(self):
        records = self.load_records("TA-2026-018")
        later = copy.deepcopy(records[-1])
        later["version"] = "1.4"
        later["released"] = "2026-11-26"
        later["changelog"] = later["changelog"] + [{
            "version": "1.4", "date": "2026-11-26", "change": "Carry-forward."
        }]
        records.append(later)
        verified = self.verified("TA-2026-018") + [("record", "TA-2026-018", "1.4",
            build.sha256_bytes((json.dumps(later, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))]
        verified = [(kind, rid, "1.1", "0" * 64) if (kind, rid, version) == ("record", "TA-2026-018", "1.1")
                    else (kind, rid, version, digest) for kind, rid, version, digest in verified]
        with self.assertRaises(build.BuildError):
            build.validate_record_history(records, verified)

    def test_canonical_role_mismatch_is_rejected(self):
        records = self.load_records("TA-2026-018")
        records[-1]["claims"][1]["role"] = "main"
        with self.assertRaises(release_safety.GuardError):
            release_safety.validate_historical_schema2_bridge(
                ROOT, release_safety.PUBLIC_HISTORY_BASELINE, records[-1])

    def test_marker_is_exact_and_not_release_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            control = Path(folder)
            deployment = control / "05_Website" / "Deployment"
            deployment.mkdir(parents=True)
            marker_data = {
                "marker": release_safety.HISTORICAL_MARKER,
                "decision_date": "2026-11-25",
                "recognized_public_state_date": "2026-11-23",
                "approved_release": False,
                "classification": "B",
                "purpose": "runtime_audit_migration_only",
                "authorization_reconstructible": False,
                "scientific_correctness_determined": False,
                "authorizes_new_or_changed_bytes": False,
                "future_corrections_require_current_procedure": True,
                "source_baseline": release_safety.PUBLIC_HISTORY_BASELINE,
                "entries": sorted(release_safety.HISTORICAL_PUBLIC_STATE_ENTRIES,
                                  key=lambda item: (item["public_id"], item["version"]))
            }
            (deployment / release_safety.HISTORICAL_MARKER_FILE).write_text(
                json.dumps(marker_data, indent=2) + "\n", encoding="utf-8")
            marker = release_safety.historical_public_state_marker(control)
        self.assertIsNotNone(marker)
        self.assertFalse(marker[1]["approved_release"])
        self.assertEqual(marker[1]["marker"], "ASSTATED_HISTORICAL_PUBLIC_STATE_V1")
        self.assertEqual(marker[1]["decision_date"], "2026-11-25")
        self.assertEqual(marker[1]["recognized_public_state_date"], "2026-11-23")
        self.assertEqual(marker[1]["classification"], "B")
        self.assertEqual(marker[1]["purpose"], "runtime_audit_migration_only")
        self.assertFalse(marker[1]["authorization_reconstructible"])
        self.assertFalse(marker[1]["scientific_correctness_determined"])
        self.assertFalse(marker[1]["authorizes_new_or_changed_bytes"])
        self.assertTrue(marker[1]["future_corrections_require_current_procedure"])
        self.assertEqual(len(marker[1]["entries"]), 7)


if __name__ == "__main__":
    unittest.main()
