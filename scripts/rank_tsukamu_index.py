"""Evaluate approved Tsukamu Index per 100 participated kyoku, cross-check Dontsuka base."""
import csv,json,os,sqlite3,sys,time
from pathlib import Path

con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA temp_store=MEMORY")
sql=(Path(__file__).resolve().parents[1]/"sql/tsukamu_per_100_kyoku_v01.sql").read_text(encoding="utf-8")
sql=sql.replace("SELECT 54 AS player_id, NULL AS start_year, NULL AS stage",
                "SELECT ? AS player_id, NULL AS start_year, NULL AS stage")
assert sql.count("SELECT ? AS player_id, NULL AS start_year, NULL AS stage")==1
out=Path("results");out.mkdir(exist_ok=True)

def dump_csv(file,rows):
 if not rows:return
 with (out/file).open("w",newline="",encoding="utf-8-sig") as f:
  w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
def dump_json(file,x):
 (out/file).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")

assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
players=con.execute("""
 SELECT DISTINCT p.id,p.name
 FROM player p
 JOIN game_player_result gr ON gr.player_id=p.id
 ORDER BY p.id
""").fetchall()
rows=[]
for i,p in enumerate(players,1):
 start=time.monotonic()
 result=dict(con.execute(sql,(p["id"],)).fetchone())
 assert result["player_name"]==p["name"]
 rows.append(result)
 print(f'{i}/{len(players)} {p["name"]}: {result["atari_tile_draws"]}/{result["participated_kyoku_count"]} index={result["tsukamu_index_per_100_kyoku"]:.4f} elapsed={time.monotonic()-start:.1f}s',flush=True)

# Original all-season Dontsuka calculation has an independently stored numerator and
# draw count; check against those original artifacts without changing source logic.
original_file=out/"dontsuka_all_matches.csv"
if not original_file.is_file():
 raise RuntimeError("Reference dontsuka_all_matches.csv is absent; run original Dontsuka first")
with original_file.open("r",encoding="utf-8-sig",newline="") as f:
 previous={int(x["player_id"]):x for x in csv.DictReader(f)}
assert len(previous)==len(rows),(len(previous),len(rows))

denom_differences=[]
for r in rows:
 ref=previous[r["player_id"]]
 assert r["total_draws"]==int(ref["total_draws"]),(r,ref)
 assert r["atari_tile_draws"]==int(ref["hit_draws"]),(r,ref)
 assert r["kyoku_with_draw_count"]==int(ref["kyoku_count"]),(r,ref)
 assert r["participated_kyoku_count"]>=r["kyoku_with_draw_count"],r
 count2=con.execute("""
   SELECT COUNT(k.id)
   FROM game_player_result gr
   JOIN kyoku k ON k.game_id=gr.game_id
   WHERE gr.player_id=?
 """,(r["player_id"],)).fetchone()[0]
 assert r["participated_kyoku_count"]==count2,(r,count2)
 if r["participated_kyoku_count"]!=r["kyoku_with_draw_count"]:
  denom_differences.append({
    "player_id":r["player_id"],"player_name":r["player_name"],
    "participated":r["participated_kyoku_count"],
    "kyoku_with_draw":r["kyoku_with_draw_count"],
    "previous_hits_per_100_drawn_kyoku":ref["hits_per_100_kyoku"],
    "correct_index_per_100_participated_kyoku":r["tsukamu_index_per_100_kyoku"]})
 check=round(100*r["atari_tile_draws"]/r["participated_kyoku_count"],4)
 assert abs(check-r["tsukamu_index_per_100_kyoku"])<.00006,r

counts=con.execute("""
 SELECT COUNT(*) AS participant_kyoku
 FROM kyoku k JOIN game_player_result gr ON gr.game_id=k.game_id
""").fetchone()["participant_kyoku"]
assert sum(x["participated_kyoku_count"] for x in rows)==counts
total_hits=sum(x["atari_tile_draws"] for x in rows)
total_draws=sum(x["total_draws"] for x in rows)

# Conditional historical reference: 2025-26 HIRO柴田, fixed baseline 101 hits.
hiros=[p["id"] for p in players if p["name"]=="HIRO柴田"]
fixed={}
if hiros:
 period_sql=sql.replace("NULL AS start_year, NULL AS stage","2025 AS start_year, NULL AS stage")
 fixed=dict(con.execute(period_sql,(hiros[0],)).fetchone())
 assert fixed["atari_tile_draws"]==101,fixed
 assert fixed["total_draws"]==4164,fixed
else:
 raise RuntimeError("Expected player HIRO柴田 not found")

rows.sort(key=lambda x:(-x["tsukamu_index_per_100_kyoku"],
                        -x["atari_tile_draws"],-x["participated_kyoku_count"],x["player_name"]))
dump_csv("tsukamu_index_all_players.csv",rows)
dump_json("tsukamu_index_top10.json",rows[:10])
dump_csv("tsukamu_denominator_differences.csv",denom_differences)
summary={"db_integrity":"ok","players":len(rows),
         "participant_kyoku_total":counts,
         "atari_tile_draws_total":total_hits,
         "total_draws":total_draws,
         "index_all_players_weighted":round(100*total_hits/counts,4),
         "matched_original_dontsuka_hits":len(rows),
         "players_without_draw_in_some_participated_kyoku":len(denom_differences),
         "original_kyoku_denominator_differences":denom_differences[:15],
         "2025_26_HIRO":fixed}
dump_json("tsukamu_index_verification.json",summary)
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10",json.dumps(rows[:10],ensure_ascii=False),flush=True)
