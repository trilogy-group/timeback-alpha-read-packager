#!/usr/bin/env python3
"""Deploy Anuj's MAP-proxy mastery test (mastery_test_N.jsonl) as a powerpath course on TimeBack,
so it renders + scores like the rest. Each record's `actual_question` reuses the course bundle
schema, so we reuse publish_powerpath's QTI generators. One course -> one unit -> one lesson ->
the full item bank as a powerpath-100 test + per-item stimulus + parent/child ALIs + enroll.

NOTE (delivery caveat): served as powerpath-100 (the shape that renders+scores on the TimeBack UI),
NOT a true fixed-form sitting. The team's mastery-gate-vs-proxy delivery decision can refine this.
"""
import json, ast, sys, os, argparse, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_to_timeback as P
import publish_powerpath as PP


def actual(r):
    a = r.get("actual_question")
    return ast.literal_eval(a) if isinstance(a, str) else a


def norm_stim(q):
    """Mastery items store stimulus as a string (mcq/msq/hot-text/match) or a dict {content}/{value} (ebsr)."""
    s = q.get("stimulus")
    if isinstance(s, dict):
        s = s.get("content") or s.get("value") or s.get("text") or ""
    q["stimulus"] = s or ""
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--org", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--enroll-student", default=None)
    ap.add_argument("--checkpoint", default="/tmp/mastery_publish_state.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--drop", default="", help="comma-sep bundle item_ids to exclude")
    a = ap.parse_args()

    drop = set(x for x in a.drop.split(",") if x)
    rows = [json.loads(l) for l in open(a.jsonl) if l.strip()]
    PRE = a.prefix
    item_base = P.QTI + "/assessment-items"

    items, stims, child = [], [], []
    skipped = []
    for n, r in enumerate(rows, 1):
        q = norm_stim(actual(r))
        t = q.get("type") or r.get("format")
        if r.get("item_id") in drop or q.get("item_id") in drop:
            skipped.append(q.get("item_id")); continue
        if t not in PP.BUILDERS:
            skipped.append((q.get("item_id"), "type " + str(t))); continue
        iid = "%s-q%02d-%s" % (PRE, n, t.replace("-", ""))
        try:
            xml = PP.BUILDERS[t](iid, q)
        except Exception as e:
            skipped.append((iid, str(e)[:60])); continue
        stim_id = iid + "-s"
        content = PP.item_stim_text(q) or PP._txt_to_html(q.get("stimulus") or "", r.get("substandard_id"))
        stims.append({"identifier": stim_id, "title": (q.get("substandard_id") or a.title)[:80], "content": content})
        xml = PP.with_stimulus_ref(xml, stim_id)
        items.append({"id": iid, "xml": xml, "type": t})
        stem = q.get("question") or (q.get("part_a", {}) or {}).get("question") or t
        child.append({"sourcedId": "%s-ali-q%02d" % (PRE, n), "questionId": iid,
                      "title": ("MAP-proxy Q: %s" % stem)[:240]})

    print("=" * 70)
    print("MASTERY DEPLOY: %s | items=%d (skipped %d) org=%s" % (PRE, len(items), len(skipped), a.org))
    tc = {}
    for it in items: tc[it["type"]] = tc.get(it["type"], 0) + 1
    print("  types:", tc)
    if skipped: print("  skipped:", skipped[:10])

    if a.dry_run or not a.publish:
        import xml.dom.minidom as MD
        bad = 0
        for it in items:
            try: MD.parseString(it["xml"])
            except Exception as e: bad += 1; print("  XML ERR", it["id"], e)
        print("DRY-RUN: %d items, %d malformed." % (len(items), bad)); return

    state = json.load(open(a.checkpoint)) if os.path.exists(a.checkpoint) else {}
    tok, _ = P.mint_token(); QTI, OR = P.QTI, P.OR
    GB = OR + "/gradebook/v1p2/assessmentLineItems"
    UNIT, LES, TEST, CR, ALI = PRE + "-u0", PRE + "-u0-l0", PRE + "-test", PRE + "-u0-l0-cr", PRE + "-u0-l0-ali"

    P.post(OR + "/rostering/v1p2/courses", {"course": {"sourcedId": PRE, "status": "active", "title": a.title,
        "courseCode": PRE, "grades": ["3"], "subjects": ["Reading"], "org": {"sourcedId": a.org},
        "metadata": {"primaryApp": "timeback", "lessonType": "powerpath-100", "assessmentType": "map-proxy-mastery"}}},
        "course:" + PRE, tok, state, a.checkpoint)
    P.post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {"sourcedId": UNIT, "status": "active",
        "title": "MAP-Proxy Mastery Test", "sortOrder": 1000, "course": {"sourcedId": PRE}, "parent": None,
        "courseComponent": None, "metadata": {}}}, "unit:" + UNIT, tok, state, a.checkpoint)
    P.post(OR + "/rostering/v1p2/courses/components", {"courseComponent": {"sourcedId": LES, "status": "active",
        "title": a.title, "sortOrder": 10, "course": {"sourcedId": PRE}, "parent": {"sourcedId": UNIT},
        "courseComponent": {"sourcedId": UNIT}, "metadata": {}}}, "lesson:" + LES, tok, state, a.checkpoint)
    for s in stims:
        P.post(QTI + "/stimuli", {"identifier": s["identifier"], "title": s["title"], "content": s["content"]},
               "stim:" + s["identifier"], tok, state, a.checkpoint)
    for it in items:
        P.post(QTI + "/assessment-items", {"format": "xml", "xml": it["xml"]}, "item:" + it["id"], tok, state, a.checkpoint)
    P.post(QTI + "/assessment-tests", PP.test_json(TEST, a.title, [it["id"] for it in items], item_base),
           "test:" + TEST, tok, state, a.checkpoint)
    P.post(OR + "/resources/v1p2/resources/", {"resource": {"sourcedId": TEST, "status": "active", "title": a.title,
        "importance": "primary", "vendorResourceId": TEST, "metadata": {"type": "qti", "subType": "qti-test",
        "lessonType": "powerpath-100", "xp": 30, "subject": "Reading", "grade": "3",
        "url": QTI + "/assessment-tests/" + TEST}}}, "res:" + TEST, tok, state, a.checkpoint)
    P.post(OR + "/rostering/v1p2/courses/component-resources", {"componentResource": {"sourcedId": CR, "status": "active",
        "title": a.title, "sortOrder": 1, "resource": {"sourcedId": TEST}, "courseComponent": {"sourcedId": LES},
        "metadata": {"lessonType": "powerpath-100"}}}, "cr:" + CR, tok, state, a.checkpoint)
    P.post(GB, {"assessmentLineItem": {"sourcedId": ALI, "status": "active", "title": "PowerPath Test: " + a.title,
        "description": a.title, "componentResource": {"sourcedId": CR}, "course": {"sourcedId": PRE},
        "resultValueMin": 0, "resultValueMax": 100, "metadata": {"lessonType": "powerpath-100", "courseSourcedId": PRE}}},
        "ali:" + ALI, tok, state, a.checkpoint)
    for c in child:
        P.post(GB, {"assessmentLineItem": {"sourcedId": c["sourcedId"], "status": "active", "title": c["title"],
            "description": c["title"], "parentAssessmentLineItem": {"sourcedId": ALI}, "course": {"sourcedId": PRE},
            "resultValueMin": 0, "resultValueMax": 1, "metadata": {"questionId": c["questionId"], "lessonType": "powerpath-100", "grade": "3"}}},
            "cali:" + c["sourcedId"], tok, state, a.checkpoint)
    if a.enroll_student:
        TERM, CLASS, ENR = PRE + "-term", PRE + "-class", PRE + "-enr"
        P.post(OR + "/rostering/v1p2/academicSessions", {"academicSession": {"sourcedId": TERM, "status": "active",
            "title": a.title + " Term", "type": "term", "startDate": "2025-08-01", "endDate": "2026-06-30",
            "schoolYear": "2026", "org": {"sourcedId": a.org}}}, "term:" + TERM, tok, state, a.checkpoint)
        P.post(OR + "/rostering/v1p2/classes", {"class": {"sourcedId": CLASS, "status": "active", "title": a.title,
            "classCode": CLASS, "classType": "scheduled", "grades": ["3"], "subjects": ["Reading"],
            "course": {"sourcedId": PRE}, "org": {"sourcedId": a.org}, "school": {"sourcedId": a.org},
            "terms": [{"sourcedId": TERM}]}}, "class:" + CLASS, tok, state, a.checkpoint)
        P.post(OR + "/rostering/v1p2/enrollments", {"enrollment": {"sourcedId": ENR, "status": "active",
            "role": "student", "primary": True, "user": {"sourcedId": a.enroll_student}, "class": {"sourcedId": CLASS},
            "org": {"sourcedId": a.org}, "school": {"sourcedId": a.org}}}, "enroll:" + ENR, tok, state, a.checkpoint)
    print("\n=== DONE === %d-item MAP-proxy test deployed" % len(items))
    print("activity: https://alpha.timeback.com/app/activity/%s?courseId=%s&kind=quiz&url=%s&title=MAP" %
          (CR, PRE, P.QTI.replace(":", "%3A").replace("/", "%2F") + "%2Fassessment-tests%2F" + TEST))


if __name__ == "__main__":
    main()
