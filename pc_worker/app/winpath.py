import re

_MNT = re.compile(r"^/mnt/([a-zA-Z])(/.*)?$")
_WIN = re.compile(r"^([a-zA-Z]):(.*)$")

# (unix 接頭辞, windows 接頭辞) のペア。サンドボックスの動的マウント
# `/sessions/<dyn>/mnt/@@@` ↔ `C:\...\@@@` のように、`/mnt/<drive>` 規則では
# 表現できないマウントを文字列置換で相互変換するための写像。app.mounts が実行時に構築する。
PathMap = tuple[str, str]


def _strip_trailing_sep(prefix: str, sep: str) -> str:
    return prefix[:-1] if prefix.endswith(sep) and len(prefix) > 1 else prefix


def _match_prefix(path: str, prefix: str, sep: str) -> bool:
    """path が prefix と完全一致、または prefix + 区切り で始まるか。
    部分的な名前一致（/a/foobar に /a/foo がマッチ）を防ぐため境界を確認する。"""
    return path == prefix or path.startswith(prefix + sep)


def unix_to_windows(path: str, maps: list[PathMap] | None = None) -> str:
    """unix パス → windows パス。

    1. maps（unix 接頭辞→windows 接頭辞）を最長一致で試す（サンドボックスの動的マウント対応）
    2. `/mnt/c/foo` → `C:\\foo` の汎用規則
    3. どれにも当たらなければそのまま返す
    """
    for unix_prefix, win_prefix in _sorted_by_unix_len(maps):
        up = _strip_trailing_sep(unix_prefix, "/")
        if _match_prefix(path, up, "/"):
            rest = path[len(up):].replace("/", "\\")
            return _strip_trailing_sep(win_prefix, "\\") + rest
    m = _MNT.match(path)
    if not m:
        return path
    drive = m.group(1).upper()
    rest = (m.group(2) or "").replace("/", "\\")
    return f"{drive}:{rest}"


def windows_to_unix(path: str, maps: list[PathMap] | None = None) -> str:
    """windows パス → unix パス。

    1. maps（windows 接頭辞→unix 接頭辞）を最長一致で試す
    2. `C:\\foo` → `/mnt/c/foo` の汎用規則
    3. どれにも当たらなければそのまま返す
    """
    for unix_prefix, win_prefix in _sorted_by_win_len(maps):
        wp = _strip_trailing_sep(win_prefix, "\\")
        if _match_prefix(path, wp, "\\"):
            rest = path[len(wp):].replace("\\", "/")
            up = _strip_trailing_sep(unix_prefix, "/")
            return up + rest
    m = _WIN.match(path)
    if not m:
        return path
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    if not rest.startswith("/"):
        rest = "/" + rest
    return f"/mnt/{drive}{rest}"


def _sorted_by_unix_len(maps: list[PathMap] | None) -> list[PathMap]:
    return sorted(maps or [], key=lambda m: len(m[0]), reverse=True)


def _sorted_by_win_len(maps: list[PathMap] | None) -> list[PathMap]:
    return sorted(maps or [], key=lambda m: len(m[1]), reverse=True)
