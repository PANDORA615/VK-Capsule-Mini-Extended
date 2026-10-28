import asyncio
import base64
import hashlib
import secrets
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from capsule.assistant import Router, Unconfigured
from capsule.audio import ReplyAudio
from capsule.bridge import GeminiCapsulaBridge, MarusyaBridge
from capsule.catalog import Catalog, Station
from capsule.config import Settings
from capsule.intents import parse
from capsule.lights import Lights, Zone
from capsule.player import MpvPlayer, SimulatedPlayer
from capsule.providers import GoogleFlash, GoogleLive, PiperTTS, VoskSTT
from capsule.radio import Radio
from capsule.storage import Store


class PlayRequest(BaseModel):
    station: str = Field(min_length=1, max_length=200)


class VolumeRequest(BaseModel):
    value: int = Field(ge=0, le=100)


class ModeRequest(BaseModel):
    mode: Literal["auto", "live_only", "fallback_only"]


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class Preferences(BaseModel):
    microphone_muted: bool = False
    wake_word: str = Field(default="", max_length=30, pattern=r"^[\w ]*$")


def create_app(settings: Settings | None = None):
    cfg = settings or Settings()
    simulation = cfg.capsule_mode == "simulation"
    catalog = Catalog(
        Store(cfg.capsule_state_dir / "stations.json"), cfg.radio_directory_url, simulation
    )
    player = SimulatedPlayer() if simulation else MpvPlayer()
    radio = Radio(
        catalog,
        Store(cfg.capsule_state_dir / "radio.json"),
        player,
        cfg.radio_max_volume,
        cfg.radio_resume_after_reboot,
    )
    audio = ReplyAudio(Store(cfg.capsule_state_dir / "audio.json"), cfg.assistant_max_volume)
    lights = Lights(Store(cfg.capsule_state_dir / "lights.json"))
    preferences_store = Store(cfg.capsule_state_dir / "preferences.json")
    preferences = Preferences(**preferences_store.read())
    key = cfg.google_api_key.get_secret_value()
    router = Router(
        GoogleLive(key, cfg.gemini_primary_model) if key else Unconfigured(),
        GoogleFlash(key, cfg.gemini_fallback_model, PiperTTS(cfg.piper_model_path))
        if key
        else Unconfigured(),
        cfg.gemini_cooldown_seconds,
    )
    router.mode = cfg.gemini_routing
    stt = VoskSTT(cfg.vosk_model_path)
    bridge = MarusyaBridge(cfg.marusya_server_url, cfg.marusya_device_id)
    gemini_bridge = GeminiCapsulaBridge(
        cfg.gemini_capsula_url,
        cfg.gemini_capsula_device_id,
        cfg.gemini_capsula_panel_password.get_secret_value(),
    )
    voice_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        await radio.startup()
        yield
        await radio.stop()

    app = FastAPI(
        title="Капсула · Дом", version="0.2.1", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.radio, app.state.catalog = radio, catalog
    app.state.router, app.state.lights, app.state.audio = router, lights, audio
    app.state.settings = cfg
    idem: OrderedDict[str, tuple] = OrderedDict()
    idem_lock = asyncio.Lock()

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if (
            request.headers.get("content-length", "0").isdigit()
            and int(request.headers.get("content-length", 0)) > 1_100_000
        ):
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        token = cfg.capsule_token.get_secret_value()
        if (
            request.url.path.startswith("/api/")
            and token
            and not secrets.compare_digest(
                request.headers.get("authorization", ""), "Bearer " + token
            )
        ):
            return JSONResponse({"detail": "Требуется токен владельца"}, status_code=401)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "Cross-origin requests are disabled"}, status_code=403)
        if request.method in {"POST", "PATCH", "PUT"}:
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 1_100_000:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        key = request.headers.get("Idempotency-Key")
        if request.method == "POST" and key:
            if len(key) > 128:
                return JSONResponse({"detail": "Invalid idempotency key"}, status_code=400)
            body = await request.body()
            fingerprint = hashlib.sha256(request.url.path.encode() + body).hexdigest()
            async with idem_lock:
                cached = idem.get(key)
                if cached and time.monotonic() - cached[0] < 600:
                    if cached[1] != fingerprint:
                        return JSONResponse(
                            {"detail": "Idempotency key reused for another action"}, status_code=409
                        )
                    return Response(cached[2], status_code=cached[3], media_type="application/json")
                response = await call_next(request)
                content = b"".join([chunk async for chunk in response.body_iterator])
                if response.status_code < 500:
                    idem[key] = (time.monotonic(), fingerprint, content, response.status_code)
                    while (
                        len(idem) > 256 or sum(len(item[2]) for item in idem.values()) > 2_000_000
                    ):
                        idem.popitem(last=False)
                return Response(
                    content, status_code=response.status_code, headers=dict(response.headers)
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def device_status():
        return {
            "name": "Капсула Мини",
            "mode": cfg.capsule_mode,
            "hardware_profile": "unknown",
            "hardware_verification_required": True,
            "lights": lights.status(),
            "preferences": preferences.model_dump(),
            "ssh": {
                "configured": bool(cfg.capsule_ssh_host),
                "user": cfg.capsule_ssh_user,
                "port": cfg.capsule_ssh_port,
                "access_verified": False,
            },
            "voice": {
                "stt_configured": bool(cfg.vosk_model_path),
                "tts_configured": bool(cfg.piper_model_path),
                "wake_word_backend": "optional_transcript_prefix",
                "aec": "unverified",
            },
        }

    @app.get("/api/v1/health")
    async def health():
        return {"ok": True, "mode": cfg.capsule_mode, "hardware_verified": False}

    @app.get("/api/v1/device")
    async def device():
        return device_status()

    @app.get("/api/v1/bridge/status")
    async def bridge_status():
        return await bridge.status()

    class ClockRequest(BaseModel):
        enabled: bool
        brightness: int = Field(ge=0, le=100)

    @app.post("/api/v1/bridge/clock")
    async def bridge_clock(body: ClockRequest):
        return await bridge.clock(body.enabled, body.brightness)

    @app.get("/api/v1/integrations/capsula/status")
    async def capsula_status():
        return await gemini_bridge.status()

    @app.post("/api/v1/integrations/capsula/light")
    async def capsula_light(body: Zone):
        if body.effect != "steady":
            raise ValueError("API колонки поддерживает постоянный ночник; выберите Постоянный")
        return await gemini_bridge.light(body.enabled, body.color, body.brightness)

    class DeviceControl(BaseModel):
        action: Literal[
            "louder",
            "quieter",
            "mute",
            "unmute",
            "pause",
            "resume",
            "stop",
            "bluetooth_pair",
            "bluetooth_devices",
        ]

    @app.post("/api/v1/device/control")
    async def device_control(body: DeviceControl):
        commands: dict[str, tuple[str, dict[str, object]]] = {
            "louder": ("volume.adjust", {"delta": 5}),
            "quieter": ("volume.adjust", {"delta": -5}),
            "mute": ("volume.mute", {"muted": True}),
            "unmute": ("volume.mute", {"muted": False}),
            "pause": ("media.control", {"operation": "pause"}),
            "resume": ("media.control", {"operation": "play"}),
            "stop": ("media.control", {"operation": "stop"}),
            "bluetooth_pair": ("bluetooth.pair", {"timeout_seconds": 120}),
            "bluetooth_devices": ("bluetooth.devices", {}),
        }
        action, args = commands[body.action]
        return await gemini_bridge.command(action, args)

    @app.get("/api/v1/assistant/status")
    async def assistant_status():
        return router.status()

    @app.post("/api/v1/assistant/mode")
    async def assistant_mode(body: ModeRequest):
        router.mode = body.mode
        return router.status()

    @app.get("/api/v1/radio/stations")
    async def stations(query: str = ""):
        return [s.model_dump() for s in await catalog.search(query[:200])]

    @app.post("/api/v1/radio/stations")
    async def add_station(body: Station):
        return catalog.add(body)

    @app.get("/api/v1/radio/status")
    async def radio_status():
        return radio.status()

    @app.post("/api/v1/radio/play")
    async def play(body: PlayRequest):
        found = await catalog.search(body.station)
        if len(found) != 1:
            return JSONResponse(
                {
                    "detail": "Какое именно радио?" if found else "Станция не найдена",
                    "candidates": [s.model_dump() for s in found[:3]],
                },
                status_code=409 if found else 404,
            )
        return await radio.play(found[0])

    @app.post("/api/v1/radio/stop")
    async def stop():
        return await radio.stop()

    @app.post("/api/v1/radio/pause")
    async def pause():
        return await radio.pause()

    @app.post("/api/v1/radio/resume")
    async def resume():
        return await radio.resume()

    @app.post("/api/v1/radio/next")
    async def next_station():
        return await radio.step(1)

    @app.post("/api/v1/radio/previous")
    async def previous_station():
        return await radio.step(-1)

    @app.get("/api/v1/radio/favorites")
    async def favorites():
        return [
            catalog.stations[id].model_dump() for id in catalog.favorites if id in catalog.stations
        ]

    @app.post("/api/v1/radio/favorites")
    async def add_favorite(body: PlayRequest):
        if body.station not in catalog.stations:
            raise HTTPException(404, "Station not found")
        if body.station not in catalog.favorites:
            catalog.favorites.append(body.station)
        catalog.save()
        return await favorites()

    @app.delete("/api/v1/radio/favorites/{station_id}")
    async def remove_favorite(station_id: str):
        catalog.favorites = [id for id in catalog.favorites if id != station_id]
        catalog.save()
        return await favorites()

    @app.get("/api/v1/audio/status")
    async def audio_status():
        return audio.status()

    @app.post("/api/v1/audio/volume")
    async def volume(body: VolumeRequest):
        return audio.set_volume(body.value)

    @app.post("/api/v1/lights/{zone}")
    async def set_light(zone: Literal["front", "top"], body: Zone):
        return lights.set(zone, body)

    @app.post("/api/v1/preferences")
    async def set_preferences(body: Preferences):
        preferences.microphone_muted = body.microphone_muted
        preferences.wake_word = body.wake_word
        preferences_store.write(preferences.model_dump())
        return preferences

    async def execute(text: str, pcm: bytes | None = None):
        intent = parse(text, preferences.wake_word or "маруся")
        if intent.action.startswith("radio_"):
            action = intent.action.removeprefix("radio_")
            if action == "status":
                playing = radio.state not in {"IDLE", "ERROR"}
                return {
                    "text": radio.station.name if playing and radio.station else "Радио выключено",
                    "local": True,
                }
            if action == "play":
                found = await catalog.search(str(intent.value))
                if len(found) != 1:
                    names = ", ".join(station.name for station in found[:3])
                    return {
                        "text": "Уточните станцию: " + names if found else "Станция не найдена",
                        "local": True,
                    }
                result = await radio.play(found[0])
            elif action == "resume":
                if radio.last_id or radio.state == "PAUSED":
                    result = await radio.resume()
                else:
                    found = await catalog.search(cfg.radio_default_station)
                    if len(found) != 1:
                        return {"text": "Назовите радиостанцию для первого запуска", "local": True}
                    result = await radio.play(found[0])
            elif action == "stop":
                result = await radio.stop()
            elif action == "pause":
                result = await radio.pause()
            else:
                result = await radio.step(1 if action == "next" else -1)
            name = radio.station.name if radio.station else ""
            message = (
                "Подключаю " + name
                if action in {"play", "resume", "next", "previous"}
                else "Готово"
            )
            return {"text": message, "radio": result, "local": True}
        if intent.action in {"volume", "volume_delta"}:
            value = int(str(intent.value))
            result = audio.set_volume(value if intent.action == "volume" else audio.volume + value)
            if radio.state not in {"IDLE", "ERROR"}:
                await radio.set_volume(
                    radio.volume + value if intent.action == "volume_delta" else value
                )
            return {"text": "Громкость изменена", "audio_settings": result, "local": True}
        if intent.action == "stop_answer":
            await radio.stop()
            return {"text": "Озвучка остановлена", "playback": "stop", "local": True}
        answer = await router.ask(text, pcm)
        return {
            "text": answer.text,
            "audio": base64.b64encode(answer.audio).decode(),
            "model": answer.model,
            "local": False,
        }

    @app.post("/api/v1/commands")
    async def command(body: CommandRequest):
        return await execute(body.text)

    async def audio_command(pcm: bytes):
        if preferences.microphone_muted:
            raise HTTPException(403, "Микрофон выключен в приложении")
        if not pcm or len(pcm) > 960000 or len(pcm) % 2:
            raise HTTPException(400, "Нужен PCM s16le mono 16kHz, не более 30 секунд")
        async with voice_lock:
            if preferences.microphone_muted:
                raise HTTPException(403, "Микрофон выключен в приложении")
            await radio.duck(True)
            try:
                text = await asyncio.to_thread(stt.transcribe, pcm)
                if not text.strip():
                    return {"text": "Не расслышала, повторите", "local": True}
                return {**await execute(text, pcm), "transcript": text}
            finally:
                await radio.duck(False)

    @app.post("/api/v1/voice/transcribe")
    async def transcribe(request: Request):
        return await audio_command(await request.body())

    @app.websocket("/api/v1/voice/session")
    async def voice_session(ws: WebSocket):
        origin = ws.headers.get("origin")
        if origin and origin not in {
            "http://" + ws.headers.get("host", ""),
            "https://" + ws.headers.get("host", ""),
        }:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), 5)
            token = cfg.capsule_token.get_secret_value()
            if token and not secrets.compare_digest(str(hello.get("token", "")), token):
                await ws.close(code=1008)
                return
            # One explicitly submitted utterance per connection, never background recording.
            message = await asyncio.wait_for(ws.receive_json(), 35)
            encoded = message.get("pcm", "")
            if len(encoded) > 1_280_000:
                raise ValueError("Audio too large")
            await ws.send_json(await audio_command(base64.b64decode(encoded, validate=True)))
            await ws.close()
        except WebSocketDisconnect:
            pass
        except (ValueError, TimeoutError, HTTPException):
            await ws.close(code=1008)

    @app.post("/api/v1/simulation/network")
    async def network(body: dict):
        if not isinstance(player, SimulatedPlayer):
            raise HTTPException(404, "Only available in simulation")
        if not isinstance(body.get("available"), bool):
            raise HTTPException(422, "available must be boolean")
        player.network = body["available"]
        return {"available": player.network}

    web = Path(__file__).parent / "web"

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(web / "index.html")

    app.mount("/static", StaticFiles(directory=web), name="static")
    return app
