import asyncio

import pytest

from capsule.catalog import Catalog, Station
from capsule.player import SimulatedPlayer
from capsule.radio import Radio
from capsule.storage import Store


async def until(predicate, seconds=3):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.fixture
def radio(tmp_path):
    cat = Catalog(Store(tmp_path / "catalog.json"), "http://unused.invalid", True)
    return Radio(
        cat,
        Store(tmp_path / "radio.json"),
        SimulatedPlayer(),
        poll=0.005,
        watchdog=0.015,
        retry_cap=0.01,
    )


async def test_play_pause_duck_safe_volume_persist_and_reboot(radio):
    await radio.play(radio.catalog.stations["dacha"])
    await until(lambda: radio.state == "PLAYING")
    assert radio.last_id == "dacha"
    await radio.set_volume(100)
    assert radio.volume == 75
    await radio.duck(True)
    await radio.duck(True)
    assert radio.player.volume == 12
    await radio.duck(False)
    assert radio.player.volume == 12
    await radio.duck(False)
    assert radio.player.volume == 75
    await radio.pause()
    assert radio.state == "PAUSED"
    await radio.resume()
    await until(lambda: radio.state == "PLAYING")
    radio.resume_after_reboot = True
    radio.save()
    await radio.stop()
    new = Radio(radio.catalog, radio.store, SimulatedPlayer(), poll=0.005)
    await new.startup()
    await until(lambda: new.state == "PLAYING")
    assert new.station.id == "dacha" and new.volume == 75
    await new.stop()
    assert not new.player.connected


async def test_disconnect_alternate_url_recovery(radio):
    station = Station(
        id="dual", name="Two URLs", urls=["https://one.invalid/live", "https://two.invalid/live"]
    )
    radio.player.failed_urls.add(station.urls[0])
    await radio.play(station)
    await until(lambda: radio.state == "PLAYING")
    assert radio.player.url == station.urls[1] and radio.reconnects >= 1
    radio.player.network = False
    await until(lambda: radio.state == "RECONNECTING")
    radio.player.network = True
    await until(lambda: radio.state == "PLAYING")
    assert radio.error is None
    await radio.stop()


async def test_switch_has_one_active_player(radio):
    await asyncio.gather(*[radio.play(s) for s in radio.catalog.stations.values()])
    await until(lambda: radio.state == "PLAYING")
    assert radio.station.id == "retro"
    assert radio.history == ["retro"]
    await radio.stop()


async def test_24_hours_virtual_clock_with_two_minute_outages(radio):
    # 86,400 virtual seconds, no claim of a real-time 24h hardware/decoder soak.
    now = 0.0

    async def virtual_sleep(seconds):
        nonlocal now
        now += seconds
        radio.player.network = not (600 <= now < 720 or 43200 <= now < 43320)
        await asyncio.sleep(0)

    radio.poll, radio.watchdog, radio.retry_cap = 1, 20, 30
    radio.sleep = virtual_sleep
    await radio.play(radio.catalog.stations["avto"])
    while now < 86400:
        await asyncio.sleep(0)
    assert radio.state == "PLAYING"
    assert radio.reconnects > 0 and radio.player.connected
    assert len(radio.events) <= 40 and len(radio.history) <= 20
    await radio.stop()
