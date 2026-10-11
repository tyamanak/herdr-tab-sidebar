"""Apply the plan to a live Herdr, one writer at a time.

Herdr starts one short process per event, so several of them can overlap. Each
one takes a ticket, then waits for a lock. Whoever holds the lock reads a fresh
snapshot and writes until a later snapshot confirms nothing is left to change,
so a burst of events cannot leave a heading on the wrong row. A waiter whose
ticket was issued before that snapshot has nothing left to do and exits.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from typing import Dict, List, Optional

from . import plan as planner
from .api import Herdr, HerdrError

LOCK_TIMEOUT_SECONDS = 30.0
# How long one run keeps following a session that changes under it.
CONVERGE_SECONDS = 8.0
# Passes made back to back before pausing between them.
QUICK_PASSES = 3
PASS_PAUSE_SECONDS = 0.05
# Passes clear() makes to remove tokens that are written back meanwhile.
MAX_PASSES = 5


class SyncError(Exception):
    pass


class State:
    """Files under the plugin's state directory."""

    def __init__(self, directory: str, create: bool = True):
        self.directory = directory
        if create:
            os.makedirs(directory, exist_ok=True)

    def path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    @property
    def enabled(self) -> bool:
        return os.path.exists(self.path("enabled"))

    def set_enabled(self, value: bool) -> None:
        if value:
            with open(self.path("enabled"), "w") as stream:
                stream.write(time.strftime("%Y-%m-%dT%H:%M:%S%z\n"))
        else:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path("enabled"))

    @property
    def reload_pending(self) -> bool:
        """The plugin changed config.toml and the running Herdr has not read it yet."""
        return os.path.exists(self.path("reload-pending"))

    def set_reload_pending(self, value: bool) -> None:
        if value:
            with open(self.path("reload-pending"), "w") as stream:
                stream.write(time.strftime("%Y-%m-%dT%H:%M:%S%z\n"))
        else:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path("reload-pending"))

    def _read_int(self, name: str) -> int:
        try:
            with open(self.path(name)) as stream:
                return int(stream.read().strip() or 0)
        except (FileNotFoundError, ValueError):
            return 0

    def _write_int(self, name: str, value: int) -> None:
        temp = self.path("%s.%d.tmp" % (name, os.getpid()))
        with open(temp, "w") as stream:
            stream.write("%d\n" % value)
        os.replace(temp, self.path(name))

    def take_ticket(self) -> int:
        with locked(self.path("ticket.lock"), LOCK_TIMEOUT_SECONDS):
            ticket = self._read_int("ticket") + 1
            self._write_int("ticket", ticket)
            return ticket

    def last_ticket(self) -> int:
        return self._read_int("ticket")

    def handled(self) -> int:
        return self._read_int("handled")

    def set_handled(self, ticket: int) -> None:
        self._write_int("handled", ticket)

    def record(self, result: dict) -> None:
        temp = self.path("last.json.%d.tmp" % os.getpid())
        with open(temp, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=1)
        os.replace(temp, self.path("last.json"))


@contextlib.contextmanager
def locked(path: str, timeout: float):
    deadline = time.monotonic() + timeout
    with open(path, "a+") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SyncError("timed out waiting for %s" % os.path.basename(path))
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _is_gone(error: HerdrError) -> bool:
    return "not_found" in error.code


def write_patches(herdr: Herdr, source: str, patches: Dict[str, dict]) -> List[str]:
    """Send token patches. Returns the panes that closed in the meantime."""
    # Mark representatives first so a tab is never left without a row.
    order = sorted(patches, key=lambda p: patches[p].get(planner.TOKEN_REP) != "1")
    gone = []
    for pane_id in order:
        try:
            herdr.report_tokens(pane_id, source, patches[pane_id])
        except HerdrError as error:
            if not _is_gone(error):
                raise
            gone.append(pane_id)
    return gone


def converge(herdr: Herdr, state: State, source: str, force: bool) -> dict:
    """Write until a fresh snapshot needs no change. Caller holds the lock.

    The limit is time, not a number of passes: during a burst the session can
    change on many passes in a row, and the events behind those changes take
    their tickets only once their own process is up. Stopping early would
    report a failure for a list that settles a moment later.
    """
    written = 0
    attempt = 0
    deadline = time.monotonic() + CONVERGE_SECONDS
    while True:
        attempt += 1
        ticket = state.last_ticket()
        snapshot = herdr.snapshot()
        plan = planner.build_plan(snapshot)
        patches = planner.diff(plan, force=force and attempt == 1)
        if attempt == 1:
            # Reapplied on every run: the view is lost when the server
            # restarts or the plugin is disabled, and there is no way to read
            # it back.
            herdr.set_view(planner.view_request(source))
        gone = write_patches(herdr, source, patches)
        written += len(patches) - len(gone)
        # Everything up to this ticket happened before the snapshot above.
        state.set_handled(ticket)
        if not patches:
            return {"result": "synced", "passes": attempt, "panes_written": written,
                    "rows": len(plan["rows"])}
        if time.monotonic() >= deadline:
            break
        if attempt >= QUICK_PASSES:
            time.sleep(PASS_PAUSE_SECONDS)
    if state.last_ticket() > ticket:
        # The session is still changing, and each of those changes queued its
        # own run behind the lock; that run continues from here.
        return {"result": "handed_over", "passes": attempt, "panes_written": written}
    raise SyncError(
        "still changing after %d passes in %.0f s; something else keeps rewriting the "
        "session or the ts_ tokens" % (attempt, CONVERGE_SECONDS)
    )


def sync(herdr: Herdr, state: State, source: str, force: bool = False,
         reason: str = "") -> dict:
    if not state.enabled:
        return {"result": "disabled"}
    ticket = state.take_ticket()
    with locked(state.path("sync.lock"), LOCK_TIMEOUT_SECONDS):
        if not state.enabled:
            return {"result": "disabled"}
        if not force and state.handled() >= ticket:
            return {"result": "coalesced"}
        result = converge(herdr, state, source, force)
        result["reason"] = reason
        result["at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state.record(result)
        return result


def clear_tokens(herdr: Herdr, source: str) -> int:
    """Remove every token of the plugin. Returns the number of panes cleared."""
    cleared = 0
    for _ in range(MAX_PASSES):
        snapshot = herdr.snapshot()
        remaining = planner.build_plan(snapshot)["current"]
        patches = {
            pane_id: {name: None for name in have}
            for pane_id, have in remaining.items() if have
        }
        if not patches:
            return cleared
        cleared += len(patches) - len(write_patches(herdr, source, patches))
    raise SyncError("tokens kept reappearing while clearing")


def clear(herdr: Herdr, state: State, source: str) -> dict:
    """Turn the display off: drop the view, then every token."""
    with locked(state.path("sync.lock"), LOCK_TIMEOUT_SECONDS):
        state.set_enabled(False)
        view = herdr.clear_view(source)
        return {"result": "cleared", "panes_cleared": clear_tokens(herdr, source), "view": view}


def describe(snapshot: Optional[dict], state: State) -> dict:
    info = {
        "enabled": state.enabled,
        "reload_pending": state.reload_pending,
        "state_dir": state.directory,
        "ticket": state.last_ticket(),
        "handled": state.handled(),
    }
    try:
        with open(state.path("last.json"), encoding="utf-8") as stream:
            info["last_sync"] = json.load(stream)
    except (FileNotFoundError, ValueError):
        info["last_sync"] = None
    if snapshot is not None:
        plan = planner.build_plan(snapshot)
        info["panes_with_tokens"] = sum(1 for have in plan["current"].values() if have)
        info["panes_needing_change"] = len(planner.diff(plan))
        info["rows_planned"] = len(plan["rows"])
    return info
