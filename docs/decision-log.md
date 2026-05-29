# 決定ログ

## 2026-05-27 — Phase A 技術判断

### line-bot-sdk v3 を採用（v4 ではなく）

v3 系は安定リリースで広く利用されている。Phase A では署名検証にのみ使用するが、将来の拡張性を考慮して SDK を依存に含めた。ただし Phase A の Webhook 処理は SDK のハンドラ機構を使わず、自前で `X-Line-Signature` を検証している（SDK の `WebhookParser` は同期的で FastAPI の async と相性が悪いため）。

### コンテンツダウンロードに httpx を使用（line-bot-sdk 内蔵メソッドではなく）

line-bot-sdk v3 の `LineBotApi.get_message_content()` は同期 I/O。FastAPI の async エンドポイント内で `httpx.AsyncClient` を使い非同期ダウンロードする方が自然。Phase B で GCS ストリーミングアップロードに切り替える際もこの方が拡張しやすい。

### Phase A では Webhook を同期処理

画像 1 枚なら数秒以内で完了する想定。5 秒を超えるケース（大きい動画など）が出た場合は Phase B で BackgroundTasks に分離する。

## 2026-05-28 — Phase B 判断（Cowork 確定、CLAUDE.md に永続決定として記載済み）

### Firestore / GCS Emulator は使わず本番直書き

Emulator の学習コストが見合わない。Phase A〜B は本番 1 プロジェクト方針と整合し、小規模なら無料枠内で収まる。

### テキストメッセージも Firestore に保存

受信ログ＝検索アーカイブの方針と整合。テキストも過去検索で使う価値がある。ファイル本体は保存せず、メタ＋ text フィールドのみ。

### BackgroundTasks でコンテンツダウンロードを分離

Cloud Run のタイムアウト＋ LINE Webhook の即 200 要件。画像複数枚や動画で Webhook 応答が遅れるリスクを排除。FastAPI の `BackgroundTasks` を使用。

### line-bot-sdk-python を依存から外す

Phase A で SDK を入れていたが未使用。自前検証＋httpx が async と相性がよく、Phase B でも継続。未使用依存を残さない方針。

### コンテンツダウンロードを同期 httpx.Client に変更

BackgroundTasks はスレッドプールで実行されるため、async I/O を使う意味が薄い。`httpx.Client`（同期）でシンプルに。GCS の `upload_from_string` も同期 API のため統一。

## 2026-05-28 — Phase B 残課題対応

### Cloud Run min-instances=1 + Startup CPU Boost を採用

min-instances=0 だと cold start で初回 Webhook がタイムアウトし、LINE 取りこぼしのリスク（実際に Webhook 検証 1 回目失敗を観測）。業務用ボットの取りこぼし回避のため min-instances=1 で常駐。月額 ¥1,000〜2,000 の上振れは許容（Cowork 判断）。CPU Boost は無料で再起動時の起動短縮にも効く二重対策。

### structured logging は案 A（python-json-logger で stdout に JSON）を採用

`gcloud run services logs read` のデフォルト出力にアプリ層 `logger.info` が出ない問題への対応。案 B（google-cloud-logging ハンドラで直接 API 送信）は起動時 Auth 解決や例外時の挙動に注意が要り、Phase B 軽量化方針に合わない。案 A は stdout に JSON を吐くだけで Cloud Logging が jsonPayload として解釈し、追加の認証・ネットワーク依存がない。`levelname` を `severity` にリネームして重大度も認識させる。

## 2026-05-28 — Phase C 技術判断

### 案件名 → SharePoint フォルダのマッピングは (a)「案件名 = フォルダ名」を採用

kickoff の選択肢 (a)/(b) のうち (a) を初期採用。`SHAREPOINT_ROOT/<案件名>/09.受領資料/` のように案件名をそのままフォルダ名に使う。設計事務所の業務実態として案件名と SharePoint フォルダ名は一致しているのが通例で、(b)（Notion の OneDrive URL フィールド参照）より実装がシンプル。運用で不整合が出たら (b) に切り替える。

### 仕分け判断は Claude Sonnet 4.6 + 構造化出力（messages.parse）

kickoff 指定どおり `claude-sonnet-4-6` を採用（マルチモーダルで画像/PDF を読む必要がある）。出力は `client.messages.parse(output_format=ClassifyResult)` で Pydantic 検証付きの構造化 JSON を取得。プロンプトキャッシュはシステムプロンプト+案件候補リスト（1 run 内で不変）に `cache_control` を付与。thinking は分類タスクのため disabled でコスト・レイテンシを抑える。

### 確信度しきい値の判定は orchestrator 側に集約

classify はモデルの生出力（case_name と confidence）をそのまま返し、しきい値（0.8）による分岐は orchestrator が一元的に行う。classify を純粋な「Claude 呼び出し」に保ち、テストとロジックを分離するため。

### 議事ログのファイル名と個別ファイル名の厳密な相互リンクは Phase C 後の精緻化とする

議事ログ Markdown 内のファイル参照は受信時の元ファイル名（`fileName`）で `../09.受領資料/<元ファイル名>` を指す。個別ファイルは `YYYY-MM-DD <Claude推測タイトル>.<ext>` で保存されるため、現状リンクは厳密一致しない。両者を完全一致させるには分類結果のタイトルを log_writer に渡す必要があり、複雑化を避けて Phase C 後に精緻化する。

### コンテンツダウンロードと Notion OneDrive リンク

PC 側スクリプトは同期 SDK（google-cloud-storage / firestore / notion-client / anthropic 同期クライアント）で実装。Notion の OneDrive フィールドには SharePoint URL ではなくローカルパスの `file://` URL を入れる（kickoff §注意事項のとおり、OneDrive 同期に任せ SharePoint API での URL 取得は避ける方針）。けいすけが Notion から開いたとき同期済みなら参照できる。

## 2026-05-29 — Phase C 実行環境を WSL 一本化（A 方針）、Cowork 監査はログ複製で代替

pc_worker の実行環境を **WSL2 リポジトリ内に一本化**（A 方針）。OneDrive 配下へ一式コピーして Windows Python で動かす B-2 案は不採用。

- 理由: WSL リポジトリと OneDrive コピーの二重管理が運用負債になる（更新の都度コピーを忘れるとバージョン乖離）
- `.env` も WSL 側のみ。SharePoint 書き込みは WSL から `/mnt/c/.../OneDrive/...` 経由で同期に委ねる
- A 方針では Cowork がコード・`.env`・実行コンソールに直接アクセスできないため、監査経路を 2 点で代替:
  1. `pc_worker/.env.example` を受け渡しフォルダ（`Coworkとの受け渡し/`）に複製し、Cowork が必要項目を把握できるようにする（実値は共有しない）
  2. `config.add_file_handler(run_id)` で実行ログを `$LOG_OUTPUT_DIR/YYYY-MM-DD/<run_id>.jsonl`（OneDrive 配下）に JSON Lines で複製出力。`LOG_OUTPUT_DIR` 未設定・書込不可時は WARN を出してコンソールのみで継続（ログ複製のために本処理を止めない）

これにより CLAUDE.md §永続決定事項 Phase C 実装方針の項目 17/18（Cowork 許可フォルダへコピー配置）は本決定で上書きされる。

## 2026-05-29 — Phase C を Cowork 主導仕分けに転換（Phase C'）

Phase C 実地確認の手前で、仕分け判断を **Cowork（Opus）が担う構成**に転換。pc_worker（判定ロジック内蔵）を、判定を持たない薄い CLI ラッパー **pc_cli** に再構築した。

### 転換理由（5 つ）

1. **コスト**: API 案 月 ¥1,000〜3,000 → Cowork 案 ¥0（Claude Max 20x サブスク内で完結、`ANTHROPIC_API_KEY` 不要）
2. **精度**: claude-sonnet-4-6（API）→ claude-opus-4-7（Cowork）の上位モデル
3. **運用品質**: 確信度低のものをけいすけにその場で対話確認できる（API 案の needs_review は溜まる一方）
4. **Phase D 連続性**: アーカイブ検索ヘルパーも Cowork なので仕分け・記録・検索が同一プロセスで完結
5. **鍵管理の簡素化**: `ANTHROPIC_API_KEY` が不要に

### Cowork 案 vs API 案

| 観点 | API 案（Phase C） | Cowork 案（Phase C'）|
|------|------------------|---------------------|
| コスト | 月 ¥1,000〜3,000 | ¥0（サブスク内）|
| 判定モデル | claude-sonnet-4-6 | claude-opus-4-7 |
| 即時性 | バッチ 1 回実行 | スケジュール 4 回/日（朝昼夕夜）。数時間以内反映で十分 |
| 確信度低の扱い | needs_review に溜まる | その場でけいすけに対話確認 |
| 運用負担 | スクリプト保守 | Cowork Skill + pc_cli |

投稿想定（けいすけヒアリング 2026-05-29）: ファイル 1 日 50 件未満 / テキスト多め（タスク化要あり）/ 即時性は数時間以内で十分。

### 旧実装の流用・廃止判定

| ファイル | 判定 |
|---|---|
| config.py | 流用（判定系変数 ANTHROPIC_API_KEY/CLASSIFY_*/LOG_AGGREGATION_HOURS/CANDIDATE_LOOKBACK_DAYS 削除、TMP_DOWNLOAD_DIR 追加、ログを stderr 化）|
| pull.py | 流用 → CLI 化（list_pending / download / mark_done / mark_review）|
| notion_writer.py | 流用 → CLI 化（list_cases / write_task / update_task、3 req/sec スロットル維持）|
| sharepoint_writer.py | 流用 → CLI 化（place-file、overwrite 追加、パストラバーサル対策維持）|
| log_writer.py | 流用（build_session_log は参照用に残置、write-log は Cowork 提供 content を書く）|
| classify.py | **削除**（Cowork が直接マルチモーダル判定）|
| orchestrator.py | **削除**（Cowork が pc_cli を順序立てて呼ぶ）|
| main.py | **削除** → cli.py に置換 |
| cli.py / winpath.py | **新規**（Typer 9 サブコマンド / unix↔windows パス変換）|

旧 classify のシステムプロンプト・orchestrator の確信度分岐フローは `docs/cowork-skill-reference.md` に退避（Cowork Skill 移植用）。

### pc_cli の出力契約

stdout=結果 JSON のみ、ログ=stderr（+ LOG_OUTPUT_DIR ファイル）。Cowork が stdout の JSON だけをパースできるよう、Phase B/C ではコンソールログを stdout に出していたのを **stderr に変更**。
