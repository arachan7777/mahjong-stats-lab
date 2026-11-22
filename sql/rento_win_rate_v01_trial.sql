-- 麻雀スタッツ研究所：連闘勝率 試算SQL v0.1
-- 定義：「同一日・同一ステージ・同一卓の第1試合と第2試合」に同じ選手が出場。
-- 連闘勝率：連闘した第2試合で1着だった回数 / 連闘した第2試合への出場回数 ×100。
-- 対照：連闘していない選手の同じ第2試合トップ率。理論値25%とも比較。
-- 一試合の2戦目1出場は1機会。ダブルトップは両試合とも最終1着の連闘。
-- 卓判定：Mリーグ公式試合IDの末尾 A=白卓、B=黒卓。第1／第2はday_game_number。
-- 順位：game_player_result.rank、pt：league_points + penalty_league_points。
-- 全年度・レギュラー／セミファイナル／ファイナル。ステージ別は集計側で分ける。
-- 候補指標の試算のみ。既存の独立21指標群と派生2種は変更しない。
WITH
games_with_table AS (
 SELECT
   g.id AS game_id,
   g.date AS game_date,
   g.season_stage_id,
   ss.stage AS stage,
   ls.start_year AS season_start_year,
   g.day_game_number AS game_number,
   SUBSTR(g.m_league_game_id, -1, 1) AS table_code,
   g.m_league_game_id AS official_game_id
 FROM game g
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE SUBSTR(g.m_league_game_id, -1, 1) IN ('A','B')
),
paired_games AS (
 SELECT
    first.game_id AS first_game_id,
    second.game_id AS second_game_id,
    second.game_date,
    second.stage,
    second.season_start_year,
    second.table_code,
    first.official_game_id AS first_official_id,
    second.official_game_id AS second_official_id
 FROM games_with_table first
 JOIN games_with_table second
   ON first.game_date=second.game_date
  AND first.season_stage_id=second.season_stage_id
  AND first.table_code=second.table_code
  AND first.game_number=1
  AND second.game_number=2
)
SELECT
  pair.first_game_id,
  pair.second_game_id,
  pair.game_date,
  pair.stage,
  pair.season_start_year,
  pair.table_code,
  pair.first_official_id,
  pair.second_official_id,
  second.player_id,
  p.name AS player_name,
  second.team_id AS team_id,
  CASE WHEN first.player_id IS NOT NULL THEN 1 ELSE 0 END AS is_repeat,
  first.rank AS first_rank,
  ROUND(first.league_points + first.penalty_league_points,1) AS first_pt,
  second.rank AS second_rank,
  ROUND(second.league_points + second.penalty_league_points,1) AS second_pt
FROM paired_games pair
JOIN game_player_result second ON second.game_id=pair.second_game_id
LEFT JOIN game_player_result first
  ON first.game_id=pair.first_game_id AND first.player_id=second.player_id
JOIN player p ON p.id=second.player_id
ORDER BY pair.second_game_id, second.player_id;
