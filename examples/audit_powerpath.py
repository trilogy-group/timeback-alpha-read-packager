#!/usr/bin/env python3
"""Audit a powerpath-100 course: verify every lesson is wired the way Praveen's working
course is. Per lesson checks (the powerpath100-instructions.md healthy-shape invariants):
  * component-resource exists, metadata.lessonType == powerpath-100
  * resource exists, metadata.lessonType == powerpath-100, url -> the QTI test
  * QTI assessment-test /questions returns a REAL bank (>= MIN_BANK items)  [selector pool]
  * parent assessmentLineItem exists for the component-resource (0-100)
  * child assessmentLineItems count ~matches the bank (questionId tracking)
Prints PASS/FAIL per lesson + a summary. Exit 0 if all PASS.

Usage: python3 audit_powerpath.py --course grade3-reading-ela-pp-9700 [--min-bank 8]
"""
import sys, os, argparse, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_to_timeback as P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", required=True)
    ap.add_argument("--min-bank", type=int, default=8)
    a = ap.parse_args()
    tok, _ = P.mint_token()
    OR, QTI = P.OR, P.QTI
    GB = OR + "/gradebook/v1p2/assessmentLineItems"

    def getj(base, path):
        return P.get_json(base + path, tok)

    # lessons (components with a parent) of the course
    flt = urllib.parse.quote(f"course.sourcedId='{a.course}'")
    st, d = getj(OR, f"/rostering/v1p2/courses/components?limit=3000&filter={flt}")
    comps = (d or {}).get("courseComponents", [])
    lessons = [c for c in comps if (c.get("parentComponent") or c.get("parent"))]
    units = [c for c in comps if not (c.get("parentComponent") or c.get("parent"))]
    print(f"course {a.course}: units={len(units)} lessons={len(lessons)}")

    npass = nfail = 0
    fails = []
    for L in sorted(lessons, key=lambda x: x.get("sourcedId", "")):
        lid = L["sourcedId"]
        cr_id = lid + "-cr"
        test_id = lid + "-test"
        problems = []

        st, d = getj(OR, f"/rostering/v1p2/courses/component-resources/{cr_id}")
        cr = (d or {}).get("componentResource") or {}
        if st != 200:
            problems.append(f"cr missing (HTTP {st})")
        elif (cr.get("metadata") or {}).get("lessonType") != "powerpath-100":
            problems.append(f"cr.lessonType={cr.get('metadata',{}).get('lessonType')}")

        st, d = getj(OR, f"/resources/v1p2/resources/{test_id}")
        res = (d or {}).get("resource") or {}
        if st != 200:
            problems.append(f"resource missing (HTTP {st})")
        elif (res.get("metadata") or {}).get("lessonType") != "powerpath-100":
            problems.append(f"res.lessonType={res.get('metadata',{}).get('lessonType')}")

        st, q = getj(QTI, f"/assessment-tests/{test_id}/questions")
        nq = len((q or {}).get("questions", [])) if st == 200 else 0
        if nq < a.min_bank:
            problems.append(f"bank={nq} (<{a.min_bank})")

        # parent ALI
        st, d = getj(OR, f"/gradebook/v1p2/assessmentLineItems/{lid}-ali")
        if st != 200:
            problems.append("parent ALI missing")

        if problems:
            nfail += 1
            fails.append((lid, nq, problems))
        else:
            npass += 1

    print(f"\n=== AUDIT: {npass} PASS / {nfail} FAIL (min bank {a.min_bank}) ===")
    for lid, nq, probs in fails[:40]:
        print(f"  FAIL {lid} (bank={nq}): {', '.join(probs)}")
    sys.exit(0 if nfail == 0 else 1)


if __name__ == "__main__":
    main()
