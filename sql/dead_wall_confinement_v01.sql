-- 麻雀スタッツ研究所 王牌幽閉率 SQL v0.1
-- 基準: ユーザーによる2026-11-22定義説明。
-- 「最初に聴牌した時点の待ち牌5枚のうち、その同じ牌種が
--   流局時の王牌14枚に4枚残れば幽閉率は80%」。
-- 対象: 流局した局の中で、本人が一度でも聴牌した局。
-- 初聴牌とは本人のis_actor=1の最初の聴牌スナップショット。
-- 分母: 初聴牌直後に、4人の配牌とその時までのツモで取得されていない
--       『元の待ち牌』の物理的な残枚数（牌種ごとに4枚から差し引く）。
-- 分子: 流局までの全ツモ終了後に14枚の王牌に残った『元の待ち牌』の枚数。
--       ドラ表示牌も王牌の物理的な14枚に含む（点数集計と無関係）。
-- 待ち替えがあっても、初聴牌時の待ち牌をそのまま追跡する。
-- 集約: 各選手の分子合計 ÷ 分母合計 ×100。個別事例は 4/5=80%。
-- 補助: 公開ドラ表示牌を除外した「非ドラ表示枚数」の比率も別列。
--       元のDB available_tile_countは公開ドラ表示牌を除外しているため、
--       物理的な全14枚を扱う主指標にはそのまま流用しない。
-- start_year=NULLで全年度、stage=NULLで全ステージ。
-- 和了終了局は対象外。局内で一度も聴牌していない選手は対象外。
-- サンプルに分母0の局があっても総分母には0を加算（0/0 は表示しない）。
WITH
params AS (SELECT NULL AS start_year, NULL AS stage),
selected_games AS MATERIALIZED (
  SELECT g.id AS game_id
  FROM game g
  JOIN season_stage ss ON ss.id=g.season_stage_id
  JOIN league_season ls ON ls.id=ss.league_season_id
  CROSS JOIN params cfg
  WHERE (cfg.start_year IS NULL OR ls.start_year=cfg.start_year)
    AND (cfg.stage IS NULL OR ss.stage=cfg.stage)
),
exhaustive_draws AS MATERIALIZED (
  SELECT e.kyoku_id
  FROM ryukyoku_event r
  JOIN event e ON e.id=r.event_id
  JOIN kyoku k ON k.id=e.kyoku_id
  JOIN selected_games sg ON sg.game_id=k.game_id
),
first_tenpai_ranked AS MATERIALIZED (
  SELECT e.kyoku_id,pts.player_id,e.event_order,e.id AS snapshot_event_id,
         pts.waiting_tiles,
         ROW_NUMBER() OVER (
           PARTITION BY e.kyoku_id,pts.player_id
           ORDER BY e.event_order,e.id
         ) AS rn
  FROM player_tenpai_state pts
  JOIN event e ON e.id=pts.event_id
  JOIN exhaustive_draws ed ON ed.kyoku_id=e.kyoku_id
  WHERE pts.is_actor=1
),
original_wait_tiles AS MATERIALIZED (
  SELECT f.kyoku_id,f.player_id,f.event_order AS tenpai_order,
         CASE WHEN substr(TRIM(j.value),1,1)='0'
              THEN '5'||substr(TRIM(j.value),2)
              ELSE TRIM(j.value) END AS tile
  FROM first_tenpai_ranked f
  JOIN json_each('["'||replace(f.waiting_tiles,',','","')||'"]') j
  WHERE f.rn=1
),
initial_hand_counts AS MATERIALIZED (
  SELECT e.kyoku_id,
         CASE WHEN substr(TRIM(j.value),1,1)='0'
              THEN '5'||substr(TRIM(j.value),2)
              ELSE TRIM(j.value) END AS tile,
         COUNT(*) AS dealt_count
  FROM haipai_event h
  JOIN event e ON e.id=h.event_id
  JOIN exhaustive_draws ed ON ed.kyoku_id=e.kyoku_id
  JOIN json_each('["'||replace(h.hand,',','","')||'"]') j
  GROUP BY e.kyoku_id,tile
),
all_draws AS MATERIALIZED (
  SELECT e.kyoku_id,e.event_order,
         CASE WHEN substr(d.tile,1,1)='0'
              THEN '5'||substr(d.tile,2)
              ELSE d.tile END AS tile
  FROM draw_event d
  JOIN event e ON e.id=d.event_id
  JOIN exhaustive_draws ed ON ed.kyoku_id=e.kyoku_id
),
visible_dora AS MATERIALIZED (
  SELECT e.kyoku_id,e.event_order,
         CASE WHEN substr(de.dora_indicator_tile,1,1)='0'
              THEN '5'||substr(de.dora_indicator_tile,2)
              ELSE de.dora_indicator_tile END AS tile
  FROM dora_indicator_event de
  JOIN event e ON e.id=de.event_id
  JOIN exhaustive_draws ed ON ed.kyoku_id=e.kyoku_id
  WHERE de.dora_type='omote'
),
per_wait_tile AS (
  SELECT w.kyoku_id,w.player_id,w.tile,
         (4-COALESCE(h.dealt_count,0)
            -(SELECT COUNT(*) FROM all_draws d
              WHERE d.kyoku_id=w.kyoku_id AND d.tile=w.tile
                AND d.event_order<w.tenpai_order)) AS initial_remaining,
         (4-COALESCE(h.dealt_count,0)
            -(SELECT COUNT(*) FROM all_draws d
              WHERE d.kyoku_id=w.kyoku_id AND d.tile=w.tile)) AS final_king_wall,
         (SELECT COUNT(*) FROM visible_dora v
           WHERE v.kyoku_id=w.kyoku_id AND v.tile=w.tile
             AND v.event_order<=w.tenpai_order) AS first_visible_dora,
         (SELECT COUNT(*) FROM visible_dora v
           WHERE v.kyoku_id=w.kyoku_id AND v.tile=w.tile) AS final_visible_dora
  FROM original_wait_tiles w
  LEFT JOIN initial_hand_counts h ON h.kyoku_id=w.kyoku_id AND h.tile=w.tile
),
by_kyoku AS (
  SELECT player_id,kyoku_id,
         SUM(initial_remaining) AS initial_wait_tiles,
         SUM(final_king_wall) AS dead_wall_wait_tiles,
         SUM(first_visible_dora) AS initial_dora_indicators,
         SUM(final_visible_dora) AS final_dora_indicators
  FROM per_wait_tile
  GROUP BY player_id,kyoku_id
),
by_player AS (
  SELECT player_id,
         COUNT(*) AS first_tenpai_exhaustive_draw_kyoku,
         SUM(CASE WHEN initial_wait_tiles>0 THEN 1 ELSE 0 END) AS positive_wait_count_kyoku,
         SUM(initial_wait_tiles) AS initial_wait_tiles_total,
         SUM(dead_wall_wait_tiles) AS dead_wall_wait_tiles_total,
         SUM(initial_dora_indicators) AS initial_dora_indicator_wait_tiles,
         SUM(final_dora_indicators) AS final_dora_indicator_wait_tiles
  FROM by_kyoku
  GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.first_tenpai_exhaustive_draw_kyoku,b.positive_wait_count_kyoku,
       b.initial_wait_tiles_total,b.dead_wall_wait_tiles_total,
       ROUND(100.0*b.dead_wall_wait_tiles_total/
             NULLIF(b.initial_wait_tiles_total,0),4) AS dead_wall_confinement_pct,
       b.initial_dora_indicator_wait_tiles,b.final_dora_indicator_wait_tiles,
       ROUND(100.0*(b.dead_wall_wait_tiles_total-b.final_dora_indicator_wait_tiles)/
         NULLIF(b.initial_wait_tiles_total-b.initial_dora_indicator_wait_tiles,0),4)
         AS dead_wall_non_indicator_pct
FROM by_player b JOIN player p ON p.id=b.player_id
ORDER BY dead_wall_confinement_pct DESC,
         b.dead_wall_wait_tiles_total DESC,
         b.first_tenpai_exhaustive_draw_kyoku DESC,p.name;
