"""Determine initial-undrawn waits vs final physical dead-wall waits, avoiding snapshot semantic traps.
Audit only: preserve the user's precise 5 -> 4 = 80% example, no official index change.
"""
import sqlite3,os,sys,json,csv
from collections import Counter,defaultdict
from pathlib import Path
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True);con.row_factory=sqlite3.Row
out=Path("results");out.mkdir(exist_ok=True)
def q(s,pars=()):return [dict(x) for x in con.execute(s,pars)]
def dump_csv(name,rows):
 if not rows:return
 with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def norm(s):
 if s is None:return None
 s=s.strip()
 if s.startswith("t"):s=s[1:]
 if s.startswith("0"):s="5"+s[1:]
 return s
def tiles(s):return [norm(x) for x in s.split(",") if x.strip()]
base=Counter({f"{i}{s}":4 for s in "mps" for i in range(1,10)})
base.update({f"{i}z":4 for i in range(1,8)})
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"

end=q("""
 SELECT e.kyoku_id,e.id AS event_id,e.event_order,
        rp.player_id,rp.is_tenpai,pts.waiting_tiles,
        pts.available_tile_count,pts.dora_indicator_tile_count
 FROM ryukyoku_event re JOIN event e ON e.id=re.event_id
 JOIN ryukyoku_player rp ON rp.ryukyoku_event_id=re.event_id
 LEFT JOIN player_tenpai_state pts ON pts.event_id=re.event_id AND pts.player_id=rp.player_id
 ORDER BY e.kyoku_id,rp.player_id
""")
endby=defaultdict(dict)
for v in end:endby[v["kyoku_id"]][v["player_id"]]=v
exhaust=set(endby)

hand=defaultdict(list);draws=defaultdict(list);doras=defaultdict(list);first=defaultdict(dict)
for r in con.execute("""
 SELECT e.kyoku_id,h.hand FROM haipai_event h JOIN event e ON e.id=h.event_id
"""):
 if r["kyoku_id"] in exhaust:hand[r["kyoku_id"]].extend(tiles(r["hand"]))
for r in con.execute("""
 SELECT e.kyoku_id,e.event_order,d.tile,d.is_rinshan
 FROM draw_event d JOIN event e ON e.id=d.event_id
"""):
 if r["kyoku_id"] in exhaust:draws[r["kyoku_id"]].append((r["event_order"],norm(r["tile"]),r["is_rinshan"]))
for r in con.execute("""
 SELECT e.kyoku_id,e.event_order,de.dora_type,de.dora_indicator_tile
 FROM dora_indicator_event de JOIN event e ON e.id=de.event_id
"""):
 if r["kyoku_id"] in exhaust:doras[r["kyoku_id"]].append((r["event_order"],r["dora_type"],norm(r["dora_indicator_tile"])))
for r in con.execute("""
 SELECT e.kyoku_id,e.event_order,e.id AS tenpai_event_id,e.type AS event_type,
        pts.player_id,pts.waiting_tiles,pts.available_tile_count,
        pts.dora_indicator_tile_count
 FROM player_tenpai_state pts JOIN event e ON e.id=pts.event_id
 WHERE pts.is_actor=1
 ORDER BY e.kyoku_id,pts.player_id,e.event_order,e.id
"""):
 ky=r["kyoku_id"]
 if ky in exhaust and r["player_id"] not in first[ky]:
  first[ky][r["player_id"]]=dict(r)

stats=Counter();rowbyplayer=defaultdict(Counter);profiles=Counter();samples=[];anomalies=[]
for ky,terminal in endby.items():
 initial_hand=Counter(hand[ky])
 dlist=sorted(draws[ky])
 dora=sorted(doras[ky])
 endcounts=initial_hand+Counter(t for _,t,_ in dlist)
 residual=base-endcounts
 assert sum(residual.values())==14,(ky,sum(residual.values()))
 assert all(endcounts[t]<=4 for t in endcounts)
 end_dora=Counter(t for _,typ,t in dora if typ=="omote")
 for pid,ini in first[ky].items():
  z=terminal.get(pid)
  if z is None:
   stats["missing_terminal_player"]+=1
   continue
  waits=set(tiles(ini["waiting_tiles"]))
  curwait=set(tiles(z["waiting_tiles"])) if z["is_tenpai"]==1 else set()
  final_physical=sum(residual[t] for t in waits)
  final_visible=sum(end_dora[t] for t in waits)
  final_hidden=final_physical-final_visible
  reconstructed_current=sum(residual[t] for t in curwait)
  current_dora=sum(end_dora[t] for t in curwait)
  if z["is_tenpai"]==1:
   if reconstructed_current != z["available_tile_count"]+z["dora_indicator_tile_count"]:
    stats["terminal_reconstruction_not_equal_available_plus_dora"]+=1
    if len(anomalies)<20:anomalies.append({"kyoku_id":ky,"player":pid,"type":"terminal_dora_relation","reconstructed":reconstructed_current,"db_available":z["available_tile_count"],"db_dora":z["dora_indicator_tile_count"],"actual_dora":current_dora})
   if current_dora!=z["dora_indicator_tile_count"]:
    stats["terminal_dora_indicator_discrepancy"]+=1
  recent_dora=Counter(t for order,typ,t in dora if order<=ini["event_order"] and typ=="omote")
  already_drawn=Counter(t for order,t,_ in dlist if order<ini["event_order"])
  initial_unseen=base-(initial_hand+already_drawn)
  den_physical=sum(initial_unseen[t] for t in waits)
  den_visible=sum(recent_dora[t] for t in waits)
  den_hidden=den_physical-den_visible
  den_db=ini["available_tile_count"]
  den_db_dora=ini["dora_indicator_tile_count"]
  stats["tracked_first_tenpai"]+=1
  if z["is_tenpai"]!=1:stats["ended_noten"]+=1
  elif waits!=curwait:stats["wait_changed"]+=1
  else:stats["same_wait"]+=1
  if den_physical<final_physical:
    stats["physical_ratio_over_100"]+=1
  if den_physical==0:stats["physical_den_zero"]+=1
  if den_db==0:stats["db_available_zero"]+=1
  if den_db<final_hidden:stats["db_available_less_than_final_hidden"]+=1
  if den_hidden!=den_db:
    stats["initial_hidden_vs_db_mismatch"]+=1
    profiles[(den_hidden-den_db)]+=1
  if den_physical!=den_db:
    stats["initial_physical_vs_db_mismatch"]+=1
  if final_hidden<0:stats["terminal_hidden_negative"]+=1
  if den_hidden<0:stats["initial_hidden_negative"]+=1
  row=rowbyplayer[pid]
  row["tenpai_count"]+=1
  row["original_wait_total_initial_physical"]+=den_physical
  row["original_wait_total_final_physical"]+=final_physical
  row["original_wait_total_initial_hidden"]+=den_hidden
  row["original_wait_total_final_hidden"]+=final_hidden
  row["same_wait_count"]+=waits==curwait
  row["changed_wait_count"]+=waits!=curwait
  row["initial_db_count"]+=den_db
  row["final_dora_wait_count"]+=final_visible
  if len(samples)<45 and ((den_db==0 and final_hidden>0) or (den_db<final_hidden) or (len(samples)<10 and waits!=curwait) or (den_physical==5 and final_physical==4)):
    samples.append({"kyoku_id":ky,"pid":pid,"first_waits":ini["waiting_tiles"],"last_waits":z["waiting_tiles"],
    "den_physical":den_physical,"den_hidden":den_hidden,"den_db_available":den_db,"den_db_dora":den_db_dora,
    "final_physical":final_physical,"final_hidden":final_hidden,"final_visible_dora":final_visible,"ratio":round(100*final_physical/den_physical,3) if den_physical else None})

summary={"sqlite_check":"ok","exhaustive_draws":len(exhaust),"eligible_tenpai":stats["tracked_first_tenpai"],
"stats":dict(stats),"db_hidden_minus_model_distribution":dict(profiles),"sample_cases":samples,
"terminal_mismatches":anomalies}
rows=[]
for pid,r in rowbyplayer.items():
  rows.append({"player_id":pid,**dict(r),
   "weighted_physical_dead_wall_pct":round(100*r["original_wait_total_final_physical"]/r["original_wait_total_initial_physical"],4) if r["original_wait_total_initial_physical"] else None,
   "weighted_non_dora_dead_wall_pct":round(100*r["original_wait_total_final_hidden"]/r["original_wait_total_initial_hidden"],4) if r["original_wait_total_initial_hidden"] else None})
rows.sort(key=lambda x:(-(x["weighted_physical_dead_wall_pct"] or 0),-x["tenpai_count"]))
dump_csv("dead_wall_original_wait_audit_players.csv",rows)
(out/"dead_wall_original_wait_audit.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print("AUDIT",json.dumps({k:v for k,v in summary.items() if k not in ("sample_cases","terminal_mismatches")},ensure_ascii=False),flush=True)
print("SAMPLES",json.dumps(samples[:25],ensure_ascii=False),flush=True)
print("MISMATCHES",json.dumps(anomalies[:10],ensure_ascii=False),flush=True)
print("TOP10_PROVISIONAL",json.dumps(rows[:10],ensure_ascii=False),flush=True)
