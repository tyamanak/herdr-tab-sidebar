# Configuration

English | [Japanese](config.ja.md)

This page belongs to the [README](../README.md) of herdr-tab-sidebar.

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
  are damaged. [Removing it by hand](#removing-it-by-hand) has the repair.
- If a later step of a first `apply` fails, it tries to take back the block,
  the view and the tokens it had written, and reports the failure. If it could
  not take everything back (Herdr stopped answering, say), the error names
  what is left; `status` shows the state, and
  [Removing it by hand](#removing-it-by-hand) has the way to remove the rest.

**The Agents panel.** While applied, the plugin owns Herdr's Agent view (the
panel header shows `tabs`) and writes six display-only tokens named `ts_*` on
agent panes. Nothing else in the session is changed. The plugin does nothing
before `apply` and nothing after `release`.

## When the release does not finish

Step 2 of [Uninstall](../README.md#uninstall) waits for the newest `status`
entry to end with `state: released`.

If the `release` entry failed, its error says why; fix that and release again.
`status` does not say `released` while Herdr has not reloaded `config.toml`
after the block was taken out; releasing again retries the reload.

In rare cases, an `apply` that fails after such a failed reload can make
`status` say `released` while the old layout is still on screen (every row
of the Agents panel shows only a state icon). If that happens, run
`herdr server reload-config` to refresh the configuration Herdr holds in
memory.

## Removing it by hand

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
