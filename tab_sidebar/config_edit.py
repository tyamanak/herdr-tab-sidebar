"""Add and remove the plugin's Agents row layout in Herdr's config.toml.

The plugin owns one marked block appended to the end of the file and never
touches a line outside it. Removing the block restores the file byte for byte.
"""
from __future__ import annotations

import itertools
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional, Tuple

BEGIN = "# >>> herdr-tab-sidebar: managed block, remove with the plugin's release action >>>"
END = "# <<< herdr-tab-sidebar <<<"

# Label Herdr gives this machine when the client shows several machines.
LOCAL_MACHINE_LABEL = "Local"

LAYOUT = """[ui.sidebar.agents]
row_gap = 0
rows = [
  [{ token = "$ts_group", bold = true }],
  ["$ts_label", "$ts_extra", { token = "machine", rules = [{ equals = "%s", hide = true }] }, "state_icon"],
]
""" % LOCAL_MACHINE_LABEL

BLOCK = "%s\n%s%s\n" % (BEGIN, LAYOUT, END)


class ConfigError(Exception):
    pass


def config_path() -> str:
    explicit = os.environ.get("HERDR_CONFIG_PATH")
    if explicit:
        return explicit
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "herdr", "config.toml")


def _damaged(reason: str) -> ConfigError:
    return ConfigError(
        "the plugin's markers in config.toml are damaged (%s); nothing was changed. "
        "Repair them by hand as the README describes under \"Uninstall\", then run this again"
        % reason
    )


def split_block(text: str) -> Tuple[str, Optional[str], str]:
    """(before, block or None, after). The block includes its marker lines.

    A marker counts only as a whole line. The file holds either no marker at
    all or one begin line followed by one end line; anything else could make
    the plugin take lines that are not its own, so it is refused.
    """
    lines = text.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == END]
    if text.count(BEGIN) != len(begins) or text.count(END) != len(ends):
        raise _damaged("a marker shares its line with other text")
    if not begins and not ends:
        return text, None, ""
    if len(begins) > 1 or len(ends) > 1:
        raise _damaged("%d begin and %d end markers" % (len(begins), len(ends)))
    if not ends:
        raise _damaged("a begin marker without its end marker")
    if not begins:
        raise _damaged("an end marker without its begin marker")
    if ends[0] < begins[0]:
        raise _damaged("the end marker comes before the begin marker")
    start, stop = begins[0], ends[0] + 1
    return "".join(lines[:start]), "".join(lines[start:stop]), "".join(lines[stop:])


_HEADER = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.\-\s]+?)\s*\]\]?\s*(#.*)?$")


def find_conflict(text: str) -> Optional[str]:
    """A line outside the block that already defines the Agents row layout."""
    table = ""
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        header = _HEADER.match(line)
        if header:
            table = re.sub(r"[\s\"']", "", header.group(1))
            key = ""
        else:
            key = re.sub(r"[\s\"']", "", stripped.split("=", 1)[0])
        path = ".".join(part for part in (table, key) if part)
        if path == "ui.sidebar.agents" or path.startswith("ui.sidebar.agents."):
            return "line %d: %s" % (number, stripped)
        # An inline table such as `sidebar = { agents = ... }` or
        # `ui = { sidebar = ... }` could hold the layout as well.
        if "=" in stripped and not header and path in ("ui", "ui.sidebar"):
            return "line %d: %s" % (number, stripped)
    return None


def with_block(text: str) -> str:
    before, block, after = split_block(text)
    if block is not None:
        return before + BLOCK + after
    conflict = find_conflict(text)
    if conflict:
        raise ConfigError(
            "config.toml already defines the Agents row layout (%s); "
            "remove it or merge by hand, then apply again" % conflict
        )
    separator = "" if text == "" or text.endswith("\n") else "\n"
    return text + separator + BLOCK


def without_block(text: str, added_newline: bool = False) -> str:
    before, block, after = split_block(text)
    if block is None:
        return text
    if added_newline and after == "" and before.endswith("\n"):
        before = before[:-1]
    return before + after


def check(herdr_bin: str, path: str) -> Tuple[bool, str]:
    env = dict(os.environ, HERDR_CONFIG_PATH=path)
    try:
        done = subprocess.run(
            [herdr_bin, "config", "check"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, done.stdout.decode("utf-8", "replace").strip()


def _backup(target: str, backup_dir: str) -> str:
    """Copy ``target`` under a name no earlier backup has. Returns the name."""
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for number in itertools.count():
        name = "config.toml.%s%s" % (stamp, ".%d" % number if number else "")
        try:
            handle = os.open(os.path.join(backup_dir, name),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(handle, "wb") as copy, open(target, "rb") as stream:
            shutil.copyfileobj(stream, copy)
        shutil.copystat(target, os.path.join(backup_dir, name))
        return name


def _write(path: str, read: str, text: str, herdr_bin: Optional[str],
           backup_dir: Optional[str]) -> None:
    """Replace the config, which held ``read`` when it was read, with ``text``.

    Checking the new file takes a moment. If the config changed in that time
    (an editor, another tool, a symlink pointed elsewhere), writing ``text``
    would undo that change, so nothing is written.
    """
    target = os.path.realpath(path)
    directory = os.path.dirname(target)
    handle, temp = tempfile.mkstemp(prefix=".config.toml.tab-sidebar-", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        if herdr_bin:
            ok, output = check(herdr_bin, temp)
            if not ok:
                raise ConfigError("herdr config check rejected the new config:\n%s" % output)
        if os.path.exists(target):
            shutil.copymode(target, temp)
            if backup_dir:
                _backup(target, backup_dir)
        # The last thing before the replace, so that as little as possible can
        # happen in between. A backup made just above may then be one too many.
        if os.path.realpath(path) != target or _read(target) != read:
            raise ConfigError(
                "config.toml changed while the plugin was working on it; "
                "nothing was written. Run this again"
            )
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", newline="") as stream:
            return stream.read()
    except FileNotFoundError:
        return ""


def has_block(path: str) -> bool:
    return split_block(_read(path))[1] is not None


def install(path: str, herdr_bin: Optional[str], state_dir: str) -> bool:
    """Add the block. Returns False when the file already holds it."""
    text = _read(path)
    updated = with_block(text)
    if updated == text:
        return False
    os.makedirs(os.path.dirname(os.path.realpath(path)), exist_ok=True)
    _write(path, text, updated, herdr_bin, os.path.join(state_dir, "backups"))
    # Remembered so that remove() can give back a file that had no final
    # newline. Written after the config: a failed write must leave no trace.
    marker = os.path.join(state_dir, "added-newline")
    if split_block(text)[1] is None:
        if text != "" and not text.endswith("\n"):
            open(marker, "w").close()
        elif os.path.exists(marker):
            os.unlink(marker)
    return True


def remove(path: str, state_dir: str) -> bool:
    """Remove the block. Returns False when the file does not hold it."""
    text = _read(path)
    marker = os.path.join(state_dir, "added-newline")
    updated = without_block(text, added_newline=os.path.exists(marker))
    if updated == text:
        return False
    # Not validated: giving the file back must work even if the rest of it
    # has since become invalid.
    _write(path, text, updated, None, os.path.join(state_dir, "backups"))
    if os.path.exists(marker):
        os.unlink(marker)
    return True
