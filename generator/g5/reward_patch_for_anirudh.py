"""
reward_patch_for_anirudh.py

Two heuristic additions to test_g5_reading_reward.py::evaluate().
These fire in <2ms — no API calls, no training-loop latency impact.

HOW TO USE:
  1. Copy the two functions (passage_curriculum_penalty, cold_passage_bonus)
     into test_g5_reading_reward.py
  2. Modify the evaluate() function's return to add them:

     total_reward = (
         existing_inceptbench_score(item)        # unchanged
         + passage_curriculum_penalty(passage)   # NEW
         + cold_passage_bonus(passage)           # NEW
     )

WHY:
  InceptBench scores 0-1 for structural quality (well-formed question, valid key,
  near-neighbour distractors, CCSS label). It does NOT test passage-dependency.
  These two heuristics add a directional signal toward cold (non-encyclopedic) passages.

  Tier 1 (penalty -0.2): penalizes curriculum-grade encyclopedic topics.
    The model generated "What is the primary function of chlorophyll?" from a photosynthesis
    passage — InceptBench rated it valid. Any Grade 5 student answers it without reading.

  Tier 2 (bonus +0.1): rewards passages with markers of cold, specific content.
    Named but non-famous individuals, specific measurements, argument-stance language,
    reversal language — these are signals the passage has original content to lock the question.

LIMITATION (be honest):
  These are heuristics, not oracles. A passage on the Coriolis effect that never uses
  "Coriolis" will escape the curriculum fingerprint. A famous name used in a non-biographical
  role (Marie Curie working in a lab in a narrative) will false-positive.
  These improve calibration on the most egregious cases; the gold standard remains a
  cross-family blind-solve run offline against checkpoints.
"""

import re

# ─── Tier 1: curriculum fingerprint penalty ───────────────────────────────────

CURRICULUM_TOPIC_FINGERPRINTS = [
    # Science concepts taught K-8
    r'\bphotosynthesis\b', r'\bwater cycle\b', r'\bevaporation\b', r'\bcondensation\b',
    r'\bplate tectonics\b', r'\bvolcan\w+\b', r'\berosion\b', r'\bbioluminescen\w+\b',
    r'\bgeothermal\b', r'\bosmosis\b', r'\bmigration pattern\b',
    r'\bfood chain\b', r'\bfood web\b', r'\blife cycle\b', r'\brock cycle\b',
    r'\bcarbon cycle\b', r'\bnitrogen cycle\b', r'\bchlorophyll\b',
    r'\bphotovoltaic\b', r'\bsolar (panel|energy|power)\b',
    # Famous figures — biographical summaries are curriculum content
    r'\b(Marie Curie|Charles Darwin|Isaac Newton|Albert Einstein|Benjamin Franklin)\b',
    r'\b(Frederick Douglass|Abraham Lincoln|George Washington|Thomas Jefferson)\b',
    r'\b(Neil Armstrong|Amelia Earhart|Harriet Tubman|Rosa Parks)\b',
    r'\b(Leonardo da Vinci|Galileo Galilei|Nikola Tesla)\b',
    # Well-known events with curriculum-memorized outcomes
    r'\b(Civil War|World War (I|II|1|2|One|Two)|Vietnam War)\b',
    r'\b(American Revolution|French Revolution|Industrial Revolution)\b',
    r'\b(moon landing|Apollo 11|D-Day|Pearl Harbor)\b',
    r'\b(Great Wall|Panama Canal|Transcontinental Railroad|Hoover Dam)\b',
    r'\b(Boston Tea Party|Declaration of Independence|Emancipation Proclamation)\b',
    # Generic-process topics
    r'\bphotosynthes\w+\b', r'\bcellular respiration\b',
    r'\bsolar system\b', r'\bgravit\w+ (pull|force|field)\b',
    r'\belectromagneti\w+\b', r'\bphotosynthes\w+\b',
]

def passage_curriculum_penalty(passage_text: str) -> float:
    """
    Returns -0.2 if the passage is on a curriculum-grade encyclopedic topic,
    0.0 otherwise.

    A passage that hits a curriculum fingerprint is likely to produce
    leaky questions regardless of how well-formed they are.
    """
    text_lower = (passage_text or "").lower()
    for pattern in CURRICULUM_TOPIC_FINGERPRINTS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return -0.2
    return 0.0


# ─── Tier 2: cold passage bonus ───────────────────────────────────────────────

COLD_PASSAGE_SIGNALS = [
    # Specific measurements (not famous constants)
    r'\b\d+\.?\d*\s*(percent|%|degrees[CF]|km|kilometers|meters|grams|kg|liters)\b',
    # Named but non-famous individuals (FirstName LastName pattern not in famous-person list)
    r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',
    # Character decision / reversal language
    r'\b(decided|hesitated|reconsidered|doubted|changed her mind|changed his mind|reversed course|reversed her|reversed his)\b',
    # Argument-stance language
    r'\b(argues|contends|claims|disputes|challenges the view|the author believes|the author argues|according to the author)\b',
    # Causal chain language
    r'\b(which led to|which caused|as a result of which|the consequence was|this triggered|setting off a chain)\b',
    # Reversal / surprise language
    r'\b(surprisingly|unexpectedly|contrary to|despite|paradoxically|counterintuitively|it turned out|it was discovered that)\b',
    # Obscure-consequence angle
    r'\b(unintended|unforeseen|unexpected (benefit|consequence|effect|result)|overlooked|underestimated)\b',
]

def cold_passage_bonus(passage_text: str) -> float:
    """
    Returns +0.1 if the passage shows ≥3 markers of cold, specific, arguable content.
    Returns 0.0 otherwise.

    Cold passages contain new, non-memorizable information: specific decisions,
    argument stances, reversal moments, specific-comparison outcomes.
    """
    text = (passage_text or "")
    hits = sum(1 for p in COLD_PASSAGE_SIGNALS if re.search(p, text, re.IGNORECASE))
    return 0.1 if hits >= 3 else 0.0


# ─── Integration template ─────────────────────────────────────────────────────
#
# In test_g5_reading_reward.py, modify the evaluate() function:
#
#   from reward_patch_for_anirudh import passage_curriculum_penalty, cold_passage_bonus
#
#   def evaluate(item: dict) -> float:
#       # existing logic
#       inceptbench_score = your_existing_inceptbench_score(item)
#       passage = item.get("passage") or item.get("stimulus") or ""
#
#       total = (
#           inceptbench_score
#           + passage_curriculum_penalty(passage)
#           + cold_passage_bonus(passage)
#       )
#       return max(0.0, min(1.0, total))  # clamp to [0, 1]
#
# The clamp prevents the curriculum penalty (-0.2) from creating negative rewards
# when InceptBench scores close to 0.

if __name__ == "__main__":
    # Quick smoke test
    encyclopedic = "Photosynthesis is the process by which plants use sunlight, water and carbon dioxide to produce oxygen and energy in the form of sugar."
    cold = "Marisol hesitated at the entrance to the collapsed mine. The rescue team claimed it was safe, but contrary to their assessment, she noticed three new cracks running along the support beam. She decided to call the second team rather than proceed, despite the foreman's objection that this would delay the rescue by four hours."

    print("Encyclopedic passage:")
    print(f"  curriculum_penalty: {passage_curriculum_penalty(encyclopedic)}")
    print(f"  cold_bonus:         {cold_passage_bonus(encyclopedic)}")

    print("\nCold passage:")
    print(f"  curriculum_penalty: {passage_curriculum_penalty(cold)}")
    print(f"  cold_bonus:         {cold_passage_bonus(cold)}")
