"""Artifact-bound LB-01 applicability decision, authorized by PM 2026-11-24.
This is not a scanner filter. Keep original report, stderr and exit status.
Only the three reviewed advisories are eligible, for this exact wheel.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_report import validate, norm
from bootstrap_verify import verify

DIGEST = "f3b60b20ffaadd4415ed7957212a38ac63fa4c5fa375bd0f4a797777940fad13"
COMPONENT_HASHES = {
    "pip/_vendor/vendor.txt": "11885a895536bbc3dbf956f493d775fab0ba0bcde182b8d2549f2cbd2ed9fd76",
    "pip/_vendor/pkg_resources/LICENSE": "86da0f01aeae46348a3c3d465195dc1ceccde79f79e87769a64b8da04b2a4741",
    "pip/_vendor/pkg_resources/__init__.py": "bdb4c9d3faee5201b1423944aacaee16688d3d5ca1dadf6afb3c930d3d39df12",
}
# Exact observed record identities; aliases are not wildcard matches.
# Each row: scanner ID, authorized advisory, observed aliases, fixed version, max records.
RULES = {
    "PYSEC-2025-49": ("CVE-2025-47273",
        (frozenset(("GHSA-5rjg-fvgr-3xxf", "CVE-2025-47273")),
         frozenset(("GHSA-5rjg-fvgr-3xxf", "CVE-2025-47273", "BIT-setuptools-2025-47273"))),
        "78.1.1", 2),
    "PYSEC-2026-3447": ("CVE-2026-59890",
        (frozenset(("GHSA-h35f-9h28-mq5c", "CVE-2026-59890", "BIT-setuptools-2026-59890")),),
        "83.0.0", 2),
    "GHSA-xmj3-9gf7-h52w": ("GHSA-xmj3-9gf7-h52w", (frozenset(),), "84.1.0", 1),
}
WARNINGS = [
    "WARNING:pip_audit._cli:--no-deps is supported, but users are encouraged to fully hash their pinned dependencies",
    "WARNING:pip_audit._cli:Consider using a tool like `pip-compile`: https://pip-tools.readthedocs.io/en/latest/#using-hashes",
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def artifact_inventory(wheel, lock, installed):
    if wheel.is_symlink() or not wheel.is_file() or wheel.stat().st_size > 5_000_000:
        raise ValueError("Invalid approved wheel")
    if lock.read_text().split() != ["pip==26.3", "--hash=sha256:" + DIGEST]:
        raise ValueError("Disposition lock mismatch")
    if sha(wheel.read_bytes()) != DIGEST:
        raise ValueError("Disposition artifact mismatch")
    verify(wheel, lock)
    if installed.is_symlink() or not installed.is_dir():
        raise ValueError("Invalid installed pip directory")
    with zipfile.ZipFile(wheel) as z:
        expected = {}
        for name in z.namelist():
            if not name.startswith("pip/") or name.endswith("/"):
                continue
            path = PurePosixPath(name)
            if ".." in path.parts or str(path) != name or "\\" in name:
                raise ValueError("Unsafe wheel member")
            expected[name] = sha(z.read(name))
        if any(expected.get(k) != v for k, v in COMPONENT_HASHES.items()):
            raise ValueError("Approved component bytes mismatch")
        actual = {}
        for path in installed.rglob("*"):
            if path.is_symlink():
                raise ValueError("Unexpected installed symlink")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError("Unexpected installed member")
            rel = path.relative_to(installed)
            # pip installation may generate bytecode for corresponding source.
            # Reject orphan or nonstandard cache entries, not reviewed source.
            if rel.parent.name == "__pycache__" and re.fullmatch(r".+\.cpython-312(?:\.opt-[12])?\.pyc", rel.name):
                source = rel.parent.parent / (rel.name.split(".cpython-312", 1)[0] + ".py")
                if "pip/" + source.as_posix() not in expected:
                    raise ValueError("Orphan installed bytecode")
                continue
            actual["pip/" + rel.as_posix()] = sha(path.read_bytes())
        if actual != expected:
            raise ValueError("Installed pip differs from approved wheel")
        vendor = z.read("pip/_vendor/vendor.txt").decode("utf-8")
    pins = ["pip==26.3"] + [line.strip() for line in vendor.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(pins) != 19:
        raise ValueError("Approved vendor inventory mismatch")
    return "\n".join(pins) + "\n"


def evaluate(pins, report, rc, stderr, expected_pins):
    if pins.splitlines() != expected_pins.splitlines():
        raise ValueError("Report inventory not bound to wheel")
    packages, findings = validate(expected_pins, report, rc)
    if set(report) != {"dependencies", "fixes"} or report["fixes"] != []:
        raise ValueError("Unexpected scanner report schema or fix operation")
    affected = sum(bool(d["vulns"]) for d in report["dependencies"])
    summary = (f"Found {findings} known {'vulnerability' if findings == 1 else 'vulnerabilities'} in "
               f"{affected} {'package' if affected == 1 else 'packages'}") if findings else "No known vulnerabilities found"
    if stderr.splitlines() != WARNINGS + [summary]:
        raise ValueError("Scanner diagnostics not a complete successful scan")
    counts = Counter()
    decisions = []
    for dep in report["dependencies"]:
        for vuln in dep["vulns"]:
            if norm(dep["name"]) != "setuptools" or dep["version"] != "70.3.0":
                raise ValueError("Finding outside approved component")
            rule = RULES.get(vuln["id"])
            if not rule:
                raise ValueError("Unreviewed advisory")
            advisory, aliases, fix, limit = rule
            observed = vuln.get("aliases")
            if (set(vuln) != {"id", "aliases", "fix_versions", "description"}
                    or not isinstance(observed, list) or not all(isinstance(x, str) for x in observed)
                    or len(observed) != len(set(observed)) or frozenset(observed) not in aliases
                    or vuln.get("fix_versions") != [fix] or not isinstance(vuln.get("description"), str)
                    or not vuln["description"].strip()):
                raise ValueError("Advisory record changed; review required")
            counts[vuln["id"]] += 1
            if counts[vuln["id"]] > limit:
                raise ValueError("Unexpected advisory multiplicity")
            decisions.append({"scanner_id": vuln["id"], "advisory": advisory,
                              "state": "not_affected", "justification": "component_not_present"})
    return {"artifact_sha256": DIGEST, "scanner_exit": rc, "packages": packages,
            "raw_findings": findings, "decisions": decisions, "applicable_findings": 0,
            "policy": "LB-01-PM-20261124-31", "result": "PASS"}


def unique_object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("Duplicate JSON key")
        result[k] = v
    return result


def read_report(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 8_000_000:
        raise ValueError("Invalid report")
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


if __name__ == "__main__":
    wheel, lock, installed, pins, report, stderr = map(Path, sys.argv[1:7])
    expected = artifact_inventory(wheel, lock, installed)
    if stderr.stat().st_size > 100_000:
        raise ValueError("Scanner diagnostics exceed bound")
    decision = evaluate(pins.read_text(), read_report(report), int(sys.argv[7]), stderr.read_text(), expected)
    decision["raw_report_sha256"] = sha(report.read_bytes())
    print("BOOTSTRAP_APPLICABILITY_DECISION", json.dumps(decision, sort_keys=True))
