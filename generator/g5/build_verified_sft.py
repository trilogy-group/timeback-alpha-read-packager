#!/usr/bin/env python3
"""
build_verified_sft.py

Builds verified_sft_g5.jsonl — a Fireworks CHAT-format SFT corpus from:
  1. Non-MCQ/MSQ InceptBench-PASS items in shape_repaired_candidates.jsonl
  2. The 600 published course items from g5_bundle_fixed.jsonl (non-MCQ/MSQ)

Each training example:
  system: PASSAGE-NECESSITY RULES (from PASSAGE_DESIGN_RULES.md)
  user:   PASSAGE + STANDARD + FORMAT
  assistant: full item JSON

Usage:
  python3 build_verified_sft.py \
    --candidates /path/to/shape_repaired_candidates.jsonl \
    --bundle /tmp/g5_bundle_fixed.jsonl \
    --output /tmp/verified_sft_g5.jsonl \
    [--max-items N]
"""

import argparse, json, re, html, random, sys
from html.parser import HTMLParser

# ─── PASSAGE-NECESSITY RULES (from PASSAGE_DESIGN_RULES.md lines 133-173) ────
PASSAGE_RULES = """## PASSAGE-NECESSITY RULES

Every passage you generate must be passage-dependent: a student who studied this topic in school should be UNABLE to answer the questions without reading THIS specific passage. The rules below define how to achieve that.

### Passages that produce leaked items — AVOID these

**Curriculum-fact passages** summarize well-documented topics: famous scientists and their discoveries, major historical events with known outcomes, standard definitions of scientific terms, or consensus positions on environmental issues. These topics are taught in grades K-8 and any student who paid attention in class already carries the answer. Questions built on these passages test background knowledge, not reading.

**Headline-figure passages** anchor around the famous number or date everyone knows: the year of the moon landing, the speed of light, the boiling point of water, the population of a major country. These figures are pre-loaded.

**Summary-of-a-famous-person passages** list what a well-known figure did, achieved, or was known for. The biography of Marie Curie, Neil Armstrong, or Frederick Douglass is curriculum content.

**Generic-process passages** explain how a standard process works — photosynthesis, the water cycle, plate tectonics — using only the textbook explanation.

### Passages that produce passage-dependent items — USE these

**Decision-and-reaction passages** place a specific individual at a moment of choice or emotional response. The character's specific reasoning, doubt, or reversal is only accessible through this passage.

**Argument-stance passages** take an explicit, debatable position on a question where reasonable people disagree. The author's specific claim and the evidence marshaled to support it are created inside this text.

**Obscure-consequence passages** treat a famous event from an unfamiliar angle: the ecological aftermath of a well-known disaster, the economic ripple from a famous law, the unintended beneficiary of a celebrated invention.

**Surprising-reversal passages** present information that contradicts the student's likely prior expectation. The reversal is the key piece of content.

**Specific-comparison passages** adjudicate between two named things using criteria introduced in the passage itself.

**Causal-chain passages** present a sequence of causes and effects in a specific order where a student who knows only the beginning and end cannot answer questions about the intermediate steps.

### The passage-necessity test

Before writing any item for a passage, run this check:
> Could a student who studied this topic in school — but did NOT read this specific passage — answer this question correctly?
If YES: the passage is leaking. Fix the passage first, then rebuild the items."""


SYSTEM_PROMPT = f"""You are an expert Grade 5 reading assessment designer. You generate questions that are genuinely passage-dependent: a student who studied the topic in school but did NOT read this specific passage cannot answer the question from prior knowledge alone.

{PASSAGE_RULES}

Output valid JSON with the exact structure for the requested item type."""


# ─── HTML → plain text ────────────────────────────────────────────────────────

class _Stripper(HTMLParser):
    def __init__(self): super().__init__(); self.parts = []
    def handle_data(self, d): self.parts.append(d)
    def get_text(self): return "".join(self.parts)

def strip_html(text):
    if not text: return ""
    text = html.unescape(str(text))
    if not re.search(r'<[a-zA-Z]', text):
        return text
    s = _Stripper(); s.feed(text); return s.get_text().strip()


# ─── Item → clean JSON for assistant turn ─────────────────────────────────────

def item_to_json(row):
    """Convert a shape_repaired_candidates row to a clean item JSON dict."""
    t = row.get('type', '')
    std = row.get('substandard_id', '')

    if t == 'sequence':
        return {
            "type": "sequence",
            "standard": std,
            "question": row.get('question', ''),
            "items": row.get('items', []),
            "correct_order": row.get('correct_order', []),
        }

    if t == 'match':
        return {
            "type": "match",
            "standard": std,
            "question": row.get('question', ''),
            "categories": row.get('categories', []),
            "items": row.get('items', []),
        }

    if t == 'hot-text':
        # stimulus may contain [[token]] markup for selectable spans
        return {
            "type": "hot-text",
            "standard": std,
            "question": row.get('question', ''),
            "annotated_passage": row.get('stimulus', ''),
            "answer_explanation": row.get('answer_explanation', ''),
        }

    if t == 'ebsr':
        def clean_options(opts):
            return [{"key": o.get("key"), "text": o.get("text"),
                     "is_correct": o.get("is_correct"),
                     "feedback": o.get("feedback")} for o in (opts or [])]

        pa = row.get('part_a', {})
        pb = row.get('part_b', {})
        return {
            "type": "ebsr",
            "standard": std,
            "part_a": {
                "question": pa.get('question', ''),
                "answer_options": clean_options(pa.get('answer_options', [])),
            },
            "part_b": {
                "question": pb.get('question', ''),
                "answer_options": clean_options(pb.get('answer_options', [])),
            },
        }

    return None


def bundle_item_to_json(row):
    """Convert a g5_bundle item row to clean item JSON for SFT."""
    t = row.get('type', '')
    std = row.get('substandard_id', '')

    if t in ('mcq', 'msq'):
        return None  # skip MCQ/MSQ from bundle too

    def clean_opts(opts):
        return [{"key": o.get("key") or o.get("id"), "text": o.get("text"),
                 "is_correct": o.get("is_correct", False),
                 "feedback": o.get("feedback", "")} for o in (opts or [])]

    if t == 'sequence':
        return {
            "type": "sequence",
            "standard": std,
            "question": row.get('question', ''),
            "items": row.get('items', []),
            "correct_order": row.get('correct_order', []),
        }

    if t == 'match':
        return {
            "type": "match",
            "standard": std,
            "question": row.get('question', ''),
            "categories": row.get('categories', []),
            "items": row.get('items', []),
        }

    if t in ('hot-text', 'hottext'):
        return {
            "type": "hot-text",
            "standard": std,
            "question": row.get('question') or (row.get('part_a', {}) or {}).get('question', ''),
            "annotated_passage": row.get('stimulus', {}),
            "answer_explanation": row.get('answer_explanation', ''),
        }

    if t == 'ebsr':
        pa = row.get('part_a', {})
        pb = row.get('part_b', {})
        return {
            "type": "ebsr",
            "standard": std,
            "part_a": {
                "question": pa.get('question', '') if isinstance(pa, dict) else '',
                "answer_options": clean_opts(pa.get('answer_options', []) if isinstance(pa, dict) else []),
            },
            "part_b": {
                "question": pb.get('question', '') if isinstance(pb, dict) else '',
                "answer_options": clean_opts(pb.get('answer_options', []) if isinstance(pb, dict) else []),
            },
        }

    return None


def get_passage(row):
    """Extract plain-text passage from a row (either source)."""
    stim = row.get('stimulus', '')
    if isinstance(stim, dict):
        stim = stim.get('value', '') or stim.get('content', '')
    return strip_html(str(stim or ''))


def make_chat_record(passage, item_json, item_type, standard):
    """Build a single Fireworks CHAT-format training record."""
    if not passage.strip() or item_json is None:
        return None

    user_content = (
        f"PASSAGE:\n{passage}\n\n"
        f"STANDARD: {standard}\n"
        f"FORMAT: {item_type}\n\n"
        "Generate one passage-dependent assessment item."
    )

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": json.dumps(item_json, ensure_ascii=False)},
        ]
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True,
                    help="shape_repaired_candidates.jsonl path")
    ap.add_argument("--bundle", default=None,
                    help="g5_bundle_fixed.jsonl (optional, adds published course items)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-items", type=int, default=None,
                    help="Cap total records (for quick tests)")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    random.seed(a.seed)
    records = []
    skipped = 0

    # ── Source 1: shape_repaired_candidates ────────────────────────────────
    print("Loading shape_repaired_candidates...")
    with open(a.candidates) as f:
        cands = [json.loads(l) for l in f if l.strip()]

    GOOD_TYPES = {'hot-text', 'sequence', 'match', 'ebsr'}
    for row in cands:
        t = row.get('type', '')
        if t not in GOOD_TYPES:
            continue
        if not row.get('evaluation', {}).get('inceptbench', {}).get('passed', False):
            continue
        passage = get_passage(row)
        if len(passage) < 80:  # skip stub passages
            skipped += 1
            continue
        item_json = item_to_json(row)
        if item_json is None:
            skipped += 1
            continue
        rec = make_chat_record(passage, item_json, t, row.get('substandard_id', ''))
        if rec:
            records.append(rec)

    print(f"  From candidates: {len(records)} records ({skipped} skipped)")

    # ── Source 2: published bundle (non-MCQ/MSQ only) ─────────────────────
    if a.bundle:
        print(f"Loading bundle {a.bundle}...")
        with open(a.bundle) as f:
            bundle_rows = [json.loads(l) for l in f if l.strip()]
        bundle_items = [r for r in bundle_rows if r.get('type') not in ('article', 'mcq', 'msq', None)]
        bundle_added = 0
        for row in bundle_items:
            t = (row.get('type') or '').replace('hottext', 'hot-text')
            if t not in GOOD_TYPES:
                continue
            passage = get_passage(row)
            if len(passage) < 80:
                continue
            item_json = bundle_item_to_json(row)
            if item_json is None:
                continue
            rec = make_chat_record(passage, item_json, t, row.get('substandard_id', ''))
            if rec:
                records.append(rec)
                bundle_added += 1
        print(f"  From bundle: {bundle_added} records")

    # ── Shuffle + cap ─────────────────────────────────────────────────────
    random.shuffle(records)
    if a.max_items:
        records = records[:a.max_items]

    # ── Write ─────────────────────────────────────────────────────────────
    with open(a.output, 'w') as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    from collections import Counter
    types_out = Counter(
        json.loads(r['messages'][2]['content']).get('type', '?')
        for r in records
    )
    token_est = sum(
        len(r['messages'][0]['content']) + len(r['messages'][1]['content']) + len(r['messages'][2]['content'])
        for r in records
    ) // 4  # rough chars→tokens

    print(f"\n=== OUTPUT: {a.output} ===")
    print(f"Total records: {len(records)}")
    print(f"Type distribution: {dict(types_out)}")
    print(f"Estimated tokens: ~{token_est:,} (~${token_est/1_000_000:.2f} at $1/M)")


if __name__ == "__main__":
    main()
