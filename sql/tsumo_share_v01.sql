-- 麻雀スタッツ研究所 ツモ割合 SQL v0.1
-- 原典：「麻雀スタッツ研究所_database_sqlite3_集計再開マニュアル」9. 追加スタッツ
-- 定義：全和了のうちツモ和了が占める割合。基本和了率とは別指標。
-- 分子：本人によるツモ和了イベント（event.type='tsumo'）の件数。
-- 分母：本人によるツモ和了とロン和了イベントの合計件数。
-- ロン和了にはダブロン等、各和了者の和了イベントをそれぞれ計上。
-- 放銃回数・ツモ被り・和了局数÷参加局数とは異なる。
-- 対象期間：start_year=NULL で全シーズン、stage=NULL で全ステージ。
-- ツモ和了・ロン和了が0件の選手は返さない（ゼロ除算回避）。
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
wins AS (
  SELECT a.actor_player_id AS player_id, e.id AS win_event_id, e.type AS win_type
  FROM agari_event a
  JOIN event e ON e.id=a.event_id
  JOIN kyoku k ON k.id=e.kyoku_id
  JOIN selected_games sg ON sg.game_id=k.game_id
  WHERE e.type IN ('tsumo','ron')
),
by_player AS (
  SELECT player_id,
         COUNT(*) AS all_agari_count,
         SUM(CASE WHEN win_type='tsumo' THEN 1 ELSE 0 END) AS tsumo_agari_count,
         SUM(CASE WHEN win_type='ron' THEN 1 ELSE 0 END) AS ron_agari_count
  FROM wins GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.all_agari_count,b.tsumo_agari_count,b.ron_agari_count,
       ROUND(100.0*b.tsumo_agari_count/NULLIF(b.all_agari_count,0),4) AS tsumo_share_pct,
       ROUND(100.0*b.ron_agari_count/NULLIF(b.all_agari_count,0),4) AS ron_share_pct
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY tsumo_share_pct DESC,b.tsumo_agari_count DESC,
         b.all_agari_count DESC,p.name;
