-- 麻雀スタッツ研究所 第17指標群「赤に愛された指数」 SQL v0.1
-- 正本：赤ドラそのもの（0m/0p/0s）を選手が一局で取得した枚数。
-- 赤が通常ドラ／カンドラでも赤としては1枚、裏ドラは一切含まない。
-- 1人が1局で取得できる赤の物理実牌は0～3枚（萬・筒・索 各1枚）。
-- ※半荘1試合の通算は複数局のため3枚を超え得る。
-- 分母は参加した実際の局数（kyoku_player_result）。同じ東1局でも本場違いは別局。
-- 配牌、ツモ（嶺上含む）、チー・ポン・大明槓の取得牌、ロン和了牌を数える。
-- 持っていた牌を暗槓・加槓しても新規取得にはならない。牌を保持する間は重複しない。
-- 一度取得した赤ドラは、後で捨てても、その局の取得実績に残す。
-- 他家が後でその赤ドラを鳴く／ロンするなら、その選手の取得としても1回数える。
-- 主指標：赤に愛された指数＝赤ドラ取得総枚数 ÷ 参加局数（枚/局）。
-- 参考：赤に愛された局率＝赤を1枚以上取得した局数÷参加局数、
--       2枚取得局数、3枚取得局数、赤の配牌・ツモ・鳴き・ロン別枚数、赤各色。
-- 規定局数下限なし。既存01～16と派生11B／13Bは全く変更しない。
WITH
params AS (SELECT NULL AS start_year, NULL AS stage),
selected_games AS MATERIALIZED (
 SELECT g.id AS game_id
 FROM game g
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 CROSS JOIN params p
 WHERE (p.start_year IS NULL OR ls.start_year=p.start_year)
   AND (p.stage IS NULL OR ss.stage=p.stage)
),
participants AS MATERIALIZED (
 SELECT k.id AS kyoku_id, r.player_id
 FROM kyoku k JOIN selected_games g ON g.game_id=k.game_id
 JOIN kyoku_player_result r ON r.kyoku_id=k.id
),
red_acquisitions AS MATERIALIZED (
 SELECT e.kyoku_id,h.actor_player_id AS player_id,
        TRIM(j.value) AS tile,'haipai' AS origin,e.id AS event_id
 FROM haipai_event h
 JOIN event e ON e.id=h.event_id
 JOIN participants p ON p.kyoku_id=e.kyoku_id AND p.player_id=h.actor_player_id
 JOIN json_each('["'||REPLACE(h.hand,',','","')||'"]') j
 WHERE TRIM(j.value) IN ('0m','0p','0s')
 UNION ALL
 SELECT e.kyoku_id,d.actor_player_id,d.tile,'draw',e.id
 FROM draw_event d JOIN event e ON e.id=d.event_id
 JOIN participants p ON p.kyoku_id=e.kyoku_id AND p.player_id=d.actor_player_id
 WHERE d.tile IN ('0m','0p','0s')
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,c.tile,'chi',e.id
 FROM chi_event c JOIN event e ON e.id=c.event_id
 JOIN participants p ON p.kyoku_id=e.kyoku_id AND p.player_id=c.actor_player_id
 WHERE c.tile IN ('0m','0p','0s')
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,c.tile,'pon',e.id
 FROM pon_event c JOIN event e ON e.id=c.event_id
 JOIN participants p ON p.kyoku_id=e.kyoku_id AND p.player_id=c.actor_player_id
 WHERE c.tile IN ('0m','0p','0s')
 UNION ALL
 SELECT e.kyoku_id,c.actor_player_id,c.tile,'daiminkan',e.id
 FROM daiminkan_event c JOIN event e ON e.id=c.event_id
 JOIN participants p ON p.kyoku_id=e.kyoku_id AND p.player_id=c.actor_player_id
 WHERE c.tile IN ('0m','0p','0s')
 UNION ALL
 SELECT e.kyoku_id,a.actor_player_id,a.agari_tile,'ron',e.id
 FROM agari_event a JOIN event e ON e.id=a.event_id AND e.type='ron'
 JOIN participants p ON p.kyoku_id=e.kyoku_id AND p.player_id=a.actor_player_id
 WHERE a.agari_tile IN ('0m','0p','0s')
),
by_kyoku_player AS MATERIALIZED (
 SELECT p.kyoku_id,p.player_id,
        COUNT(a.tile) AS red_count,
        SUM(CASE WHEN a.tile='0m' THEN 1 ELSE 0 END) AS red_manzu_count,
        SUM(CASE WHEN a.tile='0p' THEN 1 ELSE 0 END) AS red_pinzu_count,
        SUM(CASE WHEN a.tile='0s' THEN 1 ELSE 0 END) AS red_souzu_count,
        SUM(CASE WHEN a.origin='haipai' THEN 1 ELSE 0 END) AS red_haipai_count,
        SUM(CASE WHEN a.origin='draw' THEN 1 ELSE 0 END) AS red_draw_count,
        SUM(CASE WHEN a.origin IN ('chi','pon','daiminkan') THEN 1 ELSE 0 END)
          AS red_call_count,
        SUM(CASE WHEN a.origin='ron' THEN 1 ELSE 0 END) AS red_ron_count
 FROM participants p
 LEFT JOIN red_acquisitions a ON a.kyoku_id=p.kyoku_id AND a.player_id=p.player_id
 GROUP BY p.kyoku_id,p.player_id
),
by_player AS (
 SELECT player_id,
        COUNT(*) AS played_kyoku_count,
        SUM(red_count) AS red_total_count,
        SUM(CASE WHEN red_count>=1 THEN 1 ELSE 0 END) AS red_seen_kyoku_count,
        SUM(CASE WHEN red_count=2 THEN 1 ELSE 0 END) AS red_two_kyoku_count,
        SUM(CASE WHEN red_count=3 THEN 1 ELSE 0 END) AS red_three_kyoku_count,
        MAX(red_count) AS max_red_per_kyoku,
        SUM(red_manzu_count) AS red_manzu_total,
        SUM(red_pinzu_count) AS red_pinzu_total,
        SUM(red_souzu_count) AS red_souzu_total,
        SUM(red_haipai_count) AS red_haipai_total,
        SUM(red_draw_count) AS red_draw_total,
        SUM(red_call_count) AS red_call_total,
        SUM(red_ron_count) AS red_ron_total
 FROM by_kyoku_player GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.played_kyoku_count,b.red_total_count,
       ROUND(1.0*b.red_total_count/NULLIF(b.played_kyoku_count,0),4)
         AS aka_loved_per_kyoku,
       b.red_seen_kyoku_count,
       ROUND(100.0*b.red_seen_kyoku_count/NULLIF(b.played_kyoku_count,0),4)
         AS aka_seen_kyoku_pct,
       b.red_two_kyoku_count,b.red_three_kyoku_count,
       b.max_red_per_kyoku,
       b.red_manzu_total,b.red_pinzu_total,b.red_souzu_total,
       b.red_haipai_total,b.red_draw_total,b.red_call_total,b.red_ron_total
FROM by_player b JOIN player p ON p.id=b.player_id
ORDER BY aka_loved_per_kyoku DESC,
         b.red_total_count DESC,b.played_kyoku_count DESC,p.name;
