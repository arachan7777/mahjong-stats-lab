-- 麻雀スタッツ研究所：東南西北の初期座席成績（白卓・黒卓）・試算専用
-- 本SQLは原典（独立21指標群＋派生2種）を変更しない。
-- 取得元：konoui/m-league-game-db の公開SQLite。
-- 対象座位：東1局最初の局の kyoku_player_result.player_wind（1z=東、2z=南、3z=西、4z=北）。
-- 卓：公式試合ID m_league_game_id の末尾 A=白卓、B=黒卓。
-- 順位：game_player_result.rank を正とする（同点順位を独自に修正しない）。
-- 獲得pt：game_player_result.league_points + penalty_league_points。
-- このSQLは全期間の選手×試合レコードを出力。
-- 集計期間は検証用 Python スクリプトで2025-26以降レギュラーを主対象にし、
-- 卓別、シーズン別、2卓同時開催日、および全歴史の参考値を作る。
WITH first_east_one AS (
  SELECT k.game_id, MIN(k.id) AS first_kyoku_id
  FROM kyoku k
  WHERE k.round = '1z1'
  GROUP BY k.game_id
)
SELECT
  g.id AS game_id,
  g.m_league_game_id AS official_game_id,
  g.date AS game_date,
  ls.start_year AS season_start_year,
  ss.stage AS stage,
  g.day_game_number AS day_game_number,
  CASE SUBSTR(g.m_league_game_id,-1,1)
    WHEN 'A' THEN '白卓'
    WHEN 'B' THEN '黒卓'
    ELSE '不明'
  END AS table_name,
  kpr.player_wind AS seat_wind,
  gpr.player_id AS player_id,
  p.name AS player_name,
  gpr.team_id AS team_id,
  gpr.rank AS final_rank,
  gpr.score AS final_score,
  ROUND(gpr.league_points + gpr.penalty_league_points, 4) AS final_pt
FROM game g
JOIN season_stage ss ON ss.id = g.season_stage_id
JOIN league_season ls ON ls.id = ss.league_season_id
JOIN first_east_one fe ON fe.game_id = g.id
JOIN kyoku_player_result kpr ON kpr.kyoku_id = fe.first_kyoku_id
JOIN game_player_result gpr
  ON gpr.game_id = g.id AND gpr.player_id = kpr.player_id
JOIN player p ON p.id = gpr.player_id
ORDER BY g.id, kpr.player_wind;
