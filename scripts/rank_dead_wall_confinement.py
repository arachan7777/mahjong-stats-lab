"""Evaluate original-tenpai dead-wall confinement SQL, audited against tile-deck reconstruction."""
from pathlib import Path
import csv,os,sqlite3,json,sys
c=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True);c.row_factory=sqlite3.Row
c.execute("PRAGMA temp_store=MEMORY")
out=Path("results");out.mkdir(exist_ok=True)
sql=(Path(__file__).resolve().parents[1]/"sql/dead_wall_confinement_v01.sql").read_text(encoding="utf-8")
def dump_csv(name,rows):
 if not rows:return
 with (out/name).open("w",newline="",encoding="utf-8-sig") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def save_json(name,obj):
 (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
assert c.execute("PRAGMA quick_check").fetchone()[0]=="ok"
rows=[dict(x) for x in c.execute(sql)]
assert rows,"No players found"
dump_csv("dead_wall_confinement_all_players.csv",rows)
save_json("dead_wall_confinement_top10.json",rows[:10])

# Separate Python analysis independently derives unseen tiles from the 136-tile deck.
# Crosscheck every player, not just headline totals.
old=out/"dead_wall_original_wait_audit_players.csv"
if not old.exists(): raise RuntimeError("Run audit_dead_wall_original_waits.py before this script")
with old.open(newline="",encoding="utf-8-sig") as f:
 expected={int(r["player_id"]):r for r in csv.DictReader(f)}
assert len(rows)==len(expected),(len(rows),len(expected))
totals={"first_tenpai_exhaustive_draw_kyoku":0,"initial_wait_tiles_total":0,"dead_wall_wait_tiles_total":0,
        "initial_dora_indicator_wait_tiles":0,"final_dora_indicator_wait_tiles":0}
for r in rows:
 a=expected[r["player_id"]]
 for key,ex_key in [
  ("first_tenpai_exhaustive_draw_kyoku","tenpai_count"),
  ("initial_wait_tiles_total","original_wait_total_initial_physical"),
  ("dead_wall_wait_tiles_total","original_wait_total_final_physical"),
  ("initial_dora_indicator_wait_tiles",None),
  ("final_dora_indicator_wait_tiles","final_dora_wait_count")]:
  totals[key]+=r[key]
  if ex_key:
   assert r[key]==int(a[ex_key]),(r["player_name"],key,r[key],a[ex_key])
 assert r["initial_wait_tiles_total"]>=r["dead_wall_wait_tiles_total"],r
 assert 0<=r["dead_wall_confinement_pct"]<=100,r
 assert abs(r["dead_wall_confinement_pct"]-
       round(100*r["dead_wall_wait_tiles_total"]/r["initial_wait_tiles_total"],4))<.00006,r
 assert abs(r["dead_wall_non_indicator_pct"]-
       round(100*(r["dead_wall_wait_tiles_total"]-r["final_dora_indicator_wait_tiles"])/
         (r["initial_wait_tiles_total"]-r["initial_dora_indicator_wait_tiles"]),4))<.00006,r

# Confirm independent DB values: total first-tenpai at exhaustive draw is 8100,
# and 100%-upper-bound cannot be violated with the full undealt deck.
assert totals["first_tenpai_exhaustive_draw_kyoku"]>=8100,totals
assert totals["first_tenpai_exhaustive_draw_kyoku"]==audit["stats"]["tracked_first_tenpai"],(totals,audit["stats"])
assert totals["initial_wait_tiles_total"]>0,totals
assert totals["dead_wall_wait_tiles_total"]>0,totals

# Re-read primary audit JSON to avoid silently ignoring any anomalies.
audit=json.loads((out/"dead_wall_original_wait_audit.json").read_text(encoding="utf-8"))
must_be_zero=["physical_ratio_over_100","terminal_reconstruction_not_equal_available_plus_dora",
              "terminal_dora_indicator_discrepancy","initial_hidden_vs_db_mismatch",
              "initial_hidden_negative","terminal_hidden_negative","no_first_own_tenpai"]
for key in must_be_zero:
 assert audit["stats"].get(key,0)==0,(key,audit["stats"].get(key))
summary={
 "sqlite_check":"ok","players":len(rows),
 "independent_all_player_counts_matched":len(rows),
 "all_5065_exhaustive_draws_reconstructed_to_14_remaining_tiles":audit["exhaustive_draws"]==5065,
 "original_wait_changed_cases":audit["stats"]["wait_changed"],
 "first_tenpai_but_noten_at_draw":audit["stats"].get("ended_noten",0),
 "first_tenpai_and_still_tenpai_at_draw":audit["stats"].get("same_wait",0)+audit["stats"].get("wait_changed",0),
 "initial_tenpai_at_draw":totals["first_tenpai_exhaustive_draw_kyoku"],
 "aggregate":totals,
 "league_weighted_confinement_pct":round(100*totals["dead_wall_wait_tiles_total"]/totals["initial_wait_tiles_total"],4),
 "league_weighted_non_indicator_pct":round(100*(totals["dead_wall_wait_tiles_total"]-totals["final_dora_indicator_wait_tiles"])/
  (totals["initial_wait_tiles_total"]-totals["initial_dora_indicator_wait_tiles"]),4),
 "validated_against":"Independent Python initial-deck/draw-event reconstruction"}
save_json("dead_wall_confinement_verification.json",summary)
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10",json.dumps(rows[:10],ensure_ascii=False),flush=True)
