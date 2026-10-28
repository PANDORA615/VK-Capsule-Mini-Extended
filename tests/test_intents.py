import pytest

from capsule.intents import parse


@pytest.mark.parametrize(
    "phrase,action,value",
    [
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
