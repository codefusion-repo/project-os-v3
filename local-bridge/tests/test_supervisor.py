import unittest
from unittest.mock import patch, Mock
from project_os_bridge.supervised import read_metadata


class ReadinessTests(unittest.TestCase):
    def test_no_redirect(self):
        with patch("project_os_bridge.readiness.http.client.HTTPSConnection") as cls:
            conn=cls.return_value
            conn.getresponse.return_value.status=302
            with self.assertRaises(RuntimeError):
                read_metadata(Mock())
            self.assertEqual(conn.request.call_count,1)
            conn.close.assert_called_once()

    def test_reject_oversized_response(self):
        with patch("project_os_bridge.readiness.http.client.HTTPSConnection") as cls:
            conn=cls.return_value
            conn.getresponse.return_value.status=200
            conn.getresponse.return_value.read.return_value=b"x"*16385
            with self.assertRaises(RuntimeError):
                read_metadata(Mock())
            conn.close.assert_called_once()

class LifecycleTests(unittest.TestCase):
    def invoke(self, metadata, *, fail_tunnel=False, stop_after_launch=False):
        from types import SimpleNamespace
        from threading import Event
        from project_os_bridge.supervised import supervise
        import subprocess
        order=[]
        stop=Event()
        bridge=Mock()
        tunnel=Mock()
        bridge.poll.return_value=None
        tunnel.poll.return_value=None
        failed_tunnel=Mock()
        failed_tunnel.poll.return_value=1
        def spawn(cmd, **kwargs):
            order.append(cmd[0])
            if cmd[0]=="tunnel":
                if fail_tunnel and order.count("tunnel")==1:
                    return failed_tunnel
                if stop_after_launch or fail_tunnel:
                    stop.set()
            return bridge if cmd[0]=="bridge" else tunnel
        def cleanup(tunnel_child, bridge_child):
            order.append("stop-tunnel" if tunnel_child is tunnel else "stop-none")
            order.append("stop-bridge" if bridge_child is bridge else "stop-none")
        with patch("socket.socket"), patch("project_os_bridge.supervised.subprocess.Popen",side_effect=spawn), patch("project_os_bridge.supervised.read_metadata",return_value=metadata), patch("project_os_bridge.supervised.stop_children",side_effect=cleanup):
            if metadata["resource"]!="expected":
                with self.assertRaises(RuntimeError):
                    supervise(["bridge"],["tunnel"],{}, {}, Mock(),SimpleNamespace(resource="expected",issuer="issuer"),stop)
            else:
                supervise(["bridge"],["tunnel"],{}, {}, Mock(),SimpleNamespace(resource="expected",issuer="issuer"),stop)
        return order

    def test_invalid_metadata_never_starts_tunnel(self):
        self.assertEqual(self.invoke({"resource":"wrong","authorization_servers":["issuer"]}),["bridge","stop-none","stop-bridge"])

    def test_tunnel_exit_restarts_only_tunnel(self):
        self.assertEqual(self.invoke({"resource":"expected","authorization_servers":["issuer"]},fail_tunnel=True),["bridge","tunnel","tunnel","stop-tunnel","stop-bridge"])

    def test_requested_stop_orders_cleanup(self):
        self.assertEqual(self.invoke({"resource":"expected","authorization_servers":["issuer"]},stop_after_launch=True),["bridge","tunnel","stop-tunnel","stop-bridge"])

    def test_occupied_port_never_spawns(self):
        from threading import Event
        from project_os_bridge.supervised import supervise
        with patch("socket.socket") as sock, patch("project_os_bridge.supervised.subprocess.Popen") as spawn:
            sock.return_value.__enter__.return_value.bind.side_effect = OSError("occupied")
            with self.assertRaises(OSError):
                supervise(["bridge"], ["tunnel"], {}, {}, Mock(), Mock(), Event())
            spawn.assert_not_called()

    def test_stop_signals_both_children_before_wait(self):
        from project_os_bridge.supervised import stop_children
        order = []
        tunnel, bridge = Mock(), Mock()
        for name, child in (("tunnel", tunnel), ("bridge", bridge)):
            child.poll.return_value = None
            child.terminate.side_effect = lambda name=name: order.append("signal-" + name)
            child.wait.side_effect = lambda timeout, name=name: order.append("wait-" + name)
        stop_children(tunnel, bridge)
        self.assertEqual(order, ["signal-tunnel", "signal-bridge", "wait-tunnel", "wait-bridge"])

    def test_bridge_cleanup_survives_tunnel_signal_failure(self):
        from project_os_bridge.supervised import stop_children
        tunnel, bridge = Mock(), Mock()
        tunnel.poll.return_value = bridge.poll.return_value = None
        tunnel.terminate.side_effect = OSError("synthetic signal failure")
        with self.assertRaises(OSError):
            stop_children(tunnel, bridge)
        bridge.terminate.assert_called_once()
        bridge.wait.assert_called_once_with(timeout=90)
