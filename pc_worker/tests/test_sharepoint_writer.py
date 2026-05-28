from app.sharepoint_writer import write_to_case_folder


def test_write_bytes_creates_nested_folders(tmp_path):
    # conftest の _env が SHAREPOINT_ROOT を tmp_path に設定済み
    dest = write_to_case_folder("案件A", "09.受領資料", "2026-05-28 見積書.pdf", b"data")
    assert dest.exists()
    assert dest.read_bytes() == b"data"
    assert dest.parent == tmp_path / "案件A" / "09.受領資料"


def test_filename_collision_is_numbered(tmp_path):
    write_to_case_folder("案件A", "09.受領資料", "2026-05-28 見積書.pdf", b"first")
    second = write_to_case_folder("案件A", "09.受領資料", "2026-05-28 見積書.pdf", b"second")
    assert second.name == "2026-05-28 見積書 (2).pdf"
    assert second.read_bytes() == b"second"


def test_write_text_content(tmp_path):
    dest = write_to_case_folder("案件A", "09.LINEやりとり資料", "2026-05-28 議事ログ.md", "# 議事ログ\n本文")
    assert dest.read_text(encoding="utf-8") == "# 議事ログ\n本文"


def test_path_traversal_is_neutralized(tmp_path):
    # Claude 由来の悪意ある案件名/タイトルが SHAREPOINT_ROOT の外に書き込めないこと
    dest = write_to_case_folder("../../etc", "09.受領資料", "../../../evil.sh", b"x")
    assert dest.exists()
    assert tmp_path.resolve() in dest.resolve().parents
    assert "evil.sh" not in [p.name for p in tmp_path.parent.iterdir()]


def test_dotdot_case_name_becomes_safe(tmp_path):
    dest = write_to_case_folder("..", "09.受領資料", "x.pdf", b"x")
    assert tmp_path.resolve() in dest.resolve().parents
