#!/usr/bin/env python3
"""deploy_mastery_gate.py

Publish Form A and Form B mastery gate tests to the live G5 course
g5-reading-ela-pp-9801.

WHAT IT DOES
------------
Reads /tmp/g5_mastery_gate_v1.jsonl (48 items: 24 Form A + 24 Form B).
For each form it:
  1. POSTs per-item stimuli to QTI /stimuli
  2. POSTs QTI 3.0 items to QTI /assessment-items
  3. POSTs one QTI assessment-test (the bank) to QTI /assessment-tests
  4. POSTs a resource (powerpath-100) to OR /resources
  5. POSTs a courseComponent (mastery_gate) to OR /courses/components
     parented to the course root (no parent unit — terminal gate)
  6. POSTs a component-resource linking the test to the component
  7. POSTs a parent ALI (0-100) + 24 child ALIs (0-1, questionId=item id)

Component IDs:
  Form A component : g5-reading-ela-pp-9801-gate-a
  Form B component : g5-reading-ela-pp-9801-gate-b
  Form A test      : g5-reading-ela-pp-9801-gate-a-test
  Form B test      : g5-reading-ela-pp-9801-gate-b-test
  Items (Form A)   : g5-reading-ela-pp-9801-gate-a-q01-<type>, ...
  Items (Form B)   : g5-reading-ela-pp-9801-gate-b-q01-<type>, ...

USAGE
-----
  python3 deploy_mastery_gate.py [--dry-run] [--form A|B|both] \
      [--gate-file /tmp/g5_mastery_gate_v1.jsonl] \
      [--checkpoint /tmp/deploy_gate_state.json]

FLAGS
-----
  --dry-run     Validate XML, print plan, no API calls.
  --form        A, B, or both (default: both)
  --gate-file   Path to the 48-item JSONL (default: /tmp/g5_mastery_gate_v1.jsonl)
  --checkpoint  Resume-safe state file (default: /tmp/deploy_gate_state.json)
  --publish     Required to actually POST (safety gate — omit for dry-run)

SCHEMA NOTES
------------
- EBSR items may use is_correct=True on answer_options instead of answer field.
  Both variants are handled.
- hot-text items may have answer as a list (multi-select).
- stimulus is always a plain string (not a dict) in this file.
"""

import argparse
import json
import os
import re
import sys
import html as html_mod
import xml.dom.minidom as MD
from xml.sax.saxutils import escape

# ── resolve push_to_timeback ────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "..", "v2_final_package", "scripts"))
sys.path.insert(0, _SCRIPTS)
from push_to_timeback import mint_token, post, get_json  # noqa: E402

COURSE_ID = "g5-reading-ela-pp-9801"
QTI_BASE  = "https://qti.alpha-1edtech.ai/api"
OR_BASE   = "https://api.alpha-1edtech.ai/ims/oneroster"

# ── QTI 3.0 boilerplate ─────────────────────────────────────────────────────────

NS = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    '<qti-assessment-item xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsqtiasi_v3p0 '
    'https://purl.imsglobal.org/spec/qti/v3p0/schema/xsd/imsqti_asiv3p0_v1p0.xsd" '
    'identifier="{iid}" title="{title}" adaptive="false" time-dependent="false" '
    'tool-name="alpha-read-packager" tool-version="powerpath">\n'
)
SCORE_DECL = (
    '  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float" normal-maximum="1.0">\n'
    '    <qti-default-value><qti-value>0</qti-value></qti-default-value>\n  </qti-outcome-declaration>\n'
    '  <qti-outcome-declaration identifier="MAXSCORE" cardinality="single" base-type="float">\n'
    '    <qti-default-value><qti-value>1.0</qti-value></qti-default-value>\n  </qti-outcome-declaration>\n'
)
RP_MATCH_KEY = (
    '  <qti-response-processing><qti-response-condition><qti-response-if>\n'
    '    <qti-match><qti-variable identifier="RESPONSE"/>'
    '<qti-base-value base-type="identifier">{key}</qti-base-value></qti-match>\n'
    '    <qti-set-outcome-value identifier="SCORE">'
    '<qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
    '  </qti-response-if><qti-response-else>\n'
    '    <qti-set-outcome-value identifier="SCORE">'
    '<qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>\n'
    '  </qti-response-else></qti-response-condition></qti-response-processing>\n'
)
RP_CORRECT = (
    '  <qti-response-processing><qti-response-condition><qti-response-if>\n'
    '    <qti-match><qti-variable identifier="RESPONSE"/>'
    '<qti-correct identifier="RESPONSE"/></qti-match>\n'
    '    <qti-set-outcome-value identifier="SCORE">'
    '<qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
    '  </qti-response-if><qti-response-else>\n'
    '    <qti-set-outcome-value identifier="SCORE">'
    '<qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>\n'
    '  </qti-response-else></qti-response-condition></qti-response-processing>\n'
)


def _stem(q_text):
    return '  <qti-item-body>\n    <div class="stem"><p>%s</p></div>\n' % escape(q_text or "")


def _mcq_xml(iid, d, multi=False):
    opts = d["answer_options"]
    correct = d["answer"] if isinstance(d["answer"], list) else [d["answer"]]
    card = "multiple" if multi else "single"
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(k) for k in correct)
    body = NS.format(iid=iid, title="MSQ" if multi else "MCQ")
    body += (
        '  <qti-response-declaration identifier="RESPONSE" cardinality="%s" base-type="identifier">\n'
        '    <qti-correct-response>\n%s    </qti-correct-response>\n'
        '  </qti-response-declaration>\n' % (card, cr)
    )
    body += SCORE_DECL + _stem(d["question"])
    body += '    <qti-choice-interaction response-identifier="RESPONSE" max-choices="%d">\n' % (
        len(opts) if multi else 1)
    for o in opts:
        body += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (
            escape(o["key"]), escape(o["text"]))
    body += '    </qti-choice-interaction>\n  </qti-item-body>\n'
    body += RP_CORRECT if multi else RP_MATCH_KEY.format(key=escape(correct[0]))
    return body + "</qti-assessment-item>\n"


def _order_xml(iid, d):
    steps = d["items"]
    order = d["correct_order"]
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(s) for s in order)
    body = NS.format(iid=iid, title="Order")
    body += (
        '  <qti-response-declaration identifier="RESPONSE" cardinality="ordered" base-type="identifier">\n'
        '    <qti-correct-response>\n%s    </qti-correct-response>\n'
        '  </qti-response-declaration>\n' % cr
    )
    body += SCORE_DECL + _stem(d["question"])
    body += '    <qti-order-interaction response-identifier="RESPONSE" shuffle="true">\n'
    for s in steps:
        body += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (
            escape(s["id"]), escape(s.get("content") or s.get("text", "")))
    body += '    </qti-order-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return body + "</qti-assessment-item>\n"


def _hottext_xml(iid, d):
    toks = d["tokens"]
    correct = d["answer"]
    if isinstance(correct, list):
        card = "multiple"
        max_choices = d.get("max_selections") or len(correct)
        cr = "".join("      <qti-value>%s</qti-value>\n" % escape(t) for t in correct)
    else:
        card = "single"
        max_choices = 1
        cr = "      <qti-value>%s</qti-value>\n" % escape(correct)
    body = NS.format(iid=iid, title="HotText")
    body += (
        '  <qti-response-declaration identifier="RESPONSE" cardinality="%s" base-type="identifier">\n'
        '    <qti-correct-response>\n%s    </qti-correct-response>\n'
        '  </qti-response-declaration>\n' % (card, cr)
    )
    body += SCORE_DECL + _stem(d["question"])
    spans = " ".join(
        '<qti-hottext identifier="%s">%s</qti-hottext>' % (escape(t["id"]), escape(t["text"]))
        for t in toks
    )
    body += (
        '    <qti-hottext-interaction response-identifier="RESPONSE" max-choices="%d">\n'
        '      <p>%s</p>\n'
        '    </qti-hottext-interaction>\n  </qti-item-body>\n' % (max_choices, spans)
    )
    body += RP_CORRECT
    return body + "</qti-assessment-item>\n"


def _match_xml(iid, d):
    items = d["items"]
    cats = d["categories"]
    cr = "".join(
        "      <qti-value>%s %s</qti-value>\n" % (
            escape(it["id"]), escape(it.get("correct_category_id") or it.get("category", "")))
        for it in items
    )
    body = NS.format(iid=iid, title="Match")
    body += (
        '  <qti-response-declaration identifier="RESPONSE" cardinality="multiple" base-type="directedPair">\n'
        '    <qti-correct-response>\n%s    </qti-correct-response>\n'
        '  </qti-response-declaration>\n' % cr
    )
    body += SCORE_DECL + _stem(d["question"])
    body += '    <qti-match-interaction response-identifier="RESPONSE" max-associations="%d" shuffle="true" class="qti-choices-top">\n' % len(items)
    body += '      <qti-simple-match-set>\n'
    for it in items:
        body += '        <qti-simple-associable-choice identifier="%s" match-max="1"><p>%s</p></qti-simple-associable-choice>\n' % (
            escape(it["id"]), escape(it.get("text", "")))
    body += '      </qti-simple-match-set>\n      <qti-simple-match-set>\n'
    for c in cats:
        label = c.get("label") or c.get("text") or c.get("id", "")
        body += '        <qti-simple-associable-choice identifier="%s" match-max="%d"><p>%s</p></qti-simple-associable-choice>\n' % (
            escape(c["id"]), len(items), escape(label))
    body += '      </qti-simple-match-set>\n    </qti-match-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return body + "</qti-assessment-item>\n"


def _resolve_answer(part):
    """Get the correct answer key from a part dict.
    Supports both: part['answer'] = 'B'  OR  part['answer_options'][i]['is_correct'] = True
    """
    answer = part.get("answer")
    if answer:
        return answer
    for o in part.get("answer_options", []):
        if o.get("is_correct"):
            return o["key"]
    return None


def _ebsr_xml(iid, d):
    a_part, b_part = d["part_a"], d["part_b"]
    body = NS.format(iid=iid, title="EBSR")
    for rid, part in (("RESPONSE_1", a_part), ("RESPONSE_2", b_part)):
        answer_key = _resolve_answer(part)
        body += (
            '  <qti-response-declaration identifier="%s" cardinality="single" base-type="identifier">\n'
            '    <qti-correct-response><qti-value>%s</qti-value></qti-correct-response>\n'
            '  </qti-response-declaration>\n' % (rid, escape(answer_key))
        )
    body += (
        '  <qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float" '
        'normal-maximum="2.0"><qti-default-value><qti-value>0</qti-value></qti-default-value>'
        '</qti-outcome-declaration>\n'
        '  <qti-outcome-declaration identifier="MAXSCORE" cardinality="single" base-type="float">'
        '<qti-default-value><qti-value>2.0</qti-value></qti-default-value></qti-outcome-declaration>\n'
        '  <qti-outcome-declaration identifier="SCORE_1" cardinality="single" base-type="float" '
        'normal-maximum="1.0"><qti-default-value><qti-value>0</qti-value></qti-default-value>'
        '</qti-outcome-declaration>\n'
        '  <qti-outcome-declaration identifier="SCORE_2" cardinality="single" base-type="float" '
        'normal-maximum="1.0"><qti-default-value><qti-value>0</qti-value></qti-default-value>'
        '</qti-outcome-declaration>\n'
    )
    body += '  <qti-item-body>\n    <div class="stem"><p>Read the passage and answer both parts.</p></div>\n'
    for rid, part, label in (("RESPONSE_1", a_part, "Part A."), ("RESPONSE_2", b_part, "Part B.")):
        body += (
            '    <qti-choice-interaction response-identifier="%s" max-choices="1">\n'
            '      <qti-prompt><p><strong class="part-label">%s</strong> %s</p></qti-prompt>\n'
            % (rid, label, escape(part["question"]))
        )
        for o in part["answer_options"]:
            body += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (
                escape(o["key"]), escape(o["text"]))
        body += '    </qti-choice-interaction>\n'
    body += '  </qti-item-body>\n'
    body += '  <qti-response-processing>\n'
    for rid, part, sc in (("RESPONSE_1", a_part, "SCORE_1"), ("RESPONSE_2", b_part, "SCORE_2")):
        answer_key = _resolve_answer(part)
        body += (
            '    <qti-response-condition><qti-response-if>\n'
            '      <qti-match><qti-variable identifier="%s"/>'
            '<qti-base-value base-type="identifier">%s</qti-base-value></qti-match>\n'
            '      <qti-set-outcome-value identifier="%s">'
            '<qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>\n'
            '    </qti-response-if></qti-response-condition>\n'
        ) % (rid, escape(answer_key), sc)
    body += (
        '    <qti-set-outcome-value identifier="SCORE">'
        '<qti-sum><qti-variable identifier="SCORE_1"/>'
        '<qti-variable identifier="SCORE_2"/></qti-sum></qti-set-outcome-value>\n'
        '  </qti-response-processing>\n'
    )
    return body + "</qti-assessment-item>\n"


BUILDERS = {
    "mcq":      lambda i, d: _mcq_xml(i, d, False),
    "msq":      lambda i, d: _mcq_xml(i, d, True),
    "sequence": _order_xml,
    "hot-text": _hottext_xml,
    "match":    _match_xml,
    "ebsr":     _ebsr_xml,
}


def _with_stim_ref(item_xml, stim_id):
    ref = '  <qti-assessment-stimulus-ref identifier="%s" href="stimuli/%s"/>\n' % (stim_id, stim_id)
    return item_xml.replace('  <qti-item-body>\n', ref + '  <qti-item-body>\n', 1)


def _stim_html(q):
    """Build stimulus HTML from item's stimulus field (always a string in gate file)."""
    raw = q.get("stimulus", "")
    if isinstance(raw, dict):
        raw = raw.get("value", "")
    raw = (raw or "").strip()
    if not raw:
        return '<div class="passage"><p></p></div>'
    if re.search(r'<[a-zA-Z]', raw):
        return '<div class="passage">%s</div>' % raw
    raw = html_mod.unescape(raw)
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", raw) if p.strip()]
    inner = "".join("<p>%s</p>" % html_mod.escape(p) for p in paras) or "<p>%s</p>" % html_mod.escape(raw)
    return '<div class="passage">%s</div>' % inner


def _question_stem(q):
    if q.get("type") == "ebsr":
        return ((q.get("part_a") or {}).get("question") or q.get("question") or "EBSR")[:200]
    return (q.get("question") or q.get("type", "question"))[:200]


def _test_json(test_id, title, item_ids):
    item_base = QTI_BASE + "/assessment-items"
    refs = [{"identifier": i, "href": "%s/%s" % (item_base, i)} for i in item_ids]
    return {
        "identifier": test_id, "title": title,
        "qti-test-part": [{"identifier": "tp0", "navigationMode": "linear",
            "submissionMode": "individual",
            "qti-assessment-section": [{"identifier": "s0", "title": "items", "visible": True,
                "required": True, "fixed": False, "sequence": 1,
                "qti-assessment-item-ref": refs}]}],
        "qti-outcome-declaration": [{"identifier": "SCORE", "cardinality": "single", "baseType": "float"}],
    }


def build_form_plan(rows, form_letter):
    """Build all objects needed for one form.

    Returns list of dicts, each with:
      stim_id, stim_content, item_id, item_xml, qtype, stem
    Plus form-level ids.
    """
    form_items = [r for r in rows if (r.get("gate_form") or r.get("form")) == form_letter]
    if not form_items:
        raise ValueError("No items found for form %s" % form_letter)

    prefix = "%s-gate-%s" % (COURSE_ID, form_letter.lower())
    test_id = prefix + "-test"
    comp_id = prefix
    res_id  = prefix + "-test"   # resource shares test id (same pattern as lessons)

    plan_items = []
    for qi, q in enumerate(form_items, 1):
        qtype = q.get("type", "mcq")
        type_tag = qtype.replace("-", "")
        iid = "%s-q%02d-%s" % (prefix, qi, type_tag)
        stim_id = iid + "-s"
        try:
            xml = BUILDERS[qtype](iid, q)
        except Exception as e:
            print("  !! skip item %s (%s): %s" % (iid, qtype, e))
            continue
        xml = _with_stim_ref(xml, stim_id)
        plan_items.append({
            "item_id":    iid,
            "item_xml":   xml,
            "qtype":      qtype,
            "stem":       _question_stem(q),
            "stim_id":    stim_id,
            "stim_html":  _stim_html(q),
            "child_ali":  "%s-ali-q%02d" % (prefix, qi),
        })

    return {
        "form":    form_letter,
        "prefix":  prefix,
        "comp_id": comp_id,
        "test_id": test_id,
        "res_id":  res_id,
        "title":   "Mastery Gate Form %s" % form_letter,
        "items":   plan_items,
        "parent_ali": prefix + "-ali",
    }


def deploy_form(plan, tok, state, ckpt, dry_run=False):
    """Deploy one form. Returns count of items actually deployed."""
    F = plan["form"]
    title = plan["title"]
    comp_id = plan["comp_id"]
    test_id = plan["test_id"]
    res_id  = plan["res_id"]
    items   = plan["items"]
    parent_ali = plan["parent_ali"]

    GB = OR_BASE + "/gradebook/v1p2/assessmentLineItems"
    item_ids = [it["item_id"] for it in items]

    print("\n--- Form %s: %d items ---" % (F, len(items)))

    if dry_run:
        bad = 0
        for it in items:
            try:
                MD.parseString(it["item_xml"])
            except Exception as e:
                bad += 1
                print("  XML ERR %s: %s" % (it["item_id"], e))
        print("  DRY-RUN Form %s: %d items, %d malformed XML" % (F, len(items), bad))
        print("  Would create:")
        print("    courseComponent : %s" % comp_id)
        print("    assessment-test : %s" % test_id)
        print("    resource        : %s" % res_id)
        print("    parent ALI      : %s" % parent_ali)
        print("    stimuli         : %d" % len(items))
        print("    QTI items       : %d" % len(items))
        print("    child ALIs      : %d" % len(items))
        return len(items)

    # 1. Per-item stimuli
    for it in items:
        post(QTI_BASE + "/stimuli",
             {"identifier": it["stim_id"], "title": it["stem"][:120], "content": it["stim_html"]},
             "stim:" + it["stim_id"], tok, state, ckpt)

    # 2. QTI items
    for it in items:
        post(QTI_BASE + "/assessment-items",
             {"format": "xml", "xml": it["item_xml"]},
             "item:" + it["item_id"], tok, state, ckpt)

    # 3. Assessment test (bank)
    post(QTI_BASE + "/assessment-tests",
         _test_json(test_id, title, item_ids),
         "test:" + test_id, tok, state, ckpt)

    # 4. Resource
    post(OR_BASE + "/resources/v1p2/resources/", {"resource": {
        "sourcedId": res_id, "status": "active", "title": title,
        "importance": "primary", "vendorResourceId": res_id,
        "metadata": {
            "type": "qti", "subType": "qti-test",
            "lessonType": "powerpath-100",
            "xp": 0, "subject": "Reading", "grade": "5",
            "url": QTI_BASE + "/assessment-tests/" + test_id,
        }}},
        "res:" + res_id, tok, state, ckpt)

    # 5. courseComponent (mastery gate — no parent unit, sits at course level)
    sort_order = 9000 + (0 if F == "A" else 1)   # after all lesson units
    post(OR_BASE + "/rostering/v1p2/courses/components", {"courseComponent": {
        "sourcedId": comp_id, "status": "active", "title": title,
        "sortOrder": sort_order,
        "course": {"sourcedId": COURSE_ID},
        "parent": None, "courseComponent": None,
        "metadata": {
            "lessonType": "mastery_gate",
            "gateForm": F,
            "primaryApp": "timeback",
        }}},
        "comp:" + comp_id, tok, state, ckpt)

    # 6. component-resource (powerpath-100 — same shape as lessons so renderer picks it up)
    post(OR_BASE + "/rostering/v1p2/courses/component-resources", {"componentResource": {
        "sourcedId": comp_id + "-cr", "status": "active", "title": title,
        "sortOrder": 1,
        "resource": {"sourcedId": res_id},
        "courseComponent": {"sourcedId": comp_id},
        "metadata": {"lessonType": "powerpath-100"},
    }},
        "cr:" + comp_id, tok, state, ckpt)

    # 7. Parent ALI (0-100)
    post(GB, {"assessmentLineItem": {
        "sourcedId": parent_ali, "status": "active",
        "title": ("Mastery Gate Test: %s" % title)[:240],
        "description": ("Mastery Gate Test: %s" % title)[:240],
        "componentResource": {"sourcedId": comp_id + "-cr"},
        "course": {"sourcedId": COURSE_ID},
        "resultValueMin": 0, "resultValueMax": 100,
        "metadata": {"lessonType": "powerpath-100", "courseSourcedId": COURSE_ID, "gateForm": F},
    }},
        "ali:" + parent_ali, tok, state, ckpt)

    # 8. Child ALIs (0-1)
    for it in items:
        post(GB, {"assessmentLineItem": {
            "sourcedId": it["child_ali"], "status": "active",
            "title": ("Mastery Gate Q: %s" % it["stem"])[:240],
            "description": ("Mastery Gate Q: %s" % it["stem"])[:240],
            "parentAssessmentLineItem": {"sourcedId": parent_ali},
            "course": {"sourcedId": COURSE_ID},
            "resultValueMin": 0, "resultValueMax": 1,
            "metadata": {
                "questionId": it["item_id"],
                "lessonType": "powerpath-100",
                "grade": "5",
            },
        }},
            "cali:" + it["child_ali"], tok, state, ckpt)

    return len(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate-file", default="/tmp/g5_mastery_gate_v1.jsonl")
    ap.add_argument("--form", choices=["A", "B", "both"], default="both")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="Required to actually POST. Omit for dry-run.")
    ap.add_argument("--checkpoint", default="/tmp/deploy_gate_state.json")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.gate_file) if l.strip()]
    forms = (["A", "B"] if a.form == "both" else [a.form])

    plans = {f: build_form_plan(rows, f) for f in forms}

    print("=" * 72)
    print("MASTERY GATE DEPLOY: course=%s" % COURSE_ID)
    for f, p in plans.items():
        type_counts = {}
        for it in p["items"]:
            type_counts[it["qtype"]] = type_counts.get(it["qtype"], 0) + 1
        print("  Form %s: %d items  comp=%s  %s" % (f, len(p["items"]), p["comp_id"], type_counts))
    print("=" * 72)

    dry_run = a.dry_run or not a.publish

    state = {}
    if not dry_run and os.path.exists(a.checkpoint):
        state = json.load(open(a.checkpoint))

    tok = None
    if not dry_run:
        tok, scopes = mint_token()
        print("token OK | scopes:", (scopes or "")[:60])

    total = 0
    for f in forms:
        n = deploy_form(plans[f], tok, state, a.checkpoint, dry_run=dry_run)
        total += n

    print()
    if dry_run:
        print("DRY-RUN complete. Use --publish to deploy.")
    else:
        for f in forms:
            print("Gate Form %s: %d items deployed" % (f, len(plans[f]["items"])))
        print("Total: %d items across %d form(s)" % (total, len(forms)))
        print("AlphaBuild: https://app.alpha-build.org/content/" + COURSE_ID)


if __name__ == "__main__":
    main()
