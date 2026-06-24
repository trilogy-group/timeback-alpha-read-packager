#!/usr/bin/env python3
"""
certified_to_bundle.py — convert certify_pipeline.py passing.jsonl into
publish_powerpath.py bundle.jsonl format.

Usage:
  python3 certified_to_bundle.py \
      --passing  certify_output/passing.jsonl \
      --passage-map passage_map.json \
      --output   bundle.jsonl \
      [--originals input.jsonl] \
      [--dry-run]

passage_map.json can be keyed by item_id OR passage_hash.
Expected value shape per key:
  {
    "expedition_index": 0,
    "lesson_id": "lesson-abc",
    "lesson_title": "Title",
    "unit": "Unit 1",
    "lesson_index": 0,
    "expedition": "Expedition 1",
    "passage_text": "..."
  }

Output rows follow build_plan() expectations in publish_powerpath.py:
  - one article row  (type='article') per lesson, then N item rows
  - envelope fields:  expedition_index, lesson_id, lesson_title, unit,
                      lesson_index, expedition
  - item fields:      type, question, plus type-specific payload fields
  - every row:        humanApproved=false, substandard_id

Re-expansion rules (adapted → publisher field names):
  hot-text:  options+key            → tokens+answer+question+max_selections
  sequence:  options+key(id_order)  → items(content)+correct_order+question
  match:     left/right/key(dict)   → items(correct_category_id)+categories(label)+question
  ebsr:      flat options+key       → nested part_a/part_b with answer_options+answer+question
  mcq/msq:   options+key            → answer_options(key field)+answer+question

If --originals is supplied, item rows prefer the original raw fields (lossless),
falling back to adapted fields only when the original is absent.
"""

import argparse
import hashlib
import json
import sys
from collections import OrderedDict


# ---------------------------------------------------------------------------
# Type re-expanders: adapted row → publisher-ready dict
# ---------------------------------------------------------------------------

def _expand_hottext(row, orig=None):
    """
    adapted: options=[{id, text}], key=[id, ...]
    publisher hottext_xml needs: tokens=[{id, text}], answer=[id,...],
                                 question=str, max_selections=int
    """
    if orig:
        tokens = orig.get("tokens", [])
        answer = orig.get("answer", row.get("key", []))
        question = orig.get("question", "") or row.get("stem", "")
        max_sel = orig.get("max_selections") or len(answer) or 1
        return {"tokens": tokens, "answer": answer,
                "question": question, "max_selections": max_sel}

    options = row.get("options", [])
    key = row.get("key", [])
    if isinstance(key, str):
        key = [key]
    tokens = [{"id": o["id"], "text": o["text"]} for o in options]
    question = row.get("stem", "")
    max_sel = len(key) or 1
    return {"tokens": tokens, "answer": key,
            "question": question, "max_selections": max_sel}


def _expand_sequence(row, orig=None):
    """
    adapted: options=[{id, text}], key=[id,...] (correct order)
    publisher order_xml needs: items=[{id, content}], correct_order=[id,...], question=str
    NOTE: publisher uses 'content', not 'text' inside items.
    """
    if orig:
        raw_items = orig.get("items", [])
        # publisher wants 'content'; coerce 'text' → 'content' if needed
        items = []
        for it in raw_items:
            items.append({"id": it["id"],
                          "content": it.get("content") or it.get("text", "")})
        correct_order = orig.get("correct_order", row.get("key", []))
        question = orig.get("question", "") or row.get("stem", "")
        return {"items": items, "correct_order": correct_order, "question": question}

    options = row.get("options", [])
    key = row.get("key", [])
    if isinstance(key, str):
        key = [key]
    items = [{"id": o["id"], "content": o.get("text", "")} for o in options]
    question = row.get("stem", "")
    return {"items": items, "correct_order": key, "question": question}


def _expand_match(row, orig=None):
    """
    adapted: left=[{id,text}], right=[{id,text}], key={item_id: cat_id}
    publisher match_xml needs:
      items=[{id, text, correct_category_id}]
      categories=[{id, label}]   ← 'label', not 'text'
      question=str
    """
    if orig:
        raw_items = orig.get("items", [])
        raw_cats  = orig.get("categories", [])
        # normalize categories to [{id, label}]
        categories = []
        for c in raw_cats:
            if isinstance(c, str):
                categories.append({"id": c, "label": c})
            else:
                categories.append({"id": c.get("id", ""),
                                   "label": c.get("label") or c.get("text", "")})
        # normalize items to include correct_category_id
        items = []
        for it in raw_items:
            items.append({"id": it["id"], "text": it.get("text", ""),
                          "correct_category_id": it.get("correct_category_id",
                                                         it.get("category", ""))})
        question = orig.get("question", "") or row.get("stem", "")
        return {"items": items, "categories": categories, "question": question}

    left  = row.get("left", row.get("options", []))
    right = row.get("right", [])
    key   = row.get("key", {})  # {item_id: cat_id}
    if not isinstance(key, dict):
        key = {}

    items = [{"id": o["id"], "text": o.get("text", ""),
              "correct_category_id": key.get(o["id"], "")}
             for o in left]
    categories = [{"id": c.get("id", ""), "label": c.get("text", "")} for c in right]
    question = row.get("stem", "")
    return {"items": items, "categories": categories, "question": question}


def _expand_ebsr(row, orig=None):
    """
    adapted: options=[{id, text, part='A'/'B', is_correct, feedback}], key=[A_x, B_y]
    publisher ebsr_xml needs:
      part_a={question, answer, answer_options=[{key, text}]}
      part_b={question, answer, answer_options=[{key, text}]}
    """
    if orig:
        pa = orig.get("part_a", {})
        pb = orig.get("part_b", {})

        def _norm_part(p):
            opts = p.get("answer_options", [])
            # publisher wants {key, text} in answer_options
            norm_opts = [{"key": o.get("key") or o.get("id", ""),
                          "text": o.get("text", "")} for o in opts]
            answer = p.get("answer", "")
            if not answer:
                answer = next((o.get("key") or o.get("id", "")
                               for o in opts if o.get("is_correct")), "")
            return {"question": p.get("question", ""),
                    "answer": answer,
                    "answer_options": norm_opts}

        return {"part_a": _norm_part(pa), "part_b": _norm_part(pb)}

    options = row.get("options", [])
    key_list = row.get("key", [])
    if isinstance(key_list, str):
        key_list = [key_list]

    pa_opts = [o for o in options if o.get("part") == "A"]
    pb_opts = [o for o in options if o.get("part") == "B"]

    def _key_for_part(prefix_label, opts_list):
        # key ids are like "A_somekey" — strip the prefix
        for k in key_list:
            if isinstance(k, str) and k.startswith(prefix_label + "_"):
                raw_key = k[len(prefix_label) + 1:]
                return raw_key
        # fallback: first is_correct option
        for o in opts_list:
            if o.get("is_correct"):
                oid = o.get("id", "")
                # strip part prefix if present
                if oid.startswith(prefix_label + "_"):
                    return oid[len(prefix_label) + 1:]
                return oid
        return ""

    def _norm_opts(opts_list, prefix_label):
        out = []
        for o in opts_list:
            oid = o.get("id", "")
            raw_key = oid[len(prefix_label) + 1:] if oid.startswith(prefix_label + "_") else oid
            out.append({"key": raw_key, "text": o.get("text", "")})
        return out

    pa_answer = _key_for_part("A", pa_opts)
    pb_answer = _key_for_part("B", pb_opts)

    # question stem lives in stem for part_a question in adapted; part_b may share stem
    stem = row.get("stem", "")

    part_a = {"question": stem, "answer": pa_answer,
              "answer_options": _norm_opts(pa_opts, "A")}
    part_b = {"question": stem, "answer": pb_answer,
              "answer_options": _norm_opts(pb_opts, "B")}

    return {"part_a": part_a, "part_b": part_b}


def _expand_mcq(row, orig=None, multi=False):
    """
    adapted: options=[{id, text}], key=str (or list for msq)
    publisher mcq_xml needs: answer_options=[{key, text}], answer=str/list, question=str
    """
    if orig:
        opts = orig.get("answer_options", [])
        # publisher expects {key, text}
        answer_options = [{"key": o.get("key") or o.get("id", ""),
                           "text": o.get("text", "")} for o in opts]
        answer = orig.get("answer", row.get("key", ""))
        question = orig.get("question", "") or row.get("stem", "")
        return {"answer_options": answer_options, "answer": answer, "question": question}

    options = row.get("options", [])
    key = row.get("key", [] if multi else "")
    answer_options = [{"key": o.get("id", ""), "text": o.get("text", "")} for o in options]
    question = row.get("stem", "")
    return {"answer_options": answer_options, "answer": key, "question": question}


EXPANDERS = {
    "hot-text":  _expand_hottext,
    "sequence":  _expand_sequence,
    "match":     _expand_match,
    "ebsr":      _expand_ebsr,
    "mcq":       lambda row, orig=None: _expand_mcq(row, orig, multi=False),
    "msq":       lambda row, orig=None: _expand_mcq(row, orig, multi=True),
}


# ---------------------------------------------------------------------------
# passage_map helpers
# ---------------------------------------------------------------------------

def _passage_hash(text):
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def _build_lookup(passage_map, items):
    """
    Return a lookup function: item_id → envelope dict or None.

    Tries item_id key first; if the map doesn't contain item_ids, tries
    passage_hash of any 'passage_text' field present in the certified row.
    """
    # Check if keys look like item ids (non-hash-like) or hashes
    sample_keys = list(passage_map.keys())[:5]
    # passage_hash keys are 16-char hex; item ids usually aren't
    keys_look_like_hashes = all(len(k) == 16 and all(c in "0123456789abcdef" for c in k)
                                 for k in sample_keys) if sample_keys else False

    # Build a hash→envelope index if needed
    hash_index = {}
    if keys_look_like_hashes:
        hash_index = passage_map

    def lookup(item_id, passage_text=""):
        # 1. Direct item_id lookup
        if item_id in passage_map:
            return passage_map[item_id]
        # 2. Hash-based lookup
        if passage_text and hash_index:
            h = _passage_hash(passage_text)
            if h in hash_index:
                return hash_index[h]
        return None

    return lookup


# ---------------------------------------------------------------------------
# Bundle grouping and emission
# ---------------------------------------------------------------------------

def _make_envelope(env_data):
    return {
        "expedition_index": env_data.get("expedition_index", 0),
        "lesson_id":        env_data.get("lesson_id", "unknown"),
        "lesson_title":     env_data.get("lesson_title", ""),
        "unit":             env_data.get("unit", ""),
        "lesson_index":     env_data.get("lesson_index", 0),
        "expedition":       env_data.get("expedition", ""),
    }


def _make_article_row(env_data):
    row = _make_envelope(env_data)
    row["type"] = "article"
    row["title"] = env_data.get("lesson_title", "")
    # passage_text → content (what publish_powerpath.py's passage_html reads)
    row["content"] = env_data.get("passage_text", "")
    row["humanApproved"] = False
    return row


def _make_item_row(certified_row, env_data, orig_row=None):
    """
    Build one publisher-ready item row from a certified (adapted) row.
    orig_row is the original Abdul-schema item (optional, for lossless expansion).
    """
    item_type = certified_row.get("type", "")
    expander = EXPANDERS.get(item_type)
    if not expander:
        return None  # unknown type — skip

    try:
        payload = expander(certified_row, orig_row)
    except Exception as e:
        sys.stderr.write(f"WARN: expand {item_type} id={certified_row.get('id','?')}: {e}\n")
        return None

    row = _make_envelope(env_data)
    row["type"] = item_type
    row["humanApproved"] = False
    row["substandard_id"] = certified_row.get("ccss") or certified_row.get("substandard_id", "")

    # Carry through useful metadata
    for field in ("kct", "cell_key", "lexile", "difficulty"):
        val = certified_row.get(field)
        if val:
            row[field] = val

    # Merge type-specific payload
    row.update(payload)

    # Keep the adapted item's own id for traceability
    row["item_id"] = certified_row.get("id", "")

    return row


# ---------------------------------------------------------------------------
# Main conversion logic
# ---------------------------------------------------------------------------

def convert(passing_path, passage_map_path, output_path,
            originals_path=None, dry_run=False):
    # Load passage map
    with open(passage_map_path, encoding="utf-8") as f:
        passage_map = json.load(f)

    # Load certified items
    certified = []
    with open(passing_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                certified.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.stderr.write(f"WARN: bad JSON line in passing.jsonl: {e}\n")

    # Load originals if provided
    orig_by_id = {}
    if originals_path:
        with open(originals_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # Support Abdul wrapper (rec.item) or bare item
                    item = rec.get("item", rec)
                    iid = item.get("item_id") or item.get("id")
                    if iid:
                        orig_by_id[iid] = item
                except json.JSONDecodeError:
                    pass

    lookup = _build_lookup(passage_map, certified)

    # Group by lesson, preserving first-seen order
    lesson_order = []  # ordered list of (ei, lesson_id)
    lesson_envs = {}   # (ei, lesson_id) → envelope dict
    lesson_items = {}  # (ei, lesson_id) → [certified_row, ...]

    unmatched = 0
    for row in certified:
        item_id = row.get("id", "")
        passage_text = row.get("passage_text", "")
        env = lookup(item_id, passage_text)
        if env is None:
            unmatched += 1
            # Use a fallback "orphan" lesson
            env = {
                "expedition_index": 0,
                "lesson_id": "orphan",
                "lesson_title": "Unmatched Items",
                "unit": "",
                "lesson_index": 0,
                "expedition": "",
                "passage_text": "",
            }

        ei = int(env.get("expedition_index", 0))
        lid = env.get("lesson_id", "orphan")
        key = (ei, lid)

        if key not in lesson_envs:
            lesson_order.append(key)
            lesson_envs[key] = env
            lesson_items[key] = []

        lesson_items[key].append(row)

    # Sort lessons by (expedition_index, lesson_index)
    lesson_order.sort(key=lambda k: (
        int(lesson_envs[k].get("expedition_index", 0)),
        int(lesson_envs[k].get("lesson_index", 0)),
    ))

    # Compute counts for dry-run / summary
    n_articles = len(lesson_order)
    n_items_total = sum(len(lesson_items[k]) for k in lesson_order)
    n_lessons = len(lesson_order)
    type_counts = {}
    for k in lesson_order:
        for row in lesson_items[k]:
            t = row.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

    if dry_run:
        print("DRY-RUN: no output written.")
        print(f"  certified items loaded : {len(certified)}")
        print(f"  unmatched (orphan)     : {unmatched}")
        print(f"  lessons (groups)       : {n_lessons}")
        print(f"  article rows           : {n_articles}")
        print(f"  item rows              : {n_items_total}")
        print(f"  total bundle rows      : {n_articles + n_items_total}")
        print("  by type:")
        for t, c in sorted(type_counts.items()):
            print(f"    {t:<14} {c}")
        return

    # Write output
    n_written = 0
    n_skipped = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for key in lesson_order:
            env = lesson_envs[key]
            # 1. Emit article row
            article_row = _make_article_row(env)
            out.write(json.dumps(article_row) + "\n")
            n_written += 1

            # 2. Emit item rows (up to 10 per lesson per spec)
            items_for_lesson = lesson_items[key][:10]
            for certified_row in items_for_lesson:
                item_id = certified_row.get("id", "")
                orig_row = orig_by_id.get(item_id) if orig_by_id else None
                item_row = _make_item_row(certified_row, env, orig_row)
                if item_row is None:
                    n_skipped += 1
                    continue
                out.write(json.dumps(item_row) + "\n")
                n_written += 1

    print(f"bundle.jsonl written: {n_written} rows "
          f"({n_articles} articles + {n_written - n_articles} items), "
          f"{n_skipped} items skipped (unknown type), "
          f"{unmatched} items without passage-map match.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="certified_to_bundle.py",
        description=(
            "Convert certify_pipeline.py passing.jsonl → publish_powerpath.py bundle.jsonl."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--passing",     required=True, metavar="PATH",
                    help="passing.jsonl from certify_pipeline.py")
    ap.add_argument("--passage-map", required=True, metavar="PATH", dest="passage_map",
                    help="JSON map: {item_id|passage_hash: {expedition_index, lesson_id, ...}}")
    ap.add_argument("--output",      required=True, metavar="PATH",
                    help="Output bundle.jsonl for publish_powerpath.py")
    ap.add_argument("--originals",   default=None,  metavar="PATH",
                    help="Original input.jsonl (Abdul schema) for lossless re-expansion")
    ap.add_argument("--dry-run",     action="store_true",
                    help="Print counts without writing output")
    return ap.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])
    convert(
        passing_path=args.passing,
        passage_map_path=args.passage_map,
        output_path=args.output,
        originals_path=args.originals,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
