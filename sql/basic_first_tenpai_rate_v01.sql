-- 麻雀スタッツ研究所 正式共通集計SQL / 先制テンパイ率
-- 定義：本人がその局で最も早くテンパイを完成させた局数 ÷ 本人参加局数。
-- 先制は配牌または本人の打牌直後の player_tenpai_state (is_actor=1) の最初のイベント。
-- 先制テンパイ成立者が一人も確認できない局は分子に含めず、分母の参加局には含む。
-- 既存の独立21指標＋派生2種には変更なし。全期間・全選手。読み取り専用。
WITH
candidate_tenpai AS MATERIALIZED (
 SELECT e.kyoku_id,e.event_order,pts.player_id,
 ROW_NUMBER() OVER (PARTITION BY e.kyoku_id ORDER BY e.event_order,pts.player_id) AS first_position
 FROM player_tenpai_state pts JOIN event e ON e.id=pts.event_id
 WHERE pts.is_actor=1 AND e.type IN ('haipai','discard')
),
first_tenpai AS MATERIALIZED (
 SELECT p.name player_name,ls.start_year season_start_year,ss.stage,
 COUNT(*) AS first_count
 FROM candidate_tenpai c
 JOIN player p ON p.id=c.player_id
 JOIN kyoku k ON k.id=c.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE c.first_position=1
 GROUP BY p.name,ls.start_year,ss.stage
),
base_stats AS MATERIALIZED (
 SELECT player_name,season_start_year,stage,
        SUM(total_kyoku_count) AS played_kyoku,
        SUM(total_game_count) AS played_games
 FROM player_season_stage_stats_base
 GROUP BY player_name,season_start_year,stage
),
per_stage AS MATERIALIZED (
 SELECT b.player_name,b.season_start_year,b.stage,b.played_kyoku,b.played_games,
        COALESCE(f.first_count,0) AS first_count
 FROM base_stats b
 LEFT JOIN first_tenpai f ON f.player_name=b.player_name
   AND f.season_start_year=b.season_start_year AND f.stage=b.stage
),
scoped AS (
 SELECT 'all' AS period, NULL AS season_start_year, NULL AS stage, player_name, played_kyoku, played_games, first_count FROM per_stage
 UNION ALL SELECT 'season', season_start_year, NULL, player_name, played_kyoku, played_games, first_count FROM per_stage
 UNION ALL SELECT 'stage', NULL, stage, player_name, played_kyoku, played_games, first_count FROM per_stage
 UNION ALL SELECT 'season_stage', season_start_year, stage, player_name, played_kyoku, played_games, first_count FROM per_stage
),
aggregated AS (
 SELECT period,season_start_year,stage,player_name,
        SUM(played_kyoku) played_kyoku,SUM(played_games) played_games,
        SUM(first_count) first_count
 FROM scoped
 GROUP BY period,season_start_year,stage,player_name
),
ranked AS (
 SELECT *,
        ROUND(100.0*first_count/NULLIF(played_kyoku,0),4) first_rate_pct,
        ROUND(100.0*SUM(first_count) OVER w/NULLIF(SUM(played_kyoku) OVER w,0),4) league_rate_pct,
        ROW_NUMBER() OVER (PARTITION BY period,season_start_year,stage
                           ORDER BY 1.0*first_count/NULLIF(played_kyoku,0) DESC,first_count DESC,player_name ASC) league_rank,
        COUNT(*) OVER w players_count
 FROM aggregated
 WINDOW w AS (PARTITION BY period,season_start_year,stage)
)
SELECT * FROM ranked
ORDER BY CASE period WHEN 'all' THEN 0 WHEN 'season' THEN 1 WHEN 'stage' THEN 2 ELSE 3 END,
 season_start_year,stage,league_rank;
