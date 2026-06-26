#!/usr/bin/env python3
"""
add_match_decoys.py — Fix the "unused-right-bucket-exists" structural gate failure
in Abdul's Grade-5 match items by injecting one plausible-but-unused decoy category
into every match item.

Usage:
    python3 add_match_decoys.py <input_jsonl> <output_jsonl> [--passage-lookup <json>]

Defaults:
    input_jsonl   : required positional arg
    output_jsonl  : required positional arg
    passage-lookup: /tmp/passage_lookup.json (item_id → passage text)

Every match item gets exactly ONE new right-side bucket appended:
  - text contains the decoy label
  - id   is "decoy_cat" (or "decoy_cat_<N>" if a collision exists)
  - It is NOT referenced in item["key"], so no left item maps to it.

The decoy is chosen by rule — no LLM call required.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------
# Rule-based decoy engine
# ---------------------------------------------------------------------------

def _decoy_explicit_implicit(item, passage: str) -> str:
    """Items with Explicitly-Stated / Must-Be-Inferred always get this third bucket."""
    return "Author's Opinion or Judgment"


def _decoy_main_ideas(item, passage: str) -> str:
    """Items with two paragraph-level main-idea buckets get a plausible third topic."""
    cats_text = " ".join(r["text"].lower() for r in item["right"])
    p = passage.lower()

    if "photosynthesis" in p or "solar" in cats_text:
        return "Animals consume plants and release carbon dioxide as a byproduct of respiration."
    if "migration" in p or "bird" in cats_text:
        return "Environmental threats like habitat loss are reducing migratory bird populations."
    if "seed" in p or "dispersal" in cats_text:
        return "Seeds require specific soil conditions and temperatures to germinate successfully."
    if "desert" in p or "moisture" in cats_text or "foliage" in cats_text:
        return "Desert animals have evolved behavioral strategies to cope with extreme heat."
    return "Human activities have disrupted the natural processes described in this passage."


def _decoy_entity_roles(item, passage: str) -> str:
    """Items that name ecosystem entities (comprehend-informational-relationships)
    get a plausible organism/structure that could belong to the same system."""
    cats = " ".join(r["text"].lower() for r in item["right"])

    # Match by distinctive entity names — ordered most-specific first
    checks = [
        (["zooxanthellae", "coral poly", "parrotfish"],       "Crown-of-Thorns Starfish"),
        (["termite", "fungus garden", "chimney"],             "Queen's Chamber"),
        (["leafcutter ant", "cultivated fungus", "escovopsis"], "Soldier Ants"),
        (["fungus", "algae", "mineral dust"],                 "Moss Spores"),
        (["elaiosome", "harvester ant", "kangaroo rat"],      "Cactus Wren"),
        (["army ant", "antbird"],                             "Leaf-Cutter Ants"),
        (["aphid", "honeydew", "herding ant"],                "Plant Roots"),
        (["sea otter", "sea urchin", "giant kelp"],           "Harbor Seals"),
        (["cleaner wrasse", "moray eel"],                     "Manta Rays"),
        (["mistletoe", "host tree", "mistletoebird"],         "Bark Beetles"),
        (["photobacteria", "anglerfish", "lanternfish"],      "Vampire Squid"),
    ]
    for keywords, decoy in checks:
        if any(kw in cats for kw in keywords):
            return decoy

    # Generic fallback
    return "Decomposers"


# Vocabulary decoy lookup.
# Primary signal = the actual target words being tested (item["left"] texts, lower-cased).
# Fallback signal = passage tokens.
# Each entry: (set_of_trigger_words, decoy_definition).
# The trigger words are matched exactly (whole-token) against the LEFT items first,
# then against the passage.  Order matters: first match wins.
#
# Design rule: keep trigger sets DISJOINT so order rarely matters, but sort by
# specificity so an overlap always resolves to the more specific topic.

_VOCAB_TARGET_TABLE = [
    # Target-word signals → topic detected from the vocabulary words themselves
    ({"ascent", "summit", "treacherous"},
     "Rugged: Rough and uneven, especially describing difficult terrain"),
    ({"celestial", "luminous", "obscure"},
     "Orbit: The curved path an object follows as it moves around another body in space"),
    ({"harmonious", "solo", "enthusiastic"},
     "Tempo: The speed or pace at which a piece of music is played or performed"),
    ({"knead", "pungent", "incorporate"},
     "Simmer: To cook gently just below the boiling point"),
    ({"knead", "mold", "brittle"},
     "Kiln: A furnace used to fire or harden clay objects at high temperatures"),
    ({"draft", "revise", "vivid"},
     "Narrate: To tell or describe a sequence of events aloud or in writing"),
    ({"flourish", "nurture", "parched"},
     "Wilt: To become limp or droop due to heat or a lack of water"),
    ({"cavernous", "navigate", "eerie"},
     "Stalactite: A spike of rock that hangs from the ceiling of a cave"),
    ({"elusive", "plumage", "hover"},
     "Migrate: To travel from one region to another with the changing seasons"),
    ({"pliable", "intertwine", "durable"},
     "Loom: A device used to weave threads or fibers into fabric"),
    ({"excavate", "fragment", "ancient"},
     "Stratum: A distinct horizontal layer of rock or earth in which artifacts are found"),
    ({"assemble", "function", "manual"},
     "Calibrate: To adjust a device so it measures or operates with greater precision"),
    ({"construct", "anchor", "hollow"},
     "Blueprint: A detailed technical drawing or plan used to guide construction"),
    # vibrant+shelter+fragile is marine/nature context (coral reef); check before art blend
    ({"vibrant", "shelter", "fragile"},
     "Camouflage: Colors or patterns that help an animal blend into its surroundings"),
    ({"vibrant", "blend", "miniature"},
     "Palette: A flat surface on which an artist mixes colors before applying them"),
    ({"cooperative", "forage", "sustain"},
     "Swarm: A large group of insects moving together in a dense cluster"),
]

# Passage-level fallback: whole-word tokens only (no prefix matching)
_VOCAB_PASSAGE_TABLE = [
    ({"telescope", "comet", "celestial", "constellation", "galaxy"},
     "Orbit: The curved path an object follows as it moves around another body in space"),
    ({"concert", "orchestra", "choir", "tempo", "melody", "harmonious"},
     "Tempo: The speed or pace at which a piece of music is played or performed"),
    ({"dough", "yeast", "recipe", "oven", "batter", "knead"},
     "Simmer: To cook gently just below the boiling point"),
    ({"kiln", "ceramic", "pottery", "sculpt", "glaze"},
     "Kiln: A furnace used to fire or harden clay objects at high temperatures"),
    ({"draft", "revise", "author", "chapter"},
     "Narrate: To tell or describe a sequence of events aloud or in writing"),
    ({"tomato", "backyard", "nurture", "flourish", "parched"},
     "Wilt: To become limp or droop due to heat or a lack of water"),
    ({"cave", "cavern", "stalactite", "stalagmite", "cavernous"},
     "Stalactite: A spike of rock that hangs from the ceiling of a cave"),
    ({"plumage", "flock", "elusive", "birdhouse", "feather"},
     "Migrate: To travel from one region to another with the changing seasons"),
    ({"reef", "anemone", "clownfish", "coral"},
     "Camouflage: Colors or patterns that help an animal blend into its surroundings"),
    ({"honeybee", "hive", "colony", "insect", "forage", "cooperative"},
     "Swarm: A large group of insects moving together in a dense cluster"),
    ({"loom", "weave", "textile", "pliable", "intertwine"},
     "Loom: A device used to weave threads or fibers into fabric"),
    ({"excavate", "artifact", "ruins", "stratum", "archaeologist"},
     "Stratum: A distinct horizontal layer of rock or earth in which artifacts are found"),
    ({"mural", "canvas", "easel", "brushstroke", "palette"},
     "Palette: A flat surface on which an artist mixes colors before applying them"),
    ({"mountain", "summit", "ascent", "altitude", "treacherous"},
     "Rugged: Rough and uneven, especially describing difficult terrain"),
]


def _decoy_vocabulary(item, passage: str) -> str:
    """Items that test context-clues vocabulary get a thematically plausible
    fourth word + definition that is NOT used in the passage.

    Strategy:
      1. Check the item's actual target words (left) against the target lookup table.
      2. If no match, fall back to whole-word passage token matching.
      3. Ultimate fallback: Precise.
    """
    import re

    # Build left-word token set (whole words, lower-cased)
    left_tokens = set(re.findall(r"[a-z]+", " ".join(l["text"].lower() for l in item["left"])))
    # Build passage token set
    passage_tokens = set(re.findall(r"[a-z]+", passage.lower()))

    # 1. Target-word lookup (highest priority).
    # Require >=2 matching tokens from the trigger set to avoid single-word
    # false positives when two trigger sets share a common word (e.g. "vibrant").
    for trigger_set, decoy in _VOCAB_TARGET_TABLE:
        if len(trigger_set & left_tokens) >= 2:
            return decoy

    # 2. Passage-level fallback (any single distinctive keyword is enough here
    # because passage keywords are chosen to be unambiguous domain signals).
    for trigger_set, decoy in _VOCAB_PASSAGE_TABLE:
        if trigger_set & passage_tokens:
            return decoy

    return "Precise: Exact and correct in every detail, without any error"


def _decoy_domain_vocab(item, passage: str) -> str:
    """Items classifying domain-specific words by function."""
    cats = " ".join(r["text"].lower() for r in item["right"])
    if "cell" in cats or "organelle" in cats:
        return "A protective membrane that surrounds and encloses the entire cell"
    if "glacier" in cats or "geological" in cats or "erosion" in cats:
        return "A volcanic process that builds entirely new surface landforms"
    return "A chemical process that transforms raw matter into a new substance"


# For morphological-analysis, the category IDs encode the root (cat_sub, cat_geo, etc.)
# We add a root that is NOT present in the item's existing categories.
_MORPH_ROOTS_IN_ORDER = [
    ("micro",  "micro- (meaning: small or tiny)"),
    ("tele",   "tele- (meaning: far away or distant)"),
    ("photo",  "photo- (meaning: light)"),
    ("therm",  "therm- (meaning: heat)"),
    ("aqua",   "aqua- (meaning: water)"),
    ("terra",  "terra- (meaning: earth or land)"),
    ("astro",  "astro- (meaning: star or space)"),
    ("chrono", "chrono- (meaning: time)"),
    ("anti",   "anti- (meaning: against or opposite)"),
]

def _decoy_morphology(item, passage: str) -> str:
    """Items that match words to root meanings get an absent root as the decoy."""
    present_ids = " ".join(r["id"].lower() for r in item["right"])
    present_words = " ".join(l["text"].lower() for l in item["left"])
    for root, label in _MORPH_ROOTS_IN_ORDER:
        if root not in present_ids and root not in present_words:
            return label
    return "poly- (meaning: many or multiple)"


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH = {
    "explicit-vs-implicit-details":        _decoy_explicit_implicit,
    "determine-multiple-main-ideas-and-details": _decoy_main_ideas,
    "comprehend-informational-relationships":    _decoy_entity_roles,
    "context-clues-vocabulary":            _decoy_vocabulary,
    "domain-specific-vocabulary-context":  _decoy_domain_vocab,
    "morphological-analysis":              _decoy_morphology,
}


def generate_decoy_text(item: dict, passage: str) -> str:
    kct = item.get("kct", "")
    fn = _DISPATCH.get(kct)
    if fn:
        return fn(item, passage)
    # Unknown KCT: generic structural decoy
    return "Not Enough Information to Classify"


# ---------------------------------------------------------------------------
# ID collision helper
# ---------------------------------------------------------------------------

def _safe_decoy_id(existing_ids: set) -> str:
    base = "decoy_cat"
    if base not in existing_ids:
        return base
    for n in range(2, 100):
        candidate = f"{base}_{n}"
        if candidate not in existing_ids:
            return candidate
    return f"decoy_cat_{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Core transformer
# ---------------------------------------------------------------------------

def inject_decoy(item: dict, passage: str) -> dict:
    """Return a copy of item with one unused decoy bucket appended to item['right']."""
    item = dict(item)  # shallow copy

    if item.get("type") != "match":
        return item

    decoy_text = generate_decoy_text(item, passage)

    existing_right_ids = {r["id"] for r in item.get("right", [])}
    decoy_id = _safe_decoy_id(existing_right_ids)

    new_right = list(item.get("right", []))
    new_right.append({"id": decoy_id, "text": decoy_text})
    item["right"] = new_right

    # key: decoy_id deliberately NOT added → no left item maps to it
    return item


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_jsonl",  help="Path to input JSONL file")
    parser.add_argument("output_jsonl", help="Path to output JSONL file")
    parser.add_argument(
        "--passage-lookup",
        default="/tmp/passage_lookup.json",
        help="JSON file mapping item_id → passage text (default: /tmp/passage_lookup.json)",
    )
    args = parser.parse_args()

    # Load passage lookup
    lookup_path = Path(args.passage_lookup)
    if lookup_path.exists():
        with open(lookup_path) as f:
            passage_lookup: dict = json.load(f)
        print(f"[info] Loaded passage lookup with {len(passage_lookup):,} entries.", file=sys.stderr)
    else:
        passage_lookup = {}
        print(f"[warn] Passage lookup not found at {lookup_path}; passages will be empty.", file=sys.stderr)

    input_path  = Path(args.input_jsonl)
    output_path = Path(args.output_jsonl)

    total = 0
    patched = 0
    skipped = 0

    with open(input_path) as fin, open(output_path, "w") as fout:
        for lineno, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[error] Line {lineno}: JSON decode error — {exc}", file=sys.stderr)
                fout.write(line + "\n")
                total += 1
                skipped += 1
                continue

            total += 1
            if item.get("type") == "match":
                passage = passage_lookup.get(item.get("id", ""), "")
                item = inject_decoy(item, passage)
                patched += 1

            fout.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(
        f"[done] Processed {total:,} items — "
        f"{patched:,} match items patched, "
        f"{total - patched - skipped:,} non-match items passed through, "
        f"{skipped:,} skipped due to errors.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
