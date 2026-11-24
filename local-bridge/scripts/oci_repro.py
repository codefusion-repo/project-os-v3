"""CI-only OCI manifest equality check with bounded metadata diagnostics."""
import hashlib
import json
import sys
import tarfile
from pathlib import Path


def verify_expected(expected, actual):
    """Reject equal but unexpected images; a manifest lock is mandatory."""
    for value in (expected, actual):
        if len(value) != 71 or not value.startswith("sha256:") or any(c not in "0123456789abcdef" for c in value[7:]):
            raise ValueError("Invalid manifest lock digest")
    if expected != actual:
        raise ValueError("Manifest lock mismatch")


def checked_blob(root, digest):
    algorithm, value = digest.split(":", 1)
    if algorithm != "sha256" or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid OCI digest")
    raw = (root / "blobs" / algorithm / value).read_bytes()
    if hashlib.sha256(raw).hexdigest() != value:
        raise ValueError("OCI blob digest mismatch")
    return raw


def load_manifest(root, digest):
    index = json.loads((root / "index.json").read_text())
    if len(index["manifests"]) != 1 or index["manifests"][0]["digest"] != digest:
        raise ValueError("OCI index mismatch")
    manifest = json.loads(checked_blob(root, digest))
    for descriptor in (manifest["config"], *manifest["layers"]):
        if len(checked_blob(root, descriptor["digest"])) != descriptor["size"]:
            raise ValueError("OCI descriptor size mismatch")
    return manifest


def layer_entries(root, descriptor):
    digest = descriptor["digest"]
    checked_blob(root, digest)
    with tarfile.open(root / "blobs" / "sha256" / digest[7:], "r:*") as archive:
        return [(m.name, m.type.decode("ascii"), m.mode, m.uid, m.gid, m.size,
                 m.mtime, m.linkname, sorted(m.pax_headers.items()),
                 hashlib.sha256(archive.extractfile(m).read()).hexdigest() if m.isfile() else None)
                for m in archive]


def compare(a, ad, b, bd):
    left, right = load_manifest(a, ad), load_manifest(b, bd)
    print("OCI_REPEAT_DIGESTS", ad, bd, flush=True)
    if ad == bd:
        print("OCI_REPRODUCIBLE_PASS", ad, flush=True)
        return True
    lc, rc = (json.loads(checked_blob(root, manifest["config"]["digest"]))
              for root, manifest in ((a, left), (b, right)))
    print("OCI_CONFIG_DIFF_KEYS", sorted(k for k in lc.keys() | rc.keys() if lc.get(k) != rc.get(k)))
    print("OCI_LAYER_DIGESTS", [d["digest"] for d in left["layers"]], [d["digest"] for d in right["layers"]])
    if len(left["layers"]) == len(right["layers"]) and left["layers"][-1] != right["layers"][-1]:
        le, re = layer_entries(a, left["layers"][-1]), layer_entries(b, right["layers"][-1])
        print("OCI_LAYER_ENTRY_ORDER_EQUAL", [x[0] for x in le] == [x[0] for x in re])
        lm, rm = {x[0]: x for x in le}, {x[0]: x for x in re}
        for name in sorted(lm.keys() | rm.keys()):
            l, r = lm.get(name), rm.get(name)
            if l != r:
                fields = ("name", "type", "mode", "uid", "gid", "size", "mtime", "link", "pax", "content")
                print("OCI_ENTRY_DIFF", name, [f for i, f in enumerate(fields) if l is None or r is None or l[i] != r[i]])
    return False


if __name__ == "__main__":
    raise SystemExit(0 if compare(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]) else 1)
