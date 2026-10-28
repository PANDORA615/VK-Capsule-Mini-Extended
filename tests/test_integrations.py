import json

import httpx
import pytest
from typer.testing import CliRunner

from capsule.bridge import GeminiCapsulaBridge, MarusyaBridge
from capsule.cli import app
from capsule.providers import convert_error, pcm_wav
from capsule.storage import Store


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


def test_ssh_uses_standard_client_with_host_verification(monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setenv("CAPSULE_SSH_HOST", "192.0.2.4")
    monkeypatch.setenv("CAPSULE_SSH_USER", "root")
    monkeypatch.setattr("capsule.cli.shutil.which", lambda name: "/usr/bin/ssh")

    def run(args, check):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("capsule.cli.subprocess.run", run)
    assert CliRunner().invoke(app, ["ssh"]).exit_code == 0
    assert calls[0][0] == "ssh"
    assert "StrictHostKeyChecking=yes" in calls[0]
    assert calls[0][-2:] == ["--", "192.0.2.4"]


async def test_device_control_checks_capability_and_command_allowlist():
    seen = []

    def handler(request):
        if request.url.path.endswith("login"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("state"):
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {"device_id": "own", "session": "s1", "capabilities": ["volume.adjust"]}
                    ]
                },
            )
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "data": {"level": 40}})

    bridge = GeminiCapsulaBridge(
        "http://device.invalid", "own", "fixture", httpx.MockTransport(handler)
    )
    result = await bridge.command("volume.adjust", {"delta": 5})
    assert result["agent_acknowledged"] and result["data"]["level"] == 40
    assert seen == [{"action": "volume.adjust", "args": {"delta": 5}}]
    with pytest.raises(ValueError):
        await bridge.command("shell", {"command": "anything"})
