Русский | [English](README.en.md)

# TgAutoS

Telethon userbot scripts for the TgAuto Android app: https://github.com/vipa-ch-cloud/TgAuto

Выберите папку с этими скриптами в приложении (вкладка «Скрипты»). Каждый скрипт лежит в своей папке: `<id>.py`, README и `config.schema.json`.

| Папка | Что делает |
|---|---|
| `automod/` | Автомодерация чатов Telegram с помощью LLM. См. `automod/README.md`. |
| `autoresponder/` | Автоответчик для личного аккаунта. См. `autoresponder/README.md`. |

## Формат config.schema.json
Файл рядом со скриптом включает кнопку «Конфиг» в приложении. Схема описывает разделы и поля (переключатели, числа, текст, списки, выбор), приложение рисует форму и записывает только изменённые ключи в конфиг скрипта. Поля с именами, похожими на секреты (ключи, пароли, токены), не показываются. Необязательные поля `title_en`, `description_en`, `section_en`, `note_en` (и `title_en` у вариантов выбора) задают английские тексты: при английском языке приложения берутся они, иначе русские. Живые примеры: `automod/config.schema.json` и `autoresponder/config.schema.json`.

## Секреты
api_id/api_hash, сессии и ключи LLM здесь не хранятся: приложение передаёт их скрипту при запуске (переменные окружения `TELESCRIPT_*`).

## Лицензия
Скрипты распространяются по лицензии GNU GPL v3 или новее (GPL-3.0-or-later). Полный текст в файле [LICENSE](LICENSE).

## Магазин скриптов
Приложение TgAuto читает подписанный каталог из этого репозитория: `index.json` + `index.json.sig` (ветка `main`), пакеты лежат в `packages/<id>-<версия>.tgascript`, флаги verified/official — в `store-meta.json`. Приложение доверяет только каталогу, подписанному ключом владельца.

Предложить скрипт: откройте issue по форме «Submit a script» или PR с папкой скрипта. Владелец читает код (сетевые хосты, действия в Telegram, рискованные модули); принятый скрипт получает `verified` и попадает в каталог. Серверной загрузки нет. Непроверенные скрипты можно поставить из файла `.tgascript` с предупреждением.

Сборка: `make_script_pkg.py <папка> --key <ключ> -o packages/<id>-<версия>.tgascript`, затем `make_store_index.py packages --base-url https://raw.githubusercontent.com/vipa-ch-cloud/TgAutoS/main/packages --meta store-meta.json --key <ключ> -o .`
