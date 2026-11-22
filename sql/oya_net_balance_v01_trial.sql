-- 麻雀スタッツ研究所：「親番純収支」試算SQL v0.1
-- 主指標 = 親番での収入総点数 - 親番での支出総点数（点）。
-- 収入: 親番の和了（ロン/ツモ、供託・本場含む）+ 親番の流局聴牌料。
-- 支出: 親番放銃（ロン本体+本場）+ 親被り（子ツモ時の親払い・本場含む）
--       + 親番の流局不聴罰符 + 親番の成立リーチの供託1000点。
-- 収支は kyoku_player_result.score の局開始→終了差額でも独立照合する。
-- 親番を「局開始時のoya_player_id」で判定し、流局・連荘も各局1回と数える。
-- 親番の自己リーチ棒がその局の和了で戻った場合は収入と支出の両方に反映。
-- 既存「第6指標 親被り率／指数」の収支計算法と接続し、原典は変更しない。
-- start_year=NULL / stage=NULL は全年度・全ステージ。
WITH
params AS (SELECT NULL AS start_year,NULL AS stage),
target_games AS (
 SELECT g.id AS game_id
 FROM game g JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 CROSS JOIN params p
 WHERE (p.start_year IS NULL OR ls.start_year=p.start_year)
   AND (p.stage IS NULL OR ss.stage=p.stage)
),
score_sequence AS (
 SELECT k.id AS kyoku_id,k.game_id,k.oya_player_id,
        kpr.player_id,kpr.score,
        COALESCE(LAG(kpr.score) OVER (
          PARTITION BY k.game_id,kpr.player_id ORDER BY k.id
        ),25000) AS before_score
 FROM kyoku k
 JOIN target_games tg ON tg.game_id=k.game_id
 JOIN kyoku_player_result kpr ON kpr.kyoku_id=k.id
),
parent_kyoku AS (
 SELECT kyoku_id,game_id,player_id,before_score,score,
        score-before_score AS score_delta
 FROM score_sequence
 WHERE player_id=oya_player_id
),
agari_base AS (
 SELECT e.kyoku_id,e.type,a.actor_player_id,a.target_player_id,
        a.agari_points,a.honba_points,a.kyotaku_points,a.revenue_points,
        k.oya_player_id,
        CASE
          WHEN a.is_yakuman=1 THEN CAST(a.agari_points/4 AS INTEGER)
          WHEN a.han>=11 THEN 6000
          WHEN a.han>=8 THEN 4000
          WHEN a.han>=6 THEN 3000
          WHEN a.han>=5 THEN 2000
          WHEN a.fu*(1 << (a.han+2))>=1920 THEN 2000
          ELSE a.fu*(1 << (a.han+2))
        END AS base_point
 FROM event e
 JOIN agari_event a ON a.event_id=e.id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN target_games tg ON tg.game_id=k.game_id
 WHERE e.type IN ('ron','tsumo')
),
cash_flow AS (
 -- 親番でロン／ツモの和了収入：本場・回収供託も含む。
 SELECT a.kyoku_id,'own_agari' AS category,
        a.revenue_points AS income,0 AS expense
 FROM agari_base a
 WHERE a.actor_player_id=a.oya_player_id
 UNION ALL
 -- 親番で放銃：和了者の本体点数＋本場支払（供託は支払者からの支出ではない）。
 SELECT a.kyoku_id,'deal_in',0,a.agari_points+a.honba_points
 FROM agari_base a
 WHERE a.type='ron' AND a.target_player_id=a.oya_player_id
 UNION ALL
 -- 子ツモの親支払い：基礎点×2を100点単位で切上げ＋本場100点/本場。
 SELECT a.kyoku_id,'parent_tsumo_loss',0,
        100*CAST((2*a.base_point+99)/100 AS INTEGER)
        +CAST(a.honba_points/3 AS INTEGER)
 FROM agari_base a
 WHERE a.type='tsumo' AND a.actor_player_id<>a.oya_player_id
 UNION ALL
 -- 親番の流局：聴牌料／不聴罰符は同じ項目から符号別に取り出す。
 SELECT e.kyoku_id,'ryukyoku_tenpai',MAX(rp.tenpai_points,0),
        MAX(-rp.tenpai_points,0)
 FROM event e
 JOIN ryukyoku_event re ON re.event_id=e.id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN target_games tg ON tg.game_id=k.game_id
 JOIN ryukyoku_player rp
   ON rp.ryukyoku_event_id=e.id AND rp.player_id=k.oya_player_id
 UNION ALL
 -- 成立リーチ供託はその時点で1000点支払う。和了時の戻りは収入側に入る。
 SELECT e.kyoku_id,'accepted_reach',0,1000
 FROM event e
 JOIN reach_event r ON r.event_id=e.id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN target_games tg ON tg.game_id=k.game_id
 WHERE r.is_accepted=1 AND r.actor_player_id=k.oya_player_id
),
by_kyoku AS (
 SELECT k.kyoku_id,
        COALESCE(SUM(f.income),0) AS income_points,
        COALESCE(SUM(f.expense),0) AS expense_points,
        COALESCE(SUM(CASE WHEN f.category='own_agari' THEN f.income ELSE 0 END),0) AS agari_income,
        COALESCE(SUM(CASE WHEN f.category='ryukyoku_tenpai' THEN f.income ELSE 0 END),0) AS tenpai_income,
        COALESCE(SUM(CASE WHEN f.category='deal_in' THEN f.expense ELSE 0 END),0) AS deal_in_expense,
        COALESCE(SUM(CASE WHEN f.category='parent_tsumo_loss' THEN f.expense ELSE 0 END),0) AS kaburi_expense,
        COALESCE(SUM(CASE WHEN f.category='ryukyoku_tenpai' THEN f.expense ELSE 0 END),0) AS noten_expense,
        COALESCE(SUM(CASE WHEN f.category='accepted_reach' THEN f.expense ELSE 0 END),0) AS reach_expense
 FROM parent_kyoku k
 LEFT JOIN cash_flow f ON f.kyoku_id=k.kyoku_id
 GROUP BY k.kyoku_id
),
verified AS (
 SELECT k.*,b.income_points,b.expense_points,
        b.agari_income,b.tenpai_income,b.deal_in_expense,
        b.kaburi_expense,b.noten_expense,b.reach_expense,
        b.income_points-b.expense_points AS reconstructed_net,
        (b.income_points-b.expense_points)-k.score_delta AS audit_diff
 FROM parent_kyoku k
 JOIN by_kyoku b ON b.kyoku_id=k.kyoku_id
),
by_player AS (
 SELECT player_id,COUNT(*) AS parent_kyoku_count,
        SUM(income_points) AS total_income_points,
        SUM(expense_points) AS total_expense_points,
        SUM(reconstructed_net) AS parent_net_points,
        ROUND(1.0*SUM(reconstructed_net)/COUNT(*),2) AS net_per_parent_kyoku,
        SUM(agari_income) AS agari_income_points,
        SUM(tenpai_income) AS tenpai_income_points,
        SUM(deal_in_expense) AS deal_in_expense_points,
        SUM(kaburi_expense) AS kaburi_expense_points,
        SUM(noten_expense) AS noten_expense_points,
        SUM(reach_expense) AS reach_expense_points,
        SUM(score_delta) AS score_delta_net_points,
        SUM(CASE WHEN audit_diff<>0 THEN 1 ELSE 0 END) AS audit_mismatch_kyoku_count,
        SUM(CASE WHEN reconstructed_net>0 THEN 1 ELSE 0 END) AS plus_kyoku_count,
        SUM(CASE WHEN reconstructed_net<0 THEN 1 ELSE 0 END) AS minus_kyoku_count,
        SUM(CASE WHEN reconstructed_net=0 THEN 1 ELSE 0 END) AS zero_kyoku_count
 FROM verified GROUP BY player_id
)
SELECT p.id AS player_id,p.name AS player_name,b.*
FROM by_player b JOIN player p ON p.id=b.player_id
ORDER BY b.parent_net_points DESC,b.net_per_parent_kyoku DESC,p.name;
