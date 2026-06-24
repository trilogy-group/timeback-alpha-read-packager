#!/usr/bin/env python3
"""
fix_ebsr_evidence.py

Fixes 159 EBSR items that fail the partB-is-evidence gate check.

Part B options must be direct quotes or close paraphrases from the passage.
This script identifies summary-style / truncated-quote options and replaces
them with verbatim text from the passage.

Fix categories handled:
  ellipsis_end        : 'Some text ending with...' -> full sentence from passage
  dual_text           : 'Text 1: "partial..."\nText 2: "partial..."' -> full sentences
  illustration_para   : paraphrase of illustration block -> verbatim illustration sentence
  dehtml              : stripped-HTML version of passage sentence -> clean sentence (no HTML)
  fuzzy_match         : other summaries -> best-matching passage sentence (>=0.5 score)
  manual_review       : literary-analysis format or low-confidence match -> flagged, unchanged

Input:
  /tmp/ebsr_fails.json       — 159 EBSR items (list of item dicts)
  /tmp/passage_lookup.json   — dict mapping item_id -> passage text (may contain HTML + [Illustration:...])

Output:
  ./ebsr_fixed.jsonl         — one JSON object per line, fixed items
  ./ebsr_manual_review.jsonl — items or individual options that need human review
"""

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FAILS_PATH = Path("/tmp/ebsr_fails.json")
PASSAGE_PATH = Path("/tmp/passage_lookup.json")
FIXED_OUT = Path(__file__).parent / "ebsr_fixed.jsonl"
REVIEW_OUT = Path(__file__).parent / "ebsr_manual_review.jsonl"

FUZZY_THRESHOLD = 0.50   # word-overlap score below which we flag for manual review
ILLUS_THRESHOLD = 0.35   # lower bar for illustration sentence matching (shorter sentences)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
STOPWORDS = {
    "the", "a", "an", "of", "in", "to", "and", "is", "it", "its", "for",
    "on", "are", "was", "with", "that", "this", "as", "by", "at", "from",
    "be", "been", "or", "not", "but", "so", "if", "he", "she", "they",
    "we", "i", "you", "his", "her", "their", "our", "into", "all", "which",
    "were", "had", "has", "have", "do", "did", "would", "could", "will",
    "can", "may", "very", "more", "also", "than", "up", "out", "about",
}


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_prose_sentences(passage: str) -> list[str]:
    """Extract sentences from passage prose (strips HTML, removes illustration blocks)."""
    clean = strip_html(passage)
    clean = re.sub(r"\[Illustration:[^\]]+\]", " ", clean, flags=re.IGNORECASE)
    clean = normalize_ws(clean)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]


def get_illustration_sentences(passage: str) -> list[str]:
    """Extract sentences from [Illustration: ...] blocks."""
    blocks = re.findall(r"\[Illustration:([^\]]+)\]", passage, re.IGNORECASE)
    sentences: list[str] = []
    for block in blocks:
        for s in re.split(r"(?<=[.!?])\s+", block.strip()):
            s = s.strip()
            if s:
                sentences.append(s)
    return sentences


def word_overlap(text_a: str, text_b: str) -> float:
    """Fraction of significant words in text_a that also appear in text_b."""
    words_a = set(re.findall(r"\b\w+\b", text_a.lower())) - STOPWORDS
    words_b = set(re.findall(r"\b\w+\b", text_b.lower())) - STOPWORDS
    if not words_a:
        return 0.0
    return len(words_a & words_b) / len(words_a)


def best_sentence_match(query: str, sentences: list[str]) -> tuple[str | None, float]:
    """Return (best_sentence, score) using word-overlap scoring."""
    best_score = 0.0
    best_sent: str | None = None
    for s in sentences:
        score = word_overlap(query, s)
        if score > best_score:
            best_score = score
            best_sent = s
    return best_sent, best_score


def find_sentence_containing(fragment: str, sentences: list[str]) -> str | None:
    """Find the sentence that contains `fragment` as a substring (case-insensitive)."""
    frag = normalize_ws(fragment).lower()
    for s in sentences:
        if frag in s.lower():
            return s
    return None


# ---------------------------------------------------------------------------
# Option classification
# ---------------------------------------------------------------------------

def classify_option(opt_text: str, passage: str) -> str:
    """
    Returns one of:
      exact_quote | ellipsis_end | dual_text | illustration_para |
      dehtml | fuzzy_match | literary_analysis
    """
    if opt_text in passage:
        return "exact_quote"

    # Dual-text format: "Text 1: '...'\nText 2: '...'"
    if re.match(r"Text \d+:", opt_text):
        return "dual_text"

    # Ends with trailing ellipsis (text cuts off with '...' possibly followed by more dots)
    if opt_text.endswith("..."):
        return "ellipsis_end"

    # Middle ellipsis that is NOT dual_text — literary analysis format
    # e.g. "The word 'X' and 'Y' which indicate Z"
    if "..." in opt_text or re.search(r"'[^']+' and '", opt_text):
        return "literary_analysis"

    # Check if passage has an illustration block
    if re.search(r"\[Illustration:", passage, re.IGNORECASE):
        return "illustration_para"

    # Check if option matches a de-HTML'd passage sentence exactly
    clean_sents = get_prose_sentences(passage)
    if opt_text in clean_sents:
        return "dehtml"

    return "fuzzy_match"


# ---------------------------------------------------------------------------
# Fixers
# ---------------------------------------------------------------------------

def fix_ellipsis_end(opt_text: str, passage: str) -> tuple[str, str]:
    """Expand a truncated quote (ends with ...) to the full passage sentence."""
    # Strip trailing '...' (possibly preceded by a period)
    fragment = opt_text.strip()
    if fragment.endswith("..."):
        fragment = fragment[:-3].strip().rstrip(".")
    elif fragment.endswith("...."):
        fragment = fragment[:-4].strip()

    prose_sents = get_prose_sentences(passage)
    sent = find_sentence_containing(fragment, prose_sents)
    if sent:
        return sent, "ellipsis_end_resolved"
    # fallback: fuzzy
    sent, score = best_sentence_match(fragment, prose_sents)
    if sent and score >= FUZZY_THRESHOLD:
        return sent, f"ellipsis_end_fuzzy({score:.2f})"
    return opt_text, "ellipsis_end_UNRESOLVED"


def fix_dual_text(opt_text: str, passage: str) -> tuple[str, str]:
    """
    For 'Text 1: "partial..."\nText 2: "partial..."' options,
    find the full sentence for each fragment and reconstruct.
    """
    prose_sents = get_prose_sentences(passage)

    parts = re.findall(r"(Text \d+): '([^']*)'", opt_text)
    if not parts:
        # Try with double-quoted fragments
        parts = re.findall(r'(Text \d+): "([^"]*)"', opt_text)
    if not parts:
        return opt_text, "dual_text_PARSE_FAIL"

    rebuilt_parts: list[str] = []
    status_parts: list[str] = []

    for label, fragment in parts:
        # Strip leading/trailing ellipsis from fragment
        frag = fragment.strip().strip(".")
        if frag.startswith("..."):
            frag = frag[3:].strip()
        if frag.endswith("..."):
            frag = frag[:-3].strip()
        frag = frag.strip("'\"")

        sent = find_sentence_containing(frag, prose_sents)
        if sent:
            rebuilt_parts.append(f'{label}: "{sent}"')
            status_parts.append("resolved")
        else:
            sent, score = best_sentence_match(frag, prose_sents)
            if sent and score >= FUZZY_THRESHOLD:
                rebuilt_parts.append(f'{label}: "{sent}"')
                status_parts.append(f"fuzzy({score:.2f})")
            else:
                rebuilt_parts.append(f'{label}: "{fragment}"')
                status_parts.append("UNRESOLVED")

    new_text = "\n".join(rebuilt_parts)
    status = "dual_text_" + "/".join(status_parts)
    return new_text, status


def fix_illustration_para(opt_text: str, passage: str) -> tuple[str, str]:
    """Replace illustration paraphrase with best-matching illustration sentence."""
    illus_sents = get_illustration_sentences(passage)
    if not illus_sents:
        return opt_text, "illustration_para_NO_BLOCK"

    sent, score = best_sentence_match(opt_text, illus_sents)
    if sent and score >= ILLUS_THRESHOLD:
        return sent, f"illustration_para_resolved({score:.2f})"

    # Try against full prose as fallback
    prose_sents = get_prose_sentences(passage)
    sent2, score2 = best_sentence_match(opt_text, prose_sents)
    if sent2 and score2 >= FUZZY_THRESHOLD:
        return sent2, f"illustration_para_prose_fallback({score2:.2f})"

    return opt_text, f"illustration_para_UNRESOLVED(score={score:.2f})"


def fix_dehtml(opt_text: str, passage: str) -> tuple[str, str]:
    """
    Option is the de-HTML'd text of a passage sentence.
    Return the same text (already clean) since the gate should strip HTML too.
    """
    prose_sents = get_prose_sentences(passage)
    if opt_text in prose_sents:
        return opt_text, "dehtml_confirmed"
    # Minor whitespace/punctuation variant — fuzzy
    sent, score = best_sentence_match(opt_text, prose_sents)
    if sent and score >= FUZZY_THRESHOLD:
        return sent, f"dehtml_fuzzy({score:.2f})"
    return opt_text, "dehtml_UNRESOLVED"


def fix_fuzzy(opt_text: str, passage: str) -> tuple[str, str]:
    """Try best-sentence fuzzy match across all prose sentences."""
    prose_sents = get_prose_sentences(passage)
    sent, score = best_sentence_match(opt_text, prose_sents)
    if sent and score >= FUZZY_THRESHOLD:
        return sent, f"fuzzy_resolved({score:.2f})"
    return opt_text, f"fuzzy_UNRESOLVED(score={score:.2f})"


# ---------------------------------------------------------------------------
# Main fix dispatcher
# ---------------------------------------------------------------------------

def fix_option(opt: dict, passage: str) -> tuple[dict, str]:
    """
    Return (fixed_option_dict, fix_status).
    fix_status is 'exact_quote' or one of the fix method results.
    """
    text = opt["text"]
    cat = classify_option(text, passage)

    if cat == "exact_quote":
        return opt, "exact_quote"

    if cat == "literary_analysis":
        # These reference actual quoted words/phrases from the passage.
        # They ARE valid textual evidence; flag for human review but don't modify.
        return opt, "literary_analysis_MANUAL_REVIEW"

    new_text: str
    status: str

    if cat == "ellipsis_end":
        new_text, status = fix_ellipsis_end(text, passage)
    elif cat == "dual_text":
        new_text, status = fix_dual_text(text, passage)
    elif cat == "illustration_para":
        new_text, status = fix_illustration_para(text, passage)
    elif cat == "dehtml":
        new_text, status = fix_dehtml(text, passage)
    else:  # fuzzy_match
        new_text, status = fix_fuzzy(text, passage)

    fixed_opt = {**opt, "text": new_text, "_fix_status": status, "_original_text": text}
    return fixed_opt, status


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Loading {FAILS_PATH} ...")
    with open(FAILS_PATH) as f:
        items: list[dict] = json.load(f)

    print(f"Loading {PASSAGE_PATH} ...")
    with open(PASSAGE_PATH) as f:
        passages: dict[str, str] = json.load(f)

    print(f"Processing {len(items)} items ...")

    fixed_items: list[dict] = []
    review_items: list[dict] = []

    stats: dict[str, int] = {}

    for item in items:
        item_id = item["id"]
        passage = passages.get(item_id, "")
        if not passage:
            print(f"  WARNING: no passage for {item_id}", file=sys.stderr)

        fixed_options: list[dict] = []
        needs_review = False
        fix_log: list[str] = []

        for opt in item["options"]:
            if opt["part"] != "B":
                fixed_options.append(opt)
                continue

            fixed_opt, status = fix_option(opt, passage)
            fixed_options.append(fixed_opt)

            stats[status] = stats.get(status, 0) + 1

            if "UNRESOLVED" in status or "MANUAL_REVIEW" in status or "PARSE_FAIL" in status:
                needs_review = True

            fix_log.append(f"  [{opt['id']}] {status}")

        fixed_item = {**item, "options": fixed_options, "_fix_log": fix_log}

        if needs_review:
            review_items.append(fixed_item)
        else:
            fixed_items.append(fixed_item)

    # Write output
    print(f"\nWriting {len(fixed_items)} fully-fixed items to {FIXED_OUT}")
    with open(FIXED_OUT, "w") as f:
        for item in fixed_items:
            f.write(json.dumps(item) + "\n")

    print(f"Writing {len(review_items)} review items to {REVIEW_OUT}")
    with open(REVIEW_OUT, "w") as f:
        for item in review_items:
            f.write(json.dumps(item) + "\n")

    print("\n--- Fix stats ---")
    for status, count in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {status}: {count}")

    print(f"\nDone. {len(fixed_items)} fixed, {len(review_items)} flagged for review.")


if __name__ == "__main__":
    main()
