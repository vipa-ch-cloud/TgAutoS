# animatedsending — анимированная отправка сообщений

Русский | [English below](#english)

> Идея и первая реализация принадлежат сообществу. Автор в каталоге: Claude (идея и первая реализация — сообщество). Скрипт помечен тегом `community`.

Юзербот на Telethon. Вы пишете сообщение с префиксом, а скрипт сам анимирует его появление, правя это же сообщение. Без ИИ, без внешнего бэкенда и без сети: только `edit_message` вашего собственного сообщения. На чужие сообщения скрипт не реагирует.

## Команды

| Команда | Что делает |
|---|---|
| `.a <стиль> текст` (или `.anim ...`) | анимировать сообщение в выбранном стиле |
| `.a текст` | анимировать в стиле по умолчанию |
| `.a -- текст` | то же, если текст начинается со слова-названия стиля |
| `.anim list` | список эффектов |
| `.anim status` | текущие настройки |
| `.anim on` / `.anim off` | включить / выключить |
| `.anim set style <имя>` | стиль по умолчанию |
| `.anim set speed <число>` | правок в секунду (0.2..30); `speed max` включает режим максимальной скорости |
| `.anim set turbo on/off` | режим максимальной скорости |
| `.anim set cursor <символы>` / `cursor off` | свой курсор |
| `.anim set mask <символы>` / `mask reset` | свой набор символов маски |
| `.anim set frames <N>` | максимум кадров (2..400) |
| `.anim set glyph <символ> <похожие>` / `glyph reset` | таблица похожих символов для дешифровки |
| `.anim set reset` | сбросить настройки |

Настройки сохраняются в `animatedsending.json` (они же в экране «Конфиг» приложения) и перечитываются при каждой команде.

## Эффекты

`typewriter` печатная машинка, `words` по словам, `lines` по строкам, `random` случайный порядок символов, `reverse` справа налево, `decrypt` дешифровка (сначала похожие символы латиницы/кириллицы/цифр или символы маски, затем настоящие буквы), `matrix` матричный дождь, `wave` бегущая волна регистра и подчёркивания, `glitch` мерцающие артефакты и схлопывание, `blink` печать с мигающим курсором, `grow` нарастание ░▒▓█, `handwriting` «рукописный» вывод с паузами разной длины, `slot` слот-машина. Есть короткие алиасы (`rain`, `rev`, `dec`, `hand` и русские названия).

## Скорость и FloodWait

Telegram ограничивает частоту правок. Число кадров ограничено (`max_frames`), кадры прореживаются, дубликаты убираются. Режим максимальной скорости склеивает несколько символов в одну правку и подбирает задержку по времени ответа Telegram. При `FloodWaitError` скрипт ждёт и замедляется; `MessageNotModified` игнорируется. Итоговая правка всегда ставит точный исходный текст, с исходным форматированием (entities), если оно было. Пустые сообщения пропускаются, лимит 4096 символов.

## Запуск

```
python animatedsending.py login   # вход по QR (при запуске из приложения сессия берётся от аккаунта приложения)
python animatedsending.py run
```

Переменные окружения (приложение задаёт сам): `ANIMATEDSENDING_CONFIG_DIR`, `ANIMATEDSENDING_DATA_DIR`, `ANIMATEDSENDING_SESSION`, `ANIMATEDSENDING_API_ID`, `ANIMATEDSENDING_API_HASH`.

## Тесты

```
python3 -m unittest
```

Чистая логика лежит в `frames(text, style, opts)` и `timeline(...)`: последний кадр всегда равен исходному тексту, длина кадра не больше 4096, результат детерминирован при `seed`. Сеть и Telegram тестам не нужны.

---

<a id="english"></a>
# animatedsending — animated message sending

> The idea and first implementation come from the community (tag `community`; catalog author: Claude, community idea and first implementation).

A Telethon userbot. Write a message with a prefix and the script animates its appearance by editing that same message. No AI, no external backend, no network: only `edit_message` on your own message. It never reacts to other people's messages.

## Commands

| Command | What it does |
|---|---|
| `.a <style> text` (or `.anim ...`) | animate the message in the given style |
| `.a text` | animate in the default style |
| `.a -- text` | same when the text starts with a style name |
| `.anim list` | list the effects |
| `.anim status` | current settings |
| `.anim on` / `.anim off` | enable / disable |
| `.anim set style <name>` | default style |
| `.anim set speed <n>` | edits per second (0.2..30); `speed max` turns on max speed mode |
| `.anim set turbo on/off` | max speed mode |
| `.anim set cursor <chars>` / `cursor off` | custom cursor |
| `.anim set mask <chars>` / `mask reset` | custom mask character set |
| `.anim set frames <N>` | max frames (2..400) |
| `.anim set glyph <char> <look-alikes>` / `glyph reset` | look-alike table for decrypt |
| `.anim set reset` | reset settings |

Settings live in `animatedsending.json` (also the app's "Config" screen) and are re-read on every command.

## Effects

typewriter, words, lines, random, reverse, decrypt (look-alike Latin/Cyrillic/digit characters or mask characters first, then the real letters), matrix rain, wave (running case/underline wave), glitch (flickering artifacts, then collapse), blink (typing with a blinking cursor), grow (░▒▓█ fade-in), handwriting (uneven pauses), slot (slot machine). Short aliases exist (`rain`, `rev`, `dec`, `hand`, Russian names).

## Speed and FloodWait

Telegram rate-limits edits. Frame count is capped (`max_frames`), frames are thinned out and deduplicated. Max speed mode batches several characters per edit and adapts the delay to Telegram's response time. On `FloodWaitError` the script waits and slows down; `MessageNotModified` is ignored. The last edit always sets the exact original text, with the original entities (formatting) when present. Empty messages are skipped; the limit is 4096 characters.

## Running

```
python animatedsending.py login
python animatedsending.py run
```

Env (set by the app): `ANIMATEDSENDING_CONFIG_DIR`, `ANIMATEDSENDING_DATA_DIR`, `ANIMATEDSENDING_SESSION`, `ANIMATEDSENDING_API_ID`, `ANIMATEDSENDING_API_HASH`.

## Tests

```
python3 -m unittest
```

The pure logic is `frames(text, style, opts)` / `timeline(...)`: the last frame always equals the source text, frames are at most 4096 characters, output is deterministic with `seed`. No network needed.
