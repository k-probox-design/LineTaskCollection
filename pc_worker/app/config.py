import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

try:
    from pythonjsonlogger.json import JsonFormatter  # python-json-logger v3+
except ImportError:  # pragma: no cover
    from pythonjsonlogger.jsonlogger import JsonFormatter  # v2

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class _Settings:
    @property
    def anthropic_api_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def notion_api_key(self) -> str:
        return os.environ.get("NOTION_API_KEY", "")

    @property
    def notion_database_id_design_task(self) -> str:
        return os.environ.get("NOTION_DATABASE_ID_DESIGN_TASK", "")

    @property
    def gcs_bucket(self) -> str:
        return os.environ.get("GCS_BUCKET", "probox-linetask-prod-intake")

    @property
    def firestore_project(self) -> str:
        return os.environ.get("FIRESTORE_PROJECT", "probox-linetask-prod")

    @property
    def sharepoint_root(self) -> str:
        return os.environ.get("SHAREPOINT_ROOT", "")

    @property
    def classify_confidence_threshold(self) -> float:
        return float(os.environ.get("CLASSIFY_CONFIDENCE_THRESHOLD", "0.8"))

    @property
    def log_aggregation_hours(self) -> int:
        return int(os.environ.get("LOG_AGGREGATION_HOURS", "24"))

    @property
    def candidate_lookback_days(self) -> int:
        return int(os.environ.get("CANDIDATE_LOOKBACK_DAYS", "90"))

    @property
    def classify_model(self) -> str:
        return os.environ.get("CLASSIFY_MODEL", "claude-sonnet-4-6")

    @property
    def log_output_dir(self) -> str:
        return os.environ.get("LOG_OUTPUT_DIR", "")


settings = _Settings()

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
    handler = logging.StreamHandler(sys.stdout)
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
