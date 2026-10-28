# Участие

Python 3.12+, `pip install -e '.[dev,ai]'`. Перед PR: `ruff check capsule tests scripts`, `ruff format --check capsule tests scripts`, `mypy capsule`, `pytest -q`. Для реального декодера нужен mpv; без него тест явно skipped. Проверка UI требует Chromium и запущенного сервера в simulation.

Для аппаратных результатов приложите ревизию платы, версии ядра/агента, условия измерения и обезличенный отчёт. Не превращайте `simulated` в `verified` без измерения. Не добавляйте чужие бинарники, proprietary wake-word веса, дампы и адреса разделов без источника/лицензии. Не добавляйте пустые каталоги вместо работающего кода.
