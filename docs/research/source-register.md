# Реестр источников

Проверено 28 октября 2026. Публикация — свидетельство автора, а не проверка нашей колонки.

| Источник | Результат | Статус проекта |
|---|---|---|
| [cmp18, Debian live, 23.08.2026](https://debianlive.ru/2026/08/vk-mini-legacy-amlogic-a113x-часть-1-ставим-alpine-со-свежим-майнла/) | Автор описывает Alpine на A113X, UART и различия плат; его результат нельзя переносить на RK3308B | `hardware_verification_required` |
| [Google Models](https://ai.google.dev/gemini-api/docs/models) | В каталоге есть `gemini-3.8-live`, `gemini-3.5-flash-lite` | Документация проверена; API с ключом владельца не проверен |
| [Google Live](https://ai.google.dev/gemini-api/docs/live-api/capabilities) | Официальный SDK; PCM s16le mono 16 kHz вход, 24 kHz выход | Контрактные проверки; внешний сервис `unverified` |
| [Google Pricing](https://ai.google.dev/gemini-api/docs/pricing) | Квоты и тарифы зависят от модели/проекта, fallback не гарантирует бесплатности | Проверять перед эксплуатацией |
| [Radio Browser API](https://api.radio-browser.info/) | Публичный каталог; доступность/права конкретного потока проверяет владелец | HTTP-адаптер и кэш |
| [Yandex Station Extended](https://github.com/Marker284/yandex-station-extended) | Структурный ориентир документации, CC BY 4.0; не инструкция для VK | Код/образы не заимствованы |
| [Vosk](https://alphacephei.com/vosk/), [Piper](https://github.com/OHF-Voice/piper1-gpl) | Опциональные локальные движки; модели устанавливаются владельцем с учётом лицензий | Без моделей `unverified` |

Нет подтверждённых VID/PID, GPIO, адресов I²C, разделов или универсального образа. Не выдумывать их.

Дополнительно предоставлено владельцем и изучено в этой сессии:

| Источник | Что найдено | Проверка |
|---|---|---|
| [yawaflua/Gemini-for-Capsula](https://github.com/yawaflua/Gemini-for-Capsula) | ALSA-агент, seg7/line-display, LED-кольцо, panel API `light.night`; исходники с Apache-2.0 заголовками | Наш отдельный адаптер проверен контрактно; железо unverified |
| [v3rt3p/marusya-server](https://github.com/v3rt3p/marusya-server) | API devices, clockEnabled/clockBrightness, GPL-3.0 LICENSE | Код не включён; отдельный HTTP-адаптер |
| [inmyuse/marusia](https://github.com/inmyuse/marusia) | React/Vite/3D-витрина, non-commercial LICENSE | Не является драйвером; ассеты не использованы |
| [LibreCapsula](https://t.me/librecapsula) | Карточка Telegram-группы | Сообщения недоступны; технические утверждения unverified |
