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


settings = _Settings()
