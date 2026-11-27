-- Separate exploratory analysis: dora acquired specifically from draw_event.
-- Fixed input release: konoui/m-league-game-db 20261120-2341-04338cbb.
-- Keep the canonical dora-loved v0.1 physical-tile rules:
-- red fives count once as red; omote/kan dora only; ura excluded;
-- a non-red draw can qualify if it becomes dora while still held;
-- FIFO acquisition/discard matching includes every acquisition source.
WITH
selected_games AS MATERIALIZED (
 SELECT g.id AS game_id, ls.start_year
 FROM game g
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
),
selected_kyoku AS MATERIALIZED (
 SELECT k.id AS kyoku_id,k.game_id,sg.start_year
 FROM kyoku k JOIN selected_games sg ON sg.game_id=k.game_id
),
participants AS MATERIALIZED (
 SELECT k.kyoku_id,k.start_year,gpr.player_id
 FROM selected_kyoku k
 JOIN game_player_result gpr ON gpr.game_id=k.game_id
),
raw_acquisitions AS MATERIALIZED (
 SELECT e.kyoku_id,h.actor_player_id AS player_id,e.event_order AS event_order,
        CAST(j.key AS INTEGER) AS seq,TRIM(j.value) AS tile,'haipai' AS origin
 FROM haipai_event h
 JOIN event e ON e.id=h.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 JOIN json_each('["'||REPLACE(h.hand,',','","')||'"]') j
 UNION ALL
 SELECT e.kyoku_id,d.actor_player_id,e.event_order,0,d.tile,'draw'
 FROM draw_event d JOIN event e ON e.id=d.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,e.event_order,0,c.tile,'chi'
 FROM chi_event c JOIN event e ON e.id=c.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,e.event_order,0,c.tile,'pon'
 FROM pon_event c JOIN event e ON e.id=c.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,e.event_order,0,c.tile,'daiminkan'
 FROM daiminkan_event c JOIN event e ON e.id=c.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,a.actor_player_id,e.event_order,0,a.agari_tile,'ron'
 FROM agari_event a JOIN event e ON e.id=a.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 WHERE e.type='ron'
),
acquisitions AS MATERIALIZED (
 SELECT kyoku_id,player_id,event_order,seq,tile,origin,
        CASE WHEN substr(tile,1,1)='0' THEN '5'||substr(tile,2) ELSE tile END AS normal_tile,
        ROW_NUMBER() OVER (
          PARTITION BY kyoku_id,player_id,tile ORDER BY event_order,seq
        ) AS tile_sequence
 FROM raw_acquisitions
),
discards AS MATERIALIZED (
 SELECT e.kyoku_id,d.actor_player_id AS player_id,d.tile,e.event_order,
        ROW_NUMBER() OVER (
          PARTITION BY e.kyoku_id,d.actor_player_id,d.tile ORDER BY e.event_order
        ) AS tile_sequence
 FROM discard_event d JOIN event e ON e.id=d.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
),
omote_dora AS MATERIALIZED (
 SELECT e.kyoku_id,e.event_order,
        CASE WHEN substr(d.dora_tile,1,1)='0'
             THEN '5'||substr(d.dora_tile,2) ELSE d.dora_tile END AS dora_tile
 FROM dora_indicator_event d JOIN event e ON e.id=d.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 WHERE d.dora_type='omote'
),
classified_acquisitions AS MATERIALIZED (
 SELECT a.*,x.event_order AS discard_order,
        CASE WHEN substr(a.tile,1,1)='0'
          OR EXISTS (
           SELECT 1 FROM omote_dora od
           WHERE od.kyoku_id=a.kyoku_id
             AND od.dora_tile=a.normal_tile
             AND (x.event_order IS NULL OR od.event_order<x.event_order)
          ) THEN 1 ELSE 0 END AS became_dora
 FROM acquisitions a
 LEFT JOIN discards x ON x.kyoku_id=a.kyoku_id AND x.player_id=a.player_id
                     AND x.tile=a.tile AND x.tile_sequence=a.tile_sequence
),
by_kyoku_player AS MATERIALIZED (
 SELECT k.kyoku_id,k.start_year,k.player_id,
        COUNT(CASE WHEN a.origin='draw' THEN 1 END) AS draw_event_count,
        COALESCE(SUM(CASE WHEN a.origin='draw' AND a.became_dora=1 THEN 1 ELSE 0 END),0)
          AS dora_draw_count,
        COALESCE(SUM(CASE WHEN a.origin='draw' AND a.became_dora=1
                           AND substr(a.tile,1,1)='0' THEN 1 ELSE 0 END),0)
          AS red_dora_draw_count,
        COALESCE(SUM(CASE WHEN a.origin='draw' AND a.became_dora=1
                           AND substr(a.tile,1,1)<>'0' THEN 1 ELSE 0 END),0)
          AS normal_dora_draw_count
 FROM participants k
 LEFT JOIN classified_acquisitions a
   ON a.kyoku_id=k.kyoku_id AND a.player_id=k.player_id
 GROUP BY k.kyoku_id,k.start_year,k.player_id
),
player_period AS (
 SELECT CAST(start_year AS TEXT) AS period,player_id,
        COUNT(*) AS played_kyoku_count,
        SUM(draw_event_count) AS draw_event_count,
        SUM(dora_draw_count) AS dora_draw_count,
        SUM(red_dora_draw_count) AS red_dora_draw_count,
        SUM(normal_dora_draw_count) AS normal_dora_draw_count,
        SUM(CASE WHEN dora_draw_count>0 THEN 1 ELSE 0 END) AS kyoku_with_dora_draw_count,
        MAX(dora_draw_count) AS max_dora_draws_in_kyoku
 FROM by_kyoku_player
 GROUP BY start_year,player_id
 UNION ALL
 SELECT 'ALL' AS period,player_id,
        COUNT(*) AS played_kyoku_count,
        SUM(draw_event_count) AS draw_event_count,
        SUM(dora_draw_count) AS dora_draw_count,
        SUM(red_dora_draw_count) AS red_dora_draw_count,
        SUM(normal_dora_draw_count) AS normal_dora_draw_count,
        SUM(CASE WHEN dora_draw_count>0 THEN 1 ELSE 0 END) AS kyoku_with_dora_draw_count,
        MAX(dora_draw_count) AS max_dora_draws_in_kyoku
 FROM by_kyoku_player
 GROUP BY player_id
)
SELECT pp.period,p.id AS player_id,p.name AS player_name,
       pp.played_kyoku_count,pp.draw_event_count,pp.dora_draw_count,
       pp.red_dora_draw_count,pp.normal_dora_draw_count,
       ROUND(100.0*pp.dora_draw_count/NULLIF(pp.draw_event_count,0),4) AS dora_per_100_draws,
       ROUND(100.0*pp.red_dora_draw_count/NULLIF(pp.draw_event_count,0),4) AS red_dora_per_100_draws,
       ROUND(100.0*pp.normal_dora_draw_count/NULLIF(pp.draw_event_count,0),4) AS normal_dora_per_100_draws,
       ROUND(100.0*pp.dora_draw_count/NULLIF(pp.played_kyoku_count,0),4) AS dora_per_100_kyoku,
       pp.kyoku_with_dora_draw_count,
       ROUND(100.0*pp.kyoku_with_dora_draw_count/NULLIF(pp.played_kyoku_count,0),4)
         AS kyoku_with_dora_draw_pct,
       pp.max_dora_draws_in_kyoku
FROM player_period pp JOIN player p ON p.id=pp.player_id
ORDER BY pp.period,p.name;
