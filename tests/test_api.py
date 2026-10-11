import json
import os
import socket
import tempfile
import threading
import unittest

from tab_sidebar.api import Herdr, HerdrError


class FakeServer:
    """Answers each connection with the next canned line and records requests."""

    def __init__(self, replies):
        self.dir = tempfile.TemporaryDirectory(dir="/tmp")
        self.path = os.path.join(self.dir.name, "s")
        self.replies = list(replies)
        self.requests = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.path)
        self.sock.listen(8)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        for reply in self.replies:
            conn, _ = self.sock.accept()
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    data += conn.recv(65536)
                self.requests.append(json.loads(data.decode("utf-8")))
                if reply is not None:
                    conn.sendall(reply)

    def close(self):
        self.thread.join(timeout=2)
        self.sock.close()
        self.dir.cleanup()


class ApiTest(unittest.TestCase):
    def server(self, *replies):
        server = FakeServer(replies)
        self.addCleanup(server.close)
        return server

    def test_success_returns_the_result(self):
        server = self.server(b'{"id":"x","result":{"type":"ok","snapshot":{"tabs":[]}}}\n')
        self.assertEqual(Herdr(server.path).snapshot(), {"tabs": []})
        self.assertEqual(server.requests[0]["method"], "session.snapshot")

    def test_error_reply_raises_with_its_code(self):
        server = self.server(
            b'{"id":"x","error":{"code":"invalid_request","message":"missing field `pane_id`"}}\n'
        )
        with self.assertRaises(HerdrError) as caught:
            Herdr(server.path).set_view({"source": "s"})
        self.assertEqual(caught.exception.code, "invalid_request")

    def test_reply_without_a_result_is_not_success(self):
        for reply in (b"{}\n", b"not json\n", b"[]\n", b"", b'{"id":"x","result":null}\n'):
            server = self.server(reply)
            with self.assertRaises(HerdrError, msg=reply):
                Herdr(server.path).call("agent.view.clear", {})

    def test_missing_socket_raises(self):
        with self.assertRaises(HerdrError):
            Herdr("/tmp/does-not-exist-tab-sidebar.sock").snapshot()
        previous = os.environ.pop("HERDR_SOCKET_PATH", None)
        try:
            with self.assertRaises(HerdrError):
                Herdr()
        finally:
            if previous is not None:
                os.environ["HERDR_SOCKET_PATH"] = previous

    def test_tokens_are_sent_as_a_patch_with_nulls(self):
        server = self.server(b'{"id":"x","result":{"type":"ok"}}\n')
        Herdr(server.path).report_tokens("w1:p1", "plugin:t", {"ts_rep": "1", "ts_group": None})
        self.assertEqual(
            server.requests[0]["params"],
            {"pane_id": "w1:p1", "source": "plugin:t", "tokens": {"ts_rep": "1", "ts_group": None}},
        )


if __name__ == "__main__":
    unittest.main()
