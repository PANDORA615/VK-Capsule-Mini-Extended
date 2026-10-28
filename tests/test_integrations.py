import json

import httpx
import pytest
from typer.testing import CliRunner

from capsule.bridge import GeminiCapsulaBridge, MarusyaBridge
from capsule.catalog import Catalog, Station
from capsule.cli import app
from capsule.providers import convert_error, pcm_wav
from capsule.storage import Store


def test_alias_fuzzy_and_ambiguity(tmp_path):
    cat = Catalog(Store(tmp_path / "catalog.json"), "http://unused.invalid", True)
    assert cat.local("Дачу")[0].id == "dacha"
    assert cat.local("ретро фм")[0].id == "retro"
    assert cat.local("авторадио")[0].id == "avto"
    cat.add(Station(id="other", name="Радио Дача", urls=["https://radio.invalid/live"]))
    assert len(cat.local("дача")) == 2
    assert all(
        s.source != "simulation" for s in Catalog(cat.store, cat.directory, False).stations.values()
    )


async def test_bridge_clock_preserves_config_and_redacts_secret():
    device = {
        "id": "own",
        "config": {
            "vkAccountInfo": {"accessToken": "PRIVATE"},
            "settings": {
                "general": {
                    "clockEnabled": True,
                    "clockBrightness": 100,
                    "revision": 17,
                    "masterVolume": 35,
                }
            },
        },
    }
    patches = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=[device])
        patches.append(json.loads(request.content))
        return httpx.Response(200, json={})

    bridge = MarusyaBridge("http://bridge.invalid", "own", httpx.MockTransport(handler))
    assert "PRIVATE" not in json.dumps(await bridge.status())
    assert not (await bridge.clock(False, 20))["hardware_acknowledged"]
    general = patches[0]["config"]["settings"]["general"]
    assert general["clockBrightness"] == 20 and general["revision"] == 18
    assert general["masterVolume"] == 35


async def test_gemini_capsula_authenticated_light_contract():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers.get("X-Marusya-Panel") == "1"
        if request.url.path.endswith("login"):
            assert json.loads(request.content) == {"password": "owner-secret"}
            return httpx.Response(
                200,
                json={"ok": True},
                headers={"set-cookie": "marusya_panel=session; Path=/panel/"},
            )
        assert "marusya_panel=session" in request.headers.get("cookie", "")
        if request.url.path.endswith("state"):
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {"device_id": "own", "session": "s1", "capabilities": ["light.night"]}
                    ]
                },
            )
        assert json.loads(request.content) == {
            "action": "light.night",
            "args": {"on": True, "color": "ffb66e", "brightness": 45},
        }
        return httpx.Response(200, json={"ok": True})

    bridge = GeminiCapsulaBridge(
        "http://capsula.invalid", "own", "owner-secret", httpx.MockTransport(handler)
    )
    assert (await bridge.light(True, "#ffb66e", 45))["agent_acknowledged"]
    assert len(requests) == 3


def test_backup_and_unknown_board_no_writer(tmp_path):
    runner = CliRunner()
    source = tmp_path / "source.dump"
    target = tmp_path / "backup.dump"
    source.write_bytes(b"exported-data" * 100)
    result = runner.invoke(app, ["backup", "create", str(source), str(target)])
    assert result.exit_code == 0, result.output
    manifest = target.with_suffix(".dump.manifest.json")
    assert runner.invoke(app, ["backup", "verify", str(manifest)]).exit_code == 0
    target.write_bytes(b"tampered")
    assert runner.invoke(app, ["backup", "verify", str(manifest)]).exit_code == 1
    compatible = tmp_path / "compatible"
    compatible.write_text("unknown,board")
    assert (
        json.loads(runner.invoke(app, ["identify", str(compatible)]).output)["flash_write"]
        == "blocked"
    )
    assert runner.invoke(app, ["recovery", "validate"]).exit_code == 2
    assert runner.invoke(app, ["firmware", "write"]).exit_code != 0


def test_corrupt_state_and_secret_redaction(tmp_path):
    store = Store(tmp_path / "state.json")
    store.path.write_text("{broken")
    with pytest.raises(RuntimeError, match="Invalid state"):
        store.read()

    class SdkError(Exception):
        code = 401

    assert str(convert_error(SdkError("key=PRIVATE"))) == "Provider error 401"


def test_official_sdk_schema_and_real_wav_format():
    import io
    import wave

    from google.genai import types

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    assert config.response_modalities == [types.Modality.AUDIO]
    with wave.open(io.BytesIO(pcm_wav(b"\0\0" * 24000)), "rb") as handle:
        assert handle.getnframes() == 24000 and handle.getframerate() == 24000
