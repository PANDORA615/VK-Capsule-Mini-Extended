import pytest

from capsule.assistant import Answer, ProviderError, Router


class Fake:
    def __init__(self, code=None, retry=0):
        self.code, self.retry, self.calls = code, retry, 0

    async def answer(self, text, pcm=None):
        self.calls += 1
        if self.code:
            raise ProviderError(self.code, self.retry)
        return Answer("Ответ", model="contract-fixture")


async def test_429_fallback_retry_after_and_recover_on_next_turn():
    now = 0
    live, flash = Fake(429, 300), Fake()
    router = Router(live, flash, clock=lambda: now)
    await router.ask("Вопрос")
    assert router.state == "FALLBACK_FLASH_LITE" and live.calls == 1
    now = 200
    await router.ask("Ещё вопрос")
    assert live.calls == 1
    now = 301
    live.code = None
    await router.ask("Новая фраза")
    assert router.state == "PRIMARY_LIVE" and live.calls == 2


@pytest.mark.parametrize("code", [401, 403])
async def test_auth_error_is_not_quota(code):
    router = Router(Fake(code), Fake(429))
    await router.ask("Вопрос")
    assert router.status()["errors"]["primary"] == code
    assert router.status()["retry_in"]["primary"] > 3500
    assert router.state == "OFFLINE_COMMANDS_ONLY"


async def test_shared_quota_offline_and_no_repeated_probes():
    live, flash = Fake(429), Fake(429)
    router = Router(live, flash)
    assert "радио работает" in (await router.ask("Вопрос")).text
    await router.ask("Другой вопрос")
    assert live.calls == flash.calls == 1


async def test_manual_mode():
    live, flash = Fake(), Fake()
    router = Router(live, flash)
    router.mode = "fallback_only"
    await router.ask("Вопрос")
    assert live.calls == 0 and flash.calls == 1
