-- 麻雀スタッツ研究所 第13独立指標「ジュンカラリーチ率」SQL v0.2
-- ユーザー確定定義: 成立リーチ時点で山にも王牌にも当たり牌が1枚も存在しない。
-- 分母: reach_event.is_accepted=1 の成立リーチ全件。
-- 分子: リーチ宣言打牌直後の待ち牌の物理的残数が0枚の成立リーチ。
-- 神目線残り枚数 available_tile_count + 公開ドラ表示牌にある待ち牌数
-- dora_indicator_tile_count = 0 が必要。公開ドラ表示牌も王牌の一部。
-- ツモ可能山・未公開王牌・公開ドラ表示牌すべてに当たり牌が存在しないケース。
-- v0.1のavailable_tile_count=0だけの条件は、公開ドラ表示牌の残存を見逃すため訂正。
-- 分子・分母は回数。比率はその合計で計算。局末が和了でも流局でも分母対象。
-- 既存01〜12と派生11Bの定義・SQLは一切変更しない。
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
by_player AS (
 SELECT player_id,COUNT(*) AS accepted_reach_count,
        SUM(CASE WHEN available_tile_count=0 AND dora_indicator_tile_count=0
                 THEN 1 ELSE 0 END) AS pure_empty_reach_count,
        SUM(CASE WHEN available_tile_count=0 THEN 1 ELSE 0 END)
           AS zero_excluding_visible_dora_count,
        SUM(CASE WHEN available_tile_count=0 AND dora_indicator_tile_count>0
                 THEN 1 ELSE 0 END) AS visible_dora_only_count
 FROM declaration_states
 GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.accepted_reach_count,b.pure_empty_reach_count,
       ROUND(100.0*b.pure_empty_reach_count/
             NULLIF(b.accepted_reach_count,0),4)
             AS pure_empty_reach_pct,
       b.zero_excluding_visible_dora_count,
       b.visible_dora_only_count
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY pure_empty_reach_pct DESC,
         b.pure_empty_reach_count DESC,
         b.accepted_reach_count DESC,p.name;
