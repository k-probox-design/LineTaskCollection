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
