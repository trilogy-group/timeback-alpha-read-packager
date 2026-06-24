# fix(grade-5): eliminate passage-blind MCQ/MSQ leak via prompt rules + N=3 tournament

## Problem

Forensic analysis of 250 Grade 5 items revealed a 62.7% MCQ leak rate and 51.0% MSQ leak rate — meaning a student who has never read the passage can eliminate wrong answers using world knowledge alone. The root cause is structural, not random:

| Defect pattern | MCQ share | MSQ share |
|---|---|---|
| Absolute language in wrong options (`all`, `never`, `always`, `the only`, etc.) | 27% | 34% |
| Correct answer is the longest option | 28% | — |
| Generic topic-domain wrong options (true of any passage on this subject) | 22% | 8% |
| World-knowledge-only correct answer (only option citing a real mechanism) | — | 25% |

These four patterns account for 87% of leaked items. The existing `DISTRACTOR QUALITY` section in the system prompt requires distractors to be "relevant to the passage" — but relevance is not the same as passage-dependency. An option can be topically relevant while still being trivially eliminatable.

Two compounding factors: Grade 5 runs N=1 (no tournament selection, so mediocre items ship unchallenged), and there are no per-standard overrides for the highest-leak standards (RL.5.6, RI.5.6, RI.5.3, RI.5.5).

---

## What this PR changes

### Patch 1 — `src/edullm/grades/grade_5/prompts.py`

Adds a **PASSAGE-NECESSITY RULES** section (5 rules, ~60 lines) to `SYSTEM_PROMPT`, inserted immediately after the existing `DISTRACTOR QUALITY` section. The rules are non-negotiable — violating any one causes `distractor_quality` to fail.

- **Rule A** — No absolute language in wrong options. Banned: `all`, `none`, `never`, `always`, `completely`, `entirely`, `the only`, `every`, `exclusively`, `totally`, `solely`, `destroyed all`, etc. Absolute claims are trivially eliminatable.
- **Rule B** — Correct answer must not be the longest option. All four options must stay within 15% of the same character length.
- **Rule C** — No generic topic-domain wrong options for main-idea/central-idea stems. Every wrong option must be a "promoted supporting detail" — a real detail from the passage incorrectly elevated to main-idea status.
- **Rule D** — Wrong options for science/social studies content must cite plausible but incorrect mechanisms, not claims eliminatable by Grade 5 world knowledge alone.
- **Rule E** — Final passage-access check before accepting any MCQ/MSQ item. Includes a near-neighbor distractor construction recipe (start with a true statement from the passage; change one of: subject, cause, effect, relationship direction, or scope).

### Patch 2 — `src/edullm/generation/config.py`

Changes N from 1 to 3 for Grade 5 MCQ and MSQ in `N_CANDIDATES_MATRIX`. Fill-in stays at 1 (no distractors, no passage-blind failure mode).

```python
# Before
("5", "mcq"): 1,
("5", "msq"): 1,

# After
("5", "mcq"): 3,
("5", "msq"): 3,
```

The anti-leak grader scores all 3 candidates; the first PASS is returned. If all 3 fail, the one with the highest structural score is used as fallback. With the per-item leak probability dropping to ~30% after Patch 1 (conservative), the probability all three candidates leak is 0.30^3 = 2.7%. This is consistent with the Grade 6 result (N=3, similar prompt, ~14% leak rate on a 30-item spot check).

### Patch 3 — `src/edullm/grades/grade_5/overrides.py`

Adds 5 entries to `STANDARD_GUIDANCE` and 3 entries to `COMBO_OVERRIDES` targeting the highest-leak standard/type combinations.

New `STANDARD_GUIDANCE` entries:
- `RL.5.2` — promoted-supporting-detail rule (Rule C) for theme/main-idea MCQ
- `RI.5.2` — same rule for informational main-idea MCQ
- `RI.5.6` — extends the existing entry with an explicit absolute-language ban for point-of-view comparison items (Rule A)
- `RI.5.3` — extends with Rule D (plausible mechanisms) for science/social studies content
- `RI.5.5` — text structure comparison: bans absolute language and requires Rule E check

New `COMBO_OVERRIDES` entries:
- `(CCSS.ELA-LITERACY, mcq, medium)` — 5-point passage-necessity checklist, run before output
- `(CCSS.ELA-LITERACY, mcq, hard)` — same checklist plus requirement that near-neighbors distort details from different parts of the passage
- `(CCSS.ELA-LITERACY, msq, medium)` — parallel 5-point checklist for MSQ items (targets the 51% MSQ leak rate)

---

## Estimated impact

| Change | Mechanism | Expected MCQ leak rate |
|---|---|---|
| Baseline (current) | N=1, no passage-necessity rules | 62.7% |
| Patch 1 alone | Blocks 4 distractor patterns at generation time | ~30-35% |
| Patch 2 alone | Best-of-3 from current (unchanged) distribution | ~40% |
| Patches 1 + 2 combined | Best-of-3 from improved distribution | ~10-15% |
| All 3 patches | Per-standard reinforcement on highest-leak combos | ~10-15%, with fewer hard-floor failures on RL.5.6 / RI.5.6 |

**Conservative combined estimate: MCQ 62.7% → 12-18%. MSQ 51.0% → 10-15%.**

Patch 3 contributes ~3-5pp additional reduction on the specific standards listed above. The prompt fix (Patch 1) and the tournament (Patch 2) are multiplicative, not additive — they operate at different stages of the pipeline.

---

## Test plan

**Before merging:**

- [ ] Regenerate a sample of 30 Grade 5 MCQ items on the same passages used in the original audit. Manually apply the passage-blind test to each (can a student eliminate this wrong option without reading the passage?). Target: <20% leak on this spot check.
- [ ] Confirm the N matrix change in `config.py` is live by checking generation logs — you should see 3 candidates generated and scored for each MCQ/MSQ item.
- [ ] Confirm no regression on fill-in items — N=1 for fill-in must remain unchanged.

**After merging (within 1 week):**

- [ ] Run 100 new Grade 5 MCQ items through the pipeline. Apply the passage-blind grader (Method 4) to all 100.
- [ ] Compare leak rate to the 62.7% baseline. Accept if ≤ 20%. Flag for further investigation if > 25%.
- [ ] Run 50 new Grade 5 MSQ items. Compare to the 51.0% baseline. Accept if ≤ 18%.
- [ ] Spot-check RL.5.6 and RI.5.6 items specifically — these were the hardest-to-fix standards in the original audit.

**Regression check:**

- [ ] Confirm Grade 6 MCQ leak rate has not moved (N=3 was already in place there — this PR should not touch Grade 6 behavior).
- [ ] Run the full InceptBench eval suite. No regressions expected since no schema, model, or evaluation metric changes are included.

**Future gate:** If a batch of 3,000+ Grade 5 evals confirms leak rate below 5%, N can be dialed back to N=2 to reduce inference cost. That is a separate PR.

---

## Files changed

- `src/edullm/grades/grade_5/prompts.py` — insert ~60 lines into `SYSTEM_PROMPT` string (no structural changes)
- `src/edullm/generation/config.py` — 3-line change in `N_CANDIDATES_MATRIX` (Grade 5 rows only)
- `src/edullm/grades/grade_5/overrides.py` — add 5 `STANDARD_GUIDANCE` entries + 3 `COMBO_OVERRIDES` entries

No schema changes. No new imports. No model changes. All changes are prompt text and one integer matrix edit.

---

## Notes for reviewer (Stan)

The 1,154 Grade 5 evals underlying the original N=1 decision did not surface the passage-blind failure mode because InceptBench does not measure passage-necessity — items were scoring well on the 12 automated metrics while shipping uneliminable distractors. The N=3 call is the right correction given the identified quality gap; it matches what is already running for Grade 6 without incident.

The `RI.5.6` entry in `overrides.py` is a replacement of the existing entry (not an addition) — the PR diff will show a delete + insert for that key. All other entries are net-new additions.
