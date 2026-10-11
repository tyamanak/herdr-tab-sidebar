"""The commands behind the manifest's hooks and actions. See README.md."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys

from . import config_edit, plan as planner, sync as syncer
from .api import Herdr, HerdrError

MANIFEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "herdr-plugin.toml")
_ID_LINE = re.compile(r'^id\s*=\s*"([^"]+)"\s*(#.*)?$')
# Long enough for the apply in front to finish: a config check, a reload and
# the sync each have their own, shorter limit.
ACTION_LOCK_SECONDS = 120.0


def manifest_id(path: str = MANIFEST) -> str:
    """The plugin id, which herdr-plugin.toml alone defines.

    Python 3.9 has no TOML parser; the id is the top-level ``id`` line.
    """
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("["):
                break
            found = _ID_LINE.match(line.strip())
            if found:
                return found.group(1)
    raise syncer.SyncError("no plugin id in %s" % path)


def plugin_id() -> str:
    # Herdr sets the variable for hooks and actions; a shell does not.
    return os.environ.get("HERDR_PLUGIN_ID") or manifest_id()


def source() -> str:
    return "plugin:%s" % plugin_id()


def state_dir() -> str:
    directory = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if not directory:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state"
        )
        directory = os.path.join(base, "herdr", "plugins", plugin_id())
    return directory


def state() -> syncer.State:
    return syncer.State(state_dir())


def herdr_bin() -> str:
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def reload_config() -> str:
    try:
        done = subprocess.run(
            [herdr_bin(), "server", "reload-config"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as err:
        raise syncer.SyncError("could not run reload-config: %s" % err)
    output = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0:
        raise syncer.SyncError("reload-config failed: %s" % output)
    return output


def reload_and_note(current) -> str:
    """Reload, and on success drop the note that a reload is still owed."""
    output = reload_config()
    # A note that cannot be removed only makes status ask for one more release.
    with contextlib.suppress(OSError):
        current.set_reload_pending(False)
    return output


def cmd_event(args) -> dict:
    event = os.environ.get("HERDR_PLUGIN_EVENT", "")
    # The server forgets tokens and the view when it restarts or hands over.
    force = event == "startup"
    return syncer.sync(Herdr(), state(), source(), force=force, reason=event or "event")


def cmd_resync(args) -> dict:
    return syncer.sync(Herdr(), state(), source(), force=True, reason="resync")


class NotUndone(Exception):
    """A first apply failed and could not take everything back."""

    def __init__(self, error: Exception, left: list):
        super().__init__(
            "%s\ntab-sidebar: could not take everything back; still there: %s. Run the status "
            "action to see what is left, and see \"Uninstall\" in the README to remove it by hand"
            % (error, "; ".join(left))
        )


def action_lock(current):
    """Held for a whole apply or release, undo included, so two never interleave.

    Not the lock sync() and clear() take: they take theirs inside this one,
    and event hooks keep running under theirs alone.
    """
    return syncer.locked(current.path("action.lock"), ACTION_LOCK_SECONDS)


def undo_apply(herdr, current, path) -> list:
    """Take back what a failed first apply left behind.

    Never raises. Returns what it could not take back, as text.
    """
    left = []
    try:
        # Drops the enabled flag, the view and every token already written.
        syncer.clear(herdr, current, source())
    except (HerdrError, syncer.SyncError, OSError):
        # Whatever stopped it, try each part on its own.
        try:
            current.set_enabled(False)
        except OSError:
            left.append("the enabled flag in the plugin's state directory")
        try:
            herdr.clear_view(source())
        except HerdrError:
            left.append("the Agent view")
        try:
            syncer.clear_tokens(herdr, source())
        except (HerdrError, syncer.SyncError):
            left.append("ts_ tokens on agent panes")
    # Noted before the block goes, so that a reload that fails below is still
    # owed afterwards: status will not say "released", and release retries it.
    # If the note cannot be written (a full disk), the undo goes on without it.
    with contextlib.suppress(OSError):
        current.set_reload_pending(True)
    try:
        removed = config_edit.remove(path, current.directory)
    except (config_edit.ConfigError, OSError):
        left.append("the managed block in config.toml")
        removed = False
    if removed:
        try:
            reload_and_note(current)
        except syncer.SyncError:
            left.append("the row layout in the running server, until config.toml is reloaded "
                        "(run the release action to try again)")
    else:
        # The file is as the server loaded it; nothing is owed.
        with contextlib.suppress(OSError):
            current.set_reload_pending(False)
    return left


def cmd_apply(args) -> dict:
    current = state()
    with action_lock(current):
        herdr = Herdr()
        path = config_edit.config_path()
        # Only an apply that adds the block itself takes everything back when
        # it fails. A failed repeat on an applied session leaves it applied.
        first = not config_edit.has_block(path)
        try:
            changed = config_edit.install(path, herdr_bin(), current.directory)
            owed = changed or current.reload_pending
            reloaded = reload_and_note(current) if owed else "unchanged"
            current.set_enabled(True)
            result = syncer.sync(herdr, current, source(), force=True, reason="apply")
        except (HerdrError, syncer.SyncError, OSError) as error:
            # Do not leave the row layout behind without its tokens: every
            # row would show nothing but a state icon. OSError is a state
            # file that could not be written, a full disk for example.
            if first:
                left = undo_apply(herdr, current, path)
                if left:
                    raise NotUndone(error, left) from error
            raise
        result.update({"config_changed": changed, "reload": reloaded})
        return result


def cmd_release(args) -> dict:
    current = state()
    with action_lock(current):
        herdr = Herdr()
        path = config_edit.config_path()
        # The config goes first. If its markers are damaged, or the file
        # changes under us, release stops here with the session still fully
        # applied, rather than with the row layout left behind without tokens.
        if config_edit.has_block(path):
            # Noted before the block goes: if the reload at the end fails, the
            # running server still draws the row layout, and only this note
            # tells status and the next release that a reload is owed. Without
            # the note that would go unseen, so a note that cannot be written
            # stops the release here, with nothing changed.
            current.set_reload_pending(True)
        try:
            changed = config_edit.remove(path, current.directory)
        except (config_edit.ConfigError, OSError):
            # Nothing was written; the file is as the server loaded it.
            with contextlib.suppress(OSError):
                current.set_reload_pending(False)
            raise
        try:
            result = syncer.clear(herdr, current, source())
        except (HerdrError, syncer.SyncError, OSError):
            with contextlib.suppress(syncer.SyncError):
                reload_and_note(current)
            raise
        # Always, not only when this run changed the file: an earlier release
        # may have removed the block and then failed to reload.
        result.update({"config_changed": changed, "reload": reload_and_note(current)})
        return result


def read_snapshot(path=None) -> dict:
    """A session snapshot from a file, the socket, or the read-only CLI."""
    if path:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    elif os.environ.get("HERDR_SOCKET_PATH"):
        return Herdr().snapshot()
    else:
        try:
            done = subprocess.run([herdr_bin(), "api", "snapshot"], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=30)
        except (OSError, subprocess.SubprocessError) as err:
            raise syncer.SyncError("could not run herdr api snapshot: %s" % err)
        if done.returncode != 0:
            raise syncer.SyncError("herdr api snapshot failed: %s" % done.stderr.decode().strip())
        data = json.loads(done.stdout.decode("utf-8"))
    result = data.get("result", data)
    return result.get("snapshot", result)


def cmd_status(args) -> int:
    """Read-only. With --expect, say whether apply or release really took effect."""
    directory = state_dir()
    info = syncer.describe(read_snapshot(), syncer.State(directory, create=False))
    path = config_edit.config_path()
    try:
        info["config_block"] = config_edit.has_block(path)
        damaged = None
    except config_edit.ConfigError as error:
        # Neither applied nor released, and neither action will touch it.
        info["config_block"] = None
        damaged = str(error).replace("; nothing was changed", "")
    info.update({"config_path": path, "python": sys.version.split()[0]})
    print(json.dumps(info, ensure_ascii=False))
    if damaged:
        print("%s: %s" % ("NOT %s" % args.expect if args.expect else "state: damaged", damaged))
        return 1 if args.expect else 0
    against = {
        "applied": [text for bad, text in (
            (not info["enabled"], "the plugin is not enabled (apply has not completed)"),
            (not info["config_block"], "config.toml has no managed block"),
            (info["panes_needing_change"] > 0,
             "%d pane(s) do not carry the right tokens" % info["panes_needing_change"]),
        ) if bad],
        "released": [text for bad, text in (
            (info["enabled"], "the plugin is still enabled"),
            (info["config_block"], "config.toml still has the managed block"),
            (info["panes_with_tokens"] > 0,
             "%d pane(s) still carry ts_ tokens" % info["panes_with_tokens"]),
            (info["reload_pending"],
             "the running Herdr has not reloaded config.toml since the plugin changed it; "
             "run the release action again, or `herdr server reload-config` if that keeps failing"),
        ) if bad],
    }
    if not args.expect:
        # The status action has no argument: name the state that holds.
        holds = [name for name, problems in against.items() if not problems]
        print("state: %s" % (holds[0] if holds else "neither applied (%s) nor released (%s)" % (
            "; ".join(against["applied"]), "; ".join(against["released"]))))
        return 0
    problems = against[args.expect]
    if problems:
        print("NOT %s: %s" % (args.expect, "; ".join(problems)))
        return 1
    print("OK: %s (%d rows)" % (args.expect, info["rows_planned"]))
    return 0


def cmd_preview(args) -> None:
    """Read-only: print the rows a snapshot would produce. Writes nothing."""
    print(planner.render_preview(planner.build_plan(read_snapshot(args.snapshot))))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tab-sidebar")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("event", cmd_event), ("resync", cmd_resync), ("apply", cmd_apply),
                          ("release", cmd_release)):
        commands.add_parser(name).set_defaults(handler=handler)
    status = commands.add_parser("status")
    status.add_argument("--expect", choices=("applied", "released"))
    status.set_defaults(handler=cmd_status)
    preview = commands.add_parser("preview")
    preview.add_argument("--snapshot", help="file holding `herdr api snapshot` output")
    preview.set_defaults(handler=cmd_preview)
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (HerdrError, syncer.SyncError, config_edit.ConfigError, NotUndone, OSError) as error:
        # OSError: a state or config file that could not be read or written.
        print("tab-sidebar: %s" % error, file=sys.stderr)
        return 1
    if isinstance(result, int):
        return result
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0
