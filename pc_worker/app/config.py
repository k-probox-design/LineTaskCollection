import logging
import os
import sys
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


settings = _Settings()

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"levelname": "severity", "asctime": "timestamp"},
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True
