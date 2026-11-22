"""リーチ王牌幽閉率 v0.1 独立検証。
流局に至った成立リーチの宣言打牌時の待ちを固定し、
配牌・ツモ・ドラ表示を別集計してSQLの各リーチと照合する。
"""
import csv,json,os,sqlite3,sys
from collections import Counter,defaultdict
from pathlib import Path

con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA temp_store=MEMORY")
out=Path("results");out.mkdir(exist_ok=True)
root=Path(__file__).resolve().parents[1]

def query(s,params=()): return [dict(z) for z in con.execute(s,params)]
def savecsv(file,rows):
 if not rows:return
 with (out/file).open("w",newline="",encoding="utf-8-sig") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def savejson(file,obj):
 (out/file).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
def norm(t):
 t=t.strip()
 if t.startswith("t"): t=t[1:]
 if t and t[0]=="0": t="5"+t[1:]
 return t
def tiles(s): return [norm(t) for t in s.split(",") if t.strip()]

base=Counter({f"{n}{s}":4 for s in "mps" for n in range(1,10)})
base.update({f"{n}z":4 for n in range(1,8)})
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"

exhaust={r["kyoku_id"] for r in query("""
 SELECT e.kyoku_id FROM ryukyoku_event re JOIN event e ON e.id=re.event_id
""")}
hands=defaultdict(Counter);draws=defaultdict(list);doras=defaultdict(list)
for r in con.execute("SELECT e.kyoku_id,h.hand FROM haipai_event h JOIN event e ON e.id=h.event_id"):
 if r["kyoku_id"] in exhaust:hands[r["kyoku_id"]].update(tiles(r["hand"]))
for r in con.execute("""
 SELECT e.kyoku_id,e.event_order,d.tile
 FROM draw_event d JOIN event e ON e.id=d.event_id
"""):
 if r["kyoku_id"] in exhaust:draws[r["kyoku_id"]].append((r["event_order"],norm(r["tile"])))
for r in con.execute("""
 SELECT e.kyoku_id,e.event_order,d.dora_indicator_tile
 FROM dora_indicator_event d JOIN event e ON e.id=d.event_id
 WHERE d.dora_type='omote'
"""):
 if r["kyoku_id"] in exhaust:doras[r["kyoku_id"]].append((r["event_order"],norm(r["dora_indicator_tile"])))

# Find all actual accepted reach events in ryukyoku kyoku, independently of the flag.
accepted=query("""
 SELECT re.kyoku_id,re.id AS reach_event_id,re.event_order AS reach_order,
        r.actor_player_id AS player_id
 FROM reach_event r JOIN event re ON re.id=r.event_id
 JOIN ryukyoku_event ry JOIN event ye ON ye.id=ry.event_id
   ON ye.kyoku_id=re.kyoku_id
 WHERE r.is_accepted=1
 ORDER BY re.kyoku_id,re.event_order
""")
# Correspond each accepted reach to its own flagged declaration discard.
flags=query("""
 SELECT e.kyoku_id,e.id AS discard_event_id,e.event_order AS discard_order,
        d.actor_player_id AS player_id,
        pts.waiting_tiles,pts.available_tile_count,pts.dora_indicator_tile_count,
        pts.is_actor
 FROM discard_event d JOIN event e ON e.id=d.event_id
 JOIN ryukyoku_event ry JOIN event ye ON ye.id=ry.event_id
   ON ye.kyoku_id=e.kyoku_id
 LEFT JOIN player_tenpai_state pts
     ON pts.event_id=e.id AND pts.player_id=d.actor_player_id
 WHERE d.is_reach_declaration=1
 ORDER BY e.kyoku_id,e.event_order
""")
fmap=defaultdict(list)
for r in flags:fmap[(r["kyoku_id"],r["player_id"])].append(r)
counter=Counter()
cases={};examples=[];player=defaultdict(Counter)
for r in accepted:
 counter["accepted_reach_in_draw"]+=1
 arr=[x for x in fmap.get((r["kyoku_id"],r["player_id"]),[]) if x["discard_order"]>r["reach_order"]]
 assert len(arr)==1,("accepted_event_without_one_declaration",r,arr)
 d=arr[0]
 assert d["is_actor"]==1 and d["waiting_tiles"] not in (None,""),("no_declaration_tenpai_snapshot",r,d)
 counter["accepted_flagged_declarations"]+=1
 ky=r["kyoku_id"]
 hand=hands[ky];draw=draws[ky]
 rem=base-(hand+Counter(t for _,t in draw))
 assert sum(rem.values())==14,(ky,sum(rem.values()))
 waits=set(tiles(d["waiting_tiles"]))
 assert waits
 initial=base-(hand+Counter(t for order,t in draw if order<d["discard_order"]))
 den=sum(initial[t] for t in waits)
 num=sum(rem[t] for t in waits)
 dora_start=sum(t in waits for order,t in doras[ky] if order<=d["discard_order"])
 dora_end=sum(t in waits for order,t in doras[ky])
 assert 0<=num<=den,(r,d,den,num)
 assert den-dora_start==d["available_tile_count"],(ky,r["player_id"],den,dora_start,d["available_tile_count"])
 assert dora_start==d["dora_indicator_tile_count"],(ky,r["player_id"],dora_start,d["dora_indicator_tile_count"])
 if den==0:
  assert num==0,(r,d)
  counter["excluded_zero_remaining_reach"]+=1
  continue
 key=(ky,r["player_id"],d["discard_event_id"])
 assert key not in cases,key
 cases[key]=(den,num,dora_start,dora_end)
 p=player[r["player_id"]]
 p["accepted_reach_ryukyoku_count"]+=1
 p["remaining_when_reached_total"]+=den
 p["dead_wall_reach_wait_tiles_total"]+=num
 p["initial_dora_indicator_wait_tiles"]+=dora_start
 p["final_dora_indicator_wait_tiles"]+=dora_end
 counter["eligible_reach_kyoku"]+=1
 if len(examples)<20:
  examples.append({"kyoku_id":ky,"player_id":r["player_id"],"wait":",".join(sorted(waits)),
                   "den":den,"num":num,"pct":round(100*num/den,4)})

# Every accepted reach with a ryukyoku has one declaration; no different flagged count.
assert len(flags)==len(accepted)==counter["accepted_flagged_declarations"],(len(flags),len(accepted))
sql=(root/"sql/reach_dead_wall_confinement_v01.sql").read_text(encoding="utf-8")
start=sql.index("SELECT p.id AS player_id,p.name AS player_name")
by_episode=sql[:start]+"""
SELECT kyoku_id,player_id,wait_event_id,remaining_when_reached,
       dead_wall_reach_wait_tiles,initial_dora_indicators,final_dora_indicators
FROM eligible_reaches
ORDER BY kyoku_id,player_id,wait_event_id
"""
sql_episodes=query(by_episode)
seen=set()
for x in sql_episodes:
 key=(x["kyoku_id"],x["player_id"],x["wait_event_id"])
 assert key not in seen,key
 seen.add(key)
 assert key in cases,("sql_episode_not_found_python",x)
 assert (x["remaining_when_reached"],x["dead_wall_reach_wait_tiles"],
         x["initial_dora_indicators"],x["final_dora_indicators"])==cases[key],("episode_disagreement",x,cases[key])
assert seen==set(cases),("episodes_missing",len(seen),len(cases))

rows=query(sql)
assert rows,("no_ranking",counter)
assert len(rows)==len(player),(len(rows),len(player))
totals=Counter()
for r in rows:
 exp=player[r["player_id"]]
 for col in ("accepted_reach_ryukyoku_count","remaining_when_reached_total",
             "dead_wall_reach_wait_tiles_total","initial_dora_indicator_wait_tiles","final_dora_indicator_wait_tiles"):
  assert r[col]==exp[col],("player_disagreement",r["player_name"],col,r[col],exp[col])
  totals[col]+=r[col]
 assert abs(r["reach_dead_wall_confinement_pct"]-round(100*exp["dead_wall_reach_wait_tiles_total"]/exp["remaining_when_reached_total"],4))<.00006

# Confirm it is a strict subset of all accepted reaches in the database.
global_accepted=con.execute("SELECT COUNT(*) FROM reach_event WHERE is_accepted=1").fetchone()[0]
assert len(accepted)<=global_accepted
assert counter["eligible_reach_kyoku"]+counter["excluded_zero_remaining_reach"]==len(accepted)
summary={
 "sqlite_quick_check":"ok","all_ryukyoku_kyoku":len(exhaust),
 "all_accepted_reach_events_global":global_accepted,
 "accepted_reaches_at_ryukyoku":len(accepted),
 "excluded_zero_remaining_reach":counter["excluded_zero_remaining_reach"],
 "eligible_reach_kyoku":counter["eligible_reach_kyoku"],
 "independently_verified_each_reach":len(seen),
 "players":len(rows),
 "denominator_remaining_wait_tiles":totals["remaining_when_reached_total"],
 "numerator_final_dead_wall_wait_tiles":totals["dead_wall_reach_wait_tiles_total"],
 "weighted_reach_dead_wall_confinement_pct":round(100*totals["dead_wall_reach_wait_tiles_total"]/totals["remaining_when_reached_total"],4),
 "declared_reach_tenpai_dora_indicator_tiles":totals["initial_dora_indicator_wait_tiles"],
 "final_dora_indicator_wait_tiles":totals["final_dora_indicator_wait_tiles"],
 "non_indicator_pct":round(100*(totals["dead_wall_reach_wait_tiles_total"]-totals["final_dora_indicator_wait_tiles"])/(totals["remaining_when_reached_total"]-totals["initial_dora_indicator_wait_tiles"]),4),
 "examples":examples
}
savecsv("reach_dead_wall_confinement_all_players.csv",rows)
savecsv("reach_dead_wall_confinement_event_details.csv",sql_episodes)
savejson("reach_dead_wall_confinement_top10.json",rows[:10])
savejson("reach_dead_wall_confinement_verification.json",summary)
print("VALIDATION",json.dumps({k:v for k,v in summary.items() if k!="examples"},ensure_ascii=False),flush=True)
print("TOP10",json.dumps(rows[:10],ensure_ascii=False),flush=True)
print("EXAMPLES",json.dumps(examples[:5],ensure_ascii=False),flush=True)
