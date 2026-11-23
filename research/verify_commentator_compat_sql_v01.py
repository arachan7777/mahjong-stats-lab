#!/usr/bin/env python3
"""正式実況マスター×正本DBのSQL2本を、先行検証済みPython集計結果に全件照合する。"""
import csv,json,sqlite3,sys
from pathlib import Path

def read_json(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def compare(actual, expected, label, atol=.001):
    if expected is None:
        assert actual is None,(label,actual,expected)
    elif isinstance(expected,(float,int)) and not isinstance(expected,bool):
        assert actual is not None and abs(actual-expected)<atol,(label,actual,expected)
    else:
        assert actual==expected,(label,actual,expected)

con=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
# read-only connection with query_only ON prevents even temporary tables; only staging SQL may write temp.
con.execute("PRAGMA query_only=OFF")
con.executescript(Path("sql/broadcast_commentary_master_20261120_v01.sql").read_text(encoding="utf-8"))
con.execute("PRAGMA query_only=ON")
counts=con.execute("SELECT COUNT(*) AS all_games, SUM(commentator='日吉辰哉') AS h_games FROM broadcast_commentary_game").fetchone()
assert (counts["all_games"],counts["h_games"])==(2068,736),dict(counts)
missing=con.execute("SELECT b.game_id FROM broadcast_commentary_game b LEFT JOIN game g ON g.id=b.game_id WHERE g.id IS NULL").fetchall()
assert not missing,missing
old_player=read_json("results/hiyoshi_compat_20261123.json")
old_team=read_json("results/hiyoshi_team_compat_20261123.json")
q1=Path("sql/commentator_player_compat_v01.sql").read_text(encoding="utf-8")
q2=Path("sql/commentator_team_compat_v01.sql").read_text(encoding="utf-8")
players=[dict(r) for r in con.execute(q1)]
teams=[dict(r) for r in con.execute(q2)]
assert len(players)==56,len(players)
assert len(teams)==20,len(teams)
assert sum(r["h_games"] for r in players)==736*4
assert sum(r["other_games"] for r in players)==1332*4
assert sum(r["h_games"] for r in teams if r["scope"]=="all")==736*4
assert sum(r["other_games"] for r in teams if r["scope"]=="all")==1332*4

p_old={v["name"]:v for v in old_player["all_players"]}
for r in players:
    x=p_old[r["player_name"]]
    for a,b in (("h_games","h_games"),("h_total_pt","h_pt"),("h_avg_pt","h_avg"),
                ("h_top_pct","h_top_pct"),("h_avg_rank","h_avg_rank"),
                ("other_games","other_games"),("other_avg_pt","other_avg"),
                ("other_top_pct","other_top_pct"),("delta_avg_pt","delta"),
                ("delta_top_pct_pp","top_delta_pp")):
        compare(r[a],x[b],f"player={r['player_name']} {a}")
    compare(r["eligible_for_ranking"],int(r["h_games"]>=20 and r["other_games"]>=20),
            "player eligible")
t_old={(scope,x["team"]):x for scope,arr in
       (("all",old_team["all_teams"]),("regular",old_team["regular_teams"])) for x in arr}
for r in teams:
    x=t_old[(r["scope"],r["team_name"])]
    h,o=x["hiyoshi"],x["other"]
    for key,old in (("h_games",h["games"]),("h_total_pt",h["total_pt"]),("h_avg_pt",h["avg_pt"]),
                    ("h_top_count",h["top_count"]),("h_top_pct",h["top_pct"]),
                    ("h_last_count",h["last_count"]),("h_last_pct",h["last_pct"]),
                    ("h_avg_rank",h["avg_rank"]),("h_total_margin",h["total_margin_vs_opponents"]),
                    ("h_avg_margin",h["avg_margin_vs_opponents"]),
                    ("h_total_score_delta",h["score_delta_total"]),
                    ("h_avg_score_delta",h["score_delta_average"]),
                    ("other_games",o["games"]),("other_total_pt",o["total_pt"]),
                    ("other_avg_pt",o["avg_pt"]),("other_top_pct",o["top_pct"]),
                    ("other_last_pct",o["last_pct"]),("other_avg_rank",o["avg_rank"]),
                    ("delta_avg_pt",x["delta_avg_pt"]),
                    ("delta_top_pct_pp",x["delta_top_pct_pp"]),
                    ("delta_avg_rank",x["delta_avg_rank"]),
                    ("delta_avg_margin",x["delta_avg_margin_vs_opponents"])):
        compare(r[key],old,f"team={r['scope']} {r['team_name']} {key}",atol=.0011)

outdir=Path("results");outdir.mkdir(exist_ok=True)
with (outdir/"hiyoshi_player_sql_v01.csv").open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=list(players[0]));writer.writeheader();writer.writerows(players)
with (outdir/"hiyoshi_team_sql_v01.csv").open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=list(teams[0]));writer.writeheader();writer.writerows(teams)
print("SQL_VALIDATED_PLAYERS",len(players),"SQL_VALIDATED_TEAMS",len(teams),"MASTER",dict(counts),flush=True)
print("SQL_TEAM_WORST",[(r["team_name"],r["delta_avg_pt"],r["h_total_pt"]) for r in teams if r["scope"]=="all"][:10],flush=True)
