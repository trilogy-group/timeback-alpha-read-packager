# PASSAGE_GENERATOR.md — G5 Non-Leaky Passage Prompt Templates

See PASSAGE_DESIGN_RULES.md for the underlying theory. This document is operational:
copy-paste the templates, fill the placeholders, run the self-check.

---

## Overview

| Constraint | Value |
|---|---|
| Lexile target | 800–950 (hard floor and ceiling for G5) |
| Word count | 180–240 words per passage |
| Domain rotation cap | ≤ 15% of total passages from any single domain |
| Item format compatibility | hot-text, sequence, match, EBSR |

**Approved domains (non-curriculum):**
urban planning, materials engineering, agricultural economics, sports biomechanics,
environmental law, architectural history, public health policy, food science, labor economics,
marine navigation, wildlife rehabilitation, industrial design, urban ecology, medical history
(non-famous), culinary science, transportation engineering, textile manufacturing.

**Blocked domains (curriculum — leak risk):**
astronomy, biology of famous organisms, major wars, chemistry of standard processes,
famous explorer biographies, standard earth science (water cycle, plate tectonics).

---

## Template 1 — Argument-Stance

*Most versatile type. Every passage should layer this on top of whichever structural type it uses.*

### SYSTEM prompt

```
You are a reading-assessment passage writer for Grade 5 students.
Lexile target: 800–950. Word count: 180–240. Prose only (no headers, bullets, or tables).

PASSAGE MUST BE PASSAGE-DEPENDENT:
A student who studied [DOMAIN] in school but never read this specific text must be
UNABLE to answer the questions without reading it.

FINGERPRINT BLOCKLIST — never use these passage shapes:
- biography of a famous scientist listing their discoveries
- standard process summary (water cycle, photosynthesis, plate tectonics)
- famous historical event with a known outcome
- passage whose central fact is a headline figure (year of moon landing, speed of light)
- any passage whose main claim a student could retrieve from a typical K-8 curriculum

LEXILE GUARDRAIL:
- Average sentence length: 15–22 words
- Vocabulary: Tier 2 academic words are fine; avoid both primer-simple and graduate-obscure
- No passive-only constructions; vary sentence structure

FALSIFIABILITY REQUIREMENT:
The passage's central claim must be a debatable proposition, not a settled fact.
The author takes a specific, explicit side. Include one acknowledged counterargument
that the author then rebuts or qualifies. This makes the stance non-retrievable.

REQUIRED STRUCTURAL MOVES (include all three):
1. Author states a specific, arguable position in the opening paragraph.
2. At least one non-headline specific figure (e.g., 34%, 1.8 km, 1923) that is obscure
   and only accessible through this passage.
3. A named individual or group assigned a specific motivation or belief, not a
   general role ("city planners wanted efficiency" is too generic; name a specific
   decision-maker or coalition and give their stated rationale).
```

### USER prompt scaffold

```
Write a 180–240 word argument-stance passage for Grade 5.

Domain: [DOMAIN — pick from approved list, not from blocked list]
Specific topic angle: [NARROW ANGLE — not the famous version of this topic, e.g.,
  not "why urban trees are good" but "why the 1972 Chicago tree canopy ordinance
  was counterproductive despite good intentions"]

The passage must:
- Open with the author's explicit, arguable claim (one sentence, declarative)
- Support the claim with at least two pieces of evidence, one of which is a
  specific number or measurement that is NOT the famous headline figure
- Name at least one individual or group with a specific motivation assigned in-text
- Include one counterargument in one sentence, then rebut or qualify it
- Close with a conclusion that restates the claim with new language

Do NOT:
- Summarize the standard textbook account
- State only facts that a student who studied [DOMAIN] would already know
- Use a famous person as the central figure

Output: passage text only, no title, no headers.
```

### AFTER-GENERATION SELF-CHECK prompt

```
Read the passage above. Answer these three questions:

1. LEAK TEST: Could a typical Grade 5 student who studied [DOMAIN] in school —
   but never read this specific passage — correctly answer "What is the author's
   main argument?" and "What specific evidence supports it?" using only prior
   knowledge? Answer YES or NO with one sentence of justification.

2. STANCE CLARITY: Is the author's position explicitly stated (not merely implied)?
   Quote the sentence that states it.

3. NON-HEADLINE FIGURE: Does the passage contain at least one specific number,
   date, or measurement that is NOT a famous widely-known figure for this topic?
   Quote it.

If the answer to (1) is YES, or (2) or (3) fail, rewrite the passage before use.
```

### Example domain picks

- **Agricultural economics:** "Why consolidation of mid-size grain farms after
  1985 reduced regional food price stability — contrary to the efficiency argument
  made at the time." (Obscure policy angle; no famous headline facts.)
- **Environmental law:** "Why the 1990 Clean Air Act's cap-and-trade sulfur provision
  cost northeastern utilities 40% more than the EPA's 1989 projection, and what
  that means for future emissions markets." (Specific figure; debatable implication.)

### Anti-pattern to avoid

> "Many scientists believe that urban trees reduce air pollution. Studies show that
> trees absorb carbon dioxide and provide shade. Some critics argue trees are too
> expensive to maintain, but most experts agree the benefits outweigh the costs."

This is a stance-free opinion sandwich. No named figure, no specific number,
no falsifiable claim. Every sentence is retrievable from prior knowledge.

---

## Template 2 — Causal-Chain

### SYSTEM prompt

```
You are a reading-assessment passage writer for Grade 5 students.
Lexile target: 800–950. Word count: 180–240. Prose only.

PASSAGE MUST BE PASSAGE-DEPENDENT.

FINGERPRINT BLOCKLIST: (same as Template 1)

LEXILE GUARDRAIL: (same as Template 1)

FALSIFIABILITY REQUIREMENT:
The causal chain must include at least one link that is non-obvious or counterintuitive.
Do not use a causal chain whose every step is curriculum-standard knowledge.

REQUIRED STRUCTURAL MOVES:
1. Present a sequence of exactly 3–5 causally linked steps, each step named explicitly
   with a transition word (caused, led to, triggered, resulted in, produced).
2. At least one intermediate step must be non-obvious (i.e., a student cannot predict
   step N+1 from step N using general knowledge alone).
3. Include one named actor, policy, or measurement at a specific point in the chain
   so that questions can test position in the chain, not just endpoints.
```

### USER prompt scaffold

```
Write a 180–240 word causal-chain passage for Grade 5.

Domain: [DOMAIN]
Chain topic: [DESCRIBE the first cause and the final effect; leave the intermediate
  steps to be generated — e.g., "Start: a textile tariff change in 1923.
  End: collapse of a regional river fishery by 1931."]

Requirements:
- Number the chain steps explicitly in the prose using words (first, then, this caused,
  which in turn, finally) — do NOT use numbered lists
- Each step must be distinct; do not restate the same link in different words
- At least one intermediate step must surprise a reader who knows the start and end
- Include one specific measurement or figure at one of the intermediate steps

Output: passage text only, no title, no headers.
```

### AFTER-GENERATION SELF-CHECK prompt

```
Read the passage above. Answer:

1. LIST the causal chain as a numbered sequence: Step 1 → Step 2 → ... → Step N.
   Are there between 3 and 5 steps?

2. NON-OBVIOUS LINK: Which step could NOT be predicted by a student who only knows
   the starting condition and the final outcome? Quote it.

3. LEAK TEST: Could a student answer "What caused [FINAL EFFECT]?" using only prior
   knowledge about [DOMAIN], without reading this passage? YES or NO + justification.

If chain has fewer than 3 steps, a non-obvious link is absent, or (3) is YES, rewrite.
```

### Example domain picks

- **Marine navigation:** How a change in a single port dredging schedule in 1908
  cascaded into a regional shipping-rate spike that bankrupted three ferry companies.
- **Food science:** How a switch in commercial bread flour milling technique in the
  1960s altered gluten structure in ways that increased shelf life but reduced
  satiety signals in consumers.

### Anti-pattern to avoid

> "Deforestation causes soil erosion, which leads to flooding, which harms fish
> populations." Every link is curriculum-standard. No measurement, no named actor,
> no non-obvious step. A student answers without reading.

---

## Template 3 — Decision-Reaction

### SYSTEM prompt

```
You are a reading-assessment passage writer for Grade 5 students.
Lexile target: 800–950. Word count: 180–240. Prose only.

PASSAGE MUST BE PASSAGE-DEPENDENT.

FINGERPRINT BLOCKLIST: (same as Template 1)

LEXILE GUARDRAIL: (same as Template 1)

FALSIFIABILITY REQUIREMENT:
The character's decision must not be the famous or expected choice. If the character
is real and well-known, the decision must be one NOT taught in standard curriculum.
Prefer fictional-but-realistic characters in specific professional roles.

REQUIRED STRUCTURAL MOVES:
1. Establish a character in a specific professional role (not a celebrity or
   curriculum figure) facing a concrete decision with two clearly defined options.
2. Show the character's internal reasoning for the choice actually made —
   at least one reason must be non-obvious.
3. Describe the immediate reaction and one downstream consequence of the decision.
```

### USER prompt scaffold

```
Write a 180–240 word decision-reaction passage for Grade 5.

Domain: [DOMAIN]
Character: [ROLE, not a famous person — e.g., "a harbor master in 1920s Glasgow",
  "a textile quality inspector in 1950s North Carolina", "a city traffic engineer
  in 1960s São Paulo"]
Decision: [TWO OPTIONS the character faces, e.g., "approve a new dye formula
  that cuts cost by 22% but carries unknown long-term fiber effects, or reject it
  and risk the mill closing"]

Requirements:
- Character's reasoning must include at least one reason that contradicts
  the obvious self-interest logic
- Include a specific figure (cost, date, measurement) to anchor the decision stakes
- The downstream consequence must be counterintuitive or ironic

Output: passage text only, no title, no headers.
```

### AFTER-GENERATION SELF-CHECK prompt

```
Read the passage above. Answer:

1. DECISION CLARITY: What are the two options the character faces? Can both be
   identified from the passage alone?

2. NON-OBVIOUS REASONING: Quote the sentence that shows the character's reasoning.
   Could a student predict this reasoning from general knowledge about the domain?

3. LEAK TEST: Could a student correctly answer "Why did [CHARACTER] choose [OPTION]?"
   without reading this passage? YES or NO + justification.

If (1) fails, (2) is predictable, or (3) is YES, rewrite.
```

### Example domain picks

- **Wildlife rehabilitation:** A rehabilitation center director deciding whether to
  release a recovering osprey before full wing strength is confirmed, because a
  holding-pen infection is spreading.
- **Industrial design:** A factory floor supervisor approving a non-standard alloy
  mix that violates company specification but will prevent a three-week shutdown.

### Anti-pattern to avoid

> "Marie Curie decided to keep working on radium even though it was dangerous.
> She believed science was worth the sacrifice." Famous figure, predictable reasoning,
> no measurement, no non-obvious downstream consequence.

---

## Template 4 — Surprising-Reversal

### SYSTEM prompt

```
You are a reading-assessment passage writer for Grade 5 students.
Lexile target: 800–950. Word count: 180–240. Prose only.

PASSAGE MUST BE PASSAGE-DEPENDENT.

FINGERPRINT BLOCKLIST: (same as Template 1)

LEXILE GUARDRAIL: (same as Template 1)

FALSIFIABILITY REQUIREMENT:
The reversal must contradict a specific, named expectation — not just say "surprisingly."
The passage must state what people expected AND what actually happened, and explain
the mechanism that caused the gap. The mechanism is the lock; it lives only in
this passage.

REQUIRED STRUCTURAL MOVES:
1. State the common expectation explicitly in the first paragraph.
2. Introduce the reversal in the second paragraph with a specific figure or outcome.
3. Explain the mechanism that produced the reversal — this mechanism is the
   passage-dependent content that questions will test.
```

### USER prompt scaffold

```
Write a 180–240 word surprising-reversal passage for Grade 5.

Domain: [DOMAIN]
Setup expectation: [WHAT MOST PEOPLE WOULD PREDICT — e.g., "that replacing
  coal-fired kilns with electric kilns would reduce a ceramics factory's energy costs"]
Actual outcome: [THE REVERSAL — e.g., "energy costs rose 31% in the first two years
  because electric kilns require longer warm-up cycles that doubled daily energy draws"]
Mechanism: [WHY THE REVERSAL HAPPENED — this is the passage-dependent content]

Requirements:
- Use the word "expected" or "predicted" or "assumed" in the first paragraph
- Include at least one specific number in the reversal statement
- The mechanism explanation must take at least two sentences
- Do not soften the reversal; it should be genuinely counterintuitive

Output: passage text only, no title, no headers.
```

### AFTER-GENERATION SELF-CHECK prompt

```
Read the passage above. Answer:

1. EXPECTATION STATED: Quote the sentence that names the common expectation.

2. REVERSAL STATED: Quote the sentence that states what actually happened.
   Does it include a specific number or measurement?

3. MECHANISM PRESENT: Quote the sentences that explain WHY the reversal happened.
   Is this mechanism something a student could retrieve from prior knowledge
   about [DOMAIN], or does it live only in this passage?

4. LEAK TEST: Could a student answer "What actually happened and why?" without
   reading? YES or NO + justification.

If any of (1)–(3) are absent, or (4) is YES, rewrite.
```

### Example domain picks

- **Public health policy:** The expectation that mandatory calorie labeling on menus
  would reduce fast-food calorie consumption; the reversal that average order calories
  increased 8% in the first year because customers used the labels to justify
  higher-calorie choices.
- **Transportation engineering:** The expectation that widening a highway interchange
  would reduce peak-hour congestion; the reversal that travel times increased because
  the wider road induced 40% more vehicle trips (induced demand).

### Anti-pattern to avoid

> "It might seem surprising that some deserts get cold at night. This is because
> deserts have low humidity and lose heat quickly." The "surprise" is taught in
> every earth science unit. No specific figure, no named expectation holder,
> no mechanism that lives only in this passage.

---

## Template 5 — Obscure-Consequence

### SYSTEM prompt

```
You are a reading-assessment passage writer for Grade 5 students.
Lexile target: 800–950. Word count: 180–240. Prose only.

PASSAGE MUST BE PASSAGE-DEPENDENT.

FINGERPRINT BLOCKLIST: (same as Template 1)

LEXILE GUARDRAIL: (same as Template 1)

FALSIFIABILITY REQUIREMENT:
The consequence must be one that a student who knows the famous event would NOT
know. The famous event is the hook (it can appear); the consequence and the
causal link from event to consequence are the lock.

REQUIRED STRUCTURAL MOVES:
1. Introduce the anchor event briefly (1–2 sentences max) — it may be well-known.
2. Pivot immediately to the obscure consequence — this is the body of the passage.
3. Trace the specific mechanism linking event to consequence with at least one
   non-obvious intermediate step and one specific figure.
```

### USER prompt scaffold

```
Write a 180–240 word obscure-consequence passage for Grade 5.

Domain: [DOMAIN]
Anchor event (hook): [WELL-KNOWN OR SEMI-KNOWN EVENT — e.g., "the 1906 San Francisco
  earthquake and fire"]
Obscure consequence: [UNFAMILIAR SIDE EFFECT — e.g., "permanent relocation of
  the West Coast canned-goods industry to Monterey, because destroyed San Francisco
  warehouses were never rebuilt"]
Mechanism: [HOW THE EVENT CAUSED THIS SPECIFIC CONSEQUENCE]

Requirements:
- Spend no more than 2 sentences on the anchor event; the consequence is the subject
- Include one specific figure in the consequence section
- The mechanism must include at least one step a student could not predict from
  knowing only the anchor event

Output: passage text only, no title, no headers.
```

### AFTER-GENERATION SELF-CHECK prompt

```
Read the passage above. Answer:

1. ANCHOR BALANCE: How many sentences describe the anchor event? Should be ≤ 2.

2. CONSEQUENCE OBSCURITY: Would a student who knows the anchor event already
   know this consequence? YES or NO + justification.

3. MECHANISM CHECK: Is the causal link from event to consequence fully traced
   in the passage, with at least one non-obvious intermediate step?

4. LEAK TEST: Could a student answer "What was one consequence of [ANCHOR EVENT]?"
   with this specific consequence, without reading? YES or NO + justification.

If (1) > 2 sentences, (2) is YES, (3) is missing, or (4) is YES, rewrite.
```

### Example domain picks

- **Labor economics:** The anchor = mechanized harvesting adoption in California
  in the 1960s. Consequence = rapid growth of a seasonal migrant labor contracting
  industry in Arizona, because displaced California laborers moved there in numbers
  that exceeded Arizona farm demand, creating a new middleman sector.
- **Urban ecology:** The anchor = construction of the Interstate Highway System
  in the 1950s. Consequence = a 300% increase in urban hawk nesting density in
  Midwestern cities, because highway medians created continuous grassland corridors
  that supported the vole populations hawks depend on.

### Anti-pattern to avoid

> "The Industrial Revolution caused pollution. One consequence was that rivers
> in England became dirty and fish populations declined." Both the event and the
> consequence are curriculum-standard. No specific figure, no mechanism, no lock.

---

## Template 6 — Specific-Comparison

### SYSTEM prompt

```
You are a reading-assessment passage writer for Grade 5 students.
Lexile target: 800–950. Word count: 180–240. Prose only.

PASSAGE MUST BE PASSAGE-DEPENDENT.

FINGERPRINT BLOCKLIST: (same as Template 1)

LEXILE GUARDRAIL: (same as Template 1)

FALSIFIABILITY REQUIREMENT:
The comparison must use criteria introduced in this passage — not criteria a student
would apply from general knowledge. The winner or better-performer on the passage's
criteria must be non-obvious, or must contradict the common assumption.

REQUIRED STRUCTURAL MOVES:
1. Name both items being compared explicitly in the first paragraph.
2. Introduce 2–3 comparison criteria that the passage defines — do not rely on
   commonly known criteria.
3. Apply each criterion to both items with specific figures.
4. State a conclusion that follows from the passage's criteria, not from prior
   knowledge about the items.
```

### USER prompt scaffold

```
Write a 180–240 word specific-comparison passage for Grade 5.

Domain: [DOMAIN]
Item A: [FIRST NAMED THING]
Item B: [SECOND NAMED THING]
Comparison criteria (passage-defined): [2–3 CRITERIA THAT ARE NOT COMMON KNOWLEDGE —
  e.g., "load-bearing performance per unit of material weight, resistance to
  thermal cycling, and cost per decade of maintenance" rather than "which is stronger"]
Expected winner by common assumption: [ITEM A or B — the passage should either
  confirm with a non-obvious mechanism, or reverse this assumption]
Actual conclusion in passage: [WHICH WINS ON THE PASSAGE'S CRITERIA, and why]

Requirements:
- Each criterion must have at least one specific number applied to at least one item
- The conclusion sentence must explicitly name the criterion that determined the winner
- Do not state which item "most people think is better" — show the assumption
  through the comparison structure itself

Output: passage text only, no title, no headers.
```

### AFTER-GENERATION SELF-CHECK prompt

```
Read the passage above. Answer:

1. CRITERIA SOURCE: List the comparison criteria used. Are they defined inside the
   passage, or are they general knowledge a student brings in?

2. FIGURES PRESENT: For each criterion, is there at least one specific number
   applied to at least one item?

3. CONCLUSION TRACEABILITY: Can the conclusion be derived only by following the
   passage's criteria, or could a student reach the same conclusion from prior
   knowledge?

4. LEAK TEST: Could a student correctly answer "Which is better and why?" without
   reading this passage? YES or NO + justification.

If (1) criteria are common knowledge, (2) has no figures, (3) is derivable without
reading, or (4) is YES, rewrite.
```

### Example domain picks

- **Materials engineering:** Comparing cast iron pipe versus ductile iron pipe for
  urban water mains, judged by fracture propagation rate under frost heave, not by
  the commonly known "strength" criterion.
- **Culinary science:** Comparing two bread leavening methods (long-fermentation
  sourdough vs. commercial yeast) judged by crust tensile strength and crumb
  moisture retention after 48 hours — not flavor or rise time.

### Anti-pattern to avoid

> "Electric cars and gasoline cars can be compared in several ways. Electric cars
> produce less pollution, but gasoline cars can travel farther on one fill-up.
> Both have advantages and disadvantages." No passage-defined criteria, no specific
> figures, no non-obvious conclusion. Entirely answerable from prior knowledge.

---

## Domain Rotation Tracker (pseudocode)

```python
# domain_rotation.py
# Enforce: no single domain > 15% of total passages generated in a batch.

from collections import defaultdict

def check_domain_cap(domain_counts: dict[str, int], proposed_domain: str) -> bool:
    """
    Returns True (OK to use) or False (cap exceeded).
    domain_counts: {"urban planning": 4, "food science": 2, ...}
    proposed_domain: the domain you are about to generate for
    """
    total = sum(domain_counts.values()) + 1  # +1 for the proposed passage
    proposed_count = domain_counts.get(proposed_domain, 0) + 1
    return (proposed_count / total) <= 0.15

def next_allowed_domain(domain_counts: dict[str, int],
                        approved_domains: list[str]) -> list[str]:
    """Return approved domains that are still under the 15% cap."""
    total = sum(domain_counts.values()) + 1
    return [
        d for d in approved_domains
        if (domain_counts.get(d, 0) + 1) / total <= 0.15
    ]

# Usage in a generation loop:
domain_counts = defaultdict(int)
approved = [
    "urban planning", "materials engineering", "agricultural economics",
    "sports biomechanics", "environmental law", "architectural history",
    "public health policy", "food science", "labor economics",
    "marine navigation", "wildlife rehabilitation", "industrial design",
    "urban ecology", "medical history (non-famous)", "culinary science",
    "transportation engineering", "textile manufacturing",
]

for passage_slot in range(NUM_PASSAGES):
    allowed = next_allowed_domain(domain_counts, approved)
    chosen = pick_domain(allowed)          # your selection logic here
    generate_passage(chosen)
    domain_counts[chosen] += 1
```

**Hard rule:** If `next_allowed_domain` returns fewer than 5 options, stop and
add more domains to the approved list before continuing.

---

## Quick Validation Checklist (deterministic, no LLM)

These two checks replicate the logic in `deterministic_passage_gate.py`.
Run both before submitting any passage for item writing.

### Check 1 — Topic / Fingerprint Block

```
BLOCKED_PATTERNS = [
    # Famous scientists
    r'\b(curie|darwin|newton|einstein|pasteur|leeuwenhoek|faraday|galileo)\b',
    # Curriculum processes
    r'\b(photosynthesis|water cycle|plate tectonics|mitosis|osmosis|bioluminescence)\b',
    # Famous events
    r'\b(moon landing|world war|american revolution|great wall|panama canal|library of alexandria)\b',
    # Headline figures
    r'\bspeed of light\b',
    r'\bboiling point of water\b',
]

def topic_check(passage_text: str) -> bool:
    """Returns True (PASS) if no blocked pattern found."""
    text = passage_text.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, text):
            return False   # FAIL — blocked pattern present
    return True            # PASS
```

**If FAIL:** do not patch the passage. Replace the topic.

### Check 2 — Information Density

```
def information_density_check(passage_text: str) -> bool:
    """
    Returns True (PASS) if passage contains:
      - at least 1 specific number (digit string, percentage, measurement)
      - at least 1 named non-famous individual OR named organization
      - word count between 180 and 240

    A passage failing any sub-check is structurally leak-prone.
    """
    import re

    # Sub-check A: specific figure present
    has_figure = bool(re.search(r'\d+\.?\d*\s*(%|km|kg|lb|ft|mph|°|dollars?|tons?|years?)?', passage_text))

    # Sub-check B: named entity present (capitalized non-sentence-start word)
    sentences = passage_text.split('.')
    named_entities = []
    for s in sentences:
        words = s.strip().split()
        # Skip first word (sentence start); flag capitalized words elsewhere
        named_entities += [w for w in words[1:] if w and w[0].isupper()]
    has_named_entity = len(named_entities) >= 1

    # Sub-check C: word count in range
    word_count = len(passage_text.split())
    in_range = 180 <= word_count <= 240

    return has_figure and has_named_entity and in_range
```

**If FAIL on figure:** add a specific measurement or date to the passage.
**If FAIL on named entity:** name a specific actor or location.
**If FAIL on word count:** expand or trim to target range before item writing.

---

*End of PASSAGE_GENERATOR.md*
