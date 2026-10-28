import pytest

from capsule.intents import parse


@pytest.mark.parametrize(
    "phrase,action,value",
    [
        ("включи радио Дача", "radio_play", "радио дача"),
        ("включи радио", "radio_resume", None),
        ("выключи радио", "radio_stop", None),
        ("поставь радио на паузу", "radio_pause", None),
        ("включи свет на кухне", "question", "включи свет на кухне"),
        ("громче", "volume_delta", 10),
        ("погромче", "volume_delta", 10),
        ("Маруся сделай погромче", "volume_delta", 10),
        ("тише", "volume_delta", -10),
        ("сделай потише", "volume_delta", -10),
        ("убавь громкость", "volume_delta", -10),
        ("громкость 40 процентов", "volume", 40),
        ("установи громкость 0", "volume", 0),
        ("сделай громкость 75", "volume", 75),
        ("стоп", "stop_answer", None),
        ("останови ответ", "stop_answer", None),
        ("объясни почему небо голубое", "question", "объясни почему небо голубое"),
        ("громкость 999", "question", "громкость 999"),
    ],
)
def test_commands(phrase, action, value):
    intent = parse(phrase)
    assert (intent.action, intent.value) == (action, value)


def test_custom_or_empty_prefix():
    assert parse("капсула, тише", "Капсула").action == "volume_delta"
    assert parse("почему идёт дождь", "").action == "question"
