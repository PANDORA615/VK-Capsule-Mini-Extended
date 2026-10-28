import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    action: str
    value: str | int | None = None


def parse(text: str, wake_word: str = "маруся") -> Intent:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    if wake_word.strip():
        prefix = " ".join(wake_word.lower().replace("ё", "е").split())
        text = re.sub(rf"^\s*{re.escape(prefix)}\b", "", text)
    text = re.sub(r"\bпожалуйста\b", "", text)
    text = " ".join(text.split())
    if text in {"стоп", "хватит", "останови ответ", "замолчи"}:
        return Intent("stop_answer")
    if text in {"громче", "погромче", "сделай погромче", "сделай громче", "прибавь громкость"}:
        return Intent("volume_delta", 10)
    if text in {"тише", "потише", "сделай тише", "сделай потише", "убавь громкость"}:
        return Intent("volume_delta", -10)
    match = re.fullmatch(
        r"(?:сделай |установи )?громкость (\d{1,3})(?: процентов| процента| процент)?", text
    )
    if match and 0 <= int(match[1]) <= 100:
        return Intent("volume", int(match[1]))
    return Intent("question", text)
