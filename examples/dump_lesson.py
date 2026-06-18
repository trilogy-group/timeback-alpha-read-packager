#!/usr/bin/env python3
"""Dump ONE lesson's passage + every question (stem, options/keys) in readable form,
for adversarial content review. Mirrors publish_powerpath.py's grouping (expedition_index,
ordered lesson_index)."""
import json, argparse, os
from collections import OrderedDict

# Default bundle path is overridable via $G3_BUNDLE or --bundle (no hardcoded personal path).
RAW = os.environ.get("G3_BUNDLE", "course_bundle.jsonl")
QTYPES = {"mcq", "msq", "sequence", "hot-text", "match", "ebsr"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ei", type=int, required=True)
    ap.add_argument("--li", type=int, required=True)
    ap.add_argument("--bundle", default=RAW)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.bundle) if l.strip()]

    lessons = OrderedDict()
    for r in rows:
        if int(r.get("expedition_index", 0)) != a.ei:
            continue
        lid = r.get("lesson_id")
        L = lessons.setdefault(lid, {"lesson_index": int(r.get("lesson_index", 0)),
                                     "title": r.get("lesson_title"), "items": [], "article": None})
        if r["type"] == "article":
            if L["article"] is None:
                L["article"] = r
        elif r["type"] in QTYPES:
            L["items"].append(r)

    # Index over ALL lessons in the unit (sorted by lesson_index), matching publish_powerpath's
    # `enumerate(ekeys)` — item-less lessons consume an ordinal there too, so -uN-lM ids line up.
    keys = sorted(lessons.keys(), key=lambda k: lessons[k]["lesson_index"])
    if a.li >= len(keys):
        print("NO SUCH LESSON (ei=%d li=%d; this unit has %d lessons)" % (a.ei, a.li, len(keys)))
        return
    L = lessons[keys[a.li]]
    if not L["items"]:
        print("LESSON %d in unit %d has no question items (not deployed as -u%d-l%d)." % (a.li, a.ei, a.ei, a.li))
        return
    art = L["article"] or {}
    print("LESSON: %s   (unit %d, lesson %d)" % (L["title"], a.ei, a.li))
    print("=" * 70)
    print("PASSAGE (%s):" % (art.get("title") or "?"))
    print((art.get("content") or "(no passage)").strip())
    print("=" * 70)
    for n, q in enumerate(L["items"], 1):
        t = q["type"]
        print("\n[Q%d | %s | item_id=%s]" % (n, t, q.get("item_id")))
        st = q.get("stimulus")
        st = st.get("value", "") if isinstance(st, dict) else (st or "")
        print("  PASSAGE SHOWN WITH THIS QUESTION:", (st.strip()[:700] or "(none)"))
        if t in ("mcq", "msq"):
            print("  STEM:", q.get("question"))
            for o in q.get("answer_options", []):
                mark = "  <-- KEY" if o.get("is_correct") else ""
                print("    (%s) %s%s" % (o.get("key"), o.get("text"), mark))
            print("  MARKED ANSWER:", q.get("answer"))
        elif t == "hot-text":
            print("  STEM:", q.get("question"))
            for tok in q.get("tokens", []):
                mark = "  <-- KEY" if tok.get("id") in (q.get("answer") or []) else ""
                print("    [%s] %s%s" % (tok.get("id"), tok.get("text"), mark))
        elif t == "match":
            print("  STEM:", q.get("question"))
            cats = {c["id"]: c["label"] for c in q.get("categories", [])}
            for it in q.get("items", []):
                print("    %s -> %s" % (it.get("text"), cats.get(it.get("correct_category_id"))))
        elif t == "sequence":
            print("  STEM:", q.get("question"))
            steps = {s["id"]: s["content"] for s in q.get("items", [])}
            for i, sid in enumerate(q.get("correct_order", []), 1):
                print("    %d. %s" % (i, steps.get(sid)))
        elif t == "ebsr":
            for part, lab in ((q.get("part_a", {}), "A"), (q.get("part_b", {}), "B")):
                print("  PART %s STEM:" % lab, part.get("question"))
                for o in part.get("answer_options", []):
                    mark = "  <-- KEY" if o.get("is_correct") else ""
                    print("    (%s) %s%s" % (o.get("key"), o.get("text"), mark))


if __name__ == "__main__":
    main()
