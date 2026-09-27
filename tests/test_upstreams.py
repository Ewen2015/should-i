#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the parts of this product that are pure logic -- no keys, no
network, no browser:

    python3 tests/test_upstreams.py

Exits non-zero if anything fails, so it can gate a commit. Two groups live here.
The `frame_*` guards decide whether a model's restatement is allowed anywhere
near the run, and they are checked without a network call because they are
exactly the code that is supposed to work when the network is broken. The cache
tests pin the rules the cache must not break, since it sits in front of every
paid call.
"""

from __future__ import annotations

import contextlib
import json
import sys

import _bootstrap  # noqa: F401  -- puts ../app on sys.path

import jevcache


FAILURES = []
CHECKS = [0]


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


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        print("\n-- %s" % test.__name__)
        test()
    print("\n%d checks, %d failed" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        print("FAILED: %s" % ", ".join(FAILURES))
    return 1 if FAILURES else 0


def test_frame_fallback_names_the_do_side():
    """The restatement is what tells the reader what the 0-1 axis measures.

    This is the no-network path only. It runs when DeepSeek is unreachable, and
    it is crude on purpose -- but it must never produce a question that says the
    opposite of what was asked, and it must never emit two question marks. Both
    of those were real bugs in the first draft: "…星际文明吗？" came out as
    "…星际文明吗吗？" and "你支持…吗？" lost its "？".
    """
    import upstreams
    cases = {
        "人类要成为一个星际文明吗？": "你支持人类要成为一个星际文明吗？",
        "我要不要辞职去读研？": "你支持辞职去读研吗？",
        "该不该给小孩买手机？": "你支持给小孩买手机吗？",
        "我是否应该搬家": "你支持搬家吗？",
        "要不要跟父母一起住？": "你支持跟父母一起住吗？",
        # Already in the target form: only the punctuation may be repaired.
        "你支持人类登上火星吗": "你支持人类登上火星吗？",
        "你支持人类登上火星吗？": "你支持人类登上火星吗？",
    }
    for question, want in cases.items():
        check("改写成「你支持…吗？」: %s" % question,
              upstreams._frame_fallback(question), want)

    # Nothing to wrap: return the user's text untouched rather than "你支持吗？".
    check("只有标点就不假装改写", upstreams._frame_fallback("???"), "???")
    check("空串原样返回", upstreams._frame_fallback(""), "")

    # The scale's own axis is 做 / 不做, and the page shows 支持 as 做. A question
    # about banning something must therefore name the ban, not its absence.
    out = upstreams._frame_fallback("该不该禁止短视频？")
    truthy("问「该不该禁止」时，X 是「禁止」本身", "禁止" in out and "不禁止" not in out)


def test_frame_support_refuses_an_answer_or_a_paragraph():
    """The guard on the model's reply, exercised without a network call.

    Two failure modes matter more than grammar. A reply that is prose puts a
    paragraph where a one-line question belongs; a reply that ANSWERS the
    question puts the product's conclusion above a map that is supposed to be
    showing it. Both are refused, and the crude rule runs instead.
    """
    import upstreams
    for good in ["你支持人类成为一个星际文明吗？", "你支持辞职去读研吗？",
                 "你支持选 A 还是 B 吗？", "你支持禁止短视频吗？"]:
        truthy("形状对: %s" % good, upstreams._frame_ok(good))
    for bad in [None, "", "   ", "我觉得应该去", "支持不支持？",
                "你支持吗",                                   # too short to name anything
                "我觉得应该去。你支持吗？",                    # it answered first
                "这是一段解释。" * 12,                         # a paragraph
                "你支持人类登上火星吗",                        # missing the ？, repaired below
                "你支持" + "很长" * 40 + "吗？"]:
        if bad == "你支持人类登上火星吗":
            # No trailing ？ is fine -- the shape is the sentence, not the mark.
            truthy("缺问号也算形状对", upstreams._frame_ok(bad))
            continue
        falsy("形状不对就退回规则: %r" % (bad if not isinstance(bad, str) else bad[:18]),
              upstreams._frame_ok(bad))


def test_frame_en_ok_keeps_the_english_line_honest():
    """The English restatement, as it is used in the run's state.

    This line names the decision for 5226 English judgements, so the failure
    that matters is not grammar -- it is accepting something that is not an
    English restatement at all and letting every number below it be about an X
    nobody asked about. Refusing leaves the run on the reader's own words.
    """
    import upstreams
    for good in ["Do you support humanity becoming an interstellar civilisation?",
                 "Do you support quitting your job and going back to school?",
                 "Would you back banning short videos?",
                 # `that` here is a conjunction, not the dangling pronoun. The
                 # first version of the guard refused all three of these, and
                 # four real runs went out with no English in the state.
                 "Do you support that the world was created by God for humans?",
                 "Do you support that God created this universe for humanity?",
                 "Do you support this reading of the decision?"]:
        truthy("形状对: %s" % good, upstreams.frame_en_ok(good))
    for bad in [None, "", "   ", "你支持人类成为星际文明吗？",
                "Do you support it?",                          # names nothing
                "I think humanity should go to the stars.",     # an answer
                "Do you support X?\nAnd also Y?",               # two questions
                "Do you support X? Or Y?",                      # two questions
                "Do you support ？",
                "Do you support " + "very long " * 30 + "?"]:
        falsy("形状不对就退回原文: %r" % (bad if not isinstance(bad, str) else bad[:22]),
              upstreams.frame_en_ok(bad))
    # Wrapped in whitespace is still one line.
    check("掐掉空白", upstreams.frame_en_ok("  Do you support X?  "),
          "Do you support X?")



# --------------------------------------------------------------------------- #
# The Jev cache. It sits in front of every upstream call, so the rules it must
# not break are checked here instead of trusted.
# --------------------------------------------------------------------------- #

@contextlib.contextmanager
def _temp_cache():
    """A throwaway cache file, so no test writes into the repo's own."""
    import os
    import tempfile

    handle, path = tempfile.mkstemp(prefix="jevcache_test_", suffix=".db")
    os.close(handle)
    previous = os.environ.get(jevcache.ENV_NAME)
    os.environ[jevcache.ENV_NAME] = path
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop(jevcache.ENV_NAME, None)
        else:
            os.environ[jevcache.ENV_NAME] = previous
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


def test_the_cache_key_is_the_request_and_nothing_else():
    url = "http://example/v1/systemone"
    body = b'{"model":"m","state":"q"}'
    check("same url and body is the same key",
          jevcache.digest(url, body), jevcache.digest(url, body))
    falsy("a different body is a different key",
          jevcache.digest(url, body) == jevcache.digest(url, b'{"model":"m","state":"Q"}'))
    falsy("a different url is a different key",
          jevcache.digest(url, body) == jevcache.digest("http://example/v1/other", body))
    # Without the separator these two would hash the same concatenated string,
    # and two unrelated requests would share one answer.
    falsy("a url cannot be shifted into a body",
          jevcache.digest("http://a/b", b"c") == jevcache.digest("http://a/bc", b""))


def test_only_an_answer_is_worth_remembering():
    falsy("an empty body is not an answer", jevcache.storable({}))
    falsy("an error envelope is not an answer", jevcache.storable({"error": "nope"}))
    falsy("a non-dict is not an answer", jevcache.storable(["answers"]))
    falsy("nor is an empty answers dict", jevcache.storable({"answers": {}}))
    truthy("a Jev answer is", jevcache.storable({"answers": {"a": 0.7}}))
    truthy("a DeepSeek answer is", jevcache.storable({"choices": [{"message": {}}]}))


def test_a_hit_is_priced_at_zero_but_says_what_it_saved():
    import upstreams

    priced = upstreams._as_reused({
        "answers": {"a": 1},
        "usage": {"input_tokens": 55926, "output_tokens": 10539},
    })
    check("live input tokens are zero", priced["usage"]["input_tokens"], 0)
    check("live output tokens are zero", priced["usage"]["output_tokens"], 0)
    check("what it would have cost is kept", priced["usage"]["saved_input_tokens"], 55926)
    check("both of them", priced["usage"]["saved_output_tokens"], 10539)
    truthy("and the hit says it is one", priced["usage"]["reused"])
    check("the answer itself is untouched", priced["answers"], {"a": 1})

    bare = upstreams._as_reused({"answers": {"a": 1}})
    check("an answer with no usage still costs zero", bare["usage"]["input_tokens"], 0)
    check("and claims nothing saved", bare["usage"]["saved_input_tokens"], 0)


def test_a_stored_answer_comes_back_and_a_corrupt_row_is_only_a_miss():
    import sqlite3

    with _temp_cache() as path:
        url = "http://x/v1"
        key = jevcache.digest(url, b'{"q":1}')
        check("nothing is stored yet", jevcache.get(key), None)

        jevcache.put(key, url, {"answers": {"a": 0.7}})
        check("the answer comes back", jevcache.get(key), {"answers": {"a": 0.7}})
        check("a key nobody wrote is still a miss", jevcache.get("0" * 64), None)

        # The run is the expensive thing; it does not get to die on the cache.
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE response SET body = ?", ("{not json",))
        check("a corrupt row reads as a miss, not a crash", jevcache.get(key), None)

        miss_key = jevcache.digest(url, b'{"q":2}')
        jevcache.put(miss_key, url, {"error": "boom"})
        check("a failure is never stored", jevcache.get(miss_key), None)


def test_the_cache_can_be_switched_off_for_a_measured_run():
    with _temp_cache() as path:
        import os

        os.environ[jevcache.ENV_NAME] = "0"
        falsy("off is off", jevcache.enabled())
        jevcache.put("k" * 64, "http://x/v1", {"answers": {"a": 1}})
        check("a switched-off cache does not even read", jevcache.get("k" * 64), None)

        # An empty value means off, not "fall back to the repo's own file": the
        # whole point of setting it is to stop spending from the cache.
        os.environ[jevcache.ENV_NAME] = ""
        falsy("an empty value is off, not 'use the default path'", jevcache.enabled())
        falsy("...and its path is not the repo's", jevcache.path() == jevcache.DEFAULT_DB)

        os.environ[jevcache.ENV_NAME] = path
        truthy("a path means on", jevcache.enabled())


def test_the_cache_evicts_the_least_recently_used_past_its_ceiling():
    import sqlite3

    with _temp_cache() as path:
        payload = {"answers": {"pad": "x" * 80}}
        size = len(json.dumps(payload, ensure_ascii=False).encode())

        keys = [jevcache.digest("http://x/v1", b"%d" % i) for i in range(3)]
        ceiling = jevcache.MAX_BYTES
        try:
            jevcache.MAX_BYTES = 10 ** 9          # fill first, order the rows ourselves
            for key in keys:
                jevcache.put(key, "http://x/v1", payload)
            with sqlite3.connect(path) as conn:
                for n, key in enumerate(keys):
                    conn.execute(
                        "UPDATE response SET used_at = ? WHERE digest = ?", (1000.0 + n, key)
                    )

            jevcache.MAX_BYTES = size * 2          # room for exactly two rows
            newest = jevcache.digest("http://x/v1", b"newest")
            jevcache.put(newest, "http://x/v1", payload)

            check("the oldest row is gone", jevcache.get(keys[0]), None)
            check("so is the next one", jevcache.get(keys[1]), None)
            truthy("the most recently used survives", jevcache.get(keys[2]) is not None)
            truthy("and so does the one that pushed it over", jevcache.get(newest) is not None)
        finally:
            jevcache.MAX_BYTES = ceiling


if __name__ == "__main__":
    sys.exit(main())
