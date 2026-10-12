# herdr-tab-sidebar

English | [Japanese](README.ja.md)

A [Herdr](https://herdr.dev) plugin that turns the sidebar's Agents panel into
a vertical tab list: one row per tab with an agent, grouped under a heading
per workspace.

![The Agents panel listing agent tabs grouped by workspace](docs/demo.svg)

The picture is a made-up session drawn by `demo/run.py --svg`; see
[Demo](docs/internals.md#demo).

- Workspaces follow the order of the Spaces panel (your own order), and tabs
  follow the order of the tab bar.
- A tab with several agents is one row. `+1` counts the agents without their
  own row, and a trailing `!` means one of them is blocked or done.
- Selecting a row focuses that tab's representative pane.

## Requirements

- Herdr 0.9.1 or later.
- Python 3.9 or later, available as `python3` on the Herdr server's PATH.
- macOS or Linux. Linux has not been tested manually yet.

## Install

```sh
herdr plugin install tyamanak/herdr-tab-sidebar
herdr plugin action invoke tyamanak.tab-sidebar.apply
```

Installing makes no visible changes on its own. `apply` adds the row layout
to `config.toml`, reloads the config, and populates the rows.

You do not have to edit `config.toml` manually. `apply` appends 8 lines to the
end of the file, and `release` removes them to restore it. A backup of the old
file is kept on every change.

One exception: if `config.toml` already defines `[ui.sidebar.agents]`, `apply`
refuses and changes nothing. Remove or comment out your section, then run
`apply`. See [What it changes](docs/config.md#what-it-changes).

## Uninstall

Release first, and only uninstall after confirming the release. Because actions
run in the background and `invoke` returns before they finish, run these as
three separate steps rather than pasting them all at once.

1. Release:

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.release
   ```

2. Check the status, wait a moment, and read the result in the log:

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.status
   ```

   ```sh
   herdr plugin log list --plugin tyamanak.tab-sidebar
   ```

   Proceed once the newest `status` entry ends with `state: released`. If it
   does not, see
   [When the release does not finish](docs/config.md#when-the-release-does-not-finish).

3. Uninstall:

   ```sh
   herdr plugin uninstall tyamanak.tab-sidebar
   ```

To remove the plugin's lines from `config.toml` manually, see
[Removing it by hand](docs/config.md#removing-it-by-hand).

## Limits

- Tabs without an agent have no row: Herdr only lists panes running an agent.
- In tabs with multiple agents, the other agents cannot be reached with
  next/previous agent while the plugin is applied.
- While applied, the plugin replaces Herdr's own ordering of the Agents panel
  and Herdr's Agent view. Using it alongside another plugin that sets the view
  has not been tried.

See [Limits](docs/usage.md#limits) for the full list.

## Documentation

- [Usage](docs/usage.md): requirements, checking, actions, updating, limits.
- [Configuration](docs/config.md): what `apply` writes and how to undo it.
- [Internals](docs/internals.md): how it works, tests, demo.

## License

MIT. See [LICENSE](LICENSE).
