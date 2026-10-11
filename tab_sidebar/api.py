"""Minimal Herdr socket client: one JSON request per connection."""
from __future__ import annotations

import json
import os
import socket
from typing import Optional

TIMEOUT_SECONDS = 10.0


class HerdrError(Exception):
    """An error response, or a reply that is not a valid success response."""

    def __init__(self, method: str, code: str, message: str):
        super().__init__("%s failed: %s: %s" % (method, code, message))
        self.method = method
        self.code = code
        self.message = message


class Herdr:
    def __init__(self, socket_path: Optional[str] = None):
        path = socket_path or os.environ.get("HERDR_SOCKET_PATH")
        if not path:
            raise HerdrError("connect", "no_socket", "HERDR_SOCKET_PATH is not set")
        self.socket_path = path
        self._next_id = 0

    def call(self, method: str, params: Optional[dict] = None) -> dict:
        self._next_id += 1
        request_id = "tab-sidebar-%d-%d" % (os.getpid(), self._next_id)
        payload = json.dumps(
            {"id": request_id, "method": method, "params": params or {}}, ensure_ascii=False
        )
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(TIMEOUT_SECONDS)
                sock.connect(self.socket_path)
                sock.sendall(payload.encode("utf-8") + b"\n")
                data = b""
                while not data.endswith(b"\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    data += chunk
        except OSError as err:
            raise HerdrError(method, "socket_error", str(err))
        try:
            response = json.loads(data.decode("utf-8"))
        except ValueError:
            raise HerdrError(method, "bad_response", repr(data[:200]))
        # Never treat an error reply as success: require an explicit result.
        if not isinstance(response, dict):
            raise HerdrError(method, "bad_response", repr(data[:200]))
        error = response.get("error")
        if error is not None:
            if isinstance(error, dict):
                raise HerdrError(
                    method, str(error.get("code", "error")), str(error.get("message", ""))
                )
            raise HerdrError(method, "error", str(error))
        result = response.get("result")
        if not isinstance(result, dict):
            raise HerdrError(method, "bad_response", "no result in reply")
        return result

    def snapshot(self) -> dict:
        snapshot = self.call("session.snapshot").get("snapshot")
        if not isinstance(snapshot, dict):
            raise HerdrError("session.snapshot", "bad_response", "no snapshot in result")
        return snapshot

    def report_tokens(self, pane_id: str, source: str, tokens: dict) -> None:
        self.call(
            "pane.report_metadata", {"pane_id": pane_id, "source": source, "tokens": tokens}
        )

    def set_view(self, params: dict) -> dict:
        return self.call("agent.view.set", params)

    def clear_view(self, source: str) -> dict:
        return self.call("agent.view.clear", {"source": source})
