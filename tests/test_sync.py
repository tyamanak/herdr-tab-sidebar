import copy
import tempfile
import threading
import time
import unittest
from unittest import mock

from tab_sidebar import plan as planner
from tab_sidebar import sync as syncer
from tab_sidebar.api import HerdrError

from tests.helpers import snapshot

SOURCE = "plugin:test"


class FakeHerdr:
    """In-memory stand-in for the socket client, with hooks to change state mid-run."""

    def __init__(self, snap):
        self.snap = snap
        self.lock = threading.Lock()
        self.view = None
        self.calls = []
        self.before_report = None
        self.snapshots = 0

    def snapshot(self):
        with self.lock:
            self.snapshots += 1
            return copy.deepcopy(self.snap)

    def set_view(self, params):
        self.calls.append(("view.set", params["source"]))
        self.view = params
        return {"type": "agent_view", "active": True}

    def clear_view(self, source):
        self.calls.append(("view.clear", source))
        if self.view and self.view["source"] == source:
            self.view = None
        return {"type": "agent_view", "active": False}

    def report_tokens(self, pane_id, source, tokens):
        if self.before_report:
            hook, self.before_report = self.before_report, None
            hook()
        with self.lock:
            targets = [e for g in ("panes", "agents") for e in self.snap[g] if e["pane_id"] == pane_id]
            if not targets:
                raise HerdrError("pane.report_metadata", "pane_not_found", pane_id)
            self.calls.append(("report", pane_id, dict(tokens)))
            for entry in targets:
                merged = dict(entry.get("tokens") or {})
                for name, value in tokens.items():
                    if value is None:
                        merged.pop(name, None)
                    else:
                        merged[name] = value
                entry["tokens"] = merged

    def close_tab(self, tab_id):
        with self.lock:
            for group in ("tabs", "panes", "agents"):
                self.snap[group] = [e for e in self.snap[group] if e["tab_id"] != tab_id]

    def shown(self):
        entries = [(a["tokens"].get("ts_group"), a["tokens"].get("ts_label"), a["pane_id"])
                   for a in self.snap["agents"] if a.get("tokens", {}).get("ts_rep") == "1"]
        return entries

    def reports(self):
        return [c for c in self.calls if c[0] == "report"]


def two_workspaces():
    return snapshot(
        ("w1", "api-server", [("t1", "fix-login", [("p1", "idle")]), ("t2", "review-pr", [("p2", "idle")])]),
        ("w2", "web-app", [("t1", "update-deps", [("p1", "working"), ("p2", "idle")])]),
    )


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state = syncer.State(self.dir.name)
        self.herdr = FakeHerdr(two_workspaces())

    def test_nothing_happens_until_applied(self):
        self.assertEqual(syncer.sync(self.herdr, self.state, SOURCE)["result"], "disabled")
        self.assertEqual(self.herdr.calls, [])

    def test_sync_writes_tokens_sets_the_view_and_verifies(self):
        self.state.set_enabled(True)
        result = syncer.sync(self.herdr, self.state, SOURCE)
        self.assertEqual(result["result"], "synced")
        self.assertEqual(result["passes"], 2)  # write, then confirm from a fresh snapshot
        self.assertEqual(self.herdr.view["source"], SOURCE)
        self.assertEqual(
            self.herdr.shown(),
            [("api-server", "fix-login", "w1:p1"), (None, planner.PAD + "review-pr", "w1:p2"),
             ("web-app", "update-deps", "w2:p1")],
        )

    def test_second_sync_writes_nothing_but_restores_the_view(self):
        self.state.set_enabled(True)
        syncer.sync(self.herdr, self.state, SOURCE)
        before = len(self.herdr.reports())
        self.herdr.view = None  # e.g. the plugin was disabled and enabled again
        result = syncer.sync(self.herdr, self.state, SOURCE)
        self.assertEqual((result["result"], result["passes"]), ("synced", 1))
        self.assertEqual(len(self.herdr.reports()), before)
        self.assertIsNotNone(self.herdr.view)

    def test_force_rewrites_every_token(self):
        self.state.set_enabled(True)
        syncer.sync(self.herdr, self.state, SOURCE)
        before = len(self.herdr.reports())
        syncer.sync(self.herdr, self.state, SOURCE, force=True)
        self.assertEqual(len(self.herdr.reports()) - before, 4)  # 3 rows + 1 extra agent

    def test_change_during_a_run_is_picked_up_before_it_returns(self):
        self.state.set_enabled(True)
        syncer.sync(self.herdr, self.state, SOURCE)
        # While the next run is writing, the heading tab closes.
        self.herdr.snap["tabs"][1]["label"] = "renamed"
        self.herdr.before_report = lambda: self.herdr.close_tab("w1:t1")
        result = syncer.sync(self.herdr, self.state, SOURCE)
        self.assertEqual(result["result"], "synced")
        self.assertEqual(
            self.herdr.shown(), [("api-server", "renamed", "w1:p2"), ("web-app", "update-deps", "w2:p1")]
        )

    def test_pane_closed_while_writing_is_not_an_error(self):
        self.state.set_enabled(True)
        self.herdr.before_report = lambda: self.herdr.close_tab("w2:t1")
        result = syncer.sync(self.herdr, self.state, SOURCE)
        self.assertEqual(result["result"], "synced")
        self.assertEqual([r[2] for r in self.herdr.shown()], ["w1:p1", "w1:p2"])

    def test_other_api_errors_are_raised(self):
        self.state.set_enabled(True)

        def fail(*args):
            raise HerdrError("pane.report_metadata", "invalid_request", "missing field")

        self.herdr.report_tokens = fail
        with self.assertRaises(HerdrError):
            syncer.sync(self.herdr, self.state, SOURCE)

    def churn(self, passes=None, ticket=False):
        """Rename a tab before each snapshot, for ``passes`` snapshots or forever."""
        counter = [0]
        original = self.herdr.snapshot

        def snapshot():
            counter[0] += 1
            if passes is None or counter[0] <= passes:
                self.herdr.snap["tabs"][0]["label"] = "label-%d" % counter[0]
                if ticket:
                    self.state.take_ticket()  # the event that caused the change
            return original()

        self.herdr.snapshot = snapshot
        self.addCleanup(setattr, self.herdr, "snapshot", original)
        return original

    def test_change_on_five_passes_in_a_row_then_quiet_is_not_a_failure(self):
        # The events behind the changes have not taken a ticket yet.
        self.state.set_enabled(True)
        self.churn(passes=5)
        tickets = self.state.last_ticket()
        result = syncer.sync(self.herdr, self.state, SOURCE)
        self.assertEqual((result["result"], result["passes"]), ("synced", 6))
        self.assertEqual(self.state.last_ticket(), tickets + 1)
        self.assertEqual(
            self.herdr.shown(),
            [("api-server", "label-5", "w1:p1"), (None, planner.PAD + "review-pr", "w1:p2"),
             ("web-app", "update-deps", "w2:p1")],
        )
        self.assertEqual(planner.diff(planner.build_plan(self.herdr.snap)), {})

    def test_change_on_many_passes_then_quiet_is_not_a_failure(self):
        self.state.set_enabled(True)
        self.churn(passes=40)
        with mock.patch.object(syncer, "PASS_PAUSE_SECONDS", 0):
            result = syncer.sync(self.herdr, self.state, SOURCE)
        self.assertEqual((result["result"], result["passes"]), ("synced", 41))
        self.assertEqual(self.herdr.shown()[0], ("api-server", "label-40", "w1:p1"))

    def test_endless_churn_reports_failure(self):
        self.state.set_enabled(True)
        self.churn()
        with mock.patch.object(syncer, "CONVERGE_SECONDS", 0.2):
            with self.assertRaises(syncer.SyncError):
                syncer.sync(self.herdr, self.state, SOURCE)

    def test_churn_with_a_later_run_queued_hands_over(self):
        self.state.set_enabled(True)
        original = self.churn(ticket=True)
        with mock.patch.object(syncer, "CONVERGE_SECONDS", 0.2):
            self.assertEqual(syncer.sync(self.herdr, self.state, SOURCE)["result"], "handed_over")
        # The queued run is not skipped.
        self.herdr.snapshot = original
        self.assertLess(self.state.handled(), self.state.last_ticket())
        self.assertEqual(syncer.sync(self.herdr, self.state, SOURCE)["result"], "synced")

    def test_burst_of_events_is_serialised_and_coalesced(self):
        self.state.set_enabled(True)
        syncer.sync(self.herdr, self.state, SOURCE)
        self.herdr.calls.clear()
        snapshots_before = self.herdr.snapshots
        active = [0]
        overlap = []
        original = self.herdr.snapshot

        def watched():
            active[0] += 1
            overlap.append(active[0])
            try:
                # Long enough for the other events to take their tickets while
                # this one holds the lock; otherwise, on a busy machine, they
                # can run one after the other and none is coalesced.
                time.sleep(0.005)
                return original()
            finally:
                active[0] -= 1

        self.herdr.snapshot = watched
        results = []
        barrier = threading.Barrier(24)

        def event(index):
            barrier.wait()
            if index == 0:
                self.herdr.close_tab("w1:t1")
            results.append(syncer.sync(self.herdr, self.state, SOURCE)["result"])

        threads = [threading.Thread(target=event, args=(i,)) for i in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(max(overlap), 1)
        self.assertEqual(len(results), 24)
        self.assertGreaterEqual(results.count("coalesced"), 1)
        self.assertLess(self.herdr.snapshots - snapshots_before, 24 * 2)
        self.assertEqual(self.herdr.shown(), [("api-server", "review-pr", "w1:p2"), ("web-app", "update-deps", "w2:p1")])
        self.assertEqual(self.state.handled(), self.state.last_ticket())

    def test_event_after_the_last_snapshot_is_never_dropped(self):
        self.state.set_enabled(True)
        syncer.sync(self.herdr, self.state, SOURCE)
        # An event whose ticket is newer than the handled mark must run.
        self.herdr.close_tab("w1:t1")
        self.assertEqual(syncer.sync(self.herdr, self.state, SOURCE)["result"], "synced")
        self.assertEqual(self.herdr.shown()[0], ("api-server", "review-pr", "w1:p2"))

    def test_clear_removes_view_and_tokens_and_stops_later_events(self):
        self.state.set_enabled(True)
        syncer.sync(self.herdr, self.state, SOURCE)
        self.herdr.snap["agents"][0]["tokens"]["model"] = "opus"
        result = syncer.clear(self.herdr, self.state, SOURCE)
        self.assertEqual(result["result"], "cleared")
        self.assertIsNone(self.herdr.view)
        leftovers = [e.get("tokens") for g in ("panes", "agents") for e in self.herdr.snap[g]
                     if any(k.startswith("ts_") for k in e.get("tokens") or {})]
        self.assertEqual(leftovers, [])
        self.assertEqual(self.herdr.snap["agents"][0]["tokens"], {"model": "opus"})
        self.assertFalse(self.state.enabled)
        self.assertEqual(syncer.sync(self.herdr, self.state, SOURCE)["result"], "disabled")

    def test_lock_timeout_is_reported(self):
        with syncer.locked(self.state.path("sync.lock"), 1):
            with self.assertRaises(syncer.SyncError):
                with syncer.locked(self.state.path("sync.lock"), 0.1):
                    pass


if __name__ == "__main__":
    unittest.main()
