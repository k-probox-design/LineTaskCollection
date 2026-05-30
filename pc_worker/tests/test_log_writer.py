from datetime import datetime, timezone
from unittest.mock import patch

from app.log_writer import build_session_log


class _Doc:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


def test_build_session_log_orders_and_filters_window():
    around = datetime(2026, 5, 28, 14, 40, tzinfo=timezone.utc)
    docs = [
        _Doc({"type": "file", "fileName": "見積_山田.pdf",
               "receivedAt": datetime(2026, 5, 28, 14, 31, tzinfo=timezone.utc)}),
        _Doc({"type": "text", "text": "おはようございます",
               "receivedAt": datetime(2026, 5, 28, 14, 30, tzinfo=timezone.utc)}),
        _Doc({"type": "text", "text": "ずっと前のメッセージ",
               "receivedAt": datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)}),
    ]
    with patch("app.log_writer._query_group_messages", return_value=iter(docs)):
        md = build_session_log("C1", around, window_hours=24)

    assert "議事ログ" in md
    assert "おはようございます" in md
    assert "見積_山田.pdf" in md
    assert "../09.受領資料/見積_山田.pdf" in md
    assert "ずっと前のメッセージ" not in md
    # 時系列順: テキスト(14:30)がファイル(14:31)より前
    assert md.index("おはようございます") < md.index("見積_山田.pdf")
