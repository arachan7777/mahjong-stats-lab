"""Stage 4A only: continuous concealed tile-type possession and ron attribution.
Use the approved physical replay and normalize red tiles only for type identity.
No recalculation of hypothetical scores or past don-tsuka.
"""
from collections import Counter, defaultdict
from dontsuka_v026_2a_replay import Replay, normal, tile

class Tracker:
    def __init__(self):
        self.replay=Replay()
        self.active=defaultdict(list)
        self.origins=[]
        self.changes=[]
        self.last_draw={}
        self.source=None
    def step(self,e,origins=(),tsumogiri=None):
        p=e.get("actor"); kind=e["type"]
        before=Counter(normal(t) for t in self.replay.hands.get(p,[]))
        previous_draw=self.last_draw.get(p)
        # Capture active intervals before consuming a discard/kan tile.
        if kind in ("discard","shominkan","ankan"):
            raw=tile(e["tile"]); typ=normal(raw)
            self.source=dict(event_id=e["id"],event_order=e["event_order"],kind=kind,actor=p,
                             tile=raw,tile_type=typ,tsumogiri=tsumogiri,
                             draw_id=previous_draw["id"] if previous_draw else None,
                             active=list(self.active.get((p,typ),[])),before_count=before[typ])
            if kind=="discard" and tsumogiri:
                if not previous_draw or tile(previous_draw["tile"])!=raw:
                    raise ValueError("tsumogiri has no matching physical draw")
        elif kind in ("draw","chi","pon","daiminkan"):
            self.source=None
        self.replay.step(e)
        after=Counter(normal(t) for t in self.replay.hands.get(p,[]))
        if kind=="draw":
            self.last_draw[p]=e
        elif kind in ("discard","chi","pon","daiminkan","ankan","shominkan"):
            self.last_draw.pop(p,None)
        for typ in set(before)|set(after):
            key=(p,typ)
            if before[typ]!=after[typ] and self.active.get(key):
                for o in self.active[key]:
                    self.changes.append(dict(draw_event_id=o["draw_event_id"],target=o["target"],
                        event_id=e["id"],event_order=e["event_order"],event_type=kind,
                        before_count=before[typ],after_count=after[typ]))
                    if not after[typ]:
                        o.update(end_event_id=e["id"],end_event_order=e["event_order"],
                                 end_reason="zero",end_count=0)
                if not after[typ]:
                    self.active.pop(key)
        for r in origins:
            typ=normal(tile(e["tile"]))
            if kind!="draw" or int(r["drawer"])!=p or int(r["event_order"])!=e["event_order"] or tile(r["tile"])!=tile(e["tile"]):
                raise ValueError("approved origin identity differs")
            o=dict(r,tile_type=typ,start_event_id=e["id"],start_event_order=e["event_order"],
                   before_count=before[typ],start_count=after[typ],end_event_id="",
                   end_event_order="",end_reason="",end_count="")
            self.origins.append(o);self.active[(p,typ)].append(o)
    def finish(self,e):
        for (p,typ),items in self.active.items():
            for o in items:
                o.update(end_event_id=e["id"],end_event_order=e["event_order"],end_reason="kyoku_end",
                         end_count=sum(normal(t)==typ for t in self.replay.hands[p]))
        self.active.clear()

def classify(tracker,win):
    """One actual ron row; independent per-origin relationships.
    Same-vs-other target at origin level can coexist for a single ron.
    """
    p=int(win["target_player_id"]); winner=int(win["actor_player_id"])
    source=tracker.source
    if not source or source["actor"]!=p or source["tile"]!=tile(win["agari_tile"]):
        raise ValueError("ron source identity mismatch")
    origins=[o for o in tracker.origins if int(o["drawer"])==p]
    active={(int(o["draw_event_id"]),int(o["target"])) for o in source["active"]}
    special=source["kind"] in ("shominkan","ankan")
    links=[]
    for o in origins:
        key=(int(o["draw_event_id"]),int(o["target"]))
        same_type=o["tile_type"]==source["tile_type"]
        retained=key in active
        immediate=bool(retained and source["tsumogiri"] and source["draw_id"]==key[0])
        if special: relation="special_excluded"
        elif immediate: relation="immediate"
        elif retained: relation="subsequent"
        elif same_type: relation="same_type_after_end_unclassified"
        else: relation="different_tile"
        links.append(dict(draw_event_id=key[0],target=key[1],ron_event_id=win["event_id"],
                          rank_drop=o["rank_drop"],tile_type=o["tile_type"],relation=relation,
                          retained_at_ron_source=int(retained),same_target=int(key[1]==winner)))
    rel={r["relation"] for r in links}
    causal=[r for r in links if r["relation"] in ("immediate","subsequent")]
    if not origins: category="no_dontsuka"
    elif special: category="special_excluded"
    elif "immediate" in rel: category="immediate"
    elif "subsequent" in rel: category="subsequent"
    elif "same_type_after_end_unclassified" in rel: category="unclassified"
    else: category="different_tile"
    target_class=("same_target" if any(r["same_target"] for r in causal) else "other_target") if causal else ""
    # Event-level target comparison uses the set of all causal origin targets;
    # per-origin matches and nonmatches are retained independently.
    return dict(ron_event_id=win["event_id"],kyoku_id=win["kyoku_id"],player_id=p,winner=winner,
                source_event_id=source["event_id"],source_kind=source["kind"],tile=source["tile"],
                tsumogiri=int(source["kind"]=="discard" and bool(source["tsumogiri"])),
                actual_ron=1,category=category,target_class=target_class,
                causal_origin_count=len({r["draw_event_id"] for r in causal}),
                causal_opponent_rows=len(causal)),links
