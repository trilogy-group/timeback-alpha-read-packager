# Grade-5 Reading — Forensic Handoff for Abdul

**Date:** 2026-06-23  
**Gate owner:** Stan Huseletov (stanislav.huseletov@trilogy.com)  
**Generator owner:** Abdul  
**Corpus audited:** 8,937 pass items (adapted from `adapt_abdul.py` output at `/tmp/abdul_adapted_all.jsonl`)

---

## HEADLINE

| Metric | Number |
|--------|--------|
| Total items in pass set | 8,937 |
| Estimated usable NOW (pass gate, passage-dependent) | 4,598 |
| Estimated needs regeneration or fix | 4,339 |
| L.5 vocabulary items (entire MAP slice) | 0 |
| RF.5 oral-reading items (quarantine) | 1,557 |

The good news: EBSR is nearly watertight (98.3% usable, 1,449 items). Hot-text is better than expected (82.5% passage-dependent, 1,220 items). The bad news: MCQ/MSQ leak at 62.7%/51.0% due to three fixable structural patterns in your prompt. The structural gap: 0 L.5 vocabulary items exist — the MAP blueprint requires ~2,435.

---

## USABLE NOW

Items that pass the anti-leak gate as-is, with no regeneration required.

| Format | Total in corpus | Usable | Usable % | Condition |
|--------|----------------|--------|----------|-----------|
| EBSR | 1,475 | 1,449 | 98.3% | Part B options must be verbatim passage quotes avg >50 chars — the format is doing the security work. ~25 fully-leaked items need review (camouflage-type common-word stems with short Part B quotes). |
| Hot-text (RL/RI) | ~1,200 | 1,179 | 98.4% | RL/RI hot-text items are nearly watertight. Use as-is. |
| Hot-text (RF.5.3/RF.5.4.C) | 279 | 41 | ~15% | RF.5.3 morphology items apply rules, not passage content — they work as decoding items but are not comprehension items. RF.5.4.C context-clue items for common words (dormant, adversity) leak via general vocabulary knowledge. |
| Sequence (RL fiction) | ~400 | 400 | ~100% | Character-specific fictional narrative event sequences (Liam, Clara, Ryan, Julian) are nearly always passage-dependent. Keep all of these. |
| Sequence (all other) | 1,111 | 280 | ~25% | Natural process sequences (water cycle, fossil, honey) and reading-strategy metacognitive sequences are recoverable without passage. See REGENERATION REQUIRED. |
| MCQ (non-leaky) | ~1,600 | ~593 | ~37% | Items that avoid LONGEST_OPTION, ABSOLUTE_LANGUAGE, and TOPIC_GENERAL patterns. |
| MSQ (non-leaky) | ~1,315 | ~644 | ~49% | Items that avoid ABSOLUTE_LANGUAGE and WORLD_KNOWLEDGE_KEY patterns. |

**Total estimated usable now: ~4,598 items**

---

## REGENERATION REQUIRED

Items that fail the gate due to structural defects. Listed in priority order.

### 1. MCQ distractor leakage — ~1,007 items need regeneration

**Leak rate: 62.7% of 1,600 MCQ items = ~1,007 items**

Three patterns account for nearly all leakage:

| Pattern | % of MCQ | Count to fix | Description |
|---------|----------|-------------|-------------|
| LONGEST_OPTION | 28% | ~448 | Correct answer is the longest option — test-savvy students pick longest |
| ABSOLUTE_LANGUAGE | 27.3% | ~437 | Wrong options use "all", "never", "completely", "made illegal", etc. — trivially eliminatable |
| TOPIC_GENERAL | 22% | ~352 | Main-idea questions include a generic "could be any passage on this topic" wrong option |

These patterns overlap, so total distinct leaky MCQ items ≈ 1,007.

### 2. MSQ distractor leakage — ~668 items need regeneration

**Leak rate: 51.0% of 1,315 MSQ items = ~668 items**

| Pattern | % of MSQ | Count to fix | Description |
|---------|----------|-------------|-------------|
| ABSOLUTE_LANGUAGE | 34% | ~447 | Dominant MSQ failure — "forced ALL", "completely illegal", "stopped ALTOGETHER" |
| WORLD_KNOWLEDGE_KEY | 25% | ~329 | Correct answers use well-known science mechanisms; wrong options don't — solvable without passage |
| TOPIC_GENERAL | 8% | ~105 | Generic main-idea wrong options |

### 3. Sequence items — ~831 items need regeneration

55% of sequence items (831 of 1,511) are recoverable without passage reading:
- World-knowledge natural processes: 428 items (honey, fossils, water cycle, geology, volcanic rock, geyser, hydrothermal vents, river meanders, tsunami/earthquake)
- Causal/logical ordering: 403 items (reading-strategy metacognitive procedures, argument structure, universal narrative arc)

**Replace with:** character-specific fictional narrative event sequences (RL.5.1/5.2/5.3 items tied to named characters in specific stories) — these are near-100% passage-dependent.

### 4. RF.5 oral-reading items — 1,557 items quarantined from MAP delivery

These are oral-reading/fluency items (RF.5.3.A, RF.5.4.A/B/C). They cannot be assessed via silent digital reading tasks and contribute 0% to MAP comprehension blueprint.

**Action:**
- Audit RF.5.4.A/B/C hot-text items (~72 in RF.5.4.A) — if stem requires passage-level meaning, re-tag to RL.5.4
- Retire or hold in fluency-only track outside MAP blueprint pool
- Do NOT include in MAP-facing delivery without re-tagging audit

---

## GENERATOR FIX GUIDE

These are exact prompt additions to paste into your Gemini generator system prompt. Copy them verbatim.

---

**ABSOLUTE_LANGUAGE FIX:**

> Never use absolute language (all, none, never, always, completely, entirely, the only, every, exclusively, totally, solely, banned, made illegal) in any wrong answer option. Absolute claims are trivially eliminatable because readers know real-world phenomena are rarely absolute. Each wrong option must describe something that could plausibly be partially true or true in a different context.

---

**LONGEST_OPTION FIX:**

> Keep all four answer options within 15% of the same character length. The correct answer must NOT be the longest option. Before finalizing, check: is the correct answer noticeably longer than the wrong options? If yes, trim it or lengthen the wrong options to match. Wrong options must be substantively complete sentences, not truncated fragments.

---

**TOPIC_GENERAL FIX:**

> For main-idea and central-idea questions, do NOT include a wrong option that is a broad true generalization about the topic domain (e.g., "Many ocean animals have developed unique survival strategies."). Such generic options are immediately recognizable as wrong because they could be the main idea of ANY passage on that topic. Instead, every wrong option must name a specific but incorrect main idea — one that plausibly could have been the main point of THIS specific passage but was not.

---

**WORLD_KNOWLEDGE_KEY FIX:**

> Wrong answer options must ALSO sound scientifically plausible to someone with general domain knowledge. Do not make the correct answer the ONLY option that aligns with what a 5th grader already knows about the topic. Specifically: if the correct answer states a well-known scientific mechanism (e.g., molecules pack closer together), then at least two wrong options must ALSO invoke plausible scientific mechanisms — just the wrong ones for this specific passage. The discrimination must come from passage-specific detail, not general science literacy.

---

**PAIRED WRONG OPTIONS FIX:**

> After generating your four options, do a pairwise check: are any two wrong options logical contradictions of each other (e.g., one says increases and another says decreases)? If so, replace one. When two wrong options contradict each other, a student can eliminate both and is left with only one wrong option and the correct one — effectively turning a 4-choice MCQ into a 50/50.

---

**PASSAGE-SPECIFIC ANCHORING FIX:**

> Every wrong option must require reading the passage to confidently eliminate. Ask yourself: could a smart 5th grader who has NOT read this passage cross off this wrong option using only (a) world knowledge or (b) recognizing it as an absolute claim? If yes, replace it with a distractor that references a genuine misreading of the passage — something that sounds like it came from the passage but subtly distorts a key detail (wrong cause, wrong effect, reversed relationship, or correct detail applied to the wrong part of the text).

---

## MISSING ITEMS TO GENERATE

This is the most critical structural gap. The entire L.5 vocabulary strand is absent.

### L.5 Vocabulary — 0 items exist, ~2,435 needed

MAP blueprint requires approximately 33% of non-RF items to be L.5 vocabulary. Current state:

| Standard | Items | Target | Gap |
|----------|-------|--------|-----|
| L.5.4 (context clues, word relationships) | 0 | ~810 | -810 |
| L.5.5 (figurative language, word relationships) | 0 | ~810 | -810 |
| L.5.6 (academic vocabulary, domain words) | 0 | ~815 | -815 |
| **Total L.5** | **0** | **~2,435** | **-2,435** |

**Before generating all 2,435 from scratch:** Audit existing RI.5.4 and RL.5.4 items — those with vocabulary-in-context stems may qualify for dual-tag or re-tag to L.5.4/L.5.5. This could reduce net new generation to ~1,800 items.

**Generation note:** RI.5 and RL.5 are already well-covered (373–404 items per substandard, no sparse standards). Do NOT generate more RI.5/RL.5 items until L.5 is built — both strands are already over-indexed vs MAP targets precisely because L.5 is absent.

### KCT0_FLUENCY — 377 items to prune (low priority)

377 oral-reading fluency items (KCT0_FLUENCY) tagged with oral-reading-expression, oral-reading-fluency-expression, etc. These add no comprehension value to this course. They overlap with the RF.5 quarantine action above. Prune or move to fluency-only track.

---

## KCT REQUIREMENT

Required KCT distribution vs current state:

| KCT | Skill Cluster | Current Count | Current % | Target % | Status |
|-----|--------------|--------------|-----------|----------|--------|
| KCT1 | Literal comprehension / main ideas | 836 | 9.4% | ~10% | OK |
| KCT2 | Vocabulary / figurative language | 1,537 | 17.2% | ~15-20% | OK |
| KCT3 | Text structure / compare-contrast | 2,584 | 28.9% | 25% minimum | MEETS TARGET |
| KCT4 | Author's purpose / point of view | 2,217 | 24.8% | ~20-25% | OK |
| KCT5 | Theme / inference | 1,386 | 15.5% | ~15% | OK |
| KCT0_FLUENCY | Oral reading (no MAP value) | 377 | 4.2% | 0% (prune) | PRUNE |

KCT3 (Text Structure) at 28.9% meets the 25% minimum target. KCT distribution is healthy once fluency items are pruned. When you add L.5 vocabulary items, tag them KCT2 (vocabulary/figurative language) — this will bring KCT2 to roughly 20–22%, which remains within target.

Top KCT strings by bucket (use these when tagging new items):
- KCT1: `informational-text-comprehension`, `determine-multiple-main-ideas-and-details`
- KCT2: `context-clues-self-correction`, `figurative-language-metaphor`, `context-clues-vocabulary`
- KCT3: `text-structure-comparison`, `compare-contrast-themes-genre`, `point-of-view-comparison`
- KCT4: `point-of-view-influence`, `visual-elements-tone-meaning`, `reading-comprehension-purpose`
- KCT5: `theme-character-response`, `drawing-inferences-literature`, `drawing-inferences-informational`

---

## CCSS COVERAGE GAPS

| Standard | Count | Status |
|----------|-------|--------|
| RI.5.1–RI.5.10 | 379–404 each | Covered, do not add more yet |
| RL.5.1–RL.5.9 | 373–399 each | Covered, do not add more yet |
| **L.5.4** | **0** | CRITICAL GAP |
| **L.5.5** | **0** | CRITICAL GAP |
| **L.5.6** | **0** | CRITICAL GAP |
| RF.5 (all) | 1,557 | Quarantine from MAP delivery |

**RL.5.8 note:** RL.5.8 does not exist in CCSS (it is RI-only). The audit confirmed zero mislabeled items — this is correct.

**MAP balance impact of L.5 absence:** With L.5 at 0%, RI.5 and RL.5 crowd to 52.5%/47.5% of non-RF items vs MAP targets of 32%/35%. No pruning of RI/RL is needed — adding ~2,435 L.5 items grows the denominator and self-corrects the ratio to approximately RL.5 35% / RI.5 32% / L.5 33%.

---

## REAL GATE NUMBERS (run on 8,937 items, 2026-06-23)

These are the actual structural gate results on your full pass set.

| Type | Structural Pass | Total | Pass Rate | Notes |
|------|----------------|-------|-----------|-------|
| hot-text | 1,479 | 1,479 | **100%** | No structural defects |
| sequence | 1,511 | 1,511 | **100%** | No structural defects |
| msq | 1,319 | 1,480 | **89%** | Absolute language + world-knowledge-key |
| ebsr | 1,316 | 1,475 | **89%** | Quote format on Part B options |
| mcq | 961 | 1,473 | **65%** | Longest-option + absolute language + topic-general |
| match | 0 | 1,519 | **0%** | EVERY item missing decoy bucket (see fix below) |
| **Total** | **6,586** | **8,937** | **73.7%** | |

### Match: decoy bucket requirement

Every match item needs at least 1 unused right-side category (a "decoy bucket"). Right now all match items are clean 1:1 mappings — a student can match by elimination without reading. Fix: add one extra right-side category that is plausible but does not map to any item. This is the only match fix needed; it will flip 0% → ~100% structural pass rate.

---

## HOW TO RUN OUR GATE

Both scripts live at `/Users/stanhus/Documents/grade3-reading/artifacts/alpha-read-packager/generator/g5/`.

### Fastest path: certify_pipeline.py (one command)

```bash
python3 certify_pipeline.py <your_output.jsonl> ./gate2_output/
```

This runs the full Gate 2 pipeline end-to-end:
1. Adapts your JSONL to grader format
2. Runs all structural checks
3. Writes three output files:
   - `gate2_output/structural_pass.jsonl` — items ready for passage-blind LLM check
   - `gate2_output/structural_fail.jsonl` — items with structural defects + reasons
   - `gate2_output/gate_report.json` — statistics per type
4. Prints a human-readable summary

**Submit `structural_pass.jsonl` to Stan for passage-blind certification.**

### Manual path (if you want step-by-step visibility)

#### Step 1 — Adapt your output to gate format

```bash
python3 adapt_abdul.py <your_output.jsonl> /tmp/adapted.jsonl
```

Input: your grade5-reading-v2 schema JSONL (one item-wrapper record per line).  
Output: flat JSONL with fields: `id`, `type`, `stem`, `options`, `key`, `feedback`, `ccss`.

#### Step 2 — Run the anti-leak gate

```bash
# Convert JSONL to JSON (grader expects a JSON list)
python3 -c "
import json, sys
items = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
json.dump(items, open(sys.argv[2], 'w'))
" /tmp/adapted.jsonl /tmp/adapted.json

python3 anti_leak_grader.py /tmp/adapted.json
```

The grader runs all deterministic structural checks (no LLM, no network). For passage-blind solvability it emits the exact LLM-grade prompt per item and marks those `NEEDS_LLM_GRADE` — a run containing those items is not fully green.

#### Step 3 — Interpret results

- `PASS` — item clears all deterministic checks → goes to `structural_pass.jsonl`
- `FAIL` — item has a structural defect (check the reason field) → goes to `structural_fail.jsonl`
- `NEEDS_LLM_GRADE` — deterministic checks passed; passage-blind solvability requires LLM judgment; Stan runs this step independently

**A submission is ready for certification when:** zero `FAIL` items and Stan has completed the `NEEDS_LLM_GRADE` pass.

### Passage-blind check (Stan's step, after you submit)

Stan runs the passage-blind LLM check on your `structural_pass.jsonl` using a cross-family model (generator = Gemini → grader = Claude, or vice versa). To see the exact prompts the grader will emit:

```bash
# Run without --no-llm-prompt flag to see passage-blind prompts
python3 anti_leak_grader.py /tmp/adapted.json
```

Each item that passes structural checks gets an exact prompt printed that Stan (or a cross-family LLM) uses to adjudicate passage-blind solvability.

### Important: selector-family != grader-family invariant

Generator and grader must be from different model families (e.g., generator = Gemini, grader = Claude). This is non-negotiable. A model grading its own output cannot produce an auditable passage-blind verdict.

---

## THE CONTRACT

**Abdul generates. Stan certifies.**

Abdul's job: produce items that pass `anti_leak_grader.py` with zero `FAIL` results (after applying the generator prompt fixes above). Submit batches via the adapted JSONL format.

Stan's job: run the independent cross-family passage-blind LLM gate on all `NEEDS_LLM_GRADE` items, log provenance, and issue PASS/FAIL certification. Stan does not edit items — only certifies or rejects with specific failure reasons.

**Done = items pass Stan's gate.** Not "done = items pass IB scoring" and not "done = items look good to me." The gate is the shared acceptance criterion, written into the bake-off rubric.

**Fail-set note:** 3,228 items are currently in the fail set. The forensic analysis estimates ~2,087 of these are salvageable — 64.7% failed on style (difficulty-alignment mismatch or IB 0.84 threshold) with no structural defects, not on passage dependency. Specifically, ~714 items failed only because the IB overall score was 0.84 (INFERIOR threshold) with no individual metric below 0.8 and Opus=PASS. These may need no fix at all — just a threshold review. Stan will flag these for a separate review pass rather than requiring regeneration.

---

## HONEST GAPS

Things that are blocked externally and cannot be resolved by Abdul or Stan acting alone:

1. **L.5 vocabulary items require real passages.** The ~2,435 missing L.5 items need vocabulary-in-context stems, which means real grade-5 passages tagged to L.5.4/5.5/5.6. If your generator creates items against synthetic passages, confirm those passages are grade-5 Lexile (830–1010L) before submission.

2. **MAP pilot is 0/313 for this cohort.** No in-cohort MAP score data exists yet. All "MAP alignment" claims are based on blueprint matching, not empirical difficulty data. The gate certifies structural quality and passage-dependency, not psychometric validity.

3. **RF.5 re-tagging audit is un-done.** Before quarantining all 1,557 RF.5 items, someone needs to audit ~72 RF.5.4.A hot-text items for re-tag eligibility to RL.5.4. This is a Stan task, not Abdul.

4. **IB threshold policy.** The ~714 items that fail only on IB 0.84 threshold with Opus=PASS need a policy decision (lower threshold, or manual review) — this is a Becky/Anuj call, not something Abdul or Stan can unilaterally resolve.

5. **Sequence item replacement requires passage-specific content.** Replacing 831 leaky sequence items with character-specific fictional narrative sequences requires knowing which characters and stories are in the corpus. Abdul needs the passage list to generate these correctly.

---

## QUICK-REFERENCE NUMBERS

| Item | Count |
|------|-------|
| Total pass items | 8,937 |
| Estimated usable now | 4,598 |
| Needs regeneration (MCQ/MSQ leaky) | ~1,675 |
| Needs regeneration (sequence leaky) | ~831 |
| RF.5 quarantine (not comprehension) | 1,557 |
| L.5 vocabulary items needed | ~2,435 |
| Fail-set estimated salvageable | ~2,087 |
| EBSR usability rate | 98.3% |
| Hot-text RL/RI usability rate | 98.4% |
| MCQ leak rate (current prompt) | 62.7% |
| MSQ leak rate (current prompt) | 51.0% |
| Sequence leak rate | 55.0% |
