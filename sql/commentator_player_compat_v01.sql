-- 麻雀スタッツ研究所　実況者×選手相性（通算） v0.1
-- 正本：2026-11-20版MリーグDB + 同日固定実況マスター
-- 実行前：sql/broadcast_commentary_master_20261120_v01.sql を読み込む。
-- 対象実況者の変更は target の氏名のみ。既存DBとマスターを更新しない。
-- ポイント = league_points + penalty_league_points（反則減点を含む）。
-- 相性差 = 対象実況時の1試合平均pt - その他実況時の1試合平均pt。
-- 順位対象 = 双方20試合以上。順位対象外も結果行に残す。
WITH target AS (
  SELECT '日吉辰哉' AS commentator
),
results AS (
  SELECT
    r.player_id,
    p.name AS player_name,
    r.game_id,
    r.rank AS game_rank,
    COALESCE(r.league_points, 0) + COALESCE(r.penalty_league_points, 0) AS pt,
    CASE WHEN bc.commentator = (SELECT commentator FROM target) THEN 1 ELSE 0 END AS is_target
  FROM game_player_result AS r
  JOIN player AS p ON p.id = r.player_id
  JOIN broadcast_commentary_game AS bc ON bc.game_id = r.game_id
),
aggregate AS (
  SELECT
    player_id, player_name,
    SUM(is_target) AS h_games,
    SUM(CASE WHEN is_target = 0 THEN 1 ELSE 0 END) AS other_games,
    ROUND(SUM(CASE WHEN is_target = 1 THEN pt ELSE 0 END), 1) AS h_total_pt,
    ROUND(SUM(CASE WHEN is_target = 0 THEN pt ELSE 0 END), 1) AS other_total_pt,
    ROUND(SUM(pt), 1) AS total_pt,
    SUM(CASE WHEN is_target = 1 AND game_rank = 1 THEN 1 ELSE 0 END) AS h_top_count,
    SUM(CASE WHEN is_target = 0 AND game_rank = 1 THEN 1 ELSE 0 END) AS other_top_count,
    SUM(CASE WHEN is_target = 1 AND game_rank = 4 THEN 1 ELSE 0 END) AS h_last_count,
    SUM(CASE WHEN is_target = 0 AND game_rank = 4 THEN 1 ELSE 0 END) AS other_last_count,
    SUM(CASE WHEN is_target = 1 THEN game_rank ELSE 0 END) AS h_rank_sum,
    SUM(CASE WHEN is_target = 0 THEN game_rank ELSE 0 END) AS other_rank_sum
  FROM results
  GROUP BY player_id, player_name
),
metrics AS (
  SELECT
    *,
    ROUND(h_total_pt / NULLIF(h_games, 0), 4) AS h_avg_pt,
    ROUND(other_total_pt / NULLIF(other_games, 0), 4) AS other_avg_pt,
    ROUND(100.0 * h_top_count / NULLIF(h_games, 0), 4) AS h_top_pct,
    ROUND(100.0 * other_top_count / NULLIF(other_games, 0), 4) AS other_top_pct,
    ROUND(100.0 * h_last_count / NULLIF(h_games, 0), 4) AS h_last_pct,
    ROUND(100.0 * other_last_count / NULLIF(other_games, 0), 4) AS other_last_pct,
    ROUND(1.0 * h_rank_sum / NULLIF(h_games, 0), 4) AS h_avg_rank,
    ROUND(1.0 * other_rank_sum / NULLIF(other_games, 0), 4) AS other_avg_rank
  FROM aggregate
),
comparison AS (
  SELECT
    *,
    ROUND(h_avg_pt - other_avg_pt, 4) AS delta_avg_pt,
    ROUND(h_top_pct - other_top_pct, 4) AS delta_top_pct_pp,
    CASE WHEN h_games >= 20 AND other_games >= 20 THEN 1 ELSE 0 END AS eligible_for_ranking
  FROM metrics
)
SELECT
  player_id, player_name, h_games, h_total_pt, h_avg_pt,
  h_top_count, h_top_pct, h_last_count, h_last_pct, h_avg_rank,
  other_games, other_total_pt, other_avg_pt,
  other_top_count, other_top_pct, other_last_count, other_last_pct, other_avg_rank,
  total_pt, delta_avg_pt, delta_top_pct_pp, eligible_for_ranking
FROM comparison
ORDER BY eligible_for_ranking DESC, delta_avg_pt DESC, h_games DESC, player_name;
