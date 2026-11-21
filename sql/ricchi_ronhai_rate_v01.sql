-- 麻雀スタッツ研究所 リッチロンハイ率 SQL v0.1
-- 既存集計マニュアルの定義に基づく独立した新規SQL（他の原典は変更しない）。
-- 定義: リーチ宣言牌で放銃した局数 / リーチ宣言した局数 ×100。
-- 分母は成立リーチ数ではない。宣言牌で放銃して不成立になったリーチも含む。
-- 判定: 宣言打牌フラグ=1の打牌と、直前の本人リーチイベントを同一局内で結ぶ。
--       reach_event.is_accepted=0 かつ、宣言牌と同じ牌で本人がロン放銃
--       したイベントを確認したものだけを分子に計上。
--       同じ牌を後の巡目に放銃しても、成立リーチなら分子に計上しない。
-- 赤牌0m/0p/0sは通常5と同種として比較。
-- 対象期間: params.start_year=NULL なら全シーズン、stage=NULL なら全ステージ。
WITH
params AS (SELECT NULL AS start_year, NULL AS stage),
selected_games AS (
  SELECT g.id AS game_id
  FROM game g
  JOIN season_stage ss ON ss.id=g.season_stage_id
  JOIN league_season ls ON ls.id=ss.league_season_id
  CROSS JOIN params cfg
  WHERE (cfg.start_year IS NULL OR ls.start_year=cfg.start_year)
    AND (cfg.stage IS NULL OR ss.stage=cfg.stage)
),
declarations AS (
  SELECT e.kyoku_id, r.actor_player_id AS player_id,
         e.event_order AS reach_order, r.is_accepted,
         de.event_order AS declaration_order,
         CASE WHEN substr(d.tile,1,1)='0'
              THEN '5'||substr(d.tile,2) ELSE d.tile END AS declaration_tile
  FROM reach_event r
  JOIN event e ON e.id=r.event_id
  JOIN kyoku k ON k.id=e.kyoku_id
  JOIN selected_games sg ON sg.game_id=k.game_id
  JOIN discard_event d ON d.actor_player_id=r.actor_player_id
    AND d.is_reach_declaration=1
  JOIN event de ON de.id=d.event_id
    AND de.kyoku_id=e.kyoku_id
    AND de.event_order>e.event_order
),
judged AS (
  SELECT d.*,
         CASE WHEN d.is_accepted=0 AND EXISTS (
           SELECT 1
           FROM event ron
           JOIN agari_event a ON a.event_id=ron.id
           WHERE ron.kyoku_id=d.kyoku_id
             AND ron.type='ron'
             AND ron.event_order>d.declaration_order
             AND a.target_player_id=d.player_id
             AND (CASE WHEN substr(a.agari_tile,1,1)='0'
                      THEN '5'||substr(a.agari_tile,2)
                      ELSE a.agari_tile END)=d.declaration_tile
         ) THEN 1 ELSE 0 END AS is_ricchi_ronhai
  FROM declarations d
),
by_kyoku AS (
  SELECT player_id,kyoku_id,
         MAX(is_ricchi_ronhai) AS is_ricchi_ronhai,
         MAX(CASE WHEN is_accepted=0 THEN 1 ELSE 0 END) AS rejected_reach
  FROM judged
  GROUP BY player_id,kyoku_id
),
by_player AS (
  SELECT player_id,
         COUNT(*) AS reach_declaration_kyoku_count,
         SUM(is_ricchi_ronhai) AS ricchi_ronhai_kyoku_count,
         SUM(rejected_reach) AS rejected_reach_kyoku_count
  FROM by_kyoku
  GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.reach_declaration_kyoku_count,
       b.ricchi_ronhai_kyoku_count,
       ROUND(100.0*b.ricchi_ronhai_kyoku_count/
         NULLIF(b.reach_declaration_kyoku_count,0),4) AS ricchi_ronhai_pct,
       b.rejected_reach_kyoku_count
FROM by_player b JOIN player p ON p.id=b.player_id
ORDER BY ricchi_ronhai_pct DESC,
         b.ricchi_ronhai_kyoku_count DESC,
         b.reach_declaration_kyoku_count DESC,p.name;
