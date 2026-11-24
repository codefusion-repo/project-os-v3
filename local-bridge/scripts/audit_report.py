"""Validate audit coverage, without adjudicating or removing any finding."""
import json
import re
import sys
from pathlib import Path


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def validate(pins, report, rc):
    expected = {}
    for line in pins.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9.!+_-]+)", line)
        if not match or norm(match[1]) in expected:
            raise ValueError("Invalid audit inventory")
        expected[norm(match[1])] = match[2]
    if not expected or not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise ValueError("Missing audit inventory")
    actual = {}
    findings = 0
    for dep in report["dependencies"]:
        name = norm(dep["name"])
        if name in actual or "skip_reason" in dep or not isinstance(dep.get("vulns"), list):
            raise ValueError("Duplicate, skipped or incomplete audit package")
        actual[name] = dep["version"]
        for vuln in dep["vulns"]:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str) or not vuln["id"]:
                raise ValueError("Invalid finding")
            findings += 1
    if actual != expected:
        raise ValueError("Audit coverage mismatch")
    if rc not in (0, 1) or (rc == 0) != (findings == 0):
        raise ValueError("Scanner status inconsistent with report")
    return len(actual), findings


if __name__ == "__main__":
    pins, report = (Path(p) for p in sys.argv[1:3])
    if report.stat().st_size > 8_000_000:
        raise ValueError("Audit report exceeds bound")
    print("AUDIT_COVERAGE_VERIFIED", *validate(pins.read_text(), json.loads(report.read_text()), int(sys.argv[3])))
