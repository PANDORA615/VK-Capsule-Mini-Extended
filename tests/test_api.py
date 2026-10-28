import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from capsule.api import create_app
from capsule.assistant import Answer, ProviderError
from capsule.config import Settings


def test_lights_and_case_persist_independently(settings):
    value = {"color": "#ffb66e", "brightness": 25, "enabled": True, "effect": "breathe"}
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        assert client.post("/api/v1/lights/top", json=value).status_code == 200
        assert (
            client.post(
                "/api/v1/preferences", json={"case_color": "blue", "wake_word": ""}
            ).status_code
            == 200
        )
        device = client.get("/api/v1/device").json()
        assert device["lights"]["zones"]["top"] == value
        assert device["lights"]["zones"]["front"]["brightness"] == 60
    with TestClient(create_app(settings)) as client:
        device = client.get("/api/v1/device").json()
        assert device["preferences"]["case_color"] == "blue"
        assert device["preferences"]["wake_word"] == ""
        assert device["lights"]["zones"]["top"] == value


def test_volume_limit_idempotency_and_reboot(settings):
    with TestClient(create_app(settings)) as client:
        headers = {"Idempotency-Key": "same-request"}
        first = client.post("/api/v1/commands", json={"text": "громче"}, headers=headers)
        second = client.post("/api/v1/commands", json={"text": "громче"}, headers=headers)
        assert first.json() == second.json()
        assert client.get("/api/v1/audio/status").json()["volume"] == 45
        assert (
            client.post("/api/v1/commands", json={"text": "тише"}, headers=headers).status_code
            == 409
        )
        assert client.post("/api/v1/audio/volume", json={"value": 100}).json()["volume"] == 75
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/audio/status").json()["volume"] == 75


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


def test_both_ai_models_offline_leave_settings_available(settings):
    class Fail:
        async def answer(self, text, pcm=None):
            raise ProviderError(429)

    app = create_app(settings)
    app.state.router.primary = app.state.router.fallback = Fail()
    with TestClient(app) as client:
        reply = client.post("/api/v1/commands", json={"text": "Объясни про космос"}).json()
        assert not reply["local"] and "Сейчас не могу ответить" in reply["text"]
        assert client.get("/api/v1/assistant/status").json()["state"] == "OFFLINE_COMMANDS_ONLY"
        assert client.post("/api/v1/commands", json={"text": "тише"}).json()["local"]
        assert client.post("/api/v1/lights/front", json={"brightness": 30}).status_code == 200


def test_mute_and_websocket(settings):
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/preferences", json={"microphone_muted": True})
        assert client.post("/api/v1/voice/transcribe", content=b"\0\0").status_code == 403
        with client.websocket_connect("/api/v1/voice/session") as ws:
            ws.send_json({"token": ""})
            ws.send_json({"pcm": "AAA="})
            from starlette.websockets import WebSocketDisconnect

            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_body_and_preferences_validation(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/lights/invalid", json={}).status_code == 422
        assert client.post("/api/v1/lights/front", json={"brightness": 500}).status_code == 422
        assert client.post("/api/v1/preferences", json={"case_color": "invalid"}).status_code == 422
        assert client.post("/api/v1/voice/transcribe", content=b"a" * 1_100_001).status_code == 413


def test_general_question_and_removed_player_endpoints(settings):
    class Assistant:
        async def answer(self, text, pcm=None):
            assert text == "Объясни почему небо голубое"
            return Answer("Из-за рассеяния солнечного света", model="contract-fixture")

    app = create_app(settings)
    app.state.router.primary = Assistant()
    with TestClient(app) as client:
        reply = client.post("/api/v1/commands", json={"text": "Объясни почему небо голубое"}).json()
        assert not reply["local"] and "рассеяния" in reply["text"]
        assert not any("/radio/" in route.path for route in app.routes)
        assert client.post("/api/v1/commands", json={"text": "стоп"}).json()["playback"] == "stop"
