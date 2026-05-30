import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("NOTION_DATABASE_ID_DESIGN_TASK", "db_test_123")
    monkeypatch.setenv("SHAREPOINT_ROOT", str(tmp_path))
    monkeypatch.setenv("FIRESTORE_PROJECT", "probox-linetask-prod")
    monkeypatch.setenv("GCS_BUCKET", "probox-linetask-prod-intake")
    monkeypatch.delenv("MOUNT_MAP", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    yield
