import unittest

from tab_sidebar import plan as planner
from tab_sidebar.plan import PAD

from tests.helpers import apply_view, displayed, entries, settle, snapshot

API = ("w1", "🚀 api-server", [
    ("t1", "fix-login", [("p1", "idle")]),
    ("t2", "rate-limit", [("p2", "working"), "p3"]),
    ("t3", "review-pr", [("p4", "done")]),
])
WEB = ("w2", "web-app", [("t1", "update-deps", [("p1", "working")])])
DOCS = ("w3", "docs", [("t1", "shell", ["p1"])])


def rows(snap):
    return [(r["heading"], r["label"], r["pane_id"]) for r in planner.build_plan(snap)["rows"]]


class PlanTest(unittest.TestCase):
    def test_tabs_follow_tab_bar_order_under_workspace_headings(self):
        self.assertEqual(
            rows(snapshot(API, WEB)),
            [
                ("🚀 api-server", "fix-login", "w1:p1"),
                (None, "rate-limit", "w1:p2"),
                (None, "review-pr", "w1:p4"),
                ("web-app", "update-deps", "w2:p1"),
            ],
        )

    def test_view_sort_reproduces_the_planned_rows(self):
        snap = snapshot(API, WEB)
        self.assertEqual(
            displayed(snap),
            [
                ("🚀 api-server", "fix-login", "w1:p1"),
                (None, PAD + "rate-limit", "w1:p2"),
                (None, PAD + "review-pr", "w1:p4"),
                ("web-app", "update-deps", "w2:p1"),
            ],
        )

    def test_tab_position_is_the_array_position_not_the_tab_number(self):
        # A tab dragged to the front keeps its number but leads the array.
        moved = ("w1", "🚀 api-server", [
            ("t9", "newest-first", [("p9", "idle")]),
            ("t1", "fix-login", [("p1", "idle")]),
        ])
        self.assertEqual(
            displayed(snapshot(moved)),
            [("🚀 api-server", "newest-first", "w1:p9"), (None, PAD + "fix-login", "w1:p1")],
        )

    def test_workspace_order_follows_the_spaces_order_not_the_name(self):
        self.assertEqual(
            [r[0] for r in displayed(snapshot(API, WEB)) if r[0]],
            ["🚀 api-server", "web-app"],
        )
        self.assertEqual(
            [r[0] for r in displayed(snapshot(WEB, API)) if r[0]],
            ["web-app", "🚀 api-server"],
        )

    def test_reordering_workspaces_needs_no_token_change(self):
        settled = settle(snapshot(API, WEB))
        reordered = dict(settled, workspaces=list(reversed(settled["workspaces"])))
        self.assertEqual(planner.diff(planner.build_plan(reordered)), {})
        shown = [e["pane_id"] for e in apply_view(planner.view_request("s"), entries(reordered))]
        self.assertEqual(shown, ["w2:p1", "w1:p1", "w1:p2", "w1:p4"])

    def test_several_agents_in_a_tab_make_one_row(self):
        snap = snapshot(("w1", "api-server", [
            ("t1", "pair", [("p1", "working"), ("p2", "idle"), "p3"]),
            ("t2", "solo", [("p4", "idle")]),
        ]))
        self.assertEqual(
            displayed(snap), [("api-server", "pair", "w1:p1"), (None, PAD + "solo", "w1:p4")]
        )
        plan = planner.build_plan(snap)
        self.assertEqual(plan["desired"]["w1:p1"][planner.TOKEN_EXTRA], "+1")
        # The other agent is marked as handled but is not a representative.
        self.assertEqual(plan["desired"]["w1:p2"][planner.TOKEN_MANAGED], "1")
        self.assertIsNone(plan["desired"]["w1:p2"][planner.TOKEN_REP])
        # A plain shell pane gets nothing.
        self.assertTrue(all(v is None for v in plan["desired"]["w1:p3"].values()))

    def test_hidden_agent_needing_attention_is_flagged_on_the_row(self):
        for status, expected in (("blocked", "+1!"), ("done", "+1!"), ("working", "+1")):
            snap = snapshot(("w1", "api-server", [("t1", "pair", [("p1", "idle"), ("p2", status)])]))
            self.assertEqual(
                planner.build_plan(snap)["desired"]["w1:p1"][planner.TOKEN_EXTRA], expected
            )

    def test_representative_stays_on_the_same_pane(self):
        # p2 was chosen earlier (it was alone); p1 became an agent later.
        snap = snapshot(("w1", "api-server", [
            ("t1", "pair", [("p1", "idle"), ("p2", "idle", {"ts_rep": "1", "ts_m": "1"})]),
        ]))
        self.assertEqual(rows(snap), [("api-server", "pair", "w1:p2")])
        # ...and it stays there on the next run.
        self.assertEqual(rows(settle(snap)), [("api-server", "pair", "w1:p2")])

    def test_representative_moves_when_its_agent_leaves(self):
        snap = snapshot(("w1", "api-server", [
            ("t1", "pair", [("p1", "idle"), ("p2", None, {"ts_rep": "1", "ts_m": "1"})]),
        ]))
        snap["agents"] = [a for a in snap["agents"] if a["pane_id"] != "w1:p2"]
        plan = planner.build_plan(snap)
        self.assertEqual([r["pane_id"] for r in plan["rows"]], ["w1:p1"])
        # The pane that lost its agent is cleaned up.
        self.assertEqual(
            planner.diff(plan)["w1:p2"], {planner.TOKEN_MANAGED: None, planner.TOKEN_REP: None}
        )

    def test_two_flagged_panes_in_one_tab_still_give_one_row(self):
        # A representative pane was moved into a tab that already had one.
        flag = {"ts_rep": "1", "ts_m": "1"}
        snap = snapshot(("w1", "api-server", [("t1", "pair", [("p1", "idle", flag), ("p2", "idle", flag)])]))
        self.assertEqual(displayed(snap), [("api-server", "pair", "w1:p1")])

    def test_closing_the_first_tab_moves_the_heading(self):
        before = settle(snapshot(API, WEB))
        after = dict(before)
        after["tabs"] = [t for t in before["tabs"] if t["tab_id"] != "w1:t1"]
        after["panes"] = [p for p in before["panes"] if p["tab_id"] != "w1:t1"]
        after["agents"] = [a for a in before["agents"] if a["tab_id"] != "w1:t1"]
        self.assertEqual(
            displayed(after),
            [
                ("🚀 api-server", "rate-limit", "w1:p2"),
                (None, PAD + "review-pr", "w1:p4"),
                ("web-app", "update-deps", "w2:p1"),
            ],
        )
        patch = planner.diff(planner.build_plan(after))
        self.assertEqual(sorted(patch), ["w1:p2", "w1:p4"])
        self.assertEqual(patch["w1:p2"][planner.TOKEN_GROUP], "🚀 api-server")
        self.assertEqual(patch["w1:p4"], {planner.TOKEN_POS: "0001"})

    def test_closing_a_whole_workspace_leaves_the_others_untouched(self):
        before = settle(snapshot(API, WEB))
        after = {k: [x for x in v if x["workspace_id"] != "w1"] for k, v in before.items()}
        self.assertEqual(planner.diff(planner.build_plan(after)), {})
        self.assertEqual(displayed(after), [("web-app", "update-deps", "w2:p1")])

    def test_workspace_without_agents_has_no_heading(self):
        snap = snapshot(DOCS, API, WEB)
        self.assertEqual([r[0] for r in displayed(snap) if r[0]], ["🚀 api-server", "web-app"])
        self.assertTrue(
            all(v is None for v in planner.build_plan(snap)["desired"]["w3:p1"].values())
        )

    def test_heading_goes_to_the_first_tab_that_has_an_agent(self):
        snap = snapshot(("w1", "api-server", [
            ("t1", "shell", ["p1"]),
            ("t2", "agent", [("p2", "idle")]),
        ]))
        self.assertEqual(displayed(snap), [("api-server", "agent", "w1:p2")])
        self.assertEqual(planner.build_plan(snap)["desired"]["w1:p2"][planner.TOKEN_POS], "0001")

    def test_remote_agents_keep_their_rows_after_the_local_groups(self):
        local = snapshot(API, WEB)
        # Another machine's agents carry no tokens from this plugin, and their
        # workspace order overlaps the local one.
        remote = snapshot(
            ("w1", "remote-a", [("t1", "x", [("p1", "idle")])]),
            ("w2", "remote-b", [("t1", "y", [("p1", "working")])]),
        )
        shown = displayed(local, remote=remote)
        self.assertEqual(len(shown), 6)
        self.assertEqual(
            shown[:4],
            [
                ("🚀 api-server", "fix-login", "w1:p1"),
                (None, PAD + "rate-limit", "w1:p2"),
                (None, PAD + "review-pr", "w1:p4"),
                ("web-app", "update-deps", "w2:p1"),
            ],
        )
        self.assertEqual(shown[4:], [(None, None, "w1:p1"), (None, None, "w2:p1")])

    def test_a_new_agent_shows_up_before_the_plugin_has_marked_it(self):
        settled = settle(snapshot(API))
        fresh = snapshot(("w1", "🚀 api-server", [("t7", "new", [("p7", "working")])]))
        both = entries(settled) + [dict(e, workspace_order=0) for e in entries(fresh)]
        shown = [e["pane_id"] for e in apply_view(planner.view_request("s"), both)]
        self.assertEqual(shown, ["w1:p1", "w1:p2", "w1:p4", "w1:p7"])

    def test_settled_snapshot_needs_no_writes(self):
        self.assertEqual(planner.diff(planner.build_plan(settle(snapshot(API, WEB, DOCS)))), {})

    def test_force_rewrites_present_tokens_only(self):
        patch = planner.diff(planner.build_plan(settle(snapshot(WEB))), force=True)
        self.assertEqual(
            patch,
            {"w2:p1": {"ts_m": "1", "ts_rep": "1", "ts_pos": "0000",
                       "ts_group": "web-app", "ts_label": "update-deps"}},
        )

    def test_long_labels_fit_the_token_limit(self):
        snap = snapshot(("w1", "W" * 200, [
            ("t1", "a" * 200, [("p1", "idle")]),
            ("t2", "b" * 200, [("p2", "idle")]),
        ]))
        for tokens in planner.build_plan(snap)["desired"].values():
            for value in tokens.values():
                self.assertLessEqual(len(value or ""), planner.MAX_VALUE_CHARS)

    def test_only_control_characters_are_dropped_from_labels(self):
        family = "\U0001F468\u200d\U0001F469"  # joined emoji
        snap = snapshot(("w1", "a\u3000b", [("t1", " %s\tx\x07 " % family, [("p1", "idle")])]))
        tokens = planner.build_plan(snap)["desired"]["w1:p1"]
        self.assertEqual(tokens[planner.TOKEN_GROUP], "a\u3000b")
        self.assertEqual(tokens[planner.TOKEN_LABEL], family + "x")

    def test_tokens_stay_within_the_report_limit_and_the_prefix(self):
        self.assertLessEqual(len(planner.TOKENS), 16)
        self.assertTrue(all(name.startswith("ts_") for name in planner.TOKENS))

    def test_other_plugins_tokens_are_ignored(self):
        snap = snapshot(("w1", "api-server", [("t1", "x", [("p1", "idle", {"model": "opus"})])]))
        plan = planner.build_plan(snap)
        self.assertEqual(plan["current"]["w1:p1"], {})
        self.assertNotIn("model", planner.diff(plan)["w1:p1"])

    def test_tokens_given_as_pairs_are_understood(self):
        self.assertEqual(planner.token_map([["ts_rep", "1"]]), {"ts_rep": "1"})


if __name__ == "__main__":
    unittest.main()
