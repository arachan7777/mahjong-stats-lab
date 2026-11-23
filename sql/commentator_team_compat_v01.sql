-- 麻雀スタッツ研究所　実況者×チーム相性（全ステージ / レギュラー） v0.1
-- 正本：2026-11-20版MリーグDB + 同日固定実況マスター
-- 実行前：sql/broadcast_commentary_master_20261120_v01.sql を読み込む。
-- チーム所属は game_player_result.team_id を使用（移籍・在籍時期を反映）。
-- ポイント = league_points + penalty_league_points（反則減点を含む）。
-- 「対戦3チーム平均との得失点差」＝自身の獲得pt - 同卓相手3チームの平均pt。
-- 相性差 = 対象実況時平均pt - その他実況時平均pt。
-- ランキング対象は双方20試合以上。順位対象外も残す。
WITH target AS (
  SELECT '日吉辰哉' AS commentator
),
game_points AS (
  SELECT
    r.game_id,
    r.team_id,
    t.name AS team_name,
    s.stage,
    r.rank AS game_rank,
    r.score,
    COALESCE(r.league_points, 0) + COALESCE(r.penalty_league_points, 0) AS pt,
    bc.commentator,
    CASE WHEN bc.commentator = (SELECT commentator FROM target) THEN 1 ELSE 0 END AS is_target
  FROM game_player_result AS r
  JOIN team AS t ON t.id = r.team_id
  JOIN game AS g ON g.id = r.game_id
  JOIN season_stage AS s ON s.id = g.season_stage_id
  JOIN broadcast_commentary_game AS bc ON bc.game_id = r.game_id
),
with_margin AS (
  SELECT *,
    (4.0 * pt - SUM(pt) OVER (PARTITION BY game_id)) / 3.0 AS margin_vs_3_opponents,
    score - 25000 AS score_delta
  FROM game_points
),
scoped AS (
  SELECT 'all' AS scope, * FROM with_margin
  UNION ALL
  SELECT 'regular' AS scope, * FROM with_margin WHERE stage = 'regular'
),
aggregate AS (
  SELECT
    scope, team_id, team_name,
    SUM(is_target) AS h_games,
    SUM(CASE WHEN is_target = 0 THEN 1 ELSE 0 END) AS other_games,
    ROUND(SUM(CASE WHEN is_target = 1 THEN pt ELSE 0 END), 1) AS h_total_pt,
    ROUND(SUM(CASE WHEN is_target = 0 THEN pt ELSE 0 END), 1) AS other_total_pt,
    SUM(CASE WHEN is_target = 1 AND game_rank = 1 THEN 1 ELSE 0 END) AS h_top_count,
    SUM(CASE WHEN is_target = 0 AND game_rank = 1 THEN 1 ELSE 0 END) AS other_top_count,
    SUM(CASE WHEN is_target = 1 AND game_rank = 4 THEN 1 ELSE 0 END) AS h_last_count,
    SUM(CASE WHEN is_target = 0 AND game_rank = 4 THEN 1 ELSE 0 END) AS other_last_count,
    SUM(CASE WHEN is_target = 1 THEN game_rank ELSE 0 END) AS h_rank_sum,
    SUM(CASE WHEN is_target = 0 THEN game_rank ELSE 0 END) AS other_rank_sum,
    ROUND(SUM(CASE WHEN is_target = 1 THEN margin_vs_3_opponents ELSE 0 END), 1) AS h_total_margin,
    ROUND(SUM(CASE WHEN is_target = 0 THEN margin_vs_3_opponents ELSE 0 END), 1) AS other_total_margin,
    ROUND(SUM(CASE WHEN is_target = 1 THEN score_delta ELSE 0 END), 0) AS h_total_score_delta
  FROM scoped
  GROUP BY scope, team_id, team_name
),
metrics AS (
  SELECT *,
    ROUND(h_total_pt / NULLIF(h_games, 0), 4) AS h_avg_pt,
    ROUND(other_total_pt / NULLIF(other_games, 0), 4) AS other_avg_pt,
    ROUND(100.0 * h_top_count / NULLIF(h_games, 0), 4) AS h_top_pct,
    ROUND(100.0 * other_top_count / NULLIF(other_games, 0), 4) AS other_top_pct,
    ROUND(100.0 * h_last_count / NULLIF(h_games, 0), 4) AS h_last_pct,
    ROUND(100.0 * other_last_count / NULLIF(other_games, 0), 4) AS other_last_pct,
    ROUND(1.0 * h_rank_sum / NULLIF(h_games, 0), 4) AS h_avg_rank,
    ROUND(1.0 * other_rank_sum / NULLIF(other_games, 0), 4) AS other_avg_rank,
    ROUND(h_total_margin / NULLIF(h_games, 0), 4) AS h_avg_margin,
    ROUND(other_total_margin / NULLIF(other_games, 0), 4) AS other_avg_margin,
    ROUND(h_total_score_delta / NULLIF(h_games, 0), 2) AS h_avg_score_delta
  FROM aggregate
),
comparison AS (
  SELECT *,
    ROUND(h_avg_pt - other_avg_pt, 4) AS delta_avg_pt,
    ROUND(h_top_pct - other_top_pct, 4) AS delta_top_pct_pp,
    ROUND(h_avg_rank - other_avg_rank, 4) AS delta_avg_rank,
    ROUND(h_avg_margin - other_avg_margin, 4) AS delta_avg_margin,
    CASE WHEN h_games >= 20 AND other_games >= 20 THEN 1 ELSE 0 END AS eligible_for_ranking
  FROM metrics
)
SELECT
  scope, team_id, team_name, h_games, h_total_pt, h_avg_pt, h_top_count,
  h_top_pct, h_last_count, h_last_pct, h_avg_rank,
  h_total_margin, h_avg_margin, h_total_score_delta, h_avg_score_delta,
  other_games, other_total_pt, other_avg_pt, other_top_count,
  other_top_pct, other_last_count, other_last_pct, other_avg_rank,
  other_total_margin, other_avg_margin,
  delta_avg_pt, delta_top_pct_pp, delta_avg_rank, delta_avg_margin, eligible_for_ranking
FROM comparison
ORDER BY scope, eligible_for_ranking DESC, delta_avg_pt ASC, h_games DESC, team_name;
