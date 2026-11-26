"""Interactive local-only bootstrap; no credentials or permissions provisioned."""
import argparse
import json
import os
import sys
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
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--prepare-service", action="store_true",
                         help="Prepare a new private HTTPS service for an existing instance")
    actions.add_argument("--github-repository", help="Resolve exact repository ID using the dedicated credential")
    actions.add_argument("--github-project", type=Path, help="Enroll the explicitly selected private project configuration")
    actions.add_argument("--github-revoke", help="Revoke one locally enrolled project")
    parser.add_argument("--no-fixture", action="store_true",
                        help="Disable fixture binding during service preparation")
    args=parser.parse_args()
    if args.no_fixture and not args.prepare_service:
        parser.error("--no-fixture requires --prepare-service")
    os.umask(0o077)
    if args.github_repository is not None or args.github_project is not None or args.github_revoke is not None:
        from .project_enrollment import repository_identity, update_runtime
        try:
            if args.github_repository is not None:
                print(repository_identity(args.root, args.github_repository))
                return
            if not sys.stdin.isatty():
                raise PermissionError("Local interactive operator required")
            action = "authorize the selected read-only project" if args.github_project else "revoke the selected project"
            if input("Confirm " + action + " within the approved scope [yes/N]: ").strip().lower() != "yes":
                print("Cancelled; no grant changed.")
                raise SystemExit(1)
            changed, migrated = update_runtime(args.root, config=args.github_project, revoke=args.github_revoke)
            print("Project grant updated." if changed else "Project grant already matches.")
            if migrated:
                print("First multi-project profile prepared; start using the existing reviewed lifecycle and applicable gates.")
            print("No credential, service, or opt-in changed.")
            return
        except (OSError, ValueError, RuntimeError, EOFError, KeyboardInterrupt):
            print("PROJECT_SETUP_BLOCKED; check the existing unit, dedicated credential, binding and first-profile migration requirements.", file=sys.stderr)
            raise SystemExit(1)
    if args.prepare_service:
        from .service_setup import interactive_prepare
        interactive_prepare(args.root, allow_fixture=not args.no_fixture)
        return
    initialize(args.root,input("Exact AuthKit issuer: ").strip(),
               input("Exact MCP resource: ").strip(),input("WorkOS subject: ").strip())
    print("Private instance initialized; access remains disabled. Review SECURITY.md and WORKOS.md.")


if __name__=="__main__":
    main()
