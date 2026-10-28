import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any


class SimulatedPlayer:
    """Explicit state-machine fixture; does not decode or play sound."""

    def __init__(self):
        self.connected = False
        self.paused = False
        self.volume = 35
        self.position = 0.0
        self.network = True
        self.failed_urls: set[str] = set()
        self.url = ""

    async def start(self, url: str, volume: int):
        self.url, self.volume, self.position = url, volume, 0
        self.connected, self.paused = True, False

    async def command(self, *args):
        if args[0] == "set_property":
            if args[1] == "pause":
                self.paused = args[2]
            elif args[1] == "volume":
                self.volume = args[2]

    async def progress(self) -> float | None:
        if not self.connected or not self.network or self.url in self.failed_urls:
            return None
        if not self.paused:
            self.position += 1
        return self.position

    async def close(self):
        self.connected = False


class MpvPlayer:
    """One mpv process, no shell, bounded IPC and decoder startup time."""

    def __init__(self, audio_output: str = "auto"):
        self.process: asyncio.subprocess.Process | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.temp: tempfile.TemporaryDirectory | None = None
        self.request = 0
        self.lock = asyncio.Lock()
        self.audio_output = audio_output

    async def start(self, url: str, volume: int):
        await self.close()
        self.temp = tempfile.TemporaryDirectory(prefix="capsule-mpv-")
        socket = Path(self.temp.name) / "ipc"
        try:
            self.process = await asyncio.create_subprocess_exec(
                "mpv",
                "--no-config",
                "--no-video",
                "--no-terminal",
                "--idle=yes",
                "--load-scripts=no",
                "--ytdl=no",
                "--cache=yes",
                "--cache-secs=10",
                "--demuxer-max-bytes=8MiB",
                "--demuxer-max-back-bytes=1MiB",
                f"--ao={self.audio_output}",
                f"--volume={volume}",
                f"--input-ipc-server={socket}",
                "--",
                url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(6):
                while not socket.exists():
                    if self.process.returncode is not None:
                        raise RuntimeError("mpv exited before IPC became available")
                    await asyncio.sleep(0.05)
                self.reader, self.writer = await asyncio.open_unix_connection(str(socket))
        except BaseException:
            await self.close()
            raise

    async def command(self, *args) -> Any:
        async with self.lock:
            if not self.writer or not self.reader:
                raise RuntimeError("Player is disconnected")
            self.request += 1
            self.writer.write(
                (json.dumps({"command": args, "request_id": self.request}) + "\n").encode()
            )
            await self.writer.drain()
            async with asyncio.timeout(3):
                while True:
                    line = await self.reader.readline()
                    if not line:
                        raise RuntimeError("Player IPC closed")
                    reply = json.loads(line)
                    if reply.get("request_id") == self.request:
                        if reply.get("error") != "success":
                            return None
                        return reply.get("data")

    async def progress(self) -> float | None:
        if not self.process or self.process.returncode is not None:
            return None
        value = await self.command("get_property", "playback-time")
        return float(value) if value is not None else None

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except (BrokenPipeError, ConnectionError):
                pass
        self.writer = self.reader = None
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
        if self.temp:
            self.temp.cleanup()
        self.temp = None
