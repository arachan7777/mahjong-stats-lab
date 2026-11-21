-- 麻雀スタッツ研究所 流局時聴牌率 SQL v0.1
-- 原典：「麻雀スタッツ研究所_database_sqlite3_集計再開マニュアル」
-- 定義：流局局のうち、ryukyoku_player.is_tenpai = 1 の割合。
-- 分子：対象の選手が流局終了時に聴牌していた局数。
-- 分母：対象の選手が参加した流局局数（和了終了局は含まない）。
-- ※ リーチの有無・本人の流局時得失点・親子・本場による除外はしない。
-- ※ 形式聴牌などの追加独自判定はせず、DBのis_tenpaiを原典どおり使う。
-- ※ 一局は一回のみカウント。期間は試合の年度／ステージで指定する。
-- ※ params.start_year=NULL は全シーズン、stage=NULL は全ステージ。
WITH
params AS (SELECT NULL AS start_year, NULL AS stage),
selected_games AS (
  SELECT g.id AS game_id
  FROM game g
  JOIN season_stage ss ON ss.id = g.season_stage_id
  JOIN league_season ls ON ls.id = ss.league_season_id
  CROSS JOIN params cfg
  WHERE (cfg.start_year IS NULL OR ls.start_year = cfg.start_year)
    AND (cfg.stage IS NULL OR ss.stage = cfg.stage)
),
draw_outcomes AS (
  SELECT e.kyoku_id, rp.player_id, rp.is_tenpai, rp.tenpai_points
  FROM ryukyoku_event r
  JOIN event e ON e.id = r.event_id AND e.type = 'ryukyoku'
  JOIN kyoku k ON k.id = e.kyoku_id
  JOIN selected_games sg ON sg.game_id = k.game_id
  JOIN ryukyoku_player rp ON rp.ryukyoku_event_id = r.event_id
),
by_player AS (
  SELECT player_id,
         COUNT(DISTINCT kyoku_id) AS ryukyoku_count,
         COUNT(DISTINCT CASE WHEN is_tenpai = 1 THEN kyoku_id END) AS tenpai_ryukyoku_count,
         COUNT(DISTINCT CASE WHEN is_tenpai = 0 THEN kyoku_id END) AS noten_ryukyoku_count,
         SUM(tenpai_points) AS ryukyoku_tenpai_points_net
  FROM draw_outcomes
  GROUP BY player_id
)
SELECT p.id AS player_id, p.name AS player_name,
       b.ryukyoku_count, b.tenpai_ryukyoku_count, b.noten_ryukyoku_count,
       ROUND(100.0 * b.tenpai_ryukyoku_count / NULLIF(b.ryukyoku_count,0),4)
         AS ryukyoku_tenpai_pct,
       b.ryukyoku_tenpai_points_net
FROM by_player b
JOIN player p ON p.id = b.player_id
ORDER BY ryukyoku_tenpai_pct DESC, b.tenpai_ryukyoku_count DESC,
         b.ryukyoku_count DESC, p.name;
