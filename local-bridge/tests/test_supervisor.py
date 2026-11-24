import unittest
from unittest.mock import patch, Mock
from project_os_bridge.supervised import read_metadata


class ReadinessTests(unittest.TestCase):
    def test_no_redirect(self):
        with patch("project_os_bridge.supervised.http.client.HTTPSConnection") as cls:
            conn=cls.return_value
            conn.getresponse.return_value.status=302
            with self.assertRaises(RuntimeError):
                read_metadata(Mock())
            self.assertEqual(conn.request.call_count,1)
            conn.close.assert_called_once()

    def test_reject_oversized_response(self):
        with patch("project_os_bridge.supervised.http.client.HTTPSConnection") as cls:
            conn=cls.return_value
            conn.getresponse.return_value.status=200
            conn.getresponse.return_value.read.return_value=b"x"*16385
            with self.assertRaises(RuntimeError):
                read_metadata(Mock())
            conn.close.assert_called_once()
