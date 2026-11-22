-- 麻雀スタッツ研究所｜保管指標「西川幸太郎指数」Ver.2
-- 正式SQLとして保存／アプリ・動画等での使用は現時点では保留。
-- 2026-09-24確定のVer.2定義を継承（Ver.1と混同しない）。
--
-- 指数 = 西牌放銃率(%) + 南4局放銃率(%) + 役満放銃占有率(%)
-- ① 西牌放銃率 = 西（3z）ロン放銃回数 / 本人の総ロン放銃回数 × 100
-- ② 南4局放銃率 = 南4局（2z4、本場を問わない）ロン放銃回数
--                  / 本人の総ロン放銃回数 × 100
-- ③ 役満放銃占有率 = 本人の役満ロン放銃回数
--                   / 対象範囲の全選手の役満ロン放銃回数 × 100
-- ①②③は重複して該当してもそれぞれに加算する。
-- ロンのみ。ツモで親被り・被ツモした局は放銃として数えない。
-- 役満の判定は agari_event.is_yakuman=1 を使う（翻数で代用しない）。
-- ダブロン時は agari_event ごとのロン成立をそれぞれ1回として集計。
--
-- 使用範囲：全期間・全ステージ、パラメータがNULLなら絞り込まない。
-- 個人の総放銃0、または範囲内の役満ロン放銃総数0の場合、指数はNULL。
WITH
params AS (
  SELECT
    NULL AS start_year,
    NULL AS stage,
    NULL AS end_date
),
selected_games AS (
  SELECT g.id AS game_id
  FROM game g
  JOIN season_stage ss ON ss.id = g.season_stage_id
  JOIN league_season ls ON ls.id = ss.league_season_id
  CROSS JOIN params prm
  WHERE (prm.start_year IS NULL OR ls.start_year = prm.start_year)
    AND (prm.stage IS NULL OR ss.stage = prm.stage)
    AND (prm.end_date IS NULL OR g.date <= prm.end_date)
),
dealin_events AS (
  SELECT
    ae.event_id,
    ae.target_player_id AS player_id,
    ae.agari_tile,
    k.round,
    ae.is_yakuman
  FROM agari_event ae
  JOIN event e ON e.id = ae.event_id
  JOIN kyoku k ON k.id = e.kyoku_id
  JOIN selected_games sg ON sg.game_id = k.game_id
  WHERE e.type = 'ron'
    AND ae.target_player_id IS NOT NULL
),
by_player AS (
  SELECT
    player_id,
    COUNT(*) AS total_dealin_count,
    SUM(CASE WHEN agari_tile = '3z' THEN 1 ELSE 0 END)
      AS west_dealin_count,
    SUM(CASE WHEN round = '2z4' THEN 1 ELSE 0 END)
      AS south4_dealin_count,
    SUM(CASE WHEN is_yakuman = 1 THEN 1 ELSE 0 END)
      AS yakuman_dealin_count
  FROM dealin_events
  GROUP BY player_id
),
global_yakuman AS (
  SELECT COUNT(*) AS total_yakuman_ron_dealin_count
  FROM dealin_events
  WHERE is_yakuman = 1
),
counts AS (
  SELECT
    p.id AS player_id,
    p.name AS player_name,
    COALESCE(bp.total_dealin_count, 0) AS total_dealin_count,
    COALESCE(bp.west_dealin_count, 0) AS west_dealin_count,
    COALESCE(bp.south4_dealin_count, 0) AS south4_dealin_count,
    COALESCE(bp.yakuman_dealin_count, 0) AS yakuman_dealin_count,
    gy.total_yakuman_ron_dealin_count
  FROM player p
  LEFT JOIN by_player bp ON bp.player_id = p.id
  CROSS JOIN global_yakuman gy
)
SELECT
  player_id,
  player_name,
  total_dealin_count,
  west_dealin_count,
  south4_dealin_count,
  yakuman_dealin_count,
  total_yakuman_ron_dealin_count,
  ROUND(100.0 * west_dealin_count / NULLIF(total_dealin_count, 0), 4)
    AS west_dealin_pct,
  ROUND(100.0 * south4_dealin_count / NULLIF(total_dealin_count, 0), 4)
    AS south4_dealin_pct,
  ROUND(100.0 * yakuman_dealin_count /
        NULLIF(total_yakuman_ron_dealin_count, 0), 4)
    AS yakuman_dealin_share_pct,
  ROUND(
    100.0 * west_dealin_count / NULLIF(total_dealin_count, 0)
    + 100.0 * south4_dealin_count / NULLIF(total_dealin_count, 0)
    + 100.0 * yakuman_dealin_count /
      NULLIF(total_yakuman_ron_dealin_count, 0),
    4
  ) AS nishikawa_kotaro_index
FROM counts
ORDER BY
  nishikawa_kotaro_index DESC,
  yakuman_dealin_count DESC,
  west_dealin_count DESC,
  player_name;
