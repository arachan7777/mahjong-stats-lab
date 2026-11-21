"""Validate tsumo share among agari events by independent row/type audits."""
from pathlib import Path
import os,sqlite3,csv,json,sys
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
root=Path(__file__).resolve().parents[1]
sql=(root/"sql/tsumo_share_v01.sql").read_text(encoding="utf-8")
out=Path("results");out.mkdir(exist_ok=True)
def query(q,args=()):
 return [dict(x) for x in con.execute(q,args)]
def save(name,rows):
 if not rows:return
 with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0]))
  writer.writeheader();writer.writerows(rows)
def json_save(name,x):
 (out/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
results=query(sql)
assert results,"SQL returned no wins"
save("tsumo_share_all_players.csv",results)
json_save("tsumo_share_top10.json",results[:10])
counts={"all":sum(r["all_agari_count"] for r in results),
        "tsumo":sum(r["tsumo_agari_count"] for r in results),
        "ron":sum(r["ron_agari_count"] for r in results)}
independent=query("""
 SELECT COUNT(*) AS all_agari,
        SUM(CASE WHEN a.target_player_id IS NULL THEN 1 ELSE 0 END) AS null_target,
        SUM(CASE WHEN a.target_player_id IS NOT NULL THEN 1 ELSE 0 END) AS has_target,
        SUM(CASE WHEN e.type='tsumo' THEN 1 ELSE 0 END) AS tsumo_event,
        SUM(CASE WHEN e.type='ron' THEN 1 ELSE 0 END) AS ron_event,
        SUM(CASE WHEN e.type NOT IN('tsumo','ron') THEN 1 ELSE 0 END) AS invalid_event_type,
        SUM(CASE WHEN e.type='tsumo' AND a.target_player_id IS NOT NULL THEN 1
                 WHEN e.type='ron' AND a.target_player_id IS NULL THEN 1 ELSE 0 END) AS type_target_mismatch,
        SUM(CASE WHEN gpr.player_id IS NULL THEN 1 ELSE 0 END) AS winner_not_in_game
 FROM agari_event a
 JOIN event e ON e.id=a.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game_player_result gpr_check ON gpr_check.game_id=k.game_id
                            AND gpr_check.player_id=k.oya_player_id
 LEFT JOIN game_player_result gpr ON gpr.game_id=k.game_id
                            AND gpr.player_id=a.actor_player_id
""")[0]
assert independent["invalid_event_type"]==0,independent
assert independent["type_target_mismatch"]==0,independent
assert independent["winner_not_in_game"]==0,independent
assert counts["all"]==independent["all_agari"],(counts,independent)
assert counts["tsumo"]==independent["null_target"]==independent["tsumo_event"],(counts,independent)
assert counts["ron"]==independent["has_target"]==independent["ron_event"],(counts,independent)
per_player=query("""
 SELECT a.actor_player_id AS player_id,
        COUNT(*) AS all_wins,
        SUM(CASE WHEN a.target_player_id IS NULL THEN 1 ELSE 0 END) AS tsumo_wins,
        SUM(CASE WHEN a.target_player_id IS NOT NULL THEN 1 ELSE 0 END) AS ron_wins
 FROM agari_event a GROUP BY a.actor_player_id
""")
baseline={r["player_id"]:r for r in per_player}
assert len(results)==len(baseline)
for r in results:
 b=baseline[r["player_id"]]
 assert (r["all_agari_count"],r["tsumo_agari_count"],r["ron_agari_count"])==(b["all_wins"],b["tsumo_wins"],b["ron_wins"]),(r,b)
 assert r["all_agari_count"]==r["tsumo_agari_count"]+r["ron_agari_count"]
 rate=round(100*r["tsumo_agari_count"]/r["all_agari_count"],4)
 assert abs(rate-r["tsumo_share_pct"])<.00006,r
 assert abs(r["tsumo_share_pct"]+r["ron_share_pct"]-100)<.00011,r

multi_ron=query("""
 SELECT COUNT(*) AS multi_ron_kyoku,COALESCE(SUM(ron_count),0) AS ron_wins_in_multi_ron
 FROM (
   SELECT e.kyoku_id,COUNT(*) AS ron_count
   FROM event e
   WHERE e.type='ron'
   GROUP BY e.kyoku_id HAVING COUNT(*)>=2
 )
""")[0]
sub={}
for year,stage in [(2025,"regular"),(2026,"regular")]:
 sub_sql=sql.replace("SELECT NULL AS start_year, NULL AS stage",f"SELECT {year} AS start_year, '{stage}' AS stage")
 rows=query(sub_sql)
 if not rows:continue
 sub_all=sum(r["all_agari_count"] for r in rows)
 sub_tsumo=sum(r["tsumo_agari_count"] for r in rows)
 check=query("""
 SELECT COUNT(*) AS n,
        SUM(CASE WHEN e.type='tsumo' THEN 1 ELSE 0 END) AS t,
        SUM(CASE WHEN e.type='ron' THEN 1 ELSE 0 END) AS r
 FROM agari_event a
 JOIN event e ON e.id=a.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE ls.start_year=? AND ss.stage=?
 """,(year,stage))[0]
 assert sub_all==check["n"] and sub_tsumo==check["t"],(year,sub_all,sub_tsumo,check)
 sub[f"{year}_{stage}"]=check
 save(f"tsumo_share_{year}_{stage}.csv",rows)
summary={"sqlite_quick_check":"ok","players":len(results),
         "all_wins":counts["all"],"tsumo_wins":counts["tsumo"],"ron_wins":counts["ron"],
         "tsumo_share_pct":round(100*counts["tsumo"]/counts["all"],4),
         "independent":independent,"multi_ron":multi_ron,"subsets":sub}
json_save("tsumo_share_verification.json",summary)
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10",json.dumps(results[:10],ensure_ascii=False),flush=True)
