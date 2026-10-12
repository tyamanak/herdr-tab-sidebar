# herdr-tab-sidebar

English | [Japanese](README.ja.md)

A [Herdr](https://herdr.dev) plugin that turns the Agents panel of the sidebar
into a vertical tab list: one row per tab that has an agent, grouped under a
heading per workspace.

![The Agents panel listing agent tabs grouped by workspace](docs/demo.svg)

The picture is a made-up session drawn by `demo/run.py --svg`; see
[Demo](docs/internals.md#demo).

- Workspaces come in the order of the Spaces panel (your own order), tabs in
  the order of the tab bar.
- A tab with several agents is one row. `+1` counts the agents that have no
  row of their own, and `!` after it means one of those is blocked or done.
- Selecting a row focuses that tab's representative pane.

## Requirements

- Herdr 0.9.1 or later.
- Python 3.9 or later, found as `python3` on the PATH of the Herdr server.
- macOS or Linux. On Linux nothing has been tried by hand yet.

## Install

```sh
herdr plugin install tyamanak/herdr-tab-sidebar
herdr plugin action invoke tyamanak.tab-sidebar.apply
```

Installing changes nothing you can see. `apply` adds the row layout to
`config.toml`, reloads the config and fills in the rows.

You do not have to edit `config.toml` yourself. `apply` appends 8 lines to the
end of the file, and `release` removes them and leaves the file as it was. A
copy of the old file is kept on every change.

The one exception: if `config.toml` already defines `[ui.sidebar.agents]`,
`apply` refuses and changes nothing. Remove or comment out yours, then run
`apply`. See [What it changes](docs/config.md#what-it-changes).

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

   Go on when the newest `status` entry ends with `state: released`. If it
   does not, see
   [When the release does not finish](docs/config.md#when-the-release-does-not-finish).

3. Uninstall:

   ```sh
   herdr plugin uninstall tyamanak.tab-sidebar
   ```

To remove the plugin's lines from `config.toml` yourself, see
[Removing it by hand](docs/config.md#removing-it-by-hand).

## Limits

- Tabs without an agent have no row. Herdr only lists panes that run an agent.
- The other agents of a tab with several agents cannot be reached with
  next/previous agent while the plugin is applied.
- While applied, the plugin replaces Herdr's own ordering of the Agents panel
  and Herdr's Agent view. Using it next to another plugin that sets the view
  has not been tried.

The full list is in [Limits](docs/usage.md#limits).

## Documentation

- [Usage](docs/usage.md): requirements, checking, actions, updating, limits.
- [Configuration](docs/config.md): what `apply` writes and how to undo it.
- [Internals](docs/internals.md): how it works, tests, demo.

## License

MIT. See [LICENSE](LICENSE).
