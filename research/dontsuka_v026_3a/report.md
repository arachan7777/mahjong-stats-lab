# ドンツカ総合研究v0.26 第3工程A 実装・検証報告書

2026年11月28日／固定版DB 20261120-2341-04338cbb

## 1. 対象・参照
研究原典第1・2・3・11項、第1工程、第2工程A・B承認済み成果物、前回中断報告を確認。第3工程Aのみ実装。原典・正本DB・既存指標・承認済み成果物を変更しない。第3工程B以降の率集計は未実施。
原典 https://docs.google.com/document/d/1GsxBxUrteBtrvv6_HUrGBKd46m-TqDwrshlFlZaocqw/edit
中断報告 https://docs.google.com/document/d/1kJ71rCE0xyBM9_nCcvSQ2KpYeDfrvBqIEr9vDWq6OdU/edit
第2工程A報告 https://docs.google.com/document/d/1UexyT2sAfPboepYMYE_J9zW9lEkEAIBlnhPwjXP5w-I/edit
第2工程B報告 https://docs.google.com/document/d/1UPF5B7oUdvC1JLKIIm4FIJEsYN8MzWEI/edit

## 2. 実装
第1工程の承認済みSQLから対象を再抽出し、イベント列から他家の手牌、副露、成立済みリーチ、ダブルリーチ、ドラ表示をツモ時点まで再構成。第2工程Aの和了評価基盤（mahjong 1.4.0）を再利用。実際のツモ牌の赤牌属性を維持し、表ドラ・赤ドラ・開示済みカンドラを算入。裏ドラ、カン裏、一発、海底摸月・河底撈魚、嶺上開花、槍槓は除外。通常ロンとして評価、切り上げ満貫適用。
第2工程Bの点棒・順位スナップショットを使用し、対象家ごとに同じツモ直前点棒から独立計算。放銃者は本体打点＋300×本場を失い、和了者は同額＋既存供託を取得。供託の二重控除なし。平均順位方式で順位下降幅を求め、単独4位の下降幅は0。頭ハネは放銃者から下家、対面、上家の順で1家のみを選択。複数家の失点は合算しない。
実和了の記録差37件は第2工程AのCSVをそのまま保存。仮想評価に流用しない。
実装上の判断：既存ライブラリ再利用、専用ファイルとワークフローへの分離、ZIPでの成果物保存、差異診断は独立処理として追加。原典の変更なし。

## 3. 検証
DB取得・展開はGitHub Actions内のみ、読み取り専用。quick_check=ok、2,068試合、25,238局、56選手。
DB ZIP SHA-256 e2e702402301ae136da71e3f79113f929e291779ff4997c24db5262aaa4ff548
SQLite SHA-256 edeccd86e100f6ffba88871d7c418a06488d3f515b22cdd2e2b9dced17573e6c
承認済み第2工程A ZIP SHA-256 77a165910c731a63a52d3eda966050dddf164cd12ab0b0130979c9ce39e58a17
承認済み第2工程B ZIP SHA-256 a81dd53043b557edbccd1dcc4ab0db798a6c71db68aebbd12532272e600a2781
第2工程A・Bの実和了20,173件のID・和了者・放銃者・本体打点・本場・供託・試合・局・和了種別を照合し一致。第2工程Bの全ツモID 1,257,732件が固定DBと一致。対象ツモ27,578件のイベント識別情報、点棒・順位・本場・供託を保存後独立照合。
人工テスト10/10成功（親子打点、符・切り上げ満貫、役満、赤・表ドラ、偶発役除外、ダブルリーチ、本場供託、同点平均順位、単独4位、複数家独立計算・頭ハネ）。
第1工程確定値と再抽出件数はすべて一致：総ツモ1,257,732、基本27,578、対他家別28,060、シングル27,101、ダブル472、トリプル5。第1工程当時の全イベントID一覧は独立取得しておらず、承認済みSQLの再抽出を基準とした。
独立再計算：仮想和了打点28,060件、点棒移動と平均順位28,060件、頭ハネ27,578件、全一致。評価不能0。

## 4. 前回中断報告との照合
対他家別順位下降：前回13,228、今回13,170、差−58。
対他家別順位維持：前回14,832、今回14,890、差＋58。
頭ハネ基準順位下降：前回12,990、今回12,931、差−59。
前回値への強制補正なし。今回の全件計算は成功したが、前回との差異の正確な個別同定は未完了。

## 5. 追加差異診断
固定DBの待ち別役・翻情報と再構成結果を28,060件比較。現物牌一致27,045、正規化牌のみ一致1,015。赤牌属性を実ツモ牌に合わせ、今回の独立計算符で評価した比較では、役・翻差15件（全件ドラ）、打点差14件、順位下降区分差1件（頭ハネでも1件）。比較方式の順位下降13,169、頭ハネ12,930。
イベント順序を追加照合し、15件すべてで待ち別状態の記録時点から対象ツモまでにカンドラ表示が追加されたことを確認。例：局10715、ツモイベント1156651、対象選手ID18。待ち別状態記録1157172（順序2300069）の後、表示イベント1156229（順序2300072）で5索が開示され、対象ツモ順序2300073。6索1枚のドラ加算により本体2,000→3,900点、順位下降幅0→0.5。原典どおりツモ時点のドラを採用。
赤牌補正なしの感度診断：打点差851、順位区分差91、順位下降13,079、頭ハネ12,844。前回集計値を再現しない。
前回中断時のコードと対他家別明細が永続保存されていないため、上記診断で確認した差と旧集計との差−58・−59は同一とは断定できない。旧集計の個別原因は資料不足で未同定。第2工程Aの実和了差37件の映像確認も今回範囲外。新結果は保存・検証済み、承認前の値として扱う。

## 6. 実行・成果物
研究ブランチ https://github.com/arachan7777/mahjong-stats-lab/tree/codex/dontsuka-v026-base-20261128
計算 scripts/dontsuka_v026_3a.py
人工テスト scripts/test_dontsuka_v026_3a.py
独立照合 scripts/verify_dontsuka_v026_3a_saved.py
診断 scripts/dontsuka_v026_3a_diagnostic.py
専用Actions .github/workflows/dontsuka-v026-3a.yml、dontsuka-v026-3a-diagnostic.yml、dontsuka-v026-3a-report.yml
本実行 https://github.com/arachan7777/mahjong-stats-lab/actions/runs/46085666669
実行コミット 2e5be18959c5f35ddbfaaafb248d5e0d0192c4b7
全件成果物 https://drive.google.com/file/d/1s9I7VLoB0L3eZPdQ7llrRuvj9UYfuBhO/view
ZIP 4,301,985バイト SHA-256 da593920add867904fc82f8f51207a6fe318fa42a2945e1880c5653112fe4ce1
収録：対他家別全件CSV、頭ハネ全件CSV、評価不能明細（0件）、実牌譜事例、人工テスト結果、実行ログ、依存関係、第2工程A実和了差異CSV、Manifest。再取得ZIPのSHA一致、CRC正常、Manifest内8ファイルのハッシュ一致。
診断初回 https://github.com/arachan7777/mahjong-stats-lab/actions/runs/46086032873
保存 https://drive.google.com/file/d/1AFk02I3sImrRH-nAHzb0LitRbzTlV5gH/view
SHA-256 e25cca5ed1445f004e2931ea30c103e04e175543310a1bff27825b90688ea064
診断追加 https://github.com/arachan7777/mahjong-stats-lab/actions/runs/46086174648
保存 https://drive.google.com/file/d/14WdB_nFKWybLx5ldUinB8A3azCQkuuJx/view
SHA-256 5a79893e8e502c4d29b8fe601f62b7c2a73a4f86c110d5a51daa5853e277fec4
診断両ZIPの再取得SHA・CRC・Manifest内3/5ファイルのハッシュ一致。両実行の全件比較CSV・差異CSVはバイト単位一致。
保存先 https://drive.google.com/drive/folders/1fz4YTM84D1Q8o0VeLZ6EECtSHBMiIpIr
検証記録は research/dontsuka_v026_3a/ 内のJSONとして別途保存。

## 7. 停止判定
第3工程Aの新規実装・人工テスト・固定DB全件計算・成果物保存・保存後再取得照合は実施済み。前回未確定値との差異の正確な個別原因同定のみ旧明細・旧コード不足で留保。前回との差を隠さず、承認待ちとして停止する。第3工程B以降未着手。
