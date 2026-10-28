"""Original HTTP adapter to the published marusya-server API; no upstream code bundled."""

import asyncio
from urllib.parse import quote

import httpx


class MarusyaBridge:
    def __init__(self, url: str, device_id: str, transport=None):
        self.url, self.device_id, self.transport = url.rstrip("/"), device_id, transport
        self.lock = asyncio.Lock()

    @property
    def configured(self):
        return bool(self.url and self.device_id)

    async def _device(self, client):
        response = await client.get(self.url + "/devices")
        response.raise_for_status()
        for device in response.json():
            if device.get("id") == self.device_id:
                return device
        raise ValueError("Указанная колонка отсутствует на marusya-server")

    async def status(self):
        if not self.configured:
            return {"configured": False, "hardware_verified": False}
        try:
            async with httpx.AsyncClient(timeout=6, transport=self.transport) as client:
                device = await self._device(client)
            general = device["config"]["settings"]["general"]
            return {
                "configured": True,
                "reachable": True,
                "clock_enabled": bool(general["clockEnabled"]),
                "clock_brightness": general["clockBrightness"],
                "hardware_verified": False,
                "top_led_supported": False,
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {"configured": True, "reachable": False, "hardware_verified": False}

    async def clock(self, enabled: bool, brightness: int):
        if not self.configured:
            raise ValueError("Настройте MARUSYA_SERVER_URL и MARUSYA_DEVICE_ID")
        if not 0 <= brightness <= 100:
            raise ValueError("Яркость должна быть от 0 до 100")
        async with self.lock:
            try:
                async with httpx.AsyncClient(timeout=8, transport=self.transport) as client:
                    device = await self._device(client)
                    config = device["config"]
                    general = config["settings"]["general"]
                    general.update(
                        clockEnabled=enabled,
                        clockBrightness=brightness,
                        revision=general["revision"] + 1,
                    )
                    response = await client.patch(
                        self.url + "/devices/" + quote(self.device_id, safe=""),
                        json={"config": config},
                    )
                    response.raise_for_status()
            except (httpx.HTTPError, KeyError, TypeError):
                raise ValueError("marusya-server недоступен или его API изменился") from None
        # Upstream does not report physical delivery. Do not claim the display changed.
        return {"accepted_by_server": True, "hardware_acknowledged": False}


class GeminiCapsulaBridge:
    """Published yawaflua panel contract; only explicit device controls are exposed."""

    def __init__(self, url: str, device_id: str, password: str, transport=None):
        self.url, self.device_id, self.password = url.rstrip("/"), device_id, password
        self.transport = transport

    @property
    def configured(self):
        return bool(self.url and self.device_id and self.password)

    async def _session(self, client):
        result = await client.post(self.url + "/panel/api/login", json={"password": self.password})
        result.raise_for_status()
        result = await client.get(self.url + "/panel/api/state")
        result.raise_for_status()
        for device in result.json()["devices"]:
            if device["device_id"] == self.device_id:
                return device
        raise ValueError("Колонка не подключена к Gemini-for-Capsula")

    async def status(self):
        if not self.configured:
            return {"configured": False, "hardware_verified": False}
        try:
            async with httpx.AsyncClient(
                timeout=10, transport=self.transport, headers={"X-Marusya-Panel": "1"}
            ) as client:
                device = await self._session(client)
            return {
                "configured": True,
                "connected": True,
                "night_light_supported": "light.night" in device["capabilities"],
                "capabilities": device["capabilities"],
                "hardware_verified": False,
            }
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return {"configured": True, "connected": False, "hardware_verified": False}

    async def command(self, action: str, args: dict):
        allowed = {
            "volume.adjust",
            "volume.mute",
            "media.control",
            "bluetooth.pair",
            "bluetooth.devices",
        }
        if action not in allowed:
            raise ValueError("Команда не разрешена через веб-панель")
        if not self.configured:
            raise ValueError("Настройте адрес, ID и пароль панели агента в .env")
        try:
            async with httpx.AsyncClient(
                timeout=15, transport=self.transport, headers={"X-Marusya-Panel": "1"}
            ) as client:
                device = await self._session(client)
                if action not in device["capabilities"]:
                    raise ValueError("Агент не объявил поддержку " + action)
                result = await client.post(
                    self.url
                    + "/panel/api/devices/"
                    + quote(device["session"], safe="")
                    + "/command",
                    json={"action": action, "args": args},
                )
                result.raise_for_status()
                payload = result.json()
                if not payload.get("ok"):
                    raise ValueError("Агент не подтвердил команду")
                return {"agent_acknowledged": True, "data": payload.get("data", {})}
        except (httpx.HTTPError, KeyError, TypeError):
            raise ValueError("Не удалось выполнить команду через аппаратный агент") from None

    async def light(self, on: bool, color: str, brightness: int):
        if not self.configured:
            raise ValueError("Настройте GEMINI_CAPSULA_URL, DEVICE_ID и PANEL_PASSWORD в .env")
        try:
            async with httpx.AsyncClient(
                timeout=15, transport=self.transport, headers={"X-Marusya-Panel": "1"}
            ) as client:
                device = await self._session(client)
                if "light.night" not in device["capabilities"]:
                    raise ValueError("Агент колонки не объявил поддержку light.night")
                result = await client.post(
                    self.url
                    + "/panel/api/devices/"
                    + quote(device["session"], safe="")
                    + "/command",
                    json={
                        "action": "light.night",
                        "args": {
                            "on": on and brightness > 0,
                            "color": color.removeprefix("#"),
                            "brightness": max(1, brightness),
                        },
                    },
                )
                result.raise_for_status()
                if not result.json().get("ok"):
                    raise ValueError("Агент не подтвердил выполнение команды")
        except (httpx.HTTPError, KeyError, TypeError):
            raise ValueError(
                "Ошибка Gemini-for-Capsula: проверьте адрес, пароль панели и подключение агента"
            ) from None
        return {"agent_acknowledged": True, "physical_light_observed": False}
