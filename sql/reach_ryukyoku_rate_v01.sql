-- 麻雀スタッツ研究所 第12独立指標「リーチ時流局率」 SQL v0.1
-- 定義：成立した本人のリーチのうち、当該局が流局で終了した割合。
-- 分母：reach_event.is_accepted=1 の成立リーチ数（リーチ宣言牌放銃など不成立は除く）。
-- 分子：分母の成立リーチのうち、同一kyoku_idにryukyoku_eventがある数。
-- 分子・分母は「成立リーチ1回」を単位とし、待ち牌枚数は一切使わない。
-- 本人以外の和了で終了したリーチも分母に含む。
-- ツモ和了・ロン和了で終了した局は分子には含めない。
-- 同じ局で2人以上がリーチして流局すれば、各人に1回ずつ計上。
-- 複数ステージを通算する際は分子合計÷分母合計。対局/選手ごとの率の平均ではない。
-- start_year=NULL, stage=NULL: 全シーズン・全ステージ。
-- start_year=2025: 2025-26シーズンの全ステージ。
-- 第11指標「王牌幽閉率」と派生「リーチ王牌幽閉率」は変更しない。
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
draw_ended_kyoku AS MATERIALIZED (
 SELECT DISTINCT e.kyoku_id
 FROM ryukyoku_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
),
accepted_reach AS MATERIALIZED (
 SELECT r.actor_player_id AS player_id,e.kyoku_id,
        e.id AS reach_event_id
 FROM reach_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
 WHERE r.is_accepted=1
),
by_player AS (
 SELECT a.player_id,
        COUNT(*) AS accepted_reach_count,
        SUM(CASE WHEN d.kyoku_id IS NOT NULL THEN 1 ELSE 0 END)
          AS reach_ryukyoku_count,
        SUM(CASE WHEN d.kyoku_id IS NULL THEN 1 ELSE 0 END)
          AS reach_non_ryukyoku_count
 FROM accepted_reach a
 LEFT JOIN draw_ended_kyoku d ON d.kyoku_id=a.kyoku_id
 GROUP BY a.player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.accepted_reach_count,b.reach_ryukyoku_count,
       b.reach_non_ryukyoku_count,
       ROUND(100.0*b.reach_ryukyoku_count/
          NULLIF(b.accepted_reach_count,0),4)
          AS reach_ryukyoku_pct
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY reach_ryukyoku_pct DESC,
         b.reach_ryukyoku_count DESC,
         b.accepted_reach_count DESC,p.name;
