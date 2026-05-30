from app.folders import list_case_folders


def _build_tree(root):
    # depth 1: ステータスフォルダ + 直接案件 + 非案件
    (root / "@@@決定案件").mkdir()
    (root / "テラチャージ").mkdir()
    (root / ".hidden").mkdir()  # 隠し → 除外
    (root / "desktop.ini").write_text("x")  # ファイル → 除外

    # depth 2: 案件フォルダ（09.LINEやりとり資料 あり/なし）
    case_a = root / "@@@決定案件" / "00.HESTA_大阪府_アミューズ関目_様"
    case_a.mkdir()
    (case_a / "09.LINEやりとり資料").mkdir()
    (case_a / "09.受領資料").mkdir()
    (root / "テラチャージ" / "3.26 HERMIT CRAB 藤が丘").mkdir()

    # depth 3: 年フォルダ配下の案件
    nest = root / "@@@決定案件" / "2025年作成"
    nest.mkdir()
    (nest / "深い案件").mkdir()


def test_recursive_scan_depths(tmp_path):
    _build_tree(tmp_path)
    folders = list_case_folders(str(tmp_path), max_depth=3)
    names = {f["folder_name"] for f in folders}

    assert "@@@決定案件" in names
    assert "テラチャージ" in names
    assert "00.HESTA_大阪府_アミューズ関目_様" in names
    assert "深い案件" in names  # depth 3 まで拾う

    by_name = {f["folder_name"]: f for f in folders}
    assert by_name["@@@決定案件"]["depth"] == 1
    assert by_name["@@@決定案件"]["parent_folder_name"] is None
    assert by_name["00.HESTA_大阪府_アミューズ関目_様"]["depth"] == 2
    assert by_name["00.HESTA_大阪府_アミューズ関目_様"]["parent_folder_name"] == "@@@決定案件"
    assert by_name["深い案件"]["depth"] == 3
    assert by_name["深い案件"]["parent_folder_name"] == "2025年作成"


def test_excludes_hidden_and_files(tmp_path):
    _build_tree(tmp_path)
    folders = list_case_folders(str(tmp_path), max_depth=3)
    names = {f["folder_name"] for f in folders}
    assert ".hidden" not in names
    assert "desktop.ini" not in names


def test_max_depth_limits(tmp_path):
    _build_tree(tmp_path)
    folders = list_case_folders(str(tmp_path), max_depth=1)
    depths = {f["depth"] for f in folders}
    assert depths == {1}  # depth 1 のみ


def test_has_line_yaritori_flag(tmp_path):
    _build_tree(tmp_path)
    by_name = {f["folder_name"]: f for f in list_case_folders(str(tmp_path), max_depth=3)}
    assert by_name["00.HESTA_大阪府_アミューズ関目_様"]["has_line_yaritori_folder"] is True
    assert by_name["3.26 HERMIT CRAB 藤が丘"]["has_line_yaritori_folder"] is False


def test_child_dir_count(tmp_path):
    _build_tree(tmp_path)
    by_name = {f["folder_name"]: f for f in list_case_folders(str(tmp_path), max_depth=3)}
    # アミューズ関目 配下は 09.LINEやりとり資料 と 09.受領資料 の 2 ディレクトリ
    assert by_name["00.HESTA_大阪府_アミューズ関目_様"]["child_dir_count"] == 2


def test_windows_path_emitted(tmp_path):
    _build_tree(tmp_path)
    folders = list_case_folders(str(tmp_path), max_depth=1)
    for f in folders:
        assert "absolute_path_unix" in f
        assert "absolute_path_windows" in f


def test_query_filters_by_name_across_depths(tmp_path):
    _build_tree(tmp_path)
    # 深い案件（depth3「深い案件」）も query で拾える（bug2 対策）
    deep = list_case_folders(str(tmp_path), max_depth=3, query="深い")
    names = {f["folder_name"] for f in deep}
    assert names == {"深い案件"}


def test_query_is_case_insensitive_substring(tmp_path):
    (tmp_path / "兵庫県_三和鶏園_姫路農場_様").mkdir()
    hits = list_case_folders(str(tmp_path), max_depth=2, query="姫路")
    assert [f["folder_name"] for f in hits] == ["兵庫県_三和鶏園_姫路農場_様"]


def test_query_no_match_returns_empty(tmp_path):
    _build_tree(tmp_path)
    assert list_case_folders(str(tmp_path), max_depth=3, query="存在しない案件") == []
