"""Local-only fixed revision/package fixture (no repository code execution)."""
import argparse
import os
from pathlib import Path
from .workspace_fixture import package_cli

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request-key")
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--evidence-job-id")
    parser.add_argument("--profile", choices=("fixture-package",), default="fixture-package")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    os.umask(0o077)
    package_cli(args, parser)

if __name__ == "__main__":
    main()
