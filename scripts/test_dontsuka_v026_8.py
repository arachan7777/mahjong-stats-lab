"""Stage 8 artificial physical-hand / event tests (no production DB)."""
import unittest
from itertools import product
from dontsuka_v026_8_core import RoundTracker, Interval, relation, rate, TENPAI
from dontsuka_v026_6_core import Inventory, state, remaining
from dontsuka_v026_7_core import History
from dontsuka_v026_8 import conditions

H1="1m 2m 3m 1p 2p 3p 1s 2s 3s 1z 1z 4m 5m".split()
H2="7m 8m 9m 7p 8p 9p 7s 8s 9s 2z 2z 4p 5p".split()
H3="1m 2m 4m 6m 8m 1p 3p 5p 8p 1s 4s 6s 3z".split()
H4="1m 3m 5m 7m 9m 2p 4p 6p 9p 2s 5s 7s 4z".split()

class Fixture:
    def __init__(self,h1=H1,h2=H2,h3=H3,h4=H4):
        self.r=RoundTracker(101);self.n=0
        for p,h in enumerate((h1,h2,h3,h4),1):
            self.e("haipai",p,hand=",".join(h))
    def e(self,k,p=None,hits=(),**extra):
        self.n+=1
        x=dict(id=self.n,event_order=self.n,type=k,actor=p,wall=40,rinshan=False,declaration=False)
        x.update(extra);return self.r.feed(x,hits)
    def draw(self,p,t,hits=()):return self.e("draw",p,hits=hits,tile=t)
    def discard(self,p,t,decl=False):self.e("discard",p,tile=t,declaration=decl)
    def reach(self,p,t,accepted=True):
        self.e("reach",p,accepted=accepted);self.discard(p,t,True)
    def pair(self,p,t):
        return next(x for x in p["pairs"] if x["target_id"]==t)
    def close(self):self.e("ryukyoku");return self.r.finish()

class Tests(unittest.TestCase):
    def test_initial_simultaneous(self):
        f=Fixture();a=f.r.active[1];b=f.r.active[2]
        self.assertNotEqual(a.start_event_id,b.start_event_id)
        self.assertEqual(relation(a,b),"simultaneous")
        d=f.draw(1,"6p",(2,));p=f.pair(d,2)
        self.assertEqual(p["relation"],"simultaneous")
        self.assertEqual(p["combination"],"")
        self.assertEqual(d["interval_draw_number"],1)
        f.discard(1,"6p");f.close()
    def test_reach_independent_and_chase(self):
        h2=H2[:-1]+["1m"];f=Fixture(H1,h2)
        self.assertEqual(state(f.r.replay,2)[0],"not_tenpai")
        a=f.r.active[1].key
        f.draw(2,"5p");f.reach(2,"1m")
        b=f.r.active[2]
        self.assertEqual(f.r.first_reach["player_id"],2)
        d=f.draw(1,"9p")
        self.assertEqual(f.pair(d,2)["relation"],"self_earlier")
        self.assertEqual(f.pair(d,2)["combination"],"self_earlier:damaten:riichi")
        f.reach(1,"9p");self.assertEqual(f.r.active[1].key,a)
        d=f.draw(2,"6m",(1,));p=f.pair(d,1)
        self.assertEqual(p["relation"],"self_later")
        self.assertEqual(p["first_reach_class"],"chase_riichi")
        self.assertEqual(p["combination"],"self_later:riichi:riichi")
        self.assertEqual(p["target_info"]["interval_id"],a)
        self.assertEqual(p["self_info"]["interval_id"],b.key)
        f.discard(2,"6m");f.close()
    def test_first_reach_earlier_tenpai(self):
        f=Fixture(H1,H2[:-1]+["1m"])
        a=f.r.active[1].key
        f.draw(1,"9p");f.reach(1,"9p")
        f.draw(2,"5p");f.discard(2,"1m")
        d=f.draw(1,"6p",(2,));p=f.pair(d,2)
        self.assertEqual(p["first_reach_class"],"later_damaten")
        self.assertEqual(p["relation"],"self_earlier")
        self.assertEqual(p["target_at_first_reach"]["state"],"not_tenpai")
        self.assertEqual(f.r.active[1].key,a)
        f.discard(1,"6p");f.close()
    def test_prior_damaten(self):
        f=Fixture();f.draw(1,"9p");f.reach(1,"9p")
        d=f.draw(1,"7z");p=f.pair(d,2)
        self.assertEqual(p["first_reach_class"],"prior_damaten")
        self.assertEqual(p["target_at_first_reach"]["state"],"damaten")
        self.assertEqual(p["is_opponent_dontsuka"],0)
        self.assertIn("prior_damaten",conditions(p))
        f.discard(1,"7z");f.close()
    def test_temporary_fourteen_and_wait_change(self):
        f=Fixture();a=f.r.active[1]
        f.draw(1,"6m")
        self.assertIs(f.r.active[1],a)
        f.discard(1,"4m")
        self.assertIs(f.r.active[1],a)
        self.assertNotEqual(a.states[0]["waits"],a.states[-1]["waits"])
        d=f.draw(1,"9p");self.assertEqual(d["interval_draw_number"],2)
        f.discard(1,"1m")
        self.assertNotIn(1,f.r.active);self.assertEqual(a.end_reason,"tenpai_broken")
        f.draw(1,"1m");f.discard(1,"9p")
        self.assertIn(1,f.r.active);self.assertNotEqual(f.r.active[1].key,a.key)
        d=f.draw(1,"9p");self.assertEqual(d["interval_draw_number"],1)
        f.discard(1,"9p");f.close()
    def test_call_maintenance_and_prior_open(self):
        f=Fixture();a=f.r.active[1]
        f.draw(2,"1z");f.discard(2,"1z")
        f.e("pon",1,target=2,tile="1z",block="1z1z1z")
        self.assertIs(f.r.active[1],a)
        f.discard(1,"4m");self.assertIs(f.r.active[1],a)
        self.assertEqual(a.states[-1]["state"],"open")
        f.draw(2,"9p");f.reach(2,"9p")
        d=f.draw(2,"5m",(1,));p=f.pair(d,1)
        self.assertEqual(p["first_reach_class"],"prior_open")
        f.discard(2,"5m");f.close()
    def test_call_later_open(self):
        f=Fixture(H1[:-1]+["9m"])
        f.draw(2,"9p");f.reach(2,"9p")
        f.draw(3,"1z");f.discard(3,"1z")
        f.e("pon",1,target=3,tile="1z",block="1z1z1z")
        f.discard(1,"4m")
        d=f.draw(2,"9m",(1,));p=f.pair(d,1)
        self.assertEqual(p["first_reach_class"],"later_open")
        f.discard(2,"9m");f.close()
    def test_kan(self):
        h="1m 1m 1m 1p 2p 3p 1s 2s 3s 1z 1z 4m 5m".split()
        f=Fixture(h,H2,["6z" if t=="1m" else t for t in H3],["7z" if t=="1m" else t for t in H4]);a=f.r.active[1]
        f.draw(1,"1m");f.e("ankan",1,tile="1m",block="1m1m1m1m")
        self.assertIs(f.r.active[1],a)
        d=f.e("draw",1,tile="9p",rinshan=True)
        self.assertEqual(d["interval_draw_number"],2)
        f.discard(1,"9p");f.close()
        h="3m 4m 5m 4m 5m 6m 5m 6m 7m 1p 2p 5z 5z".split()
        f=Fixture(h,H2,H3,["7z" if t=="5m" else t for t in H4]);a=f.r.active[1]
        f.draw(1,"5m");f.e("ankan",1,tile="5m",block="5m5m5m5m")
        self.assertNotIn(1,f.r.active);self.assertEqual(a.end_reason,"tenpai_broken")
        f.close()
    def test_unaccepted_reach_and_future(self):
        f=Fixture();d=f.draw(1,"9p");f.reach(1,"9p",False)
        self.assertIsNone(f.r.first_reach)
        self.assertEqual(f.r.reach_records[0]["accepted"],0)
        self.assertEqual(f.r.active[1].states[-1]["state"],"damaten")
        self.assertTrue(all(not x["self_first_reach"] for x in d["pairs"]))
        f.close()
    def test_first_hits_multiple_no_hit_and_zero(self):
        h3="4m 5m 6m 4s 5s 6s 2m 3m 4m 5m 5m 4p 5p".split()
        h4="2m 3m 4m 2s 3s 4s 6m 7m 8m 6s 6s 4p 7z".split()
        f=Fixture(H1,H2,h3,h4);a=f.r.active[1]
        d=f.draw(1,"9p");self.assertEqual(d["first_hit"],0);f.discard(1,"9p")
        d=f.draw(1,"3p",(2,3));self.assertEqual((d["first_hit"],d["interval_draw_number"],d["opponent_count"]),(1,2,2));f.discard(1,"3p")
        f.draw(2,"9s");f.discard(2,"9s")
        f.draw(3,"8s");f.discard(3,"8s")
        f.draw(4,"5p");f.discard(4,"7z")
        d=f.draw(1,"3p",(2,3,4));self.assertEqual((d["first_hit"],d["opponent_count"]),(0,3))
        self.assertEqual([p["target_id"] for p in d["pairs"] if p["first_target_hit"]],[4])
        f.discard(1,"3p");rr=f.close()
        self.assertEqual(a.first_hit_draw_number,2)
        self.assertEqual(a.first_target_hits[4]["draw_number"],3)
        self.assertIsNone(next(x for x in rr if x["player_id"]==2)["first_hit_draw_number"])
        self.assertEqual(rate(0,0),"")
        self.assertEqual(rate(0,1),"0.000000000")
    def test_physical_wait_and_pure_zero(self):
        f=Fixture();_,waits,_=state(f.r.replay,1)
        known={t:4 for t in waits}
        self.assertEqual(remaining(waits,known),0)
        self.assertIn(state(f.r.replay,1)[0],TENPAI)
        r=Inventory()
        r.hands[1]="1m 2m 3m 1p 2p 3p 4p 5p 6p 6s".split()
        r.melds[1]=[("pon",["6s"]*3)]
        self.assertEqual(state(r,1)[0],"not_tenpai")
    def test_foul(self):
        f=Fixture(H1[:-1]);d=f.draw(1,"9p")
        self.assertEqual(d["self_info"]["state"],"unknown")
        self.assertTrue(all(x["relation"]=="undetermined_state" for x in d["pairs"]))
        f.discard(1,"9p");f.close()
        f=Fixture(H1+["9p"]);d=f.draw(1,"9p")
        self.assertEqual(d["self_info"]["state"],"unknown");f.close()
    def test_all_18_combinations_physical(self):
        for earlier,later in product(sorted(TENPAI),repeat=2):
            for first in (1,2):
                second=3-first
                types={first:earlier,second:later}
                hands={1:H1,2:H2}
                missing={1:"5m",2:"5p"};extra={1:"9m",2:"1m"}
                if earlier=="open":hands[first]=hands[first][:-1]+[extra[first]]
                hands[second]=hands[second][:-1]+[extra[second]]
                f=Fixture(hands[1],hands[2])
                for p in (first,second):
                    typ=types[p]
                    if typ=="open":
                        z=f"{p}z";f.draw(3,z);f.discard(3,z)
                        f.e("pon",p,target=3,tile=z,block=z*3)
                        f.discard(p,"4m" if p==1 else "4p")
                    elif p==second:
                        f.draw(p,missing[p])
                        if typ=="riichi":f.reach(p,extra[p])
                        else:f.discard(p,extra[p])
                    elif typ=="riichi":
                        f.draw(p,"5z");f.reach(p,"5z")
                    self.assertEqual(state(f.r.replay,p)[0],typ,(earlier,later,first,p))
                self.assertEqual(relation(f.r.active[first],f.r.active[second]),"self_earlier")
                for p,rel in ((first,"self_earlier"),(second,"self_later")):
                    d=f.draw(p,"6z" if p==1 else "7z")
                    q=f.pair(d,3-p)
                    self.assertEqual(q["combination"],f"{rel}:{types[p]}:{types[3-p]}")
                    f.discard(p,"6z" if p==1 else "7z")
                f.close()
    def test_all_18_combinations_logic(self):
        # All enum combinations; event-sequence coverage is separate above.
        for a,b in product(TENPAI,repeat=2):
            for rel in ("self_earlier","self_later"):
                row=dict(combination=f"{rel}:{a}:{b}",relation=rel,self_first_reach=0)
                self.assertEqual(conditions(row),[rel,row["combination"]])
        a=Interval(1,1,2,2,"discard",True,False)
        b=Interval(1,2,3,3,"discard",True,False)
        self.assertEqual((relation(a,b),relation(b,a)),("self_earlier","self_later"))
        b.start_known=False;self.assertEqual(relation(a,b),"undetermined")

if __name__=="__main__":unittest.main(verbosity=2)
