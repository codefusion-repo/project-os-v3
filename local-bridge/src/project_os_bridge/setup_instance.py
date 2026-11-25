"""Interactive local-only bootstrap; no credentials or permissions provisioned."""
import argparse
import json
import os
from pathlib import Path

from .workos_auth import validate_issuer, validate_resource, private_directory


def initialize(root, issuer, resource, subject):
    if os.getuid()==0:
        raise PermissionError("Run as an unprivileged service user")
    validate_issuer(issuer)
    validate_resource(resource)
    import re
    if not isinstance(subject,str) or not re.fullmatch(r"user_[A-Za-z0-9]{1,128}",subject):
        raise ValueError("Explicit WorkOS subject required")
    if not root.is_absolute() or root.parent.resolve(strict=True)!=root.parent or root.name in ("",".",".."):
        raise ValueError("Canonical new directory required")
    # Refuse any Git checkout ancestor, including linked worktrees.
    for parent in (root.parent,*root.parent.parents):
        if os.path.lexists(parent/".git"):
            raise PermissionError("Configuration must be outside Git")
    root.mkdir(mode=0o700)
    private_directory(root)
    state=root/"state"
    state.mkdir(mode=0o700)
    fd=os.open(root/"oauth.json",os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump({"issuer":issuer,"resource":resource,"subject":subject},f)
        f.flush()
        os.fsync(f.fileno())
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--prepare-service", action="store_true",
                        help="Prepare a new private HTTPS service for an existing instance")
    parser.add_argument("--no-fixture", action="store_true",
                        help="Disable fixture binding during service preparation")
    args=parser.parse_args()
    if args.no_fixture and not args.prepare_service:
        parser.error("--no-fixture requires --prepare-service")
    os.umask(0o077)
    if args.prepare_service:
        from .service_setup import interactive_prepare
        interactive_prepare(args.root, allow_fixture=not args.no_fixture)
        return
    initialize(args.root,input("Exact AuthKit issuer: ").strip(),
               input("Exact MCP resource: ").strip(),input("WorkOS subject: ").strip())
    print("Private instance initialized; access remains disabled. Review SECURITY.md and WORKOS.md.")


if __name__=="__main__":
    main()
