-- 麻雀スタッツ研究所：土壇場ラス回避率 正式SQL v0.1
-- 正式第20指標。第1～19指標群および派生2種の判定条件は変更しない。
-- 対象：最初の南4局開始時点で4着の選手（本場数不問）。
-- 成功：最終順位が3着以上（4→1、4→2、4→3）。途中の変動は不問。
-- 1試合につき最大1機会。南4局の連荘は全部含む。
-- 本人和了あり／なし＝南4局中の本人和了イベントの有無。因果帰属ではない。
-- 開始順位：直前の局の kyoku_player_result.rank。
-- 最終順位：game_player_result.rank。DBの順位をそのまま使用。
-- 年度とステージはNULLで全件。既存19指標の定義は一切変更しない。
WITH
params AS (
  SELECT NULL AS start_year, NULL AS stage
),
target_games AS (
  SELECT g.id AS game_id
  FROM game g
  JOIN season_stage ss ON ss.id = g.season_stage_id
  JOIN league_season ls ON ls.id = ss.league_season_id
  CROSS JOIN params p
  WHERE (p.start_year IS NULL OR ls.start_year = p.start_year)
    AND (p.stage IS NULL OR ss.stage = p.stage)
),
first_south4 AS (
  SELECT k.game_id, MIN(k.id) AS first_kyoku_id
  FROM kyoku k
  JOIN target_games g ON g.game_id = k.game_id
  WHERE k.round = '2z4'
  GROUP BY k.game_id
),
south4_starts AS (
  SELECT f.game_id, f.first_kyoku_id,
         (SELECT MAX(prior.id)
          FROM kyoku prior
          WHERE prior.game_id = f.game_id
            AND prior.id < f.first_kyoku_id) AS previous_kyoku_id
  FROM first_south4 f
),
opportunities AS (
  SELECT s.game_id, kpr.player_id,
         kpr.rank AS start_rank, gpr.rank AS final_rank
  FROM south4_starts s
  JOIN kyoku_player_result kpr
    ON kpr.kyoku_id = s.previous_kyoku_id
  JOIN game_player_result gpr
    ON gpr.game_id = s.game_id AND gpr.player_id = kpr.player_id
  WHERE kpr.rank = 4
),
own_south4_agari AS (
  SELECT k.game_id, a.actor_player_id AS player_id,
         COUNT(*) AS own_agari_count
  FROM kyoku k
  JOIN south4_starts s ON s.game_id = k.game_id
  JOIN event e ON e.kyoku_id = k.id
  JOIN agari_event a ON a.event_id = e.id
  WHERE k.round = '2z4'
  GROUP BY k.game_id, a.actor_player_id
),
judged AS (
  SELECT o.game_id, o.player_id, o.start_rank, o.final_rank,
         COALESCE(a.own_agari_count, 0) AS own_agari_count
  FROM opportunities o
  LEFT JOIN own_south4_agari a
    ON a.game_id = o.game_id AND a.player_id = o.player_id
)
SELECT
  p.id AS player_id,
  p.name AS player_name,
  COUNT(*) AS last_place_opportunities,
  SUM(CASE WHEN j.final_rank BETWEEN 1 AND 3 THEN 1 ELSE 0 END)
    AS last_place_escapes,
  ROUND(
    100.0 * SUM(CASE WHEN j.final_rank BETWEEN 1 AND 3 THEN 1 ELSE 0 END)
    / NULLIF(COUNT(*), 0), 4
  ) AS last_place_escape_pct,
  SUM(CASE WHEN j.final_rank = 1 THEN 1 ELSE 0 END) AS fourth_to_first_count,
  SUM(CASE WHEN j.final_rank = 2 THEN 1 ELSE 0 END) AS fourth_to_second_count,
  SUM(CASE WHEN j.final_rank = 3 THEN 1 ELSE 0 END) AS fourth_to_third_count,
  SUM(CASE WHEN j.final_rank = 4 THEN 1 ELSE 0 END) AS remained_fourth_count,
  SUM(CASE WHEN j.final_rank BETWEEN 1 AND 3 AND j.own_agari_count > 0 THEN 1 ELSE 0 END)
    AS escape_with_own_agari_count,
  SUM(CASE WHEN j.final_rank BETWEEN 1 AND 3 AND j.own_agari_count = 0 THEN 1 ELSE 0 END)
    AS escape_without_own_agari_count
FROM judged j
JOIN player p ON p.id = j.player_id
GROUP BY p.id, p.name
ORDER BY last_place_escape_pct DESC,
         last_place_escapes DESC,
         last_place_opportunities DESC,
         p.name;
