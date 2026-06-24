#!/usr/bin/env python3
"""
assemble_dryrun.py — LOCAL-ONLY dry-run assembler for the questions->course path.

WHAT THIS IS
  Takes a synthetic G5 pilot (1 passage + 12 items in 6 formats) and renders EACH
  item to QTI 3.0 rawXml, stamps metadata (humanApproved:false + the item's RL.5/
  RI.5/L.5 learningObjectiveSet), and assembles a powerpath-style test.json that
  references all 12. It writes artifacts to disk ONLY — it never mints a token,
  never opens a socket, never POSTs to OneRoster/QTI. The pilot passage is
  synthetic and must not touch a real course.

  This proves RENDERING + ASSEMBLY locally. Live OneRoster/QTI wiring is proven
  SEPARATELY by deploy_cc_extra.py (which live-deployed mcq/msq/order). The
  sequence/match/ebsr/hot-text rendering here is the part that adapter never
  exercised live, so the QTI it emits is validated only for XML well-formedness
  offline (xml.dom.minidom) — not against the QTI service /validate endpoint.

RENDERER LINEAGE
  QTI shape (SCORE_DECL / RP_SINGLE / RP_EBSR / modal feedback / inline passage)
  is lifted verbatim from examples/v2_wire_transfer.py + examples/deploy_cc_extra.py.
  The test.json shape is publish_powerpath.test_json. The build_qti below is a NEW
  adapter for the pilot's flat-options item shape ({type, stem, options:[{id,text,
  part?,side?}], key, feedback, ccss}); the upstream adapters used different shapes
  (ebsr subobjects, passage-derived hottext spans, no match decoy bucket), so each
  of those formats needed a renderer extension. See FORMAT NOTES per branch.

USAGE
  python3 assemble_dryrun.py                       # uses /tmp/g5_pilot_synthetic.json
  python3 assemble_dryrun.py --pilot path.json     # custom pilot
  python3 assemble_dryrun.py --out dir/            # custom output dir
"""
import argparse
import json
import os
import re
import sys
import xml.dom.minidom as MD
from xml.sax.saxutils import escape as esc

# ---- defaults -------------------------------------------------------------
DEFAULT_PILOT = "/tmp/g5_pilot_synthetic.json"
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_lesson")
# A synthetic, clearly-fake QTI base. NEVER hit — only stamped into hrefs so the
# emitted test.json has the same shape publish_powerpath would POST.
ITEM_BASE = "https://LOCAL-DRYRUN.invalid/qti/v3p0/assessment-items"

# ---- QTI scaffolding (verbatim from v2_wire_transfer.py / deploy_cc_extra.py) ----
SCORE_DECL = ('<qti-outcome-declaration identifier="SCORE" cardinality="single" base-type="float">'
              '<qti-default-value><qti-value>0</qti-value></qti-default-value></qti-outcome-declaration>'
              '<qti-outcome-declaration identifier="FEEDBACK" cardinality="single" base-type="identifier"/>')
RP_SINGLE = ('<qti-response-processing><qti-response-condition><qti-response-if>'
    '<qti-match><qti-variable identifier="RESPONSE"/><qti-correct identifier="RESPONSE"/></qti-match>'
    '<qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>'
    '<qti-set-outcome-value identifier="FEEDBACK"><qti-base-value base-type="identifier">CORRECT</qti-base-value></qti-set-outcome-value>'
    '</qti-response-if><qti-response-else>'
    '<qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>'
    '<qti-set-outcome-value identifier="FEEDBACK"><qti-base-value base-type="identifier">INCORRECT</qti-base-value></qti-set-outcome-value>'
    '</qti-response-else></qti-response-condition></qti-response-processing>')
# EBSR scores only when BOTH parts are correct (RESPONSE_A AND RESPONSE_B). Verbatim
# from v2_wire_transfer.RP_EBSR.
RP_EBSR = ('<qti-response-processing><qti-response-condition><qti-response-if><qti-and>'
    '<qti-match><qti-variable identifier="RESPONSE_A"/><qti-correct identifier="RESPONSE_A"/></qti-match>'
    '<qti-match><qti-variable identifier="RESPONSE_B"/><qti-correct identifier="RESPONSE_B"/></qti-match></qti-and>'
    '<qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">1</qti-base-value></qti-set-outcome-value>'
    '<qti-set-outcome-value identifier="FEEDBACK"><qti-base-value base-type="identifier">CORRECT</qti-base-value></qti-set-outcome-value>'
    '</qti-response-if><qti-response-else>'
    '<qti-set-outcome-value identifier="SCORE"><qti-base-value base-type="float">0</qti-base-value></qti-set-outcome-value>'
    '<qti-set-outcome-value identifier="FEEDBACK"><qti-base-value base-type="identifier">INCORRECT</qti-base-value></qti-set-outcome-value>'
    '</qti-response-else></qti-response-condition></qti-response-processing>')

FB_INCORRECT = {
    "mcq": "Not quite. Reread the passage and find the exact words that answer the question.",
    "msq": "Not quite. This question has more than one correct choice — pick every option the text supports, and only those.",
    "hot-text": "Not quite. Reread the passage and click the sentence that actually answers the question.",
    "sequence": "Not quite. Put the steps back in the order they happen in the passage, from first to last.",
    "match": "Not quite. Match each item to the partner the text actually links it with; check every pair.",
    "ebsr": "Not quite. Your Part B sentence must directly support the idea you chose in Part A. Re-read and pick the evidence that fits.",
}

# canonical type normalization (mirrors the grader's aliases)
_TYPE_ALIASES = {
    "mcq": "mcq", "single-select": "mcq", "single_select": "mcq", "multiple-choice": "mcq",
    "msq": "msq", "multi-select": "msq", "multi_select": "msq", "multiple-select": "msq",
    "hot-text": "hot-text", "hottext": "hot-text", "hot_text": "hot-text",
    "ebsr": "ebsr", "evidence-based": "ebsr", "two-part": "ebsr",
    "sequence": "sequence", "order": "sequence", "ordering": "sequence", "sequencing": "sequence",
    "match": "match", "matching": "match", "pairs": "match",
}


def norm_type(t):
    return _TYPE_ALIASES.get((t or "").strip().lower(), "mcq")


def modal(fmt, correct_text):
    return ('<qti-modal-feedback outcome-identifier="FEEDBACK" identifier="CORRECT" show-hide="show">'
            f'<qti-content-body><p>{esc(correct_text)}</p></qti-content-body></qti-modal-feedback>'
            '<qti-modal-feedback outcome-identifier="FEEDBACK" identifier="INCORRECT" show-hide="show">'
            f'<qti-content-body><p>{esc(FB_INCORRECT.get(fmt, FB_INCORRECT["mcq"]))}</p></qti-content-body></qti-modal-feedback>')


def passage_html(text):
    return "".join(f"<p>{esc(p)}</p>" for p in (text or "").split("\n") if p.strip())


def _key_list(key):
    """Normalize a key into a flat list of string tokens (scalar, list, or 'a, b' / 'L1-R1, ...')."""
    if isinstance(key, (list, tuple)):
        return [str(k).strip() for k in key]
    if isinstance(key, str):
        return [p.strip() for p in key.split(",") if p.strip()]
    return [str(key).strip()]


# ──────────────────────────── build_qti ────────────────────────────
def build_qti(item, iid, passage_text):
    """
    Render ONE pilot item to QTI 3.0. Returns (xml, corr_val, err).
    Pilot item shape: {type, stem, options:[{id,text,part?,side?}], key, feedback, ccss}.
    corr_val is the canonical correct response (used only to mirror the verify shape
    deploy_cc_extra would POST; nothing is posted here).
    """
    t = norm_type(item.get("type"))
    prompt = esc(item.get("stem", ""))
    opts = item.get("options") or []
    fb_correct = item.get("feedback") or "Correct."
    body_passage = passage_html(passage_text)

    def choices(ol):
        return "".join(
            f'<qti-simple-choice identifier="{esc(str(o["id"]))}">{esc(o.get("text",""))}</qti-simple-choice>'
            for o in ol)

    # ---- mcq : single qti-choice-interaction (lineage: deploy_cc_extra mcq) ----
    if t == "mcq":
        corr = _key_list(item.get("key"))
        idset = {str(o["id"]) for o in opts}
        if len(corr) != 1 or corr[0] not in idset:
            return None, None, "mcq key must be exactly one real option id"
        rd = (f'<qti-response-declaration identifier="RESPONSE" cardinality="single" base-type="identifier">'
              f'<qti-correct-response><qti-value>{esc(corr[0])}</qti-value></qti-correct-response>'
              f'</qti-response-declaration>')
        inter = (f'<qti-choice-interaction response-identifier="RESPONSE" max-choices="1" shuffle="true">'
                 f'<qti-prompt>{prompt}</qti-prompt>{choices(opts)}</qti-choice-interaction>')
        rp, corr_val = RP_SINGLE, corr[0]

    # ---- msq : multi-cardinality qti-choice-interaction (lineage: deploy_cc_extra msq) ----
    elif t == "msq":
        cs = _key_list(item.get("key"))
        idset = {str(o["id"]) for o in opts}
        if not cs or not set(cs) <= idset:
            return None, None, "msq key not a subset of option ids"
        rd = ('<qti-response-declaration identifier="RESPONSE" cardinality="multiple" base-type="identifier">'
              '<qti-correct-response>' + "".join(f"<qti-value>{esc(c)}</qti-value>" for c in cs)
              + '</qti-correct-response></qti-response-declaration>')
        inter = (f'<qti-choice-interaction response-identifier="RESPONSE" max-choices="0" shuffle="true">'
                 f'<qti-prompt>{prompt}</qti-prompt>{choices(opts)}</qti-choice-interaction>')
        rp, corr_val = RP_SINGLE, cs

    # ---- hot-text : qti-hottext-interaction over EXPLICIT pilot spans ----
    # FORMAT NOTE (extension): v2_wire_transfer derived spans by sentence-splitting the
    # passage and keyed by INDEX. The pilot ships explicit {id,text} spans with a span-id
    # key, so we render each option as its own <qti-hottext> carrying the pilot's own id.
    elif t == "hot-text":
        if len(opts) < 2:
            return None, None, "hot-text needs >= 2 spans"
        cs = _key_list(item.get("key"))
        idset = {str(o["id"]) for o in opts}
        if not cs or not set(cs) <= idset:
            return None, None, "hot-text key span(s) not among offered spans"
        card = "single" if len(cs) == 1 else "multiple"
        mc = "1" if card == "single" else "0"
        spans = " ".join(
            f'<qti-hottext identifier="{esc(str(o["id"]))}">{esc(o.get("text",""))}</qti-hottext>'
            for o in opts)
        rd = (f'<qti-response-declaration identifier="RESPONSE" cardinality="{card}" base-type="identifier">'
              '<qti-correct-response>' + "".join(f"<qti-value>{esc(c)}</qti-value>" for c in cs)
              + '</qti-correct-response></qti-response-declaration>')
        inter = (f'<qti-hottext-interaction response-identifier="RESPONSE" max-choices="{mc}">'
                 f'<qti-prompt>{prompt}</qti-prompt><p>{spans}</p></qti-hottext-interaction>')
        rp, corr_val = RP_SINGLE, (cs[0] if card == "single" else cs)

    # ---- ebsr : TWO response-declarations + TWO interactions from a FLAT options list ----
    # FORMAT NOTE (extension): v2_wire_transfer read ebsr_partA / ebsr_partB subobjects.
    # The pilot ships one flat options list partitioned by a per-option "part":"A"/"B"
    # field, with key=[partA_id, partB_id]. We split on "part", route the two keyed ids
    # into RESPONSE_A / RESPONSE_B, and gate scoring with RP_EBSR (both parts must match).
    elif t == "ebsr":
        a_opts = [o for o in opts if str(o.get("part", "")).strip().upper() == "A"]
        b_opts = [o for o in opts if str(o.get("part", "")).strip().upper() == "B"]
        if not a_opts or not b_opts:
            return None, None, "ebsr needs both Part A and Part B options (via 'part' field)"
        cs = _key_list(item.get("key"))
        a_ids = {str(o["id"]) for o in a_opts}
        b_ids = {str(o["id"]) for o in b_opts}
        ca = next((c for c in cs if c in a_ids), None)
        cb = next((c for c in cs if c in b_ids), None)
        if ca is None or cb is None:
            return None, None, "ebsr key must resolve one Part A id and one Part B id"
        rd = (f'<qti-response-declaration identifier="RESPONSE_A" cardinality="single" base-type="identifier">'
              f'<qti-correct-response><qti-value>{esc(ca)}</qti-value></qti-correct-response></qti-response-declaration>'
              f'<qti-response-declaration identifier="RESPONSE_B" cardinality="single" base-type="identifier">'
              f'<qti-correct-response><qti-value>{esc(cb)}</qti-value></qti-correct-response></qti-response-declaration>')
        inter = (f'<qti-choice-interaction response-identifier="RESPONSE_A" max-choices="1" shuffle="true">'
                 f'<qti-prompt>Part A</qti-prompt>{choices(a_opts)}</qti-choice-interaction>'
                 f'<qti-choice-interaction response-identifier="RESPONSE_B" max-choices="1" shuffle="true">'
                 f'<qti-prompt>Part B</qti-prompt>{choices(b_opts)}</qti-choice-interaction>')
        rp, corr_val = RP_EBSR, {"RESPONSE_A": ca, "RESPONSE_B": cb}

    # ---- sequence : qti-order-interaction (lineage: deploy_cc_extra order) ----
    # FORMAT NOTE: pilot stores steps SHUFFLED vs key (anti-leak), key = ordered id list.
    # The order-interaction declares the correct order; shuffle="true" presents them mixed.
    elif t == "sequence":
        cs = _key_list(item.get("key"))
        idset = {str(o["id"]) for o in opts}
        if set(cs) != idset or len(cs) != len(opts):
            return None, None, "sequence key must be a permutation of all step ids"
        rd = ('<qti-response-declaration identifier="RESPONSE" cardinality="ordered" base-type="identifier">'
              '<qti-correct-response>' + "".join(f"<qti-value>{esc(c)}</qti-value>" for c in cs)
              + '</qti-correct-response></qti-response-declaration>')
        # present the steps in their STORED (shuffled) order; shuffle="true" further mixes
        inter = (f'<qti-order-interaction response-identifier="RESPONSE" shuffle="true">'
                 f'<qti-prompt>{prompt}</qti-prompt>{choices(opts)}</qti-order-interaction>')
        rp, corr_val = RP_SINGLE, cs

    # ---- match : qti-match-interaction with an UNUSED decoy right bucket ----
    # FORMAT NOTE (extension): v2_wire_transfer built lefts/rights from match_pairs, so
    # every right was used (no decoy). The pilot ships a flat options list with a "side"
    # field (left/right) where one right bucket is intentionally UNUSED, and key="L1-R1,
    # L2-R2, L3-R3". We carry ALL right buckets (decoy included) into the match set so the
    # decoy renders, and declare only the keyed pairs as the correct directedPairs.
    elif t == "match":
        lefts = [o for o in opts if str(o.get("side", "")).strip().lower() in ("left", "l")]
        rights = [o for o in opts if str(o.get("side", "")).strip().lower() in ("right", "r")]
        if not lefts or not rights:
            return None, None, "match needs left and right buckets (via 'side' field)"
        lids = {str(o["id"]) for o in lefts}
        rids = {str(o["id"]) for o in rights}
        pairs = []
        for tok in _key_list(item.get("key")):
            m = re.split(r'[-:=]', tok, maxsplit=1)
            if len(m) != 2:
                return None, None, f"match pair token {tok!r} not 'L-R'"
            l, r = m[0].strip(), m[1].strip()
            if l not in lids or r not in rids:
                return None, None, f"match pair {tok!r} references unknown bucket"
            pairs.append((l, r))
        used_rights = {r for _, r in pairs}
        if not (rids - used_rights):
            return None, None, "match has no unused decoy right bucket (anti-leak)"
        # directedPair correct responses: "L R"
        rd = ('<qti-response-declaration identifier="RESPONSE" cardinality="multiple" base-type="directedPair">'
              '<qti-correct-response>'
              + "".join(f"<qti-value>{esc(l)} {esc(r)}</qti-value>" for l, r in pairs)
              + '</qti-correct-response></qti-response-declaration>')
        # match-max="1" per left; rights left open (a right may be a decoy / reusable)
        ls = "".join(
            f'<qti-simple-associable-choice identifier="{esc(str(o["id"]))}" match-max="1">'
            f'{esc(o.get("text",""))}</qti-simple-associable-choice>' for o in lefts)
        rs = "".join(
            f'<qti-simple-associable-choice identifier="{esc(str(o["id"]))}" match-max="1">'
            f'{esc(o.get("text",""))}</qti-simple-associable-choice>' for o in rights)
        inter = (f'<qti-match-interaction response-identifier="RESPONSE" max-associations="0" shuffle="true">'
                 f'<qti-prompt>{prompt}</qti-prompt>'
                 f'<qti-simple-match-set>{ls}</qti-simple-match-set>'
                 f'<qti-simple-match-set>{rs}</qti-simple-match-set></qti-match-interaction>')
        rp, corr_val = RP_SINGLE, [f"{l} {r}" for l, r in pairs]

    else:
        return None, None, f"unsupported type {item.get('type')!r}"

    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<qti-assessment-item xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0" identifier="{esc(iid)}" '
           f'title="{esc(item.get("stem","")[:120])}" adaptive="false" time-dependent="false">'
           f'{rd}{SCORE_DECL}<qti-item-body>{body_passage}{inter}</qti-item-body>{rp}{modal(t, fb_correct)}'
           f'</qti-assessment-item>')
    return xml, corr_val, None


# ──────────────────────────── metadata ────────────────────────────
def item_metadata(item):
    """Stamp humanApproved:false + the item's RL.5/RI.5/L.5 learningObjectiveSet.
    Mirrors the metadata body deploy_cc_extra POSTs (CASE source, learningObjectiveIds)."""
    ccss = item.get("ccss")
    codes = ccss if isinstance(ccss, list) else [c.strip() for c in str(ccss or "").replace(",", " ").split() if c.strip()]
    return {
        "subject": "Reading",
        "grade": "5",
        "difficulty": item.get("difficulty", "medium"),
        "humanApproved": False,
        "learningObjectiveSet": [{"source": "CASE", "learningObjectiveIds": codes}],
    }


def test_json(test_id, title, item_ids, item_base):
    """publish_powerpath.test_json — one linear test-part -> one section -> all item-refs."""
    refs = [{"identifier": i, "href": "%s/%s" % (item_base, i)} for i in item_ids]
    return {"identifier": test_id, "title": title,
            "qti-test-part": [{"identifier": "tp0", "navigationMode": "linear",
                "submissionMode": "individual",
                "qti-assessment-section": [{"identifier": "s0", "title": "items", "visible": True,
                    "required": True, "fixed": False, "sequence": 1,
                    "qti-assessment-item-ref": refs}]}],
            "qti-outcome-declaration": [{"identifier": "SCORE", "cardinality": "single", "baseType": "float"}]}


def iid_of(passage_id, idx, item):
    base = re.sub(r'[^a-z0-9]+', '-', (passage_id or "g5").lower()).strip('-')
    return f"g5dry-{base}-{idx:02d}-{norm_type(item.get('type'))}"


# ──────────────────────────── preview ────────────────────────────
def render_preview(passage, rows):
    out = []
    out.append("# G5 PILOT — DRY-RUN ASSEMBLY PREVIEW")
    out.append("")
    out.append("> LOCAL-ONLY. Nothing here was posted to OneRoster/QTI. The passage is "
               "synthetic. Rendering + assembly proven here; live wiring proven separately "
               "by deploy_cc_extra.py.")
    out.append("")
    out.append("All items stamped `humanApproved: false`.")
    out.append("")
    out.append("## Passage")
    out.append("")
    out.append(f"**{passage.get('title','(untitled)')}**  ")
    out.append(f"_genre: {passage.get('genre','?')} · lexile: {passage.get('lexile','?')} · "
               f"id: `{passage.get('id','?')}`_")
    out.append("")
    for para in (passage.get("text", "") or "").split("\n"):
        if para.strip():
            out.append(para.strip())
            out.append("")
    out.append("---")
    out.append("")
    out.append("## Items (12)")
    out.append("")
    for r in rows:
        item = r["item"]
        t = norm_type(item.get("type"))
        out.append(f"### Item {r['idx']+1} — `{t}`  (status: {r['status']})")
        out.append("")
        out.append(f"- **id:** `{r['iid']}`  ")
        out.append(f"- **format:** {t}  ")
        out.append(f"- **ccss / learningObjectiveSet:** {', '.join(r['codes']) or '(none)'}  ")
        out.append(f"- **difficulty:** {item.get('difficulty','?')}  ")
        out.append(f"- **xml file:** `{r['xml_file']}`")
        out.append("")
        out.append(f"**Stem:** {item.get('stem','').strip()}")
        out.append("")
        keyset = set(_key_list(item.get("key")))
        if t == "match":
            lefts = [o for o in item.get("options", []) if str(o.get("side","")).lower() in ("left","l")]
            rights = [o for o in item.get("options", []) if str(o.get("side","")).lower() in ("right","r")]
            pairs = {}
            for tok in _key_list(item.get("key")):
                m = re.split(r'[-:=]', tok, maxsplit=1)
                if len(m) == 2:
                    pairs[m[0].strip()] = m[1].strip()
            used_rights = set(pairs.values())
            out.append("**Left buckets:**")
            for o in lefts:
                tgt = pairs.get(str(o["id"]))
                tgt_txt = next((rr.get("text") for rr in rights if str(rr["id"]) == tgt), tgt)
                out.append(f"- `{o['id']}` {o.get('text','')}  →  **[KEY]** `{tgt}` {tgt_txt}")
            out.append("")
            out.append("**Right buckets:**")
            for o in rights:
                tag = "  ← **DECOY (unused)**" if str(o["id"]) not in used_rights else ""
                out.append(f"- `{o['id']}` {o.get('text','')}{tag}")
            out.append("")
        elif t == "ebsr":
            a_opts = [o for o in item.get("options", []) if str(o.get("part","")).upper() == "A"]
            b_opts = [o for o in item.get("options", []) if str(o.get("part","")).upper() == "B"]
            out.append("**Part A options:**")
            for o in a_opts:
                mark = "  ← **[KEY]**" if str(o["id"]) in keyset else ""
                out.append(f"- `{o['id']}` {o.get('text','')}{mark}")
            out.append("")
            out.append("**Part B options (evidence):**")
            for o in b_opts:
                mark = "  ← **[KEY]**" if str(o["id"]) in keyset else ""
                out.append(f"- `{o['id']}` {o.get('text','')}{mark}")
            out.append("")
        elif t == "sequence":
            keyorder = _key_list(item.get("key"))
            out.append("**Steps (stored / shuffled order):**")
            for o in item.get("options", []):
                out.append(f"- `{o['id']}` {o.get('text','')}")
            out.append("")
            out.append("**Correct order [KEY]:** " + " → ".join(f"`{k}`" for k in keyorder))
            out.append("")
        else:  # mcq / msq / hot-text
            label = "Spans" if t == "hot-text" else "Options"
            out.append(f"**{label}:**")
            for o in item.get("options", []):
                mark = "  ← **[KEY]**" if str(o["id"]) in keyset else ""
                out.append(f"- `{o['id']}` {o.get('text','')}{mark}")
            out.append("")
        fb = item.get("feedback", "")
        out.append(f"**Feedback (correct):** {fb}")
        out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out)


# ──────────────────────────── main ────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", default=DEFAULT_PILOT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()

    if not os.path.exists(a.pilot):
        sys.stderr.write(f"ERROR: pilot not found: {a.pilot}\n")
        return 2
    data = json.load(open(a.pilot, encoding="utf-8"))
    passage = data.get("passage", {})
    items = data.get("items", [])
    if not items:
        sys.stderr.write("ERROR: no items in pilot\n")
        return 2

    os.makedirs(a.out, exist_ok=True)
    passage_id = passage.get("id", "g5")

    print("=" * 72)
    print("ASSEMBLE DRY-RUN (LOCAL ONLY — no network, no OneRoster/QTI writes)")
    print(f"pilot:   {a.pilot}")
    print(f"passage: {passage.get('title')!r}  ({passage_id})")
    print(f"items:   {len(items)}")
    print(f"out:     {a.out}")
    print("=" * 72)

    rows = []
    item_ids = []
    metas = {}
    by_fmt = {}
    n_render_ok = n_xml_ok = 0
    fails = []

    for idx, item in enumerate(items):
        t = norm_type(item.get("type"))
        iid = iid_of(passage_id, idx, item)
        xml, corr, err = build_qti(item, iid, passage.get("text", ""))
        rec = {"idx": idx, "item": item, "iid": iid,
               "codes": item_metadata(item)["learningObjectiveSet"][0]["learningObjectiveIds"]}
        by_fmt.setdefault(t, {"render": 0, "xml": 0, "fail": 0})
        if not xml:
            fails.append((iid, t, err))
            by_fmt[t]["fail"] += 1
            rec.update({"status": "RENDER-FAIL: " + (err or "?"), "xml_file": "(none)"})
            rows.append(rec)
            print(f"[#{idx}] {t:9} RENDER-FAIL  {err}")
            continue
        n_render_ok += 1
        by_fmt[t]["render"] += 1
        # offline well-formedness check (the only validation we can do without the QTI service)
        xml_ok = False
        try:
            MD.parseString(xml)
            xml_ok = True
            n_xml_ok += 1
            by_fmt[t]["xml"] += 1
        except Exception as e:
            fails.append((iid, t, "malformed-xml: " + str(e)))

        xml_file = iid + ".xml"
        with open(os.path.join(a.out, xml_file), "w", encoding="utf-8") as f:
            f.write(xml)
        item_ids.append(iid)
        metas[iid] = item_metadata(item)
        rec.update({"status": "OK (xml well-formed)" if xml_ok else "XML-MALFORMED",
                    "xml_file": xml_file, "corr": corr})
        rows.append(rec)
        print(f"[#{idx}] {t:9} rendered -> {xml_file}   xml_ok={xml_ok}   ccss={rec['codes']}")

    # ---- assemble the test.json (publish_powerpath shape) ----
    test_id = f"g5dry-{re.sub(r'[^a-z0-9]+','-',passage_id.lower()).strip('-')}-test"
    title = f"G5 dry-run — {passage.get('title','pilot')}"
    test = test_json(test_id, title, item_ids, ITEM_BASE)
    # attach the per-item metadata bodies so the assembled artifact is self-describing
    # (publish_powerpath posts these to /assessment-items/metadata separately; here we
    #  carry them alongside so a reviewer sees the full stamped shape in one file).
    bundle = {
        "_dry_run": True,
        "_note": "LOCAL ONLY. Not posted. item_base is a deliberately-invalid host. "
                 "Live OneRoster/QTI wiring is proven separately by deploy_cc_extra.py.",
        "_passage": {"id": passage_id, "title": passage.get("title"),
                     "genre": passage.get("genre"), "lexile": passage.get("lexile")},
        "test": test,
        "item_metadata": metas,
    }
    test_path = os.path.join(a.out, "test.json")
    with open(test_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    # ---- preview ----
    preview = render_preview(passage, rows)
    preview_path = os.path.join(a.out, "PREVIEW.md")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(preview)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print(f"  rendered (build_qti ok) ... {n_render_ok}/{len(items)}")
    print(f"  xml well-formed ........... {n_xml_ok}/{len(items)}")
    print(f"  in assembled test ......... {len(item_ids)}")
    print("  per-format (render/xml-ok/fail):")
    for fmt in sorted(by_fmt):
        c = by_fmt[fmt]
        print(f"    {fmt:10} {c['render']} render / {c['xml']} xml-ok / {c['fail']} fail")
    if fails:
        print("  FAILURES:")
        for iid, t, err in fails:
            print(f"    {t:9} {iid}: {err}")
    print("\n  ARTIFACTS:")
    print(f"    test.json   -> {test_path}")
    print(f"    PREVIEW.md  -> {preview_path}")
    print(f"    {len(item_ids)} item XMLs in {a.out}")
    print("=" * 72)
    return 0 if (n_render_ok == len(items) and n_xml_ok == len(items)) else 1


if __name__ == "__main__":
    sys.exit(main())
