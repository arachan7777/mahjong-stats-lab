-- 麻雀スタッツ研究所 第15独立指標「ドラに愛された指数」試作 SQL v0.1
-- 分母：選手が参加した物理的な局（kyoku.id）数。東1局0本場・東1局1本場は別の1局。
-- 分子：局中に一度でも自分の手牌/副露に入った「ドラとして有効な実物牌」の枚数。
-- 対象：通常ドラ、赤ドラ、カンドラ（dora_type='omote'）。裏ドラは除外する。
-- 配牌・ツモ（嶺上含む）・他家からの鳴き牌・ロン和了牌を取得として記録する。
-- 当時ドラでなくても、保持中にカンドラでドラ指定された実物牌なら1枚計上。
-- 既に捨てた後にカンドラ化された牌は計上しない。捨てた後も取得済みの実績は残す。
-- 同じ実物牌を何巡も保持していても1枚。赤5が通常ドラ5でも物理的な1枚=1枚。
-- 同牌種が何度も入ってくれば、各取得を別の実物牌として計上する。
-- 一度持った牌を鳴きで相手から受け取った場合もその選手の取得1枚とする。
-- リーチ/和了/聴牌の有無を問わず全局を対象。
-- 結果: 総取得ドラ枚数÷参加局数(1局あたり)、100局あたりの枚数も表示する。
-- 副指標: 1枚以上取得した局の割合、取得牌数の内訳。
-- 一般のドラ枚数/翻数とは異なる。赤5が通常ドラ5なら翻数2でも本指標は物理的1枚。
-- 万一、同じ牌記号が複数回あってもFIFOで取得と打牌を対応させる。
-- 原典01～14と派生11B,13Bを改変しない。

WITH
params AS (SELECT NULL AS start_year, NULL AS stage),
selected_games AS MATERIALIZED (
 SELECT g.id game_id
 FROM game g
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 CROSS JOIN params cfg
 WHERE (cfg.start_year IS NULL OR ls.start_year=cfg.start_year)
 AND (cfg.stage IS NULL OR ss.stage=cfg.stage)
),
selected_kyoku AS MATERIALIZED (
 SELECT k.id AS kyoku_id,k.game_id,k.honba_count,k.round
 FROM kyoku k JOIN selected_games sg ON sg.game_id=k.game_id
),
participants AS MATERIALIZED (
 SELECT k.kyoku_id, gpr.player_id
 FROM selected_kyoku k
 JOIN game_player_result gpr ON gpr.game_id=k.game_id
),
raw_acquisitions AS MATERIALIZED (
 SELECT e.kyoku_id,h.actor_player_id AS player_id,
        e.event_order AS event_order,CAST(j.key AS INTEGER) AS seq,
        TRIM(j.value) AS tile, 'haipai' AS origin
 FROM haipai_event h
 JOIN event e ON e.id=h.event_id
 JOIN selected_kyoku sk ON sk.kyoku_id=e.kyoku_id
 JOIN json_each('["'||REPLACE(h.hand,',','","')||'"]') j
 UNION ALL
 SELECT e.kyoku_id,d.actor_player_id,e.event_order,0,d.tile,'draw'
 FROM draw_event d
 JOIN event e ON e.id=d.event_id
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
 SELECT a.*,
        x.event_order AS discard_order,
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
 SELECT k.kyoku_id,k.player_id,
        COUNT(a.tile) AS physical_tiles_acquired,
        COALESCE(SUM(a.became_dora),0) AS dora_tiles_acquired,
        COALESCE(SUM(CASE WHEN substr(a.tile,1,1)='0' AND a.became_dora=1 THEN 1 ELSE 0 END),0)
           AS red_dora_acquired,
        COALESCE(SUM(CASE WHEN a.origin='ron' AND a.became_dora=1 THEN 1 ELSE 0 END),0)
           AS ron_dora_acquired
 FROM participants k
 LEFT JOIN classified_acquisitions a ON a.kyoku_id=k.kyoku_id AND a.player_id=k.player_id
 GROUP BY k.kyoku_id,k.player_id
),
by_player AS (
 SELECT player_id,COUNT(*) AS played_kyoku_count,
        SUM(dora_tiles_acquired) AS dora_total_tiles,
        SUM(CASE WHEN dora_tiles_acquired>0 THEN 1 ELSE 0 END) AS kyoku_with_dora_count,
        SUM(red_dora_acquired) AS red_dora_total_tiles,
        SUM(ron_dora_acquired) AS ron_dora_total_tiles,
        MAX(dora_tiles_acquired) AS max_dora_tiles_in_kyoku
 FROM by_kyoku_player GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.played_kyoku_count,b.dora_total_tiles,
       ROUND(1.0*b.dora_total_tiles/NULLIF(b.played_kyoku_count,0),4) AS dora_loved_per_kyoku,
       ROUND(100.0*b.dora_total_tiles/NULLIF(b.played_kyoku_count,0),4) AS dora_loved_per_100kyoku,
       b.kyoku_with_dora_count,
       ROUND(100.0*b.kyoku_with_dora_count/NULLIF(b.played_kyoku_count,0),4) AS kyoku_with_dora_pct,
       b.red_dora_total_tiles,b.ron_dora_total_tiles,b.max_dora_tiles_in_kyoku
FROM by_player b JOIN player p ON p.id=b.player_id
ORDER BY dora_loved_per_kyoku DESC,
         b.dora_total_tiles DESC,
         b.played_kyoku_count DESC,p.name;
