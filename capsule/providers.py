import asyncio
import io
import json
import tempfile
import wave
from pathlib import Path

from capsule.assistant import Answer, ProviderError


def pcm_wav(pcm: bytes, rate=24000) -> bytes:
    result = io.BytesIO()
    with wave.open(result, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return result.getvalue()


def convert_error(exc: Exception) -> ProviderError:
    # Never forward SDK exception text: it may contain request URLs or credentials.
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if not isinstance(code, int):
        code = 503
    retry = 0.0
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            retry = min(86400, float(response.headers.get("Retry-After", 0)))
        except (ValueError, AttributeError):
            pass
    return ProviderError(code, retry)


class GoogleLive:
    def __init__(self, key: str, model: str):
        self.key, self.model = key, model

    async def answer(self, text: str, pcm: bytes | None = None) -> Answer:
        from google import genai
        from google.genai import types

        try:
            async with genai.Client(api_key=self.key).aio as client:
                config = types.LiveConnectConfig(
                    response_modalities=[types.Modality.AUDIO],
                    output_audio_transcription=types.AudioTranscriptionConfig(),
                    system_instruction="Отвечай по-русски, кратко. Ты домашний помощник.",
                    realtime_input_config=types.RealtimeInputConfig(
                        automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
                    ),
                )
                async with client.live.connect(model=self.model, config=config) as session:
                    if pcm is not None:
                        await session.send_realtime_input(activity_start=types.ActivityStart())
                        for offset in range(0, len(pcm), 3200):
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=pcm[offset : offset + 3200],
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        await session.send_realtime_input(activity_end=types.ActivityEnd())
                    else:
                        await session.send_client_content(
                            turns={"role": "user", "parts": [{"text": text}]}, turn_complete=True
                        )
                    chunks, texts, size = [], [], 0
                    async for message in session.receive():
                        content = message.server_content
                        if content:
                            if content.output_transcription and content.output_transcription.text:
                                texts.append(content.output_transcription.text)
                            if content.model_turn:
                                for part in content.model_turn.parts or []:
                                    if part.inline_data and part.inline_data.data:
                                        size += len(part.inline_data.data)
                                        if size > 6_000_000:
                                            raise ProviderError(413)
                                        chunks.append(part.inline_data.data)
                            if content.turn_complete:
                                break
                    if not chunks:
                        raise ProviderError(502)
                    return Answer("".join(texts), pcm_wav(b"".join(chunks)), self.model)
        except ProviderError:
            raise
        except Exception as exc:
            raise convert_error(exc) from None


class VoskSTT:
    def __init__(self, model_path: str):
        self.model_path, self.model = model_path, None

    def transcribe(self, pcm: bytes) -> str:
        if not self.model_path:
            raise ValueError("VOSK_MODEL_PATH is not configured")
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        if self.model is None:
            self.model = Model(self.model_path)
        recognizer = KaldiRecognizer(self.model, 16000)
        recognizer.AcceptWaveform(pcm)
        return json.loads(recognizer.FinalResult()).get("text", "")


class PiperTTS:
    """Piper executable on the host, model supplied by the owner; no fake audio."""

    def __init__(self, model_path: str):
        self.model_path = model_path

    async def speak(self, text: str) -> bytes:
        if not self.model_path:
            raise ProviderError(503)
        with tempfile.TemporaryDirectory(prefix="capsule-tts-") as folder:
            output = Path(folder) / "speech.wav"
            process = await asyncio.create_subprocess_exec(
                "piper",
                "--model",
                self.model_path,
                "--output_file",
                str(output),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                async with asyncio.timeout(30):
                    await process.communicate(text[:3000].encode())
                if process.returncode or not output.exists():
                    raise ProviderError(502)
                audio = output.read_bytes()
                with wave.open(io.BytesIO(audio), "rb") as handle:
                    if handle.getnframes() == 0:
                        raise ProviderError(502)
                return audio
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()


class GoogleFlash:
    def __init__(self, key: str, model: str, tts: PiperTTS):
        self.key, self.model, self.tts = key, model, tts

    async def answer(self, text: str, pcm: bytes | None = None) -> Answer:
        from google import genai

        try:
            async with genai.Client(api_key=self.key).aio as client:
                result = await client.models.generate_content(
                    model=self.model,
                    contents=text,
                    config={
                        "system_instruction": "Отвечай кратко по-русски, до 4 предложений.",
                        "max_output_tokens": 400,
                    },
                )
            reply = result.text or "Не удалось получить ответ"
            audio = await self.tts.speak(reply)
            return Answer(reply, audio, self.model)
        except ProviderError:
            raise
        except Exception as exc:
            raise convert_error(exc) from None
