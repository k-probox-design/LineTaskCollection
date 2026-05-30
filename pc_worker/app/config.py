import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from app import mounts, winpath

try:
    from pythonjsonlogger.json import JsonFormatter  # python-json-logger v3+
except ImportError:  # pragma: no cover
    from pythonjsonlogger.jsonlogger import JsonFormatter  # v2

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class _Settings:
    @property
    def notion_api_key(self) -> str:
        return os.environ.get("NOTION_API_KEY", "")

    @property
    def notion_database_id_design_task(self) -> str:
        return os.environ.get("NOTION_DATABASE_ID_DESIGN_TASK", "")

    @property
    def notion_data_source_id(self) -> str:
        # 任意。未設定なら notion_writer が databases.retrieve で自動解決する（Notion 2025-09-03）
        return os.environ.get("NOTION_DATA_SOURCE_ID", "")

    @property
    def gcs_bucket(self) -> str:
        return os.environ.get("GCS_BUCKET", "probox-linetask-prod-intake")

    @property
    def firestore_project(self) -> str:
        return os.environ.get("FIRESTORE_PROJECT", "probox-linetask-prod")

    @property
    def mount_map(self) -> str:
        return os.environ.get("MOUNT_MAP", "")

    @property
    def path_maps(self) -> list[winpath.PathMap]:
        """実行時に解決した (unix 接頭辞 ↔ windows 接頭辞) 写像。winpath 変換に渡す。"""
        return mounts.discover_maps(self.mount_map)

    # SHAREPOINT_ROOT / TMP_DOWNLOAD_DIR / LOG_OUTPUT_DIR は Windows パスでも unix パスでも
    # 書ける。Windows 形式ならサンドボックスの動的マウントを解決して unix にしてから返す。
    @property
    def sharepoint_root(self) -> str:
        return mounts.resolve_to_unix(os.environ.get("SHAREPOINT_ROOT", ""), self.path_maps)

    @property
    def tmp_download_dir(self) -> str:
        return mounts.resolve_to_unix(os.environ.get("TMP_DOWNLOAD_DIR", ""), self.path_maps)

    @property
    def log_output_dir(self) -> str:
        return mounts.resolve_to_unix(os.environ.get("LOG_OUTPUT_DIR", ""), self.path_maps)


settings = _Settings()


def to_windows(unix_path: str) -> str:
    """unix パス → windows パス（実行時マウント写像込み）。CLI の出力整形で使う。"""
    return winpath.unix_to_windows(unix_path, settings.path_maps)


def normalize_google_credentials() -> str | None:
    """GOOGLE_APPLICATION_CREDENTIALS が Windows パスならサンドボックスの実マウントへ解決し
    os.environ に書き戻す（google-cloud ライブラリは os.environ を直接読むため）。

    鍵ファイルが未設定なら何もしない（ADC 経路にフォールバック）。解決後パスが存在しない場合は
    WARN のみで処理は止めない（認証失敗時に google ライブラリ側が明示エラーを出す）。
    """
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw:
        return None
    resolved = mounts.resolve_to_unix(raw, settings.path_maps)
    if resolved != raw:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = resolved
    if not Path(resolved).is_file():
        logger.warning("[AUTH] GOOGLE_APPLICATION_CREDENTIALS のパスが見つかりません: %s", resolved)
    else:
        logger.info("[AUTH] サービスアカウント鍵を使用: %s", resolved)
    return resolved

logger = logging.getLogger("config")

_configured = False


def _json_formatter() -> JsonFormatter:
    return JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"levelname": "severity", "asctime": "timestamp"},
    )


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    # CLI の結果 JSON は stdout、ログは stderr に分離する（pc_cli の出力契約）
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_json_formatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True


def add_file_handler(run_id: str) -> bool:
    """LOG_OUTPUT_DIR/YYYY-MM-DD/<run_id>.jsonl に JSON Lines でログを複製出力する。

    Cowork が OneDrive 経由で実行結果を監査できるようにするための追加ハンドラ。
    LOG_OUTPUT_DIR が未設定・パス不存在・書き込み不可のときは WARN を 1 行出して
    スキップし、コンソール出力のみで処理を継続する（ログ複製のために本処理を止めない）。
    """
    log_dir = settings.log_output_dir
    if not log_dir:
        logger.warning("[LOG] LOG_OUTPUT_DIR 未設定。OneDrive へのログ複製をスキップします")
        return False

    try:
        day_dir = Path(log_dir) / date.today().isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        log_path = day_dir / f"{run_id}.jsonl"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(_json_formatter())
        logging.getLogger().addHandler(handler)
        logger.info("[LOG] OneDrive ログ複製を有効化: %s", log_path)
        return True
    except OSError as e:
        logger.warning(
            "[LOG] OneDrive ログ複製を初期化できません(%s)。コンソールのみで継続します", e
        )
        return False
