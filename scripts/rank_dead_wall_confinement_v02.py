"""独立検算：流局時の王牌幽閉率 v0.2（待ち替えのたび加算、残0枚除外）。

SQLから一切の中間集計を流用せず、牌種ごとに牌譜を再構築して、
各待ち変更時の残枚数、流局時の元待ち牌の王牌枚数を比較する。
"""
import csv,json,os,sqlite3,sys
from collections import Counter,defaultdict
from pathlib import Path

db=os.path.abspath(sys.argv[1])
con=sqlite3.connect("file:"+db+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA temp_store=MEMORY")
output=Path("results")
output.mkdir(exist_ok=True)
def get(query,params=()):
    return [dict(row) for row in con.execute(query,params)]
def norm(t):
    t=t.strip()
    if t.startswith("t"):t=t[1:]
    if t and t[0]=="0":t="5"+t[1:]
    return t
def split(tiles):
    return [norm(t) for t in tiles.split(",") if t.strip()]
def write(name,rows):
    if not rows:return
    with (output/name).open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=rows[0])
        w.writeheader();w.writerows(rows)

base=Counter({f"{i}{s}":4 for s in "mps" for i in range(1,10)})
base.update({f"{i}z":4 for i in range(1,8)})
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
draw_kyokus={r["kyoku_id"] for r in get("""
  SELECT e.kyoku_id FROM ryukyoku_event r JOIN event e ON e.id=r.event_id
""")}
hands=defaultdict(Counter)
drawn=defaultdict(list)
dora=defaultdict(list)
state=defaultdict(lambda:defaultdict(list))
for row in con.execute("SELECT e.kyoku_id,h.hand FROM haipai_event h JOIN event e ON e.id=h.event_id"):
    if row["kyoku_id"] in draw_kyokus:
        hands[row["kyoku_id"]].update(split(row["hand"]))
for row in con.execute("""
    SELECT e.kyoku_id,e.event_order,d.tile
    FROM draw_event d JOIN event e ON e.id=d.event_id
"""):
    if row["kyoku_id"] in draw_kyokus:
        drawn[row["kyoku_id"]].append((row["event_order"],norm(row["tile"])))
for row in con.execute("""
    SELECT e.kyoku_id,e.event_order,d.dora_indicator_tile
    FROM dora_indicator_event d JOIN event e ON e.id=d.event_id
    WHERE d.dora_type='omote'
"""):
    if row["kyoku_id"] in draw_kyokus:
        dora[row["kyoku_id"]].append((row["event_order"],norm(row["dora_indicator_tile"])))
for row in con.execute("""
    SELECT e.kyoku_id,e.id AS event_id,e.event_order,pts.player_id,
           pts.waiting_tiles,pts.available_tile_count,pts.dora_indicator_tile_count
    FROM player_tenpai_state pts JOIN event e ON e.id=pts.event_id
    WHERE pts.is_actor=1
    ORDER BY e.kyoku_id,pts.player_id,e.event_order,e.id
"""):
    if row["kyoku_id"] in draw_kyokus:
        state[row["kyoku_id"]][row["player_id"]].append(dict(row))

all_cases={}
counter=Counter()
per_player=defaultdict(Counter)
sample=[]
all_snapshots=0
first_count=0
for ky in sorted(draw_kyokus):
    hand=hands[ky]
    draws=sorted(drawn[ky])
    dora_events=sorted(dora[ky])
    remaining=base-(hand+Counter(t for _,t in draws))
    assert sum(remaining.values())==14,(ky,sum(remaining.values()))
    assert all(hand[t]+sum(1 for _,x in draws if x==t)<=4 for t in base)
    counter["draw_kyoku"]+=1
    final_dora=Counter(t for _,t in dora_events)
    for player_id,snaps in state[ky].items():
        prior_wait=None
        episode_idx=0
        for snap in snaps:
            all_snapshots+=1
            waits=frozenset(split(snap["waiting_tiles"]))
            assert len(waits)==len(split(snap["waiting_tiles"]))
            if waits==prior_wait:
                counter["duplicate_same_wait_snapshot"]+=1
                continue
            prior_wait=waits
            episode_idx+=1
            counter["wait_transitions_raw"]+=1
            if episode_idx==1:
                first_count+=1
            else:
                counter["nonfirst_wait_transitions"]+=1
            previous_draw=Counter(t for order,t in draws if order<snap["event_order"])
            initial_unseen=base-(hand+previous_draw)
            denominator=sum(initial_unseen[t] for t in waits)
            numerator=sum(remaining[t] for t in waits)
            initial_dora=sum(1 for order,t in dora_events if order<=snap["event_order"] and t in waits)
            final_dora_waits=sum(final_dora[t] for t in waits)
            assert denominator>=numerator>=0,(ky,player_id,denominator,numerator)
            assert denominator>=initial_dora and numerator>=final_dora_waits
            assert denominator-initial_dora==snap["available_tile_count"],(ky,player_id,denominator,initial_dora,snap["available_tile_count"])
            assert initial_dora==snap["dora_indicator_tile_count"],(ky,player_id,initial_dora,snap["dora_indicator_tile_count"])
            if denominator==0:
                assert numerator==0
                counter["excluded_zero_remaining"]+=1
                continue
            counter["eligible_wait_episodes"]+=1
            key=(ky,player_id,snap["event_id"])
            all_cases[key]=(denominator,numerator,initial_dora,final_dora_waits)
            pp=per_player[player_id]
            pp["wait_change_episode_count"]+=1
            pp["initial_wait_tiles_total"]+=denominator
            pp["dead_wall_wait_tiles_total"]+=numerator
            pp["initial_dora_indicator_wait_tiles"]+=initial_dora
            pp["final_dora_indicator_wait_tiles"]+=final_dora_waits
            # Count unique kyoku separately, not total waiting episodes.
            if "kyokus" not in pp: pp["kyokus"]=set()
            pp["kyokus"].add(ky)
            if len(sample)<20 and (episode_idx>=2 or (denominator==5 and numerator==4)):
                sample.append({"kyoku":ky,"player_id":player_id,"episode":episode_idx,
                               "wait":",".join(sorted(waits)),"remaining_when_tenpai":denominator,
                               "dead_wall_original_wait":numerator,"pct":round(100*numerator/denominator,4)})

sql=(Path(__file__).resolve().parents[1]/"sql/dead_wall_confinement_v02.sql").read_text(encoding="utf-8")
sql_rows=get(sql)
assert sql_rows,"SQL has no output"
# Extract the per-episode CTE from the production SQL, then verify EVERY episode.
final_start=sql.index("SELECT p.id AS player_id,p.name AS player_name")
episode_sql=sql[:final_start]+"""
SELECT kyoku_id,player_id,wait_event_id,initial_wait_tiles,dead_wall_wait_tiles,
       initial_dora_indicators,final_dora_indicators
FROM eligible_episodes
ORDER BY kyoku_id,player_id,wait_event_id
"""
source_cases=get(episode_sql)
seen=set()
for q in source_cases:
    key=(q["kyoku_id"],q["player_id"],q["wait_event_id"])
    assert key not in seen,key
    seen.add(key)
    expected=all_cases.get(key)
    assert expected is not None,("extra_sql_episode",q)
    actual=(q["initial_wait_tiles"],q["dead_wall_wait_tiles"],q["initial_dora_indicators"],q["final_dora_indicators"])
    assert actual==expected,("case_mismatch",key,actual,expected)
assert seen==set(all_cases),("missing_sql_episodes",len(all_cases),len(seen))

assert len(sql_rows)==len(per_player)==56,(len(sql_rows),len(per_player))
all_den=all_num=all_dora_initial=all_dora_final=all_events=0
for q in sql_rows:
    p=per_player[q["player_id"]]
    vals=["eligible_exhaustive_draw_kyoku","wait_change_episode_count","initial_wait_tiles_total","dead_wall_wait_tiles_total",
          "initial_dora_indicator_wait_tiles","final_dora_indicator_wait_tiles"]
    expected=[len(p["kyokus"]),p["wait_change_episode_count"],p["initial_wait_tiles_total"],p["dead_wall_wait_tiles_total"],
              p["initial_dora_indicator_wait_tiles"],p["final_dora_indicator_wait_tiles"]]
    for field,x in zip(vals,expected):
        assert q[field]==x,("player_mismatch",q["player_name"],field,q[field],x)
    assert abs(q["dead_wall_confinement_pct"]-round(100*p["dead_wall_wait_tiles_total"]/p["initial_wait_tiles_total"],4))<0.00006
    all_den+=p["initial_wait_tiles_total"]
    all_num+=p["dead_wall_wait_tiles_total"]
    all_dora_initial+=p["initial_dora_indicator_wait_tiles"]
    all_dora_final+=p["final_dora_indicator_wait_tiles"]
    all_events+=p["wait_change_episode_count"]
assert all_events==len(all_cases)==counter["eligible_wait_episodes"]
assert counter["duplicate_same_wait_snapshot"]+counter["wait_transitions_raw"]==all_snapshots
assert counter["excluded_zero_remaining"]+counter["eligible_wait_episodes"]==counter["wait_transitions_raw"]

write("dead_wall_confinement_v02_all_players.csv",sql_rows)
write("dead_wall_confinement_v02_episodes.csv",source_cases)
summary={
  "integrity":"ok","players":len(sql_rows),"draw_kyoku":len(draw_kyokus),
  "first_tenpai_episodes":first_count,
  "different_wait_transitions":counter["nonfirst_wait_transitions"],
  "eligible_wait_change_episodes":all_events,
  "excluded_zero_remaining":counter["excluded_zero_remaining"],
  "same_wait_snapshots_not_double_counted":counter["duplicate_same_wait_snapshot"],
  "verified_every_episode_against_python":len(seen),
  "initial_wait_tiles_total":all_den,"dead_wall_wait_tiles_total":all_num,
  "league_weighted_confinement_pct":round(100*all_num/all_den,4),
  "initial_dora_indicator_wait_tiles":all_dora_initial,
  "final_dora_indicator_wait_tiles":all_dora_final,
  "league_weighted_non_indicator_pct":round(100*(all_num-all_dora_final)/(all_den-all_dora_initial),4),
  "example_transition_cases":sample,
}
(output/"dead_wall_confinement_v02_verification.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
(output/"dead_wall_confinement_v02_top10.json").write_text(json.dumps(sql_rows[:10],ensure_ascii=False,indent=2),encoding="utf-8")
print("VALIDATION",json.dumps({k:v for k,v in summary.items() if k!="example_transition_cases"},ensure_ascii=False),flush=True)
print("TOP10",json.dumps(sql_rows[:10],ensure_ascii=False),flush=True)
print("EXAMPLE_CASES",json.dumps(sample[:12],ensure_ascii=False),flush=True)
