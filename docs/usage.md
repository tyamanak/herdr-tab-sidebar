# Usage

English | [Japanese](usage.ja.md)

This page belongs to the [README](../README.md) of herdr-tab-sidebar.

## Requirements

- Herdr 0.9.1 or later. Developed and tested with Herdr 0.9.3.
- Python 3.9 or later, found as `python3` on the PATH of the Herdr server.
  Only the standard library is used. With an older `python3` every hook and
  action fails with a message that says so.
- macOS or Linux. Everything below was run on macOS. On Linux nothing has
  been tried by hand yet; the unit tests are set up to run there in CI.

## Install once

Install it once. A second copy under another plugin id (a fork, or a local
`herdr plugin link` of a clone next to the installed one) would write the same
`ts_*` tokens and the same block in `config.toml`, and the two would undo each
other's work.

## Check

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

## Actions

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

## Update

To update, install again; Herdr replaces its checkout:

```sh
herdr plugin install tyamanak/herdr-tab-sidebar
```

## Limits

- Tabs without an agent are not listed. Herdr only lists panes that run an
  agent, so a tab that holds only shells has no row.
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
