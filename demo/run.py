#!/usr/bin/env python3
"""Show the plugin on a throwaway Herdr server filled with made-up work.

    python3 demo/run.py              open the demo session in this terminal
    python3 demo/run.py --text       print the screen as text
    python3 demo/run.py --svg FILE   write the screen as an SVG image

The server, its config, state and socket live in a temporary directory that is
removed at the end (see tests/isolated/sandbox.py). Your own Herdr session and
config are never read or written. No agent is started: the panes only print
prepared text, and their agent states are reported with
`herdr pane report-agent`.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests", "isolated"))

import sandbox  # noqa: E402
import svg  # noqa: E402
from sandbox import PLUGIN, REPO  # noqa: E402

# No update checks, sounds, notifications or window title: nothing leaves the
# terminal, and nothing of the machine (such as its host name) is drawn.
CONFIG = """onboarding = false

[terminal]
shell_mode = "non_login"

[update]
version_check = false
manifest_check = false

[keys]
prefix = "%s"

[ui]
window_title = ""
confirm_close = false
status_indicators = "symbols"

[ui.sound]
enabled = false

[ui.toast]
delivery = "off"
"""

# What every pane runs instead of your shell: print the text prepared for the
# pane, then a plain prompt. It reads no shell startup file.
PANE_SHELL = """#!/bin/sh
[ -n "$DEMO_PANE" ] && cat "$HOME/.demo/$DEMO_PANE.txt" 2>/dev/null
unset ENV DEMO_PANE
PS1='$ ' exec /bin/sh
"""

# (workspace, [(tab, [pane, ...]), ...]). A pane is (state, text); the state
# is None for a plain shell. The first pane of a tab fills its left half.
WORKSPACES = [
    ("api-server", [
        ("fix-login", [("idle", "$ agent 'fix the login redirect loop'\n\n"
                                "  Done. The session cookie is now set before the redirect.\n")]),
        ("rate-limit", [
            ("working", "$ agent 'rate-limit the public API'\n\n"
                        "  Read   src/routes/public.ts\n"
                        "  Read   src/middleware/index.ts\n\n"
                        "  Plan\n"
                        "    1. token bucket keyed by API key\n"
                        "    2. answer 429 with Retry-After\n"
                        "    3. tests for burst and refill\n\n"
                        "  Edit   src/middleware/rate_limit.ts\n"
                        "  Run    npm test -- rate_limit\n"),
            ("working", "$ agent 'load test the rate limiter'\n\n"
                        "  Run    k6 run load/burst.js\n\n"
                        "  200    9,412\n"
                        "  429      588\n"
                        "  p95    41 ms\n"),
        ]),
        ("review-pr-128", [("blocked", "$ agent 'review pull request 128'\n\n"
                                       "  Allow running `git fetch origin`? [y/n]\n")]),
        ("db-migration", [("done", "$ agent 'add an index on orders.created_at'\n\n"
                                   "  Done. Migration 0042 is ready to apply.\n")]),
        ("flaky-tests", [("working", "$ agent 'find out why the queue tests are flaky'\n")]),
        ("update-deps", [("idle", "$ agent 'update the dependencies'\n")]),
        ("api-docs", [
            ("done", "$ agent 'document the v2 endpoints'\n"),
            ("blocked", "$ agent 'check the examples against staging'\n"),
        ]),
        ("cache-layer", [("working", "$ agent 'cache the product list'\n")]),
        ("error-codes", [("idle", "$ agent 'list every error code we return'\n")]),
        ("load-test", [("working", "$ agent 'profile the search endpoint'\n")]),
        ("logs", [(None, "$ tail -f log/development.log\n")]),
        ("release-notes", [("blocked", "$ agent 'draft the release notes'\n")]),
    ]),
    ("web-app", [
        ("dark-mode", [("working", "$ agent 'add a dark colour scheme'\n")]),
        ("signup-form", [("done", "$ agent 'validate the signup form'\n")]),
        ("a11y-audit", [("idle", "$ agent 'audit keyboard navigation'\n")]),
    ]),
    ("docs", [
        ("quickstart", [("idle", "$ agent 'shorten the quickstart'\n")]),
        ("changelog", [("working", "$ agent 'write the changelog for 2.4'\n")]),
    ]),
    ("scratch", [("notes", [(None, "$ \n")])]),
]
# The tab the session opens on.
SHOWN = ("api-server", "rate-limit")
# The agent the panes claim to run. Herdr 0.9.3 forgets a report within about
# a second unless the name is an agent it knows, so a made-up name cannot be
# used. The name is not drawn while the plugin's row layout is applied, and
# main() checks that it is not on the screen.
AGENT = "claude"


class Stop(Exception):
    """Raised by a signal so the cleanup below always runs."""


def _stop(signum, frame):
    raise Stop(signal.Signals(signum).name)


class Demo(sandbox.Sandbox):
    def __init__(self, herdr_bin: str, prefix: str):
        super().__init__(herdr_bin, CONFIG % prefix)
        shell = os.path.join(self.dir, "bin", "demo-shell")
        with open(shell, "w", encoding="utf-8") as stream:
            stream.write(PANE_SHELL)
        os.chmod(shell, 0o755)
        self.env["SHELL"] = shell
        os.makedirs(os.path.join(self.home, ".demo"))

    def pane_text(self, text: str) -> list:
        """Arguments that make the next pane print ``text``."""
        name = "pane-%d" % len(os.listdir(os.path.join(self.home, ".demo")))
        with open(os.path.join(self.home, ".demo", name + ".txt"), "w", encoding="utf-8") as stream:
            stream.write(text)
        return ["--env", "DEMO_PANE=%s" % name]

    def wait_for_prompts(self, timeout: float = 20.0):
        """Wait until every pane has printed its text and shows the prompt."""
        deadline = time.time() + timeout
        waiting = [p["pane_id"] for p in self.api().snapshot()["panes"]]
        while waiting and time.time() < deadline:
            waiting = [p for p in waiting
                       if not self.cli("pane", "read", p)["text"].rstrip().endswith("$")]
            if waiting:
                time.sleep(0.2)
        if waiting:
            raise SystemExit("panes did not start: %s" % ", ".join(waiting))

    def build(self):
        """Create the workspaces, apply the plugin and set the agent states."""
        # A workspace the server came up with, if any, is dropped at the end.
        initial = [w["workspace_id"] for w in self.api().snapshot()["workspaces"]]
        wanted = {}  # pane_id -> state
        tabs = {}  # (workspace, tab) -> tab_id
        seen = []  # tabs whose agents have been looked at
        for workspace, tab_list in WORKSPACES:
            cwd = os.path.join(self.home, "code", workspace)
            os.makedirs(cwd)
            workspace_id = None
            for label, panes in tab_list:
                options = ["--cwd", cwd, "--no-focus"] + self.pane_text(panes[0][1])
                if workspace_id is None:
                    made = self.cli("workspace", "create", "--label", workspace, *options)
                    workspace_id = made["workspace"]["workspace_id"]
                    self.cli("tab", "rename", made["tab"]["tab_id"], label)
                else:
                    made = self.cli("tab", "create", "--workspace", workspace_id,
                                    "--label", label, *options)
                tabs[(workspace, label)] = made["tab"]["tab_id"]
                pane_ids = [made["root_pane"]["pane_id"]]
                for _state, text in panes[1:]:
                    split = self.cli("pane", "split", pane_ids[0], "--direction", "right",
                                     "--cwd", cwd, "--no-focus", *self.pane_text(text))
                    pane_ids.append(split["pane"]["pane_id"])
                for pane_id, (state, _text) in zip(pane_ids, panes):
                    if state:
                        wanted[pane_id] = state
                if any(state == "idle" for state, _text in panes):
                    seen.append(made["tab"]["tab_id"])
        for workspace_id in initial:
            self.cli("workspace", "close", workspace_id)
        self.wait_for_prompts()

        for pane_id in wanted:
            self.agent(pane_id, "working", AGENT)
        self.cli("plugin", "link", REPO)
        self.cli("plugin", "action", "invoke", "%s.apply" % PLUGIN)
        logs = self.settle()
        if logs[-1]["status"] != "succeeded":
            raise SystemExit("apply failed: %s" % logs[-1].get("stderr"))

        # "done" is an agent that stopped while its tab was not on screen. A
        # client only draws it for a stop it saw happen, so those agents keep
        # working until finish() is called with a client attached.
        for pane_id, state in wanted.items():
            self.agent(pane_id, "idle" if state == "idle" else
                       "blocked" if state == "blocked" else "working", AGENT)
        for tab_id in seen:
            self.cli("tab", "focus", tab_id)
        self.cli("tab", "focus", tabs[SHOWN])
        self.settle()
        self.wanted = wanted

    def finish(self):
        """Let the agents planned as done stop. Call with a client attached."""
        for pane_id, state in self.wanted.items():
            if state == "done":
                self.agent(pane_id, "idle", AGENT)
        self.settle()

    def check_states(self):
        actual = {a["pane_id"]: a["agent_status"] for a in self.api().snapshot()["agents"]}
        if actual != self.wanted:
            raise SystemExit("the demo session did not reach the planned agent states:\n"
                             "  planned %r\n  actual  %r" % (self.wanted, actual))

    def attach(self) -> int:
        """Hand this terminal to a client of the demo server until it detaches."""
        def finish():
            try:
                self.finish()
            except (AssertionError, sandbox.HerdrError, OSError):
                pass  # the session is closing; nothing to report on a full screen

        later = threading.Timer(2.0, finish)
        later.start()
        try:
            return subprocess.call([self.bin], env=self.env, cwd=self.home)
        finally:
            later.cancel()
            later.join()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--text", action="store_true", help="print the screen as text and exit")
    mode.add_argument("--svg", metavar="FILE", help="write the screen as an SVG image and exit")
    parser.add_argument("--herdr", help="herdr executable (default: the one on PATH)")
    parser.add_argument("--prefix", default="ctrl+g",
                        help="prefix key of the demo session (default: %(default)s); pick "
                             "another one if the Herdr you start this from uses the same key")
    parser.add_argument("--rows", type=int, default=44, help="screen height for --text and --svg")
    parser.add_argument("--cols", type=int, default=108, help="screen width for --text and --svg")
    args = parser.parse_args()
    interactive = not (args.text or args.svg)
    if interactive and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("needs a terminal; use --text or --svg otherwise")

    for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _stop)
    box = None
    try:
        box = Demo(sandbox.find_herdr(args.herdr), args.prefix)
        if interactive:
            print("Demo session on a throwaway Herdr server. Your own Herdr session and "
                  "config are not touched.")
            print("To leave, press %s and then q; everything is removed afterwards. "
                  "Setting up..." % args.prefix)
        box.start()
        box.build()
        if interactive:
            input("Ready. Press Enter to open the demo. ")
            box.attach()
            return 0
        shot = box.capture(args.rows, args.cols, attached=box.finish)
        box.check_states()
        if shot.title is not None:
            raise SystemExit("the demo session set a window title: %r" % shot.title)
        if not any("✓" in line for line in shot.lines()):
            raise SystemExit("no finished agent is on the screen")
        if any(AGENT in line for line in shot.lines()):
            raise SystemExit("the agent name %r is on the screen" % AGENT)
        if args.svg:
            with open(args.svg, "w", encoding="utf-8") as stream:
                stream.write(svg.render(shot))
        else:
            print("\n".join(shot.lines()))
        return 0
    except Stop as stop:
        try:
            print("\nStopped by %s." % stop, file=sys.stderr)
        except OSError:
            pass  # the terminal is gone
        return 130
    finally:
        # Nothing may interrupt the cleanup.
        for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, signal.SIG_IGN)
        if box is not None:
            box.stop()
            box.remove()
            if interactive:
                try:
                    print("Demo server stopped and its temporary directory removed.")
                    sys.stdout.flush()
                except OSError:
                    # The terminal is gone; leave nothing for Python to flush.
                    sys.stdout = sys.stderr = open(os.devnull, "w")


if __name__ == "__main__":
    sys.exit(main())
