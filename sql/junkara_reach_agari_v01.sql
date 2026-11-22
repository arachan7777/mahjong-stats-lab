-- 麻雀スタッツ研究所 第13B派生指標「ジュンカラリーチ和了率」SQL v0.1
-- 定義：ジュンカラリーチが成立した回数のうち、その本人がロン和了できた割合。
-- ジュンカラの正本：第13指標 v0.2。宣言直後の待ち牌が通常山・王牌ともに物理的0枚。
-- 判定：本人の player_tenpai_state.available_tile_count=0
--       かつ dora_indicator_tile_count=0。公開ドラ表示牌も王牌の一部として扱う。
-- 分母：上記条件を満たす「成立リーチ」回数。成立前の宣言牌放銃は除外。
-- 分子：その成立リーチの後、同じ局でその本人がロン和了した回数。
-- 他家の手牌から当たり牌が捨てられればロン和了が可能。
-- ツモ和了は原理上存在しないため分子に含まない（検証で別途0件確認）。
-- 同じ局で2人以上のジュンカラリーチがあれば、それぞれ1回ずつ数える。
-- ゼロ分母の選手はランキングに含まず、規定回数下限は設定しない。
-- 既存01～13・派生11BのSQL・定義は変更しない。
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
accepted_reaches AS MATERIALIZED (
 SELECT re.kyoku_id,re.id AS reach_event_id,
        re.event_order AS reach_event_order,
        r.actor_player_id AS player_id
 FROM reach_event r
 JOIN event re ON re.id=r.event_id
 JOIN kyoku k ON k.id=re.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
 WHERE r.is_accepted=1
),
declaration_states AS MATERIALIZED (
 SELECT a.player_id,a.kyoku_id,a.reach_event_id,
        d.id AS declaration_event_id,
        d.event_order AS declaration_order,
        pts.waiting_tiles,
        pts.available_tile_count,
        pts.dora_indicator_tile_count
 FROM accepted_reaches a
 JOIN discard_event de ON de.actor_player_id=a.player_id
                       AND de.is_reach_declaration=1
 JOIN event d ON d.id=de.event_id
             AND d.kyoku_id=a.kyoku_id
             AND d.event_order>a.reach_event_order
 JOIN player_tenpai_state pts ON pts.event_id=d.id
                            AND pts.player_id=a.player_id
                            AND pts.is_actor=1
),
junkara_reaches AS MATERIALIZED (
 SELECT *
 FROM declaration_states
 WHERE available_tile_count=0
   AND dora_indicator_tile_count=0
),
junkara_with_results AS MATERIALIZED (
 SELECT j.*,
        CASE WHEN EXISTS (
         SELECT 1 FROM agari_event a
         JOIN event e ON e.id=a.event_id
         WHERE e.kyoku_id=j.kyoku_id
           AND e.event_order>j.declaration_order
           AND e.type='ron'
           AND a.actor_player_id=j.player_id
        ) THEN 1 ELSE 0 END AS won_by_ron,
        CASE WHEN EXISTS (
         SELECT 1 FROM agari_event a
         JOIN event e ON e.id=a.event_id
         WHERE e.kyoku_id=j.kyoku_id
           AND e.event_order>j.declaration_order
           AND e.type='tsumo'
           AND a.actor_player_id=j.player_id
        ) THEN 1 ELSE 0 END AS won_by_tsumo
 FROM junkara_reaches j
),
by_player AS (
 SELECT player_id,COUNT(*) AS junkara_reach_count,
        SUM(won_by_ron) AS junkara_reach_ron_count,
        SUM(won_by_tsumo) AS junkara_reach_tsumo_count
 FROM junkara_with_results
 GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.junkara_reach_count,
       b.junkara_reach_ron_count,
       ROUND(100.0*b.junkara_reach_ron_count/
              NULLIF(b.junkara_reach_count,0),4)
           AS junkara_reach_agari_pct,
       b.junkara_reach_tsumo_count
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY junkara_reach_agari_pct DESC,
         b.junkara_reach_ron_count DESC,
         b.junkara_reach_count DESC,p.name;
