#!/usr/bin/env python3
"""deploy_spaced_review.py

Publish 6 spaced review courseComponents to the live G5 course
g5-reading-ela-pp-9801.

WHAT IT DOES
------------
Reads /tmp/g5_spaced_review_components.jsonl (6 entries produced by
build_spaced_review.py).  For each entry it:
  1. POSTs a courseComponent (review) to OR /courses/components
  2. POSTs componentResource entries linking each item ALI ID to the component

COMPONENT IDs (from JSONL)
--------------------------
  g5-reading-ela-pp-9801-review-1  … g5-reading-ela-pp-9801-review-6

USAGE
-----
  python3 deploy_spaced_review.py [--live] \
      [--jsonl /tmp/g5_spaced_review_components.jsonl]

FLAGS
-----
  --live   Actually POST to the TimeBack API.
           Without this flag the script runs in DRY-RUN mode (default).
  --jsonl  Path to the JSONL produced by build_spaced_review.py
           (default: /tmp/g5_spaced_review_components.jsonl)

SAFETY
------
Dry-run is the default.  --live must be passed explicitly and requires
Stan's approval per the no-generation-without-approval rule.
"""

import argparse
import json
import os
import sys

# ── resolve push_to_timeback ────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "..", "v2_final_package", "scripts"))
sys.path.insert(0, _SCRIPTS)

COURSE_ID = "g5-reading-ela-pp-9801"
OR_BASE   = "https://api.alpha-1edtech.ai/ims/oneroster"

COMP_URL  = OR_BASE + "/rostering/v1p2/courses/components"
CR_URL    = OR_BASE + "/rostering/v1p2/courses/component-resources"

DEFAULT_JSONL = "/tmp/g5_spaced_review_components.jsonl"


def load_entries(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def build_component_payload(entry, index):
    """Build the courseComponent POST body from a JSONL entry."""
    sourced_id = entry.get("sourcedId") or ("g5-reading-ela-pp-9801-review-%d" % index)
    title      = entry.get("title")     or ("Spaced Review — Session %d" % index)
    sort_order = entry.get("sortOrder") or (9010 + index)
    meta       = entry.get("metadata", {})

    return {
        "courseComponent": {
            "sourcedId": sourced_id,
            "status":    "active",
            "title":     title,
            "sortOrder": sort_order,
            "course":    {"sourcedId": COURSE_ID},
            "parent":    None,
            "courseComponent": None,
            "metadata": {
                "lessonType":     "powerpath-100",
                "componentType":  "review",
                "reviewSession":  meta.get("reviewSession", index),
                "afterLesson":    meta.get("afterLesson"),
                "sourceRange":    meta.get("sourceRange"),
                "itemCount":      meta.get("itemCount", 10),
                "kct3Count":      meta.get("kct3Count"),
                "dok3Count":      meta.get("dok3Count"),
                "typeBreakdown":  meta.get("typeBreakdown"),
            },
        }
    }


def build_component_resource_payloads(entry, index):
    """Build componentResource POST bodies, one per item ALI ID in the entry."""
    sourced_id = entry.get("sourcedId") or ("g5-reading-ela-pp-9801-review-%d" % index)
    meta       = entry.get("metadata", {})
    item_ids   = meta.get("itemIds", [])

    payloads = []
    for j, ali_id in enumerate(item_ids, 1):
        cr_id = "%s-cr-%02d" % (sourced_id, j)
        payloads.append({
            "componentResource": {
                "sourcedId": cr_id,
                "status":    "active",
                "title":     "%s item %02d" % (sourced_id, j),
                "sortOrder": j,
                "resource":          {"sourcedId": ali_id},
                "courseComponent":   {"sourcedId": sourced_id},
                "metadata":          {"lessonType": "powerpath-100"},
            }
        })
    return payloads


def dry_run(entries):
    print("=" * 60)
    print("DRY RUN — no API calls will be made")
    print("Pass --live to actually POST to TimeBack")
    print("=" * 60)
    print()

    for i, entry in enumerate(entries, 1):
        comp_payload = build_component_payload(entry, i)
        cr_payloads  = build_component_resource_payloads(entry, i)
        comp         = comp_payload["courseComponent"]

        print("--- Session %d ---" % i)
        print("  Would POST courseComponent to: %s" % COMP_URL)
        print("    sourcedId  : %s" % comp["sourcedId"])
        print("    title      : %s" % comp["title"])
        print("    sortOrder  : %s" % comp["sortOrder"])
        print("    course     : %s" % COURSE_ID)
        meta = comp["metadata"]
        print("    lessonType : %s" % meta["lessonType"])
        print("    reviewSession: %s  afterLesson: %s" % (
            meta.get("reviewSession"), meta.get("afterLesson")))
        print("    typeBreakdown: %s" % meta.get("typeBreakdown"))
        print("    itemCount  : %s  kct3Count: %s" % (
            meta.get("itemCount"), meta.get("kct3Count")))
        if cr_payloads:
            print("  Would POST %d componentResources to: %s" % (len(cr_payloads), CR_URL))
            for cr in cr_payloads[:2]:
                cr_obj = cr["componentResource"]
                print("    %s -> resource %s" % (cr_obj["sourcedId"], cr_obj["resource"]["sourcedId"]))
            if len(cr_payloads) > 2:
                print("    ... and %d more" % (len(cr_payloads) - 2))
        else:
            print("  No itemIds found — no componentResources to POST")
        print()

    print("DRY RUN complete — %d components, %d total componentResources" % (
        len(entries),
        sum(len(e.get("metadata", {}).get("itemIds", [])) for e in entries)
    ))


def live_run(entries):
    # Import only when actually running live to avoid accidental token mint in dry-run
    from push_to_timeback import mint_token, post  # noqa: E402

    tok   = mint_token()
    state = {}
    ckpt  = "/tmp/deploy_spaced_review_state.json"

    # Load existing checkpoint if present
    if os.path.exists(ckpt):
        try:
            with open(ckpt) as f:
                state = json.load(f)
            print("Resumed from checkpoint: %d steps already done" % len(state))
        except Exception:
            state = {}

    for i, entry in enumerate(entries, 1):
        comp_payload = build_component_payload(entry, i)
        cr_payloads  = build_component_resource_payloads(entry, i)
        comp_id      = comp_payload["courseComponent"]["sourcedId"]

        # 1. courseComponent
        r = post(COMP_URL, comp_payload, "comp:" + comp_id, tok, state, ckpt)
        status = getattr(r, "status_code", "n/a") if r else "skipped(ckpt)"
        print("POST component %s: HTTP %s" % (comp_id, status))

        # 2. componentResources
        for cr_payload in cr_payloads:
            cr_id = cr_payload["componentResource"]["sourcedId"]
            r = post(CR_URL, cr_payload, "cr:" + cr_id, tok, state, ckpt)
            status = getattr(r, "status_code", "n/a") if r else "skipped(ckpt)"
            print("  POST componentResource %s: HTTP %s" % (cr_id, status))

    print()
    print("Live deploy complete — %d components posted" % len(entries))


def main():
    parser = argparse.ArgumentParser(
        description="Deploy spaced review courseComponents to g5-reading-ela-pp-9801")
    parser.add_argument("--live",  action="store_true",
                        help="Actually POST to the TimeBack API (default: dry-run)")
    parser.add_argument("--jsonl", default=DEFAULT_JSONL,
                        help="Path to g5_spaced_review_components.jsonl")
    args = parser.parse_args()

    if not os.path.exists(args.jsonl):
        print("ERROR: JSONL file not found: %s" % args.jsonl, file=sys.stderr)
        sys.exit(1)

    entries = load_entries(args.jsonl)
    if not entries:
        print("ERROR: No entries loaded from %s" % args.jsonl, file=sys.stderr)
        sys.exit(1)

    print("Loaded %d spaced review entries from %s" % (len(entries), args.jsonl))
    print()

    if args.live:
        print("LIVE MODE — posting to TimeBack API")
        print()
        live_run(entries)
    else:
        dry_run(entries)


if __name__ == "__main__":
    main()
