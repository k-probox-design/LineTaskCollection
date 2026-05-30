from app import mounts

WIN_ATSIGN = "C:\\Users\\knaka\\OneDrive - 株式会社ビギン\\@@@"
WIN_BOT = "C:\\Users\\knaka\\OneDrive - 株式会社ビギン\\@@設計\\51.LINE投稿ボット"


def test_parse_mount_map_splits_and_strips():
    raw = f" {WIN_ATSIGN} ;{WIN_BOT}; "
    assert mounts.parse_mount_map(raw) == [WIN_ATSIGN, WIN_BOT]


def test_parse_mount_map_empty():
    assert mounts.parse_mount_map("") == []


def test_windows_basename():
    assert mounts._windows_basename(WIN_ATSIGN) == "@@@"
    assert mounts._windows_basename(WIN_BOT) == "51.LINE投稿ボット"
    assert mounts._windows_basename(WIN_BOT + "\\") == "51.LINE投稿ボット"


def test_session_mount_base_detects_current_session():
    self_path = "/sessions/friendly-charming-ptolemy/mnt/51.LINE投稿ボット/pc_cli/app/mounts.py"
    assert mounts._session_mount_base(self_path) == "/sessions/friendly-charming-ptolemy/mnt"


def test_session_mount_base_none_outside_sandbox():
    assert mounts._session_mount_base("/home/knaka/projects/LineTaskCollection/pc_worker/app/mounts.py") is None


def test_discover_maps_via_session_base(tmp_path, monkeypatch):
    # サンドボックス相当: <session base>/mnt/@@@ が実在する状況を作る
    session_base = tmp_path / "sessions" / "sess-xyz" / "mnt"
    (session_base / "@@@").mkdir(parents=True)
    monkeypatch.setattr(mounts, "_session_mount_base", lambda _self: str(session_base))

    maps = mounts.discover_maps(WIN_ATSIGN, self_path="ignored")
    assert maps == [(str(session_base / "@@@"), WIN_ATSIGN)]


def test_discover_maps_via_wsl_fallback(tmp_path, monkeypatch):
    # WSL 相当: /sessions は無く、windows_to_unix の指す実ディレクトリがある状況
    real = tmp_path / "atsign"
    real.mkdir()
    monkeypatch.setattr(mounts, "_session_mount_base", lambda _self: None)
    monkeypatch.setattr(mounts.winpath, "windows_to_unix", lambda p, m=None: str(real))

    maps = mounts.discover_maps(WIN_ATSIGN, self_path="ignored")
    assert maps == [(str(real), WIN_ATSIGN)]


def test_discover_maps_via_glob_when_outside_sessions(tmp_path, monkeypatch):
    # git clone を /outputs で実行する場合、self_path が /sessions 配下にないので session_base=None。
    # その場合でも /sessions/*/mnt/<name> の glob フォールバックでマウントを解決できること（A案=B案の土台）。
    real = tmp_path / "mnt-atsign"
    real.mkdir()
    monkeypatch.setattr(mounts, "_session_mount_base", lambda _self: None)
    monkeypatch.setattr(mounts.winpath, "windows_to_unix", lambda p, m=None: p)  # WSL 分岐は不一致
    monkeypatch.setattr(mounts.Path, "glob", lambda self, pat: iter([real]))

    maps = mounts.discover_maps(WIN_ATSIGN, self_path="/outputs/linetask/pc_worker/app/mounts.py")
    assert maps == [(str(real), WIN_ATSIGN)]


def test_discover_maps_skips_unresolved(monkeypatch):
    # どこにも実在しない → 写像から除外（処理は止めない）
    monkeypatch.setattr(mounts, "_session_mount_base", lambda _self: None)
    monkeypatch.setattr(mounts.winpath, "windows_to_unix", lambda p, m=None: p)  # 変換せず=未解決
    monkeypatch.setattr(mounts.Path, "glob", lambda self, pat: iter([]))

    assert mounts.discover_maps(WIN_ATSIGN, self_path="ignored") == []


def test_resolve_to_unix_converts_windows_path():
    maps = [("/sessions/s/mnt/@@@", WIN_ATSIGN)]
    assert mounts.resolve_to_unix(WIN_ATSIGN + "\\案件", maps) == "/sessions/s/mnt/@@@/案件"


def test_resolve_to_unix_passthrough_unix_path():
    assert mounts.resolve_to_unix("/mnt/c/Users/x", []) == "/mnt/c/Users/x"


def test_resolve_to_unix_empty():
    assert mounts.resolve_to_unix("", []) == ""
