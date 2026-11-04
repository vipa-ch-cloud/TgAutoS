# TeleScript scripts

Telethon userbot scripts for the TeleScript Android app (the app lives in its own repository).
Pick the folder with these scripts in the app: the "Scripts" tab, "Выбери папку со скриптами".

| Folder | What it does |
|---|---|
| `automod/` | Telegram chat automoderation (LLM-assisted). See `automod/README.md`. |
| `autoresponder/` | Personal-account auto-reply. See `autoresponder/README.md`. |

Each folder has `<id>.py`, a README and `config.schema.json`, which drives the "Конфиг" form in the app.
Secrets (api_id/api_hash, sessions, LLM keys) are never stored here: the app passes them to the script at run time.
