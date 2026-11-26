import unittest
from pathlib import Path

from project_os_bridge.project_enrollment import next_runtime


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("/fixture/project/.project-os/config.json")
        self.binding = ("demo", "example/demo", 123)
        self.base = {"tunnel": "fixture", "tunnel_id": "fixture", "image": None,
                     "project_config": str(self.path)}

    def test_first_migration_and_idempotent_enrollment(self):
        result, migrated = next_runtime(self.base, config=self.path, binding=self.binding)
        self.assertTrue(migrated)
        self.assertNotIn("project_config", result)
        self.assertEqual(result["github_projects"]["demo"]["repository_id"], 123)
        self.assertEqual(result["tunnel"], self.base["tunnel"])
        again, migrated = next_runtime(result, config=self.path, binding=self.binding)
        self.assertFalse(migrated)
        self.assertEqual(result, again)
        self.assertIn("project_config", self.base)

    def test_other_project_and_revocation_preserve_existing_grants(self):
        result, _ = next_runtime(self.base, config=self.path, binding=self.binding)
        other = Path("/fixture/other/.project-os/config.json")
        both, migrated = next_runtime(result, config=other, binding=("other", "example/other", 456))
        self.assertFalse(migrated)
        self.assertEqual(set(both["github_projects"]), {"demo", "other"})
        revoked, _ = next_runtime(both, revoke="demo")
        self.assertEqual(set(revoked["github_projects"]), {"other"})
        self.assertEqual(set(both["github_projects"]), {"demo", "other"})

    def test_no_implicit_migration_or_rebinding(self):
        with self.assertRaises(PermissionError):
            next_runtime(self.base, config=Path("/fixture/other/.project-os/config.json"),
                         binding=("other", "example/other", 456))
        result, _ = next_runtime(self.base, config=self.path, binding=self.binding)
        with self.assertRaises(PermissionError):
            next_runtime(result, config=self.path, binding=("demo", "example/demo", 999))
        with self.assertRaises(ValueError):
            next_runtime(self.base, revoke="demo")
