"""Stage 5A only: score prospective waits using approved Stage 2A evaluator."""
from collections import Counter
from functools import lru_cache
from mahjong.shanten import Shanten
from dontsuka_v026_2a_audit import evaluate,index,score
from dontsuka_v026_2a_replay import normal

TYPES=tuple(str(n)+s for s in "mps" for n in range(1,10))+tuple(str(n)+"z" for n in range(1,8))
EXCLUDED={"裏ドラ","一発","搶槓","槍槓","海底摸月","河底撈魚","嶺上開花","天和","地和"}
def vector(h):
    v=[0]*34
    for t in h:v[index(t)]+=1
    return tuple(v)

@lru_cache(maxsize=100000)
def sh(v):
    return Shanten().calculate_shanten(list(v))

@lru_cache(maxsize=50000)
def shape(v):
    if sh(v)!=0:return ()
    out=[]
    for i,t in enumerate(TYPES):
        if v[i]==4:continue
        w=list(v);w[i]+=1
        if sh(tuple(w))==-1:out.append(t)
    return tuple(out)

def candidates(h,m):
    if len(h)+3*len(m)!=13:raise ValueError("not a 13-effective-tile state")
    own=Counter(h+[t for _,b in m for t in b])
    counts=Counter(normal(t) for t in own.elements())
    out=[]
    for t in shape(vector(h)):
        if counts[t]>=4:continue
        if t[0]=="5":
            if own[t]<3:out.append(t)
            red="0"+t[1]
            if own[red]<1:out.append(red)
        else:out.append(t)
    return tuple(out)

def qualifies(v,dealer):
    return bool(v["yakuman"] or v["han"]>=4 or v["points"]>=(12000 if dealer else 8000))

def evaluate_waits(h,m,pwind,rwind,omote,reached,double,furiten=False,riichi_possible=True):
    opened=any(k!="ankan" for k,b in m)
    if reached and opened:raise ValueError("open accepted riichi")
    if double and not reached:raise ValueError("unaccepted double riichi")
    virtual=bool(not reached and not opened and riichi_possible)
    waits=candidates(h,m)
    patterns=[]
    for t in waits:
        for tsumo in (False,True):
            flags=dict(is_tsumo=tsumo,is_riichi=bool(reached or virtual),
              is_daburu_riichi=bool(double),is_ippatsu=False,is_rinshan=False,
              is_chankan=False,is_haitei=False,is_houtei=False,first_uninterrupted=False)
            row=dict(tile=t,method="tsumo" if tsumo else "ron",
                virtual_riichi=virtual,flags=flags,furiten=furiten)
            try:
                v=evaluate(h+[t],m,t,flags,pwind,rwind,list(omote),[])
            except ValueError as ex:
                if str(ex) not in ("hand calculator: no_yaku","hand calculator: hand_not_winning"):raise
                patterns.append(dict(row,status=str(ex),eligible=False,qualifies=False))
                continue
            if EXCLUDED.intersection(v["yaku"]):raise ValueError("excluded yaku")
            if v["yaku"].get("立直",0)+v["yaku"].get("ダブル立直",0)>2 or ("立直" in v["yaku"] and "ダブル立直" in v["yaku"]):raise ValueError("duplicate riichi")
            expected=score(v["han"],v["fu"],tsumo,pwind=="1z",len(v["yaku"]) if v["yakuman"] else 0)
            if expected!=v["points"]:raise ValueError("independent score arithmetic mismatch")
            eligible=tsumo or not furiten
            patterns.append(dict(row,**v,status="evaluated",eligible=eligible,
                                 qualifies=eligible and qualifies(v,pwind=="1z")))
    return waits,patterns,any(r["qualifies"] for r in patterns)
