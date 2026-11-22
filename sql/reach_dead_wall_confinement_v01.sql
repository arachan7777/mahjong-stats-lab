-- 麻雀スタッツ研究所 リーチ王牌幽閉率 SQL v0.1（王牌幽閉率 v0.2 派生指標）
-- 対象: リーチが成立した局のうち、ツモ・ロン和了ではなく流局した局。
-- 起点: リーチ宣言打牌（is_reach_declaration=1）直後の本人の待ち牌。
--        同一局の accepted reach_event により成立を確認。
-- 分母: リーチ宣言打牌直後に物理的に残っていた同じ待ち牌の枚数。
-- 分子: その待ち牌が流局時の王牌14枚に残っていた枚数。
-- 割合: 分子合計 / 分母合計 ×100。5枚→4枚なら80%。
-- 同一局のリーチは1回のみ。成立前のダマテン時点は加算しない。
-- リーチ後の同一待ち継続記録は重複計上しない。
-- 有効な残り待ち牌0枚のリーチは、割合の分母・分子には計上しない。
-- 王牌の物理的な14枚を対象（ドラ表示牌は含む）。
-- 参考として公開ドラ表示牌を除く割合も別列で算出。
-- v0.2通常王牌幽閉率・その他の既存10指標は一切変更しない。
-- params.start_year=NULL / stage=NULL で全シーズン・全ステージ。
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
accepted_reach_discards AS MATERIALIZED (
 SELECT de.kyoku_id,de.id AS wait_event_id,
        de.event_order AS reach_discard_order,
        d.actor_player_id AS player_id,pts.waiting_tiles
 FROM discard_event d
 JOIN event de ON de.id=d.event_id
 JOIN exhaustive_draws ed ON ed.kyoku_id=de.kyoku_id
 JOIN player_tenpai_state pts
   ON pts.event_id=de.id
   AND pts.player_id=d.actor_player_id AND pts.is_actor=1
 WHERE d.is_reach_declaration=1
   AND EXISTS (
     SELECT 1 FROM reach_event r JOIN event re ON re.id=r.event_id
     WHERE re.kyoku_id=de.kyoku_id AND r.actor_player_id=d.actor_player_id
       AND r.is_accepted=1 AND re.event_order<de.event_order
   )
),
original_wait_tiles AS MATERIALIZED (
 SELECT f.kyoku_id,f.player_id,f.wait_event_id,
        f.reach_discard_order AS tenpai_order,
        CASE WHEN substr(TRIM(j.value),1,1)='0'
             THEN '5'||substr(TRIM(j.value),2)
             ELSE TRIM(j.value) END AS tile
 FROM accepted_reach_discards f
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
by_reach AS (
  SELECT player_id,kyoku_id,wait_event_id,
         SUM(initial_remaining) AS remaining_when_reached,
         SUM(final_king_wall) AS dead_wall_reach_wait_tiles,
         SUM(first_visible_dora) AS initial_dora_indicators,
         SUM(final_visible_dora) AS final_dora_indicators
  FROM per_wait_tile
  GROUP BY player_id,kyoku_id,wait_event_id
),
eligible_reaches AS (
 SELECT * FROM by_reach WHERE remaining_when_reached>0
),
by_player AS (
 SELECT player_id,
        COUNT(*) AS accepted_reach_ryukyoku_count,
        SUM(remaining_when_reached) AS remaining_when_reached_total,
        SUM(dead_wall_reach_wait_tiles) AS dead_wall_reach_wait_tiles_total,
        SUM(initial_dora_indicators) AS initial_dora_indicator_wait_tiles,
        SUM(final_dora_indicators) AS final_dora_indicator_wait_tiles
 FROM eligible_reaches
 GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.accepted_reach_ryukyoku_count,
       b.remaining_when_reached_total,
       b.dead_wall_reach_wait_tiles_total,
       ROUND(100.0*b.dead_wall_reach_wait_tiles_total/
         NULLIF(b.remaining_when_reached_total,0),4)
         AS reach_dead_wall_confinement_pct,
       b.initial_dora_indicator_wait_tiles,
       b.final_dora_indicator_wait_tiles,
       ROUND(100.0*(b.dead_wall_reach_wait_tiles_total-b.final_dora_indicator_wait_tiles)/
         NULLIF(b.remaining_when_reached_total-b.initial_dora_indicator_wait_tiles,0),4)
         AS reach_dead_wall_non_indicator_pct
FROM by_player b JOIN player p ON p.id=b.player_id
ORDER BY reach_dead_wall_confinement_pct DESC,
         b.dead_wall_reach_wait_tiles_total DESC,
         b.accepted_reach_ryukyoku_count DESC,p.name;
