import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit_report", Path(__file__).resolve().parents[1] / "scripts" / "audit_report.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AuditReportTests(unittest.TestCase):
    def test_clean_and_vulnerable_report(self):
        pins = "a==1.0\n"
        dep = {"name":"a","version":"1.0","vulns":[]}
        self.assertEqual(module.validate(pins, {"dependencies":[dep]}, 0),(1,0))
        dep["vulns"] = [{"id":"CVE-test"},{"id":"CVE-test"}]
        self.assertEqual(module.validate(pins, {"dependencies":[dep]}, 1),(1,2))
        with self.assertRaises(ValueError):
            module.validate(pins, {"dependencies":[dep]}, 0)

    def test_missing_skipped_duplicate_or_wrong_version_blocks(self):
        dep = {"name":"a","version":"1.0","vulns":[]}
        for deps in ([], [dep,dep], [{"name":"a","version":"2.0","vulns":[]}],
                     [{"name":"a","version":"1.0","skip_reason":"unavailable"}],
                     [{"name":"a","version":"1.0","vulns":[],"skip_reason":"unavailable"}]):
            with self.subTest(deps=deps), self.assertRaises(ValueError):
                module.validate("a==1.0\n", {"dependencies":deps}, 0)

    def test_scanner_error_and_invalid_pins_block(self):
        report={"dependencies":[{"name":"a","version":"1.0","vulns":[]}]}
        for pins, rc in (("a==1.0\n", 2), ("a>=1.0\n",0), ("a==1.0\na==1.0\n",0), ("a==1.0\n",1)):
            with self.subTest(pins=pins,rc=rc), self.assertRaises(ValueError):
                module.validate(pins,report,rc)
