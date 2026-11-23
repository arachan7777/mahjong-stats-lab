-- 麻雀スタッツ研究所｜基本統計「和了役構成比」v0.1
-- 初回対象役：「三色同順」　正式DB 2026-11-20収録分を初回検算対象とする。
-- 新しい独立指標第22番ではない。既存の独立21指標＋派生2種は変更しない。
--
-- 定義：
-- 和了役構成比(%) = 指定役を含む本人の和了イベント数 / 本人の全和了イベント数 × 100
-- 複合役の場合、それぞれの構成役に1回ずつ計上してよい。
-- 同一和了内で同じ役を2回数えない。複合役があるため全役の構成比合計は100%を超えうる。
-- ドラ・赤ドラ・裏ドラ等の加算翻は和了役と区別。今回の対象は三色同順のみ。
-- ロン・ツモの両方、鳴き和了・門前和了の両方を含む。
-- 分母は「全和了」。流局、放銃、和了しなかった局は含まない。
-- 表示: 通算 all / 年度 season / ステージ stage / 年度×ステージ season_stage。
-- 門前／非門前の各三色回数、役の翻数別内訳（1翻・2翻）も併記。
-- SQL上の target_yaku にある名称だけ変えれば、他の和了役も同一条件で集計できる。
-- 両条件・最低和了回数での足切りは行わない。和了数0の場合の割合はNULL。
WITH
target_yaku AS (
    SELECT '三色同順' AS name
),
win_events AS (
    SELECT
        a.event_id AS agari_event_id,
        a.actor_player_id AS player_id,
        p.name AS player_name,
        ls.start_year AS season_start,
        ss.stage AS stage,
        a.is_menzen AS is_menzen,
        (
            SELECT y.han
            FROM agari_yaku y
            JOIN yaku_name n ON n.id = y.yaku_name_id
            WHERE y.agari_event_id = a.event_id
              AND n.name = (SELECT name FROM target_yaku)
        ) AS target_yaku_han
    FROM agari_event a
    JOIN event e ON e.id = a.event_id
    JOIN kyoku k ON k.id = e.kyoku_id
    JOIN game g ON g.id = k.game_id
    JOIN season_stage ss ON ss.id = g.season_stage_id
    JOIN league_season ls ON ls.id = ss.league_season_id
    JOIN player p ON p.id = a.actor_player_id
),
scoped AS (
    SELECT 'all' AS scope, NULL AS season_start, NULL AS stage, * FROM win_events
    UNION ALL
    SELECT 'season' AS scope, season_start, NULL AS stage, * FROM win_events
    UNION ALL
    SELECT 'stage' AS scope, NULL AS season_start, stage, * FROM win_events
    UNION ALL
    SELECT 'season_stage' AS scope, season_start, stage, * FROM win_events
),
aggregated AS (
    SELECT
        scope,
        season_start,
        stage,
        player_id,
        player_name,
        COUNT(*) AS agari_count,
        COUNT(target_yaku_han) AS target_yaku_agari_count,
        SUM(CASE WHEN target_yaku_han IS NOT NULL AND is_menzen = 1 THEN 1 ELSE 0 END) AS target_yaku_menzen_count,
        SUM(CASE WHEN target_yaku_han IS NOT NULL AND is_menzen = 0 THEN 1 ELSE 0 END) AS target_yaku_open_count,
        SUM(CASE WHEN target_yaku_han = 1 THEN 1 ELSE 0 END) AS target_yaku_1han_count,
        SUM(CASE WHEN target_yaku_han = 2 THEN 1 ELSE 0 END) AS target_yaku_2han_count
    FROM scoped
    GROUP BY scope, season_start, stage, player_id, player_name
)
SELECT
    a.scope,
    a.season_start,
    a.stage,
    a.player_id,
    a.player_name,
    (SELECT name FROM target_yaku) AS target_yaku,
    a.agari_count,
    a.target_yaku_agari_count,
    ROUND(100.0 * a.target_yaku_agari_count / NULLIF(a.agari_count, 0), 4) AS target_yaku_composition_pct,
    a.target_yaku_menzen_count,
    a.target_yaku_open_count,
    a.target_yaku_1han_count,
    a.target_yaku_2han_count
FROM aggregated a
ORDER BY
    CASE a.scope
        WHEN 'all' THEN 1 WHEN 'season' THEN 2
        WHEN 'stage' THEN 3 ELSE 4 END,
    a.season_start,
    a.stage,
    target_yaku_composition_pct DESC,
    a.target_yaku_agari_count DESC,
    a.player_name;
