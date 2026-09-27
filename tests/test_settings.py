#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the key file behind the settings screen -- no keys, no network:

    python3 tests/test_settings.py

Two things are being pinned down here, and the second matters more than the
first. First, that saving, merging and clearing keys behaves. Second, that a
secret does not escape: not into the status payload the browser fetches, not into
a traceback, not by being world-readable on disk, and not by being handed back in
the response to the request that set it.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile

import _bootstrap  # noqa: F401  -- puts ../app on sys.path

import settings  # noqa: E402
import server  # noqa: E402
import upstreams  # noqa: E402

FAILURES = []
CHECKS = [0]

JEV = "jev-key-1234567890-abcdef"
DS = "sk-deepseek-0987654321-zyxwvu"

# Every env name `upstreams` consults, so a test can blank the lot and be sure a
# key it thinks it configured is the only one in play.
ALL_ENV = tuple(
    name for names in upstreams.ENV_NAMES.values() for name in names
)


def check(name, got, want):
    CHECKS[0] += 1
    ok = got == want
    print("%-58s %s" % (name, "ok" if ok else "FAIL"))
    if not ok:
        print("       got  %r\n       want %r" % (got, want))
        FAILURES.append(name)


def truthy(name, value):
    check(name, bool(value), True)


def falsy(name, value):
    check(name, bool(value), False)


class isolated:
    """A scratch settings path, with every key env var blanked for the duration.

    Without the blanking, a test that sets nothing would still see the developer's
    own exported keys and 'no keys configured' would never be true.
    """

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="jev-settings-")
        self.path = os.path.join(self.dir, "s.json")
        self.saved = {name: os.environ.get(name) for name in ALL_ENV}
        self.saved_path = os.environ.get("SHOULD_I_SETTINGS")
        os.environ["SHOULD_I_SETTINGS"] = self.path
        for name in ALL_ENV:
            os.environ.pop(name, None)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if self.saved_path is None:
            os.environ.pop("SHOULD_I_SETTINGS", None)
        else:
            os.environ["SHOULD_I_SETTINGS"] = self.saved_path
        for leftover in (self.path, self.path + ".tmp"):
            if os.path.exists(leftover):
                os.remove(leftover)
        os.rmdir(self.dir)
        return False


def test_save_then_load_round_trips():
    with isolated():
        falsy("一开始什么也没有", settings.get("jev_api_key"))
        settings.save({"jev_api_key": JEV, "deepseek_api_key": DS})
        check("两个都存下来了", settings.load(),
              {"jev_api_key": JEV, "deepseek_api_key": DS})
        truthy("文件真的写出来了", os.path.exists(settings.path()))


def test_save_merges_and_an_empty_string_clears():
    with isolated():
        settings.save({"jev_api_key": JEV, "deepseek_api_key": DS})
        settings.save({"jev_api_key": "jev-second-key-000000"})
        check("只改给到的那一个", settings.load()["deepseek_api_key"], DS)
        check("改的那个换成了新值", settings.load()["jev_api_key"], "jev-second-key-000000")
        settings.save({"jev_api_key": ""})
        check("空字符串 = 清除这一个", settings.load(), {"deepseek_api_key": DS})
        settings.save({"deepseek_api_key": "   "})
        check("只有空白也算清除", settings.load(), {})
        falsy("清空之后文件也删了（不是留一个空对象）", os.path.exists(settings.path()))


def test_the_key_file_is_not_world_readable():
    with isolated():
        settings.save({"jev_api_key": JEV})
        mode = stat.S_IMODE(os.stat(settings.path()).st_mode)
        check("权限就是 0600", oct(mode), oct(0o600))


def test_a_corrupt_or_hostile_file_reads_as_no_keys():
    with isolated():
        for junk in ("{not json", "[]", '{"jev_api_key": 123}', "null",
                     '{"other": "x"}', '{"jev_api_key": ["a"]}', '{"jev_api_key": null}'):
            with open(settings.path(), "w", encoding="utf-8") as handle:
                handle.write(junk)
            check("坏文件读成空（%s）" % junk[:12], settings.load(), {})
        # A non-string is refused rather than coerced: the file is ours, so a
        # number in it means corruption, and "123" would fail as a 401 later.
        with open(settings.path(), "w", encoding="utf-8") as handle:
            json.dump({"jev_api_key": 123, "evil": "x",
                       "deepseek_api_key": "real-key-value-here"}, handle)
        check("认不出的字段和非法类型都被丢掉", settings.load(),
              {"deepseek_api_key": "real-key-value-here"})


def test_mask_never_hands_back_the_whole_key():
    check("正常长度只露头尾", settings.mask("sk-abcdefghijklmnop"), "sk-a…mnop")
    for short in ("", None, "abc", "abcdefghij"):
        check("太短就干脆不给（%r）" % (short,), settings.mask(short), "…" if short else None)
    mask = settings.mask(JEV)
    falsy("中间那一段不在里面", JEV[4:-4] in mask)


def test_the_status_payload_carries_no_key_material():
    """This payload is what the browser fetches, so it is the one place a key
    could leak without anyone noticing."""
    with isolated():
        settings.save({"jev_api_key": JEV, "deepseek_api_key": DS})
        blob = json.dumps(upstreams.key_status(), ensure_ascii=False)
        falsy("Jev key 不在里面", JEV in blob)
        falsy("DeepSeek key 也不在", DS in blob)
        status = upstreams.key_status()
        check("但说了来源是设置文件", status["jev_api_key"]["source"], "settings")
        truthy("并且配置算是齐了", status["jev_api_key"]["configured"])
        truthy("提示里只有头尾", status["jev_api_key"]["hint"] == settings.mask(JEV))


def test_the_request_that_saves_a_key_does_not_get_it_back():
    """POST /api/settings answers with the same status payload. The key must not
    ride along in it."""
    with isolated():
        result = server.Handler.handle_settings(
            None, {"jev_api_key": JEV, "deepseek_api_key": DS}
        )
        blob = json.dumps(result, ensure_ascii=False)
        falsy("整份响应里没有 Jev key", JEV in blob)
        falsy("也没有 DeepSeek key", DS in blob)
        check("存是存下来了", settings.get("jev_api_key"), JEV)

        # `settings.load()` deliberately returns the real keys -- it is the
        # internal API, and the server has to be able to read them. What must
        # never carry one is anything the browser can ask for.
        for probe, what in ((upstreams.key_status(), "状态payload"),
                            (result, "保存响应"),
                            ({"settings": upstreams.key_status()}, "GET /api/settings")):
            falsy("%s 里没有完整 key" % what, JEV in json.dumps(probe, ensure_ascii=False))


def test_the_handler_rejects_paste_accidents():
    """Format checking is pointless for an opaque key, but the two ways a paste
    goes wrong are worth catching at the point the user can still see it."""
    with isolated():
        for body, what in (
            ({"jev_api_key": "abc\ndef"}, "中间换行"),
            ({"jev_api_key": "abc def"}, "中间空格"),
            ({"jev_api_key": "x" * 600}, "太长"),
            ({"jev_api_key": ["a"]}, "不是字符串"),
            ({"deepseek_api_key": 12345}, "数字"),
        ):
            try:
                server.Handler.handle_settings(None, body)
                check("拒绝：%s" % what, "没报错", "ValueError")
            except ValueError:
                check("拒绝：%s" % what, "ValueError", "ValueError")
        falsy("一个都没写进文件", settings.load())
        # Trailing whitespace from a sloppy copy is trimmed, not rejected.
        result = server.Handler.handle_settings(None, {"jev_api_key": "  " + JEV + "\n"})
        check("首尾空白是修剪，不是拒绝", settings.get("jev_api_key"), JEV)
        check("修剪后照样能用", result["settings"]["jev_api_key"]["configured"], True)


def test_an_empty_body_changes_nothing():
    with isolated():
        settings.save({"jev_api_key": JEV})
        result = server.Handler.handle_settings(None, {})
        check("没有字段就不动文件", settings.load(), {"jev_api_key": JEV})
        truthy("但照样回状态", result["settings"]["jev_api_key"]["configured"])


def test_key_source_prefers_the_settings_file_over_the_environment():
    """Typing a key into the screen is a deliberate act; having it silently lose
    to a stale export in some forgotten shell is the bug this precedence avoids."""
    with isolated():
        os.environ["TYPESAFE_API_KEY"] = "from-the-environment"
        check("没填设置时用环境变量", upstreams.key_source("jev_api_key"), "env")
        check("值也确实来自环境", upstreams.key_value("jev_api_key"), "from-the-environment")
        settings.save({"jev_api_key": JEV})
        check("填了设置就用设置", upstreams.key_source("jev_api_key"), "settings")
        check("值也跟着换", upstreams.key_value("jev_api_key"), JEV)
        settings.save({"jev_api_key": ""})
        check("清掉设置又退回环境变量", upstreams.key_source("jev_api_key"), "env")
        os.environ.pop("DEEPSEEK_API_KEY", None)
        check("两个都没有就是 None", upstreams.key_source("deepseek_api_key"), None)


def test_a_missing_key_says_where_to_put_it():
    """The error a user actually hits. It has to name the settings screen, because
    'set an environment variable' is not something the page can help with."""
    with isolated():
        try:
            upstreams.jev_key()
            check("缺 key 应当报错", "没报错", "UpstreamError")
        except upstreams.UpstreamError as exc:
            truthy("提到「设置」", "设置" in str(exc))
            truthy("也提到环境变量名", "JEV_API_KEY" in str(exc))
        try:
            upstreams.deepseek_key()
            check("DeepSeek 同样", "没报错", "UpstreamError")
        except upstreams.UpstreamError as exc:
            truthy("DeepSeek 的提示也提到「设置」", "设置" in str(exc))


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        print("\n-- %s" % test.__name__)
        test()
    print("\n%d checks, %d failed" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        print("FAILED: %s" % ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
