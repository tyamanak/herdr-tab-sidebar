# herdr-tab-sidebar

A [Herdr](https://herdr.dev) plugin that turns the Agents panel of the sidebar
into a vertical tab list: one row per tab that has an agent, grouped under a
heading per workspace.

![The Agents panel listing agent tabs grouped by workspace](docs/demo.svg)

The picture is a made-up session drawn by `demo/run.py --svg`; see
[Demo](#demo).

- Workspaces come in the order of the Spaces panel (your own order), tabs in
  the order of the tab bar.
- A tab with several agents is one row. `+1` counts the agents that have no
  row of their own, and `!` after it means one of those is blocked or done.
- Selecting a row focuses that tab's representative pane.
- Tabs without an agent are not listed. Herdr only lists panes that run an
  agent, so a tab that holds only shells has no row.

## Requirements

- Herdr 0.9.1 or later. Developed and tested with Herdr 0.9.3.
- Python 3.9 or later, found as `python3` on the PATH of the Herdr server.
  Only the standard library is used. With an older `python3` every hook and
  action fails with a message that says so.
- macOS or Linux. Everything below was run on macOS. On Linux nothing has
  been tried by hand yet; the unit tests are set up to run there in CI.

## Install

```sh
herdr plugin install tyamanak/herdr-tab-sidebar
herdr plugin action invoke tyamanak.tab-sidebar.apply
```

Installing changes nothing you can see. `apply` adds the row layout to
`config.toml` (see [What it changes](#what-it-changes)), reloads the config and
fills in the rows.

Install it once. A second copy under another plugin id (a fork, or a local
`herdr plugin link` of a clone next to the installed one) would write the same
`ts_*` tokens and the same block in `config.toml`, and the two would undo each
other's work.

### Check

```sh
herdr plugin action invoke tyamanak.tab-sidebar.status
herdr plugin log list --plugin tyamanak.tab-sidebar
```

The last line the `status` action printed is `state: applied`,
`state: released`, or what stands in the way of either. Actions run in the
background, so their output and any error are in the plugin log, not in the
terminal that invoked them.

From a clone of this repository the same check is one command with an exit
code:

```sh
python3 main.py status --expect applied    # or: --expect released
```

It prints `OK: applied (N rows)`, or `NOT applied:` and the reasons.
`python3 main.py preview` prints the rows the current session would produce.
Both only read.

### Other actions

| Action | Effect |
|---|---|
| `tyamanak.tab-sidebar.apply` | add the block to `config.toml`, reload the config, set the view, write all tokens |
| `tyamanak.tab-sidebar.release` | clear the view and all tokens, remove the block, reload the config |
| `tyamanak.tab-sidebar.resync` | write the view and every token again from the current session |
| `tyamanak.tab-sidebar.status` | report the state; changes nothing |

The list follows the session by itself (a workspace renamed; tabs created,
closed, renamed or moved; panes closed or moved; agents detected and their
state changes) and comes back after a server restart. `resync` is for the case
where it looks stale anyway.

To update, install again; Herdr replaces its checkout:

```sh
herdr plugin install tyamanak/herdr-tab-sidebar
```

## What it changes

**`config.toml`.** `apply` appends these 8 lines to the end of Herdr's
`config.toml` and touches nothing else in the file. `release` removes them and
leaves the file byte for byte as it was.

```toml
# >>> herdr-tab-sidebar: managed block, remove with the plugin's release action >>>
[ui.sidebar.agents]
row_gap = 0
rows = [
  [{ token = "$ts_group", bold = true }],
  ["$ts_label", "$ts_extra", { token = "machine", rules = [{ equals = "Local", hide = true }] }, "state_icon"],
]
# <<< herdr-tab-sidebar <<<
```

- The new file is checked with `herdr config check` before it replaces the old
  one, and a copy of the old file is kept under the plugin's state directory
  (`~/.local/state/herdr/plugins/tyamanak.tab-sidebar/backups/`, or under
  `$XDG_STATE_HOME`). Every change adds a copy; none is overwritten.
- If `config.toml` already defines `[ui.sidebar.agents]` in any form, `apply`
  refuses and changes nothing. The two layouts cannot both be in effect:
  remove or comment out yours, then run `apply`. To bring parts of yours back
  (a token of your own in the second row, say), edit the lines inside the
  block. Such edits stay until the next `apply`, which resets the block;
  `release` removes the block whole.
- If `config.toml` is a symlink (a dotfiles repository, for example), the file
  it points to is rewritten and the link stays. If the file cannot be written
  (a read-only store), `apply` fails and changes nothing.
- If `config.toml` changes while `apply` or `release` is working on it (an
  editor saving, another tool), the action writes nothing and says so. Run it
  again.
- The two marker lines must stay as they are: each on a line of its own, one
  of each, the begin line first. If one is missing, doubled or moved, `apply`
  and `release` both refuse and change nothing, and `status` says the markers
  are damaged. [Uninstall](#uninstall) has the repair by hand.
- If a later step of a first `apply` fails, it tries to take back the block,
  the view and the tokens it had written, and reports the failure. If it could
  not take everything back (Herdr stopped answering, say), the error names
  what is left; `status` shows the state, and [Uninstall](#uninstall) has the
  way to remove the rest by hand.

**The Agents panel.** While applied, the plugin owns Herdr's Agent view (the
panel header shows `tabs`) and writes six display-only tokens named `ts_*` on
agent panes. Nothing else in the session is changed. The plugin does nothing
before `apply` and nothing after `release`.

## Limits

- Tabs without an agent have no row (see the top of this page).
- The state icon is at the end of a row, not the start. Herdr indents the
  first line of an entry differently from the following ones, so a leading
  icon could not line up between the first tab of a workspace and the rest.
- While applied, the plugin's list replaces Herdr's own ordering of the Agents
  panel (`agent_panel_sort`). `release` brings it back.
- Herdr has one Agent view. The plugin sets it on every run, so it replaces a
  view set by another plugin, and another plugin that sets the view replaces
  this one. Using it next to such a plugin has not been tried.
- Agents on another machine (Herdr can show several machines in one client)
  keep a row after the local groups, but the row shows only the
  machine name and the state icon: the row layout is one definition for every
  row, and the plugin's tokens exist only on local panes. This is what the
  code and the unit tests say; it has not been looked at on a real remote
  connection. If you work that way most of the time, `release` first.
- The other agents of a tab with several agents cannot be reached with
  next/previous agent while the plugin is applied.
- Herdr runs at most 32 plugin commands at once and drops the rest. If a very
  large burst of changes leaves the list stale, the next change or `resync`
  fixes it.
- Not tried: updating Herdr in place while the session keeps running. A plain
  server restart is covered by the tests (the startup hook restores the list).

## Uninstall

Release first, and uninstall only once the release is confirmed. Actions run
in the background: `invoke` returns before the action has finished, so these
are three separate steps, not one block to paste.

1. Release:

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.release
   ```

2. Ask for the state, wait a moment, and read the answer in the log:

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.status
   ```

   ```sh
   herdr plugin log list --plugin tyamanak.tab-sidebar
   ```

   Go on when the newest `status` entry ends with `state: released`. If the
   `release` entry failed, its error says why; fix that and release again.
   `status` does not say `released` while Herdr has not reloaded `config.toml`
   after the block was taken out; releasing again retries the reload.

   In rare cases, an `apply` that fails after such a failed reload can make
   `status` say `released` while the old layout is still on screen (every row
   of the Agents panel shows only a state icon). If that happens, run
   `herdr server reload-config` to refresh the configuration Herdr holds in
   memory.

3. Uninstall:

   ```sh
   herdr plugin uninstall tyamanak.tab-sidebar
   ```

### Removing it by hand

For the cases where `release` cannot do it: the plugin was uninstalled first,
the markers are damaged, or a failed `apply` could not take everything back.

1. In `config.toml`, delete the plugin's lines: from the
   `# >>> herdr-tab-sidebar` marker to the `# <<< herdr-tab-sidebar <<<`
   marker, both included. If a marker is missing or doubled, delete every
   marker line and the `[ui.sidebar.agents]` table shown under
   [What it changes](#what-it-changes), and leave your own lines.
2. Run `herdr server reload-config`. Until then every row of the Agents panel
   may show only a state icon.
3. If the plugin is still installed, run `release` once more so that it drops
   the view and its flag, then check with `status`.

Any `ts_*` tokens still on the panes are display-only, and nothing draws them
once the block is gone.

## How it works

`main.py` is a short program that Herdr starts from the manifest's startup
hook, event hooks and actions. Each run reads `session.snapshot`, computes the
tokens every pane should carry (`tab_sidebar/plan.py`) and writes only the
differences with `pane.report_metadata`. Nothing stays running.

| Token | On | Meaning |
|---|---|---|
| `ts_m` | every agent pane of a listed tab | handled by this plugin |
| `ts_rep` | the tab's representative pane | this pane is the tab's row |
| `ts_pos` | representative | position in the tab bar, zero padded |
| `ts_group` | first representative of a workspace | heading text |
| `ts_label` | representative | tab name |
| `ts_extra` | representative | `+N` other agents, `!` if one needs attention |

`agent.view.set` (source `plugin:tyamanak.tab-sidebar`, label `tabs`) keeps the
representatives plus any pane the plugin has not marked, and sorts by `ts_m`,
Herdr's own `workspace_order`, then `ts_pos`. Because the workspace order is
Herdr's, reordering workspaces needs no hook and no token change.

Runs are serialised with a lock under the plugin's state directory. A run that
waited while an earlier one already covered its event exits without doing
anything, and the lock holder repeats until a fresh snapshot needs no change
(for up to 8 seconds; after that it fails unless a later run is queued).

## Tests

```sh
python3 -m unittest discover -s tests -t .
python3 tests/isolated/run.py
```

The first command needs only Python. The second needs `herdr` on the PATH (or
`--herdr PATH`): it starts its own headless Herdr server under a temporary
directory (config, state, plugin registry and socket), links this checkout
there and exercises the real hooks, actions and rendering. It builds the
environment of that server from scratch, refuses to continue unless the server
it reaches reports a socket inside the temporary directory, and removes the
directory at the end. Your session and `~/.config/herdr` are not touched.

## Demo

```sh
python3 demo/run.py              # open the demo session in this terminal
python3 demo/run.py --text       # print the screen as text
python3 demo/run.py --svg FILE   # write the screen as an SVG image
```

The demo uses the same kind of throwaway server as the tests and fills it with
made-up workspaces and tabs. No agent is started: the panes print prepared
text, and their states are reported with `herdr pane report-agent`. The first
form tells you how to leave before it opens (`ctrl+g`, then `q`), and removes
the server and its directory when you do, or when the terminal is closed. If
you start it from inside Herdr and your own prefix key is `ctrl+g`, pass
another one with `--prefix`.

## License

MIT. See [LICENSE](LICENSE).
