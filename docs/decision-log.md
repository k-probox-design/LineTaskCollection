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
