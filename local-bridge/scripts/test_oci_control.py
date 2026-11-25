import copy
from datetime import datetime, timedelta, timezone
import unittest
from oci_control import evaluate, EXPECTED, RESIDUAL, FIXTURE, validate_db


class OCIControlTests(unittest.TestCase):
    def setUp(self):
        self.image = "/disposable/oci@" + RESIDUAL
        self.report = {"SchemaVersion": 2, "ArtifactType": "container_image",
                       "ArtifactName": self.image, "Metadata": {"OS": {"Family": "alpine", "Name": "3.24.4", "EOSL": False}},
                       "Results": [{"Class": "os-pkgs", "Type": "alpine", "Packages": [{"Name": "a", "Version": "1-r0"}]},
                                   {"Class": "lang-pkgs", "Type": "python-pkg", "Vulnerabilities": [
                                       dict(zip(("VulnerabilityID", "PkgName", "InstalledVersion", "Severity"), key))
                                       for key in EXPECTED]}]}

    def check(self, report=None, rc=0, manifest=RESIDUAL, inventory="a-1-r0\n"):
        return evaluate(self.report if report is None else report, self.image, manifest, "residual", inventory, rc)

    def test_expected_rejection_is_not_approval(self):
        result = self.check()
        self.assertEqual(result["control"], "EXPECTED_REJECTION_PASS")
        self.assertEqual(result["candidate_gate"], "BLOCKED")
        self.assertFalse(result["approved"])

    def test_scanner_failure_identity_and_inventory_block(self):
        for kwargs in ({"rc": 1}, {"rc": 124}, {"manifest": FIXTURE}, {"inventory": "b-1-r0\n"}, {"inventory": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.check(**kwargs)

    def test_missing_unexpected_or_duplicate_findings_block(self):
        for mutation in ("missing", "empty", "extra", "changed"):
            report = copy.deepcopy(self.report)
            rows = report["Results"][1]["Vulnerabilities"]
            if mutation == "missing":
                rows.pop()
            elif mutation == "empty":
                rows.clear()
            elif mutation == "extra":
                rows.append(copy.deepcopy(rows[0]))
            else:
                rows[0]["Severity"] = "HIGH"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.check(report)

    def test_eol_and_incomplete_report_block(self):
        for key in ("ArtifactName", "Results", "Metadata"):
            report = copy.deepcopy(self.report)
            report.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(report)
        self.report["Metadata"]["OS"]["EOSL"] = True
        with self.assertRaises(ValueError):
            self.check()

    def test_fixture_zero_findings_is_evidence_only(self):
        image = "/disposable/oci@" + FIXTURE
        self.report["ArtifactName"] = image
        self.report["Results"].pop()
        result = evaluate(self.report, image, FIXTURE, "fixture-only", "a-1-r0\n", 0)
        self.assertEqual(result["control"], "FIXTURE_CANDIDATE_EVIDENCE_PASS")
        self.assertFalse(result["approved"])
        self.report["Results"][0]["Vulnerabilities"] = [{"VulnerabilityID": "new", "PkgName": "a", "InstalledVersion": "1-r0", "Severity": "LOW"}]
        with self.assertRaises(ValueError):
            evaluate(self.report, image, FIXTURE, "fixture-only", "a-1-r0\n", 0)

    def test_db_freshness_and_missing_metadata(self):
        now = datetime(2026, 11, 24, 18, tzinfo=timezone.utc)
        db = {"Version": 2, "UpdatedAt": (now-timedelta(hours=5)).isoformat(),
              "DownloadedAt": (now-timedelta(minutes=1)).isoformat(),
              "NextUpdate": (now+timedelta(hours=19)).isoformat()}
        self.assertEqual(validate_db(db, now)["updated"], db["UpdatedAt"])
        for key, value in (("Version", 1), ("NextUpdate", now.isoformat()),
                           ("UpdatedAt", (now-timedelta(hours=25)).isoformat()),
                           ("DownloadedAt", (now-timedelta(hours=2)).isoformat()),
                           ("DownloadedAt", (now+timedelta(seconds=1)).isoformat()),
                           ("UpdatedAt", "2026-11-24T13:00:00"), ("NextUpdate", None)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_db(dict(db, **{key:value}), now)
