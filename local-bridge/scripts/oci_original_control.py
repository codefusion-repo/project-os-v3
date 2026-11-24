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
    packages = {(p["Name"], p["Version"]) for p in os_rows[0]["Packages"]}
    if len(packages) != len(os_rows[0]["Packages"]):
        raise ValueError("Duplicate OS package")
    for row in report["Results"]:
        if row.get("Class") not in ("os-pkgs", "lang-pkgs"):
            raise ValueError("Unexpected result class")
        for v in row.get("Vulnerabilities") or []:
            if not all(isinstance(v.get(k), str) and v[k] for k in ("VulnerabilityID", "PkgName", "InstalledVersion", "Severity")):
                raise ValueError("Incomplete finding")
            if row.get("Class") == "os-pkgs" and (v["PkgName"], v["InstalledVersion"]) not in packages:
                raise ValueError("Finding not in OS inventory")
    def records(rows):
        return collections.Counter(tuple(r.get(k) for k in FIELDS) for r in rows)
    if (result["candidate_gate"] != "BLOCKED" or result["counts"] != lock["counts"]
            or len(lock["high_critical"]) != 53 or records(result["high_critical"]) != records(lock["high_critical"])):
        raise ValueError("Original rejection findings changed")
    return {"control": "ORIGINAL_EXPECTED_REJECTION_PASS", "candidate_gate": "BLOCKED",
            "approved": False, "image": IMAGE, "scanner_exit": scanner_rc, "audit_exit": audit_rc,
            "counts": result["counts"], "os_packages": len(packages)}


def load(path, limit):
    raw = Path(path).read_bytes()
    if not raw or len(raw) > limit:
        raise ValueError("Missing or oversized JSON")
    return raw, json.loads(raw, object_pairs_hook=unique)


if __name__ == "__main__":
    report_path, lock_path, scanner, audit, diagnostics, db_path = sys.argv[1:]
    raw, report = load(report_path, 20_000_000)
    _, lock = load(lock_path, 100_000)
    db_raw, db = load(db_path, 65536)
    result = evaluate(report, lock, int(Path(scanner).read_text()), int(Path(audit).read_text()), Path(diagnostics).read_text())
    result["db"] = validate_db(db, datetime.now(timezone.utc))
    result["db_metadata_sha256"] = hashlib.sha256(db_raw).hexdigest()
    result["report_sha256"] = hashlib.sha256(raw).hexdigest()
    print("OCI_CONTROL_DECISION", json.dumps(result, sort_keys=True))
