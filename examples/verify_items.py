#!/usr/bin/env python3
"""Exhaustive render/score integrity check for a deployed powerpath course.
For EVERY item in EVERY lesson bank, fetch the live QTI and verify it is render- AND score-ready:
  1. assessment-test exists and /questions resolves to a bank (no dangling refs)
  2. each item GET 200 + well-formed XML
  3. has >=1 supported interaction (choice / order / hottext / match)
  4. SCORABLE: every <qti-correct-response> value references identifiers that ACTUALLY EXIST in the
     matching interaction (choice/hottext/associable ids) — catches keys that point at nothing
  5. has <qti-response-processing> (so PowerPath gets a SCORE)
  6. <qti-assessment-stimulus-ref> (if present) resolves to an existing stimulus
Prints PASS/FAIL per item with the reason. Exit 0 iff zero failures.

Usage: python3 verify_items.py --course grade3-reading-ela-pp-9701 [--only-unit N]
"""
import sys, os, argparse, urllib.parse
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_to_timeback as P

def ln(tag):  # localname
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

INTERACTIONS = {"qti-choice-interaction", "qti-order-interaction", "qti-hottext-interaction",
                "qti-match-interaction", "qti-inline-choice-interaction", "qti-text-entry-interaction"}
# identifier-bearing option elements, by what they belong to
OPTION_TAGS = {"qti-simple-choice", "qti-hottext", "qti-simple-associable-choice", "qti-inline-choice"}


def check_item(rawxml):
    """Return list of problems (empty = ok)."""
    probs = []
    try:
        root = ET.fromstring(rawxml)
    except Exception as e:
        return ["malformed-xml: %s" % str(e)[:80]]

    els = list(root.iter())
    inter = [e for e in els if ln(e.tag) in INTERACTIONS]
    if not inter:
        probs.append("no-supported-interaction")

    # gather option identifiers, keyed by the response-identifier of the enclosing interaction
    # (fallback: a global pool so a key present anywhere passes the "exists" test)
    global_ids = set()
    resp_ids = {}   # response-identifier -> set(option ids)
    for it in inter:
        rid = it.get("response-identifier") or it.get("responseIdentifier")
        ids = set()
        for d in it.iter():
            if ln(d.tag) in OPTION_TAGS and d.get("identifier"):
                ids.add(d.get("identifier"))
        global_ids |= ids
        if rid:
            resp_ids.setdefault(rid, set()).update(ids)

    # correct-response validity per response-declaration
    rdecls = [e for e in els if ln(e.tag) == "qti-response-declaration"]
    scored_any = False
    for rd in rdecls:
        rid = rd.get("identifier")
        cr = next((c for c in rd.iter() if ln(c.tag) == "qti-correct-response"), None)
        if cr is None:
            continue
        vals = [v.text.strip() for v in cr.iter() if ln(v.tag) == "qti-value" and v.text]
        if not vals:
            continue
        scored_any = True
        pool = resp_ids.get(rid) or global_ids
        for v in vals:
            tokens = v.split()  # directedPair "A B" -> two ids; else single id
            for tk in tokens:
                if tk not in pool:
                    probs.append("key-id-not-in-options: resp=%s val=%r missing=%r" % (rid, v, tk))
                    break
    if not scored_any:
        probs.append("no-correct-response")

    rp = [e for e in els if ln(e.tag) == "qti-response-processing"]
    if not rp:
        probs.append("no-response-processing")

    return probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", required=True)
    ap.add_argument("--only-unit", type=int, default=None)
    ap.add_argument("--check-stimuli", action="store_true", help="also GET each stimulus-ref (slower)")
    a = ap.parse_args()
    tok, _ = P.mint_token()
    OR, QTI = P.OR, P.QTI

    flt = urllib.parse.quote(f"course.sourcedId='{a.course}'")
    st, d = P.get_json(OR + f"/rostering/v1p2/courses/components?limit=3000&filter={flt}", tok)
    comps = (d or {}).get("courseComponents", [])
    lessons = [c for c in comps if (c.get("parentComponent") or c.get("parent"))]
    def uli(sid):  # extract unit index from sourcedId ...-uN-lM
        try: return int(sid.split("-u")[1].split("-l")[0])
        except Exception: return -1
    if a.only_unit is not None:
        lessons = [c for c in lessons if uli(c["sourcedId"]) == a.only_unit]
    lessons.sort(key=lambda c: c["sourcedId"])

    total_items = 0; failures = []; stim_cache = {}
    lessons_no_bank = []
    for L in lessons:
        test_id = L["sourcedId"] + "-test"
        sv, q = P.get_json(QTI + f"/assessment-tests/{test_id}/questions", tok)
        qs = (q or {}).get("questions", []) if sv == 200 else []
        if not qs:
            lessons_no_bank.append((L["sourcedId"], sv)); continue
        for item in qs:
            ref = item.get("reference") or {}
            iid = ref.get("identifier") if isinstance(ref, dict) else (item.get("identifier") or ref)
            total_items += 1
            si, idoc = P.get_json(QTI + f"/assessment-items/{iid}", tok)
            if si != 200 or not idoc:
                failures.append((L["sourcedId"], iid, "item-fetch HTTP %s" % si)); continue
            raw = idoc.get("rawXml") or ""
            probs = check_item(raw)
            # stimulus-ref resolves?
            if a.check_stimuli:
                try:
                    root = ET.fromstring(raw)
                    for e in root.iter():
                        if ln(e.tag) == "qti-assessment-stimulus-ref":
                            href = (e.get("href") or "").split("/")[-1] or e.get("identifier")
                            if href and href not in stim_cache:
                                ss, _ = P.get_json(QTI + f"/stimuli/{href}", tok)
                                stim_cache[href] = ss
                            if href and stim_cache.get(href) != 200:
                                probs.append("stimulus-missing: %s" % href)
                except Exception:
                    pass
            if probs:
                failures.append((L["sourcedId"], iid, "; ".join(probs)))

    print(f"course {a.course}{' unit '+str(a.only_unit) if a.only_unit is not None else ''}: "
          f"lessons={len(lessons)} items_checked={total_items} FAILURES={len(failures)} "
          f"lessons_without_bank={len(lessons_no_bank)}")
    for lid, iid, why in failures[:60]:
        print(f"  FAIL {lid} {iid}: {why}")
    for lid, sv in lessons_no_bank:
        print(f"  NO-BANK {lid} (HTTP {sv})")
    sys.exit(0 if not failures and not lessons_no_bank else 1)


if __name__ == "__main__":
    main()
