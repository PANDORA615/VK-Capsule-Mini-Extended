import asyncio
import random
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal

from capsule.catalog import Catalog, Station
from capsule.player import MpvPlayer, SimulatedPlayer
from capsule.storage import Store

State = Literal["IDLE", "CONNECTING", "PLAYING", "BUFFERING", "PAUSED", "RECONNECTING", "ERROR"]


class Radio:
    def __init__(
        self,
        catalog: Catalog,
        store: Store,
        player: MpvPlayer | SimulatedPlayer,
        max_volume=75,
        resume=False,
        poll=1.0,
        watchdog=20.0,
        retry_cap=30.0,
        sleep=asyncio.sleep,
    ):
        self.catalog, self.store, self.player = catalog, store, player
        data = store.read()
        self.max_volume = max_volume
        self.volume = min(max(0, data.get("volume", 35)), max_volume)
        self.last_id = data.get("last_id")
        self.history: list[str] = data.get("history", [])[-20:]
        self.resume_after_reboot = data.get("resume_after_reboot", resume)
        self.state: State = "IDLE"
        self.station: Station | None = None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.poll, self.watchdog, self.retry_cap = poll, watchdog, retry_cap
        self.reconnects = 0
        self.error: str | None = None
        self.duck_depth = 0
        self.url_index = 0
        self.events: list[dict] = []
        self.sleep = sleep

    def event(self, state: State):
        self.state = state
        self.events.append({"state": state, "at": datetime.now(UTC).isoformat()})
        self.events = self.events[-40:]

    def save(self):
        self.store.write(
            {
                "last_id": self.last_id,
                "history": self.history[-20:],
                "volume": self.volume,
                "resume_after_reboot": self.resume_after_reboot,
            }
        )

    def status(self):
        return {
            "state": self.state,
            "station": self.station.model_dump() if self.station else None,
            "volume": self.volume,
            "effective_volume": self.effective_volume,
            "max_volume": self.max_volume,
            "last_id": self.last_id,
            "resume_after_reboot": self.resume_after_reboot,
            "reconnects": self.reconnects,
            "error": self.error,
            "events": self.events,
            "track": None,
            "simulation": isinstance(self.player, SimulatedPlayer),
        }

    @property
    def effective_volume(self):
        return min(self.volume, 12) if self.duck_depth else self.volume

    async def startup(self):
        if self.resume_after_reboot and self.last_id in self.catalog.stations:
            await self.play(self.catalog.stations[self.last_id])

    async def _stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.task = None
        await self.player.close()

    async def play(self, station: Station):
        if not isinstance(self.player, SimulatedPlayer) and not station.urls:
            raise ValueError("Station has no verified candidate URL; search or add a stream first")
        async with self.lock:
            await self._stop()
            self.station, self.error, self.url_index = station, None, 0
            self.event("CONNECTING")
            self.task = asyncio.create_task(self._run(station))
        return self.status()

    async def _run(self, station: Station):
        urls = station.urls or [f"simulated:{station.id}"]
        failures = 0
        try:
            while True:
                try:
                    await self.player.start(urls[self.url_index % len(urls)], self.effective_volume)
                    previous = None
                    stalled = 0.0
                    verified = False
                    while True:
                        await self.sleep(self.poll)
                        if self.state == "PAUSED":
                            continue
                        progress = await self.player.progress()
                        if (
                            progress is not None
                            and progress > 0
                            and (previous is None or progress > previous)
                        ):
                            previous, stalled = progress, 0
                            self.error = None
                            self.event("PLAYING") if self.state != "PLAYING" else None
                            if not verified:
                                verified, failures = True, 0
                                self.last_id = station.id
                                if not self.history or self.history[-1] != station.id:
                                    self.history.append(station.id)
                                    self.history = self.history[-20:]
                                station.verified_at = datetime.now(UTC).isoformat()
                                self.catalog.save()
                                self.save()
                        else:
                            stalled += self.poll
                            if self.state == "PLAYING":
                                self.event("BUFFERING")
                            if stalled >= self.watchdog:
                                raise TimeoutError("No decoder progress")
                except FileNotFoundError:
                    self.error = "mpv не установлен. Установите mpv на Linux-сервере."
                    self.event("ERROR")
                    return
                except (OSError, RuntimeError, TimeoutError, ConnectionError):
                    await self.player.close()
                    failures += 1
                    self.reconnects += 1
                    self.url_index += 1
                    self.error = "Поток недоступен. Повторное подключение…"
                    self.event("RECONNECTING")
                    delay = min(self.retry_cap, 2 ** min(failures - 1, 8))
                    await self.sleep(delay + random.uniform(0, min(0.3, delay / 10)))
        finally:
            await self.player.close()

    async def stop(self):
        async with self.lock:
            await self._stop()
            self.event("IDLE")
            self.error = None
        return self.status()

    async def pause(self):
        async with self.lock:
            if self.state not in {"PLAYING", "BUFFERING"}:
                raise ValueError("Сначала включите радио")
            await self.player.command("set_property", "pause", True)
            self.event("PAUSED")
        return self.status()

    async def resume(self):
        async with self.lock:
            if self.state == "PAUSED":
                await self.player.command("set_property", "pause", False)
                self.event("CONNECTING")
                return self.status()
        station = self.catalog.stations.get(self.last_id or "")
        if station is None:
            raise ValueError("Выберите радиостанцию")
        return await self.play(station)

    async def set_volume(self, value: int):
        async with self.lock:
            self.volume = max(0, min(value, self.max_volume))
            if self.state in {"PLAYING", "BUFFERING", "PAUSED"}:
                await self.player.command("set_property", "volume", self.effective_volume)
            self.save()
        return self.status()

    async def duck(self, active: bool):
        async with self.lock:
            self.duck_depth = max(0, self.duck_depth + (1 if active else -1))
            if self.state in {"PLAYING", "BUFFERING", "PAUSED"}:
                await self.player.command("set_property", "volume", self.effective_volume)

    async def step(self, direction: int):
        ids = self.catalog.favorites or list(self.catalog.stations)
        if not ids:
            raise ValueError("Нет сохранённых станций")
        current = self.station.id if self.station else self.last_id
        index = ids.index(current) if current in ids else -1
        return await self.play(self.catalog.stations[ids[(index + direction) % len(ids)]])
