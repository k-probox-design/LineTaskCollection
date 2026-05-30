#!/usr/bin/env bash
# pc_cli の「正」(WSL リポジトリ pc_worker/) を OneDrive 配下の実行用コピー(pc_cli/)へ同期する。
#
# 設計意図:
#   - 正は常に WSL リポジトリ。OneDrive 側は Cowork サンドボックスから実行するための複製にすぎない。
#   - .env と secrets/ は同期しない（けいすけが OneDrive 側に置いた秘密値を上書き・削除しないため）。
#   - .venv / __pycache__ / テストキャッシュも除外。
#   - 揮発サンドボックスでの依存導入用に requirements.txt は同期する。
#   - 同期後に OneDrive コピーを Pinned（常にこのデバイス上に保持）へ設定する。これをしないと
#     OneDrive がファイルを「クラウドのみ（未ハイドレート）」に戻し、Cowork の Linux マウント越しに
#     中身が途中で切れて読めなくなる（2026-05-30 に実害発生）。rsync の mtime 引継ぎによる
#     キャッシュ巻き戻りも避けるため実コピーの mtime を現在時刻へ更新する。
#
# 使い方:  bash scripts/sync-pc-cli-to-onedrive.sh [--dry-run]
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../pc_worker" && pwd)/"
DEST="/mnt/c/Users/knaka/OneDrive - 株式会社ビギン/@@設計/51.LINE投稿ボット/pc_cli/"
# 上記 DEST の Windows 絶対パス（attrib.exe に渡す。末尾 \ は付けない）
WIN_PCCLI='C:\Users\knaka\OneDrive - 株式会社ビギン\@@設計\51.LINE投稿ボット\pc_cli'

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

if [[ ${#DRY[@]} -gt 0 ]]; then
  echo "[sync] DRY RUN のため mtime 更新・ピン留め・検証はスキップ"
  exit 0
fi

# (1) 実コピーの mtime を現在時刻へ更新（rsync -t が引き継ぐ古い mtime によるキャッシュ巻き戻りを防ぐ）
#     secrets/ など同期対象外は触らない。
find "$DEST" -path "${DEST}secrets" -prune -o \
            -path "${DEST}pc_worker_tmp" -prune -o \
            -path "${DEST}pc_worker_logs" -prune -o \
            -print -exec touch {} + >/dev/null 2>&1 || true

# (2) OneDrive ピン留め: FILE_ATTRIBUTE_PINNED(+P) を立て、Free-up-space(-U) を外す。再帰(/S)・ディレクトリも(/D)。
#     これで OneDrive が実体をローカルに保持し続け、Cowork マウントから常に完全な中身が読める。
echo "[sync] OneDrive にピン留め中（attrib +P -U）..."
if cmd.exe /c "attrib +P -U \"${WIN_PCCLI}\\*\" /S /D" >/dev/null 2>&1; then
  echo "[sync] ピン留め完了"
else
  echo "[sync] WARN: attrib によるピン留めに失敗（cmd.exe interop 不可？）。手動で「常にこのデバイス上に保持」を設定してください" >&2
fi

# (3) 軽い検証: 代表ファイルの WSL 正サイズと OneDrive 実コピーサイズが一致するか（未ハイドレート検出）
check_rel="app/notion_writer.py"
if [[ -f "${SRC}${check_rel}" && -f "${DEST}${check_rel}" ]]; then
  src_size=$(stat -c%s "${SRC}${check_rel}")
  dst_size=$(stat -c%s "${DEST}${check_rel}")
  if [[ "$src_size" == "$dst_size" ]]; then
    echo "[sync] 検証 OK: ${check_rel} は完全サイズ ${dst_size} バイト（未ハイドレート無し）"
  else
    echo "[sync] WARN: ${check_rel} のサイズ不一致（正=${src_size} / コピー=${dst_size}）。未ハイドレートか同期途中の可能性" >&2
  fi
fi

echo "[sync] 初回は ${DEST}.env.sandbox.example を .env にコピーして NOTION_API_KEY を記入、secrets/ に SA 鍵を配置してください"
