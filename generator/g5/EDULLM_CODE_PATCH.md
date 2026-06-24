# EduLLM-ELA Grade 5 — Passage-Blind Leakage Fix
## Exact Code Patch

**Problem:** 62.7% of MCQ and 51.0% of MSQ items are solvable without reading the passage.
**Root causes (from forensic analysis of 250 items):**
1. System prompt has no passage-necessity requirement — distractors are graded on plausibility alone, not passage-dependency.
2. N=1 for Grade 5 MCQ and MSQ — no tournament selection, so even mediocre items ship.
3. The existing DISTRACTOR QUALITY section tests "relevance to topic" but never tests "requires passage access to eliminate."

---

## PATCH 1 — `src/edullm/grades/grade_5/prompts.py`

### What to change

Add a new section **PASSAGE-NECESSITY RULES** immediately after the existing `DISTRACTOR QUALITY` section in `SYSTEM_PROMPT`. The insertion point is after this line:

```
- NOTE: Fill-in questions have NO options/distractors — they are open-ended blanks
```

### Before (end of DISTRACTOR QUALITY section, line ~77 of the string)

```python
- PARALLELISM: All options must match the grammatical structure of the stem (if stem says "to ___" all options must be infinitive form)
- NOTE: Fill-in questions have NO options/distractors — they are open-ended blanks

### FILL-IN FORMAT COMPLIANCE
```

### After (insert the block between NOTE line and FILL-IN FORMAT COMPLIANCE)

```python
- PARALLELISM: All options must match the grammatical structure of the stem (if stem says "to ___" all options must be infinitive form)
- NOTE: Fill-in questions have NO options/distractors — they are open-ended blanks

### PASSAGE-NECESSITY RULES (MCQ/MSQ only — new, non-negotiable)
The ONLY acceptable discrimination source is the passage. A student who has NOT read the passage
must not be able to eliminate any wrong option with confidence. Violating any rule below causes
the distractor_quality metric to fail.

--- RULE A: NO ABSOLUTE LANGUAGE IN WRONG OPTIONS ---
NEVER use absolute language in any wrong answer option.
Banned words in wrong options: all, none, never, always, completely, entirely, the only, every,
exclusively, totally, solely, banned, made illegal, forced all, stopped all, destroyed all,
caused everyone to, replaced all.
Absolute claims are trivially eliminatable — readers know real-world phenomena are rarely total.
Each wrong option must describe something that could plausibly be partially true OR true in
a different context.

BAD distractor: "It forced all male clerks to leave their jobs and become mechanics."
GOOD distractor: "It led many experienced clerks to shift into supervisory roles overseeing typists."

--- RULE B: CORRECT ANSWER MUST NOT BE THE LONGEST OPTION ---
Keep all four answer options within 15% of the same character length (ideally within 5 words).
The correct answer must NOT be the longest option.
Before finalizing, check: is the correct answer noticeably longer than the wrong options?
  - If yes: trim it, OR extend the wrong options with a substantive false clause to match length.
Wrong options must be substantively complete sentences, not truncated fragments.

BAD: Correct = 22 words. Wrong options = 8, 9, 11 words.
GOOD: All options within 3-4 words of each other.

--- RULE C: NO GENERIC TOPIC-DOMAIN WRONG OPTIONS ---
For main-idea and central-idea questions, do NOT include a wrong option that is a broad true
generalization about the topic domain.

BAD for a sea otter passage: "Marine animals have developed many unique behaviors to survive in
the ocean." (True of ANY ocean passage — does not require reading THIS passage.)

Instead, every wrong option for a main-idea stem must name a specific but incorrect main idea —
one that plausibly could have been the main point of THIS specific passage but was not.
Use "promoted supporting detail" distractors: take a real detail from the passage and elevate
it incorrectly to main-idea status.

GOOD: "Sea otters use rocks as tools, making them one of the few non-human animals that use
objects to get food." (IS in the passage, but is a supporting detail, not the main idea.)

--- RULE D: WRONG OPTIONS MUST INVOKE PLAUSIBLE MECHANISMS ---
For science and social studies content, wrong options must sound scientifically or historically
plausible to someone with general Grade 5 domain knowledge.
Do not make the correct answer the ONLY option that references a real scientific or causal mechanism.
At least two wrong options must cite a plausible but incorrect mechanism.

BAD wrong option: "Gravity pulls sound waves downward through physical objects."
  (A Grade 5 student knows gravity doesn't selectively apply to sound — eliminatable.)
GOOD wrong option: "Solids and liquids have higher temperatures that cause vibrations to move
faster through their particles."
  (Plausible — temperature does affect wave speed — but not what THIS passage explains.)

--- RULE E: PASSAGE-ACCESS FINAL CHECK (run before accepting any MCQ/MSQ item) ---
For every wrong option, ask: "Could a smart Grade 5 student who has NOT read this passage
cross this option off using only (a) world knowledge, or (b) recognizing absolute language?"
If yes → replace with a near-neighbor distractor: something that sounds like it came from the
passage but subtly distorts one key detail (wrong cause, wrong effect, reversed relationship,
or a correct detail applied to the wrong part of the text).

CONSTRUCTION RECIPE FOR NEAR-NEIGHBOR DISTRACTORS:
  1. Start with a true statement from the passage.
  2. Change ONE of: the subject, the cause, the effect, the relationship direction, or the scope.
  3. Leave everything else intact so it sounds like it came from the passage.

Example:
  True (passage): "Water near the surface overflows, reducing pressure and triggering eruption."
  Near-neighbor: "Water deep underground overflows into surface cracks, which releases pressure
  and stops the eruption." (subject swapped: deep vs. surface; relationship reversed: triggers vs. stops)

### FILL-IN FORMAT COMPLIANCE
```

### Why this fixes the leak

The existing DISTRACTOR QUALITY section only requires distractors to be "relevant to the passage/scenario and the skill being tested." Relevance is not the same as passage-dependency. A distractor can be topically relevant to the subject matter (sea otters, sound waves, historical events) while still being eliminatable by world knowledge alone. The five new rules directly block the four patterns that account for 87% of leaked items:

| Pattern | Rule that blocks it |
|---|---|
| Absolute language in wrong options (27% MCQ / 34% MSQ) | Rule A |
| Correct answer is longest option (28% MCQ) | Rule B |
| Generic topic-domain wrong options (22% MCQ / 8% MSQ) | Rule C |
| World-knowledge-only correct answer (25% MSQ) | Rule D |
| Residual cases | Rule E (near-neighbor check) |

---

## PATCH 2 — `src/edullm/generation/config.py`

### What to change

Increase N from 1 to 3 for Grade 5 MCQ and MSQ in `N_CANDIDATES_MATRIX`.

### Before

```python
    # Grade 5 (1,154 evals)
    ("5", "mcq"): 1,
    ("5", "msq"): 1,
    ("5", "fill-in"): 1,
```

### After

```python
    # Grade 5 (1,154 evals — MCQ/MSQ raised to 3 for passage-blind leak fix 2026-06-23)
    ("5", "mcq"): 3,
    ("5", "msq"): 3,
    ("5", "fill-in"): 1,
```

Note: fill-in stays at 1. Fill-in has no distractors so the passage-blind leak does not apply. Raising fill-in N would only increase cost without addressing the identified failure mode.

### Why N=3 + the grader-as-critic cuts MCQ leak from 62% to ~15-20%

The tournament model works as follows: generate 3 candidates, score each with the self-eval/verify pipeline, keep the one with the highest distractor quality score. After the prompt fix (Patch 1), any single candidate has a lower probability of leaking. The N=3 tournament gives three independent draws from the improved distribution. If the per-item leak probability after the prompt fix is ~30% (conservative), the probability that ALL THREE candidates leak is 0.30^3 = 2.7%. In practice the verifier is also a critic that flags absolute language and length imbalance, so the realized leak rate post-tournament should land in the 10-20% range — consistent with the Grade 6 result (N=3, similar prompt, ~14% leak rate on a manual spot-check of 30 items).

The 1,154 Grade 5 evaluations underlying the current N=1 decision are too few to have surfaced the passage-blind failure mode — the InceptBench evaluator does not measure passage-necessity, so items were scoring well on the 12 automated metrics while shipping uneliminable distractors. N=3 is the right call given the identified quality gap; it can be dialed back to N=2 once a batch of 3,000+ evals confirms the leak rate has dropped below 5%.

---

## PATCH 3 — `src/edullm/grades/grade_5/overrides.py`

### Assessment

`overrides.py` contains `STANDARD_GUIDANCE` and `COMBO_OVERRIDES`. Both are the right place to add per-standard passage-necessity reinforcement. The passage-blind leak is worst for these question types:

- Main-idea / central-idea stems (RL.5.2, RI.5.2) — Rule C is most relevant
- Point-of-view comparison stems (RL.5.6, RI.5.6) — Rule A (absolutes) is most relevant
- Science/social studies content (RI.5.3, RI.5.5) — Rule D (plausible mechanisms) is most relevant

### Recommended additions to `STANDARD_GUIDANCE`

Add the following entries to the `STANDARD_GUIDANCE` dict. These do not replace existing entries — they add to or extend them.

```python
    # RL.5.2 / RI.5.2 — main idea / theme: promote-supporting-detail distractor rule
    "CCSS.ELA-LITERACY.RL.5.2": """
- For main-idea/theme MCQ: NEVER include a broad true generalization about the topic as a wrong option.
- Every wrong option must be a "promoted supporting detail" — a real detail from the passage
  elevated incorrectly to main-idea status. Students must have read the passage to rule it out.
- See PASSAGE-NECESSITY RULES → Rule C in the system prompt.
""",
    "CCSS.ELA-LITERACY.RI.5.2": """
- For main-idea MCQ: NEVER include a broad true generalization about the topic as a wrong option.
- Every wrong option must name a specific but incorrect main idea — something that plausibly could
  have been the main point of THIS passage but was not (promoted supporting detail).
- See PASSAGE-NECESSITY RULES → Rule C in the system prompt.
""",
    # RI.5.6 — multiple accounts / point of view: absolute language ban
    # (existing entry is analysis-focused; extend with passage-necessity note)
    # Replace the existing RI.5.6 entry with:
    "CCSS.ELA-LITERACY.RI.5.6": """
- Tests analyzing multiple accounts of the same event/topic
- Provide TWO texts with different perspectives
- For fill-in: ensure the explanation does NOT reference MCQ options that don't exist
- For MCQ/MSQ: NEVER use absolute language in wrong options ("both authors agree completely",
  "neither author ever mentions", "all experts believe"). See PASSAGE-NECESSITY RULES → Rule A.
- Wrong options must describe plausible but incorrect characterizations of each author's stance —
  students must read both accounts to rule them out.
""",
    # RI.5.3 / RI.5.5 — science/social studies mechanism questions
    "CCSS.ELA-LITERACY.RI.5.3": """
- The question stem MUST include a clear directive (existing rule — keep).
- For MCQ/MSQ on science or social studies content: at least two wrong options must cite a
  plausible but incorrect mechanism — not a claim eliminatable by Grade 5 world knowledge.
- See PASSAGE-NECESSITY RULES → Rule D in the system prompt.
""",
    "CCSS.ELA-LITERACY.RI.5.5": """
- Tests comparing and contrasting the overall structure of two or more texts.
- For MCQ: all four options must describe plausible structural characterizations. Never include
  an option eliminatable by absolute language ("the only text that ever uses", "completely avoids").
- See PASSAGE-NECESSITY RULES → Rules A and E in the system prompt.
""",
```

### Recommended addition to `COMBO_OVERRIDES`

The highest-leak combo is MCQ/medium with main-idea or point-of-view stems. Add:

```python
    # MCQ/medium: passage-necessity reinforcement (covers the 62.7% leak case)
    ("CCSS.ELA-LITERACY", "mcq", "medium"): """
PASSAGE-NECESSITY CHECK (required for every MCQ/medium item):
Before finalizing, verify ALL of the following:
1. No wrong option uses absolute language (all, none, never, always, entirely, the only, every).
2. The correct answer is NOT the longest option (all options within 15% character length).
3. No wrong option is a broad true generalization about the topic domain.
4. Every wrong option requires reading THIS passage to eliminate — not world knowledge alone.
5. At least two wrong options are "near-neighbors": plausible-sounding but subtly wrong on
   one specific detail (wrong cause, wrong effect, reversed relationship, or promoted detail).
If any check fails, revise before outputting.
""",
    # MCQ/hard: same check, since hard items had similar leak rates
    ("CCSS.ELA-LITERACY", "mcq", "hard"): """
PASSAGE-NECESSITY CHECK (required for every MCQ/hard item):
1. No wrong option uses absolute language.
2. Correct answer is NOT the longest option.
3. No wrong option is a broad true generalization.
4. Every wrong option requires passage access to eliminate.
5. All three wrong options are near-neighbors with distinct, specific distortions.
For hard difficulty: the near-neighbors must distort details from DIFFERENT parts of the passage
so students must read carefully throughout, not just skim one paragraph.
""",
    # MSQ/medium: passage-necessity (51% MSQ leak rate)
    ("CCSS.ELA-LITERACY", "msq", "medium"): """
PASSAGE-NECESSITY CHECK (required for every MSQ/medium item):
1. No wrong option uses absolute language.
2. No wrong option is eliminatable by Grade 5 world/domain knowledge alone.
3. Both wrong options must cite plausible but incorrect mechanisms, details, or interpretations.
4. For science/social studies content: both wrong options must sound scientifically plausible
   (Rule D) — the correct answers must NOT be the only options citing real mechanisms.
5. Near-neighbor structure: each wrong option distorts one specific detail from the passage.
""",
```

---

## Git Diff Summary

```diff
diff --git a/src/edullm/generation/config.py b/src/edullm/generation/config.py
--- a/src/edullm/generation/config.py
+++ b/src/edullm/generation/config.py
@@ -34,9 +34,9 @@ N_CANDIDATES_MATRIX: dict[tuple[str, str], int] = {
-    # Grade 5 (1,154 evals)
-    ("5", "mcq"): 1,
-    ("5", "msq"): 1,
-    ("5", "fill-in"): 1,
+    # Grade 5 (1,154 evals — MCQ/MSQ raised to 3 for passage-blind leak fix 2026-06-23)
+    ("5", "mcq"): 3,
+    ("5", "msq"): 3,
+    ("5", "fill-in"): 1,
```

```diff
diff --git a/src/edullm/grades/grade_5/prompts.py b/src/edullm/grades/grade_5/prompts.py
--- a/src/edullm/grades/grade_5/prompts.py
+++ b/src/edullm/grades/grade_5/prompts.py
@@ (after the NOTE: Fill-in questions have NO options/distractors line)
+
+### PASSAGE-NECESSITY RULES (MCQ/MSQ only — new, non-negotiable)
+The ONLY acceptable discrimination source is the passage. A student who has NOT read the passage
+must not be able to eliminate any wrong option with confidence. Violating any rule below causes
+the distractor_quality metric to fail.
+
+--- RULE A: NO ABSOLUTE LANGUAGE IN WRONG OPTIONS ---
+[... full text as shown in Patch 1 above ...]
+
+--- RULE E: PASSAGE-ACCESS FINAL CHECK ---
+[... full text as shown in Patch 1 above ...]
```

```diff
diff --git a/src/edullm/grades/grade_5/overrides.py b/src/edullm/grades/grade_5/overrides.py
--- a/src/edullm/grades/grade_5/overrides.py
+++ b/src/edullm/grades/grade_5/overrides.py
@@ STANDARD_GUIDANCE dict
+    "CCSS.ELA-LITERACY.RL.5.2": """...""",
+    "CCSS.ELA-LITERACY.RI.5.2": """...""",
+    # Replace existing RI.5.6 entry with extended version
+    "CCSS.ELA-LITERACY.RI.5.6": """...""",
+    "CCSS.ELA-LITERACY.RI.5.3": """... extended with Rule D reference ...""",
+    "CCSS.ELA-LITERACY.RI.5.5": """...""",
@@ COMBO_OVERRIDES dict
+    ("CCSS.ELA-LITERACY", "mcq", "medium"): """...""",
+    ("CCSS.ELA-LITERACY", "mcq", "hard"): """...""",
+    ("CCSS.ELA-LITERACY", "msq", "medium"): """...""",
```

---

## Estimated Impact

| Change | Mechanism | Expected MCQ leak reduction |
|---|---|---|
| Patch 1 (prompt rules) alone | Blocks 4 distractor patterns at generation time | 62.7% → ~30-35% |
| Patch 2 (N=3 tournament) alone | Best-of-3 selection from current distribution | 62.7% → ~40% |
| Patch 1 + Patch 2 combined | Best-of-3 from improved distribution | ~30% → ~10-15% |
| Patch 3 (overrides) | Per-standard reinforcement for highest-leak combos | Additional ~3-5pp |

**Conservative combined estimate: MCQ leak 62.7% → 12-18%. MSQ leak 51.0% → 10-15%.**

The verifier (Method 4 rewrite loop with Claude-sonnet-4-6) already catches distractor grounding failures but has no specific check for passage-necessity. The Patch 1 rules function as generation-time prevention; the N=3 tournament functions as selection-time defense. The two are multiplicative, not additive.

---

## Files touched

1. `src/edullm/generation/config.py` — 3-line change (N matrix, Grade 5 rows)
2. `src/edullm/grades/grade_5/prompts.py` — insert ~60 lines into `SYSTEM_PROMPT` string
3. `src/edullm/grades/grade_5/overrides.py` — add ~5 `STANDARD_GUIDANCE` entries + 3 `COMBO_OVERRIDES` entries

No schema changes. No new imports. No model changes. All changes are prompt text and one integer matrix edit.
