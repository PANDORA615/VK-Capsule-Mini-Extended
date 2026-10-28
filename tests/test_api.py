import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from capsule.api import create_app
from capsule.assistant import ProviderError
from capsule.config import Settings


def test_menu_light_state_and_persistence(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        value = {"color": "#ffb66e", "brightness": 25, "enabled": True, "effect": "breathe"}
        assert client.post("/api/v1/lights/top", json=value).status_code == 200
        result = client.get("/api/v1/device").json()
        assert result["lights"]["zones"]["top"] == value
        assert result["lights"]["zones"]["front"]["brightness"] == 60
        assert result["hardware_verification_required"]
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/device").json()["lights"]["zones"]["top"] == value


def test_idempotency_no_duplicate_side_effects(settings):
    with TestClient(create_app(settings)) as client:
        headers = {"Idempotency-Key": "same-request"}
        first = client.post("/api/v1/commands", json={"text": "громче"}, headers=headers)
        second = client.post("/api/v1/commands", json={"text": "громче"}, headers=headers)
        assert first.json() == second.json()
        assert client.get("/api/v1/radio/status").json()["volume"] == 45
        assert (
            client.post("/api/v1/commands", json={"text": "тише"}, headers=headers).status_code
            == 409
        )


def test_auth_static_access_origins_and_validation(settings):
    settings.capsule_token = "secret-token"
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/v1/device").status_code == 401
        headers = {"Authorization": "Bearer secret-token"}
        assert client.get("/api/v1/device", headers=headers).status_code == 200
        assert (
            client.post("/api/v1/audio/volume", json={"value": 101}, headers=headers).status_code
            == 422
        )
        headers["Origin"] = "https://foreign.invalid"
        assert client.get("/api/v1/device", headers=headers).status_code == 403
    with pytest.raises(ValidationError):
        Settings(_env_file=None, capsule_host="0.0.0.0", capsule_allow_lan=False)


def test_radio_still_works_when_both_ai_models_fail(settings):
    app = create_app(settings)

    class Fail:
        async def answer(self, text, pcm=None):
            raise ProviderError(429)

    app.state.router.primary = app.state.router.fallback = Fail()
    with TestClient(app) as client:
        assert client.post("/api/v1/commands", json={"text": "Маруся включи Дачу"}).json()["local"]
        time.sleep(1.1)
        client.post("/api/v1/commands", json={"text": "расскажи про космос"})
        assert client.get("/api/v1/assistant/status").json()["state"] == "OFFLINE_COMMANDS_ONLY"
        assert client.get("/api/v1/radio/status").json()["state"] == "PLAYING"
        assert client.post("/api/v1/commands", json={"text": "Маруся тише"}).json()["local"]
        assert client.post("/api/v1/radio/stop").json()["state"] == "IDLE"


def test_mute_rejects_audio_and_websocket(settings):
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/preferences", json={"microphone_muted": True})
        assert client.post("/api/v1/voice/transcribe", content=b"\0\0").status_code == 403
        with client.websocket_connect("/api/v1/voice/session") as ws:
            ws.send_json({"token": ""})
            ws.send_json({"pcm": "AAA="})
            from starlette.websockets import WebSocketDisconnect

            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_unsafe_url_and_invalid_zone(settings):
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/radio/stations",
                json={"id": "evil", "name": "bad", "urls": ["file:///etc/passwd"]},
            ).status_code
            == 422
        )
        assert client.post("/api/v1/lights/invalid", json={}).status_code == 422
        assert client.post("/api/v1/lights/front", json={"brightness": 500}).status_code == 422
        assert client.post("/api/v1/voice/transcribe", content=b"a" * 1_100_001).status_code == 413
