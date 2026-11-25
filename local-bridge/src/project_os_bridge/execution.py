"""Fixed disposable validation, not a sandbox for arbitrary repository code."""
from .repository import FixtureRepository


def validate_fixture(repo: FixtureRepository, principal, expected_revision):
    repo.policy.require(principal,"fixture_validate","disposable")
    snapshot=repo.read(principal)
    if snapshot["revision"]!=expected_revision:
        return {"status":"BLOCKED","reason":"REVISION_CONFLICT"}
    # Trusted internal code only, no subprocess and no evaluation of fixture text.
    valid=bool(snapshot["text"].strip())
    return {"status":"SUCCEEDED" if valid else "FAILED",
            "revision":snapshot["revision"],"check":"nonempty_utf8","passed":valid}
