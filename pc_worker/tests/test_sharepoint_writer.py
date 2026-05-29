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
