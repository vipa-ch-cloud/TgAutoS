[Русский](README.md) | English

# TgAutoS

Telethon userbot scripts for the TgAuto Android app: https://github.com/vipa-ch-cloud/TgAuto

Pick the folder with these scripts in the app (the "Scripts" tab). Each script lives in its own folder: `<id>.py`, a README and `config.schema.json`.

| Folder | What it does |
|---|---|
| `automod/` | Telegram chat auto-moderation using an LLM. See `automod/README.md` (Russian). |
| `autoresponder/` | Auto-responder for a personal account. See `autoresponder/README.md` (Russian). |

## config.schema.json format
A file next to a script enables the "Config" button in the app. The schema describes sections and fields (switches, numbers, text, lists, choices); the app draws a form and writes only the changed keys into the script's config. Fields whose names look like secrets (keys, passwords, tokens) are not shown. Optional fields `title_en`, `description_en`, `section_en`, `note_en` (and `title_en` on choice options) provide English texts: they are used when the app language is English, otherwise the Russian ones are shown. Live examples: `automod/config.schema.json` and `autoresponder/config.schema.json`.

## Secrets
api_id/api_hash, sessions and LLM keys are not stored here: the app passes them to the script at launch (`TELESCRIPT_*` environment variables).

## License
Licensed under the GNU GPL v3 or later (GPL-3.0-or-later). The full text is in [LICENSE](LICENSE).
