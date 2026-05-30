from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import pull


def _doc(doc_id, received, **fields):
    d = MagicMock()
    d.id = doc_id
    data = {"groupId": "Cgrp", "receivedAt": received, **fields}
    d.to_dict.return_value = data
    return d


def _utc(y, mo, da, h=0, mi=0):
    return datetime(y, mo, da, h, mi, tzinfo=timezone.utc)


def _fs_with_stream(docs, group_name=None):
    """collection().where().stream() が docs を返す Firestore モック。

    intake_groups の document().get() は既定で exists=False（group_name 無し）。
    group_name を渡すと exists=True かつ groupName を返す。
    """
    client = MagicMock()
    stream_chain = client.collection.return_value.where.return_value
    stream_chain.stream.return_value = iter(docs)

    gsnap = MagicMock()
    gsnap.exists = group_name is not None
    gsnap.to_dict.return_value = {"groupName": group_name} if group_name else {}
    client.collection.return_value.document.return_value.get.return_value = gsnap
    return client


def test_list_messages_sorts_and_maps_fields():
    docs = [
        _doc("b", _utc(2026, 5, 30, 13, 0), type="text", text="後", status="done"),
        _doc("a", _utc(2026, 5, 30, 12, 0), type="file", fileName="z.pdf",
             gcsPath="gs://x/p.pdf", status="pending",
             senderUserId="U1", senderDisplayName="山田"),
    ]
    client = _fs_with_stream(docs)
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_messages("Cgrp", limit=200)

    assert [m["doc_id"] for m in out] == ["a", "b"]  # 時系列昇順
    first = out[0]
    assert first["message_type"] == "file"
    assert first["file_name"] == "z.pdf"
    assert first["has_gcs"] is True
    assert first["sender_user_id"] == "U1"
    assert first["sender_display_name"] == "山田"
    assert "received_at" in first and first["received_at"].endswith("+00:00")


def test_list_messages_around_doc_window():
    center = _utc(2026, 5, 30, 12, 0)
    inside = _doc("in", _utc(2026, 5, 30, 11, 0), type="text", text="近い")
    outside = _doc("out", _utc(2026, 5, 25, 12, 0), type="text", text="遠い")
    center_doc = _doc("center", center, type="file")

    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = center_doc
    center_doc.exists = True
    client.collection.return_value.where.return_value.stream.return_value = iter([inside, outside, center_doc])

    with patch("app.pull._firestore", return_value=client):
        out = pull.list_messages("Cgrp", around_doc="center", window_hours=24)

    ids = {m["doc_id"] for m in out}
    assert "in" in ids and "center" in ids
    assert "out" not in ids  # 5日前は ±24h 窓の外


def test_list_messages_since_until_filter():
    docs = [
        _doc("old", _utc(2026, 5, 1), type="text", text="x"),
        _doc("mid", _utc(2026, 5, 15), type="text", text="y"),
        _doc("new", _utc(2026, 5, 30), type="text", text="z"),
    ]
    client = _fs_with_stream(docs)
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_messages("Cgrp", since="2026-05-10T00:00:00+00:00", until="2026-05-20T00:00:00+00:00")
    assert [m["doc_id"] for m in out] == ["mid"]


def test_list_messages_limit_truncates():
    docs = [_doc(str(i), _utc(2026, 5, 30, 0, i), type="text", text=str(i)) for i in range(10)]
    client = _fs_with_stream(docs)
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_messages("Cgrp", limit=3)
    assert len(out) == 3


def test_list_messages_attaches_group_name():
    docs = [_doc("a", _utc(2026, 5, 30, 12, 0), type="text", text="x", status="done")]
    client = _fs_with_stream(docs, group_name="姫路農場グループ")
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_messages("Cgrp")
    assert out[0]["group_name"] == "姫路農場グループ"


def test_list_messages_no_group_name_when_absent():
    docs = [_doc("a", _utc(2026, 5, 30, 12, 0), type="text", text="x", status="done")]
    client = _fs_with_stream(docs)  # group_name 無し
    with patch("app.pull._firestore", return_value=client):
        out = pull.list_messages("Cgrp")
    assert "group_name" not in out[0]


def test_list_messages_around_doc_missing_raises():
    client = MagicMock()
    snap = MagicMock()
    snap.exists = False
    client.collection.return_value.document.return_value.get.return_value = snap
    with patch("app.pull._firestore", return_value=client):
        with pytest.raises(ValueError):
            pull.list_messages("Cgrp", around_doc="nope")
