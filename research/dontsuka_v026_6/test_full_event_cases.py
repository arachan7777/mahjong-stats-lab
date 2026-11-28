"""Supplemental Stage 6 full four-player event fixtures (no new research rules)."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from dontsuka_v026_6_core import Inventory,state,compare,pairs,remaining

def event(r,k,p=None,**kwargs):
    e=dict(id=len(r.trace)+1,event_order=len(r.trace)+1,type=k,actor=p,wall=40,rinshan=False,declaration=False)
    e.update(kwargs);r.step(e)
def setup(tanki):
    r=Inventory()
    h1="7m 8m 9m 7p 8p 9p 1s 2s 3s 4s 5s 1z 1z".split()
    base="1m 2m 3m 4m 5m 6m 1p 2p 3p 4p 5p 6p".split()
    hands={1:h1,**{p:base+[t] for p,t in zip((2,3,4),tanki)}}
    for p,h in hands.items():event(r,"haipai",p,hand=",".join(h))
    return r
def opponents_reach(r):
    for p,t in zip((2,3,4),("2z","3z","4z")):
        event(r,"draw",p,tile=t)
        event(r,"reach",p,accepted=True)
        event(r,"discard",p,tile=t,declaration=True)
class FullEvents(unittest.TestCase):
    def test_non_single_double_triple_with_real_waits(self):
        for waits,tile,n in [(("9s","8s","7s"),"6z",0),(("9s","8s","7s"),"9s",1),(("9s","9s","7s"),"9s",2),(("9s","9s","9s"),"9s",3)]:
            r=setup(waits);opponents_reach(r)
            states={p:state(r,p) for p in r.hands};public,private,known=r.snapshot()
            self.assertEqual(states[1][0],"damaten")
            self.assertTrue(all(states[p][0]=="riichi" and states[p][1]==(w,) for p,w in zip((2,3,4),waits)))
            pp=list(pairs(states,1,(2,3,4)))
            self.assertEqual(pp,[(2,True),(3,True),(4,True)])
            saved={p:compare(1,p,public,private,known,states[1][1],states[p][1]) for p,_ in pp}
            event(r,"draw",1,tile=tile)
            flags={p:int(tile in states[p][1]) for p,_ in pp}
            self.assertEqual(sum(flags.values()),n)
            self.assertEqual(len(saved),3)
            self.assertEqual(int(any(flags.values())),int(n>0))
            self.assertEqual(state(r,1)[0],"unknown") # no post-draw state substitution
    def test_pure_zero_visible_zero_full_event(self):
        r=setup(("9s","8s","7s"))
        for p in (1,3,4):
            event(r,"draw",p,tile="9s");event(r,"discard",p,tile="9s")
        public,private,known=r.snapshot();s=state(r,2)
        self.assertEqual(s[:2],("damaten",("9s",)))
        self.assertEqual(remaining(s[1],public+private[2]),0)
        self.assertEqual(remaining(s[1],known),0)
        self.assertEqual(known["9s"],4)
    def test_dead_wall_and_live_wall_are_not_distinguished(self):
        r=setup(("9s","9s","9s"))
        public,private,known=r.snapshot();s=state(r,2)
        self.assertEqual(known["9s"],3)
        self.assertEqual(remaining(s[1],known),1)
        # Both explicit possible assignments of the fourth tile are outside
        # the information accepted by compare; same pre-draw count.
        for assignment in ("unrevealed_dead_wall","live_wall"):
            self.assertEqual(remaining(s[1],known),1,assignment)
    def test_disclosed_indicator_removed_only_when_revealed(self):
        r=setup(("9s","9s","9s"))
        self.assertEqual(remaining(("9s",),r.snapshot()[2]),1)
        event(r,"dora_indicator",tile="9s",dora_type="omote")
        public,private,known=r.snapshot()
        self.assertEqual(remaining(("9s",),known),0)
        self.assertEqual(remaining(("9s",),public+private[2]),2)
if __name__=="__main__":unittest.main(verbosity=2)
