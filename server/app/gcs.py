import logging
import time

from google.cloud import storage

from app.config import settings

logger = logging.getLogger("gcs")

_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client(project=settings.firestore_project)
    return _client


def upload_to_pending(file_bytes: bytes, message_id: str, ext: str) -> str:
    timestamp = int(time.time())
    blob_name = f"pending/{timestamp}_{message_id}{ext}"
    bucket = _get_client().bucket(settings.gcs_bucket)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(file_bytes)
    gcs_path = f"gs://{settings.gcs_bucket}/{blob_name}"
    logger.info("[GCS] uploaded %s (%d bytes)", gcs_path, len(file_bytes))
    return gcs_path
