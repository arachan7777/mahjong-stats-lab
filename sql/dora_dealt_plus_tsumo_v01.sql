-- 配牌 + 通常ツモ/嶺上ツモのドラ取得を集計。鳴き牌・ロン牌は計上しない。
-- 同一物理牌は赤ドラ優先で1枚扱い。通常ドラは表ドラ・カンドラ、裏ドラ除外。
-- 配牌牌は保持中に表ドラ/カンドラ指定された場合も計上。捨てた後の指定は対象外。
-- 基準は league_season.start_year。配牌、ツモの内訳と合算を選手・シーズン別に出力。
WITH
selected_kyoku AS MATERIALIZED (
 SELECT k.id AS kyoku_id,k.game_id,ls.start_year
 FROM kyoku k
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
),
participants AS MATERIALIZED (
 SELECT sk.kyoku_id,sk.start_year,gpr.player_id
 FROM selected_kyoku sk
 JOIN game_player_result gpr ON gpr.game_id=sk.game_id
),
raw_acquisitions AS MATERIALIZED (
 SELECT e.kyoku_id,h.actor_player_id AS player_id,e.event_order,
        CAST(j.key AS INTEGER) AS seq,TRIM(j.value) AS tile,'haipai' AS origin
 FROM haipai_event h JOIN event e ON e.id=h.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 JOIN json_each('["'||REPLACE(h.hand,',','","')||'"]') j
 UNION ALL
 SELECT e.kyoku_id,d.actor_player_id,e.event_order,0,d.tile,'draw'
 FROM draw_event d JOIN event e ON e.id=d.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,e.event_order,0,c.tile,'chi'
 FROM chi_event c JOIN event e ON e.id=c.event_id JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,e.event_order,0,c.tile,'pon'
 FROM pon_event c JOIN event e ON e.id=c.event_id JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,e.event_order,0,c.tile,'daiminkan'
 FROM daiminkan_event c JOIN event e ON e.id=c.event_id JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 UNION ALL
 SELECT e.kyoku_id,a.actor_player_id,e.event_order,0,a.agari_tile,'ron'
 FROM agari_event a JOIN event e ON e.id=a.event_id JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 WHERE e.type='ron'
),
acquisitions AS MATERIALIZED (
 SELECT *,CASE WHEN substr(tile,1,1)='0' THEN '5'||substr(tile,2) ELSE tile END AS normal_tile,
        ROW_NUMBER() OVER (PARTITION BY kyoku_id,player_id,tile ORDER BY event_order,seq) AS tile_sequence
 FROM raw_acquisitions
),
discards AS MATERIALIZED (
 SELECT e.kyoku_id,d.actor_player_id AS player_id,d.tile,e.event_order,
        ROW_NUMBER() OVER (PARTITION BY e.kyoku_id,d.actor_player_id,d.tile ORDER BY e.event_order) AS tile_sequence
 FROM discard_event d JOIN event e ON e.id=d.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
),
omote_dora AS MATERIALIZED (
 SELECT e.kyoku_id,e.event_order,
        CASE WHEN substr(d.dora_tile,1,1)='0' THEN '5'||substr(d.dora_tile,2) ELSE d.dora_tile END AS dora_tile
 FROM dora_indicator_event d JOIN event e ON e.id=d.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 WHERE d.dora_type='omote'
),
classified AS MATERIALIZED (
 SELECT a.*,x.event_order AS discard_order,
        CASE WHEN substr(a.tile,1,1)='0' OR EXISTS (
          SELECT 1 FROM omote_dora od
          WHERE od.kyoku_id=a.kyoku_id AND od.dora_tile=a.normal_tile
            AND (x.event_order IS NULL OR od.event_order<x.event_order)
        ) THEN 1 ELSE 0 END AS is_dora
 FROM acquisitions a
 LEFT JOIN discards x ON x.kyoku_id=a.kyoku_id AND x.player_id=a.player_id
   AND x.tile=a.tile AND x.tile_sequence=a.tile_sequence
),
by_kyoku AS (
 SELECT p.kyoku_id,p.start_year,p.player_id,
        SUM(CASE WHEN c.origin='haipai' AND c.is_dora=1 AND substr(c.tile,1,1)='0' THEN 1 ELSE 0 END) AS deal_red,
        SUM(CASE WHEN c.origin='haipai' AND c.is_dora=1 AND substr(c.tile,1,1)<>'0' THEN 1 ELSE 0 END) AS deal_normal,
        SUM(CASE WHEN c.origin='draw' AND c.is_dora=1 AND substr(c.tile,1,1)='0' THEN 1 ELSE 0 END) AS draw_red,
        SUM(CASE WHEN c.origin='draw' AND c.is_dora=1 AND substr(c.tile,1,1)<>'0' THEN 1 ELSE 0 END) AS draw_normal,
        SUM(CASE WHEN c.origin='draw' THEN 1 ELSE 0 END) AS draw_count
 FROM participants p LEFT JOIN classified c
   ON c.kyoku_id=p.kyoku_id AND c.player_id=p.player_id
 GROUP BY p.kyoku_id,p.start_year,p.player_id
),
period_rows AS (
 SELECT start_year,player_id,COUNT(*) AS played_kyoku_count,
        SUM(draw_count) AS draw_event_count,
        SUM(deal_red) AS deal_red,SUM(deal_normal) AS deal_normal,
        SUM(draw_red) AS draw_red,SUM(draw_normal) AS draw_normal
 FROM by_kyoku GROUP BY start_year,player_id
 UNION ALL
 SELECT NULL AS start_year,player_id,COUNT(*) AS played_kyoku_count,
        SUM(draw_count) AS draw_event_count,
        SUM(deal_red),SUM(deal_normal),SUM(draw_red),SUM(draw_normal)
 FROM by_kyoku GROUP BY player_id
)
SELECT CASE WHEN r.start_year IS NULL THEN 'ALL' ELSE CAST(r.start_year AS TEXT) END AS period,
       p.id AS player_id,p.name AS player_name,r.played_kyoku_count,r.draw_event_count,
       r.deal_red,r.deal_normal,r.draw_red,r.draw_normal,
       r.deal_red+r.draw_red AS combined_red,
       r.deal_normal+r.draw_normal AS combined_normal,
       r.deal_red+r.deal_normal+r.draw_red+r.draw_normal AS combined_total,
       ROUND(100.0*(r.deal_red+r.draw_red)/NULLIF(r.played_kyoku_count,0),4) AS red_per_100_kyoku,
       ROUND(100.0*(r.deal_normal+r.draw_normal)/NULLIF(r.played_kyoku_count,0),4) AS normal_per_100_kyoku,
       ROUND(100.0*(r.deal_red+r.deal_normal+r.draw_red+r.draw_normal)/NULLIF(r.played_kyoku_count,0),4) AS total_per_100_kyoku,
       ROUND(100.0*r.deal_red/NULLIF(r.played_kyoku_count,0),4) AS dealt_red_per_100_kyoku,
       ROUND(100.0*r.deal_normal/NULLIF(r.played_kyoku_count,0),4) AS dealt_normal_per_100_kyoku,
       ROUND(100.0*r.draw_red/NULLIF(r.played_kyoku_count,0),4) AS tsumo_red_per_100_kyoku,
       ROUND(100.0*r.draw_normal/NULLIF(r.played_kyoku_count,0),4) AS tsumo_normal_per_100_kyoku
FROM period_rows r JOIN player p ON p.id=r.player_id
ORDER BY period,player_name;
