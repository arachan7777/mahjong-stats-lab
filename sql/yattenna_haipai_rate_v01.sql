-- 麻雀スタッツ研究所 第16独立指標「やってんな配牌率」 SQL v0.1
-- 定義：自分の初期配牌13枚の時点でイーシャンテン(1)またはテンパイ(0)だった割合。
-- 分子：haipai_event に対応する本人の player_state.shanten_count IN (0,1) の人局数。
-- 分母：参加した全局数（kyoku_player_result の1人×1局）。同じ東1局でも本場が違えば別局。
-- 親・子とも「初期配牌13枚」を判定。親の第一ツモを含めない。
-- 0＝テンパイ、1＝イーシャンテン。2以上は対象外。
-- 判定の shanten_count は標準形・七対子・国士無双のうち最小の値。
-- リーチ・和了・鳴き・流局を問わず全参加局を数える。
-- 参考列：テンパイ配牌数、イーシャンテン配牌数、各々の率。
-- 厳密な1シャンテンとテンパイの2カテゴリが重ならないことを確認。
-- 既存01〜15と派生11B/13Bの定義・SQLに変更なし。
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
participations AS MATERIALIZED (
 SELECT k.id AS kyoku_id, r.player_id
 FROM kyoku k
 JOIN selected_games sg ON sg.game_id=k.game_id
 JOIN kyoku_player_result r ON r.kyoku_id=k.id
),
initial_states AS MATERIALIZED (
 SELECT e.kyoku_id, h.actor_player_id AS player_id,
        psh.shanten_count,
        psh.standard_type_shanten_count,
        psh.seven_pairs_shanten_count,
        psh.thirteen_orphans_shanten_count
 FROM haipai_event h
 JOIN event e ON e.id=h.event_id
 JOIN selected_games sg
   ON sg.game_id=(SELECT game_id FROM kyoku WHERE id=e.kyoku_id)
 JOIN player_state psh ON psh.event_id=h.event_id
   AND psh.player_id=h.actor_player_id
   AND psh.turn_number=0
),
by_player AS (
 SELECT q.player_id,
        COUNT(*) AS played_kyoku_count,
        SUM(CASE WHEN s.shanten_count IN (0,1) THEN 1 ELSE 0 END)
          AS yattenna_haipai_count,
        SUM(CASE WHEN s.shanten_count=0 THEN 1 ELSE 0 END)
          AS haipai_tenpai_count,
        SUM(CASE WHEN s.shanten_count=1 THEN 1 ELSE 0 END)
          AS haipai_ishanten_count,
        SUM(CASE WHEN s.shanten_count IS NULL THEN 1 ELSE 0 END)
          AS missing_initial_state_count
 FROM participations q
 LEFT JOIN initial_states s
   ON s.kyoku_id=q.kyoku_id AND s.player_id=q.player_id
 GROUP BY q.player_id
)
SELECT p.id AS player_id,p.name AS player_name,
       b.played_kyoku_count,b.yattenna_haipai_count,
       ROUND(100.0*b.yattenna_haipai_count/
             NULLIF(b.played_kyoku_count,0),4)
         AS yattenna_haipai_pct,
       b.haipai_tenpai_count,
       b.haipai_ishanten_count,
       ROUND(100.0*b.haipai_tenpai_count/
             NULLIF(b.played_kyoku_count,0),4)
         AS haipai_tenpai_pct,
       ROUND(100.0*b.haipai_ishanten_count/
             NULLIF(b.played_kyoku_count,0),4)
         AS haipai_ishanten_pct,
       b.missing_initial_state_count
FROM by_player b
JOIN player p ON p.id=b.player_id
ORDER BY yattenna_haipai_pct DESC,
         b.yattenna_haipai_count DESC,
         b.played_kyoku_count DESC,p.name;
