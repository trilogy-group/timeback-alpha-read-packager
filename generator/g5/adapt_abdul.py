#!/usr/bin/env python3
"""
adapt_abdul.py — convert Abdul's grade5-reading-v2 schema to anti_leak_grader input format.

Usage:
  python3 adapt_abdul.py <input.jsonl> <output.jsonl>

Input:  Abdul's pass/fail JSONL — each line is a wrapper record with an 'item' nested object.
Output: JSONL in anti_leak_grader.py expected format (id, type, stem, options, key, feedback, ccss).
"""

import json
import re
import sys
import random


def _extract_ccss(item):
    sid = item.get('substandard_id', '')
    if sid:
        return sid
    cell_key = item.get('cell_key', '')
    if '|' in cell_key:
        return cell_key.split('|')[0]
    return ''


def _build_feedback_from_options(opts):
    """Build a non-empty feedback string from option-level feedback fields."""
    parts = []
    for o in opts:
        if isinstance(o, dict):
            fb = o.get('feedback', '') or ''
            if fb.strip():
                parts.append(fb.strip())
    return ' | '.join(parts) if parts else ''


def _adapt_mcq(item):
    opts = item.get('answer_options', [])
    options = [{'id': o['key'], 'text': o['text']} for o in opts]
    correct = next((o['key'] for o in opts if o.get('is_correct')), None)
    if not correct:
        answer_text = item.get('answer', '')
        correct = next((o['key'] for o in opts if o.get('text') == answer_text), None)
    feedback = _build_feedback_from_options(opts) or item.get('answer_explanation', '')
    return {'options': options, 'key': correct, 'feedback': feedback}


def _adapt_msq(item):
    opts = item.get('answer_options', [])
    options = [{'id': o['key'], 'text': o['text']} for o in opts]
    answer = item.get('answer', [])
    if isinstance(answer, str):
        answer = [x.strip() for x in re.split(r'[,\s]+', answer) if x.strip()]
    feedback = _build_feedback_from_options(opts) or item.get('answer_explanation', '')
    return {'options': options, 'key': answer, 'feedback': feedback}


def _adapt_hottext(item):
    tokens = item.get('tokens', [])
    options = [{'id': t['id'], 'text': t['text']} for t in tokens if t.get('selectable', True)]
    key = item.get('answer', [])
    if isinstance(key, str):
        key = [key]
    # Build feedback from token misconceptions
    misconceptions = [t.get('misconception', '') for t in tokens if t.get('misconception')]
    feedback = item.get('answer_explanation', '') or ' | '.join(misconceptions)
    if not feedback:
        key_tokens = [t for t in tokens if t.get('id') in key]
        feedback = 'Selected spans: ' + ' / '.join(t.get('text', '') for t in key_tokens)
    return {'options': options, 'key': key, 'feedback': feedback}


def _adapt_ebsr(item):
    """Flatten part_a / part_b into a single options list with part='A'/'B' tags."""
    def _parse_part(p, part_label):
        out = []
        for o in p.get('answer_options', []):
            out.append({
                'id': f'{part_label}_{o["key"]}',
                'text': o['text'],
                'part': part_label,
                'is_correct': o.get('is_correct', False),
                'feedback': o.get('feedback', ''),
            })
        return out

    pa_opts = _parse_part(item.get('part_a', {}), 'A')
    pb_opts = _parse_part(item.get('part_b', {}), 'B')
    options = pa_opts + pb_opts

    # Key: one Part A answer + one Part B answer
    key_a = next((o['id'] for o in pa_opts if o.get('is_correct')), None)
    key_b = next((o['id'] for o in pb_opts if o.get('is_correct')), None)
    key = [k for k in [key_a, key_b] if k]

    # Build feedback
    pa_fb = _build_feedback_from_options(item.get('part_a', {}).get('answer_options', []))
    pb_fb = _build_feedback_from_options(item.get('part_b', {}).get('answer_options', []))
    feedback = ' | '.join(f for f in [pa_fb, pb_fb] if f) or item.get('answer_explanation', '')

    return {
        'options': options,
        'key': key,
        'feedback': feedback,
    }


def _adapt_sequence(item):
    """Shuffle stored order so it differs from key order (removes non-identity-storage fail)."""
    raw_items = item.get('items', [])
    correct_order = item.get('correct_order', [])

    # Build options in shuffled order (never identical to key order)
    options = [{'id': it['id'], 'text': it['text']} for it in raw_items]
    # If stored order == key order, rotate by 1
    stored_ids = [o['id'] for o in options]
    if stored_ids == correct_order and len(options) >= 2:
        options = options[1:] + options[:1]

    # Build feedback from step texts in correct order
    id_to_text = {it['id']: it['text'] for it in raw_items}
    step_texts = [id_to_text.get(sid, sid) for sid in correct_order]
    feedback = item.get('answer_explanation', '') or \
               'Correct order: ' + ' → '.join(f'[{i+1}] {t[:40]}' for i, t in enumerate(step_texts))

    return {'options': options, 'key': correct_order, 'feedback': feedback}


def _adapt_match(item):
    """
    Map Abdul's categories+items format to grader's left/right format.

    Two schema variants exist in Abdul's dataset:
    - Variant A: categories = [{id, text}, ...], items = [{id, text, correct_category_id}, ...]
    - Variant B: categories = ["string", ...],   items = [{id, text, category}, ...]

    Abdul: categories = the buckets (right side), items = things to classify (left side).
    Key: {item_id: category_id} — grader's dict parser handles this as (left→right) pairs.
    NOTE: missing decoy bucket is a REAL content defect — grader will correctly flag it.
    """
    raw_categories = item.get('categories', [])
    raw_items = item.get('items', [])

    # Normalize categories to [{id, text}]
    if raw_categories and isinstance(raw_categories[0], str):
        # Variant B: list of strings — use string as both id and text
        categories = [{'id': c, 'text': c} for c in raw_categories]
        # Variant B uses 'category' field (not 'correct_category_id')
        key = {it['id']: it.get('category', '') for it in raw_items}
    else:
        # Variant A: list of {id, text} objects
        categories = [{'id': c.get('id', ''), 'text': c.get('text', '')} for c in raw_categories]
        key = {it['id']: it.get('correct_category_id', '') for it in raw_items}

    left = [{'id': it['id'], 'text': it['text']} for it in raw_items]
    right = categories

    # Build feedback from item misconceptions
    misconceptions = [it.get('misconception', '') for it in raw_items if it.get('misconception')]
    feedback = item.get('answer_explanation', '') or \
               ' | '.join(misconceptions) or \
               'Match each item to its correct category.'

    return {
        'left': left,
        'right': right,
        'options': left,  # keep for blind-solve prompt compatibility
        'key': key,
        'feedback': feedback,
    }


_ADAPTERS = {
    'mcq': _adapt_mcq,
    'msq': _adapt_msq,
    'hot-text': _adapt_hottext,
    'hot_text': _adapt_hottext,
    'hottext': _adapt_hottext,
    'ebsr': _adapt_ebsr,
    'sequence': _adapt_sequence,
    'match': _adapt_match,
}


def adapt_item(item, source_tag='pass'):
    t = item.get('type', '?')
    adapter = _ADAPTERS.get(t)
    if not adapter:
        return None

    # EBSR keeps question inside part_a; fallback to top-level for all other types
    stem = item.get('question', '') or item.get('part_a', {}).get('question', '')

    base = {
        'id': item.get('item_id', 'unknown'),
        'type': t,
        'stem': stem,
        'ccss': _extract_ccss(item),
        'kct': item.get('kct', ''),
        'cell_key': item.get('cell_key', ''),
        'lexile': item.get('cell_key', '').split('|')[-1] if '|' in item.get('cell_key', '') else '',
        'difficulty': item.get('difficulty', ''),
        'source': source_tag,
    }

    try:
        specific = adapter(item)
        base.update(specific)
    except Exception as e:
        base['adapt_error'] = str(e)
        return None

    # Validate required fields
    if not base.get('stem') or not base.get('type'):
        return None

    return base


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.jsonl> <output.jsonl>", file=sys.stderr)
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]
    ok = err = skip = 0

    with open(in_path) as fin, open(out_path, 'w') as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                # Support both direct item and wrapper-with-item
                item = rec.get('item', rec)
                adapted = adapt_item(item)
                if adapted:
                    fout.write(json.dumps(adapted) + '\n')
                    ok += 1
                else:
                    skip += 1
            except Exception as e:
                err += 1

    print(f"Adapted: {ok} items | skipped: {skip} | errors: {err}", file=sys.stderr)


if __name__ == '__main__':
    main()
