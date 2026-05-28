import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class _Settings:
    @property
    def line_channel_secret(self) -> str:
        return os.environ.get("LINE_CHANNEL_SECRET", "")

    @property
    def line_channel_access_token(self) -> str:
        return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

    @property
    def gcs_bucket(self) -> str:
        return os.environ.get("GCS_BUCKET", "probox-linetask-prod-intake")

    @property
    def firestore_project(self) -> str:
        return os.environ.get("FIRESTORE_PROJECT", "probox-linetask-prod")

    @property
    def local_fallback(self) -> bool:
        return os.environ.get("LOCAL_FALLBACK", "false").lower() == "true"


settings = _Settings()
