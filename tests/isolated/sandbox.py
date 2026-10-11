"""A throwaway Herdr server under a fresh temporary directory.

Config, state, plugin registry and socket all live in that directory. Every
command runs with an environment built from scratch that points there, so no
variable of the calling shell or pane leaks in, and start() aborts unless the
server it reaches reports a socket inside the directory.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from tab_sidebar import cli  # noqa: E402
from tab_sidebar.api import Herdr, HerdrError  # noqa: E402
import screen  # noqa: E402

PLUGIN = cli.manifest_id()


def find_herdr(explicit=None) -> str:
    path = explicit or shutil.which("herdr")
    if not path:
        raise SystemExit("herdr was not found on PATH; pass --herdr PATH")
    return os.path.realpath(path)


class Sandbox:
    def __init__(self, herdr_bin: str, config_text: str, extra_env=None):
        self.bin = herdr_bin
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="hts."))
        for name in ("config/herdr", "state", "home", "bin"):
            os.makedirs(os.path.join(self.dir, name))
        self.home = os.path.join(self.dir, "home")
        self.config = os.path.join(self.dir, "config", "herdr", "config.toml")
        with open(self.config, "w", encoding="utf-8") as stream:
            stream.write(config_text)
        self.socket = os.path.join(self.dir, "config", "herdr", "herdr.sock")
        # The manifest runs "python3" from the server's PATH. Make that the
        # interpreter running this script, whatever its file is called.
        wrapper = os.path.join(self.dir, "bin", "python3")
        with open(wrapper, "w", encoding="utf-8") as stream:
            stream.write('#!/bin/sh\nexec %s "$@"\n' % shlex.quote(sys.executable))
        os.chmod(wrapper, 0o755)
        self.env = {
            "HOME": self.home,
            "XDG_CONFIG_HOME": os.path.join(self.dir, "config"),
            "XDG_STATE_HOME": os.path.join(self.dir, "state"),
            "PATH": os.path.join(self.dir, "bin") + ":/usr/bin:/bin:/usr/sbin:/sbin",
            "TERM": "xterm-256color",
            "SHELL": "/bin/sh",
            "LANG": "en_US.UTF-8",
        }
        self.env.update(extra_env or {})
        self.server = None

    def start(self):
        log = open(os.path.join(self.dir, "server.log"), "ab")
        self.server = subprocess.Popen([self.bin, "server"], env=self.env, cwd=self.home,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True)
        log.close()
        deadline = time.time() + 20
        while time.time() < deadline:
            if os.path.exists(self.socket):
                try:
                    self.api().snapshot()
                    break
                except HerdrError:
                    pass
            time.sleep(0.1)
        else:
            raise SystemExit("isolated server did not start; see %s/server.log" % self.dir)
        status = subprocess.run([self.bin, "status"], env=self.env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT).stdout.decode()
        if "socket: %s" % self.socket not in status:
            raise SystemExit("refusing to continue: not talking to the isolated server\n" + status)

    def stop(self):
        if self.server is not None:
            subprocess.run([self.bin, "server", "stop"], env=self.env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            try:
                self.server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait()
            self.server = None

    def remove(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def api(self) -> Herdr:
        return Herdr(self.socket)

    def cli(self, *args) -> dict:
        done = subprocess.run([self.bin] + list(args), env=self.env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60)
        if done.returncode != 0:
            raise AssertionError("herdr %s failed: %s%s" % (
                " ".join(args), done.stdout.decode(), done.stderr.decode()))
        text = done.stdout.decode().strip()
        return json.loads(text)["result"] if text.startswith("{") else {"text": text}

    def logs(self) -> list:
        return self.cli("plugin", "log", "list", "--plugin", PLUGIN, "--limit", "200")["logs"]

    def settle(self, timeout: float = 30.0) -> list:
        """Wait until no hook is running and none has started for a moment."""
        deadline = time.time() + timeout
        previous = None
        while time.time() < deadline:
            logs = self.logs()
            marker = (len(logs), logs[-1]["log_id"] if logs else None,
                      sum(1 for entry in logs if entry["status"] == "running"))
            if marker[2] == 0 and marker == previous:
                return logs
            previous = marker
            time.sleep(0.4)
        raise AssertionError("plugin hooks did not settle")

    def agent(self, pane_id: str, status: str = "idle", name: str = "claude",
              source: str = "user:test"):
        self.cli("pane", "report-agent", pane_id, "--source", source, "--agent", name,
                 "--state", status)

    def capture(self, rows: int = 45, cols: int = 130, seconds: float = 3.0,
                attached=None) -> "screen.Screen":
        """What a client attached to this server draws."""
        return screen.capture([self.bin], self.env, rows, cols, seconds, attached)
