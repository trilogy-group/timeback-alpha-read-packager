"""
deterministic_passage_gate.py

Two deterministic checks that run BEFORE any model call to decide whether a
passage is worth generating questions from.

Both checks are fast (regex-only, <1 ms) and callable from the reward pipeline,
the item-generation loop, or offline QA scripts.

API
---
    deterministic_passage_gate(passage_text: str) -> tuple[bool, str]

Returns:
    (True,  "pass")               passage clears both checks; proceed
    (False, "topic:<pattern>")    curriculum topic hit; reject
    (False, "low_density")        passage too sparse to lock a cold question

Design notes
------------
CHECK 1 — Topic gate
    Delegates to CURRICULUM_TOPIC_FINGERPRINTS from reward_patch_for_anirudh.
    If that module is not importable (different working directory or standalone
    use), falls back to an embedded minimal fingerprint list so this file stays
    self-contained for CI/testing.

CHECK 2 — Information-density gate
    Counts "information-rich" sentences by scanning for four signal classes:
      - Specific number/measurement
      - Causal connector
      - Stance marker (author argument language)
      - Reversal / surprise language
    If the passage is longer than 150 characters and fewer than 2 sentences carry
    at least one such signal, the passage is too sparse to anchor a non-leaky
    question (it has nothing new to ask about).

Honest limitation
-----------------
CHECK 2 splits on sentence-boundary punctuation; multi-sentence spans without
terminal punctuation (e.g. bullet lists, headers) will not split correctly and
may under-count or over-count density. For structured/tabular content, apply a
pre-processing normalizer before calling this gate.
"""

from __future__ import annotations

import re
from typing import Optional

# ─── Import curriculum fingerprints (with graceful fallback) ──────────────────

try:
    from reward_patch_for_anirudh import CURRICULUM_TOPIC_FINGERPRINTS  # type: ignore
except ImportError:
    # Minimal fallback — covers the highest-frequency encyclopedic topics.
    # Keep in sync manually if reward_patch_for_anirudh.py changes significantly.
    CURRICULUM_TOPIC_FINGERPRINTS = [
        r'\bphotosynthes\w+\b', r'\bwater cycle\b', r'\bplate tectonics\b',
        r'\bfood (chain|web)\b', r'\blife cycle\b', r'\brock cycle\b',
        r'\bcarbon cycle\b', r'\bnitrogen cycle\b', r'\bchlorophyll\b',
        r'\bcellular respiration\b', r'\bsolar system\b',
        r'\bnatural\s+selection\b', r'\bsurvival\s+of\s+the\s+fittest\b',
        r'\bmitosis\b', r'\bmeiosis\b', r'\bchloroplast\b',
        r'\bcell\s+(wall|membrane|nucleus)\b',
        r'\bconvert(s)?\s+sunlight\b', r'\btectonic\s+plate\b',
        r'\bwater\s+evaporat', r'\brelease(s)?\s+oxygen\b',
        r'\bgravitational\s+(pull|force|field)\b',
        r'\bgene(tic)?\s+expression\b',
        r'\b(Marie Curie|Charles Darwin|Isaac Newton|Albert Einstein)\b',
        r'\b(Abraham Lincoln|George Washington|Thomas Jefferson)\b',
        r'\b(Neil Armstrong|Harriet Tubman|Rosa Parks|Amelia Earhart)\b',
        r'\bCurie\b', r'\bDarwin\b', r'\bNewton\b', r'\bEinstein\b',
        r'\bFranklin\b', r'\bJefferson\b', r'\bLincoln\b', r'\bWashington\b',
        r'\bArmstrong\b', r'\bTubman\b', r'\bParks\b', r'\bEarhart\b',
        r'\b(Civil War|World War (I|II|1|2|One|Two))\b',
        r'\b(American Revolution|French Revolution|Industrial Revolution)\b',
        r'\b(Underground\s+Railroad|abolition(ist)?)\b',
        r'\b(Reconstruction|Emancipation)\b',
        r'\b(eruption|lava\s+flow|ash\s+cloud|tectonic\s+shift)\b',
    ]

# ─── Check 2: information-density signals ────────────────────────────────────

# Each pattern below must match within a single sentence to count.

_DENSITY_PATTERNS = [
    # Specific number / measurement
    re.compile(
        r'\b\d+\.?\d*\s*'
        r'(percent|%|degrees?\s*[CF]|km|meters?|grams?|kg|liters?|miles?|feet|inches?)',
        re.IGNORECASE,
    ),
    # Causal connector
    re.compile(
        r'\b(which\s+led\s+to|which\s+caused|as\s+a\s+result|triggered|setting\s+off)',
        re.IGNORECASE,
    ),
    # Stance marker
    re.compile(
        r'\b(argues?|contends?|claims?|disputes?|challenges?\s+the'
        r'|the\s+author\s+(argues?|believes?|contends?))',
        re.IGNORECASE,
    ),
    # Reversal / surprise language
    re.compile(
        r'\b(surprisingly|unexpectedly|contrary\s+to|paradoxically|counterintuitively)',
        re.IGNORECASE,
    ),
]

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _density_count(passage_text: str) -> int:
    """Return the number of sentences that contain at least one density signal."""
    sentences = _SENTENCE_SPLIT.split(passage_text.strip())
    count = 0
    for sentence in sentences:
        if any(pat.search(sentence) for pat in _DENSITY_PATTERNS):
            count += 1
    return count


# ─── Public gate function ─────────────────────────────────────────────────────

def deterministic_passage_gate(passage_text: str) -> tuple[bool, str]:
    """
    Run two deterministic checks on a passage.

    Parameters
    ----------
    passage_text : str
        Raw passage string (UTF-8 text, any length).

    Returns
    -------
    (passed: bool, reason: str)
        passed=True,  reason="pass"             both checks clear
        passed=False, reason="topic:<pattern>"  curriculum topic hit
        passed=False, reason="low_density"      fewer than 2 density sentences
                                                in a passage longer than 150 chars
    """
    text = passage_text or ""

    # CHECK 1: curriculum topic fingerprint
    for pattern in CURRICULUM_TOPIC_FINGERPRINTS:
        if re.search(pattern, text, re.IGNORECASE):
            return (False, f"topic:{pattern}")

    # CHECK 2: information density
    if len(text) > 150 and _density_count(text) < 2:
        return (False, "low_density")

    return (True, "pass")


# ─── __main__ smoke test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    _ENCYCLOPEDIC = (
        "Photosynthesis is the process by which plants use sunlight, water, and carbon "
        "dioxide to produce oxygen and energy in the form of sugar. Chloroplasts in plant "
        "cells contain chlorophyll, which absorbs light energy. This process releases oxygen "
        "as a byproduct. Plants convert sunlight into chemical energy stored in glucose. "
        "The water cycle and carbon cycle interact with photosynthesis at a global scale."
    )

    _COLD = (
        "When the Ridgeback Timber Company proposed clear-cutting 4,200 acres of the Carlow "
        "forest in 2019, ecologist Priya Menon argued that the company's environmental impact "
        "study had underestimated soil erosion by at least 35 percent. Contrary to the "
        "company's projections, her field measurements showed that water runoff had already "
        "increased by 18 liters per square meter after a pilot cut of just 120 acres. "
        "Surprisingly, the regional forestry board sided with Menon, which led to a two-year "
        "moratorium — a decision that set off a chain of similar challenges in three "
        "neighboring counties."
    )

    _LOW_DENSITY = (
        "The forest was quiet in the morning. Birds sang in the trees. The sun rose slowly "
        "over the hills. A deer walked through the clearing and looked around. The wind "
        "moved through the leaves. It was a peaceful day in the valley. Children played "
        "near the stream. The water was clear and cold. Everyone enjoyed the morning."
    )

    passages = [
        ("Encyclopedic (photosynthesis)", _ENCYCLOPEDIC),
        ("Cold + dense (Priya Menon logging)", _COLD),
        ("Low-density narrative", _LOW_DENSITY),
    ]

    print("=== deterministic_passage_gate smoke test ===\n")
    for label, text in passages:
        passed, reason = deterministic_passage_gate(text)
        density = _density_count(text)
        status = "PASS" if passed else "REJECT"
        print(f"[{status}] {label}")
        print(f"         reason={reason!r}  density_sentences={density}")
        print()
