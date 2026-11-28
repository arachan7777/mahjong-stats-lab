"""Artificial event fixtures for stage 7; no production DB."""
import unittest,random
from collections import Counter
from dontsuka_v026_7_core import Inventory,History,Linker,hand_state,movement,disposition
from dontsuka_v026_5a_core import sh,vector,TYPES

def e(i,k,p=1,**kw):
    return dict(id=i,event_order=i,type=k,actor=p,wall=40,rinshan=False,declaration=False,**kw)
def initial(h):
    r=Inventory();r.step(e(1,"haipai",hand=",".join(h)));return r
def transition(h,draw,discard):
    r=initial(h);a=hand_state(r,1,13);r.step(e(2,"draw",tile=draw));during=hand_state(r,1,14)
    r.step(e(3,"discard",tile=discard));b=hand_state(r,1,13)
    return a,during,b,movement(a,b)
class Tests(unittest.TestCase):
    def test_transitions(self):
        h="1m 2m 3m 1p 2p 3p 1s 2s 3s 1z 1z 4m 5m".split()
        i=h[:-1]+["9m"]
        fixtures=[(h,"9p","9p",0,0,"tenpai_maintained"),(h,"9p","1m",0,1,"tenpai_broken"),(i,"5m","9m",1,0,"progress"),(i,"9p","9p",1,1,"maintained"),(i,"9p","1m",1,2,"regress")]
        for tiles,d,t,x,y,label in fixtures:
            a,m,b,cl=transition(tiles,d,t)
            self.assertEqual((a["shanten"],b["shanten"],cl[1]),(x,y,label),(tiles,d,t,a,b))
        # Concrete two-to-three fixture is selected deterministically and printed.
        rng=random.Random(7);deck=list(TYPES)*4
        for _ in range(10000):
            hh=rng.sample(deck,13)
            if sh(vector(hh))!=2:continue
            d=next(t for t in TYPES if Counter(hh)[t]<4 and t not in hh)
            for t in set(hh):
                final=hh+[d];final.remove(t)
                if sh(vector(final))==3:
                    a,m,b,cl=transition(hh,d,t);self.assertEqual((a["shanten"],b["shanten"],cl[1]),(2,3,"regress"));print("2 to 3 fixture",hh,d,t);return
        self.fail("two-to-three fixture missing")
    def test_special_shapes(self):
        seven="1m 1m 3m 3m 5m 5m 1p 1p 3p 3p 1z 1z 7z".split()
        kokushi="1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z".split()
        for h in (seven,kokushi):
            r=initial(h);self.assertEqual(hand_state(r,1,13)["state"],"damaten")
            r.reaches.add(1);self.assertEqual(hand_state(r,1,13)["state"],"riichi")
        h="1m 2m 3m 1p 2p 3p 1s 2s 3s 1z 1z 4m 5m".split()
        r=initial(h);r.hands[1]=h[3:];r.melds[1]=[("chi",h[:3])];self.assertEqual(hand_state(r,1,13)["state"],"open")
        r=initial(h[:-1]);self.assertEqual(hand_state(r,1,13)["reason"],"few_tiles")
        r=initial(h+["9p"]);self.assertEqual(hand_state(r,1,13)["reason"],"many_tiles")
        a,m,b,cl=transition(h,"6m","6m");self.assertEqual((m["shanten"],a["shanten"],b["shanten"]),(-1,0,0))
    def test_fifth_copy(self):
        r=initial("1m 2m 3m 1p 2p 3p 4p 5p 6p 6s".split());r.melds[1]=[("pon",["6s"]*3)]
        a=hand_state(r,1,13);self.assertEqual((a["shanten"],a["state"],a["reason"]),(0,"not_tenpai","structural_no_physical_wait"));self.assertEqual(movement(a,a)[1],"not_applicable")
    def test_history(self):
        h=History()
        h.record(e(1,"discard",2,tile="0m"))
        h.record(e(2,"discard",3,tile="1p"))
        h.record(e(3,"reach",2,accepted=True))
        self.assertEqual(h.genbutsu(2,e(4,"discard",1,tile="1p"))[0],0)
        d=e(4,"discard",2,tile="2z");d["declaration"]=True;h.record(d)
        self.assertEqual(h.genbutsu(2,e(5,"discard",1,tile="5m"))[:3],(1,"target_own_discard",1))
        self.assertEqual(h.genbutsu(2,e(5,"discard",1,tile="1p"))[0],0)
        h.record(e(5,"discard",3,tile="1p"));h.record(e(6,"pon",4,tile="1p"))
        self.assertEqual(h.genbutsu(2,e(7,"discard",1,tile="1p"))[:3],(1,"passed_after_accepted_reach",5))
        self.assertEqual(h.genbutsu(4,e(7,"discard",1,tile="1p"))[0],0)
        h.record(e(8,"discard",1,tile="3p"));self.assertEqual(h.genbutsu(2,e(9,"discard",1,tile="3p"))[0],1)
        self.assertEqual(h.genbutsu(2,e(7,"discard",1,tile="3p"))[0],0)
    def test_links(self):
        for k in ("ankan","shominkan"):
            l=Linker();l.feed(e(1,"draw"));l.feed(e(2,k));l.feed(e(3,"dora_indicator"))
            r=e(4,"draw");r["rinshan"]=True
            self.assertEqual(l.feed(r)[0][1],"kan_before_rinshan")
            self.assertEqual(l.feed(e(5,"discard"))[0][0]["id"],4);l.finish()
            l=Linker();l.feed(e(1,"draw"));l.feed(e(2,k));self.assertEqual(l.feed(e(3,"ron"))[0][1],"kan_robbed");l.finish()
        l=Linker();l.feed(e(1,"daiminkan"));r=e(2,"draw");r["rinshan"]=True;l.feed(r);self.assertEqual(l.feed(e(3,"discard"))[0][0]["id"],2);l.finish()
        l=Linker();l.feed(e(1,"draw"));self.assertEqual(l.feed(e(2,"tsumo"))[0][1],"tsumo_win");l.finish()
        l=Linker();l.feed(e(1,"draw"));l.feed(e(2,"reach",accepted=True));d=e(3,"discard");d["declaration"]=True;self.assertEqual(l.feed(d)[0][0]["id"],1);l.finish()
        self.assertEqual(disposition(d,True,False),"reach_declaration")
        self.assertEqual(disposition(e(4,"discard"),True,True),"accepted_reach_tsumogiri")
        self.assertEqual(disposition(e(4,"discard"),True,False),"tsumogiri")
        self.assertEqual(disposition(e(4,"discard"),False,False),"tedashi")
    def test_denominators_and_keys(self):
        from dontsuka_v026_7 import pct
        ids=[1,2,3,4]
        hits={2:[2],3:[2,3],4:[2,3,4]}
        keys={(e,t) for e,ts in hits.items() for t in ts}
        self.assertEqual((len(ids),len(hits),len(keys)),(4,3,6))
        self.assertEqual(pct(0,0),"");self.assertEqual(pct(3,4),"75.000000000")
if __name__=="__main__":unittest.main(verbosity=2)
