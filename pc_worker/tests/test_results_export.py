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


_GID_A = "Cd42d2bcf838ae883edd71ac4cee84ab7"
_GID_B = "C0083aefc8befe2434f68697ecb14440e"


def test_build_rows_needs_review_blank_fields():
    page = _page("abc-123", "【LINE】2026-05-31 画像", note=f"groupId: {_GID_A}", pri="仕分け待ち", onedrive=None)
    row = results_export.build_rows([page])[0]
    assert row["case"] == ""
    assert row["fname"] == ""
    assert row["conf"] == ""
    assert row["folder"] == ""        # OneDrive 未設定
    assert row["gid"] == _GID_A
    assert row["file"] == "画像"
    assert row["pri"] == "仕分け待ち"


def test_build_rows_real_example_A_local_path_inline_note():
    # 例A: OneDrive ローカルパス ＋ インライン groupId=/確信度=
    onedrive = ("C:\\Users\\knaka\\OneDrive - 株式会社ビギン\\@@@\\@@関電_Kenes\\Kenes_見積もり案件"
                "\\2025年作成\\宮城県_ニッコン（日本梱包運輸倉庫）_岩沼営業所\\09.LINEやりとり資料"
                "\\2026-05-30 現地調査後レイアウト図 改定04（620パネル・1063.3kw）.pdf")
    note = ("案件: 宮城県_ニッコン（日本梱包運輸倉庫）_岩沼営業所<br>[Claude推測] …確信度=高（…一意一致）。"
            f"会話補足:「岩沼は基礎が高いよ」。groupId={_GID_A} / messageId=616234063460041113")
    row = results_export.build_rows([_page("p", "【LINE】2026-05-30 現地調査後レイアウト図", note=note, onedrive=onedrive)])[0]
    assert row["gid"] == _GID_A
    assert row["conf"] == "高"
    assert row["fname"] == "2026-05-30 現地調査後レイアウト図 改定04（620パネル・1063.3kw）.pdf"
    assert row["folder"] == ""  # ローカルパスは SharePoint へ機械変換不可
    assert row["case"] == "宮城県_ニッコン（日本梱包運輸倉庫）_岩沼営業所"
    assert row["room_name"] == ""


def test_build_rows_real_example_B_sharepoint_folder_url():
    # 例B: SharePoint フォルダURL（案件フォルダ止まり・%20）＋ インライン groupId=…(部屋名)
    # 拡張子が無いフォルダ URL はそのまま folder（09 自動付加は撤廃、2026-06-07）。
    onedrive = ("https://begin419671.sharepoint.com/sites/Kenes/Shared%20Documents/"
                "Kenes_見積もり案件/2025年作成/兵庫県_三和鶏園_姫路農場_様")
    note = ("案件: 三和鶏園姫路農場<br>[Claude推測] 案件=三和鶏園 姫路農場（…）/確信度=高（…）/判断理由=…/"
            f"groupId={_GID_B}(【社内】産業用図面)/docIds=…/画像7枚を09.LINEやりとり資料へ配置済")
    row = results_export.build_rows([_page("p", "【LINE】2026-05-30 図面一式", note=note, onedrive=onedrive)])[0]
    assert row["gid"] == _GID_B
    assert row["conf"] == "高"
    assert row["room_name"] == "【社内】産業用図面"
    assert row["fname"] == ""  # フォルダ止まり＝多ファイル
    # %20 はデコードして生スペース、フォルダ URL はそのまま（09 を勝手に足さない）
    assert row["folder"] == ("https://begin419671.sharepoint.com/sites/Kenes/Shared Documents/"
                             "Kenes_見積もり案件/2025年作成/兵庫県_三和鶏園_姫路農場_様")
    assert "%2520" not in row["folder"] and "%20" not in row["folder"]  # 二重/未デコードでない


def test_build_rows_onedrive_personal_log_html_new_layout():
    # 新方式: 個人 OneDrive の LINE資料/<案件名>/議事ログ.html → folder は親（案件名直下、09 無し）
    onedrive = ("https://begin419671-my.sharepoint.com/personal/k_nakamura_begin-e_co_jp/"
                "Documents/@@設計/51.LINE投稿ボット/LINE資料/佐藤邸 新築/議事ログ.html")
    note = "案件: 佐藤邸 新築\nファイル: 2026-06-07 見積書.pdf\n確信度: 高"
    row = results_export.build_rows([_page("p", "【LINE】佐藤邸 新築 ｜[見積] 見積書 (06-07)",
                                           note=note, onedrive=onedrive)])[0]
    # 09 を付加せず案件名フォルダで止まる（新レイアウトは直下配置）
    assert row["folder"] == ("https://begin419671-my.sharepoint.com/personal/k_nakamura_begin-e_co_jp/"
                             "Documents/@@設計/51.LINE投稿ボット/LINE資料/佐藤邸 新築")
    assert row["fname"] == "2026-06-07 見積書.pdf"
    assert "%2520" not in row["folder"] and "%20" not in row["folder"]
    # JS: fileUrl = folder + "/" + fname、logUrl = folder + "/議事ログ.html" が正しく組める
    assert row["folder"] + "/議事ログ.html" == (
        "https://begin419671-my.sharepoint.com/personal/k_nakamura_begin-e_co_jp/"
        "Documents/@@設計/51.LINE投稿ボット/LINE資料/佐藤邸 新築/議事ログ.html")


def test_derive_folder_legacy_folder_url_with_09_kept():
    # レガシー: 拡張子なし・09 を含むフォルダ URL → そのまま（親へ降りない）
    url = "https://x/sites/y/案件A/09.LINEやりとり資料"
    assert results_export._derive_folder(url) == "https://x/sites/y/案件A/09.LINEやりとり資料"


def test_build_rows_file_url_uses_parent_as_folder():
    # http のファイルURL → 親（既に 09 配下）を folder に、basename を fname に
    onedrive = ("https://begin419671.sharepoint.com/sites/Kenes/Shared%20Documents/案件A/"
                "09.LINEやりとり資料/2026-05-30 見積.pdf")
    row = results_export.build_rows([_page("p", "【LINE】2026-05-30 見積", onedrive=onedrive)])[0]
    assert row["folder"] == ("https://begin419671.sharepoint.com/sites/Kenes/Shared Documents/案件A/09.LINEやりとり資料")
    assert row["fname"] == "2026-05-30 見積.pdf"


def test_build_rows_new_format_file_line_wins():
    # 後方互換: 『ファイル:』独立行があれば OneDrive basename より優先
    onedrive = "https://x/sites/y/案件/09.LINEやりとり資料/other.pdf"
    note = "案件: A\nファイル: explicit.pdf\n確信度: 中"
    row = results_export.build_rows([_page("p", "【LINE】2026-05-30 A", note=note, onedrive=onedrive)])[0]
    assert row["fname"] == "explicit.pdf"
    assert row["conf"] == "中"


def test_build_rows_local_onedrive_path_becomes_empty_folder():
    page = _page("p1", "【LINE】2026-05-30 x", onedrive="C:\\Users\\knaka\\OneDrive\\案件\\f.pdf")
    row = results_export.build_rows([page])[0]
    assert row["folder"] == ""  # http(s) でなければリンク不可 → 空


def test_build_rows_date_falls_back_to_hizuke():
    page = _page("p2", "【LINE】2026-05-30 x")
    page["properties"]["日付"] = {"date": {"start": "2026-05-29T10:00:00.000+09:00"}}
    row = results_export.build_rows([page])[0]
    assert row["date"] == "2026-05-29"


def test_strip_title_new_and_old_formats():
    s = results_export._strip_title
    # 新・確定: 案件名スロット除去・末尾 (MM-DD) 除去・[種別] は残す
    assert s("【LINE】三和鶏園姫路農場 ｜[図面] 単線結線図 売電用WHメーター追加 (05-31)") == \
        "[図面] 単線結線図 売電用WHメーター追加"
    # 新・要振り分け
    assert s("【LINE】（要振り分け） ｜[写真] 受変電盤メーター採寸写真 (06-01)") == \
        "[写真] 受変電盤メーター採寸写真"
    # 旧（後方互換）: 先頭の YYYY-MM-DD を剥がす
    assert s("【LINE】2026-05-31 単線結線図 売電用WHメーター追加") == "単線結線図 売電用WHメーター追加"
    # ｜ も日付も無い変則
    assert s("【LINE】何か") == "何か"
    # 末尾が (YYYY-MM-DD)・全角括弧でも除去
    assert s("【LINE】A社 ｜[見積] 御見積書 （2026-06-01）") == "[見積] 御見積書"
    # 空フォールバック: 剥がすと空になるなら剥がす前を返す
    assert s("【LINE】 ｜ (05-31)") == "｜ (05-31)"


def test_build_rows_new_title_with_onedrive_log_html():
    # OneDrive が議事ログ.html（ファイルURL）でも folder=09フォルダ・fname=備考の『ファイル:』由来。
    # ファイル単体URLは備考の『ファイルURL:』行に移ったが既存抽出を壊さないこと。
    onedrive = ("https://begin419671.sharepoint.com/sites/Kenes/Shared%20Documents/"
                "Kenes_見積もり案件/2025年作成/兵庫県_三和鶏園_姫路農場_様/"
                "09.LINEやりとり資料/議事ログ.html")
    note = ("案件: 三和鶏園姫路農場<br>ファイル: 提案01図面.pdf<br>確信度: 高<br>"
            "ファイルURL: https://begin419671.sharepoint.com/sites/Kenes/Shared%20Documents/"
            "案件/09.LINEやりとり資料/提案01図面.pdf<br>"
            f"groupId={_GID_A}(【社内】産業用図面)")
    title = "【LINE】三和鶏園姫路農場 ｜[図面] 提案01図面 (05-31)"
    row = results_export.build_rows([_page("p", title, note=note, onedrive=onedrive)])[0]
    # 議事ログ.html の親（09 フォルダ）が folder。生スペース・二重エンコード無し
    assert row["folder"] == ("https://begin419671.sharepoint.com/sites/Kenes/Shared Documents/"
                             "Kenes_見積もり案件/2025年作成/兵庫県_三和鶏園_姫路農場_様/09.LINEやりとり資料")
    assert "%2520" not in row["folder"] and "%20" not in row["folder"]
    assert row["fname"] == "提案01図面.pdf"  # 備考の『ファイル:』由来（OneDrive が html でも不変）
    assert row["file"] == "[図面] 提案01図面"  # 案件名重複なし・[種別] 残す
    assert row["case"] == "三和鶏園姫路農場"
    assert row["conf"] == "高"  # ファイルURL: 行があっても既存抽出が壊れない
    assert row["gid"] == _GID_A
    assert row["room_name"] == "【社内】産業用図面"


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
