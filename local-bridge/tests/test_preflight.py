import subprocess
import unittest
from pathlib import Path


class PreflightTests(unittest.TestCase):
    def test_bash_syntax(self):
        script=Path(__file__).resolve().parents[1]/"scripts"/"preflight.sh"
        subprocess.run(["bash","-n",str(script)],check=True)
