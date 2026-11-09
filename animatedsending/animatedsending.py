#!/usr/bin/env python3
"""AnimatedSending: animated sending of your own Telegram messages (Telethon userbot).

No AI and no external backend: the script only edits your own message (edit_message)
frame by frame. The idea and the first implementation come from the community.

Commands (written by the account owner, outgoing messages only):
  .a <style> text      animate the message in the given style (.anim is the same)
  .a text              animate in the default style
  .a -- text           same, even when the text starts with a style name
  .anim list           list the effects
  .anim status         current settings
  .anim on | off       enable / disable the animation
  .anim set style <name> | speed <edits per second | max> | cursor <chars | off>
           | mask <chars | reset> | turbo on|off | frames <N> | glyph <ch> <chars> | glyph reset
           | reset

Usage:
  python animatedsending.py login    QR login (writes api.json on first run)
  python animatedsending.py run      start the script

Paths (env, set by the app; prefix ANIMATEDSENDING_ or TELESCRIPT_):
  CONFIG_DIR (api.json, proxy.json, animatedsending.json), DATA_DIR, SESSION,
  API_ID, API_HASH, INSTANCE.

The pure frame generators (frames / timeline) have no network dependency and are unit-tested.
"""
import asyncio
import copy
import getpass
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path

try:  # telethon is only needed at runtime; tests run without it
    from telethon import TelegramClient, connection, errors, events
except ImportError:  # pragma: no cover
    TelegramClient = connection = errors = events = None

log = logging.getLogger("animatedsending")

MAX_LEN = 4096


def _env(name):
    return os.environ.get("ANIMATEDSENDING_" + name) or os.environ.get("TELESCRIPT_" + name)


INSTANCE = _env("INSTANCE") or "animatedsending"
APP_NAME = f"tg-autoresponder-{INSTANCE}"
CONFIG_DIR = Path(_env("CONFIG_DIR") or Path.home() / ".config" / APP_NAME)
DATA_DIR = Path(_env("DATA_DIR") or Path.home() / ".local/share" / APP_NAME)
SESSION = Path(_env("SESSION") or DATA_DIR / "account")
CONFIG = CONFIG_DIR / "api.json"
PROXY = CONFIG_DIR / "proxy.json"
SETTINGS = CONFIG_DIR / "animatedsending.json"

# ---------------------------------------------------------------- effects data

STYLES = {
    "typewriter": ("typewriter", "печатная машинка, по символам", "typewriter, char by char"),
    "words": ("words", "по словам", "word by word"),
    "lines": ("lines", "по строкам", "line by line"),
    "random": ("random", "символы появляются в случайном порядке", "characters appear in random order"),
    "reverse": ("reverse", "обратный: справа налево", "reverse: right to left"),
    "decrypt": ("decrypt", "дешифровка: гомоглифы и маска, затем настоящие буквы", "decryption: look-alikes and mask, then the real letters"),
    "matrix": ("matrix", "матричный дождь", "matrix rain"),
    "wave": ("wave", "бегущая волна регистра и подчёркивания", "running wave of case and underline"),
    "glitch": ("glitch", "глитч: артефакты и схлопывание", "glitch: artifacts and collapse"),
    "blink": ("blink", "печать с мигающим курсором", "typing with a blinking cursor"),
    "grow": ("grow", "нарастание ░▒▓█, затем текст", "fade-in ░▒▓█, then the text"),
    "handwriting": ("handwriting", "«рукописный» вывод с разными паузами", "handwriting with uneven pauses"),
    "slot": ("slot", "слот-машина: прокрутка символов", "slot machine: spinning symbols"),
}
ALIASES = {
    "type": "typewriter", "t": "typewriter", "tw": "typewriter", "word": "words", "w": "words",
    "line": "lines", "l": "lines", "rand": "random", "r": "random", "rev": "reverse",
    "dec": "decrypt", "d": "decrypt", "cipher": "decrypt", "rain": "matrix", "m": "matrix",
    "g": "glitch", "cursor": "blink", "b": "blink", "fade": "grow", "hand": "handwriting",
    "h": "handwriting", "write": "handwriting", "s": "slot", "reel": "slot",
    "wav": "wave", "печать": "typewriter", "слова": "words", "строки": "lines",
    "случайно": "random", "обратный": "reverse", "шифр": "decrypt", "матрица": "matrix",
    "волна": "wave", "глитч": "glitch", "курсор": "blink", "рукопись": "handwriting",
    "слот": "slot", "нарастание": "grow",
}

DEFAULT_CURSOR = "▌"
DEFAULT_MASK = ""  # empty = per-style defaults
STYLE_MASKS = {"decrypt": "#$%&*@?!/<>", "matrix": "01ｱｲｳｴｵｶｷｸｹｺ", "glitch": "▓▒░█▌▐╳#@%&",
               "slot": "", "grow": "░▒▓█"}
FADE = "░▒▓█"

# look-alikes: latin / cyrillic / digits (both directions)
HOMOGLYPHS = {
    "a": "аα@4", "b": "Ь6в", "c": "с¢(", "d": "ԁ", "e": "е3є", "g": "9", "h": "һн", "i": "і1!|", "j": "ј",
    "k": "к", "l": "1|І", "m": "м", "n": "п", "o": "о0", "p": "р", "q": "ԛ", "r": "г", "s": "ѕ5$",
    "t": "т7", "u": "υ", "v": "ν", "w": "ԝ", "x": "х×", "y": "у",
    "A": "А4Λ", "B": "В8", "C": "С", "E": "Е3", "H": "Н", "I": "І1l", "J": "Ј", "K": "К", "M": "М",
    "N": "Ν", "O": "О0", "P": "Р", "S": "Ѕ5", "T": "Т7", "X": "Х", "Y": "Ү", "Z": "Ζ2", "G": "6",
    "а": "a@4", "в": "B8", "г": "r", "е": "e3", "з": "3", "и": "u", "к": "k", "м": "m", "н": "h",
    "о": "o0", "п": "n", "р": "p", "с": "c", "т": "t7", "у": "y", "х": "x", "ч": "4", "ь": "b",
    "б": "6", "я": "R", "ш": "w", "ю": "10", "д": "g",
    "А": "A4", "В": "B8", "Е": "E3", "К": "K", "М": "M", "Н": "H", "О": "O0", "Р": "P", "С": "C",
    "Т": "T", "Х": "X", "З": "3", "Ч": "4", "Б": "6", "Я": "R",
    "0": "OОo", "1": "lI|", "2": "Z", "3": "ЗЕ", "4": "ЧA", "5": "S", "6": "б", "7": "T", "8": "B", "9": "g",
}

ZWJ = "‍"
_EXTEND = re.compile(r"[̀-ͯ҃-҉֑-ֽً-ٟ‌‍⃐-⃿"
                     r"︀-️\U0001f3fb-\U0001f3ff\U000e0020-\U000e007f]")
_REGIONAL = re.compile(r"[\U0001f1e6-\U0001f1ff]")


def split_units(text):
    """Split text into display units (code point + combining marks, ZWJ emoji sequences,
    flags, skin tones), so that no cut ever lands inside a character."""
    units = []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        if _REGIONAL.match(text[i]) and j < n and _REGIONAL.match(text[j]):
            j += 1
        while j < n:
            if _EXTEND.match(text[j]):
                j += 1
                if text[j - 1] == ZWJ and j < n:
                    j += 1
            else:
                break
        units.append(text[i:j])
        i = j
    return units


def _blank(u):
    return u.isspace()


def _nonblank_idx(units):
    return [i for i, u in enumerate(units) if not _blank(u)]


def normalize_style(name):
    name = (name or "").strip().lower()
    name = ALIASES.get(name, name)
    return name if name in STYLES else None


# ---------------------------------------------------------------- frame generators

def _opts(opts):
    o = {"seed": None, "cursor": DEFAULT_CURSOR, "mask": DEFAULT_MASK, "homoglyphs": None,
         "batch": 1, "max_frames": 80}
    o.update({k: v for k, v in (opts or {}).items() if v is not None or k == "seed"})
    return o


def _mask_for(style, o):
    return o["mask"] or STYLE_MASKS.get(style) or STYLE_MASKS["glitch"]


def _glyph_table(o):
    table = dict(HOMOGLYPHS)
    for k, v in (o.get("homoglyphs") or {}).items():
        if k and v:
            table[k] = v
    return table


def _scramble(u, rng, table, mask, use_glyphs=True):
    if use_glyphs and u in table and table[u]:
        return rng.choice(list(table[u]))
    return rng.choice(list(mask))


def _join(units):
    return "".join(units)


def _steps(total, o):
    """Step numbers to render (0..total-1): all of them, or an even sample (always with the
    last one) when far more than max_frames; keeps long texts fast."""
    cap = (o["max_frames"] or 0) * 2 * max(1, o["batch"] or 1)
    if not cap or total <= cap:
        return range(total)
    stride = total / cap
    picked = sorted({min(total - 1, int(k * stride)) for k in range(cap)} | {total - 1})
    return picked


def _typewriter(units, o, rng, style):
    n = len(units)
    cur = o["cursor"]
    out = []
    for i in range(1, n + 1):
        out.append((_join(units[:i]) + (cur if i < n else ""), 1.0))
    return out


def _words(units, o, rng, style):
    toks = re.findall(r"\S+|\s+", _join(units))
    out, acc = [], ""
    for t in toks:
        acc += t
        if not t.isspace():
            out.append((acc, 1.0))
    return out


def _lines(units, o, rng, style):
    parts = _join(units).splitlines(keepends=True) or [""]
    out, acc = [], ""
    for p in parts:
        acc += p
        out.append((acc, 1.0))
    return out


def _random(units, o, rng, style):
    idx = _nonblank_idx(units)
    rng.shuffle(idx)
    shown = [u if _blank(u) else "·" for u in units]
    out = []
    for i in idx:
        shown[i] = units[i]
        out.append((_join(shown), 1.0))
    return out


def _reverse(units, o, rng, style):
    n = len(units)
    cur = o["cursor"]
    return [((cur if i < n else "") + _join(units[n - i:]), 1.0) for i in range(1, n + 1)]


def _decrypt(units, o, rng, style):
    n = len(units)
    mask = _mask_for("decrypt", o)
    table = _glyph_table(o)
    steps = n + 6
    reveal = {}
    for k, i in enumerate(_nonblank_idx(units)):
        reveal[i] = min(steps - 1, int(k * 0.8) + 3 + rng.randint(0, 3))
    out = []
    for s in _steps(steps, o):
        row = []
        for i, u in enumerate(units):
            if _blank(u) or s >= reveal[i]:
                row.append(u)
            else:
                # early steps: look-alikes, later: random mask characters
                row.append(_scramble(u, rng, table, mask, use_glyphs=(s < reveal[i] - 2 or rng.random() < .4)))
        out.append((_join(row), 1.0))
    return out


def _matrix(units, o, rng, style):
    n = len(units)
    mask = _mask_for("matrix", o)
    start = {i: rng.randint(0, max(1, n // 2)) for i in _nonblank_idx(units)}
    out = []
    for s in _steps(max(1, n // 2) + 6, o):
        row = []
        for i, u in enumerate(units):
            if _blank(u):
                row.append(u)
            elif s < start[i]:
                row.append(" ")
            elif s < start[i] + 3:
                row.append(rng.choice(list(mask)))
            else:
                row.append(u)
        out.append((_join(row), 1.0))
    return out


def _wave(units, o, rng, style):
    n = len(units)
    out = []
    for s in _steps(n + 4, o):
        row = []
        for i, u in enumerate(units):
            d = s - i
            if _blank(u) or not 0 <= d < 4:
                row.append(u)
            else:
                up = u.swapcase()
                row.append(up if up != u and d % 2 == 0 else u + "̲")
        out.append((_join(row), 1.0))
    return out


def _glitch(units, o, rng, style):
    n = len(units)
    mask = _mask_for("glitch", o)
    out = []
    steps = 12
    for s in range(steps):
        p = 0.9 * (1 - s / steps) + (0.25 if rng.random() < .25 and s > 3 else 0)
        width = n if s > 3 else max(1, int(n * (0.3 + 0.7 * s / 4)))
        row = []
        for i, u in enumerate(units[:width]):
            row.append(u if _blank(u) or rng.random() > p else rng.choice(list(mask)))
        out.append((_join(row), 1.0))
    return out


def _blink(units, o, rng, style):
    n = len(units)
    cur = o["cursor"] or DEFAULT_CURSOR
    off = "▁" if cur != "▁" else "▔"
    out = [(_join(units[:i]) + cur, 1.0) for i in range(1, n)]
    for k in range(3):
        out.append((_join(units) + cur, 2.5))
        out.append((_join(units) + off, 2.5))
    return out


def _grow(units, o, rng, style):
    n = len(units)
    fade = o["mask"] if o["mask"] else FADE
    fade = list(fade)
    stages = len(fade)
    out = []
    for s in _steps(n + stages + 1, o):
        row = []
        for i, u in enumerate(units):
            d = s - i
            if _blank(u):
                row.append(u)
            elif d < 0:
                row.append(" ")
            elif d < stages:
                row.append(fade[d])
            else:
                row.append(u)
        out.append((_join(row), 1.0))
    return out


def _handwriting(units, o, rng, style):
    out = []
    cur = o["cursor"]
    n = len(units)
    for i in range(1, n + 1):
        u = units[i - 1]
        w = rng.uniform(0.5, 1.8)
        if u.isspace():
            w += 0.8
        elif u in ".,;:!?…—-":
            w += 1.4
        out.append((_join(units[:i]) + (cur if i < n and cur else ""), round(w, 3)))
    return out


def _slot(units, o, rng, style):
    n = len(units)
    custom = o["mask"]
    digits, lat, cyr = "0123456789", "abcdefghijklmnopqrstuvwxyz", "абвгдежзиклмнопрстуфхцчшэюя"

    def pool(u):
        if custom:
            return custom
        if u.isdigit():
            return digits
        low = u.lower()
        if low in cyr:
            return cyr.upper() if u.isupper() else cyr
        if low in lat:
            return lat.upper() if u.isupper() else lat
        return "!?#$%&*+=~" + digits

    idx = _nonblank_idx(units)
    stop = {i: 3 + int(k * 0.7) + rng.randint(0, 2) for k, i in enumerate(idx)}
    out = []
    for s in _steps(max(stop.values(), default=0) + 1, o):
        row = [u if _blank(u) or s >= stop[i] else rng.choice(list(pool(u))) for i, u in enumerate(units)]
        out.append((_join(row), 1.0))
    return out


_GENERATORS = {
    "typewriter": _typewriter, "words": _words, "lines": _lines, "random": _random,
    "reverse": _reverse, "decrypt": _decrypt, "matrix": _matrix, "wave": _wave,
    "glitch": _glitch, "blink": _blink, "grow": _grow, "handwriting": _handwriting, "slot": _slot,
}


def _limit(frames_w, max_frames, batch):
    """Thin out frames: every `batch`-th, then evenly down to max_frames. The last is kept;
    skipped frames add their weight to the kept one."""
    if batch and batch > 1 and len(frames_w) > 1:
        kept = []
        for i in range(0, len(frames_w), batch):
            chunk = frames_w[i:i + batch]
            kept.append((chunk[-1][0], sum(w for _, w in chunk)))
        frames_w = kept
    if max_frames and max_frames > 1 and len(frames_w) > max_frames:
        step = len(frames_w) / max_frames
        kept, last = [], -1
        for k in range(max_frames):
            j = min(len(frames_w) - 1, int((k + 1) * step) - 1)
            if j > last:
                kept.append((frames_w[j][0], sum(w for _, w in frames_w[last + 1:j + 1])))
                last = j
        if last < len(frames_w) - 1:
            kept.append((frames_w[-1][0], sum(w for _, w in frames_w[last + 1:])))
        frames_w = kept
    return frames_w


def _sanitize(frame, o):
    """A frame must be non-empty (Telegram refuses empty text) and within the limit."""
    if len(frame) > MAX_LEN:
        frame = frame[:MAX_LEN]
    if not frame.strip():
        frame = (o["cursor"] or "…")[:1] if o["cursor"] else "…"
    return frame


def timeline(text, style="typewriter", opts=None):
    """Return [(frame, weight)]: the frame texts and a relative delay multiplier for each.
    The last frame is always exactly `text`. Empty text gives []; text longer than
    4096 characters raises ValueError."""
    if not isinstance(text, str) or not text.strip():
        return []
    if len(text) > MAX_LEN:
        raise ValueError("text longer than 4096 characters")
    name = normalize_style(style)
    if name is None:
        raise ValueError(f"unknown style: {style!r}")
    o = _opts(opts)
    rng = random.Random(o["seed"])
    units = split_units(text)
    frames_w = _GENERATORS[name](units, o, rng, name)
    frames_w = [(_sanitize(f, o), w) for f, w in frames_w]
    # drop consecutive duplicates (Telegram answers MessageNotModified), merging weights
    ded = []
    for f, w in frames_w:
        if ded and ded[-1][0] == f:
            ded[-1] = (f, ded[-1][1] + w)
        else:
            ded.append((f, w))
    ded = [(f, w) for f, w in ded if f != text]
    ded = _limit(ded, o["max_frames"], o["batch"])
    ded.append((text, 1.0))
    return ded


def frames(text, style="typewriter", opts=None):
    """Frame texts of the animation; frames[-1] == text. See timeline()."""
    return [f for f, _ in timeline(text, style, opts)]


# ---------------------------------------------------------------- entities

def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


def shift_entities(entities, cut, total):
    """Entities (objects with offset/length in UTF-16 units) of the message text, re-based to
    the text that starts `cut` units later and is `total` units long. Entities fully inside the
    removed prefix are dropped, partly overlapping ones are clipped."""
    out = []
    for e in entities or []:
        start, end = e.offset - cut, e.offset + e.length - cut
        start, end = max(0, start), min(total, end)
        if end <= start:
            continue
        ne = copy.copy(e)
        ne.offset, ne.length = start, end - start
        out.append(ne)
    return out


# ---------------------------------------------------------------- settings

DEFAULTS = {
    "enabled": True,
    "style": "typewriter",
    "speed": 2.0,          # edits per second (normal mode)
    "turbo": False,        # max speed: batching and adaptive delay
    "cursor": DEFAULT_CURSOR,
    "mask": "",            # custom mask character set, empty = per-style defaults
    "homoglyphs": {},      # extra look-alikes: {"a": "а@"}
    "max_frames": 80,
    "preserve_format": True,
    "flood_max_wait": 30,  # seconds: longer FloodWait aborts the animation
    "seed": None,
}


def load_settings(path=None):
    path = Path(path) if path else SETTINGS
    data = dict(DEFAULTS)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    except (OSError, ValueError):
        pass
    return clean_settings(data)


def clean_settings(s):
    s = dict(s)
    d = DEFAULTS
    s["enabled"] = bool(s.get("enabled", True))
    s["style"] = normalize_style(str(s.get("style"))) or d["style"]
    try:
        s["speed"] = min(30.0, max(0.2, float(s.get("speed"))))
    except (TypeError, ValueError):
        s["speed"] = d["speed"]
    s["turbo"] = bool(s.get("turbo"))
    s["cursor"] = str(s["cursor"]) if s.get("cursor") is not None else d["cursor"]
    s["cursor"] = s["cursor"][:8]
    s["mask"] = str(s.get("mask") or "")[:64]
    hg = s.get("homoglyphs")
    s["homoglyphs"] = {str(k): str(v) for k, v in hg.items() if k} if isinstance(hg, dict) else {}
    try:
        s["max_frames"] = min(400, max(2, int(s.get("max_frames"))))
    except (TypeError, ValueError):
        s["max_frames"] = d["max_frames"]
    s["preserve_format"] = bool(s.get("preserve_format", True))
    try:
        s["flood_max_wait"] = min(600, max(1, int(s.get("flood_max_wait"))))
    except (TypeError, ValueError):
        s["flood_max_wait"] = d["flood_max_wait"]
    return s


def save_settings(s, path=None):
    path = Path(path) if path else SETTINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- command parsing

COMMAND_RE = re.compile(r"^\s*\.(?:anim|a)(?=\s|$)(.*)$", re.S | re.I)


def parse_command(raw, default_style="typewriter"):
    """Parse the message text. Returns None (not ours) or a dict:
    {"kind": "animate", "style", "text", "cut"} (cut = characters before the text),
    {"kind": "sub", "name", "args"}."""
    m = COMMAND_RE.match(raw or "")
    if not m:
        return None
    rest = m.group(1)
    body = rest.lstrip()
    base = len(raw) - len(body)
    head = body.split(None, 1)
    first = head[0] if head else ""
    if first.lower() in ("list", "status", "on", "off", "set", "help", "ls", "список"):
        args = head[1].strip() if len(head) > 1 else ""
        return {"kind": "sub", "name": {"ls": "list", "список": "list"}.get(first.lower(), first.lower()), "args": args}
    if not body:
        return {"kind": "sub", "name": "help", "args": ""}
    style = default_style
    text = body
    cut = base
    if first == "--" and len(head) > 1:
        text, cut = head[1], len(raw) - len(head[1])
    elif len(head) > 1 and normalize_style(first):
        style = normalize_style(first)
        text, cut = head[1], len(raw) - len(head[1])
    cut_text = text.rstrip()
    return {"kind": "animate", "style": style, "text": cut_text, "cut": cut}


def render_list(lang="ru"):
    i = 1 if lang == "ru" else 2
    rows = [f"{k} — {v[i + 0]}" for k, v in STYLES.items()]
    head = "Эффекты (.a <стиль> текст):" if lang == "ru" else "Effects (.a <style> text):"
    return head + "\n" + "\n".join(rows)


HELP_RU = ("AnimatedSending\n.a <стиль> текст — анимированная отправка\n.anim list — эффекты\n"
           ".anim status — настройки\n.anim on / off — включить / выключить\n"
           ".anim set style|speed|cursor|mask|turbo|frames|glyph <значение>\n.anim set reset — сбросить настройки")


def apply_set(settings, args):
    """Apply `.anim set ...`. Returns (new_settings, reply text)."""
    parts = args.split(None, 1)
    if not parts:
        return settings, "Что менять: style, speed, cursor, mask, turbo, frames, glyph, reset"
    key = parts[0].lower()
    val = parts[1].strip() if len(parts) > 1 else ""
    s = dict(settings)
    if key == "reset":
        keep = {"enabled": s["enabled"]}
        s = clean_settings({**DEFAULTS, **keep})
        return s, "Настройки сброшены"
    if key == "style":
        name = normalize_style(val)
        if not name:
            return settings, "Неизвестный стиль. См. .anim list"
        s["style"] = name
        return s, f"Стиль по умолчанию: {name}"
    if key == "speed":
        if val.lower() in ("max", "turbo", "макс"):
            s["turbo"] = True
            return s, "Режим максимальной скорости включён"
        try:
            v = float(val.replace(",", "."))
        except ValueError:
            return settings, "speed: число правок в секунду (0.2..30) или max"
        s["speed"] = min(30.0, max(0.2, v))
        return s, f"Скорость: {s['speed']:g} правок/с"
    if key == "turbo":
        on = val.lower() in ("on", "1", "yes", "да", "вкл", "true")
        if val.lower() not in ("on", "off", "1", "0", "yes", "no", "да", "нет", "вкл", "выкл", "true", "false"):
            return settings, "turbo on|off"
        s["turbo"] = on
        return s, "Режим максимальной скорости: " + ("вкл" if on else "выкл")
    if key == "cursor":
        s["cursor"] = "" if val.lower() in ("off", "none", "нет", "") else val[:8]
        return s, "Курсор: " + (s["cursor"] or "нет")
    if key == "mask":
        s["mask"] = "" if val.lower() in ("reset", "default", "") else val[:64]
        return s, "Маска: " + (s["mask"] or "по умолчанию для стиля")
    if key in ("frames", "maxframes"):
        try:
            s["max_frames"] = min(400, max(2, int(val)))
        except ValueError:
            return settings, "frames: целое число 2..400"
        return s, f"Максимум кадров: {s['max_frames']}"
    if key in ("glyph", "glyphs", "homoglyph"):
        if val.lower() == "reset":
            s["homoglyphs"] = {}
            return s, "Таблица похожих символов сброшена"
        gp = val.replace("=", " ").split(None, 1)
        if len(gp) != 2 or len(split_units(gp[0])) != 1:
            return settings, "glyph <символ> <похожие символы> | glyph reset"
        hg = dict(s["homoglyphs"])
        hg[gp[0]] = gp[1].replace(" ", "")[:32]
        s["homoglyphs"] = hg
        return s, f"{gp[0]} → {hg[gp[0]]}"
    return settings, "Неизвестная настройка: " + key


def render_status(s):
    return ("AnimatedSending: " + ("включено" if s["enabled"] else "выключено") +
            f"\nстиль: {s['style']}\nскорость: {s['speed']:g}/с" + (" (turbo)" if s["turbo"] else "") +
            f"\nкурсор: {s['cursor'] or 'нет'}\nмаска: {s['mask'] or 'по стилю'}"
            f"\nкадров не больше: {s['max_frames']}\nсвои глифы: {len(s['homoglyphs'])}")


# ---------------------------------------------------------------- timing

class Pacer:
    """Adaptive delay between edits. `base` seconds normally; in turbo mode starts small,
    follows the observed edit latency, grows on FloodWait and slowly recovers."""

    def __init__(self, speed=2.0, turbo=False):
        self.turbo = turbo
        self.base = 1.0 / max(0.2, speed)
        self.delay = 0.12 if turbo else self.base
        self.floor = 0.05 if turbo else self.base

    def next_delay(self, weight=1.0):
        return max(0.0, self.delay * (weight if not self.turbo else 1 + (weight - 1) * 0.5))

    def on_ok(self, rtt):
        if self.turbo:  # follow the observed latency, recover slowly after a FloodWait
            self.delay = max(self.floor, rtt * 1.1, self.delay * 0.97)

    def on_flood(self, seconds=0):
        self.delay = min(5.0, max(self.delay * 1.6, 0.3))
        if not self.turbo:
            self.base = self.delay


# ---------------------------------------------------------------- runtime

async def _edit(client, msg, text, entities, pacer, settings, final=False):
    """One edit with FloodWait handling. Returns "ok" / "skip" (not modified) / "stop"."""
    for attempt in range(4):
        try:
            started = time.monotonic()
            await client.edit_message(msg.chat_id, msg.id, text, parse_mode=None,
                                      formatting_entities=entities or None, link_preview=False)
            pacer.on_ok(time.monotonic() - started)
            return "ok"
        except errors.MessageNotModifiedError:
            return "skip"
        except errors.FloodWaitError as e:
            pacer.on_flood(e.seconds)
            if e.seconds > settings["flood_max_wait"] and not final:
                return "stop"
            await asyncio.sleep(min(e.seconds, 600) + 0.5)
        except (errors.MessageIdInvalidError, errors.MessageAuthorRequiredError,
                errors.MessageEditTimeExpiredError, errors.ChatAdminRequiredError,
                errors.MessageEmptyError, errors.MessageTooLongError):
            return "stop"
        except (errors.RPCError, ConnectionError, asyncio.TimeoutError) as e:
            log.warning("edit failed: %r", e)
            await asyncio.sleep(1 + attempt)
    return "stop"


async def animate(client, msg, text, style, settings, entities=None):
    """Play the animation on `msg` and always end with the exact final text (+ formatting)."""
    opts = {"seed": settings.get("seed"), "cursor": settings["cursor"], "mask": settings["mask"],
            "homoglyphs": settings["homoglyphs"], "max_frames": settings["max_frames"]}
    pacer = Pacer(settings["speed"], settings["turbo"])
    if settings["turbo"]:
        opts["batch"] = 2
        opts["max_frames"] = min(400, settings["max_frames"] * 2)
    tl = timeline(text, style, opts)
    if not tl:
        return False
    final_ent = entities if settings["preserve_format"] else None
    stopped = False
    for frame, weight in tl[:-1]:
        res = await _edit(client, msg, frame, None, pacer, settings)
        if res == "stop":
            stopped = True
            break
        await asyncio.sleep(pacer.next_delay(weight))
    # the final edit is always attempted (also after an abort, if the message still exists)
    for _ in range(3):
        res = await _edit(client, msg, text, final_ent, pacer, settings, final=True)
        if res != "stop":
            return True
        if stopped:
            await asyncio.sleep(2)
    log.error("could not set the final text of message %s", msg.id)
    return False


class AnimatedSending:
    def __init__(self, client, me_id, path=None):
        self.client = client
        self.me_id = me_id
        self.path = path
        self.sem = asyncio.Semaphore(3)

    def settings(self):
        return load_settings(self.path)

    async def reply(self, msg, text):
        try:
            await self.client.edit_message(msg.chat_id, msg.id, text, parse_mode=None)
        except errors.MessageNotModifiedError:
            pass

    async def on_message(self, event):
        msg = event.message
        if not msg.out or msg.fwd_from or msg.via_bot_id:
            return
        s = self.settings()
        cmd = parse_command(msg.raw_text or "", s["style"])
        if cmd is None:
            return
        if cmd["kind"] == "sub":
            await self.subcommand(msg, cmd, s)
            return
        if not s["enabled"]:
            return
        text = cmd["text"]
        if not text.strip():
            return
        if len(text) > MAX_LEN:
            await self.reply(msg, "Текст длиннее 4096 символов, анимация пропущена: " + text[:200])
            return
        ents = None
        if s["preserve_format"] and msg.entities:
            raw = msg.raw_text
            ents = shift_entities(msg.entities, utf16_len(raw[:cmd["cut"]]), utf16_len(text)) or None
        async with self.sem:
            try:
                await animate(self.client, msg, text, cmd["style"], s, ents)
            except Exception:  # never crash the handler
                log.exception("animation failed")

    async def subcommand(self, msg, cmd, s):
        name, args = cmd["name"], cmd["args"]
        if name == "list":
            await self.reply(msg, render_list("ru"))
        elif name == "status":
            await self.reply(msg, render_status(s))
        elif name in ("on", "off"):
            s["enabled"] = name == "on"
            save_settings(s, self.path)
            await self.reply(msg, "AnimatedSending " + ("включено" if s["enabled"] else "выключено"))
        elif name == "set":
            new, answer = apply_set(s, args)
            if new is not s and new != s:
                save_settings(clean_settings(new), self.path)
            await self.reply(msg, answer)
        else:
            await self.reply(msg, HELP_RU)


# ---------------------------------------------------------------- Telegram plumbing

def load_api_credentials():
    if _env("API_ID") and _env("API_HASH"):
        return {"api_id": int(_env("API_ID")), "api_hash": _env("API_HASH")}
    if not CONFIG.exists():
        raise RuntimeError(f"нет {CONFIG} и не заданы ANIMATEDSENDING_API_ID/ANIMATEDSENDING_API_HASH")
    return json.loads(CONFIG.read_text())


def make_client(session=None):
    api = load_api_credentials()
    kwargs = {}
    if PROXY.exists():
        proxy = json.loads(PROXY.read_text())
        if proxy.get("type") == "socks5":
            kwargs = {"proxy": ("socks5", proxy["host"], proxy["port"])}
        else:
            kwargs = {"connection": connection.ConnectionTcpMTProxyRandomizedIntermediate,
                      "proxy": (proxy["host"], proxy["port"], proxy["secret"])}
    return TelegramClient(session or str(SESSION), api["api_id"], api["api_hash"], **kwargs)


def prepare_dirs():
    for path in (CONFIG_DIR, DATA_DIR, SESSION.parent):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.chmod(0o700)
        except OSError:
            pass
    if not SETTINGS.exists():
        save_settings(DEFAULTS)


def show_qr(url):
    try:
        import qrcode
    except ImportError:
        print(f"Модуль qrcode не установлен. Откройте ссылку как QR в любом генераторе:\n{url}")
        return
    code = qrcode.QRCode(border=2)
    code.add_data(url)
    code.make(fit=True)
    code.print_ascii(invert=True)


async def qr_sign_in(client, on_url=show_qr):
    login_token = await client.qr_login()
    print("На телефоне: Настройки → Устройства → Подключить устройство. Отсканируйте код:")
    while True:
        on_url(login_token.url)
        try:
            await login_token.wait(timeout=25)
            return
        except asyncio.TimeoutError:
            if await client.is_user_authorized():
                return
            print("Срок кода истёк, вот новый:")
            await login_token.recreate()
        except errors.SessionPasswordNeededError:
            await client.sign_in(password=getpass.getpass("Облачный пароль (ввод скрыт): "))
            return


async def login():
    prepare_dirs()
    if not CONFIG.exists() and not _env("API_ID"):
        api_id = int(input("api_id: ").strip())
        api_hash = getpass.getpass("api_hash (ввод скрыт): ").strip()
        CONFIG.touch(mode=0o600)
        CONFIG.write_text(json.dumps({"api_id": api_id, "api_hash": api_hash}))
    client = make_client()
    await client.connect()
    if not await client.is_user_authorized():
        await qr_sign_in(client)
    me = await client.get_me()
    print(f"Вход выполнен, id {me.id}.")
    await client.disconnect()
    try:
        Path(f"{SESSION}.session").chmod(0o600)
    except OSError:
        pass


async def run():
    """Non-interactive: needs an existing session, never reads stdin (Android app)."""
    prepare_dirs()
    client = make_client()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        sys.exit("Нет входа в аккаунт: сначала выполните вход (python animatedsending.py login "
                 "или сессия из приложения через ANIMATEDSENDING_SESSION)")
    me = await client.get_me()
    bot = AnimatedSending(client, me.id)
    client.add_event_handler(bot.on_message, events.NewMessage(
        outgoing=True, pattern=r"(?is)^\s*\.(?:anim|a)(?:\s|$)"))
    log.info("running as %s, style %s", me.id, bot.settings()["style"])
    await client.run_until_disconnected()


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = sys.argv[1:] if argv is None else argv
    if TelegramClient is None:
        sys.exit("Нужен telethon: pip install telethon")
    if args == ["login"]:
        asyncio.run(login())
    elif args in (["run"], []):
        asyncio.run(run())
    else:
        sys.exit("Использование: python animatedsending.py login | run")


if __name__ == "__main__":
    main()
