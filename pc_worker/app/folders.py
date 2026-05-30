import logging
from datetime import datetime, timezone
from pathlib import Path

from app import winpath
from app.config import settings
from app.sharepoint_writer import LINE_SUBFOLDER

logger = logging.getLogger("folders")


def _count_child_dirs(path: Path) -> int:
    count = 0
    try:
        for child in path.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                count += 1
    except OSError:
        return 0
    return count


def _mtime_iso(path: Path) -> str:
    ts = path.stat().st_mtime
    # ローカルタイムゾーン付き ISO8601（システム tz を反映）
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat()


def list_case_folders(root: str | None = None, max_depth: int = 3, query: str | None = None) -> list[dict]:
    """SHAREPOINT_ROOT 配下を再帰スキャンし、案件フォルダ候補のメタを返す。

    深さ制御のため iterdir() を再帰呼び出しする。ディレクトリのみ・隠し(.始まり)除外・root 自体は含めない。
    query を渡すと、不揃いな深さ（ブランチごとに depth2〜4）を跨いで「名前に query を含む」フォルダだけ返す。
    全件は depth3 で約 6700 件と多いので、案件名が分かっているときは query で絞るのが安定（bug2 対策）。
    """
    base = Path(root or settings.sharepoint_root)
    if not base.is_dir():
        raise FileNotFoundError(f"root not found: {base}")

    # マウント写像は filesystem 探索を伴うため、ディレクトリ毎ではなく 1 回だけ解決して使い回す
    maps = settings.path_maps
    query_norm = query.casefold() if query else None
    results: list[dict] = []

    def walk(path: Path, depth: int, parent_name: str | None) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(path.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            # query 指定時は名前マッチのみ採用（マッチしないフォルダも子に案件があり得るので走査は続ける）
            if query_norm is None or query_norm in child.name.casefold():
                unix = str(child)
                results.append({
                    "folder_name": child.name,
                    "parent_folder_name": parent_name,
                    "depth": depth,
                    "absolute_path_unix": unix,
                    "absolute_path_windows": winpath.unix_to_windows(unix, maps),
                    "child_dir_count": _count_child_dirs(child),
                    "has_line_yaritori_folder": (child / LINE_SUBFOLDER).is_dir(),
                    "last_modified": _mtime_iso(child),
                })
            walk(child, depth + 1, child.name)

    walk(base, 1, None)
    logger.info(
        "[FOLDERS] list_case_folders found %d dirs under %s (max_depth=%d, query=%s)",
        len(results), base, max_depth, query,
    )
    return results
