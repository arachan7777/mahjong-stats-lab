"""Concrete hand and boundary tests, Stage 5A only."""
import unittest
from dontsuka_v026_5a_core import evaluate_waits,qualifies,candidates
from dontsuka_v026_2a_audit import score
from dontsuka_v026_5a import kan_transition,new_kan_furiten,no_physical_wait
from dontsuka_v026_2a_replay import Replay
def hand(s):return s.split()
def evaluate(s,m=(),om=(),reached=False,double=False,furiten=False,possible=True):
    return evaluate_waits(hand(s),list(m),"2z","1z",list(om),reached,double,furiten,possible)
def find(patterns,t,method):
    return next(x for x in patterns if x["tile"]==t and x["method"]==method)
class Test(unittest.TestCase):
    def test_or(self):
        for h,f,ok in [(3,30,False),(3,60,True),(3,70,True),(4,20,True),(4,30,True),(5,20,True)]:
            self.assertEqual(qualifies(dict(han=h,fu=f,points=score(h,f,False,False),yakuman=False),False),ok)
    def test_pinfu_tsumo(self):
        w,p,ok=evaluate("2m 3m 4m 3p 4p 5p 4s 5s 6s 2p 2p 6s 7s")
        self.assertTrue(ok)
        ron,tsumo=find(p,"8s","ron"),find(p,"8s","tsumo")
        self.assertEqual((ron["han"],ron["fu"]),(3,30))
        self.assertEqual((tsumo["han"],tsumo["fu"]),(4,20))
        self.assertFalse(ron["qualifies"]);self.assertTrue(tsumo["qualifies"])
        self.assertEqual(tsumo["yaku"]["門前清自摸和"],1)
        self.assertEqual(ron["yaku"]["立直"],1)
        self.assertTrue(ron["virtual_riichi"])
        self.assertIn("0s",w)
    def test_kiriage_concrete(self):
        _,p,_=evaluate("9p 9p 9p 5z 5z 7z 7z 2s 3s 4s",[("ankan",hand("2m 2m 2m 2m"))],["1s"])
        r=find(p,"7z","ron")
        self.assertEqual((r["han"],r["fu"],r["points"]),(3,60,8000))
        self.assertTrue(r["qualifies"])
    def test_accepted_and_double(self):
        s="2m 3m 4m 3p 4p 5p 4s 5s 6s 2p 2p 6s 7s"
        for double in (False,True):
            _,p,_=evaluate(s,reached=True,double=double)
            r=find(p,"8s","ron")
            self.assertFalse(r["virtual_riichi"])
            self.assertEqual(r["yaku"].get("立直",0),0 if double else 1)
            self.assertEqual(r["yaku"].get("ダブル立直",0),2 if double else 0)
    def test_open_red_and_kan_dora(self):
        _,p,ok=evaluate("3p 4p 5p 4s 5s 6s 2p 2p 6s 7s",[("chi",hand("2m 3m 4m"))],["1p","4s"])
        self.assertTrue(ok)
        r=find(p,"0s","tsumo")
        self.assertFalse(r["virtual_riichi"])
        self.assertNotIn("門前清自摸和",r["yaku"])
        self.assertEqual(r["yaku"]["赤ドラ"],1)
        self.assertEqual(r["yaku"]["ドラ"],4)
    def test_sanshoku_high_low(self):
        _,p,ok=evaluate("2m 3m 4m 2p 3p 4p 2s 3s 5p 6p 7p 1z 1z")
        a,b=find(p,"1s","ron"),find(p,"4s","ron")
        self.assertLess(a["han"],b["han"])
        self.assertEqual(b["yaku"]["三色同順"],2)
        self.assertTrue(ok)
    def test_chiitoitsu(self):
        _,p,_=evaluate("1m 1m 2m 2m 3p 3p 4p 4p 6s 6s 7s 7s 5z")
        r=find(p,"5z","ron")
        self.assertEqual(r["fu"],25);self.assertEqual(r["yaku"]["七対子"],2)
    def test_yakuman(self):
        _,p,ok=evaluate("1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z")
        self.assertTrue(ok);self.assertTrue(find(p,"1m","ron")["yakuman"])
    def test_furiten(self):
        _,p,ok=evaluate("2m 3m 4m 3p 4p 5p 4s 5s 6s 2p 2p 6s 7s",furiten=True)
        self.assertTrue(ok);self.assertFalse(find(p,"8s","ron")["eligible"])
        self.assertTrue(find(p,"8s","tsumo")["eligible"])
    def test_no_yaku_open(self):
        _,p,ok=evaluate("4p 5p 6p 7s 8s 9s 2z 2z 2s 3s",[("chi",hand("1m 2m 3m"))],["1z","1s","2s"])
        self.assertFalse(ok);self.assertTrue(all(x["status"]=="hand calculator: no_yaku" for x in p))
    def test_pre_draw(self):
        h=hand("2m 3m 4m 3p 4p 5p 4s 5s 6s 2p 2p 6s 7s")
        self.assertTrue(candidates(h,[]))
        with self.assertRaises(ValueError):candidates(h+["8s"],[])
class TransitionTests(unittest.TestCase):
    def test_kan_new_tenpai_and_discard_furiten(self):
        p=47; rp=Replay()
        rp.last_action=("ankan",p,"1p")
        rp.last_draw[p]=dict(event_order=20)
        rp.trace=[dict(type="discard",actor=p,tile="3m",event_order=10),
                  dict(type="draw",actor=p,event_order=20),
                  dict(type="ankan",actor=p,event_order=21),
                  dict(type="dora_indicator",event_order=22)]
        state=dict(shanten_count=1,event_order=10); ev=dict(rinshan=1,event_order=23)
        h=hand("2m 8m 6p 6p 6m 3m 7m 4m 3m 1m")
        m=[("ankan",hand("1p 1p 1p 1p"))]
        self.assertTrue(kan_transition(rp,ev,p,state))
        w=candidates(h,m);self.assertTrue(w)
        self.assertEqual(new_kan_furiten(rp,ev,p,state,h,m), "3m" in w)
        rp.trace[0]["tile"]=w[0];self.assertTrue(new_kan_furiten(rp,ev,p,state,h,m))
        rp.trace[0]["tile"]="7z";self.assertFalse(new_kan_furiten(rp,ev,p,state,h,m))
        rp.reaches.add(p)
        with self.assertRaises(ValueError):new_kan_furiten(rp,ev,p,state,h,m)
    def test_kan_stale_and_intervening(self):
        rp=Replay();rp.last_action=("ankan",15,"5s")
        rp.trace=[dict(type="ankan",actor=15,event_order=21),dict(type="dora_indicator",event_order=22)]
        self.assertTrue(kan_transition(rp,dict(rinshan=1),15,dict(shanten_count=0,event_order=10)))
        self.assertFalse(kan_transition(rp,dict(rinshan=0),15,dict(shanten_count=0,event_order=10)))
        self.assertFalse(kan_transition(rp,dict(rinshan=1),15,dict(shanten_count=0,event_order=21)))
        rp.trace.append(dict(type="discard",actor=99,event_order=23))
        self.assertFalse(kan_transition(rp,dict(rinshan=1),15,dict(shanten_count=0,event_order=10)))
    def test_fifth_tile_impossible(self):
        h=hand("8m 9m 7p 9p 8p 7s 7m")
        m=[("chi",hand("0s 3s 4s")),("pon",hand("7s 7s 7s"))]
        self.assertTrue(no_physical_wait(h,m));self.assertFalse(candidates(h,m))
        self.assertFalse(no_physical_wait(h,[m[0],("pon",hand("6s 6s 6s"))]))
    def test_invalid_count_not_fabricated(self):
        for n in (12,14):
            with self.assertRaises(ValueError):candidates(["1m"]*n,[])
if __name__=="__main__":unittest.main(verbosity=2)
