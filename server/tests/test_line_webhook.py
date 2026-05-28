import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

CHANNEL_SECRET = "test_channel_secret_1234567890"
CHANNEL_TOKEN = "test_channel_access_token"


def _make_signature(body: bytes, secret: str = CHANNEL_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@pytest.fixture()
def client():
    with patch.dict(
        "os.environ",
        {
            "LINE_CHANNEL_SECRET": CHANNEL_SECRET,
            "LINE_CHANNEL_ACCESS_TOKEN": CHANNEL_TOKEN,
            "LOCAL_FALLBACK": "true",
        },
    ):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


def test_valid_signature_join_event(client):
    payload = {
        "events": [
            {
                "type": "join",
                "source": {"type": "group", "groupId": "C1234567890abcdef"},
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _make_signature(body)

    resp = client.post(
        "/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200


def test_invalid_signature_returns_400(client):
    payload = {"events": []}
    body = json.dumps(payload).encode("utf-8")

    resp = client.post(
        "/line/webhook",
        content=body,
        headers={"X-Line-Signature": "bad_signature", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
