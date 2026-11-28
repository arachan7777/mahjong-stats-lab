"""Concrete one-shanten fixtures plus exact reference progression comparison."""
import unittest
from dontsuka_v026_5b_core import classify,progressions,physical_draws,scoring
from dontsuka_v026_5a_core import sh,vector,qualifies
from dontsuka_v026_2a_audit import score

def h(s):return s.split()
def fixture(s,m=()):
    target=h(s)
    # Remove an exact tile from a known concrete tenpai and add an honor.
    # Assert the resulting pre-draw state really is one-shanten.
    for t in sorted(set(target)):
        for junk in ("7z","6z","5z","4z","3z","2z","1z"):
            if junk in target or any(junk in b for _,b in m):continue
            before=target.copy();before.remove(t);before.append(junk)
            if sh(vector(before))==1 and t in physical_draws(before,list(m)):
                return before,t,junk
    raise AssertionError("no concrete fixture")
def compare(before,m=(),om=(),discards=()):
    a=list(progressions(before,list(m)));b=list(progressions(before,list(m),True))
    assert a==b,(before,m,a,b)
    x=classify(before,list(m),"2z","1z",om,discards)
    y=classify(before,list(m),"2z","1z",om,discards,True)
    assert x==y,(x,y)
    return x,a

class Tests(unittest.TestCase):
    def check_target(self,s,m=(),om=(),tile=None,method=None,expected=None):
        before,t,d=fixture(s,m)
        x,options=compare(before,m,om)
        row=next(r for r in options if r[:2]==(t,d))
        self.assertEqual(row[2],tuple(sorted(h(s))))
        _,p,_=scoring(row[2],tuple((k,tuple(sorted(b))) for k,b in m),"2z","1z",tuple(om))
        if tile:
            v=next(r for r in p if r["tile"]==tile and r["method"]==method)
            self.assertEqual(v["status"],"evaluated")
            if expected:expected(v)
        return x,options,p
    def test_normal_multiple_and_pre_draw(self):
        x,a,p=self.check_target("2m 3m 4m 3p 4p 5p 4s 5s 6s 2p 2p 6s 7s",tile="8s",method="tsumo",expected=lambda r:self.assertEqual((r["han"],r["fu"],r["qualifies"]),(4,20,True)))
        self.assertGreater(len(a),1);self.assertTrue(x["is_shoubute"])
        ron=next(r for r in p if r["tile"]=="8s" and r["method"]=="ron")
        self.assertEqual((ron["han"],ron["fu"],ron["qualifies"]),(3,30,False))
        self.assertTrue(ron["virtual_riichi"])
    def test_chiitoitsu(self):
        x,a,p=self.check_target("1m 1m 2m 2m 3p 3p 4p 4p 6s 6s 7s 7s 5z",om=("6z",),tile="5z",method="tsumo",expected=lambda r:self.assertEqual(r["yaku"]["七対子"],2))
        self.assertTrue(x["is_shoubute"])
    def test_kokushi(self):
        before=h("1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 2m")
        x,a=compare(before);self.assertTrue(x["is_shoubute"])
        self.assertTrue(any(r[0]=="7z" and r[1]=="2m" for r in a))
        self.assertTrue(x["witness"]["pattern"]["yakuman"])
    def test_sanshoku_high_low(self):
        x,a,p=self.check_target("2m 3m 4m 2p 3p 4p 2s 3s 5p 6p 7p 1z 1z",tile="4s",method="ron",expected=lambda r:self.assertEqual(r["yaku"]["三色同順"],2))
        a1,b1=[next(r for r in p if r["tile"]==t and r["method"]=="ron") for t in ("1s","4s")]
        self.assertLess(a1["han"],b1["han"]);self.assertTrue(x["is_shoubute"])
    def test_open_red_kan_dora(self):
        x,a,p=self.check_target("3p 4p 5p 4s 5s 6s 2p 2p 6s 7s",[("chi",h("2m 3m 4m"))],["1p","4s"],"0s","tsumo",lambda r:self.assertEqual((r["yaku"]["赤ドラ"],r["yaku"]["ドラ"],r["virtual_riichi"]),(1,4,False)))
        self.assertTrue(x["is_shoubute"])
    def test_kan_kiriage(self):
        x,a,p=self.check_target("9p 9p 9p 5z 5z 7z 7z 2s 3s 4s",[("ankan",h("2m 2m 2m 2m"))],["1s"],"7z","ron",lambda r:self.assertEqual((r["han"],r["fu"],r["points"]),(3,60,8000)))
        self.assertTrue(x["is_shoubute"])
    def test_fifth_red_and_invalid(self):
        m=[("ankan",h("5m 5m 5m 0m"))]
        before=h("1m 2m 3m 4p 5p 6p 7s 8s 1z 2z")
        draws=set(physical_draws(before,m));self.assertNotIn("5m",draws);self.assertNotIn("0m",draws)
        for n in (12,14):
            with self.assertRaises(ValueError):list(progressions(["1m"]*n,[]))
    def test_furiten_and_future_invariance(self):
        before,t,d=fixture("2m 3m 4m 3p 4p 5p 4s 5s 6s 2p 2p 6s 7s")
        x,a=compare(before,discards=("8s",))
        self.assertTrue(x["is_shoubute"])
        # Actual future draws are intentionally not accepted by the API.
        self.assertEqual(x,classify(before,[],"2z","1z",(),("8s",)))
    def test_or_boundaries(self):
        for han,fu,ok in [(3,30,False),(3,60,True),(3,70,True),(4,20,True),(4,30,True)]:
            self.assertEqual(qualifies(dict(han=han,fu=fu,points=score(han,fu,False,False),yakuman=False),False),ok)
    def test_reference_sample(self):
        # Additional deterministic concrete states with physical inventory.
        for s in ("1m 2m 3m 1p 2p 4p 4s 5s 6s 7s 8s 1z 1z","2m 2m 3m 4m 5m 4p 5p 6p 6s 7s 8s 8z 8z".replace("8z","7z"),"1m 1m 2m 2m 3p 3p 4p 4p 6s 6s 7s 5z 2z"):
            before=h(s)
            if sh(vector(before))==1:compare(before)
if __name__=="__main__":unittest.main(verbosity=2)
