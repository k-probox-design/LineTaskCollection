from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _env_vars():
    with patch.dict(
        "os.environ",
        {
            "LINE_CHANNEL_SECRET": "test_secret",
            "LINE_CHANNEL_ACCESS_TOKEN": "test_token",
            "LOCAL_FALLBACK": "false",
        },
    ):
        yield


class TestStoreMetadataJoin:
    def test_upsert_group_called(self):
        with patch("app.firestore.upsert_group") as mock_upsert, \
             patch("app.firestore.record_message") as mock_record:
            from app.line_webhook import _store_metadata
            event = {
                "type": "join",
                "source": {"type": "group", "groupId": "Cabc123"},
            }
            _store_metadata(event)
            mock_upsert.assert_called_once_with("Cabc123")
            mock_record.assert_called_once()
            args = mock_record.call_args[0]
            assert args[1]["type"] == "join"
            assert args[1]["groupId"] == "Cabc123"


class TestStoreMetadataText:
    def test_record_message_called(self):
        with patch("app.firestore.record_message") as mock_record:
            from app.line_webhook import _store_metadata
            event = {
                "type": "message",
                "source": {"type": "group", "groupId": "Cabc123"},
                "message": {"type": "text", "id": "msg001", "text": "hello"},
            }
            _store_metadata(event)
            mock_record.assert_called_once_with("msg001", {
                "groupId": "Cabc123",
                "type": "text",
                "text": "hello",
                "status": "done",
            })


class TestStoreMedia:
    def test_upload_and_record(self):
        with patch("app.gcs.upload_to_pending", return_value="gs://bucket/pending/123_msg002.jpg") as mock_upload, \
             patch("app.firestore.record_message") as mock_record:
            from app.line_webhook import _store_media
            _store_media(b"\xff\xd8\xff", "msg002", ".jpg", "Cabc123", "image", None)
            mock_upload.assert_called_once_with(b"\xff\xd8\xff", "msg002", ".jpg")
            mock_record.assert_called_once()
            meta = mock_record.call_args[0][1]
            assert meta["status"] == "pending"
            assert meta["gcsPath"] == "gs://bucket/pending/123_msg002.jpg"
            assert "fileName" not in meta

    def test_file_message_preserves_filename(self):
        with patch("app.gcs.upload_to_pending", return_value="gs://bucket/pending/123_msg003.pdf") as mock_upload, \
             patch("app.firestore.record_message") as mock_record:
            from app.line_webhook import _store_media
            _store_media(b"data", "msg003", ".pdf", "Cabc123", "file", "estimate.pdf")
            mock_upload.assert_called_once_with(b"data", "msg003", ".pdf")
            meta = mock_record.call_args[0][1]
            assert meta["fileName"] == "estimate.pdf"

    def test_exception_logged_not_raised(self):
        with patch("app.gcs.upload_to_pending", side_effect=Exception("GCS error")), \
             patch("app.line_webhook.logger") as mock_logger:
            from app.line_webhook import _store_media
            _store_media(b"data", "msg004", ".jpg", "Cabc123", "image", None)
            mock_logger.exception.assert_called_once()
