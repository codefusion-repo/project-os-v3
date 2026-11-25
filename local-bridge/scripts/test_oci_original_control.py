import copy
import json
from pathlib import Path
import unittest

from oci_original_control import evaluate, IMAGE, report_records, fingerprint


class OriginalControlTests(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(Path(__file__).with_name("oci-original-rejection.json").read_text())
        findings = self.lock["high_critical"]
        pkgs = sorted({(v["PkgName"], v["InstalledVersion"]) for v in findings})
        low = [{"VulnerabilityID": f"synthetic-{severity}-{i}", "PkgName": pkgs[0][0], "InstalledVersion": pkgs[0][1], "Severity": severity}
               for severity, count in self.lock["counts"].items() if severity != "HIGH" for i in range(count)]
        self.report = {"SchemaVersion": 2, "ArtifactType": "container_image", "ArtifactName": IMAGE,
                       "Metadata": {"OS": {"Family": "debian", "Name": "13.8", "EOSL": False}},
                       "Results": [{"Class": "os-pkgs", "Type": "debian",
                                    "Packages": [{"Name": n, "Version": v} for n,v in pkgs],
                                    "Vulnerabilities": copy.deepcopy(findings) + low}]}
        # Synthetic report: model Trivy's Debian epoch/version/release and identifier fields.
        packages = {}
        for n, version in pkgs:
            epoch, _, rest = version.rpartition(":")
            version_part, _, release = rest.rpartition("-")
            if not version_part:
                version_part, release = rest, ""
            identity = {"UID": n + "@" + version, "PURL": "synthetic:" + n + "@" + version}
            packages[(n, version)] = {"ID": n + "@" + version, "Name": n, "Version": version_part,
                                       "Epoch": int(epoch or 0), "Release": release, "Identifier": identity}
        for finding in self.report["Results"][0]["Vulnerabilities"]:
            pkg = packages[(finding["PkgName"], finding["InstalledVersion"])]
            finding["PkgID"], finding["PkgIdentifier"] = pkg["ID"], copy.deepcopy(pkg["Identifier"])
        self.report["Results"][0]["Packages"] = list(packages.values())
        records, inventory = report_records(self.report)
        self.lock.update(findings_count=len(records), inventory_count=len(inventory),
                         findings_sha256=fingerprint(records), inventory_sha256=fingerprint(inventory))
        self.diagnostic = "OCI BLOCKED: EOL or high/critical findings require review"

    def check(self, report=None, scanner=0, audit=1, diagnostic=None):
        return evaluate(self.report if report is None else report, self.lock, scanner, audit,
                        self.diagnostic if diagnostic is None else diagnostic)

    def test_exact_rejection(self):
        decision = self.check()
        self.assertEqual(decision["control"], "ORIGINAL_EXPECTED_REJECTION_PASS")
        self.assertFalse(decision["approved"])

    def test_scanner_failure_unexpected_acceptance_and_wrong_reason(self):
        for kw in ({"scanner": 1}, {"scanner": 124}, {"audit": 0}, {"audit": 2}, {"diagnostic": "other failure"}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.check(**kw)

    def test_same_count_different_finding_blocks(self):
        report = copy.deepcopy(self.report)
        report["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] = "different"
        with self.assertRaises(ValueError):
            self.check(report)

    def test_missing_inventory_identity_or_eol_blocks(self):
        for mutation in ("identity", "inventory", "eol"):
            report = copy.deepcopy(self.report)
            if mutation == "identity":
                report["ArtifactName"] = "other"
            elif mutation == "inventory":
                report["Results"][0]["Packages"] = []
            else:
                report["Metadata"]["OS"]["EOSL"] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.check(report)

    def test_disappeared_or_new_findings_block(self):
        for extra in (False, True):
            report = copy.deepcopy(self.report)
            findings = report["Results"][0]["Vulnerabilities"]
            if extra:
                findings.append(copy.deepcopy(findings[0]))
            else:
                findings.pop()
            with self.assertRaises(ValueError):
                self.check(report)

    def test_epoch_release_and_package_identity_required(self):
        report = copy.deepcopy(self.report)
        pkg = next(p for p in report["Results"][0]["Packages"] if p["Epoch"])
        pkg["Epoch"] = 0
        with self.assertRaises(ValueError):
            self.check(report)
        report = copy.deepcopy(self.report)
        report["Results"][0]["Vulnerabilities"][0]["PkgIdentifier"]["PURL"] = "other"
        with self.assertRaises(ValueError):
            self.check(report)

    def test_lower_severity_and_inventory_drift_same_counts_block(self):
        report = copy.deepcopy(self.report)
        next(v for v in report["Results"][0]["Vulnerabilities"] if v["Severity"] == "LOW")["VulnerabilityID"] = "different"
        with self.assertRaises(ValueError):
            self.check(report)
        report = copy.deepcopy(self.report)
        report["Results"][0]["Packages"].append({"ID":"extra@1","Name":"extra","Version":"1","Identifier":{"UID":"extra","PURL":"synthetic:extra"}})
        with self.assertRaises(ValueError):
            self.check(report)

    def test_r37_reviewed_snapshot_retains_historical_rejection(self):
        path = Path(__file__).parent
        previous = json.loads((path / "oci-original-rejection.json").read_text())
        current = json.loads((path / "oci-original-rejection-r37.json").read_text())
        for key in ("image", "inventory_count", "inventory_sha256", "high_critical"):
            self.assertEqual(current[key], previous[key])
        self.assertEqual(previous["findings_count"], 228)
        self.assertEqual(previous["counts"]["UNKNOWN"], 14)
        self.assertEqual(current["findings_count"], 232)
        self.assertEqual(current["counts"], {**previous["counts"], "UNKNOWN": 18})
        self.assertEqual(current["findings_sha256"], "a97d07f3d399c86bca8482416e7ec78c3e02caf142c4da81f9cb8f20cd0f17ac")
        self.assertEqual(current["source_artifact"], 14980589296)
        self.assertEqual(current["source_report_sha256"], "234c9e5b5fc0699f528b5d79ee518e40ae4956a606148d4aa9305473b2883906")
        self.assertEqual(
            {(v["VulnerabilityID"], v["PkgName"], v["InstalledVersion"], v["FixedVersion"], v["Severity"])
             for v in current["added_findings"]},
            {("CVE-2026-124851", "libzstd1", "1.5.7+dfsg-1", None, "UNKNOWN"),
             *(("CVE-2026-84785", p, "3.5.9-1~deb13u1", None, "UNKNOWN")
               for p in ("libssl3t64", "openssl", "openssl-provider-legacy"))})
        self.assertEqual(len(current["added_findings"]), 4)

    def test_reviewed_snapshot_change_does_not_allow_unreviewed_unknown_drift(self):
        report = copy.deepcopy(self.report)
        findings = report["Results"][0]["Vulnerabilities"]
        for i in range(4):
            added = copy.deepcopy(findings[0])
            added.update(VulnerabilityID=f"reviewed-extra-{i}", Severity="UNKNOWN")
            findings.append(added)
        with self.assertRaises(ValueError):
            self.check(report)
        records, inventory = report_records(report)
        self.lock.update(findings_count=len(records), findings_sha256=fingerprint(records),
                         counts={**self.lock["counts"], "UNKNOWN": 18})
        self.assertFalse(self.check(report)["approved"])
        changed = copy.deepcopy(report)
        changed["Results"][0]["Vulnerabilities"][-1]["VulnerabilityID"] = "unreviewed-extra"
        with self.assertRaises(ValueError):
            self.check(changed)
        with self.assertRaises(ValueError):
            self.check(self.report)
