"""CI-only comparison of public official Python images; never approves an image."""
import collections
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

TAGS = ('3.12-slim-bookworm', '3.12-slim-trixie', '3.12-alpine')
REGISTRY = 'https://registry-1.docker.io/v2/library/python/manifests/'
AUTH = 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull'
INDEX = ('application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json')
MANIFEST = ('application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json')
LIMIT = 4 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Unexpected registry redirect')


def get(url, headers):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(urllib.request.Request(url, headers=headers), timeout=30) as response:
        raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Registry response too large')
        return raw, response.headers


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def fetch_manifest(ref, token, allowed, request=get):
    raw, headers = request(REGISTRY + ref, {'Authorization': 'Bearer ' + token, 'Accept': ', '.join(allowed)})
    actual = digest(raw)
    if headers.get('Docker-Content-Digest') != actual or (ref.startswith('sha256:') and ref != actual):
        raise ValueError('Manifest digest mismatch')
    data = json.loads(raw)
    if data.get('schemaVersion') != 2 or data.get('mediaType') not in allowed or headers.get('Content-Type', '').split(';')[0] != data['mediaType']:
        raise ValueError('Unexpected manifest type')
    return data, actual, len(raw)


def resolve(tag, token, request=get):
    if tag not in TAGS:
        raise ValueError('Unapproved comparison tag')
    index, index_digest, _ = fetch_manifest(tag, token, INDEX, request)
    matches = [d for d in index['manifests'] if d.get('platform', {}).get('os') == 'linux' and d.get('platform', {}).get('architecture') == 'amd64']
    if len(matches) != 1:
        raise ValueError('Expected exactly one linux/amd64 descriptor')
    desc = matches[0]
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', desc.get('digest', '')) or desc.get('mediaType') not in MANIFEST or desc['platform'].get('variant') not in (None, '', 'v1'):
        raise ValueError('Unsupported platform descriptor')
    child, child_digest, size = fetch_manifest(desc['digest'], token, MANIFEST, request)
    if size != desc.get('size') or child['mediaType'] != desc['mediaType']:
        raise ValueError('Descriptor mismatch')
    return {'tag': tag, 'index_digest': index_digest, 'manifest_digest': child_digest, 'platform': 'linux/amd64'}


def summarize(report, image):
    if report.get('ArtifactName') != image:
        raise ValueError('Report identity mismatch')
    os_info = (report.get('Metadata') or {}).get('OS') or {}
    results = report.get('Results') or []
    if not os_info.get('Family') or not any(r.get('Class') == 'os-pkgs' and r.get('Packages') for r in results):
        raise ValueError('OS package inventory missing')
    counts = collections.Counter()
    findings = []
    for result in results:
        for vuln in result.get('Vulnerabilities') or []:
            severity = vuln.get('Severity', 'UNKNOWN')
            counts[severity] += 1
            if severity in ('HIGH', 'CRITICAL'):
                findings.append({k: vuln.get(k) for k in ('VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion', 'Severity')})
    return {'os': os_info['Family'], 'os_version': os_info.get('Name'), 'eosl': bool(os_info.get('EOSL')), 'counts': dict(counts), 'high_critical': findings, 'candidate_gate': 'BLOCKED' if os_info.get('EOSL') or counts['HIGH'] or counts['CRITICAL'] else 'NO_HIGH_CRITICAL_REPORTED'}


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or not os.environ.get('RUNNER_TEMP'):
        raise SystemExit('CI only')
    with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as tmp:
        work = Path(tmp)
        for name in ('home', 'cache'):
            (work / name).mkdir()
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(work / 'home'), 'LC_ALL': 'C'}
        def run(*args):
            subprocess.run(args, cwd=work, env=env, check=True, timeout=600)
        archive = 'trivy_0.76.2_Linux-64bit.tar.gz'
        run('curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https', '--proto-redir', '=https', '--max-time', '180', '-o', archive, 'https://github.com/aquasecurity/trivy/releases/download/v0.76.2/' + archive)
        if digest((work / archive).read_bytes()) != 'sha256:bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf':
            raise SystemExit('Scanner checksum mismatch')
        run('tar', '-xzf', archive, 'trivy')
        trivy = ('./trivy', '--cache-dir', str(work / 'cache'))
        run(*trivy, 'image', '--download-db-only', '--timeout', '5m')
        run(*trivy, '--version')
        token = json.loads(get(AUTH, {})[0])['token']
        failed = False
        for tag in TAGS:
            try:
                record = resolve(tag, token)
                print('OCI_RESOLVED', json.dumps(record, sort_keys=True), flush=True)
                image = 'docker.io/library/python@' + record['manifest_digest']
                output = work / (tag + '.json')
                run(*trivy, 'image', '--skip-db-update', '--image-src', 'remote', '--platform', 'linux/amd64', '--scanners', 'vuln', '--pkg-types', 'os,library', '--ignorefile', '/dev/null', '--list-all-pkgs', '--no-progress', '--timeout', '8m', '--format', 'json', '--output', str(output), image)
                record.update(summarize(json.loads(output.read_text()), image))
                print('OCI_COMPARISON', json.dumps(record, sort_keys=True), flush=True)
            except Exception as exc:
                # Never print exception payloads containing registry authorization or responses.
                print('OCI_COMPARISON_ERROR', tag, type(exc).__name__, flush=True)
                failed = True
        if failed:
            raise SystemExit('Incomplete OCI comparison')


if __name__ == '__main__':
    main()
