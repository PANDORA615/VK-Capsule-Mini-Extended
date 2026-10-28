import base64
import io
import wave

from fastapi.testclient import TestClient

from capsule.api import create_app
from capsule.assistant import ProviderError
from capsule.providers import PiperTTS, VoskSTT, pcm_wav


def test_stt_flash_piper_contract(settings, monkeypatch):
    # All external services are contract fixtures. This is not voice quality evidence.
    from google import genai

    seen = []

    def transcribe(self, pcm):
        seen.append("stt")
        assert pcm == b"\0\0" * 160
        return "расскажи про космос"

    class Models:
        async def generate_content(self, **kwargs):
            seen.append("flash")
            assert kwargs["contents"] == "расскажи про космос"

            class Result:
                text = "Тестовый ответ"

            return Result()

    class Client:
        def __init__(self, **kwargs):
            self.aio = self
            self.models = Models()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def speak(self, text):
        seen.append("piper")
        assert text == "Тестовый ответ"
        return pcm_wav(b"\0\0" * 240)

    class QuotaFailure:
        async def answer(self, text, pcm=None):
            raise ProviderError(429)

    monkeypatch.setattr(VoskSTT, "transcribe", transcribe)
    monkeypatch.setattr(PiperTTS, "speak", speak)
    monkeypatch.setattr(genai, "Client", Client)
    settings.google_api_key = "fixture-key"
    app = create_app(settings)
    app.state.router.primary = QuotaFailure()
    with TestClient(app) as client:
        result = client.post("/api/v1/voice/transcribe", content=b"\0\0" * 160)
        assert result.status_code == 200
        assert seen == ["stt", "flash", "piper"]
        with wave.open(io.BytesIO(base64.b64decode(result.json()["audio"])), "rb") as wav:
            assert wav.getnframes() == 240
        assert client.post("/api/v1/commands", json={"text": "сделай тише"}).json()["local"]
