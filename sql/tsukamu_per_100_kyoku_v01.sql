-- 麻雀スタッツ研究所 どんだけ掴むねん指数 SQL v0.1
-- 2026年9月24日に了承された局数補正型の表示指標を継承。
-- 分子: 自分がツモした瞬間、少なくとも1人の他家が実際にロン可能だった牌をツモした枚数。
--       他家のフリテンを除外し、赤5/通常5は同牌種。同じツモで複数家がロン可能でも1枚。
--       自分がすでに持っていた牌が後で他家の当たり牌になっても分子に含めない。
-- 分母: 出場した試合における参加局数（その局で実際にツモが発生しなくても参加局として数える）。
-- 指数: 当たり牌ツモ枚数 / 参加局数 * 100（100局あたり当たり牌ツモ枚数）。
--      リーグ平均=100とする相対指数ではない。ドンツカ率とは分母が異なる。
-- 判定ロジックは既存のドンツカ率v0.4、全選手ランナーを継承し、参加局の分母のみ独立集計。
-- player_id=54 はHIRO柴田。start_year=NULLで全年度、stage=NULLで全ステージ。
WITH
params AS (SELECT 54 AS player_id, NULL AS start_year, NULL AS stage),
selected_games AS MATERIALIZED (
 SELECT g.id AS game_id
 FROM game g
 JOIN game_player_result gpr ON gpr.game_id=g.id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 CROSS JOIN params cfg
 WHERE gpr.player_id=cfg.player_id
   AND (cfg.start_year IS NULL OR ls.start_year=cfg.start_year)
   AND (cfg.stage IS NULL OR ss.stage=cfg.stage)
),
participant_kyoku AS (
 SELECT COUNT(k.id) AS participated_kyoku_count
 FROM selected_games sg
 JOIN kyoku k ON k.game_id=sg.game_id
),
draws AS MATERIALIZED (
 SELECT e.id AS draw_id,e.kyoku_id,e.event_order AS draw_order,
        k.game_id,
        CASE WHEN substr(d.tile,1,1)='0'
             THEN '5'||substr(d.tile,2) ELSE d.tile END AS tile
 FROM draw_event d
 JOIN event e ON e.id=d.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN selected_games sg ON sg.game_id=k.game_id
 CROSS JOIN params cfg
 WHERE d.actor_player_id=cfg.player_id
),
last_actor AS MATERIALIZED (
 SELECT d.*,gpr.player_id AS opponent_id,
        (SELECT e2.id
         FROM event e2
         JOIN player_state ps2 ON ps2.event_id=e2.id
         WHERE e2.kyoku_id=d.kyoku_id
           AND e2.event_order<d.draw_order
           AND ps2.player_id=gpr.player_id
         ORDER BY e2.event_order DESC,e2.id DESC LIMIT 1) AS actor_event_id
 FROM draws d
 JOIN game_player_result gpr ON gpr.game_id=d.game_id
 CROSS JOIN params cfg
 WHERE gpr.player_id<>cfg.player_id
),
eligible_actor AS MATERIALIZED (
 SELECT a.*,ae.event_order AS actor_order
 FROM last_actor a
 JOIN player_state ps ON ps.event_id=a.actor_event_id
                     AND ps.player_id=a.opponent_id
 JOIN event ae ON ae.id=a.actor_event_id
 WHERE ps.shanten_count=0
),
latest_snapshot AS MATERIALIZED (
 SELECT a.*,
        (SELECT pts.event_id
         FROM event se
         JOIN player_tenpai_state pts
           ON pts.event_id=se.id AND pts.player_id=a.opponent_id
         WHERE se.kyoku_id=a.kyoku_id
           AND se.event_order>=a.actor_order
           AND se.event_order<a.draw_order
         ORDER BY se.event_order DESC,se.id DESC LIMIT 1) AS snapshot_event_id
 FROM eligible_actor a
),
hit_draws AS MATERIALIZED (
 SELECT DISTINCT s.draw_id
 FROM latest_snapshot s
 JOIN player_tenpai_state pts
   ON pts.event_id=s.snapshot_event_id AND pts.player_id=s.opponent_id
 JOIN tenpai_agari_matrix m
   ON m.event_id=s.snapshot_event_id AND m.player_id=s.opponent_id
 WHERE pts.is_furiten=0 AND m.is_ron_agari=1
   AND (CASE WHEN substr(m.waiting_tile,1,1)='0'
             THEN '5'||substr(m.waiting_tile,2) ELSE m.waiting_tile END)=s.tile
),
drawing_summary AS (
 SELECT COUNT(*) AS total_draws,
        COUNT(h.draw_id) AS hit_draws,
        COUNT(DISTINCT d.kyoku_id) AS kyoku_with_draw_count
 FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id
)
SELECT p.id AS player_id,p.name AS player_name,
       pk.participated_kyoku_count,
       ds.kyoku_with_draw_count,
       ds.total_draws,ds.hit_draws AS atari_tile_draws,
       ROUND(100.0*ds.hit_draws/NULLIF(pk.participated_kyoku_count,0),4)
         AS tsukamu_index_per_100_kyoku,
       ROUND(100.0*ds.hit_draws/NULLIF(ds.total_draws,0),4)
         AS dontsuka_pct_reference
FROM params cfg
JOIN player p ON p.id=cfg.player_id
CROSS JOIN participant_kyoku pk
CROSS JOIN drawing_summary ds;
