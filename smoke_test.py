#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end check of a running Ask Great Thinkers server, without a browser.

    python3 -u server.py &
    python3 smoke_test.py "人类要成为一个星际文明吗？"          # plan + rewrite only
    python3 smoke_test.py "人类要成为一个星际文明吗？" --run    # + the full 11-chunk sweep

Two levels on purpose, because the two halves of this product cost wildly
different amounts. `/api/thinkers/plan` and `/api/thinkers/frame` are a local
read and one short DeepSeek call. `/api/thinkers/scale` is eleven Jev requests
carrying 5,610 judgements, which is real money -- so it only runs when you ask
for it with --run.

It talks to 127.0.0.1 only, so it must not go through whatever http_proxy the
machine has set: a local proxy answers 502 for loopback and it looks like the
server is down.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

DEFAULT_QUESTION = "人类要成为一个星际文明吗？"


def call(base, path, payload=None, method=None, timeout=180):
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if data is not None else "GET"),
    )
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def stream(base, path, payload):
    """POST and read the NDJSON lines as they land, printing each one."""
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with OPENER.open(request, timeout=900) as response:
        for raw in response:
            line = raw.decode().strip()
            if line:
                yield json.loads(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--base", default="http://127.0.0.1:8420")
    parser.add_argument("--run", action="store_true",
                        help="also run the 11-chunk sweep (spends real tokens)")
    parser.add_argument("--anchors", default="",
                        help="comma-separated roster ids to use as the ruler")
    args = parser.parse_args()

    status, health = call(args.base, "/api/health")
    if status != 200:
        sys.exit("server not reachable at %s (%s)" % (args.base, status))
    settings_status = health.get("settings") or {}
    where = {"settings": "设置文件", "env": "环境变量"}

    def source_of(name):
        entry = settings_status.get(name) or {}
        found = where.get(entry.get("source"), "未设置")
        hint = entry.get("hint")
        return "%s: %s%s" % (entry.get("label", name), found,
                             "（%s）" % hint if hint else "")

    print("=== 0. health ===")
    print("  ", " | ".join(source_of(n) for n in ("jev_api_key", "deepseek_api_key")))
    print("   jev    %s model=%s" % (health.get("jev_base"), health.get("jev_model")))
    print("   deepseek %s model=%s" % (health.get("deepseek_base"),
                                       health.get("deepseek_model")))

    print("\n=== 1. plan (local, free) ===")
    status, plan = call(args.base, "/api/thinkers/plan")
    if status != 200:
        sys.exit("plan failed: %s %s" % (status, json.dumps(plan, ensure_ascii=False)[:300]))
    print("   名录 %d 位 · %d 帧 × %d 位 · %d 个文化圈"
          % (plan["roster"], len(plan["frames"]), plan["size"], len(plan["circles"])))
    for row in plan["frames"][:2] + plan["frames"][-1:]:
        print("     帧 %-2d %s" % (row["i"], row["title"]))
    print("   尺子默认 12 人:", " ".join(a["zh"] for a in plan["anchors"]))

    print("\n=== 2. frame (one short DeepSeek call) ===")
    status, frame = call(args.base, "/api/thinkers/frame", {"question": args.question})
    if status != 200:
        sys.exit("frame failed: %s %s" % (status, json.dumps(frame, ensure_ascii=False)[:300]))
    print("   原话    :", frame["question"])
    print("   改写    :", frame["frame"])
    print("   英文题干:", frame["frame_en"] or "（没拿到，运行只用原话）")

    if not args.run:
        print("\n（没有跑尺子。加 --run 才会发那 11 次请求。）")
        return 0

    print("\n=== 3. scale (11 chunks x 255 x 2 judgements) ===")
    payload = {"question": args.question, "frame_en": frame["frame_en"]}
    if args.anchors:
        payload["anchors"] = [a for a in args.anchors.split(",") if a]
    for line in stream(args.base, "/api/thinkers/scale", payload):
        if line.get("type") == "meta":
            print("   %d 批 · %d 位·次 · state=%s"
                  % (line["total"], line["measurements"],
                     json.dumps(line["state"], ensure_ascii=False)))
        elif line.get("type") == "progress":
            print("   第 %2d/%d 批 已回 %4d 人" % (line["done"], line["total"],
                                                  line["answered"]))
        elif line.get("type") == "error":
            sys.exit("scale failed: %s" % line["error"])
        elif line.get("type") == "scale":
            scores = line["scores"]
            answered = line["answered"]
            yes = [k for k, v in scores.items() if v >= 0.6]
            no = [k for k, v in scores.items() if v < 0.4]
            mid = answered - len(yes) - len(no)
            print("\n   覆盖 %d / %d，%d 人测了不止一次" % (answered, line["roster"],
                                                          line["repeats"]))
            print("   分档 最支持 %d · 无所谓 %d · 最反对 %d" % (len(yes), mid, len(no)))
            print("   花费 %s 输入 / %s 输出 token（%d/%d 批复用）"
                  % (line["usage"].get("input_tokens"), line["usage"].get("output_tokens"),
                     line.get("reused", 0), line["chunks"]))
            print("   节省 %s / %s（缓存" % (line["saved"].get("input_tokens"),
                                             line["saved"].get("output_tokens")) + "）")
            cal = line["calibration"]
            print("   锚点跨 %d 批: 最大差 %.4f · 平均差 %.4f"
                  % (cal["rung"]["n"], cal["rung"]["max_delta"], cal["rung"]["mean_delta"]))
            print("   重叠的人两次: 最大差 %.4f" % cal["repeat"]["max_delta"])
            ranked = sorted(scores.items(), key=lambda kv: -kv[1])
            for key, value in ranked[:5] + ranked[-5:]:
                print("     %-28s %.3f" % (key, value))
        elif line.get("type") == "done":
            print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
