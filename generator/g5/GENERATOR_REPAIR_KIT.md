# Generator Repair Kit — Distractor Quality Fixes

**For:** Abdul (Gemini generator prompt)
**Based on:** Forensic analysis of 150 MCQ + 100 MSQ items (62.7% MCQ leak rate, 51.0% MSQ leak rate)
**Purpose:** Drop the section below directly into your Gemini generator prompt.

---

## DIAGNOSIS SUMMARY

Three patterns account for nearly all leaked items:

| Pattern | MCQ share | MSQ share | Why it leaks |
|---|---|---|---|
| Absolute language in wrong options | 27.3% | 34% | Students eliminate "always/never/all/only" without reading |
| Correct answer is the longest option | 28% | n/a | Length cue alone recovers the key |
| Generic topic-domain wrong option | 22% | 8% | "Any passage on this topic" option is trivially wrong |
| World-knowledge-only correct answer | — | 25% | Right answer is the only scientifically plausible one |

Fix all four and you eliminate the leak. The prompt additions below are paste-ready.

---

## PASTE THIS INTO YOUR GEMINI PROMPT

Place this block immediately after your existing distractor-generation instructions.

---

```
=== DISTRACTOR QUALITY RULES (NON-NEGOTIABLE) ===

You are generating answer options for a 5th-grade reading assessment. The ONLY acceptable discrimination
source is the passage. A student who has NOT read the passage must not be able to eliminate any wrong
option with confidence. Apply every rule below before finalizing each item.

--- RULE 1: NO ABSOLUTE LANGUAGE IN WRONG OPTIONS ---
Never use absolute language in any wrong answer option. Banned words and phrases:
  all, none, never, always, completely, entirely, the only, every, exclusively, totally, solely,
  banned, made illegal, forced all, stopped all, destroyed all, caused everyone to, replaced all.
Absolute claims are trivially eliminatable — readers know real-world phenomena are rarely total.
Each wrong option must describe something that could plausibly be partially true OR true in a
different context.

BAD distractor: "It forced all male clerks to leave their jobs and become mechanics."
GOOD distractor: "It led many experienced clerks to shift into supervisory roles overseeing typists."

--- RULE 2: CORRECT ANSWER MUST NOT BE THE LONGEST OPTION ---
Keep all four answer options within 15% of the same character length.
The correct answer must NOT be the longest option.
Before finalizing, measure: is the correct answer noticeably longer than the wrong options?
  - If yes: trim it, OR extend the wrong options to match length.
Wrong options must be substantively complete sentences, not truncated fragments used only to
create contrast. Padding a wrong option with a false clause is acceptable to equalize length.

BAD: Correct = 22 words. Wrong options = 8, 9, 11 words.
GOOD: All options within 3–4 words of each other.

--- RULE 3: NO GENERIC TOPIC-DOMAIN WRONG OPTIONS ---
For main-idea and central-idea questions, do NOT include a wrong option that is a broad true
generalization about the topic domain.

Example of banned option type for a passage about sea otters:
  BAD: "Marine animals have developed many unique behaviors to find food and survive in the ocean."
  (This is true of ANY passage about ocean animals — it does not require reading THIS passage.)

Instead, every wrong option for a main-idea stem must name a specific but incorrect main idea —
one that plausibly could have been the main point of THIS specific passage but was not.
The wrong option should reference a real detail from the passage, elevated incorrectly to
main-idea status (a "promoted supporting detail" distractor).

GOOD wrong option for the sea otter passage: "Sea otters use rocks as tools, making them one of
the few non-human animals that use objects to get food."
(This IS in the passage, but it is a supporting detail, not the main idea — students must have
read the passage to know whether this is the main point.)

--- RULE 4: WRONG OPTIONS MUST INVOKE PLAUSIBLE MECHANISMS ---
For science and social studies content, wrong options must ALSO sound scientifically or historically
plausible to someone with general 5th-grade domain knowledge.
Do not make the correct answer the ONLY option that references a real scientific or causal mechanism.

If the correct answer states: "The molecules in solids are packed closer together, passing
vibrations more quickly" — then at least two wrong options must ALSO cite a plausible mechanism,
just the wrong one for this passage.

BAD wrong option: "Gravity pulls sound waves downward through physical objects."
  (A 5th grader knows gravity does not selectively apply to sound — eliminatable by world knowledge.)
GOOD wrong option: "Solids and liquids have higher temperatures that cause vibrations to move
faster through their particles."
  (Plausible — temperature does affect wave speed — but not what THIS passage explains.)

--- RULE 5: NO MUTUALLY CONTRADICTORY WRONG OPTIONS ---
After generating your options, do a pairwise check: are any two wrong options logical contradictions
of each other? (e.g., one says "increased" and another says "decreased" for the same variable.)
If so, replace one. When two wrong options contradict each other, a student can eliminate both and
is left with a 50/50 — you have effectively built a 2-choice item.

--- RULE 6: EVERY WRONG OPTION MUST REQUIRE PASSAGE ACCESS TO ELIMINATE ---
Final check before accepting any item: ask yourself —
  Could a smart 5th grader who has NOT read this passage cross off this wrong option using only
  (a) world knowledge, or (b) recognizing it as an absolute claim?
If yes → replace it with a "near-neighbor" distractor: something that sounds like it came from
the passage but subtly distorts one key detail (wrong cause, wrong effect, reversed relationship,
or a correct detail applied to the wrong part of the text).

=== END DISTRACTOR QUALITY RULES ===
```

---

## WORKED EXAMPLE: BEFORE vs. AFTER

**Stem:** Based on the two accounts, how do the authors' points of view about the desert solar farm differ?

### BEFORE (leaky — 62.7% of your current output looks like this)

A) Dr. Sato views the desert as an ideal place to generate solar energy, while Ms. Carter views it as a fragile wilderness that must be protected from development.
B) Dr. Sato wants to build a resort near the solar panels, while Ms. Carter wants to fence off the **entire** desert to keep **all** people out.
C) **Both** Dr. Sato and Ms. Carter **agree** that desert tortoises will benefit from the shade under the new solar panels.
D) Dr. Sato is concerned about the survival of rare desert plants, while Ms. Carter is focused on reducing carbon emissions.

**Why it leaks:**
- Option B uses "entire" and "all people" — absolute language, eliminatable without reading.
- Option C uses "Both... agree" on a question asking about a *difference* — eliminatable by reading the stem alone.
- Option D has the authors' concerns *reversed* from the passage but is actually the hardest distractor (near-neighbor). The problem is options B and C are too easy, so students only need to choose between A and D.
- Option A is 24 words. Options B–D are 17, 15, 16 words. Length flags A as correct.

### AFTER (passage-dependent)

A) Dr. Sato views the desert as an ideal location for energy production, while Ms. Carter argues that desert construction threatens the habitat of native wildlife.
B) Dr. Sato believes solar panels should replace oil refineries in the region, while Ms. Carter supports expanding solar energy only in already-developed areas.
C) Dr. Sato focuses on how the farm would reduce the town's energy bills, while Ms. Carter focuses on which companies should be awarded the construction contract.
D) Dr. Sato acknowledges some harm to desert wildlife but argues the energy benefits outweigh the costs, while Ms. Carter argues the opposite.

**Why it works:**
- Option A: Correct. Requires reading both accounts.
- Option B: Near-neighbor. "Replace oil refineries" and "already-developed areas" sound like things an author might argue — but neither appears in the passage. Students must read to rule this out.
- Option C: Near-neighbor. "Energy bills" and "construction contract" are plausible economic concerns — not what the authors actually discuss.
- Option D: The hardest distractor — it correctly identifies the authors' tension (harm vs. benefit trade-off) but reverses Dr. Sato's position. Requires close reading to eliminate.
- All options: 20–24 words. No absolutes. No self-contradictions. No length cue.

---

## 3 SELF-CHECK TESTS (run before accepting any MCQ item)

Run these three tests on every item before outputting it. If any test fails, revise the item.

**Test 1 — The Passageless Elimination Test**
Give the stem + options to a hypothetical smart 5th grader who has NOT read the passage. Ask: can they eliminate any option with confidence? If yes, that option fails. Replace it.

Checklist:
- [ ] No option contains "all, none, never, always, completely, entirely, the only, every, exclusively, totally, solely, banned, made illegal"
- [ ] No option is a broad true generalization that applies to ANY passage on this topic
- [ ] No option is eliminatable purely by scientific or historical common knowledge

**Test 2 — The Length Parity Test**
Count characters (or words) in each option.
- [ ] All options are within 15% of the same length (ideally within 5 words of each other)
- [ ] The correct answer is NOT the longest option
- [ ] No option is a truncated fragment (under 10 words for a 5th-grade item)

**Test 3 — The Contradiction Test**
Read every pair of wrong options.
- [ ] No two wrong options directly contradict each other (e.g., "increased" vs. "decreased" for the same variable)
- [ ] No two wrong options cover the same conceptual territory (near-duplicates inflate perceived difficulty without adding it)
- [ ] Each wrong option describes a distinct, independently plausible misreading

---

## WHY "NEAR-NEIGHBOR" DISTRACTORS WORK

A near-neighbor distractor is a wrong option that shares surface features with the correct answer but distorts one key detail — a wrong cause, a wrong effect, a reversed relationship, or a correct detail applied to the wrong part of the text.

Near-neighbors work because:

1. **They require passage access.** A student cannot eliminate a near-neighbor using world knowledge or pattern recognition — they must locate the relevant passage section and verify the specific claim. This is exactly the reading comprehension behavior the item is meant to measure.

2. **They model real misreading errors.** Students who read too fast, skim, or confuse adjacent paragraphs will find near-neighbors plausible. A distractor that no real reader would pick is wasted cognitive load.

3. **They distribute wrong-answer selections.** On a well-constructed item, each wrong option should attract roughly 10–20% of test-takers (with the correct answer attracting 50–60%+). Near-neighbors pull students who partially understood the passage but made a specific error. Absolute-language distractors and generic-domain options pull nobody — they inflate the "correct by elimination" rate without measuring anything.

**The construction recipe for a near-neighbor:**
- Start with a true statement from the passage.
- Change ONE of: the subject, the cause, the effect, the relationship direction, or the scope.
- Leave everything else intact so it sounds like it came from the passage.

Example:
- True (passage): "Water near the surface overflows, reducing pressure on the deep water and triggering the eruption."
- Near-neighbor distractor: "Water deep underground overflows into surface cracks, which releases pressure and stops the eruption." (subject swapped: deep vs. surface; relationship reversed: triggers vs. stops)

A student who read carefully knows both details are wrong. A student who skimmed might pick it.

---

*Forensics data: 150 MCQ + 100 MSQ items analyzed. MCQ leak rate 62.7%, MSQ leak rate 51.0%.*
*Primary drivers: absolute language (27–34%), longest-option cue (28% MCQ), generic-domain main-idea distractors (22% MCQ / 8% MSQ), world-knowledge-only correct answers (25% MSQ).*

---

## EBSR PART B: VERBATIM EVIDENCE QUOTE RULE

**For every EBSR item, Part B options MUST be formatted as direct passage quotes with quotation marks.**

Each Part B option must follow this exact format:

```
According to the passage, '[exact sentence from the passage here].'
```

Rules:
1. The sentence inside the quotes must be copied **verbatim** from the passage — word for word, no paraphrasing.
2. The **correct** Part B option must be the sentence that best supports the Part A answer (the evidence sentence that proves the Part A claim).
3. **Wrong** Part B options must be other real sentences from the passage that are plausible evidence for a DIFFERENT, incorrect Part A answer — not random sentences, not summaries, not invented text.
4. Every option, correct and wrong alike, must use the `According to the passage, '...'` wrapper with single quotes around the verbatim sentence.

BAD (paraphrase — fails grader):
```
"The white coat allows the fox to blend in and hide from predators."
```

GOOD (verbatim quote — passes grader):
```
"According to the passage, 'The white coat helps the fox blend in perfectly with the snow, making it nearly invisible to predators.'"
```

**Self-check before accepting any EBSR item:**
- [ ] Every Part B option contains a single-quoted verbatim passage sentence
- [ ] Every Part B option starts with "According to the passage, '"
- [ ] The correct Part B option directly supports the correct Part A answer
- [ ] Wrong Part B options are real passage sentences that would support a DIFFERENT (wrong) Part A answer — not random or off-topic sentences
