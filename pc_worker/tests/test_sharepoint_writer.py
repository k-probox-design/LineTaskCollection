import pytest

from app.sharepoint_writer import LINE_SUBFOLDER, place_in_case_folder


def _case_folder(tmp_path):
    folder = tmp_path / "00.HESTA_大阪府_アミューズ関目_様"
    folder.mkdir()
    return folder


def test_creates_line_subfolder_and_writes_bytes(tmp_path):
    case = _case_folder(tmp_path)
    dest, created = place_in_case_folder(str(case), "2026-05-29 概算見積.pdf", b"data")
    assert created is True
    assert dest.exists()
    assert dest.read_bytes() == b"data"
    assert dest.parent == case / LINE_SUBFOLDER


def test_created_subfolder_false_when_exists(tmp_path):
    case = _case_folder(tmp_path)
    (case / LINE_SUBFOLDER).mkdir()
    dest, created = place_in_case_folder(str(case), "2026-05-29 x.pdf", b"data")
    assert created is False
    assert dest.exists()


def test_filename_collision_is_numbered(tmp_path):
    case = _case_folder(tmp_path)
    place_in_case_folder(str(case), "2026-05-29 見積.pdf", b"first")
    second, _ = place_in_case_folder(str(case), "2026-05-29 見積.pdf", b"second")
    assert second.name == "2026-05-29 見積 (2).pdf"
    assert second.read_bytes() == b"second"


def test_overwrite_keeps_fixed_name(tmp_path):
    case = _case_folder(tmp_path)
    p1, _ = place_in_case_folder(str(case), "2026-05-29 議事ログ.md", "v1", overwrite=True)
    p2, _ = place_in_case_folder(str(case), "2026-05-29 議事ログ.md", "v2", overwrite=True)
    assert p1 == p2
    assert p2.read_text(encoding="utf-8") == "v2"


def test_missing_case_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        place_in_case_folder(str(tmp_path / "存在しない案件"), "x.pdf", b"d")


def test_path_traversal_in_title_neutralized(tmp_path):
    case = _case_folder(tmp_path)
    dest, _ = place_in_case_folder(str(case), "../../../evil.sh", b"x")
    # 案件フォルダ配下に封じ込められる
    assert (case / LINE_SUBFOLDER).resolve() in dest.resolve().parents
    assert "evil.sh" not in [p.name for p in tmp_path.parent.iterdir()]


# --- 個人 OneDrive 運用（subfolder 無し配置 ＋ 案件フォルダ自動作成、2026-06-07） ---

def test_no_subfolder_writes_directly_under_case_folder(tmp_path):
    case = _case_folder(tmp_path)
    dest, created = place_in_case_folder(str(case), "2026-06-07 見積.pdf", b"data", subfolder=None)
    assert dest.parent == case  # 09 を作らず案件フォルダ直下
    assert not (case / LINE_SUBFOLDER).exists()
    assert created is False  # 既存案件フォルダ＝新規作成していない
    assert dest.read_bytes() == b"data"


def test_empty_subfolder_also_writes_directly(tmp_path):
    case = _case_folder(tmp_path)
    dest, _ = place_in_case_folder(str(case), "x.pdf", b"d", subfolder="")
    assert dest.parent == case


def test_allow_create_makes_missing_case_folder(tmp_path):
    case = tmp_path / "LINE資料" / "新規案件"
    assert not case.exists()
    dest, created = place_in_case_folder(
        str(case), "2026-06-07 議事ログ.html", "<html>", subfolder=None, allow_create=True
    )
    assert created is True  # subfolder 無し時は「案件フォルダを新規作成したか」
    assert dest.parent == case
    assert case.is_dir()
    assert dest.read_text(encoding="utf-8") == "<html>"


def test_allow_create_false_still_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        place_in_case_folder(str(tmp_path / "無い"), "x.pdf", b"d", subfolder=None)


def test_no_subfolder_traversal_still_contained(tmp_path):
    case = _case_folder(tmp_path)
    dest, _ = place_in_case_folder(str(case), "../../evil.sh", b"x", subfolder=None)
    assert case.resolve() in dest.resolve().parents
    assert "evil.sh" not in [p.name for p in tmp_path.parent.iterdir()]
