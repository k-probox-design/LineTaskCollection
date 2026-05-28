# pc_worker — PC 側仕分け処理

LINE で受信し GCS/Firestore にバッファされた資料を pull し、Claude で案件に仕分けて
Notion「設計タスク管理」DB に登録、確信があれば SharePoint(OneDrive 同期フォルダ)へ格納する。

常駐させず、手動 or タスクスケジューラで起動 → バッチ 1 回実行 → 終了するシンプル設計。

## 依存インストール

```bash
cd pc_worker
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## 設定

```bash
cp .env.example .env
# ANTHROPIC_API_KEY / NOTION_API_KEY / NOTION_DATABASE_ID_DESIGN_TASK /
# SHAREPOINT_ROOT を入力。GCP は ADC(gcloud auth application-default login)で解決
```

セットアップ手順の詳細は `docs/operations.md` の Phase C セクションを参照。

## 起動

```bash
python -m app.main
```

1 回実行して未処理(Firestore `status=pending`)を全件さばいて終了する。

## テスト

```bash
pytest tests/ -v
```

外部 API(GCS / Firestore / Notion / Anthropic)は全てモックする。
