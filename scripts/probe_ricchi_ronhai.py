"""Inspect reach declaration flags and ron event sequencing before fixing the new indicator."""
import os,sqlite3,json
from collections import Counter,defaultdict
from pathlib import Path
import sys
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
q="""
 SELECT e.id AS event_id,e.kyoku_id,e.event_order,e.type,
        d.actor_player_id AS discarded_by,d.tile AS discard_tile,
        d.is_reach_declaration,
        r.actor_player_id AS reached_by,r.is_accepted,
        a.actor_player_id AS winner,a.target_player_id AS target,a.agari_tile
 FROM event e
 LEFT JOIN discard_event d ON d.event_id=e.id AND e.type='discard'
 LEFT JOIN reach_event r ON r.event_id=e.id AND e.type='reach'
 LEFT JOIN agari_event a ON a.event_id=e.id AND e.type='ron'
 WHERE e.type IN ('reach','ron') OR (e.type='discard' AND d.is_reach_declaration=1)
 ORDER BY e.kyoku_id,e.event_order,e.id
"""
groups=defaultdict(list)
for row in con.execute(q):
    z=dict(row);groups[z["kyoku_id"]].append(z)
def norm(t):
    if t is None:return None
    if t.startswith('t'):t=t[1:]
    if t.startswith('0'):t='5'+t[1:]
    return t
stats=Counter(); samples=defaultdict(list); audit=[]
for kyoku,seq in groups.items():
    dec=[x for x in seq if x["is_reach_declaration"]==1]
    reach=[x for x in seq if x["type"]=="reach"]
    ron=[x for x in seq if x["type"]=="ron"]
    for d in dec:
        p=d["discarded_by"]
        matching=[x for x in ron if x["target"]==p and x["event_order"]>d["event_order"]]
        tilematches=[x for x in matching if norm(x["agari_tile"])==norm(d["discard_tile"])]
        after_same_reach=[x for x in reach if x["reached_by"]==p and x["event_order"]>=d["event_order"]]
        before_same_reach=[x for x in reach if x["reached_by"]==p and x["event_order"]<=d["event_order"]]
        status=after_same_reach[0] if after_same_reach else (before_same_reach[-1] if before_same_reach else None)
        if status is None: key="missing_reach_event"
        elif status["is_accepted"]==0:key="unaccepted"
        else:key="accepted"
        stats["declarations"]+=1
        stats[key]+=1
        if tilematches: stats["declared_tile_ron"]+=1
        if matching:stats["any_after_ron"]+=1
        if tilematches and key!="unaccepted":stats["tile_ron_unexpected_"+key]+=1
        if key=="unaccepted" and not tilematches:stats["unaccepted_without_tile_ron"]+=1
        if len(tilematches)>1:stats["multi_ron_declaration"]+=1
        if key=="unaccepted" and tilematches:stats["unaccepted_and_tile_ron"]+=1
        signature=key+"_"+("tile_ron" if tilematches else "no_tile_ron")
        if len(samples[signature])<8:
            samples[signature].append({"kyoku":kyoku,"discard":d,"nearest_reach":status,"ron":ron[:5]})
    for x in reach:
        if x["is_accepted"]==0:stats["unaccepted_reach_events"]+=1
        else:stats["accepted_reach_events"]+=1
        if not any(d["discarded_by"]==x["reached_by"] for d in dec):
            stats["reach_event_without_flagged_discard"]+=1
            if len(samples["reach_without_discard"])<10:samples["reach_without_discard"].append({"reach":x,"sequence":seq})
result={"summary":dict(stats),"sample":dict(samples)}
Path("results").mkdir(exist_ok=True)
Path("results/ricchi_ronhai_probe.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print("PROBE",json.dumps(result["summary"],ensure_ascii=False),flush=True)
print("CASE_KEYS",list(samples),flush=True)
