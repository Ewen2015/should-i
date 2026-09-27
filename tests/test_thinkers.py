# -*- coding: utf-8 -*-
"""Pure-logic tests for thinkers.py. No network."""
import sys
from urllib.parse import quote

import _bootstrap  # noqa: F401  -- puts ../app on sys.path

import thinkers

from thinkers import (ANCHORS, CIRCLE_EN, CIRCLE_ORDER, CURRENT_YEAR, ROSTER, SIZE,
                      STANCE_AGAINST, STANCE_FOR, STANCE_PREFIX, STANCE_PREFIX_SWAP,
                      STANCE_YES, WIKI_HOST, WIKI_BASE,
                      Thinker, anchors_from_ids, circles_of, compose_batches,
                      end_year, frame_title, order_key, pinyin_of, plan,
                      scale_chunks, scale_state, span_label, stance_count,
                      stance_questions,
                      stance_scores, wiki_url, window_starts,
                      years_label)

N = [0, 0]
FAILS = []


def ok(cond, label):
    N[0] += 1
    if cond:
        N[1] += 1
    else:
        FAILS.append(label)


def eq(a, b, label):
    ok(a == b, "%s (got %r, want %r)" % (label, a, b))


def synth(n, circle, start=-2000, step=5):
    """`start` is the END year, because that is what the axis orders on."""
    return [Thinker("%s%d" % (circle, i), "T", "名", None, start + i * step - 60,
                    start + i * step, circle, 0.0, 0.0, "f") for i in range(n)]


# ---------------------------------------------------------------- the roster
eq(len(ROSTER), len(set(t.id for t in ROSTER)), "ids are unique")
ok(len(ROSTER) >= SIZE, "roster can fill at least one batch")
# The roster was 672 curated names until it was rebuilt from Wikidata; a
# regression that silently dropped the ingested block would still pass every
# other assertion here, so pin the scale.
ok(len(ROSTER) > 2500, "the ingested Wikidata roster is present")
ok(len({t.circle for t in ROSTER}) >= 12, "the roster spans most cultural circles")
ok(all(t.circle in CIRCLE_ORDER for t in ROSTER), "every circle is known")
ok(all(t.frame for t in ROSTER), "every thinker has a framework line")
ok(all(t.zh for t in ROSTER), "every thinker has a Chinese name")
ok(all(isinstance(t.born, int) for t in ROSTER), "every thinker has a birth year")
ok(all(-90 <= t.lat <= 90 for t in ROSTER), "latitudes are valid")
ok(all(-180 <= t.lon <= 180 for t in ROSTER), "longitudes are valid")
ok(all(t.died is None or t.died > t.born for t in ROSTER), "death is after birth")
# Names are a key, not a label: the picker offers a name and nothing else, so
# two rows sharing one is a reader staring at two identical chips and no way to
# tell which is which. The roster had exactly that until 2026-09-26 -- 36 people
# were in it twice, once from the hand-written core and once from the Wikidata
# harvest, with the same article and a simplified name in one row and a
# traditional one in the other (hitchins / 克里斯托弗·希钦斯 vs
# christopher_hitchens / 克里斯托弗·希欽斯). So this is exact, not "near":
eq(len({t.zh for t in ROSTER}), len(ROSTER), "no two thinkers share a Chinese name")

# One Wikipedia article is one person, and two rows pointing at the same
# article is the same person listed twice -- whatever the two names look like.
# This is the check that would have caught the 36 duplicates: the Chinese names
# did not always match character for character, but the article title always
# did. `Diogenes` and `Diogenes of Sinope` are the same page under two slugs,
# which is exactly the case a name-based comparison misses.
eq(len({t.wiki for t in ROSTER}), len(ROSTER),
   "no two thinkers link to the same Wikipedia article")

# ------------------------------------------------- names and Wikipedia links
# The page shows both languages and links each name to its article. The rule is
# now "no link, no listing": the two people we could not verify against any
# Wikipedia (足目, 万维钢) were dropped from the roster rather than shown as
# unclickable text, so the count is "all", not "most".
linked = [t for t in ROSTER if t.wiki]
en_linked = [t for t in linked if WIKI_HOST[t.id] == "en"]
zh_linked = [t for t in linked if WIKI_HOST[t.id] == "zh"]
ja_linked = [t for t in linked if WIKI_HOST[t.id] == "ja"]
# Nobody is linked to two wikis at once: WIKI_HOST is a single answer, and a
# person who appeared on two lists would get whichever _build() saw last.
eq(len(linked), len(en_linked) + len(zh_linked) + len(ja_linked),
   "every linked thinker is on exactly one wiki")
ok(all(t.en for t in en_linked), "every English-linked thinker has an English name")
eq(len(linked), len(ROSTER),
   "every thinker in the roster has a verified article (%d/%d)"
   % (len(linked), len(ROSTER)))
ok(all("(" not in t.en for t in en_linked if t.en),
   "the display name carries no disambiguator")
ok(zh_linked, "the roster links to the Chinese wiki where no English article exists")
ok(ja_linked, "the roster links to the Japanese wiki where no English article exists")
for t in linked:
    u = wiki_url(t)
    ok(not t.wiki.startswith(" ") and not t.wiki.endswith(" "),
       "the title for %s is not padded" % t.id)
    ok(" " not in u, "the url for %s has no raw space" % t.id)
    base = {"zh": "https://zh.wikipedia.org/wiki/",
            "ja": "https://ja.wikipedia.org/wiki/"}.get(
                WIKI_HOST[t.id], "https://en.wikipedia.org/wiki/")
    ok(u.startswith(base), "the url for %s is on the wiki its article is on" % t.id)
    eq(u, base + quote(t.wiki.replace(" ", "_")),
       "the url for %s is the quoted article title" % t.id)
    ok(not u.startswith("http://"), "the url for %s is https" % t.id)
# a person with no English article must not be given an invented English name
for t in zh_linked + ja_linked:
    ok(t.en is None, "%s has no English name, because it has no English article" % t.id)
# Everyone in the roster is linked, so nothing exercises this path today -- but
# `wiki_url` must still refuse to invent one when a future name cannot be
# verified. A link to a stranger is worse than no link.
nobody = Thinker("nobody", None, "无名", None, 1900, 1950, "cn", 0.0, 0.0, "f")
ok(wiki_url(nobody) is None, "a thinker with no article gets no link")
ok(nobody.en is None, "a thinker with no article gets no English name either")

# Xunzi's plain name is a disambiguation page, so the article keeps a qualifier
# while the name shown to the reader does not. This is the case that a naive
# "/wiki/" + label would have linked to the wrong page.
xunzi = [t for t in ROSTER if t.id == "xunzi"][0]
eq(xunzi.wiki, "Xunzi (philosopher)", "a disambiguated article keeps its qualifier")
eq(xunzi.en, "Xunzi", "the display name drops the qualifier")
ok("%28" in wiki_url(xunzi), "the disambiguator is percent-encoded")

# ----------------------------------------------------------- the end-year axis
alive = [t for t in ROSTER if t.died is None]
ok(len(alive) > 50, "the roster includes living thinkers")
for t in alive[:20]:
    eq(end_year(t), CURRENT_YEAR, "a living thinker's end year is this year")
ok(all(end_year(t) >= t.born for t in ROSTER), "end year is never before birth")
eq(max(end_year(t) for t in ROSTER), CURRENT_YEAR, "the axis reaches the present")

# the axis must NOT be the birth year -- that was the bug
ok(max(t.born for t in ROSTER) < CURRENT_YEAR - 30,
   "nobody is born in the current year, so a birth axis cannot reach now")

# figures the user named are actually present
by_zh = {t.zh: t for t in ROSTER}
for name in ("刘慈欣", "马斯克"):
    ok(name in by_zh, "%s is in the roster" % name)
    eq(end_year(by_zh[name]), CURRENT_YEAR, "%s is placed at now" % name)

# 尼采 was missing from the source lists entirely and was added by hand
# (2026-09-26) after the user asked for him. He is a person, not a test fixture,
# but a roster that quietly loses him again is the regression worth catching --
# the picker's pinyin index below is checked against his name for the same
# reason: "nicai" and "nc" are how someone will actually look for him.
ok("尼采" in by_zh, "尼采 is in the roster")
eq((by_zh["尼采"].born, by_zh["尼采"].died), (1844, 1900), "尼采 is 1844-1900")

# ----------------------------------------------- the 255 invariant, per frame
batches, reserve = compose_batches()
ok(len(batches) > 0, "produces batches")
for i, b in enumerate(batches):
    eq(len(b), SIZE, "batch %d is exactly %d" % (i, SIZE))
eq(len(reserve), 0, "a full roster leaves no reserve")

# ------------------------------- nobody is dropped, and the end is the present
covered = set()
for b in batches:
    covered |= {t.id for t in b}
eq(covered, {t.id for t in ROSTER}, "every thinker appears in at least one frame")

eq(max(end_year(t) for t in batches[-1]), CURRENT_YEAR,
   "the last frame reaches the present day")
ok(not any(end_year(t) > CURRENT_YEAR for b in batches for t in b),
   "no frame reaches into the future")
ok("至今" in span_label(batches[-1]) or "在世" in span_label(batches[-1]),
   "the last frame says the argument is still running")
# The living thinkers no longer fit in one frame, so the invariant is that the
# newest ones land in the final frames, not that every one of them lands in the
# very last one.
for name in ("刘慈欣", "马斯克"):
    ok(any(t.zh == name for b in batches[-2:] for t in b),
       "%s is judged in one of the final frames" % name)

# this is the bug the first version shipped: a strict partition dropped the tail,
# and the tail was the newest thinkers, so the animation stopped early.
eq(len(window_starts(517, 255)), 3, "517 needs 3 overlapping frames, not 2 + a dropped tail")

# --------------------------------------------------- batches are (time x space)
for i, b in enumerate(batches):
    ok(b == sorted(b, key=order_key), "batch %d is internally ordered" % i)
    ok(end_year(b[0]) <= end_year(b[-1]), "batch %d is a time interval" % i)

starts = [end_year(b[0]) for b in batches]
for i in range(1, len(starts)):
    ok(starts[i] > starts[i - 1], "batch %d starts later than batch %d" % (i, i - 1))

spans = [end_year(b[-1]) - end_year(b[0]) for b in batches]
ok(spans == sorted(spans, reverse=True), "batch spans shrink as history densifies")
eq(len(batches), -(-len(ROSTER) // SIZE), "the sweep covers the whole roster")
ok(spans[0] > spans[-1] * 3, "the earliest frame spans far more than the last")

# a roster that is an exact multiple of 255 still partitions with no overlap
exact = synth(SIZE * 3, "eu", start=-2000, step=1)
eb, er = compose_batches(exact, SIZE)
eq(len(eb), 3, "an exact multiple yields one frame per 255")
eq(len({t.id for b in eb for t in b}), SIZE * 3, "exact partition loses nobody")
eq(eb[0][-1].id, "eu254", "the first exact frame ends at 255")
eq(len(er), 0, "an exact partition leaves no reserve")

# ------------------------------------------------------------------ the edges
tb, tr = compose_batches(synth(100, "eu"), SIZE)
eq(len(tb), 0, "a pool under 255 yields no batch")
eq(len(tr), 100, "everything under 255 becomes reserve")
eq(window_starts(100, 255), [], "no window starts below one frame")
eq(window_starts(255, 255), [0], "exactly one frame is a single window")
eq(window_starts(510, 255), [0, 255], "two exact frames do not overlap")
# 511 cannot be covered by two windows: [0,255) + [255,510) leaves index 255 out.
eq(len(window_starts(511, 255)), 3, "one over needs a third window, not a dropped person")
eq(window_starts(511, 255), [0, 128, 256], "the extra window splits the overlap evenly")
eq(window_starts(511, 255)[-1], 511 - 255, "the last window still ends at the tail")
for n in (256, 300, 597, 672, 1000, 1275, 1276):
    ws = window_starts(n, SIZE)
    eq(ws[0], 0, "windows for n=%d start at 0" % n)
    eq(ws[-1], n - SIZE, "windows for n=%d end at the tail" % n)
    ok(all(ws[i] > ws[i - 1] for i in range(1, len(ws))), "windows for n=%d advance" % n)
    ok(all(ws[i] - ws[i - 1] <= SIZE for i in range(1, len(ws))),
       "windows for n=%d never leave a gap" % n)

# ------------------------------------------------- circle-scoped batches can fire
solo = synth(SIZE + 60, "eu", start=1900, step=0)
sb, sr = compose_batches(solo, SIZE)
ok(all(len(b) == SIZE for b in sb), "solo batches are exactly 255")
ok(all(circles_of(b) == ["eu"] for b in sb), "a solo-capable circle yields pure batches")
ok([{t.id for t in b} for b in sb][0] != [{t.id for t in b} for b in sb][1],
   "overlapping solo frames are not the same 255 people")

# a mixed pool keeps every circle rather than dropping the minority
mixed = synth(200, "eu", start=1900, step=0) + synth(80, "cn", start=1900, step=0)
mb, mr = compose_batches(mixed, SIZE)
ok(all(len(b) == SIZE for b in mb), "mixed batches are exactly 255")
eq({t.id for b in mb for t in b}, {t.id for t in mixed}, "a mixed pool loses nobody")

# ------------------------------------------------------------------ the shapes
b0 = batches[0]

# The Choice question that used to be built here -- `question_for()`, with its
# `criteria_for()` map -- is gone with the endpoint that sent it. No builder in
# thinkers.py puts anything other than 名字/生卒年/地区 in front of a model now,
# and the stance tests below are the guard on that promise.

# living thinkers read as open-ended, dead ones as a closed range
eq(years_label(by_zh["马斯克"]), "1971–", "a living thinker has an open range")
eq(years_label(by_zh["孔子"]), "551B–479B", "a BCE thinker reads as BCE")
ok("–" in years_label(by_zh["杨振宁"]), "a modern death reads as a closed range")

# ------------------------------------------------------- the picker's pinyin index
# The anchor picker matches three things: the characters, the English name, and
# the pinyin index. That index is GENERATED (gen_pinyin.py) from the roster, so
# the failure to guard against is somebody added to thinkers_data.py without
# re-running the generator: present on the map, findable by Chinese and English
# name, invisible to anyone typing pinyin.
ok(all(pinyin_of(t) for t in ROSTER if any("\u4e00" <= c <= "\u9fff" for c in t.zh)),
   "every Chinese name has a pinyin index")

# The three shapes the index has to carry: the primary reading, the initials a
# Chinese keyboard user abbreviates with, and -- for transliterated names -- the
# alternate reading, because pypinyin reads 缪 in 加缪 as mou and a reader who
# knows the name types miu.
for zh, form in (("康德", "kangde"), ("康德", "kd"), ("加缪", "jiamou"),
                 ("加缪", "jiamiu"), ("波伏娃", "bfw"), ("马斯克", "msk"),
                 ("老子", "lz"), ("迦那陀", "jianatuo"),
                 ("尼采", "nicai"), ("尼采", "nc")):
    ok(form in pinyin_of(by_zh[zh]).split(),
       "%s is searchable by %s" % (zh, form))

# A Latin-script roster name has nothing to romanise, and the picker matches it
# on the name itself -- so an empty index there is correct, not a gap.
eq(pinyin_of(by_zh["Basava"]), "", "a Latin-script name needs no pinyin index")

# Every dot in the payload carries its search forms, or the picker cannot use
# them; and the index is per-person data, not a per-keystroke computation.
ok(all(len(pinyin_of(t)) <= 64 for t in ROSTER), "the index stays small")

# ---------------------------------------------------------------- the frame plan
rows, res = plan()
eq(len(rows), len(batches), "plan has one row per batch")
for r in rows:
    eq(r["n"], SIZE, "plan row %d reports 255" % r["i"])
    ok(r["year_hi"] >= r["year_lo"], "plan row %d has a sane span" % r["i"])
    ok(r["title"], "plan row %d has a title" % r["i"])
ok(all(rows[i]["year_lo"] > rows[i - 1]["year_lo"] for i in range(1, len(rows))),
   "plan rows advance in time")
eq(rows[-1]["year_hi"], CURRENT_YEAR, "the plan's last row ends at the present")

# ------------------------------------------------------------ labels and spans
b = batches[0]
eq(span_label(b), "%s – %s" % ("公元前 %d 年" % -end_year(b[0]), "公元 %d 年" % end_year(b[-1])),
   "span label reads as an era range")
ok("/" in frame_title(b), "frame title is structured")
for t in ROSTER:
    eq(len(circles_of([t])), 1, "a single thinker has one circle")

# ------------------------------------------------------------ the stance layer
# Every person in a chunk gets asked one small question: would you read this
# person as for it or against it. These are nouls, so they do not compete with
# the rest of the 255 -- which is the whole reason they can be added up across
# eleven requests instead of staying inside one.
ok(0 < STANCE_YES < 1, "the stance threshold is a probability")

SHORT_FIX = 8
short = b0[:SHORT_FIX]
eq(len(short), SHORT_FIX, "the stance fixture is a fixed size")
sq = stance_questions(short)
eq(len(sq), 2 * len(short), "two stance questions per shortlisted thinker")
ok(all(k.startswith(STANCE_PREFIX) or k.startswith(STANCE_PREFIX_SWAP) for k in sq),
   "stance keys are namespaced")
ok(len(set(sq)) == len(sq), "stance keys are unique")
ok(all(v["type"] == "noul" for v in sq.values()), "stance questions are nouls")
fwd_keys = [k for k in sq if k.startswith(STANCE_PREFIX)]
swap_keys = [k for k in sq if k.startswith(STANCE_PREFIX_SWAP)]
eq(len(fwd_keys), len(short), "one forward question per thinker")
eq(len(swap_keys), len(short), "one swapped question per thinker")
eq(sorted(fwd_keys), sorted(STANCE_PREFIX + t.id for t in short), "forward ids match")

for t in short:
    for key in (STANCE_PREFIX + t.id, STANCE_PREFIX_SWAP + t.id):
        q = sq[key]
        ok(set(q["criteria"]) == {"true", "false"}, "stance %s has a true/false split" % key)
        ok(t.zh in q["instructions"], "stance %s names the thinker" % key)
        ok(years_label(t) in q["instructions"], "stance %s carries the years" % key)
        ok(CIRCLE_EN[t.circle] in q["instructions"],
           "stance %s carries the English circle" % key)
        if t.en:
            ok(t.en in q["instructions"], "stance %s carries the English name" % key)
        # The framework sentence must NOT come back. It was measured (see
        # docs/design.md 「只有身份，没有观点」): carrying it moved the average
        # person 0.0555, 9x the noise floor, and turned 24% of the roster
        # across 0.5.
        ok(not t.frame or t.frame.split("；")[0][:4] not in q["instructions"],
           "stance %s does not smuggle the framework back in" % key)
        ok(q["criteria"]["true"] in (STANCE_FOR, STANCE_AGAINST),
           "stance %s uses the English labels" % key)

# The whole point of the second question: `true` must change sides, otherwise
# centring the pair would cancel nothing.
for t in short:
    f = sq[STANCE_PREFIX + t.id]
    b = sq[STANCE_PREFIX_SWAP + t.id]
    ok(f["criteria"]["true"] != b["criteria"]["true"],
       "the swapped question moves `true` to the other side (%s)" % t.id)
    eq(b["criteria"]["true"], f["criteria"]["false"],
       "swapped true is forward false (%s)" % t.id)
    # Leading label, not merely "contains": "not support it" ends with
    # "support it", so a suffix test would pass on the wrong ordering.
    ok(b["instructions"].split("would he say: ")[1].startswith(STANCE_AGAINST + ","),
       "the swapped instruction leads with the `not support` label (%s)" % t.id)
    ok(f["instructions"].split("would he say: ")[1].startswith(STANCE_FOR + ","),
       "the forward instruction leads with the `support` label (%s)" % t.id)

# Centring: (forward - backward + 1) / 2. A pair that agrees sits on 0.5 no
# matter how loud it is, because that is exactly the tilt being removed.
ids = [t.id for t in short]
pair = {}
for i in ids:
    pair[STANCE_PREFIX + i] = 0.9
    pair[STANCE_PREFIX_SWAP + i] = 0.1
sc = stance_scores(short, pair)
eq(len(sc), len(short), "every fully answered thinker gets a score")
ok(all(abs(v - 0.9) < 1e-9 for v in sc.values()),
   "a 0.9/0.1 pair centres at 0.9")
eq(stance_scores(short, {STANCE_PREFIX + ids[0]: 0.6,
                         STANCE_PREFIX_SWAP + ids[0]: 0.6})[ids[0]], 0.5,
   "a framework read the same both ways sits on the fence")
eq(stance_scores(short, {STANCE_PREFIX + ids[0]: 0.95,
                         STANCE_PREFIX_SWAP + ids[0]: 0.95})[ids[0]], 0.5,
   "a model that just likes `true` gets 0.5, not 0.95")
ok(abs(stance_scores(short, {STANCE_PREFIX + ids[0]: 0.9,
                             STANCE_PREFIX_SWAP + ids[0]: 0.9})[ids[0]] - 0.5) < 1e-9,
   "the tilt cancels at any loudness")
eq(stance_scores(short, {STANCE_PREFIX + ids[0]: 0.9}), {},
   "one direction is not enough to centre")
half = {STANCE_PREFIX + ids[0]: 0.9, STANCE_PREFIX_SWAP + ids[0]: 0.1,
        STANCE_PREFIX + ids[1]: 0.9}
eq(list(stance_scores(short, half)), [ids[0]], "a half-answered thinker is dropped")
eq(stance_scores(short, {}), {}, "no answers means no scores")

# Only what came back is counted: a missing score must never read as a "no".
# Returns (yes, answered) -- answered, not against. The second slot is the
# denominator the page prints, so getting it backwards renders "6 of 2".
eq(stance_count(short, {}), (0, 0), "no scores means no verdicts")
eq(stance_count(short, {ids[0]: 0.9, ids[1]: 0.1}), (1, 2), "one for of two answered")
eq(stance_count(short, {ids[0]: STANCE_YES}), (1, 1), "the threshold itself counts as yes")
eq(stance_count(short, {ids[0]: STANCE_YES - 0.001}), (0, 1),
   "just below the threshold is a no")
eq(stance_count(short, {i: 1.0 for i in ids}), (len(short), len(short)), "all yes")
eq(stance_count(short, {i: 0.0 for i in ids}), (0, len(short)), "all no")
eq(stance_count(short, {ids[0]: 1.0, "nobody": 1.0}), (1, 1),
   "a score for someone outside the shortlist is ignored")

yes, answered = stance_count(short, {ids[0]: 1.0})
eq((yes, answered), (1, 1), "a single score answers for one")
ok(answered < len(short), "missing scores shrink the denominator")
for k in range(len(short)):
    part = dict((i, 0.9) for i in ids[:k])
    y, a = stance_count(short, part)
    eq(a, k, "%d scores answer for %d" % (k, k))
    ok(y <= a, "yes never outruns answered (%d scores)" % k)

# ------------------------------------------------------- what the run is over
# Every stance noul says "support it" and none of them names "it": the decision
# lives in the state, once per request. These pin the two things that makes it
# readable -- the reader's own words are in there, and the English the questions
# are asked in is in there with them -- and the one thing it must not do, which
# is pass off a translation nobody made.
state = scale_state("人类要成为一个星际文明吗？",
                    "Do you support humanity becoming an interstellar civilisation?")
eq(state["what_the_user_typed"], "人类要成为一个星际文明吗？",
   "the reader's own words ride along verbatim")
eq(state["the_same_decision_in_english"],
   "Do you support humanity becoming an interstellar civilisation?",
   "the English the questions are asked in is in the state")
ok("support" in state["note"] and "decision" in state["note"],
   "the note ties `support it` to that decision")

# No English, no claim of one. This is the DeepSeek-unreachable path: the run
# still happens, judged on the reader's words, which is what shipped before.
bare = scale_state("人类要成为一个星际文明吗？")
eq(bare, {"what_the_user_typed": "人类要成为一个星际文明吗？"},
   "without the restatement the state is the reader's words and nothing else")
ok("note" not in bare, "no note when there is no decision to point at")
eq(scale_state("要不要辞职？", "   "), {"what_the_user_typed": "要不要辞职？"},
   "whitespace is not an English restatement")

# An English question needs no second copy of itself.
eq(scale_state("Do you support quitting your job?",
               "Do you support quitting your job?"),
   {"what_the_user_typed": "Do you support quitting your job?"},
   "a reader who already wrote English gets one line, not two")

# ------------------------------------------------- the whole-roster ruler
# The scale is the one route that asks about every name at once, so the things
# that can go wrong there are coverage (someone silently dropped) and linkage
# (two requests that cannot be read against each other). Both are pinned here.
chunks = scale_chunks()
rung_ids = set(t.id for t in ANCHORS)
all_ids = [t.id for c in chunks for t in c]
eq(sorted(set(len(c) for c in chunks)), [SIZE], "every scale chunk is exactly full")
eq(set(all_ids), set(t.id for t in ROSTER), "the ruler covers every single person")
ok(all(len([t for t in c if t.id in rung_ids]) == len(ANCHORS) for c in chunks),
   "every chunk carries all %d rungs" % len(ANCHORS))
# A rung asked twice inside one request would let one person's two answers
# disagree where nobody could explain why.
for c in chunks:
    ok(len(set(t.id for t in c)) == len(c), "no duplicate option inside a chunk")
# The last chunk is clamped to reach the present, so the newest people are
# measured twice -- that overlap is a free second reading, not an accident.
repeated = [i for i in set(all_ids) if all_ids.count(i) > 1]
ok(len(repeated) >= len(ANCHORS), "the rungs are all measured more than once")
ok(all(any(t.id in rung_ids for t in c) for c in chunks), "no chunk lost its rungs")
# The tail is the thing that silently vanished once before: a partition that
# does not clamp ends the ruler decades before the present.
ordered = sorted(ROSTER, key=order_key)
eq([t.id for t in chunks[-1] if t.id not in rung_ids][-1], ordered[-1].id,
   "the last chunk ends on the newest thinker in the roster")
eq(end_year([t for t in chunks[-1] if t.id not in rung_ids][-1]), CURRENT_YEAR,
   "and that person is still speaking")
ok(len([t for t in chunks[-1] if t.id not in rung_ids] ) == SIZE - len(ANCHORS),
   "last chunk is full after the clamp")
# Dropping the rungs must still cover the whole roster: the anchors are drawn
# FROM the roster, so turning them off is a different chunking, not a subset.
plain = scale_chunks(anchors=False)
eq(sorted(set(len(c) for c in plain)), [SIZE], "unanchored chunks are full too")
eq(set(t.id for c in plain for t in c), set(t.id for t in ROSTER),
   "unanchored chunking still covers everyone exactly the same")

# ---------------------------------------------- the reader's own rungs
# The twelve are a default, not a fixture: the page lets someone put their own
# people on the ruler. A rung they chose has to be measured exactly like one we
# chose, so the only difference allowed is WHICH ids come back.
mine = anchors_from_ids(["kanada", "laozi", "musk"])
eq([t.zh for t in mine][:1], ["迦那陀"], "the reader's order is kept")
mine_chunks = scale_chunks(anchors=mine)
eq(len(mine_chunks), len(chunks), "swapping rungs does not change the request count")
eq(sorted(set(len(c) for c in mine_chunks)), [SIZE], "custom-rung chunks are still full")
eq(set(t.id for c in mine_chunks for t in c), set(t.id for t in ROSTER),
   "custom rungs still cover every person")
mine_ids = set(t.id for t in mine)
ok(all(len([t for t in c if t.id in mine_ids]) == len(mine) for c in mine_chunks),
   "every chunk carries all of the reader's rungs")
# A person asked twice inside one request could disagree with themselves.
eq(len(anchors_from_ids(["laozi", "laozi", "musk"])), 2, "duplicate rungs collapse")
# Silently measuring fewer rungs than asked for is how a calibration ends up
# describing something other than what the page says it did.
try:
    anchors_from_ids(["laozi", "not_a_person"])
    ok(False, "an unknown rung is refused")
except ValueError:
    ok(True, "an unknown rung is refused")
try:
    anchors_from_ids([])
    ok(False, "an empty ruler is refused")
except ValueError:
    ok(True, "an empty ruler is refused")

# ------------------------------------------------- the removed Choice layer
# `question_for()` / `criteria_for()` / `stance_shortlist()` / `STANCE_N` were
# deleted on 2026-09-26, along with `/api/thinkers/run` and `/api/thinkers/stream`
# and `upstreams.thinkers_frame()`. They are what sent a 255-option Choice whose
# option labels carried our one-line summary of each person, and no builder may
# do that again: an option label IS the prompt, and that summary was measured to
# be the thing being measured rather than a reminder about the person. This is
# the tripwire, not a style preference.
for gone in ("question_for", "criteria_for", "stance_shortlist", "STANCE_N"):
    ok(not hasattr(thinkers, gone), "thinkers.%s stays deleted" % gone)

print("thinkers: %d/%d passed" % (N[1], N[0]))
for f in FAILS:
    print("  FAIL:", f)
sys.exit(1 if FAILS else 0)
