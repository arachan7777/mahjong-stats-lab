"""Validate Kumakuma Time v0.1 against DB transitions; save full rankings."""
from pathlib import Path
import csv, json, os, sqlite3, sys

db=os.path.abspath(sys.argv[1])
con=sqlite3.connect("file:"+db+"?mode=ro", uri=True)
con.row_factory=sqlite3.Row
root=Path(__file__).resolve().parents[1]
original=(root/"sql/kumakuma_time_v01.sql").read_text(encoding="utf-8")
out=Path("results")
out.mkdir(exist_ok=True)

def query(sql,params=()):
    return [dict(x) for x in con.execute(sql,params)]

def save_csv(name,rows):
    if not rows:
        print("EMPTY",name,flush=True)
        return
    with (out/name).open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def save_json(name,value):
    (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")

check=con.execute("PRAGMA quick_check").fetchone()[0]
if check!="ok": raise RuntimeError("SQLite quick_check: "+check)

rows=query(original)
if not rows: raise RuntimeError("Kumakuma query returned no players")
save_csv("kumakuma_all_players.csv",rows)
save_json("kumakuma_top10.json",rows[:10])

def aggregate(x):
    return {"players":len(x),"oya_starts":sum(i["oya_starts"] for i in x),
      "reached_1":sum(i["reached_1"] for i in x),
      "reached_2":sum(i["reached_2"] for i in x),
      "reached_3":sum(i["reached_3"] for i in x),
      "reached_4":sum(i["reached_4"] for i in x),
      "renchan_transitions":sum(i["total_renchan"] for i in x)}
all_total=aggregate(rows)

# Verify continuity on the raw kyoku sequence, independent of aggregation query.
counts=dict(con.execute("SELECT 'games' AS kind,COUNT(*) FROM game UNION ALL SELECT 'kyoku',COUNT(*) FROM kyoku").fetchall())
assert all_total["oya_starts"]+all_total["renchan_transitions"]==counts["kyoku"],(all_total,counts)
for x in rows:
    assert x["oya_starts"]>=x["reached_1"]>=x["reached_2"]>=x["reached_3"]>=x["reached_4"]>=0,x

# Every same-dealer transition must have the defined event cause in prior kyoku.
audit_sql="""
WITH ordered AS (
 SELECT k.id AS kyoku_id,k.game_id,k.oya_player_id,
        LAG(k.id) OVER (PARTITION BY k.game_id ORDER BY k.id) AS prior_kyoku_id,
        LAG(k.oya_player_id) OVER (PARTITION BY k.game_id ORDER BY k.id) AS prior_oya
 FROM kyoku k
)
SELECT t.game_id,t.prior_kyoku_id,t.kyoku_id,t.oya_player_id,
 EXISTS (
   SELECT 1 FROM event e JOIN agari_event a ON a.event_id=e.id
   WHERE e.kyoku_id=t.prior_kyoku_id AND a.actor_player_id=t.oya_player_id
 ) AS parent_won,
 EXISTS (
   SELECT 1 FROM event e
   JOIN ryukyoku_event r ON r.event_id=e.id
   JOIN ryukyoku_player rp ON rp.ryukyoku_event_id=r.event_id
   WHERE e.kyoku_id=t.prior_kyoku_id
     AND rp.player_id=t.oya_player_id AND rp.is_tenpai=1
 ) AS parent_tenpai_draw
FROM ordered t
WHERE t.prior_oya=t.oya_player_id
ORDER BY t.game_id,t.prior_kyoku_id
"""
audit=query(audit_sql)
unknown=[x for x in audit if not (x["parent_won"] or x["parent_tenpai_draw"])]
save_csv("kumakuma_unsupported_continuations.csv",unknown)
causes={"supported_win":sum(i["parent_won"] for i in audit),
        "supported_tenpai_draw":sum(i["parent_tenpai_draw"] for i in audit),
        "overlap":sum(i["parent_won"] and i["parent_tenpai_draw"] for i in audit),
        "unsupported":len(unknown),
        "same_parent_transitions":len(audit)}
assert len(audit)==all_total["renchan_transitions"],(len(audit),all_total)
# Specific historical fixed-period cross-check; do not force equality to old DB if new data differs.
fixed_sql=original.replace(
 "SELECT NULL AS start_year, NULL AS stage",
 "SELECT 2025 AS start_year, 'regular' AS stage"
)
fixed=query(fixed_sql)
fixed_total=aggregate(fixed)
gk=query("""
 SELECT COUNT(DISTINCT g.id) AS games,COUNT(k.id) AS kyoku
 FROM game g
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN kyoku k ON k.game_id=g.id
 WHERE ls.start_year=2025 AND ss.stage='regular'
""")[0]
fixed_total.update(gk)
assert fixed_total["oya_starts"]+fixed_total["renchan_transitions"]==fixed_total["kyoku"]
save_csv("kumakuma_2025_regular_players.csv",fixed)
summary={"db_counts":counts,"all_stages":all_total,"event_audit":causes,"regular_2025":fixed_total,
         "reference_2025_regular":{"games":300,"kyoku":3640,"reached_4":35},
         "reference_2025_matches":{
           "games":fixed_total["games"]==300,
           "kyoku":fixed_total["kyoku"]==3640,
           "reached_4":fixed_total["reached_4"]==35
         }}
save_json("kumakuma_verification.json",summary)
print("AUDIT",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10",json.dumps(rows[:10],ensure_ascii=False),flush=True)
if unknown:
    print("UNSUPPORTED CONTINUATIONS",json.dumps(unknown[:20],ensure_ascii=False),flush=True)
    raise RuntimeError("Parent continuity includes unsupported event causes; investigate before validating.")
print("VALIDATED: all same-dealer transitions supported by parent win or tenpai draw",flush=True)
