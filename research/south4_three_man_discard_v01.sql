-- 麻雀スタッツ研究所 研究候補「三万点以上捨てる一打」試算 v0.1
-- 意味：南4局の局開始時トップが、自分の放銃を含む局でトップから陥落し、
--       その後の南4局の連荘を含めても一度もトップへ戻れず、最終トップでもない。
-- さらにリーチ供託の支出による順位転落を放銃に誤帰属しないよう、
--       放銃の直前時点（成立リーチの1000点支出反映）の暫定順位を点数で確認。
-- 点数の「30000」は愛称由来。実際の放銃点数が30000点以上という条件ではない。
-- 過去に確定した第21指標「オーラス守護神率」の母集団（南4開始1着）と照合可能。
-- 今回は特定の1局のロン放銃を抽出。多重ロンは1放銃機会として扱う。
-- 各行は南4局の放銃者1人×1局（成否を問わず、広めに抽出した検証用の全件）。
-- 正式指標への採用・既存原典の改定は未実施。
WITH
all_rounds AS (
 SELECT k.id AS kyoku_id,k.game_id,k.round,k.honba_count,k.oya_player_id,
        LAG(k.id) OVER (PARTITION BY k.game_id ORDER BY k.id) AS previous_kyoku_id
 FROM kyoku k
),
south4 AS (
 SELECT * FROM all_rounds WHERE round='2z4'
),
first_south4 AS (
 SELECT game_id,MIN(kyoku_id) AS first_kyoku_id FROM south4 GROUP BY game_id
),
initial_leads AS (
 SELECT f.game_id,r.player_id,r.rank AS first_south4_start_rank
 FROM first_south4 f
 JOIN south4 k ON k.kyoku_id=f.first_kyoku_id
 JOIN kyoku_player_result r ON r.kyoku_id=k.previous_kyoku_id
),
ron_event_groups AS (
 SELECT k.kyoku_id,k.game_id,k.oya_player_id,k.honba_count,
        a.target_player_id AS loser_player_id,
        MIN(e.event_order) AS first_ron_order,
        COUNT(*) AS ron_winner_count,
        SUM(CASE WHEN a.actor_player_id=k.oya_player_id THEN 1 ELSE 0 END)
          AS winner_is_parent_count,
        SUM(a.agari_points+a.honba_points) AS total_ron_payment,
        GROUP_CONCAT(a.actor_player_id) AS winner_player_ids,
        GROUP_CONCAT(a.agari_points+a.honba_points) AS winner_payments
 FROM south4 k
 JOIN event e ON e.kyoku_id=k.kyoku_id AND e.type='ron'
 JOIN agari_event a ON a.event_id=e.id
 WHERE a.target_player_id IS NOT NULL
 GROUP BY k.kyoku_id,a.target_player_id
),
round_players AS (
 SELECT rg.*,
        prev.player_id,prev.rank AS before_kyoku_rank,prev.score AS before_kyoku_score,
        after.rank AS after_kyoku_rank,after.score AS after_kyoku_score,
        prev.score -
          1000*(SELECT COUNT(*)
                FROM event re
                JOIN reach_event rr ON rr.event_id=re.id
                WHERE re.kyoku_id=rg.kyoku_id
                  AND re.event_order<rg.first_ron_order
                  AND rr.is_accepted=1 AND rr.actor_player_id=prev.player_id)
        AS before_ron_score
 FROM ron_event_groups rg
 JOIN south4 k ON k.kyoku_id=rg.kyoku_id
 JOIN kyoku_player_result prev ON prev.kyoku_id=k.previous_kyoku_id
 JOIN kyoku_player_result after
   ON after.kyoku_id=rg.kyoku_id AND after.player_id=prev.player_id
),
loser_snapshot AS (
 SELECT rp.*,
        (SELECT MAX(other.before_ron_score)
         FROM round_players other
         WHERE other.kyoku_id=rp.kyoku_id AND other.loser_player_id=rp.loser_player_id
           AND other.player_id<>rp.player_id) AS max_other_before_ron_score
 FROM round_players rp
 WHERE rp.player_id=rp.loser_player_id
)
SELECT
  v.game_id,v.kyoku_id,v.honba_count,
  g.date AS game_date,ls.start_year AS season_start_year,ss.stage,
  v.player_id AS loser_player_id,p.name AS loser_name,
  v.oya_player_id,
  v.before_kyoku_rank,v.after_kyoku_rank,
  v.before_kyoku_score,v.before_ron_score,
  v.max_other_before_ron_score,v.after_kyoku_score,
  COALESCE(il.first_south4_start_rank,0) AS first_south4_start_rank,
  gr.rank AS final_rank,
  v.ron_winner_count,
  v.winner_is_parent_count,v.total_ron_payment,
  v.winner_player_ids,v.winner_payments,
  (SELECT COUNT(*)
   FROM south4 later
   JOIN kyoku_player_result later_rank
      ON later_rank.kyoku_id=later.kyoku_id AND later_rank.player_id=v.player_id
   WHERE later.game_id=v.game_id
     AND later.kyoku_id>v.kyoku_id AND later_rank.rank=1) AS later_first_rank_kyoku_count,
  (SELECT COUNT(*)
   FROM south4 later
   WHERE later.game_id=v.game_id AND later.kyoku_id>v.kyoku_id) AS later_south4_kyoku_count,
  CASE WHEN v.before_ron_score>v.max_other_before_ron_score THEN 1 ELSE 0 END
    AS strict_lead_before_ron,
  CASE WHEN v.before_ron_score=v.max_other_before_ron_score THEN 1 ELSE 0 END
    AS tied_lead_before_ron
FROM loser_snapshot v
JOIN game g ON g.id=v.game_id
JOIN season_stage ss ON ss.id=g.season_stage_id
JOIN league_season ls ON ls.id=ss.league_season_id
JOIN player p ON p.id=v.player_id
JOIN game_player_result gr ON gr.game_id=v.game_id AND gr.player_id=v.player_id
LEFT JOIN initial_leads il ON il.game_id=v.game_id AND il.player_id=v.player_id
ORDER BY v.game_id,v.kyoku_id,v.player_id;
