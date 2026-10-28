import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    action: str
    value: str | int | None = None


def parse(text: str, wake_word: str = "маруся") -> Intent:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(rf"^\s*{re.escape(wake_word)}\b", "", text)
    text = re.sub(r"\bпожалуйста\b", "", text)
    text = " ".join(text.split())
    if text in {"стоп", "выключи", "выключи радио", "останови радио", "хватит", "останови"}:
        return Intent("stop")
    if text in {"пауза", "приостанови радио", "поставь на паузу", "пауза радио"}:
        return Intent("pause")
    if text in {
        "продолжи",
        "продолжи радио",
        "включи радио",
        "включи то радио что было вчера",
        "включи последнее радио",
        "поставь радио",
    }:
        return Intent("resume")
    if text in {"что играет", "какое радио играет", "что за станция"}:
        return Intent("status")
    if text in {"громче", "погромче", "сделай погромче", "сделай громче", "прибавь громкость"}:
        return Intent("volume_delta", 10)
    if text in {"тише", "потише", "сделай тише", "сделай потише", "убавь громкость"}:
        return Intent("volume_delta", -10)
    match = re.fullmatch(
        r"(?:сделай |установи )?громкость (\d{1,3})(?: процентов| процента| процент)?", text
    )
    if match and 0 <= int(match[1]) <= 100:
        return Intent("volume", int(match[1]))
    if text in {"следующая станция", "другое радио", "следующее радио"}:
        return Intent("next")
    if text in {"предыдущая станция", "предыдущее радио"}:
        return Intent("previous")
    match = re.fullmatch(r"(?:включи|поставь|запусти)\s+(.+)", text)
    if match:
        return Intent("play", match[1])
    return Intent("question", text)
