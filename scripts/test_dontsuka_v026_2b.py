import unittest
from itertools import product
from dontsuka_v026_2b_replay import Ledger,ranks,tsumo_split,finish

class Tests(unittest.TestCase):
    def ledger(self, scores=None,sticks=0, dealer=1,honba=0):
        return Ledger(scores or {1:25000,2:25000,3:25000,4:25000},sticks,dealer,honba)
    def test_ties(self):
        for s,r in [([4,3,2,1],[1,2,3,4]),([4,4,2,1],[1.5,1.5,3,4]),
                    ([4,3,3,1],[1,2.5,2.5,4]),([4,3,1,1],[1,2,3.5,3.5]),
                    ([4,4,4,1],[2,2,2,4]),([4,1,1,1],[1,3,3,3]),([1,1,1,1],[2.5]*4)]:
            self.assertEqual(list(ranks(dict(enumerate(s))).values()),r)
    def test_all_tie_permutations(self):
        for v in product(range(4),repeat=4):
            r=ranks(dict(enumerate(v)));self.assertEqual(sum(r.values()),10)
            for i in range(4):
                for j in range(4):
                    if v[i]>v[j]:self.assertLess(r[i],r[j])
                    if v[i]==v[j]:self.assertEqual(r[i],r[j])
    def test_accepted(self):
        l=self.ledger();l.step("draw",{});self.assertEqual(l.s[1],25000)
        l.step("reach",dict(actor_player_id=1,is_accepted=1));l.step("draw",{})
        self.assertEqual((l.s[1],l.sticks,ranks(l.s)[1]),(24000,1,4))
    def test_rejected(self):
        l=self.ledger();l.step("reach",dict(actor_player_id=2,is_accepted=0))
        self.assertEqual((l.s[2],l.sticks),(25000,0))
    def test_duplicate_reach(self):
        l=self.ledger();r=dict(actor_player_id=2,is_accepted=1);l.step("reach",r)
        with self.assertRaises(ValueError):l.step("reach",r)
    def test_ron(self):
        l=self.ledger({1:25000,2:24000,3:25000,4:25000},1,honba=2)
        l.step("ron",dict(actor_player_id=2,target_player_id=1,agari_points=8000,honba_points=600,kyotaku_points=1000))
        self.assertEqual((l.s,l.sticks),({1:16400,2:33600,3:25000,4:25000},0))
    def test_parent_tsumo(self):
        l=self.ledger(honba=1);l.step("tsumo",dict(actor_player_id=1,agari_points=12000,honba_points=300,kyotaku_points=0))
        self.assertEqual(l.s,{1:37300,2:20900,3:20900,4:20900})
    def test_child_tsumo_rounding(self):
        self.assertEqual(tsumo_split(1100,2,1,[1,2,3,4]),{1:500,3:300,4:300})
        self.assertEqual(tsumo_split(8000,2,1,[1,2,3,4]),{1:4000,3:2000,4:2000})
        l=self.ledger(honba=1);l.step("tsumo",dict(actor_player_id=2,agari_points=1100,honba_points=300,kyotaku_points=0))
        self.assertEqual(l.s,{1:24400,2:26400,3:24600,4:24600})
    def test_draw_carry(self):
        l=self.ledger();l.step("reach",dict(actor_player_id=1,is_accepted=1))
        l.step("ryukyoku",dict(delta={1:3000,2:-1000,3:-1000,4:-1000}))
        self.assertEqual((l.s,l.sticks),({1:27000,2:24000,3:24000,4:24000},1))
        l2=self.ledger(l.s,l.sticks);self.assertEqual(l2.sticks,1)
    def test_match_end(self):
        s={1:35000,2:35000,3:20000,4:9000};f,p=finish(s,1,{1:"2z",2:"1z",3:"3z",4:"4z"})
        self.assertEqual((f,p),({1:35000,2:36000,3:20000,4:9000},2))
        self.assertEqual(s[2],35000)
    def test_recorded_honba_difference(self):
        a=self.ledger(honba=1);b=self.ledger(honba=1)
        r=dict(actor_player_id=2,target_player_id=3,agari_points=8000,honba_points=0,kyotaku_points=0)
        a.step("ron",r);b.step("ron",dict(r,honba_points=300))
        self.assertEqual(a.s,{1:25000,2:33000,3:17000,4:25000})
        self.assertEqual(b.s,{1:25000,2:33300,3:16700,4:25000})
    def test_neutral_and_terminal(self):
        l=self.ledger()
        for k in ("haipai","discard","pon","chi","daiminkan","shominkan","ankan","dora_indicator"):l.step(k,{})
        self.assertEqual(l.s,{1:25000,2:25000,3:25000,4:25000})
        l.step("ryukyoku",dict(delta={p:0 for p in l.s}))
        with self.assertRaises(ValueError):l.step("draw",{})
    def test_conservation(self):
        with self.assertRaises(ValueError):self.ledger({1:25000,2:25000,3:25000,4:24900})
    def test_kyotaku_no_double_count(self):
        l=self.ledger();l.step("reach",dict(actor_player_id=2,is_accepted=1))
        l.step("ron",dict(actor_player_id=2,target_player_id=3,agari_points=8000,honba_points=0,kyotaku_points=1000))
        self.assertEqual(l.s,{1:25000,2:33000,3:17000,4:25000})

if __name__=="__main__":unittest.main(verbosity=2)
