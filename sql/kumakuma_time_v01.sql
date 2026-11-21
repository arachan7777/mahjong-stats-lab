-- 麻雀スタッツ研究所 クマクマタイム率 SQL v0.1 (新規・独立ファイル)
-- 原典の定義: 親番開始を1試行とし、親の和了または親聴牌流局による
-- 次局への親権維持を1連荘と数える。本場数は無関係。
-- 4連荘以上に到達した親番開始の割合 = クマクマタイム率。
-- 試合末尾で次局が無ければ維持回数は加算しない。
-- params.start_year/stage がNULLなら全期間・全ステージ。
-- このSQLは「連続した同一親の局」を連荘とし、維持原因の整合性は別途
-- agari_event / ryukyoku_player の実イベントと監査する。
WITH
params AS (SELECT NULL AS start_year, NULL AS stage),
selected_games AS (
  SELECT g.id AS game_id
  FROM game g
  JOIN season_stage ss ON ss.id=g.season_stage_id
  JOIN league_season ls ON ls.id=ss.league_season_id
  CROSS JOIN params cfg
  WHERE (cfg.start_year IS NULL OR ls.start_year=cfg.start_year)
    AND (cfg.stage IS NULL OR ss.stage=cfg.stage)
),
ordered_kyoku AS (
  SELECT k.id AS kyoku_id,k.game_id,k.oya_player_id,
         LAG(k.oya_player_id) OVER (
           PARTITION BY k.game_id ORDER BY k.id
         ) AS prior_oya
  FROM kyoku k
  JOIN selected_games sg ON sg.game_id=k.game_id
),
start_markers AS (
  SELECT *,
         CASE WHEN prior_oya=oya_player_id THEN 0 ELSE 1 END AS is_new_start
  FROM ordered_kyoku
),
runs AS (
  SELECT *,
         SUM(is_new_start) OVER (
           PARTITION BY game_id ORDER BY kyoku_id
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
         ) AS run_id
  FROM start_markers
),
parent_runs AS (
  SELECT game_id,run_id,MAX(oya_player_id) AS player_id,
         COUNT(*) AS total_parent_kyoku,
         COUNT(*)-1 AS renchan_count,
         MIN(kyoku_id) AS first_kyoku_id,
         MAX(kyoku_id) AS last_kyoku_id
  FROM runs
  GROUP BY game_id,run_id
),
by_player AS (
  SELECT player_id,COUNT(*) AS oya_starts,
         SUM(CASE WHEN renchan_count>=1 THEN 1 ELSE 0 END) AS reached_1,
         SUM(CASE WHEN renchan_count>=2 THEN 1 ELSE 0 END) AS reached_2,
         SUM(CASE WHEN renchan_count>=3 THEN 1 ELSE 0 END) AS reached_3,
         SUM(CASE WHEN renchan_count>=4 THEN 1 ELSE 0 END) AS reached_4,
         MAX(renchan_count) AS max_renchan,
         SUM(renchan_count) AS total_renchan
  FROM parent_runs GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,b.oya_starts,
       b.reached_1,b.reached_2,b.reached_3,b.reached_4,
       ROUND(100.0*b.reached_1/NULLIF(b.oya_starts,0),4) AS reached_1_pct,
       ROUND(100.0*b.reached_2/NULLIF(b.oya_starts,0),4) AS reached_2_pct,
       ROUND(100.0*b.reached_3/NULLIF(b.oya_starts,0),4) AS reached_3_pct,
       ROUND(100.0*b.reached_4/NULLIF(b.oya_starts,0),4) AS kumakuma_pct,
       b.max_renchan,b.total_renchan
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY kumakuma_pct DESC,b.reached_4 DESC,b.oya_starts DESC,p.name;
