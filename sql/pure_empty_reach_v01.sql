-- 麻雀スタッツ研究所 第13独立指標「ジュンカラリーチ率」SQL v0.1
-- 定義: 成立したリーチのうち、宣言打牌直後に山の当たり牌が残り0枚の割合。
-- 判定の正本: 宣言打牌と同じ event_id の本人の player_tenpai_state.available_tile_count=0。
-- この数値は4人の初期手牌と取得済み牌を含めて計算された神目線の残枚数で、
-- 表ドラ表示牌（すでに公開されている牌）を「残りの当たり牌」から除く。
-- 「山」はこのDBの残り未取得牌（ツモ可能山と未公開王牌）として扱う。
-- ツモ可能な生きた山だけに0枚（王牌にはまだ残る）という意味とは区別する。
-- 分母: reach_event.is_accepted=1 のリーチ成立回数。
-- 分子: リーチ宣言打牌直後の本人の残り待ち牌枚数が0の成立リーチ回数。
-- リーチ後に他家が和了しても、流局しても、本人が和了しても分母に計上。
-- 同一局の複数リーチは選手ごとに別々の1回として数える。
-- 参考: ドラ表示牌まで含め未取得の牌が0枚だった厳密な物理的0枚も参考列にする。
-- year/stage NULL は全期間。比率は各選手の分子合計÷分母合計×100。
-- 第11「王牌幽閉率」、派生11B、第12「リーチ時流局率」は変更しない。
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
        SUM(CASE WHEN available_tile_count=0 THEN 1 ELSE 0 END)
           AS pure_empty_reach_count,
        SUM(CASE WHEN available_tile_count=0 AND dora_indicator_tile_count=0
                 THEN 1 ELSE 0 END) AS zero_even_including_visible_dora_count,
        SUM(CASE WHEN available_tile_count=0 AND dora_indicator_tile_count>0
                 THEN 1 ELSE 0 END) AS zero_except_visible_dora_count
 FROM declaration_states
 GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.accepted_reach_count,b.pure_empty_reach_count,
       ROUND(100.0*b.pure_empty_reach_count/
             NULLIF(b.accepted_reach_count,0),4)
             AS pure_empty_reach_pct,
       b.zero_even_including_visible_dora_count,
       b.zero_except_visible_dora_count
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY pure_empty_reach_pct DESC,
         b.pure_empty_reach_count DESC,
         b.accepted_reach_count DESC,p.name;
