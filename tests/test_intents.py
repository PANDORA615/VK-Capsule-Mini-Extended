import pytest

from capsule.intents import parse


@pytest.mark.parametrize(
    "phrase,action,value",
    [
        ("Маруся, включи Радио Дача", "play", "радио дача"),
        ("Маруся поставь Дачу", "play", "дачу"),
        ("Включи Русское Радио", "play", "русское радио"),
        ("Поставь Авторадио", "play", "авторадио"),
        ("Маруся включи Ретро FM", "play", "ретро fm"),
        ("Запусти радио Джаз", "play", "радио джаз"),
        ("Маруся, включи радио, пожалуйста", "resume", None),
        ("Маруся включи то радио что было вчера", "resume", None),
        ("включи последнее радио", "resume", None),
        ("продолжи радио", "resume", None),
        ("продолжи", "resume", None),
        ("поставь радио", "resume", None),
        ("Маруся стоп", "stop", None),
        ("выключи радио", "stop", None),
        ("Маруся выключи", "stop", None),
        ("останови радио", "stop", None),
        ("хватит", "stop", None),
        ("пауза", "pause", None),
        ("поставь на паузу", "pause", None),
        ("приостанови радио", "pause", None),
        ("сделай погромче", "volume_delta", 10),
        ("Маруся громче", "volume_delta", 10),
        ("погромче", "volume_delta", 10),
        ("прибавь громкость", "volume_delta", 10),
        ("Маруся тише", "volume_delta", -10),
        ("сделай потише", "volume_delta", -10),
        ("убавь громкость", "volume_delta", -10),
        ("потише", "volume_delta", -10),
        ("Маруся громкость 40 процентов", "volume", 40),
        ("установи громкость 0", "volume", 0),
        ("сделай громкость 75", "volume", 75),
        ("что играет", "status", None),
        ("какое радио играет", "status", None),
        ("другое радио", "next", None),
        ("предыдущая станция", "previous", None),
        ("расскажи про космос", "question", "расскажи про космос"),
        ("громкость 999", "question", "громкость 999"),
    ],
)
def test_commands(phrase, action, value):
    result = parse(phrase)
    assert (result.action, result.value) == (action, value)


def test_custom_wake_word():
    assert parse("капсула, стоп", "капсула").action == "stop"
