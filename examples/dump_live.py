#!/usr/bin/env python3
"""Dump the LIVE/SHIPPED content of one lesson's powerpath bank (what a student actually sees):
fetch the deployed assessment-test, then each item's QTI + its stimulus, and print stem + options
(key marked) + the passage. Use for adversarial QA of the deployed course (post-prune)."""
import sys, os, argparse
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_to_timeback as P

def ln(t): return t.rsplit("}", 1)[-1] if "}" in t else t
def text(e): return " ".join("".join(e.itertext()).split())

def _collect_text(o):
    """Recursively gather prose from the API's parsed-XML dict/list (skip _attributes)."""
    out = []
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, list):
        for x in o: out.append(_collect_text(x))
    elif isinstance(o, dict):
        for k, v in o.items():
            if k == "_attributes": continue
            out.append(_collect_text(v))
    return " ".join(s for s in out if s and s.strip())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", required=True)
    ap.add_argument("--ei", type=int, required=True)
    ap.add_argument("--li", type=int, required=True)
    a = ap.parse_args()
    tok, _ = P.mint_token(); QTI = P.QTI
    test = f"{a.course}-u{a.ei}-l{a.li}-test"
    sv, q = P.get_json(QTI + f"/assessment-tests/{test}/questions", tok)
    if sv != 200 or not q:
        print(f"NO TEST {test} (HTTP {sv})"); return
    items = [(it.get("reference") or {}).get("identifier") for it in q.get("questions", [])]
    print(f"LIVE BANK {test}: {len(items)} items")
    print("=" * 70)
    stim_cache = {}
    for n, iid in enumerate(items, 1):
        si, idoc = P.get_json(QTI + f"/assessment-items/{iid}", tok)
        raw = (idoc or {}).get("rawXml", "") if si == 200 else ""
        try:
            root = ET.fromstring(raw)
        except Exception as e:
            print(f"\n[Q{n} {iid}] PARSE-ERROR {e}"); continue
        els = list(root.iter())
        itype = next((ln(e.tag).replace("qti-", "").replace("-interaction", "")
                      for e in els if ln(e.tag).endswith("-interaction")), "?")
        # correct values
        correct = set()
        for rd in els:
            if ln(rd.tag) == "qti-response-declaration":
                for cr in rd.iter():
                    if ln(cr.tag) == "qti-correct-response":
                        for v in cr.iter():
                            if ln(v.tag) == "qti-value" and v.text:
                                correct.add(v.text.strip())
        # stimulus
        href = None
        for e in els:
            if ln(e.tag) == "qti-assessment-stimulus-ref":
                href = (e.get("href") or "").split("/")[-1] or e.get("identifier")
        passage = ""
        if href:
            if href not in stim_cache:
                ss, sd = P.get_json(QTI + f"/stimuli/{href}", tok)
                c = (sd or {}).get("content", "") if ss == 200 else "(stimulus HTTP %s)" % ss
                if isinstance(c, (dict, list)):
                    c = _collect_text(c)
                stim_cache[href] = c
            passage = stim_cache[href]
        # stem = item-body text minus options
        body = next((e for e in els if ln(e.tag) == "qti-item-body"), None)
        prompts = [text(e) for e in els if ln(e.tag) == "qti-prompt"]
        stem_div = ""
        if body is not None:
            for d in body:
                if ln(d.tag) == "div":
                    stem_div = text(d)
        import re as _re
        ptxt = _re.sub(r"<[^>]+>", " ", str(passage))
        ptxt = " ".join(ptxt.split())
        print(f"\n[Q{n} | {itype} | {iid}]")
        print("  PASSAGE:", ptxt[:500] or "(none)")
        if stem_div: print("  STEM:", stem_div)
        for p in prompts: print("  PROMPT:", p)
        for e in els:
            t = ln(e.tag)
            if t in ("qti-simple-choice", "qti-hottext", "qti-simple-associable-choice"):
                ident = e.get("identifier")
                mark = "  <-- KEY" if (ident in correct or any(ident in c.split() for c in correct)) else ""
                print(f"    ({ident}) {text(e)}{mark}")
        if correct: print("  CORRECT:", sorted(correct))

if __name__ == "__main__":
    main()
