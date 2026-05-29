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
