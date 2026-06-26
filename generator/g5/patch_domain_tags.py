#!/usr/bin/env python3
"""Patch domain tags on G5 child ALIs in TimeBack.

Reads /tmp/g5_bundle_fixed.jsonl to get all question item_ids and their
substandard_id, infers domain from the standard prefix, then PATCHes
assessmentLineItem.metadata.domain on each child ALI.

Domain mapping:
  RL.5.x  -> "Literary"
  RI.5.x  -> "Informational"
  L.5.x   -> "Vocabulary"
  (other) -> "General"

The child ALI sourcedId convention (from publish_powerpath.py) is:
  {lesson_id}-ali-q{NN}  where lesson_id = {prefix}-u{ei}-l{li}

Usage:
  export TIMEBACK_SSO_CLIENT_ID=...
  export TIMEBACK_SSO_CLIENT_SECRET=...

  # Always dry-run first
  python3 patch_domain_tags.py --bundle /tmp/g5_bundle_fixed.jsonl \\
      --prefix g5-reading-ela-pp-9801 --dry-run

  # Live run only with Stan's explicit OK
  python3 patch_domain_tags.py --bundle /tmp/g5_bundle_fixed.jsonl \\
      --prefix g5-reading-ela-pp-9801
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "v2_final_package", "scripts"))
from push_to_timeback import mint_token, get_json, OR  # noqa: E402


# ── domain inference ─────────────────────────────────────────────────────────

def infer_domain(substandard_id: str) -> str:
    """Map a CCSS substandard id to a domain label."""
    s = (substandard_id or "").strip().upper()
    if s.startswith("RL"):
        return "Literary"
    if s.startswith("RI"):
        return "Informational"
    if s.startswith("L"):
        return "Vocabulary"
    return "General"


# ── ALI id convention (mirrors publish_powerpath.py) ─────────────────────────

def derive_ali_id(prefix: str, expedition_index: int, lesson_within_exp: int,
                  question_within_lesson: int) -> str:
    """Return the child ALI sourcedId the publisher would have created.

    publish_powerpath.py names child ALIs:
        {lesson_id}-ali-q{NN}
    where lesson_id = {prefix}-u{ei}-l{li} (0-based expedition and lesson indices).
    question index is 1-based (q01, q02, ...).
    """
    lesson_id = f"{prefix}-u{expedition_index}-l{lesson_within_exp}"
    return f"{lesson_id}-ali-q{question_within_lesson:02d}"


# ── load bundle and build patch plan ─────────────────────────────────────────

def build_patch_plan(bundle_path: str, prefix: str):
    """Return list of (ali_id, item_id, substandard_id, domain) tuples."""
    rows = []
    with open(bundle_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Group by (expedition_index, lesson_id) — same ordering as publish_powerpath.py
    # to derive stable lesson-within-expedition indices.
    from collections import defaultdict
    lessons_map: dict = OrderedDict()   # (ei, lid) -> list of question rows
    for r in rows:
        if r.get("type") == "article":
            continue
        ei = int(r.get("expedition_index", 0))
        lid = r.get("lesson_id") or f"{ei}::?"
        key = (ei, lid)
        lessons_map.setdefault(key, {"lesson_index": int(r.get("lesson_index", 0)),
                                     "items": []})
        lessons_map[key]["items"].append(r)

    # Sort expeditions, then lessons within each expedition by lesson_index
    exps = sorted({k[0] for k in lessons_map})
    plan = []
    for ei in exps:
        ekeys = [k for k in lessons_map if k[0] == ei]
        ekeys.sort(key=lambda k: lessons_map[k]["lesson_index"])
        for li, key in enumerate(ekeys):
            for qi, r in enumerate(lessons_map[key]["items"], 1):
                ali_id = derive_ali_id(prefix, ei, li, qi)
                item_id = r.get("item_id", "")
                sub = r.get("substandard_id", "")
                domain = infer_domain(sub)
                plan.append({
                    "ali_id": ali_id,
                    "item_id": item_id,
                    "substandard_id": sub,
                    "domain": domain,
                })
    return plan


# ── PATCH helper ─────────────────────────────────────────────────────────────

def patch_ali_domain(ali_id: str, current_meta: dict, domain: str, tok: str) -> tuple:
    """PATCH domain into ALI metadata.  Returns (success: bool, note: str)."""
    url = OR + f"/gradebook/v1p2/assessmentLineItems/{ali_id}"
    new_meta = dict(current_meta)
    new_meta["domain"] = domain
    body = json.dumps({"assessmentLineItem": {"metadata": new_meta}}).encode()
    for attempt in range(3):
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(url, data=body, method="PATCH",
                    headers={"Authorization": "Bearer " + tok,
                             "Content-Type": "application/json"}),
                timeout=30)
            return True, f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            body_err = b""
            try:
                body_err = e.read()
            except Exception:
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep([5, 15, 30][attempt])
                continue
            return False, f"HTTP {e.code} {body_err[:160]}"
        except Exception as exc:
            if attempt < 2:
                time.sleep([5, 15, 30][attempt])
                continue
            return False, str(exc)[:160]
    return False, "max retries"


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Patch domain tags on G5 ALIs")
    ap.add_argument("--bundle", default="/tmp/g5_bundle_fixed.jsonl",
                    help="Path to g5_bundle_fixed.jsonl")
    ap.add_argument("--prefix", default="g5-reading-ela-pp-9801",
                    help="Course prefix / sourcedId")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan without making any API calls")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only patch first N ALIs (for testing)")
    a = ap.parse_args()

    plan = build_patch_plan(a.bundle, a.prefix)
    if a.limit:
        plan = plan[:a.limit]

    # Domain distribution summary
    from collections import Counter
    domain_counts = Counter(p["domain"] for p in plan)
    print(f"Patch plan: {len(plan)} child ALIs to tag")
    for d, n in sorted(domain_counts.items()):
        print(f"  {d}: {n}")

    if a.dry_run:
        print("\n=== DRY RUN — no network calls ===")
        for p in plan[:10]:
            print(f"  WOULD PATCH {p['ali_id']} | {p['substandard_id']} -> domain={p['domain']}")
        if len(plan) > 10:
            print(f"  ... ({len(plan) - 10} more)")
        return

    tok, scopes = mint_token()
    print(f"Token OK | scopes: {scopes[:60]}")

    ok = err = skipped = 0
    for p in plan:
        ali_id = p["ali_id"]
        # Read current metadata so we preserve existing keys
        status, data = get_json(OR + f"/gradebook/v1p2/assessmentLineItems/{ali_id}", tok)
        if status != 200 or not data:
            print(f"  SKIP {ali_id}: GET returned {status}")
            skipped += 1
            continue
        current_meta = data.get("assessmentLineItem", {}).get("metadata", {}) or {}
        if current_meta.get("domain") == p["domain"]:
            print(f"  SKIP {ali_id}: domain already '{p['domain']}'")
            skipped += 1
            continue
        success, note = patch_ali_domain(ali_id, current_meta, p["domain"], tok)
        if success:
            print(f"  OK   {ali_id} -> domain={p['domain']} ({note})")
            ok += 1
        else:
            print(f"  ERR  {ali_id}: {note}")
            err += 1

    print(f"\n=== DONE === patched={ok} skipped={skipped} errors={err}")


if __name__ == "__main__":
    main()
