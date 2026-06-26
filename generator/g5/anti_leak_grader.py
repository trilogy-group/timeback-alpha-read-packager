#!/usr/bin/env python3
"""
anti_leak_grader.py — standalone, FORMAT-AWARE acceptance-test grader for Grade-5
reading items (mcq / msq / hot-text / ebsr / sequence / match).

WHAT THIS IS
  A self-contained, runnable acceptance gate for a JSON file of Grade-5 reading
  items in SIX formats. It runs ONLY the structural anti-leak checks a script can
  decide on its own (no LLM, no network). For the one thing a script genuinely
  cannot decide — passage-blind solvability — it does NOT guess: it emits the exact
  LLM-grade prompt to run per item and marks that item NEEDS_LLM_GRADE.

  Honesty stance (matches the workspace north star): deterministic checks are
  reported as PASS/FAIL with reasons; the passage-blind judgment is reported as
  NEEDS_LLM_GRADE, never as a silent pass. A run that contains NEEDS_LLM_GRADE
  items is NOT fully green. MAP-likeness signals the script CAN see (single
  defensible key, near-neighbour distractor count) are reported as soft NOTES, not
  as silent passes or hard fails.

SUPPORTED FORMATS (type aliases are normalized; case-insensitive)
  mcq        : "mcq" / "single-select" / "multiple-choice" / "single_select"
  msq        : "msq" / "multi-select" / "multiple-select" / "multi_select"
  hot-text   : "hot-text" / "hottext" / "hot_text"
  ebsr       : "ebsr" / "evidence-based" / "two-part"
  sequence   : "sequence" / "order" / "ordering" / "sequencing"
  match      : "match" / "matching" / "pairs"
  (an item with no/unknown type is graded with the generic single-select rules)

INPUT
  A JSON file. Either a top-level list of items, or {"items": [...]}, or
  {"passage": {...}, "items": [...]}. Each item is an object.

  Common recognized fields (extra fields are ignored):
    type      : str   format selector (see aliases above).
    stem      : str   the question text (required, non-empty).
    options   : list  the answer options / spans / sequence steps / ebsr parts.
                      Each is a string or an object with {"id","text"} (or
                      {"label","value"}, etc.).
    key       : the correct answer. Form depends on format (see below).
    feedback  : str OR dict OR list  explanatory feedback (required, non-empty).
    ccss      : str OR list  Common Core code(s); >=1 must be Grade-5 reading
                (RL.5.* / RI.5.* / L.5.*).

  Format-specific key / option shapes:
    mcq       : key = ONE option id / index / exact text. >=3 options (>=2 distractors).
    msq       : key = a SET of option ids. Accepts JSON array ["a","b"], a python
                list, a comma-string "a, b", or list-of-ids. Every id must be a
                real option; >=1 distractor must remain; >=2 keyed for a real "set".
    hot-text  : options = the offered selectable spans (passage sentences/phrases).
                key = the span id(s) that must exist among the offered spans.
    ebsr      : TWO parts. Part A = answer near-neighbours; Part B = evidence
                quotes. key = [partA_id, partB_id] (a set/array/comma-string of 2).
                Parts are detected from a "part" field or a "Part A:"/"Part B:"
                text prefix, or split halfway. BOTH parts' keys must resolve; Part B
                key must be an evidence/passage span (not a free answer option).
    sequence  : options = the steps to order. key = the ORDERED list of ALL step
                ids (no dupes, no omissions). LEAK TELL: if the stored/display order
                already equals the key order (identity order), a blind solver can
                read the answer off the screen -> FAIL. Storage must be shuffled.
    match     : options = left buckets + right buckets, OR a "left"/"right" pair of
                lists. key = the pairs, e.g. "L1-R1, L2-R2" or [["L1","R1"],...] or
                {"L1":"R1",...}. Every left must map to a valid right; no left
                unmapped; at least one UNUSED right bucket must exist (anti-leak:
                a clean 1:1 set invites world-knowledge matching).

DETERMINISTIC CHECKS (script decides — PASS/FAIL)
  Shared (all formats):
    stem-present, ccss-present, ccss-grade5-family, feedback-nonempty, key-present.
  Format-specific (see each format above):
    mcq      : options-count>=3, distractor-count>=2, key-valid-single,
               longest-option-tell, option-length-balance.
    msq      : key-set-valid, key-set-size>=2, distractor-remains, longest-set-tell.
    hot-text : spans-present, key-spans-exist, distractor-spans-remain.
    ebsr     : two-parts-present, partA-key-valid, partB-key-valid,
               partB-is-evidence, distractors-each-part.
    sequence : steps-present>=3, key-covers-all-steps, key-no-dupes,
               non-identity-storage (the leak tell).
    match    : left/right-present, pairs-parse, every-left-mapped, rights-valid,
               unused-right-bucket-exists.

  MAP-likeness soft NOTES (decidable, not gating):
    single-defensible-key   : mcq/ebsrA expect exactly one keyed answer.
    near-neighbour-count    : flags when too few plausible distractors remain.

LLM-ONLY CHECK (script CANNOT decide — NEEDS_LLM_GRADE)
  passage-blind solvability : can the item be answered correctly WITHOUT the
                              passage? The script prints the exact prompt to run;
                              a human or LLM must adjudicate.

EXIT CODE
  0  : every item passed all deterministic checks AND no item needs LLM grading.
  1  : any deterministic FAIL, OR any item is NEEDS_LLM_GRADE (run not fully green).
  2  : usage / load error.

USAGE
  python3 anti_leak_grader.py items.json
  python3 anti_leak_grader.py items.json --no-llm-prompt   # suppress prompt text
  python3 anti_leak_grader.py items.json --no-notes        # suppress MAP-like notes
  python3 anti_leak_grader.py --selftest                   # run the inline example
"""

import json
import sys
import os
import re

# ---- tunables -------------------------------------------------------------
BALANCE_MAX_RATIO = 2.0       # longest option <= 2.0x mean of the others (by chars)
MIN_DISTRACTORS = 2           # mcq: at least 2 wrong options
GRADE5_FAMILIES = ("RL.5", "RI.5", "L.5", "RF.5")

# canonical format names
F_MCQ = "mcq"
F_MSQ = "msq"
F_HOT = "hot-text"
F_EBSR = "ebsr"
F_SEQ = "sequence"
F_MATCH = "match"

_TYPE_ALIASES = {
    "mcq": F_MCQ, "single-select": F_MCQ, "single_select": F_MCQ,
    "multiple-choice": F_MCQ, "multiplechoice": F_MCQ, "mc": F_MCQ,
    "msq": F_MSQ, "multi-select": F_MSQ, "multi_select": F_MSQ,
    "multiple-select": F_MSQ, "multiselect": F_MSQ,
    "hot-text": F_HOT, "hottext": F_HOT, "hot_text": F_HOT,
    "ebsr": F_EBSR, "evidence-based": F_EBSR, "two-part": F_EBSR,
    "evidence-based-selected-response": F_EBSR,
    "sequence": F_SEQ, "order": F_SEQ, "ordering": F_SEQ, "sequencing": F_SEQ,
    "match": F_MATCH, "matching": F_MATCH, "pairs": F_MATCH,
}


def detect_format(item):
    """Map an item's declared type to a canonical format. Defaults to mcq."""
    t = (item.get("type") or "").strip().lower()
    return _TYPE_ALIASES.get(t, F_MCQ)


# ---- option / key normalization ------------------------------------------
def _option_text(opt):
    """Return the display text of an option (string or dict)."""
    if isinstance(opt, str):
        return opt
    if isinstance(opt, dict):
        for k in ("text", "value", "label", "option", "content"):
            v = opt.get(k)
            if isinstance(v, str) and v.strip():
                return v
        for v in opt.values():
            if isinstance(v, str) and v.strip():
                return v
    return ""


def _option_id(opt, idx):
    """Return a stable id for an option (explicit id, else its index as str)."""
    if isinstance(opt, dict):
        for k in ("id", "key", "label"):
            v = opt.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return str(idx)


def _split_key_tokens(key):
    """
    Flatten a key into a list of raw scalar tokens, handling: scalars, python
    lists/tuples/sets, JSON-array strings, and comma-separated strings ("a, b").
    Pair tokens like "L1-R1" are NOT split here (match handles those).
    """
    tokens = []

    def add_scalar(k):
        if isinstance(k, bool):
            return  # bool is an int subclass — never a key
        if isinstance(k, (int, str)):
            tokens.append(k)

    def walk(k):
        if isinstance(k, (list, tuple, set)):
            for x in k:
                walk(x)
            return
        if isinstance(k, str):
            s = k.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    parsed = json.loads(s)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    for x in parsed:
                        walk(x)
                    return
            if "," in s:
                parts = [p.strip() for p in s.split(",") if p.strip()]
                if len(parts) > 1:
                    for p in parts:
                        tokens.append(p)
                    return
            add_scalar(s)
            return
        add_scalar(k)

    walk(key)
    return tokens


def _match_token_to_index(tok, ids, texts):
    """Resolve ONE scalar token to an option index, or None."""
    if isinstance(tok, bool):
        return None
    if isinstance(tok, int):
        return tok if 0 <= tok < len(ids) else None
    if isinstance(tok, str):
        s = tok.strip()
        if s.isdigit():
            ki = int(s)
            if 0 <= ki < len(ids):
                return ki
        for i, oid in enumerate(ids):
            if oid == s:
                return i
        for i, t in enumerate(texts):
            if t == tok or t == s:
                return i
    return None


def resolve_key_indices(key, options):
    """
    Resolve a key into a deduped, order-preserving list of option indices.
    Handles scalars, lists, JSON-array strings, comma-strings. (Match pairs are
    resolved separately.)
    """
    ids = [_option_id(o, i) for i, o in enumerate(options)]
    texts = [_option_text(o) for o in options]
    out = []
    for tok in _split_key_tokens(key):
        idx = _match_token_to_index(tok, ids, texts)
        if idx is not None:
            out.append(idx)
    seen, deduped = set(), []
    for i in out:
        if i not in seen:
            seen.add(i)
            deduped.append(i)
    return deduped


def _ccss_codes(ccss):
    if ccss is None:
        return []
    if isinstance(ccss, str):
        return [c.strip() for c in ccss.replace(",", " ").split() if c.strip()]
    if isinstance(ccss, (list, tuple, set)):
        return [c.strip() for c in ccss if isinstance(c, str) and c.strip()]
    return []


def _feedback_nonempty(feedback):
    if isinstance(feedback, str):
        return bool(feedback.strip())
    if isinstance(feedback, dict):
        return any(isinstance(v, str) and v.strip() for v in feedback.values())
    if isinstance(feedback, (list, tuple)):
        return any(isinstance(v, str) and v.strip() for v in feedback)
    return False


# ---- shared check fragments ----------------------------------------------
def _check_shared(item, reasons, notes):
    stem = item.get("stem")
    if not (isinstance(stem, str) and stem.strip()):
        reasons.append("stem-present: stem is missing or empty")

    codes = _ccss_codes(item.get("ccss"))
    if not codes:
        reasons.append("ccss-present: no CCSS code(s) provided")
    elif not any(any(c.startswith(fam) for fam in GRADE5_FAMILIES) for c in codes):
        reasons.append("ccss-grade5-family: no code in %s (got %s)"
                       % ("/".join(GRADE5_FAMILIES), ", ".join(codes)))

    if not _feedback_nonempty(item.get("feedback")):
        reasons.append("feedback-nonempty: feedback missing or empty")

    if item.get("key") in (None, "", [], {}):
        reasons.append("key-present: key is missing or empty")


def _longest_option_tell(keyed_idxs, lengths, label="keyed option"):
    """Return a reason if the keyed option is longest AND >=20% longer than the next
    distractor (a meaningful giveaway). Strict-longest alone fires ~36% of MCQs (mostly
    noise — correct answers naturally run a bit longer/more-qualified); the >=20% margin
    isolates the real ~5% exploitable tell (verified course-wide on rex-v2: 36.5% strict
    vs 5.2% at >=20% margin)."""
    if not keyed_idxs or not lengths:
        return None
    max_len = max(lengths)
    n_at_max = sum(1 for L in lengths if L == max_len)
    # uniquely longest AND keyed AND a meaningful (>=20%) margin over the next distractor
    if n_at_max == 1 and max(lengths[i] for i in keyed_idxs) == max_len \
            and lengths.index(max_len) in keyed_idxs:
        others = [L for i, L in enumerate(lengths) if i not in keyed_idxs]
        nxt = max(others) if others else 0
        if nxt > 0 and max_len >= 1.2 * nxt:
            return ("longest-option-tell: %s is longest AND >=20%% longer (%d vs next %d chars) "
                    "— length giveaway" % (label, max_len, nxt))
    return None


def _set_longest_tell(keyed_idxs, lengths):
    """
    MSQ length tell: flag when the keyed SET is exactly the N longest options
    (a blind solver could pick 'the longest two').
    """
    if not keyed_idxs or len(keyed_idxs) >= len(lengths):
        return None
    order = sorted(range(len(lengths)), key=lambda i: lengths[i], reverse=True)
    top_n = set(order[:len(keyed_idxs)])
    # the keyed set must BE the N longest AND clear the next distractor by >=20%
    # (margin, not strict — same rationale as the single-option tell: strict over-flags noise)
    cut = lengths[order[len(keyed_idxs) - 1]]      # shortest keyed option
    nxt = lengths[order[len(keyed_idxs)]]          # longest distractor
    if top_n == set(keyed_idxs) and nxt > 0 and cut >= 1.2 * nxt:
        return ("longest-option-tell: keyed set is the %d longest AND each >=20%% longer "
                "than every distractor (%d vs %d chars) — 'pick the longest' giveaway"
                % (len(keyed_idxs), cut, nxt))
    return None


def _balance_tell(lengths):
    if len(lengths) < 2:
        return None
    max_len = max(lengths)
    others = [L for L in lengths if L != max_len]
    if not others:
        return None  # all equal -> balanced
    others_mean = sum(others) / len(others)
    if others_mean > 0 and max_len > BALANCE_MAX_RATIO * others_mean:
        return ("option-length-balance: longest option %d chars > %.1fx mean of others "
                "%.1f — unbalanced lengths" % (max_len, BALANCE_MAX_RATIO, others_mean))
    return None


# ---- ebsr part detection -------------------------------------------------
_PART_A_RE = re.compile(r"^\s*part\s*a\b", re.IGNORECASE)
_PART_B_RE = re.compile(r"^\s*part\s*b\b", re.IGNORECASE)


def _ebsr_part_of(opt, idx, n):
    """Return 'A' or 'B' for an ebsr option."""
    if isinstance(opt, dict):
        p = opt.get("part")
        if isinstance(p, str) and p.strip():
            pl = p.strip().lower()
            if pl in ("a", "part a", "parta"):
                return "A"
            if pl in ("b", "part b", "partb"):
                return "B"
    t = _option_text(opt)
    if _PART_A_RE.match(t):
        return "A"
    if _PART_B_RE.match(t):
        return "B"
    # fallback: first half = A, second half = B
    return "A" if idx < (n + 1) // 2 else "B"


# ---- per-format deterministic checks -------------------------------------
def _check_mcq(item, reasons, notes):
    options = item.get("options")
    if not isinstance(options, list):
        reasons.append("options-count: 'options' missing or not a list")
        return
    if len(options) < 3:
        reasons.append("options-count: mcq needs >= 3 options (got %d)" % len(options))
    texts = [_option_text(o) for o in options]
    lengths = [len(t) for t in texts]

    keyed = resolve_key_indices(item.get("key"), options)
    if len(keyed) == 0:
        reasons.append("key-valid-option: key %r does not match any option"
                       % (item.get("key"),))
        return
    if len(keyed) > 1:
        reasons.append("key-valid-single: mcq key %r resolves to %d options (must be exactly 1)"
                       % (item.get("key"), len(keyed)))
    else:
        notes.append("single-defensible-key: mcq has exactly one keyed answer (good)")

    n_distract = len(options) - 1
    if n_distract < MIN_DISTRACTORS:
        reasons.append("distractor-count: only %d distractor(s), need >= %d"
                       % (n_distract, MIN_DISTRACTORS))
    elif n_distract == MIN_DISTRACTORS:
        notes.append("near-neighbour-count: exactly %d distractors — at the MAP-like minimum"
                     % n_distract)

    t = _longest_option_tell(keyed[:1], lengths)
    if t:
        reasons.append(t)
    b = _balance_tell(lengths)
    if b:
        reasons.append(b)


def _check_msq(item, reasons, notes):
    options = item.get("options")
    if not isinstance(options, list):
        reasons.append("options-count: 'options' missing or not a list")
        return
    if len(options) < 3:
        reasons.append("options-count: msq needs >= 3 options (got %d)" % len(options))
    texts = [_option_text(o) for o in options]
    lengths = [len(t) for t in texts]

    raw_tokens = _split_key_tokens(item.get("key"))
    keyed = resolve_key_indices(item.get("key"), options)
    ids = [_option_id(o, i) for i, o in enumerate(options)]
    # every raw token must resolve to a real option
    unresolved = []
    for tok in raw_tokens:
        if _match_token_to_index(tok, ids, texts) is None:
            unresolved.append(tok)
    if unresolved:
        reasons.append("key-set-valid: msq key token(s) %r match no option (accepts "
                       "JSON array, list, or comma-string)" % unresolved)
    if len(keyed) == 0:
        reasons.append("key-set-valid: msq key resolves to no real options")
        return
    if len(keyed) < 2:
        reasons.append("key-set-size: msq key resolves to %d option(s); a real SET needs >= 2"
                       % len(keyed))
    n_distract = len(options) - len(keyed)
    if n_distract < 1:
        reasons.append("distractor-remains: msq keys every option; >= 1 distractor required")
    elif n_distract == 1:
        notes.append("near-neighbour-count: only 1 distractor remains after the keyed set")
    t = _set_longest_tell(keyed, lengths)
    if t:
        reasons.append(t)


def _check_hot_text(item, reasons, notes):
    options = item.get("options") or item.get("spans")
    if not isinstance(options, list):
        reasons.append("spans-present: hot-text needs an 'options'/'spans' list of selectable spans")
        return
    if len(options) < 2:
        reasons.append("spans-present: hot-text needs >= 2 offered spans (got %d)" % len(options))
    texts = [_option_text(o) for o in options]
    if any(not t.strip() for t in texts):
        reasons.append("spans-present: one or more offered spans are empty")

    ids = [_option_id(o, i) for i, o in enumerate(options)]
    raw_tokens = _split_key_tokens(item.get("key"))
    if not raw_tokens:
        reasons.append("key-spans-exist: hot-text key is missing")
        return
    unresolved = [tok for tok in raw_tokens
                  if _match_token_to_index(tok, ids, texts) is None]
    if unresolved:
        reasons.append("key-spans-exist: key span id(s) %r are not among the offered spans"
                       % unresolved)
    keyed = resolve_key_indices(item.get("key"), options)
    n_distract = len(options) - len(keyed)
    if keyed and n_distract < 1:
        reasons.append("distractor-spans-remain: every offered span is keyed; >= 1 non-key span required")
    if len(keyed) == 1:
        notes.append("single-defensible-key: hot-text keys exactly one span (good)")


def _check_ebsr(item, reasons, notes):
    options = item.get("options")
    if not isinstance(options, list) or len(options) < 4:
        reasons.append("two-parts-present: ebsr needs an options list with both Part A and "
                       "Part B choices (got %s)"
                       % (len(options) if isinstance(options, list) else "non-list"))
        return
    n = len(options)
    parts = [_ebsr_part_of(o, i, n) for i, o in enumerate(options)]
    a_idxs = [i for i, p in enumerate(parts) if p == "A"]
    b_idxs = [i for i, p in enumerate(parts) if p == "B"]
    if not a_idxs:
        reasons.append("two-parts-present: no Part A options detected")
    if not b_idxs:
        reasons.append("two-parts-present: no Part B options detected (Part B missing)")
    if not a_idxs or not b_idxs:
        return

    keyed = resolve_key_indices(item.get("key"), options)
    keyed_a = [i for i in keyed if i in a_idxs]
    keyed_b = [i for i in keyed if i in b_idxs]

    if not keyed_a:
        reasons.append("partA-key-valid: no resolved key in Part A (Part A answer missing/invalid)")
    elif len(keyed_a) > 1:
        reasons.append("partA-key-valid: Part A resolves to %d keys (must be exactly 1)" % len(keyed_a))
    else:
        notes.append("single-defensible-key: ebsr Part A keys exactly one answer (good)")

    if not keyed_b:
        reasons.append("partB-key-valid: no resolved key in Part B (Part B answer missing/invalid)")
    elif len(keyed_b) > 1:
        reasons.append("partB-key-valid: Part B resolves to %d keys (must be exactly 1)" % len(keyed_b))

    # Part B must reference passage evidence: a quoted/verbatim span, not a free option.
    if keyed_b:
        bt = _option_text(options[keyed_b[0]])
        # strip a leading "Part B:" prefix for the evidence test
        bt_body = _PART_B_RE.sub("", bt).lstrip(": ").strip()
        has_quote = ('"' in bt) or ("“" in bt) or ("”" in bt) or ("'" in bt_body[:2])
        looks_like_span = bool(options[keyed_b[0]].get("evidence")) \
            if isinstance(options[keyed_b[0]], dict) else False
        if not (has_quote or looks_like_span):
            reasons.append("partB-is-evidence: keyed Part B is not a quoted passage-evidence "
                           "sentence (Part B must cite text, not restate a free answer)")

    # distractors in each part
    if len(a_idxs) - len(keyed_a) < 1:
        reasons.append("distractors-each-part: Part A has no distractor")
    if len(b_idxs) - len(keyed_b) < 1:
        reasons.append("distractors-each-part: Part B has no distractor")


def _check_sequence(item, reasons, notes):
    options = item.get("options") or item.get("steps")
    if not isinstance(options, list):
        reasons.append("steps-present: sequence needs an 'options'/'steps' list")
        return
    if len(options) < 3:
        reasons.append("steps-present: sequence needs >= 3 steps (got %d)" % len(options))
    ids = [_option_id(o, i) for i, o in enumerate(options)]

    # key must be the ordered list of ALL step ids
    key = item.get("key")
    key_tokens = _split_key_tokens(key)
    if not key_tokens:
        reasons.append("key-covers-all-steps: sequence key is missing (must be the ordered "
                       "list of all step ids)")
        return
    texts = [_option_text(o) for o in options]
    key_idx_order = []
    for tok in key_tokens:
        idx = _match_token_to_index(tok, ids, texts)
        if idx is None:
            reasons.append("key-covers-all-steps: sequence key token %r is not a real step id"
                           % (tok,))
        else:
            key_idx_order.append(idx)

    # no dupes
    if len(key_idx_order) != len(set(key_idx_order)):
        reasons.append("key-no-dupes: sequence key repeats a step id")
    # covers all
    if set(key_idx_order) != set(range(len(options))):
        missing = [ids[i] for i in range(len(options)) if i not in set(key_idx_order)]
        if missing:
            reasons.append("key-covers-all-steps: sequence key omits step id(s) %r" % missing)

    # THE LEAK TELL: stored/display order must NOT already equal the key order.
    # stored order = the option ids as they appear in the file (indices 0..n-1).
    stored_order = list(range(len(options)))
    if key_idx_order == stored_order and len(options) >= 2:
        reasons.append("non-identity-storage: stored/display order equals the key order "
                       "(identity order) — a blind solver reads the answer off the screen; "
                       "shuffle the stored steps")
    else:
        notes.append("single-defensible-key: sequence storage is shuffled vs key order (good)")


def _split_pair_token(tok):
    """Split a 'L1-R1' / 'L1:R1' / 'L1=>R1' pair token into (left, right) or None."""
    if isinstance(tok, (list, tuple)) and len(tok) == 2:
        return str(tok[0]).strip(), str(tok[1]).strip()
    if isinstance(tok, str):
        s = tok.strip()
        for sep in ("=>", "->", ":", "=", "-", "→", "|"):
            if sep in s:
                left, right = s.split(sep, 1)
                if left.strip() and right.strip():
                    return left.strip(), right.strip()
    return None


def _match_parse_pairs(key):
    """
    Parse a match key into a list of (left, right) tokens.
    Accepts: "L1-R1, L2-R2", [["L1","R1"],...], {"L1":"R1",...}, ["L1-R1",...].
    """
    pairs = []
    if isinstance(key, dict):
        for k, v in key.items():
            pairs.append((str(k).strip(), str(v).strip()))
        return pairs
    if isinstance(key, (list, tuple)):
        # could be list of [l,r] pairs OR list of "L-R" strings
        for el in key:
            p = _split_pair_token(el)
            if p:
                pairs.append(p)
        return pairs
    if isinstance(key, str):
        s = key.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                return _match_parse_pairs(parsed)
            except json.JSONDecodeError:
                pass
        # comma-separated pair tokens
        for tok in s.split(","):
            p = _split_pair_token(tok)
            if p:
                pairs.append(p)
        return pairs
    return pairs


def _match_sides(item):
    """
    Resolve the left and right id pools for a match item.
    Supports either explicit {"left":[...],"right":[...]} or a single 'options'
    list whose ids are partitioned by a 'side' field / L*/R* id convention.
    Returns (left_ids:set, right_ids:set).
    """
    left = item.get("left")
    right = item.get("right")
    if isinstance(left, list) and isinstance(right, list):
        lids = {_option_id(o, "L%d" % i) for i, o in enumerate(left)}
        rids = {_option_id(o, "R%d" % i) for i, o in enumerate(right)}
        return lids, rids

    options = item.get("options")
    lids, rids = set(), set()
    if isinstance(options, list):
        for i, o in enumerate(options):
            oid = _option_id(o, i)
            side = o.get("side") if isinstance(o, dict) else None
            if isinstance(side, str) and side.strip().lower() in ("left", "l"):
                lids.add(oid)
            elif isinstance(side, str) and side.strip().lower() in ("right", "r"):
                rids.add(oid)
            elif re.match(r"^[lL]\d", str(oid)):
                lids.add(oid)
            elif re.match(r"^[rR]\d", str(oid)):
                rids.add(oid)
    return lids, rids


def _check_match(item, reasons, notes):
    lids, rids = _match_sides(item)
    if not lids or not rids:
        reasons.append("left/right-present: could not find both left and right buckets "
                       "(use {\"left\":[...],\"right\":[...]} or L*/R* ids / a 'side' field)")
        return

    pairs = _match_parse_pairs(item.get("key"))
    if not pairs:
        reasons.append("pairs-parse: match key did not parse into (left,right) pairs "
                       "(e.g. \"L1-R1, L2-R2\")")
        return

    used_rights = set()
    mapped_lefts = set()
    for left, right in pairs:
        if left not in lids:
            reasons.append("every-left-mapped: pair left %r is not a real left bucket" % left)
        else:
            mapped_lefts.add(left)
        if right not in rids:
            reasons.append("rights-valid: pair right %r is not a real right bucket" % right)
        else:
            used_rights.add(right)

    unmapped = lids - mapped_lefts
    if unmapped:
        reasons.append("every-left-mapped: left bucket(s) %r have no pairing" % sorted(unmapped))

    # anti-leak: at least one UNUSED right bucket must exist
    unused_rights = rids - used_rights
    if not unused_rights:
        reasons.append("unused-right-bucket-exists: every right bucket is used (clean 1:1 map) "
                       "— add >= 1 decoy right bucket so a world-knowledge 1:1 solver fails")
    else:
        notes.append("near-neighbour-count: %d unused (decoy) right bucket(s) present (good)"
                     % len(unused_rights))

    # no left mapped twice
    left_counts = {}
    for left, _ in pairs:
        left_counts[left] = left_counts.get(left, 0) + 1
    dup_left = [l for l, c in left_counts.items() if c > 1]
    if dup_left:
        reasons.append("every-left-mapped: left bucket(s) %r mapped more than once" % dup_left)


_FORMAT_CHECKS = {
    F_MCQ: _check_mcq,
    F_MSQ: _check_msq,
    F_HOT: _check_hot_text,
    F_EBSR: _check_ebsr,
    F_SEQ: _check_sequence,
    F_MATCH: _check_match,
}


# ---- deterministic driver per item ---------------------------------------
def grade_item_deterministic(item):
    """
    Run shared + format-specific deterministic checks on one item.
    Returns (passed, reasons, notes, fmt).
    """
    if not isinstance(item, dict):
        return False, ["item is not a JSON object"], [], "?"
    reasons, notes = [], []
    fmt = detect_format(item)
    _check_shared(item, reasons, notes)
    _FORMAT_CHECKS.get(fmt, _check_mcq)(item, reasons, notes)
    return (len(reasons) == 0), reasons, notes, fmt


# ---- LLM-only prompt builder ----------------------------------------------
def build_llm_prompt(item, idx, fmt):
    """The exact prompt to run for the passage-blind solvability check."""
    options = item.get("options") or item.get("spans") or []
    opt_lines = []
    if isinstance(options, list):
        for i, o in enumerate(options):
            opt_lines.append("  (%s) %s" % (_option_id(o, i), _option_text(o)))
    key = item.get("key")
    return (
        "PASSAGE-BLIND SOLVABILITY CHECK — Grade-5 reading item #%d  (format: %s)\n"
        "You are an anti-leak grader. You do NOT have the passage. Decide whether this\n"
        "item can be answered CORRECTLY without the passage, using only general knowledge,\n"
        "answer-shape tells, grammar agreement, canonical real-world order/pairing, or\n"
        "elimination.\n"
        "\n"
        "STEM:\n  %s\n"
        "OPTIONS:\n%s\n"
        "STATED KEY: %r\n"
        "\n"
        "Answer in strict JSON, nothing else:\n"
        '  {"passage_blind_solvable": true|false,\n'
        '   "confidence": 0.0-1.0,\n'
        '   "guessed_answer": "<what you would pick blind, in the key shape>",\n'
        '   "tell": "<the leak you exploited, or \\"none\\">",\n'
        '   "verdict": "PASS"|"FAIL"}\n'
        "Rules: verdict=FAIL if passage_blind_solvable is true at confidence >= 0.6\n"
        "AND guessed_answer matches the stated key. Otherwise verdict=PASS.\n"
        % (idx, fmt, (item.get("stem") or "").strip(),
           "\n".join(opt_lines) or "  (none)", key)
    )


# ---- driver ---------------------------------------------------------------
def load_items(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    raise ValueError("input must be a JSON list of items, or an object with an 'items' list")


SELFTEST_ITEMS = [
    {"type": "mcq",
     "stem": "In paragraph 2, what does the word 'arid' most nearly mean?",
     "options": [
         {"id": "a", "text": "Dry"},
         {"id": "b", "text": "Cold"},
         {"id": "c", "text": "Loud"},
         {"id": "d", "text": "Green"}],
     "key": "a",
     "feedback": "'Arid' describes a dry climate; the passage's desert setting confirms it.",
     "ccss": "RI.5.4"},
]


def main(argv):
    args = argv[1:]
    show_prompt = "--no-llm-prompt" not in args
    show_notes = "--no-notes" not in args
    args = [a for a in args if a not in ("--no-llm-prompt", "--no-notes")]

    if "--selftest" in args:
        items = SELFTEST_ITEMS
        src = "<inline selftest>"
    else:
        if not args:
            sys.stderr.write(__doc__ or "")
            sys.stderr.write("\nERROR: provide a JSON items file (or --selftest)\n")
            return 2
        path = args[0]
        if not os.path.exists(path):
            sys.stderr.write("ERROR: file not found: %s\n" % path)
            return 2
        try:
            items = load_items(path)
        except Exception as e:
            sys.stderr.write("ERROR: could not load %s: %s\n" % (path, e))
            return 2
        src = path

    if not items:
        sys.stderr.write("ERROR: no items found in %s\n" % src)
        return 2

    n = len(items)
    n_fail = n_llm = 0
    per_fmt = {}

    print("=" * 72)
    print("ANTI-LEAK GRADER  (format-aware deterministic structural checks)")
    print("source: %s" % src)
    print("items: %d   |   deterministic checks decided here;"
          " passage-blind needs an LLM" % n)
    print("=" * 72)

    for idx, item in enumerate(items):
        passed, reasons, notes, fmt = grade_item_deterministic(item)
        per_fmt.setdefault(fmt, {"pass": 0, "fail": 0})
        stem_preview = (item.get("stem") if isinstance(item, dict) else "") or ""
        stem_preview = stem_preview.strip().replace("\n", " ")
        if len(stem_preview) > 60:
            stem_preview = stem_preview[:57] + "..."

        if not passed:
            n_fail += 1
            per_fmt[fmt]["fail"] += 1
            print("\n[#%d] FAIL  (%s) | %s" % (idx, fmt, stem_preview))
            for r in reasons:
                print("        - %s" % r)
        else:
            n_llm += 1
            per_fmt[fmt]["pass"] += 1
            print("\n[#%d] PASS (deterministic) -> NEEDS_LLM_GRADE (%s) | %s"
                  % (idx, fmt, stem_preview))
            print("        deterministic: all structural anti-leak checks passed")
            if show_notes and notes:
                for nt in notes:
                    print("        note: %s" % nt)
            print("        undecided    : passage-blind solvability (LLM required)")
            if show_prompt:
                print("        ---- run this prompt against the item ----")
                for line in build_llm_prompt(item, idx, fmt).splitlines():
                    print("        | " + line)

    n_pass = n - n_fail
    rate = (n_pass / n * 100.0) if n else 0.0

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("  total items ............... %d" % n)
    print("  deterministic PASS ........ %d  (%.1f%%)" % (n_pass, rate))
    print("  deterministic FAIL ........ %d" % n_fail)
    print("  NEEDS_LLM_GRADE ........... %d  (passage-blind, undecided by script)" % n_llm)
    print("  per-format (pass/fail):")
    for fmt in sorted(per_fmt):
        c = per_fmt[fmt]
        print("    %-10s %d pass / %d fail" % (fmt, c["pass"], c["fail"]))
    print("=" * 72)

    fully_green = (n_fail == 0 and n_llm == 0)
    if fully_green:
        print("RESULT: PASS — all deterministic checks green and no LLM grade pending.")
        return 0
    if n_fail > 0:
        print("RESULT: FAIL — %d item(s) failed deterministic checks." % n_fail)
    else:
        print("RESULT: NOT GREEN — %d item(s) pending passage-blind LLM grade; "
              "run the printed prompts." % n_llm)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
