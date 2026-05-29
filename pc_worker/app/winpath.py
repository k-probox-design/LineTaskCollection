import re

_MNT = re.compile(r"^/mnt/([a-zA-Z])(/.*)?$")
_WIN = re.compile(r"^([a-zA-Z]):(.*)$")


def unix_to_windows(path: str) -> str:
    """`/mnt/c/foo/bar` → `C:\\foo\\bar`。/mnt 配下でなければそのまま返す。"""
    m = _MNT.match(path)
    if not m:
        return path
    drive = m.group(1).upper()
    rest = (m.group(2) or "").replace("/", "\\")
    return f"{drive}:{rest}"


def windows_to_unix(path: str) -> str:
    """`C:\\foo\\bar` → `/mnt/c/foo/bar`。ドライブレターでなければそのまま返す。"""
    m = _WIN.match(path)
    if not m:
        return path
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    if not rest.startswith("/"):
        rest = "/" + rest
    return f"/mnt/{drive}{rest}"
