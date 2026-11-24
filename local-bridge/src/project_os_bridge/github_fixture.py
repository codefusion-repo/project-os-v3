"""Synthetic GitHub data for exercising the authenticated batching contract."""
from .github import GitHubReader


class SyntheticGitHubReader(GitHubReader):
    def __init__(self, policy, root):
        super().__init__(policy, {"disposable":"example/disposable"}, root)

    def _request(self, endpoint):
        parts=endpoint.split("/")
        number=int(parts[4])
        if len(parts)==5:
            return {"complete":True,"data":{"number":number,"title":"Synthetic fixture"}}
        return {"complete":True,"data":[{"body":"Synthetic comment","id":number}]}

    def batch_issues(self, principal, project, numbers):
        result=super().batch_issues(principal,project,numbers)
        result["source"]="synthetic-fixture"
        for item in result["issues"].values():
            item["source"]="synthetic-fixture"
        return result
