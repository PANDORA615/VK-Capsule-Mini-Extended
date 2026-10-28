import asyncio
import math
import shutil
import struct
import threading
import wave
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from capsule.player import MpvPlayer


@pytest.mark.skipif(not shutil.which("mpv"), reason="mpv not installed")
async def test_real_http_mpv_decode_pause_volume_cleanup(tmp_path):
    # Real local HTTP and decoder; synthetic tone to null sink, no speaker claim.
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(1500 * math.sin(2 * math.pi * 440 * i / 16000)))
                for i in range(64000)
            )
        )

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    player = MpvPlayer("null")
    try:
        await player.start(f"http://127.0.0.1:{server.server_port}/tone.wav", 35)
        async with asyncio.timeout(6):
            while (await player.progress() or 0) < 0.2:
                await asyncio.sleep(0.05)
        await player.command("set_property", "pause", True)
        assert await player.command("get_property", "pause") is True
        await player.command("set_property", "volume", 20)
        assert await player.command("get_property", "volume") == 20
    finally:
        await player.close()
        server.shutdown()
        server.server_close()
        thread.join()
    assert player.process is None
