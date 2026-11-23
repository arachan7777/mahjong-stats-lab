-- 麻雀スタッツ研究所 正式共通集計SQL / 平均和了巡目
-- 既存の独立21指標＋派生2種の定義・番号は変更しない。
-- 対象：全選手。対象DBの全期間。 period は all / season / stage / season_stage。
-- source: konoui/m-league-game-db; validated against snapshot 2026-11-20.
-- SQLite read-only SELECT; no permanent tables or writes.
WITH
observations AS MATERIALIZED (
 SELECT a.actor_player_id AS player_id,p.name AS player_name,
        ls.start_year AS season_start_year,ss.stage,
        (
          SELECT COUNT(*)
          FROM discard_event d
          JOIN event de ON de.id=d.event_id
          WHERE de.kyoku_id=e.kyoku_id
            AND de.event_order<e.event_order
            AND d.actor_player_id=a.actor_player_id
        ) + CASE WHEN e.type='tsumo' THEN 1 ELSE 0 END AS turn_no,
        e.type AS event_type
 FROM agari_event a
 JOIN event e ON e.id=a.event_id
 JOIN player p ON p.id=a.actor_player_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE e.type IN ('ron','tsumo')
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
