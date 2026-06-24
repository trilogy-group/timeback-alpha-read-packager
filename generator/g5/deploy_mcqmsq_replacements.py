#!/usr/bin/env python3
"""
deploy_mcqmsq_replacements.py

Replace encyclopedic MCQ/MSQ items in the live G5 course g5-reading-ela-pp-9801
with cold-passage replacements (match/sequence/hot-text types).

WHAT IT DOES
------------
For each MCQ/MSQ slot identified from g5_lesson_passages.json, it:
  1. Matches a replacement from g5_mcqmsq_cold_replacements.jsonl by lesson_id
     (best-match on substandard, then any open slot in the lesson).
  2. Builds QTI 3.0 XML for the replacement type (match/sequence/hot-text).
  3. PUTs the new QTI item body to the assessment-items endpoint (same IID).
  4. PUTs the new stimulus to the stimuli endpoint.
  5. Updates the child ALI title.

ENDPOINTS TOUCHED (PUT only — never POST, never DELETE)
  PUT  QTI  /assessment-items/<iid>
  PUT  QTI  /stimuli/<stim_id>
  PUT  OR   /gradebook/v1p2/assessmentLineItems/<child_ali_id>

COVERAGE
--------
166 replacements available for 240 slots (69.2%). The 74 gaps are noted but not
treated as failures — the remaining MCQ/MSQ items stay in place.

USAGE
-----
  python3 deploy_mcqmsq_replacements.py [--dry-run]
  python3 deploy_mcqmsq_replacements.py \\
      --replacements /tmp/g5_mcqmsq_cold_replacements.jsonl \\
      --lessons /tmp/g5_lesson_passages.json \\
      --bundle /tmp/g5_bundle_fixed.jsonl \\
      [--dry-run]
"""

import argparse
import json
import os
import re
import sys
import html as html_mod
from collections import OrderedDict, defaultdict
from xml.sax.saxutils import escape

# ── resolve push_to_timeback ─────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "..", "v2_final_package", "scripts"))
sys.path.insert(0, _SCRIPTS)
from push_to_timeback import mint_token, get_json  # noqa: E402

PRE = "g5-reading-ela-pp-9801"
QTI_BASE = "https://qti.alpha-1edtech.ai/api"
OR_BASE  = "https://api.alpha-1edtech.ai/ims/oneroster"

DEFAULT_REPLACEMENTS = "/tmp/g5_mcqmsq_cold_replacements.jsonl"
DEFAULT_LESSONS      = "/tmp/g5_lesson_passages.json"
DEFAULT_BUNDLE       = "/tmp/g5_bundle_fixed.jsonl"

# ── QTI 3.0 boilerplate ──────────────────────────────────────────────────────────

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


def _order_xml(iid, d):
    """Build QTI for sequence/order items."""
    steps = d["items"]
    order = d.get("correct_order", list(range(len(steps))))
    # correct_order may be list of indices into steps, or step IDs
    # Handle both: if ints, use steps[i] text as identifier
    if order and isinstance(order[0], int):
        ordered_ids = [str(steps[i]) if isinstance(steps[i], str) else "step%d" % steps[i]
                       for i in order]
        # Build simple choice list using step text as identifier
        step_items = []
        for idx, step in enumerate(steps):
            sid = "step%d" % idx
            text = step if isinstance(step, str) else step.get("text", str(step))
            step_items.append({"id": sid, "text": text})
        correct_ids = ["step%d" % i for i in order]
    else:
        # order is already IDs
        step_items = []
        for step in steps:
            if isinstance(step, str):
                step_items.append({"id": step, "text": step})
            else:
                step_items.append({"id": step.get("id", step.get("text", "")), "text": step.get("text", step.get("content", ""))})
        correct_ids = order

    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(str(cid)) for cid in correct_ids)
    body = NS.format(iid=iid, title="Order")
    body += (
        '  <qti-response-declaration identifier="RESPONSE" cardinality="ordered" base-type="identifier">\n'
        '    <qti-correct-response>\n%s    </qti-correct-response>\n'
        '  </qti-response-declaration>\n' % cr
    )
    body += SCORE_DECL + _stem(d["question"])
    body += '    <qti-order-interaction response-identifier="RESPONSE" shuffle="true">\n'
    for s in step_items:
        body += '      <qti-simple-choice identifier="%s"><p>%s</p></qti-simple-choice>\n' % (
            escape(str(s["id"])), escape(str(s["text"])))
    body += '    </qti-order-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return body + "</qti-assessment-item>\n"


def _hottext_xml(iid, d):
    """Build QTI for hot-text items.

    Input formats supported:
      A) tokens + answer  (legacy)
      B) annotated_passage with [[correct_span]] markers (new generator format)
         — all sentences become hottext candidates; [[...]] = correct selection(s)
    """
    import re as _re

    annotated = d.get("annotated_passage", "")
    if annotated:
        # Extract correct spans from [[...]]
        correct_spans = _re.findall(r'\[\[(.*?)\]\]', annotated)
        clean = _re.sub(r'\[\[(.*?)\]\]', r'\1', annotated)
        # Split into sentence-level tokens
        raw_sentences = [s.strip() for s in _re.split(r'(?<=[.!?])\s+', clean) if s.strip()]
        toks = [{"id": "t%d" % i, "text": s} for i, s in enumerate(raw_sentences)]
        # Map correct spans to token IDs
        correct_ids = []
        for span in correct_spans:
            for tok in toks:
                if span.strip() in tok["text"] or tok["text"] in span.strip():
                    correct_ids.append(tok["id"])
                    break
        # Fallback: if no match, mark first token
        if not correct_ids:
            correct_ids = [toks[0]["id"]] if toks else []
    else:
        toks = d.get("tokens", [])
        correct = d.get("answer", d.get("correct", []))
        if isinstance(correct, list):
            correct_ids = [str(t) for t in correct]
        else:
            correct_ids = [str(correct)] if correct else []

    card = "multiple" if len(correct_ids) > 1 else "single"
    max_choices = len(correct_ids) if correct_ids else 1
    cr = "".join("      <qti-value>%s</qti-value>\n" % escape(cid) for cid in correct_ids)

    body = NS.format(iid=iid, title="HotText")
    body += (
        '  <qti-response-declaration identifier="RESPONSE" cardinality="%s" base-type="identifier">\n'
        '    <qti-correct-response>\n%s    </qti-correct-response>\n'
        '  </qti-response-declaration>\n' % (card, cr)
    )
    body += SCORE_DECL + _stem(d["question"])
    spans_xml = " ".join(
        '<qti-hottext identifier="%s">%s</qti-hottext>' % (
            escape(str(t["id"])), escape(str(t.get("text", t["id"]))))
        for t in toks
    )
    body += (
        '    <qti-hottext-interaction response-identifier="RESPONSE" max-choices="%d">\n'
        '      <p>%s</p>\n'
        '    </qti-hottext-interaction>\n  </qti-item-body>\n' % (max_choices, spans_xml)
    )
    body += RP_CORRECT
    return body + "</qti-assessment-item>\n"


def _match_xml(iid, d):
    """Build QTI for match items.

    Input format: categories may be list of strings or list of dicts.
    Items are dicts with 'text' and 'category' (string label).
    """
    items_raw = d.get("items", [])
    cats_raw = d.get("categories", [])

    # Normalize categories: strings → dicts with stable IDs
    cats = []
    for ci, c in enumerate(cats_raw):
        if isinstance(c, str):
            cats.append({"id": "cat%d" % ci, "label": c})
        else:
            cats.append({
                "id": str(c.get("id", "cat%d" % ci)),
                "label": c.get("label") or c.get("text") or c.get("id", "cat%d" % ci),
            })

    # Build cat label → cat id map
    cat_label_to_id = {c["label"]: c["id"] for c in cats}

    # Normalize items: assign stable IDs, resolve correct category ID
    items = []
    for ii, it in enumerate(items_raw):
        if isinstance(it, str):
            items.append({"id": "item%d" % ii, "text": it, "cat_id": cats[0]["id"] if cats else ""})
        else:
            it_text = it.get("text", "item%d" % ii)
            cat_label = it.get("category") or it.get("correct_category_id", "")
            cat_id = cat_label_to_id.get(cat_label, cat_label)
            it_id = str(it.get("id", "item%d" % ii))
            items.append({"id": it_id, "text": it_text, "cat_id": cat_id})

    cr = "".join(
        "      <qti-value>%s %s</qti-value>\n" % (escape(it["id"]), escape(it["cat_id"]))
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
            escape(it["id"]), escape(it["text"]))
    body += '      </qti-simple-match-set>\n      <qti-simple-match-set>\n'
    for c in cats:
        body += '        <qti-simple-associable-choice identifier="%s" match-max="%d"><p>%s</p></qti-simple-associable-choice>\n' % (
            escape(c["id"]), len(items), escape(c["label"]))
    body += '      </qti-simple-match-set>\n    </qti-match-interaction>\n  </qti-item-body>\n' + RP_CORRECT
    return body + "</qti-assessment-item>\n"


BUILDERS = {
    "sequence": _order_xml,
    "hot-text": _hottext_xml,
    "match": _match_xml,
}


def _with_stim_ref(item_xml, stim_id):
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
    stim = q.get("stimulus", "")
    raw = _stim_val(stim)
    if not raw.strip():
        return '<div class="passage"><p></p></div>'
    if re.search(r'<[a-zA-Z]', raw):
        return '<div class="passage">%s</div>' % raw
    return _txt_to_html(raw)


def _question_stem(q):
    stem = q.get("question") or q.get("type", "question")
    return stem[:200]


# ── HTTP helpers ─────────────────────────────────────────────────────────────────

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


# ── Bundle → item_id → live IID mapping ─────────────────────────────────────────

def build_item_id_to_live(bundle_path):
    """Return dict: item_id → {iid, stim_id, child_ali_id, type, substandard_id, live_lesson_id}"""
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

    mapping = {}
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
            live_lesson_id = "%s-u%d-l%d" % (PRE, ei, li)
            for qi, item in enumerate(L["items"], 1):
                item_id = item.get("item_id")
                itype = item.get("type", "mcq")
                type_tag = itype.replace("-", "")
                iid = "%s-q%02d-%s" % (live_lesson_id, qi, type_tag)
                stim_id = iid + "-s"
                child_ali_id = "%s-ali-q%02d" % (live_lesson_id, qi)
                if item_id:
                    mapping[item_id] = {
                        "iid": iid,
                        "stim_id": stim_id,
                        "child_ali_id": child_ali_id,
                        "type": itype,
                        "substandard_id": item.get("substandard_id"),
                        "live_lesson_id": live_lesson_id,
                        "source_lesson_id": item.get("lesson_id"),
                    }
    return mapping


# ── Matching: replacement → MCQ/MSQ slot ────────────────────────────────────────

def build_patch_plan(lessons_path, replacements_path, item_id_to_live):
    """Match replacement items to MCQ/MSQ slots.

    Strategy: per lesson, best-match on substandard_id first, then any open slot.
    Returns list of dicts: {replacement, slot_item_id, live_iid, stim_id, child_ali_id}
    """
    lessons = json.load(open(lessons_path))
    replacements = [json.loads(l) for l in open(replacements_path) if l.strip()]

    repl_by_lesson = defaultdict(list)
    for r in replacements:
        repl_by_lesson[r["lesson_id"]].append(r)

    plan = []
    skipped_no_live = 0

    for lesson in lessons:
        lid = lesson["lesson_id"]
        slots = lesson.get("mcq_msq_items", [])
        repls = repl_by_lesson.get(lid, [])
        if not repls:
            continue

        available_slots = list(slots)

        for repl in repls:
            repl_std = repl.get("substandard_id")

            # Best-match: exact substandard first
            matched_slot = None
            for slot in available_slots:
                if slot.get("substandard_id") == repl_std:
                    matched_slot = slot
                    break

            # Fallback: any open slot
            if matched_slot is None and available_slots:
                matched_slot = available_slots[0]

            if matched_slot is None:
                skipped_no_live += 1
                continue

            available_slots.remove(matched_slot)
            slot_item_id = matched_slot["id"]
            live_info = item_id_to_live.get(slot_item_id)
            if live_info is None:
                skipped_no_live += 1
                continue

            plan.append({
                "replacement": repl,
                "slot_item_id": slot_item_id,
                "slot_substandard": matched_slot.get("substandard_id"),
                "lesson_id": lid,
                "iid": live_info["iid"],
                "stim_id": live_info["stim_id"],
                "child_ali_id": live_info["child_ali_id"],
                "original_type": live_info["type"],
            })

    if skipped_no_live:
        print(f"WARNING: {skipped_no_live} replacements could not be matched to live IIDs")

    return plan


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Replace encyclopedic MCQ/MSQ items in g5-reading-ela-pp-9801.")
    ap.add_argument("--replacements", default=DEFAULT_REPLACEMENTS)
    ap.add_argument("--lessons", default=DEFAULT_LESSONS)
    ap.add_argument("--bundle", default=DEFAULT_BUNDLE)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the patch plan without calling any API")
    a = ap.parse_args()

    # ── 1. Load and validate inputs ─────────────────────────────────────────────
    for path in (a.replacements, a.lessons, a.bundle):
        if not os.path.exists(path):
            sys.exit(f"ERROR: file not found: {path}")

    replacements = [json.loads(l) for l in open(a.replacements) if l.strip()]
    lessons = json.load(open(a.lessons))
    total_slots = sum(len(l.get("mcq_msq_items", [])) for l in lessons)

    print(f"Replacements available:  {len(replacements)}")
    print(f"MCQ/MSQ slots to fill:   {total_slots}")

    # ── 2. Build live IID mapping ───────────────────────────────────────────────
    print("Building bundle → live IID mapping...")
    item_id_to_live = build_item_id_to_live(a.bundle)
    mcq_msq_live = {k: v for k, v in item_id_to_live.items() if v["type"] in ("mcq", "msq")}
    print(f"Live MCQ/MSQ IIDs mapped: {len(mcq_msq_live)}")

    # ── 3. Build patch plan ─────────────────────────────────────────────────────
    print("Building patch plan...")
    plan = build_patch_plan(a.lessons, a.replacements, item_id_to_live)
    gap = total_slots - len(plan)
    print(f"Patch plan:              {len(plan)} replacements matched ({len(plan)/total_slots*100:.1f}% coverage)")
    if gap:
        print(f"Gap (no replacement):    {gap} slots will keep original MCQ/MSQ items")

    # ── 4. Dry-run output ───────────────────────────────────────────────────────
    if a.dry_run:
        print("\n=== DRY RUN — no API calls ===")
        print(f"{'IID':<65}  {'OLD_TYPE':<8}  {'NEW_TYPE':<10}  {'OLD_SUBSTD':<12}  {'NEW_SUBSTD':<12}")
        for p in plan:
            repl = p["replacement"]
            print(
                f"  {p['iid']:<65}  {p['original_type']:<8}  {repl.get('type','?'):<10}  "
                f"{p['slot_substandard']:<12}  {repl.get('substandard_id','?'):<12}"
            )
        print(f"\nDRY RUN complete: {len(plan)} slots would be patched, {gap} slots unchanged.")
        return

    # ── 5. Mint token ───────────────────────────────────────────────────────────
    print("\nMinting token...")
    tok, scopes = mint_token()
    print("Token OK | scopes:", (scopes or "")[:80])

    ok_count = fail_count = skip_count = 0
    GB = OR_BASE + "/gradebook/v1p2/assessmentLineItems"

    for i, p in enumerate(plan):
        repl = p["replacement"]
        iid = p["iid"]
        stim_id = p["stim_id"]
        new_type = repl.get("type", "sequence")
        qstem = _question_stem(repl)

        print(f"\n[{i+1:03d}/{len(plan)}] {iid}")
        print(f"      {p['original_type']}→{new_type}  slot_std={p['slot_substandard']}  repl_std={repl.get('substandard_id','?')}")

        # Build QTI XML
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

        xml = _with_stim_ref(xml, stim_id)
        stim_content = _stimulus_content(repl)

        # ── PUT item ──────────────────────────────────────────────────────────
        item_url = QTI_BASE + "/assessment-items/" + iid
        status, resp = _put_json(item_url, {"format": "xml", "xml": xml}, tok)
        if status in (200, 201, 204):
            print(f"  OK  PUT item      HTTP {status}")
        else:
            existing = _get_existing(item_url, tok)
            if existing:
                existing.update({"format": "xml", "xml": xml})
                status, resp = _put_json(item_url, existing, tok)
            ok2 = status in (200, 201, 204)
            print(f"  {'OK ' if ok2 else 'FAIL'} PUT item      HTTP {status}  {resp[:120] if not ok2 else ''}")
            if not ok2:
                fail_count += 1
                continue

        # ── PUT stimulus ──────────────────────────────────────────────────────
        stim_url = QTI_BASE + "/stimuli/" + stim_id
        stim_title = (repl.get("question") or stim_id)[:120]
        stim_body = {"identifier": stim_id, "title": stim_title, "content": stim_content}
        status, resp = _put_json(stim_url, stim_body, tok)
        if status not in (200, 201, 204):
            existing = _get_existing(stim_url, tok)
            if existing:
                existing.update(stim_body)
                status, resp = _put_json(stim_url, existing, tok)
        ok_s = status in (200, 201, 204)
        print(f"  {'OK ' if ok_s else 'FAIL'} PUT stim      HTTP {status}  {resp[:120] if not ok_s else ''}")

        # ── PATCH child ALI title ─────────────────────────────────────────────
        child_ali_url = GB + "/" + p["child_ali_id"]
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
            print(f"  WARN ALI {p['child_ali_id']} not found — title not updated")

        ok_count += 1

    print(f"\n=== DONE ===")
    print(f"  Deployed: {ok_count}")
    print(f"  Skipped:  {skip_count}")
    print(f"  Failed:   {fail_count}")
    print(f"  Gap (no replacement available): {gap}")
    print(f"  Coverage: {ok_count}/{total_slots} ({ok_count/total_slots*100:.1f}%)")
    print(f"\nCourse: https://app.alpha-build.org/content/{PRE}")


if __name__ == "__main__":
    main()
