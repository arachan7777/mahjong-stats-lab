-- 麻雀スタッツ研究所 第18指標群「ドラマチックリーチ率・ドラマチック成就率」SQL v0.1
-- 確認基準：リーチ宣言打牌直後に待ち牌が1種類のみ、その牌が公開済みの表ドラ
--             またはカンドラに該当する成立リーチだけを対象とする。
-- 二種類以上の待ちの一部だけがドラになる「高めドラ」は除外する。
-- 複合形の待ちも除外。赤ドラ単独・裏ドラ・リーチ後に追加されたカンドラは対象外。
-- 分母(リーチ率)：成立リーチの総回数（reach_event.is_accepted=1）。
-- 分子(リーチ率)：ドラマチックリーチ成立回数。
-- 分母(成就率)：ドラマチックリーチ成立回数。
-- 分子(成就率)：同じ局で宣言後に本人がツモまたはロンで和了した回数。
-- 一局に複数の成立リーチがあれば各リーチ個別に判定。規定回数なし。
-- 待ち牌が現物として山に残るか否かはこの指標の認定条件にしない。
-- 既存独立指標01〜17、派生11B・13Bの定義・SQLは変更しない。
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
 SELECT e.kyoku_id,
        r.actor_player_id AS player_id,
        r.event_id AS reach_event_id,
        e.event_order AS reach_order
 FROM reach_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
 WHERE r.is_accepted=1
),
declaration_states AS MATERIALIZED (
 SELECT a.kyoku_id,a.player_id,a.reach_event_id,a.reach_order,
        e.id AS declaration_event_id,
        e.event_order AS declaration_order,
        pts.waiting_tiles,
        pts.tile_type_count,
        pts.waiting_type,
        pts.available_tile_count,
        pts.dora_indicator_tile_count,
        CASE WHEN pts.tile_type_count=1
                   AND pts.waiting_type<>'複合形'
                   AND INSTR(pts.waiting_tiles,',')=0
                   AND EXISTS (
                      SELECT 1
                      FROM dora_indicator_event di
                      JOIN event de ON de.id=di.event_id
                      WHERE de.kyoku_id=e.kyoku_id
                        AND de.event_order<=e.event_order
                        AND di.dora_type='omote'
                        AND (CASE WHEN substr(di.dora_tile,1,1)='0'
                                  THEN '5'||substr(di.dora_tile,2)
                                  ELSE di.dora_tile END)
                            =(CASE WHEN substr(trim(pts.waiting_tiles),1,1)='0'
                                   THEN '5'||substr(trim(pts.waiting_tiles),2)
                                   ELSE trim(pts.waiting_tiles) END)
                    )
              THEN 1 ELSE 0 END AS is_dramatic_reach
 FROM accepted_reaches a
 JOIN discard_event de ON de.actor_player_id=a.player_id
                      AND de.is_reach_declaration=1
 JOIN event e ON e.id=de.event_id
             AND e.kyoku_id=a.kyoku_id
             AND e.event_order>a.reach_order
 JOIN player_tenpai_state pts ON pts.event_id=e.id
                             AND pts.player_id=a.player_id
                             AND pts.is_actor=1
),
reach_outcomes AS MATERIALIZED (
 SELECT d.*,
        CASE WHEN EXISTS (
          SELECT 1 FROM agari_event ag
          JOIN event w ON w.id=ag.event_id
          WHERE w.kyoku_id=d.kyoku_id
            AND w.event_order>d.declaration_order
            AND ag.actor_player_id=d.player_id
            AND w.type IN ('ron','tsumo')
        ) THEN 1 ELSE 0 END AS own_agari,
        CASE WHEN EXISTS (
          SELECT 1 FROM agari_event ag
          JOIN event w ON w.id=ag.event_id
          WHERE w.kyoku_id=d.kyoku_id
            AND w.event_order>d.declaration_order
            AND ag.actor_player_id=d.player_id
            AND w.type='ron'
        ) THEN 1 ELSE 0 END AS own_ron,
        CASE WHEN EXISTS (
          SELECT 1 FROM agari_event ag
          JOIN event w ON w.id=ag.event_id
          WHERE w.kyoku_id=d.kyoku_id
            AND w.event_order>d.declaration_order
            AND ag.actor_player_id=d.player_id
            AND w.type='tsumo'
        ) THEN 1 ELSE 0 END AS own_tsumo
 FROM declaration_states d
),
by_player AS (
 SELECT player_id,
        COUNT(*) AS accepted_reach_count,
        SUM(is_dramatic_reach) AS dramatic_reach_count,
        SUM(CASE WHEN is_dramatic_reach=1 THEN own_agari ELSE 0 END)
          AS dramatic_agari_count,
        SUM(CASE WHEN is_dramatic_reach=1 THEN own_ron ELSE 0 END)
          AS dramatic_ron_count,
        SUM(CASE WHEN is_dramatic_reach=1 THEN own_tsumo ELSE 0 END)
          AS dramatic_tsumo_count
 FROM reach_outcomes GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.accepted_reach_count,
       b.dramatic_reach_count,
       ROUND(100.0*b.dramatic_reach_count/
             NULLIF(b.accepted_reach_count,0),4) AS dramatic_reach_pct,
       b.dramatic_agari_count,
       ROUND(100.0*b.dramatic_agari_count/
             NULLIF(b.dramatic_reach_count,0),4) AS dramatic_success_pct,
       b.dramatic_ron_count,b.dramatic_tsumo_count
FROM by_player b JOIN player p ON p.id=b.player_id
ORDER BY dramatic_reach_pct DESC,
         b.dramatic_reach_count DESC,
         b.accepted_reach_count DESC,p.name;
