# 環境構築ログ

## 2026-05-27 — Phase A 初期セットアップ

- リポジトリ: `https://github.com/k-probox-design/LineTaskCollection`（private）
- WSL2 / Ubuntu 24.04、Python 3.12.3
- `python3.12-venv` パッケージを `apt install` で追加（Ubuntu 24.04 デフォルトでは未インストール）
- `server/` 配下に FastAPI 最小構成を配置
- 依存: fastapi, uvicorn, line-bot-sdk v3, httpx, python-dotenv
- テストフレームワーク: pytest + pytest-asyncio
- hatchling ビルドで `[tool.hatch.build.targets.wheel] packages = ["app"]` が必要だった（ディレクトリ名がプロジェクト名と一致しないため）
- `pip install -e ".[dev]"` で editable install 成功
- pytest 2/2 パス（署名検証の正常系・異常系）

## 2026-05-28 — Phase B GCS/Firestore 統合

- line-bot-sdk を依存から除外、google-cloud-firestore / google-cloud-storage を追加
- BackgroundTasks で Webhook 即 200 + 後段処理分離
- gcs.py / firestore.py を新設、config.py に GCS_BUCKET / FIRESTORE_PROJECT / LOCAL_FALLBACK を追加
- Dockerfile (python:3.11-slim) + cloudrun-deploy.sh を作成
- pytest 9/9 パス（署名検証 2 + process_event 4 + gcs 1 + firestore 2）

## 2026-05-28 — Cloud Run デプロイ + Phase B 残課題対応

- WSL2 に gcloud 未インストールだったため Google Cloud SDK 570.0.0 をホームディレクトリに導入
- 1 回目デプロイ失敗: 非 root コンテナで import 時の `/app/tmp` mkdir が PermissionError → 遅延作成に修正
- Service URL: `https://linetask-receive-538691653180.asia-northeast1.run.app`
- 残課題対応: min-instances=1 + cpu-boost、python-json-logger による structured logging（4.1.0、v3+ の import パス）、ADC 手順を operations.md に追記
- pytest 10/10 パス

## 2026-05-28 — Phase C PC 側仕分け処理

- `pc_worker/` を独立 Python パッケージとして新設（`server/` とは依存を共有しない）
- 依存: anthropic 0.104.1, notion-client 3.1.0, google-cloud-storage/firestore, python-dotenv, python-json-logger
- モジュール: config / pull / classify / notion_writer / log_writer / sharepoint_writer / orchestrator / main
- 仕分けは `claude-sonnet-4-6` + `messages.parse`（構造化出力）+ プロンプトキャッシュ
- pytest 15/15 パス（外部 API 全モック）
