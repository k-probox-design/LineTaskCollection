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
