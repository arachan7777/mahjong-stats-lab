"""Stage 6: physical remaining counts from the approved pre-draw replay.
All counters use tile types, not red/ordinary identities.
"""
from collections import Counter
from dontsuka_v026_2a_replay import Replay,normal,TYPES
from dontsuka_v026_5a_core import candidates,sh,vector

def require(ok,msg):
    if not ok: raise ValueError(msg)

def counts(tiles):
    return Counter(normal(t) for t in tiles)

def remaining(waits, known):
    return sum(4-known[t] for t in set(map(normal,waits)))

def sign(n):
    return "advantage" if n>0 else "equal" if n==0 else "disadvantage"

def state(rp,p):
    h,m=rp.hands[p],rp.melds[p]
    if len(h)+3*len(m)!=13:
        return "unknown",(),len(h)+3*len(m)
    q=sh(vector(h))
    require(q>=0,"winning shape before draw")
    w=tuple(sorted(set(map(normal,candidates(h,m))))) if q==0 else ()
    # Same physical wait requirement as approved 5A; a fifth copy is not a wait.
    if not w: return "not_tenpai",(),13
    k="riichi" if p in rp.reaches else "open" if any(k!="ankan" for k,b in m) else "damaten"
    return k,w,13

class Inventory(Replay):
    def __init__(self):
        super().__init__()
        self.rivers=Counter()
        self.dealt_drawn=Counter()

    def step(self,e):
        k=e["type"]
        if k=="discard":
            self.rivers[normal(e["tile"])]+=1
        elif k in ("chi","pon","daiminkan"):
            t=normal(e["tile"])
            require(self.rivers[t]>0,"missing called river tile")
            self.rivers[t]-=1
        super().step(e)
        if k=="haipai":
            self.dealt_drawn.update(counts(self.hands[e["actor"]]))
        elif k=="draw":
            self.dealt_drawn[normal(e["tile"])]+=1

    def snapshot(self):
        # A called discard is removed from rivers, and included in melds once.
        # All four type identities in an ankan are public; red identity is irrelevant.
        public=self.rivers+counts(self.omote)+counts(t for ms in self.melds.values() for _,b in ms for t in b)
        private={p:counts(h) for p,h in self.hands.items()}
        all_known=public.copy()
        for h in private.values():all_known.update(h)
        require(all_known==self.dealt_drawn+counts(self.omote),"physical inventory reconciliation")
        require(all(0<=n<=4 for n in all_known.values()),"physical tile limit")
        return public,private,all_known

def compare(a,b,public,private,all_known,aw,bw):
    va=remaining(aw,public+private[a]);vb=remaining(bw,public+private[b])
    ya=remaining(aw,all_known);yb=remaining(bw,all_known)
    require(0<=ya<=va and 0<=yb<=vb,"remaining count bound")
    vd,yd=va-vb,ya-yb
    v,y=sign(vd),sign(yd)
    return dict(self_visible=va,target_visible=vb,self_wall=ya,target_wall=yb,
                visible_diff=vd,wall_diff=yd,visible_class=v,wall_class=y,combined=v+"_"+y)

def pairs(states,p,targets):
    """Exclude only known non-tenpai; keep unknown/possible comparisons explicit."""
    a=states[p][0]
    for t in targets:
        b=states[t][0]
        if a=="not_tenpai" or b=="not_tenpai":continue
        yield t,a!="unknown" and b!="unknown"
