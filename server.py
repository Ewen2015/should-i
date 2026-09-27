#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask Great Thinkers -- 2578 people asked one question.

    export TYPESAFE_API_KEY="..."   # Jev: the judgements
    export DEEPSEEK_API_KEY="..."   # one short call: naming what X is
    python3 server.py               # then open http://127.0.0.1:8420

Standard library only, no build step, no framework. The API keys stay in this
process; the browser only ever talks to /api/*.

    GET  /api/health          -> which vars the server can see (booleans only)
    GET  /api/settings        -> configured / where from / last four, never a key
    GET  /api/thinkers/plan   -> the roster, its circles and its frames
    POST /api/settings        {jev_api_key, deepseek_api_key, test} -> status only
    POST /api/thinkers/frame  {question}         -> "你支持 X 吗？" + the English X
    POST /api/thinkers/scale  {question, ...}    -> the whole roster, as NDJSON

There is no database and no user. Nothing here is about the reader, so there is
nothing to remember about them -- which is also why a thinkers run takes no lock:
it is eleven upstream calls and no tables.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import settings  # noqa: E402
import thinkers  # noqa: E402
import upstreams  # noqa: E402

# The whole-roster scale sweep. Each chunk is 510 nouls (255 thinkers x both
# directions), so four in flight is ~2000 judgements outstanding -- a lot to ask
# of one API, but the single-chunk measurement came back in 4.2s, which leaves
# headroom.
SCALE_WORKERS = 4

INDEX = os.path.join(HERE, "index.html")


def _calibration(seen, rung_ids, zh_by_id):
    """How far the same person moved between chunks -- the proof, not the promise.

    Two kinds of repeat. The rungs are asked inside all eleven chunks, so
    their spread is the direct cost of splitting the roster across requests. The
    newest seventy are in two chunks because the last one is clamped to reach the
    present, so their spread is the same measurement made by a different worker
    on a different slice.

    `zh_by_id` is passed in rather than read off thinkers.ANCHORS because the
    rungs are the reader's choice now: naming them from the shipped twelve would
    put the wrong name on a rung they replaced.

    Everything here is absent-but-honest: a rung that did not come back in a
    chunk simply contributes fewer values, and if nothing repeated at all the
    spreads are 0 rather than a confident-looking lie.
    """
    rungs, repeats = [], []
    for key, values in seen.items():
        if len(values) < 2:
            continue
        span = max(values) - min(values)
        (rungs if key in rung_ids else repeats).append((key, values, span))

    def summarise(rows):
        return {
            "n": len(rows),
            "max_delta": round(max([r[2] for r in rows] or [0]), 4),
            "mean_delta": round(
                sum(r[2] for r in rows) / len(rows), 4) if rows else 0.0,
        }

    return {
        "rungs": sorted(
            [
                {
                    "id": key,
                    "zh": zh_by_id.get(key),
                    "n": len(values),
                    "mean": round(sum(values) / len(values), 4),
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                }
                for key, values, _span in rungs
            ],
            key=lambda r: r["mean"],
        ),
        "rung": summarise(rungs),
        "repeat": summarise(repeats),
    }


def _zh_by_id(rungs):
    return {t.id: t.zh for t in rungs}





class Handler(BaseHTTPRequestHandler):
    server_version = "AskGreatThinkers/0.1"
    settings_lock = threading.Lock()  # serialises read-modify-write of the key file

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))

    # -- helpers ----------------------------------------------------------- #
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode() or "{}")

    # -- routes ------------------------------------------------------------ #
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            with open(INDEX, "rb") as handle:
                self._send(200, handle.read(), "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if path == "/api/health":
            self._send(
                200,
                {
                    # Booleans plus where each key came from -- never a key.
                    "jev_key": upstreams.key_source("jev_api_key") is not None,
                    "deepseek_key": upstreams.key_source("deepseek_api_key") is not None,
                    "settings": upstreams.key_status(),
                    "jev_model": upstreams.jev_model(),
                    "jev_base": upstreams.jev_base(),
                    "deepseek_model": upstreams.deepseek_model(),
                    "deepseek_base": upstreams.deepseek_base(),
                },
            )
            return
        if path == "/api/settings":
            self._send(200, {"settings": upstreams.key_status()})
            return
        if path == "/api/thinkers/plan":
            rows, reserve = thinkers.plan()
            _batches, _reserve2 = thinkers.compose_batches()
            # Frames overlap on purpose (see thinkers.window_starts), so a
            # thinker can be judged in more than one frame -- this is a list.
            frame_of = {}
            for _i, _b in enumerate(_batches):
                for _t in _b:
                    frame_of.setdefault(_t.id, []).append(_i)
            self._send(
                200,
                {
                    "size": thinkers.SIZE,
                    "roster": len(thinkers.ROSTER),
                    "reserve": reserve,
                    "frames": rows,
                    "circles": thinkers.CIRCLE_ZH,
                    # The ruler's shipped twelve, so the picker can open on the
                    # current set before a run has ever happened.
                    "anchors": [
                        {"id": t.id, "zh": t.zh, "en": t.en}
                        for t in thinkers.ANCHORS
                    ],
                    "dots": [
                        {
                            "id": t.id,
                            "zh": t.zh,
                            "en": t.en,
                            # The URL is built server-side; the browser never
                            # assembles one out of a name.
                            "url": thinkers.wiki_url(t),
                            "wiki": t.wiki,
                            "born": t.born,
                            # The map sweeps on the end year, not the birth
                            # year: a living thinker counts as still speaking,
                            # so they light up at "now" rather than decades ago.
                            "end_year": thinkers.end_year(t),
                            "died": t.died,
                            "circle": t.circle,
                            "lat": t.lat,
                            "lon": t.lon,
                            # Search forms for the picker: pinyin of the
                            # Chinese name, so a Chinese keyboard can reach
                            # 康德 and 加缪. See thinkers.pinyin_of().
                            "py": thinkers.pinyin_of(t),
                            # Which frames judge this thinker, taken from the
                            # batches themselves. Anything in `reserve` never
                            # gets judged, so it stays empty rather than guessed at.
                            "frames": frame_of.get(t.id, []),
                        }
                        for t in thinkers.ROSTER
                    ],
                },
            )
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self._read_json()
        except ValueError:
            self._send(400, {"error": "请求体不是合法 JSON"})
            return

        # A connectivity test makes two network calls and a scale run makes
        # eleven, and none of them touches a table -- so nothing here takes a
        # lock except the read-modify-write of the key file, which is the one
        # thing two requests must not interleave.
        if path.startswith("/api/settings"):
            with self.settings_lock:
                self.dispatch_post(path, body)
            return
        self.dispatch_post(path, body)

    def dispatch_post(self, path, body):
        try:
            if path == "/api/settings":
                self._send(200, self.handle_settings(body))
            elif path == "/api/settings/test":
                self._send(200, {"settings": upstreams.key_status(),
                                 "test": upstreams.check_keys()})
            elif path == "/api/thinkers/frame":
                self._send(200, self.handle_thinkers_frame(body))
            elif path == "/api/thinkers/scale":
                self.handle_thinkers_scale(body)
            else:
                self._send(404, {"error": "not found"})
        except upstreams.UpstreamError as exc:
            self._send(
                502,
                {
                    "error": str(exc),
                    "hint": "去「设置」里填 key，或检查环境变量和网络",
                    # The page turns this into a link, so a missing key is one
                    # click from being fixed rather than a dead end.
                    "settings": upstreams.key_status(),
                },
            )
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception:  # noqa: BLE001 - prototype: surface the traceback to the console
            traceback.print_exc()
            self._send(500, {"error": "服务端异常，看终端日志"})

    # -- handlers ---------------------------------------------------------- #
    # The Choice-path handlers (`_thinkers_batches`, `thinkers_frames`,
    # `_thinkers_frame`, `handle_thinkers_run`) and `handle_thinkers_stream`
    # were deleted on 2026-09-26, with the endpoints that called them. They sent
    # one 255-option Choice per frame and followed it with a stance noul on the
    # options that lit up; the page renders the ruler instead, which asks every
    # person in a chunk. There is no second path left to keep in sync.

    def handle_thinkers_scale(self, body):
        """Score the WHOLE roster on one scale, streamed as the chunks land.

        This is the answer to "put all of humanity on one ruler". It has to be
        nouls, not Choices. A Choice asks "which ONE of these 255 is most apt",
        and 255 options is a competition: measured on the real API, a 255-option
        Choice returns probabilities for 3-6 of them and exactly zero for the
        other ~250, including names like 孔子 and 苏格拉底. Zero cannot be
        rescaled -- no anchor arithmetic turns it back into a position -- so a
        Choice can rank the top of a batch and nothing else. See docs/design.md
        「为什么是 noul，不是 Choice」 before "fixing" this into a Choice.

        A noul is a plain judgement that does not compete, and it was measured
        batch-independent: the same frameworks inside two batches whose other 243
        members come from opposite ends of history agreed to r=0.995, max
        |delta| 0.050. That is exactly the property a common scale needs.

        The eleven chunks all carry the same rungs -- thinkers.ANCHORS by
        default, or the reader's own list if the request names one -- so the
        cross-request agreement is measured live and shipped with the scores
        rather than claimed here.
        """
        question = (body.get("question") or "").strip()
        if len(question) < 2:
            self._send(400, {"error": "先说一件你在纠结的事"})
            return
        # What the whole run is judged over: the reader's own words, plus the
        # decision in the English the questions are asked in. The nouls say
        # "support it" without ever naming what "it" is -- an unresolvable
        # pronoun in every one of them, all pointing at a state that until now
        # was only the question they typed. The English ride-along comes from
        # /api/thinkers/frame, the same call that paints the headline, so the
        # sentence on screen and the sentence in the state cannot disagree. It
        # is shape-checked here rather than trusted: a stale or Chinese line
        # would silently mislabel every judgement under it.
        state = thinkers.scale_state(
            question, upstreams.frame_en_ok(body.get("frame_en"))
        )
        # The reader may replace the ruler's twelve people. Resolved before the
        # headers go out, so a bad id is a normal 400 and never a stream that
        # dies halfway through spending their tokens.
        # `is None` rather than truthiness on purpose: an empty list is a
        # REQUEST for an empty ruler, which is an error, not a request for the
        # default. Testing this the sloppy way once cost a real eleven-request
        # run -- `[]` fell through to the shipped twelve and quietly asked
        # Jev 5226 questions.
        raw_anchors = body.get("anchors")
        try:
            rungs = (thinkers.anchors_from_ids(raw_anchors) if raw_anchors is not None
                     else thinkers.ANCHORS)
        except (ValueError, TypeError) as exc:
            self._send(400, {"error": str(exc)})
            return
        if len(rungs) >= thinkers.SCALE_PER_REQUEST:
            self._send(400, {"error": "标尺人太多，每批装不下"})
            return
        chunks = thinkers.scale_chunks(anchors=rungs)
        rung_ids = set(t.id for t in rungs)
        zh_by_id = _zh_by_id(rungs)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def line(obj):
            self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
            self.wfile.flush()

        line({"type": "meta", "total": len(chunks), "roster": len(thinkers.ROSTER),
              "measurements": sum(len(c) for c in chunks),
              # Sent so the page can show the reader the exact words the run was
              # judged over instead of paraphrasing them.
              "state": state,
              "anchors": [{"id": t.id, "zh": t.zh, "en": t.en} for t in rungs]})

        # `usage` is what this run actually spent. `saved` is what it would have
        # spent without the cache -- kept as a separate number rather than folded
        # into the first, because a run that reads eleven answers off the disk
        # cost nothing and reporting 636k tokens for it would be a lie about the
        # one thing this page is careful about.
        usage = {}
        saved = {}
        reused = 0
        # Every measurement of every person, in landing order. 119 of the 2578 are
        # measured more than once -- the 12 rungs in all 11 chunks, plus the
        # newest 107, whose last chunk overlaps on purpose. Averaging instead of
        # overwriting is what turns the repeat into a second measurement rather
        # than a race between two workers.
        seen = {}

        def judged(chunk):
            raw, used = upstreams.thinkers_stance(
                state, thinkers.stance_questions(chunk), timeout=600
            )
            return thinkers.stance_scores(chunk, raw), used

        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=SCALE_WORKERS
            ) as pool:
                futures = [pool.submit(judged, chunk) for chunk in chunks]
                for n, future in enumerate(
                    concurrent.futures.as_completed(futures), start=1
                ):
                    part, used = future.result()
                    for key, value in part.items():
                        seen.setdefault(key, []).append(value)
                    if used.get("reused"):
                        reused += 1
                    for key in ("input_tokens", "output_tokens"):
                        usage[key] = usage.get(key, 0) + (used.get(key) or 0)
                        saved[key] = saved.get(key, 0) + (
                            used.get("saved_" + key) or 0
                        )
                    # The scores ride along with the progress line, not only in
                    # the final one. The page animates century by century and
                    # advances on what has actually arrived, so "how many are
                    # back" is not enough -- it needs to know WHICH ones, or it
                    # would have to guess which century is safe to show.
                    line({"type": "progress", "done": n, "total": len(chunks),
                          "answered": len(seen),
                          "scores": {k: round(v, 4) for k, v in part.items()}})
        except Exception as exc:  # noqa: BLE001 - the status line is long gone
            line({"type": "error", "error": str(exc)})
            return

        # Missing thinkers are simply absent, never 0.5: "we did not get an
        # answer" and "the framework sits on the fence" are different claims and
        # only one of them is a finding.
        scores = {k: sum(v) / len(v) for k, v in seen.items()}
        line({"type": "scale", "scores": {k: round(v, 4) for k, v in scores.items()},
              "answered": len(scores), "roster": len(thinkers.ROSTER),
              "repeats": sum(1 for v in seen.values() if len(v) > 1),
              "usage": usage, "chunks": len(chunks),
              "reused": reused, "saved": saved,
              "calibration": _calibration(seen, rung_ids, zh_by_id)})
        line({"type": "done"})

    def handle_thinkers_frame(self, body):
        """The question as the 0-1 scale reads it: "你支持X吗？".

        Separate from /api/thinkers/scale on purpose. This one is one short
        DeepSeek call with no roster in it, so the page can ask for it the moment
        the reader submits and paint it long before the 11 Jev requests land.
        """
        question = (body.get("question") or "").strip()
        if len(question) < 2:
            raise ValueError("先说一件你在纠结的事")
        frame, frame_en = upstreams.frame_support(question)
        return {"frame": frame, "frame_en": frame_en,
                "question": question}

    def handle_settings(self, body):
        """Save keys the user typed. Returns status only -- never the keys back.

        Validation is deliberately about paste accidents rather than format: API
        keys are opaque, so there is nothing to check but "did a newline or a
        stray space come along with it" and "is this plausibly a key".
        """
        patch = {}
        for name in settings.FIELDS:
            if name not in body:
                continue
            value = body.get(name)
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ValueError("%s 必须是字符串" % name)
            value = value.strip()
            if len(value) > settings.MAX_KEY_LENGTH:
                raise ValueError("%s 太长了（超过 %d 个字符）" % (name, settings.MAX_KEY_LENGTH))
            if any(ch.isspace() for ch in value):
                raise ValueError("%s 中间有空白字符——像是粘贴时带上了换行或空格" % name)
            patch[name] = value
        if patch:
            settings.save(patch)
        result = {"settings": upstreams.key_status()}
        if body.get("test"):
            # Same request, so saving and checking cannot get out of step: the
            # test always runs against what was just written.
            result["test"] = upstreams.check_keys()
        return result


def main():
    parser = argparse.ArgumentParser(description="Ask Great Thinkers server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8420)))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    missing = [
        upstreams.PROVIDER_LABEL[name]
        for name in settings.FIELDS
        if upstreams.key_source(name) is None
    ]
    if missing:
        print(
            "警告：还没有 %s 的 API key。可以设环境变量，或者在页面的「设置」里填。"
            % "、".join(missing),
            file=sys.stderr,
        )
    else:
        for name in settings.FIELDS:
            source = upstreams.key_source(name)
            print(
                "%-9s: 来自%s"
                % (upstreams.PROVIDER_LABEL[name], "设置文件" if source == "settings" else "环境变量")
            )

    print("Jev      : %s  model=%s" % (upstreams.jev_base(), upstreams.jev_model()))
    print("DeepSeek : %s  model=%s" % (upstreams.deepseek_base(), upstreams.deepseek_model()))
    print("open     : http://%s:%d" % (args.host, args.port))
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
