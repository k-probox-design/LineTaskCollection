import logging
import re
from pathlib import Path

logger = logging.getLogger("sharepoint_writer")

# LINE 由来資料（画像/PDF/議事ログ）の統一格納先サブフォルダ
LINE_SUBFOLDER = "09.LINEやりとり資料"

# Windows のパス長上限(260)を考慮した、ファイル名(拡張子除く)の安全な最大長
_MAX_STEM_LEN = 120

# パス区切り・Windows 禁止文字・制御文字。タイトルは Cowork 由来の信頼できない値なので
# ファイル名に使う前に必ず除去し、ディレクトリトラバーサルを防ぐ。
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_filename(filename: str) -> str:
    suffix = _INVALID_CHARS.sub("", Path(filename).suffix)
    stem = _INVALID_CHARS.sub("_", Path(filename).stem).strip().strip(".") or "_"
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


def place_in_case_folder(
    case_folder: str,
    filename: str,
    content: bytes | str,
    overwrite: bool = False,
) -> tuple[Path, bool]:
    """案件フォルダ(絶対パス)配下の 09.LINEやりとり資料/ にファイルを書き込む。

    戻り値は (書き込んだパス, 09.LINEやりとり資料 を新規作成したか)。
    案件フォルダが存在しない場合は FileNotFoundError（CLI 側で case_folder_not_found に変換）。
    案件フォルダ自体の自動作成はしない（マッチしなければ needs_review 運用）。
    """
    base = Path(case_folder)
    if not base.is_dir():
        raise FileNotFoundError(f"case folder not found: {case_folder}")

    subdir = base / LINE_SUBFOLDER
    created_subfolder = not subdir.exists()
    subdir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_filename(filename)
    candidate = subdir / safe_name
    # サニタイズ済みだが念のためトラバーサル封じ込め
    if not candidate.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"格納先が案件フォルダの外を指しています: {candidate}")

    dest = candidate if overwrite else _dedupe_path(candidate)
    if isinstance(content, bytes):
        dest.write_bytes(content)
    else:
        dest.write_text(content, encoding="utf-8")

    logger.info("[SHAREPOINT] wrote %s (created_subfolder=%s)", dest, created_subfolder)
    return dest, created_subfolder


def to_onedrive_link(path: Path) -> str | None:
    """SharePoint web 表示用 URL を返す（未実装スタブ。後続精緻化対象）。

    OneDrive 同期に任せる方針のため、現状は web URL を生成せず None を返す。
    Cowork は destination_windows をローカル参照に使う。
    """
    return None
