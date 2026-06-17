#!/usr/bin/env python3
"""Prune QA-flagged items from a deployed powerpath course's banks: for each affected lesson,
re-PUT its assessment-test with the flagged item-refs removed. Orphaned QTI items are left
(harmless). Idempotent. Reads the flagged bundle itemIds from the QA workflow result JSON.

Usage:
  python3 prune_banks.py --prefix grade3-reading-ela-pp-9701 --bundle <b.jsonl> --qa <qa.json> [--dry-run|--one|--apply]
"""
import json, sys, argparse, os, urllib.request, urllib.error
from collections import OrderedDict, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_to_timeback as P
from publish_powerpath import test_json, QTYPES

def put(url, body, tok):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="PUT",
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=40); return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--qa", required=True, help="QA workflow result JSON (has result.confirmed[].itemId)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--one", action="store_true", help="PUT only the first affected test (validate PUT)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    qa = json.load(open(a.qa))
    qa = qa.get("result", qa)
    drop = {c["itemId"] for c in qa.get("confirmed", [])}
    print("flagged itemIds to drop:", len(drop))

    rows = [json.loads(l) for l in open(a.bundle) if l.strip()]
    # rebuild publisher grouping -> per (ei, li_ord) ordered items
    lm = OrderedDict()
    for r in rows:
        ei = int(r.get("expedition_index", 0)); lid = r.get("lesson_id")
        L = lm.setdefault((ei, lid), {"ei": ei, "li": int(r.get("lesson_index", 0)), "title": r.get("lesson_title"), "items": []})
        if r["type"] in QTYPES:
            L["items"].append(r)
    by_ei = defaultdict(list)
    for k, L in lm.items(): by_ei[L["ei"]].append(L)

    PRE = a.prefix
    item_base = P.QTI + "/assessment-items"
    affected = []
    for ei in sorted(by_ei):
        ls = sorted(by_ei[ei], key=lambda x: x["li"])
        for li, L in enumerate(ls):
            ids, kept, removed = [], [], 0
            for qi, q in enumerate(L["items"], 1):
                iid = "%s-u%d-l%d-q%02d-%s" % (PRE, ei, li, qi, q["type"].replace("-", ""))
                if q["item_id"] in drop:
                    removed += 1
                else:
                    kept.append(iid)
            if removed:
                test_id = "%s-u%d-l%d-test" % (PRE, ei, li)
                affected.append({"test": test_id, "title": L["title"], "ei": ei, "li": li,
                                 "before": len(L["items"]), "after": len(kept), "kept": kept})

    print("\naffected tests:", len(affected))
    for t in affected:
        flag = "  <-- BELOW 8" if t["after"] < 8 else ""
        print("  %-40s %2d -> %2d%s" % (t["test"], t["before"], t["after"], flag))

    if a.dry_run:
        print("\nDRY-RUN. (--one to PUT first test, --apply to PUT all)")
        return

    tok, _ = P.mint_token()
    todo = affected[:1] if a.one else affected
    for t in todo:
        body = test_json(t["test"], t["title"], t["kept"], item_base)
        st, err = put(P.QTI + "/assessment-tests/" + t["test"], body, tok)
        # verify
        sv, q = P.get_json(P.QTI + "/assessment-tests/" + t["test"] + "/questions", tok)
        nq = len((q or {}).get("questions", [])) if sv == 200 else "?"
        print("  PUT %-40s HTTP %s  now /questions=%s  (target %d)%s"
              % (t["test"], st, nq, t["after"], (" ERR:" + str(err)) if err else ""))

if __name__ == "__main__":
    main()
