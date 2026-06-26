#!/usr/bin/env python3
"""
patch_excluded_standards.py

Replace the 59 items on excluded standards (RL.5.7 / RI.5.7) in the live G5 course
g5-reading-ela-pp-9801.

WHAT IT DOES
------------
For each RL.5.7 / RI.5.7 item slot in the live course (identified from --bundle), it:
  1. Picks the next available replacement from --selections (ordered round-robin by substandard
     to preserve coverage balance; no type-matching required — the live slot keeps its QTI id
     but gets a completely new item body).
  2. Builds the QTI 3.0 XML for the replacement using the same builders as publish_powerpath.py.
  3. Builds a new per-item stimulus from the replacement's stimulus field.
  4. PUTs the new QTI item body to the assessment-items endpoint.
  5. PUTs the new stimulus to the stimuli endpoint.
  6. Updates the child ALI title so the lesson list shows the new question stem.

ENDPOINTS TOUCHED (PUT only — never POST, never DELETE)
  PUT  QTI  /assessment-items/<iid>        — replace item XML in-place
  PUT  QTI  /stimuli/<stim_id>             — replace stimulus content in-place
  PUT  OR   /gradebook/v1p2/assessmentLineItems/<child_ali_id>   — update title

The assessment-test (bank) is NOT modified: the test section still references the same item ids,
so the powerpath scorer continues to work without any further changes.

USAGE
-----
  python3 patch_excluded_standards.py \\
      --bundle /tmp/g5_bundle_fixed.jsonl \\
      --selections /tmp/g5_replacement_selections.jsonl \\
      [--dry-run]

ARGS
----
  --bundle       Path to the 1,200-row JSONL bundle (articles + items) that was used to publish
                 g5-reading-ela-pp-9801. Used to identify which lesson/slot each excluded item
                 occupies so the correct live ID can be computed.
  --selections   Path to the 59-item JSONL of replacement items (one per excluded slot).
  --dry-run      Print what would be changed without calling any API.
"""

import argparse
import json
import os
import re
import sys
import html as html_mod
from collections import OrderedDict
from xml.sax.saxutils import escape

# ── resolve push_to_timeback from the v2_final_package scripts dir ─────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "..", "v2_final_package", "scripts"))
sys.path.insert(0, _SCRIPTS)
from push_to_timeback import mint_token, get_json  # noqa: E402

PRE = "g5-reading-ela-pp-9801"
QTI_BASE = "https://qti.alpha-1edtech.ai/api"
OR_BASE  = "https://api.alpha-1edtech.ai/ims/oneroster"

# ── QTI 3.0 boilerplate (same as publish_powerpath.py) ─────────────────────────

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
            escape(s["id"]), escape(s["content"] if "content" in s else s.get("text", "")))
    body += '    </qti-order-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return body + "</qti-assessment-item>\n"


def _hottext_xml(iid, d):
    toks = d["tokens"]
    correct = d["answer"]
    if isinstance(correct, list):
        # multi-select hot-text
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
            escape(it["id"]), escape(it.get("correct_category_id", it.get("category", ""))))
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


def _ebsr_xml(iid, d):
    a_part, b_part = d["part_a"], d["part_b"]
    body = NS.format(iid=iid, title="EBSR")
    for rid, part in (("RESPONSE_1", a_part), ("RESPONSE_2", b_part)):
        answer_key = part.get("answer") or next(
            (o["key"] for o in part.get("answer_options", []) if o.get("is_correct")), None
        )
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
        answer_key = part.get("answer") or next(
            (o["key"] for o in part.get("answer_options", []) if o.get("is_correct")), None
        )
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
    "mcq": lambda i, d: _mcq_xml(i, d, False),
    "msq": lambda i, d: _mcq_xml(i, d, True),
    "sequence": _order_xml,
    "hot-text": _hottext_xml,
    "match": _match_xml,
    "ebsr": _ebsr_xml,
}


def _with_stim_ref(item_xml, stim_id):
    """Insert <qti-assessment-stimulus-ref> right before <qti-item-body>."""
    ref = '  <qti-assessment-stimulus-ref identifier="%s" href="stimuli/%s"/>\n' % (stim_id, stim_id)
    return item_xml.replace('  <qti-item-body>\n', ref + '  <qti-item-body>\n', 1)


def _stim_val(s):
    if isinstance(s, dict):
        return s.get("value", "")
    return s or ""


def _txt_to_html(txt):
    txt = html_mod.unescape(txt or "")
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", txt) if p.strip()]
    inner = "".join("<p>%s</p>" % html_mod.escape(p) for p in paras) or "<p>%s</p>" % html_mod.escape(txt)
    return '<div class="passage">%s</div>' % inner


def _stimulus_content(q):
    """Build stimulus HTML from the replacement item's stimulus field."""
    stim = q.get("stimulus", "")
    raw = _stim_val(stim)
    if not raw.strip():
        return '<div class="passage"><p></p></div>'
    # If it already has HTML tags, pass through as-is wrapped in passage div
    if re.search(r'<[a-zA-Z]', raw):
        return '<div class="passage">%s</div>' % raw
    return _txt_to_html(raw)


def _question_stem(q):
    """Extract a short question stem for ALI title (≤200 chars)."""
    if q.get("type") == "ebsr":
        stem = ((q.get("part_a") or {}).get("question") or q.get("question") or "EBSR")
    else:
        stem = q.get("question") or q.get("type", "question")
    return stem[:200]


# ── HTTP helpers ────────────────────────────────────────────────────────────────

def _put_json(url, body, tok):
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method="PUT",
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode()[:300]
    except Exception as e:
        code = getattr(e, "code", 0)
        try:
            detail = e.read()[:200].decode()
        except Exception:
            detail = str(e)[:200]
        return code, detail


def _get_existing(url, tok):
    status, data = get_json(url, tok)
    if status == 200:
        return data if isinstance(data, dict) else {}
    return None


# ── Bundle → excluded slot plan ─────────────────────────────────────────────────

def build_excluded_slots(bundle_path):
    """Return list of dicts describing every RL.5.7/RI.5.7 item slot in the live course.

    Each dict:
      iid        — the live QTI assessment-item id (e.g. g5-reading-ela-pp-9801-u0-l1-q05-sequence)
      stim_id    — iid + "-s"  (the live stimulus id)
      lesson_id  — e.g. g5-reading-ela-pp-9801-u0-l1
      qi         — 1-based position within lesson
      ei / li    — expedition / lesson indices used to build lesson_id
      substandard — "RL.5.7" or "RI.5.7"
      type       — original type tag (may differ from replacement type)
      child_ali_id — sourcedId for the child ALI (lesson_id + "-ali-q<qi:02d>")
    """
    rows = [json.loads(l) for l in open(bundle_path) if l.strip()]
    lessons_map = OrderedDict()
    for r in rows:
        ei = int(r.get("expedition_index", 0))
        lid = r.get("lesson_id") or ("%s::?" % ei)
        key = (ei, lid)
        L = lessons_map.setdefault(key, {
            "ei": ei, "lesson_id": lid,
            "lesson_index": int(r.get("lesson_index", 0)),
            "items": [], "article": None,
        })
        t = r.get("type")
        if t == "article":
            if L["article"] is None:
                L["article"] = r
        else:
            L["items"].append(r)

    slots = []
    exps = sorted({k[0] for k in lessons_map})
    for ei in exps:
        ekeys = sorted(
            [k for k in lessons_map if k[0] == ei],
            key=lambda k: lessons_map[k]["lesson_index"],
        )
        for li, key in enumerate(ekeys):
            L = lessons_map[key]
            if not L["items"]:
                continue
            lesson_id = "%s-u%d-l%d" % (PRE, ei, li)
            for qi, q in enumerate(L["items"], 1):
                if q.get("substandard_id") not in ("RL.5.7", "RI.5.7"):
                    continue
                qtype = q.get("type", "mcq")
                type_tag = qtype.replace("-", "")
                iid = "%s-q%02d-%s" % (lesson_id, qi, type_tag)
                stim_id = iid + "-s"
                child_ali_id = "%s-ali-q%02d" % (lesson_id, qi)
                slots.append({
                    "iid": iid,
                    "stim_id": stim_id,
                    "lesson_id": lesson_id,
                    "qi": qi,
                    "ei": ei,
                    "li": li,
                    "substandard": q.get("substandard_id"),
                    "type": qtype,
                    "child_ali_id": child_ali_id,
                })
    return slots


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Patch 59 excluded-standard items in g5-reading-ela-pp-9801.")
    ap.add_argument("--bundle", required=True,
                    help="Path to g5_bundle_fixed.jsonl (1,200-row source of truth)")
    ap.add_argument("--selections", required=True,
                    help="Path to g5_replacement_selections.jsonl (59 replacement items)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the patch plan without calling any API")
    a = ap.parse_args()

    # ── 1. Load replacement pool ────────────────────────────────────────────────
    replacements = [json.loads(l) for l in open(a.selections) if l.strip()]
    print(f"Replacement pool: {len(replacements)} items loaded from {a.selections}")
    if len(replacements) == 0:
        sys.exit("ERROR: replacement selections file is empty.")

    # ── 2. Build excluded slot list from bundle ─────────────────────────────────
    slots = build_excluded_slots(a.bundle)
    print(f"Excluded slots identified: {len(slots)} (RL.5.7 + RI.5.7)")
    if len(slots) != len(replacements):
        print(f"WARNING: slot count ({len(slots)}) != replacement count ({len(replacements)}). "
              f"Will pair first min(N) pairs; extras are skipped.")

    n_pairs = min(len(slots), len(replacements))

    if a.dry_run:
        print("\n=== DRY RUN — no API calls ===")
        print(f"{'SLOT IID':<60}  {'OLD_SUBSTD':<10}  {'NEW_SUBSTD':<10}  {'NEW_TYPE':<12}  STIM_ID")
        for i in range(n_pairs):
            slot = slots[i]
            repl = replacements[i]
            print(
                f"  {slot['iid']:<60}  {slot['substandard']:<10}  "
                f"{repl.get('substandard_id','?'):<10}  "
                f"{repl.get('type','?'):<12}  {slot['stim_id']}"
            )
        print(f"\nDRY RUN complete: {n_pairs} slots would be patched.")
        return

    # ── 3. Mint token ───────────────────────────────────────────────────────────
    print("Minting token...")
    tok, scopes = mint_token()
    print("Token OK | scopes:", (scopes or "")[:80])

    ok_count = fail_count = skip_count = 0
    GB = OR_BASE + "/gradebook/v1p2/assessmentLineItems"

    for i in range(n_pairs):
        slot = slots[i]
        repl = replacements[i]
        iid = slot["iid"]
        stim_id = slot["stim_id"]
        new_type = repl.get("type", slot["type"])
        new_substandard = repl.get("substandard_id", "?")
        qstem = _question_stem(repl)

        print(f"\n[{i+1:02d}/{n_pairs}] {iid}")
        print(f"      old_substandard={slot['substandard']}  new={new_substandard}  new_type={new_type}")

        # Build new QTI XML
        builder = BUILDERS.get(new_type)
        if builder is None:
            print(f"  SKIP — no builder for type '{new_type}'")
            skip_count += 1
            continue
        try:
            xml = builder(iid, repl)
        except Exception as e:
            print(f"  SKIP — XML build failed: {e}")
            skip_count += 1
            continue

        # Attach stimulus ref
        xml = _with_stim_ref(xml, stim_id)

        # Build stimulus content
        stim_content = _stimulus_content(repl)

        # ── PUT item ───────────────────────────────────────────────────────────
        item_url = QTI_BASE + "/assessment-items/" + iid
        status, resp = _put_json(item_url, {"format": "xml", "xml": xml}, tok)
        if status in (200, 201, 204):
            print(f"  OK  PUT item      HTTP {status}")
        else:
            # Try fetching the existing item and merging
            existing = _get_existing(item_url, tok)
            if existing:
                existing.update({"format": "xml", "xml": xml})
                status, resp = _put_json(item_url, existing, tok)
            ok2 = status in (200, 201, 204)
            print(f"  {'OK ' if ok2 else 'FAIL'} PUT item      HTTP {status}  {resp[:120] if not ok2 else ''}")
            if not ok2:
                fail_count += 1
                continue

        # ── PUT stimulus ───────────────────────────────────────────────────────
        stim_url = QTI_BASE + "/stimuli/" + stim_id
        stim_title = (repl.get("question") or repl.get("template_id") or stim_id)[:120]
        stim_body = {"identifier": stim_id, "title": stim_title, "content": stim_content}
        status, resp = _put_json(stim_url, stim_body, tok)
        if status not in (200, 201, 204):
            # fall back: merge with existing
            existing = _get_existing(stim_url, tok)
            if existing:
                existing.update(stim_body)
                status, resp = _put_json(stim_url, existing, tok)
        ok_s = status in (200, 201, 204)
        print(f"  {'OK ' if ok_s else 'FAIL'} PUT stim      HTTP {status}  {resp[:120] if not ok_s else ''}")

        # ── PATCH child ALI title ──────────────────────────────────────────────
        child_ali_url = GB + "/" + slot["child_ali_id"]
        ali = _get_existing(child_ali_url, tok)
        if ali:
            ali_body = ali.get("assessmentLineItem", ali)
            new_title = ("PowerPath Question: %s" % qstem)[:240]
            ali_body["title"] = new_title
            ali_body["description"] = new_title
            status, resp = _put_json(
                child_ali_url,
                {"assessmentLineItem": ali_body},
                tok,
            )
            if status not in (200, 201, 204):
                status, resp = _put_json(child_ali_url, ali_body, tok)
            ok_a = status in (200, 201, 204)
            print(f"  {'OK ' if ok_a else 'WARN'} PUT ALI title HTTP {status}  {resp[:120] if not ok_a else ''}")
        else:
            print(f"  WARN ALI {slot['child_ali_id']} not found (404) — title not updated")

        ok_count += 1

    print(f"\n=== DONE ===")
    print(f"  Patched:  {ok_count}")
    print(f"  Skipped:  {skip_count}")
    print(f"  Failed:   {fail_count}")
    print(f"\nCourse: https://app.alpha-build.org/content/{PRE}")


if __name__ == "__main__":
    main()
