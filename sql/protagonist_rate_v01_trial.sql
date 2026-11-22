-- 麻雀スタッツ研究所：主人公補正率 試算SQL v0.1
-- 対象：南4局0本場開始時点で2～4着の選手。
-- 成功：南4局の連荘を含む試合最終順位が1着。
-- 自力：南4局中に本人の和了が1回以上ある成功。
-- 他力：南4局中に本人の和了が一度もない成功。
-- 大逆転：南4局開始時4着から最終1着。自力／他力と重複。
-- 順位：前局の kyoku_player_result.rank と game_player_result.rank を正とする。
-- 年度とステージは NULL = 全件。変更すると期間絞り込み可能。
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
  JOIN target_games tg ON tg.game_id = k.game_id
  WHERE k.round = '2z4'
  GROUP BY k.game_id
),
south4_starts AS (
  SELECT f.game_id, f.first_kyoku_id,
         (SELECT MAX(prev.id)
          FROM kyoku prev
          WHERE prev.game_id = f.game_id
            AND prev.id < f.first_kyoku_id) AS previous_kyoku_id
  FROM first_south4 f
  JOIN kyoku k ON k.id = f.first_kyoku_id
  WHERE k.honba_count = 0
),
opportunities AS (
  SELECT s.game_id, kr.player_id,
         kr.rank AS start_rank,
         gr.rank AS final_rank
  FROM south4_starts s
  JOIN kyoku_player_result kr ON kr.kyoku_id = s.previous_kyoku_id
  JOIN game_player_result gr
    ON gr.game_id = s.game_id AND gr.player_id = kr.player_id
  WHERE kr.rank BETWEEN 2 AND 4
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
         COALESCE(w.own_agari_count, 0) AS own_agari_count
  FROM opportunities o
  LEFT JOIN own_south4_agari w
    ON w.game_id = o.game_id AND w.player_id = o.player_id
)
SELECT
  p.id AS player_id,
  p.name AS player_name,
  COUNT(*) AS opportunities,
  SUM(CASE WHEN j.final_rank = 1 THEN 1 ELSE 0 END) AS protagonist_count,
  ROUND(
    100.0 * SUM(CASE WHEN j.final_rank = 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 4
  ) AS protagonist_rate_pct,
  SUM(CASE WHEN j.final_rank = 1 AND j.own_agari_count > 0 THEN 1 ELSE 0 END) AS self_protagonist_count,
  SUM(CASE WHEN j.final_rank = 1 AND j.own_agari_count = 0 THEN 1 ELSE 0 END) AS other_protagonist_count,
  SUM(CASE WHEN j.start_rank = 4 AND j.final_rank = 1 THEN 1 ELSE 0 END) AS fourth_to_first_count,
  SUM(CASE WHEN j.start_rank = 2 THEN 1 ELSE 0 END) AS second_opportunities,
  SUM(CASE WHEN j.start_rank = 2 AND j.final_rank = 1 THEN 1 ELSE 0 END) AS second_to_first_count,
  SUM(CASE WHEN j.start_rank = 3 THEN 1 ELSE 0 END) AS third_opportunities,
  SUM(CASE WHEN j.start_rank = 3 AND j.final_rank = 1 THEN 1 ELSE 0 END) AS third_to_first_count,
  SUM(CASE WHEN j.start_rank = 4 THEN 1 ELSE 0 END) AS fourth_opportunities,
  ROUND(100.0 * SUM(CASE WHEN j.start_rank = 2 AND j.final_rank = 1 THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN j.start_rank = 2 THEN 1 ELSE 0 END), 0), 4) AS second_to_first_pct,
  ROUND(100.0 * SUM(CASE WHEN j.start_rank = 3 AND j.final_rank = 1 THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN j.start_rank = 3 THEN 1 ELSE 0 END), 0), 4) AS third_to_first_pct,
  ROUND(100.0 * SUM(CASE WHEN j.start_rank = 4 AND j.final_rank = 1 THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN j.start_rank = 4 THEN 1 ELSE 0 END), 0), 4) AS fourth_to_first_pct
FROM judged j
JOIN player p ON p.id = j.player_id
GROUP BY p.id, p.name
ORDER BY protagonist_rate_pct DESC, protagonist_count DESC, opportunities DESC, p.name;
