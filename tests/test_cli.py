import ast
import contextlib
import copy
import errno
import io
import json
import os
import runpy
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from tab_sidebar import cli, config_edit, sync as syncer

from tests.helpers import fake_command, settle, snapshot
from tests.test_sync import FakeHerdr

CONFIG = "[ui]\nagent_panel_sort = \"priority\"\n"
SNAP = ("w1", "api-server", [("t1", "fix-login", [("p1", "idle")])])
TWO_TABS = ("w1", "api-server", [("t1", "fix-login", [("p1", "idle")]),
                                 ("t2", "review-pr", [("p2", "idle")])])


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.config = os.path.join(self.dir.name, "config.toml")
        with open(self.config, "w") as stream:
            stream.write(CONFIG)
        self.state_dir = os.path.join(self.dir.name, "state")
        self.herdr = FakeHerdr(snapshot(SNAP))
        self.reload = mock.Mock(return_value="applied")
        env = {"HERDR_CONFIG_PATH": self.config, "HERDR_PLUGIN_STATE_DIR": self.state_dir,
               "HERDR_BIN_PATH": fake_command(self.dir.name, 0),
               "HERDR_SOCKET_PATH": "unused"}
        for patcher in (mock.patch.dict(os.environ, env),
                        mock.patch.object(cli, "Herdr", lambda: self.herdr),
                        mock.patch.object(cli, "reload_config", self.reload)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def read_config(self):
        with open(self.config) as stream:
            return stream.read()

    def fail_reports(self, after=0, until=None):
        """Let ``after`` token writes through, then fail (up to write ``until``)."""
        original = self.herdr.report_tokens
        count = [0]

        def report(*args):
            count[0] += 1
            if count[0] > after and (until is None or count[0] <= until):
                raise cli.HerdrError("pane.report_metadata", "invalid_request", "boom")
            return original(*args)

        self.herdr.report_tokens = report

    def leftovers(self):
        return [entry["pane_id"] for group in ("panes", "agents") for entry in self.herdr.snap[group]
                if any(name.startswith("ts_") for name in entry.get("tokens") or {})]
    def session(self):
        """What apply and release may change, to compare before and after."""
        return (self.read_config(), syncer.State(self.state_dir, create=False).enabled,
                copy.deepcopy(self.herdr.view),
                [copy.deepcopy(entry.get("tokens")) for entry in self.herdr.snap["agents"]])


class CliTest(Fixture):
    def test_status_tells_applied_from_released(self):
        self.assertEqual(self.run_main("status", "--expect", "released")[0], 0)
        self.assertFalse(os.path.exists(self.state_dir))  # status creates nothing
        code, out, _ = self.run_main("status", "--expect", "applied")
        self.assertEqual(code, 1)
        self.assertIn("NOT applied", out)

        self.assertEqual(self.run_main("apply")[0], 0)
        code, out, _ = self.run_main("status", "--expect", "applied")
        self.assertEqual((code, out.splitlines()[-1]), (0, "OK: applied (1 rows)"))
        self.assertEqual(self.run_main("status", "--expect", "released")[0], 1)

        self.assertEqual(self.run_main("release")[0], 0)
        self.assertEqual(self.run_main("status", "--expect", "released")[0], 0)
        self.assertEqual(self.read_config(), CONFIG)

    def test_status_without_an_expectation_names_the_state(self):
        def state():
            code, out, _ = self.run_main("status")
            return code, out.splitlines()[-1]

        self.assertEqual(state(), (0, "state: released"))
        self.run_main("apply")
        self.assertEqual(state(), (0, "state: applied"))
        self.herdr.snap["tabs"][0]["label"] = "renamed"
        code, line = state()
        self.assertEqual(code, 0)
        self.assertTrue(line.startswith("state: neither applied (1 pane(s) do not carry"), line)
        self.assertIn("nor released (the plugin is still enabled", line)

    def test_status_notices_tokens_that_went_stale(self):
        self.run_main("apply")
        self.herdr.snap["tabs"][0]["label"] = "renamed"
        code, out, _ = self.run_main("status", "--expect", "applied")
        self.assertEqual(code, 1)
        self.assertIn("1 pane(s) do not carry the right tokens", out)

    def test_apply_that_fails_after_writing_the_config_puts_it_back(self):
        self.reload.side_effect = [syncer.SyncError("reload-config failed"), "applied"]
        code, _, err = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("reload-config failed", err)
        self.assertEqual(self.read_config(), CONFIG)
        self.assertEqual(self.reload.call_count, 2)  # the second one loads the restored file
        self.assertFalse(syncer.State(self.state_dir).enabled)
        self.assertEqual(self.herdr.reports(), [])

    def test_apply_that_fails_while_writing_tokens_puts_the_config_back(self):
        def fail(*args):
            raise cli.HerdrError("pane.report_metadata", "invalid_request", "boom")

        self.herdr.report_tokens = fail
        self.assertEqual(self.run_main("apply")[0], 1)
        self.assertEqual(self.read_config(), CONFIG)
        self.assertFalse(syncer.State(self.state_dir).enabled)
        self.assertEqual(self.run_main("event")[1].strip(), json.dumps({"result": "disabled"}))

    def test_apply_that_fails_part_way_through_the_tokens_takes_everything_back(self):
        self.herdr.snap = snapshot(TWO_TABS)
        self.fail_reports(after=1, until=2)
        code, _, err = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("boom", err)
        # One token write went through and the view was set before the failure.
        self.assertEqual(len(self.herdr.reports()), 2)  # that write, and its removal
        self.assertIn(("view.set", cli.source()), self.herdr.calls)
        self.assertIsNone(self.herdr.view)
        self.assertEqual(self.leftovers(), [])
        self.assertFalse(syncer.State(self.state_dir).enabled)
        self.assertEqual(self.read_config(), CONFIG)
        self.assertEqual(self.run_main("status", "--expect", "released")[0], 0)

    def test_a_failing_undo_does_not_hide_the_first_error(self):
        self.herdr.snap = snapshot(TWO_TABS)
        self.fail_reports(after=1)
        self.herdr.clear_view = mock.Mock(
            side_effect=cli.HerdrError("agent.view.clear", "socket_error", "gone"))
        self.reload.side_effect = ["applied", syncer.SyncError("reload-config failed")]
        code, _, err = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("pane.report_metadata failed: invalid_request: boom", err)
        self.assertNotIn("gone", err)
        self.assertNotIn("reload-config", err)
        # What could still be taken back was.
        self.assertFalse(syncer.State(self.state_dir).enabled)
        self.assertEqual(self.read_config(), CONFIG)

    def test_failed_reapply_leaves_an_applied_session_applied(self):
        self.run_main("apply")
        applied = self.read_config()
        tokens = [entry.get("tokens") for entry in self.herdr.snap["agents"]]
        self.fail_reports()
        self.assertEqual(self.run_main("apply")[0], 1)
        self.assertEqual(self.read_config(), applied)
        self.assertIn(config_edit.BEGIN, applied)
        self.assertTrue(syncer.State(self.state_dir).enabled)
        self.assertIsNotNone(self.herdr.view)
        self.assertNotIn(("view.clear", cli.source()), self.herdr.calls)
        self.assertEqual([entry.get("tokens") for entry in self.herdr.snap["agents"]], tokens)

    def test_failed_reapply_keeps_a_block_it_had_to_reset(self):
        self.run_main("apply")
        applied = self.read_config()
        with open(self.config, "w") as stream:
            stream.write(applied.replace("row_gap = 0", "row_gap = 1"))
        self.fail_reports()
        self.assertEqual(self.run_main("apply")[0], 1)
        self.assertEqual(self.read_config(), applied)
        self.assertTrue(syncer.State(self.state_dir).enabled)
        self.assertIsNotNone(self.herdr.view)

    def test_preview_reads_a_snapshot_file(self):
        path = os.path.join(self.dir.name, "snap.json")
        with open(path, "w") as stream:
            json.dump({"result": {"snapshot": settle(snapshot(SNAP))}}, stream)
        code, out, _ = self.run_main("preview", "--snapshot", path)
        self.assertEqual((code, out), (0, "api-server\n  fix-login · [idle]\n"))

SOUND = "[ui.sound]\nenabled = false\n"


class DamagedMarkersCliTest(Fixture):
    def damage(self):
        """An applied session whose end marker was lost, with a setting added."""
        text = self.read_config().replace(config_edit.END + "\n", "") + SOUND + config_edit.BLOCK
        with open(self.config, "w") as stream:
            stream.write(text)

    def test_apply_and_release_leave_an_applied_session_with_damaged_markers_alone(self):
        self.run_main("apply")
        self.damage()
        before = self.session()
        calls = len(self.herdr.calls)
        for command in ("apply", "release"):
            code, out, err = self.run_main(command)
            self.assertEqual((code, out), (1, ""), command)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
            self.assertIn("tab-sidebar: the plugin's markers in config.toml are damaged", err)
            self.assertIn('"Uninstall"', err)
            self.assertEqual(self.session(), before, command)
            self.assertEqual(len(self.herdr.calls), calls, command)  # Herdr was not asked a thing
        self.assertEqual(self.reload.call_count, 1)  # only the first, good apply

    def test_every_kind_of_damage_stops_both_actions_before_they_write(self):
        shapes = {
            "nested begin": CONFIG + config_edit.BEGIN + "\n" + SOUND + config_edit.BEGIN + "\n"
                            + config_edit.END + "\n",
            "end first": CONFIG + config_edit.END + "\n" + SOUND + config_edit.BEGIN + "\n",
            "mid-line": CONFIG + "x = 1 " + config_edit.BEGIN + "\n" + SOUND + config_edit.END + "\n",
            "two blocks": CONFIG + config_edit.BLOCK + SOUND + config_edit.BLOCK,
        }
        for name, text in shapes.items():
            with open(self.config, "w") as stream:
                stream.write(text)
            before = self.session()
            for command in ("apply", "release"):
                self.assertEqual(self.run_main(command)[0], 1, (name, command))
                self.assertEqual(self.session(), before, (name, command))
        self.assertEqual(self.herdr.calls, [])
        self.reload.assert_not_called()

    def test_status_reports_damaged_markers_in_one_line(self):
        self.run_main("apply")
        self.damage()
        code, out, err = self.run_main("status")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.splitlines()[-1].startswith(
            "state: damaged: the plugin's markers in config.toml are damaged"), out)
        self.assertIsNone(json.loads(out.splitlines()[0])["config_block"])
        for expect in ("applied", "released"):
            code, out, err = self.run_main("status", "--expect", expect)
            self.assertEqual((code, err), (1, ""))
            self.assertEqual(len(out.splitlines()), 2)
            self.assertTrue(out.splitlines()[-1].startswith(
                "NOT %s: the plugin's markers in config.toml are damaged" % expect), out)


class ChangedMeanwhileCliTest(Fixture):
    def test_apply_does_not_overwrite_an_edit_made_during_the_check(self):
        def edit_during_check(_herdr, _candidate):
            with open(self.config, "a") as stream:
                stream.write(SOUND)
            return True, "ok"

        with mock.patch.object(config_edit, "check", side_effect=edit_during_check):
            code, _, err = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("config.toml changed while the plugin was working on it", err)
        self.assertEqual(self.read_config(), CONFIG + SOUND)
        self.assertFalse(syncer.State(self.state_dir).enabled)
        self.assertEqual(self.leftovers(), [])
        self.assertIsNone(self.herdr.view)
        self.reload.assert_not_called()
        self.assertEqual(self.run_main("status", "--expect", "released")[0], 0)
        # Run again, as the message says.
        self.assertEqual(self.run_main("apply")[0], 0)
        self.assertEqual(self.read_config(), CONFIG + SOUND + config_edit.BLOCK)

    def test_release_does_not_overwrite_an_edit_and_stays_applied(self):
        self.run_main("apply")
        real = tempfile.mkstemp

        def edit_then_make(*args, **kwargs):
            with open(self.config, "a") as stream:
                stream.write(SOUND)
            return real(*args, **kwargs)

        with mock.patch.object(config_edit.tempfile, "mkstemp", side_effect=edit_then_make):
            code, _, err = self.run_main("release")
        self.assertEqual(code, 1)
        self.assertIn("config.toml changed while the plugin was working on it", err)
        self.assertEqual(self.read_config(), CONFIG + config_edit.BLOCK + SOUND)
        # Still applied in every respect, not half released.
        self.assertEqual(self.run_main("status", "--expect", "applied")[0], 0)
        self.assertIsNotNone(self.herdr.view)
        self.assertEqual(self.run_main("release")[0], 0)
        self.assertEqual(self.read_config(), CONFIG + SOUND)

    def together(self, *commands):
        """Run the actions at once. Returns the threads in the order they used Herdr."""
        order = []
        for name in ("set_view", "clear_view", "report_tokens"):
            def recorded(*args, _real=getattr(self.herdr, name)):
                order.append(threading.current_thread().name)
                time.sleep(0.002)
                return _real(*args)
            setattr(self.herdr, name, recorded)
        self.reload.side_effect = lambda: time.sleep(0.02) or "applied"
        barrier = threading.Barrier(len(commands))
        errors = []

        def run(handler):
            barrier.wait()
            try:
                handler(None)
            except Exception as error:  # reported by the assertion below
                errors.append(error)

        threads = [threading.Thread(target=run, args=(handler,), name="%s-%d" % (handler.__name__, i))
                   for i, handler in enumerate(commands)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        runs = [name for index, name in enumerate(order) if index == 0 or order[index - 1] != name]
        self.assertEqual(len(runs), len(set(runs)), "actions interleaved: %s" % runs)
        return runs

    def verdicts(self):
        return [self.run_main("status", "--expect", expect)[0] for expect in ("applied", "released")]

    def test_two_applies_at_once_run_one_after_the_other(self):
        self.herdr.snap = snapshot(TWO_TABS)
        self.assertEqual(len(self.together(cli.cmd_apply, cli.cmd_apply)), 2)
        self.assertEqual(self.verdicts(), [0, 1])
        self.assertEqual(self.read_config(), CONFIG + config_edit.BLOCK)

    def test_apply_and_release_at_once_end_in_one_state_or_the_other(self):
        self.herdr.snap = snapshot(TWO_TABS)
        for _ in range(5):
            self.together(cli.cmd_apply, cli.cmd_release)
            self.assertEqual(sorted(self.verdicts()), [0, 1])
            self.assertIn(self.read_config(), (CONFIG, CONFIG + config_edit.BLOCK))
        # From an applied session as well.
        self.run_main("apply")
        self.together(cli.cmd_release, cli.cmd_apply, cli.cmd_release)
        self.assertEqual(sorted(self.verdicts()), [0, 1])

    def test_a_release_that_arrives_in_the_middle_of_an_apply_waits_for_it(self):
        self.herdr.snap = snapshot(TWO_TABS)
        release, finished = [], []

        def reload():
            if not release:
                # The apply has written the block and is not enabled yet.
                release.append(threading.Thread(
                    target=lambda: finished.append(cli.cmd_release(None)["result"])))
                release[0].start()
                release[0].join(0.3)
                self.assertEqual(finished, [], "the release did not wait for the apply")
            return "applied"

        self.reload.side_effect = reload
        self.assertEqual(self.run_main("apply")[0], 0)
        release[0].join(10)
        self.assertEqual(finished, ["cleared"])
        # The release ran after the whole apply, so the session is released.
        self.assertEqual(self.verdicts(), [1, 0])
        self.assertEqual(self.read_config(), CONFIG)

    def test_an_action_does_not_wait_on_its_own_sync_lock(self):
        with mock.patch.object(cli, "ACTION_LOCK_SECONDS", 2), \
                mock.patch.object(syncer, "LOCK_TIMEOUT_SECONDS", 2):
            started = time.monotonic()
            self.assertEqual(self.run_main("apply")[0], 0)
            self.assertEqual(self.run_main("release")[0], 0)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_a_second_action_gives_up_with_a_reason_when_the_first_never_ends(self):
        self.run_main("status")
        os.makedirs(self.state_dir, exist_ok=True)
        with syncer.locked(os.path.join(self.state_dir, "action.lock"), 1):
            with mock.patch.object(cli, "ACTION_LOCK_SECONDS", 0.1):
                code, _, err = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("timed out waiting for action.lock", err)
        self.assertEqual(self.read_config(), CONFIG)

    def test_event_hooks_do_not_take_the_action_lock(self):
        self.run_main("apply")
        with syncer.locked(os.path.join(self.state_dir, "action.lock"), 1):
            code, out, _ = self.run_main("event")
        self.assertEqual((code, json.loads(out)["result"]), (0, "synced"))


class ReloadOwedTest(Fixture):
    """Herdr does not reload config.toml after the plugin took its block out."""

    def status(self, *expect):
        code, out, _ = self.run_main("status", *expect)
        return code, out.splitlines()[-1]

    def pending(self):
        return syncer.State(self.state_dir, create=False).reload_pending

    def assert_not_released(self):
        code, line = self.status("--expect", "released")
        self.assertEqual(code, 1)
        self.assertTrue(line.startswith(
            "NOT released: the running Herdr has not reloaded config.toml"), line)
        self.assertIn("run the release action again", line)
        self.assertIn("herdr server reload-config", line)
        code, line = self.status()
        self.assertEqual(code, 0)
        self.assertTrue(line.startswith("state: neither applied ("), line)
        self.assertIn("nor released (the running Herdr has not reloaded config.toml", line)

    def test_a_release_whose_reload_failed_is_not_released_until_a_retry_reloads(self):
        self.run_main("apply")
        self.reload.side_effect = [syncer.SyncError("reload-config failed: busy")]
        code, _, err = self.run_main("release")
        self.assertEqual((code, err.strip()), (1, "tab-sidebar: reload-config failed: busy"))
        # The file, the tokens, the view and the flag are all released...
        self.assertEqual(self.read_config(), CONFIG)
        self.assertEqual((self.leftovers(), self.herdr.view), ([], None))
        self.assertFalse(syncer.State(self.state_dir).enabled)
        # ...but the running server still draws the row layout.
        self.assertTrue(self.pending())
        self.assert_not_released()
        self.assertEqual(self.status("--expect", "applied")[0], 1)

        # Still failing: the retry tries again and says so again.
        self.reload.side_effect = [syncer.SyncError("reload-config failed: busy")]
        calls = self.reload.call_count
        self.assertEqual(self.run_main("release")[0], 1)
        self.assertEqual(self.reload.call_count, calls + 1)
        self.assert_not_released()

        self.reload.side_effect = None
        code, out, _ = self.run_main("release")
        self.assertEqual(code, 0)
        self.assertEqual(self.reload.call_count, calls + 2)
        self.assertEqual((json.loads(out)["config_changed"], json.loads(out)["reload"]),
                         (False, "applied"))
        self.assertFalse(self.pending())
        self.assertEqual(self.status("--expect", "released"), (0, "OK: released (1 rows)"))
        self.assertEqual(self.status(), (0, "state: released"))

    def test_an_undo_whose_reload_failed_is_finished_by_release(self):
        self.reload.side_effect = ["applied", syncer.SyncError("reload-config failed: busy")]
        with mock.patch.object(syncer.State, "record", disk_full):
            code, _, err = self.run_main("apply")
        lines = err.strip().splitlines()
        self.assertEqual((code, lines[0]), (1, "tab-sidebar: [Errno 28] No space left on device"))
        self.assertIn("still there: the row layout in the running server", lines[1])
        self.assertIn("run the release action to try again", lines[1])
        self.assertEqual(self.read_config(), CONFIG)
        self.assertTrue(self.pending())
        self.assert_not_released()

        self.reload.side_effect = None
        calls = self.reload.call_count
        self.assertEqual(self.run_main("release")[0], 0)
        self.assertEqual(self.reload.call_count, calls + 1)
        self.assertEqual(self.status("--expect", "released")[0], 0)

    def test_an_apply_that_succeeds_settles_an_owed_reload(self):
        self.run_main("apply")
        self.reload.side_effect = [syncer.SyncError("reload-config failed: busy")]
        self.assertEqual(self.run_main("release")[0], 1)
        self.assertTrue(self.pending())
        self.reload.side_effect = None
        self.assertEqual(self.run_main("apply")[0], 0)
        self.assertFalse(self.pending())
        self.assertEqual(self.status("--expect", "applied"), (0, "OK: applied (1 rows)"))
        self.assertEqual(self.run_main("release")[0], 0)
        self.assertEqual(self.status("--expect", "released")[0], 0)

    def test_release_with_nothing_applied_succeeds_and_reloads_once(self):
        code, out, _ = self.run_main("release")
        self.assertEqual((code, json.loads(out)["config_changed"]), (0, False))
        self.assertEqual(self.reload.call_count, 1)
        self.assertFalse(self.pending())
        self.assertEqual(self.status("--expect", "released")[0], 0)

    def test_a_release_that_wrote_nothing_owes_no_reload(self):
        self.run_main("apply")
        with mock.patch.object(config_edit, "remove",
                               side_effect=config_edit.ConfigError("changed meanwhile")):
            self.assertEqual(self.run_main("release")[0], 1)
        self.assertFalse(self.pending())
        self.assertEqual(self.status("--expect", "applied")[0], 0)

    def test_release_changes_nothing_when_it_cannot_note_the_owed_reload(self):
        self.run_main("apply")
        before = self.session()
        with mock.patch.object(syncer.State, "set_reload_pending", disk_full):
            code, _, err = self.run_main("release")
        self.assertEqual((code, err.strip()),
                         (1, "tab-sidebar: [Errno 28] No space left on device"))
        self.assertEqual(self.session(), before)
        self.assertEqual(self.status("--expect", "applied")[0], 0)

    def test_the_undo_of_apply_goes_on_when_it_cannot_note_the_owed_reload(self):
        with mock.patch.object(syncer.State, "record", disk_full), \
                mock.patch.object(syncer.State, "set_reload_pending", disk_full):
            code, _, err = self.run_main("apply")
        self.assertEqual((code, err.strip()),
                         (1, "tab-sidebar: [Errno 28] No space left on device"))
        self.assertEqual(self.read_config(), CONFIG)
        self.assertEqual((self.leftovers(), self.herdr.view), ([], None))
        self.assertFalse(syncer.State(self.state_dir).enabled)

    def test_damaged_markers_are_still_reported_first(self):
        self.run_main("apply")
        self.reload.side_effect = [syncer.SyncError("reload-config failed: busy")]
        self.run_main("release")
        with open(self.config, "a") as stream:
            stream.write(config_edit.BEGIN + "\n")
        self.assertTrue(self.status()[1].startswith("state: damaged: "))


def disk_full(*_args, **_kwargs):
    raise OSError(errno.ENOSPC, "No space left on device")


class StateWriteFailureTest(Fixture):
    """A state file cannot be written, as on a full disk."""

    def failing(self, name):
        if name == "enabled":
            real = syncer.State.set_enabled

            def set_enabled(state, value):
                return disk_full() if value else real(state, value)
            return mock.patch.object(syncer.State, "set_enabled", set_enabled)
        return mock.patch.object(syncer.State, name, disk_full)

    WRITES = ("enabled", "take_ticket", "set_handled", "record")

    def test_a_first_apply_takes_everything_back(self):
        for name in self.WRITES:
            self.herdr.snap = snapshot(TWO_TABS)
            self.herdr.calls.clear()
            with self.failing(name):
                code, out, err = self.run_main("apply")
            self.assertEqual((code, out), (1, ""), name)
            self.assertEqual(err.strip().splitlines(),
                             ["tab-sidebar: [Errno 28] No space left on device"], name)
            self.assertEqual(self.read_config(), CONFIG, name)
            self.assertFalse(syncer.State(self.state_dir).enabled, name)
            self.assertEqual(self.leftovers(), [], name)
            self.assertIsNone(self.herdr.view, name)
            self.assertIn(("view.clear", cli.source()), self.herdr.calls, name)
            self.assertEqual(self.run_main("status", "--expect", "released")[0], 0, name)

    def test_a_repeat_on_an_applied_session_leaves_it_applied(self):
        self.herdr.snap = snapshot(TWO_TABS)
        self.run_main("apply")
        before = self.session()
        for name in self.WRITES:
            with self.failing(name):
                code, _, err = self.run_main("apply")
            self.assertEqual(code, 1, name)
            self.assertIn("No space left on device", err)
            self.assertEqual(self.session(), before, name)
            self.assertEqual(self.run_main("status", "--expect", "applied")[0], 0, name)

    def test_every_entry_point_reports_it_in_one_line(self):
        self.run_main("apply")
        for command, patched in (
                (("event",), mock.patch.object(syncer.State, "take_ticket", disk_full)),
                (("resync",), mock.patch.object(syncer.State, "record", disk_full)),
                (("release",), mock.patch.object(syncer.State, "set_enabled", disk_full)),
                (("apply",), mock.patch.object(syncer.State, "set_handled", disk_full)),
                (("status",), mock.patch.object(cli.config_edit, "has_block", disk_full)),
                (("status", "--expect", "applied"),
                 mock.patch.object(syncer.State, "last_ticket", disk_full)),
                (("apply",), mock.patch.object(cli, "state", disk_full))):
            with patched:
                code, out, err = self.run_main(*command)
            self.assertEqual(code, 1, command)
            self.assertEqual(err.strip().splitlines(),
                             ["tab-sidebar: [Errno 28] No space left on device"], command)
            self.assertNotIn("Traceback", out + err)

    def test_what_could_not_be_taken_back_is_named_after_the_first_error(self):
        self.herdr.snap = snapshot(TWO_TABS)
        self.herdr.clear_view = mock.Mock(
            side_effect=cli.HerdrError("agent.view.clear", "socket_error", "gone"))
        self.reload.side_effect = ["applied", syncer.SyncError("reload-config failed")]
        with self.failing("set_handled"):
            code, _, err = self.run_main("apply")
        self.assertEqual(code, 1)
        lines = err.strip().splitlines()
        self.assertEqual(lines[0], "tab-sidebar: [Errno 28] No space left on device")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("tab-sidebar: could not take everything back; "
                                            "still there: the Agent view; "), lines[1])
        self.assertIn("the row layout in the running server", lines[1])
        self.assertIn("status action", lines[1])
        self.assertIn('"Uninstall" in the README', lines[1])
        # What could be taken back was: the block, the flag and the tokens.
        self.assertEqual(self.read_config(), CONFIG)
        self.assertFalse(syncer.State(self.state_dir).enabled)
        self.assertEqual(self.leftovers(), [])

    def test_a_block_that_cannot_be_removed_is_named_too(self):
        with self.failing("record"), \
                mock.patch.object(config_edit, "remove", side_effect=disk_full):
            code, _, err = self.run_main("apply")
        self.assertEqual(code, 1)
        self.assertIn("still there: the managed block in config.toml", err)
        self.assertIn(config_edit.BEGIN, self.read_config())


class PluginIdTest(unittest.TestCase):
    def manifest(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = os.path.join(directory.name, "herdr-plugin.toml")
        with open(path, "w") as stream:
            stream.write(text)
        return path

    def test_the_id_comes_from_the_manifest(self):
        with open(cli.MANIFEST, encoding="utf-8") as stream:
            self.assertIn('\nid = "%s"\n' % cli.manifest_id(), "\n" + stream.read())
        with mock.patch.dict(os.environ):
            os.environ.pop("HERDR_PLUGIN_ID", None)
            self.assertEqual(cli.source(), "plugin:%s" % cli.manifest_id())

    def test_herdr_may_name_the_plugin(self):
        with mock.patch.dict(os.environ, {"HERDR_PLUGIN_ID": "someone.else"}):
            self.assertEqual(cli.source(), "plugin:someone.else")

    def test_only_the_top_level_id_counts(self):
        path = self.manifest('# id = "no"\nname = "x"\nid = "a.b-c"  # the id\n'
                             '[[actions]]\nid = "apply"\n')
        self.assertEqual(cli.manifest_id(path), "a.b-c")
        with self.assertRaises(syncer.SyncError):
            cli.manifest_id(self.manifest('name = "x"\n[[actions]]\nid = "apply"\n'))


class LauncherTest(unittest.TestCase):
    """main.py must say why it stops on an interpreter that is too old."""

    path = os.path.join(os.path.dirname(cli.MANIFEST), "main.py")

    def test_an_old_python_is_told_the_reason(self):
        err = io.StringIO()
        old = (3, 8, 18, "final", 0)
        with mock.patch.object(sys, "version_info", old), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(self.path, run_name="__main__")
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("needs Python 3.9 or later", err.getvalue())

    def test_the_launcher_has_no_syntax_an_old_python_rejects(self):
        with open(self.path, encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.JoinedStr, ast.AnnAssign, ast.NamedExpr,
                                            ast.FunctionDef, ast.AsyncFunctionDef))
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "__future__")
        # The version check comes before the first import of the package.
        body = [type(node) for node in tree.body]
        self.assertLess(body.index(ast.If), body.index(ast.ImportFrom))


if __name__ == "__main__":
    unittest.main()
