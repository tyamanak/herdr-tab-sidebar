import os
import tempfile
import unittest
from unittest import mock

from tab_sidebar import config_edit
from tab_sidebar.config_edit import BEGIN, BLOCK, END, ConfigError

from tests.helpers import fake_command

USER_CONFIG = """onboarding = false
[ui]
agent_panel_sort = "priority"

confirm_close = false
[keys]
prefix = "ctrl+a"

[[keys.command]]  # comment
key = "prefix+g"
type = "shell"

[ui.toast]
delivery = "off"
"""


class TextTest(unittest.TestCase):
    def test_block_is_appended_and_nothing_else_changes(self):
        updated = config_edit.with_block(USER_CONFIG)
        self.assertTrue(updated.startswith(USER_CONFIG))
        self.assertEqual(updated[len(USER_CONFIG):], BLOCK)
        self.assertIn('agent_panel_sort = "priority"', updated)

    def test_remove_restores_the_file_byte_for_byte(self):
        self.assertEqual(config_edit.without_block(config_edit.with_block(USER_CONFIG)), USER_CONFIG)

    def test_apply_twice_keeps_one_block(self):
        once = config_edit.with_block(USER_CONFIG)
        self.assertEqual(config_edit.with_block(once), once)
        self.assertEqual(once.count(BEGIN), 1)

    def test_an_edited_block_is_reset_on_apply_and_dropped_on_release(self):
        edited = config_edit.with_block(USER_CONFIG).replace("row_gap = 0", "row_gap = 1")
        self.assertEqual(config_edit.with_block(edited), config_edit.with_block(USER_CONFIG))
        self.assertEqual(config_edit.without_block(edited), USER_CONFIG)

    def test_text_added_after_the_block_survives_release(self):
        later = config_edit.with_block(USER_CONFIG) + "[theme]\nname = \"x\"\n"
        self.assertEqual(config_edit.without_block(later), USER_CONFIG + "[theme]\nname = \"x\"\n")

    def test_release_without_a_block_is_a_no_op(self):
        self.assertEqual(config_edit.without_block(USER_CONFIG), USER_CONFIG)

    def test_existing_agents_layout_is_refused(self):
        for existing in (
            "[ui.sidebar.agents]\nrows = [[\"agent\"]]\n",
            "[ ui.sidebar.agents ]\nrow_gap = 1\n",
            "[ui.sidebar.agents.rows_by_agent]\nclaude = [[\"agent\"]]\n",
            "[ui.sidebar]\nagents = { row_gap = 1 }\n",
            "[ui]\nsidebar.agents.row_gap = 1\n",
            "[ui]\nsidebar = { agents = { row_gap = 1 } }\n",
            "ui.sidebar.agents.row_gap = 1\n",
        ):
            with self.assertRaises(ConfigError, msg=existing):
                config_edit.with_block(existing)

    def test_other_sidebar_settings_are_not_a_conflict(self):
        for existing in (
            "[ui.sidebar.spaces]\nrows = [[\"workspace\"]]\n",
            "# [ui.sidebar.agents]\n",
            "[keys]\nagents = \"x\"\n",
        ):
            self.assertIn(BEGIN, config_edit.with_block(existing))

    def test_broken_markers_are_refused(self):
        for broken in (BEGIN + "\n", END + "\n", BLOCK + BLOCK):
            with self.assertRaises(ConfigError):
                config_edit.with_block(USER_CONFIG + broken)
            with self.assertRaises(ConfigError):
                config_edit.without_block(USER_CONFIG + broken)

    def test_layout_only_defines_the_agents_rows(self):
        body = BLOCK.replace(BEGIN, "").replace(END, "")
        headers = [line for line in body.splitlines() if line.startswith("[")]
        self.assertEqual(headers, ["[ui.sidebar.agents]"])


class FileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "config.toml")
        self.state = os.path.join(self.dir.name, "state")
        os.makedirs(self.state)

    def write(self, text):
        with open(self.path, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)

    def read(self):
        with open(self.path, encoding="utf-8", newline="") as stream:
            return stream.read()

    def test_install_then_remove_round_trips(self):
        for original in (USER_CONFIG, USER_CONFIG.rstrip("\n"), "", "a = 1\r\n"):
            self.write(original)
            self.assertTrue(config_edit.install(self.path, None, self.state))
            self.assertFalse(config_edit.install(self.path, None, self.state))
            self.assertIn(BLOCK, self.read())
            self.assertTrue(config_edit.remove(self.path, self.state))
            self.assertFalse(config_edit.remove(self.path, self.state))
            self.assertEqual(self.read(), original)

    def test_a_backup_is_kept_and_the_mode_is_preserved(self):
        self.write(USER_CONFIG)
        os.chmod(self.path, 0o600)
        config_edit.install(self.path, None, self.state)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        backups = os.listdir(os.path.join(self.state, "backups"))
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self.state, "backups", backups[0]), encoding="utf-8") as stream:
            self.assertEqual(stream.read(), USER_CONFIG)

    def test_a_symlinked_config_stays_a_symlink(self):
        real = os.path.join(self.dir.name, "real.toml")
        with open(real, "w") as stream:
            stream.write(USER_CONFIG)
        os.symlink(real, self.path)
        config_edit.install(self.path, None, self.state)
        self.assertTrue(os.path.islink(self.path))
        with open(real) as stream:
            self.assertIn(BEGIN, stream.read())

    def test_a_rejected_config_is_not_written(self):
        self.write(USER_CONFIG)
        with self.assertRaises(ConfigError):
            config_edit.install(self.path, fake_command(self.dir.name, 1), self.state)
        self.assertEqual(self.read(), USER_CONFIG)
        self.assertEqual(os.listdir(self.dir.name).count("config.toml"), 1)
        self.assertFalse([n for n in os.listdir(self.dir.name) if n.startswith(".config.toml")])

    def test_conflict_leaves_the_file_alone(self):
        conflicting = USER_CONFIG + "[ui.sidebar.agents]\nrow_gap = 1\n"
        self.write(conflicting)
        with self.assertRaises(ConfigError):
            config_edit.install(self.path, None, self.state)
        self.assertEqual(self.read(), conflicting)


# Files whose markers the plugin must refuse: each could make it take lines
# that are not its own. SOUND stands for a setting the user added.
SOUND = "[ui.sound]\nenabled = false\n"
DAMAGED = {
    "end marker lost, a second block after the user's lines":
        USER_CONFIG + BEGIN + "\n[ui.sidebar.agents]\nrow_gap = 0\n" + SOUND + BLOCK,
    "nested begin marker":
        USER_CONFIG + BEGIN + "\n" + SOUND + BEGIN + "\n" + END + "\n",
    "end marker before the begin marker":
        USER_CONFIG + END + "\n" + SOUND + BEGIN + "\n",
    "begin marker in the middle of a line":
        USER_CONFIG + "note = 1  " + BEGIN + "\n" + SOUND + END + "\n",
    "end marker in the middle of a line":
        USER_CONFIG + BEGIN + "\n" + SOUND + "x = 1 " + END + "\n",
    "a whole block, and a marker quoted inside another line":
        USER_CONFIG + 'note = "' + END + '"\n' + SOUND + BLOCK,
    "indented marker":
        USER_CONFIG + "  " + BEGIN + "\n" + SOUND + END + "\n",
    "begin marker only": USER_CONFIG + BEGIN + "\n" + SOUND,
    "end marker only": USER_CONFIG + SOUND + END + "\n",
    "two whole blocks": USER_CONFIG + BLOCK + SOUND + BLOCK,
}


class DamagedMarkersTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "config.toml")
        self.state = os.path.join(self.dir.name, "state")
        os.makedirs(self.state)

    def test_text_with_damaged_markers_is_refused_with_a_way_out(self):
        for name, text in DAMAGED.items():
            for change in (config_edit.with_block, config_edit.without_block):
                with self.assertRaises(ConfigError, msg=name) as caught:
                    change(text)
                self.assertIn("markers in config.toml are damaged", str(caught.exception), name)
                self.assertIn('"Uninstall"', str(caught.exception), name)

    def test_neither_install_nor_remove_touches_a_damaged_file(self):
        for name, text in DAMAGED.items():
            with open(self.path, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
            for change in (lambda: config_edit.install(self.path, None, self.state),
                           lambda: config_edit.remove(self.path, self.state)):
                with self.assertRaises(ConfigError, msg=name):
                    change()
                with open(self.path, encoding="utf-8", newline="") as stream:
                    self.assertEqual(stream.read(), text, name)
            self.assertEqual(os.listdir(self.state), [], name)
            self.assertEqual(os.listdir(self.dir.name).count("config.toml"), 1)
            self.assertFalse([n for n in os.listdir(self.dir.name) if n.startswith(".config")])

    def test_a_whole_block_is_still_taken_whatever_the_line_endings(self):
        crlf = "a = 1\r\n" + BLOCK.replace("\n", "\r\n") + "b = 2\r\n"
        self.assertEqual(config_edit.without_block(crlf), "a = 1\r\nb = 2\r\n")
        self.assertEqual(config_edit.without_block(USER_CONFIG + BLOCK.rstrip("\n")), USER_CONFIG)


class ChangedMeanwhileTest(unittest.TestCase):
    """The config is edited by someone else between the read and the write."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "config.toml")
        self.state = os.path.join(self.dir.name, "state")
        os.makedirs(self.state)
        self.herdr = fake_command(self.dir.name, 0)

    def write(self, text, path=None):
        with open(path or self.path, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)

    def read(self, path=None):
        with open(path or self.path, encoding="utf-8", newline="") as stream:
            return stream.read()

    def leftovers(self):
        return [n for n in os.listdir(self.dir.name) if n.startswith(".config")]

    def test_an_edit_made_during_the_check_is_not_overwritten_by_install(self):
        self.write(USER_CONFIG)

        def edit_during_check(_herdr, _candidate):
            self.write(USER_CONFIG + SOUND)
            return True, "ok"

        with mock.patch.object(config_edit, "check", side_effect=edit_during_check):
            with self.assertRaises(ConfigError) as caught:
                config_edit.install(self.path, self.herdr, self.state)
        self.assertIn("changed while the plugin was working on it", str(caught.exception))
        self.assertIn("Run this again", str(caught.exception))
        self.assertEqual(self.read(), USER_CONFIG + SOUND)
        self.assertEqual(self.leftovers(), [])
        # The backup is written before the last look, so one copy was made.
        self.assertEqual(os.listdir(self.state), ["backups"])
        # Running it again, as the message says, works on the new content.
        self.assertTrue(config_edit.install(self.path, self.herdr, self.state))
        self.assertEqual(self.read(), USER_CONFIG + SOUND + BLOCK)

    def test_an_edit_made_during_remove_is_not_overwritten(self):
        self.write(USER_CONFIG + BLOCK)
        real = tempfile.mkstemp

        def edit_then_make(*args, **kwargs):
            self.write(USER_CONFIG + BLOCK + SOUND)
            return real(*args, **kwargs)

        with mock.patch.object(config_edit.tempfile, "mkstemp", side_effect=edit_then_make):
            with self.assertRaises(ConfigError):
                config_edit.remove(self.path, self.state)
        self.assertEqual(self.read(), USER_CONFIG + BLOCK + SOUND)
        self.assertEqual(self.leftovers(), [])
        self.assertTrue(config_edit.remove(self.path, self.state))
        self.assertEqual(self.read(), USER_CONFIG + SOUND)

    def test_an_edit_made_while_the_backup_is_written_is_not_overwritten(self):
        # The last look comes after the backup, right before the replace.
        for change in ("install", "remove"):
            start = USER_CONFIG if change == "install" else USER_CONFIG + BLOCK
            self.write(start)
            real = config_edit._backup

            def backup_then_edit(target, directory):
                name = real(target, directory)
                self.write(start + SOUND)
                return name

            with mock.patch.object(config_edit, "_backup", side_effect=backup_then_edit):
                with self.assertRaises(ConfigError, msg=change) as caught:
                    if change == "install":
                        config_edit.install(self.path, self.herdr, self.state)
                    else:
                        config_edit.remove(self.path, self.state)
            self.assertIn("changed while the plugin was working on it", str(caught.exception))
            self.assertEqual(self.read(), start + SOUND, change)
            self.assertEqual(self.leftovers(), [], change)

    def test_a_file_that_appears_or_disappears_meanwhile_is_noticed(self):
        def appear(_herdr, _candidate):
            self.write(SOUND)
            return True, "ok"

        with mock.patch.object(config_edit, "check", side_effect=appear):
            with self.assertRaises(ConfigError):
                config_edit.install(self.path, self.herdr, self.state)
        self.assertEqual(self.read(), SOUND)

        self.write(USER_CONFIG)

        def vanish(_herdr, _candidate):
            os.unlink(self.path)
            return True, "ok"

        with mock.patch.object(config_edit, "check", side_effect=vanish):
            with self.assertRaises(ConfigError):
                config_edit.install(self.path, self.herdr, self.state)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.leftovers(), [])

    def test_a_symlink_pointed_elsewhere_meanwhile_is_noticed(self):
        first, second = (os.path.join(self.dir.name, name) for name in ("one.toml", "two.toml"))
        self.write(USER_CONFIG, first)
        self.write(USER_CONFIG, second)  # the same text: only the target differs
        os.symlink(first, self.path)

        def repoint(_herdr, _candidate):
            os.unlink(self.path)
            os.symlink(second, self.path)
            return True, "ok"

        with mock.patch.object(config_edit, "check", side_effect=repoint):
            with self.assertRaises(ConfigError):
                config_edit.install(self.path, self.herdr, self.state)
        self.assertEqual((self.read(first), self.read(second)), (USER_CONFIG, USER_CONFIG))
        self.assertEqual(os.path.realpath(self.path), os.path.realpath(second))
        self.assertEqual(self.leftovers(), [])

    def test_backups_made_in_the_same_second_do_not_replace_each_other(self):
        self.write(USER_CONFIG)
        with mock.patch.object(config_edit.time, "strftime", return_value="20260102-030405"):
            config_edit.install(self.path, None, self.state)
            config_edit.remove(self.path, self.state)
            config_edit.install(self.path, None, self.state)
        backups = os.path.join(self.state, "backups")
        self.assertEqual(sorted(os.listdir(backups)), [
            "config.toml.20260102-030405", "config.toml.20260102-030405.1",
            "config.toml.20260102-030405.2"])
        texts = [self.read(os.path.join(backups, name)) for name in sorted(os.listdir(backups))]
        self.assertEqual(texts, [USER_CONFIG, USER_CONFIG + BLOCK, USER_CONFIG])


if __name__ == "__main__":
    unittest.main()
