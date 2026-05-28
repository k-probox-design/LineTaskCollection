from unittest.mock import patch, MagicMock


def test_upsert_group():
    mock_client = MagicMock()
    mock_doc = MagicMock()
    mock_client.collection.return_value.document.return_value = mock_doc

    with patch("app.firestore._get_client", return_value=mock_client):
        from app.firestore import upsert_group
        upsert_group("Cabc123")

    mock_client.collection.assert_called_with("intake_groups")
    mock_client.collection.return_value.document.assert_called_with("Cabc123")
    mock_doc.set.assert_called_once()
    call_kwargs = mock_doc.set.call_args
    data = call_kwargs[0][0]
    assert data["caseName"] is None
    assert data["sharepointFolder"] is None
    assert "registeredAt" in data
    assert call_kwargs[1]["merge"] is True


def test_record_message():
    mock_client = MagicMock()
    mock_doc = MagicMock()
    mock_client.collection.return_value.document.return_value = mock_doc

    with patch("app.firestore._get_client", return_value=mock_client):
        from app.firestore import record_message
        record_message("msg456", {"groupId": "Cabc123", "type": "image", "status": "pending"})

    mock_client.collection.assert_called_with("intake_messages")
    mock_client.collection.return_value.document.assert_called_with("msg456")
    mock_doc.set.assert_called_once()
    data = mock_doc.set.call_args[0][0]
    assert data["groupId"] == "Cabc123"
    assert data["type"] == "image"
    assert data["status"] == "pending"
    assert "receivedAt" in data
