import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class PreflightTests(unittest.TestCase):
    def test_bash_syntax(self):
        script=Path(__file__).resolve().parents[1]/"scripts"/"preflight.sh"
        subprocess.run(["bash","-n",str(script)],check=True)

    def test_adb_inventory_distinguishes_connected_emulator(self):
        script=Path(__file__).resolve().parents[1]/"scripts"/"preflight.sh"
        for devices, expected in (
            ("emulator-5554 device", "CONNECTED"),
            ("emulator-5554 offline", "NOT_DETECTED"),
            ("physical-fixture device", "NOT_DETECTED"),
        ):
            with self.subTest(devices=devices), tempfile.TemporaryDirectory() as folder:
                adb=Path(folder)/"adb"
                adb.write_text("#!/bin/sh\nif [ \"$1\" = devices ]; then printf '%s\\n' 'List of devices attached' '"+devices+"'; fi\n",encoding="utf-8")
                adb.chmod(0o700)
                env=dict(os.environ,PATH=folder+":/usr/bin:/bin")
                result=subprocess.run(["bash",str(script)],env=env,capture_output=True,text=True,timeout=30,check=True)
                self.assertIn("adb_emulator_attach: "+expected,result.stdout)
                self.assertNotIn("emulator-5554",result.stdout)
                self.assertNotIn("physical-fixture",result.stdout)
