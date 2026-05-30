from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _env_and_cache():
    with patch.dict("os.environ", {"LINE_CHANNEL_ACCESS_TOKEN": "test_token"}):
        from app import profile
        profile._cache.clear()
        profile._group_cache.clear()
        yield
        profile._cache.clear()
        profile._group_cache.clear()


def _resp(name):
    r = MagicMock()
    r.json.return_value = {"displayName": name}
    r.raise_for_status.return_value = None
    return r


def test_resolve_uses_group_member_endpoint_for_group():
    from app import profile
    client = MagicMock()
    client.__enter__.return_value.get.return_value = _resp("山田太郎")
    with patch("app.profile.httpx.Client", return_value=client):
        name = profile.resolve_display_name("Cgrp", "Uuser")
    assert name == "山田太郎"
    called_url = client.__enter__.return_value.get.call_args[0][0]
    assert called_url == "https://api.line.me/v2/bot/group/Cgrp/member/Uuser"


def test_resolve_uses_profile_endpoint_for_1to1():
    from app import profile
    client = MagicMock()
    client.__enter__.return_value.get.return_value = _resp("田口")
    with patch("app.profile.httpx.Client", return_value=client):
        profile.resolve_display_name(None, "Uuser")
    called_url = client.__enter__.return_value.get.call_args[0][0]
    assert called_url == "https://api.line.me/v2/bot/profile/Uuser"


def test_resolve_caches_second_call():
    from app import profile
    client = MagicMock()
    client.__enter__.return_value.get.return_value = _resp("名前")
    with patch("app.profile.httpx.Client", return_value=client) as mk:
        profile.resolve_display_name("Cgrp", "Uuser")
        profile.resolve_display_name("Cgrp", "Uuser")
    mk.assert_called_once()  # 2 回目はキャッシュで API を叩かない


def test_resolve_returns_none_on_error():
    from app import profile
    with patch("app.profile.httpx.Client", side_effect=Exception("network")):
        assert profile.resolve_display_name("Cgrp", "Uuser") is None


def test_resolve_none_for_missing_user():
    from app import profile
    assert profile.resolve_display_name("Cgrp", None) is None


def test_sender_fields_includes_userid_even_when_name_fails():
    from app import profile
    with patch("app.profile.resolve_display_name", return_value=None):
        assert profile.sender_fields("Cgrp", "Uuser") == {"senderUserId": "Uuser"}


def test_sender_fields_includes_displayname():
    from app import profile
    with patch("app.profile.resolve_display_name", return_value="山田"):
        assert profile.sender_fields("Cgrp", "Uuser") == {
            "senderUserId": "Uuser",
            "senderDisplayName": "山田",
        }


def test_sender_fields_empty_without_user():
    from app import profile
    assert profile.sender_fields("Cgrp", None) == {}


# --- group name 解決 ---

def _group_resp(name):
    r = MagicMock()
    r.json.return_value = {"groupName": name}
    r.raise_for_status.return_value = None
    return r


def test_resolve_group_name_uses_summary_endpoint():
    from app import profile
    client = MagicMock()
    client.__enter__.return_value.get.return_value = _group_resp("姫路農場グループ")
    with patch("app.profile.httpx.Client", return_value=client):
        name = profile.resolve_group_name("Cgrp")
    assert name == "姫路農場グループ"
    assert client.__enter__.return_value.get.call_args[0][0] == "https://api.line.me/v2/bot/group/Cgrp/summary"


def test_resolve_group_name_caches():
    from app import profile
    client = MagicMock()
    client.__enter__.return_value.get.return_value = _group_resp("G")
    with patch("app.profile.httpx.Client", return_value=client) as mk:
        profile.resolve_group_name("Cgrp")
        profile.resolve_group_name("Cgrp")
    mk.assert_called_once()


def test_resolve_group_name_none_for_na_and_error():
    from app import profile
    assert profile.resolve_group_name("N/A") is None
    assert profile.resolve_group_name(None) is None
    with patch("app.profile.httpx.Client", side_effect=Exception("boom")):
        assert profile.resolve_group_name("Cgrp") is None
