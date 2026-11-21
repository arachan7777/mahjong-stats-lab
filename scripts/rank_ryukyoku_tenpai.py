"""Run draw-tenpai SQL and audit per-event/per-player completeness independently."""
import csv,json,os,sqlite3,sys
from pathlib import Path
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
sql=(Path(__file__).resolve().parents[1]/"sql/ryukyoku_tenpai_rate_v01.sql").read_text(encoding="utf-8")
out=Path("results");out.mkdir(exist_ok=True)
def query(q,pars=()):
 return [dict(x) for x in con.execute(q,pars)]
def save_csv(name,rows):
 if not rows:return
 with (out/name).open("w",newline="",encoding="utf-8-sig") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]))
  w.writeheader();w.writerows(rows)
def save_json(name,x):
 (out/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")

assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
players=query(sql)
assert players,"No results"
save_csv("ryukyoku_tenpai_all_players.csv",players)
save_json("ryukyoku_tenpai_top10.json",players[:10])
tot_den=sum(x["ryukyoku_count"] for x in players)
tot_num=sum(x["tenpai_ryukyoku_count"] for x in players)
tot_noten=sum(x["noten_ryukyoku_count"] for x in players)

# Independently count raw draw events, draw participants and tenpai flags.
baseline=query("""
 SELECT (SELECT COUNT(*) FROM ryukyoku_event) AS ryukyoku_events,
        (SELECT COUNT(*) FROM event WHERE type='ryukyoku') AS ryukyoku_event_type_count,
        (SELECT COUNT(*) FROM ryukyoku_player) AS player_draw_rows,
        (SELECT COUNT(*) FROM ryukyoku_player WHERE is_tenpai=1) AS tenpai_rows,
        (SELECT COUNT(*) FROM ryukyoku_player WHERE is_tenpai=0) AS noten_rows,
        (SELECT COUNT(*) FROM ryukyoku_player WHERE is_tenpai NOT IN(0,1)
            OR is_tenpai IS NULL) AS invalid_tenpai_flags,
        (SELECT COUNT(DISTINCT e.kyoku_id)
         FROM event e JOIN ryukyoku_event r ON r.event_id=e.id) AS unique_draw_kyoku
""")[0]
assert baseline["ryukyoku_events"]==baseline["ryukyoku_event_type_count"]==baseline["unique_draw_kyoku"],baseline
assert tot_den==baseline["player_draw_rows"]==4*baseline["ryukyoku_events"],(tot_den,baseline)
assert tot_num==baseline["tenpai_rows"],(tot_num,baseline)
assert tot_noten==baseline["noten_rows"],(tot_noten,baseline)
assert tot_den==tot_num+tot_noten and baseline["invalid_tenpai_flags"]==0

# Per draw event: every one of the four game participants is present exactly once.
per_draw=query("""
 WITH re AS (
   SELECT r.event_id,e.kyoku_id,k.game_id
   FROM ryukyoku_event r
   JOIN event e ON e.id=r.event_id
   JOIN kyoku k ON k.id=e.kyoku_id
 ), audited AS (
   SELECT re.event_id,re.kyoku_id,
          COUNT(rp.player_id) AS player_rows,
          COUNT(DISTINCT rp.player_id) AS distinct_players,
          SUM(CASE WHEN gr.player_id IS NULL THEN 1 ELSE 0 END) AS missing_in_game,
          COALESCE(SUM(rp.tenpai_points),0) AS points_balance,
          SUM(CASE WHEN rp.is_tenpai=1 THEN 1 ELSE 0 END) AS tenpai_players
   FROM re
   LEFT JOIN ryukyoku_player rp ON rp.ryukyoku_event_id=re.event_id
   LEFT JOIN game_player_result gr ON gr.game_id=re.game_id
                                  AND gr.player_id=rp.player_id
   GROUP BY re.event_id,re.kyoku_id
 )
 SELECT * FROM audited
 WHERE player_rows<>4 OR distinct_players<>4 OR missing_in_game<>0
       OR points_balance<>0 OR tenpai_players NOT BETWEEN 0 AND 4
 ORDER BY kyoku_id
""")
save_csv("ryukyoku_tenpai_event_anomalies.csv",per_draw)
if per_draw: raise AssertionError("Draw event participant/balance anomalies: "+str(len(per_draw)))

for x in players:
 assert 0<=x["tenpai_ryukyoku_count"]<=x["ryukyoku_count"],x
 assert x["tenpai_ryukyoku_count"]+x["noten_ryukyoku_count"]==x["ryukyoku_count"],x
 rate=100*x["tenpai_ryukyoku_count"]/x["ryukyoku_count"]
 assert abs(rate-x["ryukyoku_tenpai_pct"])<.000051,x

# Historical subset: independent direct aggregation rather than original SQL expression.
subsets={}
for year,stage in [(2025,"regular"),(2026,"regular")]:
 ssql=sql.replace("SELECT NULL AS start_year, NULL AS stage",
                  f"SELECT {year} AS start_year, '{stage}' AS stage")
 ss=query(ssql)
 if not ss:continue
 sub_baseline=query("""
 SELECT COUNT(*) AS player_rows,
        SUM(CASE WHEN rp.is_tenpai=1 THEN 1 ELSE 0 END) AS tenpai_rows,
        COUNT(DISTINCT e.kyoku_id) AS draws
 FROM ryukyoku_player rp
 JOIN ryukyoku_event r ON r.event_id=rp.ryukyoku_event_id
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage s ON s.id=g.season_stage_id
 JOIN league_season l ON l.id=s.league_season_id
 WHERE l.start_year=? AND s.stage=?
 """,(year,stage))[0]
 assert sum(x["ryukyoku_count"] for x in ss)==sub_baseline["player_rows"]
 assert sum(x["tenpai_ryukyoku_count"] for x in ss)==sub_baseline["tenpai_rows"]
 subsets[f"{year}_{stage}"]=sub_baseline
 save_csv(f"ryukyoku_tenpai_{year}_{stage}.csv",ss)

summary={"integrity":"ok","players":len(players),
         "total_draw_kyoku":baseline["ryukyoku_events"],
         "total_player_draws":tot_den,"tenpai_player_draws":tot_num,
         "noten_player_draws":tot_noten,
         "overall_tenpai_pct":round(100*tot_num/tot_den,4),
         "event_balance_anomalies":len(per_draw),
         "independent_counts":baseline,"subsets":subsets}
save_json("ryukyoku_tenpai_verification.json",summary)
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10",json.dumps(players[:10],ensure_ascii=False),flush=True)
