"""Artificial tests for Stage 3B unit and denominator separation."""
import unittest

from dontsuka_v026_2b_replay import ranks
from dontsuka_v026_3b import first_rank_drop_event, kyoku_outcome, rates


class Stage3BTests(unittest.TestCase):
    def test_average_rank_ties(self):
        self.assertEqual(ranks({1: 40000, 2: 30000, 3: 20000, 4: 10000}),
                         {1: 1, 2: 2, 3: 3, 4: 4})
        self.assertEqual(ranks({1: 30000, 2: 30000, 3: 20000, 4: 20000}),
                         {1: 1.5, 2: 1.5, 3: 3.5, 4: 3.5})
        self.assertEqual(ranks({1: 25000, 2: 25000, 3: 25000, 4: 25000}),
                         {1: 2.5, 2: 2.5, 3: 2.5, 4: 2.5})

    def test_lone_fourth_cannot_drop_below_fourth(self):
        self.assertEqual(ranks({1: 10000, 2: 30000, 3: 30000, 4: 30000})[1], 4)
        self.assertEqual(4.0 - 4.0, 0.0)

    def test_first_rank_drop_moment_is_retained(self):
        rows = [
            {"event_order": "30", "draw_event_id": "3", "rank_drop": "0.5", "drawer_rank_before": "2.0"},
            {"event_order": "10", "draw_event_id": "1", "rank_drop": "0.5", "drawer_rank_before": "1.5"},
            {"event_order": "20", "draw_event_id": "2", "rank_drop": "0", "drawer_rank_before": "2.0"},
        ]
        first = first_rank_drop_event(rows)
        self.assertEqual((first["draw_event_id"], first["drawer_rank_before"]), ("1", "1.5"))

    def test_multiple_opponents_are_one_draw_and_one_kyoku(self):
        rows = [
            {"event_order": "10", "draw_event_id": "7", "rank_drop": "0.5", "drawer_rank_before": "1.0"},
            {"event_order": "10", "draw_event_id": "7", "rank_drop": "0", "drawer_rank_before": "1.0"},
            {"event_order": "20", "draw_event_id": "8", "rank_drop": "0.5", "drawer_rank_before": "2.0"},
        ]
        selected = first_rank_drop_event(rows)
        self.assertEqual(selected["draw_event_id"], "7")
        self.assertEqual(sum(float(r["rank_drop"]) > 0 for r in rows), 2)  # opponent unit
        self.assertEqual(len({r["draw_event_id"] for r in rows if float(r["rank_drop"]) > 0}), 2)  # draw unit
        self.assertEqual(len({"kyoku-player"}), 1)  # kyoku-player denominator key

    def test_rank_and_ron_are_independent(self):
        self.assertEqual(kyoku_outcome(2.0, 1.5, True),
                         {"rank_maintained_or_improved": 1, "actual_ron": 1, "ron_avoided": 0})
        self.assertEqual(kyoku_outcome(2.0, 3.0, False),
                         {"rank_maintained_or_improved": 0, "actual_ron": 0, "ron_avoided": 1})

    def test_zero_denominator_is_empty(self):
        self.assertEqual(rates(0, 0), "")
        self.assertEqual(rates(1, 2), "50.000000000")

    def test_rank_drop_width_uses_half_rank_steps(self):
        for value in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            self.assertEqual(round(value * 2), value * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
