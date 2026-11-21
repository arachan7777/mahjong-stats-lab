"""Test reconstructing exact exhaustive-draw dead wall, and tracking INITIAL waits.
This is a feasibility audit, not final indicator SQL. No existing metrics changed.
"""
import sqlite3, os, sys, csv, json
from collections import defaultdict, Counter
from pathlib import Path

db=os.path.abspath(sys.argv[1])
c=sqlite3.connect("file:"+db+"?mode=ro",uri=True); c.row_factory=sqlite3.Row
out=Path("results");out.mkdir(exist_ok=True)
def qry(q,pars=()): return [dict(x) for x in c.execute(q,pars)]
def dump(name,objs):
  if not objs:return
  with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(objs[0]));w.writeheader();w.writerows(objs)
def norm(t):
  if t is None: return None
  t=t.strip()
  if t.startswith("t"):t=t[1:]
  if t and t[0]=="0":t="5"+t[1:]
  return t
def tiles(hand):
  return [norm(x) for x in hand.split(",") if x.strip()]
def wait_tiles(w):
  return set(tiles(w))
all_tiles=[f"{rank}{suit}" for suit in "mps" for rank in range(1,10)]+[f"{rank}z" for rank in range(1,8)]
base=Counter({t:4 for t in all_tiles})
assert c.execute("PRAGMA quick_check").fetchone()[0]=="ok"
draws=qry("""
 SELECT e.kyoku_id, e.id AS event_id, e.event_order
 FROM event e JOIN ryukyoku_event r ON r.event_id=e.id
 ORDER BY e.kyoku_id
""")
exhaust=set(x["kyoku_id"] for x in draws)
obs=defaultdict(lambda:{"haipai":[],"draw":[]})
for x in c.execute("SELECT e.kyoku_id,h.hand FROM haipai_event h JOIN event e ON e.id=h.event_id"):
  if x["kyoku_id"] in exhaust:obs[x["kyoku_id"]]["haipai"].extend(tiles(x["hand"]))
for x in c.execute("SELECT e.kyoku_id,d.tile FROM draw_event d JOIN event e ON e.id=d.event_id"):
  if x["kyoku_id"] in exhaust:obs[x["kyoku_id"]]["draw"].append(norm(x["tile"]))
waiting_kyoku=defaultdict(dict)
for x in c.execute("""
 SELECT e.kyoku_id,pts.player_id,e.event_order,e.id AS event_id,
        pts.waiting_tiles,pts.available_tile_count,pts.ideal_tile_count
 FROM player_tenpai_state pts JOIN event e ON e.id=pts.event_id
 WHERE pts.is_actor=1 ORDER BY e.kyoku_id,pts.player_id,e.event_order,e.id
"""):
  if x["kyoku_id"] not in exhaust:continue
  d=waiting_kyoku[x["kyoku_id"]]
  if x["player_id"] not in d:d[x["player_id"]]=dict(x)
terminal=qry("""
 SELECT e.kyoku_id,pts.player_id,pts.waiting_tiles,pts.available_tile_count,
        rp.is_tenpai
 FROM event e
 JOIN ryukyoku_event r ON r.event_id=e.id
 JOIN ryukyoku_player rp ON rp.ryukyoku_event_id=e.id
 LEFT JOIN player_tenpai_state pts
    ON pts.event_id=e.id AND pts.player_id=rp.player_id
 ORDER BY e.kyoku_id, rp.player_id
""")
last=defaultdict(dict)
for x in terminal:last[x["kyoku_id"]][x["player_id"]]=x
stats=Counter();anom=[];players=defaultdict(lambda:Counter());samples=[]
lastcomp=Counter();ratio_classes=Counter()
for dt in draws:
  ky=dt["kyoku_id"];data=obs[ky]
  seen=Counter(data["haipai"]+data["draw"])
  unobserved=base-seen
  extras={t:seen[t] for t in seen if t not in base or seen[t]>4}
  rem=sum(unobserved.values())
  stats["draw_kyoku"]+=1
  stats["haipai_tiles"]+=len(data["haipai"]);stats["draw_tiles"]+=len(data["draw"])
  stats["remaining_"+str(rem)]+=1
  if extras or rem!=14:
    stats["deck_reconstruction_anomalies"]+=1
    if len(anom)<30:anom.append({"kyoku_id":ky,"handtiles":len(data["haipai"]),"drawtiles":len(data["draw"]),"remaining":rem,"extras":extras,"seen_sample":(data["haipai"]+data["draw"])[:20]})
  if extras:continue
  for pid,z in last[ky].items():
    if z["is_tenpai"]==1 and z["waiting_tiles"] is not None:
      rebuilt=sum(unobserved[t] for t in wait_tiles(z["waiting_tiles"]))
      lastcomp["checked"]+=1
      if rebuilt!=z["available_tile_count"]:
        lastcomp["different"]+=1
        if len(anom)<30:anom.append({"kyoku_id":ky,"pid":pid,"type":"terminal_mismatch","db":z["available_tile_count"],"rebuild":rebuilt,"wait":z["waiting_tiles"],"rem":rem})
  for pid,initial in waiting_kyoku[ky].items():
    ts=last[ky].get(pid)
    if ts is None:continue
    names=wait_tiles(initial["waiting_tiles"])
    if not names:continue
    numerator=sum(unobserved[t] for t in names)
    denominator=initial["available_tile_count"]
    status=("same_wait" if ts["is_tenpai"]==1 and wait_tiles(ts["waiting_tiles"])==names
            else "changed_wait" if ts["is_tenpai"]==1 else "end_noten")
    stats["initial_tenpai_found"]+=1;stats[status]+=1
    if denominator==0:stats["initial_available_zero"]+=1
    else:
      stats["positive_denominator"]+=1
      if numerator>denominator:stats["greater_than_100_pct"]+=1
      elif numerator==denominator:stats["exactly_100_pct"]+=1
      elif numerator==0:stats["zero_pct"]+=1
      ratio_classes[status]+=1
      row=players[pid];row["initial_tenpai_kyoku"]+=1
      row["initial_remaining_wait_tiles"]+=denominator
      row["end_deadwall_original_wait_tiles"]+=numerator
      row["over_100_kyoku"]+=numerator>denominator
      if len(samples)<40 and (numerator>denominator or status!="same_wait"):
        samples.append({"kyoku_id":ky,"player_id":pid,"init_wait":initial["waiting_tiles"],"init_available":denominator,"last_wait":ts["waiting_tiles"],"terminal_tenpai":ts["is_tenpai"],"deadwall_original_wait":numerator,"ratio":round(100*numerator/denominator,3),"status":status})
    if len(samples)<40 and denominator and numerator==round(.8*denominator) and status=="same_wait" and denominator>=5:
      samples.append({"kyoku_id":ky,"player_id":pid,"init_wait":initial["waiting_tiles"],"init_available":denominator,"last_wait":ts["waiting_tiles"],"terminal_tenpai":ts["is_tenpai"],"deadwall_original_wait":numerator,"ratio":round(100*numerator/denominator,3),"status":status})

data={
 "sqlite_quick_check":"ok",
 "note":"Feasibility only. Denominator: at FIRST own-tenpai snapshot available_tile_count; numerator: physical tiles of SAME initial wait types remaining un-drawn at exhaustive draw. Includes draw states that later changed waits or ended noten, annotated; no implicit new definition.",
 "stats":dict(stats),
 "terminal_original_db_count_comparison":dict(lastcomp),
 "status_counts":dict(ratio_classes),
 "examples":samples,
 "anomaly_samples":anom
}
rows=[]
for pid,p in players.items():
  rows.append({"player_id":pid,"eligible_first_tenpai_kyoku":p["initial_tenpai_kyoku"],"initial_wait_available_sum":p["initial_remaining_wait_tiles"],"deadwall_initial_wait_sum":p["end_deadwall_original_wait_tiles"],"aggregate_ratio_pct":round(100*p["end_deadwall_original_wait_tiles"]/p["initial_remaining_wait_tiles"],4) if p["initial_remaining_wait_tiles"] else None,"over_100_kyoku":p["over_100_kyoku"]})
rows.sort(key=lambda z:(-(z["aggregate_ratio_pct"] or 0),-z["eligible_first_tenpai_kyoku"]))
dump("initial_wait_deadwall_feasibility_players.csv",rows)
(out/"initial_wait_deadwall_feasibility.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
print("AUDIT",json.dumps({k:v for k,v in data.items() if k not in ("examples","anomaly_samples")},ensure_ascii=False),flush=True)
print("EXAMPLES",json.dumps(samples[:15],ensure_ascii=False),flush=True)
print("TOP10_PROVISIONAL",json.dumps(rows[:10],ensure_ascii=False),flush=True)
print("ANOMALIES",json.dumps(anom[:8],ensure_ascii=False),flush=True)
