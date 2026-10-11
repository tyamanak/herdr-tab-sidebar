"""Pure computation: Herdr session snapshot -> pane tokens for the Agents panel.

Nothing in this module talks to Herdr. It takes the ``snapshot`` object of a
``session.snapshot`` response and returns the tokens every pane should carry,
so the ordering, representative and heading rules can be unit tested from JSON.
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional

TOKEN_MANAGED = "ts_m"
TOKEN_REP = "ts_rep"
TOKEN_POS = "ts_pos"
TOKEN_GROUP = "ts_group"
TOKEN_LABEL = "ts_label"
TOKEN_EXTRA = "ts_extra"
TOKENS = (TOKEN_MANAGED, TOKEN_REP, TOKEN_POS, TOKEN_GROUP, TOKEN_LABEL, TOKEN_EXTRA)

# Herdr caps token values at 80 characters and trims surrounding whitespace.
MAX_VALUE_CHARS = 80
# The first content line of a sidebar entry is indented 1 column and every
# later line 3 columns. A heading entry shows its tab label on the second line,
# so the other entries pad their label by two cells to line up with it.
# U+2800 (braille blank) is one cell wide, renders empty and survives trimming.
PAD = "⠀⠀"
ATTENTION_STATUSES = ("blocked", "done")

Tokens = Dict[str, Optional[str]]


def token_map(raw) -> Dict[str, str]:
    """Tokens as a dict, whether the API sent a map or a list of pairs."""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    result = {}
    for item in raw or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            result[str(item[0])] = str(item[1])
        elif isinstance(item, dict) and "name" in item and "value" in item:
            result[str(item["name"])] = str(item["value"])
    return result


def own_tokens(raw) -> Dict[str, str]:
    return {k: v for k, v in token_map(raw).items() if k in TOKENS}


def clip(text: str, limit: int = MAX_VALUE_CHARS) -> str:
    # Same normalisation as Herdr: drop control characters, trim the ends.
    text = "".join(ch for ch in str(text) if unicodedata.category(ch) != "Cc").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_plan(snapshot: dict) -> dict:
    """Return the desired tokens and the resulting display order.

    Result keys:
      ``desired``: pane_id -> {token: value or None} for every pane in the
        snapshot (``None`` means the token must be absent).
      ``current``: pane_id -> the plugin's tokens the snapshot reports now.
      ``rows``: the managed entries in display order, for tests and previews.
    """
    workspaces = snapshot.get("workspaces") or []
    tabs = snapshot.get("tabs") or []
    panes = snapshot.get("panes") or []
    agents = snapshot.get("agents") or []

    agent_by_pane = {a["pane_id"]: a for a in agents if a.get("pane_id")}
    pane_ids: List[str] = []
    current: Dict[str, Dict[str, str]] = {}
    pane_order: Dict[str, int] = {}
    for pane in panes:
        pane_id = pane.get("pane_id")
        if not pane_id or pane_id in pane_order:
            continue
        pane_order[pane_id] = len(pane_ids)
        pane_ids.append(pane_id)
        current[pane_id] = own_tokens(pane.get("tokens"))
    for pane_id, agent in agent_by_pane.items():
        if pane_id not in pane_order:
            pane_order[pane_id] = len(pane_ids)
            pane_ids.append(pane_id)
            current[pane_id] = {}
        current[pane_id].update(own_tokens(agent.get("tokens")))

    # Agents of each tab, in the tab's pane order.
    agents_by_tab: Dict[str, List[str]] = {}
    for pane_id in pane_ids:
        agent = agent_by_pane.get(pane_id)
        if agent and agent.get("tab_id"):
            agents_by_tab.setdefault(agent["tab_id"], []).append(pane_id)

    desired: Dict[str, Tokens] = {p: {t: None for t in TOKENS} for p in pane_ids}
    rows = []
    for ws_index, workspace in enumerate(workspaces):
        ws_id = workspace.get("workspace_id")
        ws_tabs = [t for t in tabs if t.get("workspace_id") == ws_id]
        heading_done = False
        for position, tab in enumerate(ws_tabs):
            members = agents_by_tab.get(tab.get("tab_id")) or []
            if not members:
                continue
            # Keep the previous representative while it is still an agent of
            # this tab, so a row does not jump between panes on every event.
            sticky = [p for p in members if current[p].get(TOKEN_REP) == "1"]
            rep = sticky[0] if sticky else members[0]
            others = [p for p in members if p != rep]
            for pane_id in others:
                desired[pane_id][TOKEN_MANAGED] = "1"

            heading = None if heading_done else clip(workspace.get("label") or ws_id or "")
            heading_done = True
            tab_label = str(tab.get("label") or "").strip() or "tab %s" % tab.get("number", position + 1)
            pad = "" if heading else PAD
            label = pad + clip(tab_label, MAX_VALUE_CHARS - len(pad))
            extra = None
            if others:
                attention = any(
                    agent_by_pane[p].get("agent_status") in ATTENTION_STATUSES for p in others
                )
                extra = "+%d%s" % (len(others), "!" if attention else "")
            desired[rep].update(
                {
                    TOKEN_MANAGED: "1",
                    TOKEN_REP: "1",
                    TOKEN_POS: "%04d" % position,
                    TOKEN_GROUP: heading or None,
                    TOKEN_LABEL: label,
                    TOKEN_EXTRA: extra,
                }
            )
            rows.append(
                {
                    "workspace_index": ws_index,
                    "workspace_id": ws_id,
                    "tab_id": tab.get("tab_id"),
                    "pane_id": rep,
                    "heading": heading or None,
                    "label": tab_label,
                    "extra": extra,
                    "status": agent_by_pane[rep].get("agent_status"),
                }
            )
    return {"desired": desired, "current": current, "rows": rows}


def diff(plan: dict, force: bool = False) -> Dict[str, Tokens]:
    """Token patches (value or None to clear) that turn current into desired.

    ``force`` rewrites every token that should be present even when the
    snapshot already reports it, for startup and manual resync.
    """
    patches: Dict[str, Tokens] = {}
    for pane_id, want in plan["desired"].items():
        have = plan["current"].get(pane_id, {})
        patch: Tokens = {}
        for name in TOKENS:
            value = want.get(name)
            if value is None:
                if name in have:
                    patch[name] = None
            elif force or have.get(name) != value:
                patch[name] = value
        if patch:
            patches[pane_id] = patch
    return patches


def view_request(source: str) -> dict:
    """``agent.view.set`` params.

    Panes the plugin has not marked yet (a new agent, or an agent of another
    machine) pass the filter and keep their own row; they sort after the
    managed rows so they never split a workspace group.
    """
    return {
        "source": source,
        "label": "tabs",
        "filter": {
            "op": "any",
            "filters": [
                {"op": "eq", "field": {"token": TOKEN_REP}, "value": "1"},
                {"op": "not", "filter": {"op": "exists", "field": {"token": TOKEN_MANAGED}}},
            ],
        },
        "sort": [
            {"field": {"token": TOKEN_MANAGED}, "order": "asc"},
            {"field": "workspace_order", "order": "asc"},
            {"field": {"token": TOKEN_POS}, "order": "asc"},
            {"field": "tab_order", "order": "asc"},
            {"field": "pane_order", "order": "asc"},
        ],
    }


def render_preview(plan: dict) -> str:
    """The managed rows as the Agents panel would list them (text only)."""
    lines = []
    for row in plan["rows"]:
        if row["heading"]:
            lines.append(row["heading"])
        extra = " · %s" % row["extra"] if row["extra"] else ""
        lines.append("  %s%s · [%s]" % (row["label"], extra, row["status"] or "?"))
    return "\n".join(lines)
