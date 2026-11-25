import json
import unittest

import oci_compare as oci


def response(data):
    raw = json.dumps(data).encode()
    return raw, {'Docker-Content-Digest': oci.digest(raw), 'Content-Type': data['mediaType']}


class TestOCI(unittest.TestCase):
    def fixture(self):
        child = response({'schemaVersion': 2, 'mediaType': oci.MANIFEST[0]})
        desc = {'platform': {'os': 'linux', 'architecture': 'amd64'}, 'digest': oci.digest(child[0]), 'size': len(child[0]), 'mediaType': oci.MANIFEST[0]}
        return child, desc

    def resolve(self, child, descriptors):
        index = response({'schemaVersion': 2, 'mediaType': oci.INDEX[0], 'manifests': descriptors})
        def request(url, headers):
            self.assertEqual(headers['Authorization'], 'Bearer test')
            return index if url.endswith(oci.TAGS[0]) else child
        return oci.resolve(oci.TAGS[0], 'test', request)

    def test_resolves_exact_child(self):
        child, desc = self.fixture()
        result = self.resolve(child, [dict(desc, platform={'os': 'unknown', 'architecture': 'unknown'}), desc])
        self.assertEqual(result['manifest_digest'], desc['digest'])
        self.assertNotEqual(result['index_digest'], desc['digest'])

    def test_missing_or_ambiguous_platform(self):
        child, desc = self.fixture()
        for descriptors in ([], [desc, desc]):
            with self.subTest(descriptors=descriptors), self.assertRaises(ValueError):
                self.resolve(child, descriptors)

    def test_descriptor_and_digest_mismatch(self):
        child, desc = self.fixture()
        for bad in (dict(desc, size=0), dict(desc, digest='sha256:' + '0' * 64), dict(desc, mediaType=oci.INDEX[0])):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.resolve(child, [bad])
        with self.assertRaises(ValueError):
            self.resolve((child[0], dict(child[1], **{'Docker-Content-Digest': 'invalid'})), [desc])

    def test_unapproved_tag(self):
        with self.assertRaises(ValueError):
            oci.resolve('latest', 'test')

    def test_report_identity_inventory_and_gate(self):
        report = {'ArtifactName': 'image', 'Metadata': {'OS': {'Family': 'debian'}}, 'Results': [{'Class': 'os-pkgs', 'Packages': [{}]}]}
        self.assertEqual(oci.summarize(report, 'image')['candidate_gate'], 'NO_HIGH_CRITICAL_REPORTED')
        report['Results'][0]['Vulnerabilities'] = [{'Severity': 'HIGH'}]
        self.assertEqual(oci.summarize(report, 'image')['candidate_gate'], 'BLOCKED')
        with self.assertRaises(ValueError):
            oci.summarize(report, 'other')
        report['Results'] = []
        with self.assertRaises(ValueError):
            oci.summarize(report, 'image')


if __name__ == '__main__':
    unittest.main()
