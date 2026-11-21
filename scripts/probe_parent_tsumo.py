import sqlite3,sys,json,os
from pathlib import Path
conn=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
conn.row_factory=sqlite3.Row
sql="""
WITH all_scores AS (
 SELECT k.id AS kyoku_id,k.game_id,k.oya_player_id,k.round,k.honba_count,
        kpr.player_id,kpr.score,
        LAG(kpr.score) OVER (PARTITION BY k.game_id,kpr.player_id ORDER BY k.id) AS prior_score
 FROM kyoku k JOIN kyoku_player_result kpr ON kpr.kyoku_id=k.id
), parent_tsumo AS (
 SELECT s.*, e.id AS win_event_id,a.actor_player_id AS winner_id,
        a.agari_points,a.honba_points,a.kyotaku_points,a.han,a.fu,a.is_yakuman,
        (SELECT COUNT(*) FROM reach_event r
         JOIN event re ON re.id=r.event_id
         WHERE re.kyoku_id=s.kyoku_id AND r.actor_player_id=s.player_id AND r.is_accepted=1) AS parent_reaches
 FROM all_scores s
 JOIN event e ON e.kyoku_id=s.kyoku_id AND e.type='tsumo'
 JOIN agari_event a ON a.event_id=e.id
 WHERE s.player_id=s.oya_player_id AND a.actor_player_id<>s.player_id
)
SELECT *,COALESCE(prior_score,25000)-score-1000*parent_reaches AS inferred_parent_payment
FROM parent_tsumo
ORDER BY kyoku_id
"""
rows=[dict(r) for r in conn.execute(sql)]
print("Parent-taken-tsumo sample",len(rows),flush=True)
rdata={
 "total_events":len(rows),
 "first_kyoku_events":sum(r["prior_score"] is None for r in rows),
 "nonpositive_payment":sum(r["inferred_parent_payment"]<=0 for r in rows),
 "nonhundred_payment":sum(r["inferred_parent_payment"]%100!=0 for r in rows),
 "parent_reached":sum(r["parent_reaches"]>0 for r in rows),
 "sample_first":rows[:25],
 "sample_last":rows[-10:],
 "anomalies":[r for r in rows if r["inferred_parent_payment"]<=0 or r["inferred_parent_payment"]%100!=0][:30],
 "unique_example_agari":{}
}
for r in rows:
 k=f'{r["agari_points"]}|{r["honba_points"]}'
 if k not in rdata["unique_example_agari"]: rdata["unique_example_agari"][k]=r["inferred_parent_payment"]
print("PROBE",json.dumps({k:v for k,v in rdata.items() if k not in ("sample_first","sample_last","unique_example_agari")},ensure_ascii=False),flush=True)
Path("results").mkdir(exist_ok=True)
Path("results/parent_tsumo_probe.json").write_text(json.dumps(rdata,ensure_ascii=False,indent=2),encoding="utf-8")
