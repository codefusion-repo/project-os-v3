"""Review inventory from the public, digest-locked Alpine CI image."""
import collections
import hashlib
import json
import sys
from pathlib import Path

from oci_compare import summarize


def security_index(documents):
    index = collections.defaultdict(list)
    for repository, doc in documents.items():
        if doc.get("distroversion") != "v3.24" or doc.get("reponame") != repository:
            raise ValueError("Unexpected Alpine security database identity")
        if not doc.get("packages"):
            raise ValueError("Empty Alpine security database")
        for item in doc["packages"]:
            pkg = item["pkg"]
            for version, ids in (pkg.get("secfixes") or {}).items():
                for identifier in ids:
                    index[(pkg["name"], identifier)].append({"repository": repository, "fixed_version": version})
    return index


def inventory(report, image, documents):
    summary = summarize(report, image)
    if summary["os"] != "alpine" or not summary["os_version"].startswith("3.24."):
        raise ValueError("Unexpected Alpine release")
    index = security_index(documents)
    rows = []
    for result in report["Results"]:
        packages = {(p["Name"], p["Version"]): p for p in result.get("Packages") or []}
        for v in result.get("Vulnerabilities") or []:
            name, version, identifier = (v[k] for k in ("PkgName", "InstalledVersion", "VulnerabilityID"))
            if not all(isinstance(x, str) and x for x in (name, version, identifier)):
                raise ValueError("Incomplete vulnerability identity")
            package = packages.get((name, version), {})
            source = package.get("SrcName") or v.get("SrcName") or name
            is_os = result.get("Class") == "os-pkgs"
            fixes = index.get((source, identifier), []) if is_os else []
            rows.append({
                "id": identifier, "package": name, "installed": version,
                "source": source, "source_confirmed": bool(package.get("SrcName") or v.get("SrcName")),
                "class": result.get("Class"), "type": result.get("Type"),
                "severity": v.get("Severity", "UNKNOWN"),
                "severity_source": v.get("SeveritySource"),
                "scanner_fixed": v.get("FixedVersion"), "scanner_status": v.get("Status"),
                "primary_url": v.get("PrimaryURL"),
                "alpine_secdb": sorted(fixes, key=lambda x: (x["repository"], x["fixed_version"])),
                "review": "FIX_RECORDED" if fixes else "NO_MATCH_IN_SECDB" if is_os else "UPSTREAM_REVIEW_REQUIRED",
            })
    if dict(collections.Counter(r["severity"] for r in rows)) != summary["counts"]:
        raise ValueError("Incomplete findings inventory")
    return sorted(rows, key=lambda r: (r["severity"], r["package"], r["id"], r["installed"]))


def main():
    report_path, image, main_path, community_path = sys.argv[1:]
    docs = {}
    for name, path in (("main", main_path), ("community", community_path)):
        raw = Path(path).read_bytes()
        docs[name] = json.loads(raw)
        print("ALPINE_SECDB", name, hashlib.sha256(raw).hexdigest())
    rows = inventory(json.loads(Path(report_path).read_text()), image, docs)
    for row in rows:
        print("ALPINE_FINDING", json.dumps(row, sort_keys=True))
    print("ALPINE_INVENTORY_COMPLETE", len(rows))


if __name__ == "__main__":
    main()
