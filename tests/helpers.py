"""Snapshot builders and a small model of Herdr's Agent view evaluation."""
from __future__ import annotations

import copy
import functools
import os

from tab_sidebar import plan as planner


def fake_command(directory, exit_code):
    """A stand-in for the herdr executable that only exits with a code."""
    path = os.path.join(directory, "herdr-exit-%d" % exit_code)
    with open(path, "w") as stream:
        stream.write("#!/bin/sh\nexit %d\n" % exit_code)
    os.chmod(path, 0o755)
    return path


def snapshot(*workspaces):
    """Build a session snapshot.

    Each workspace is ``(id, label, [tab, ...])`` and each tab is
    ``(tab_id_suffix, label, [pane, ...])``. A pane is ``"p1"`` for a shell or
    ``("p1", status)`` / ``("p1", status, tokens)`` for an agent.
    """
    result = {"workspaces": [], "tabs": [], "panes": [], "agents": []}
    for number, (ws_id, label, tabs) in enumerate(workspaces, 1):
        result["workspaces"].append(
            {"workspace_id": ws_id, "label": label, "number": number, "tab_count": len(tabs)}
        )
        for tab_number, (tab_suffix, tab_label, panes) in enumerate(tabs, 1):
            tab_id = "%s:%s" % (ws_id, tab_suffix)
            result["tabs"].append(
                {"workspace_id": ws_id, "tab_id": tab_id, "label": tab_label,
                 "number": int(tab_suffix.lstrip("t")), "pane_count": len(panes)}
            )
            for pane in panes:
                spec = (pane,) if isinstance(pane, str) else pane
                pane_id = "%s:%s" % (ws_id, spec[0])
                entry = {"workspace_id": ws_id, "tab_id": tab_id, "pane_id": pane_id}
                if len(spec) > 2 and spec[2]:
                    entry["tokens"] = dict(spec[2])
                if len(spec) > 1:
                    entry.update({"agent": "claude", "agent_status": spec[1]})
                    result["agents"].append(dict(entry))
                result["panes"].append(entry)
    return result


def settle(snap):
    """The snapshot as it looks once the plan's tokens have been written."""
    plan = planner.build_plan(snap)
    after = copy.deepcopy(snap)
    for group in ("panes", "agents"):
        for entry in after[group]:
            tokens = {k: v for k, v in plan["desired"][entry["pane_id"]].items() if v is not None}
            entry.pop("tokens", None)
            if tokens:
                entry["tokens"] = tokens
    return after


def _pane_number(pane_id):
    return int("".join(ch for ch in pane_id.split(":p")[-1] if ch.isdigit()) or 0)


def entries(snap, scope=0):
    """Agent view entries of one machine, as Herdr derives them."""
    ws_index = {w["workspace_id"]: i for i, w in enumerate(snap["workspaces"])}
    tab_number = {t["tab_id"]: t["number"] for t in snap["tabs"]}
    return [
        {
            "scope": scope,
            "pane_id": agent["pane_id"],
            "tab_id": agent["tab_id"],
            "tokens": dict(agent.get("tokens") or {}),
            "workspace_order": ws_index[agent["workspace_id"]],
            "tab_order": tab_number[agent["tab_id"]],
            "pane_order": _pane_number(agent["pane_id"]),
        }
        for agent in snap["agents"]
    ]


def _field(entry, field):
    if isinstance(field, dict):
        return entry["tokens"].get(field["token"])
    return entry.get(field)


def _matches(entry, node):
    op = node["op"]
    if op == "any":
        return any(_matches(entry, child) for child in node["filters"])
    if op == "all":
        return all(_matches(entry, child) for child in node["filters"])
    if op == "not":
        return not _matches(entry, node["filter"])
    if op == "eq":
        return _field(entry, node["field"]) == node["value"]
    if op == "exists":
        return _field(entry, node["field"]) is not None
    raise AssertionError("unsupported op %s" % op)


def apply_view(view, all_entries):
    """Filter and sort like src/agent_view_eval.rs: stable, missing values last."""
    kept = [e for e in all_entries if _matches(e, view["filter"])]

    def compare(left, right):
        for sort in view["sort"]:
            a, b = _field(left, sort["field"]), _field(right, sort["field"])
            if a is None and b is None:
                continue
            if a is None:
                return 1
            if b is None:
                return -1
            if a != b:
                order = -1 if a < b else 1
                return -order if sort.get("order") == "desc" else order
        return 0

    return sorted(kept, key=functools.cmp_to_key(compare))


def displayed(snap, remote=None):
    """(heading, label, pane_id) of every row the Agents panel would show."""
    view = planner.view_request("plugin:test")
    rows = entries(settle(snap))
    if remote is not None:
        rows += entries(remote, scope=1)
    return [
        (e["tokens"].get(planner.TOKEN_GROUP), e["tokens"].get(planner.TOKEN_LABEL), e["pane_id"])
        for e in apply_view(view, rows)
    ]
