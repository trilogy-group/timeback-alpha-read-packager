#!/usr/bin/env python3
"""Build Leitner-style spaced review sessions for the G5 60-lesson reading course.

Reads /tmp/g5_bundle_fixed.jsonl, selects items per Leitner schedule, and outputs
6 review-session courseComponent objects (or prints a dry-run summary).

Spaced Review Schedule (Leitner-style, 60 lessons):
  Review 1 (after lesson 10): items from lessons 1-5
  Review 2 (after lesson 20): items from lessons 6-15
  Review 3 (after lesson 30): items from lessons 11-25 + lessons 1-10 starred
  Review 4 (after lesson 40): items from lessons 21-35
  Review 5 (after lesson 50): items from lessons 31-45
  Review 6 (after lesson 60): items from lessons 41-55 + unit 1 starred

Selection priority:
  1. DOK-3 first
  2. Hardest difficulty (C > B > A)
  3. KCT3 preferred (text structure = cohort weakness)
  4. Exclude MCQ and MSQ (cold types only)
  Max 10 items per review session.

Usage:
  python3 build_spaced_review.py [--dry-run] [--bundle PATH] [--out PATH]
"""

import json
import argparse
import sys
from collections import defaultdict
from typing import List, Dict, Any, Optional

BUNDLE_DEFAULT = "/tmp/g5_bundle_fixed.jsonl"
ITEMS_PER_SESSION = 10
COLD_TYPES = {"hot-text", "sequence", "match", "ebsr"}
DIFFICULTY_RANK = {"C": 3, "B": 2, "A": 1}

# Leitner schedule: (review_number, after_lesson, source_lessons, starred_epochs)
# starred_epochs: list of (lesson_start, lesson_end) for previously-seen ranges to revisit
SCHEDULE = [
    {
        "review_num": 1,
        "after_lesson": 10,
        "label": "Review 1",
        "source_range": (1, 5),
        "starred_ranges": [],
    },
    {
        "review_num": 2,
        "after_lesson": 20,
        "label": "Review 2",
        "source_range": (6, 15),
        "starred_ranges": [],
    },
    {
        "review_num": 3,
        "after_lesson": 30,
        "label": "Review 3",
        "source_range": (11, 25),
        "starred_ranges": [(1, 10)],  # lessons 1-10 starred (second pass)
    },
    {
        "review_num": 4,
        "after_lesson": 40,
        "label": "Review 4",
        "source_range": (21, 35),
        "starred_ranges": [],
    },
    {
        "review_num": 5,
        "after_lesson": 50,
        "label": "Review 5",
        "source_range": (31, 45),
        "starred_ranges": [],
    },
    {
        "review_num": 6,
        "after_lesson": 60,
        "label": "Review 6",
        "source_range": (41, 55),
        "starred_ranges": [(1, 15)],  # unit 1 starred (third pass)
    },
]


def load_items(bundle_path: str) -> List[Dict[str, Any]]:
    """Load all non-article items from the bundle."""
    items = []
    with open(bundle_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("type") in COLD_TYPES:
                items.append(row)
    return items


def priority_key(item: Dict[str, Any]) -> tuple:
    """Higher tuple = higher priority. Used for sorted(..., key=..., reverse=True)."""
    dok = int(item.get("dok") or 0)
    diff = DIFFICULTY_RANK.get(str(item.get("difficulty") or "").upper(), 0)
    kct3 = 1 if str(item.get("kct") or "") == "KCT3" else 0
    # type preference: ebsr > match > hot-text > sequence (richer/harder first)
    type_rank = {"ebsr": 4, "match": 3, "hot-text": 2, "sequence": 1}.get(
        item.get("type", ""), 0
    )
    return (dok, diff, kct3, type_rank)


def select_items(
    all_items: List[Dict[str, Any]],
    source_range: tuple,
    starred_ranges: List[tuple],
    n: int = ITEMS_PER_SESSION,
    already_used: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Select up to n items from source_range (plus starred_ranges as fallback pool).

    Items already used in prior review sessions are excluded first; if the pool is
    still short we allow reuse from starred_ranges only.
    """
    if already_used is None:
        already_used = set()

    lo, hi = source_range
    primary_pool = [
        item
        for item in all_items
        if lo <= item.get("lesson_index", 0) <= hi
        and item.get("item_id") not in already_used
    ]

    # Starred ranges: union of all starred lesson windows
    starred_ids = set()
    for s_lo, s_hi in starred_ranges:
        for item in all_items:
            li = item.get("lesson_index", 0)
            if s_lo <= li <= s_hi:
                starred_ids.add(item.get("item_id"))

    starred_pool = [
        item
        for item in all_items
        if item.get("item_id") in starred_ids
        and item.get("item_id") not in already_used
    ]

    # Sort both pools by priority descending
    primary_pool.sort(key=priority_key, reverse=True)
    starred_pool.sort(key=priority_key, reverse=True)

    # Fill: primary first, then starred to top up
    selected = []
    seen = set()
    for item in primary_pool:
        if len(selected) >= n:
            break
        iid = item.get("item_id")
        if iid not in seen:
            selected.append(item)
            seen.add(iid)

    if len(selected) < n:
        for item in starred_pool:
            if len(selected) >= n:
                break
            iid = item.get("item_id")
            if iid not in seen:
                selected.append(item)
                seen.add(iid)

    return selected[:n]


def build_course_component(session: Dict, items: List[Dict[str, Any]], prefix: str = "g5-reading-ela-pp-9801") -> Dict:
    """Build a OneRoster courseComponent object for a review session."""
    rv = session["review_num"]
    comp_id = "%s-review-%d" % (prefix, rv)
    item_refs = [item.get("item_id") for item in items]
    dok3_count = sum(1 for i in items if i.get("dok") == 3)
    kct3_count = sum(1 for i in items if i.get("kct") == "KCT3")
    type_breakdown = {}
    for i in items:
        t = i.get("type", "?")
        type_breakdown[t] = type_breakdown.get(t, 0) + 1

    return {
        "sourcedId": comp_id,
        "status": "active",
        "componentType": "review",
        "title": session["label"],
        "sortOrder": session["after_lesson"] * 10 + 5,  # slots between lessons
        "metadata": {
            "reviewSession": rv,
            "afterLesson": session["after_lesson"],
            "sourceRange": list(session["source_range"]),
            "starredRanges": [list(sr) for sr in session["starred_ranges"]],
            "itemCount": len(items),
            "dok3Count": dok3_count,
            "kct3Count": kct3_count,
            "typeBreakdown": type_breakdown,
            "itemIds": item_refs,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Build G5 spaced review sessions")
    parser.add_argument("--dry-run", action="store_true", help="Print schedule without writing output")
    parser.add_argument("--bundle", default=BUNDLE_DEFAULT, help="Path to g5_bundle_fixed.jsonl")
    parser.add_argument("--out", default=None, help="Output JSONL path for courseComponents")
    parser.add_argument("--prefix", default="g5-reading-ela-pp-9801", help="Course ID prefix")
    args = parser.parse_args()

    # Load items
    try:
        all_items = load_items(args.bundle)
    except FileNotFoundError:
        print("ERROR: Bundle not found at %s" % args.bundle, file=sys.stderr)
        sys.exit(1)

    print("Loaded %d cold-type items from %s" % (len(all_items), args.bundle))
    print("")

    # Build sessions
    components = []
    all_used = set()
    total_items = 0

    for session in SCHEDULE:
        selected = select_items(
            all_items,
            source_range=session["source_range"],
            starred_ranges=session["starred_ranges"],
            n=ITEMS_PER_SESSION,
            already_used=all_used,
        )
        # track used items across sessions (no exact duplication of primary-pool items)
        lo, hi = session["source_range"]
        for item in selected:
            li = item.get("lesson_index", 0)
            if lo <= li <= hi:
                all_used.add(item.get("item_id"))

        dok3_count = sum(1 for i in selected if i.get("dok") == 3)
        kct3_count = sum(1 for i in selected if i.get("kct") == "KCT3")
        type_breakdown = {}
        for i in selected:
            t = i.get("type", "?")
            type_breakdown[t] = type_breakdown.get(t, 0) + 1

        total_items += len(selected)

        comp = build_course_component(session, selected, prefix=args.prefix)
        components.append(comp)

        # Print summary line
        starred_note = ""
        if session["starred_ranges"]:
            ranges_str = ", ".join("lessons %d-%d" % (s, e) for s, e in session["starred_ranges"])
            starred_note = " + starred (%s)" % ranges_str
        type_str = ", ".join("%s:%d" % (k, v) for k, v in sorted(type_breakdown.items()))
        print(
            "%s (after lesson %d): %d items from lessons %d-%d%s | DOK-3: %d, KCT3: %d | types: %s"
            % (
                session["label"],
                session["after_lesson"],
                len(selected),
                session["source_range"][0],
                session["source_range"][1],
                starred_note,
                dok3_count,
                kct3_count,
                type_str,
            )
        )

    print("")
    print("=== Summary ===")
    print("Sessions: %d" % len(components))
    print("Items per session: %d (max)" % ITEMS_PER_SESSION)
    print("Total review items: %d" % total_items)
    print("Cold types only (no MCQ/MSQ): YES")
    print("")

    if args.dry_run:
        print("[dry-run] No output written.")
        print("")
        print("Sample courseComponent (Review 1):")
        print(json.dumps(components[0], indent=2))
        return

    # Write output
    out_path = args.out or ("/tmp/g5_spaced_review_components.jsonl")
    with open(out_path, "w") as f:
        for comp in components:
            f.write(json.dumps(comp) + "\n")
    print("Wrote %d courseComponent objects to %s" % (len(components), out_path))


if __name__ == "__main__":
    main()
