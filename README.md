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
  own row. A trailing `!` means one of them is blocked or done.
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

This rewrites `config.toml`, adding `[ui.sidebar.agents]`.

If `[ui.sidebar.agents]` is already defined, nothing is changed. Remove or
comment out your definition and then run `apply`, or see
[What it changes](docs/config.md#what-it-changes).

## Uninstall

Run the following steps in order.

1. Release the plugin

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.release
   ```

2. Check the state

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.status
   herdr plugin log list --plugin tyamanak.tab-sidebar
   ```

   Make sure the newest `status` entry ends with `state: released` before
   going on. If it does not become `released`, see
   [When the release does not finish](docs/config.md#when-the-release-does-not-finish).

3. Uninstall

   ```sh
   herdr plugin uninstall tyamanak.tab-sidebar
   ```

To remove the plugin's lines from `config.toml` manually, see
[Removing it by hand](docs/config.md#removing-it-by-hand).

## Limits

- Tabs without an agent, such as shells, are not listed.
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
