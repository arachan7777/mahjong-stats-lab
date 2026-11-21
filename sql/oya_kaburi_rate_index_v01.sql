-- 麻雀スタッツ研究所 親被り率・親被り指数 SQL v0.1
-- 独立した新規SQL。既存原典は変更しない。
-- 既存定義:
-- 親被り = 自分が親の局で他家がツモ和了し、親として支払った局。
-- 親被り率 = 親被り局数 / 自分の親局数 × 100。
-- 親被り指数 = 親被り率 / 同対象範囲のリーグ全体親被り率 × 100。
-- 親被りの総失点・平均失点はツモ支払分のみ。リーチ棒1000点は控除。
-- 局終了時の持ち点の差から支払額を得る。第1局の開始持ち点は25000点。
-- 本場支払は含み、供託・リーチ棒支出は含めない。
-- params: start_year=NULL で全年度、stage=NULL で全ステージ。
WITH
params AS (
 SELECT NULL AS start_year, NULL AS stage
),
selected_games AS (
 SELECT g.id AS game_id
 FROM game g
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 CROSS JOIN params cfg
 WHERE (cfg.start_year IS NULL OR ls.start_year=cfg.start_year)
   AND (cfg.stage IS NULL OR ss.stage=cfg.stage)
),
score_sequence AS (
 SELECT k.id AS kyoku_id,k.game_id,k.oya_player_id,
        r.player_id,r.score,
        LAG(r.score) OVER (
          PARTITION BY k.game_id,r.player_id ORDER BY k.id
        ) AS previous_score
 FROM kyoku k
 JOIN selected_games sg ON sg.game_id=k.game_id
 JOIN kyoku_player_result r ON r.kyoku_id=k.id
),
oya_kyoku AS (
 SELECT kyoku_id,game_id,player_id,score,previous_score
 FROM score_sequence
 WHERE player_id=oya_player_id
),
child_tsumo AS (
 SELECT e.kyoku_id,COUNT(*) AS child_tsumo_events
 FROM event e
 JOIN agari_event a ON a.event_id=e.id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
 WHERE e.type='tsumo' AND a.actor_player_id<>k.oya_player_id
 GROUP BY e.kyoku_id
),
accepted_oya_reach AS (
 SELECT e.kyoku_id,r.actor_player_id AS player_id,COUNT(*) AS reach_count
 FROM reach_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
 WHERE r.is_accepted=1 AND r.actor_player_id=k.oya_player_id
 GROUP BY e.kyoku_id,r.actor_player_id
),
oya_outcomes AS (
 SELECT o.player_id,o.kyoku_id,
        CASE WHEN c.child_tsumo_events>0 THEN 1 ELSE 0 END AS is_kaburi,
        CASE WHEN c.child_tsumo_events>0 THEN
          COALESCE(o.previous_score,25000)-o.score
            -1000*COALESCE(r.reach_count,0)
        ELSE 0 END AS kaburi_payment_points
 FROM oya_kyoku o
 LEFT JOIN child_tsumo c ON c.kyoku_id=o.kyoku_id
 LEFT JOIN accepted_oya_reach r
   ON r.kyoku_id=o.kyoku_id AND r.player_id=o.player_id
),
by_player AS (
 SELECT player_id,
        COUNT(*) AS oya_kyoku_count,
        SUM(is_kaburi) AS kaburi_count,
        SUM(kaburi_payment_points) AS kaburi_total_loss_points,
        ROUND(1.0*SUM(kaburi_payment_points)/
          NULLIF(SUM(is_kaburi),0),2) AS kaburi_avg_loss_points
 FROM oya_outcomes
 GROUP BY player_id
),
league AS (
 SELECT SUM(oya_kyoku_count) AS league_oya_kyoku,
        SUM(kaburi_count) AS league_kaburi
 FROM by_player
)
SELECT p.id AS player_id,p.name AS player_name,
       b.oya_kyoku_count,b.kaburi_count,
       ROUND(100.0*b.kaburi_count/
         NULLIF(b.oya_kyoku_count,0),4) AS kaburi_pct,
       ROUND(
         100.0*b.kaburi_count*l.league_oya_kyoku/
         NULLIF(b.oya_kyoku_count*l.league_kaburi,0),2
       ) AS kaburi_index,
       b.kaburi_total_loss_points,b.kaburi_avg_loss_points,
       l.league_oya_kyoku,l.league_kaburi,
       ROUND(100.0*l.league_kaburi/
         NULLIF(l.league_oya_kyoku,0),4) AS league_kaburi_pct
FROM by_player b
JOIN player p ON p.id=b.player_id
CROSS JOIN league l
ORDER BY kaburi_index DESC,b.kaburi_count DESC,b.oya_kyoku_count DESC,p.name;
