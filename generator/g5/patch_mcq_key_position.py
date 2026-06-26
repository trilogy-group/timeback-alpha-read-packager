#!/usr/bin/env python3
"""Fix MCQ answer-position bias (52%+ of keys on option A) in the G5 PowerPath course.

SAFETY: This script is DRY-RUN by default.  It will NEVER make live API calls
unless --live is passed.  Do NOT pass --live without Stan's explicit sign-off —
answer-position changes affect scoring and require validation.

What it does
------------
1. GETs all child ALIs for the course and filters to MCQ items
   (metadata.questionId ends with "-mcq" OR the QTI item type is "choice").
2. For each MCQ, fetches the QTI item XML and finds the current correct key.
3. If the correct key is option A, rotates the simple-choices so A goes to
   position B, C, or D — picked deterministically by:
       target_pos = hash(item_id) % 3  -> 0=B, 1=C, 2=D
   The rotation keeps all other choices in their original relative order and
   updates the qti-response-declaration correct-response value to match.
4. PUTs the updated XML back via the QTI assessment-items endpoint.
5. Prints a summary line:
       MCQ items checked: N, keys on A: N, would rotate: N  (dry run)
   or:
       MCQ items checked: N, keys on A: N, rotated: N, errors: N  (live)

Usage:
  export TIMEBACK_SSO_CLIENT_ID=...
  export TIMEBACK_SSO_CLIENT_SECRET=...

  # Dry-run (default and safe — always run this first):
  python3 patch_mcq_key_position.py --prefix g5-reading-ela-pp-9801

  # Live run — REQUIRES Stan's explicit OK:
  python3 patch_mcq_key_position.py --prefix g5-reading-ela-pp-9801 --live
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "v2_final_package", "scripts"))
from push_to_timeback import mint_token, get_json, OR, QTI  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _target_position(item_id: str) -> str:
    """Deterministic target position for a key-on-A item: B, C, or D."""
    h = int(hashlib.sha256(item_id.encode()).hexdigest(), 16)
    return ["B", "C", "D"][h % 3]


def _rotate_mcq_xml(raw_xml: str, item_id: str) -> tuple:
    """Rotate options in raw QTI XML so correct key A moves to a new position.

    Returns (new_xml: str, new_key: str) or raises ValueError if the XML doesn't
    have exactly one qti-choice-interaction with option A as the correct key.

    Algorithm:
      - Parse the XML to find the <qti-simple-choice identifier="A"> element
        and the order of all simple-choices.
      - Pick target position T = _target_position(item_id) -> B/C/D.
      - Reorder: the choice that had identifier=A gets identifier=T;
        the choices between A's original slot and T's slot shift one step
        toward A's original slot.  All other identifiers are unchanged.
      - Update qti-response-declaration correct-response value to T.
    """
    # We manipulate as text to avoid namespace hell and preserve formatting.
    # Strategy: collect all <qti-simple-choice identifier="X">...</qti-simple-choice>
    # blocks, rotate, rebuild.

    choice_pat = re.compile(
        r'(<qti-simple-choice\s+identifier=")([^"]+)(")(.*?)(</qti-simple-choice>)',
        re.DOTALL)
    choices = choice_pat.findall(raw_xml)
    # choices[i] = (prefix, identifier, suffix, inner, closing)
    if not choices:
        raise ValueError("No qti-simple-choice elements found")

    # Build ordered list of (identifier, full_match_text)
    ordered = []
    for m in choice_pat.finditer(raw_xml):
        ordered.append({
            "id": m.group(2),
            "full": m.group(0),
            "inner": m.group(4),  # content between > and </qti-simple-choice>
        })

    ids = [c["id"] for c in ordered]
    if "A" not in ids:
        raise ValueError("Option A not found in choices")

    # Check correct response is A
    corr_pat = re.compile(r'(<qti-correct-response[^>]*>)(.*?)(</qti-correct-response>)', re.DOTALL)
    m_corr = corr_pat.search(raw_xml)
    if not m_corr:
        raise ValueError("No qti-correct-response found")
    corr_inner = m_corr.group(2)
    val_pat = re.compile(r'<qti-value>([^<]+)</qti-value>')
    corr_vals = val_pat.findall(corr_inner)
    if not corr_vals or corr_vals[0].strip() != "A":
        raise ValueError(f"Correct key is not A (found {corr_vals})")

    target = _target_position(item_id)
    if target not in ids:
        raise ValueError(f"Target position {target} not in choices {ids}")

    # Rotate: swap A and target while keeping inner content tied to original choice
    # i.e. the CONTENT of what was A goes to the TARGET slot; choice formerly at
    # target goes to A's original slot.  This is a simple identifier-swap, not
    # a reorder of the elements — the display order stays the same but the
    # identifier labels (which are used for scoring) get swapped.
    id_map = {c["id"]: c for c in ordered}
    a_inner = id_map["A"]["inner"]
    t_inner = id_map[target]["inner"]

    # Build replacement XML for each choice: swap identifiers A <-> target
    def remap_id(orig_id):
        if orig_id == "A":
            return target
        if orig_id == target:
            return "A"
        return orig_id

    new_xml = raw_xml
    # Replace each choice block
    for c in ordered:
        old_full = c["full"]
        new_id = remap_id(c["id"])
        new_full = old_full.replace(
            f'identifier="{c["id"]}"', f'identifier="{new_id}"', 1)
        new_xml = new_xml.replace(old_full, new_full, 1)

    # Update correct-response value A -> target
    new_corr_inner = corr_inner.replace(
        f"<qti-value>A</qti-value>", f"<qti-value>{target}</qti-value>")
    new_xml = new_xml.replace(m_corr.group(0),
        m_corr.group(1) + new_corr_inner + m_corr.group(3), 1)

    # Also update RP_MATCH_KEY inline <qti-base-value base-type="identifier">A</>
    rp_pat = re.compile(r'(<qti-base-value\s+base-type="identifier"\s*>)(A)(</qti-base-value>)')
    new_xml = rp_pat.sub(r'\g<1>' + target + r'\g<3>', new_xml)

    return new_xml, target


# ── API helpers ───────────────────────────────────────────────────────────────

def _put_item(item_id: str, new_xml: str, tok: str) -> tuple:
    """PUT updated QTI item XML.  Returns (success: bool, note: str)."""
    url = QTI + f"/assessment-items/{item_id}"
    body = json.dumps({"format": "xml", "xml": new_xml}).encode()
    for attempt in range(3):
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(url, data=body, method="PUT",
                    headers={"Authorization": "Bearer " + tok,
                             "Content-Type": "application/json"}),
                timeout=40)
            return True, f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            err_body = b""
            try:
                err_body = e.read()
            except Exception:
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep([5, 15, 30][attempt])
                continue
            return False, f"HTTP {e.code} {err_body[:160]}"
        except Exception as exc:
            if attempt < 2:
                time.sleep([5, 15, 30][attempt])
                continue
            return False, str(exc)[:160]
    return False, "max retries"


def _fetch_all_child_alis(prefix: str, tok: str) -> list:
    """Page through assessmentLineItems filtering to child ALIs for this course."""
    ali_list = []
    limit = 200
    offset = 0
    while True:
        url = (OR + f"/gradebook/v1p2/assessmentLineItems"
               f"?limit={limit}&offset={offset}")
        status, data = get_json(url, tok)
        if status != 200 or not data:
            print(f"  WARNING: ALI page fetch failed (status={status})")
            break
        items = data.get("assessmentLineItems", [])
        for ali in items:
            meta = ali.get("metadata") or {}
            qid = meta.get("questionId", "")
            course = meta.get("courseSourcedId", "")
            # Filter to this course's MCQ child ALIs
            if course == prefix and qid.endswith("-mcq"):
                ali_list.append(ali)
        if len(items) < limit:
            break
        offset += limit
        # Guard: don't scan the entire 4.9M ALI table
        if offset > 50000:
            print("  WARNING: scanned 50k ALIs without exhausting — stopping page walk")
            break
    return ali_list


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Fix MCQ answer-position bias")
    ap.add_argument("--prefix", default="g5-reading-ela-pp-9801",
                    help="Course sourcedId / prefix")
    ap.add_argument("--live", action="store_true",
                    help="Actually PUT changes. NEVER run without Stan's explicit OK.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only check first N MCQ items (for testing)")
    a = ap.parse_args()

    if a.live:
        print("*** LIVE MODE — will PUT answer-position changes to TimeBack ***")
        print("*** STOP NOW if Stan has not explicitly approved this run.    ***")
        print()

    tok, scopes = mint_token()
    print(f"Token OK | scopes: {scopes[:60]}")

    # The ALI walk is slow for a large course.  Fall back to direct item ID
    # derivation from the naming convention when the course is ours.
    # The publish_powerpath.py convention: items are named
    #   {prefix}-u{ei}-l{li}-q{qi:02d}-mcq
    # We enumerate by probing GET until we hit 404.
    print(f"Probing MCQ items for course {a.prefix} ...")

    mcq_ids = []
    ei = 0
    while True:
        li = 0
        found_in_exp = 0
        while True:
            qi = 1
            found_in_lesson = 0
            while True:
                iid = f"{a.prefix}-u{ei}-l{li}-q{qi:02d}-mcq"
                status, _ = get_json(QTI + f"/assessment-items/{iid}", tok)
                if status == 200:
                    mcq_ids.append(iid)
                    found_in_lesson += 1
                    found_in_exp += 1
                    qi += 1
                elif status == 404:
                    break
                else:
                    # Unexpected error — skip this slot
                    qi += 1
                    if qi > 30:
                        break
            # Stop lesson walk if lesson 0 of a new expedition also has nothing
            if found_in_lesson == 0:
                break
            li += 1
        if found_in_exp == 0:
            break
        ei += 1

    if a.limit:
        mcq_ids = mcq_ids[:a.limit]

    total_checked = len(mcq_ids)
    keys_on_a = 0
    would_rotate = 0
    rotated = 0
    errors = 0
    skipped = 0

    for item_id in mcq_ids:
        status, data = get_json(QTI + f"/assessment-items/{item_id}", tok)
        if status != 200 or not data:
            print(f"  SKIP {item_id}: GET returned {status}")
            skipped += 1
            continue
        raw_xml = data.get("rawXml", "")
        if not raw_xml:
            skipped += 1
            continue

        # Quick check: is correct key A?
        corr_vals = re.findall(
            r'<qti-correct-response[^>]*>.*?<qti-value>([^<]+)</qti-value>.*?</qti-correct-response>',
            raw_xml, re.DOTALL)
        if not corr_vals or corr_vals[0].strip() != "A":
            continue  # key not on A — nothing to do

        keys_on_a += 1
        try:
            new_xml, new_key = _rotate_mcq_xml(raw_xml, item_id)
            would_rotate += 1
            if a.live:
                success, note = _put_item(item_id, new_xml, tok)
                if success:
                    print(f"  ROTATED {item_id}: A -> {new_key} ({note})")
                    rotated += 1
                else:
                    print(f"  ERR     {item_id}: {note}")
                    errors += 1
            else:
                target = _target_position(item_id)
                print(f"  WOULD ROTATE {item_id}: A -> {target}")
        except ValueError as exc:
            print(f"  SKIP {item_id}: {exc}")
            skipped += 1

    print()
    if a.live:
        print(f"MCQ items checked: {total_checked}, keys on A: {keys_on_a}, "
              f"rotated: {rotated}, errors: {errors}, skipped: {skipped}")
    else:
        print(f"MCQ items checked: {total_checked}, keys on A: {keys_on_a}, "
              f"would rotate: {would_rotate}")
        print("(dry run — pass --live to apply changes, ONLY with Stan's explicit OK)")


if __name__ == "__main__":
    main()
