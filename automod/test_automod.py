#!/usr/bin/env python3
"""Unit tests for automod.py; no Telegram, no network, no LLM. Run: python3 test_automod.py"""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

TMP = tempfile.mkdtemp(prefix="automod-test-")
os.environ["AUTOMOD_CONFIG_DIR"] = str(Path(TMP) / "config")
os.environ["AUTOMOD_DATA_DIR"] = str(Path(TMP) / "data")
os.environ["AUTOMOD_SESSION"] = str(Path(TMP) / "data" / "account")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import automod  # noqa: E402
import logging  # noqa: E402

logging.disable(logging.CRITICAL)

SETTINGS = automod.load_settings(Path(TMP) / "missing.json")
SETTINGS["send_delay"] = 0
SETTINGS["amt_delay"] = 0


def msg(id, user_id, text="привет", **extra):
    return {"id": id, "user_id": user_id, "name": f"u{user_id}", "username": None,
            "is_bot": False, "reply_to": None, "text": text, **extra}


class EnvPaths(unittest.TestCase):
    def test_env_overrides(self):
        self.assertEqual(automod.CONFIG_DIR, Path(TMP) / "config")
        self.assertEqual(automod.DATA_DIR, Path(TMP) / "data")
        self.assertEqual(automod.SESSION, Path(TMP) / "data" / "account")
        self.assertEqual(automod.INSTANCE, "automod")

    def test_settings_merge(self):
        path = Path(TMP) / "s.json"
        path.write_text(json.dumps({"batch_size": 50, "commands": {"mute": "!мут {duration}"}}))
        s = automod.load_settings(path)
        self.assertEqual(s["batch_size"], 50)
        self.assertEqual(s["commands"]["mute"], "!мут {duration}")
        self.assertEqual(s["commands"]["warn"], "варн")
        self.assertEqual(s["prefix"], "!")


class ParseCommand(unittest.TestCase):
    def test_on(self):
        self.assertEqual(automod.parse_command(".automod"), {"action": "on", "rules": None})
        self.assertEqual(automod.parse_command("  .AutoMod on "), {"action": "on", "rules": None})

    def test_off_status(self):
        self.assertEqual(automod.parse_command(".automod off")["action"], "off")
        self.assertEqual(automod.parse_command(".automod status")["action"], "status")

    def test_rules_arg(self):
        self.assertEqual(automod.parse_command(".automod -r=https://telegra.ph/Pravila-01-01"),
                         {"action": "on", "rules": "https://telegra.ph/Pravila-01-01"})
        self.assertEqual(automod.parse_command(".automod -r t.me/chat/12")["rules"], "t.me/chat/12")
        self.assertEqual(automod.parse_command(".automod on -r=<t.me/c/1/2>")["rules"], "t.me/c/1/2")

    def test_not_command(self):
        for text in ("", None, "automod", ".automoderation", "привет .automod", ".autom"):
            self.assertIsNone(automod.parse_command(text), text)

    def test_unknown_arg(self):
        self.assertEqual(automod.parse_command(".automod blah")["action"], "help")


class ParseRulesLink(unittest.TestCase):
    def test_tme_public(self):
        self.assertEqual(automod.parse_rules_link("https://t.me/mychat/123"), ("tme", "mychat", 123))
        self.assertEqual(automod.parse_rules_link("t.me/mychat/5/123"), ("tme", "mychat", 123))
        self.assertEqual(automod.parse_rules_link("https://t.me/mychat/123?single"),
                         ("tme", "mychat", 123))

    def test_tme_private(self):
        self.assertEqual(automod.parse_rules_link("https://t.me/c/123/456"),
                         ("tme", -100123, 456))
        self.assertEqual(automod.parse_rules_link("t.me/c/123/7/456"), ("tme", -100123, 456))

    def test_http(self):
        self.assertEqual(automod.parse_rules_link("https://telegra.ph/Pravila-03-11"),
                         ("http", "https://telegra.ph/Pravila-03-11"))
        self.assertEqual(automod.parse_rules_link("telegra.ph/Pravila-03-11"),
                         ("http", "https://telegra.ph/Pravila-03-11"))
        self.assertEqual(automod.parse_rules_link("http://example.com/rules"),
                         ("http", "http://example.com/rules"))

    def test_bad(self):
        for link in ("", "t.me/mychat", "t.me/c/abc/1", "ftp://x", "просто текст", "t.me/+invite"):
            self.assertIsNone(automod.parse_rules_link(link), link)


class FetchRules(unittest.TestCase):
    def test_telegraph_api(self):
        api = {"ok": True, "result": {"title": "Правила", "content": [
            {"tag": "p", "children": ["2.1 Не оскорблять"]},
            {"tag": "p", "children": ["2.2 Без ", {"tag": "b", "children": ["спама"]}]}]}}
        calls = []

        def getter(url):
            calls.append(url)
            return json.dumps(api)
        text = automod.fetch_url_text("https://telegra.ph/Pravila-03-11", getter)
        self.assertEqual(calls, ["https://api.telegra.ph/getPage/Pravila-03-11?return_content=true"])
        self.assertIn("2.1 Не оскорблять", text)
        self.assertIn("2.2 Без спама", text)

    def test_html_page(self):
        page = ("<html><head><title>x</title><script>var a=1</script></head><body>"
                "<nav>меню</nav><p>1.1 Будьте вежливы</p><p>1.2 Без&nbsp;рекламы</p></body></html>")
        text = automod.fetch_url_text("https://example.com/r", lambda url: page)
        self.assertEqual(text, "1.1 Будьте вежливы\n1.2 Без рекламы")

    def test_single_link(self):
        self.assertEqual(automod.single_link("Правила чата: https://telegra.ph/Pr-01"),
                         "https://telegra.ph/Pr-01")
        self.assertIsNone(automod.single_link("1. Не спамить\n2. Не ругаться"))


class ParseViolations(unittest.TestCase):
    def test_clean(self):
        answer = json.dumps({"violations": [{"message_id": 5, "user_id": 9, "rule": "2.1",
                                             "punishment": "mute", "duration_minutes": 60,
                                             "category": "insult", "reason": "оскорбление"}]})
        v = automod.parse_violations(answer)
        self.assertEqual(v, [{"message_id": 5, "user_id": 9, "rule": "2.1", "punishment": "mute",
                              "duration_minutes": 60, "category": "insult",
                              "reason": "оскорбление"}])

    def test_fenced_and_chatter(self):
        answer = 'Вот ответ:\n```json\n{"violations": [{"message_id": "7", "rule": "п. 3.2", ' \
                 '"punishment": "Варн"}]}\n```\nВсё.'
        v = automod.parse_violations(answer)
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["message_id"], 7)
        self.assertEqual(v[0]["rule"], "3.2")
        self.assertEqual(v[0]["punishment"], "warn")

    def test_bare_list(self):
        v = automod.parse_violations('[{"id": 1, "punishment": "бан", "rule": 4}]')
        self.assertEqual((v[0]["message_id"], v[0]["punishment"], v[0]["rule"]), (1, "ban", "4"))

    def test_garbage(self):
        for answer in ("", "нет нарушений", "{broken", '{"violations": "none"}', "null",
                       '{"violations": [1, "x", {"punishment": "warn"}, '
                       '{"message_id": 2, "punishment": "kill"}]}'):
            self.assertEqual(automod.parse_violations(answer), [], answer)

    def test_empty(self):
        self.assertEqual(automod.parse_violations('{"violations": []}'), [])


def v(message_id, punishment="warn", rule="1", minutes=None, category="other", reason="x",
      user_id=None):
    return {"message_id": message_id, "user_id": user_id, "rule": rule, "punishment": punishment,
            "duration_minutes": minutes, "category": category, "reason": reason}


class Caps(unittest.TestCase):
    def test_protected_and_unknown(self):
        batch = [msg(1, 10), msg(2, 20), msg(3, 30, is_bot=True), msg(4, -1001)]
        out = automod.apply_caps([v(1), v(2), v(3), v(4), v(99)], batch, {20}, SETTINGS)
        self.assertEqual([x["message_id"] for x in out], [1])

    def test_author_from_batch_not_llm(self):
        out = automod.apply_caps([v(1, user_id=20)], [msg(1, 10)], {20}, SETTINGS)
        self.assertEqual(out[0]["user_id"], 10)

    def test_one_per_user_most_severe(self):
        batch = [msg(1, 10), msg(2, 10), msg(3, 10)]
        out = automod.apply_caps([v(1), v(2, "mute", minutes=30), v(3)], batch, set(), SETTINGS)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["message_id"], out[0]["punishment"]), (2, "mute"))

    def test_max_per_batch(self):
        batch = [msg(i, 100 + i) for i in range(1, 11)]
        violations = [v(i) for i in range(1, 11)] + []
        violations[7] = v(8, "ban", category="spam")
        out = automod.apply_caps(violations, batch, set(), SETTINGS)
        self.assertEqual(len(out), 5)
        self.assertIn(8, [x["message_id"] for x in out])  # severe ones go first

    def test_ban_only_when_rule_says_ban(self):
        rules = "1. Реклама запрещена — бан.\n2. Оскорбления запрещены."
        batch = [msg(1, 10), msg(2, 20)]
        out = automod.apply_caps([v(1, "ban", "2"), v(2, "ban", "1")], batch, set(), SETTINGS,
                                 rules=rules)
        by_user = {x["user_id"]: x for x in out}
        self.assertEqual(by_user[10]["punishment"], "mute")  # rule 2 names no ban
        self.assertEqual(by_user[10]["duration_minutes"], SETTINGS["mute_default_minutes"])
        self.assertEqual(by_user[20]["punishment"], "ban")

    def test_rule_punishment_applied_exactly(self):
        rules = "2. Общение\n2.1 Флуд — мут 1 день.\n2.2 Мат — варн, при повторе бан"
        out = automod.apply_caps([v(1, "warn", "2.1")], [msg(1, 10)], set(), SETTINGS, rules=rules)
        self.assertEqual((out[0]["punishment"], out[0]["duration_minutes"]), ("mute", 1440))
        # the model's choice is kept when the rule names it
        out = automod.apply_caps([v(1, "ban", "2.2")], [msg(1, 10)], set(), SETTINGS, rules=rules)
        self.assertEqual(out[0]["punishment"], "ban")
        out = automod.apply_caps([v(1, "mute", "2.2")], [msg(1, 10)], set(), SETTINGS, rules=rules)
        self.assertEqual(out[0]["punishment"], "warn")

    def test_parse_rules(self):
        rules = "Правила\n1. Общие\n1.1 Без спама — бан\n  продолжение\n2) Мат — мут 3 часа"
        parsed = automod.parse_rules(rules)
        self.assertIn("продолжение", parsed["1.1"])
        self.assertIn("Общие", automod.rule_text(rules, "1.1"))
        self.assertEqual(automod.rule_punishments(parsed["2"]),
                         [{"punishment": "mute", "duration_minutes": 180}])
        self.assertEqual(automod.rule_punishments("бан навсегда")[0]["punishment"], "ban")
        self.assertEqual(automod.parse_duration("на 2 недели"), 20160)

    def test_find_ad_rule(self):
        self.assertEqual(automod.find_ad_rule("1. Без мата\n2. Реклама запрещена — бан"), "2")
        self.assertEqual(automod.find_ad_rule(automod.DEFAULT_RULES), "1")
        self.assertIsNone(automod.find_ad_rule("1. Без мата\n2. Уважайте друг друга"))

    def test_mute_clamped(self):
        batch = [msg(1, 10), msg(2, 20), msg(3, 30)]
        out = automod.apply_caps([v(1, "mute", minutes=99999), v(2, "mute", minutes=1),
                                  v(3, "mute")], batch, set(), SETTINGS)
        self.assertEqual([x["duration_minutes"] for x in out], [1440, 10, 60])

    def test_already_punished(self):
        out = automod.apply_caps([v(1)], [msg(1, 10)], set(), SETTINGS, already_punished=[1])
        self.assertEqual(out, [])


class IrisFormat(unittest.TestCase):
    def test_user_example(self):
        text = automod.format_iris_command(v(1, "mute", "2.1", 60), SETTINGS)
        self.assertEqual(text, "!мут 1 час\nautomod 2.1")

    def test_warn_ban(self):
        self.assertEqual(automod.format_iris_command(v(1, "warn", "3"), SETTINGS),
                         "!варн\nautomod 3")
        self.assertEqual(automod.format_iris_command(v(1, "ban", "1.4"), SETTINGS),
                         "!бан\nautomod 1.4")

    def test_custom_template(self):
        s = dict(SETTINGS, prefix=".", commands={**SETTINGS["commands"], "mute": "мут {duration}"})
        self.assertEqual(automod.format_iris_command(v(1, "mute", "5", 30), s),
                         ".мут 30 минут\nautomod 5")

    def test_empty_prefix(self):
        s = dict(SETTINGS, prefix="")
        self.assertEqual(automod.format_iris_command(v(1, "mute", "2.1", 60), s),
                         "мут 1 час\nautomod 2.1")
        self.assertEqual(automod.format_iris_command(v(1, "warn", "3"), s, target="@vasya"),
                         "варн @vasya\nautomod 3")

    def test_target_form(self):
        self.assertEqual(automod.format_target("vasya", 5), "@vasya")
        self.assertEqual(automod.format_target(None, 123456), "123456")
        self.assertEqual(automod.format_iris_command(v(1, "mute", "2.1", 60), SETTINGS,
                                                     target="@vasya"),
                         "!мут 1 час @vasya\nautomod 2.1")
        self.assertEqual(automod.format_iris_command(v(1, "ban", "1", 1440), SETTINGS,
                                                     target="123456"),
                         "!бан 1 сутки 123456\nautomod 1")

    def test_durations(self):
        cases = {1: "1 минута", 2: "2 минуты", 11: "11 минут", 21: "21 минута", 30: "30 минут",
                 60: "1 час", 120: "2 часа", 300: "5 часов", 1260: "21 час", 1440: "1 сутки",
                 2880: "2 суток", 10080: "1 неделя", 90: "90 минут"}
        for minutes, expected in cases.items():
            self.assertEqual(automod.format_duration(minutes), expected)

    def test_no_quotes(self):
        text = automod.format_iris_command(v(1, "mute", "2.1", 60), SETTINGS)
        self.assertNotIn('"', text)
        self.assertNotIn("«", text)


class Backends(unittest.TestCase):
    def test_api_request(self):
        b = automod.ApiBackend("claude-haiku-5-5", "sk-test")
        req = b.build_request("sys", "user")
        body = json.loads(req.data)
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.get_header("X-api-key"), "sk-test")
        self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual(body["system"], "sys")
        self.assertNotIn("tools", body)

    def test_api_complete(self):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        payload = {"content": [{"type": "text", "text": '{"violations": []}'}]}
        b = automod.ApiBackend("m", "k", opener=lambda req, timeout: Resp(json.dumps(payload).encode()))
        self.assertEqual(asyncio.run(b.complete("s", "u")), '{"violations": []}')

    def test_api_needs_key(self):
        with self.assertRaises(ValueError):
            automod.ApiBackend("m", "")

    def test_make_backend(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}):
            b = automod.make_backend(dict(SETTINGS, backend="api"))
        self.assertEqual((b.name, b.api_key), ("api", "env-key"))
        self.assertEqual(automod.make_backend(dict(SETTINGS, backend="cli")).name, "cli")
        with mock.patch.object(automod.shutil, "which", return_value=None), \
                mock.patch.object(automod.Path, "exists", return_value=False), \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            self.assertEqual(automod.make_backend(SETTINGS).name, "api")

    def test_cli_args(self):
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.communicate = mock.AsyncMock(return_value=(b'{"violations": []}', b""))
        b = automod.CliBackend("claude-haiku-5-5", sandbox=Path(TMP) / "empty")
        with mock.patch.object(automod.asyncio, "create_subprocess_exec",
                               mock.AsyncMock(return_value=proc)) as spawn:
            out = asyncio.run(b.complete("SYS", "input"))
        self.assertEqual(out, '{"violations": []}')
        args = spawn.call_args.args
        self.assertEqual(args[1:12], ("-p", "--model", "claude-haiku-5-5", "--tools", "",
                                      "--strict-mcp-config", "--setting-sources", "",
                                      "--no-session-persistence", "--system-prompt", "SYS"))
        self.assertEqual(spawn.call_args.kwargs["cwd"], Path(TMP) / "empty")


class FakeBackend:
    name = "fake"

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def complete(self, system_prompt, text):
        self.calls.append((system_prompt, text))
        return self.answer


def fake_event(chat_id, msg_id, user_id, text, bot=False, is_group=True, username=None, **extra):
    sender = SimpleNamespace(id=user_id, username=username or f"user{user_id}", bot=bot,
                             first_name=f"U{user_id}", last_name=None)
    message = SimpleNamespace(id=msg_id, message=text, action=None, media=None,
                              reply_to_msg_id=None, **extra)
    event = SimpleNamespace(chat_id=chat_id, sender_id=user_id, raw_text=text, message=message,
                            is_group=is_group, get_sender=mock.AsyncMock(return_value=sender),
                            delete=mock.AsyncMock())
    return event


class FakeClient:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self.calls = []  # ("send"|"delete", ...) in order
        self.gone = set()  # message ids that no longer exist
        self.history = []  # messages iter_messages serves, any order
        self.replies = {}  # message id -> reply messages
        self.banned = set()  # user ids banned or restricted right now

    async def send_message(self, chat, text, **kw):
        self.sent.append((chat, text, kw.get("reply_to")))
        self.calls.append(("send", text, kw.get("reply_to")))
        return SimpleNamespace(id=len(self.sent), delete=mock.AsyncMock())

    async def delete_messages(self, chat, ids):
        self.deleted.extend(ids)
        self.calls.append(("delete", list(ids)))

    async def get_messages(self, chat, ids=None):
        return None if ids in self.gone else SimpleNamespace(id=ids, action=None)

    async def iter_messages(self, chat, limit=None, offset_id=0, reply_to=None):
        if reply_to is not None:
            items = list(self.replies.get(reply_to, []))
        else:
            items = sorted((m for m in self.history if not offset_id or m.id < offset_id),
                           key=lambda m: -m.id)
        for m in items[:limit]:
            yield m

    async def get_permissions(self, chat, user):
        return SimpleNamespace(is_banned=user in self.banned)


class Batching(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=TMP))
        self.log_patch = mock.patch.object(automod, "ACTIONS_LOG", self.dir / "actions.log")
        self.log_patch.start()
        self.utils_patch = mock.patch.object(
            automod, "utils", SimpleNamespace(get_display_name=lambda s: s.first_name))
        self.utils_patch.start()

    def tearDown(self):
        self.log_patch.stop()
        self.utils_patch.stop()

    def make_bot(self, answer, admins=()):
        state = automod.State(self.dir / "state.json")
        state.chat(-1001)["enabled"] = True
        state.chat(-1001)["rules"] = "2.1 Не оскорблять"
        bot = automod.Automod(FakeClient(), state, 1, SETTINGS, FakeBackend(answer))
        bot.protected_ids = mock.AsyncMock(return_value={1, *admins})
        return bot

    async def feed(self, bot, count, start=1, chat=-1001):
        for i in range(start, start + count):
            await bot.on_message(fake_event(chat, i, 1000 + i % 7, f"сообщение {i}"))
        for _ in range(20):
            await asyncio.sleep(0)

    def test_trigger_at_100(self):
        answer = json.dumps({"violations": [{"message_id": 42, "rule": "2.1",
                                             "punishment": "mute", "duration_minutes": 60}]})
        bot = self.make_bot(answer)

        async def scenario():
            await self.feed(bot, 99)
            self.assertEqual(bot.backend.calls, [])
            self.assertEqual(len(bot.state.chat(-1001)["buffer"]), 99)
            await self.feed(bot, 1, start=100)
            while bot.busy:
                await asyncio.sleep(0)
        asyncio.run(scenario())
        self.assertEqual(len(bot.backend.calls), 1)
        self.assertIn("[42]", bot.backend.calls[0][1])
        self.assertIn("2.1 Не оскорблять", bot.backend.calls[0][1])
        self.assertEqual(bot.client.sent, [(-1001, "!мут 1 час\nautomod 2.1", 42)])
        self.assertEqual(bot.state.chat(-1001)["buffer"], [])
        self.assertEqual(bot.state.chat(-1001)["punished"], [42])
        logged = [json.loads(l) for l in (self.dir / "actions.log").read_text().splitlines()]
        self.assertEqual(logged[-1]["command"], "!мут 1 час\nautomod 2.1")

    def test_deleted_message_uses_target(self):
        answer = json.dumps({"violations": [{"message_id": 42, "rule": "2.1",
                                             "punishment": "mute", "duration_minutes": 60}]})
        bot = self.make_bot(answer)
        bot.client.gone = {42}

        async def scenario():
            await self.feed(bot, 100)
            while bot.busy:
                await asyncio.sleep(0)
        asyncio.run(scenario())
        author = 1000 + 42 % 7
        self.assertEqual(bot.client.sent, [(-1001, f"!мут 1 час @user{author}\nautomod 2.1", None)])

    def test_counter_survives_restart(self):
        bot = self.make_bot('{"violations": []}')
        asyncio.run(self.feed(bot, 60))
        state2 = automod.State(self.dir / "state.json")
        self.assertEqual(len(state2.chat(-1001)["buffer"]), 60)
        bot2 = automod.Automod(FakeClient(), state2, 1, SETTINGS, FakeBackend('{"violations": []}'))
        bot2.protected_ids = mock.AsyncMock(return_value={1})

        async def scenario():
            await self.feed(bot2, 40, start=61)
            while bot2.busy:
                await asyncio.sleep(0)
        asyncio.run(scenario())
        self.assertEqual(len(bot2.backend.calls), 1)

    def test_ignored_messages(self):
        bot = self.make_bot('{"violations": []}')

        async def scenario():
            await bot.on_message(fake_event(-1001, 1, 1, "своё"))  # owner
            await bot.on_message(fake_event(-1001, 2, 5, ".automod status"))
            await bot.on_message(fake_event(-1002, 3, 5, "другой чат"))  # not enabled
            await bot.on_message(fake_event(-1001, 4, 5, "лс", is_group=False))
        asyncio.run(scenario())
        self.assertEqual(bot.state.chat(-1001)["buffer"], [])

    def test_admins_never_punished(self):
        answer = json.dumps([{"message_id": i, "punishment": "ban", "category": "spam"}
                             for i in range(1, 101)])
        bot = self.make_bot(answer, admins={1001, 1002})

        async def scenario():
            await self.feed(bot, 100)
            while bot.busy:
                await asyncio.sleep(0)
        asyncio.run(scenario())
        # 7 distinct authors, 2 are admins, cap 5
        self.assertEqual(len(bot.client.sent), 5)
        # rule 2.1 names no ban, so the bans become short mutes
        self.assertTrue(all(text.startswith("!мут 1 час\n") for _, text, _ in bot.client.sent))
        self.assertIn("[админ]", bot.backend.calls[0][1])

    def test_dry_run(self):
        bot = self.make_bot('{"violations": [{"message_id": 3, "punishment": "warn"}]}')
        bot.settings = dict(SETTINGS, dry_run=True)

        async def scenario():
            await self.feed(bot, 100)
            while bot.busy:
                await asyncio.sleep(0)
        asyncio.run(scenario())
        self.assertEqual(bot.client.sent, [])
        self.assertIn('"dry_run": true', (self.dir / "actions.log").read_text())

    def test_llm_failure_drops_batch(self):
        bot = self.make_bot("")
        bot.backend.complete = mock.AsyncMock(side_effect=RuntimeError("down"))

        async def scenario():
            await self.feed(bot, 100)
            while bot.busy:
                await asyncio.sleep(0)
        asyncio.run(scenario())
        self.assertEqual(bot.state.chat(-1001)["buffer"], [])
        self.assertIn("batch_failed", (self.dir / "actions.log").read_text())


class BotAds(unittest.TestCase):
    W = automod.ad_whitelist(SETTINGS)

    def ad(self, text="", **kw):
        return automod.detect_bot_ad({"text": text, **kw}, self.W)

    def test_detects(self):
        self.assertTrue(self.ad("лучший бот @SuperCashBot"))
        self.assertTrue(self.ad("заходи t.me/free_stars_bot"))
        self.assertTrue(self.ad("жми https://t.me/somegame?start=ref123"))
        self.assertTrue(self.ad("Переходи в бота и забирай подарок"))
        self.assertTrue(self.ad("Заработок от 5000 в день без вложений, пиши @manager_vip"))
        self.assertTrue(self.ad("", urls=["https://t.me/xbot?start=1"]))
        self.assertTrue(self.ad("пробуй", via_bot="gamee", buttons=["https://t.me/gamee?start=x"]))
        self.assertTrue(self.ad("что угодно", fwd_kind="bot", fwd_name="promo_bot"))
        self.assertTrue(self.ad("Новый бот @moneyrain_bot", fwd_kind="channel"))
        self.assertTrue(self.ad("привет", sender_is_bot=True, sender_username="spam_bot"))

    def test_not_flagged(self):
        self.assertIsNone(self.ad("привет всем, как дела?"))
        self.assertIsNone(self.ad("у меня доход упал, грустно"))  # earnings word, no link
        self.assertIsNone(self.ad("спроси у @iris_moon_bot"))  # whitelisted Iris
        self.assertIsNone(self.ad("ок", sender_is_bot=True, sender_username="iris_cm_bot"))
        self.assertIsNone(self.ad("новости дня", fwd_kind="channel"))
        self.assertIsNone(self.ad("смешной стикер", via_bot="sticker", buttons=[]))
        self.assertIsNone(self.ad("пиши на почту v1pach@yandex.com"))
        self.assertIsNone(automod.detect_bot_ad({"text": "@my_helper_bot"}, ["my_helper_bot"]))

    def test_features(self):
        entity = SimpleNamespace(url="https://t.me/x_bot")
        button = SimpleNamespace(url="https://t.me/y?start=1")
        message = SimpleNamespace(message="hi", entities=[entity],
                                  reply_markup=SimpleNamespace(rows=[SimpleNamespace(buttons=[button])]),
                                  via_bot_id=None, fwd_from=None)
        f = asyncio.run(automod.ad_features(message, SimpleNamespace(bot=False, username="u")))
        self.assertEqual(f["urls"], ["https://t.me/x_bot"])
        self.assertEqual(f["buttons"], ["https://t.me/y?start=1"])

        class PeerUser:
            pass
        fwd = SimpleNamespace(from_id=PeerUser(), from_name=None)
        source = SimpleNamespace(bot=True, username="promo_bot")
        message = SimpleNamespace(message="x", fwd_from=fwd,
                                  forward=SimpleNamespace(get_sender=mock.AsyncMock(return_value=source)))
        f = asyncio.run(automod.ad_features(message, None))
        self.assertEqual((f["fwd_kind"], f["fwd_name"]), ("bot", "promo_bot"))


class AdFlow(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=TMP))
        self.log_patch = mock.patch.object(automod, "ACTIONS_LOG", self.dir / "actions.log")
        self.log_patch.start()
        self.utils_patch = mock.patch.object(
            automod, "utils", SimpleNamespace(get_display_name=lambda s: s.first_name))
        self.utils_patch.start()

    def tearDown(self):
        self.log_patch.stop()
        self.utils_patch.stop()

    def make_bot(self, rules="1. Реклама ботов — мут 1 день\n2. Без мата", admins=(), **settings):
        state = automod.State(self.dir / "state.json")
        state.chat(-1001).update(enabled=True, rules=rules)
        bot = automod.Automod(FakeClient(), state, 1, dict(SETTINGS, ad_punish_delay=0, **settings),
                              FakeBackend('{"violations": []}'))
        bot.protected_ids = mock.AsyncMock(return_value={1, *admins})
        return bot

    def send(self, automod_bot, text, user_id=500, **kw):
        asyncio.run(automod_bot.on_message(fake_event(-1001, 77, user_id, text, **kw)))

    def test_punish_then_delete(self):
        bot = self.make_bot()
        self.send(bot, "Переходи в бота @free_money_bot", username="spammer")
        self.assertEqual(bot.client.calls, [("send", "!мут 1 сутки\nautomod 1", 77),
                                            ("delete", [77])])
        self.assertEqual(bot.state.chat(-1001)["buffer"], [])
        log = (self.dir / "actions.log").read_text()
        self.assertIn("delete_ad", log)
        # cooldown: the second ad is deleted without a second punishment
        self.send(bot, "снова @free_money_bot", username="spammer")
        self.assertEqual([c[0] for c in bot.client.calls], ["send", "delete", "delete"])

    def test_reply_failure_falls_back_to_target(self):
        bot = self.make_bot()
        original = bot.client.send_message

        async def flaky(chat, text, **kw):
            if kw.get("reply_to"):
                raise RuntimeError("reply failed")
            return await original(chat, text, **kw)
        bot.client.send_message = flaky
        self.send(bot, "t.me/cash_bot?start=1", username="spammer")
        self.assertEqual(bot.client.calls, [("delete", [77]),
                                            ("send", "!мут 1 сутки @spammer\nautomod 1", None)])

    def test_rules_without_ads_only_delete(self):
        bot = self.make_bot(rules="1. Без мата\n2. Уважайте друг друга")
        self.send(bot, "@free_money_bot лучший")
        self.assertEqual(bot.client.calls, [("delete", [77])])

    def test_default_rules_warn(self):
        bot = self.make_bot(rules="")
        self.send(bot, "@free_money_bot лучший", username=None)
        self.assertEqual(bot.client.calls[0][1], "!варн\nautomod 1")

    def test_bot_sender_deleted_without_punishment(self):
        bot = self.make_bot()
        self.send(bot, "Купи!", bot=True, username="adv_bot")
        self.assertEqual(bot.client.calls, [("delete", [77])])

    def test_admin_and_owner_protected(self):
        bot = self.make_bot(admins={500})
        self.send(bot, "@free_money_bot")
        self.send(bot, "@free_money_bot", user_id=-1001)  # anonymous admin
        self.assertEqual(bot.client.calls, [])
        self.assertEqual(len(bot.state.chat(-1001)["buffer"]), 2)

    def test_disabled_flag_and_dry_run(self):
        bot = self.make_bot(delete_bot_ads=False)
        self.send(bot, "@free_money_bot")
        self.assertEqual(bot.client.calls, [])
        bot = self.make_bot(dry_run=True)
        self.send(bot, "@free_money_bot")
        self.assertEqual(bot.client.calls, [])
        self.assertIn('"dry_run": true', (self.dir / "actions.log").read_text())

    def test_plain_message_buffered(self):
        bot = self.make_bot()
        self.send(bot, "всем привет")
        self.assertEqual(bot.client.calls, [])
        self.assertEqual(len(bot.state.chat(-1001)["buffer"]), 1)


class Commands(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=TMP))
        self.log_patch = mock.patch.object(automod, "ACTIONS_LOG", self.dir / "actions.log")
        self.log_patch.start()

    def tearDown(self):
        self.log_patch.stop()

    def make_bot(self, perms, pinned=None, about=None, fetched="1.1 Правило"):
        client = FakeClient()
        client.get_entity = mock.AsyncMock(return_value=SimpleNamespace(id=1, title="Чат"))
        client.get_permissions = mock.AsyncMock(return_value=perms)
        client.get_messages = mock.AsyncMock(
            return_value=SimpleNamespace(message="3.1 Правила из сообщения"))
        bot = automod.Automod(client, automod.State(self.dir / "s.json"), 1, SETTINGS,
                              FakeBackend(""), fetcher=lambda url: fetched)
        bot.pinned_and_about = mock.AsyncMock(return_value=(pinned, about))
        return bot

    def admin(self, **kw):
        return SimpleNamespace(**{"is_creator": False, "is_admin": True, "ban_users": True,
                                  "delete_messages": True, **kw})

    def run_cmd(self, bot, text, sender=1):
        event = fake_event(-1001, 50, sender, text)
        asyncio.run(bot.on_command(event))
        return event

    def test_enable_default_rules_and_delete(self):
        bot = self.make_bot(self.admin())
        event = self.run_cmd(bot, ".automod")
        event.delete.assert_awaited_once()
        chat = bot.state.chat(-1001)
        self.assertTrue(chat["enabled"])
        self.assertEqual(chat["rules"], automod.DEFAULT_RULES)
        self.assertIn("automod включён", bot.client.sent[-1][1])
        self.assertNotIn("Внимание", bot.client.sent[-1][1])

    def test_pinned_then_about(self):
        bot = self.make_bot(self.admin(), pinned="1. Не спамить, 2. Не оскорблять никого тут",
                            about="описание с правилами чата, достаточно длинное")
        self.run_cmd(bot, ".automod")
        self.assertEqual(bot.state.chat(-1001)["rules_source"], "закреплённое сообщение")
        bot = self.make_bot(self.admin(), pinned="ок", about="Правила: 1. Без рекламы. 2. Без мата.")
        self.run_cmd(bot, ".automod")
        self.assertEqual(bot.state.chat(-1001)["rules_source"], "описание чата")

    def test_pinned_link_followed(self):
        bot = self.make_bot(self.admin(), pinned="Правила чата тут: https://telegra.ph/Pr-01",
                            fetched="2.1 Не оскорблять")
        self.run_cmd(bot, ".automod")
        self.assertEqual(bot.state.chat(-1001)["rules"], "2.1 Не оскорблять")

    def test_rules_from_links(self):
        bot = self.make_bot(self.admin(), fetched="2.1 С сайта")
        self.run_cmd(bot, ".automod -r=https://telegra.ph/Pr-01")
        self.assertEqual(bot.state.chat(-1001)["rules"], "2.1 С сайта")
        self.run_cmd(bot, ".automod -r=https://t.me/c/555/77")
        self.assertEqual(bot.state.chat(-1001)["rules"], "3.1 Правила из сообщения")
        bot.client.get_messages.assert_awaited_with(-100555, ids=77)

    def test_not_admin_reported(self):
        bot = self.make_bot(self.admin(is_admin=False))
        self.run_cmd(bot, ".automod")
        self.assertIn("не администратор", bot.client.sent[-1][1])

    def test_off_and_status(self):
        bot = self.make_bot(self.admin())
        self.run_cmd(bot, ".automod")
        self.run_cmd(bot, ".automod status")
        self.assertIn("включён", bot.client.sent[-1][1])
        self.run_cmd(bot, ".automod off")
        self.assertFalse(bot.state.chat(-1001)["enabled"])
        self.assertIn("выключен", bot.client.sent[-1][1])

    def test_stranger_ignored(self):
        bot = self.make_bot(self.admin())
        event = self.run_cmd(bot, ".automod", sender=777)
        event.delete.assert_not_awaited()
        self.assertFalse(bot.state.chat(-1001)["enabled"])

    def test_bad_link_reported(self):
        bot = self.make_bot(self.admin())
        event = self.run_cmd(bot, ".automod -r=t.me/chat")
        event.delete.assert_awaited_once()
        self.assertIn("ошибка", bot.client.sent[-1][1])
        self.assertFalse(bot.state.chat(-1001)["enabled"])


class AndroidRun(unittest.TestCase):
    def test_env_credentials(self):
        with mock.patch.dict(os.environ, {"AUTOMOD_API_ID": "123", "AUTOMOD_API_HASH": "abc"}):
            self.assertEqual(automod.load_api_credentials(), {"api_id": 123, "api_hash": "abc"})

    def test_run_never_prompts_without_session(self):
        client = mock.MagicMock()
        client.connect = mock.AsyncMock()
        client.disconnect = mock.AsyncMock()
        client.is_user_authorized = mock.AsyncMock(return_value=False)
        with mock.patch.object(automod, "make_client", return_value=client), \
                mock.patch("builtins.input", side_effect=AssertionError("prompted")), \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), \
                mock.patch.object(automod, "load_settings", return_value=dict(SETTINGS, backend="api")):
            with self.assertRaises(SystemExit) as caught:
                asyncio.run(automod.run())
        self.assertIn("Нет входа", str(caught.exception))

    def test_run_without_api_key_exits(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}), \
                mock.patch.object(automod, "load_settings", return_value=dict(SETTINGS, backend="api")):
            with self.assertRaises(SystemExit) as caught:
                asyncio.run(automod.run())
        self.assertIn("API key", str(caught.exception))


class Prompt(unittest.TestCase):
    def test_system_prompt(self):
        prompt = automod.SYSTEM_PROMPT.format(max_per_batch=5)
        self.assertIn("не больше 5", prompt)
        self.assertIn('"violations"', prompt)

    def test_batch_text_tags(self):
        text = automod.build_batch_text("R", [msg(1, 5), msg(2, 6, is_bot=True), msg(3, 7)], {7})
        lines = text.splitlines()
        self.assertTrue(any(l.startswith("[2]") and "[бот]" in l for l in lines))
        self.assertTrue(any(l.startswith("[3]") and "[админ]" in l for l in lines))
        self.assertFalse(any(l.startswith("[1]") and "[" in l[3:] for l in lines))


class NewParse(unittest.TestCase):
    def test_delete_flag(self):
        self.assertEqual(automod.parse_command(".automod -d"), {"action": "delete", "rules": None})
        self.assertEqual(automod.parse_command(".automod -r=t.me/c/1/2 -d")["action"], "delete")
        self.assertEqual(automod.parse_command(".automod -d -r t.me/c/1/2")["action"], "delete")
        self.assertEqual(automod.parse_command(".automod off -d")["action"], "help")

    def test_context_and_ams(self):
        self.assertEqual(automod.parse_command(".context 50"),
                         {"action": "context", "value": 50, "rules": None})
        self.assertIsNone(automod.parse_command(".context")["value"])
        self.assertEqual(automod.parse_command(".context abc")["action"], "help")
        self.assertEqual(automod.parse_command(" .AMS ")["action"], "ams")
        self.assertIsNone(automod.parse_command(".amsterdam"))
        self.assertIsNone(automod.parse_command(".contexts 5"))


class GeminiChain(unittest.TestCase):
    def test_argv_has_no_auto_approve(self):
        b = automod.GeminiBackend("gemini-2.5-flash", sandbox=Path(TMP) / "sb")
        argv = b.argv("gemini")
        self.assertEqual(argv[:5], ["gemini", "-m", "gemini-2.5-flash", "-o", "json"])
        self.assertEqual(argv[5], "-p")
        for bad in ("-y", "--yolo", "--approval-mode", "--allowed-tools", "--skip-trust"):
            self.assertNotIn(bad, argv)

    def test_settings_file_disables_tools(self):
        b = automod.GeminiBackend("m", sandbox=Path(TMP) / "sb2")
        b.write_settings()
        data = json.loads((Path(TMP) / "sb2" / ".gemini" / "settings.json").read_text())
        self.assertEqual(data["tools"]["core"], [])
        self.assertIn("run_shell_command", data["tools"]["exclude"])
        self.assertEqual(data["mcp"]["allowed"], [])
        self.assertEqual(data["mcpServers"], {})
        self.assertNotIn("allowed", data["tools"])  # never a confirmation bypass

    def run_gemini(self, stdout, code=0, stderr=b""):
        class Proc:
            returncode = code

            async def communicate(self, data=None):
                Proc.stdin = data
                return stdout, stderr
        captured = {}

        async def fake_exec(*argv, **kw):
            captured["argv"], captured["kw"] = argv, kw
            return Proc()
        b = automod.GeminiBackend("m", sandbox=Path(TMP) / "sb3")
        with mock.patch.object(automod.asyncio, "create_subprocess_exec", fake_exec):
            try:
                return asyncio.run(b._once("СИСТЕМА", "ЧАТ")), captured, Proc
            except RuntimeError as error:
                return error, captured, Proc

    def test_gemini_success_stdin_and_cwd(self):
        out = json.dumps({"response": '{"violations": []}'}).encode()
        reply, captured, proc = self.run_gemini(out)
        self.assertEqual(reply, '{"violations": []}')
        self.assertIn("СИСТЕМА".encode(), proc.stdin)
        self.assertIn("ЧАТ".encode(), proc.stdin)
        self.assertEqual(Path(captured["kw"]["cwd"]), Path(TMP) / "sb3")
        self.assertNotIn("--yolo", captured["argv"])

    def test_gemini_failures(self):
        err, _, _ = self.run_gemini(b"", code=1, stderr=b"429 quota exceeded")
        self.assertIsInstance(err, automod.RateLimited)
        err, _, _ = self.run_gemini(b"", code=1, stderr=b"boom")
        self.assertNotIsInstance(err, automod.RateLimited)
        err, _, _ = self.run_gemini(b"not json")
        self.assertIsInstance(err, RuntimeError)
        err, _, _ = self.run_gemini(json.dumps({"error": {"message": "RESOURCE_EXHAUSTED"}}).encode())
        self.assertIsInstance(err, automod.RateLimited)

    def fake(self, name, answer=None, error=None):
        b = FakeBackend(answer)
        b.name = name
        if error:
            b.complete = mock.AsyncMock(side_effect=error)
        return b

    def test_chain_fallback_and_unparseable(self):
        now = [0]
        a = self.fake("cli", "no json here")
        g = self.fake("gemini", error=RuntimeError("exit 1"))
        c = self.fake("api", '{"violations": []}')
        chain = automod.ChainBackend([a, g, c], 1800, clock=lambda: now[0])
        self.assertEqual(asyncio.run(chain.complete("s", "t")), '{"violations": []}')
        self.assertEqual(chain.name, "cli+gemini+api")
        chain = automod.ChainBackend([a, g], 1800)
        with self.assertRaises(RuntimeError):
            asyncio.run(chain.complete("s", "t"))

    def test_chain_rate_limit_cooldown(self):
        now = [0]
        a = self.fake("cli", error=automod.RateLimited("usage limit"))
        g = self.fake("gemini", '{"violations": []}')
        chain = automod.ChainBackend([a, g], 1800, clock=lambda: now[0])
        asyncio.run(chain.complete("s", "t"))
        asyncio.run(chain.complete("s", "t"))
        self.assertEqual(a.complete.await_count, 1)  # skipped during the cooldown
        now[0] = 1801
        asyncio.run(chain.complete("s", "t"))
        self.assertEqual(a.complete.await_count, 2)

    def test_auto_filters_available(self):
        def build(have_claude, have_gemini, key):
            def which(name):
                return "/bin/" + name if (name == "claude" and have_claude) or (
                    name == "gemini" and have_gemini) else None
            with mock.patch.object(automod.shutil, "which", which), \
                    mock.patch.object(automod.Path, "exists", return_value=False), \
                    mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": key}):
                return automod.make_backend(dict(SETTINGS, api_key=""))
        self.assertEqual(build(True, True, "k").name, "cli+gemini+api")
        self.assertEqual(build(False, True, "k").name, "gemini+api")
        self.assertEqual(build(False, True, "").name, "gemini")
        self.assertEqual(build(False, False, "k").name, "api")
        explicit = automod.make_backend(dict(SETTINGS, backend=["gemini", "cli"]))
        self.assertEqual(explicit.name, "gemini+cli")


class NewCommands(Commands):
    def setUp(self):
        super().setUp()
        self.utils_patch = mock.patch.object(
            automod, "utils", SimpleNamespace(get_display_name=lambda s: s.first_name))
        self.utils_patch.start()

    def tearDown(self):
        self.utils_patch.stop()
        super().tearDown()

    def bot_enabled(self):
        bot = self.make_bot(self.admin())
        self.run_cmd(bot, ".automod")
        bot.protected_ids = mock.AsyncMock(return_value={1})
        return bot

    def test_context(self):
        bot = self.bot_enabled()
        event = self.run_cmd(bot, ".context")
        event.delete.assert_awaited_once()
        self.assertIn("100", bot.client.sent[-1][1])
        self.run_cmd(bot, ".context 30")
        self.assertEqual(bot.batch_size(-1001), 30)
        self.assertIn("30/30" if False else "30", bot.client.sent[-1][1])
        self.run_cmd(bot, ".context 5")
        self.assertEqual(bot.batch_size(-1001), 10)
        self.run_cmd(bot, ".context 9999")
        self.assertEqual(bot.batch_size(-1001), 500)
        self.run_cmd(bot, ".automod status")
        self.assertIn("/500", bot.client.sent[-1][1])

    def test_context_triggers_check(self):
        bot = self.bot_enabled()
        bot.backend = FakeBackend('{"violations": []}')
        self.run_cmd(bot, ".context 10")

        async def scenario():
            for i in range(1, 11):
                await bot.on_message(fake_event(-1001, i, 500 + i, f"текст {i}"))
            while bot.busy:
                await asyncio.sleep(0)
            for _ in range(20):
                await asyncio.sleep(0)
        asyncio.run(scenario())
        self.assertEqual(len(bot.backend.calls), 1)

    def test_delete_removes_everything(self):
        bot = self.bot_enabled()
        self.run_cmd(bot, ".context 20")
        bot.state.add_message(-1001, msg(1, 5))
        event = self.run_cmd(bot, ".automod -d")
        event.delete.assert_awaited_once()
        self.assertNotIn("-1001", bot.state.chats)
        self.assertIn("удалён", bot.client.sent[-1][1])
        self.assertFalse(bot.state.enabled(-1001))
        self.assertEqual(bot.batch_size(-1001), SETTINGS["batch_size"])
        self.assertNotIn("-1001", json.loads((self.dir / "s.json").read_text())["chats"])

    def history_msg(self, i, user=600):
        return SimpleNamespace(id=i, message=f"старое {i}", action=None, media=None,
                               sender_id=user + i % 3, reply_to_msg_id=None,
                               get_sender=mock.AsyncMock(return_value=SimpleNamespace(
                                   id=user + i % 3, username=f"u{i}", bot=False, first_name=f"H{i}")))

    def test_ams_disabled(self):
        bot = self.make_bot(self.admin())
        self.run_cmd(bot, ".ams")
        self.assertIn("не включён", bot.client.sent[-1][1])
        self.assertEqual(bot.backend.calls, [])

    def test_ams_buffer_plus_history(self):
        bot = self.bot_enabled()
        self.run_cmd(bot, ".context 10")
        bot.backend = FakeBackend(json.dumps({"violations": [
            {"message_id": 3, "rule": "1.1", "punishment": "mute", "duration_minutes": 60}]}))
        bot.client.history = [self.history_msg(i) for i in range(1, 8)]  # 1..7 in Telegram
        for i in (8, 9, 10, 11):  # buffered
            bot.state.add_message(-1001, msg(i, 700 + i, f"буфер {i}"))
        self.run_cmd(bot, ".ams")
        self.assertEqual(len(bot.backend.calls), 1)
        text = bot.backend.calls[0][1]
        for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
            if i == 1:
                continue  # 10 messages: ids 2..11
            self.assertIn(f"[{i}]", text)
        self.assertNotIn("[1] ", text)
        self.assertEqual(bot.state.chat(-1001)["buffer"], [])
        self.assertTrue(any("!мут" in t for _, t, _ in bot.client.sent))
        self.assertIn("проверено сообщений: 10", bot.client.sent[-1][1])

    def test_ams_empty(self):
        bot = self.bot_enabled()
        self.run_cmd(bot, ".ams")
        self.assertIn("нет сообщений", bot.client.sent[-1][1])


class AlreadyPunished(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=TMP))
        self.log_patch = mock.patch.object(automod, "ACTIONS_LOG", self.dir / "actions.log")
        self.log_patch.start()
        self.utils_patch = mock.patch.object(
            automod, "utils", SimpleNamespace(get_display_name=lambda s: s.first_name))
        self.utils_patch.start()

    def tearDown(self):
        self.log_patch.stop()
        self.utils_patch.stop()

    def make_bot(self, **settings):
        state = automod.State(self.dir / "s.json")
        state.chat(-1001).update(enabled=True, rules="1. Реклама ботов — мут 1 день\n2. Без мата")
        bot = automod.Automod(FakeClient(), state, 1, dict(SETTINGS, ad_punish_delay=0, **settings),
                              FakeBackend(""))
        bot.protected_ids = mock.AsyncMock(return_value={1, 9})
        return bot

    def violation(self, mid=42, user=500):
        return {"message_id": mid, "user_id": user, "rule": "2", "punishment": "mute",
                "duration_minutes": 60, "reason": "мат"}

    def punish(self, bot, **kw):
        violation = self.violation(**kw)
        batch = [msg(violation["message_id"], violation["user_id"], "мат")]
        return asyncio.run(bot.punish(-1001, violation, batch))

    def skips(self):
        path = self.dir / "actions.log"
        rows = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
        return [r for r in rows if r["action"] == "skip_already_punished"]

    def test_normal_punishment_recorded(self):
        bot = self.make_bot()
        self.assertTrue(self.punish(bot))
        self.assertEqual(len(bot.client.sent), 1)
        self.assertEqual(bot.state.chat(-1001)["punish_log"][0]["user_id"], 500)

    def test_a_same_message_and_recent_user_rule(self):
        bot = self.make_bot()
        bot.state.chat(-1001)["punished"] = [42]
        self.assertFalse(self.punish(bot))
        bot = self.make_bot()
        bot.record_punishment(-1001, 500, "2")
        self.assertFalse(self.punish(bot, mid=43))
        self.assertEqual(bot.client.sent, [])
        self.assertEqual(len(self.skips()), 2)
        # outside the window the punishment is allowed again
        bot = self.make_bot(punish_recent_seconds=0)
        bot.record_punishment(-1001, 500, "2")
        self.assertTrue(self.punish(bot, mid=44))

    def test_b_admin_reply(self):
        bot = self.make_bot()
        bot.client.replies[42] = [SimpleNamespace(message="Варн\nмат", sender_id=9,
                                                  get_sender=mock.AsyncMock())]
        self.assertFalse(self.punish(bot))
        self.assertEqual(bot.client.sent, [])
        self.assertIn("ответил", self.skips()[0]["reason"])

    def test_b_iris_reply_and_chatter_ignored(self):
        bot = self.make_bot()
        iris = SimpleNamespace(username="iris_cm_bot")
        bot.client.replies[42] = [SimpleNamespace(message="Пользователь замучен", sender_id=77,
                                                  get_sender=mock.AsyncMock(return_value=iris))]
        self.assertFalse(self.punish(bot))
        bot = self.make_bot()
        stranger = SimpleNamespace(username="someone")
        bot.client.replies[42] = [
            SimpleNamespace(message="бан ему!", sender_id=123,
                            get_sender=mock.AsyncMock(return_value=stranger)),
            SimpleNamespace(message="согласен", sender_id=9, get_sender=mock.AsyncMock())]
        self.assertTrue(self.punish(bot))

    def test_c_already_banned(self):
        bot = self.make_bot()
        bot.client.banned = {500}
        self.assertFalse(self.punish(bot))
        self.assertEqual(bot.client.sent, [])
        self.assertIn("забанен", self.skips()[0]["reason"])

    def test_ad_path_deletes_but_skips_punishment(self):
        bot = self.make_bot()
        bot.client.banned = {500}
        asyncio.run(bot.on_message(fake_event(-1001, 77, 500, "Переходи в бота @free_money_bot",
                                              username="spammer")))
        self.assertEqual(bot.client.calls, [("delete", [77])])
        self.assertEqual(len(self.skips()), 1)




import json  # noqa: E402
import logging  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

MOD = automod


class Providers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        previous = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, previous)

    KEY = "sk-SECRET-123456"

    def provider(self, pid="p1", **kw):
        return {"id": pid, "kind": "openai", "title": pid, "base_url": "https://llm.example/v1",
                "api_key": self.KEY, "model": "m1", "headers": {"X-Org": "org-SECRET-42"},
                "timeout": 5, **kw}

    def settings(self, **kw):
        return {"backend": "auto", "model": "claude-haiku-5-5", "gemini_model": "gemini-2.5-flash",
                "api_key": "", "api_url": "https://api.anthropic.com/v1/messages",
                "llm_timeout": 30, "backend_cooldown": 100, **kw}

    def backend(self, opener, **kw):
        b = MOD.OpenAIBackend(self.provider(**kw), opener=opener)
        b.retry_delay = 0
        return b

    @staticmethod
    def answering(content, seen=None):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

        def opener(request, timeout=None):
            if seen is not None:
                seen.append((request, timeout))
            return Response()
        return opener

    @staticmethod
    def failing(code, body=""):
        import io
        import urllib.error

        def opener(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, code, "err", {}, io.BytesIO(body.encode()))
        return opener

    def write_file(self, data):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = Path(d) / "providers.json"
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        return path

    # ---- providers file

    def test_load_keeps_order_and_ignores_unknown_ids(self):
        path = self.write_file({"providers": [self.provider("a"), self.provider("b"), self.provider("c")],
                                "order": ["c", "zzz", "a"]})
        self.assertEqual([p["id"] for p in MOD.load_providers(path)], ["c", "a"])

    def test_missing_order_uses_file_order(self):
        path = self.write_file({"providers": [self.provider("a"), self.provider("b")]})
        self.assertEqual([p["id"] for p in MOD.load_providers(path)], ["a", "b"])

    def test_env_var_points_to_file(self):
        from unittest.mock import patch
        path = self.write_file({"providers": [self.provider("a")], "order": ["a"]})
        with patch.dict("os.environ", {"TELESCRIPT_LLM_PROVIDERS_FILE": str(path)}):
            self.assertEqual([p["id"] for p in MOD.load_providers()], ["a"])
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("TELESCRIPT_LLM_PROVIDERS_FILE", None)
            self.assertEqual(MOD.load_providers(), [])

    def test_broken_file_gives_no_providers_and_logs_no_content(self):
        path = self.write_file('{"api_key": "%s" oops' % self.KEY)
        with self.assertLogs(MOD.log, level="WARNING") as logs:
            self.assertEqual(MOD.load_providers(path), [])
        self.assertNotIn(self.KEY, "\n".join(logs.output))
        self.assertEqual(MOD.load_providers(Path(path).parent / "nope.json"), [])

    # ---- the openai kind

    async def test_response_is_parsed(self):
        seen = []
        b = self.backend(self.answering("  привет  ", seen))
        self.assertEqual(await b.complete("sys", "user"), "привет")
        request, timeout = seen[0]
        self.assertEqual(request.full_url, "https://llm.example/v1/chat/completions")
        self.assertEqual(timeout, 5)
        self.assertEqual(request.get_header("Authorization"), f"Bearer {self.KEY}")
        self.assertEqual(request.get_header("X-org"), "org-SECRET-42")

    async def test_list_content_parts(self):
        b = self.backend(self.answering([{"type": "text", "text": "а"}, {"type": "text", "text": "б"}]))
        self.assertEqual(await b.complete("s", "u"), "аб")

    async def test_payload_has_messages_and_no_tools(self):
        seen = []
        b = self.backend(self.answering("ok", seen), extra_body={
            "tools": [{"type": "function"}], "functions": [1], "tool_choice": "auto",
            "reasoning_effort": "low"})
        await b.complete("SYSTEM", "USER")
        body = json.loads(seen[0][0].data)
        self.assertEqual(body["messages"], [{"role": "system", "content": "SYSTEM"},
                                            {"role": "user", "content": "USER"}])
        self.assertEqual(body["model"], "m1")
        self.assertLessEqual(body["temperature"], 0.5)
        self.assertFalse(body["stream"])
        self.assertEqual(body["reasoning_effort"], "low")  # harmless extra_body is kept
        for key in ("tools", "functions", "tool_choice", "function_call"):
            self.assertNotIn(key, body)

    async def test_deepseek_style_base_url(self):
        seen = []
        b = MOD.OpenAIBackend(self.provider(base_url="https://api.deepseek.com/"),
                              opener=self.answering("ok", seen))
        await b.complete("s", "u")
        self.assertEqual(seen[0][0].full_url, "https://api.deepseek.com/chat/completions")

    async def test_rate_limit_statuses_are_not_retried(self):
        for code in (429, 402):
            calls = []

            def opener(request, timeout=None, code=code):
                calls.append(1)
                return self.failing(code, "slow down")(request, timeout)
            with self.assertRaises(MOD.RateLimited):
                await self.backend(opener).complete("s", "u")
            self.assertEqual(len(calls), 1)

    async def test_quota_text_in_a_400_is_a_limit(self):
        with self.assertRaises(MOD.RateLimited):
            await self.backend(self.failing(400, "Insufficient Balance")).complete("s", "u")

    async def test_server_error_is_retried_once(self):
        calls = []

        def opener(request, timeout=None):
            calls.append(1)
            return self.failing(500, "boom")(request, timeout)
        with self.assertRaises(RuntimeError) as ctx:
            await self.backend(opener).complete("s", "u")
        self.assertNotIsInstance(ctx.exception, MOD.RateLimited)
        self.assertEqual(len(calls), 2)

    async def test_error_text_is_short_and_scrubbed(self):
        body = f"Incorrect API key provided: {self.KEY}. " + "x" * 5000
        with self.assertRaises(RuntimeError) as ctx:
            await self.backend(self.failing(401, body)).complete("s", "u")
        text = str(ctx.exception)
        self.assertNotIn(self.KEY, text)
        self.assertLess(len(text), 400)

    async def test_bad_responses(self):
        for content in ("", "   ", None):
            with self.assertRaises(RuntimeError):
                await self.backend(self.answering(content)).complete("s", "u")

        class Garbage:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"<html>not json"
        with self.assertRaises(RuntimeError):
            await self.backend(lambda r, timeout=None: Garbage()).complete("s", "u")

    async def test_network_error(self):
        import urllib.error

        def opener(request, timeout=None):
            raise urllib.error.URLError(f"cannot reach {self.KEY}")
        with self.assertRaises(RuntimeError) as ctx:
            await self.backend(opener).complete("s", "u")
        self.assertNotIn(self.KEY, str(ctx.exception))

    def test_provider_needs_base_url(self):
        with self.assertRaises(ValueError):
            MOD.OpenAIBackend({"id": "x", "kind": "openai"})

    # ---- the chain

    def build(self, backend="auto", providers=None, **kw):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as home, patch("shutil.which", return_value=None), \
                patch("pathlib.Path.home", return_value=Path(home)):
            return MOD.make_backend(self.settings(backend=backend, **kw), providers)

    @staticmethod
    def names(b):
        return [x.name for x in getattr(b, "backends", [b])]

    def test_auto_is_cli_gemini_providers_then_api(self):
        from unittest.mock import patch
        providers = [self.provider("b"), self.provider("a")]
        with tempfile.TemporaryDirectory() as home:
            bin_dir = Path(home) / ".local/bin"
            bin_dir.mkdir(parents=True)
            for name in ("claude", "gemini"):
                (bin_dir / name).write_text("")
            with patch("shutil.which", return_value=None), patch("pathlib.Path.home", return_value=Path(home)):
                chain = MOD.make_backend(self.settings(api_key="k-anthropic"), providers)
        self.assertEqual(self.names(chain), ["cli", "gemini", "b", "a", "api"])

    def test_auto_without_clis_and_key_uses_only_providers(self):
        chain = self.build(providers=[self.provider("b"), self.provider("a")])
        self.assertEqual(self.names(chain), ["b", "a"])

    def test_auto_with_nothing_is_an_error(self):
        with self.assertRaises(ValueError):
            self.build(providers=[])

    def test_old_names_ids_and_unknown_names(self):
        providers = [self.provider("b"), self.provider("a")]
        self.assertEqual(self.names(self.build(["a", "cli", "nonsense"], providers)), ["a", "cli"])
        self.assertEqual(self.names(self.build("providers", providers)), ["b", "a"])
        self.assertEqual(self.names(self.build("codex", providers)), ["codex"])
        self.assertEqual(self.names(self.build("api", providers, api_key="k")), ["api"])

    def test_kinds(self):
        providers = [self.provider("g"), {"id": "cx", "kind": "cli_codex", "model": "gpt-5"},
                     {"id": "weird", "kind": "alien"}]
        chain = self.build("providers", providers)
        self.assertEqual(self.names(chain), ["g", "cx"])
        self.assertIsInstance(chain.backends[0], MOD.OpenAIBackend)
        self.assertIsInstance(chain.backends[1], MOD.CodexBackend)

    async def test_chain_order_cooldown_and_fallthrough(self):
        now = [0]
        calls = []

        def make(pid, opener):
            def counting(request, timeout=None):
                calls.append(pid)
                return opener(request, timeout)
            return self.backend(counting, id=pid)
        limited = make("a", self.failing(429, "quota"))
        good = make("b", self.answering('{"ok": 1}'))
        chain = MOD.ChainBackend([limited, good], 100, clock=lambda: now[0])
        self.assertEqual(await chain.complete("s", "u"), '{"ok": 1}')
        self.assertEqual(await chain.complete("s", "u"), '{"ok": 1}')
        self.assertEqual(calls, ["a", "b", "b"])  # "a" is paused after its 429
        now[0] = 200
        await chain.complete("s", "u")
        self.assertEqual(calls[-2:], ["a", "b"])

    async def test_secrets_never_reach_logs_or_the_final_error(self):
        chain = MOD.ChainBackend([self.backend(self.failing(401, f"bad key {self.KEY}")),
                                  self.backend(self.failing(429, f"{self.KEY} quota"), id="q")])
        with self.assertLogs(MOD.log, level="DEBUG") as logs:
            with self.assertRaises(RuntimeError) as ctx:
                await chain.complete("s", "u")
        everything = "\n".join(logs.output) + str(ctx.exception)
        self.assertNotIn(self.KEY, everything)
        self.assertNotIn("org-SECRET-42", everything)

    # ---- the codex kind

    def test_codex_argv_is_read_only_without_approvals(self):
        argv = MOD.CodexBackend("gpt-5").argv("codex")
        self.assertEqual(argv, ["codex", "exec", "--sandbox", "read-only", "--ephemeral",
                                "--skip-git-repo-check",
                                "-m", "gpt-5", "-"])
        self.assertEqual(MOD.CodexBackend("").argv("codex")[-1], "-")
        self.assertNotIn("-m", MOD.CodexBackend("").argv("codex"))
        for bad in ("danger-full-access", "workspace-write", "--yolo", "--full-auto",
                    "--dangerously-bypass-approvals-and-sandbox"):
            self.assertNotIn(bad, argv)

    async def test_codex_runs_in_sandbox_with_stdin_prompt(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        proc = MagicMock(returncode=0)
        proc.communicate = AsyncMock(return_value=(" ответ \n".encode(), b"progress"))
        with tempfile.TemporaryDirectory() as box, \
                patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as spawn:
            reply = await MOD.CodexBackend("", sandbox=box).complete("СИС", "ЮЗЕР")
            self.assertEqual(spawn.await_args.kwargs["cwd"], Path(box))
        self.assertEqual(reply, "ответ")
        sent = proc.communicate.await_args.args[0].decode()
        self.assertIn("СИС", sent)
        self.assertIn("ЮЗЕР", sent)
        self.assertNotIn("OPENAI_API_KEY", spawn.await_args.kwargs["env"])

    async def test_codex_failures(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        proc = MagicMock(returncode=1)
        proc.communicate = AsyncMock(return_value=(b"", b"usage limit reached"))
        with tempfile.TemporaryDirectory() as box, \
                patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with self.assertRaises(MOD.RateLimited):
                await MOD.CodexBackend("", sandbox=box).complete("s", "u")

    async def test_codex_auth_hint(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        proc = MagicMock(returncode=1)
        proc.communicate = AsyncMock(return_value=(b"", b"Not logged in"))
        with tempfile.TemporaryDirectory() as box, \
                patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with self.assertRaises(RuntimeError) as ctx:
                await MOD.CodexBackend("", sandbox=box).complete("s", "u")
        self.assertIn("codex login", str(ctx.exception))


class ReconnectFilterTest(unittest.TestCase):
    def setUp(self):
        previous = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, previous)
        self.now = [0.0]
        self.flt = MOD.ReconnectFilter(interval=60, clock=lambda: self.now[0])
        self.out = []
        h = logging.Handler()
        h.emit = lambda r: self.out.append(r.getMessage())
        self.mod_log = MOD.log
        self.old = (self.mod_log.handlers[:], self.mod_log.level, self.mod_log.propagate)
        self.mod_log.handlers, self.mod_log.propagate = [h], False
        self.mod_log.setLevel(logging.INFO)

    def tearDown(self):
        self.mod_log.handlers, level, self.mod_log.propagate = self.old
        self.mod_log.setLevel(level)

    def rec(self, msg, name="telethon.network.mtprotosender", level=logging.WARNING, exc=None):
        return logging.LogRecord(name, level, __file__, 1, msg, None, exc)

    def test_spam_collapsed_and_rate_limited(self):
        spam = ["Server closed the connection: 0 bytes read on a total of 8 expected bytes",
                "Attempt 3 at connecting failed: OSError: Connect call failed ('149.154.167.51', 443)"]
        for _ in range(5):
            for m in spam:
                self.assertFalse(self.flt.filter(self.rec(m)))
        self.assertEqual(len(self.out), 1)
        self.assertIn("нет связи", self.out[0])
        self.now[0] = 61
        self.flt.filter(self.rec(spam[0]))
        self.assertEqual(len(self.out), 2)

    def test_restored_once(self):
        self.flt.filter(self.rec("Server closed the connection: x"))
        ok = self.rec("Connection to 149.154.167.51:443/TcpFull complete!", level=logging.INFO)
        self.assertFalse(self.flt.filter(ok))
        self.assertFalse(self.flt.filter(ok))
        self.assertEqual([("нет связи" in m) for m in self.out], [True, False])
        self.assertIn("восстановлена", self.out[1])

    def test_real_errors_pass(self):
        self.assertTrue(self.flt.filter(self.rec("Unhandled error while receiving updates", level=logging.ERROR)))
        err = self.rec("Server closed the connection: x", exc=(ValueError, ValueError("a"), None))
        self.assertTrue(self.flt.filter(err))
        self.assertTrue(self.flt.filter(self.rec("batch failed in 1", name=MOD.log.name, level=logging.ERROR)))
        self.assertEqual(self.out, [])


def hist(id, user_id, text, **extra):
    sender = SimpleNamespace(id=user_id, username=f"u{user_id}", bot=False, first_name=f"U{user_id}",
                             last_name=None)
    return SimpleNamespace(id=id, message=text, action=None, media=None, sender_id=user_id,
                           reply_to_msg_id=None, fwd_from=None, entities=None, reply_markup=None,
                           via_bot_id=None, get_sender=mock.AsyncMock(return_value=sender), **extra)


class PromoPrefilter(unittest.TestCase):
    def detect(self, text, **kw):
        return automod.detect_promo_ad({"text": text, **kw}, dict(SETTINGS, **kw.pop("cfg", {})))

    def test_invite_link_is_strong(self):
        self.assertEqual(self.detect("залетай t.me/+AbCdEf12345")[0], "strong")

    def test_channel_plug_is_strong(self):
        self.assertEqual(self.detect("Подписывайся на наш канал @celestiana_news")[0], "strong")

    def test_plain_mention_and_link_are_not_strong(self):
        self.assertNotEqual(self.detect("@vasya привет, как дела")[0], "strong")
        self.assertNotEqual(self.detect("глянь https://example.com/article")[0], "strong")
        self.assertIsNone(self.detect("обычное сообщение")[0])

    def test_custom_keyword_alone_is_strong(self):
        found = automod.detect_promo_ad({"text": "Bunker лучший"},
                                        dict(SETTINGS, ad_keywords=["bunker"]))
        self.assertEqual(found[0], "strong")

    def test_bad_regex_is_ignored(self):
        found = automod.detect_promo_ad({"text": "привет"}, dict(SETTINGS, ad_keywords=["(["]))
        self.assertIsNone(found[0])

    def test_forwarded_channel_ad(self):
        self.assertEqual(self.detect("t.me/somechannel", fwd_kind="channel")[0], "strong")


class AdsInBatchPath(AdFlow):
    def test_channel_ad_is_deleted_and_punished(self):
        bot = self.make_bot(rules="1. Реклама — мут 1 день")
        self.send(bot, "Подписывайся на наш канал t.me/+AbCdEf12345", username="spammer")
        self.assertIn(("delete", [77]), bot.client.calls)

    def test_admin_ad_is_not_touched(self):
        bot = self.make_bot(admins=(500,))
        self.send(bot, "Подписывайся на наш канал t.me/+AbCdEf12345")
        self.assertEqual(bot.client.calls, [])

    def test_prefilter_can_be_turned_off(self):
        bot = self.make_bot(ad_prefilter=False)
        self.send(bot, "Подписывайся на наш канал t.me/+AbCdEf12345")
        self.assertEqual(bot.client.calls, [])

    def test_hint_reaches_the_model(self):
        text = automod.build_batch_text("1. x", [msg(1, 5, "t.me/abcde", hint=True),
                                                 msg(2, -100, "x")], set())
        self.assertIn("[подозрение: реклама]", text)
        self.assertIn("[канал]", text)

    def test_prompt_defines_ads(self):
        self.assertIn("Реклама это нарушение", automod.SYSTEM_PROMPT)

    def test_flagged_ad_message_is_deleted(self):
        bot = self.make_bot(rules="1. Реклама — варн")
        bot.client.get_messages = mock.AsyncMock(return_value=SimpleNamespace(id=9, action=None))
        batch = [msg(9, 500, "купи курс", username="s")]
        asyncio.run(bot.punish(-1001, {"message_id": 9, "user_id": 500, "rule": "1",
                                       "punishment": "warn", "duration_minutes": None,
                                       "category": "ad", "reason": "x"}, batch))
        self.assertIn(("delete", [9]), bot.client.calls)

    def test_report_stays_in_chat(self):
        bot = self.make_bot()
        asyncio.run(bot.report(-1001, "итог"))
        self.assertEqual(bot.client.sent[-1][1], "итог")
        self.assertFalse(hasattr(bot, "_delete_quietly"))


class TestRun(AdFlow):
    def make_amt(self, history, answer='{"violations": []}', **settings):
        bot = self.make_bot(**settings)
        bot.state.chats.clear()  # not enabled in this chat
        bot.backend = FakeBackend(answer)
        bot.client.history = history
        return bot

    def test_parse(self):
        self.assertEqual(automod.parse_command(".amt")["action"], "amt")

    def test_replies_only_no_punishment_and_works_when_disabled(self):
        bot = self.make_amt([hist(1, 500, "привет"),
                             hist(2, 600, "заходи в наш канал t.me/+AbCdEf12345"),
                             hist(3, 1, "и я тоже t.me/+ZzZzZzZz1234 подпишись")])
        report = asyncio.run(bot.test_run(-1001))
        self.assertEqual([(t, r) for _, t, r in bot.client.sent],
                         [(automod.AMT_TEXT, 2), (automod.AMT_TEXT, 3)])
        self.assertEqual(bot.client.deleted, [])
        self.assertIn("проверено сообщений 3, найдено нарушений 2", report)
        self.assertFalse(bot.state.enabled(-1001))

    def test_admins_are_checked_too(self):
        bot = self.make_amt([hist(1, 500, "t.me/+AbCdEf12345")], admins=(500,))
        asyncio.run(bot.test_run(-1001))
        self.assertEqual(len(bot.client.sent), 1)

    def test_model_verdict_counts(self):
        bot = self.make_amt([hist(1, 500, "грубость")],
                            answer='{"violations": [{"message_id": 1, "user_id": 500, "rule": "2", '
                                   '"punishment": "warn", "category": "insult", "reason": "x"}]}')
        asyncio.run(bot.test_run(-1001))
        self.assertEqual([r for _, _, r in bot.client.sent], [1])

    def test_cap(self):
        history = [hist(i, 500 + i, f"t.me/+AbCdEf{i:06d}") for i in range(1, 8)]
        bot = self.make_amt(history, amt_max=3)
        report = asyncio.run(bot.test_run(-1001))
        self.assertEqual(len(bot.client.sent), 3)
        self.assertIn("найдено нарушений 7", report)
        self.assertIn("отвечено 3", report)

    def test_own_test_replies_and_commands_are_skipped(self):
        bot = self.make_amt([hist(1, 1, automod.AMT_TEXT), hist(2, 1, ".amt")])
        report = asyncio.run(bot.test_run(-1001))
        self.assertIn("проверено сообщений 0", report)

    def test_command_dispatch(self):
        bot = self.make_amt([hist(2, 600, "t.me/+AbCdEf12345")])
        bot.client.get_permissions = mock.AsyncMock()
        event = fake_event(-1001, 50, 1, ".amt")
        asyncio.run(bot.on_command(event))
        texts = [t for _, t, _ in bot.client.sent]
        self.assertEqual(texts[0], automod.AMT_TEXT)
        self.assertIn("тест .amt", texts[-1])


if __name__ == "__main__":
    unittest.main(verbosity=1)
