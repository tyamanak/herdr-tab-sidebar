#!/usr/bin/env python3
"""End-to-end check against a throwaway Herdr server.

Starts its own headless server with config, state, plugin registry and socket
under a fresh temporary directory, links this checkout there, and drives the
real manifest hooks and actions. Your Herdr session, config.toml and plugin
registry are never read or written (see sandbox.py).

Usage: python3 tests/isolated/run.py [--herdr PATH] [--keep]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sandbox  # noqa: E402
import screen  # noqa: E402
from sandbox import PLUGIN, REPO  # noqa: E402
from tab_sidebar import config_edit, plan as planner  # noqa: E402
from tab_sidebar.api import HerdrError  # noqa: E402

# A config with settings of its own: a table after [ui], a blank line inside
# a table, and nothing that reaches the network or makes a sound.
USER_CONFIG = """onboarding = false
[ui]
agent_panel_sort = "priority"

confirm_close = false
[update]
version_check = false
manifest_check = false

[ui.sound]
enabled = false

[ui.toast]
delivery = "off"
"""


class Sandbox(sandbox.Sandbox):
    def __init__(self, herdr_bin: str):
        super().__init__(herdr_bin, USER_CONFIG)
        self.checks = 0

    def read_config(self) -> str:
        with open(self.config, encoding="utf-8", newline="") as stream:
            return stream.read()

    def tokens(self) -> dict:
        return {a["pane_id"]: planner.own_tokens(a.get("tokens"))
                for a in self.api().snapshot()["agents"]}

    def rows(self) -> list:
        """(heading, label, extra) of each representative, from live tokens."""
        snap = self.api().snapshot()
        ws_order = {w["workspace_id"]: i for i, w in enumerate(snap["workspaces"])}
        reps = [a for a in snap["agents"] if (a.get("tokens") or {}).get("ts_rep") == "1"]
        reps.sort(key=lambda a: (ws_order[a["workspace_id"]], a["tokens"]["ts_pos"]))
        return [(a["tokens"].get("ts_group"), a["tokens"]["ts_label"].lstrip(planner.PAD),
                 a["tokens"].get("ts_extra")) for a in reps]

    def panel(self) -> dict:
        return screen.agents_panel(self.capture().lines())

    def verdict(self, expect: str):
        """`main.py status --expect ...` as a user would run it from a shell."""
        env = dict(self.env, HERDR_BIN_PATH=self.bin)
        done = subprocess.run(
            [sys.executable, os.path.join(REPO, "main.py"), "status", "--expect", expect],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        return done.returncode, done.stdout.decode().strip().splitlines()[-1].split(" (")[0]

    def action_log(self, action: str):
        """The newest log entry of one action, however many events ran since."""
        entries = [entry for entry in self.logs() if entry.get("action_id") == action]
        return entries[-1] if entries else None

    def check(self, label: str, actual, expected):
        self.checks += 1
        if actual != expected:
            raise AssertionError("%s\n  expected: %r\n  actual:   %r" % (label, expected, actual))
        print("ok  %s" % label)

    def needs_no_change(self, label: str):
        self.check(label, planner.diff(planner.build_plan(self.api().snapshot())), {})


def panel_text(panel: dict) -> list:
    """Entry lines without the trailing state icon, padding shown as spaces."""
    lines = []
    for line in panel["lines"]:
        line = line.replace("⠀", " ")
        head, sep, _icon = line.rpartition(" · ")
        lines.append(head if sep else line)
    return lines


def scenario(box: Sandbox):
    api = box.api()

    # --- topology -------------------------------------------------------
    first = box.cli("workspace", "create", "--label", "🚀 api-server", "--no-focus")
    w1, t_login, p_login = (first["workspace"]["workspace_id"], first["tab"]["tab_id"],
                            first["root_pane"]["pane_id"])
    box.cli("tab", "rename", t_login, "fix-login")
    limit = box.cli("tab", "create", "--workspace", w1, "--label", "rate-limit", "--no-focus")
    t_limit, p_limit = limit["tab"]["tab_id"], limit["root_pane"]["pane_id"]
    p_limit2 = box.cli("pane", "split", p_limit, "--direction", "right", "--no-focus")["pane"]["pane_id"]
    p_limit_shell = box.cli("pane", "split", p_limit, "--direction", "down", "--no-focus")["pane"]["pane_id"]
    box.cli("tab", "create", "--workspace", w1, "--label", "shell-only", "--no-focus")
    review = box.cli("tab", "create", "--workspace", w1, "--label", "review-pr", "--no-focus")
    t_review, p_review = review["tab"]["tab_id"], review["root_pane"]["pane_id"]
    web = box.cli("workspace", "create", "--label", "web-app", "--no-focus")
    w2, p_deps = web["workspace"]["workspace_id"], web["root_pane"]["pane_id"]
    box.cli("tab", "rename", web["tab"]["tab_id"], "update-deps")
    box.cli("workspace", "create", "--label", "docs", "--no-focus")
    for pane in (p_login, p_limit, p_limit2, p_review, p_deps):
        box.agent(pane)

    # --- linked but not applied: nothing changes -------------------------
    box.cli("plugin", "link", REPO)
    box.agent(p_review, "working")
    box.settle()
    box.check("linked only: no tokens are written", any(box.tokens().values()), False)
    box.check("linked only: config untouched", box.read_config(), USER_CONFIG)
    box.check("linked only: standard Agents header", box.panel()["header"], ["agents", "priority"])
    box.check("linked only: status says released, not applied",
              (box.verdict("released"), box.verdict("applied")[0]), ((0, "OK: released"), 1))
    box.check("linked only: no action in the log yet", box.action_log("apply"), None)

    # --- apply ------------------------------------------------------------
    box.cli("plugin", "action", "invoke", "%s.apply" % PLUGIN)
    logs = box.settle()
    box.check("apply: action succeeded", (logs[-1]["status"], logs[-1]["exit_code"]), ("succeeded", 0))
    box.check("apply: only the managed block is added", box.read_config(), USER_CONFIG + config_edit.BLOCK)
    box.check("apply: herdr accepts the config", config_edit.check(box.bin, box.config)[0], True)
    expected = [("🚀 api-server", "fix-login", None), (None, "rate-limit", "+1"), (None, "review-pr", None),
                ("web-app", "update-deps", None)]
    box.check("apply: one row per agent tab, tab bar order, Spaces order", box.rows(), expected)
    box.check("apply: shell pane has no tokens", p_limit_shell in box.tokens(), False)
    panel = box.panel()
    box.check("apply: Agents header shows the view label", panel["header"], ["agents", "tabs"])
    box.check("apply: rendered panel", panel_text(panel),
              [" 🚀 api-server", "   fix-login", "   rate-limit · +1", "   review-pr", " web-app", "   update-deps"])
    box.needs_no_change("apply: a fresh snapshot needs no further writes")
    box.check("apply: status --expect applied", box.verdict("applied"), (0, "OK: applied"))
    box.cli("plugin", "action", "invoke", "%s.status" % PLUGIN)
    box.settle()
    entry = box.action_log("status")
    box.check("apply: the status action reports the state in the plugin log",
              (entry["status"], entry["stdout"].strip().splitlines()[-1]),
              ("succeeded", "state: applied"))
    box.needs_no_change("apply: the status action wrote nothing")

    # --- events -----------------------------------------------------------
    box.agent(p_limit2, "blocked")
    box.settle()
    box.check("status event: hidden blocked agent is flagged", box.rows()[1], (None, "rate-limit", "+1!"))
    # Back to working: an idle agent nobody has looked at yet counts as done.
    box.agent(p_limit2, "working")

    box.cli("tab", "rename", t_review, "review-pr-2")
    box.settle()
    box.check("tab.renamed: label follows", box.rows()[2], (None, "review-pr-2", None))

    api.call("tab.move", {"tab_id": t_limit, "insert_index": 0})
    box.settle()
    box.check("tab.moved: heading moves to the new first tab", box.rows()[:3],
              [("🚀 api-server", "rate-limit", "+1"), (None, "fix-login", None), (None, "review-pr-2", None)])
    box.check("tab.moved: rendered order", panel_text(box.panel())[:4],
              [" 🚀 api-server", "   rate-limit · +1", "   fix-login", "   review-pr-2"])

    before = box.tokens()
    count = len(box.logs())
    api.call("workspace.move", {"workspace_id": w2, "insert_index": 0})
    box.settle()
    box.check("workspace.move: no hook runs and no token changes",
              (box.tokens(), len(box.logs())), (before, count))
    box.check("workspace.move: rendered headings follow the Spaces order", panel_text(box.panel()),
              [" web-app", "   update-deps", " 🚀 api-server", "   rate-limit · +1", "   fix-login", "   review-pr-2"])
    api.call("workspace.move", {"workspace_id": w1, "insert_index": 0})

    box.cli("tab", "close", t_limit)
    box.settle()
    box.check("tab.closed: heading moves to the next tab", box.rows(),
              [("🚀 api-server", "fix-login", None), (None, "review-pr-2", None), ("web-app", "update-deps", None)])

    # A new tab with two agents; the first one detected stays representative.
    pair = box.cli("tab", "create", "--workspace", w1, "--label", "pair", "--no-focus")
    p_a = pair["root_pane"]["pane_id"]
    p_b = box.cli("pane", "split", p_a, "--direction", "right", "--no-focus")["pane"]["pane_id"]
    box.agent(p_b)
    box.settle()
    box.agent(p_a)
    box.settle()
    box.check("new agent tab: row appears", box.rows()[2], (None, "pair", "+1"))
    box.check("representative is sticky", box.tokens()[p_b].get("ts_rep"), "1")
    box.cli("pane", "release-agent", p_b, "--source", "user:test", "--agent", "claude")
    box.settle()
    tokens = box.tokens()
    box.check("agent left: the other pane takes over", (tokens[p_a].get("ts_rep"), box.rows()[2]),
              ("1", (None, "pair", None)))
    snap_panes = {p["pane_id"]: planner.own_tokens(p.get("tokens")) for p in api.snapshot()["panes"]}
    box.check("agent left: its pane is cleaned", snap_panes[p_b], {})

    # --- burst ------------------------------------------------------------
    started = time.time()
    procs = []
    for index in range(30):
        target = t_review if index % 2 else t_login
        procs.append(subprocess.Popen([box.bin, "tab", "rename", target, "n%d" % index],
                                      env=box.env, stdout=subprocess.DEVNULL))
    for proc in procs:
        proc.wait()
    box.cli("tab", "rename", t_login, "fix-login")
    box.cli("tab", "rename", t_review, "review-pr")
    logs = box.settle(60)
    burst = [entry for entry in logs if entry["started_unix_ms"] >= started * 1000]
    failed = [entry for entry in burst if entry["status"] != "succeeded"]
    outcomes = [json.loads(entry["stdout"])["result"] for entry in burst if entry["status"] == "succeeded"]
    print("    burst: %d hooks, %d synced, %d coalesced, %d handed over, %d failed" % (
        len(burst), outcomes.count("synced"), outcomes.count("coalesced"),
        outcomes.count("handed_over"), len(failed)))
    box.check("burst: no hook failed", failed, [])
    box.check("burst: final labels are right", box.rows(),
              [("🚀 api-server", "fix-login", None), (None, "review-pr", None), (None, "pair", None),
               ("web-app", "update-deps", None)])
    box.needs_no_change("burst: nothing left to change")
    # Many event runs have been logged since; the action's own entry is still found.
    entry = box.action_log("apply")
    box.check("burst: apply result is still readable by action",
              (entry["status"], entry["exit_code"], json.loads(entry["stdout"])["result"]),
              ("succeeded", 0, "synced"))
    box.check("burst: the newest log entries are events, not the action",
              [e.get("action_id") for e in logs[-3:]], [None, None, None])

    # --- resync -----------------------------------------------------------
    api.report_tokens(p_review, "plugin:%s" % PLUGIN, {"ts_group": "WRONG", "ts_pos": "0000"})
    box.cli("plugin", "action", "invoke", "%s.resync" % PLUGIN)
    logs = box.settle()
    box.check("resync: action succeeded", logs[-1]["status"], "succeeded")
    box.check("resync: stray heading is removed", box.rows()[1], (None, "review-pr", None))

    # --- errors are not treated as success ---------------------------------
    try:
        api.call("events.subscribe", {"subscriptions": [{"type": "pane.agent_status_changed"}]})
        raised = None
    except HerdrError as error:
        raised = error.code
    box.check("an error reply raises", raised, "invalid_request")

    # --- server restart ---------------------------------------------------
    box.stop()
    box.start()
    api = box.api()
    box.settle()
    startup = [entry for entry in box.logs() if entry.get("event") == "startup"]
    box.check("restart: startup hook ran", [entry["status"] for entry in startup], ["succeeded"])
    live = {p["pane_id"] for p in api.snapshot()["panes"]}
    for pane in (p_login, p_review, p_a, p_deps):
        if pane in live:
            box.agent(pane)
    box.settle()
    box.check("restart: rows are back", box.rows(),
              [("🚀 api-server", "fix-login", None), (None, "review-pr", None), (None, "pair", None),
               ("web-app", "update-deps", None)])
    box.check("restart: view is back", box.panel()["header"], ["agents", "tabs"])

    # --- release ----------------------------------------------------------
    box.cli("plugin", "action", "invoke", "%s.release" % PLUGIN)
    logs = box.settle()
    box.check("release: action succeeded", (logs[-1]["status"], logs[-1]["exit_code"]), ("succeeded", 0))
    box.check("release: config is byte-identical to the original", box.read_config(), USER_CONFIG)
    box.check("release: every token is gone", any(
        planner.own_tokens(p.get("tokens")) for p in api.snapshot()["panes"]), False)
    panel = box.panel()
    box.check("release: standard header is back", panel["header"], ["agents", "priority"])
    box.check("release: standard two-line rows are back",
              (any("web-app · update-deps" in line for line in panel["lines"]),
               "   claude" in panel["lines"]), (True, True))
    box.cli("tab", "rename", t_review, "after-release")
    box.settle()
    box.check("release: later events write nothing", any(box.tokens().values()), False)
    box.check("release: status --expect released",
              (box.verdict("released"), box.verdict("applied")[0]), ((0, "OK: released"), 1))
    entry = box.action_log("release")
    box.check("release: result is readable by action after later events",
              (entry["status"], json.loads(entry["stdout"])["result"],
               box.logs()[-1].get("action_id")),
              ("succeeded", "cleared", None))

    # --- damaged markers: neither action writes ----------------------------
    damaged = USER_CONFIG + config_edit.BEGIN + "\n[ui.sidebar.agents]\nrow_gap = 0\n"
    with open(box.config, "w", encoding="utf-8") as stream:
        stream.write(damaged)
    for action in ("apply", "release"):
        box.cli("plugin", "action", "invoke", "%s.%s" % (PLUGIN, action))
        box.settle()
        entry = box.action_log(action)
        box.check("damaged markers: %s fails and says why" % action,
                  (entry["status"], entry["exit_code"], "markers in config.toml are damaged" in entry["stderr"]),
                  ("failed", 1, True))
        box.check("damaged markers: %s leaves the file alone" % action, box.read_config(), damaged)
    box.check("damaged markers: nothing was enabled", any(box.tokens().values()), False)
    box.cli("plugin", "action", "invoke", "%s.status" % PLUGIN)
    box.settle()
    entry = box.action_log("status")
    box.check("damaged markers: the status action reports them",
              (entry["status"], entry["stdout"].strip().splitlines()[-1].split(":")[:2]),
              ("succeeded", ["state", " damaged"]))
    with open(box.config, "w", encoding="utf-8") as stream:
        stream.write(USER_CONFIG)

    # --- apply again, then refuse a conflicting config ----------------------
    with open(box.config, "a", encoding="utf-8") as stream:
        stream.write("[ui.sidebar.agents]\nrow_gap = 1\n")
    conflicted = box.read_config()
    box.cli("plugin", "action", "invoke", "%s.apply" % PLUGIN)
    logs = box.settle()
    box.check("conflict: apply fails", (logs[-1]["status"], logs[-1]["exit_code"]), ("failed", 1))
    box.check("conflict: config left alone", box.read_config(), conflicted)
    box.check("conflict: nothing was enabled", any(box.tokens().values()), False)
    entry = box.action_log("apply")
    box.check("conflict: the failed apply is readable by action",
              (entry["status"], entry["exit_code"], "already defines" in entry["stderr"]),
              ("failed", 1, True))
    box.check("conflict: status says not applied", box.verdict("applied")[0], 1)

    box.cli("plugin", "unlink", PLUGIN)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--herdr", help="herdr executable (default: the one on PATH)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args()
    box = Sandbox(sandbox.find_herdr(args.herdr))
    print("isolated server under %s" % box.dir)
    try:
        box.start()
        scenario(box)
    finally:
        box.stop()
        if args.keep:
            print("kept %s" % box.dir)
        else:
            box.remove()
    print("\nPASS: %d checks" % box.checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
