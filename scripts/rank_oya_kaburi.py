"""Run oya-kaburi v0.1 and independently audit counts and parent payments."""
from pathlib import Path
from collections import Counter
import csv,json,sqlite3,os,sys,math

conn=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
conn.row_factory=sqlite3.Row
source=Path(__file__).resolve().parents[1]/"sql/oya_kaburi_rate_index_v01.sql"
sql=source.read_text(encoding="utf-8")
out=Path("results")
out.mkdir(exist_ok=True)

def query(sql):
 return [dict(r) for r in conn.execute(sql)]

def write_json(name,val):
 (out/name).write_text(json.dumps(val,ensure_ascii=False,indent=2),encoding="utf-8")

def write_csv(name,rows):
 if not rows: return
 with (out/name).open("w",newline="",encoding="utf-8-sig") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]))
  w.writeheader();w.writerows(rows)

assert conn.execute("PRAGMA quick_check").fetchone()[0]=="ok"
rows=query(sql)
if not rows: raise RuntimeError("Main SQL returned no player rows")
write_csv("oya_kaburi_all_players.csv",rows)
write_json("oya_kaburi_index_top10.json",rows[:10])
write_json("oya_kaburi_total_loss_top10.json",
           sorted(rows,key=lambda x:(-x["kaburi_total_loss_points"],x["player_name"]))[:10])
total_oya=sum(i["oya_kyoku_count"] for i in rows)
total_hit=sum(i["kaburi_count"] for i in rows)
total_loss=sum(i["kaburi_total_loss_points"] for i in rows)
kyoku_total=conn.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]
parent_event=conn.execute("""
 SELECT COUNT(*) AS events,COUNT(DISTINCT e.kyoku_id) AS rounds
 FROM event e
 JOIN agari_event a ON a.event_id=e.id
 JOIN kyoku k ON k.id=e.kyoku_id
 WHERE e.type='tsumo' AND a.actor_player_id<>k.oya_player_id
""").fetchone()
assert total_oya==kyoku_total,(total_oya,kyoku_total)
assert total_hit==parent_event["rounds"],(total_hit,dict(parent_event))
assert parent_event["rounds"]==parent_event["events"],dict(parent_event)
for r in rows:
 assert 0<=r["kaburi_count"]<=r["oya_kyoku_count"],r
 rate=100*r["kaburi_count"]/r["oya_kyoku_count"]
 index=rate/(100*total_hit/total_oya)*100
 assert abs(rate-r["kaburi_pct"])<.000051,r
 assert abs(index-r["kaburi_index"])<.00501,r

# Independent audit: reconstruct parental cash outflow from before/after scores
# and independently derive child's tsumo payment from hand base points.
audit_sql="""
WITH ranked AS (
 SELECT k.id AS kyoku_id,k.game_id,k.honba_count,
        k.oya_player_id AS parent_player_id,kpr.player_id,
        kpr.score,LAG(kpr.score) OVER (
          PARTITION BY k.game_id,kpr.player_id ORDER BY k.id
        ) AS previous_score
 FROM kyoku k JOIN kyoku_player_result kpr ON kpr.kyoku_id=k.id
),
oya AS (
 SELECT * FROM ranked WHERE parent_player_id=player_id
),
reach_cost AS (
 SELECT e.kyoku_id,r.actor_player_id AS player_id,
        SUM(CASE WHEN r.is_accepted=1 THEN 1 ELSE 0 END) AS accepted
 FROM event e JOIN reach_event r ON r.event_id=e.id
 GROUP BY e.kyoku_id,r.actor_player_id
)
SELECT o.kyoku_id,o.game_id,o.honba_count,o.parent_player_id,
       o.previous_score,o.score,
       e.id AS win_event_id,a.actor_player_id AS winner_id,
       a.agari_points,a.honba_points,a.han,a.fu,a.is_yakuman,
       COALESCE(rc.accepted,0) AS parent_accepted_reach,
       COALESCE(o.previous_score,25000)-o.score-
         1000*COALESCE(rc.accepted,0) AS actual_parent_payment
FROM oya o
JOIN event e ON e.kyoku_id=o.kyoku_id AND e.type='tsumo'
JOIN agari_event a ON a.event_id=e.id
LEFT JOIN reach_cost rc ON rc.kyoku_id=o.kyoku_id
                       AND rc.player_id=o.parent_player_id
WHERE a.actor_player_id<>o.parent_player_id
ORDER BY o.kyoku_id
"""
events=query(audit_sql)
assert len(events)==total_hit

def base_points(e):
 # For non-yakuman use standard capped mahjong payments.
 # Kazoe yakuman is absent per source schema; han>=11 is sanbaiman.
 if e["is_yakuman"]:
  return e["agari_points"]//4
 han=e["han"]
 if han>=11: return 6000
 if han>=8: return 4000
 if han>=6: return 3000
 if han>=5: return 2000
 raw=e["fu"]*(2**(han+2))
 # M-League kiriage mangan: 4han/30fu and 3han/60fu (1920 base)
 # are rounded up to mangan before dividing into payments.
 return 2000 if raw>=1920 else raw

bad=[]
by_payer=Counter()
for e in events:
 b=base_points(e)
 dealer=100*math.ceil(2*b/100)
 child=100*math.ceil(b/100)
 expected_agari=dealer+2*child
 expected_parent=dealer+e["honba_points"]//3
 if (expected_agari!=e["agari_points"] or
     expected_parent!=e["actual_parent_payment"] or
     e["actual_parent_payment"]<=0 or e["actual_parent_payment"]%100!=0 or
     e["honba_points"]%300!=0):
  bad.append({**e,"expected_agari_points":expected_agari,
              "expected_parent_payment":expected_parent})
 by_payer[e["parent_player_id"]]+=e["actual_parent_payment"]
write_csv("oya_kaburi_payment_mismatches.csv",bad)
summary={
 "sqlite_quick_check":"ok",
 "players":len(rows),
 "oya_kyoku_count":total_oya,
 "kyoku_count":kyoku_total,
 "kaburi_kyoku_count":total_hit,
 "independent_parent_tsumo_events":parent_event["events"],
 "league_kaburi_rate_pct":round(100*total_hit/total_oya,4),
 "kaburi_total_loss_points":total_loss,
 "audited_payments":len(events),
 "payment_score_vs_hand_mismatches":len(bad),
 "player_loss_mismatches":[r["player_name"] for r in rows if by_payer[r["player_id"]]!=r["kaburi_total_loss_points"]],
}
# Check an independently selected prior season/stage, without assuming historical expected counts.
for year,stage in [(2025,"regular"),(2026,"regular")]:
 sample=query(sql.replace("SELECT NULL AS start_year, NULL AS stage",
                           f"SELECT {year} AS start_year, '{stage}' AS stage"))
 if not sample: continue
 sub_oya=sum(x["oya_kyoku_count"] for x in sample)
 sub_kaburi=sum(x["kaburi_count"] for x in sample)
 independent=conn.execute("""
 SELECT (SELECT COUNT(k.id) FROM kyoku k
 JOIN game g ON g.id=k.game_id
 JOIN season_stage s ON s.id=g.season_stage_id
 JOIN league_season l ON l.id=s.league_season_id
 WHERE l.start_year=? AND s.stage=?) AS oya,
 (SELECT COUNT(DISTINCT e.kyoku_id) FROM event e
 JOIN agari_event a ON a.event_id=e.id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage s ON s.id=g.season_stage_id
 JOIN league_season l ON l.id=s.league_season_id
 WHERE e.type='tsumo' AND a.actor_player_id<>k.oya_player_id
 AND l.start_year=? AND s.stage=?) AS kaburi
 """,(year,stage,year,stage)).fetchone()
 assert (sub_oya,sub_kaburi)==tuple(independent),(year,sub_oya,sub_kaburi,tuple(independent))
 summary[f"{year}_{stage}"]={"oya_kyoku_count":sub_oya,"kaburi_count":sub_kaburi}
write_json("oya_kaburi_verification.json",summary)
print("VERIFICATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10",json.dumps(rows[:10],ensure_ascii=False),flush=True)
if bad:
 print("PAYMENT MISMATCH EXAMPLES",json.dumps(bad[:10],ensure_ascii=False),flush=True)
if bad or summary["player_loss_mismatches"]:
 raise RuntimeError("Payment audit mismatches: "+str(len(bad))+
                    " players: "+str(summary["player_loss_mismatches"]))
print("VALIDATED independent event counts, rates, indices and score+hand payments",flush=True)
