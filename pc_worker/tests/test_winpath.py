from app.winpath import unix_to_windows, windows_to_unix


def test_unix_to_windows_basic():
    assert unix_to_windows("/mnt/c/Users/knaka/x.jpg") == "C:\\Users\\knaka\\x.jpg"


def test_unix_to_windows_root_drive():
    assert unix_to_windows("/mnt/d") == "D:"


def test_unix_to_windows_passthrough_non_mnt():
    assert unix_to_windows("/tmp/x") == "/tmp/x"


def test_windows_to_unix_basic():
    assert windows_to_unix("C:\\Users\\knaka\\x.jpg") == "/mnt/c/Users/knaka/x.jpg"


def test_windows_to_unix_passthrough_non_windows():
    assert windows_to_unix("/already/unix") == "/already/unix"


def test_roundtrip_with_spaces_and_japanese():
    p = "/mnt/c/Users/knaka/OneDrive - 株式会社ビギン/案件/x.pdf"
    assert windows_to_unix(unix_to_windows(p)) == p


# --- 一般化（サンドボックス動的マウント）写像 ---

_ATSIGN = "C:\\Users\\knaka\\OneDrive - 株式会社ビギン\\@@@"
_MAPS = [("/sessions/abc/mnt/@@@", _ATSIGN)]


def test_unix_to_windows_uses_map():
    src = "/sessions/abc/mnt/@@@/00.案件_様/09.LINEやりとり資料/x.pdf"
    assert unix_to_windows(src, _MAPS) == _ATSIGN + "\\00.案件_様\\09.LINEやりとり資料\\x.pdf"


def test_windows_to_unix_uses_map():
    src = _ATSIGN + "\\00.案件_様\\x.pdf"
    assert windows_to_unix(src, _MAPS) == "/sessions/abc/mnt/@@@/00.案件_様/x.pdf"


def test_map_roundtrip():
    p = "/sessions/abc/mnt/@@@/案件 名/資料.pdf"
    assert windows_to_unix(unix_to_windows(p, _MAPS), _MAPS) == p


def test_map_longest_prefix_wins():
    # より深い接頭辞を優先（@@@ と @@@/sub の両方が登録された場合）
    maps = [
        ("/sessions/abc/mnt/@@@", "C:\\root"),
        ("/sessions/abc/mnt/@@@/sub", "D:\\sub"),
    ]
    assert unix_to_windows("/sessions/abc/mnt/@@@/sub/x", maps) == "D:\\sub\\x"
    assert unix_to_windows("/sessions/abc/mnt/@@@/other/x", maps) == "C:\\root\\other\\x"


def test_map_prefix_boundary_no_partial_match():
    # /mnt/@@@ に対し /mnt/@@@extra は別物（部分名一致を起こさない）
    maps = [("/sessions/abc/mnt/@@@", _ATSIGN)]
    assert unix_to_windows("/sessions/abc/mnt/@@@extra/x", maps) == "/sessions/abc/mnt/@@@extra/x"


def test_map_falls_back_to_mnt_rule():
    # map に該当しない /mnt/c は従来規則で変換
    assert unix_to_windows("/mnt/c/Users/x", _MAPS) == "C:\\Users\\x"
