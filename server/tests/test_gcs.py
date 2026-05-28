from unittest.mock import patch, MagicMock


def test_upload_to_pending():
    mock_client = MagicMock()
    mock_blob = MagicMock()
    mock_client.bucket.return_value.blob.return_value = mock_blob

    with patch("app.gcs._get_client", return_value=mock_client), \
         patch.dict("os.environ", {"GCS_BUCKET": "test-bucket"}):
        from app.gcs import upload_to_pending
        result = upload_to_pending(b"image_data", "msg123", ".jpg")

    mock_client.bucket.assert_called_once_with("test-bucket")
    blob_name = mock_client.bucket.return_value.blob.call_args[0][0]
    assert blob_name.startswith("pending/")
    assert "msg123" in blob_name
    assert blob_name.endswith(".jpg")
    mock_blob.upload_from_string.assert_called_once_with(b"image_data")
    assert result.startswith("gs://test-bucket/pending/")
