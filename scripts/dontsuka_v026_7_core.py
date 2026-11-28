"""Stage 7 only: draw/discard linkage and genbutsu chronology.
Reference: research/kayamori_sonoda_safe_20261126.py at 0e181caed44339711a2d34f2b526a46062dd045d.
"""
from collections import defaultdict
from dontsuka_v026_6_core import Inventory,state,require,normal
from dontsuka_v026_5a_core import sh,vector,candidates

def hand_state(rp,p,expected):
    h,m=rp.hands[p],rp.melds[p]
    effective=len(h)+3*len(m)
    if effective!=expected:
        return dict(shanten="",state="unknown",effective=effective,reason="few_tiles" if effective<expected else "many_tiles")
    q=sh(vector(h))
    if expected==14:
        return dict(shanten=q,state="after_draw",effective=effective,reason="")
    require(q>=0,"winning shape at 13-effective state")
    k,w,_=state(rp,p)
    reason="structural_no_physical_wait" if q==0 and k=="not_tenpai" else ""
    return dict(shanten=q,state=k,effective=effective,reason=reason)

def movement(a,b):
    if a["shanten"]=="" or b["shanten"]=="":
        return "", "not_applicable", "abnormal_effective_tile_count"
    x,y=a["shanten"],b["shanten"];d=y-x
    if a["reason"]=="structural_no_physical_wait" or b["reason"]=="structural_no_physical_wait":
        # Retain raw delta; do not call a fifth-copy shape a physical tenpai.
        return d,"not_applicable","structural_no_physical_wait"
    label="tenpai_maintained" if x==y==0 else "tenpai_broken" if x==0 and y==1 else "progress" if d<0 else "maintained" if d==0 else "regress"
    return d,label,""

class History:
    def __init__(self):
        self.discards=defaultdict(list)
        self.all=[]
        self.pending_reach={}
        self.established={}
    def record(self,e):
        k=e["type"];p=e.get("actor")
        if k=="reach" and e["accepted"]:
            self.pending_reach[p]=e
        elif k=="discard":
            # DB reach marker precedes declaration discard; acceptance for safety
            # starts after the accepted declaration discard (prior study).
            rec=(e["event_order"],e["id"],p,normal(e["tile"]))
            self.discards[p].append(rec);self.all.append(rec)
            if e["declaration"] and p in self.pending_reach:
                self.established[p]=(e["event_order"],e["id"])
                self.pending_reach.pop(p)
    def genbutsu(self,t,e):
        typ=normal(e["tile"]);order=e["event_order"]
        own=[x for x in self.discards[t] if x[3]==typ and x[0]<order]
        reach=self.established.get(t)
        passed=[x for x in self.all if reach and reach[0]<x[0]<order and x[2]!=t and x[3]==typ]
        if own:
            x=own[-1];return 1,"target_own_discard",x[1],x[0],x[2]
        if passed:
            x=passed[-1];return 1,"passed_after_accepted_reach",x[1],x[0],x[2]
        return 0,"no_prior_qualifying_discard","","",""

def disposition(e,flags,accepted_before):
    if e["declaration"]:return "reach_declaration"
    if flags and accepted_before:return "accepted_reach_tsumogiri"
    return "tsumogiri" if flags else "tedashi"

class Linker:
    """One outstanding draw. A kan consumes its own draw without a discard.
    Calls create no new draw; rinshan draws are independent events.
    """
    def __init__(self):self.pending=None;self.kan_pending=None
    def feed(self,e):
        k=e["type"];p=e.get("actor");result=[]
        if self.kan_pending is not None and k in ("draw","ron","tsumo","ryukyoku"):
            old=self.kan_pending;self.kan_pending=None
            reason="kan_robbed" if k=="ron" else "kan_before_rinshan" if k=="draw" else "kan_round_end"
            result.append((old,reason,e))
        if k=="draw":
            if self.pending is not None:
                result.append((self.pending,"next_draw_without_discard",e))
            self.pending=e
        elif k=="discard":
            if self.pending is not None:
                reason="discard" if self.pending["actor"]==p else "other_discard_before_own_discard"
                result.append((self.pending,reason,e));self.pending=None
        elif k in ("ankan","shominkan","daiminkan"):
            if self.pending is not None:
                if self.pending["actor"]==p and k!="daiminkan":
                    self.kan_pending=self.pending
                else:result.append((self.pending,"call_without_own_discard",e))
                self.pending=None
        elif k in ("chi","pon"):
            if self.pending is not None:
                result.append((self.pending,"call_without_own_discard",e));self.pending=None
        elif k in ("ron","tsumo","ryukyoku"):
            if self.pending is not None:
                result.append((self.pending,"tsumo_win" if k=="tsumo" else "round_end_without_discard",e));self.pending=None
        return result
    def finish(self):
        require(self.pending is None and self.kan_pending is None,"unclosed draw link")
