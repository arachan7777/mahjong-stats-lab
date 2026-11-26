-- 麻雀スタッツ研究所 王牌幽閉率 SQL v0.3（流局時最終テンパイ基準）
-- 定義：流局時にテンパイしている選手を1人×1局で1件とする。
-- 王牌幽閉回数：最終待ち牌が物理的な王牌14枚に1枚以上残っていた件数。
-- 王牌幽閉回数率：王牌幽閉回数 ÷ 流局時テンパイ件数 × 100。
-- 王牌幽閉枚数：最終待ち牌のうち、流局時の物理的な王牌14枚に残っていた実牌枚数の合計。
-- 途中のテンパイ、待ち替え、宣言時点の残枚数は集計しない。
-- 赤5と通常5は同じ牌種。ドラ表示牌も王牌の実牌として主指標に含む。
-- 「tenpai_status」は成立リーチあり/なしの参考内訳。「no_reach」は門前ヤミテンと副露テンパイを含む。
-- params.start_year=NULL、stage=NULL は全期間・全ステージ。
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
  SELECT e.kyoku_id,e.id AS ryukyoku_event_id,e.event_order AS ryukyoku_order
  FROM ryukyoku_event r
  JOIN event e ON e.id=r.event_id AND e.type='ryukyoku'
  JOIN kyoku k ON k.id=e.kyoku_id
  JOIN selected_games sg ON sg.game_id=k.game_id
),
final_tenpai AS MATERIALIZED (
  SELECT ed.kyoku_id,ed.ryukyoku_event_id,ed.ryukyoku_order,
         rp.player_id,
         CASE WHEN EXISTS (
           SELECT 1
           FROM reach_event re
           JOIN event ree ON ree.id=re.event_id
           WHERE ree.kyoku_id=ed.kyoku_id
             AND ree.event_order<=ed.ryukyoku_order
             AND re.actor_player_id=rp.player_id
             AND re.is_accepted=1
         ) THEN 'reach'
         WHEN EXISTS (
           SELECT 1 FROM chi_event c JOIN event ce ON ce.id=c.event_id
           WHERE ce.kyoku_id=ed.kyoku_id AND ce.event_order<=ed.ryukyoku_order
             AND c.actor_player_id=rp.player_id
         ) OR EXISTS (
           SELECT 1 FROM pon_event c JOIN event ce ON ce.id=c.event_id
           WHERE ce.kyoku_id=ed.kyoku_id AND ce.event_order<=ed.ryukyoku_order
             AND c.actor_player_id=rp.player_id
         ) OR EXISTS (
           SELECT 1 FROM daiminkan_event c JOIN event ce ON ce.id=c.event_id
           WHERE ce.kyoku_id=ed.kyoku_id AND ce.event_order<=ed.ryukyoku_order
             AND c.actor_player_id=rp.player_id
         ) OR EXISTS (
           SELECT 1 FROM shominkan_event c JOIN event ce ON ce.id=c.event_id
           WHERE ce.kyoku_id=ed.kyoku_id AND ce.event_order<=ed.ryukyoku_order
             AND c.actor_player_id=rp.player_id
         ) THEN 'open_tenpai'
         ELSE 'menzen_dama' END AS tenpai_status
  FROM exhaustive_draws ed
  JOIN ryukyoku_player rp
    ON rp.ryukyoku_event_id=ed.ryukyoku_event_id
   AND rp.is_tenpai=1
),
last_tenpai_state AS MATERIALIZED (
  SELECT ft.kyoku_id,ft.player_id,pts.waiting_tiles,
         ROW_NUMBER() OVER (
           PARTITION BY ft.kyoku_id,ft.player_id
           ORDER BY e.event_order DESC,e.id DESC
         ) AS rn
  FROM final_tenpai ft
  JOIN player_tenpai_state pts
    ON pts.player_id=ft.player_id AND pts.is_actor=1
  JOIN event e
    ON e.id=pts.event_id AND e.kyoku_id=ft.kyoku_id
   AND e.event_order<=ft.ryukyoku_order
),
final_wait_tiles AS MATERIALIZED (
  SELECT ft.kyoku_id,ft.player_id,ft.ryukyoku_event_id,ft.tenpai_status,
         CASE WHEN substr(TRIM(j.value),1,1)='0'
              THEN '5'||substr(TRIM(j.value),2)
              ELSE TRIM(j.value) END AS tile
  FROM final_tenpai ft
  JOIN last_tenpai_state s
    ON s.kyoku_id=ft.kyoku_id AND s.player_id=ft.player_id AND s.rn=1
  JOIN json_each('["'||replace(s.waiting_tiles,',','","')||'"]') j
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
  SELECT e.kyoku_id,
         CASE WHEN substr(d.tile,1,1)='0'
              THEN '5'||substr(d.tile,2)
              ELSE d.tile END AS tile,
         COUNT(*) AS draw_count
  FROM draw_event d
  JOIN event e ON e.id=d.event_id
  JOIN exhaustive_draws ed ON ed.kyoku_id=e.kyoku_id
  GROUP BY e.kyoku_id,tile
),
visible_dora AS MATERIALIZED (
  SELECT e.kyoku_id,
         CASE WHEN substr(de.dora_indicator_tile,1,1)='0'
              THEN '5'||substr(de.dora_indicator_tile,2)
              ELSE de.dora_indicator_tile END AS tile,
         COUNT(*) AS indicator_count
  FROM dora_indicator_event de
  JOIN event e ON e.id=de.event_id
  JOIN exhaustive_draws ed ON ed.kyoku_id=e.kyoku_id
  WHERE de.dora_type='omote'
  GROUP BY e.kyoku_id,tile
),
per_tenpai AS MATERIALIZED (
  SELECT ft.kyoku_id,ft.player_id,ft.tenpai_status,
         COALESCE(SUM(4-COALESCE(h.dealt_count,0)-COALESCE(d.draw_count,0)),0)
           AS dead_wall_wait_tiles,
         COALESCE(SUM(COALESCE(v.indicator_count,0)),0)
           AS dead_wall_wait_indicators
  FROM final_tenpai ft
  LEFT JOIN final_wait_tiles w
    ON w.kyoku_id=ft.kyoku_id AND w.player_id=ft.player_id
  LEFT JOIN initial_hand_counts h
    ON h.kyoku_id=w.kyoku_id AND h.tile=w.tile
  LEFT JOIN all_draws d
    ON d.kyoku_id=w.kyoku_id AND d.tile=w.tile
  LEFT JOIN visible_dora v
    ON v.kyoku_id=w.kyoku_id AND v.tile=w.tile
  GROUP BY ft.kyoku_id,ft.player_id,ft.tenpai_status
),
status_rows AS (
  SELECT player_id,tenpai_status,
         COUNT(*) AS final_tenpai_count,
         SUM(CASE WHEN dead_wall_wait_tiles>0 THEN 1 ELSE 0 END)
           AS dead_wall_confinement_count,
         SUM(dead_wall_wait_tiles) AS dead_wall_wait_tiles,
         SUM(dead_wall_wait_indicators) AS dead_wall_wait_indicators
  FROM per_tenpai
  GROUP BY player_id,tenpai_status
),
all_rows AS (
  SELECT player_id,'all' AS tenpai_status,
         COUNT(*) AS final_tenpai_count,
         SUM(CASE WHEN dead_wall_wait_tiles>0 THEN 1 ELSE 0 END)
           AS dead_wall_confinement_count,
         SUM(dead_wall_wait_tiles) AS dead_wall_wait_tiles,
         SUM(dead_wall_wait_indicators) AS dead_wall_wait_indicators
  FROM per_tenpai
  GROUP BY player_id
),
results AS (
  SELECT * FROM all_rows
  UNION ALL
  SELECT * FROM status_rows
)
SELECT p.id AS player_id,p.name AS player_name,r.tenpai_status,
       r.final_tenpai_count,r.dead_wall_confinement_count,
       ROUND(100.0*r.dead_wall_confinement_count/
             NULLIF(r.final_tenpai_count,0),4) AS dead_wall_confinement_rate_pct,
       r.dead_wall_wait_tiles,
       ROUND(1.0*r.dead_wall_wait_tiles/
             NULLIF(r.final_tenpai_count,0),4) AS dead_wall_tiles_per_tenpai,
       ROUND(1.0*r.dead_wall_wait_tiles/
             NULLIF(r.dead_wall_confinement_count,0),4)
         AS dead_wall_tiles_per_confined_tenpai,
       r.dead_wall_wait_indicators,
       r.dead_wall_wait_tiles-r.dead_wall_wait_indicators
         AS dead_wall_wait_tiles_excluding_indicators
FROM results r
JOIN player p ON p.id=r.player_id
ORDER BY p.name,
         CASE r.tenpai_status WHEN 'all' THEN 0 WHEN 'reach' THEN 1 ELSE 2 END;
