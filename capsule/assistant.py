import asyncio
import time
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass
class Answer:
    text: str
    audio: bytes = b""
    model: str | None = None


class ProviderError(Exception):
    def __init__(self, code: int, retry_after: float = 0):
        self.code, self.retry_after = code, max(0, retry_after)
        super().__init__(f"Provider error {code}")


class Provider(Protocol):
    async def answer(self, text: str, pcm: bytes | None = None) -> Answer: ...


class Unconfigured:
    async def answer(self, text: str, pcm: bytes | None = None) -> Answer:
        raise ProviderError(503)


class Router:
    def __init__(self, primary: Provider, fallback: Provider, cooldown=120, clock=time.monotonic):
        self.primary, self.fallback = primary, fallback
        self.cooldown, self.clock = cooldown, clock
        self.mode: Literal["auto", "live_only", "fallback_only"] = "auto"
        self.state = "OFFLINE_COMMANDS_ONLY"
        self.active_model: str | None = None
        self.blocked_until = {"primary": 0.0, "fallback": 0.0}
        self.errors: dict[str, int] = {}
        self.failures = 0
        self.reason = "availability_not_checked"
        self.lock = asyncio.Lock()

    def status(self):
        return {
            "state": self.state,
            "active_model": self.active_model,
            "mode": self.mode,
            "reason": self.reason,
            "failures": self.failures,
            "retry_in": {
                name: max(0, round(at - self.clock())) for name, at in self.blocked_until.items()
            },
            "errors": self.errors,
            "quota_remaining": None,
        }

    async def ask(self, text: str, pcm: bytes | None = None) -> Answer:
        async with self.lock:
            names = {
                "auto": ["primary", "fallback"],
                "live_only": ["primary"],
                "fallback_only": ["fallback"],
            }[self.mode]
            for name in names:
                if self.blocked_until[name] > self.clock():
                    continue
                provider = self.primary if name == "primary" else self.fallback
                for attempt in range(2):
                    try:
                        async with asyncio.timeout(45):
                            result = await provider.answer(text, pcm)
                        self.state = "PRIMARY_LIVE" if name == "primary" else "FALLBACK_FLASH_LITE"
                        self.active_model = result.model
                        self.errors.pop(name, None)
                        self.reason = "available" if name == "primary" else "primary_unavailable"
                        return result
                    except (ProviderError, TimeoutError) as exc:
                        code = exc.code if isinstance(exc, ProviderError) else 504
                        wait = exc.retry_after if isinstance(exc, ProviderError) else 0
                        if code in {500, 502, 504} and attempt == 0:
                            await asyncio.sleep(0.15)
                            continue
                        self.failures += 1
                        self.errors[name] = code
                        # Authentication faults require owner intervention, not quota retry storms.
                        self.blocked_until[name] = self.clock() + max(
                            wait, 3600 if code in {401, 403} else self.cooldown
                        )
                        self.reason = (
                            "authentication_required" if code in {401, 403} else f"http_{code}"
                        )
                        break
            self.state, self.active_model = "OFFLINE_COMMANDS_ONLY", None
            return Answer("Сейчас не могу ответить. Проверьте настройки ИИ или попробуйте позже.")
