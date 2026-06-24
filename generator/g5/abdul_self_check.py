#!/usr/bin/env python3
"""
abdul_self_check.py — Pre-submission item self-check for Abdul's generator output.

Run this on YOUR output before sending items for review. It catches the most common
leak patterns without needing an API call. Items that pass here still need the full
anti_leak_grader.py + LLM blind-solve to be accepted, but any item that FAILS here
would definitely be rejected — catch it early.

WHAT THIS CHECKS (heuristics only — no passage reading, no LLM)
  For MCQ and MSQ items, four fast structural tells that correlate with passage-leak:

  H1 — World-knowledge-anchor check
       Is the question answerable from common school curriculum facts?
       Detects stems that ask about: famous scientists, historical events with known
       outcomes, standard science processes (photosynthesis, water cycle, migration),
       or topics known to produce encyclopedic passages.

  H2 — Correct option is the longest
       When the keyed answer is the longest option by >= 20%, a student who never
       read the passage can guess correctly by picking the most detailed option.
       (Validated on Abdul's corpus: 28% MCQ leak rate driver.)

  H3 — Absolute language in options
       Wrong options containing "all", "never", "always", "entirely", "the only",
       etc. are eliminatable without the passage. Students are taught to eliminate
       extreme claims — this makes the key recoverable by elimination.

  H4 — Generic stem check
       Stems like "What is the main idea?" or "What is this passage mostly about?"
       are technically valid but ONLY produce passage-dependent items if the wrong
       options are passage-specific promoted-detail distractors — not generic
       topic truths. This check flags generic stems so you can verify the options
       manually.

INPUT
  Abdul's JSONL output: one item per line, each line a JSON object.
  Accepts the grade5-reading-v2 schema (same as anti_leak_grader.py):
    type, stem, options (list of {id, text} or plain strings), key, ccss, feedback.

OUTPUT
  Each line of stdout: the original item JSON + a "pre_check" field:
    {
      "leaked": true|false,
      "flags": ["H2: correct option is longest (key=A, 47 chars > next 31 chars)", ...]
    }

  Stderr: per-item flag summary + final stats.

USAGE
  python3 abdul_self_check.py items.jsonl
  python3 abdul_self_check.py items.jsonl --quiet   # suppress per-item stderr output
  python3 abdul_self_check.py items.jsonl --only-flagged  # only print flagged items to stdout
  python3 abdul_self_check.py --selftest

EXIT CODE
  0 : all items passed (no flags)
  1 : >= 1 item flagged
  2 : usage / load error
"""

import json
import re
import sys
import os

# ---- tunables ---------------------------------------------------------------
LENGTH_MARGIN = 1.35          # key is "leaked by length" if >= 35% longer than next-longest
ABSOLUTE_TERMS = re.compile(
    r"\b(all|none|never|always|completely|entirely|the only|every one|exclusively|"
    r"totally|solely|banned|made illegal|forced all|stopped all|destroyed all|"
    r"replaced all|caused everyone|no one ever|nobody ever|the entire)\b",
    re.IGNORECASE,
)
GENERIC_STEMS = re.compile(
    r"^\s*(what is (the )?main idea|what is (this passage |the passage )?"
    r"(mostly |mainly )?(about|discuss|describe|explain)|"
    r"what does (this passage|the passage|the author) mainly|"
    r"which (best )?describes (the )?(main|central|primary) (idea|message|purpose)|"
    r"what is the (central|primary|most important) (idea|message|point))",
    re.IGNORECASE,
)

# Topics/terms whose presence in a stem/passage correlates with encyclopedic passages
# in Abdul's generator (validated on 200-item blind-solve audit).
#
# Two patterns are needed:
#  _ANCHOR_FULLWORD  — terms that are complete words; \b on both ends.
#  _ANCHOR_PREFIX    — terms that are word-prefixes (e.g. "monarch butter" matches
#                      "monarch butterflies"); no terminal \b.
_ANCHOR_FULLWORD = re.compile(
    r"\b("
    # Famous scientists / experiments
    r"leeuwenhoek|curie|newton|darwin|mendel|galileo|einstein|"
    r"scurvy|citrus|vitamin c|"
    # Standard science processes
    r"photosynthesis|evaporation|condensation|precipitation|"
    r"plate tectonics|pangaea|osmosis|mitosis|chromosomes|chlorophyll|"
    r"bioluminescence|geothermal|"
    # Famous events / known outcomes
    r"transcontinental railroad|apollo 11|wright brothers|"
    r"american revolution|civil war|"
    r"world war (i|ii|1|2|one|two)|"
    # G5 curriculum topics
    r"ancient egypt|nile river|pharaoh|hieroglyphics|"
    r"circulatory system|respiratory system|"
    r"renewable energy|fossil fuel"
    r")\b",
    re.IGNORECASE,
)
# Prefix patterns — match the start of a compound word (no terminal \b required)
_ANCHOR_PREFIX = re.compile(
    r"(james lind|water cycle|migration pattern|monarch butter|waggle danc|"
    r"food chain|food web|ecosystem|habitat|"
    r"great wall|library of alexandria|moon landing|"
    r"declaration of independence|"
    r"blood vessel|heart pump|solar panel|wind turbine|"
    r"pyramids|continental drift)",
    re.IGNORECASE,
)


def _curriculum_anchor_match(text):
    """Return the matched anchor string, or None."""
    m = _ANCHOR_FULLWORD.search(text)
    if m:
        return m.group(0)
    m = _ANCHOR_PREFIX.search(text)
    if m:
        return m.group(0)
    return None

CCSS_G5 = re.compile(r"^(RL|RI|L|RF)\.5\.")


# ---- option helpers ---------------------------------------------------------

def _opt_text(opt):
    if isinstance(opt, str):
        return opt.strip()
    if isinstance(opt, dict):
        for k in ("text", "value", "label", "content"):
            v = opt.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _opt_id(opt, idx):
    if isinstance(opt, dict):
        for k in ("id", "key", "label"):
            v = opt.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(idx)


def _resolve_key(key, options):
    """Return the set of option indices matched by key."""
    ids = [_opt_id(o, i) for i, o in enumerate(options)]
    texts = [_opt_text(o) for o in options]
    matched = set()

    def try_one(tok):
        t = str(tok).strip()
        for i, oid in enumerate(ids):
            if oid == t:
                matched.add(i)
                return
        for i, tx in enumerate(texts):
            if tx == t:
                matched.add(i)
                return
        if t.isdigit():
            idx = int(t)
            if 0 <= idx < len(options):
                matched.add(idx)

    if isinstance(key, (list, tuple)):
        for k in key:
            try_one(k)
    elif isinstance(key, str):
        s = key.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    for k in parsed:
                        try_one(k)
                    return matched
            except json.JSONDecodeError:
                pass
        if "," in s:
            for part in s.split(","):
                try_one(part.strip())
        else:
            try_one(s)
    else:
        try_one(key)

    return matched


# ---- heuristic checks -------------------------------------------------------

def _h1_world_knowledge(item):
    """H1: stem/passage references a curriculum-anchor topic."""
    stem = item.get("stem", "") or ""
    passage = item.get("passage_text", "") or item.get("passage", "") or ""
    text_to_check = stem + " " + passage
    hit = _curriculum_anchor_match(text_to_check)
    if hit:
        return ("H1: stem/passage references curriculum-anchor topic '%s' — "
                "encyclopedic-passage risk; verify passage uses P1-P8 design rules"
                % hit)
    return None


def _h2_longest_option(item):
    """H2: correct option is the longest by >= 35% margin over next-longest."""
    options = item.get("options")
    if not isinstance(options, list) or len(options) < 2:
        return None
    key = item.get("key")
    if key is None:
        return None

    keyed = _resolve_key(key, options)
    if not keyed:
        return None

    texts = [_opt_text(o) for o in options]
    ids = [_opt_id(o, i) for i, o in enumerate(options)]
    lengths = [len(t) for t in texts]

    for ki in keyed:
        klen = lengths[ki]
        other_lengths = [lengths[i] for i in range(len(options)) if i not in keyed]
        if not other_lengths:
            continue
        next_longest = max(other_lengths)
        if klen > 0 and next_longest > 0 and klen >= LENGTH_MARGIN * next_longest:
            return ("H2: correct option '%s' is longest (%d chars) and >= 35%% longer "
                    "than next (%d chars) — length giveaway for non-reader"
                    % (ids[ki], klen, next_longest))
    return None


def _h3_absolute_language(item):
    """H3: wrong options contain absolute language."""
    options = item.get("options")
    if not isinstance(options, list):
        return None
    key = item.get("key")
    keyed = _resolve_key(key, options) if key is not None else set()

    flags = []
    for i, opt in enumerate(options):
        if i in keyed:
            continue  # only check wrong options
        text = _opt_text(opt)
        m = ABSOLUTE_TERMS.search(text)
        if m:
            oid = _opt_id(opt, i)
            flags.append("H3: wrong option '%s' contains absolute term '%s' — "
                         "eliminatable without passage" % (oid, m.group(0)))
    return flags if flags else None


def _h4_generic_stem(item):
    """H4: stem is a generic main-idea question."""
    stem = item.get("stem", "") or ""
    if GENERIC_STEMS.match(stem.strip()):
        return ("H4: stem is a generic main-idea pattern ('%s...') — "
                "check that wrong options are promoted-detail distractors, "
                "not broad topic truths" % stem.strip()[:60])
    return None


# ---- format filter ----------------------------------------------------------

_MCQ_TYPES = {"mcq", "single-select", "single_select", "multiple-choice", "multiplechoice", "mc"}
_MSQ_TYPES = {"msq", "multi-select", "multi_select", "multiple-select", "multiselect"}


def _is_mcq_or_msq(item):
    t = (item.get("type") or "").strip().lower()
    return t in _MCQ_TYPES or t in _MSQ_TYPES or t == ""  # default to MCQ for untyped


# ---- per-item runner --------------------------------------------------------

def check_item(item):
    """
    Run all heuristics on one item. Returns pre_check dict:
      {"leaked": bool, "flags": [str, ...]}
    """
    if not _is_mcq_or_msq(item):
        return {"leaked": False, "flags": [], "skipped": True,
                "skip_reason": "format '%s' skipped (checks are MCQ/MSQ only)"
                               % item.get("type", "untyped")}

    flags = []

    f1 = _h1_world_knowledge(item)
    if f1:
        flags.append(f1)

    f2 = _h2_longest_option(item)
    if f2:
        flags.append(f2)

    f3 = _h3_absolute_language(item)
    if f3:
        flags.extend(f3)

    f4 = _h4_generic_stem(item)
    if f4:
        flags.append(f4)

    return {"leaked": len(flags) > 0, "flags": flags}


# ---- selftest ---------------------------------------------------------------

SELFTEST_ITEMS = [
    {
        "type": "mcq",
        "stem": "What is the main idea of the passage?",
        "options": [
            {"id": "A", "text": "Monarch butterflies migrate because they cannot survive cold winters, and the journey requires many generations to complete."},
            {"id": "B", "text": "Many animals move south in fall."},
            {"id": "C", "text": "Butterflies have wings."},
            {"id": "D", "text": "All insects change behavior when temperatures drop in the wild."},
        ],
        "key": "A",
        "feedback": "The passage is mainly about monarch butterfly migration.",
        "ccss": "RI.5.2",
        "passage_text": "Monarch butterflies migrate south each fall because they cannot survive freezing temperatures.",
        "_expected_flags": ["H1", "H2", "H3", "H4"],
        "_note": "Should flag all four heuristics",
    },
    {
        "type": "mcq",
        "stem": "Why did the river guide turn back at the third canyon?",
        "options": [
            {"id": "A", "text": "She saw the water level had dropped below the safe threshold her team had set."},
            {"id": "B", "text": "She recognized the canyon from a map her partner had drawn."},
            {"id": "C", "text": "Her equipment stopped working in the cold."},
            {"id": "D", "text": "She wanted to return before dark."},
        ],
        "key": "A",
        "feedback": "The passage states she turned back when the water level dropped.",
        "ccss": "RL.5.3",
        "passage_text": "When the gauge read 1.4 meters — two-tenths below the threshold she and Marcos had agreed on — she signaled the group to turn around.",
        "_expected_flags": [],
        "_note": "Should pass all heuristics",
    },
]


def run_selftest():
    print("=== SELFTEST ===")
    all_pass = True
    for i, item in enumerate(SELFTEST_ITEMS):
        result = check_item(item)
        expected = item.get("_expected_flags", [])
        actual_hcodes = set()
        for f in result["flags"]:
            m = re.match(r"^(H\d):", f)
            if m:
                actual_hcodes.add(m.group(1))
        expected_set = set(expected)
        ok = expected_set == actual_hcodes
        if not ok:
            all_pass = False
        print("[%d] %s | expected=%s got=%s | %s" % (
            i, item.get("_note", ""), sorted(expected_set),
            sorted(actual_hcodes), "OK" if ok else "MISMATCH"
        ))
        for f in result["flags"]:
            print("    %s" % f)
    print("=== SELFTEST %s ===" % ("PASS" if all_pass else "FAIL"))
    return 0 if all_pass else 1


# ---- main -------------------------------------------------------------------

def main(argv):
    args = argv[1:]
    quiet = "--quiet" in args
    only_flagged = "--only-flagged" in args
    args = [a for a in args if a not in ("--quiet", "--only-flagged")]

    if "--selftest" in args:
        return run_selftest()

    if not args:
        sys.stderr.write(__doc__ or "")
        sys.stderr.write("\nERROR: provide a JSONL items file (or --selftest)\n")
        return 2

    path = args[0]
    if not os.path.exists(path):
        sys.stderr.write("ERROR: file not found: %s\n" % path)
        return 2

    n_total = n_flagged = n_passed = n_skipped = 0
    flag_counts = {"H1": 0, "H2": 0, "H3": 0, "H4": 0}

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        sys.stderr.write("ERROR: could not read %s: %s\n" % (path, e))
        return 2

    for lineno, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw:
            continue

        try:
            item = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.stderr.write("WARN: line %d is not valid JSON (%s) — skipped\n" % (lineno, e))
            continue

        n_total += 1
        pre_check = check_item(item)

        if pre_check.get("skipped"):
            n_skipped += 1
            if not quiet:
                sys.stderr.write("[line %d] SKIP  %s\n" % (lineno, pre_check.get("skip_reason", "")))
            item["pre_check"] = pre_check
            if not only_flagged:
                print(json.dumps(item, ensure_ascii=False))
            continue

        for f in pre_check["flags"]:
            m = re.match(r"^(H\d):", f)
            if m:
                hcode = m.group(1)
                if hcode in flag_counts:
                    flag_counts[hcode] += 1

        if pre_check["leaked"]:
            n_flagged += 1
            if not quiet:
                stem_preview = (item.get("stem") or "")[:70]
                sys.stderr.write("[line %d] FLAG  %s\n" % (lineno, stem_preview))
                for f in pre_check["flags"]:
                    sys.stderr.write("         %s\n" % f)
            item["pre_check"] = pre_check
            print(json.dumps(item, ensure_ascii=False))
        else:
            n_passed += 1
            if not quiet:
                stem_preview = (item.get("stem") or "")[:70]
                sys.stderr.write("[line %d] PASS  %s\n" % (lineno, stem_preview))
            item["pre_check"] = pre_check
            if not only_flagged:
                print(json.dumps(item, ensure_ascii=False))

    n_mcq_msq = n_total - n_skipped
    sys.stderr.write("\n" + "=" * 60 + "\n")
    sys.stderr.write("SELF-CHECK SUMMARY\n")
    sys.stderr.write("  total items ............. %d\n" % n_total)
    sys.stderr.write("  MCQ/MSQ checked ......... %d\n" % n_mcq_msq)
    sys.stderr.write("  other formats skipped ... %d\n" % n_skipped)
    sys.stderr.write("  passed pre-check ........ %d\n" % n_passed)
    sys.stderr.write("  likely-leaked (flagged) . %d\n" % n_flagged)
    if n_mcq_msq > 0:
        pct = 100.0 * n_flagged / n_mcq_msq
        sys.stderr.write("  flag rate ............... %.1f%%\n" % pct)
        sys.stderr.write("\n  flags by heuristic:\n")
        for hcode in ("H1", "H2", "H3", "H4"):
            sys.stderr.write("    %s: %d items\n" % (hcode, flag_counts[hcode]))
    sys.stderr.write("=" * 60 + "\n")

    if n_flagged > 0:
        sys.stderr.write("\nNOTE: %d item(s) flagged. These are LIKELY-LEAKED — "
                         "do not submit without fixing.\n" % n_flagged)
        sys.stderr.write("      Passing pre-check is NOT a green light: the full "
                         "anti_leak_grader.py + LLM blind-solve still applies.\n")
        return 1

    sys.stderr.write("\nAll %d MCQ/MSQ items passed pre-check heuristics.\n" % n_passed)
    sys.stderr.write("Still run anti_leak_grader.py for the full structural gate.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
