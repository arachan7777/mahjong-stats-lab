"""Supplemental concrete four-player and kan event fixtures, Stage 7 only."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from dontsuka_v026_7_core import Inventory,History,Linker,hand_state,movement,disposition
from dontsuka_v026_6_core import state
class Game:
    def __init__(self,hands):
        self.r=Inventory();self.h=History();self.l=Linker();self.i=0
        for p,tiles in hands.items():self.ev("haipai",p,hand=",".join(tiles.split()))
    def ev(self,k,p=None,**kw):
        self.i+=1;e=dict(id=self.i,event_order=self.i,type=k,actor=p,wall=40,rinshan=False,declaration=False);e.update(kw)
        res=self.l.feed(e)
        if k not in ("ron","tsumo","ryukyoku"):self.r.step(e);self.h.record(e)
        return e,res
    def draw(self,p,t,rinshan=False):return self.ev("draw",p,tile=t,rinshan=rinshan)
    def discard(self,p,t,decl=False):return self.ev("discard",p,tile=t,declaration=decl)
    def reach(self,p,t):
        d,_=self.draw(p,t);self.ev("reach",p,accepted=True)
        e,res=self.discard(p,t,True);assert res[0][0]["id"]==d["id"]
        return e

class FullEventTests(unittest.TestCase):
    def test_multiple_origins_and_target_specific_genbutsu(self):
        for waits,tile,n in [(("9s","8s","7s"),"5z",0),(("9s","8s","7s"),"9s",1),(("9s","9s","7s"),"9s",2),(("9s","9s","9s"),"9s",3)]:
            base="1m 2m 3m 4m 5m 6m 1p 2p 3p 4p 5p 6p "
            g=Game({1:"7m 8m 9m 7p 8p 9p 1s 2s 3s 4s 5s 1z 6z",**{p:base+t for p,t in zip((2,3,4),waits)}})
            dec2=g.reach(2,"6z");g.reach(3,"2z");g.reach(4,"3z")
            self.assertTrue(all(state(g.r,p)[:2]==("riichi",(w,)) for p,w in zip((2,3,4),waits)))
            pre=hand_state(g.r,1,13)
            hits=[p for p in (2,3,4) if tile in state(g.r,p)[1]]
            d,_=g.draw(1,tile);self.assertEqual(len(hits),n)
            prospective=dict(id=g.i+1,event_order=g.i+1,type="discard",actor=1,tile="6z")
            values={p:g.h.genbutsu(p,prospective)[0] for p in (2,3,4)}
            self.assertEqual(values,{2:1,3:0,4:0})
            self.assertEqual(g.h.genbutsu(2,prospective)[2],dec2["id"])
            e,res=g.discard(1,"6z");self.assertEqual(res[0][0]["id"],d["id"])
            post=hand_state(g.r,1,13);self.assertNotEqual(movement(pre,post)[1],"not_applicable")
            self.assertEqual((int(bool(hits)),len(hits)),(int(n>0),n));g.l.finish()
    def test_actual_ankan_rinshan_events(self):
        g=Game({1:"1m 1m 1m 2m 3m 4m 1p 2p 3p 1s 2s 3s 1z"})
        a,_=g.draw(1,"1m");g.ev("ankan",1,tile="1m",block="1111m")
        self.assertEqual(hand_state(g.r,1,13)["effective"],13)
        g.ev("dora_indicator",tile="9p",dora_type="omote")
        b,res=g.draw(1,"2z",True);self.assertEqual((res[0][0]["id"],res[0][1]),(a["id"],"kan_before_rinshan"))
        e,res=g.discard(1,"2z");self.assertEqual(res[0][0]["id"],b["id"]);g.l.finish()
    def added_kan(self,terminal):
        g=Game({1:"5p 5p 1m 2m 3m 4m 5m 6m 1s 2s 3s 1z 2z",2:"0p 7m 8m 9m 7p 8p 9p 4s 5s 6s 3z 4z 5z"})
        g.draw(2,"6z");d,_=g.discard(2,"0p");g.ev("pon",1,tile="0p",block="505p",target=2)
        self.assertEqual(g.r.rivers["5p"],0)
        self.assertEqual(g.h.genbutsu(2,dict(event_order=g.i+1,tile="5p"))[:3],(1,"target_own_discard",d["id"]))
        g.discard(1,"2z");a,_=g.draw(1,"5p");g.ev("shominkan",1,tile="5p",block="5055p")
        self.assertEqual(hand_state(g.r,1,13)["effective"],13)
        if terminal:
            e,res=g.ev("ron");self.assertEqual((res[0][0]["id"],res[0][1]),(a["id"],"kan_robbed"))
        else:
            b,res=g.draw(1,"7z",True);self.assertEqual((res[0][0]["id"],res[0][1]),(a["id"],"kan_before_rinshan"))
            e,res=g.discard(1,"7z");self.assertEqual(res[0][0]["id"],b["id"])
        g.l.finish()
    def test_actual_added_kan_rinshan_and_robbed(self):
        self.added_kan(False);self.added_kan(True)
    def test_actual_daiminkan_and_rinshan(self):
        g=Game({1:"7s 7s 7s 1m 2m 3m 4m 5m 6m 1p 2p 3p 1z",2:"7s 7m 8m 9m 7p 8p 9p 4s 5s 6s 3z 4z 5z"})
        a,_=g.draw(2,"6z");d,res=g.discard(2,"7s");self.assertEqual(res[0][0]["id"],a["id"])
        _,res=g.ev("daiminkan",1,tile="7s",block="7777s",target=2);self.assertFalse(res)
        b,res=g.draw(1,"7z",True);self.assertFalse(res)
        e,res=g.discard(1,"7z");self.assertEqual(res[0][0]["id"],b["id"]);g.l.finish()
    def test_real_tsumo_win_and_riichi_discard(self):
        g=Game({1:"1m 2m 3m 1p 2p 3p 1s 2s 3s 1z 1z 4m 5m"})
        d=g.reach(1,"9p");self.assertEqual(disposition(d,True,False),"reach_declaration")
        a,_=g.draw(1,"9s");self.assertIn(1,g.h.established)
        e,res=g.discard(1,"9s");self.assertEqual(disposition(e,True,True),"accepted_reach_tsumogiri")
        self.assertEqual(res[0][0]["id"],a["id"])
        b,_=g.draw(1,"6m");self.assertEqual(hand_state(g.r,1,14)["shanten"],-1)
        e,res=g.ev("tsumo");self.assertEqual((res[0][0]["id"],res[0][1]),(b["id"],"tsumo_win"));g.l.finish()
if __name__=="__main__":unittest.main(verbosity=2)
