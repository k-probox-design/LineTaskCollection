import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app import winpath
from app.config import settings
from app.sharepoint_writer import LINE_SUBFOLDER

logger = logging.getLogger("folders")

# `09.受領資料` / `00.HESTA_..._様` のような「2桁数字＋ドット」始まりの名前は、けいすけの実構造では
# 必ず葉（案件フォルダ本体 or その配下の番号付き定番サブフォルダ）であり、その下に別案件は無い。
# 一方、中間バケツ(`2025年作成`)やブランチ(`@@関電_Kenes`)はこのパターンに一致しない。
# よってこのパターンの配下へは降りない＝深い番号付きサブフォルダ群（depth3 で約6700件の主因）を
# 走査せず、OneDrive オンデマンドの stat ハイドレートを激減させる（A-2 性能対策）。
_LEAF_RE = re.compile(r"^\d{2}\.")


def _scandir(path: str):
    """path 直下の「隠しでない」DirEntry を名前順で返す（dir 判定はまだしない）。失敗時は空。"""
    try:
        entries = [e for e in os.scandir(path) if not e.name.startswith(".")]
    except OSError:
        return []
    entries.sort(key=lambda e: e.name)
    return entries


def _is_dir(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def _meta(entry: os.DirEntry, depth: int, parent_name: str | None, maps) -> dict:
    """マッチした案件フォルダ候補の詳細メタを組み立てる（重い IO はマッチ分だけに限定）。"""
    child_dir_count = 0
    has_line = False
    try:
        for c in os.scandir(entry.path):
            if c.name.startswith("."):
                continue
            if c.is_dir(follow_symlinks=False):
                child_dir_count += 1
                if c.name == LINE_SUBFOLDER:
                    has_line = True
    except OSError:
        pass

    try:
        ts = entry.stat(follow_symlinks=False).st_mtime
        last_modified = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat()
    except OSError:
        last_modified = None

    unix = entry.path
    return {
        "folder_name": entry.name,
        "parent_folder_name": parent_name,
        "depth": depth,
        "absolute_path_unix": unix,
        "absolute_path_windows": winpath.unix_to_windows(unix, maps),
        "child_dir_count": child_dir_count,
        "has_line_yaritori_folder": has_line,
        "last_modified": last_modified,
    }


def list_case_folders(root: str | None = None, max_depth: int = 3, query: str | None = None) -> list[dict]:
    """SHAREPOINT_ROOT 配下を再帰スキャンし、案件フォルダ候補のメタを返す。

    ディレクトリのみ・隠し(.始まり)除外・root 自体は含めない。query を渡すと、不揃いな深さ
    （ブランチごとに depth2〜4）を跨いで「名前に query を含む」フォルダだけ返す。
    `^\\d{2}\\.` 始まりのフォルダ（案件本体や `09.受領資料` 等）は葉として扱い、その配下へは降りない
    （深い番号付きサブフォルダ群を走査せず高速化。bug2 性能対策）。重いメタはマッチ分のみ計算する。
    """
    base = root or settings.sharepoint_root
    if not os.path.isdir(base):
        raise FileNotFoundError(f"root not found: {base}")

    # マウント写像は filesystem 探索を伴うため、ディレクトリ毎ではなく 1 回だけ解決して使い回す
    maps = settings.path_maps
    query_norm = query.casefold() if query else None
    results: list[dict] = []

    def walk(path: str, depth: int, parent_name: str | None) -> None:
        if depth > max_depth:
            return
        for entry in _scandir(path):
            name = entry.name
            name_matches = query_norm is None or query_norm in name.casefold()
            is_leaf = bool(_LEAF_RE.match(name))
            # 名前がマッチしない番号付き葉（案件が無い・走査不要）は dir 判定の stat すら省く。
            # query 時はブランチ配下の大量の `00.X` 案件をここで触らず捨てられるのが効く（A-2 性能対策）。
            if not name_matches and is_leaf:
                continue
            # 記録は dir のときだけ（ここで初めて stat する）
            if name_matches and _is_dir(entry):
                results.append(_meta(entry, depth, parent_name, maps))
            # 葉パターンの配下には別案件は無いので降りない。非葉のみ dir 確認して再帰。
            if not is_leaf and _is_dir(entry):
                walk(entry.path, depth + 1, name)

    walk(str(base), 1, None)
    logger.info(
        "[FOLDERS] list_case_folders found %d dirs under %s (max_depth=%d, query=%s)",
        len(results), base, max_depth, query,
    )
    return results
