import re
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, field_validator

from capsule.storage import Store


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е").replace("fm", "фм")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\b(маруся|включи|поставь|пожалуйста|радио|радиостанцию)\b", " ", text)
    return " ".join(text.split())


def stream_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("Only HTTP(S) stream URLs without credentials are supported")
    return value


class Station(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    urls: list[str] = Field(default_factory=list, max_length=12)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    source: Literal["radio-browser", "owner", "simulation"] = "owner"
    country: str = ""
    language: str = ""
    verified_at: str | None = None

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, values):
        return [stream_url(value) for value in values]


SEEDS = [
    Station(id="dacha", name="Радио Дача", aliases=["дача", "дачу"], source="simulation"),
    Station(id="russkoe", name="Русское Радио", aliases=["русское"], source="simulation"),
    Station(id="avto", name="Авторадио", aliases=["авто", "авторадио"], source="simulation"),
    Station(id="retro", name="Ретро FM", aliases=["ретро", "ретро фм"], source="simulation"),
]


class Catalog:
    def __init__(self, store: Store, directory: str, simulation: bool):
        self.store, self.directory, self.simulation = store, directory.rstrip("/"), simulation
        data = store.read()
        self.stations = {s.id: s for s in (Station(**row) for row in data.get("stations", []))}
        if not simulation:
            self.stations = {id: s for id, s in self.stations.items() if s.source != "simulation"}
        if simulation:
            for s in SEEDS:
                self.stations.setdefault(s.id, s.model_copy(deep=True))
        self.favorites: list[str] = [id for id in data.get("favorites", []) if id in self.stations]
        self.directory_available: bool | None = None

    def save(self):
        self.store.write(
            {
                "stations": [s.model_dump() for s in self.stations.values()],
                "favorites": self.favorites,
            }
        )

    def add(self, station: Station):
        if not self.simulation and station.source == "simulation":
            raise ValueError("Simulation station is not playable in host mode")
        self.stations[station.id] = station
        self.save()
        return station

    def local(self, query: str) -> list[Station]:
        if not query.strip():
            return sorted(self.stations.values(), key=lambda s: s.id not in self.favorites)
        if query in self.stations:
            return [self.stations[query]]
        q = normalize(query)
        ranked = []
        for station in self.stations.values():
            names = [normalize(station.name), *[normalize(a) for a in station.aliases]]
            score = max(SequenceMatcher(None, q, n).ratio() for n in names)
            if score >= 0.72:
                ranked.append((score, station.id in self.favorites, station))
        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        if ranked and ranked[0][0] == 1:
            return [row[2] for row in ranked if row[0] == 1]
        return [row[2] for row in ranked[:3]]

    async def search(self, query: str) -> list[Station]:
        local = self.local(query)
        if local or self.simulation or not query.strip():
            return local
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                response = await client.get(
                    self.directory + "/json/stations/search",
                    params={
                        "name": normalize(query),
                        "hidebroken": "true",
                        "limit": 20,
                        "order": "votes",
                        "reverse": "true",
                    },
                    headers={"User-Agent": "VK-Capsule-Mini-Extended/0.1"},
                )
                response.raise_for_status()
                rows = response.json()
            self.directory_available = True
            result = []
            for row in rows:
                url = row.get("url_resolved") or row.get("url")
                if not url:
                    continue
                try:
                    station = Station(
                        id=row["stationuuid"],
                        name=row["name"],
                        urls=[url],
                        source="radio-browser",
                        country=row.get("country", ""),
                        language=row.get("language", ""),
                    )
                except (ValueError, KeyError):
                    continue
                self.stations[station.id] = station
                result.append(station)
            self.save()
            return result[:3]
        except (httpx.HTTPError, ValueError):
            self.directory_available = False
            return []
