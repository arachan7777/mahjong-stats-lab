-- 麻雀スタッツ研究所 正式共通集計SQL / 平均先制テンパイ巡目
-- 既存の独立21指標＋派生2種の定義・番号は変更しない。
-- 対象：全選手。対象DBの全期間。 period は all / season / stage / season_stage。
-- source: konoui/m-league-game-db; validated against snapshot 2026-11-20.
-- SQLite read-only SELECT; no permanent tables or writes.
WITH
candidate_tenpai AS MATERIALIZED (
 SELECT e.kyoku_id,e.event_order,pts.player_id,ps.turn_number,e.type,
        ROW_NUMBER() OVER (PARTITION BY e.kyoku_id ORDER BY e.event_order,pts.player_id) AS first_position
 FROM player_tenpai_state pts
 JOIN event e ON e.id=pts.event_id
 JOIN player_state ps ON ps.event_id=pts.event_id AND ps.player_id=pts.player_id
 WHERE pts.is_actor=1 AND e.type IN ('haipai','discard')
),
observations AS MATERIALIZED (
 SELECT c.player_id,p.name AS player_name,
        ls.start_year AS season_start_year,ss.stage,
        c.turn_number AS turn_no,c.type AS event_type
 FROM candidate_tenpai c
 JOIN event e ON e.kyoku_id=c.kyoku_id AND e.event_order=c.event_order
 JOIN kyoku k ON k.id=c.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN player p ON p.id=c.player_id
 WHERE c.first_position=1
),
scoped AS (
 SELECT 'all' AS period, NULL AS season_start_year, NULL AS stage, player_id, player_name, turn_no, event_type FROM observations
 UNION ALL SELECT 'season', season_start_year, NULL, player_id, player_name, turn_no, event_type FROM observations
 UNION ALL SELECT 'stage', NULL, stage, player_id, player_name, turn_no, event_type FROM observations
 UNION ALL SELECT 'season_stage', season_start_year, stage, player_id, player_name, turn_no, event_type FROM observations
),
aggregated AS (
 SELECT period,season_start_year,stage,player_id,player_name,
        COUNT(*) AS event_count, SUM(turn_no) AS turn_total,
        SUM(CASE WHEN turn_no <= 6 THEN 1 ELSE 0 END) AS early_le6,
        SUM(CASE WHEN event_type='ron' THEN 1 ELSE 0 END) AS ron_count,
        SUM(CASE WHEN event_type='tsumo' THEN 1 ELSE 0 END) AS tsumo_count
 FROM scoped
 GROUP BY period,season_start_year,stage,player_id,player_name
),
ranking AS (
 SELECT a.*,
        ROUND(1.0*a.turn_total / a.event_count,4) AS avg_turn,
        ROUND(1.0*SUM(a.turn_total) OVER w / NULLIF(SUM(a.event_count) OVER w,0),4) AS league_avg_turn,
        ROW_NUMBER() OVER (PARTITION BY period,season_start_year,stage
                           ORDER BY 1.0*a.turn_total/a.event_count ASC,a.event_count DESC,player_name ASC) AS league_rank,
        COUNT(*) OVER w AS players_with_events
 FROM aggregated a
 WINDOW w AS (PARTITION BY period,season_start_year,stage)
)
SELECT period,season_start_year,stage,player_id,player_name,
       event_count,turn_total,avg_turn,early_le6,ron_count,tsumo_count,
       league_avg_turn,league_rank,players_with_events
FROM ranking
ORDER BY CASE period WHEN 'all' THEN 0 WHEN 'season' THEN 1 WHEN 'stage' THEN 2 ELSE 3 END,
         season_start_year,stage,league_rank;
