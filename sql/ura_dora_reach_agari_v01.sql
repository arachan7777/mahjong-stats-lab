-- 麻雀スタッツ研究所 第14指標群「裏ドラ」独立SQL v0.1
-- 対象：成立リーチのあとに本人が和了した全イベント（ロン・ツモ両方）。
-- 1リーチ和了=1回。裏ドラ表示牌が複数あっても、裏ドラが何枚乗っても1回と数える。
-- 裏ドラ乗り回数：和了時の裏ドラが合計1枚以上だったリーチ和了回数。
-- 裏ドラ乗り率：裏ドラ乗り回数÷全リーチ和了回数×100。
-- 裏ドラ総枚数：agari_yaku の「裏ドラ」の han 合計。1回で3枚なら3枚を加算。
-- 裏ドラ平均枚数（乗ったとき）：裏ドラ総枚数÷裏ドラ乗り回数。
-- 裏ドラ2枚以上回数：複数枚が乗ったリーチ和了の回数。関連する参考列。
-- 槓裏・裏ドラ表示牌複数・暗刻への的中も、和了1件にまとめ、枚数は翻数で加算。
-- リーチ不成立・ダマ和了は対象外。カン裏を別リーチとは数えない。
-- 全期間のほか年度・ステージ別も同じ分子分母で加重集計。規定回数未設定。
-- 既存指標01〜13・派生11B/13Bの定義とSQLは変更しない。
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
 SELECT r.actor_player_id AS player_id, e.kyoku_id, e.event_order AS reach_order,
        e.id AS reach_event_id
 FROM reach_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
 WHERE r.is_accepted=1
),
reach_agari AS MATERIALIZED (
 SELECT a.event_id AS agari_event_id,a.actor_player_id AS player_id,
        e.kyoku_id,e.type AS agari_type
 FROM agari_event a
 JOIN event e ON e.id=a.event_id
 JOIN accepted_reaches r ON r.player_id=a.actor_player_id
                        AND r.kyoku_id=e.kyoku_id
                        AND e.event_order>r.reach_order
 WHERE e.type IN ('ron','tsumo')
),
ura_by_agari AS MATERIALIZED (
 SELECT ay.agari_event_id,
        SUM(CASE WHEN yn.name='裏ドラ' THEN ay.han ELSE 0 END) AS ura_tiles
 FROM agari_yaku ay
 JOIN yaku_name yn ON yn.id=ay.yaku_name_id
 GROUP BY ay.agari_event_id
),
scored_reach_agari AS MATERIALIZED (
 SELECT a.*,COALESCE(u.ura_tiles,0) AS ura_tiles
 FROM reach_agari a
 LEFT JOIN ura_by_agari u ON u.agari_event_id=a.agari_event_id
),
by_player AS (
 SELECT player_id,COUNT(*) AS reach_agari_count,
        SUM(CASE WHEN ura_tiles>0 THEN 1 ELSE 0 END) AS ura_hit_agari_count,
        SUM(ura_tiles) AS ura_total_tiles,
        SUM(CASE WHEN ura_tiles>=2 THEN 1 ELSE 0 END) AS ura_multi_hit_count,
        MAX(ura_tiles) AS ura_max_tiles_in_agari
 FROM scored_reach_agari
 GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.reach_agari_count,b.ura_hit_agari_count,
       ROUND(100.0*b.ura_hit_agari_count/NULLIF(b.reach_agari_count,0),4)
           AS ura_hit_rate_pct,
       b.ura_total_tiles,
       ROUND(1.0*b.ura_total_tiles/NULLIF(b.ura_hit_agari_count,0),4)
           AS ura_avg_tiles_when_hit,
       b.ura_multi_hit_count,b.ura_max_tiles_in_agari
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY ura_hit_rate_pct DESC,
         b.ura_hit_agari_count DESC,
         b.reach_agari_count DESC,p.name;
