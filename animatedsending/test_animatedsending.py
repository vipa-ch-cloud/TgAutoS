#!/usr/bin/env python3
"""Unit tests for animatedsending.py: pure frame logic, no Telegram, no network."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

TMP = tempfile.mkdtemp(prefix="animatedsending-test-")
os.environ["ANIMATEDSENDING_CONFIG_DIR"] = str(Path(TMP) / "config")
os.environ["ANIMATEDSENDING_DATA_DIR"] = str(Path(TMP) / "data")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import animatedsending as A  # noqa: E402

TEXTS = ["Hello, world!", "Привет, мир! Как дела?", "a", "line one\nline two\n\nline four",
         "Emoji 👍🏽 and 👨‍👩‍👧 flag 🇷🇺 ok ❤️", "  spaced   out  ", "日本語のテキスト", "x" * 4096,
         "Zalgo é combining", "123 456 7890"]


class Frames(unittest.TestCase):
    def test_last_frame_is_text_all_styles(self):
        for style in A.STYLES:
            for t in TEXTS:
                f = A.frames(t, style, {"seed": 1})
                self.assertEqual(f[-1], t, (style, t[:20]))

    def test_length_and_nonempty(self):
        for style in A.STYLES:
            for t in TEXTS:
                for fr in A.frames(t, style, {"seed": 2, "cursor": "▌", "mask": "#" * 10}):
                    self.assertLessEqual(len(fr), 4096)
                    self.assertTrue(fr.strip(), (style, t[:20]))

    def test_deterministic_with_seed(self):
        for style in A.STYLES:
            a = A.timeline(TEXTS[1], style, {"seed": 42})
            b = A.timeline(TEXTS[1], style, {"seed": 42})
            self.assertEqual(a, b, style)

    def test_seed_changes_random_styles(self):
        for style in ("random", "decrypt", "matrix", "glitch", "slot"):
            a = A.frames(TEXTS[1], style, {"seed": 1})
            b = A.frames(TEXTS[1], style, {"seed": 2})
            self.assertNotEqual(a, b, style)

    def test_empty_and_whitespace(self):
        for style in A.STYLES:
            self.assertEqual(A.frames("", style), [])
            self.assertEqual(A.frames("  \n ", style), [])

    def test_too_long_and_unknown(self):
        with self.assertRaises(ValueError):
            A.frames("x" * 4097, "typewriter")
        with self.assertRaises(ValueError):
            A.frames("abc", "nope")

    def test_max_frames_and_batch(self):
        t = "abcdefghij" * 40
        self.assertLessEqual(len(A.frames(t, "typewriter", {"max_frames": 20})), 21)
        self.assertEqual(A.frames(t, "typewriter", {"max_frames": 20})[-1], t)
        f1 = A.frames(t, "typewriter", {"max_frames": 0})
        f3 = A.frames(t, "typewriter", {"max_frames": 0, "batch": 3})
        self.assertLess(len(f3), len(f1))
        self.assertEqual(f3[-1], t)

    def test_no_consecutive_duplicates(self):
        for style in A.STYLES:
            f = A.frames(TEXTS[0], style, {"seed": 3})
            for x, y in zip(f, f[1:]):
                self.assertNotEqual(x, y, style)

    def test_emoji_never_split(self):
        t = "👨‍👩‍👧🇷🇺👍🏽é"
        for style in ("typewriter", "reverse", "random"):
            for fr in A.frames(t, style, {"cursor": "", "max_frames": 0}):
                self.assertNotIn("‍", fr[:1])
                self.assertEqual(fr.count("\U0001f469"), fr.count("‍") // 2 if "\U0001f469" in fr else 0, fr)
        self.assertEqual(A.split_units(t), ["👨‍👩‍👧", "🇷🇺", "👍🏽", "é"])

    def test_typewriter_prefixes(self):
        f = A.frames("abc", "typewriter", {"cursor": "|"})
        self.assertEqual(f, ["a|", "ab|", "abc"])
        self.assertEqual(A.frames("abc", "typewriter", {"cursor": ""}), ["a", "ab", "abc"])

    def test_words_lines_reverse(self):
        self.assertEqual(A.frames("one two  three", "words"), ["one", "one two", "one two  three"])
        self.assertEqual(A.frames("a\nb\nc", "lines"), ["a\n", "a\nb\n", "a\nb\nc"])
        self.assertEqual(A.frames("abc", "reverse", {"cursor": ""}), ["c", "bc", "abc"])

    def test_custom_cursor_and_mask_used(self):
        self.assertTrue(any("█" in f for f in A.frames("hello", "typewriter", {"cursor": "█"})))
        f = A.frames("hello world", "glitch", {"mask": "Ж", "seed": 1})
        self.assertTrue(any("Ж" in x for x in f))
        f = A.frames("hello", "grow", {"mask": "12"})
        self.assertTrue(any("1" in x for x in f))

    def test_decrypt_uses_homoglyphs(self):
        f = A.frames("aaaaaaaa", "decrypt", {"seed": 1, "homoglyphs": {"a": "Ж"}, "mask": "Ж"})
        self.assertTrue(any("Ж" in x for x in f))
        self.assertTrue(any("а" not in x for x in f))

    def test_whitespace_preserved_in_masking(self):
        for fr in A.frames("ab\ncd", "decrypt", {"seed": 1}):
            self.assertEqual(fr[2], "\n")

    def test_handwriting_weights_vary(self):
        w = {w for _, w in A.timeline("Hello, world. Bye", "handwriting", {"seed": 5})}
        self.assertGreater(len(w), 3)

    def test_styles_aliases(self):
        self.assertEqual(A.normalize_style("Rain"), "matrix")
        self.assertEqual(A.normalize_style("глитч"), "glitch")
        self.assertIsNone(A.normalize_style("zzz"))
        self.assertEqual(len(A.STYLES), 13)


class Parsing(unittest.TestCase):
    def test_animate(self):
        c = A.parse_command(".a glitch Привет", "typewriter")
        self.assertEqual((c["kind"], c["style"], c["text"], c["cut"]), ("animate", "glitch", "Привет", 10))
        c = A.parse_command(".anim hello there  ", "wave")
        self.assertEqual((c["style"], c["text"]), ("wave", "hello there"))
        c = A.parse_command(".a -- glitch is a style", "wave")
        self.assertEqual((c["style"], c["text"]), ("wave", "glitch is a style"))
        c = A.parse_command(".a glitch", "wave")  # style word alone is text
        self.assertEqual((c["style"], c["text"]), ("wave", "glitch"))

    def test_not_ours(self):
        for t in ("hello", ".alpha test", "x .a y", "", None, ".ab"):
            self.assertIsNone(A.parse_command(t))

    def test_sub(self):
        self.assertEqual(A.parse_command(".anim list")["name"], "list")
        c = A.parse_command(".anim set speed 5")
        self.assertEqual((c["name"], c["args"]), ("set", "speed 5"))
        self.assertEqual(A.parse_command(".a")["name"], "help")
        self.assertEqual(A.parse_command(".anim off")["name"], "off")

    def test_set(self):
        s = A.clean_settings(A.DEFAULTS)
        s2, _ = A.apply_set(s, "speed 5")
        self.assertEqual(s2["speed"], 5.0)
        s2, _ = A.apply_set(s, "speed 999")
        self.assertEqual(s2["speed"], 30.0)
        s2, _ = A.apply_set(s, "speed max")
        self.assertTrue(s2["turbo"])
        s2, _ = A.apply_set(s, "style rain")
        self.assertEqual(s2["style"], "matrix")
        s2, r = A.apply_set(s, "style zzz")
        self.assertEqual(s2, s)
        s2, _ = A.apply_set(s, "cursor ▮")
        self.assertEqual(s2["cursor"], "▮")
        s2, _ = A.apply_set(s, "cursor off")
        self.assertEqual(s2["cursor"], "")
        s2, _ = A.apply_set(s, "mask ░▒ ▓")
        self.assertEqual(s2["mask"], "░▒ ▓")
        s2, _ = A.apply_set(s, "glyph a ЖЗ")
        self.assertEqual(s2["homoglyphs"], {"a": "ЖЗ"})
        s3, _ = A.apply_set(s2, "glyph reset")
        self.assertEqual(s3["homoglyphs"], {})

    def test_settings_roundtrip(self):
        p = Path(TMP) / "s.json"
        s = A.clean_settings({**A.DEFAULTS, "speed": "bad", "style": "??", "max_frames": 99999})
        self.assertEqual((s["speed"], s["style"], s["max_frames"]), (2.0, "typewriter", 400))
        A.save_settings(s, p)
        self.assertEqual(A.load_settings(p), s)
        self.assertEqual(A.load_settings(Path(TMP) / "none.json")["style"], "typewriter")


class Entities(unittest.TestCase):
    def test_shift(self):
        E = lambda o, l: SimpleNamespace(offset=o, length=l)
        out = A.shift_entities([E(0, 2), E(3, 4), E(10, 5)], 3, 8)
        self.assertEqual([(e.offset, e.length) for e in out], [(0, 4), (7, 1)])
        out = A.shift_entities([E(2, 3)], 3, 10)  # clipped
        self.assertEqual([(e.offset, e.length) for e in out], [(0, 2)])
        self.assertEqual(A.utf16_len("a😀"), 3)


class FakeClient:
    def __init__(self, flood_first=0, notmod=False):
        self.calls, self.flood = [], flood_first
        self.notmod = notmod

    async def edit_message(self, chat, mid, text, **kw):
        if self.flood:
            self.flood -= 1
            raise A.errors.FloodWaitError(request=None, capture=0) if False else _flood(0)
        self.calls.append((text, kw))


def _flood(sec):
    e = A.errors.FloodWaitError.__new__(A.errors.FloodWaitError)
    e.seconds = sec
    return e


@unittest.skipIf(A.errors is None, "telethon not installed")
class Runtime(unittest.TestCase):
    def run_anim(self, client, **over):
        s = A.clean_settings({**A.DEFAULTS, "speed": 30, "seed": 1, **over})
        msg = SimpleNamespace(chat_id=1, id=5)
        ents = [SimpleNamespace(offset=0, length=2)]
        ok = asyncio.run(A.animate(client, msg, "Hello world", "typewriter", s, ents))
        return ok

    def test_final_exact_with_entities(self):
        c = FakeClient()
        self.assertTrue(self.run_anim(c))
        self.assertEqual(c.calls[-1][0], "Hello world")
        self.assertEqual(len(c.calls[-1][1]["formatting_entities"]), 1)
        self.assertIsNone(c.calls[0][1]["formatting_entities"])

    def test_flood_wait_survived(self):
        c = FakeClient(flood_first=2)
        self.assertTrue(self.run_anim(c))
        self.assertEqual(c.calls[-1][0], "Hello world")

    def test_turbo(self):
        c = FakeClient()
        self.assertTrue(self.run_anim(c, turbo=True))
        self.assertEqual(c.calls[-1][0], "Hello world")

    def test_long_flood_skips_frames_but_sets_final(self):
        class C(FakeClient):
            n = 0

            async def edit_message(self, chat, mid, text, **kw):
                C.n += 1
                if C.n == 3:
                    raise _flood(0.0 + 1000)
                self.calls.append((text, kw))

        c = C()
        real = asyncio.sleep

        async def fast(x):
            await real(0)

        A.asyncio.sleep, old = fast, A.asyncio.sleep
        try:
            self.assertTrue(self.run_anim(c))
        finally:
            A.asyncio.sleep = old
        self.assertEqual(c.calls[-1][0], "Hello world")


class Pacer(unittest.TestCase):
    def test_flood_slows(self):
        p = A.Pacer(10, True)
        d = p.delay
        p.on_flood(3)
        self.assertGreater(p.delay, d)
        for _ in range(500):
            p.on_ok(0.01)
        self.assertLess(p.delay, 0.2)

    def test_normal(self):
        p = A.Pacer(4, False)
        self.assertAlmostEqual(p.next_delay(), 0.25)
        self.assertAlmostEqual(p.next_delay(2), 0.5)


if __name__ == "__main__":
    unittest.main()
