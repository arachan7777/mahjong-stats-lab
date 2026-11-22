-- 麻雀スタッツ研究所 王牌幽閉率 SQL v0.2（待ち替え加算方式）
-- v0.1「初聴牌1回のみ追跡」は保存したまま、新方式を独立ファイルで追加。
-- 2026-11-22の明示指示: 流局局内で待ちが変わるたび、新たな待ちを計上。
-- 自分の最新の聴牌時の待ち集合が直前の聴牌時と同じなら再計上しない。
-- A→B→A のように一度別の待ちを経た場合、再度のAも新たな待ちとして計上。
-- テンパイを崩して同じ待ちに戻る場合は、待ち集合が変わらないので再計上しない。
-- 待ち集合を構成する牌種はソートして比較し、並び順だけの変化は無視する。
-- 各新規待ちの分母: その聴牌直後の残り待ち牌枚数（配牌と既済の全ツモから）。
-- 各新規待ちの分子: 同じ待ち牌種が流局後の王牌14枚に残った枚数。
-- 王牌内のドラ表示牌も物理的王牌として主指標に含め、除外値は参考列。
-- 残り待ち牌0枚の新規待ちは、分母・分子とも対象外として扱う。
-- 1局に複数の待ち変化があれば、その都度分子・分母を加算。
-- 集計は局ごとの比率平均でなく、全待ち変化の枚数合算の比率。
-- ロン/ツモ和了で終了した局は対象外。start_year/stage NULL は全期間。
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
own_tenpai_snapshots AS MATERIALIZED (
  SELECT e.kyoku_id,pts.player_id,e.event_order,e.id AS wait_event_id,
         pts.waiting_tiles
  FROM player_tenpai_state pts
  JOIN event e ON e.id=pts.event_id
  JOIN exhaustive_draws ed ON ed.kyoku_id=e.kyoku_id
  WHERE pts.is_actor=1
),
canonical_wait_snapshots AS MATERIALIZED (
  SELECT s.*,
         (SELECT group_concat(tile_norm, ',')
          FROM (
            SELECT CASE WHEN substr(trim(j.value),1,1)='0'
                        THEN '5'||substr(trim(j.value),2)
                        ELSE trim(j.value) END AS tile_norm
            FROM json_each('["'||replace(s.waiting_tiles,',','","')||'"]') j
            ORDER BY tile_norm
          )
         ) AS wait_signature
  FROM own_tenpai_snapshots s
),
wait_transitions AS MATERIALIZED (
  SELECT t.*,
         LAG(t.wait_signature) OVER (
           PARTITION BY t.kyoku_id,t.player_id
           ORDER BY t.event_order,t.wait_event_id
         ) AS previous_wait_signature
  FROM canonical_wait_snapshots t
),
wait_episodes AS MATERIALIZED (
  SELECT kyoku_id,player_id,event_order,wait_event_id,waiting_tiles,wait_signature
  FROM wait_transitions
  WHERE previous_wait_signature IS NULL
     OR previous_wait_signature<>wait_signature
),
original_wait_tiles AS MATERIALIZED (
  SELECT f.kyoku_id,f.player_id,f.wait_event_id,f.event_order AS tenpai_order,
         CASE WHEN substr(TRIM(j.value),1,1)='0'
              THEN '5'||substr(TRIM(j.value),2)
              ELSE TRIM(j.value) END AS tile
  FROM wait_episodes f
  JOIN json_each('["'||replace(f.waiting_tiles,',','","')||'"]') j
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
draw_counts_by_wait AS MATERIALIZED (
  SELECT w.kyoku_id,w.player_id,w.wait_event_id,w.tile,
         COUNT(d.event_order) AS all_draw_count,
         SUM(CASE WHEN d.event_order<w.tenpai_order THEN 1 ELSE 0 END)
           AS before_tenpai_draw_count
  FROM original_wait_tiles w
  LEFT JOIN all_draws d ON d.kyoku_id=w.kyoku_id AND d.tile=w.tile
  GROUP BY w.kyoku_id,w.player_id,w.wait_event_id,w.tile,w.tenpai_order
),
visible_dora_by_wait AS MATERIALIZED (
  SELECT w.kyoku_id,w.player_id,w.wait_event_id,w.tile,
         COUNT(v.event_order) AS all_dora_count,
         SUM(CASE WHEN v.event_order<=w.tenpai_order THEN 1 ELSE 0 END)
           AS before_tenpai_dora_count
  FROM original_wait_tiles w
  LEFT JOIN visible_dora v ON v.kyoku_id=w.kyoku_id AND v.tile=w.tile
  GROUP BY w.kyoku_id,w.player_id,w.wait_event_id,w.tile,w.tenpai_order
),
per_wait_tile AS (
  SELECT w.kyoku_id,w.player_id,w.wait_event_id,w.tile,
         4-COALESCE(h.dealt_count,0)-COALESCE(dc.before_tenpai_draw_count,0)
           AS initial_remaining,
         4-COALESCE(h.dealt_count,0)-COALESCE(dc.all_draw_count,0)
           AS final_king_wall,
         COALESCE(v.before_tenpai_dora_count,0) AS first_visible_dora,
         COALESCE(v.all_dora_count,0) AS final_visible_dora
  FROM original_wait_tiles w
  LEFT JOIN initial_hand_counts h
    ON h.kyoku_id=w.kyoku_id AND h.tile=w.tile
  JOIN draw_counts_by_wait dc
    ON dc.kyoku_id=w.kyoku_id AND dc.player_id=w.player_id
       AND dc.wait_event_id=w.wait_event_id AND dc.tile=w.tile
  JOIN visible_dora_by_wait v
    ON v.kyoku_id=w.kyoku_id AND v.player_id=w.player_id
       AND v.wait_event_id=w.wait_event_id AND v.tile=w.tile
),
by_episode AS (
  SELECT player_id,kyoku_id,wait_event_id,
         SUM(initial_remaining) AS initial_wait_tiles,
         SUM(final_king_wall) AS dead_wall_wait_tiles,
         SUM(first_visible_dora) AS initial_dora_indicators,
         SUM(final_visible_dora) AS final_dora_indicators
  FROM per_wait_tile
  GROUP BY player_id,kyoku_id,wait_event_id
),
eligible_episodes AS (
  SELECT * FROM by_episode WHERE initial_wait_tiles>0
),
by_player AS (
  SELECT player_id,
         COUNT(DISTINCT kyoku_id) AS eligible_exhaustive_draw_kyoku,
         COUNT(*) AS wait_change_episode_count,
         SUM(initial_wait_tiles) AS initial_wait_tiles_total,
         SUM(dead_wall_wait_tiles) AS dead_wall_wait_tiles_total,
         SUM(initial_dora_indicators) AS initial_dora_indicator_wait_tiles,
         SUM(final_dora_indicators) AS final_dora_indicator_wait_tiles
  FROM eligible_episodes
  GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.eligible_exhaustive_draw_kyoku,b.wait_change_episode_count,
       b.initial_wait_tiles_total,b.dead_wall_wait_tiles_total,
       ROUND(100.0*b.dead_wall_wait_tiles_total/
             NULLIF(b.initial_wait_tiles_total,0),4) AS dead_wall_confinement_pct,
       b.initial_dora_indicator_wait_tiles,b.final_dora_indicator_wait_tiles,
       ROUND(100.0*(b.dead_wall_wait_tiles_total-b.final_dora_indicator_wait_tiles)/
             NULLIF(b.initial_wait_tiles_total-b.initial_dora_indicator_wait_tiles,0),4)
           AS dead_wall_non_indicator_pct
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY dead_wall_confinement_pct DESC,b.dead_wall_wait_tiles_total DESC,
         b.wait_change_episode_count DESC,p.name;
