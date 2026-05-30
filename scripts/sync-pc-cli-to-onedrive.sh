#!/usr/bin/env bash
# pc_cli の「正」(WSL リポジトリ pc_worker/) を OneDrive 配下の実行用コピー(pc_cli/)へ同期する。
#
# 設計意図:
#   - 正は常に WSL リポジトリ。OneDrive 側は Cowork サンドボックスから実行するための複製にすぎない。
#   - .env と secrets/ は同期しない（けいすけが OneDrive 側に置いた秘密値を上書き・削除しないため）。
#   - .venv / __pycache__ / テストキャッシュも除外。
#   - 揮発サンドボックスでの依存導入用に requirements.txt は同期する。
#
# 使い方:  bash scripts/sync-pc-cli-to-onedrive.sh [--dry-run]
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../pc_worker" && pwd)/"
DEST="/mnt/c/Users/knaka/OneDrive - 株式会社ビギン/@@設計/51.LINE投稿ボット/pc_cli/"

DRY=()
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY=(--dry-run)
  echo "[sync] DRY RUN"
fi

if [[ ! -d "$(dirname "$DEST")" ]]; then
  echo "[sync] ERROR: OneDrive の親フォルダが見つかりません: $(dirname "$DEST")" >&2
  echo "[sync] Cowork に 51.LINE投稿ボット がマウント/同期されているか確認してください" >&2
  exit 1
fi

mkdir -p "$DEST"
# サンドボックスが書き込む先（鍵置き場・DL先・ログ先）。空ディレクトリを用意しておく。
mkdir -p "${DEST}secrets" "${DEST}pc_worker_tmp" "${DEST}pc_worker_logs"

rsync -av --delete "${DRY[@]}" \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude 'secrets/' \
  --exclude 'pc_worker_tmp/' \
  --exclude 'pc_worker_logs/' \
  "$SRC" "$DEST"

echo "[sync] done -> $DEST"
echo "[sync] 初回は ${DEST}.env.sandbox.example を .env にコピーして NOTION_API_KEY を記入、secrets/ に SA 鍵を配置してください"
