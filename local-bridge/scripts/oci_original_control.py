"""Verify a successful scan and the exact historical Debian rejection, not an approved image."""
import collections
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oci_control import unique, validate_db
from oci_compare import summarize

IMAGE = "docker.io/library/python@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b"
FIELDS = ("VulnerabilityID", "PkgName", "InstalledVersion", "FixedVersion", "Severity")


def fingerprint(rows):
    canonical = sorted(json.dumps(row, ensure_ascii=True, separators=(",", ":")) for row in rows)
    return hashlib.sha256(("\n".join(canonical) + "\n").encode()).hexdigest()


def report_records(report):
    findings, inventory = [], []
    for row in report["Results"]:
        cls, typ = row["Class"], row["Type"]
        if (cls, typ) not in (("os-pkgs", "debian"), ("lang-pkgs", "python-pkg")):
            raise ValueError("Unexpected result class/type")
        packages = {}
        for p in row["Packages"]:
            identifier = p["Identifier"]
            uid = identifier["UID"]
            if not uid or uid in packages or not identifier["PURL"]:
                raise ValueError("Missing or duplicate package identity")
            epoch, release = p.get("Epoch", 0), p.get("Release", "")
            if type(epoch) is not int or epoch < 0:
                raise ValueError("Invalid package epoch")
            version = (str(epoch) + ":" if epoch else "") + p["Version"] + ("-" + release if release else "")
            packages[uid] = (p, version)
            inventory.append([cls, typ, p.get("ID", ""), p["Name"], epoch, p["Version"], release, identifier["PURL"]])
        if not packages:
            raise ValueError("Empty package inventory")
        for v in row.get("Vulnerabilities") or []:
            if not all(isinstance(v.get(k), str) and v[k] for k in ("VulnerabilityID", "PkgName", "InstalledVersion", "Severity")):
                raise ValueError("Incomplete finding")
            identifier = v["PkgIdentifier"]
            if identifier["UID"] not in packages:
                raise ValueError("Finding not in package inventory")
            p, version = packages[identifier["UID"]]
            if (p["Identifier"] != identifier or p["Name"] != v["PkgName"] or version != v["InstalledVersion"]
                    or (cls == "os-pkgs" and (p["ID"] != v["PkgID"] or p["ID"] != p["Name"] + "@" + version))):
                raise ValueError("Finding package identity mismatch")
            findings.append([cls, typ, *(v.get(k) for k in FIELDS)])
    return findings, inventory


def evaluate(report, lock, scanner_rc, audit_rc, diagnostics):
    if scanner_rc != 0 or audit_rc != 1:
        raise ValueError("Expected successful scan and rejected audit")
    if diagnostics.splitlines().count("OCI BLOCKED: EOL or high/critical findings require review") != 1:
        raise ValueError("Expected original rejection diagnostic missing")
    if lock["image"] != IMAGE or report.get("ArtifactName") != IMAGE:
        raise ValueError("Original image identity mismatch")
    if report.get("SchemaVersion") != 2 or report.get("ArtifactType") != "container_image":
        raise ValueError("Unexpected report schema")
    os_info = report["Metadata"]["OS"]
    if os_info.get("Family") != "debian" or os_info.get("Name") != "13.8" or os_info.get("EOSL") is True:
        raise ValueError("Unexpected original OS or EOL")
    result = summarize(report, IMAGE)
    os_rows = [r for r in report["Results"] if r.get("Class") == "os-pkgs"]
    if len(os_rows) != 1 or os_rows[0].get("Type") != "debian" or not os_rows[0].get("Packages"):
        raise ValueError("Original OS inventory missing")
    all_findings, inventory = report_records(report)
    if (len(all_findings) != lock["findings_count"] or fingerprint(all_findings) != lock["findings_sha256"]
            or len(inventory) != lock["inventory_count"] or fingerprint(inventory) != lock["inventory_sha256"]):
        raise ValueError("Original complete inventory or finding identities changed")
    def records(rows):
        return collections.Counter(tuple(r.get(k) for k in FIELDS) for r in rows)
    if (result["candidate_gate"] != "BLOCKED" or result["counts"] != lock["counts"]
            or len(lock["high_critical"]) != 53 or records(result["high_critical"]) != records(lock["high_critical"])):
        raise ValueError("Original rejection findings changed")
    return {"control": "ORIGINAL_EXPECTED_REJECTION_PASS", "candidate_gate": "BLOCKED",
            "approved": False, "image": IMAGE, "scanner_exit": scanner_rc, "audit_exit": audit_rc,
            "counts": result["counts"], "os_packages": len(os_rows[0]["Packages"]), "inventory_count": len(inventory),
            "findings_sha256": fingerprint(all_findings), "inventory_sha256": fingerprint(inventory)}


def load(path, limit):
    raw = Path(path).read_bytes()
    if not raw or len(raw) > limit:
        raise ValueError("Missing or oversized JSON")
    return raw, json.loads(raw, object_pairs_hook=unique)


def historical(path, lock):
    import gzip
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != "2527d03707a2c3f94cf42b6ec8c47499934032560396c5e17d72acbcb9e8b755":
        raise ValueError("Historical evidence checksum mismatch")
    data = json.loads(gzip.decompress(raw), object_pairs_hook=unique)
    if data["source_artifact"] != lock["source_artifact"] or data["source_report_sha256"] != lock["source_report_sha256"]:
        raise ValueError("Historical provenance mismatch")
    db_raw = data["db_metadata_raw"].encode()
    if hashlib.sha256(db_raw).hexdigest() != lock["source_db_metadata_sha256"]:
        raise ValueError("Historical DB checksum mismatch")
    report = data["report"]
    validate_db(json.loads(db_raw, object_pairs_hook=unique),
                datetime.fromisoformat(report["CreatedAt"].replace("Z", "+00:00")))
    return evaluate(report, lock, data["scanner_exit"], data["audit_exit"], data["diagnostics"])


def fresh(report, lock, scanner_rc, audit_rc, diagnostics):
    if scanner_rc != 0 or report.get("ArtifactName") != IMAGE or lock["image"] != IMAGE:
        raise ValueError("Fresh scan failure or identity mismatch")
    if report.get("SchemaVersion") != 2 or report.get("ArtifactType") != "container_image":
        raise ValueError("Unexpected fresh schema")
    os_info = report["Metadata"]["OS"]
    if os_info.get("Family") != "debian" or os_info.get("Name") != "13.8":
        raise ValueError("Unexpected original OS")
    findings, inventory = report_records(report)
    if len(inventory) != lock["inventory_count"] or fingerprint(inventory) != lock["inventory_sha256"]:
        raise ValueError("Fresh original inventory changed")
    result = summarize(report, IMAGE)
    blocked = result["candidate_gate"] == "BLOCKED"
    expected = ("OCI BLOCKED: EOL or high/critical findings require review" if blocked
                else "OCI HIGH/CRITICAL GATE PASS; lower severities still require review")
    if audit_rc != int(blocked) or diagnostics.splitlines().count(expected) != 1:
        raise ValueError("Fresh audit result inconsistent")
    return {"control": "ORIGINAL_FRESH_EVIDENCE", "approved": False,
            "candidate_gate": "BLOCKED", "scanner_gate": result["candidate_gate"],
            "image": IMAGE, "scanner_exit": scanner_rc, "audit_exit": audit_rc,
            "counts": result["counts"], "findings_sha256": fingerprint(findings),
            "inventory_sha256": fingerprint(inventory),
            "finding_drift": fingerprint(findings) != lock["findings_sha256"]}


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--historical":
        _, lock = load(sys.argv[3], 100_000)
        print("OCI_HISTORICAL_DECISION", json.dumps(historical(sys.argv[2], lock), sort_keys=True))
    else:
        report_path, lock_path, scanner, audit, diagnostics, db_path = sys.argv[1:]
        raw, report = load(report_path, 20_000_000)
        _, lock = load(lock_path, 100_000)
        db_raw, db = load(db_path, 65536)
        result = fresh(report, lock, int(Path(scanner).read_text()), int(Path(audit).read_text()), Path(diagnostics).read_text())
        result["db"] = validate_db(db, datetime.now(timezone.utc))
        result["db_metadata_sha256"] = hashlib.sha256(db_raw).hexdigest()
        result["report_sha256"] = hashlib.sha256(raw).hexdigest()
        print("OCI_CONTROL_DECISION", json.dumps(result, sort_keys=True))
