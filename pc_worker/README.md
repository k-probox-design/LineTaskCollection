# pc_worker — pc_cli（仕分け実行の薄い CLI）

LINE で受信し GCS/Firestore にバッファされた資料を pull し、Cowork（Opus）の仕分け判断を受けて
Notion「設計タスク管理」DB に登録、案件フォルダ（OneDrive 同期）へ格納するための薄い API ラッパー。
仕分け判断そのものは Cowork（Skill）側が担い、pc_cli は判定ロジックを持たない（Phase C'）。

`python -m app.cli <subcommand>`: pull-pending / download / list-cases / write-task / update-task /
list-case-folders / place-file / write-log / mark-done / mark-review の 10 サブコマンド。
stdout=結果 JSON、stderr=ログ。

## 実行拠点と前提

| 拠点 | Python | パス形式 | GCP 認証 |
|------|--------|---------|---------|
| WSL ローカル開発 | 3.12 等 | `/mnt/c/...`（unix）でも Windows 形でも可 | ADC 推奨 |
| Cowork サンドボックス本番 | 3.10 | **Windows 絶対形**（動的マウントを実行時解決） | SA 鍵ファイル |

`SHAREPOINT_ROOT` 等のパスを Windows 絶対形で書くと、pc_cli が実行時に実マウント先
（WSL は `/mnt/c`、サンドボックスは `/sessions/<動的>/mnt`）へ解決する。仕組みは
`docs/cowork-skill-reference.md` の「マウント解決と winpath 一般化」を参照。

## 依存インストール

WSL 開発:

```bash
cd pc_worker
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Cowork サンドボックス（揮発するので起動毎に実行）:

```bash
pip install -r requirements.txt --break-system-packages
```

## 設定

```bash
cp .env.example .env          # WSL 開発用
# サンドボックスは .env.sandbox.example（既知値記入済み）を .env にコピーし、
# NOTION_API_KEY と secrets/ への SA 鍵配置の 2 点だけ行う
```

## OneDrive 実行コピーへの同期

正は WSL リポジトリ。Cowork から実行するための複製を OneDrive に置く:

```bash
bash scripts/sync-pc-cli-to-onedrive.sh        # --dry-run で確認可
```

`.env` と `secrets/` は同期しない（けいすけが置いた秘密値を保護）。

## テスト

```bash
pytest tests/ -v
```

外部 API(GCS / Firestore / Notion)とファイルシステムは全てモック / tmp で行う。
