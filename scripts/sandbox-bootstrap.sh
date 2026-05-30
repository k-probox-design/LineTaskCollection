#!/usr/bin/env bash
# Cowork サンドボックスのスケジュール実行で pc_cli を「完全に読める」状態に用意する。
#
# 背景（2026-05-30 実測）: OneDrive Files-On-Demand のプレースホルダは、サンドボックスの
# Linux マウント越しに中身が途中で切れて返る（`notion_writer.py` が 5395B で頭打ち→AST 失敗）。
# `attrib +P`(Pinned) は「evict しない」フラグであって実体バイトのハイドレートを保証せず、
# Windows 側 Read は完全でもマウント実体は古いまま。WSL 側のどの対策でも安定解消しなかった。
#
# 恒久対策（A 案）: コードは GitHub private repo から git clone してサンドボックスのネイティブ
# fs（/tmp）上で実行する。OneDrive からは「小サイズで完全に読める」.env と SA 鍵だけを使う。
# これでコードのハイドレート依存を断つ。検証も「Cowork が実際に読むバイト列」で AST parse する。
#
# clone 先は必ずネイティブ fs。OneDrive マウント（/sessions/<sess>/mnt/...）や /outputs 直下は
# git の内部操作（.git/config.lock の unlink 等）に対応しない／書込不可で clone が失敗する（2026-05-30 実測）。
#
# clone 先は実行ごとにユニーク（mktemp）。スケジュール実行は前回と別のサンドボックスユーザーで
# 走るため、固定パスだと前回分を rm -rf できず（所有者違い→Permission denied）に詰まる。
#
# ★ 出力契約: 人間向けログはすべて stderr。stdout は **最終 1 行のみ** で `PCWORKER=<絶対パス>`。
#   呼び出し側（Skill）はこれを拾って後続の cd / PYTHONPATH に使う:
#     PCWORKER=$(bash sandbox-bootstrap.sh | sed -n 's/^PCWORKER=//p' | tail -1)
#   後片付け（自分が作った dir の削除）は **呼び出し側の責務**。本スクリプトは clone を消さない
#   （別プロセスで起動されるため、ここで trap EXIT 削除すると Skill が使う前に消えてしまう）。
#
# 前提環境変数:
#   GITHUB_PAT   private repo の Contents:Read 権限 fine-grained PAT
#                （未設定なら OneDrive の pc_cli/.env の GITHUB_PAT= から読む）
#   REPO_REF     clone する ref。既定 main（main マージ前のテストは work ブランチ名を指定）
#   WORK_DIR     clone 先（ネイティブ fs 必須）。未指定なら mktemp -d /tmp/linetask.XXXXXX を新規作成
#
# OneDrive の pc_cli マウントは /sessions/*/mnt/51.LINE投稿ボット/pc_cli を自動検出。
set -euo pipefail

REPO="k-probox-design/LineTaskCollection"
REPO_REF="${REPO_REF:-main}"

ONEDRIVE_PCCLI="$(ls -d /sessions/*/mnt/51.LINE投稿ボット/pc_cli 2>/dev/null | head -1 || true)"
if [[ -z "$ONEDRIVE_PCCLI" ]]; then
  echo "[bootstrap] ERROR: OneDrive の pc_cli マウントが見つかりません（/sessions/*/mnt/51.LINE投稿ボット/pc_cli）" >&2
  exit 1
fi

# PAT は環境変数優先、無ければ OneDrive の .env（小サイズ＝マウントで完全に読める）から取得
if [[ -z "${GITHUB_PAT:-}" && -f "$ONEDRIVE_PCCLI/.env" ]]; then
  GITHUB_PAT="$(grep -E '^GITHUB_PAT=' "$ONEDRIVE_PCCLI/.env" | head -1 | cut -d= -f2- | tr -d '\r')"
fi
if [[ -z "${GITHUB_PAT:-}" ]]; then
  echo "[bootstrap] ERROR: GITHUB_PAT 未設定（OneDrive の pc_cli/.env に GITHUB_PAT=... を記載）" >&2
  exit 1
fi

command -v git >/dev/null || { echo "[bootstrap] ERROR: git が見つかりません" >&2; exit 1; }

# 前回までの残骸を best-effort 掃除（自分が消せるもの＝1時間以上前のものだけ。他ユーザー所有は黙ってスキップ）
for d in /tmp/linetask.*; do
  [[ -d "$d" ]] || continue
  if [[ -n "$(find "$d" -maxdepth 0 -mmin +60 2>/dev/null)" ]]; then
    rm -rf "$d" 2>/dev/null || true
  fi
done

# clone 先: 指定が無ければ実行ごとユニークな新規 dir（mktemp が空 dir を作る）
if [[ -n "${WORK_DIR:-}" ]]; then
  mkdir -p "$WORK_DIR"
else
  WORK_DIR="$(mktemp -d /tmp/linetask.XXXXXX)"
fi

# トークンは clone URL に一度だけ使い、直後に remote から除去する（WORK_DIR は揮発だが保険）
git clone --depth 1 --branch "$REPO_REF" \
  "https://oauth2:${GITHUB_PAT}@github.com/${REPO}.git" "$WORK_DIR" 1>&2
git -C "$WORK_DIR" remote set-url origin "https://github.com/${REPO}.git"

PCW="$WORK_DIR/pc_worker"
# .env は OneDrive 側（けいすけ記入済み・小サイズで完全に読める）をコピー。
# GOOGLE_APPLICATION_CREDENTIALS は Windows パス→実行時に MOUNT_MAP の glob で実マウントへ解決。
cp "$ONEDRIVE_PCCLI/.env" "$PCW/.env"

cd "$PCW"
pip install -r requirements.txt --break-system-packages -q >&2

# 検証: Windows 側 size ではなく「サンドボックスが実際に読むバイト列」で全 app/*.py を AST parse
python3 - >&2 <<'PY'
import ast, glob, sys
files = sorted(glob.glob("app/*.py"))
bad = []
for f in files:
    try:
        ast.parse(open(f, encoding="utf-8").read())
    except Exception as e:
        bad.append((f, repr(e)))
if bad:
    sys.stderr.write("[bootstrap] AST FAIL: %s\n" % bad)
    sys.exit(1)
print(f"[bootstrap] AST OK: {len(files)} files (git clone なのでハイドレート無関係)", file=sys.stderr)
PY

echo "[bootstrap] ready: $PCW (ref=$REPO_REF)" >&2
echo "[bootstrap] 後片付けは呼び出し側で: rm -rf $WORK_DIR" >&2
# stdout は機械可読の 1 行のみ（呼び出し側が cd / PYTHONPATH に使う）
echo "PCWORKER=$PCW"
