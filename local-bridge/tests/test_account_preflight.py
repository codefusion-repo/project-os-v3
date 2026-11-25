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


class ProcessPrivilegeInventoryTests(unittest.TestCase):
    def status(self, permitted="0000", effective="0000", ambient="0000", nnp="0"):
        return f"CapPrm:\t{permitted}\nCapEff:\t{effective}\nCapAmb:\t{ambient}\nNoNewPrivs:\t{nnp}\n"

    def test_unprivileged_process_and_nnp_observation(self):
        for flag in ("0", "1"):
            self.assertEqual(account.process_privilege_inventory(self.status(nnp=flag)), {
                "process_capabilities_absent": True,
                "no_new_privileges_enabled": flag == "1",
            })

    def test_each_capability_set_blocks(self):
        for key in ("permitted", "effective", "ambient"):
            with self.subTest(key=key):
                privileges = account.process_privilege_inventory(self.status(**{key: "0001"}))
                self.assertFalse(privileges["process_capabilities_absent"])
                results = dict(privileges, wsl_boundary_review_required=False)
                with patch.object(account, "inspect", return_value=results), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(account.main(), 1)

    def test_invalid_privilege_status_blocks(self):
        for status in ("", self.status(nnp="2"), self.status(effective="-1"),
                       self.status(ambient="xyz"), self.status() + "CapEff: 0\n",
                       self.status().replace("CapPrm:\t0000\n", "")):
            with self.subTest(status=status), self.assertRaises(ValueError):
                account.process_privilege_inventory(status)

    def test_observation_does_not_certify_wsl_or_bypass_groups(self):
        for wsl, groups, expected in ((False, True, 0), (True, True, 1), (False, False, 1)):
            results = dict(account.process_privilege_inventory(self.status()),
                           wsl_boundary_review_required=wsl, privileged_groups_absent=groups)
            with patch.object(account, "inspect", return_value=results), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(account.main(), expected)
