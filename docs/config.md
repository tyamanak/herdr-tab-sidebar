# Configuration

English | [Japanese](config.ja.md)

This page is part of the [README](../README.md) for herdr-tab-sidebar.

## What it changes

**`config.toml`.** `apply` appends these 8 lines to the end of Herdr's
`config.toml` and touches nothing else. `release` removes them, leaving the
file byte for byte as it was.

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

- The new file is checked with `herdr config check` before replacing the old
  one. A copy of the old file is saved in the plugin's state directory
  (`~/.local/state/herdr/plugins/tyamanak.tab-sidebar/backups/`, or under
  `$XDG_STATE_HOME`). Every change adds a copy; none is overwritten.
- If `config.toml` already defines `[ui.sidebar.agents]` in any form, `apply`
  refuses and changes nothing. Remove or comment out yours, then run `apply`.
  The two layouts cannot both be active. To restore parts of your layout
  (such as a custom token in the second row), edit the lines inside the
  block. These edits remain until the next `apply`, which resets the block.
  `release` removes the entire block.
- If `config.toml` is a symlink (such as a dotfiles repository), the target
  file is updated and the link remains intact. If the file cannot be written
  (such as in a read-only store), `apply` fails without making changes.
- If `config.toml` changes while `apply` or `release` is running (such as from
  an editor save or another tool), the action writes nothing and says so.
  Run it again.
- Leave the two marker lines as they are: each on its own line, exactly
  one of each, with the opening line first. If either is missing, duplicated,
  or moved, both `apply` and `release` refuse and change nothing, and
  `status` reports damaged markers. See
  [Removing it by hand](#removing-it-by-hand) for the fix.
- If a later step of an initial `apply` fails, it attempts to roll back the
  block, view, and tokens it wrote, then reports the failure. If it cannot
  roll everything back (for example, if Herdr stops responding), the error
  lists what remains. Check the state with `status`, and remove the rest as
  described in [Removing it by hand](#removing-it-by-hand).

**The Agents panel.** While applied, the plugin manages Herdr's Agent view
(the panel header shows `tabs`) and sets six display-only tokens named `ts_*`
on agent panes. Nothing else in the session is changed. The plugin does
nothing before `apply` and nothing after `release`.

## When the release does not finish

Step 2 of [Uninstall](../README.md#uninstall) waits for the newest `status`
entry to end with `state: released`. `invoke` returns before the action
finishes, so if the new `status` entry is missing or still running without a
result, wait a moment and read the log again.

If the `release` entry failed, its error explains why; resolve the issue and
release again. `status` will not report `released` until Herdr reloads
`config.toml` after the block is removed; releasing again retries the reload.

If `status` reports `released` while the old layout remains on screen (every
row of the Agents panel shows only a state icon), run
`herdr server reload-config` to refresh Herdr's in-memory configuration. In
rare cases, an `apply` that fails after the reload of a release has failed can
cause this.

## Removing it by hand

For the cases where `release` cannot do it: the plugin was uninstalled first,
the markers are damaged, or a failed `apply` could not roll everything back.

1. Delete the plugin's lines

   In `config.toml`, delete from the `# >>> herdr-tab-sidebar` marker to the
   `# <<< herdr-tab-sidebar <<<` marker, both included. If a marker is missing
   or duplicated, delete every marker line and the `[ui.sidebar.agents]` table
   shown under [What it changes](#what-it-changes), leaving your own lines
   intact.

2. Reload the config

   Run `herdr server reload-config`. Until then, every row of the Agents panel
   may show only a state icon.

3. Release once more

   If the plugin is still installed, run `release` once more to remove the
   view and its flag, then verify with `status`.

Any `ts_*` tokens still on the panes are display-only; nothing renders them
once the block is gone.
