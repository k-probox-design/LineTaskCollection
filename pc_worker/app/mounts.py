"""実行時マウント解決。

Cowork サンドボックスでは Windows フォルダが `/sessions/<動的セッション名>/mnt/<フォルダ名>/`
にマウントされ、`<動的セッション名>` は実行ごとに変わる。WSL では同じフォルダが
`/mnt/c/...` に見える。pc_cli はどちらでも動く必要があるため、利用者は **静的な Windows
絶対パス**を `.env` の `MOUNT_MAP` に列挙し、本モジュールが実行時に「実際のマウント先 unix
パス」を解決して (unix 接頭辞 ↔ windows 接頭辞) の写像を組み立てる。

これにより Skill 側はセッション毎にパスを注入する必要がない（動的解決の責務は pc_cli 側）。
"""

import logging
import os
import re
from pathlib import Path

from app import winpath

logger = logging.getLogger("mounts")

# pc_cli 自身が `/sessions/<dyn>/mnt/...` 配下から動いているかを見て、現在のセッションの
# マウントベースを特定するための正規表現。glob 探索より確実（複数セッションが残存しても誤らない）。
_SESSION_MNT = re.compile(r"^(/sessions/[^/]+/mnt)/")

# MOUNT_MAP のエントリ区切り。Windows パスに ; は出ないため安全。
_ENTRY_SEP = ";"


def _windows_basename(win_path: str) -> str:
    return win_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _session_mount_base(self_path: str) -> str | None:
    """自分自身（このファイル）の位置から現在のサンドボックスセッションの mnt ベースを得る。"""
    m = _SESSION_MNT.match(self_path.replace("\\", "/"))
    return m.group(1) if m else None


def parse_mount_map(raw: str) -> list[str]:
    """`MOUNT_MAP` 文字列を Windows 絶対パスのリストに分解する。"""
    return [p.strip() for p in raw.split(_ENTRY_SEP) if p.strip()]


def _resolve_unix_for(win_path: str, session_base: str | None) -> str | None:
    """1 つの Windows ルートに対応する実マウント unix パスを解決する。

    優先順位: ①現在セッションの mnt 配下 → ②WSL の /mnt/<drive> → ③他セッションの glob。
    どこにも実在しなければ None（呼び出し側で写像から除外）。
    """
    name = _windows_basename(win_path)

    if session_base:
        cand = Path(session_base) / name
        if cand.is_dir():
            return str(cand)

    wsl_path = winpath.windows_to_unix(win_path)
    if wsl_path != win_path and Path(wsl_path).is_dir():
        return wsl_path

    for cand in sorted(Path("/sessions").glob(f"*/mnt/{name}")):
        if cand.is_dir():
            return str(cand)

    return None


def discover_maps(raw_mount_map: str, self_path: str | None = None) -> list[winpath.PathMap]:
    """MOUNT_MAP から (unix 接頭辞, windows 接頭辞) の写像リストを実行時に構築する。

    実在を確認できたマウントのみ採用する。未解決のエントリは WARN を出してスキップ
    （写像が無くても /mnt 規則のフォールバックで WSL 実行は動くため処理は止めない）。
    """
    self_path = self_path if self_path is not None else str(Path(__file__).resolve())
    session_base = _session_mount_base(self_path)

    maps: list[winpath.PathMap] = []
    for win_path in parse_mount_map(raw_mount_map):
        unix_path = _resolve_unix_for(win_path, session_base)
        if unix_path is None:
            logger.warning("[MOUNT] 実マウント先を解決できません（スキップ）: %s", win_path)
            continue
        maps.append((unix_path, win_path))
        logger.info("[MOUNT] %s ⇔ %s", unix_path, win_path)
    return maps


def resolve_to_unix(path: str, maps: list[winpath.PathMap]) -> str:
    """入力が Windows 絶対パスなら写像で unix に解決、そうでなければそのまま返す。

    .env の SHAREPOINT_ROOT / TMP_DOWNLOAD_DIR / LOG_OUTPUT_DIR /
    GOOGLE_APPLICATION_CREDENTIALS を「Windows パスでも unix パスでも書ける」ようにするため、
    アクセス時にこれを通す。
    """
    if not path:
        return path
    if re.match(r"^[A-Za-z]:[\\/]", path):
        return winpath.windows_to_unix(path, maps)
    return path
