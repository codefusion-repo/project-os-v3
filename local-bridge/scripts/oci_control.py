"""CI evidence gate: rejected residual is a negative control, never an approved image."""
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

from oci_compare import summarize

RESIDUAL = "sha256:9e42be33d3f4b762175eb8c0f669e58d797219490c42a42017855256ce72deae"
FIXTURE = "sha256:0c8e915d597f997fc64b7ddfc8e25de93873d06126faccbee1f46446deb30cfb"
# Reviewed observations in both residual runners of run 45463055060.
# Any drift, including new lower-severity findings, requires review.
EXPECTED = collections.Counter([
    ("GHSA-6q48-6c7w-9gw2", "certifi", "2026.6.17", "CRITICAL"),
    ("CVE-2026-114613", "msgpack", "1.1.2", "HIGH"),
    ("GHSA-6v7p-g79w-8964", "msgpack", "1.1.2", "HIGH"),
    ("CVE-2025-47273", "setuptools", "70.3.0", "HIGH"),
    ("CVE-2026-97687", "urllib3", "2.7.0", "HIGH"),
    ("CVE-2026-97689", "urllib3", "2.7.0", "HIGH"),
    ("CVE-2026-59890", "setuptools", "70.3.0", "MEDIUM"),
    ("CVE-2026-97688", "urllib3", "2.7.0", "MEDIUM"),
    ("GHSA-xmj3-9gf7-h52w", "setuptools", "70.3.0", "LOW"),
])


def unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def evaluate(report, image, manifest, mode, expected_inventory, scanner_rc):
    if scanner_rc != 0:
        raise ValueError("Scanner failed")
    locked = {"residual": RESIDUAL, "fixture-only": FIXTURE}.get(mode)
    if locked is None or manifest != locked or not image.endswith("@" + locked):
        raise ValueError("Unexpected candidate identity")
    if report.get("SchemaVersion") != 2 or report.get("ArtifactType") != "container_image":
        raise ValueError("Unexpected report schema or artifact type")
    result = summarize(report, image)
    if result["os"] != "alpine" or result["os_version"] != "3.24.4" or result["eosl"]:
        raise ValueError("Unexpected OS or EOL")
    os_rows = [r for r in report["Results"] if r.get("Class") == "os-pkgs"]
    if len(os_rows) != 1 or os_rows[0].get("Type") != "alpine":
        raise ValueError("Unexpected OS inventory")
    expected = expected_inventory.splitlines()
    actual = [p["Name"] + "-" + p["Version"] for p in os_rows[0]["Packages"]]
    if not expected or len(expected) != len(set(expected)) or collections.Counter(actual) != collections.Counter(expected):
        raise ValueError("OS package coverage mismatch")
    findings = collections.Counter()
    for row in report["Results"]:
        if row.get("Class") not in ("os-pkgs", "lang-pkgs"):
            raise ValueError("Unexpected result class")
        if row.get("Misconfigurations") or row.get("Secrets") or row.get("Licenses"):
            raise ValueError("Unexpected scan type")
        if "Vulnerabilities" in row and row["Vulnerabilities"] is not None and not isinstance(row["Vulnerabilities"], list):
            raise ValueError("Invalid findings list")
        for v in row.get("Vulnerabilities") or []:
            key = tuple(v[k] for k in ("VulnerabilityID", "PkgName", "InstalledVersion", "Severity"))
            if not all(isinstance(x, str) and x for x in key):
                raise ValueError("Incomplete finding")
            if mode == "residual" and (row.get("Class") != "lang-pkgs" or row.get("Type") != "python-pkg"):
                raise ValueError("Unexpected residual finding class")
            findings[key] += 1
    if mode == "residual":
        if result["candidate_gate"] != "BLOCKED" or findings != EXPECTED:
            raise ValueError("Expected rejection not established or findings changed")
        control = "EXPECTED_REJECTION_PASS"
    else:
        if findings or result["candidate_gate"] != "NO_HIGH_CRITICAL_REPORTED":
            raise ValueError("Fixture candidate requires fresh review")
        control = "FIXTURE_CANDIDATE_EVIDENCE_PASS"
    return {"control": control, "candidate_gate": result["candidate_gate"],
            "manifest": manifest, "counts": result["counts"], "os_packages": len(actual),
            "scanner_exit": scanner_rc, "approved": False}


def main():
    path, image, manifest, mode, inventory, rc = sys.argv[1:]
    raw = Path(path).read_bytes()
    if not raw or len(raw) > 20_000_000:
        raise ValueError("Missing or oversized report")
    result = evaluate(json.loads(raw, object_pairs_hook=unique), image, manifest, mode,
                      Path(inventory).read_text(), int(rc))
    result["report_sha256"] = hashlib.sha256(raw).hexdigest()
    print("OCI_CONTROL_DECISION", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
