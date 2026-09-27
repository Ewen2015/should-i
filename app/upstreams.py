#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The two upstreams, and the one place a key can reach the wire.

Jev does the measuring: one call carries 255 people x two directions = 510
nouls, and eleven such calls cover the whole roster. DeepSeek does one short
language job -- naming what X is, so a 0-1 "support" scale has a subject
(see FRAME_SYSTEM). Everything else here is validation and fallback, because
the run is expensive and a model answer that does not check out must degrade to
something true rather than to something confident.

Nothing in this file is about the reader. The product is stateless on purpose:
a judgement about what Machiavelli would say is not evidence about anyone.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

import jevcache
import settings


TIMEOUT = 120
ATTEMPTS = 3


class UpstreamError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Keys, read from the environment only. Nothing here is ever sent to the browser.
# --------------------------------------------------------------------------- #
#
# Two places a key can come from: the settings file written by the settings
# screen, and the environment. The settings file wins -- see settings.py for why
# -- and `key_source()` reports which one is live so the page can say so instead
# of leaving the user to guess whether the key they just pasted took effect.
# --------------------------------------------------------------------------- #
ENV_NAMES = {
    "jev_api_key": ("JEV_API_KEY", "TYPESAFE_API_KEY", "TYPESAFE_AI_API_KEY"),
    "deepseek_api_key": ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"),
}

PROVIDER_LABEL = {
    "jev_api_key": "Jev",
    "deepseek_api_key": "DeepSeek",
}


def key_source(name):
    """'settings' / 'env' / None -- where this key is actually coming from."""
    if settings.get(name):
        return "settings"
    if any(os.environ.get(item) for item in ENV_NAMES[name]):
        return "env"
    return None


def key_value(name):
    """The live key, or None. The one place precedence is implemented."""
    value = settings.get(name)
    if value:
        return value
    for env_name in ENV_NAMES[name]:
        if os.environ.get(env_name):
            return os.environ[env_name]
    return None


def key_status():
    """Everything the settings screen needs, and no secret of any kind."""
    report = {}
    for name in settings.FIELDS:
        source = key_source(name)
        report[name] = {
            "configured": source is not None,
            "source": source,
            "hint": settings.mask(key_value(name)),
            # The first env name is enough to tell the user where to look.
            "env_hint": ENV_NAMES[name][0],
            "label": PROVIDER_LABEL[name],
        }
    report["file"] = settings.path()
    report["file_exists"] = os.path.exists(settings.path())
    return report


def _require(name):
    value = key_value(name)
    if value:
        return value
    alias = " / ".join(ENV_NAMES[name])
    raise UpstreamError(
        "缺少 %s API key（可在「设置」里填，或设环境变量 %s）"
        % (PROVIDER_LABEL[name], alias)
    )


def jev_key():
    return _require("jev_api_key")


def deepseek_key():
    return _require("deepseek_api_key")


def jev_base():
    return os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")


def jev_model():
    return os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest")


def deepseek_base():
    return os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")


def deepseek_model():
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _post(url, payload, key, timeout=TIMEOUT, cache=True):
    """POST a payload, and remember the answer if it was an answer.

    `cache=False` is for the one call whose entire job is to find out whether
    the far end is reachable right now. A connection check served from disk
    would keep saying 有回应 about a key that was revoked ten minutes ago --
    which is worse than no check at all, because it looks like evidence.
    """
    body = json.dumps(payload).encode()
    digest = jevcache.digest(url, body) if cache else None
    if digest is not None:
        stored = jevcache.get(digest)
        if stored is not None:
            return _as_reused(stored)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode())
            # Stored only here, on the success path: a timeout or a 429 is a
            # fact about one bad minute, and writing it down would make it a
            # fact about every minute after.
            if digest is not None:
                jevcache.put(digest, url, data)
            return data
        except urllib.error.HTTPError as exc:
            last = _describe_http_error(exc.code, exc.read().decode(errors="replace"))
            if exc.code in (400, 401, 403, 404, 422):
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last = str(exc)
        if attempt < ATTEMPTS:
            time.sleep(1.5 * attempt)
    raise UpstreamError(last or "request failed")


def _as_reused(stored):
    """Price a cache hit honestly: this call cost nothing.

    The original figures move to `saved_*` instead of vanishing, because "this
    answer would have cost 55,926 input tokens" is the entire reason the cache
    exists. Callers that only want the bill sum `input_tokens` and
    `output_tokens`, get zero, and report what the run actually spent.
    """
    was = stored.get("usage")
    saved_in = was.get("input_tokens") if isinstance(was, dict) else None
    saved_out = was.get("output_tokens") if isinstance(was, dict) else None
    stored["usage"] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "reused": True,
        "saved_input_tokens": saved_in or 0,
        "saved_output_tokens": saved_out or 0,
    }
    return stored


def _describe_http_error(code, body):
    """Pull the one human sentence out of an error body, if there is one.

    Providers wrap the useful line in a JSON envelope, and dumping the envelope
    into the page turns a one-line problem into a wall of escaped braces -- which
    is exactly what the settings screen did the first time it got a 401.
    """
    text = (body or "").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return "HTTP %s: %s" % (code, text[:200])
    for path in (("detail", "message"), ("error", "message"), ("message",),
                 ("detail",), ("error",), ("msg",)):
        node = data
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, str) and node.strip():
            return "HTTP %s: %s" % (code, node.strip()[:200])
    return "HTTP %s: %s" % (code, text[:200])


def _get_json(url, key, timeout=30):
    request = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise UpstreamError(
            _describe_http_error(exc.code, exc.read().decode(errors="replace"))
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpstreamError(str(exc))


# The one temperature that reaches the wire. DeepSeek's accepted range, plus a
# clamp, because this is the boundary and nothing downstream should have to trust
# a caller to be in range.
DEEPSEEK_TEMPERATURE_RANGE = (0.0, 2.0)
DEEPSEEK_TEMPERATURE_DEFAULT = 0.2


def clamp_temperature(value, low=None, high=None):
    """Clamp into the API's accepted range, and never return a non-number."""
    low = DEEPSEEK_TEMPERATURE_RANGE[0] if low is None else low
    high = DEEPSEEK_TEMPERATURE_RANGE[1] if high is None else high
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEEPSEEK_TEMPERATURE_DEFAULT
    if number != number:  # NaN
        return DEEPSEEK_TEMPERATURE_DEFAULT
    return round(min(max(number, low), high), 2)


# --------------------------------------------------------------------------- #
# DeepSeek
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Is the key actually working?
#
# The settings screen needs to answer that, because "saved" and "correct" are
# not the same thing and a typo'd key fails much later, in the middle of a
# judgment, looking like a normal error. One cheap call each. Neither check may
# raise: a settings screen that dies on a bad key is useless exactly when it is
# needed.
# --------------------------------------------------------------------------- #
def _check_jev():
    payload = {
        "state": {"what_this_is": "a connection check from the settings screen"},
        "model": jev_model(),
        "questions": {
            "reachable": {
                "type": "noul",
                "instructions": "Did this request arrive? Answer true if it did.",
                "criteria": {"true": "yes, it arrived", "false": "no"},
            }
        },
    }
    response = _post(
        jev_base() + "/v1/systemone", payload, jev_key(), timeout=45, cache=False
    )
    if "answers" not in response:
        raise UpstreamError("返回里没有 answers: %s" % json.dumps(response)[:150])
    return "有回应（model=%s）" % (response.get("model") or jev_model())


def _check_deepseek():
    # GET /models costs no tokens and is still the same host, port and auth header
    # as the frame call, so it catches a bad key without spending anything.
    #
    # It does NOT prove the configured model works: the live list now advertises
    # `deepseek-flash` and `deepseek-v4-pro` while `deepseek-chat` still answers,
    # so a name that is missing from this list is a note, not a verdict. (A real
    # completion would be a better check, but it costs tokens on every press of a
    # button, and JSON mode also refuses prompts without the word "json" in them.)
    data = _get_json(deepseek_base() + "/models", deepseek_key())
    names = [
        item.get("id")
        for item in (data.get("data") or [])
        if isinstance(item, dict)
    ]
    if not names:
        raise UpstreamError("模型列表是空的: %s" % json.dumps(data)[:150])
    listed = ", ".join(str(name) for name in names[:4])
    if deepseek_model() in names:
        return "有回应（%d 个模型，含 %s）" % (len(names), deepseek_model())
    return "key 可用；目录里是 %s（配置的是 %s，可能是别名）" % (listed, deepseek_model())


def check_keys():
    report = {}
    for name, check in (("jev", _check_jev), ("deepseek", _check_deepseek)):
        try:
            report[name] = {"ok": True, "detail": check()}
        except UpstreamError as exc:
            report[name] = {"ok": False, "detail": str(exc)[:200]}
        except Exception as exc:  # never take the settings screen down
            report[name] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
    return report


def _chat_json(system, user, temperature=1.0, max_tokens=1600):
    payload = {
        "model": deepseek_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        # Clamped at the boundary: no code path may put a number outside the
        # API's range on the wire, whatever it was told.
        "temperature": clamp_temperature(temperature),
        "max_tokens": max_tokens,
    }
    response = _post(
        deepseek_base() + "/chat/completions", payload, deepseek_key(), timeout=90
    )
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise UpstreamError("DeepSeek 返回结构异常: %s" % json.dumps(response)[:300])
    return _parse_json(content)


def _parse_json(text):
    """Models wrap JSON in fences and prose even in JSON mode. Be forgiving."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise UpstreamError("DeepSeek 没有返回可解析的 JSON")


FRAME_SYSTEM = """You restate a question so that a 0-1 support scale has a subject.

The system asks thinkers "how much do you support X", and records 0 (against) to
1 (for). A question typed as "人类要成为一个星际文明吗？" leaves X implicit, and an
implicit X makes the number unreadable: support for WHAT? Your job is to name X
and hand back one question of the form "你支持X吗？", plus the same question in
English.

`frame` -- the question in the user's own language:
- Reply in the user's own language, and change nothing else about it.
- Output exactly one question. In Chinese that is "你支持X吗？"; in English it is
  "Do you support X?". Nothing else in front of it, nothing after it.
- Keep it short -- under 40 characters in Chinese, under 15 words in English. If
  the original is already in this form, return it unchanged.
- Preserve the user's own words for X. Do not add facts, do not narrow or widen
  the decision, do not add conditions the user did not write.
- X is the decision, not the person deciding. "我要不要辞职去读研？" becomes
  "你支持辞职去读研吗？" -- not "你支持我辞职去读研吗？", which would ask every
  thinker to have an opinion about a stranger's life.
- X must name the DO side of the decision. Downstream, each thinker is asked
  whether their framework points at "做" or "不做", and "支持 X" is shown to the
  reader as the same thing as 做. So if the user asks "该不该禁止短视频？", X is
  "禁止短视频" ("你支持禁止短视频吗？"), never "不禁止短视频".
- If the question offers a choice ("选 A 还是 B"), X is the choice: "你支持选 A
  还是 B 吗？". Do not decide it for them.
- Never answer the question. You are only restating it.

`frame_en` -- the SAME question in English:
- The same X and the same reading of the decision: a translation, never a second
  opinion. The thinkers are asked in English and every question says "support
  it" without naming it; this sentence is what names it for them.
- One line, under 15 words, ending in "?". If the user already wrote in English,
  this is that sentence unchanged.

Return only this JSON: {"frame": "你支持X吗？", "frame_en": "Do you support X?"}"""


def frame_support(question):
    """The user's question, restated as the thing the 0-1 scale is measuring.

    This is a real information problem, not decoration: the roster is scored
    "how much does this person support X", so a question whose X is implicit
    ("人类要成为一个星际文明吗？") produces numbers nobody can interpret. Asking a
    model to name X is the only honest way to get it -- a rule that strips "要不要"
    and prepends "你支持" mangles anything it has not seen before, and the questions
    people actually type are not a closed set.

    Two sentences come back, and they are the same decision: `frame` in the
    user's own language (what the page shows) and `frame_en` in English (what
    the nouls are judged over -- they are asked in English, and every one of
    them says "support it" without ever naming what "it" is; see
    `thinkers.scale_state`). One call produces both so they cannot drift apart.
    A run that cannot get the English still runs on the user's own words.
    """
    text = (question or "").strip()
    if len(text) < 2:
        return text, ""
    try:
        data = _chat_json(FRAME_SYSTEM, text, temperature=0.2, max_tokens=400)
    except (UpstreamError, ValueError):
        return _frame_fallback(text), ""
    frame = data.get("frame")
    if not _frame_ok(frame):
        frame = _frame_fallback(text)
    else:
        frame = " ".join(frame.split())
    return frame, frame_en_ok(data.get("frame_en"))


def frame_en_ok(text):
    """The English restatement, or "" if what came back is not one.

    Loose on wording and strict on shape: exactly one sentence, in English,
    ending in a question mark, and it has to name something -- "Do you support
    it?" is the dangling pronoun this line exists to fix, in English. A model
    that answers the question, writes a paragraph, or hands the Chinese
    sentence back leaves the state with the user's own words only. That is a
    worse prompt but a true one -- a mislabelled decision would be worse than
    both, because the numbers under it would be about something nobody asked.
    """
    if not isinstance(text, str):
        return ""
    text = " ".join(text.split())
    if not text or len(text) > 200 or not text.endswith("?"):
        return ""
    if "。" in text or "？" in text:
        return ""
    # One question, not a list of them.
    if "?" in text[:-1]:
        return ""
    if not re.search(r"[A-Za-z]", text):
        return ""
    # X has to be named, not pointed at -- but only when the pronoun IS the
    # object. "Do you support that the world was created by God?" names its X
    # perfectly well; the first version of this check refused it, and every run
    # of four real questions went out without its English line because of it.
    if re.search(r"\b(?:support|favour|favor|back)\s+(?:it|this|that)\s*\??\s*$",
                 text, re.I):
        return ""
    return text


def _frame_ok(frame):
    """Is this the shape we asked for, or did the model answer the question?

    A model that returns prose would put a paragraph where a one-line question
    belongs, and a model that returns an ANSWER would put the product's
    conclusion above a map that is supposed to be showing it. Neither is
    checkable at a glance, so both are refused and the crude rule runs instead.
    """
    if not isinstance(frame, str):
        return False
    frame = frame.strip()
    if len(frame) < 6 or len(frame) > 72:
        return False
    # An answer would have a full stop in the middle of a "question".
    if "。" in frame or "\n" in frame:
        return False
    # The app is Chinese, but the box takes English too, and a Chinese-only
    # shape check would silently throw away a correct English restatement and
    # replace it with a mangled Chinese one.
    if frame.startswith(("你支持", "你赞成")):
        return frame.endswith(("吗", "吗？"))
    return bool(_EN_FRAME.match(frame)) and frame.endswith("?")

_EN_FRAME = re.compile(r"(?:do|does|would)\s+you\s+(?:support|favour|favor|back)\b", re.I)


# Only a safety net for when DeepSeek is unreachable. It handles the openers
# people actually type and gives up honestly on the rest -- a wrong restatement
# is worse than an awkward one, because the reader has no way to tell it is wrong.
_FRAME_LEAD = re.compile(
    r"^(?:请问|我想问一下|我想问|我想知道|大家|你觉得)[,，:：]?\s*"
    r"|^(?:我)?(?:到底|究竟)?(?:应不应该|应不应该去|该不该|要不要|是否应该|是否要|是否)\s*"
    r"|^(?:我)?(?:应该|该|要)(?=[^\s])"
)


def _frame_fallback(question):
    text = (question or "").strip()
    if not text:
        return text
    # Already in the target shape: only the punctuation can be missing.
    if text.startswith("你支持"):
        text = re.sub(r"[\s?？。！!]+$", "", text)
        return text + ("" if text.endswith("吗") else "吗") + "？"
    # Peel the question mark and a trailing 吗 together: "…星际文明吗？" has to
    # lose both, not just the punctuation, or the result ends "…文明吗吗？".
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"[\s?？。！!、,，]+$", "", text)
        text = re.sub(r"吗$", "", text).strip()
    prev = None
    while prev != text:
        prev = text
        text = _FRAME_LEAD.sub("", text, count=1).strip()
    if not text:
        return (question or "").strip()
    return "你支持" + text + "吗？"


# --------------------------------------------------------------------------- #
# Ask Great Thinkers
#
# One request carries exactly 255 judgements, one per thinker. The questions are
# built by thinkers.py (pure logic); this sends them and reads the scores back.
# This repo has no database and no personal model -- there is nothing here
# that is about the reader, so there is nothing to keep.
# --------------------------------------------------------------------------- #

def thinkers_stance(state, questions, timeout=90):
    """Send the shortlist's stance nouls and read the scores back.

    `questions` comes from thinkers.stance_questions(), which asks each
    framework both ways round. Keys are returned as sent -- `s_<id>` and
    `s2_<id>` -- because pairing them is product logic and belongs in
    thinkers.stance_scores(), not here.

    `state` comes from thinkers.scale_state(): the reader's own words plus the
    same decision in English, because the questions themselves say "support it"
    and never say what "it" is. It is sent once per request, which is the whole
    reason 510 judgements fit in one call with the decision written out once.

    A score that fails to come back is simply absent. The caller counts only
    what arrived, so a failed call can never be mistaken for "this framework
    says no".
    """
    if not questions:
        return {}, {}
    response = _post(
        jev_base() + "/v1/systemone",
        {"model": jev_model(), "state": state, "questions": questions},
        jev_key(),
        timeout=timeout,
    )
    answers = response.get("answers") or {}
    out = {}
    for key, value in answers.items():
        if key.startswith("s_") or key.startswith("s2_"):
            if isinstance(value, dict) and value.get("noul") is not None:
                out[key] = float(value["noul"])
    return out, response.get("usage") or {}
