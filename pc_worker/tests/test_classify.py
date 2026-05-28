from unittest.mock import MagicMock, patch

from app.classify import ClassifyResult, classify
from app.pull import PendingItem


def _image_item(**kw):
    base = dict(message_id="m1", group_id="C1", type="image", content_bytes=b"\xff\xd8\xff")
    base.update(kw)
    return PendingItem(**base)


def _mock_client(parsed, stop_reason="end_turn"):
    resp = MagicMock()
    resp.parsed_output = parsed
    resp.stop_reason = stop_reason
    client = MagicMock()
    client.messages.parse.return_value = resp
    return client


def test_high_confidence_image():
    parsed = ClassifyResult(
        case_name="コスモス ソラプロ", title="見積書", confidence=0.92,
        reasoning="見積書のヘッダに案件名あり", related_message_ids=["m1"],
    )
    client = _mock_client(parsed)
    with patch("app.classify._get_client", return_value=client):
        result = classify(_image_item(), ["コスモス ソラプロ", "山田邸"])

    assert result.case_name == "コスモス ソラプロ"
    assert result.confidence == 0.92

    kwargs = client.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "コスモス ソラプロ" in kwargs["system"][0]["text"]
    content = kwargs["messages"][0]["content"]
    assert any(block["type"] == "image" for block in content)


def test_medium_confidence():
    parsed = ClassifyResult(
        case_name="山田邸", title="屋根写真", confidence=0.7,
        reasoning="文字なし写真、groupId から推測", related_message_ids=[],
    )
    client = _mock_client(parsed)
    with patch("app.classify._get_client", return_value=client):
        result = classify(_image_item(), ["山田邸"])
    assert result.confidence == 0.7


def test_low_confidence_no_case():
    parsed = ClassifyResult(
        case_name=None, title="不明な写真", confidence=0.3,
        reasoning="該当案件が候補にない", related_message_ids=[],
    )
    client = _mock_client(parsed)
    with patch("app.classify._get_client", return_value=client):
        result = classify(_image_item(), ["山田邸"])
    assert result.case_name is None
    assert result.confidence == 0.3


def test_pdf_uses_document_block():
    item = PendingItem(message_id="m2", group_id="C1", type="file", file_name="見積_山田.pdf", content_bytes=b"%PDF-1.4")
    parsed = ClassifyResult(case_name="山田邸", title="見積書", confidence=0.9, reasoning="r", related_message_ids=[])
    client = _mock_client(parsed)
    with patch("app.classify._get_client", return_value=client):
        classify(item, ["山田邸"])
    content = client.messages.parse.call_args.kwargs["messages"][0]["content"]
    assert any(b["type"] == "document" for b in content)


def test_parse_failure_fallback():
    client = _mock_client(None, stop_reason="refusal")
    with patch("app.classify._get_client", return_value=client):
        result = classify(_image_item(file_name="x.jpg"), [])
    assert result.case_name is None
    assert result.confidence == 0.0
    assert "要確認" in result.reasoning
