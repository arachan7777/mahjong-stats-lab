-- 麻雀スタッツ研究所 正式共通集計SQL / 獲得Mリーグポイント
-- 定義：game_player_result.league_points＋penalty_league_points（反則減点含む）。
-- 各局の得点ではなく、試合順位点を含むMリーグ公式pt。合計は0.1ptに丸める。
-- 試合ごとの平均はpt合計/出場試合数。全シーズン・全ステージ・全選手。
-- 既存の独立21指標＋派生2種の定義・番号は変更しない。読み取り専用。
WITH
base AS MATERIALIZED (
 SELECT gr.player_id,p.name player_name,ls.start_year season_start_year,ss.stage,
 gr.game_id,gr.rank,
 (gr.league_points+gr.penalty_league_points) AS points
 FROM game_player_result gr
 JOIN player p ON p.id=gr.player_id
 JOIN game g ON g.id=gr.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
),
scoped AS (
 SELECT 'all' AS period, NULL AS season_start_year, NULL AS stage, player_id, player_name, game_id, points, rank FROM base
 UNION ALL SELECT 'season', season_start_year, NULL, player_id, player_name, game_id, points, rank FROM base
 UNION ALL SELECT 'stage', NULL, stage, player_id, player_name, game_id, points, rank FROM base
 UNION ALL SELECT 'season_stage', season_start_year, stage, player_id, player_name, game_id, points, rank FROM base
),
aggregated AS (
 SELECT period,season_start_year,stage,player_id,player_name,
        COUNT(*) played_games,ROUND(SUM(points),1) total_points,
        ROUND(AVG(points),4) points_per_game,
        SUM(CASE WHEN rank=1 THEN 1 ELSE 0 END) first_place_count,
        ROUND(AVG(rank),4) avg_rank
 FROM scoped
 GROUP BY period,season_start_year,stage,player_id,player_name
),
ranked AS (
 SELECT *,
 ROW_NUMBER() OVER(PARTITION BY period,season_start_year,stage
   ORDER BY total_points DESC,points_per_game DESC,player_name ASC) rank_total_points,
 ROW_NUMBER() OVER(PARTITION BY period,season_start_year,stage
   ORDER BY points_per_game DESC,played_games DESC,player_name ASC) rank_points_per_game,
 COUNT(*) OVER(PARTITION BY period,season_start_year,stage) players_count
 FROM aggregated
)
SELECT * FROM ranked
ORDER BY CASE period WHEN 'all' THEN 0 WHEN 'season' THEN 1 WHEN 'stage' THEN 2 ELSE 3 END,
 season_start_year,stage,rank_total_points;
