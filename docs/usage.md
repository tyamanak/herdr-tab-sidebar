# Usage

English | [Japanese](usage.ja.md)

This page is part of the [README](../README.md) of herdr-tab-sidebar.

## Requirements

- Herdr 0.9.1 or later. Developed and tested with Herdr 0.9.3.
- Python 3.9 or later, available as `python3` on the Herdr server's PATH.
  Only the standard library is used. On an older `python3`, every hook and
  action fails with an error message saying so.
- macOS or Linux. Everything below was run on macOS. Linux has not been
  tested by hand yet; unit tests are set up to run there in CI.

## Install once

Install only once. A second copy under another plugin id (such as a fork, or
a local `herdr plugin link` of a clone next to the installed one) writes the
same `ts_*` tokens and the same block in `config.toml`, so the two will undo
each other's work.

## Check

```sh
herdr plugin action invoke tyamanak.tab-sidebar.status
herdr plugin log list --plugin tyamanak.tab-sidebar
```

The last line printed by the `status` action is `state: applied`,
`state: released`, or whatever is blocking either. Because actions run in the
background, their output and errors appear in the plugin log, not in the
terminal that invoked them.

From a clone of this repository, you can run the same check with a single
command and an exit code:

```sh
python3 main.py status --expect applied    # or: --expect released
```

It prints `OK: applied (N rows)`, or `NOT applied:` followed by the reasons.
`python3 main.py preview` prints the rows the current session would produce.
Both commands are read-only.

## Actions

| Action | Effect |
|---|---|
| `tyamanak.tab-sidebar.apply` | add the block to `config.toml`, reload the config, set the view, write all tokens |
| `tyamanak.tab-sidebar.release` | clear the view and all tokens, remove the block, reload the config |
| `tyamanak.tab-sidebar.resync` | write the view and every token again from the current session |
| `tyamanak.tab-sidebar.status` | report the state; changes nothing |

The list updates automatically as the session changes (workspaces renamed;
tabs created, closed, renamed, or moved; panes closed or moved; agents
detected and their state changes) and comes back after a server restart. Use
`resync` if it ever looks stale.

## Update

To update, install the plugin again; Herdr replaces its checkout:

```sh
herdr plugin install tyamanak/herdr-tab-sidebar
```

## Limits

- Tabs without an agent, such as shells, are not listed. Herdr only lists
  panes running an agent.
- The state icon appears at the end of the row, not the start. Herdr indents
  the first line of an entry differently from following lines, so a leading
  icon cannot align between the first tab of a workspace and the rest.
- While applied, the plugin replaces Herdr's own ordering of the Agents panel
  (`agent_panel_sort`). `release` restores it.
- Herdr has only one Agent view. The plugin sets it on every run, overwriting
  any view from another plugin, and another plugin setting the view will
  overwrite this one. Using it alongside such a plugin has not been tried.
- Agents on another machine (Herdr can show several machines in one client)
  keep a row after the local groups, but it only shows the machine name and
  the state icon. The row layout is one definition for every row, and the
  plugin's tokens exist only on local panes. This is based on the code and
  unit tests; it has not been checked on a real remote connection. If you work
  that way most of the time, run `release` first.
- In tabs with multiple agents, the other agents cannot be reached with
  next/previous agent while the plugin is applied.
- Herdr runs at most 32 plugin commands at once and drops the rest. If a large
  burst of changes leaves the list stale, the next change or `resync` fixes it.
- Not tried: updating Herdr in place while the session keeps running.
  A standard server restart is covered by tests (the startup hook restores
  the list).
