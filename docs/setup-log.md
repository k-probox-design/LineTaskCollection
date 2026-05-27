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
