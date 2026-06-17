#!/usr/bin/env python3
"""Publish the REAL Grade-3 Reading course to Alpha Read by JOINING a structure manifest
with a QTI content package.

This is the course-shaped sibling of `push_to_timeback.py`. Where that script groups a flat QTI
package into one-article-per-passage under a single Unit 1, THIS script honours an AUTHORITATIVE
structure manifest: Course -> Unit per expedition (10) -> Lesson-component per lesson (47) ->
ONE article per manifest item, in `seq` order, parented to its lesson component.

INPUTS (all real, already on disk):
  --manifest  /tmp/g3course/course_manifest.json   the authoritative tree:
      {course, counts, expeditions:[{expedition_id, expedition_index, unit (title), band, lexile,
       lessons:[{lesson_id, lesson_index, title, items:[{seq, item_id, type, lesson_phase, scored}]}]}], gaps}
  --bundle    /tmp/g3course/course_bundle.jsonl     704 JSON lines keyed by item_id; type=="article"
      rows are passages (carry `content`, `title`, `passage_id`).
  --qti       /tmp/mqti/qti_package                 items/<item_id>.xml (576 raw QTI 3.0 question
      items, each with its OWN <qti-assessment-stimulus-ref>) + stimuli/*.xml + imsmanifest.xml.

JOIN MODEL (verified on these exact files):
  * 704 manifest item refs = 127 `article` passages + 577 question-type refs.
  * 576 of those question refs have a QTI file in items/. EACH carries its OWN unique stimulus-ref
    that resolves to stimuli/<id>.xml — so the model is ONE ARTICLE PER ITEM (passages are NOT shared
    across questions).
  * The 128 manifest ids NOT in items/ are 127 articles + 1 stray `match` item whose bundle row has
    NO content and NO QTI XML (best_effort, malformed). That stray question has no source to publish,
    so it is LOGGED and SKIPPED (never silently dropped). The 127 articles become passage-only
    reading articles built from the bundle `content`.

RENDER FACTS (per RULES.md — and the three formats the reader can't draw are now TRANSFORMED):
  * mcq + sequence(drag-order)  -> render (single-select choice / order), verbatim from Mayank. [R1]
  * ebsr                        -> auto-DECOMPOSED into 2 linked single-choice items -> render. [R4]
  * hot-text / match / msq      -> TRANSFORMED at build time into single-select `choice` QTI built
      FRESH from the v2 bundle row (NOT Mayank's XML), so every question RENDERS + SCORES. Stan's
      transform-now call (parity later). Keys + options come from the bundle, never invented:
        - hot-text -> ONE choice (options = selectable token texts; correct = the `answer` token).
        - match    -> ONE article with N single-select sub-items (one per row; options = categories).
        - msq      -> ONE single-best choice (LOSSY — keeps options, correct = first `answer`; logged).
  * article                     -> passage-only reading article (stimulus + a passage test).

SAFETY:
  * --dry-run builds the FULL plan in memory and PRINTS it, making ZERO network calls (no mint/post/
    get — they are gated behind `if not dry_run`, and in dry-run mode they are monkeypatched to RAISE).
  * --publish flips publishStatus=published and prints a loud banner before any POST.
  * Reuses push_to_timeback.py for the live path (mint_token/post/get_json, OneRoster/QTI bases,
    the EBSR split, and the article/resource/component-resource JSON shapes).

DO NOT publish live, commit, or push without explicit sign-off.
"""
import argparse, glob, json, os, re, sys
from collections import OrderedDict, Counter
from xml.sax.saxutils import escape as _xml_escape

# Reuse push_to_timeback.py's helpers for the live path (mint/post/get + EBSR split + bases).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
import push_to_timeback as P            # mint_token, post, get_json, QTI, OR, _ebsr_split

try:
    import arpack                       # full_sanitize via arpack._sani; from_qti_xml for format detect
except Exception:
    arpack = None

import render_transforms as RT          # build-time hot-text/match/msq -> single-select choice QTI


# ── question-item families (manifest `type`) and their render dispositions (RULES.md) ───────────
QUESTION_TYPES = {"mcq", "msq", "ebsr", "hot-text", "match", "sequence"}
RENDER_OK   = {"mcq", "sequence"}        # single-select choice / drag-order            [R1]
# hot-text/match/msq are no longer pushed verbatim: they are TRANSFORMED at build time (below) into
# single-select choice QTI built FRESH from the v2 bundle row, so every question renders + scores.
# (Previously: msq rendered single-select-only [R2]; hot-text/match rendered BLANK [R3].)
RENDER_TRANSFORM = {"hot-text", "match", "msq"}
# ebsr is handled specially: decomposes into 2 single-choice items that render.          [R4]


def _passage_html(content):
    """Turn a bundle article's plain-text `content` into a sanitized XHTML stimulus body.

    The bundle `content` is plain text with blank-line paragraph breaks (no markup). We split on
    blank lines, <p>-wrap each paragraph, then run arpack's full_sanitize (the vendored Timeback
    XHTML sanitizer) so it leaves arpack as valid XHTML — the same gate the packager uses. If arpack
    isn't importable we fall back to a minimal escape + <p>-wrap (still well-formed XHTML)."""
    text = (content or "").strip()
    if not text:
        return "<p></p>"
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [text]
    if arpack is not None and getattr(arpack, "_full_sanitize", None):
        # sanitize each paragraph's inner text, then wrap. full_sanitize escapes bare &/< and
        # self-closes voids; wrapping after keeps the <p> structure intact.
        body = "".join("<p>%s</p>" % arpack._sani(p) for p in paras)
        return body
    # minimal fallback: escape, single-line-break -> <br/>, <p>-wrap.
    out = []
    for p in paras:
        out.append("<p>%s</p>" % _xml_escape(p).replace("\n", "<br/>"))
    return "".join(out)


def _passage_stimulus_xml(sid, title, html):
    """Build a QTI 3.0 <qti-assessment-stimulus> wrapping the passage HTML (for the live XML POST
    path; the dry-run only needs the content string, which is what we pass to /stimuli)."""
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<qti-assessment-stimulus xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0" '
        f'identifier="{_xml_escape(sid)}" title="{_xml_escape(title)}">\n'
        f'  <qti-stimulus-body>{html}</qti-stimulus-body>\n'
        '</qti-assessment-stimulus>\n'
    )


def _read_xml(path):
    return open(path, encoding="utf-8-sig").read()


def _stim_ref_id(raw):
    """The stimulus-ref identifier carried inside a question item's XML (resolves to stimuli/<id>.xml)."""
    m = re.search(r'qti-assessment-stimulus-ref[^>]*identifier="([^"]+)"', raw)
    return m.group(1) if m else None


def _stim_title(raw, sid):
    m = re.search(r'title="([^"]+)"', raw)
    return m.group(1) if m else sid


def _stim_body(raw):
    m = re.search(r"<qti-stimulus-body[^>]*>(.*)</qti-stimulus-body>", raw, re.S)
    return m.group(1).strip() if m else "<p></p>"


def build_plan(a):
    """PURE, in-memory, network-free. Joins the manifest tree with the QTI package + bundle and
    returns the full publish plan: course shape, units, lessons, ordered articles, stimuli/items to
    POST, plus render-summary tallies and a list of skipped (no-source) items. Nothing here touches
    the network."""
    manifest = json.load(open(a.manifest, encoding="utf-8"))

    # bundle: item_id -> row (passages carry `content`/`title`).
    bundle = {}
    with open(a.bundle, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            if o.get("item_id"):
                bundle[o["item_id"]] = o

    items_dir = os.path.join(a.qti, "items")
    stimuli_dir = os.path.join(a.qti, "stimuli")
    have_qti = set(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(items_dir, "*.xml")))

    P_ = a.prefix
    # id base: the prefix's digits (like push_to_timeback derives `base`), 10 wide, then a global
    # zero-padded running counter -> clean unique ids: article_<base><NNNN>, vendorResourceId = bare N.
    base = (re.sub(r"\D", "", P_) or "90000001")[-10:]
    PUBLISH_STATUS = "published" if a.publish else "testing"

    # ── course shape: mirror push_to_timeback.py's alpha_read course ──────────────────────────
    course_body = {
        "sourcedId": P_, "status": "active", "title": a.title, "courseCode": P_,
        "grades": ["3"], "subjects": ["Reading"], "org": {"sourcedId": a.org},
        "primaryApp": "alpha_read",
        "metadata": {"primaryApp": "alpha_read", "isAlphaRead": True,
                     "publishStatus": PUBLISH_STATUS, "timebackVisible": True},
    }

    # stimuli + items to POST (live path). Built as we walk articles so we never push an orphan.
    stim_plan = OrderedDict()   # sid -> (title, content)  (deduped: a sid pushed once)
    item_plan = OrderedDict()   # post_id -> post_xml      (deduped)

    units = []                  # [{sourcedId, title, sortOrder, expedition_index}]
    lessons = []                # [{sourcedId, unit_sourcedId, title, sortOrder}]
    articles = []               # ordered: {N, art_id, vendor, title, lesson_sourcedId, item_refs[],
                                #           kind, render, src_item_id, manifest_type}
    skipped = []                # [(item_id, type, reason)]
    counter = 0                 # global running article counter

    render = Counter()          # tally for the RENDER SUMMARY
    type_counts = Counter()     # manifest type -> article count

    for exp in manifest["expeditions"]:
        ei = exp["expedition_index"]
        u_sid = f"{P_}-u{ei}"
        units.append({"sourcedId": u_sid, "title": exp.get("unit") or f"Unit {ei + 1}",
                      "sortOrder": ei + 1, "expedition_index": ei,
                      "band": exp.get("band"), "lexile": exp.get("lexile")})
        for lesson in exp["lessons"]:
            li = lesson["lesson_index"]
            l_sid = f"{P_}-u{ei}-l{li}"
            lessons.append({"sourcedId": l_sid, "unit_sourcedId": u_sid,
                            "title": lesson.get("title") or f"Lesson {li + 1}",
                            "sortOrder": li + 1, "unit_index": ei})
            for it in sorted(lesson["items"], key=lambda x: x.get("seq", 0)):
                iid = it["item_id"]
                itype = it.get("type")

                # ONE QUESTION PER ARTICLE: a manifest item may now expand into MULTIPLE
                # single-question articles (EBSR -> 2 parts; match -> N rows). The article id
                # counter is therefore allocated PER EMITTED ARTICLE (not once per manifest item),
                # so EBSR/match expansions each get their own running article_<N>. `emit()` is the
                # single place a new id is minted and an article appended.
                def emit(title, refs, kind, rtag, stimulus_id):
                    nonlocal counter
                    counter += 1
                    N = base + "%04d" % counter    # global, zero-padded -> unique + clean
                    art_id = "article_" + N
                    articles.append({
                        "N": N, "art_id": art_id, "vendor": N, "title": title,
                        "lesson_sourcedId": l_sid, "stimulus_id": stimulus_id, "item_refs": refs,
                        "kind": kind, "render": rtag, "src_item_id": iid,
                        "manifest_type": itype})
                    return art_id

                if itype == "article":
                    # passage-only reading article: stimulus from bundle content, test references the
                    # stimulus but has NO question item. (Allocate the id first so the stimulus id
                    # matches the article's N.)
                    counter += 1
                    N = base + "%04d" % counter
                    art_id = "article_" + N
                    row = bundle.get(iid) or {}
                    title = row.get("title") or lesson.get("title") or a.title
                    sid = f"stim_passage_{N}"
                    html = _passage_html(row.get("content"))
                    stim_plan[sid] = (title, html)
                    articles.append({
                        "N": N, "art_id": art_id, "vendor": N, "title": title,
                        "lesson_sourcedId": l_sid, "stimulus_id": sid, "item_refs": [],
                        "kind": "passage", "render": "passage", "src_item_id": iid,
                        "manifest_type": itype})
                    render["passage"] += 1
                    type_counts["article"] += 1
                    continue

                # question-type item: needs a QTI file in items/.
                if iid not in have_qti:
                    skipped.append((iid, itype, "no QTI item file in items/ (no source to publish)"))
                    continue

                raw = _read_xml(os.path.join(items_dir, iid + ".xml"))
                sref = _stim_ref_id(raw)
                title = (re.search(r'title="([^"]+)"', raw) or [None, iid])[1]

                # resolve + stage this item's OWN stimulus (one stimulus per item per the join facts).
                # We resolve sref BEFORE any transform so the passage stays attached to the rebuilt item.
                if sref:
                    spath = os.path.join(stimuli_dir, sref + ".xml")
                    if os.path.exists(spath) and sref not in stim_plan:
                        sraw = _read_xml(spath)
                        stim_plan[sref] = (_stim_title(sraw, sref), _stim_body(sraw))

                # NATIVE mode (--native): upload EXACTLY as authored — no transform, no EBSR
                # decompose. Composite EBSR, hot-text, match, msq all push verbatim as ONE article.
                # The complete, faithful course; some formats won't render in the reading app — that
                # is the honest native state (the "as-is" clone).
                if getattr(a, "native", False):
                    item_plan[iid] = raw
                    render["native_asis"] = render.get("native_asis", 0) + 1
                    emit(title, [iid], "native-as-is", "native", sref)
                    type_counts[itype] = type_counts.get(itype, 0) + 1
                    continue

                # EBSR: decompose the composite into two linked single-select items (reuse the
                # existing, tested split in push_to_timeback.py). Each part becomes its OWN
                # single-question article (1 item-ref), sharing the EBSR's stimulus, kept adjacent
                # (Part A then Part B) at this item's seq position. (Was: 1 article, 2 refs — the
                # reader only served the first question.)
                ebsr = P._ebsr_split(raw) if itype == "ebsr" else None
                if ebsr:
                    for k, (pid, _ptitle, pxml) in enumerate(ebsr):
                        item_plan[pid] = pxml
                        ptitle = "%s — Part %s" % (title, chr(65 + k))
                        emit(ptitle, [pid], "ebsr-decomposed", "render", sref)
                    render["render_ebsr"] += 1
                    render["ebsr_articles"] += len(ebsr)
                    type_counts["ebsr"] += len(ebsr)
                    continue

                # TRANSFORM the three formats the reading renderer can't draw (hot-text/match/msq):
                # IGNORE Mayank's items/<id>.xml and build FRESH single-select choice QTI from the
                # v2 bundle row, re-attaching this item's resolved stimulus-ref. Keys + options come
                # from the bundle, never invented. (See render_transforms.py.)
                if itype in RENDER_TRANSFORM:
                    row = bundle.get(iid) or {}

                    tid = iid + "-rt"   # namespace transformed items so they don't clash with the native clone
                    if itype == "hot-text":
                        res = RT.transform_hot_text(tid, row, sref)
                        if res is None:
                            skipped.append((iid, itype,
                                            "hot-text has no usable selectable tokens / answer"))
                            continue
                        xml, lossy = res
                        item_plan[tid] = xml
                        if lossy:
                            render["hot_text_multi"] += 1     # multi-token answer -> single-best
                        render["render_hot_text"] += 1
                        emit(title, [tid], "question-transformed", "transformed-hot-text", sref)
                        type_counts[itype] += 1              # 1 article per hot-text

                    elif itype == "msq":
                        res = RT.transform_msq(tid, row, sref)
                        if res is None:
                            skipped.append((iid, itype, "msq has no usable options / answer"))
                            continue
                        xml, n_correct = res
                        item_plan[tid] = xml
                        render["render_msq"] += 1
                        render["msq_lossy"] += 1              # EVERY msq is lossy (multi -> single)
                        render["msq_answers_dropped"] += max(0, n_correct - 1)
                        emit(title, [tid], "question-transformed", "transformed-msq-lossy", sref)
                        type_counts[itype] += 1              # 1 article per msq

                    else:  # match -> N single-question articles, one per row/sub-item
                        subs = RT.transform_match(iid, row, sref)
                        if subs is None:
                            skipped.append((iid, itype,
                                            "match has no categories/items (malformed best_effort)"))
                            continue
                        total = len(subs)
                        for k, (sub_id, sub_xml) in enumerate(subs, 1):
                            item_plan[sub_id] = sub_xml
                            mtitle = "%s — Match %d/%d" % (title, k, total)
                            emit(mtitle, [sub_id], "question-transformed",
                                 "transformed-match", sref)
                        render["render_match"] += 1          # source match items transformed
                        render["match_articles"] += total    # emitted single-question articles
                        render["match_subitems"] += total
                        type_counts[itype] += total          # N articles per match (one per row)
                    continue

                # every other question type (mcq, sequence): POST the raw QTI verbatim, test refs it.
                item_plan[iid] = raw
                if itype in RENDER_OK:
                    render["render_ok"] += 1
                    rtag = "render"
                else:                               # unknown/forward-compat type: push verbatim, flag
                    render["render_unknown"] += 1
                    rtag = "unknown"
                emit(title, [iid], "question", rtag, sref)
                type_counts[itype] += 1

    # ── ONE-QUESTION-PER-ARTICLE INVARIANT ───────────────────────────────────────────────────────
    # The reading renderer serves only the FIRST question of a multi-question article. So every
    # emitted article's QTI test must reference AT MOST ONE item (passage-only articles reference
    # zero). Assert it here so the build fails loudly if a future change reintroduces a multi-ref
    # article. `max_item_refs` is surfaced to the dry-run report.
    max_item_refs = max((len(art["item_refs"]) for art in articles), default=0)
    offenders = [art["art_id"] for art in articles if len(art["item_refs"]) > 1]
    assert not offenders, (
        "one-question-per-article invariant violated: %d article(s) carry >1 item-ref: %s"
        % (len(offenders), offenders[:10]))

    return {
        "manifest": manifest, "course": course_body, "publish_status": PUBLISH_STATUS,
        "units": units, "lessons": lessons, "articles": articles,
        "stim_plan": stim_plan, "item_plan": item_plan,
        "skipped": skipped, "render": render, "type_counts": type_counts, "base": base,
        "max_item_refs": max_item_refs,
    }


def print_dry_run(a, plan):
    m = plan["manifest"]
    arts = plan["articles"]
    render = plan["render"]
    print("=== DRY RUN (no network) ===")
    if a.publish:
        print("=== PUBLISH (real course) === id=%s org=%s publishStatus=published — would POST live ==="
              % (a.prefix, a.org))
    print("course: %s | org: %s | publishStatus: %s | primaryApp: alpha_read"
          % (a.prefix, a.org, plan["publish_status"]))
    print("structure: %d expedition(s) -> %d lesson(s) -> %d article(s)"
          % (len(plan["units"]), len(plan["lessons"]), len(arts)))
    print("would POST: %d stimuli | %d question item(s) (mcq/sequence verbatim + EBSR parts + "
          "hot-text/match/msq TRANSFORMED to single-select choice)"
          % (len(plan["stim_plan"]), len(plan["item_plan"])))
    r = plan["render"]
    print("transform log: hot-text=%d (multi-token->single-best %d) | match=%d items -> %d articles | "
          "msq=%d LOSSY (multi->single-best; %d answers dropped) | ebsr=%d items -> %d articles | "
          "passages=%d | skipped-no-source=%d"
          % (r["render_hot_text"], r["hot_text_multi"], r["render_match"], r["match_articles"],
             r["render_msq"], r["msq_answers_dropped"], r["render_ebsr"], r["ebsr_articles"],
             r["passage"], len(plan["skipped"])))
    print("ONE QUESTION PER ARTICLE: max item-refs per article: %d %s"
          % (plan["max_item_refs"], "OK" if plan["max_item_refs"] <= 1 else "VIOLATION"))
    if plan["skipped"]:
        print("SKIPPED (no source — never silently dropped): %d" % len(plan["skipped"]))
        for iid, t, why in plan["skipped"]:
            print("  - %s  [%s]  %s" % (iid, t, why))
    print()

    # tree: expedition (title) -> lesson (title) -> N articles
    print("plan tree:")
    arts_by_lesson = {}
    for art in arts:
        arts_by_lesson.setdefault(art["lesson_sourcedId"], []).append(art)
    for exp in m["expeditions"]:
        ei = exp["expedition_index"]
        u_sid = f"{a.prefix}-u{ei}"
        exp_total = 0
        lesson_lines = []
        for lesson in exp["lessons"]:
            l_sid = f"{a.prefix}-u{ei}-l{lesson['lesson_index']}"
            n = len(arts_by_lesson.get(l_sid, []))
            exp_total += n
            lesson_lines.append("      %s  -> %d article(s)"
                                % (lesson.get("title") or l_sid, n))
        title = (exp.get("unit") or exp.get("title") or u_sid)
        band = (" · %s" % exp["band"]) if exp.get("band") else ""
        lex = (" · %s" % exp["lexile"]) if exp.get("lexile") else ""
        print("  E%d %s%s%s  [%d lessons, %d articles]"
              % (ei + 1, title, band, lex, len(exp["lessons"]), exp_total))
        for ln in lesson_lines:
            print(ln)
    print()

    # RENDER SUMMARY — counts are now of EMITTED ARTICLES (one question each), not source items.
    tc = plan["type_counts"]
    ebsr_arts = render["ebsr_articles"]          # 2 per composite EBSR (Part A + Part B)
    match_arts = render["match_articles"]        # N per match (one per row/sub-item)
    n_transformed = render["render_hot_text"] + match_arts + render["render_msq"]
    # everything that renders + scores = verbatim choice/order + ebsr-decomposed + all transformed.
    n_render = render["render_ok"] + ebsr_arts + n_transformed
    blank = render["render_blank"]               # 0 — nothing renders blank anymore
    print("=== RENDER SUMMARY (one question per article; hot-text/match/msq TRANSFORMED to "
          "single-select choice) ===")
    print("total articles: %d   (max item-refs per article: %s — every article single-question)"
          % (len(arts), "1 ✓" if plan["max_item_refs"] == 1 else
             ("0" if plan["max_item_refs"] == 0 else ("%d VIOLATION" % plan["max_item_refs"]))))
    print("  RENDER (single-select choice / drag-order):      %d"
          "   [mcq=%d sequence=%d]  (verbatim from Mayank)"
          % (render["render_ok"], tc.get("mcq", 0), tc.get("sequence", 0)))
    print("  RENDER via EBSR-decompose (1 EBSR -> 2 articles): %d"
          "   [from %d composite EBSR; Part A + Part B, 1 item-ref each]"
          % (ebsr_arts, render["render_ebsr"]))
    print("  TRANSFORMED hot-text -> single-select choice:    %d   [hot-text]%s"
          % (render["render_hot_text"],
             ("   (of which %d had multi-token answers -> single-best, logged)"
              % render["hot_text_multi"]) if render["hot_text_multi"] else ""))
    print("  TRANSFORMED match -> N single-question articles: %d"
          "   [from %d match items; one article per row, 1 item-ref each]"
          % (match_arts, render["render_match"]))
    print("  TRANSFORMED msq -> single-best choice (LOSSY):   %d   [msq; %d total answers dropped]"
          % (render["render_msq"], render["msq_answers_dropped"]))
    print("  passage-only reading articles (no question):     %d   [article]" % render["passage"])
    if render["render_unknown"]:
        print("  unknown/forward-compat type (pushed verbatim):   %d" % render["render_unknown"])
    print("  RENDER BLANK in reading:                         %d   <- (was hot-text+match; now 0)"
          % blank)
    print("  -- %d question-articles RENDER + SCORE (mcq+sequence verbatim, ebsr Part A/B, "
          "hot-text/match-row/msq transformed); %d render blank; %d are passages --"
          % (n_render, blank, render["passage"]))
    print("  -- LOSSY transforms logged: msq %d (multi-answer -> single-best); hot-text %d "
          "(multi-token -> single-best) --" % (render["msq_lossy"], render["hot_text_multi"]))

    # reconciliation — a manifest item can now expand into >1 article (EBSR -> 2, match -> N),
    # so "items + skipped == articles" no longer holds. We reconcile two ways: (1) source manifest
    # items consumed (built-as-some-articles + skipped == manifest item refs); (2) emitted article
    # total = mcq + sequence + ebsr-articles + hot-text + match-articles + msq + passages.
    counts = m.get("counts", {}).get("items_by_type", {})
    print()
    print("=== RECONCILIATION ===")
    man_total = sum(len(l["items"]) for e in m["expeditions"] for l in e["lessons"])
    # source manifest items that produced >= 1 article (distinct src_item_id among built articles).
    src_items_built = len({art["src_item_id"] for art in arts})
    print("manifest item refs: %d" % man_total)
    print("  -> source items that produced article(s): %d" % src_items_built)
    print("  -> skipped (no source): %d" % len(plan["skipped"]))
    print("  check (items): %d + %d = %d  (expected %d)"
          % (src_items_built, len(plan["skipped"]), src_items_built + len(plan["skipped"]),
             man_total))
    print()
    ebsr_arts = render["ebsr_articles"]
    match_arts = render["match_articles"]
    print("emitted articles: %d" % len(arts))
    parts = [("mcq", tc.get("mcq", 0)), ("sequence", tc.get("sequence", 0)),
             ("ebsr (2/item)", ebsr_arts), ("hot-text", render["render_hot_text"]),
             ("match (N/item)", match_arts), ("msq", render["render_msq"]),
             ("passage", render["passage"])]
    if render["render_unknown"]:
        parts.append(("unknown", render["render_unknown"]))
    art_sum = sum(v for _, v in parts)
    print("  = " + " + ".join("%s %d" % (k, v) for k, v in parts) + " = %d" % art_sum)
    print("  check (articles): %d == %d  %s"
          % (art_sum, len(arts), "OK" if art_sum == len(arts) else "MISMATCH"))
    print("by manifest type (emitted articles; ebsr/match expanded): %s" % dict(sorted(tc.items())))
    if counts:
        print("manifest counts.items_by_type (source items):    %s" % dict(sorted(counts.items())))
    print("=== ZERO network calls made (dry-run) ===")


def _no_network(*args, **kwargs):
    raise RuntimeError("network call attempted during --dry-run (this must never happen)")


def main():
    ap = argparse.ArgumentParser(description="Publish Grade-3 Reading to Alpha Read from a manifest + QTI package.")
    ap.add_argument("--manifest", required=True, help="course_manifest.json (authoritative tree)")
    ap.add_argument("--bundle", required=True, help="course_bundle.jsonl (passage content, keyed by item_id)")
    ap.add_argument("--qti", required=True, help="QTI package dir (items/*.xml + stimuli/*.xml)")
    ap.add_argument("--org", required=True, help="OneRoster org sourcedId the VIEWER belongs to")
    ap.add_argument("--prefix", required=True, help="course sourcedId + id base (its digits seed article ids)")
    ap.add_argument("--title", required=True, help="course title")
    ap.add_argument("--enroll-student", default=None,
                    help="OneRoster user sourcedId to enroll as a student (term+class+enrollment). "
                         "Use a TEST student you own — never a real child.")
    ap.add_argument("--checkpoint", default="/tmp/publish_from_manifest_state.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the full plan in memory and PRINT it; make ZERO network calls.")
    ap.add_argument("--publish", action="store_true",
                    help="publish a REAL course: publishStatus=published, loud banner before any POST.")
    ap.add_argument("--native", action="store_true",
                    help="AS-IS clone: upload every item exactly as authored — no transform, no EBSR "
                         "decompose, one article per item. Faithful/complete (some formats won't render).")
    a = ap.parse_args()

    # In dry-run, HARD-DISABLE the network: any accidental mint/post/get raises immediately.
    if a.dry_run:
        P.mint_token = _no_network
        P.post = _no_network
        P.get_json = _no_network

    plan = build_plan(a)

    if a.dry_run:
        print_dry_run(a, plan)
        return

    # ── EXECUTE PHASE (network) — reached only when NOT --dry-run ────────────────────────────────
    if a.publish:
        print("=" * 78)
        print("=== PUBLISH (REAL COURSE) ===  id=%s  org=%s  publishStatus=published" % (a.prefix, a.org))
        print("=== %d articles across %d unit(s)/%d lesson(s) — POSTing LIVE to Alpha Read ==="
              % (len(plan["articles"]), len(plan["units"]), len(plan["lessons"])))
        print("=" * 78)

    state = json.load(open(a.checkpoint)) if os.path.exists(a.checkpoint) else {}
    tok, scopes = P.mint_token()
    print("token OK | scopes:", scopes or "(none)")
    print("course:", a.prefix, "| org:", a.org, "| publishStatus:", plan["publish_status"])
    if plan["skipped"]:
        print("NOTE: skipping %d item(s) with no source (logged in dry-run)." % len(plan["skipped"]))

    QTI, OR = P.QTI, P.OR

    print("--- stimuli ---")
    for sid, (title, content) in plan["stim_plan"].items():
        P.post(QTI + "/stimuli", {"identifier": sid, "title": title, "content": content},
               "stim:" + sid, tok, state, a.checkpoint)

    print("--- items (verbatim QTI XML; EBSR pre-decomposed into parts) ---")
    for pid, pxml in plan["item_plan"].items():
        P.post(QTI + "/assessment-items", {"format": "xml", "xml": pxml},
               "item:" + pid, tok, state, a.checkpoint)

    print("--- oneroster course ---")
    P.post(OR + "/rostering/v1p2/courses", {"course": plan["course"]},
           "course:" + a.prefix, tok, state, a.checkpoint)

    print("--- units (courseComponent, parent=course) ---")
    for u in plan["units"]:
        P.post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {
            "sourcedId": u["sourcedId"], "status": "active", "title": u["title"],
            "sortOrder": u["sortOrder"], "course": {"sourcedId": a.prefix},
            "parent": None, "courseComponent": None, "metadata": {}}},
            "unit:" + u["sourcedId"], tok, state, a.checkpoint)

    print("--- lessons (courseComponent, parent=unit) ---")
    for l in plan["lessons"]:
        P.post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {
            "sourcedId": l["sourcedId"], "status": "active", "title": l["title"],
            "sortOrder": l["sortOrder"], "course": {"sourcedId": a.prefix},
            "parent": {"sourcedId": l["unit_sourcedId"]},
            "courseComponent": {"sourcedId": l["unit_sourcedId"]}, "metadata": {}}},
            "lesson:" + l["sourcedId"], tok, state, a.checkpoint)

    print("--- articles (test + resource + component-resource = article_<N>) ---")
    for art in plan["articles"]:
        ART, N = art["art_id"], art["vendor"]
        title = art["title"]
        refs = [{"identifier": x, "href": x + ".xml"} for x in art["item_refs"]]
        # QTI test: references this article's item(s). Passage-only articles carry an empty item-ref
        # list (a reading article = passage stimulus + a no-question test) — logged as such.
        P.post(QTI + "/assessment-tests", {"identifier": ART, "title": title,
            "qti-test-part": [{"identifier": "tp1", "navigationMode": "nonlinear",
                "submissionMode": "individual",
                "qti-assessment-section": [{"identifier": "sec1", "title": title, "visible": True,
                    "required": True, "fixed": False, "sequence": 1,
                    "qti-assessment-item-ref": refs}]}],
            "qti-outcome-declaration": [{"identifier": "SCORE", "cardinality": "single", "baseType": "float"}]},
            "test:" + ART, tok, state, a.checkpoint)
        P.post(OR + "/resources/v1p2/resources/", {"resource": {
            "sourcedId": ART, "status": "active", "title": title, "importance": "primary",
            "vendorResourceId": N,
            "metadata": {"type": "qti", "subType": "qti-test", "lessonType": "alpha-read-article",
                         "xp": 12, "questionType": "custom",
                         "url": QTI + "/assessment-tests/" + ART}}},
            "res:" + ART, tok, state, a.checkpoint)
        P.post(OR + "/rostering/v1p2/courses/component-resources", {"componentResource": {
            "sourcedId": ART, "status": "active", "title": title, "sortOrder": 1,
            "resource": {"sourcedId": ART}, "courseComponent": {"sourcedId": art["lesson_sourcedId"]},
            "metadata": {"lessonType": "alpha-read-article"}}},
            "cr:" + ART, tok, state, a.checkpoint)

    if a.enroll_student:
        TERM, CLASS, ENR = a.prefix + "-term", a.prefix + "-class", a.prefix + "-enr"
        print("--- enroll student", a.enroll_student, "---")
        P.post(OR + "/rostering/v1p2/academicSessions", {"academicSession": {
            "sourcedId": TERM, "status": "active", "title": a.title + " Term", "type": "term",
            "startDate": "2025-08-01", "endDate": "2026-06-30", "schoolYear": "2026",
            "org": {"sourcedId": a.org}}}, "term:" + TERM, tok, state, a.checkpoint)
        P.post(OR + "/rostering/v1p2/classes", {"class": {
            "sourcedId": CLASS, "status": "active", "title": a.title, "classCode": CLASS,
            "classType": "scheduled", "grades": ["3"], "subjects": ["Reading"],
            "course": {"sourcedId": a.prefix}, "org": {"sourcedId": a.org},
            "school": {"sourcedId": a.org}, "terms": [{"sourcedId": TERM}]}},
            "class:" + CLASS, tok, state, a.checkpoint)
        P.post(OR + "/rostering/v1p2/enrollments", {"enrollment": {
            "sourcedId": ENR, "status": "active", "role": "student", "primary": True,
            "user": {"sourcedId": a.enroll_student}, "class": {"sourcedId": CLASS},
            "org": {"sourcedId": a.org}, "school": {"sourcedId": a.org}}},
            "enroll:" + ENR, tok, state, a.checkpoint)

    print("\n=== DONE === %d article(s) across %d unit(s) / %d lesson(s)"
          % (len(plan["articles"]), len(plan["units"]), len(plan["lessons"])))
    print("AlphaBuild course: https://app.alpha-build.org/content/" + a.prefix)


if __name__ == "__main__":
    main()
