# Internals

English | [Japanese](internals.ja.md)

This page belongs to the [README](../README.md) of herdr-tab-sidebar.

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
