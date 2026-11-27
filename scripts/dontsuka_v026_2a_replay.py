"""Stage 2A only: reconstruct the physical winning hand from ordered events.
No recorded winning yaku, fu or han is used as an evaluator input.
"""
from collections import Counter
import re

TYPES = ("chi","pon","daiminkan","shominkan","ankan")
def tile(t):
    t = str(t).strip().lstrip("^t-")
    if not re.fullmatch(r"[0-9][mpsz]", t) or (t[1]=="z" and t[0] not in "1234567"):
        raise ValueError("invalid tile: "+t)
    return t

def hand(s):
    return [tile(x) for x in s.split(",") if x.strip()]

def block(s):
    m = re.fullmatch(r"([0-9-]+)([mpsz])",s.strip())
    if m:
        return [tile(n+m[2]) for n in m[1] if n!="-"]
    # Fixed DB event blocks also use repeated full tile notation: 6z6z-6z.
    compact=s.strip().replace("-","")
    if re.fullmatch(r"(?:[0-9][mpsz])+",compact):
        return [tile(x) for x in re.findall(r"[0-9][mpsz]",compact)]
    return hand(s)

def normal(t):
    return "5"+t[1] if t[0]=="0" else t

def remove(h, tiles):
    for t in tiles:
        h.remove(t)

class Replay:
    def __init__(self):
        self.hands={}
        self.melds={}
        self.discards=Counter()
        self.draws=Counter()
        self.reaches=set()
        self.declarations={}
        self.ippatsu=set()
        self.calls=0
        self.omote=[]
        self.ura=[]
        self.last_draw={}
        self.last_action=None
        self.wall=None
        self.trace=[]
    def step(self,e):
        k=e["type"]
        p=e.get("actor")
        t=e.get("tile")
        if k=="haipai":
            if p in self.hands: raise ValueError("duplicate initial hand")
            self.hands[p]=hand(e["hand"])
            self.melds[p]=[]
        elif k=="draw":
            self.hands[p].append(tile(t))
            self.draws[p]+=1
            self.last_draw[p]=dict(e)
            self.wall=e["wall"]
            self.last_action=(k,p,tile(t))
        elif k=="discard":
            t=tile(t)
            remove(self.hands[p],[t])
            if e["declaration"]:
                self.declarations[p]=(self.discards[p]==0 and self.calls==0)
                self.ippatsu.add(p)
            elif p in self.ippatsu:
                self.ippatsu.remove(p)
            self.discards[p]+=1
            self.last_action=(k,p,t)
        elif k=="reach":
            if e["accepted"]: self.reaches.add(p)
        elif k in TYPES:
            t=tile(t)
            raw=e["block"]
            if k=="ankan" and re.fullmatch(r"_(?:[0-9][mpsz]){2}_",raw):
                # Two outer tiles are concealed in the DB notation. Recover
                # all four from the physical hand, without assuming their red status.
                visible=block(raw[1:-1])
                b=[x for x in self.hands[p] if normal(x)==normal(t)]
                if len(b)!=4 or Counter(visible)-Counter(b) or any(normal(x)!=normal(t) for x in visible):
                    raise ValueError("concealed kan tiles disagree with event")
            else:
                b=block(raw)
            if len(b)!=(3 if k in ("chi","pon") else 4):
                raise ValueError("unexpected meld length")
            if k=="shominkan":
                matches=[i for i,(kind,old) in enumerate(self.melds[p])
                         if kind=="pon" and normal(old[0])==normal(t)]
                if len(matches)!=1: raise ValueError("missing original pon")
                i=matches[0]
                old=self.melds[p][i][1]
                if Counter(old)+Counter([t]) != Counter(b): raise ValueError("added kan tiles differ")
                remove(self.hands[p],[t])
                self.melds[p][i]=(k,b)
            else:
                owned=b.copy()
                if k!="ankan":
                    if self.last_action!=("discard",e["target"],t):
                        raise ValueError("call source differs")
                    owned.remove(t)
                remove(self.hands[p],owned)
                self.melds[p].append((k,b))
            self.calls+=1
            self.ippatsu.clear()
            self.last_action=(k,p,t)
        elif k=="dora_indicator":
            if e["dora_type"] not in ("omote","ura"): raise ValueError("unknown dora type")
            getattr(self,e["dora_type"]).append(tile(t))
        self.trace.append(dict(e))
    def winning(self,p,t,tsumo,target=None):
        t=tile(t)
        h=self.hands[p].copy()
        m=self.melds[p]
        if tsumo:
            d=self.last_draw.get(p)
            # Dealer's initial 14-tile tenhou may have no draw event.
            if not d:
                if len(h)!=14 or self.calls or self.discards[p] or t not in h:
                    raise ValueError("tsumo without matching draw")
            elif self.last_action!=("draw",p,t):
                raise ValueError("tsumo not last draw")
        else:
            if self.last_action not in (("discard",target,t),("shominkan",target,t),("ankan",target,t)):
                raise ValueError("ron source differs")
            h.append(t)
        if len(h)+3*len(m)!=14:
            raise ValueError(f"invalid winning structure: concealed={len(h)} melds={len(m)}")
        counts=Counter(normal(x) for x in h+[t for _,b in m for t in b])
        if max(counts.values())>4: raise ValueError("physical tile count exceeds four")
        d=self.last_draw.get(p)
        rinshan=bool(tsumo and d and d["rinshan"])
        chankan=not tsumo and self.last_action[0] in ("shominkan","ankan")
        flags=dict(is_tsumo=tsumo,is_riichi=p in self.reaches,
                   is_daburu_riichi=p in self.reaches and self.declarations.get(p,False),
                   is_ippatsu=p in self.reaches and p in self.ippatsu,
                   is_rinshan=rinshan,is_chankan=chankan,
                   is_haitei=bool(tsumo and self.wall==0 and not rinshan),
                   is_houtei=bool(not tsumo and self.wall==0 and not chankan),
                   first_uninterrupted=bool(tsumo and not self.calls and not self.discards[p] and self.draws[p]<=1))
        return h,m,flags
