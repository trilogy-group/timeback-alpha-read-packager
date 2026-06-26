#!/usr/bin/env python3
"""
cross_family_validator.py — Cross-family blind-solve validation for Grade-5 MCQ items.

DESIGN RATIONALE
----------------
When a model generates items AND blind-solves them, same-family bias inflates pass rates.
Claude Sonnet generated the L.5 vocab MCQ items in this session. If Claude Sonnet (or
any Claude model) also blind-solves them, the result is unreliable — empirically 90%+
same-family leak rate even with new passage design rules (see g5-blind-solve-finding.md).

This script uses a DIFFERENT MODEL to blind-solve:
  - Generator : claude-sonnet-4-6 (this session's generator)
  - Validator : claude-haiku-4-5 (different model tier — cheaper, different fine-tune)

FOR PRODUCTION USE: replace claude-haiku-4-5 with gemini-2.0-flash (Google) for TRUE
cross-family validation. Haiku vs. Sonnet is a weaker isolation than Claude vs. Gemini.
The Haiku run is a useful sanity check and a cheaper first pass; it is NOT a substitute
for a Gemini cross-family run before a course goes live.

PREDICTED LEAK DISTRIBUTION (L.5 vocab MCQ families)
----------------------------------------------------
  L.5.4a  context clues       : SHOULD PASS — answer requires the passage
  L.5.5a  figurative language  : MIXED — familiar idioms/proverbs may leak
  L.5.4b  affixes              : LIKELY LEAKED — "which prefix means NOT?" = world knowledge
  L.5.5b  synonyms             : LIKELY LEAKED — "which means HAPPY?" needs no passage
  L.5.5c  connotations         : LIKELY LEAKED — "which has positive connotation?" = world knowledge

USAGE
-----
  # Validate a JSONL already in anti_leak_grader format (output of adapt_abdul.py)
  python3 cross_family_validator.py items_adapted.jsonl

  # Validate the L.5 vocab seeds JSON directly (flat list or {"items": [...]})
  python3 cross_family_validator.py l5_vocab_seeds_v2.json

  # Limit to first N items (spot-check)
  python3 cross_family_validator.py items.jsonl --sample 10

  # Write results to a specific output file
  python3 cross_family_validator.py items.jsonl --output results.jsonl

  # Use a different validator model
  python3 cross_family_validator.py items.jsonl --model gemini-2.0-flash

  # Dry-run: print the prompts that WOULD be sent, no API calls
  python3 cross_family_validator.py items.jsonl --dry-run

INPUT FORMAT
-----------
Each item (JSON object) must have:
  stem     : str   The question text
  options  : list  Each option is a string or {"id": ..., "text": ...}
  key      : str   The correct answer id / text
  ccss     : str   The standard code (used for by_ccss summary)
  type     : str   (optional) defaults to "mcq"

Fields deliberately IGNORED by the validator (leak prevention):
  passage_text, feedback, humanApproved, difficulty, lexile, source

OUTPUT FORMAT (JSONL)
--------------------
Each output line is the input item with an added "blind_solve_result" key:
{
  ...original item fields...,
  "blind_solve_result": {
    "model":   "claude-haiku-4-5",
    "picked":  "B",          -- which option id/letter the model chose
    "correct": true|false,   -- does picked == key?
    "leaked":  true|false,   -- same as correct (leaked = validator got it right blind)
    "confidence": 0.0-1.0,   -- model's stated confidence
    "tell":    "...",        -- what the model says it exploited (or "none")
    "raw":     "..."         -- raw model response (truncated to 500 chars)
  }
}

Summary printed to stderr (and to --output-summary if provided):
  total, leaked_n, leak_pct
  by_ccss: {code: {total, leaked, pct}}
  by_type: {type: {total, leaked, pct}}

EXIT CODES
----------
  0  : run completed, leak_pct < 20%  (item pool likely usable)
  1  : run completed, leak_pct >= 20% (pool needs redesign)
  2  : usage / load / API error
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-haiku-4-5"
PRODUCTION_MODEL = "gemini-2.0-flash"

# NOTE: For production cross-family validation, use PRODUCTION_MODEL (Gemini).
# claude-haiku-4-5 is a useful sanity check but is still Claude-family.
# Same-family bias is attenuated (Haiku != Sonnet) but NOT eliminated.

LEAK_THRESHOLD_PCT = 20.0   # above this → pool needs redesign

# Claude API limits; leave headroom
MAX_TOKENS = 256             # validator response is short JSON

SYSTEM_PROMPT = (
    "You are a blind-solve validator for Grade-5 reading assessment items. "
    "You will receive a question stem and answer options ONLY — no passage, "
    "no feedback, no answer key. Your task is to determine whether the correct "
    "answer is guessable without reading any passage. "
    "Answer strictly in the JSON format requested. No prose outside the JSON object."
)

USER_PROMPT_TEMPLATE = (
    "BLIND-SOLVE VALIDATION — Grade-5 MCQ\n"
    "\n"
    "You do NOT have the reading passage. Answer based only on what you see below.\n"
    "\n"
    "QUESTION:\n"
    "{stem}\n"
    "\n"
    "OPTIONS:\n"
    "{options_block}\n"
    "\n"
    "Without the passage, which option do you think is most likely correct?\n"
    "Answer in strict JSON only, nothing else:\n"
    '{{"picked": "<option_id>", "confidence": <0.0-1.0>, "tell": "<what you exploited or none>"}}\n'
    "\n"
    "Rules:\n"
    "- picked: the letter/id of the option you would choose (e.g. \"A\", \"B\", \"C\", or \"D\")\n"
    "- confidence: how sure you are, 0.0 (total guess) to 1.0 (certain)\n"
    "- tell: the specific cue you used (e.g. 'prefix un- means not', 'idiom widely known',\n"
    "  'option B is uniquely specific', 'none — pure guess')\n"
    "Do NOT include any text outside the JSON object."
)


# ---------------------------------------------------------------------------
# Option helpers (shared with anti_leak_grader.py conventions)
# ---------------------------------------------------------------------------

def _option_text(opt):
    if isinstance(opt, str):
        return opt.strip()
    if isinstance(opt, dict):
        for k in ("text", "value", "label", "option", "content"):
            v = opt.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in opt.values():
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _option_id(opt, idx):
    if isinstance(opt, dict):
        for k in ("id", "key", "label"):
            v = opt.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(idx)


def _normalize_key(key, options):
    """Return the option id string that matches the key (case-insensitive)."""
    if key is None:
        return None
    key_str = str(key).strip()
    ids = [_option_id(o, i) for i, o in enumerate(options)]
    texts = [_option_text(o) for o in options]
    # exact id match
    for oid in ids:
        if oid.lower() == key_str.lower():
            return oid
    # exact text match
    for oid, text in zip(ids, texts):
        if text.lower() == key_str.lower():
            return oid
    # single letter like "A" -> index 0
    letter_map = {chr(65 + i): ids[i] for i in range(len(ids))}
    if key_str.upper() in letter_map:
        return letter_map[key_str.upper()]
    return key_str  # return as-is; comparison will handle


def _build_options_block(options):
    lines = []
    for i, opt in enumerate(options):
        oid = _option_id(opt, i)
        text = _option_text(opt)
        lines.append(f"  {oid}. {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_items(path):
    """Load items from a .json or .jsonl file. Returns list of dicts."""
    items = []
    ext = os.path.splitext(path)[1].lower()

    if ext == ".jsonl":
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    # Support wrapper {"item": {...}} or flat item
                    if "item" in obj and isinstance(obj["item"], dict):
                        items.append(obj["item"])
                    else:
                        items.append(obj)
                except json.JSONDecodeError as e:
                    sys.stderr.write(f"WARNING: skipping malformed JSONL line {lineno}: {e}\n")
    else:
        # .json: list, {"items": [...]}, or {"passage": ..., "items": [...]}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
        else:
            raise ValueError(
                "JSON input must be a list of items, or an object with an 'items' list"
            )

    return items


# ---------------------------------------------------------------------------
# Anthropic API call
# ---------------------------------------------------------------------------

def _get_anthropic_client():
    try:
        import anthropic
    except ImportError:
        sys.stderr.write(
            "ERROR: 'anthropic' package not installed.\n"
            "Install it with: pip install anthropic\n"
        )
        sys.exit(2)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write(
            "ERROR: ANTHROPIC_API_KEY environment variable not set.\n"
        )
        sys.exit(2)
    return anthropic.Anthropic(api_key=api_key)


def _call_claude(client, model, stem, options_block):
    """Call Claude with stem+options only (no passage, no key, no feedback)."""
    user_msg = USER_PROMPT_TEMPLATE.format(
        stem=stem.strip(),
        options_block=options_block,
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip() if response.content else ""
        return raw
    except Exception as e:
        return f'{{"error": "{str(e)[:200]}"}}'


def _parse_model_response(raw):
    """Extract picked/confidence/tell from the model's JSON response."""
    # Find the first {...} block
    m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group())
            picked = str(obj.get("picked", "")).strip()
            confidence = float(obj.get("confidence", 0.5))
            tell = str(obj.get("tell", "none")).strip()
            return picked, confidence, tell
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: grep for a letter
    m2 = re.search(r'"picked"\s*:\s*"([A-Da-d0-9])"', raw)
    picked = m2.group(1).upper() if m2 else "?"
    return picked, 0.5, "parse-error"


# ---------------------------------------------------------------------------
# Core validation loop
# ---------------------------------------------------------------------------

def validate_item(item, client, model, dry_run=False):
    """
    Run blind-solve validation on one item.
    Returns a blind_solve_result dict.
    """
    stem = (item.get("stem") or "").strip()
    options = item.get("options") or []
    key = item.get("key")

    if not stem or not options:
        return {
            "model": model,
            "picked": None,
            "correct": False,
            "leaked": False,
            "confidence": 0.0,
            "tell": "item-missing-stem-or-options",
            "raw": "",
            "skipped": True,
        }

    options_block = _build_options_block(options)
    norm_key = _normalize_key(key, options)

    if dry_run:
        print(f"\n--- DRY RUN: item '{item.get('id', '?')}' ---")
        print(f"STEM: {stem}")
        print(f"OPTIONS:\n{options_block}")
        print(f"KEY (normalized): {norm_key}")
        print(f"Would call: model={model}")
        return {
            "model": model,
            "picked": None,
            "correct": None,
            "leaked": None,
            "confidence": None,
            "tell": "dry-run",
            "raw": "",
        }

    raw = _call_claude(client, model, stem, options_block)
    picked, confidence, tell = _parse_model_response(raw)

    # Normalize picked to match key format
    # The model returns a letter; match against option ids
    norm_picked = _normalize_key(picked, options) if picked and picked != "?" else picked

    correct = (
        norm_picked is not None
        and norm_key is not None
        and norm_picked.upper() == norm_key.upper()
    )

    return {
        "model": model,
        "picked": picked,
        "correct": correct,
        "leaked": correct,   # leaked = validator solved it correctly without the passage
        "confidence": round(confidence, 2),
        "tell": tell,
        "raw": raw[:500],    # truncate for storage
    }


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------

def compute_summary(results, model):
    total = len(results)
    leaked_n = sum(1 for r in results if r.get("blind_solve_result", {}).get("leaked"))
    skipped_n = sum(1 for r in results if r.get("blind_solve_result", {}).get("skipped"))
    usable = total - skipped_n
    leak_pct = (leaked_n / usable * 100.0) if usable > 0 else 0.0

    by_ccss = defaultdict(lambda: {"total": 0, "leaked": 0})
    by_type = defaultdict(lambda: {"total": 0, "leaked": 0})

    for r in results:
        bsr = r.get("blind_solve_result", {})
        if bsr.get("skipped"):
            continue
        ccss = r.get("ccss") or "unknown"
        itype = r.get("type") or "mcq"
        leaked = bool(bsr.get("leaked"))

        by_ccss[ccss]["total"] += 1
        if leaked:
            by_ccss[ccss]["leaked"] += 1
        by_type[itype]["total"] += 1
        if leaked:
            by_type[itype]["leaked"] += 1

    # Add pct
    for d in by_ccss.values():
        d["pct"] = round(d["leaked"] / d["total"] * 100.0, 1) if d["total"] else 0.0
    for d in by_type.values():
        d["pct"] = round(d["leaked"] / d["total"] * 100.0, 1) if d["total"] else 0.0

    return {
        "model": model,
        "total": total,
        "skipped": skipped_n,
        "usable": usable,
        "leaked_n": leaked_n,
        "leak_pct": round(leak_pct, 1),
        "passed_n": usable - leaked_n,
        "pass_pct": round(100.0 - leak_pct, 1),
        "by_ccss": dict(by_ccss),
        "by_type": dict(by_type),
        "threshold_pct": LEAK_THRESHOLD_PCT,
        "pool_verdict": "USABLE" if leak_pct < LEAK_THRESHOLD_PCT else "NEEDS_REDESIGN",
    }


def print_summary(summary, file=sys.stderr):
    m = summary["model"]
    is_true_cross_family = "gemini" in m.lower() or "gpt" in m.lower()
    cross_label = (
        "TRUE CROSS-FAMILY (Gemini)" if "gemini" in m.lower()
        else "SAME-FAMILY TIER (Claude Haiku vs. Sonnet — weaker isolation)"
        if "haiku" in m.lower() or "claude" in m.lower()
        else m
    )

    sep = "=" * 72
    print(sep, file=file)
    print("CROSS-FAMILY BLIND-SOLVE VALIDATION SUMMARY", file=file)
    print(f"  validator model  : {m}", file=file)
    print(f"  isolation level  : {cross_label}", file=file)
    if not is_true_cross_family:
        print(
            "  WARNING: for production use, re-run with gemini-2.0-flash",
            file=file,
        )
    print(sep, file=file)
    print(f"  total items      : {summary['total']}", file=file)
    print(f"  skipped (no stem): {summary['skipped']}", file=file)
    print(f"  usable           : {summary['usable']}", file=file)
    print(f"  leaked           : {summary['leaked_n']}  ({summary['leak_pct']}%)", file=file)
    print(f"  passed           : {summary['passed_n']}  ({summary['pass_pct']}%)", file=file)
    print(f"  threshold        : {summary['threshold_pct']}%", file=file)
    print(f"  POOL VERDICT     : {summary['pool_verdict']}", file=file)
    print(sep, file=file)

    print("  BY CCSS STANDARD:", file=file)
    for code, d in sorted(summary["by_ccss"].items()):
        bar = "LEAKED" if d["pct"] >= LEAK_THRESHOLD_PCT else "ok"
        print(f"    {code:<12}  {d['leaked']:>3}/{d['total']:<3}  ({d['pct']:>5.1f}%)  {bar}", file=file)

    print("  BY ITEM TYPE:", file=file)
    for itype, d in sorted(summary["by_type"].items()):
        bar = "LEAKED" if d["pct"] >= LEAK_THRESHOLD_PCT else "ok"
        print(f"    {itype:<12}  {d['leaked']:>3}/{d['total']:<3}  ({d['pct']:>5.1f}%)  {bar}", file=file)

    print(sep, file=file)

    # Interpretation note for L.5 vocab families
    print("  PREDICTED vs. ACTUAL (L.5 vocab families):", file=file)
    print("    L.5.4a  context clues       : predicted PASS  (passage-dependent)", file=file)
    print("    L.5.5a  figurative language  : predicted MIXED (familiar idioms may leak)", file=file)
    print("    L.5.4b  affixes              : predicted LEAKED (world-knowledge prefix/suffix)", file=file)
    print("    L.5.5b  synonyms             : predicted LEAKED (synonym swap = world knowledge)", file=file)
    print("    L.5.5c  connotations         : predicted LEAKED (pos/neg connotation = world knowledge)", file=file)
    print(sep, file=file)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Cross-family blind-solve validator for Grade-5 MCQ items."
    )
    p.add_argument("input", help="Items file (.json or .jsonl)")
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            f"Validator model (default: {DEFAULT_MODEL}). "
            f"For TRUE cross-family validation use: {PRODUCTION_MODEL}"
        ),
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output JSONL file with blind_solve_result appended to each item. "
             "Defaults to <input_basename>_blind_solved.jsonl",
    )
    p.add_argument(
        "--output-summary",
        default=None,
        help="Write summary JSON to this file (optional).",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Process only the first N items.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts that WOULD be sent; do not call the API.",
    )
    return p.parse_args(argv)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    args = parse_args(argv)

    # Load items
    if not os.path.exists(args.input):
        sys.stderr.write(f"ERROR: file not found: {args.input}\n")
        return 2
    try:
        items = load_items(args.input)
    except Exception as e:
        sys.stderr.write(f"ERROR: could not load {args.input}: {e}\n")
        return 2

    if not items:
        sys.stderr.write(f"ERROR: no items found in {args.input}\n")
        return 2

    # Filter to MCQ only (this validator is designed for MCQ)
    mcq_only = [
        it for it in items
        if (it.get("type") or "mcq").lower() in (
            "mcq", "single-select", "single_select", "multiple-choice", "mc"
        )
    ]
    non_mcq = len(items) - len(mcq_only)
    if non_mcq:
        sys.stderr.write(
            f"INFO: skipping {non_mcq} non-MCQ items "
            f"(this validator is MCQ-only; adapt for other formats if needed)\n"
        )

    work_items = mcq_only
    if args.sample:
        work_items = work_items[: args.sample]

    sys.stderr.write(
        f"Cross-family blind-solve: {len(work_items)} MCQ items | "
        f"validator={args.model}"
    )
    if args.dry_run:
        sys.stderr.write(" | DRY RUN\n")
    else:
        sys.stderr.write("\n")
        if "gemini" not in args.model.lower():
            sys.stderr.write(
                "NOTE: using Claude-family validator. For TRUE cross-family validation,\n"
                f"      re-run with --model {PRODUCTION_MODEL} (requires Google API key).\n"
            )

    # Set up output path
    if args.output:
        out_path = args.output
    else:
        base = os.path.splitext(os.path.basename(args.input))[0]
        out_dir = os.path.dirname(os.path.abspath(args.input))
        out_path = os.path.join(out_dir, f"{base}_blind_solved.jsonl")

    # API client (skip if dry-run)
    client = None
    if not args.dry_run:
        client = _get_anthropic_client()

    results = []
    n_done = 0

    with open(out_path, "w", encoding="utf-8") as fout:
        for i, item in enumerate(work_items):
            item_id = item.get("id") or item.get("item_id") or f"item_{i}"
            if not args.dry_run:
                sys.stderr.write(
                    f"\r  [{i+1:>3}/{len(work_items)}] {item_id:<30}",
                )
                sys.stderr.flush()

            bsr = validate_item(item, client, args.model, dry_run=args.dry_run)

            out_item = dict(item)
            out_item["blind_solve_result"] = bsr
            results.append(out_item)

            if not args.dry_run:
                fout.write(json.dumps(out_item) + "\n")
            n_done += 1

    if not args.dry_run:
        sys.stderr.write("\n")

    # Summary
    summary = compute_summary(results, args.model)
    print_summary(summary)

    if args.output_summary:
        with open(args.output_summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        sys.stderr.write(f"Summary written to: {args.output_summary}\n")

    if not args.dry_run:
        sys.stderr.write(f"Results written to: {out_path}\n")

    return 0 if summary["leak_pct"] < LEAK_THRESHOLD_PCT else 1


if __name__ == "__main__":
    sys.exit(main())
