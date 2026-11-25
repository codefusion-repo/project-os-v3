"""Mount diagnostics must never weaken the independent-host gate."""
import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "account_preflight", Path(__file__).resolve().parents[1] / "scripts/account_preflight.py")
account = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(account)


def mount(target, filesystem):
    return f"42 1 0:42 / {target} rw - {filesystem} source rw"


class AccountMountInventoryTests(unittest.TestCase):
    def test_no_host_mounts(self):
        self.assertEqual(account.mount_inventory(mount("/", "ext4")), {
            "windows_mounts_absent": True,
            "wsl_driver_path_mount_absent": True,
            "other_host_mounts_absent": True,
        })

    def test_driver_path_is_not_exempted(self):
        result = account.mount_inventory(mount("/usr/lib/wsl/drivers", "9p"))
        self.assertFalse(result["windows_mounts_absent"])
        self.assertFalse(result["wsl_driver_path_mount_absent"])
        self.assertTrue(result["other_host_mounts_absent"])

    def test_all_known_types_and_nonexact_targets_block(self):
        for kind in ("9p", "drvfs", "virtiofs", "cifs", "smb3"):
            for target in ("/srv/exchange", "/usr/lib/wsl/drivers/child",
                           "/usr/lib/wsl/drivers-other", r"/srv/private\040share"):
                with self.subTest(kind=kind, target=target):
                    result = account.mount_inventory(mount(target, kind))
                    self.assertFalse(result["windows_mounts_absent"])
                    self.assertFalse(result["other_host_mounts_absent"])
                    self.assertTrue(result["wsl_driver_path_mount_absent"])

    def test_mixed_mounts(self):
        result = account.mount_inventory("\n".join((
            mount("/", "ext4"), mount("/usr/lib/wsl/drivers", "9p"),
            mount("/srv/exchange", "9p"))))
        self.assertEqual(result, dict.fromkeys(result, False))

    def test_invalid_inventory_blocks(self):
        for value in ("", "invalid", "1 2 3 / / rw -", mount("relative", "9p")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                account.mount_inventory(value)

    def test_exit_gate_and_sanitized_output(self):
        for raw, wsl, expected in (
            (mount("/", "ext4"), False, 0),
            (mount("/", "ext4"), True, 1),
            (mount("/usr/lib/wsl/drivers", "9p"), False, 1),
            (mount("/srv/exchange", "9p"), False, 1),
        ):
            results = dict(account.mount_inventory(raw), wsl_boundary_review_required=wsl)
            with patch.object(account, "inspect", return_value=results), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(account.main(), expected)
            self.assertNotIn("/usr/lib/wsl/drivers", output.getvalue())
            self.assertNotIn("/srv/exchange", output.getvalue())

    def test_inventory_error_is_sanitized(self):
        with patch.object(account, "inspect", side_effect=ValueError("/private/path")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(account.main(), 1)
        self.assertEqual(output.getvalue(), "ACCOUNT_PREFLIGHT: BLOCKED\n")
