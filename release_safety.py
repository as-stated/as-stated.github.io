#!/usr/bin/env python3
"""Local and CI guards for immutable As Stated releases and safe Pages deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

PUBLIC_ROOT = "content/published/"
OPERATIONAL_README = "content/published/README.txt"
PUBLIC_HISTORY_BASELINE = "fe0c2c822a4d64fa9aa5661b30ae0732ce3b3790"
CONTROL_MARKER = "ASSTATED_RELEASE_CONTROL_V1"
DEPLOYMENT_MARKER = "ASSTATED_DEPLOYMENT_V1"
OWNER_PUBLISH_MARKER = "ASSTATED_OWNER_PUBLISH_V1"
OWNER_HOLD_MARKER = "ASSTATED_OWNER_HOLD_V1"
CONTROL_RE = re.compile(r"<!--\s*" + CONTROL_MARKER + r"\s*\n(.*?)\n" + CONTROL_MARKER + r"\s*-->", re.S)
DEPLOYMENT_RE = re.compile(r"<!--\s*" + DEPLOYMENT_MARKER + r"\s*\n(.*?)\n" + DEPLOYMENT_MARKER + r"\s*-->", re.S)
OWNER_PUBLISH_RE = re.compile(r"<!--\s*" + OWNER_PUBLISH_MARKER + r"\s*\n(.*?)\n" + OWNER_PUBLISH_MARKER + r"\s*-->", re.S)
OWNER_HOLD_RE = re.compile(r"<!--\s*" + OWNER_HOLD_MARKER + r"\s*\n(.*?)\n" + OWNER_HOLD_MARKER + r"\s*-->", re.S)
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
CASE_RE = re.compile(r"W-\d{4}\Z")
REGISTRY_CASE_RE = re.compile(r"K-\d{4}\Z")
CLAIM_RE = re.compile(r"W-\d{4}\.C\d+\Z")
MANIFEST_RE = re.compile(r"content/published/releases/record__([^/]+)__([0-9]+(?:\.[0-9]+)*)\.txt\Z")
NOTE_RE = re.compile(r"content/published/files/technical-notes/[a-z0-9]+(?:-[a-z0-9]+)*/v[0-9]+(?:\.[0-9]+)*\.pdf\Z")
SNAPSHOT_RE = re.compile(r"content/published/snapshots/[0-9]{4}-[0-9]{2}\.json\Z")
DATED_DEPLOYMENT_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}).*(?:DEPLOYMENT|LIVE_SITE_AUDIT)", re.I)
AUTHORIZATIONS = {"standing_open", "case_publish", "standing_correction", "context_only"}
HOLD_DISPOSITIONS = {"no_hold", "not_applicable", "active_hold", "lifted", "overridden_for_this_release",
                     "correction_suppression"}
HOLD_INTENT_RE = re.compile(
    r"\b(?:hold|defer|withhold|pause|suspend|delay|postpone)\b|"
    r"\b(?:do\s+not|don't|never|no\s+longer|not)\b.{0,80}\b(?:publish(?:ing)?|publication|release|releasing)\b|"
    r"\b(?:not|no\s+longer)\s+(?:ready|approved|authorized|cleared)\s+to\s+(?:publish|release)\b",
    re.IGNORECASE,
)
HOLD_BROAD_SCOPE_RE = re.compile(
    r"\b(?:all|every|any|each)\b.{0,50}\b(?:paper|case|record|release|publication)s?\b|"
    r"\b(?:site[- ]wide|project[- ]wide|globally|without exception)\b",
    re.IGNORECASE,
)


class GuardError(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def release_records_inventory(control_root: Path) -> list[dict]:
    root = control_root / "04_Publication" / "Release_Records"
    entries = []
    for path in sorted(root.rglob("*") if root.exists() else []):
        if not path.is_file() or path.suffix.lower() == ".paper":
            continue
        entries.append({"path": path.relative_to(control_root).as_posix(), "sha256": sha256(path.read_bytes())})
    return entries


def markdown_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".md") if root.exists() else []


def marker_blocks(text: str, marker: str, pattern: re.Pattern, label: str) -> list[re.Match]:
    blocks = list(pattern.finditer(text))
    opening = len(re.findall(r"<!--\s*" + re.escape(marker) + r"\b", text))
    closing = len(re.findall(r"\b" + re.escape(marker) + r"\s*-->", text))
    _require(opening == closing == len(blocks) and len(blocks) <= 1,
             f"{label} file has malformed or duplicate marker blocks")
    return blocks


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, encoding="utf-8", errors="replace")
    if check and proc.returncode:
        raise GuardError(f"git {' '.join(args)} failed ({proc.returncode})")
    return proc.stdout.strip()


def git_success(repo: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True).returncode == 0


def inside_control_root(path: str) -> bool:
    return any(path.startswith(root) for root in CONTROL_ROOTS)


def changed_paths(repo: Path, base: str) -> list[tuple[str, str]]:
    if not git_success(repo, "cat-file", "-e", f"{base}^{{commit}}"):
        raise GuardError(f"base commit is unavailable: {base}")
    raw = git(repo, "diff", "--name-status", "--no-renames", base, "--", PUBLIC_ROOT)
    changes = []
    for line in raw.splitlines():
        if not line:
            continue
        fields = line.split("\t", 1)
        if len(fields) != 2:
            raise GuardError("could not parse Git's public-history change list")
        changes.append((fields[0], fields[1].replace("\\", "/")))
    return changes


def check_public_change_set(repo: Path, changes: list[tuple[str, str]]) -> list[str]:
    """Allow only paired immutable record releases and their referenced versioned PDFs."""
    records = set()
    manifests = set()
    notes = set()
    for status, path in changes:
        if path == OPERATIONAL_README:
            _require(status == "M", "the published-channel operational README may be updated but not deleted or re-added")
            continue
        if status != "A":
            raise GuardError(f"public path is immutable or has no release procedure: {path}")
        record = versioned_record(path)
        manifest = MANIFEST_RE.fullmatch(path)
        note = NOTE_RE.fullmatch(path)
        snapshot = SNAPSHOT_RE.fullmatch(path)
        if record:
            records.add(record)
        elif manifest:
            manifests.add((manifest.group(1), manifest.group(2)))
        elif note:
            notes.add(path)
        elif snapshot:
            raise GuardError("statistics snapshots are fail-closed until they have their own release-control procedure")
        else:
            raise GuardError(f"unrecognized path under content/published: {path}")
    _require(records == manifests, "new public records and exact release manifests must be added together; orphan manifests are refused")
    record_paths = {identity: f"content/published/records/{identity[0]}/v{identity[1]}.json" for identity in records}
    referenced_notes = set()
    for identity, rel in record_paths.items():
        try:
            rec = json.loads((repo / Path(rel)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise GuardError("new public record is unreadable while checking paired files") from None
        for entry in rec.get("technical_notes", []):
            note_path = "content/published/files/" + entry.get("path", "")
            if note_path in notes:
                referenced_notes.add(note_path)
                try:
                    digest = sha256((repo / Path(note_path)).read_bytes())
                except OSError:
                    raise GuardError("new technical-note bytes cannot be read") from None
                _require(digest == entry.get("sha256"), "new technical-note bytes do not match the record hash")
    _require(notes == referenced_notes, "new technical-note PDFs must be referenced by a paired new record")
    return [path for status, path in changes]


def check_append_only(repo: Path, base: str) -> list[str]:
    """Reject rewrites and any public-root changes without a supported release path."""
    return check_public_change_set(repo, changed_paths(repo, base))


def check_public_history(repo: Path, head: str, baseline: str = PUBLIC_HISTORY_BASELINE) -> None:
    """Audit every commit since the pinned known-good public baseline, including failed earlier pushes."""
    _require(git_success(repo, "merge-base", "--is-ancestor", baseline, head),
             f"known-good public history baseline {baseline} is not an ancestor of {head}")
    commits = git(repo, "rev-list", "--reverse", "--topo-order", f"{baseline}..{head}").splitlines()
    for commit in commits:
        parents = git(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]
        per_commit = set()
        for parent in parents:
            raw = git(repo, "diff-tree", "--name-status", "--no-renames", "-r", parent, commit, "--", PUBLIC_ROOT)
            for line in raw.splitlines():
                if line:
                    status, path = line.split("\t", 1)
                    per_commit.add((status, path.replace("\\", "/")))
        if per_commit:
            check_public_change_set(repo, sorted(per_commit))


def parse_manifest(path: Path, public_id: str, version: str, data: bytes) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise GuardError(f"new public record has no readable release manifest: {path.name}") from None
    expected = {
        "as-stated-release v1",
        "kind: record",
        f"id: {public_id}",
        f"version: {version}",
        f"sha256: {sha256(data)}",
    }
    if set(text.splitlines()) != expected or len(text.splitlines()) != len(expected):
        raise GuardError(f"release manifest does not identify the exact new record bytes: {path.name}")


def versioned_record(path: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"content/published/records/([^/]+)/v([0-9]+(?:\.[0-9]+)*)\.json", path)
    return (match.group(1), match.group(2)) if match else None


def validate_version_monotonicity(repo: Path, base: str, new_records: list[tuple[str, str]]) -> None:
    """Require every added version for a public ID to advance its published sequence."""
    paths = git(repo, "ls-tree", "-r", "--name-only", base, "--", "content/published/records").splitlines()
    deployed: dict[str, set[tuple[int, ...]]] = {}
    for path in paths:
        identity = versioned_record(path)
        if identity:
            public_id, version = identity
            deployed.setdefault(public_id, set()).add(tuple(int(part) for part in version.split(".")))
    grouped: dict[str, list[tuple[int, ...]]] = {}
    for public_id, version in new_records:
        grouped.setdefault(public_id, []).append(tuple(int(part) for part in version.split(".")))
    for public_id, versions in grouped.items():
        old = deployed.get(public_id, set())
        _require(len(versions) == len(set(versions)), f"a public release repeats a version for {public_id}")
        if old:
            _require(min(versions) > max(old),
                     f"a new public version for {public_id} must advance the latest published version")


def git_bytes(repo: Path, revision: str, path: str) -> bytes | None:
    proc = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=repo, capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def find_release_record_control(control_root: Path, public_id: str, version: str) -> tuple[str, dict]:
    records = control_root / "04_Publication" / "Release_Records"
    matches = []
    for path in markdown_files(records):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        blocks = marker_blocks(text, CONTROL_MARKER, CONTROL_RE, "private release-control")
        if not blocks:
            continue
        try:
            data = json.loads(blocks[0].group(1))
        except json.JSONDecodeError:
            raise GuardError("a private release-control block is malformed") from None
        if data.get("public_id") == public_id and data.get("record_version") == version:
            matches.append((path.relative_to(control_root).as_posix(), data))
    if len(matches) != 1:
        raise GuardError(f"expected one private release-control block for {public_id} v{version}; found {len(matches)}")
    return matches[0]


def parse_release_marker(control_root: Path, public_id: str, version: str) -> dict:
    return find_release_record_control(control_root, public_id, version)[1]


def validate_release_control_freshness(control_root: Path, deployed: dict,
                                       new_records: list[tuple[str, str]]) -> None:
    baseline = deployed.get("release_records_inventory")
    _require(isinstance(baseline, list), "deployment marker needs its private release-record inventory")
    baseline_map = {}
    for item in baseline:
        _require(isinstance(item, dict) and set(item) == {"path", "sha256"} and
                 isinstance(item.get("path"), str) and SHA_RE.fullmatch(item.get("sha256", "")) is not None and
                 item["path"] not in baseline_map,
                 "deployment release-record inventory has an invalid shape")
        safe_control_note_path(control_root, item["path"])
        baseline_map[item["path"]] = item["sha256"]
    current_map = {item["path"]: item["sha256"] for item in release_records_inventory(control_root)}
    _require(all(current_map.get(path) == digest for path, digest in baseline_map.items()),
             "a private release record used by the verified deployment changed or disappeared")
    expected_new = {find_release_record_control(control_root, public_id, version)[0]
                    for public_id, version in new_records}
    extras = set(current_map) - set(baseline_map)
    _require(extras == expected_new,
             "private release-record changes do not match the public record versions in this push")


def validate_release_control_shape(data: dict, record: dict) -> None:
    required = {"control_schema", "public_id", "record_version", "record_sha256", "case_ids", "registry_case_ids",
                "canonical_snapshot", "canonical_claims", "claim_authorizations", "claim_reviews", "release_checks",
                "hold_review"}
    optional = {"outreach_events", "publish_instruction", "held_correction_review"}
    _require(isinstance(data, dict) and required <= set(data) and set(data) <= required | optional,
             "private release control has missing or unsupported fields")
    _require(data.get("control_schema") == 1 and data.get("public_id") == record.get("public_id") and
             data.get("record_version") == record.get("version") and SHA_RE.fullmatch(data.get("record_sha256", "")) is not None,
             "private release control needs its supported schema and exact public record identity/hash")
    snapshot = data.get("canonical_snapshot")
    _require(isinstance(snapshot, dict) and set(snapshot) == {"records_json_sha256", "event_files",
                                                              "applied_receipt_id", "applied_receipt_sha256"} and
             SHA_RE.fullmatch(snapshot.get("records_json_sha256", "")) is not None and
             SHA_RE.fullmatch(snapshot.get("applied_receipt_sha256", "")) is not None and
             isinstance(snapshot.get("event_files"), list) and isinstance(snapshot.get("applied_receipt_id"), str),
             "canonical_snapshot has an unsupported or incomplete shape")
    hold_review = data.get("hold_review")
    _require(isinstance(hold_review, dict) and set(hold_review) == {"checked_at", "inventory"},
             "hold_review has an unsupported or incomplete shape")
    if "publish_instruction" in data:
        instruction = data["publish_instruction"]
        _require(isinstance(instruction, dict) and set(instruction) == {"date", "source_path", "source_sha256"} and
                 isinstance(instruction.get("source_path"), str) and
                 SHA_RE.fullmatch(instruction.get("source_sha256", "")) is not None,
                 "publish_instruction has an unsupported or incomplete shape")
    if "outreach_events" in data:
        _require(isinstance(data["outreach_events"], list), "outreach_events must be a list")
    if "held_correction_review" in data:
        review = data["held_correction_review"]
        _require(isinstance(review, dict) and
                 set(review) == {"review_complete", "record_sha256", "necessary_fields", "rationale"} and
                 review.get("review_complete") is True and review.get("record_sha256") == data.get("record_sha256") and
                 isinstance(review.get("necessary_fields"), list) and
                 all(field in {"kind", "headline", "correction"} for field in review["necessary_fields"]) and
                 len(review["necessary_fields"]) == len(set(review["necessary_fields"])) and
                 isinstance(review.get("rationale"), str) and review["rationale"].strip(),
                 "held_correction_review must bind the exact record and name each necessary public correction field")


def latest_event(events: list[dict], subject: str, dimension: str) -> dict | None:
    related = [e for e in events if e.get("subject") == subject and e.get("dimension") == dimension]
    corrected = {e.get("corrects") for e in related if e.get("corrects")}
    active = [e for e in related if e.get("event") not in corrected]
    if not active:
        return None
    latest_effective = max(e.get("effective_at", "") for e in active)
    latest = [e for e in active if e.get("effective_at", "") == latest_effective]
    values = {json.dumps(e.get("value"), sort_keys=True, separators=(",", ":")) for e in latest}
    _require(len(values) == 1, f"canonical events conflict for {subject} {dimension} at {latest_effective}")
    return max(latest, key=lambda e: (e.get("recorded_at", ""), e.get("event", "")))


def active_events(events: list[dict]) -> list[dict]:
    corrected = {e.get("corrects") for e in events if e.get("corrects")}
    return [e for e in events if e.get("event") not in corrected]


def source_corrections_for_claim(events: list[dict], claim_id: str) -> list[dict]:
    active = active_events(events)
    corrections = []
    for event in active:
        if event.get("dimension") != "source_correction":
            continue
        addresses = event.get("value", {}).get("addresses_claims")
        _require(isinstance(addresses, list) and all(isinstance(item, str) for item in addresses),
                 "canonical source-correction event has an invalid claim scope")
        if claim_id in addresses:
            corrections.append(event)
    return sorted(corrections, key=lambda event: (event.get("effective_at", ""),
                                                   event.get("recorded_at", ""), event.get("event", "")))


def is_fresh_hostile_confirmation(event: dict | None) -> bool:
    value = (event or {}).get("value", {})
    return bool(event and event.get("dimension") == "check" and value.get("checker") == "ai" and
                value.get("session") in {"fresh_blind", "fresh_informed"} and
                value.get("method") in {"independent_code", "hand_proof_check"} and
                value.get("result") == "confirms")


def validate_claim_readiness(claim: dict, review: dict, current: dict, checks: list[dict]) -> None:
    """Enforce claim-specific release evidence; a record-wide checkbox cannot stand in for it."""
    readiness = review.get("readiness")
    _require(isinstance(readiness, dict), f"claim {claim.get('id')} needs a per-claim readiness review")
    result = claim.get("result", {})
    revision = claim.get("publication_revision")
    restored_positive = bool(revision and revision.get("from_status") in {"unresolved", "rejected"} and
                             revision.get("to_status") in {"open", "confirmed"})
    initial_positive_review = (restored_positive or
                               (not revision and not claim.get("status_provenance") and
                                result.get("outcome") == "defect_found" and result.get("status") == "open"))
    if initial_positive_review:
        keys = {"witness_and_counterexample_complete", "scope_and_nonclaims_complete", "correction_search_complete", "novelty_event_id",
                "source_correction_event_ids", "hostile_check_event_id", "refuting_check_event_ids"}
        if restored_positive:
            keys.add("correction_status_review_complete")
        _require(set(readiness) == keys and readiness.get("witness_and_counterexample_complete") is True and
                 readiness.get("scope_and_nonclaims_complete") is True and
                 readiness.get("correction_search_complete") is True,
                 f"claim {claim['id']} lacks current positive readiness, correction, scope or non-claims review")
        if restored_positive:
            _require(readiness.get("correction_status_review_complete") is True,
                     f"claim {claim['id']} lacks its corrective status and scope review")
        novelty = current.get("novelty")
        _require(novelty and readiness.get("novelty_event_id") == novelty.get("event") and
                 novelty.get("value", {}).get("status") != "not_searched",
                 f"claim {claim['id']} lacks a current correction and novelty search")
        source_corrections = current.get("source_correction_events", [])
        _require(readiness.get("source_correction_event_ids") == sorted(event.get("event") for event in source_corrections),
                 f"claim {claim['id']} correction search does not inventory current work, case and claim events")
        hostile_id = readiness.get("hostile_check_event_id")
        hostile = next((event for event in checks if event.get("event") == hostile_id), None)
        source_lock = current.get("source_lock")
        prior_nonpositive_status = current.get("prior_nonpositive_status")
        fresh_after_basis = (is_fresh_hostile_confirmation(hostile) and source_lock and
                             hostile.get("recorded_at", "") > source_lock.get("recorded_at", ""))
        if restored_positive:
            fresh_after_basis = bool(fresh_after_basis and prior_nonpositive_status and
                                     prior_nonpositive_status.get("value", {}).get("status") in {"unresolved", "rejected"} and
                                     hostile.get("recorded_at", "") > prior_nonpositive_status.get("recorded_at", ""))
        _require(fresh_after_basis,
                 f"claim {claim['id']} lacks a fresh hostile technical check after its current finding, source lock and prior nonpositive status")
        refuting = sorted(event.get("event") for event in checks if event.get("value", {}).get("result") == "refutes")
        _require(readiness.get("refuting_check_event_ids") == refuting,
                 f"claim {claim['id']} review does not enumerate every current refuting check")
        status = current.get("candidate_status")
        addresses = (status or {}).get("value", {}).get("addresses_refutes", [])
        unresolved = []
        for event in checks:
            if event.get("value", {}).get("result") != "refutes":
                continue
            if event.get("event") not in addresses or not status or \
                    status.get("recorded_at", "") <= event.get("recorded_at", "") or \
                    not status.get("note") or not status.get("evidence"):
                unresolved.append(event.get("event"))
        _require(not unresolved,
                 f"claim {claim['id']} has an unreconciled technical refutation; initial Open release is blocked")
    elif revision or claim.get("status_provenance"):
        target_status = (revision.get("to_status") if revision else
                         claim["status_provenance"].get("status"))
        if target_status in {"open", "confirmed"}:
            keys = {"correction_status_review_complete", "refuting_check_event_ids"}
            _require(set(readiness) == keys and readiness.get("correction_status_review_complete") is True,
                     f"claim {claim['id']} lacks its corrective status and scope review")
            refuting = sorted(event.get("event") for event in checks if event.get("value", {}).get("result") == "refutes")
            _require(readiness.get("refuting_check_event_ids") == refuting,
                     f"claim {claim['id']} correction review does not enumerate every current refuting check")
            status = current.get("candidate_status")
            addresses = (status or {}).get("value", {}).get("addresses_refutes", [])
            unresolved = [event.get("event") for event in checks
                          if event.get("value", {}).get("result") == "refutes" and
                          (event.get("event") not in addresses or not status or
                           status.get("recorded_at", "") <= event.get("recorded_at", "") or
                           not status.get("note") or not status.get("evidence"))]
            _require(not unresolved,
                     f"claim {claim['id']} has an unreconciled technical refutation; corrected positive release is blocked")
        else:
            _require(set(readiness) == {"correction_status_review_complete"} and
                     readiness.get("correction_status_review_complete") is True,
                     f"claim {claim['id']} lacks its corrective status and scope review")
    elif claim.get("unresolved_context"):
        _require(set(readiness) == {"context_only_review_complete"} and
                 readiness.get("context_only_review_complete") is True,
                 f"claim {claim['id']} lacks its context-only review")
    else:
        _require(set(readiness) == {"case_specific_review_complete"} and
                 readiness.get("case_specific_review_complete") is True,
                 f"claim {claim['id']} lacks its case-specific release review")


def validate_public_evidence(claim: dict, review: dict, current: dict, checks: list[dict]) -> None:
    evidence = claim.get("evidence")
    event_ids = review.get("evidence_event_ids")
    _require(isinstance(evidence, list) and isinstance(event_ids, list) and len(event_ids) == len(evidence) and
             len(set(event_ids)) == len(event_ids),
             f"claim {claim.get('id')} public evidence must map one-to-one to canonical events")
    events = {item.get("event"): item for item in checks}
    for item in evidence:
        if item.get("type") in {"private_human_confirmation"} and current.get("author_position"):
            events[current["author_position"]["event"]] = current["author_position"]
    for item, event_id in zip(evidence, event_ids):
        event = events.get(event_id)
        _require(event is not None, f"claim {claim['id']} public evidence refers to an unreviewed canonical event")
        value = event.get("value", {})
        matching_date = isinstance(item.get("date"), str) and event.get("effective_at", "").startswith(item["date"])
        kind = item.get("type")
        if kind == "hostile_ai_recheck":
            session = {"fresh_blind": "blind", "fresh_informed": "informed"}.get(value.get("session"))
            valid = is_fresh_hostile_confirmation(event) and item.get("session") == session
        elif kind == "researcher_reproduction":
            valid = event.get("dimension") == "check" and value.get("checker") == "programme_researcher" and \
                    value.get("method") in {"independent_code", "hand_proof_check"} and value.get("result") == "confirms"
        elif kind == "external_check":
            valid = event.get("dimension") == "check" and value.get("checker") == "external_human" and \
                    value.get("result") in {"confirms", "partially_confirms"} and \
                    (claim.get("result", {}).get("status") != "confirmed" or value.get("result") == "confirms")
        elif kind == "private_human_confirmation":
            valid = ((event.get("dimension") == "check" and value.get("checker") in {"external_human", "programme_researcher"} and
                      value.get("result") == "confirms" and
                      ((value.get("checker") == "programme_researcher" and
                        value.get("method") in {"independent_code", "hand_proof_check"}) or
                       (value.get("checker") == "external_human" and
                        value.get("method") != "rerun_original_package"))) or
                     (event.get("dimension") == "author_position" and value.get("position") == "agrees" and
                      value.get("support_qualifies", True) is True and bool(event.get("evidence"))))
        else:
            valid = False
        _require(valid and matching_date,
                 f"claim {claim['id']} public evidence does not match its cited canonical event")


def normalize_document_reference(value: str) -> str:
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.IGNORECASE).rstrip("/").casefold()


def validate_public_correction_projection(record: dict, canonical_claims: dict, events: list[dict],
                                           retired_context_claim_ids: set[str] | None = None,
                                           prior_public_correction: dict | None = None) -> None:
    public_to_canonical = {public_id: item["id"] for public_id, item in canonical_claims.items()}
    canonical_to_public = {canonical_id: public_id for public_id, canonical_id in public_to_canonical.items()}
    relevant = []
    for event in active_events(events):
        if event.get("dimension") != "source_correction":
            continue
        value = event.get("value", {})
        addresses = value.get("addresses_claims")
        _require(isinstance(addresses, list) and all(isinstance(item, str) for item in addresses),
                 "canonical source-correction event has an invalid claim scope")
        if set(addresses) & set(canonical_to_public):
            relevant.append(event)
    correction = record.get("correction")
    if correction is None:
        _require(not relevant, "canonical source-correction event is missing from the public correction projection")
        return
    if not relevant:
        _require(prior_public_correction is not None,
                 "public correction has no active canonical source-correction event")
        _require(prior_public_correction is not None and correction == prior_public_correction and
                 set(correction.get("claims", [])) <= (retired_context_claim_ids or set()),
                 "historical source-correction metadata for a retired context claim must remain byte-for-byte unchanged")
        return
    _require(relevant, "public correction has no active canonical source-correction event")
    public_scope = {canonical_to_public[claim_id]
                    for event in relevant for claim_id in event["value"]["addresses_claims"]
                    if claim_id in canonical_to_public}
    retired_scope = set(correction.get("claims", [])) & (retired_context_claim_ids or set())
    prior_correction_scope = set((prior_public_correction or {}).get("claims", []))
    _require(retired_scope <= prior_correction_scope,
             "a retired context claim cannot be added to the current source-correction scope")
    _require(set(correction.get("claims", [])) == public_scope | retired_scope,
             "public correction claim scope differs from canonical source-correction evidence")
    for event in relevant:
        value = event["value"]
        _require(correction.get("type") == value.get("document") and
                 correction.get("date") == value.get("date") and
                 correction.get("relation") == value.get("relation") and
                 correction.get("attribution") == value.get("attribution"),
                 "public correction metadata differs from canonical source-correction evidence")
        if correction.get("doi") is not None:
            _require(normalize_document_reference(correction["doi"]) ==
                     normalize_document_reference(value.get("doi_or_url", "")),
                     "public correction source does not match its canonical event")


def event_file_digest(registry_dir: Path) -> str:
    lines = "".join(f"{path.name} {sha256(path.read_bytes())}\n"
                    for path in sorted((registry_dir / "events").glob("*.json")))
    return sha256(lines.encode("utf-8"))


def validate_applied_registry_state(control_root: Path, snapshot: dict) -> tuple[dict, dict, list[dict]]:
    """Bind canonical JSON and events to the latest applied validation receipt, without reading .paper bytes."""
    registry_dir = control_root / "01_Registry"
    _require(not (registry_dir / "changesets" / ".journal").exists(),
             "canonical registry has an active or interrupted changeset journal")
    records_path = registry_dir / "records.json"
    _require(records_path.is_file(), "canonical registry records.json is unavailable")
    records_bytes = records_path.read_bytes()
    try:
        registry = json.loads(records_bytes)
    except json.JSONDecodeError:
        raise GuardError("canonical registry records.json is malformed") from None
    parsed_events = []
    for path in sorted((registry_dir / "events").glob("*.json")):
        try:
            parsed_events.append(json.loads(path.read_bytes()))
        except (OSError, json.JSONDecodeError):
            raise GuardError("a canonical event file is unreadable") from None
    receipts_dir = registry_dir / "changesets" / "applied"
    receipts = []
    for path in sorted(receipts_dir.glob("*.json")) if receipts_dir.exists() else []:
        try:
            raw = path.read_bytes()
            receipt = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            raise GuardError("an applied canonical changeset receipt is unreadable") from None
        _require(receipt.get("format") == "as-stated-applied-changeset/1" and
                 isinstance(receipt.get("sequence"), int) and receipt["sequence"] > 0 and
                 isinstance(receipt.get("id"), str) and isinstance(receipt.get("validation"), dict) and
                 receipt["validation"].get("errors") == 0,
                 "an applied canonical changeset receipt has an unsupported format")
        for side in ("before", "after"):
            _require(isinstance(receipt.get(side), dict) and set(receipt[side]) == {"records_sha256", "events_sha256"} and
                     all(SHA_RE.fullmatch(receipt[side][key] or "") is not None
                         for key in ("records_sha256", "events_sha256")),
                     "an applied canonical changeset receipt has an invalid hash state")
        receipts.append((receipt["sequence"], receipt, raw))
    receipts.sort(key=lambda item: item[0])
    _require(receipts and [item[0] for item in receipts] == list(range(1, len(receipts) + 1)),
             "canonical applied changeset receipt history is missing or out of sequence")
    for index in range(1, len(receipts)):
        _require(receipts[index][1].get("before") == receipts[index - 1][1].get("after"),
                 "canonical applied changeset receipts do not form one continuous hash chain")
    latest, latest_raw = receipts[-1][1], receipts[-1][2]
    current = {"records_sha256": sha256(records_bytes), "events_sha256": event_file_digest(registry_dir)}
    _require(latest.get("after") == current,
             "canonical registry files differ from the latest applied changeset receipt")
    _require(snapshot.get("applied_receipt_id") == latest.get("id") and
             snapshot.get("applied_receipt_sha256") == sha256(latest_raw),
             "private release review does not identify the current applied registry receipt")
    return registry, latest, parsed_events


def verify_evidence_artifacts(control_root: Path, registry: dict, expected_ids: set[str], listed: object) -> None:
    _require(isinstance(listed, list) and all(isinstance(item, dict) and set(item) == {"id", "sha256"}
                                              for item in listed),
             "claim review needs exact evidence artifact IDs and hashes")
    by_id = {item.get("id"): item for item in registry.get("artifacts", []) if isinstance(item, dict)}
    listed_by_id = {item["id"]: item["sha256"] for item in listed}
    _require(len(listed_by_id) == len(listed) and set(listed_by_id) == expected_ids,
             "claim review evidence artifact inventory is incomplete or contains unrelated evidence")
    for artifact_id, digest in listed_by_id.items():
        _require(re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_id) is not None and
                 digest == artifact_id.split(":", 1)[1],
                 "claim review evidence artifact hash does not match its canonical content ID")
        artifact = by_id.get(artifact_id)
        _require(artifact is not None, "claim review cites an artifact absent from the canonical registry")
        locations = artifact.get("locations")
        _require(isinstance(locations, list) and locations, "canonical evidence artifact has no registered locations")
        checked = False
        for loc in locations:
            relpath = loc.get("relpath") if isinstance(loc, dict) else None
            _require(loc.get("root") == "GTA_ROOT" and isinstance(relpath, str),
                     "canonical evidence artifact has an unsupported location")
            target = (control_root / Path(relpath)).resolve()
            try:
                target.relative_to(control_root.resolve())
            except ValueError:
                raise GuardError("canonical evidence artifact location escapes the project root") from None
            member = loc.get("zip_member")
            is_paper = target.suffix.lower() == ".paper" or (isinstance(member, str) and member.lower().endswith(".paper"))
            if is_paper:
                _require(target.is_file(), "registered .paper pointer is unavailable")
                continue
            try:
                if member is None:
                    actual = sha256(target.read_bytes())
                else:
                    _require(isinstance(member, str), "canonical evidence archive member is malformed")
                    with zipfile.ZipFile(target) as archive:
                        with archive.open(member) as stream:
                            hasher = hashlib.sha256()
                            for block in iter(lambda: stream.read(65536), b""):
                                hasher.update(block)
                            actual = hasher.hexdigest()
            except (OSError, KeyError, zipfile.BadZipFile):
                raise GuardError("a cited canonical evidence artifact is unavailable") from None
            _require(actual == digest, "a cited canonical evidence artifact changed after its review")
            checked = True
        _require(checked,
                 "a cited canonical evidence artifact has no verifiable non-.paper location")


def validate_canonical(control_root: Path, data: dict, record: dict,
                       retired_context_claim_ids: set[str] | None = None,
                       prior_status_event_ids: dict[str, str] | None = None,
                       prior_public_correction: dict | None = None) -> None:
    """Bind public claims, their per-claim readiness and exact evidence to current canonical state."""
    snapshot = data.get("canonical_snapshot")
    _require(isinstance(snapshot, dict), "private release record needs a canonical_snapshot")
    registry, _, all_events = validate_applied_registry_state(control_root, snapshot)
    _require(snapshot.get("records_json_sha256") == sha256((control_root / "01_Registry" / "records.json").read_bytes()),
             "canonical records.json changed after the release review")

    work_ids = data.get("case_ids")
    _require(isinstance(work_ids, list) and len(work_ids) == 1 and
             all(isinstance(x, str) and CASE_RE.fullmatch(x) for x in work_ids),
             "a one-paper public record needs exactly one reconciled W-#### case_id")
    work_id = work_ids[0]
    registry_works = {item.get("id"): item for item in registry.get("works", []) if isinstance(item, dict)}
    _require(work_id in registry_works, "the public paper is not present in the canonical registry")
    canonical_work = registry_works[work_id]
    public_work = record.get("work") or {}
    _require(" ".join(str(public_work.get("title", "")).split()).casefold() ==
             " ".join(str(canonical_work.get("title", "")).split()).casefold() and
             [" ".join(str(author).split()).casefold() for author in public_work.get("authors", [])] ==
             [" ".join(str(author).split()).casefold() for author in canonical_work.get("authors", [])] and
             public_work.get("year") == canonical_work.get("year") and
             " ".join(str(public_work.get("venue", "")).split()).casefold() ==
             " ".join(str(canonical_work.get("venue", "")).split()).casefold(),
             "public citation metadata does not match the canonical paper")
    public_doi = public_work.get("doi")
    canonical_doi = canonical_work.get("doi")
    if canonical_doi:
        _require(isinstance(public_doi, str), "public record omits the canonical paper DOI")
        _require(re.sub(r"^https?://(?:dx\.)?doi\.org/", "", public_doi, flags=re.I).lower() ==
                 re.sub(r"^https?://(?:dx\.)?doi\.org/", "", canonical_doi, flags=re.I).lower(),
                 "public record DOI does not match its canonical work")

    claims = data.get("canonical_claims")
    public_claim_ids = {c.get("id") for c in record.get("claims", [])}
    _require(isinstance(claims, dict) and set(claims) == public_claim_ids,
             "private release record must map every public claim to canonical claim and event evidence")
    registered_claims = {item.get("id"): item for item in registry.get("claims", []) if isinstance(item, dict)}
    canonical_ids = set()
    canonical_claims_by_id = {}
    for item in claims.values():
        _require(isinstance(item, dict) and CLAIM_RE.fullmatch(item.get("id", "")) is not None,
                 "canonical claim mapping is malformed")
        canonical = registered_claims.get(item["id"])
        _require(canonical is not None and canonical.get("work") == work_id and
                 item["id"].split(".", 1)[0] == work_id,
                 "all public claims must belong to the same canonical paper")
        canonical_ids.add(item["id"])
        canonical_claims_by_id[item["id"]] = canonical
    _require(len(canonical_ids) == len(public_claim_ids),
             "public claims must map one-to-one to distinct canonical claims")

    registry_case_ids = data.get("registry_case_ids", [])
    _require(isinstance(registry_case_ids, list) and registry_case_ids and
             all(isinstance(x, str) and REGISTRY_CASE_RE.fullmatch(x) for x in registry_case_ids),
             "private release record needs registered K-#### case identifiers")
    _require(len(registry_case_ids) == len(set(registry_case_ids)),
             "private release record must list each K-#### case exactly once")
    registered_cases = {item.get("id"): item for item in registry.get("cases", []) if isinstance(item, dict)}
    _require(set(registry_case_ids) <= set(registered_cases), "a release case is not present in the canonical registry")
    _require(all(registered_cases[case_id].get("work") == work_id for case_id in registry_case_ids),
             "every listed K case must belong to the same canonical paper")
    all_work_cases = {case_id for case_id, item in registered_cases.items() if item.get("work") == work_id}
    _require(set(registry_case_ids) == all_work_cases,
             "private release record must list every registered K case for the paper")

    subjects = {work_id} | canonical_ids | set(registry_case_ids)
    event_dir = control_root / "01_Registry" / "events"
    actual_events = []
    relevant_events = []
    for path in sorted(event_dir.glob("*.json")):
        raw = path.read_bytes()
        event = json.loads(raw)
        if event.get("subject") in subjects:
            actual_events.append({"path": path.relative_to(control_root).as_posix(), "sha256": sha256(raw)})
            relevant_events.append(event)
    _require(isinstance(snapshot.get("event_files"), list) and snapshot["event_files"] == actual_events,
             "canonical event inventory changed or is incomplete")
    _require(actual_events, "private release record has no current canonical event evidence")

    auths = data.get("claim_authorizations")
    reviews = data.get("claim_reviews")
    _require(isinstance(auths, dict) and set(auths) == public_claim_ids,
             "private release record needs an authorization for every public claim")
    _require(isinstance(reviews, dict) and set(reviews) == public_claim_ids,
             "private release record needs a separate readiness review for every public claim")

    works_by_id = {item.get("id"): item for item in registry.get("works", []) if isinstance(item, dict)}
    sources_by_id = {item.get("id"): item for item in registry.get("sources", []) if isinstance(item, dict)}
    for claim in record["claims"]:
        public_claim = claim["id"]
        canonical_id = claims[public_claim]["id"]
        result = claim["result"]
        revision = claim.get("publication_revision") or {}
        canonical_claim = canonical_claims_by_id[canonical_id]
        _require(claim.get("kind") == canonical_claim.get("kind") and
                 claim.get("role") == canonical_claim.get("role"),
                 f"public claim {public_claim} kind or role differs from canonical claim metadata")
        claim_events = [event for event in relevant_events if event.get("subject") == canonical_id]
        active = active_events(claim_events)
        current = {dimension: latest_event(claim_events, canonical_id, dimension)
                   for dimension in ("finding", "candidate_status", "source_lock", "author_position", "reproduction",
                                     "novelty", "manuscript")}
        prior_event_id = (prior_status_event_ids or {}).get(public_claim)
        prior_nonpositive_status = next((event for event in relevant_events
                                         if event.get("event") == prior_event_id), None)
        if revision.get("from_status") in {"unresolved", "rejected"} and revision.get("to_status") in {"open", "confirmed"}:
            _require(prior_nonpositive_status and prior_nonpositive_status.get("subject") == canonical_id and
                     prior_nonpositive_status.get("dimension") == "candidate_status" and
                     prior_nonpositive_status.get("value", {}).get("status") == revision.get("from_status"),
                     f"claim {public_claim} restoration does not bind its prior public nonpositive status event")
        current["prior_nonpositive_status"] = prior_nonpositive_status
        source_corrections = source_corrections_for_claim(relevant_events, canonical_id)
        current["source_correction_events"] = source_corrections
        current["check"] = None
        checks = sorted((e for e in active if e.get("dimension") == "check"),
                        key=lambda e: (e.get("effective_at", ""), e.get("recorded_at", ""), e.get("event", "")))
        scalar_events = [item for key, item in current.items() if key != "source_correction_events" and item]
        expected_reviewed = sorted(e["event"] for e in [*checks, *scalar_events, *source_corrections])
        review = reviews[public_claim]
        review_keys = {"finding_event_id", "status_event_id", "source_lock_event_id", "check_event_ids",
                       "reviewed_event_ids", "author_position_event_id", "evidence_artifacts", "evidence_event_ids",
                       "readiness"}
        _require(isinstance(review, dict) and set(review) == review_keys,
                 f"claim {public_claim} has an invalid per-claim review shape")
        _require(review["reviewed_event_ids"] == expected_reviewed and
                 review["check_event_ids"] == sorted(e["event"] for e in checks),
                 f"claim {public_claim} review does not enumerate every current canonical check and status event")
        validate_public_evidence(claim, review, current, checks)
        finding = current["finding"]
        status = current["candidate_status"]
        source_lock = current["source_lock"]
        _require(finding and review["finding_event_id"] == finding.get("event"),
                 f"claim {public_claim} has no matching current canonical finding event")
        canonical_finding = finding.get("value", {})
        outcome_matches = canonical_finding.get("outcome") == result.get("outcome")
        if result.get("outcome") == "unresolved":
            outcome_matches = canonical_finding.get("outcome") in {"inconclusive", "defect_found"} and \
                              status and status.get("value", {}).get("status") == "unresolved"
        _require(outcome_matches,
                 f"public claim {public_claim} outcome differs from its canonical finding")
        for field in ("defect_class", "affects", "depth"):
            if field in result:
                _require(result[field] == canonical_finding.get(field),
                         f"public claim {public_claim} {field} differs from its canonical finding")
        _require(source_lock and review["source_lock_event_id"] == source_lock.get("event"),
                 f"claim {public_claim} has no matching current source-lock event")
        source = sources_by_id.get(source_lock.get("value", {}).get("version_checked"))
        _require(source and source.get("work") == work_id and source.get("kind") == "vor" and
                 source_lock.get("value", {}).get("vor_level") == claim.get("vor_check", {}).get("level"),
                 f"claim {public_claim} public source level does not match its current canonical source lock")

        if revision:
            expected = revision["to_status"]
        elif claim.get("status_provenance"):
            expected = claim["status_provenance"].get("status")
        elif result["outcome"] == "unresolved":
            expected = "unresolved"
        elif result["outcome"] == "no_defect_found":
            expected = "negative_audit"
        else:
            expected = result.get("status")
        if expected in {"open", "confirmed"}:
            _require(finding.get("value", {}).get("outcome") == "defect_found" and status and
                     status.get("value", {}).get("status") == expected and review["status_event_id"] == status.get("event"),
                     f"canonical status for public claim {public_claim} is not {expected}")
        elif expected == "unresolved":
            value = (status or {}).get("value", {})
            _require(status and value.get("status") == "unresolved" and review["status_event_id"] == status.get("event"),
                     f"canonical status for public claim {public_claim} is not unresolved")
            _require(value.get("reason") == result.get("unresolved_reason"),
                     f"public unresolved reason for claim {public_claim} does not match canonical status evidence")
        elif expected == "rejected":
            _require(finding.get("value", {}).get("outcome") == "no_defect_found" and status and
                     status.get("value", {}).get("status") == "rejected" and review["status_event_id"] == status.get("event"),
                     f"canonical status for public claim {public_claim} is not rejected")
        elif expected == "negative_audit":
            _require(finding.get("value", {}).get("outcome") == "no_defect_found" and
                     status is None and review["status_event_id"] is None,
                     f"canonical finding for public claim {public_claim} conflicts with a negative audit")
        else:
            raise GuardError(f"public claim {public_claim} has no supported canonical status")

        has_author_position = (claim.get("author_response") or {}).get("position") in {"agrees", "partly_agrees", "disagrees"}
        author_position = current["author_position"]
        if has_author_position:
            _require(author_position and review["author_position_event_id"] == author_position.get("event") and
                     author_position.get("value", {}).get("position") == claim["author_response"]["position"],
                     f"public author position for claim {public_claim} has no matching current canonical author-position event")
        else:
            _require(review["author_position_event_id"] is None,
                     f"claim {public_claim} review cites an author position that is not projected publicly")

        expected_artifacts = set()
        evidence_events = [*checks, *scalar_events, *source_corrections]
        for event in evidence_events:
            for aid in event.get("evidence", []):
                _require(isinstance(aid, str) and aid.startswith("sha256:"),
                         f"claim {public_claim} has an event with an unsupported evidence reference")
                expected_artifacts.add(aid)
            report = event.get("value", {}).get("report")
            if report:
                expected_artifacts.add(report)
        verify_evidence_artifacts(control_root, registry, expected_artifacts, review["evidence_artifacts"])
        validate_claim_readiness(claim, review, current, checks)

    primary_id = record.get("primary_claim_id")
    for claim in record["claims"]:
        if claim.get("unresolved_context") and not claim.get("publication_revision"):
            anchor_id = claim["unresolved_context"]["anchor_claim_id"]
            _require(anchor_id == primary_id and claims[anchor_id]["id"].split(".", 1)[0] ==
                     claims[claim["id"]]["id"].split(".", 1)[0],
                     "unresolved context and its positive anchor must concern the same canonical paper")

    outreach = record.get("outreach")
    outreach_events = data.get("outreach_events")
    current_outreach = {case_id: latest_event(relevant_events, case_id, "outreach") for case_id in registry_case_ids}
    current_outreach = {case_id: event for case_id, event in current_outreach.items() if event}
    public_outreach_status = {"not_planned": "not_contacted", "not_contacted": "not_contacted",
                              "note_drafted": "not_contacted",
                              "contacted": "awaiting_substantive_response",
                              "receipt_acknowledged": "awaiting_substantive_response",
                              "reply_received": "substantive_response_received"}
    if outreach:
        _require(all(event.get("value", {}).get("status") in public_outreach_status
                     for event in current_outreach.values()),
                 "a current canonical outreach state has no safe public projection")
        _require(isinstance(outreach_events, list) and
                 {item.get("case_id") for item in outreach_events if isinstance(item, dict)} == set(registry_case_ids) and
                 len(outreach_events) == len(registry_case_ids),
                 "public outreach state needs a current event for every listed case")
        bound = {}
        for item in outreach_events:
            _require(isinstance(item, dict) and set(item) == {"case_id", "event_id"},
                     "public outreach event mapping has an invalid shape")
            case_id = item["case_id"]
            status_event = current_outreach.get(case_id)
            _require(status_event and status_event.get("event") == item["event_id"] and
                     status_event.get("dimension") == "outreach" and
                     registered_cases[case_id].get("work") == work_id,
                     "public outreach mapping does not match the latest canonical event for every case")
            bound[case_id] = public_outreach_status[status_event["value"]["status"]]
        _require(set(bound.values()) == {outreach.get("status")},
                 "public paper-level outreach status conflicts across its canonical cases")
    else:
        _require(outreach_events in (None, []), "private release record cites outreach events omitted from the public record")
    validate_public_correction_projection(record, claims, relevant_events, retired_context_claim_ids or set(),
                                           prior_public_correction)


def current_hold_notes(control_root: Path, work_ids: list[str]) -> dict[str, str]:
    notes: set[Path] = set()
    cases_root = control_root / "02_Cases"
    for work_id in work_ids:
        matches = [p for p in cases_root.iterdir() if p.is_dir() and (p.name == work_id or p.name.startswith(work_id + "__"))] if cases_root.exists() else []
        _require(len(matches) == 1, f"could not identify one case Publication folder for {work_id}")
        publication = matches[0] / "Publication"
        notes.update(markdown_files(publication))
    reviews = control_root / "04_Publication" / "Reviews"
    if reviews.exists():
        notes.update(markdown_files(reviews))
    return {p.relative_to(control_root).as_posix(): sha256(p.read_bytes()) for p in sorted(notes)}


def safe_control_note_path(control_root: Path, relpath: str) -> Path:
    pure = PurePosixPath(relpath)
    _require(not pure.is_absolute() and ".." not in pure.parts and "\\" not in relpath,
             "owner instruction note path is unsafe")
    path = (control_root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(control_root.resolve())
    except ValueError:
        raise GuardError("owner instruction note path escapes the project root") from None
    return path


def read_owner_note_marker(path: Path, marker: str, pattern: re.Pattern, label: str) -> tuple[str, dict] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise GuardError(f"{label} note is unavailable or not UTF-8") from None
    blocks = marker_blocks(text, marker, pattern, label)
    if not blocks:
        return text, None
    try:
        value = json.loads(blocks[0].group(1))
    except json.JSONDecodeError:
        raise GuardError(f"{label} marker is malformed") from None
    _require(isinstance(value, dict), f"{label} marker must contain a JSON object")
    if marker == OWNER_HOLD_MARKER:
        action = value.get("action")
        common = {"actor", "action", "date", "work_ids"}
        if action in {"hold", "correction_suppression"}:
            expected = common | {"category", "reason", "review_date"}
        elif action in {"classify_no_hold", "lift", "override_discretionary", "authorize_correction"}:
            expected = common | {"target_path", "target_sha256"}
        else:
            raise GuardError("owner hold marker has an unsupported action")
        _require(set(value) == expected and value.get("actor") == "owner" and
                 isinstance(value.get("work_ids"), list) and all(CASE_RE.fullmatch(item) for item in value["work_ids"]),
                 "owner hold marker has an invalid shape or work scope")
        try:
            datetime.strptime(value.get("date", ""), "%Y-%m-%d")
        except (TypeError, ValueError):
            raise GuardError("owner hold marker needs a dated instruction") from None
        if action == "hold":
            _require(value.get("category") in {"discretionary", "legal", "rights", "privacy", "technical", "other"},
                     "owner hold marker needs a recognized hold category")
        if action == "correction_suppression":
            _require(value.get("category") == "correction_suppression",
                     "owner correction-suppression marker has an invalid category")
        if action in {"hold", "correction_suppression"}:
            _require(isinstance(value.get("reason"), str) and bool(value["reason"].strip()),
                     "owner hold marker needs a stated reason")
            try:
                review_date = datetime.strptime(value.get("review_date", ""), "%Y-%m-%d")
                instruction_date = datetime.strptime(value.get("date", ""), "%Y-%m-%d")
            except (TypeError, ValueError):
                raise GuardError("owner hold marker needs a dated review date") from None
            _require(review_date > instruction_date, "owner hold review date must follow the hold date")
        if action in {"classify_no_hold", "lift", "override_discretionary", "authorize_correction"}:
            _require(isinstance(value.get("target_path"), str) and SHA_RE.fullmatch(value.get("target_sha256", "")) is not None,
                     "owner hold resolution marker needs a target path and exact note hash")
    return text, value


def marker_free_note_text(text: str, marker: str, pattern: re.Pattern) -> str:
    return pattern.sub("", text)


def validate_owner_publish_instruction(control_root: Path, data: dict, record: dict, actual: dict) -> dict | None:
    instruction = data.get("publish_instruction")
    if instruction is None:
        return None
    _require(isinstance(instruction, dict) and
             set(instruction) == {"date", "source_path", "source_sha256"} and
             instruction.get("source_path") in actual and
             instruction.get("source_sha256") == actual[instruction["source_path"]],
             "case-specific publish instruction must cite an inventoried, hashed owner note")
    path = safe_control_note_path(control_root, instruction["source_path"])
    text, marker = read_owner_note_marker(path, OWNER_PUBLISH_MARKER, OWNER_PUBLISH_RE, "owner publish")
    _require(marker is not None and set(marker) == {"actor", "instruction", "date", "public_id", "version", "case_ids",
                                                    "record_sha256"} and
             marker.get("actor") == "owner" and marker.get("instruction") == "publish" and
             marker.get("public_id") == record.get("public_id") and marker.get("version") == record.get("version") and
             marker.get("record_sha256") == data.get("record_sha256") and
             isinstance(marker.get("case_ids"), list) and
             all(isinstance(case_id, str) and REGISTRY_CASE_RE.fullmatch(case_id) for case_id in marker["case_ids"]) and
             len(marker["case_ids"]) == len(set(marker["case_ids"])) and
             set(marker["case_ids"]) == set(data.get("registry_case_ids", [])) and
             marker.get("date") == instruction.get("date"),
             "case-specific publish instruction needs an affirmative, dated owner marker for this exact record and cases")
    _require(not HOLD_INTENT_RE.search(text),
             "case-specific publish note contains a conflicting hold or negation")
    return marker


def validate_holds(control_root: Path, data: dict, record: dict,
                   new_public_claim_ids: set[str] | None = None) -> bool:
    work_ids = data["case_ids"]
    actual = current_hold_notes(control_root, work_ids)
    review = data.get("hold_review")
    _require(isinstance(review, dict), "private release record needs a hold_review")
    try:
        datetime.fromisoformat(review.get("checked_at", "").replace("Z", "+00:00"))
    except ValueError:
        raise GuardError("hold_review.checked_at must be an ISO timestamp") from None
    items = review.get("inventory")
    _require(isinstance(items, list), "hold_review needs a complete note inventory")
    listed = {}
    active = []
    correction_suppression = []
    overridden = []
    note_markers = {}
    for item in items:
        _require(isinstance(item, dict) and isinstance(item.get("path"), str),
                 "hold inventory item has an invalid shape")
        path = safe_control_note_path(control_root, item["path"])
        note_markers[item["path"]] = read_owner_note_marker(path, OWNER_HOLD_MARKER, OWNER_HOLD_RE, "owner hold")
    for item in items:
        _require(isinstance(item, dict) and set(item) <= {"path", "sha256", "disposition", "category", "resolution_path",
                                                          "recorded_date", "resolution_date", "resolution_work_ids"} and
                 {"path", "sha256", "disposition"} <= set(item), "hold inventory item has an invalid shape")
        _require(item["disposition"] in HOLD_DISPOSITIONS and SHA_RE.fullmatch(item["sha256"] or "") is not None,
                 "hold inventory item needs a recognized disposition and SHA-256")
        _require(item["path"] not in listed, "hold inventory contains a duplicate path")
        listed[item["path"]] = item
        if item["disposition"] == "active_hold":
            active.append(item)
        if item["disposition"] == "correction_suppression":
            correction_suppression.append(item)
        if item["disposition"] == "overridden_for_this_release":
            overridden.append(item)
        text, owner_note = note_markers[item["path"]]
        if item["disposition"] == "not_applicable":
            _require(isinstance(owner_note, dict) and isinstance(owner_note.get("work_ids"), list) and
                     owner_note["work_ids"] and not (set(work_ids) & set(owner_note["work_ids"])),
                     "not_applicable disposition needs an owner marker scoped to different papers")
            free_text = marker_free_note_text(text, OWNER_HOLD_MARKER, OWNER_HOLD_RE)
            if HOLD_INTENT_RE.search(free_text):
                mentioned_works = set(re.findall(r"\bW-\d{4}\b", free_text))
                mentioned_cases = set(re.findall(r"\bK-\d{4}\b", free_text))
                _require(not HOLD_BROAD_SCOPE_RE.search(free_text) and mentioned_works and
                         mentioned_works <= set(owner_note["work_ids"]) and
                         not (mentioned_works & set(work_ids)) and
                         not (mentioned_cases & set(data.get("registry_case_ids", []))),
                         "not_applicable note has hold language broader than its disjoint owner scope")
            continue
        if item["disposition"] in {"active_hold", "correction_suppression", "overridden_for_this_release", "lifted"}:
            try:
                datetime.strptime(item.get("recorded_date", ""), "%Y-%m-%d")
            except (TypeError, ValueError):
                raise GuardError("a hold needs its dated owner instruction date") from None
            _require(isinstance(owner_note, dict) and owner_note.get("actor") == "owner" and
                     owner_note.get("action") in {"hold", "correction_suppression"} and
                     owner_note.get("date") == item["recorded_date"] and
                     isinstance(owner_note.get("work_ids"), list) and set(work_ids) <= set(owner_note["work_ids"]),
                     "hold disposition needs a matching dated owner marker for this paper")
            if item["disposition"] == "lifted":
                _require(owner_note.get("action") in {"hold", "correction_suppression"},
                         "lifted hold does not retain its original owner hold marker")
            else:
                expected_action = "correction_suppression" if item["disposition"] == "correction_suppression" else "hold"
                _require(owner_note.get("action") == expected_action,
                         "private hold disposition differs from the owner instruction marker")
            if owner_note.get("action") == "hold":
                _require(owner_note.get("category") in {"discretionary", "legal", "rights", "privacy", "technical", "other"} and
                         item.get("category") == owner_note.get("category"),
                         "hold category must match its owner instruction marker")
            elif item.get("category") not in (None, "correction_suppression"):
                raise GuardError("correction suppression has an invalid hold category")
        elif owner_note:
            _require(owner_note.get("action") in {"classify_no_hold", "lift", "override_discretionary", "authorize_correction"},
                     "owner note marker does not match its hold inventory disposition")
        elif HOLD_INTENT_RE.search(marker_free_note_text(text, OWNER_HOLD_MARKER, OWNER_HOLD_RE)):
            raise GuardError("an ambiguous legacy hold note needs a dated owner classification citing its hash")
        if item["disposition"] in {"lifted", "overridden_for_this_release"}:
            resolution = item.get("resolution_path")
            _require(resolution and resolution in actual,
                     "a lifted or overridden hold needs a current resolution note in the inventory")
            try:
                resolution_date = datetime.strptime(item.get("resolution_date", ""), "%Y-%m-%d")
                recorded_date = datetime.strptime(item.get("recorded_date", ""), "%Y-%m-%d")
            except (TypeError, ValueError):
                raise GuardError("a lifted or overridden hold needs a later dated resolution note") from None
            _require(resolution_date > recorded_date,
                     "a hold resolution note must postdate the owner hold")
            _require(isinstance(item.get("resolution_work_ids"), list) and
                     set(item["resolution_work_ids"]) == set(work_ids),
                     "a hold resolution note must explicitly identify this same public paper")
            _, resolution_marker = note_markers[resolution]
            expected_resolution = "lift" if item["disposition"] == "lifted" else "override_discretionary"
            _require(isinstance(resolution_marker, dict) and resolution_marker.get("actor") == "owner" and
                     resolution_marker.get("action") == expected_resolution and
                     resolution_marker.get("target_sha256") == item["sha256"] and
                     resolution_marker.get("target_path") == item["path"] and
                     resolution_marker.get("date") == item["resolution_date"] and
                     set(work_ids) <= set(resolution_marker.get("work_ids", [])),
                     "hold resolution note needs a matching dated owner instruction citing the exact hold hash")
            if item["disposition"] == "overridden_for_this_release":
                original_marker = note_markers[item["path"]][1]
                _require(original_marker.get("category") == "discretionary",
                         "only a discretionary hold can be overridden for a specific release")
        if item["disposition"] == "no_hold" and HOLD_INTENT_RE.search(
                marker_free_note_text(note_markers[item["path"]][0], OWNER_HOLD_MARKER, OWNER_HOLD_RE)):
            classification = [marker for _, marker in note_markers.values()
                              if isinstance(marker, dict) and marker.get("action") == "classify_no_hold" and
                              marker.get("target_sha256") == item["sha256"] and
                              marker.get("target_path") == item["path"] and
                              marker.get("date") and set(work_ids) <= set(marker.get("work_ids", []))]
            _require(classification,
                     "an ambiguous legacy note cannot be classified no_hold without an owner note citing its hash")
    _require(set(listed) == set(actual), "owner hold/review notes were added, removed or left unclassified")
    _require(all(listed[path]["sha256"] == digest for path, digest in actual.items()),
             "an owner hold/review note changed after it was classified")
    instruction = validate_owner_publish_instruction(control_root, data, record, actual)
    def later_than_hold(date_value: str, item: dict) -> bool:
        try:
            return datetime.strptime(date_value, "%Y-%m-%d") > datetime.strptime(item["recorded_date"], "%Y-%m-%d")
        except (TypeError, KeyError, ValueError):
            return False
    correction = any(c.get("publication_revision") for c in record["claims"])
    if new_public_claim_ids is None:
        new_public_claim_ids = {c.get("id") for c in record["claims"] if not c.get("publication_revision")}
    _require(new_public_claim_ids <= {c.get("id") for c in record["claims"]},
             "new public claim inventory contains a claim absent from the record")
    has_initial_content = not correction or bool(new_public_claim_ids)
    _require(not overridden or not has_initial_content or
             (instruction and all(later_than_hold(instruction["date"], item) for item in overridden)),
             "an overridden owner hold needs a later, dated case-specific owner publish instruction")
    if correction:
        for item in correction_suppression:
            resolution_path = item.get("resolution_path")
            resolution = note_markers.get(resolution_path, (None, None))[1]
            _require(resolution_path in actual and isinstance(resolution, dict) and
                     resolution.get("actor") == "owner" and resolution.get("action") == "authorize_correction" and
                     resolution.get("target_sha256") == item["sha256"] and
                     resolution.get("target_path") == item["path"] and
                     set(resolution.get("work_ids", [])) == set(work_ids) and
                     later_than_hold(resolution.get("date", ""), item),
                     "a later owner instruction is required to override a correction-suppression hold")
    elif correction_suppression:
        raise GuardError("a correction-suppression instruction cannot authorize an initial public release")
    non_discretionary = [item for item in active if item.get("category") != "discretionary"]
    if non_discretionary and has_initial_content:
        raise GuardError("a non-discretionary owner hold blocks this public release")
    if active and has_initial_content:
        raise GuardError("an active owner hold blocks the standing publication path")
    return bool(active)


def validate_held_correction_projection(repo: Path, deployed: dict, record: dict, data: dict) -> None:
    """Keep unrelated public lifecycle changes out of a required correction under a generic hold."""
    corrections = [claim.get("publication_revision") for claim in record.get("claims", [])
                   if claim.get("publication_revision")]
    _require(corrections, "held correction projection check requires a current publication revision")
    from_versions = {revision.get("from_version") for revision in corrections}
    _require(len(from_versions) == 1 and all(isinstance(value, str) for value in from_versions),
             "a held correction must start from one verified public version")
    public_id = record["public_id"]
    version = next(iter(from_versions))
    directory = f"content/published/records/{public_id}"
    raw = git_bytes(repo, deployed["source_commit"], f"{directory}/v{version}.json")
    manifest = git_bytes(repo, deployed["source_commit"],
                         f"content/published/releases/record__{public_id}__{version}.txt")
    _require(raw is not None and manifest is not None,
             "held correction prior version is absent from the verified live deployment")
    parse_manifest_bytes(manifest, public_id, version, raw)
    try:
        prior = json.loads(raw)
    except json.JSONDecodeError:
        raise GuardError("held correction prior version is malformed") from None
    _require(prior.get("work") == record.get("work"),
             "held correction changed the public paper identity")
    administrative = {"schema", "version", "released", "history", "versions", "changelog", "claims",
                      "kind", "headline", "correction", "outreach"}
    prior_projection = {key: value for key, value in prior.items() if key not in administrative}
    current_projection = {key: value for key, value in record.items() if key not in administrative}
    _require(current_projection == prior_projection,
             "active owner hold blocks unrelated record-level additions or changes bundled with a correction")
    changed_fields = {field for field in ("kind", "headline", "correction")
                      if record.get(field) != prior.get(field)}
    if record.get("headline") != prior.get("headline"):
        changed_statuses = {(claim.get("publication_revision") or {}).get("to_status")
                            for claim in record.get("claims", []) if claim.get("publication_revision")}
        headline = (record.get("headline") or "").casefold()
        _require(record.get("kind") == "status_correction" and
                 changed_statuses & {"unresolved", "rejected"} and
                 any(status in headline for status in changed_statuses & {"unresolved", "rejected"}),
                 "an updated headline under an active hold must state the corrected unresolved or rejected status")
    if record.get("correction") != prior.get("correction"):
        prior_note = (prior.get("correction") or {}).get("note")
        current_note = (record.get("correction") or {}).get("note")
        if prior_note is not None:
            _require(current_note == prior_note,
                     "an active hold does not permit rewriting public source-correction note text")
        else:
            _require(current_note == "A published source correction is recorded.",
                     "a new source-correction note under an active hold must use the fixed public wording")
    if changed_fields:
        review = data.get("held_correction_review")
        _require(isinstance(review, dict) and review.get("review_complete") is True and
                 review.get("record_sha256") == data.get("record_sha256") and
                 review.get("necessary_fields") == sorted(changed_fields) and
                 isinstance(review.get("rationale"), str) and review["rationale"].strip(),
                 "held correction changes to kind, headline or correction metadata need a hash-bound review naming necessary fields")
    for field in ("history", "versions", "changelog"):
        before = prior.get(field, [])
        after = record.get(field, [])
        _require(isinstance(before, list) and isinstance(after, list) and
                 len(after) == len(before) + 1 and after[:len(before)] == before,
                 f"active owner hold blocks unrelated edits to the prior public {field} history")
    prior_claims = {claim["id"]: claim for claim in prior.get("claims", [])
                    if isinstance(claim, dict) and isinstance(claim.get("id"), str)}
    current_claims = {claim["id"]: claim for claim in record.get("claims", [])
                      if isinstance(claim, dict) and isinstance(claim.get("id"), str)}
    retired_context = retired_context_claim_ids(prior_claims, current_claims)
    _require(set(prior_claims) - retired_context <= set(current_claims),
             "held correction removed a previously public claim")
    for claim_id, before in prior_claims.items():
        if claim_id in retired_context:
            continue
        after = current_claims[claim_id]
        _require(after.get("author_response") == before.get("author_response"),
                 f"active owner hold blocks a bundled author-position update for claim {claim_id}")
        if not after.get("publication_revision"):
            for field in ("evidence", "vor_check"):
                _require(after.get(field) == before.get(field),
                         f"active owner hold blocks a bundled {field} update for carried claim {claim_id}")
    _require(record.get("outreach") == prior.get("outreach"),
             "active owner hold blocks a bundled outreach update with a correction")


def retired_context_claim_ids(prior_claims: dict, current_claims: dict) -> set[str]:
    corrected_nonpositive = {claim_id for claim_id, claim in current_claims.items()
                             if (claim.get("publication_revision") or {}).get("to_status") in {"unresolved", "rejected"}}
    return {claim_id for claim_id, claim in prior_claims.items()
            if (claim.get("unresolved_context") or {}).get("anchor_claim_id") in corrected_nonpositive}


def retired_context_ids_from_deployed(repo: Path, deployed: dict, record: dict) -> tuple[set[str], dict | None]:
    public_id = record["public_id"]
    directory = f"content/published/records/{public_id}"
    paths = git(repo, "ls-tree", "-r", "--name-only", deployed["source_commit"], "--", directory).splitlines()
    versions = sorted({tuple(int(part) for part in version.split(".")): version
                       for path in paths if (match := versioned_record(path))
                       for rid, version in [match] if rid == public_id}.items())
    if not versions:
        return set(), None
    version = versions[-1][1]
    raw = git_bytes(repo, deployed["source_commit"], f"{directory}/v{version}.json")
    manifest = git_bytes(repo, deployed["source_commit"],
                         f"content/published/releases/record__{public_id}__{version}.txt")
    _require(raw is not None and manifest is not None,
             "latest deployed public version or manifest is unavailable for context retirement")
    parse_manifest_bytes(manifest, public_id, version, raw)
    try:
        prior = json.loads(raw)
    except json.JSONDecodeError:
        raise GuardError("latest deployed public version is malformed") from None
    prior_claims = {claim["id"]: claim for claim in prior.get("claims", [])
                    if isinstance(claim, dict) and isinstance(claim.get("id"), str)}
    current_claims = {claim["id"]: claim for claim in record.get("claims", [])
                      if isinstance(claim, dict) and isinstance(claim.get("id"), str)}
    retired = retired_context_claim_ids(prior_claims, current_claims)
    prior_correction = prior.get("correction")
    prior_correction_claims = set((prior_correction or {}).get("claims", []))
    return retired & prior_correction_claims, prior_correction


def validate_release_checks(data: dict, record: dict) -> None:
    auths = data.get("claim_authorizations")
    _require(isinstance(auths, dict), "private release record needs claim_authorizations")
    claim_ids = {claim.get("id") for claim in record.get("claims", [])}
    _require(set(auths) == claim_ids, "every public claim needs exactly one release authorization")
    allowed = AUTHORIZATIONS
    _require(all(x in allowed for x in auths.values()), "unknown claim authorization in private release record")
    correction = any(c.get("publication_revision") for c in record["claims"])
    initial_open = False
    for claim in record["claims"]:
        auth = auths[claim["id"]]
        result = claim["result"]
        if claim.get("publication_revision"):
            _require(auth == "standing_correction", "a prior public Open correction needs standing_correction authorization")
        elif claim.get("status_provenance") and correction:
            _require(auth == "standing_correction",
                     "a carried corrected status in a corrective version uses standing_correction authorization")
        elif claim.get("status_provenance"):
            _require(auth == "case_publish",
                     "a later non-corrective version carrying corrected status needs case-specific authorization")
        elif result["outcome"] == "unresolved":
            _require(auth == "context_only" and claim.get("unresolved_context"),
                     "an unresolved claim must be explicitly authorized as context only")
        elif result["outcome"] == "defect_found" and result.get("status") == "open":
            _require(auth in {"standing_open", "case_publish"}, "an Open claim has no applicable authorization")
            initial_open = initial_open or not claim.get("publication_revision")
        else:
            _require(auth == "case_publish", "new Confirmed positives and negative audits retain case-specific authorization")
        if (claim.get("publication_revision") and
                claim["publication_revision"].get("from_status") in {"unresolved", "rejected"} and
                claim["publication_revision"].get("to_status") in {"open", "confirmed"}):
            initial_open = True

    checks = data.get("release_checks")
    _require(isinstance(checks, dict), "private release record needs release_checks")
    required = {"canonical_review_complete", "rights_privacy_clear", "public_presentation_ready"}
    if initial_open:
        required.add("initial_open_gates_complete")
    if correction:
        required |= {"correction_evidence_reviewed", "current_status_and_scope_checked"}
    if any(x == "case_publish" for x in auths.values()):
        required.add("case_publish_instruction_verified")
    allowed_checks = {"canonical_review_complete", "rights_privacy_clear", "public_presentation_ready",
                      "initial_open_gates_complete", "correction_evidence_reviewed",
                      "current_status_and_scope_checked", "case_publish_instruction_verified"}
    _require(set(checks) <= allowed_checks, "private release record contains an unsupported release check")
    _require(all(checks.get(k) is True for k in required),
             "private release record is missing a required release check")
    if any(x == "case_publish" for x in auths.values()):
        instruction = data.get("publish_instruction")
        try:
            datetime.strptime(instruction.get("date", ""), "%Y-%m-%d")
        except (AttributeError, TypeError, ValueError):
            raise GuardError("case-specific publication authorization needs the owner's dated publish instruction") from None
        _require(isinstance(instruction, dict) and set(instruction) == {"date", "source_path", "source_sha256"} and
                 isinstance(instruction.get("source_path"), str) and
                 SHA_RE.fullmatch(instruction.get("source_sha256", "")) is not None,
                 "case-specific publication authorization needs a structured, hashed owner publish note")


def current_deployment(deployment_dir: Path, control_root: Path | None = None) -> dict:
    deployment_dir = deployment_dir.resolve()
    resolved_control = control_root.resolve() if control_root is not None else deployment_dir.parents[1]
    expected_deployment = (resolved_control / "05_Website" / "Deployment").resolve()
    _require(deployment_dir == expected_deployment,
             "deployment evidence directory must be exactly the selected control root's 05_Website/Deployment")
    candidates = []
    documents = markdown_files(deployment_dir)
    unmarked_reports = []
    for path in documents:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        blocks = marker_blocks(text, DEPLOYMENT_MARKER, DEPLOYMENT_RE, "deployment evidence")
        if not blocks:
            report = DATED_DEPLOYMENT_REPORT_RE.match(path.name)
            if report:
                try:
                    unmarked_reports.append((datetime.strptime(report.group(1), "%Y-%m-%d").date(), path))
                except ValueError:
                    raise GuardError("a dated deployment report has an invalid date") from None
            continue
        try:
            data = json.loads(blocks[0].group(1))
        except json.JSONDecodeError:
            raise GuardError("a deployment evidence block is malformed") from None
        try:
            when = datetime.fromisoformat(data.get("verified_at", "").replace("Z", "+00:00"))
        except ValueError:
            raise GuardError("deployment verified_at must be an ISO timestamp") from None
        _require(when.utcoffset() is not None, "deployment verified_at must include a timezone")
        candidates.append((when, data))
    _require(candidates, "there is no machine-readable deployment record proving the current live publication state")
    latest_at = max(when for when, _ in candidates)
    latest = [data for when, data in candidates if when == latest_at]
    states = {json.dumps(data, sort_keys=True, separators=(",", ":")) for data in latest}
    _require(len(states) == 1, "latest deployment evidence is ambiguous")
    state = latest[0]
    _require(set(state) == {"source_commit", "live_audit", "verified_at", "run_id", "audit_evidence",
                            "release_records_inventory"},
             "deployment evidence needs an exact source, audit, run and verification record")
    _require(state.get("live_audit") == "PASS", "the latest deployment record does not have a passing live-site audit")
    _require(re.fullmatch(r"[0-9a-f]{40}", state.get("source_commit", "")) is not None,
             "deployment record needs its exact source commit")
    _require(isinstance(state.get("run_id"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", state["run_id"]) is not None,
             "deployment record needs its exact run_id")
    evidence = state.get("audit_evidence")
    _require(isinstance(evidence, dict) and set(evidence) == {"path", "sha256"} and
             isinstance(evidence.get("path"), str) and SHA_RE.fullmatch(evidence.get("sha256", "")) is not None,
             "deployment record needs a hashed live-audit evidence path")
    pure = PurePosixPath(evidence["path"])
    _require(not pure.is_absolute() and ".." not in pure.parts and "\\" not in evidence["path"],
             "live-audit evidence path must be a safe path inside Deployment")
    audit_path = (deployment_dir / Path(*pure.parts)).resolve()
    try:
        audit_path.relative_to(deployment_dir.resolve())
    except ValueError:
        raise GuardError("live-audit evidence path escapes Deployment") from None
    try:
        audit_bytes = audit_path.read_bytes()
    except OSError:
        raise GuardError("the hashed live-audit evidence file is unavailable") from None
    _require(sha256(audit_bytes) == evidence["sha256"], "live-audit evidence changed after the deployment record")
    try:
        audit_text = audit_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise GuardError("hashed live-audit evidence is not UTF-8 text") from None
    results = re.findall(r"^RESULT:\s*(.*?)\s*$", audit_text, flags=re.MULTILINE)
    _require(results == ["PASS"], "hashed live-audit evidence must contain exactly RESULT: PASS")
    inventory = state.get("release_records_inventory")
    _require(isinstance(inventory, list), "deployment record needs its private release-record inventory")
    actual_inventory = {item["path"]: item["sha256"] for item in release_records_inventory(resolved_control)}
    seen_inventory = set()
    for item in inventory:
        _require(isinstance(item, dict) and set(item) == {"path", "sha256"} and
                 isinstance(item.get("path"), str) and SHA_RE.fullmatch(item.get("sha256", "")) is not None and
                 item["path"] not in seen_inventory,
                 "deployment release-record inventory has an invalid shape")
        safe_control_note_path(deployment_dir.parents[1], item["path"])
        seen_inventory.add(item["path"])
        _require(actual_inventory.get(item["path"]) == item["sha256"],
                 "a private release record used by the deployment changed or disappeared after its live audit")
    try:
        verified = datetime.fromisoformat(state["verified_at"].replace("Z", "+00:00"))
    except ValueError:
        raise GuardError("deployment verified_at must be an ISO timestamp") from None
    _require(not any(date >= verified.date() for date, _ in unmarked_reports),
             "a newer dated deployment or live-audit report has no machine-readable passing deployment marker")
    return state


def validate_correction_bases(repo: Path, base: str, deployed: dict, record: dict) -> set[str]:
    deployed_sha = deployed["source_commit"]
    _require(git_success(repo, "merge-base", "--is-ancestor", deployed_sha, base),
             "the verified deployment commit is not an ancestor of the release base")
    public_id = record["public_id"]
    directory = f"content/published/records/{public_id}"
    paths = git(repo, "ls-tree", "-r", "--name-only", deployed_sha, "--", directory).splitlines()
    deployed_versions = sorted({tuple(int(part) for part in version.split(".")): version
                                for path in paths if (match := versioned_record(path))
                                for rid, version in [match] if rid == public_id}.items())

    def status_of(claim: dict) -> str:
        revision = claim.get("publication_revision") or {}
        if revision:
            return revision.get("to_status", "")
        provenance = claim.get("status_provenance") or {}
        if provenance:
            return provenance.get("status", "")
        outcome = claim.get("result", {}).get("outcome")
        if outcome == "defect_found":
            return claim["result"].get("status", "")
        if outcome == "unresolved":
            return "unresolved"
        if outcome == "no_defect_found":
            return "negative_audit"
        return ""

    def deployed_version(version: str) -> dict:
        path = f"{directory}/v{version}.json"
        raw = git_bytes(repo, deployed_sha, path)
        manifest_path = f"content/published/releases/record__{public_id}__{version}.txt"
        manifest = git_bytes(repo, deployed_sha, manifest_path)
        _require(raw is not None and manifest is not None,
                 f"correction lineage version {version} is absent from the verified live deployment")
        parse_manifest_bytes(manifest, public_id, version, raw)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise GuardError(f"correction lineage version {version} is malformed") from None
        _require(value.get("public_id") == public_id and value.get("version") == version,
                 "a deployed correction lineage record has mismatched identity")
        return value

    prior_claims: dict[str, dict] = {}
    if deployed_versions:
        latest_prior = deployed_version(deployed_versions[-1][1])
        prior_claims = {claim["id"]: claim for claim in latest_prior.get("claims", [])
                        if isinstance(claim, dict) and isinstance(claim.get("id"), str)}
    prior_claim_ids = set(prior_claims)
    current_claims = {claim["id"]: claim for claim in record.get("claims", [])
                      if isinstance(claim, dict) and isinstance(claim.get("id"), str)}
    retired_context = retired_context_claim_ids(prior_claims, current_claims)
    _require(prior_claim_ids - retired_context <= set(current_claims),
             "a new public version cannot remove a previously public claim")
    lifecycle_fields = {"author_response", "evidence", "vor_check", "publication_revision", "status_provenance"}
    for claim_id, prior_claim in prior_claims.items():
        if claim_id in retired_context:
            continue
        current_claim = current_claims[claim_id]
        if current_claim.get("publication_revision"):
            continue
        prior_content = {key: value for key, value in prior_claim.items() if key not in lifecycle_fields}
        current_content = {key: value for key, value in current_claim.items() if key not in lifecycle_fields}
        _require(current_content == prior_content,
                 f"previously public claim {claim_id} changed scientific content without publication_revision")
        prior_correction = prior_claim.get("publication_revision") or prior_claim.get("status_provenance")
        expected_provenance = None
        if prior_correction:
            revision_version = (prior_correction.get("revision_version") if prior_claim.get("status_provenance")
                               else latest_prior["version"])
            expected_provenance = {"status": status_of(prior_claim), "revision_version": revision_version}
        _require(current_claim.get("status_provenance") == expected_provenance,
                 f"previously public claim {claim_id} does not accurately carry forward its corrective status")

    for claim in record["claims"]:
        revision = claim.get("publication_revision")
        if not revision:
            continue
        version = revision["from_version"]
        _require(deployed_versions and deployed_versions[-1][1] == version,
                 "a correction must start from the latest public version in the verified live deployment")
        json_path = f"{directory}/v{version}.json"
        manifest_path = f"content/published/releases/record__{public_id}__{version}.txt"
        prior_base = git_bytes(repo, base, json_path)
        prior_deployed = git_bytes(repo, deployed_sha, json_path)
        manifest_base = git_bytes(repo, base, manifest_path)
        manifest_deployed = git_bytes(repo, deployed_sha, manifest_path)
        _require(prior_base is not None and prior_deployed is not None and prior_base == prior_deployed,
                 "correction prior version was not present unchanged in the verified live deployment")
        _require(sha256(prior_base) == revision["prior_sha256"],
                 "correction does not identify the exact prior public JSON bytes")
        _require(manifest_base is not None and manifest_deployed is not None and manifest_base == manifest_deployed,
                 "correction prior manifest was not present unchanged in the verified live deployment")
        parse_manifest_bytes(manifest_base, public_id, version, prior_base)
        prior = json.loads(prior_base)
        prior_claim = next((c for c in prior.get("claims", []) if c.get("id") == claim["id"]), None)
        _require(prior.get("work") == record.get("work") and prior_claim is not None and
                 status_of(prior_claim) == revision.get("from_status") and
                 revision.get("to_status") == status_of(claim),
                 "correction must continue the same public claim, paper and immediately prior status")

        cursor = prior
        seen = set()
        while True:
            cursor_version = cursor.get("version")
            _require(cursor_version not in seen, "correction lineage contains a cycle")
            seen.add(cursor_version)
            cursor_claim = next((item for item in cursor.get("claims", []) if item.get("id") == claim["id"]), None)
            _require(cursor_claim is not None and cursor.get("work") == record.get("work"),
                     "correction lineage changed the public claim or paper")
            provenance = cursor_claim.get("status_provenance")
            if provenance:
                origin_version = provenance.get("revision_version")
                _require(origin_version in {value for _, value in deployed_versions},
                         "correction lineage references a missing carried-status origin")
                origin = deployed_version(origin_version)
                origin_claim = next((item for item in origin["claims"] if item.get("id") == claim["id"]), None)
                _require(origin_claim is not None and origin_claim.get("publication_revision") and
                         status_of(origin_claim) == provenance.get("status") == status_of(cursor_claim),
                         "carried correction status does not match its archived correction origin")
                cursor = origin
                continue
            cursor_revision = cursor_claim.get("publication_revision")
            if not cursor_revision:
                _require(cursor.get("schema") in {2, 3} and status_of(cursor_claim) == "open",
                         "corrective versions must trace to an originally public Open finding")
                break
            from_version = cursor_revision.get("from_version")
            _require(from_version in {value for _, value in deployed_versions},
                     "correction lineage references a version absent from the verified live deployment")
            cursor_order = next((i for i, (_, value) in enumerate(deployed_versions) if value == cursor_version), None)
            _require(cursor_order is not None and cursor_order > 0 and
                     deployed_versions[cursor_order - 1][1] == from_version,
                     "correction lineage skips a previously public version")
            ancestor = deployed_version(from_version)
            ancestor_claim = next((item for item in ancestor.get("claims", []) if item.get("id") == claim["id"]), None)
            _require(ancestor_claim is not None and status_of(ancestor_claim) == cursor_revision.get("from_status") and
                     cursor_revision.get("to_status") == status_of(cursor_claim),
                     "correction lineage status or source hash does not match the archived prior version")
            _require(cursor_revision.get("prior_sha256") == sha256(git_bytes(
                repo, deployed_sha, f"{directory}/v{from_version}.json") or b""),
                     "correction lineage does not identify the exact archived prior bytes")
            cursor = ancestor
    return prior_claim_ids


def parse_manifest_bytes(data: bytes, public_id: str, version: str, record_bytes: bytes) -> None:
    lines = set(data.decode("utf-8").splitlines())
    expected = {"as-stated-release v1", "kind: record", f"id: {public_id}", f"version: {version}",
                f"sha256: {sha256(record_bytes)}"}
    _require(lines == expected and len(data.decode("utf-8").splitlines()) == len(expected),
             "prior public release manifest does not match its historical record bytes")


def validate_new_records(repo: Path, base: str, added: list[str], control_root: Path, deployment_dir: Path) -> None:
    records = [path for path in added if versioned_record(path)]
    deployed = current_deployment(deployment_dir, control_root)
    new_id_versions = [versioned_record(path) for path in records]
    validate_version_monotonicity(repo, deployed["source_commit"], [item for item in new_id_versions if item])
    validate_release_control_freshness(control_root, deployed, [item for item in new_id_versions if item])
    _require(git_success(repo, "merge-base", "--is-ancestor", deployed["source_commit"], base),
             "the verified deployed source is not an ancestor of the release base")
    if not records:
        return
    for rel in records:
        path = repo / Path(rel)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise GuardError(f"new public record is unreadable: {Path(rel).name}") from None
        identity = versioned_record(rel)
        _require((record.get("public_id"), record.get("version")) == identity,
                 "new record filename does not match its public identity")
        _require(record.get("schema") == 3, "new public record versions must use schema 3")
        rid, version = identity
        manifest = repo / "content" / "published" / "releases" / f"record__{rid}__{version}.txt"
        record_bytes = path.read_bytes()
        parse_manifest(manifest, rid, version, record_bytes)
        data = parse_release_marker(control_root, rid, version)
        validate_release_control_shape(data, record)
        _require(data.get("record_sha256") == sha256(record_bytes),
                 "private release review does not lock the exact public record bytes")
        validate_release_checks(data, record)
        prior_claim_ids = validate_correction_bases(repo, base, deployed, record)
        retired_context, prior_public_correction = retired_context_ids_from_deployed(repo, deployed, record)
        prior_status_event_ids = {}
        for claim in record.get("claims", []):
            revision = claim.get("publication_revision") or {}
            if (revision.get("from_status") in {"unresolved", "rejected"} and
                    revision.get("to_status") in {"open", "confirmed"}):
                prior_release = parse_release_marker(control_root, record["public_id"], revision["from_version"])
                prior_review = prior_release.get("claim_reviews", {}).get(claim.get("id"), {})
                status_event_id = prior_review.get("status_event_id")
                _require(isinstance(status_event_id, str) and status_event_id,
                         f"restored positive claim {claim.get('id')} needs its prior public status event")
                prior_status_event_ids[claim["id"]] = status_event_id
        validate_canonical(control_root, data, record, retired_context, prior_status_event_ids,
                           prior_public_correction)
        current_claim_ids = {claim.get("id") for claim in record.get("claims", [])}
        active_hold = validate_holds(control_root, data, record, current_claim_ids - prior_claim_ids)
        if active_hold and any(claim.get("publication_revision") for claim in record["claims"]):
            validate_held_correction_projection(repo, deployed, record, data)


def run_fresh_live_audit(deployment_dir: Path) -> None:
    script = deployment_dir / "live_site_audit.py"
    _require(script.is_file(), "the documented live-site audit script is unavailable")
    try:
        result = subprocess.run([sys.executable, str(script)], cwd=deployment_dir, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise GuardError("the required on-demand live-site audit could not complete") from None
    combined = result.stdout + "\n" + result.stderr
    results = re.findall(r"^RESULT:\s*(.*?)\s*$", combined, flags=re.MULTILINE)
    _require(result.returncode == 0 and results == ["PASS"],
             "the on-demand live-site audit did not return exactly RESULT: PASS")


def pre_push(repo: Path, remote: str, branch: str, control_root: Path | None, deployment_dir: Path | None) -> str:
    dirty = git(repo, "status", "--porcelain", "--untracked-files=normal")
    _require(not dirty, "worktree has staged, unstaged or untracked changes")
    target = f"refs/remotes/{remote}/{branch}"
    git(repo, "fetch", "--quiet", "--no-tags", remote, f"+refs/heads/{branch}:{target}")
    local_ref = git(repo, "rev-parse", target)
    advertised = git(repo, "ls-remote", remote, f"refs/heads/{branch}").split()
    _require(advertised and advertised[0] == local_ref,
             "the fetched branch does not match the actual remote; fetch again and reconcile")
    head = git(repo, "rev-parse", "HEAD")
    _require(git_success(repo, "merge-base", "--is-ancestor", local_ref, head),
             "local checkout is stale or divergent from the remote branch")
    check_append_only(repo, local_ref)
    check_public_history(repo, head)
    _require(control_root is not None and deployment_dir is not None,
             "a push needs the private control root and current deployment evidence")
    deployed = current_deployment(deployment_dir, control_root)
    deployed_sha = deployed["source_commit"]
    _require(git_success(repo, "merge-base", "--is-ancestor", deployed_sha, local_ref),
             "the verified live source is not an ancestor of the actual remote branch")
    pending_public = check_append_only(repo, deployed_sha)
    validate_new_records(repo, local_ref, pending_public, control_root, deployment_dir)
    run_fresh_live_audit(deployment_dir)
    return head


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardError(message)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    ci = sub.add_parser("check-append-only", help="CI guard against rewriting published version history")
    ci.add_argument("--base", required=True, help="event base or pull-request base commit")
    local = sub.add_parser("pre-push", help="local freshness, append-only, authorization and owner-hold preflight")
    local.add_argument("--remote", default="origin")
    local.add_argument("--branch", default="main")
    local.add_argument("--control-root", type=Path)
    local.add_argument("--deployment-dir", type=Path)
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parent
    try:
        if args.command == "check-append-only":
            changed = check_append_only(repo, args.base)
            head = git(repo, "rev-parse", "HEAD")
            check_public_history(repo, head)
            print(f"immutable public history: PASS ({len(changed)} supported additions; full pinned history checked)")
        else:
            head = pre_push(repo, args.remote, args.branch,
                            args.control_root.resolve() if args.control_root else None,
                            args.deployment_dir.resolve() if args.deployment_dir else None)
            print(f"pre-push checks: PASS at {head}")
        return 0
    except GuardError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
