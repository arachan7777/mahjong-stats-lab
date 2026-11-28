"""Stage 4B: event-state coexistence, no reclassification of origins."""
from collections import defaultdict

def origin_key(o):
    return (int(o["draw_event_id"]),int(o["target"]))

def active_at(o,order,side="after"):
    start,end=int(o["start_event_order"]),int(o["end_event_order"])
    if side=="before":
        return start<order<=end
    return start<=order<end

def state(origins,order,eligible,side="after"):
    """eligible maps (target, normalized tile) to True/False/None.
    None means not established; it is not silently counted as False."""
    down=[];same=[];unknown=[]
    for o in origins:
        if not active_at(o,order,side):
            continue
        k=origin_key(o)
        v=eligible.get((k[1],o["tile_type"]))
        if v is None:unknown.append(k)
        elif v:
            (down if float(o["rank_drop"])>0 else same).append(k)
    return tuple(sorted(down)),tuple(sorted(same)),tuple(sorted(unknown))

def coexists(s):
    return bool(s[0] and s[1])

def transition(previous,current,ever):
    if coexists(current) and not coexists(previous):
        return "restart" if ever else "start"
    if coexists(previous) and not coexists(current):return "end"
    if coexists(current) and current!=previous:return "change"
    return None

def ron_result(s,links,winner,rank_before,rank_end,source_kind,tsumogiri,
               declaration,accepted_before,open_before,closed_tenpai_before):
    """All approved origin links retained; count only matching active same-rank origins."""
    matched=sorted({origin_key(r) for r in links
                    if r["relation"] in ("immediate","subsequent")
                    and int(r["same_target"])==1 and int(r["target"])==winner
                    and origin_key(r) in s[1]})
    result=dict(matching_origins=matched,coexist_before=int(coexists(s)),
                rank_before=rank_before,rank_end=rank_end,tolerated=0,sage=0,
                reach_tsumogiri_excluded=0,reason="")
    if source_kind!="discard":result["reason"]="special_excluded";return result
    if not coexists(s):result["reason"]="no_coexistence_before_discard";return result
    if not matched:result["reason"]="no_matching_maintain_origin";return result
    if rank_before!=rank_end:result["reason"]="rank_changed";return result
    result["tolerated"]=1
    if declaration and not accepted_before:result.update(sage=1,reason="reach_declaration")
    elif accepted_before and tsumogiri:result.update(reach_tsumogiri_excluded=1,reason="accepted_reach_tsumogiri")
    elif accepted_before:result.update(reason="unresolved_accepted_reach_non_tsumogiri")
    elif open_before:result.update(sage=1,reason="open_tsumogiri" if tsumogiri else "open_tedashi")
    elif closed_tenpai_before is True:result.update(sage=1,reason="damaten_tsumogiri" if tsumogiri else "damaten_tedashi")
    else:result.update(reason="unresolved_closed_non_tenpai_or_unknown")
    return result
