-- 麻雀スタッツ研究所 ドンツカ総合研究 v0.26 共通ツモ・対他家抽出
-- Parameters: :player_id (required), :start_year (nullable), :stage (nullable)
-- One output row per own draw × each of the other three players. The row is
-- retained when the opponent is not tenpai, is furiten, or cannot ron the tile;
-- this preserves the all-draw denominator and the opponent-specific risk state.
-- The `is_dontsuka` predicate inherits scripts/rank_dontsuka_all_matches.py.
-- Read-only query; no persistent database objects are created.

WITH
draws AS MATERIALIZED (
    SELECT
        e.id AS draw_event_id,
        e.kyoku_id,
        e.event_order AS draw_order,
        k.game_id,
        d.actor_player_id AS drawer_player_id,
        CASE WHEN substr(d.tile, 1, 1) = '0'
             THEN '5' || substr(d.tile, 2) ELSE d.tile END AS tile_type,
        CASE WHEN substr(d.tile, 1, 1) = '0' THEN 1 ELSE 0 END AS is_red_draw,
        d.tile AS recorded_draw_tile,
        d.is_rinshan,
        d.wall_remaining_count,
        k.round,
        k.honba_count,
        k.kyotaku_count,
        g.date AS game_date,
        ls.start_year AS season_start_year,
        ss.stage
    FROM draw_event d
    JOIN event e ON e.id = d.event_id
    JOIN kyoku k ON k.id = e.kyoku_id
    JOIN game g ON g.id = k.game_id
    JOIN season_stage ss ON ss.id = g.season_stage_id
    JOIN league_season ls ON ls.id = ss.league_season_id
    WHERE d.actor_player_id = :player_id
      AND (:start_year IS NULL OR ls.start_year = :start_year)
      AND (:stage IS NULL OR ss.stage = :stage)
),
draw_opponents AS MATERIALIZED (
    SELECT d.*, gr.player_id AS opponent_player_id
    FROM draws d
    JOIN game_player_result gr ON gr.game_id = d.game_id
    WHERE gr.player_id <> d.drawer_player_id
),
opponent_last_action AS MATERIALIZED (
    SELECT
        d.*,
        (SELECT e2.id
         FROM event e2
         JOIN player_state ps2 ON ps2.event_id = e2.id
         WHERE e2.kyoku_id = d.kyoku_id
           AND e2.event_order < d.draw_order
           AND ps2.player_id = d.opponent_player_id
         ORDER BY e2.event_order DESC, e2.id DESC
         LIMIT 1) AS opponent_action_event_id
    FROM draw_opponents d
),
opponent_action AS MATERIALIZED (
    SELECT
        a.*,
        ae.event_order AS opponent_action_order,
        ps.turn_number AS opponent_turn_number,
        ps.hand AS opponent_hand,
        ps.called_blocks AS opponent_called_blocks,
        ps.shanten_count AS opponent_shanten_count,
        ps.call_count AS opponent_call_count,
        ps.furo_count AS opponent_furo_count,
        ps.is_menzen AS opponent_is_menzen
    FROM opponent_last_action a
    LEFT JOIN event ae ON ae.id = a.opponent_action_event_id
    LEFT JOIN player_state ps
      ON ps.event_id = a.opponent_action_event_id
     AND ps.player_id = a.opponent_player_id
),
opponent_snapshot_id AS MATERIALIZED (
    SELECT
        a.*,
        (SELECT pts.event_id
         FROM event se
         JOIN player_tenpai_state pts
           ON pts.event_id = se.id
          AND pts.player_id = a.opponent_player_id
         WHERE se.kyoku_id = a.kyoku_id
           AND se.event_order >= a.opponent_action_order
           AND se.event_order < a.draw_order
         ORDER BY se.event_order DESC, se.id DESC
         LIMIT 1) AS opponent_snapshot_event_id
    FROM opponent_action a
),
opponent_snapshot AS MATERIALIZED (
    SELECT
        a.*,
        pts.is_actor AS snapshot_is_actor,
        pts.waiting_type,
        pts.waiting_tiles,
        pts.available_tile_count,
        pts.ideal_tile_count,
        pts.discarded_tile_count,
        pts.dora_indicator_tile_count,
        pts.is_reached,
        pts.is_furiten,
        pts.is_discard_furiten,
        pts.is_temporary_furiten,
        pts.is_reach_furiten
    FROM opponent_snapshot_id a
    LEFT JOIN player_tenpai_state pts
      ON pts.event_id = a.opponent_snapshot_event_id
     AND pts.player_id = a.opponent_player_id
),
own_state_id AS MATERIALIZED (
    SELECT
        d.draw_event_id,
        (SELECT e2.id
         FROM event e2
         JOIN player_state ps2 ON ps2.event_id = e2.id
         WHERE e2.kyoku_id = d.kyoku_id
           AND e2.event_order < d.draw_order
           AND ps2.player_id = d.drawer_player_id
         ORDER BY e2.event_order DESC, e2.id DESC
         LIMIT 1) AS own_state_event_id
    FROM draws d
),
draw_context AS MATERIALIZED (
    SELECT
        d.*,
        ps.turn_number AS drawer_turn_number,
        ps.hand AS drawer_hand_before_draw,
        ps.called_blocks AS drawer_called_blocks,
        ps.shanten_count AS drawer_shanten_before_draw,
        ps.call_count AS drawer_call_count,
        ps.furo_count AS drawer_furo_count,
        ps.is_menzen AS drawer_is_menzen
    FROM draws d
    LEFT JOIN own_state_id oi ON oi.draw_event_id = d.draw_event_id
    LEFT JOIN player_state ps
      ON ps.event_id = oi.own_state_event_id
     AND ps.player_id = d.drawer_player_id
)
SELECT
    o.draw_event_id,
    o.kyoku_id,
    o.game_id,
    o.game_date,
    o.season_start_year,
    o.stage,
    o.round,
    o.honba_count,
    o.kyotaku_count,
    o.drawer_player_id,
    o.opponent_player_id,
    o.recorded_draw_tile,
    o.tile_type,
    o.is_red_draw,
    o.is_rinshan,
    o.wall_remaining_count,
    own.drawer_turn_number,
    own.drawer_hand_before_draw,
    own.drawer_called_blocks,
    own.drawer_shanten_before_draw,
    own.drawer_call_count,
    own.drawer_furo_count,
    own.drawer_is_menzen,
    o.opponent_action_event_id,
    o.opponent_action_order,
    o.opponent_turn_number,
    o.opponent_hand,
    o.opponent_called_blocks,
    o.opponent_shanten_count,
    o.opponent_call_count,
    o.opponent_furo_count,
    o.opponent_is_menzen,
    o.opponent_snapshot_event_id,
    o.waiting_type,
    o.waiting_tiles,
    o.available_tile_count,
    o.ideal_tile_count,
    o.discarded_tile_count,
    o.dora_indicator_tile_count,
    o.is_reached,
    o.is_furiten,
    o.is_discard_furiten,
    o.is_temporary_furiten,
    o.is_reach_furiten,
    CASE WHEN EXISTS (
        SELECT 1
        FROM tenpai_agari_matrix m
        WHERE m.event_id = o.opponent_snapshot_event_id
          AND m.player_id = o.opponent_player_id
          AND o.opponent_shanten_count = 0
          AND COALESCE(o.is_furiten, 1) = 0
          AND m.is_ron_agari = 1
          AND (CASE WHEN substr(m.waiting_tile, 1, 1) = '0'
                    THEN '5' || substr(m.waiting_tile, 2)
                    ELSE m.waiting_tile END) = o.tile_type
    ) THEN 1 ELSE 0 END AS is_dontsuka
FROM opponent_snapshot o
LEFT JOIN draw_context own ON own.draw_event_id = o.draw_event_id
ORDER BY o.season_start_year, o.stage, o.game_id, o.kyoku_id, o.draw_order,
         o.opponent_player_id;
