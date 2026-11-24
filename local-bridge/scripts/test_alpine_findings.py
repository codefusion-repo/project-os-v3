import unittest

from alpine_findings import inventory


def secdb(name, packages):
    return {"distroversion": "v3.24", "reponame": name, "packages": packages}


class FindingsTests(unittest.TestCase):
    def setUp(self):
        self.docs = {
            "main": secdb("main", [{"pkg": {"name": "src", "secfixes": {"2-r0": ["CVE-2026-1234"]}}}]),
            "community": secdb("community", [{"pkg": {"name": "other", "secfixes": {}}}]),
        }
        self.report = {"ArtifactName": "image", "Metadata": {"OS": {"Family": "alpine", "Name": "3.24.4"}},
                       "Results": [{"Class": "os-pkgs", "Type": "alpine",
                                    "Packages": [{"Name": "lib", "Version": "1-r0", "SrcName": "src"}],
                                    "Vulnerabilities": [{"PkgName": "lib", "InstalledVersion": "1-r0", "VulnerabilityID": "CVE-2026-1234", "Severity": "LOW"}]}]}

    def test_origin_and_fix(self):
        row, = inventory(self.report, "image", self.docs)
        self.assertEqual(row["source"], "src")
        self.assertEqual(row["alpine_secdb"], [{"repository": "main", "fixed_version": "2-r0"}])
        self.assertEqual(row["review"], "FIX_RECORDED")

    def test_missing_fix_is_not_safe(self):
        self.report["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] = "CVE-2026-9999"
        row, = inventory(self.report, "image", self.docs)
        self.assertEqual(row["review"], "NO_MATCH_IN_SECDB")
        self.assertEqual(row["alpine_secdb"], [])

    def test_wrong_release_and_report_rejected(self):
        with self.assertRaises(ValueError):
            inventory(self.report, "other", self.docs)
        self.docs["main"]["distroversion"] = "v3.23"
        with self.assertRaises(ValueError):
            inventory(self.report, "image", self.docs)

    def test_library_requires_upstream(self):
        self.report["Results"].append({"Class": "lang-pkgs", "Type": "python-pkg",
                                       "Vulnerabilities": [{"PkgName": "src", "InstalledVersion": "1-r0", "VulnerabilityID": "CVE-2026-1234", "Severity": "MEDIUM"}]})
        rows = inventory(self.report, "image", self.docs)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["review"], "UPSTREAM_REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
