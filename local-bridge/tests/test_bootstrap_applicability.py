import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("bootstrap_applicability", Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_applicability.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ApplicabilityTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(module, "DESCRIPTION_HASHES", {key: [module.sha(b"reviewed advisory")] for key in module.RULES})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pins = "pip==26.3\nsetuptools==70.3.0\n"
        self.report = {"dependencies": [
            {"name": "pip", "version": "26.3", "vulns": []},
            {"name": "setuptools", "version": "70.3.0", "vulns": [
                {"id": key, "aliases": sorted(rule[1][0]), "fix_versions": [rule[2]], "description": "reviewed advisory"}
                for key, rule in module.RULES.items()] }], "fixes": []}

    def check(self, report=None, rc=1, stderr=None, pins=None):
        return module.evaluate(self.pins if pins is None else pins,
                               self.report if report is None else report, rc,
                               "\n".join(module.WARNINGS + ["Found 3 known vulnerabilities in 1 package"])+"\n" if stderr is None else stderr,
                               self.pins)

    def test_authorized_records_preserve_raw_report(self):
        before = copy.deepcopy(self.report)
        out = self.check()
        self.assertEqual(self.report, before)
        self.assertEqual(out["scanner_exit"], 1)
        self.assertEqual(out["raw_findings"], 3)
        self.assertEqual({d["advisory"] for d in out["decisions"]}, {v[0] for v in module.RULES.values()})

    def test_unknown_advisory_and_cross_component_block(self):
        self.report["dependencies"][1]["vulns"][0]["id"] = "NEW"
        with self.assertRaises(ValueError):
            self.check()
        self.setUp()
        self.report["dependencies"][0]["vulns"] = self.report["dependencies"][1]["vulns"]
        self.report["dependencies"][1]["vulns"] = []
        with self.assertRaises(ValueError):
            self.check()

    def test_changed_alias_fix_version_or_missing_metadata_blocks(self):
        for field, value in (("aliases", ["CVE-new"]), ("fix_versions", ["999"]), ("description", ""), ("description", "newly affected component")):
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report["dependencies"][1]["vulns"][0][field] = value
                with self.assertRaises(ValueError):
                    self.check(report)

    def test_scanner_failure_and_missing_coverage_block(self):
        for rc in (0, 2, 124):
            with self.assertRaises(ValueError):
                self.check(rc=rc)
        for stderr in ("", "ERROR: network", "\n".join(module.WARNINGS + ["Found 3 known vulnerabilities in 1 package", "ERROR: failed"])):
            with self.assertRaises(ValueError):
                self.check(stderr=stderr)
        for report in ({"dependencies": [], "fixes": []}, {"dependencies": self.report["dependencies"][:1], "fixes": []}):
            with self.assertRaises(ValueError):
                self.check(report)
        with self.assertRaises(ValueError):
            self.check(pins="setuptools==70.3.0\n")

    def test_clean_scan_still_requires_complete_inventory(self):
        self.report["dependencies"][1]["vulns"] = []
        out = self.check(rc=0, stderr="\n".join(module.WARNINGS + ["No known vulnerabilities found"])+"\n")
        self.assertEqual(out["raw_findings"], 0)

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"dependencies":[],"dependencies":[]}', object_pairs_hook=module.unique_object)

    def test_artifact_and_installed_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheel = root/"pip-26.3-py3-none-any.whl"
            lock = root/"lock"
            installed = root/"pip"
            data = {"pip/_vendor/vendor.txt": ("setuptools==70.3.0\n" + "".join(f"x{i}==1\n" for i in range(17))).encode(),
                    "pip/_vendor/pkg_resources/LICENSE": b"license", "pip/_vendor/pkg_resources/__init__.py": b"code"}
            with zipfile.ZipFile(wheel, "w") as z:
                for name, content in data.items():
                    z.writestr(name, content)
                    path = root/name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            digest = module.sha(wheel.read_bytes())
            lock.write_text("pip==26.3 --hash=sha256:"+digest+"\n")
            with self.assertRaises(ValueError):
                module.artifact_inventory(wheel, lock, installed)
            with patch.object(module, "DIGEST", digest), patch.object(module, "COMPONENT_HASHES", {k:module.sha(v) for k,v in data.items()}):
                self.assertEqual(len(module.artifact_inventory(wheel, lock, installed).splitlines()), 19)
                extra = installed/"_vendor/pkg_resources/unexpected.py"
                extra.write_bytes(b"new code")
                with self.assertRaises(ValueError):
                    module.artifact_inventory(wheel, lock, installed)
                extra.unlink()
                (installed/"_vendor/vendor.txt").write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    module.artifact_inventory(wheel, lock, installed)
                wheel.write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    module.artifact_inventory(wheel, lock, installed)

    def test_excess_duplicate_records_block(self):
        self.report["dependencies"][1]["vulns"].extend([copy.deepcopy(self.report["dependencies"][1]["vulns"][0]) for _ in range(2)])
        with self.assertRaisesRegex(ValueError, "multiplicity"):
            self.check(stderr="\n".join(module.WARNINGS + ["Found 5 known vulnerabilities in 1 package"])+"\n")
