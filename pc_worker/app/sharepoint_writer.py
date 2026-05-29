import logging
import re
from pathlib import Path

from app.config import settings

logger = logging.getLogger("sharepoint_writer")

# Windows のパス長上限(260)を考慮した、ファイル名(拡張子除く)の安全な最大長
_MAX_STEM_LEN = 120

# パス区切り・Windows 禁止文字・制御文字。案件名/タイトルは Claude 由来の信頼できない値なので
# パス要素に使う前に必ず除去し、ディレクトリトラバーサルを防ぐ。
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_component(name: str) -> str:
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "_"


def _sanitize_filename(filename: str) -> str:
    suffix = Path(filename).suffix
    stem = Path(filename).stem
    stem = _INVALID_CHARS.sub("_", stem).strip().strip(".") or "_"
    suffix = _INVALID_CHARS.sub("", suffix)
    if len(stem) > _MAX_STEM_LEN:
        stem = stem[:_MAX_STEM_LEN]
    return f"{stem}{suffix}"


def _dedupe_path(path: Path) -> Path:
    """同名ファイルがあれば ` (2)`, ` (3)` … と連番化したパスを返す。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def write_to_case_folder(
    case_name: str,
    subfolder: str,
    filename: str,
    content: bytes | str,
    overwrite: bool = False,
) -> Path:
    if not settings.sharepoint_root:
        raise ValueError("SHAREPOINT_ROOT が未設定です（.env を確認）")

    case_name = _sanitize_component(case_name)
    subfolder = _sanitize_component(subfolder)
    filename = _sanitize_filename(filename)

    root = Path(settings.sharepoint_root).resolve()
    dest_dir = (root / case_name / subfolder).resolve()
    if not dest_dir.is_relative_to(root):
        raise ValueError(f"格納先が SHAREPOINT_ROOT の外を指しています: {dest_dir}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    # 議事ログのように固定名で上書きしたいときは overwrite=True、個別資料は連番化
    dest = dest_dir / filename if overwrite else _dedupe_path(dest_dir / filename)

    if isinstance(content, bytes):
        dest.write_bytes(content)
    else:
        dest.write_text(content, encoding="utf-8")

    logger.info("[SHAREPOINT] wrote %s", dest)
    return dest


def to_onedrive_link(path: Path) -> str | None:
    """SharePoint web 表示用 URL を返す（未実装スタブ。後続精緻化対象）。

    OneDrive 同期に任せる方針のため、現状は web URL を生成せず None を返す。
    Cowork は destination_windows をローカル参照に使う。
    """
    return None
