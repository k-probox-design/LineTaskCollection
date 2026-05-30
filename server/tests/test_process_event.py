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


@pytest.fixture(autouse=True)
def _no_group_net():
    # 既定で表示名/グループ名解決を None にして実ネットワークを避ける（個別テストで上書き可）。
    # _group_synced はモジュール常駐なのでテスト毎にクリア。
    from app import line_webhook
    line_webhook._group_synced.clear()
    with patch("app.profile.resolve_group_name", return_value=None), \
         patch("app.profile.resolve_display_name", return_value=None):
        yield
    line_webhook._group_synced.clear()


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
        # source に userId が無い（過去形式）→ sender フィールドは付かない
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

    def test_text_with_sender_resolved(self):
        # senderUserId は保存時 meta（HTTP 不要）、senderDisplayName は保存後 update_message で付与
        with patch("app.firestore.record_message") as mock_record, \
             patch("app.firestore.update_message") as mock_update, \
             patch("app.profile.resolve_display_name", return_value="山田太郎"):
            from app.line_webhook import _store_metadata
            event = {
                "type": "message",
                "source": {"type": "group", "groupId": "Cabc123", "userId": "Uuser1"},
                "message": {"type": "text", "id": "msg010", "text": "確認する。"},
            }
            _store_metadata(event)
            meta = mock_record.call_args[0][1]
            assert meta["senderUserId"] == "Uuser1"
            assert "senderDisplayName" not in meta  # 保存時 meta には入れない
            mock_update.assert_called_once_with("msg010", {"senderDisplayName": "山田太郎"})

    def test_group_name_saved_on_text(self):
        with patch("app.firestore.record_message"), \
             patch("app.profile.resolve_group_name", return_value="姫路農場グループ"), \
             patch("app.firestore.set_group_name") as mock_set:
            from app.line_webhook import _store_metadata
            event = {
                "type": "message",
                "source": {"type": "group", "groupId": "Cabc123", "userId": "U1"},
                "message": {"type": "text", "id": "m020", "text": "x"},
            }
            _store_metadata(event)
            mock_set.assert_called_once_with("Cabc123", "姫路農場グループ")

    def test_group_name_synced_once_per_instance(self):
        with patch("app.firestore.record_message"), \
             patch("app.profile.resolve_group_name", return_value="G") as mock_resolve, \
             patch("app.firestore.set_group_name"):
            from app.line_webhook import _store_metadata
            ev = lambda i: {
                "type": "message",
                "source": {"type": "group", "groupId": "Csame", "userId": "U"},
                "message": {"type": "text", "id": i, "text": "x"},
            }
            _store_metadata(ev("a"))
            _store_metadata(ev("b"))
            # 2 回目は _group_synced により解決をスキップ
            mock_resolve.assert_called_once()

    def test_text_with_sender_name_unresolved_keeps_userid(self):
        with patch("app.firestore.record_message") as mock_record, \
             patch("app.firestore.update_message") as mock_update, \
             patch("app.profile.resolve_display_name", return_value=None):
            from app.line_webhook import _store_metadata
            event = {
                "type": "message",
                "source": {"type": "group", "groupId": "Cabc123", "userId": "Uuser2"},
                "message": {"type": "text", "id": "msg011", "text": "x"},
            }
            _store_metadata(event)
            meta = mock_record.call_args[0][1]
            assert meta["senderUserId"] == "Uuser2"
            assert "senderDisplayName" not in meta
            mock_update.assert_not_called()  # 名前が取れなければ update しない

    def test_text_saved_even_if_enrichment_raises(self):
        # ★回帰: 表示名/グループ名解決が例外でも、メッセージ保存は完了する（取り込み欠落バグ再発防止）
        with patch("app.firestore.record_message") as mock_record, \
             patch("app.profile.resolve_display_name", side_effect=Exception("profile down")), \
             patch("app.profile.resolve_group_name", side_effect=Exception("summary down")):
            from app.line_webhook import _store_metadata
            event = {
                "type": "message",
                "source": {"type": "group", "groupId": "Cabc123", "userId": "U9"},
                "message": {"type": "text", "id": "msg012", "text": "保存されるべき"},
            }
            _store_metadata(event)  # 例外が伝播しないこと
            mock_record.assert_called_once()
            assert mock_record.call_args[0][1]["text"] == "保存されるべき"


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

    def test_media_with_sender_resolved(self):
        with patch("app.gcs.upload_to_pending", return_value="gs://bucket/pending/123_m.pdf"), \
             patch("app.firestore.record_message") as mock_record, \
             patch("app.firestore.update_message") as mock_update, \
             patch("app.profile.resolve_display_name", return_value="田口"):
            from app.line_webhook import _store_media
            _store_media(b"data", "m005", ".pdf", "Cabc123", "file", "zumen.pdf", "Uuser3")
            meta = mock_record.call_args[0][1]
            assert meta["senderUserId"] == "Uuser3"
            assert "senderDisplayName" not in meta  # 保存後 update で付与
            assert meta["fileName"] == "zumen.pdf"
            mock_update.assert_called_once_with("m005", {"senderDisplayName": "田口"})

    def test_media_saved_even_if_enrichment_raises(self):
        # ★回帰: media も enrichment 例外で保存が落ちない（保存は GCS upload 後・HTTP より前）
        with patch("app.gcs.upload_to_pending", return_value="gs://bucket/pending/x.pdf"), \
             patch("app.firestore.record_message") as mock_record, \
             patch("app.profile.resolve_display_name", side_effect=Exception("down")), \
             patch("app.profile.resolve_group_name", side_effect=Exception("down")):
            from app.line_webhook import _store_media
            _store_media(b"d", "m006", ".pdf", "Cabc123", "file", "z.pdf", "U9")
            mock_record.assert_called_once()
            assert mock_record.call_args[0][1]["gcsPath"] == "gs://bucket/pending/x.pdf"

    def test_exception_logged_not_raised(self):
        with patch("app.gcs.upload_to_pending", side_effect=Exception("GCS error")), \
             patch("app.line_webhook.logger") as mock_logger:
            from app.line_webhook import _store_media
            _store_media(b"data", "msg004", ".jpg", "Cabc123", "image", None)
            mock_logger.exception.assert_called_once()
