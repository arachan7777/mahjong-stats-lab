"""Validate riichi declaration discard deal-in rate across all seasons and stages."""
from pathlib import Path
from collections import Counter
import csv,json,os,sqlite3,sys
db=os.path.abspath(sys.argv[1])
con=sqlite3.connect("file:"+db+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
sql=(Path(__file__).resolve().parents[1]/"sql/ricchi_ronhai_rate_v01.sql").read_text(encoding="utf-8")
out=Path("results");out.mkdir(exist_ok=True)
def query(text,pars=()):
 return [dict(r) for r in con.execute(text,pars)]
def save_csv(name,rows):
 if not rows: return
 with (out/name).open("w",newline="",encoding="utf-8-sig") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def save_json(name,data):
 (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
rows=query(sql)
save_csv("ricchi_ronhai_all_players.csv",rows)
save_json("ricchi_ronhai_top10.json",rows[:10])
all_den=sum(x["reach_declaration_kyoku_count"] for x in rows)
all_num=sum(x["ricchi_ronhai_kyoku_count"] for x in rows)
all_unaccepted=sum(x["rejected_reach_kyoku_count"] for x in rows)
# Independent count with different event tables and flags
independent=query("""
 SELECT (SELECT COUNT(*) FROM discard_event WHERE is_reach_declaration=1) AS flagged_discards,
        (SELECT COUNT(*) FROM reach_event) AS reach_events,
        (SELECT COUNT(*) FROM reach_event WHERE is_accepted=0) AS unaccepted,
        (SELECT COUNT(*) FROM reach_event WHERE is_accepted=1) AS accepted,
        (SELECT COUNT(DISTINCT CAST(e.kyoku_id AS TEXT)||':'||d.actor_player_id)
           FROM discard_event d JOIN event e ON e.id=d.event_id
           WHERE d.is_reach_declaration=1) AS unique_declaration_kyoku
""")[0]
assert all_den==independent["flagged_discards"]==independent["reach_events"]==independent["unique_declaration_kyoku"],(all_den,independent)
assert all_num==all_unaccepted==independent["unaccepted"],(all_num,all_unaccepted,independent)
for x in rows:
 assert 0<=x["ricchi_ronhai_kyoku_count"]<=x["reach_declaration_kyoku_count"],x
 assert x["ricchi_ronhai_kyoku_count"]==x["rejected_reach_kyoku_count"],x
 rate=100*x["ricchi_ronhai_kyoku_count"]/x["reach_declaration_kyoku_count"]
 assert abs(rate-x["ricchi_ronhai_pct"])<.000051,x
# Independent event matching: for each unaccepted reach a declaration flag and
# corresponding ron with the same normalized tile and target player must exist.
audits=query("""
 WITH rejected AS (
  SELECT re.kyoku_id, re.event_order AS reach_order,
         r.actor_player_id AS player_id
  FROM reach_event r JOIN event re ON re.id=r.event_id
  WHERE r.is_accepted=0
 ),
 declares AS (
  SELECT re.kyoku_id,re.player_id,
     (SELECT COUNT(*) FROM event de
      JOIN discard_event d ON d.event_id=de.id
      WHERE de.kyoku_id=re.kyoku_id
       AND de.event_order>re.reach_order
       AND d.actor_player_id=re.player_id AND d.is_reach_declaration=1
       AND EXISTS (
        SELECT 1 FROM event e JOIN agari_event a ON a.event_id=e.id
        WHERE e.kyoku_id=de.kyoku_id AND e.event_order>de.event_order
          AND e.type='ron' AND a.target_player_id=re.player_id
          AND (CASE WHEN substr(a.agari_tile,1,1)='0'
                   THEN '5'||substr(a.agari_tile,2) ELSE a.agari_tile END)
           =(CASE WHEN substr(d.tile,1,1)='0'
                   THEN '5'||substr(d.tile,2) ELSE d.tile END)
       )
     ) AS matched
  FROM rejected re
 )
 SELECT COUNT(*) AS rows_checked,
        COALESCE(SUM(CASE WHEN matched=1 THEN 1 ELSE 0 END),0) AS exact_one_ron,
        COALESCE(SUM(CASE WHEN matched<>1 THEN 1 ELSE 0 END),0) AS unmatched
 FROM declares
""")[0]
assert audits["rows_checked"]==all_num and audits["exact_one_ron"]==all_num and audits["unmatched"]==0,audits
# Contextual period subquery for 2025/26 regular, as an all-period SQL parameterization check
subsql=sql.replace("SELECT NULL AS start_year, NULL AS stage","SELECT 2025 AS start_year, 'regular' AS stage")
sub=query(subsql)
sub_den=sum(x["reach_declaration_kyoku_count"] for x in sub)
sub_num=sum(x["ricchi_ronhai_kyoku_count"] for x in sub)
ind_sub=query("""
 SELECT COUNT(*) AS declarations,
        SUM(CASE WHEN r.is_accepted=0 THEN 1 ELSE 0 END) AS rejected
 FROM reach_event r JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE ls.start_year=2025 AND ss.stage='regular'
""")[0]
assert (sub_den,sub_num)==(ind_sub["declarations"],ind_sub["rejected"]),((sub_den,sub_num),ind_sub)
summary={"sqlite_quick_check":"ok","players":len(rows),
 "declarations":all_den,"declaration_tile_dealins":all_num,
 "overall_rate_pct":round(100*all_num/all_den,4),
 "independent_counts":independent,"event_level_ron_match":audits,
 "2025_regular":{"declarations":sub_den,"declaration_tile_dealins":sub_num}}
save_json("ricchi_ronhai_verification.json",summary)
save_csv("ricchi_ronhai_2025_regular.csv",sub)
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10",json.dumps(rows[:10],ensure_ascii=False),flush=True)
