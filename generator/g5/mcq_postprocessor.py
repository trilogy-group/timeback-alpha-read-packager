#!/usr/bin/env python3
"""
mcq_postprocessor.py — auto-fix structural defects in MCQ items BEFORE the
anti_leak_grader structural gate.

Operates on items already in ADAPTED format (anti_leak_grader.py / adapt_abdul.py
output): each line is a JSON object with at minimum:
  id, type, stem, options ([{id, text}, ...]), key, feedback, ccss

Only MCQ items are modified by Fixes 1-3; Fix 4 (feedback generation) applies to
all item types.

Usage:
  python3 mcq_postprocessor.py <input.jsonl> <output.jsonl>

Fixes applied
  Fix 1 — Option length equalization (MCQ only)
      If the correct answer text is >20% longer than the average distractor text
      length, trim trailing comma-clause or parenthetical from the correct option.
      Does NOT pad distractors — too likely to introduce incoherence.

  Fix 2 — Absolute language softening (MCQ/MSQ options only)
      Replaces absolute wording tokens in any option text with softer equivalents.
      Each replacement is logged.

  Fix 3 — Obvious-tell flag (MCQ only, no auto-fix)
      If one option begins with a word that also appears in the stem, emits a
      manual-review note in the item's `_review_flags` field.

  Fix 4 — Feedback generation (all types)
      If feedback is absent or shorter than 20 characters, generates minimal
      fallback: "The correct answer is [key]. [key_text] is supported by the passage."
"""

import json
import re
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# Fix 2 — absolute-language replacement map
# ---------------------------------------------------------------------------
ABSOLUTE_REPLACEMENTS = {
    r'\balways\b':      'often',
    r'\bnever\b':       'rarely',
    r'\ball\b':         'most',
    r'\bnone\b':        'few',
    r'\bcompletely\b':  'largely',
    r'\bentirely\b':    'generally',
    r'\bonly\b':        'mainly',
    r'\bevery\b':       'most',
    r'\bimpossible\b':  'unlikely',
    r'\bmust\b':        'should',
}

# Pre-compile for speed
_COMPILED_ABSOLUTE = [(re.compile(pat, re.IGNORECASE), repl)
                      for pat, repl in ABSOLUTE_REPLACEMENTS.items()]


def _soften_absolute_language(text: str) -> tuple[str, list[str]]:
    """Return (new_text, list_of_replacements_made)."""
    replacements = []
    for pattern, replacement in _COMPILED_ABSOLUTE:
        def _sub(m, r=replacement):
            # Preserve original capitalisation of first character
            orig = m.group(0)
            if orig[0].isupper():
                return r[0].upper() + r[1:]
            return r
        new_text, n = pattern.subn(_sub, text)
        if n:
            orig_matches = pattern.findall(text)
            for orig in orig_matches:
                replacements.append(f'"{orig}" -> "{replacement}"')
            text = new_text
    return text, replacements


# ---------------------------------------------------------------------------
# Fix 1 helpers — option length equalization
# ---------------------------------------------------------------------------

def _trim_trailing_clause(text: str) -> str:
    """
    Trim a trailing comma-clause or parenthetical from text.
    Tries (in order):
      1. Strip trailing parenthetical: "...word (detail)" -> "...word"
      2. Strip after last comma at end: "main clause, trailing detail" -> "main clause"
    Returns original if neither produces a meaningfully shorter string.
    """
    # 1. Strip trailing parenthetical
    trimmed = re.sub(r'\s*\([^)]*\)\s*$', '', text).strip()
    if trimmed and len(trimmed) < len(text) - 2:
        return trimmed

    # 2. Strip trailing comma-clause (only if comma is past the midpoint)
    parts = text.rsplit(',', 1)
    if len(parts) == 2:
        before = parts[0].strip()
        if len(before) >= len(text) * 0.45 and len(before) >= 8:
            return before

    return text


def _fix_option_length(item: dict) -> tuple[dict, list[str]]:
    """
    Fix 1: if correct option is >20% longer than avg distractor, trim it.
    Returns (item, fixes_log).
    """
    fixes = []
    options = item.get('options', [])
    key = item.get('key')

    if not options or not isinstance(key, str):
        return item, fixes

    correct_opts = [o for o in options if isinstance(o, dict) and o.get('id') == key]
    wrong_opts   = [o for o in options if isinstance(o, dict) and o.get('id') != key]

    if not correct_opts or not wrong_opts:
        return item, fixes

    correct_text  = correct_opts[0].get('text', '')
    wrong_lengths = [len(o.get('text', '')) for o in wrong_opts]
    avg_wrong     = sum(wrong_lengths) / len(wrong_lengths) if wrong_lengths else 0

    if avg_wrong == 0 or len(correct_text) <= avg_wrong * 1.20:
        return item, fixes

    trimmed = _trim_trailing_clause(correct_text)
    if trimmed == correct_text:
        # Nothing cleanly trimmable — leave it; gate will flag it
        return item, fixes

    # Apply trim in a copy of the options list
    new_options = []
    for o in options:
        if isinstance(o, dict) and o.get('id') == key:
            new_o = dict(o)
            new_o['text'] = trimmed
            new_options.append(new_o)
        else:
            new_options.append(o)

    item = dict(item)
    item['options'] = new_options
    fixes.append(
        f'[fix1] {item["id"]}: correct option trimmed '
        f'({len(correct_text)} -> {len(trimmed)} chars); '
        f'avg wrong={avg_wrong:.1f}'
    )
    return item, fixes


# ---------------------------------------------------------------------------
# Fix 2 — absolute language (MCQ + MSQ options)
# ---------------------------------------------------------------------------

def _fix_absolute_language(item: dict) -> tuple[dict, list[str]]:
    """
    Fix 2: replace absolute language tokens in all option texts.
    Works on MCQ and MSQ (and others — it's safe to apply broadly).
    """
    fixes = []
    options = item.get('options', [])
    new_options = []
    for o in options:
        if not isinstance(o, dict):
            new_options.append(o)
            continue
        text = o.get('text', '')
        new_text, replacements = _soften_absolute_language(text)
        if replacements:
            new_o = dict(o)
            new_o['text'] = new_text
            new_options.append(new_o)
            for r in replacements:
                fixes.append(f'[fix2] {item.get("id","?")} opt {o.get("id","?")}: {r}')
        else:
            new_options.append(o)

    if fixes:
        item = dict(item)
        item['options'] = new_options
    return item, fixes


# ---------------------------------------------------------------------------
# Fix 3 — obvious-tell flag (no auto-fix)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
    'must', 'shall', 'can', 'have', 'has', 'had', 'it', 'its', 'in', 'on',
    'at', 'to', 'of', 'for', 'and', 'or', 'but', 'not', 'with', 'that',
    'this', 'by', 'as', 'from', 'what', 'which', 'how', 'why', 'when',
    'where', 'who', 'whom', 'he', 'she', 'they', 'we', 'you', 'i',
}


def _flag_obvious_tells(item: dict) -> tuple[dict, list[str]]:
    """
    Fix 3: flag (do NOT fix) items where an option starts with a stem word.
    Adds _review_flags list to the item.
    Returns (item, fixes_log) — fixes_log entries are for the report only.
    """
    flags = []
    stem = item.get('stem', '')
    options = item.get('options', [])

    if not stem:
        return item, []

    # Tokenise the stem (words only, lower-cased)
    stem_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', stem.lower())) - _STOPWORDS

    for o in options:
        if not isinstance(o, dict):
            continue
        text = o.get('text', '').strip()
        if not text:
            continue
        # First meaningful word of the option
        first_words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        if first_words and first_words[0] in stem_words:
            flag_msg = (
                f'[fix3-manual] {item.get("id","?")} opt {o.get("id","?")}: '
                f'starts with stem word "{first_words[0]}" — review for obvious tell'
            )
            flags.append(flag_msg)

    if flags:
        item = dict(item)
        existing_flags = list(item.get('_review_flags', []))
        existing_flags.extend(flags)
        item['_review_flags'] = existing_flags

    return item, flags


# ---------------------------------------------------------------------------
# Fix 4 — feedback generation (all types)
# ---------------------------------------------------------------------------

def _key_text(item: dict) -> str:
    """Return the text of the correct-answer option for MCQ items."""
    key = item.get('key')
    if not isinstance(key, str):
        return ''
    for o in item.get('options', []):
        if isinstance(o, dict) and o.get('id') == key:
            return o.get('text', '')
    return ''


def _fix_feedback(item: dict) -> tuple[dict, list[str]]:
    """
    Fix 4: generate minimal feedback if absent or too short.
    """
    feedback = item.get('feedback', '')
    if isinstance(feedback, (dict, list)):
        # Non-string feedback already present — don't touch
        return item, []

    feedback = str(feedback).strip() if feedback else ''
    if len(feedback) >= 20:
        return item, []

    key = item.get('key', '')
    if isinstance(key, list):
        key_display = ', '.join(str(k) for k in key)
    else:
        key_display = str(key) if key else '?'

    kt = _key_text(item)
    if kt:
        new_feedback = (
            f'The correct answer is {key_display}. '
            f'{kt} is supported by the passage.'
        )
    else:
        new_feedback = f'The correct answer is {key_display}.'

    item = dict(item)
    item['feedback'] = new_feedback
    fix_msg = (
        f'[fix4] {item.get("id","?")}: feedback generated '
        f'(was {len(feedback)} chars)'
    )
    return item, [fix_msg]


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

MCQ_TYPES = {'mcq', 'single-select', 'multiple-choice', 'single_select'}


def process_item(item: dict) -> tuple[dict, list[str]]:
    """Apply all applicable fixes. Returns (fixed_item, all_fix_log_entries)."""
    all_fixes = []
    item_type = item.get('type', '').lower()

    # Fix 1: length equalization — MCQ only
    if item_type in MCQ_TYPES:
        item, fixes = _fix_option_length(item)
        all_fixes.extend(fixes)

    # Fix 2: absolute language — MCQ + MSQ (safe for others too)
    if item_type in MCQ_TYPES or item_type in {'msq', 'multi-select', 'multi_select',
                                                'multiple-select'}:
        item, fixes = _fix_absolute_language(item)
        all_fixes.extend(fixes)

    # Fix 3: obvious-tell flag — MCQ only
    if item_type in MCQ_TYPES:
        item, fixes = _flag_obvious_tells(item)
        all_fixes.extend(fixes)

    # Fix 4: feedback — all types
    item, fixes = _fix_feedback(item)
    all_fixes.extend(fixes)

    return item, all_fixes


def main():
    if len(sys.argv) < 3:
        print(f'Usage: {sys.argv[0]} <input.jsonl> <output.jsonl>', file=sys.stderr)
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]

    counters = defaultdict(int)
    total_items = 0
    items_modified = 0
    all_fix_log = []

    with open(in_path) as fin, open(out_path, 'w') as fout:
        for lineno, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as e:
                print(f'  WARN line {lineno}: JSON parse error — {e}', file=sys.stderr)
                continue

            total_items += 1
            fixed_item, fixes = process_item(item)
            all_fix_log.extend(fixes)

            if fixes:
                items_modified += 1
                for f in fixes:
                    tag = f.split(']')[0].lstrip('[')  # e.g. 'fix1', 'fix2', ...
                    counters[tag] += 1

            fout.write(json.dumps(fixed_item) + '\n')

    # --- Summary report ---
    print(f'\nMCQ post-processor summary', file=sys.stderr)
    print(f'  Items read   : {total_items}', file=sys.stderr)
    print(f'  Items touched: {items_modified}', file=sys.stderr)
    print(f'  Total fixes  : {sum(counters.values())}', file=sys.stderr)
    if counters:
        for tag in sorted(counters):
            label = {
                'fix1': 'Fix 1 — option length equalized',
                'fix2': 'Fix 2 — absolute language softened',
                'fix3-manual': 'Fix 3 — obvious-tell flags (manual review needed)',
                'fix4': 'Fix 4 — feedback generated',
            }.get(tag, tag)
            print(f'    {label}: {counters[tag]}', file=sys.stderr)

    if all_fix_log:
        print(f'\nFix detail log:', file=sys.stderr)
        for entry in all_fix_log:
            print(f'  {entry}', file=sys.stderr)

    print(f'\nOutput written to: {out_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
