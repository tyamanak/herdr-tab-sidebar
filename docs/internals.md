# Internals

English | [Japanese](internals.ja.md)

This page is part of the herdr-tab-sidebar [README](../README.md).

## How it works

`main.py` is a short program that Herdr starts from the manifest's startup
hook, event hooks, and actions. Each run reads `session.snapshot`, computes the
tokens each pane should carry (`tab_sidebar/plan.py`), and writes only the
differences with `pane.report_metadata`. Nothing stays running.

| Token | On | Meaning |
|---|---|---|
| `ts_m` | every agent pane of a listed tab | handled by this plugin |
| `ts_rep` | the tab's representative pane | this pane is the tab's row |
| `ts_pos` | representative | position in the tab bar, zero padded |
| `ts_group` | first representative of a workspace | heading text |
| `ts_label` | representative | tab name |
| `ts_extra` | representative | `+N` other agents, `!` if one needs attention |

`agent.view.set` (source `plugin:tyamanak.tab-sidebar`, label `tabs`) keeps
the representatives plus any unmarked panes, sorting by `ts_m`,
Herdr's `workspace_order`, then `ts_pos`. Because Herdr manages
workspace order, reordering workspaces needs no hooks and no token changes.

Runs are serialised with a lock under the plugin's state directory. A run that
waited while an earlier one already covered its event exits without doing
anything. The lock holder repeats until a fresh snapshot needs no changes (for
up to 8 seconds; after that it fails unless a later run is queued).

## Tests

```sh
python3 -m unittest discover -s tests -t .
python3 tests/isolated/run.py
```

The first command needs only Python. The second needs `herdr` on the PATH (or
`--herdr PATH`). It starts its own headless Herdr server in a temporary
directory (config, state, plugin registry, and socket), links this checkout
there, and exercises the real hooks, actions, and rendering. It builds the
server environment from scratch, refuses to continue unless the server it
reaches reports a socket inside the temporary directory, and removes the
directory at the end. Your session and `~/.config/herdr` are not touched.

## Demo

```sh
python3 demo/run.py              # open the demo session in this terminal
python3 demo/run.py --text       # print the screen as text
python3 demo/run.py --svg FILE   # write the screen as an SVG image
```

The demo uses the same kind of throwaway server as the tests, populated with
mock workspaces and tabs. No agents are started: panes print prepared text,
and their states are reported with `herdr pane report-agent`. The first
command shows how to exit before opening (`ctrl+g`, then `q`), and removes the
server and its directory when you quit or close the terminal. If you run it
from inside Herdr and your prefix key is `ctrl+g`, pass another one with
`--prefix`.
