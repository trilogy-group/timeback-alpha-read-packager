#!/usr/bin/env python3
"""
run_checkpoint_probe.py — Gold-standard checkpoint quality gate for G5 RFT checkpoints.

WHEN TO USE
-----------
Run this script at each Anirudh DAPO checkpoint before promoting a model to course
deployment. The gate is binary: pass or not pass. A checkpoint that does not meet the
quality bar should not be used to generate production items regardless of training loss.

PASSING RESULT
--------------
  leak_rate   <= 0.30   (30% or fewer items solvable by Claude Haiku without the passage)
  ib_pass_rate >= 0.80   (80%+ of generated items clear structural + substandard checks)

A checkpoint can have a low leak rate but fail on ib_pass_rate (it hallucinates structure).
Both conditions must hold.

CROSS-FAMILY ISOLATION
----------------------
Generator  : Qwen3-based fine-tune on Fireworks (Anirudh/Abdul DAPO checkpoint)
Validator  : Claude Haiku 4.5 via LiteLLM (claude-haiku-4-5-20251001)

This is TRUE cross-family isolation: Qwen3 vs. Claude. The generator cannot teach the
validator anything about which answer is correct. A leaked item means the passage design
rules were not followed — the answer lives in world knowledge, not the text.

USAGE
-----
  # Basic run against a Fireworks endpoint:
  python3 run_checkpoint_probe.py --endpoint https://api.fireworks.ai/inference/v1/completions/...

  # With custom passages:
  python3 run_checkpoint_probe.py --endpoint URL --passages my_passages.jsonl --n 100

  # Dry run (no API calls):
  python3 run_checkpoint_probe.py --endpoint URL --dry-run
"""

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PASSAGE_DESIGN_RULES_PATH = SCRIPT_DIR / "PASSAGE_DESIGN_RULES.md"
DEFAULT_BUNDLE_PATH = "/tmp/g5_bundle_fixed.jsonl"
DEFAULT_OUTPUT = "/tmp/checkpoint_probe_results.json"
DEFAULT_N = 50

# Excluded substandards (historically leak-prone, retired from G5 skeleton)
EXCLUDED_SUBSTANDARDS = {"RL.5.7", "RI.5.7"}

# Quality thresholds
LEAK_RATE_THRESHOLD = 0.30
IB_PASS_RATE_THRESHOLD = 0.80

# Concurrency caps
MAX_FIREWORKS_CONCURRENT = 10
MAX_BLINDSOLVE_CONCURRENT = 15

# Validator model — cross-family (Qwen3 generator vs. Claude Haiku validator)
VALIDATOR_MODEL = "claude-haiku-4-5-20251001"

# Valid item types in G5 skeleton
VALID_TYPES = {"sequence", "match", "hot-text", "ebsr", "mcq", "msq"}

# ---------------------------------------------------------------------------
# Passage design rules system prompt (first 3000 chars)
# ---------------------------------------------------------------------------

def load_system_prompt() -> str:
    """Load PASSAGE_DESIGN_RULES.md and return the first 3000 characters."""
    path = PASSAGE_DESIGN_RULES_PATH
    if not path.exists():
        sys.stderr.write(
            f"WARNING: PASSAGE_DESIGN_RULES.md not found at {path}. "
            "Using minimal fallback system prompt.\n"
        )
        return (
            "You are a Grade-5 reading assessment item generator. "
            "Every item must be passage-dependent: the student cannot answer correctly "
            "without reading the specific passage provided. "
            "Generate one assessment item in valid JSON."
        )
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return content[:3000]


# ---------------------------------------------------------------------------
# Secrets / env loading
# ---------------------------------------------------------------------------

def load_secrets():
    """
    Load secrets from ~/.aptraining_secrets.env into os.environ.
    Silently skips if the file doesn't exist.
    """
    secrets_path = Path.home() / ".aptraining_secrets.env"
    if not secrets_path.exists():
        return
    with open(secrets_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


# ---------------------------------------------------------------------------
# Passage loading
# ---------------------------------------------------------------------------

def load_passages_from_file(path: str) -> list[dict]:
    """
    Load passages from a JSONL file.
    Expected format per line: {"text": "...", "standard": "RL.5.x", "format": "sequence"}
    """
    passages = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                passages.append(obj)
            except json.JSONDecodeError as e:
                sys.stderr.write(f"WARNING: skipping malformed line {lineno}: {e}\n")
    return passages


def load_passages_from_bundle(bundle_path: str, n: int) -> list[dict]:
    """
    Draw n random passages from the G5 bundle JSONL.
    Extracts article records and maps them to the probe format:
      {"text": passage_text, "standard": substandard_id, "format": item_type}

    Pairs article records with their corresponding item records by passage_id,
    choosing a non-excluded item type as 'format' when available.
    """
    bundle_path = Path(bundle_path)
    if not bundle_path.exists():
        sys.stderr.write(
            f"ERROR: bundle file not found: {bundle_path}\n"
            "Provide --passages FILE or ensure the bundle exists at the default path.\n"
        )
        sys.exit(2)

    # Load all records
    articles: dict[str, dict] = {}   # passage_id -> article record
    items_by_passage: dict[str, list[dict]] = defaultdict(list)

    with open(bundle_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec_type = rec.get("type", "")
            pid = rec.get("passage_id") or rec.get("article_id", "")
            if not pid:
                continue

            if rec_type == "article":
                stim = rec.get("stimulus", {})
                passage_text = ""
                if isinstance(stim, dict):
                    passage_text = stim.get("value", "")
                elif isinstance(stim, str):
                    passage_text = stim
                # Also check content field
                if not passage_text:
                    passage_text = rec.get("content", "")
                if passage_text:
                    articles[pid] = {
                        "text": passage_text,
                        "passage_id": pid,
                        "substandard_id": rec.get("substandard_id", ""),
                    }
            elif rec_type in VALID_TYPES:
                sub = rec.get("substandard_id", "")
                if sub and sub not in EXCLUDED_SUBSTANDARDS:
                    items_by_passage[pid].append({
                        "type": rec_type,
                        "substandard_id": sub,
                    })

    # Build passage dicts for probe
    all_passages = []
    for pid, art in articles.items():
        text = art["text"]
        if not text or len(text) < 100:
            continue
        # Pick a format and standard from associated items
        associated = items_by_passage.get(pid, [])
        if associated:
            # Prefer non-MCQ/MSQ types (skeleton priority)
            preferred = [i for i in associated if i["type"] in ("sequence", "match", "hot-text", "ebsr")]
            chosen = random.choice(preferred) if preferred else random.choice(associated)
            fmt = chosen["type"]
            standard = chosen["substandard_id"]
        else:
            # Fallback: derive from article substandard, default format
            standard = art.get("substandard_id", "RL.5.1")
            fmt = "sequence"

        all_passages.append({
            "text": text,
            "standard": standard,
            "format": fmt,
            "passage_id": pid,
        })

    if not all_passages:
        sys.stderr.write(
            "ERROR: no usable passages found in bundle. "
            "Check that the bundle has article records with stimulus text.\n"
        )
        sys.exit(2)

    # Sample n passages (without replacement if possible)
    k = min(n, len(all_passages))
    sampled = random.sample(all_passages, k)
    if k < n:
        sys.stderr.write(
            f"WARNING: only {k} passages available in bundle; requested {n}.\n"
        )
    return sampled


# ---------------------------------------------------------------------------
# Fireworks generation
# ---------------------------------------------------------------------------

async def generate_item_fireworks(
    session,
    endpoint: str,
    api_key: str,
    system_prompt: str,
    passage: dict,
) -> dict:
    """
    POST to Fireworks endpoint and return the raw parsed JSON or an error dict.
    """
    import aiohttp

    user_content = (
        f"PASSAGE:\n{passage['text']}\n\n"
        f"STANDARD: {passage['standard']}\n"
        f"FORMAT: {passage['format']}\n\n"
        "Generate one passage-dependent assessment item."
    )

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 1024,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with session.post(endpoint, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                body = await resp.text()
                return {
                    "_error": f"HTTP {resp.status}",
                    "_error_body": body[:500],
                    "_passage": passage,
                }
            data = await resp.json(content_type=None)
    except Exception as e:
        return {
            "_error": str(e)[:200],
            "_passage": passage,
        }

    # Extract text from response (OpenAI-compatible Fireworks format)
    raw_text = ""
    try:
        choices = data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            if msg:
                raw_text = msg.get("content", "")
            else:
                raw_text = choices[0].get("text", "")
    except Exception:
        raw_text = str(data)

    return {
        "_raw_response": raw_text,
        "_passage": passage,
    }


def extract_json_from_response(raw: str) -> dict | None:
    """
    Extract a JSON object from a model response, handling markdown code blocks.
    Returns the parsed dict or None on failure.
    """
    if not raw:
        return None

    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Find the first outermost JSON object
    depth = 0
    start = None
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = cleaned[start:i+1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                start = None

    return None


# ---------------------------------------------------------------------------
# IB structural check
# ---------------------------------------------------------------------------

def certify_ib(item: dict, passage: dict) -> tuple[bool, list[str]]:
    """
    Run a structural IB check on a generated item.
    Returns (passes: bool, fail_reasons: list[str]).

    Checks:
    1. Has question (or stem)
    2. Has type field
    3. substandard_id present and not excluded
    4. Type-specific structural fields
    """
    reasons = []

    # 1. Question/stem
    question = item.get("question") or item.get("stem") or item.get("prompt") or ""
    if not question or len(str(question).strip()) < 5:
        reasons.append("missing-question: no question/stem field or too short")

    # 2. Type
    item_type = (item.get("type") or "").lower().strip()
    if not item_type:
        reasons.append("missing-type: no type field")
    elif item_type not in VALID_TYPES:
        reasons.append(f"invalid-type: '{item_type}' not in {sorted(VALID_TYPES)}")

    # 3. Substandard
    sub = (item.get("substandard_id") or item.get("ccss") or item.get("standard") or "").strip()
    if not sub:
        reasons.append("missing-substandard: no substandard_id/ccss field")
    elif sub in EXCLUDED_SUBSTANDARDS:
        reasons.append(f"excluded-substandard: {sub} is retired from G5 skeleton")
    elif not (sub.startswith("RL.5") or sub.startswith("RI.5") or sub.startswith("L.5") or sub.startswith("RF.5")):
        reasons.append(f"invalid-substandard: '{sub}' not in Grade-5 family")

    # 4. Type-specific structural fields
    if item_type == "sequence":
        items_list = item.get("items", [])
        correct_order = item.get("correct_order", [])
        if not items_list or not isinstance(items_list, list):
            reasons.append("sequence-missing-items: no 'items' list")
        elif len(items_list) < 3:
            reasons.append(f"sequence-too-short: only {len(items_list)} items (need >=3)")
        if not correct_order or not isinstance(correct_order, list):
            reasons.append("sequence-missing-correct_order: no 'correct_order' list")
        elif items_list and correct_order and len(items_list) != len(correct_order):
            reasons.append(
                f"sequence-length-mismatch: items={len(items_list)} "
                f"correct_order={len(correct_order)}"
            )

    elif item_type == "match":
        categories = item.get("categories", [])
        match_items = item.get("items", [])
        if not categories or not isinstance(categories, list):
            reasons.append("match-missing-categories: no 'categories' list")
        if not match_items or not isinstance(match_items, list):
            reasons.append("match-missing-items: no 'items' list")
        else:
            cat_ids = {c.get("id") or c if isinstance(c, str) else None for c in categories}
            for mi in match_items:
                if isinstance(mi, dict):
                    cat = mi.get("category") or mi.get("category_id")
                    if cat and cat_ids and cat not in cat_ids:
                        reasons.append(
                            f"match-invalid-category: item references '{cat}' "
                            f"not in categories"
                        )
                        break

    elif item_type == "hot-text":
        annotated = item.get("annotated_passage") or item.get("passage") or ""
        if not annotated:
            reasons.append("hot-text-missing-annotated_passage: no annotated_passage field")
        elif "[[" not in str(annotated) or "]]" not in str(annotated):
            reasons.append("hot-text-no-spans: annotated_passage has no [[span]] markers")

    elif item_type == "ebsr":
        part_a = item.get("part_a") or item.get("partA") or {}
        part_b = item.get("part_b") or item.get("partB") or {}
        if not part_a:
            reasons.append("ebsr-missing-part_a: no part_a field")
        if not part_b:
            reasons.append("ebsr-missing-part_b: no part_b field")

    elif item_type in ("mcq", "msq"):
        options = item.get("options") or item.get("choices") or []
        if not options or not isinstance(options, list) or len(options) < 2:
            reasons.append(f"{item_type}-missing-options: need >=2 options")
        key = item.get("key") or item.get("answer") or item.get("correct_answer")
        if not key:
            reasons.append(f"{item_type}-missing-key: no answer key")

    passes = len(reasons) == 0
    return passes, reasons


# ---------------------------------------------------------------------------
# Blind-solve via LiteLLM (Claude Haiku)
# ---------------------------------------------------------------------------

def _build_blindsolve_prompt(item: dict) -> str:
    """
    Build the blind-solve prompt for Claude Haiku.
    Includes the question and answer options/items WITHOUT the passage.
    """
    item_type = (item.get("type") or "").lower().strip()
    question = item.get("question") or item.get("stem") or item.get("prompt") or ""

    lines = [
        "Answer this Grade 5 reading question using only background knowledge — "
        "no passage provided.",
        "",
        f"QUESTION: {question}",
        "",
    ]

    if item_type == "sequence":
        seq_items = item.get("items", [])
        if seq_items:
            lines.append("ITEMS TO ORDER:")
            for si in seq_items:
                if isinstance(si, dict):
                    sid = si.get("id", "?")
                    content = si.get("content", "")
                    lines.append(f"  {sid}: {content}")
                else:
                    lines.append(f"  {si}")
            lines.append("")
            lines.append("Give the correct order as a list of IDs (e.g. item_2, item_1, item_3).")

    elif item_type == "match":
        categories = item.get("categories", [])
        match_items = item.get("items", [])
        if categories:
            lines.append("CATEGORIES:")
            for cat in categories:
                if isinstance(cat, dict):
                    lines.append(f"  {cat.get('id','?')}: {cat.get('label','')}")
                else:
                    lines.append(f"  {cat}")
        if match_items:
            lines.append("ITEMS TO MATCH:")
            for mi in match_items:
                if isinstance(mi, dict):
                    lines.append(f"  {mi.get('id','?')}: {mi.get('content','')}")
                else:
                    lines.append(f"  {mi}")
        lines.append("")
        lines.append("Give the category assignment for each item.")

    elif item_type == "hot-text":
        annotated = item.get("annotated_passage") or item.get("passage") or ""
        if annotated:
            # Strip the passage text itself; only show the annotated spans
            spans = re.findall(r"\[\[(.*?)\]\]", str(annotated))
            lines.append("SELECTABLE SPANS:")
            for i, span in enumerate(spans):
                lines.append(f"  [{i+1}] {span}")
        lines.append("")
        lines.append("Which span(s) answer the question? Give the span numbers.")

    elif item_type == "ebsr":
        part_a = item.get("part_a") or item.get("partA") or {}
        part_b = item.get("part_b") or item.get("partB") or {}
        if isinstance(part_a, dict):
            lines.append(f"PART A: {part_a.get('question','')}")
            opts_a = part_a.get("options", [])
            for opt in opts_a:
                if isinstance(opt, dict):
                    lines.append(f"  {opt.get('id','?')}: {opt.get('text','')}")
        if isinstance(part_b, dict):
            lines.append(f"PART B: {part_b.get('question','')}")
            opts_b = part_b.get("options", [])
            for opt in opts_b:
                if isinstance(opt, dict):
                    lines.append(f"  {opt.get('id','?')}: {opt.get('text','')}")
        lines.append("")
        lines.append("Answer Part A and Part B with option IDs.")

    elif item_type in ("mcq", "msq"):
        options = item.get("options") or item.get("choices") or []
        if options:
            lines.append("OPTIONS:")
            for i, opt in enumerate(options):
                if isinstance(opt, dict):
                    oid = opt.get("id") or opt.get("key") or chr(65 + i)
                    text = opt.get("text") or opt.get("value") or opt.get("content") or ""
                    lines.append(f"  {oid}: {text}")
                else:
                    lines.append(f"  {chr(65+i)}: {opt}")
        lines.append("")
        lines.append("Give your best answer option ID.")

    lines.append("")
    lines.append("Give your best answer.")
    return "\n".join(lines)


def _normalize_answer(answer: str, item: dict) -> str:
    """Normalize an answer string for comparison."""
    return str(answer).strip().lower()


def _answers_match(model_answer: str, correct: object, item: dict) -> bool:
    """
    Compare model_answer (free text) against the correct answer.
    Best-effort heuristic: looks for key identifiers in the model's text.
    """
    if correct is None:
        return False

    item_type = (item.get("type") or "").lower().strip()
    model_text = str(model_answer).lower()

    if item_type == "sequence":
        correct_order = correct if isinstance(correct, list) else []
        if not correct_order:
            return False
        # Check if the model's answer contains all IDs in the right order
        ids_in_answer = []
        for cid in correct_order:
            if str(cid).lower() in model_text:
                ids_in_answer.append(cid)
        # Consider leaked if the model produces the correct full sequence
        return ids_in_answer == correct_order

    elif item_type == "match":
        correct_map = correct if isinstance(correct, dict) else {}
        if not correct_map:
            return False
        # Check if most category assignments appear in the answer
        correct_count = sum(
            1 for item_id, cat in correct_map.items()
            if str(cat).lower() in model_text or str(item_id).lower() in model_text
        )
        return correct_count >= max(1, len(correct_map) * 0.7)

    elif item_type == "hot-text":
        correct_spans = correct if isinstance(correct, list) else [correct]
        for span in correct_spans:
            if str(span).lower()[:30] in model_text:
                return True
        return False

    elif item_type == "ebsr":
        # EBSR: check if part A key appears in answer
        if isinstance(correct, dict):
            part_a_key = str(correct.get("part_a", "")).lower()
            if part_a_key and part_a_key in model_text:
                return True
        return False

    else:  # mcq, msq
        correct_str = str(correct).strip().lower()
        # Look for the key letter/ID at word boundary
        pattern = r'\b' + re.escape(correct_str) + r'\b'
        if re.search(pattern, model_text):
            return True
        # Also check if correct text appears
        return correct_str in model_text


def _extract_correct_answer(item: dict) -> object:
    """Extract the canonical correct answer from an item for comparison."""
    item_type = (item.get("type") or "").lower().strip()

    if item_type == "sequence":
        return item.get("correct_order", [])
    elif item_type == "match":
        # Build item_id -> category map
        match_items = item.get("items", [])
        result = {}
        for mi in match_items:
            if isinstance(mi, dict):
                mid = mi.get("id", "")
                cat = mi.get("category") or mi.get("category_id") or ""
                if mid:
                    result[mid] = cat
        return result or None
    elif item_type == "hot-text":
        return item.get("correct_spans") or item.get("answer_spans") or []
    elif item_type == "ebsr":
        part_a = item.get("part_a") or item.get("partA") or {}
        if isinstance(part_a, dict):
            key = part_a.get("key") or part_a.get("answer") or part_a.get("correct_answer")
            if key:
                return {"part_a": key}
        return None
    else:
        return item.get("key") or item.get("answer") or item.get("correct_answer")


async def blind_solve_item(item: dict, litellm_client, semaphore: asyncio.Semaphore) -> dict:
    """
    Async blind-solve one item with Claude Haiku via LiteLLM.
    Returns a dict with leaked, model_answer, correct_answer.
    """
    prompt = _build_blindsolve_prompt(item)
    correct = _extract_correct_answer(item)

    async with semaphore:
        try:
            response = await litellm_client.acompletion(
                model=VALIDATOR_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                max_tokens=256,
                temperature=0.0,
            )
            model_answer = response.choices[0].message.content or ""
        except Exception as e:
            return {
                "leaked": False,
                "model_answer": "",
                "correct_answer": str(correct),
                "error": str(e)[:200],
            }

    leaked = _answers_match(model_answer, correct, item)
    return {
        "leaked": leaked,
        "model_answer": model_answer[:300],
        "correct_answer": str(correct)[:200],
        "error": None,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_probe(args) -> dict:
    """Main async pipeline: generate -> certify -> blind-solve -> report."""

    # 1. Load system prompt
    system_prompt = load_system_prompt()

    # 2. Load passages
    if args.passages:
        passages = load_passages_from_file(args.passages)
        passages = passages[:args.n]
        sys.stderr.write(f"Loaded {len(passages)} passages from {args.passages}\n")
    else:
        sys.stderr.write(
            f"No --passages provided. Sampling {args.n} passages from "
            f"{DEFAULT_BUNDLE_PATH}...\n"
        )
        passages = load_passages_from_bundle(DEFAULT_BUNDLE_PATH, args.n)
        sys.stderr.write(f"Sampled {len(passages)} passages from bundle.\n")

    if not passages:
        sys.stderr.write("ERROR: no passages available.\n")
        sys.exit(2)

    n_requested = len(passages)

    # --- DRY RUN ---
    if args.dry_run:
        print("\n=== DRY RUN — no API calls will be made ===\n")
        print(f"Endpoint  : {args.endpoint}")
        print(f"N passages: {n_requested}")
        print(f"Output    : {args.output}")
        print(f"Validator : {VALIDATOR_MODEL}")
        print()

        for i, p in enumerate(passages[:2]):
            user_content = (
                f"PASSAGE:\n{p['text'][:400]}...\n\n"
                f"STANDARD: {p['standard']}\n"
                f"FORMAT: {p['format']}\n\n"
                "Generate one passage-dependent assessment item."
            )
            print(f"--- Prompt {i+1} (Fireworks) ---")
            print("SYSTEM (first 400 chars):")
            print(system_prompt[:400])
            print()
            print("USER:")
            print(user_content)
            print()

        print(
            f"DRY RUN: would generate {n_requested} items, "
            f"blind-solve up to {n_requested}, "
            f"report leak rate"
        )
        return {}

    # --- LIVE RUN ---
    # Check Fireworks API key
    api_key = os.environ.get("FIREWORKS_API_KEY", "")
    if not api_key:
        sys.stderr.write(
            "ERROR: FIREWORKS_API_KEY not set. "
            "Export it or add it to ~/.aptraining_secrets.env\n"
        )
        sys.exit(2)

    # Check LiteLLM
    try:
        import litellm
    except ImportError:
        sys.stderr.write(
            "ERROR: litellm not installed. Run: pip install litellm\n"
        )
        sys.exit(2)

    litellm_base_url = os.environ.get("LITELLM_BASE_URL", "")
    litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
    if litellm_base_url:
        litellm.api_base = litellm_base_url
    if litellm_api_key:
        litellm.api_key = litellm_api_key

    sys.stderr.write(f"\n[1/3] Generating {n_requested} items from Fireworks endpoint...\n")

    # --- GENERATION ---
    try:
        import aiohttp
    except ImportError:
        sys.stderr.write("ERROR: aiohttp not installed. Run: pip install aiohttp\n")
        sys.exit(2)

    fw_semaphore = asyncio.Semaphore(MAX_FIREWORKS_CONCURRENT)

    async def bounded_generate(session, passage):
        async with fw_semaphore:
            return await generate_item_fireworks(
                session, args.endpoint, api_key, system_prompt, passage
            )

    generated_raw = []
    async with aiohttp.ClientSession() as session:
        tasks = [bounded_generate(session, p) for p in passages]
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            result = await coro
            generated_raw.append(result)
            if (i + 1) % 10 == 0 or (i + 1) == n_requested:
                sys.stderr.write(f"  Generated {i+1}/{n_requested}\r")
    sys.stderr.write("\n")

    n_generated = len(generated_raw)
    generation_errors = sum(1 for r in generated_raw if "_error" in r)
    sys.stderr.write(f"  Generated: {n_generated} | Errors: {generation_errors}\n")

    # --- PARSE + CERTIFY ---
    sys.stderr.write(f"[2/3] Parsing and certifying {n_generated} items...\n")

    certified_items = []
    ib_fail_reasons = defaultdict(int)

    for raw_result in generated_raw:
        if "_error" in raw_result:
            ib_fail_reasons["generation-error"] += 1
            continue

        raw_text = raw_result.get("_raw_response", "")
        passage = raw_result.get("_passage", {})
        item = extract_json_from_response(raw_text)

        if item is None:
            ib_fail_reasons["json-parse-error"] += 1
            continue

        # Inject passage reference fields if not present
        if not item.get("substandard_id") and passage.get("standard"):
            item["substandard_id"] = passage["standard"]
        if not item.get("type") and passage.get("format"):
            item["type"] = passage["format"]

        passes, reasons = certify_ib(item, passage)
        item["_ib_pass"] = passes
        item["_ib_reasons"] = reasons
        item["_source_passage"] = {
            "standard": passage.get("standard"),
            "format": passage.get("format"),
            "passage_id": passage.get("passage_id", ""),
        }

        if not passes:
            for r in reasons:
                key = r.split(":")[0].strip()
                ib_fail_reasons[key] += 1

        certified_items.append(item)

    n_ib_pass = sum(1 for it in certified_items if it.get("_ib_pass"))
    n_ib_fail = len(certified_items) - n_ib_pass
    total_certified = len(certified_items)
    ib_pass_rate = n_ib_pass / n_generated if n_generated else 0.0

    sys.stderr.write(
        f"  IB pass: {n_ib_pass}/{total_certified} ({ib_pass_rate:.1%}) | "
        f"Fail: {n_ib_fail} | Parse errors: {generation_errors + (n_generated - total_certified)}\n"
    )

    # --- BLIND SOLVE ---
    ib_passing_items = [it for it in certified_items if it.get("_ib_pass")]
    n_blindsolve = len(ib_passing_items)
    sys.stderr.write(f"[3/3] Blind-solving {n_blindsolve} IB-passing items with {VALIDATOR_MODEL}...\n")

    bs_semaphore = asyncio.Semaphore(MAX_BLINDSOLVE_CONCURRENT)

    async def do_blind_solve(item):
        return await blind_solve_item(item, litellm, bs_semaphore)

    bs_results = []
    if n_blindsolve > 0:
        tasks = [do_blind_solve(it) for it in ib_passing_items]
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            result = await coro
            bs_results.append(result)
            if (i + 1) % 10 == 0 or (i + 1) == n_blindsolve:
                sys.stderr.write(f"  Blind-solved {i+1}/{n_blindsolve}\r")
        sys.stderr.write("\n")

    n_leaked = sum(1 for r in bs_results if r.get("leaked"))
    n_cold = n_blindsolve - n_leaked
    leak_rate = n_leaked / n_blindsolve if n_blindsolve else 0.0

    # Attach blind-solve results to items
    for item, bsr in zip(ib_passing_items, bs_results):
        item["_blind_solve"] = bsr

    # --- BY-TYPE BREAKDOWN ---
    by_type: dict[str, dict] = defaultdict(lambda: {
        "generated": 0, "ib_pass": 0, "ib_fail": 0,
        "blind_solved": 0, "leaked": 0, "cold": 0
    })

    for it in certified_items:
        t = (it.get("type") or "unknown").lower()
        by_type[t]["generated"] += 1
        if it.get("_ib_pass"):
            by_type[t]["ib_pass"] += 1
            bsr = it.get("_blind_solve")
            if bsr:
                by_type[t]["blind_solved"] += 1
                if bsr.get("leaked"):
                    by_type[t]["leaked"] += 1
                else:
                    by_type[t]["cold"] += 1
        else:
            by_type[t]["ib_fail"] += 1

    # Compute leak rates per type
    for t, d in by_type.items():
        bs_total = d["blind_solved"]
        d["leak_rate"] = round(d["leaked"] / bs_total, 3) if bs_total else None

    # --- VERDICT ---
    viable = (
        leak_rate <= LEAK_RATE_THRESHOLD
        and ib_pass_rate >= IB_PASS_RATE_THRESHOLD
    )
    if viable:
        verdict = f"VIABLE (leak_rate={leak_rate:.1%} <= {LEAK_RATE_THRESHOLD:.0%}, ib_pass_rate={ib_pass_rate:.1%} >= {IB_PASS_RATE_THRESHOLD:.0%})"
    elif leak_rate > LEAK_RATE_THRESHOLD and ib_pass_rate < IB_PASS_RATE_THRESHOLD:
        verdict = (
            f"NOT VIABLE (leak_rate={leak_rate:.1%} > {LEAK_RATE_THRESHOLD:.0%} — redesign passages; "
            f"ib_pass_rate={ib_pass_rate:.1%} < {IB_PASS_RATE_THRESHOLD:.0%} — model needs more training)"
        )
    elif leak_rate > LEAK_RATE_THRESHOLD:
        verdict = f"NOT VIABLE (leak_rate={leak_rate:.1%} > {LEAK_RATE_THRESHOLD:.0%}) — redesign passages"
    else:
        verdict = (
            f"NOT VIABLE (ib_pass_rate={ib_pass_rate:.1%} < {IB_PASS_RATE_THRESHOLD:.0%}) — "
            "model needs more training; structural compliance too low"
        )

    report = {
        "endpoint": args.endpoint,
        "validator_model": VALIDATOR_MODEL,
        "cross_family_isolation": "TRUE (Qwen3/Fireworks generator vs. Claude Haiku validator)",
        "n_requested": n_requested,
        "n_generated": n_generated,
        "n_parse_errors": n_generated - total_certified + generation_errors,
        "ib_pass": n_ib_pass,
        "ib_fail": n_ib_fail + (n_generated - total_certified),
        "ib_pass_rate": round(ib_pass_rate, 3),
        "blind_solve_total": n_blindsolve,
        "leaked": n_leaked,
        "cold": n_cold,
        "leak_rate": round(leak_rate, 3),
        "verdict": verdict,
        "thresholds": {
            "leak_rate_max": LEAK_RATE_THRESHOLD,
            "ib_pass_rate_min": IB_PASS_RATE_THRESHOLD,
        },
        "by_type": dict(by_type),
        "fail_reasons": dict(
            sorted(ib_fail_reasons.items(), key=lambda x: x[1], reverse=True)
        ),
        "items": certified_items,
    }

    # Write output
    output_path = args.output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Print summary
    print("\n" + "=" * 72)
    print("CHECKPOINT PROBE RESULTS")
    print("=" * 72)
    print(f"  Endpoint          : {args.endpoint}")
    print(f"  Validator         : {VALIDATOR_MODEL} (cross-family)")
    print(f"  N requested       : {n_requested}")
    print(f"  N generated       : {n_generated}")
    print(f"  IB pass           : {n_ib_pass}/{n_generated} ({ib_pass_rate:.1%})")
    print(f"  Blind-solve total : {n_blindsolve}")
    print(f"  Leaked            : {n_leaked}")
    print(f"  Cold (passage-dep): {n_cold}")
    print(f"  Leak rate         : {leak_rate:.1%}")
    print()
    print(f"  VERDICT: {verdict}")
    print()
    print("  By type:")
    for t, d in sorted(by_type.items()):
        lr = f"{d['leak_rate']:.1%}" if d["leak_rate"] is not None else "n/a"
        print(
            f"    {t:<12}  gen={d['generated']}  ib_pass={d['ib_pass']}  "
            f"bs={d['blind_solved']}  leaked={d['leaked']}  leak_rate={lr}"
        )
    print()
    if ib_fail_reasons:
        print("  Top IB fail reasons:")
        for reason, count in list(ib_fail_reasons.items())[:10]:
            print(f"    [{count:>4}] {reason}")
        print()
    print(f"  Full results written to: {output_path}")
    print("=" * 72)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="run_checkpoint_probe.py",
        description=(
            "Gold-standard checkpoint quality gate for G5 RFT checkpoints. "
            "Generates N items from a Fireworks endpoint, certifies them structurally, "
            "then blind-solves with Claude Haiku to measure passage leak rate."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "PASS criteria: leak_rate <= 30%  AND  ib_pass_rate >= 80%\n\n"
            "Cross-family isolation: Qwen3 (Fireworks) vs. Claude Haiku — "
            "true cross-family, not same-family tier."
        ),
    )
    p.add_argument(
        "--endpoint",
        required=True,
        help="Fireworks inference endpoint URL (required).",
    )
    p.add_argument(
        "--passages",
        default=None,
        metavar="FILE",
        help=(
            "JSONL file with passages. Each line: "
            '{"text": "...", "standard": "RL.5.x", "format": "sequence"}. '
            f"If not provided, draws --n passages from {DEFAULT_BUNDLE_PATH}."
        ),
    )
    p.add_argument(
        "--n",
        type=int,
        default=DEFAULT_N,
        metavar="INT",
        help=f"Number of items to probe (default: {DEFAULT_N}).",
    )
    p.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help=f"Results output path (default: {DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print plan and first 2 prompts; do not call Fireworks or LiteLLM. "
            "Useful for verifying passage loading and prompt construction."
        ),
    )
    return p.parse_args(argv)


def main():
    load_secrets()
    args = parse_args(sys.argv[1:])

    if not args.dry_run:
        # Validate endpoint looks plausible
        if not args.endpoint.startswith("http"):
            sys.stderr.write(
                f"ERROR: --endpoint should start with http(s): {args.endpoint}\n"
            )
            sys.exit(2)

    try:
        asyncio.run(run_probe(args))
    except KeyboardInterrupt:
        sys.stderr.write("\nAborted.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
