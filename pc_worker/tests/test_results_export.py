import json
import re

from app import results_export


def _page(pid, title, note="", status="未着手", pri="Claude追記", onedrive=None, date_reg=None):
    props = {
        "タスク名": {"title": [{"plain_text": title}]},
        "備考": {"rich_text": [{"plain_text": note}] if note else []},
        "ステータス": {"status": {"name": status} if status else None},
        "優先度": {"select": {"name": pri} if pri else None},
        "OneDrive": {"url": onedrive},
    }
    if date_reg:
        props["タスク登録日"] = {"date": {"start": date_reg}}
    return {"id": pid, "properties": props}


def test_build_rows_confirmed():
    note = ("案件: 三和鶏園 姫路農場\n"
            "ファイル: 2026-05-30 提案01図面.pdf\n"
            "確信度: 高\n"
            "groupId: Cd42d2bcf838ae883edd71ac4cee84ab7")
    page = _page(
        "37017f63-e23f-81c1-ad31-fdf2c79030f0",
        "【LINE】2026-05-30 提案01図面 三和鶏園姫路農場",
        note=note,
        onedrive="https://begin419671.sharepoint.com/sites/x/09.LINEやりとり資料",
        date_reg="2026-05-30",
    )
    row = results_export.build_rows([page])[0]
    assert row["date"] == "2026-05-30"
    assert row["case"] == "三和鶏園 姫路農場"
    assert row["file"] == "提案01図面 三和鶏園姫路農場"  # 【LINE】と日付プレフィックス除去
    assert row["fname"] == "2026-05-30 提案01図面.pdf"
    assert row["folder"] == "https://begin419671.sharepoint.com/sites/x/09.LINEやりとり資料"
    assert row["status"] == "未着手"
    assert row["pri"] == "Claude追記"
    assert row["gid"] == "Cd42d2bcf838ae883edd71ac4cee84ab7"
    assert row["conf"] == "高"
    assert row["link"] == "https://www.notion.so/37017f63e23f81c1ad31fdf2c79030f0"  # dash 無し


def test_build_rows_needs_review_blank_fields():
    page = _page("abc-123", "【LINE】2026-05-31 画像", note="groupId: Cxxx", pri="仕分け待ち", onedrive=None)
    row = results_export.build_rows([page])[0]
    assert row["case"] == ""
    assert row["fname"] == ""
    assert row["conf"] == ""
    assert row["folder"] == ""        # OneDrive 未設定
    assert row["gid"] == "Cxxx"
    assert row["file"] == "画像"
    assert row["pri"] == "仕分け待ち"


def test_build_rows_local_onedrive_path_becomes_empty_folder():
    page = _page("p1", "【LINE】2026-05-30 x", onedrive="C:\\Users\\knaka\\OneDrive\\案件\\f.pdf")
    row = results_export.build_rows([page])[0]
    assert row["folder"] == ""  # http(s) でなければリンク不可 → 空


def test_build_rows_date_falls_back_to_hizuke():
    page = _page("p2", "【LINE】2026-05-30 x")
    page["properties"]["日付"] = {"date": {"start": "2026-05-29T10:00:00.000+09:00"}}
    row = results_export.build_rows([page])[0]
    assert row["date"] == "2026-05-29"


def test_render_html_replaces_markers_and_valid_json():
    rows = [{"date": "2026-05-30", "case": "C", "file": "F", "fname": "f.pdf",
             "folder": "https://x/y", "status": "未着手", "pri": "Claude追記",
             "link": "https://www.notion.so/abc", "gid": "Cgid", "conf": "高"}]
    html = results_export.render_html(rows, "2026-05-31 01:23 JST")

    assert "★" not in html  # 2 マーカーとも置換済み
    assert "スナップショット（生成: 2026-05-31 01:23 JST）" in html

    m = re.search(r'id="data">\s*(.*?)\s*</script>', html, re.S)
    assert m, "data ブロックが見つからない"
    parsed = json.loads(m.group(1))  # 壊れた引用符が無く JSON.parse 可能
    assert parsed == rows


def test_render_html_escapes_angle_brackets_in_data():
    # 値に < があっても </script> ブレイクアウトせず JSON.parse 可能
    rows = [{"case": "a<script>b", "date": "", "file": "", "fname": "", "folder": "",
             "status": "", "pri": "", "link": "", "gid": "", "conf": ""}]
    html = results_export.render_html(rows, "2026-05-31 00:00 JST")
    m = re.search(r'id="data">\s*(.*?)\s*</script>', html, re.S)
    assert "\\u003c" in m.group(1)        # 生の < ではなくエスケープ
    assert json.loads(m.group(1))[0]["case"] == "a<script>b"
