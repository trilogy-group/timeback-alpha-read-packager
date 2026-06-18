#!/usr/bin/env python3
"""Publish ONE good Grade-3 Reading course in Praveen's WORKING powerpath-100 shape.

Built FROM THE RAW DATA (Anirudh's course_bundle.jsonl), NOT from the alpha-read-article
courses (those hang on the TimeBack powerpath viewer because they aren't powerpath-wired).

Reverse-engineered target (reading-explorers-g3-allqtypes, the course that "works really well"):
  course -> unit components -> lesson components
  per lesson:
    * stimulus  (the passage; rendered on the left)
    * QTI items (clean QTI 3.0, adaptive=false; every native type kept — match/hot-text/msq/ebsr/
      sequence all RENDER in powerpath), each carrying a <qti-assessment-stimulus-ref> to the passage
    * ONE powerpath QTI assessment-test whose section holds ALL the lesson's item-refs (the BANK,
      8-15 items/lesson -> deep enough that the incremental powerpath scorer reaches 100, no loop)
    * OneRoster resource (metadata.lessonType = powerpath-100, url = the test)
    * component-resource (metadata.lessonType = powerpath-100)
    * parent assessmentLineItem (0-100)  + child assessmentLineItems (0-1, questionId=item id)
  + enroll the student (class/term/enrollment)

QTI item generators are g3v2_to_course.py's tested builders (adaptive=false), the same clean
shape Praveen uses. Idempotent (409 = already exists = ok). Flags below.

Usage:
  python3 publish_powerpath.py --bundle <course_bundle.jsonl> --org <org> --prefix <id> \
      --title "<title>" [--enroll-student <uid>] [--dry-run | --publish] \
      [--limit-lessons N] [--only-unit IDX] [--skeleton-only] [--checkpoint PATH]
"""
import json, os, sys, argparse, re
from xml.sax.saxutils import escape
from collections import OrderedDict, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_to_timeback as P            # mint_token, post, get_json, QTI, OR

QTI_ITEM_BASE = None  # set after bases known


# ───────────────────────── QTI 3.0 item generators (from g3v2_to_course.py, adaptive=false) ──────
NS = ('<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n'
      '<qti-assessment-item xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
      'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsqtiasi_v3p0 '
      'https://purl.imsglobal.org/spec/qti/v3p0/schema/xsd/imsqti_asiv3p0_v1p0.xsd" '
      'identifier="{iid}" title="{title}" adaptive="false" time-dependent="false" '
      'tool-name="alpha-read-packager" tool-version="powerpath">\n')
SCORE_DECL = ('  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float" normal-maximum="1.0">\n'
              '    <qti-default-value><qti-value>0</qti-value></qti-default-value>\n  </qti-outcome-declaration>\n'
              '  <qti-outcome-declaration identifier="MAXSCORE" cardinality="single" base-type="float">\n'
              '    <qti-default-value><qti-value>1.0</qti-value></qti-default-value>\n  </qti-outcome-declaration>\n')
RP_MATCH_KEY = ('  <qti-response-processing><qti-response-condition><qti-response-if>\n'
                '    <qti-match><qti-variable identifier="RESPONSE"/><qti-base-value base-type="identifier">{key}</qti-base-value></qti-match>\n'
                '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
                '  </qti-response-if><qti-response-else>\n'
                '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>\n'
                '  </qti-response-else></qti-response-condition></qti-response-processing>\n')
RP_CORRECT = ('  <qti-response-processing><qti-response-condition><qti-response-if>\n'
              '    <qti-match><qti-variable identifier="RESPONSE"/><qti-correct identifier="RESPONSE"/></qti-match>\n'
              '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
              '  </qti-response-if><qti-response-else>\n'
              '    <qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>\n'
              '  </qti-response-else></qti-response-condition></qti-response-processing>\n')


def stem(q):
    return '  <qti-item-body>\n    <div class="stem"><p>%s</p></div>\n' % escape(q or "")


def mcq_xml(iid, d, multi=False):
    opts = d["answer_options"]
    correct = d["answer"] if isinstance(d["answer"], list) else [d["answer"]]
    card = "multiple" if multi else "single"
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(k) for k in correct)
    body = NS.format(iid=iid, title="MSQ" if multi else "MCQ")
    body += '  <qti-response-declaration identifier="RESPONSE" cardinality="%s" base-type="identifier">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % (card, cr)
    body += SCORE_DECL + stem(d["question"])
    body += '    <qti-choice-interaction response-identifier="RESPONSE" max-choices="%d">\n' % (len(opts) if multi else 1)
    for o in opts:
        body += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (escape(o["key"]), escape(o["text"]))
    body += '    </qti-choice-interaction>\n  </qti-item-body>\n'
    body += (RP_CORRECT if multi else RP_MATCH_KEY.format(key=escape(correct[0])))
    return body + "</qti-assessment-item>\n"


def order_xml(iid, d):
    steps = d["items"]; order = d["correct_order"]
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(s) for s in order)
    body = NS.format(iid=iid, title="Order")
    body += '  <qti-response-declaration identifier="RESPONSE" cardinality="ordered" base-type="identifier">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % cr
    body += SCORE_DECL + stem(d["question"])
    body += '    <qti-order-interaction response-identifier="RESPONSE" shuffle="true">\n'
    for s in steps:
        body += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (escape(s["id"]), escape(s["content"]))
    body += '    </qti-order-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return body + "</qti-assessment-item>\n"


def hottext_xml(iid, d):
    toks = d["tokens"]; correct = d["answer"]
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(t) for t in correct)
    body = NS.format(iid=iid, title="HotText")
    body += '  <qti-response-declaration identifier="RESPONSE" cardinality="single" base-type="identifier">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % cr
    body += SCORE_DECL + stem(d["question"])
    spans = " ".join('<qti-hottext identifier="%s">%s</qti-hottext>' % (escape(t["id"]), escape(t["text"])) for t in toks)
    body += '    <qti-hottext-interaction response-identifier="RESPONSE" max-choices="%d">\n      <p>%s</p>\n    </qti-hottext-interaction>\n  </qti-item-body>\n' % (d.get("max_selections", 1) or 1, spans)
    body += RP_CORRECT
    return body + "</qti-assessment-item>\n"


def match_xml(iid, d):
    items = d["items"]; cats = d["categories"]
    cr = "".join("      <qti-value>%s %s</qti-value>\n" % (escape(it["id"]), escape(it["correct_category_id"])) for it in items)
    body = NS.format(iid=iid, title="Match")
    body += '  <qti-response-declaration identifier="RESPONSE" cardinality="multiple" base-type="directedPair">\n    <qti-correct-response>\n%s    </qti-correct-response>\n  </qti-response-declaration>\n' % cr
    body += SCORE_DECL + stem(d["question"])
    body += '    <qti-match-interaction response-identifier="RESPONSE" max-associations="%d" shuffle="true" class="qti-choices-top">\n' % len(items)
    body += '      <qti-simple-match-set>\n'
    for it in items:
        body += '        <qti-simple-associable-choice identifier="%s" match-max="1"><p>%s</p></qti-simple-associable-choice>\n' % (escape(it["id"]), escape(it["text"]))
    body += '      </qti-simple-match-set>\n      <qti-simple-match-set>\n'
    for c in cats:
        body += '        <qti-simple-associable-choice identifier="%s" match-max="%d"><p>%s</p></qti-simple-associable-choice>\n' % (escape(c["id"]), len(items), escape(c["label"]))
    body += '      </qti-simple-match-set>\n    </qti-match-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return body + "</qti-assessment-item>\n"


def ebsr_xml(iid, d):
    a, b = d["part_a"], d["part_b"]
    body = NS.format(iid=iid, title="EBSR")
    for rid, part in (("RESPONSE_1", a), ("RESPONSE_2", b)):
        body += '  <qti-response-declaration identifier="%s" cardinality="single" base-type="identifier">\n    <qti-correct-response><qti-value>%s</qti-value></qti-correct-response>\n  </qti-response-declaration>\n' % (rid, escape(part["answer"]))
    body += ('  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float" normal-maximum="2.0"><qti-default-value><qti-value>0</qti-value></qti-default-value></qti-outcome-declaration>\n'
             '  <qti-outcome-declaration identifier="MAXSCORE" cardinality="single" base-type="float"><qti-default-value><qti-value>2.0</qti-value></qti-default-value></qti-outcome-declaration>\n'
             '  <qti-outcome-declaration identifier="SCORE_1" cardinality="single" base-type="float" normal-maximum="1.0"><qti-default-value><qti-value>0</qti-value></qti-default-value></qti-outcome-declaration>\n'
             '  <qti-outcome-declaration identifier="SCORE_2" cardinality="single" base-type="float" normal-maximum="1.0"><qti-default-value><qti-value>0</qti-value></qti-default-value></qti-outcome-declaration>\n')
    body += '  <qti-item-body>\n    <div class="stem"><p>Read the passage and answer both parts.</p></div>\n'
    for rid, part, label in (("RESPONSE_1", a, "Part A."), ("RESPONSE_2", b, "Part B.")):
        body += '    <qti-choice-interaction response-identifier="%s" max-choices="1">\n      <qti-prompt><p><strong class="part-label">%s</strong> %s</p></qti-prompt>\n' % (rid, label, escape(part["question"]))
        for o in part["answer_options"]:
            body += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (escape(o["key"]), escape(o["text"]))
        body += '    </qti-choice-interaction>\n'
    body += '  </qti-item-body>\n'
    body += '  <qti-response-processing>\n'
    for rid, part, sc in (("RESPONSE_1", a, "SCORE_1"), ("RESPONSE_2", b, "SCORE_2")):
        body += ('    <qti-response-condition><qti-response-if>\n'
                 '      <qti-match><qti-variable identifier="%s"/><qti-base-value base-type="identifier">%s</qti-base-value></qti-match>\n'
                 '      <qti-set-outcome-value identifier="%s"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
                 '    </qti-response-if></qti-response-condition>\n') % (rid, escape(part["answer"]), sc)
    body += ('    <qti-set-outcome-value identifier="SCORE"><qti-sum><qti-variable identifier="SCORE_1"/><qti-variable identifier="SCORE_2"/></qti-sum></qti-set-outcome-value>\n'
             '  </qti-response-processing>\n')
    return body + "</qti-assessment-item>\n"


BUILDERS = {"mcq": lambda i, d: mcq_xml(i, d, False), "msq": lambda i, d: mcq_xml(i, d, True),
            "sequence": order_xml, "hot-text": hottext_xml, "match": match_xml, "ebsr": ebsr_xml}
QTYPES = set(BUILDERS)


def with_stimulus_ref(item_xml, stim_id):
    """Insert <qti-assessment-stimulus-ref> right before <qti-item-body> (Praveen's placement)."""
    ref = '  <qti-assessment-stimulus-ref identifier="%s" href="stimuli/%s"/>\n' % (stim_id, stim_id)
    return item_xml.replace('  <qti-item-body>\n', ref + '  <qti-item-body>\n', 1)


def _txt_to_html(txt, title=None):
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", txt or "") if p.strip()]
    inner = "".join("<p>%s</p>" % escape(p) for p in paras) or "<p>%s</p>" % escape(txt or "")
    head = ("<h3>%s</h3>" % escape(title)) if title else ""
    return '<div class="passage">%s%s</div>' % (head, inner)


def passage_html(article):
    txt = article.get("content") or ""
    if not txt:
        st = article.get("stimulus")
        txt = st.get("value", "") if isinstance(st, dict) else (st or "")
    return _txt_to_html(txt, article.get("title") or "Passage")


def item_stim_text(q):
    """The text THIS question was written against (its own stimulus) — what must be shown so the
    question is answerable. Bundle questions drift from the lesson article, so each item gets its own."""
    s = q.get("stimulus")
    s = s.get("value", "") if isinstance(s, dict) else (s or "")
    return _txt_to_html(s) if s.strip() else ""


# ───────────────────────── plan builder ─────────────────────────
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40]


def build_plan(a):
    rows = [json.loads(l) for l in open(a.bundle) if l.strip()]
    # group by expedition then lesson, preserving order
    by_exp = OrderedDict()
    for r in rows:
        ei = int(r.get("expedition_index", 0))
        by_exp.setdefault(ei, OrderedDict())
    # collect lessons per expedition
    lessons_map = OrderedDict()  # (ei, lesson_id) -> {title, exp, items[], article}
    for r in rows:
        ei = int(r.get("expedition_index", 0))
        lid = r.get("lesson_id") or "%s::?" % ei
        key = (ei, lid)
        L = lessons_map.setdefault(key, {"ei": ei, "lesson_id": lid,
                                         "unit": r.get("unit"), "title": r.get("lesson_title") or lid,
                                         "lesson_index": int(r.get("lesson_index", 0)),
                                         "expedition": r.get("expedition"),
                                         "items": [], "article": None})
        t = r.get("type")
        if t == "article":
            if L["article"] is None:
                L["article"] = r
        elif t in QTYPES:
            L["items"].append(r)

    # expeditions metadata
    exp_titles = {}
    for r in rows:
        exp_titles[int(r.get("expedition_index", 0))] = (r.get("unit") or r.get("expedition") or "Unit")

    PRE = a.prefix
    course = {"sourcedId": PRE, "status": "active", "title": a.title, "courseCode": PRE,
              "grades": ["3"], "subjects": ["Reading"], "org": {"sourcedId": a.org},
              "metadata": {"primaryApp": "timeback", "lessonType": "powerpath-100"}}

    units, lessons, lesson_blocks = [], [], []
    exps_sorted = sorted({k[0] for k in lessons_map})
    if a.only_unit is not None:
        exps_sorted = [e for e in exps_sorted if e == a.only_unit]
    lesson_budget = a.limit_lessons or 10 ** 9

    n_lessons_emitted = 0
    for ei in exps_sorted:
        unit_id = "%s-u%d" % (PRE, ei)
        units.append({"sourcedId": unit_id, "title": exp_titles.get(ei, "Unit %d" % ei),
                      "sortOrder": (ei + 1) * 1000})
        # lessons in this expedition, ordered by lesson_index
        ekeys = [k for k in lessons_map if k[0] == ei]
        ekeys.sort(key=lambda k: lessons_map[k]["lesson_index"])
        for li, key in enumerate(ekeys):
            if n_lessons_emitted >= lesson_budget:
                break
            L = lessons_map[key]
            if not L["items"]:
                continue
            lesson_id = "%s-u%d-l%d" % (PRE, ei, li)
            art = L["article"] or {"title": L["title"], "content": ""}
            art_html = passage_html(art)
            test_id = "%s-test" % lesson_id
            qitems, child_alis, stims = [], [], []
            for qi, q in enumerate(L["items"], 1):
                t = q["type"]
                iid = "%s-q%02d-%s" % (lesson_id, qi, t.replace("-", ""))
                try:
                    xml = BUILDERS[t](iid, q)
                except Exception as e:
                    print("  !! skip item %s (%s): %s" % (iid, t, e))
                    continue
                # PER-ITEM stimulus = the text THIS question was written against (fixes provenance
                # drift: questions reference their own stimulus, not the shared lesson article).
                stim_id = iid + "-s"
                content = item_stim_text(q) or art_html
                stims.append({"identifier": stim_id, "title": (q.get("title") or L["title"])[:120],
                              "content": content})
                xml = with_stimulus_ref(xml, stim_id)
                qstem = q.get("question") or (q.get("part_a", {}) or {}).get("question") or t
                qitems.append({"id": iid, "xml": xml, "type": t, "stem": qstem})
                child_alis.append({"sourcedId": "%s-ali-q%02d" % (lesson_id, qi),
                                   "questionId": iid, "title": ("PowerPath Question: %s" % qstem)[:240]})
            if not qitems:
                continue
            # Only register the lesson component once it actually has a powerpath block — never POST
            # an orphan lesson with no test/resource/ALIs.
            lessons.append({"sourcedId": lesson_id, "title": L["title"],
                            "sortOrder": (li + 1) * 10, "unit_sourcedId": unit_id})
            parent_ali = "%s-ali" % lesson_id
            lesson_blocks.append({
                "lesson_id": lesson_id, "title": L["title"], "test_id": test_id,
                "stims": stims, "items": qitems, "parent_ali": parent_ali, "child_alis": child_alis,
                "sort": (li + 1)})
            n_lessons_emitted += 1
        if n_lessons_emitted >= lesson_budget:
            pass

    return {"course": course, "units": units, "lessons": lessons, "blocks": lesson_blocks}


def test_json(test_id, title, item_ids, item_base):
    """Structured-JSON assessment test (the QTI service rejects the raw-XML envelope for tests).
    ONE linear/individual test-part -> ONE section -> all item-refs = the powerpath bank."""
    refs = [{"identifier": i, "href": "%s/%s" % (item_base, i)} for i in item_ids]
    return {"identifier": test_id, "title": title,
            "qti-test-part": [{"identifier": "tp0", "navigationMode": "linear",
                "submissionMode": "individual",
                "qti-assessment-section": [{"identifier": "s0", "title": "items", "visible": True,
                    "required": True, "fixed": False, "sequence": 1,
                    "qti-assessment-item-ref": refs}]}],
            "qti-outcome-declaration": [{"identifier": "SCORE", "cardinality": "single", "baseType": "float"}]}


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--org", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--enroll-student", default=None)
    ap.add_argument("--checkpoint", default="/tmp/publish_powerpath_state.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--limit-lessons", type=int, default=None)
    ap.add_argument("--only-unit", type=int, default=None)
    ap.add_argument("--skeleton-only", action="store_true",
                    help="only course+units+lessons+enroll (no QTI/resources/ALIs)")
    a = ap.parse_args()

    plan = build_plan(a)
    nb = plan["blocks"]
    nitems = sum(len(b["items"]) for b in nb)
    print("=" * 78)
    print("POWERPATH PLAN: course=%s org=%s" % (a.prefix, a.org))
    print("  units=%d lessons=%d  powerpath-tests=%d  items(bank total)=%d"
          % (len(plan["units"]), len(plan["lessons"]), len(nb), nitems))
    for b in nb[:6]:
        tc = {}
        for it in b["items"]:
            tc[it["type"]] = tc.get(it["type"], 0) + 1
        print("   %-26s bank=%2d  %s" % (b["lesson_id"], len(b["items"]), tc))
    if len(nb) > 6:
        print("   ... (%d more lessons)" % (len(nb) - 6))
    print("=" * 78)

    if a.dry_run or not a.publish:
        # validate XML well-formedness offline
        import xml.dom.minidom as MD
        bad = 0
        for b in nb:
            for it in b["items"]:
                try:
                    MD.parseString(it["xml"])
                except Exception as e:
                    bad += 1
                    print("  XML ERR %s: %s" % (it["id"], e))
        print("DRY-RUN: %d items, %d malformed. (use --publish to deploy)" % (nitems, bad))
        return

    state = json.load(open(a.checkpoint)) if os.path.exists(a.checkpoint) else {}
    tok, scopes = P.mint_token()
    QTI, OR = P.QTI, P.OR
    item_base = QTI + "/assessment-items"
    GB = OR + "/gradebook/v1p2/assessmentLineItems"
    print("token OK | scopes:", (scopes or "")[:60])

    # course + units + lessons (skeleton) — idempotent
    P.post(OR + "/rostering/v1p2/courses", {"course": plan["course"]}, "course:" + a.prefix, tok, state, a.checkpoint)
    for u in plan["units"]:
        P.post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {
            "sourcedId": u["sourcedId"], "status": "active", "title": u["title"],
            "sortOrder": u["sortOrder"], "course": {"sourcedId": a.prefix},
            "parent": None, "courseComponent": None, "metadata": {}}},
            "unit:" + u["sourcedId"], tok, state, a.checkpoint)
    for l in plan["lessons"]:
        P.post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {
            "sourcedId": l["sourcedId"], "status": "active", "title": l["title"],
            "sortOrder": l["sortOrder"], "course": {"sourcedId": a.prefix},
            "parent": {"sourcedId": l["unit_sourcedId"]},
            "courseComponent": {"sourcedId": l["unit_sourcedId"]}, "metadata": {}}},
            "lesson:" + l["sourcedId"], tok, state, a.checkpoint)

    if not a.skeleton_only:
        for b in nb:
            LID, TID = b["lesson_id"], b["test_id"]
            # per-item stimuli
            for s in b["stims"]:
                P.post(QTI + "/stimuli", {"identifier": s["identifier"], "title": s["title"],
                       "content": s["content"]}, "stim:" + s["identifier"], tok, state, a.checkpoint)
            # items
            for it in b["items"]:
                P.post(QTI + "/assessment-items", {"format": "xml", "xml": it["xml"]},
                       "item:" + it["id"], tok, state, a.checkpoint)
            # powerpath test (bank) — structured JSON
            P.post(QTI + "/assessment-tests",
                   test_json(TID, b["title"], [it["id"] for it in b["items"]], item_base),
                   "test:" + TID, tok, state, a.checkpoint)
            # resource (powerpath-100)
            P.post(OR + "/resources/v1p2/resources/", {"resource": {
                "sourcedId": TID, "status": "active", "title": b["title"], "importance": "primary",
                "vendorResourceId": TID,
                "metadata": {"type": "qti", "subType": "qti-test", "lessonType": "powerpath-100",
                             "xp": 20, "subject": "Reading", "grade": "3",
                             "url": QTI + "/assessment-tests/" + TID}}},
                "res:" + TID, tok, state, a.checkpoint)
            # component-resource (powerpath-100), parented to lesson
            P.post(OR + "/rostering/v1p2/courses/component-resources", {"componentResource": {
                "sourcedId": LID + "-cr", "status": "active", "title": b["title"], "sortOrder": b["sort"],
                "resource": {"sourcedId": TID}, "courseComponent": {"sourcedId": LID},
                "metadata": {"lessonType": "powerpath-100"}}},
                "cr:" + LID, tok, state, a.checkpoint)
            # parent ALI (0-100)
            P.post(GB, {"assessmentLineItem": {
                "sourcedId": b["parent_ali"], "status": "active",
                "title": ("PowerPath Test: %s" % b["title"])[:240],
                "description": ("PowerPath Test: %s" % b["title"])[:240],
                "componentResource": {"sourcedId": LID + "-cr"},
                "course": {"sourcedId": a.prefix},
                "resultValueMin": 0, "resultValueMax": 100,
                "metadata": {"lessonType": "powerpath-100", "courseSourcedId": a.prefix}}},
                "ali:" + b["parent_ali"], tok, state, a.checkpoint)
            # child ALIs (0-1, questionId = item id)
            for c in b["child_alis"]:
                P.post(GB, {"assessmentLineItem": {
                    "sourcedId": c["sourcedId"], "status": "active",
                    "title": c["title"], "description": c["title"],
                    "parentAssessmentLineItem": {"sourcedId": b["parent_ali"]},
                    "course": {"sourcedId": a.prefix},
                    "resultValueMin": 0, "resultValueMax": 1,
                    "metadata": {"questionId": c["questionId"], "lessonType": "powerpath-100", "grade": "3"}}},
                    "cali:" + c["sourcedId"], tok, state, a.checkpoint)

    if a.enroll_student:
        TERM, CLASS, ENR = a.prefix + "-term", a.prefix + "-class", a.prefix + "-enr"
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

    print("\n=== DONE === %d lessons / %d bank items" % (len(nb), nitems))
    print("AlphaBuild: https://app.alpha-build.org/content/" + a.prefix)


if __name__ == "__main__":
    main()
