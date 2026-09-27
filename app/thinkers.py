# -*- coding: utf-8 -*-
"""Ask Great Thinkers — roster, batching, and the Jev question shape.

Pure logic, no network. `upstreams.py` sends what this module builds.

LOCKED-IN DESIGN (do not undo)
---------------------------------------------------------------------------
1. Every Jev call carries EXACTLY `SIZE` (255) judgements. Never fewer. The API
   caps one request at 255, and a short batch is a wasted request.
2. No thinker is ever dropped, and the last frame reaches the newest thinker.
   A strict partition cannot do both (597 = 2x255 + 87), so consecutive frames
   OVERLAP by whatever it takes. Dropping the tail instead would silently end
   the animation decades before the present -- which is exactly what the first
   version did: the roster was 517 = 2x255 + 7 and the 7 leftovers were the 7
   newest thinkers, so the map stopped at 1949.
2. A batch is a slab of (time x space): the roster is ordered by year and cut
   into runs of SIZE. Early history is sparse, so one batch spans millennia
   and the whole world; as the roster densifies the same rule narrows a batch
   to a few decades inside one cultural circle. The batch boundary is
   discovered from the data, not hard-coded.
3. When one cultural circle can fill a whole batch on its own, it gets its
   own batch instead of sharing. That is what makes the modern frames read
   "German-speaking Europe, 1890-1930" rather than "everyone alive in 1900".
4. Every question names its person by IDENTIFICATION ONLY -- 中英文名, 生卒年,
   文化圈 -- and says nothing about what that person thought. The one-line
   framework summary that used to ride along was measured to be the thing being
   measured rather than a reminder; see docs/design.md 「只有身份，没有观点」.
"""
import urllib.parse
from collections import Counter, namedtuple
from datetime import date

from thinkers_data import ENGLISH, JA_WIKI, RAW, ZH_WIKI
from thinkers_pinyin import PY as PINYIN_FORMS

SIZE = 255          # the API's per-request cap; also one timeline frame
CURRENT_YEAR = date.today().year   # a living thinker counts as "still speaking"
DOMINANT_SHARE = 0.6   # one circle this dominant in the head of the pool may solo
DOMINANT_SPAN = 120    # ...only if the head of the pool is this tight in years

CIRCLE_ORDER = ("cn", "jp", "kr", "sea", "in", "isl", "grc", "rom", "eu", "ee", "na", "latam", "afr")
CIRCLE_ZH = {
    "cn": "中国", "jp": "日本", "kr": "朝鲜半岛", "sea": "东南亚",
    "in": "印度", "isl": "伊斯兰·波斯", "grc": "古典希腊", "rom": "罗马·地中海",
    "eu": "西欧", "ee": "东欧·俄罗斯", "na": "北美", "latam": "拉美", "afr": "非洲",
}
# The same thirteen circles for a question written in English. The roster is
# 79% Western and its article links are English Wikipedia, so the nouls are
# asked in English and the region has to be readable to the model that answers.
CIRCLE_EN = {
    "cn": "China", "jp": "Japan", "kr": "Korea", "sea": "Southeast Asia",
    "in": "India", "isl": "the Islamic world and Persia", "grc": "Classical Greece",
    "rom": "Rome and the Mediterranean", "eu": "Western Europe",
    "ee": "Eastern Europe and Russia", "na": "North America",
    "latam": "Latin America", "afr": "Africa",
}

# An article link is a host plus a title; nothing else is ever concatenated onto
# it. English Wikipedia covers nearly everyone -- but ten people in this roster
# have no English article at all and do have a Chinese one, and linking those to
# nothing would be worse than linking them to the wiki that has them.
WIKI_BASE = "https://en.wikipedia.org/wiki/"
ZH_WIKI_BASE = "https://zh.wikipedia.org/wiki/"
JA_WIKI_BASE = "https://ja.wikipedia.org/wiki/"

# slug -> which wiki its article is on ("en" / "zh" / "ja"). Filled in by
# `_build`, defaulting to English, so a new row in ENGLISH does not have to
# remember to say so.
WIKI_HOST = {}

# `en` is the English name shown beside the Chinese one. `wiki` is the exact
# en.wikipedia article title, which is NOT the same string whenever the plain
# name is a disambiguation page (Xunzi lives at "Xunzi (philosopher)", Diogenes
# at "Diogenes"). Either may be None for the handful of thinkers we could not
# verify -- then the name renders as text and carries no link.
Thinker = namedtuple("Thinker", "id en zh wiki born died circle lat lon frame")


def _build():
    out = []
    for slug, zh, born, died, circle, lat, lon, frame in RAW:
        en, wiki = ENGLISH.get(slug, (None, None))
        if wiki:
            WIKI_HOST[slug] = "en"
        elif slug in ZH_WIKI or slug in JA_WIKI:
            wiki = ZH_WIKI.get(slug) or JA_WIKI[slug]
            # `en` stays None on purpose: these people have no English name to
            # show, and inventing a romanisation would be a worse label than
            # the Chinese one the reader already has.
            WIKI_HOST[slug] = "zh" if slug in ZH_WIKI else "ja"
        out.append(Thinker(slug, en, zh, wiki, born, died, circle, lat, lon, frame))
    return tuple(out)


def wiki_url(t):
    """This thinker's Wikipedia URL, or None.

    Built here rather than in the browser so there is exactly one place that
    knows how a title becomes a URL -- and so an unverified thinker stays
    unlinked instead of turning into a guessed, wrong link.
    """
    if not t.wiki:
        return None
    host = WIKI_HOST.get(t.id)
    base = {"zh": ZH_WIKI_BASE, "ja": JA_WIKI_BASE}.get(host, WIKI_BASE)
    return base + urllib.parse.quote(t.wiki.replace(" ", "_"))


ROSTER = _build()


def pinyin_of(t):
    """What the anchor picker searches this person by, besides their names.

    Space-separated pinyin forms -- the primary reading, the initials, and the
    alternate readings of polyphonic characters -- generated by `gen_pinyin.py`
    and shipped to the page as data. Empty for the 68 people whose roster name
    is already Latin script (Basava, FM-2030, Hawa Abdi): there is nothing to
    romanise, and the name itself is what the picker matches on.

    This exists because of how the picker is used, not how the roster is
    written. On a Chinese keyboard the reader types letters, so "kangde" has to
    find 康德 and "jiamiu" has to find 加缪 -- pypinyin reads 缪 as mou, and a
    reader who knows the name types miu.
    """
    return PINYIN_FORMS.get(t.id, "")


def end_year(t):
    """The year this thinker stopped changing the argument.

    Living thinkers get the current year: their position is still live, so the
    timeline should reach them. Ordering and the map sweep both use this, NOT
    the birth year -- ordering by birth put every contemporary figure a
    generation too early and made the last frame end in the 1980s.
    """
    return t.died if t.died is not None else CURRENT_YEAR


def order_key(t):
    """Timeline order. Birth breaks ties so that everyone still alive -- who
    all share the current year as their end year -- is spread by generation
    instead of collapsing into one arbitrary alphabetical heap."""
    return (end_year(t), t.born, CIRCLE_ORDER.index(t.circle), t.id)


def years_label(t):
    """Birth-death as shown to the model: 551B-479B, 1963-, 1922-2024."""
    born = "%dB" % -t.born if t.born < 0 else str(t.born)
    if t.died is None:
        return "%s–" % born
    died = "%dB" % -t.died if t.died < 0 else str(t.died)
    return "%s–%s" % (born, died)


def era_of(year):
    """Human-readable era label for a year."""
    if year < 0:
        return "公元前 %d 年" % -year
    return "公元 %d 年" % year


def span_label(batch):
    """The frame's span on the END-year axis.

    A frame made only of living thinkers has no span at all -- every one of
    them ends at this year -- so it is labelled by generation instead. Without
    this the newest frame read "2026 - 至今", which says nothing.
    """
    lo, hi = end_year(batch[0]), end_year(batch[-1])
    if lo >= CURRENT_YEAR:
        return "在世 · 生于 %d–%d" % (min(t.born for t in batch),
                                      max(t.born for t in batch))
    if lo < 0:
        return "%s – %s" % (era_of(lo), era_of(hi))
    if hi >= CURRENT_YEAR:
        return "%d – 至今" % lo
    return "%d – %d" % (lo, hi)


def circles_of(batch):
    return sorted({t.circle for t in batch}, key=CIRCLE_ORDER.index)


def _dominant_circle(pool, size):
    """One circle that could fill an entire batch on its own, right now.

    Only fires when the earliest `size` thinkers are tight in time AND one
    circle owns most of them AND that circle has `size` members available.
    This is the rule that turns the modern frames into circle-scoped frames.
    """
    head = pool[:size]
    if len(head) < size:
        return None
    if end_year(head[-1]) - end_year(head[0]) > DOMINANT_SPAN:
        return None
    circle, n = Counter(t.circle for t in head).most_common(1)[0]
    if n < size * DOMINANT_SHARE:
        return None
    avail = [t for t in pool if t.circle == circle]
    if len(avail) < size:
        return None
    return circle


def window_starts(n, size):
    """Start positions for windows of `size` that cover [0, n) exactly.

    When n is a multiple of `size` these are a plain partition (0, size, 2*size,
    ...). Otherwise the last start is pinned to `n - size` and the earlier ones
    are spread evenly, so the windows overlap just enough to reach the newest
    thinker without leaving a gap. Nobody is dropped either way.
    """
    if n < size:
        return []
    frames = -(-n // size)          # ceil
    if frames <= 1:
        return [0]
    return [round(i * (n - size) / (frames - 1)) for i in range(frames)]


def compose_batches(roster=None, size=SIZE):
    """Cut the roster into frames of exactly `size`.

    Returns (batches, reserve). `reserve` is only non-empty when the whole
    roster is smaller than one frame; otherwise every thinker lands in at least
    one frame.
    """
    ordered = sorted(roster if roster is not None else ROSTER, key=order_key)
    n = len(ordered)
    starts = window_starts(n, size)
    if not starts:
        return [], ordered
    batches = []
    for start in starts:
        window = ordered[start:start + size]
        circle = _dominant_circle(window, size)
        if circle is None:
            batches.append(window)
        else:
            # Take that circle's members anchored at this window's position in
            # the roster, not from the front. Taking [:size] of the circle made
            # every sliding window emit the SAME 255 people, so the back half of
            # the tradition was never judged.
            members = [t for t in ordered if t.circle == circle]
            local = min(max(start, 0), len(members) - size)
            batches.append(members[local:local + size])
    return batches, []


def frame_title(batch):
    """What this frame is about, in one line. This is the 'meaning' of the batch.

    Circles are listed largest first. Listing them in CIRCLE_ORDER instead
    made every frame look Chinese, because China happens to come first in the
    ordering regardless of whether it holds 2 members or 90.
    """
    n = Counter(t.circle for t in batch)
    order = [c for c, _ in n.most_common()]
    if len(order) == 1:
        where = CIRCLE_ZH[order[0]]
    else:
        where = " · ".join(CIRCLE_ZH[c] for c in order[:4])
        if len(order) > 4:
            where += " 等 %d 个文化圈" % len(order)
    return "%s / %s / %d 位" % (span_label(batch), where, len(batch))


# The Choice question that used to be built here -- `question_for()` and its
# `criteria_for()` -- is gone (2026-09-26). It sent one 255-option Choice per
# frame, every option labelled `名字（生卒年，地区）：<那一行框架>`, and it was the
# only thing feeding `/api/thinkers/run` and `/api/thinkers/stream`. The page
# stopped calling both when the ruler moved to nouls -- a Choice asks "which
# ONE of these 255 is most apt", so it returned probabilities for 3-6 options
# and exactly zero for the other ~250, and a zero cannot be rescaled into a
# position. With no caller left, the frame text was reaching a model only
# through a dead endpoint, so the layer went. Nothing above is orphaned:
# `frame_title()`, `span_label()`, `circles_of()` and `plan()` are still what
# `/api/thinkers/plan` draws the page's timeline from.


# A noul score is a plain judgement, not a distribution, so it does not compete
# with the rest of the batch. Measured on the real API: the same 20 people scored
# against two completely different 255-person contexts agreed to r=0.990, max
# |delta| 0.030. That independence is the whole reason these scores can be added
# up across the eleven requests. A Choice probability cannot be: it is a share of
# one batch, which is what the deleted layer kept running into.
STANCE_YES = 0.5      # at or above this, the person is read as "support it"

# `STANCE_N` -- the cap on how many of a frame's lit options got asked -- went
# with the Choice layer, because it bounded a follow-up to a distribution that no
# longer exists. The ruler asks all 255 people in a chunk, every time.
# Every person is asked TWICE, once each way round, and the pair is centred.
# A single noul bends towards whichever option is called `true`: on 24 frameworks
# the one-way read said 92% "do it" while the same frameworks read both ways say
# 63%. The tilt is real and not noise -- same text, same thinkers, same run,
# |A - A'| = 0.012 (asking twice) against |A - B| = 0.258 (asking the other way).
# Centring costs one more small request and removes the bend instead of
# correcting for it with a constant fitted on one question.
STANCE_PREFIX = "s_"
STANCE_PREFIX_SWAP = "s2_"


# What `true` and `false` mean, in the English the nouls are asked in. Named
# constants because the pair has to mirror exactly: the swapped question puts
# the SAME two strings in the other order, and a typo in one of them would turn
# the centring step into arithmetic on two different questions.
STANCE_FOR = "support it"
STANCE_AGAINST = "not support it"


def _who(t):
    """One line of identification, and nothing else: 中文名 英文名 (years, region).

    Both names on purpose. The Chinese name is what the page shows; the English
    one is what the model can look up, and for people like Kaṇāda or Kumārila
    Bhaṭṭa the Chinese name alone is a weaker handle than the one their Wikipedia
    article is filed under. Twelve people have no English name at all and are
    named once rather than with an empty slot.

    NO framework sentence here, and that is a measurement rather than a
    preference -- see docs/design.md 「只有身份，没有观点」. The
    short version: the old wording repeated our one-line summary of each
    person's thought and asked what THAT pointed at, which made the map
    substantially a picture of the roster's own summaries rather than of its minds.
    Removing it moves the average person 0.0555 (9x the 0.0061 noise floor)
    and turned 627 of the then-2613 people across the 0.5 line.
    """
    names = t.zh if not t.en else "%s %s" % (t.zh, t.en)
    return "%s (%s, %s)" % (names, years_label(t), CIRCLE_EN[t.circle])


def _stance_question(t, swapped):
    # The two options are always spelled out, in the order `criteria` declares.
    # `swapped` does not reword the question, it reorders the two labels and
    # swaps which one `true` names -- so a model that just likes `true` is not
    # automatically voting "support it", and the average of the pair cancels
    # the tilt instead of carrying it.
    head = "%s. On the user's decision, would he say: " % _who(t)
    if swapped:
        return {
            "type": "noul",
            "instructions": head + "%s, or %s?" % (STANCE_AGAINST, STANCE_FOR),
            "criteria": {"true": STANCE_AGAINST, "false": STANCE_FOR},
        }
    return {
        "type": "noul",
        "instructions": head + "%s, or %s?" % (STANCE_FOR, STANCE_AGAINST),
        "criteria": {"true": STANCE_FOR, "false": STANCE_AGAINST},
    }


def stance_questions(picked):
    """Two `noul`s per person asked: would you read this one as for it or against.

    Built here rather than in upstreams.py because the shape of the question is
    product logic; upstreams.py only sends it.

    What is repeated is the IDENTIFICATION -- both names, the years, the circle
    -- and nothing about what the person thought. The one-line "framework"
    summary that used to sit here is gone: it was not an aid to recall, it was
    the thing being measured. See `_who`.
    """
    out = {}
    for t in picked:
        out[STANCE_PREFIX + t.id] = _stance_question(t, False)
        out[STANCE_PREFIX_SWAP + t.id] = _stance_question(t, True)
    return out


def scale_state(question, english=""):
    """The `state` one whole scale run is judged over.

    Every noul asks "would he say: support it, or not support it?" and none of
    them says what "it" is. The decision lives here, once per request -- which is
    what keeps the run at eleven requests instead of the decision repeated
    inside all 510 questions of each one.

    The reader's own words ride along verbatim: the restatement is what the page
    displays and what the scale measures, but the thing the reader typed is the
    only record of what they actually asked, and a model that never saw it would
    be judging our rewording on our word alone.

    `english` is the restatement in the language the questions are asked in --
    the same X, from the same call that produced the headline (see
    `upstreams.frame_support`). It is optional. Without it the state is what the
    product shipped before: the reader's words, and nothing pretending to be a
    translation of them.
    """
    state = {"what_the_user_typed": question}
    english = (english or "").strip()
    if english and english != question.strip():
        state["the_same_decision_in_english"] = english
        state["note"] = (
            '"support it" and "not support it" below mean supporting or not '
            "supporting that decision."
        )
    return state


# How many thinkers go into one noul request. Two nouls each (both directions),
# so this is 510 questions in one call -- measured on the real API: 4.2s and
# 510/510 returned. The whole roster is therefore 11 calls, ~570k
# input tokens, ~13s at four in flight. Scale is not sold by the request.
SCALE_PER_REQUEST = 255

# The twelve rungs. Every chunk carries all of them, so the same people are
# measured inside every company the roster can put them in -- which is the only
# way to SHOW that one number means one thing across eleven requests instead of
# asserting it. They are famous on purpose: a rung nobody can read is not a rung.
#
# Measured for this design (see docs/design.md 「尺子上那 12 个人」): the
# same 12 asked inside two batches whose other 243 members come from opposite
# ends of history agreed to r=0.995, max |delta| 0.050; adding them to a batch
# moved the other 243 by mean 0.008, max 0.030. So they calibrate without
# disturbing.
ANCHOR_ZH = ("老子", "释迦牟尼", "尼采", "马克思", "柏拉图", "孔子",
             "苏格拉底", "达尔文", "刘慈欣", "康德", "亚里士多德", "马斯克")


def default_anchors():
    """The rungs the product ships with, resolved against the roster."""
    by_zh = {}
    for t in ROSTER:
        by_zh.setdefault(t.zh, t)
    missing = [z for z in ANCHOR_ZH if z not in by_zh]
    if missing:
        raise ValueError("标尺上的人不在名录里: %s" % ", ".join(missing))
    return tuple(by_zh[z] for z in ANCHOR_ZH)


ANCHORS = default_anchors()


def anchors_from_ids(ids):
    """Rungs chosen by the reader, resolved by roster id.

    The reader may replace the twelve; the roster is what they choose FROM,
    because a rung is a person whose framework line we already have. Someone who
    is not in the roster has no framework, so there is nothing to ask -- that is
    the whole reason this resolves ids instead of accepting free text.

    Order is the caller's, duplicates are dropped (a person asked twice inside
    one request could disagree with themselves where nobody could explain why),
    and an unknown id is an error rather than a silently smaller set: quietly
    measuring eleven rungs when twelve were asked for is how a calibration ends
    up describing something other than what the page says it did.
    """
    by_id = {}
    for t in ROSTER:
        by_id.setdefault(t.id, t)
    out, seen, missing = [], set(), []
    for i in ids:
        t = by_id.get(i)
        if t is None:
            missing.append(i)
        elif t.id not in seen:
            seen.add(t.id)
            out.append(t)
    if missing:
        raise ValueError("名录里没有这些人: %s" % ", ".join(missing))
    if not out:
        raise ValueError("至少要留一个标尺人")
    return tuple(out)


def scale_chunks(roster=None, size=SCALE_PER_REQUEST, anchors=True):
    """The whole roster in slices of `size`, every slice carrying the anchors.

    `anchors` is True for the shipped twelve, False for none, or an iterable of
    Thinker to use those instead -- the reader is allowed to put their own
    people on the ruler, and a rung they chose is exactly as measurable as one
    we chose.

    Two things this has to do at once. Everyone is measured -- no subsampling,
    the whole roster. And every request has to be checkable against every other,
    which is what the shared rungs are for: with ANCHORS in all of them, the
    agreement between requests is a number we can print rather than a promise.

    Sorted by end year here rather than trusting the caller's order. ROSTER is
    NOT in timeline order -- it is roughly chronological with 1,135 inversions,
    and its last entry is a man who died in 2005 -- so slicing it as given made
    every chunk a random sample and ended the last one two decades short of the
    present. A chunk is supposed to be a slice of history; this is what makes
    that true. The last chunk is clamped to end at the newest thinker and
    therefore OVERLAPS the one before it, exactly like the frames do: a short
    final chunk would waste the cap, and dropping the tail would end the ruler
    decades before the present. The overlap is a free second measurement.
    """
    roster = ROSTER if roster is None else roster
    roster = sorted(roster, key=order_key)
    if anchors is True:
        rungs = list(ANCHORS)
    elif not anchors:
        rungs = []
    else:
        rungs = list(anchors)
    body = size - len(rungs)
    if body < 1:
        raise ValueError("每批装不下 %d 个标尺人" % len(rungs))
    # A rung is asked in the rung position only. Leaving the person in their own
    # slab as well would ask them twice inside ONE request and let the two
    # answers disagree where nobody can see why.
    rung_ids = set(t.id for t in rungs)
    rest = [t for t in roster if t.id not in rung_ids]
    n = len(rest)
    out, start = [], 0
    while start < n:
        stop = min(start + body, n)
        slab = rest[max(stop - body, 0):stop]
        out.append(tuple(slab) + tuple(rungs))
        start = stop
    return out


def stance_scores(picked, answers):
    """{thinker id: 0..1} centred on the two directions.

    `answers` is the raw {question key: score} from the API. Centring is
    (forward - backward + 1) / 2, which is 0.5 exactly when the two directions
    agree, so a framework nobody can read either way lands on the fence instead
    of being pushed to one side by the tilt.

    A thinker missing EITHER direction is dropped: with one direction there is
    nothing to centre, and using the raw score would put the tilt straight back.
    """
    out = {}
    for t in picked:
        fwd = answers.get(STANCE_PREFIX + t.id)
        bwd = answers.get(STANCE_PREFIX_SWAP + t.id)
        if fwd is None or bwd is None:
            continue
        out[t.id] = (fwd - bwd + 1.0) / 2.0
    return out


def stance_count(picked, scores):
    """(yes, answered) over the shortlist, on centred scores. Frame-comparable.

    `answered` is the second value on purpose, not the number against. Only
    thinkers that actually came back is the number the UI has to divide by --
    returning `against` here once made the page print "6 of 2", because the
    caller bound this slot to the denominator. `against` is answered - yes.

    A missing score shrinks `answered` rather than being counted as a "no":
    a call that did not come back must not read as a verdict.
    """
    answered = [t for t in picked if t.id in scores]
    yes = sum(1 for t in answered if scores[t.id] >= STANCE_YES)
    return yes, len(answered)


def plan(roster=None, size=SIZE):
    """Summary of the whole animation: one row per frame, for the UI."""
    batches, reserve = compose_batches(roster, size)
    rows = []
    for i, b in enumerate(batches):
        rows.append({
            "i": i,
            "title": frame_title(b),
            "span": span_label(b),
            "year_lo": end_year(b[0]),
            "year_hi": end_year(b[-1]),
            "span_years": end_year(b[-1]) - end_year(b[0]),
            "circles": circles_of(b),
            "n": len(b),
        })
    return rows, [t.id for t in reserve]
