"""Stage 6 artificial tests; no DB needed."""
import unittest,itertools
from collections import Counter
from dontsuka_v026_6_core import Inventory,state,compare,pairs,counts,remaining,sign

def ev(r,k,p=None,**kw):
    e=dict(id=len(r.trace)+1,event_order=len(r.trace)+1,type=k,actor=p,
           declaration=False,rinshan=False,wall=30,**kw)
    r.step(e)

def initial(r,p,tiles):ev(r,"haipai",p,hand=",".join(tiles))
def discard(r,p,t):ev(r,"discard",p,tile=t)
def call(r,k,p,t,b,target=None):ev(r,k,p,tile=t,block=b,target=target)
def snap(r):return r.snapshot()

class TestWaitComparison(unittest.TestCase):
    def test_nine_categories(self):
        # Two distinct waits. Others' concealed holdings alter the wall but
        # do not alter the respective observer's public/own inventory.
        observed=set()
        for va,vb,ya,yb in itertools.product(range(5),repeat=4):
            if ya>va or yb>vb:continue
            pub=Counter({"1m":4-va,"2m":4-vb})
            priv={1:Counter(),2:Counter(),3:Counter({"1m":va-ya,"2m":vb-yb}),4:Counter()}
            known=pub+priv[3]
            d=compare(1,2,pub,priv,known,["1m"],["2m"])
            self.assertEqual((d["self_visible"],d["target_visible"],d["self_wall"],d["target_wall"]),(va,vb,ya,yb))
            self.assertEqual(d["visible_diff"],va-vb)
            self.assertEqual(d["wall_diff"],ya-yb)
            observed.add(d["combined"])
        self.assertEqual(len(observed),9)
        self.assertIn("advantage_disadvantage",observed)
        self.assertIn("disadvantage_advantage",observed)
    def test_same_wait_different_perspective(self):
        p=Counter({"5m":1});h={1:counts(["0m","5m"]),2:Counter(),3:counts(["5m"]),4:Counter()}
        d=compare(1,2,p,h,p+h[1]+h[3],["0m","5m"],["5m"])
        self.assertEqual((d["self_visible"],d["target_visible"],d["self_wall"],d["target_wall"]),(1,3,0,0))
        self.assertEqual(d["combined"],"disadvantage_equal")
    def test_multiple_wait_red_zero_and_wall(self):
        self.assertEqual(remaining(["0p","5p","6p"],counts(["0p","5p","5p","5p","6p"])),3)
        self.assertEqual(remaining(["1s"],counts(["1s"]*4)),0)
        # Unobserved 1s could be in the dead wall; no future assignment.
        self.assertEqual(remaining(["1s"],counts(["1s"]*3)),1)
    def test_calls(self):
        for k,t,own,block in [("chi","3m",["1m","2m"],"123m"),("pon","5p",["0p","5p"],"505p"),("daiminkan","7s",["7s"]*3,"7777s")]:
            r=Inventory();initial(r,1,[t]);initial(r,2,own);discard(r,1,t)
            self.assertEqual(snap(r)[0][t],1)
            call(r,k,2,t,block,1)
            public,priv,known=snap(r)
            self.assertEqual(r.rivers[t],0)
            self.assertEqual(sum(public.values()),len(own)+1)
            self.assertEqual(known,counts([t]+own))
    def test_ankan_and_added_kan_and_dora(self):
        r=Inventory();initial(r,1,["0m","5m","5m","5m"])
        call(r,"ankan",1,"5m","_5m5m_")
        self.assertEqual(snap(r)[0]["5m"],4)
        ev(r,"dora_indicator",tile="3m",dora_type="omote")
        self.assertEqual(snap(r)[0]["3m"],1)
        ev(r,"dora_indicator",tile="9s",dora_type="ura")
        self.assertEqual(snap(r)[0]["9s"],0)
        r=Inventory();initial(r,1,["5p"]);initial(r,2,["0p","5p"]);discard(r,1,"5p");call(r,"pon",2,"5p","505p",1)
        ev(r,"draw",2,tile="5p");call(r,"shominkan",2,"5p","5055p")
        self.assertEqual(snap(r)[0]["5p"],4)
        self.assertEqual(r.rivers["5p"],0)
    def test_tenpai_status_and_timing(self):
        r=Inventory();h="1m 2m 3m 1p 2p 3p 1s 2s 3s 1z 1z 4m 5m".split()
        initial(r,1,h)
        self.assertEqual(state(r,1)[:2],("damaten",("3m","6m")))
        r.reaches.add(1);self.assertEqual(state(r,1)[0],"riichi")
        r.reaches.clear();r.hands[1]=h[3:];r.melds[1]=[("chi",h[:3])]
        self.assertEqual(state(r,1)[0],"open")
        r.hands[1]=h[:-1];r.melds[1]=[]
        self.assertEqual(state(r,1)[0],"unknown")
        # This is a completed hand only after a draw. It cannot affect its own
        # pre-draw comparison; the 14-effective state is not a pre-draw state.
        r=Inventory();initial(r,1,h)
        before=state(r,1);ev(r,"draw",1,tile="6m")
        self.assertEqual(before[0],"damaten")
        self.assertEqual(state(r,1)[0],"unknown")
    def test_non_tenpai_draw_not_retroactive(self):
        r=Inventory();h="1m 2m 3m 1p 2p 3p 1s 2s 3s 1z 1z 4m 9m".split()
        initial(r,1,h);self.assertEqual(state(r,1)[0],"not_tenpai")
        ev(r,"draw",1,tile="5m");discard(r,1,"9m")
        self.assertEqual(state(r,1)[0],"damaten")
    def test_pair_denominators_and_fouls(self):
        st={p:("damaten",("1m",),13) for p in range(1,5)}
        pp=list(pairs(st,1,[2,3,4]));self.assertEqual(len(pp),3)
        for origins in [set(),{2},{2,3},{2,3,4}]:
            self.assertEqual(sum(t in origins for t,ok in pp),len(origins))
            self.assertEqual(sum(ok for t,ok in pp),3)
        st[2]=("unknown",(),12);st[3]=("not_tenpai",(),13)
        self.assertEqual(list(pairs(st,1,[2,3,4])),[(2,False),(4,True)])
        st[1]=("unknown",(),14)
        self.assertEqual(list(pairs(st,1,[2,3,4])),[(2,False),(4,False)])
if __name__=="__main__":unittest.main(verbosity=2)
