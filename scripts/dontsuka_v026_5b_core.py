"""Stage 5B: exhaustive hypothetical draw/discard progression, no actual future tile."""
from collections import Counter
from functools import lru_cache
from dontsuka_v026_5a_core import TYPES,sh,vector,candidates,evaluate_waits
from dontsuka_v026_2a_replay import normal

VARIANTS=tuple(t for t in TYPES)+("0m","0p","0s")
def physical_draws(h,m):
    own=Counter(h+[t for _,b in m for t in b])
    norm=Counter(normal(t) for t in own.elements())
    if any(v>4 for v in norm.values()):raise ValueError("physical inventory >4")
    for t in VARIANTS:
        cap=1 if t[0]=="0" else 3 if t[0]=="5" and t[1]!="z" else 4
        if norm[normal(t)]<4 and own[t]<cap:yield t

@lru_cache(maxsize=50000)
def structural_options(v):
    # A 14-effective-tile hand with a tenpai discard has shanten <=0.
    # Shape prefilter only; actual variants and physical constraints below.
    out=[]
    for i,t in enumerate(TYPES):
        if v[i]>=4:continue
        w=list(v);w[i]+=1
        if sh(tuple(w))>0:continue
        for j,d in enumerate(TYPES):
            if not w[j]:continue
            w[j]-=1
            if sh(tuple(w))==0:out.append((t,d))
            w[j]+=1
    return frozenset(out)

def progressions(h,m,reference=False):
    if len(h)+3*len(m)!=13 or sh(vector(h))!=1:raise ValueError("not a one-shanten state")
    options=None if reference else structural_options(vector(h))
    for t in physical_draws(h,m):
        after=h+[t]
        for d in sorted(set(after)):
            if options is not None and (normal(t),normal(d)) not in options:continue
            nxt=after.copy();nxt.remove(d)
            if reference and sh(vector(nxt))!=0:continue
            waits=candidates(nxt,m)
            if waits:yield t,d,tuple(sorted(nxt)),waits

@lru_cache(maxsize=16000)
def scoring(h,m,pwind,rwind,omote):
    # Furiten changes eligibility, never the score; calculate once per exact state.
    return evaluate_waits(list(h),[(k,list(b)) for k,b in m],pwind,rwind,omote,False,False,False)

def classify(h,m,pwind,rwind,omote,discards,reference=False):
    meldkey=tuple((k,tuple(sorted(b))) for k,b in m)
    discarded={normal(t) for t in discards}
    progress=0; pattern_count=0; wins=0; qualifying_progressions=0; witness=None
    # No actual draw, discard or final result is an input. The hypothetical
    # draw clears temporary furiten; past and hypothetical own discards remain.
    for t,d,nxt,waits in progressions(h,m,reference):
        progress+=1
        furiten=bool({normal(x) for x in waits}&(discarded|{normal(d)}))
        _,patterns,_=scoring(nxt,meldkey,pwind,rwind,tuple(omote))
        pattern_count+=len(patterns)
        qualifying=[]
        for p in patterns:
            if p["qualifies"] and (p["method"]=="tsumo" or not furiten):
                q=dict(p,furiten=furiten,eligible=True)
                qualifying.append(q)
        if qualifying:
            qualifying_progressions+=1;wins+=len(qualifying)
            if witness is None:
                witness=dict(progression_draw=t,progression_discard=d,tenpai_hand=nxt,waits=waits,furiten=furiten,pattern=qualifying[0])
    return dict(is_shoubute=int(witness is not None),progressions=progress,patterns=pattern_count,
                qualifying_progressions=qualifying_progressions,qualifying_patterns=wins,witness=witness)
