# Standards Coverage Matrix — G5 Reading Course (V2 Skeleton)

**What this is.** The single source of truth for which CCSS standard is covered by which format in the V2 skeleton, how many items are in the current pool, how many are usable (pass both the structural gate and the passage-blind gate), and what gap remains before the course can ship.

**Version:** V2 skeleton (2026-06-24 redesign). MCQ and MSQ are NOT in the V2 skeleton as primary formats — see "Why MCQ/MSQ are absent" below. L.5 vocab MCQ is the only MCQ-format component retained.

**Pool counts source:** 200-item passage-blind audit (2026-06-23). Usable = structural-pass AND estimated passage-dependent at >= 80% confidence.

**Honesty floor:** Any cell marked [TO-SOURCE] has not been measured; the number is a projection or placeholder. No cell is silently invented.

---

## Why MCQ and MSQ are Absent from the V2 Skeleton

MCQ: 99.5% leak rate on Abdul's corpus (199/200 blind-solved). Root cause: encyclopedic passages on curriculum facts. Even after the GENERATOR_REPAIR_KIT.md distractor fixes, passage-level failure means the items are unanswerable without the passage only at structural detail — but the actual answer can be recovered from world knowledge.

MSQ: 100% leak rate (1,346/1,346 structural-pass items unusable). Same root cause plus the additional structural vulnerability that each option is evaluated independently (see MSQ_REGEN_GUIDE.md).

Decision (2026-06-24): V2 skeleton uses hot-text / sequence / match / EBSR as primary formats. MCQ regeneration is possible once Abdul ships a new generator with the PASSAGE_DESIGN_RULES.md passage strategy. Until then, MCQ is excluded from the course except for L.5 vocabulary items (context-dependent by design, not encyclopedic).

---

## Format Legend (V2 skeleton)

| Format | Code in skeleton | Notes |
|---|---|---|
| hot-text | HT | Student highlights passage spans; key = correct span(s) |
| sequence | SEQ | Student orders 4-6 steps; key = correct order |
| match | MATCH | Student pairs items from two columns; must include decoy right-column item |
| EBSR | EBSR | Evidence-Based Selected Response (Part A + Part B); easy-band only |
| MCQ (vocab only) | MCQ-V | MCQ for L.5.4/5.5/RI.5.4 vocabulary-in-context; context-dependent by design |

---

## Pool Counts Reference

| Format | Structural-pass pool | Usable (post-blind-gate) | Gate rate |
|---|---|---|---|
| hot-text | ~1,479 | ~1,220 | 82.5% |
| sequence | ~1,511 | ~680 | 45% |
| match | ~1,519 | ~653 | 43% |
| EBSR | ~94 | 89 | 94% (6% fail) |
| L.5 vocab MCQ | 45 | 45 [TO-CONFIRM: blind-solve not yet run] | — |
| MCQ (non-vocab) | ~4,000+ | ~20 (< 0.5%) | DO NOT USE |
| MSQ | ~1,346 | 0 | 0% |
| **Total usable** | | **~2,687** | — |

---

## Standards Coverage Matrix

**V2 skeleton slot totals (541 total slots):**
- Content lesson items: ~300 (distributed across HT/SEQ/MATCH)
- Mastery gate (24-item form × 3-4 parallel forms): 72–96 items
- MAP-equiv (40 items × 2 forms): 80 items
- Spaced review: ~45 items
- Transfer check: ~20 items

---

### Literary Standards (RL.5)

| Standard | Description | V2 Format | Pool (usable) | Skeleton slots | Gap | Notes |
|---|---|---|---|---|---|---|
| **RL.5.1** | Quote accurately from text; draw inferences | HT (key = evidence span) | ~340 | ~55 | 0 — pool sufficient | Evidence-span hot-text maps cleanly to "quote to support inference" |
| **RL.5.2** | Determine theme/central message; summarize | HT (key = theme-statement span) | ~180 | ~40 | 0 — pool sufficient | Theme items: stem asks which span states theme; strong passage-design dependency |
| **RL.5.3** | Compare/contrast characters, settings, events | MATCH (character→trait or event→consequence) | ~120 | ~30 | 0 — pool sufficient | Match format: passage-specific trait pairs; decoy right column required |
| **RL.5.4** | Determine meaning of words/phrases, figurative language | MCQ-V (vocab-in-context MCQ) | 20 of 45 total MCQ-V [TO-CONFIRM split] | ~20 | 0 if MCQ-V confirmed | Figurative language tested in MCQ-V only; HT for in-text phrase identification |
| **RL.5.5** | Explain how chapters/scenes/stanzas fit together | SEQ (story structure: exposition→complication→climax→resolution) | ~160 | ~25 | 0 — pool sufficient | Sequence must be story-stage ordered; non-identity storage check required |
| **RL.5.6** | Describe narrator/speaker point of view | HT (key = POV-indicator span) | ~90 | ~20 | 0 — pool sufficient | Stem: "Which phrase shows how the narrator feels about X?" |
| **RL.5.7** | Analyze how visual/multimedia elements contribute | NOT IN V2 SKELETON | — | 0 | KNOWN GAP — no visual/multimedia in machine-authored cold passages | Acceptable gap: MAP G5 literary weighting does not require RL.5.7 heavily at Grade 5; flag for real-passage tier |
| **RL.5.8** | N/A at Grade 5 (not assessed by CCSS at this level) | — | — | — | Not applicable | RL.5.8 is not a Grade-5 standard |
| **RL.5.9** | Compare/contrast themes, topics, POV across two texts | MATCH (two-text pairing) | ~80 | ~15 | 0 — pool sufficient | Two-text match: passage A claim → passage B stance; cross-text comparison |

---

### Informational Standards (RI.5)

| Standard | Description | V2 Format | Pool (usable) | Skeleton slots | Gap | Notes |
|---|---|---|---|---|---|---|
| **RI.5.1** | Quote accurately; explain explicit/inferential conclusions | HT (evidence-span selection) | ~340 (shared with RL.5.1 pool) | ~55 | 0 — pool sufficient | Same hot-text format; passage differs (nonfiction). Standard tagging distinguishes literary vs info. |
| **RI.5.2** | Determine main idea; explain supporting details; summarize | HT (key = main-idea span) | ~180 (shared with RL.5.2 pool) | ~40 | 0 — pool sufficient | Wrong-span distractors must be promoted-detail spans, not generic topic sentences |
| **RI.5.3** | Explain relationships between events/concepts/procedures | SEQ (cause-effect or step sequence) | ~280 | ~35 | 0 — pool sufficient | Nonfiction sequence: causal chain steps ordered; sequence is the assessment of understanding |
| **RI.5.4** | Determine meaning of domain-specific words in context | MCQ-V | 25 of 45 total MCQ-V [TO-CONFIRM split] | ~25 | 0 if MCQ-V confirmed | Domain-specific vocabulary; context-dependent scoring; passage carries definitional evidence |
| **RI.5.5** | Compare/contrast overall structure of two texts | SEQ (text-structure identification) | ~120 | ~20 | 0 — pool sufficient | Sequence maps: "problem → evidence → argument → conclusion" structure ordering |
| **RI.5.6** | Analyze multiple accounts of same event/topic; POV | HT or MATCH | ~90 | ~20 | 0 — pool sufficient | HT for POV-indicator spans; MATCH for two-account perspective pairing |
| **RI.5.7** | Draw on information from multiple print/digital sources | NOT IN V2 SKELETON | — | 0 | KNOWN GAP — cold passages are single-source | Acceptable gap at content-lesson level; flag for MAP-equiv if multi-source needed |
| **RI.5.8** | Explain how author uses reasons and evidence | HT (key = reasoning-structure span) | ~100 | ~20 | 0 — pool sufficient | "Which sentence shows the author's evidence for the claim that X?" |
| **RI.5.9** | Integrate information from multiple texts on same topic | MATCH (two-text claim pairing) | ~80 | ~15 | 0 — pool sufficient | Match: text A claim → matching evidence/contrast in text B |

---

### Language Standards (L.5)

| Standard | Description | V2 Format | Pool (usable) | Skeleton slots | Gap | Notes |
|---|---|---|---|---|---|---|
| **L.5.4** | Use context clues and word analysis to determine meaning | MCQ-V | ~20 [TO-CONFIRM] | ~15 | Possible gap if MCQ-V pool < 15 for this standard | Context-clue items; vocabulary MCQ; word-analysis sub-skills (L.5.4b root/affix) can use MATCH |
| **L.5.4a** | Use context to confirm/clarify meaning | MCQ-V | part of L.5.4 pool | ~8 | See L.5.4 | Subsumed in L.5.4 pool |
| **L.5.4b** | Use common Greek/Latin affixes and roots | MATCH (root→meaning-in-context) | ~30 [TO-CONFIRM: match pool] | ~10 | 0 if match pool confirmed | MATCH format: root/affix → passage-context meaning; decoy right column prevents world-knowledge elimination |
| **L.5.4c** | Consult reference materials (dictionaries, thesauri) | NOT IN V2 SKELETON | — | 0 | NOT ASSESSABLE in cold-passage format | This standard requires reference lookup; out of scope for auto-scored cold items |
| **L.5.5** | Demonstrate understanding of figurative language | MCQ-V | ~10 [TO-CONFIRM] | ~10 | Possible tight gap | Idioms, adages, simile, metaphor in context; MCQ-V only |
| **L.5.5a** | Interpret figurative language, including simile/metaphor | MCQ-V | part of L.5.5 pool | ~5 | See L.5.5 | |
| **L.5.5b** | Recognize and explain the meaning of common idioms, adages, proverbs | MCQ-V or MATCH | part of L.5.5 pool | ~5 | See L.5.5 | MATCH viable: idiom → meaning-in-passage-context |
| **L.5.5c** | Use the relationship between words (synonyms, antonyms, homographs) | MATCH | ~30 of L.5 MATCH pool [TO-CONFIRM] | ~5 | 0 if match pool confirmed | MATCH: word → relationship-type (passage-grounded definitions) |
| **L.5.6** | Acquire and use grade-appropriate vocabulary | MCQ-V | included in MCQ-V pool | ~5 | 0 — pool absorbed | Overlaps with L.5.4; not separately assessed |

---

### Foundational Skills (RF.5)

| Standard | Description | V2 Format | Pool (usable) | Skeleton slots | Gap | Notes |
|---|---|---|---|---|---|---|
| **RF.5.4** | Read grade-level text with accuracy, fluency, and comprehension | NOT ASSESSED in cold-passage auto-scored format | — | 0 | KNOWN INTENTIONAL GAP | RF.5.4 requires oral reading fluency measurement; cannot be auto-scored in the EBSR/HT/MATCH format. Decoding assumed at Grade 5 (G5 skeleton §1 note). Flag for Foundations strand if G5 cohort data shows below-floor readers needing decoding support. |

---

## Summary: Gaps and Actions Required

| Category | Count | Action |
|---|---|---|
| Standards with 0 gap (pool sufficient) | RL.5.1, RL.5.2, RL.5.3, RL.5.5, RL.5.6, RL.5.9, RI.5.1, RI.5.2, RI.5.3, RI.5.5, RI.5.6, RI.5.8, RI.5.9 = 13 standards | No action — assign from existing pool |
| Standards with TO-CONFIRM pool split | RL.5.4, RI.5.4, L.5.4, L.5.4b, L.5.5, L.5.5b, L.5.5c = 7 | Run blind-solve on L.5 vocab MCQ pool; tag items by sub-standard; confirm pool split meets slot counts |
| Standards with known acceptable gaps | RL.5.7, RI.5.7, RF.5.4 = 3 | Document as intentional; flag for real-passage tier (non-machine-authored) and Foundations strand routing |
| Standards not applicable at G5 | RL.5.8 = 1 | Not assessed |
| Standards requiring MCQ regeneration before reintroduction | RL.5.x MCQ / RI.5.x MCQ (non-vocab) = all MCQ-format standards | Only reintroduce after Abdul ships a new passage-strategy generator AND passes the blind-solve gate at < 30% leak rate |

---

## MAP-Equiv Blueprint vs. Standards Coverage

The MAP-equiv 40-item form (Literary 35% / Informational 32% / Vocabulary 33%) maps to standards as follows in V2:

| Domain | Items | Standards covered | Format |
|---|---|---|---|
| Literary (14 items) | 35% | RL.5.1, RL.5.2, RL.5.3, RL.5.5, RL.5.6, RL.5.9 | HT (6), SEQ (3), MATCH (3), EBSR (2) |
| Informational (13 items) | 32% | RI.5.1, RI.5.2, RI.5.3, RI.5.5, RI.5.6, RI.5.8, RI.5.9 | HT (5), SEQ (4), MATCH (3), EBSR (1) |
| Vocabulary (13 items) | 33% | L.5.4, L.5.5, RI.5.4, RL.5.4 | MCQ-V (13) |

**Honest note:** Standard MAP assessments use MCQ-heavy formats. G5 V2 MAP-equiv uses HT/SEQ/MATCH/EBSR for literary and informational items. Cognitive demands are equivalent (finding evidence, ordering events, matching cause-effect), but the format differs. This is noted explicitly in all assembly reports and should be disclosed to any stakeholder who asks about MAP comparability.

---

## What "Done" Looks Like per Standard

A standard is "done" when:
1. Pool has enough usable items (post-blind-gate) to fill skeleton slots for that standard across all components (content + gate + MAP-equiv + spaced review).
2. Items are tagged with the correct G5 CCSS code (RL.5.x / RI.5.x / L.5.x — not G3 codes).
3. Passage-design rules P1-P8 are documented in `why_clean.blind_solve_fails_because` field of each item.
4. L.5 vocab MCQ pool blind-solve is run and results logged.
5. TO-CONFIRM pool splits are resolved (counts by sub-standard confirmed).

**Current "done" count:** 13 of 21 assessed standards have confirmed sufficient pools.
**Remaining TO-CONFIRM:** 7 standards pending L.5 MCQ-V blind-solve and sub-standard tagging.
**Known gaps:** 3 standards (RL.5.7, RI.5.7, RF.5.4) intentionally deferred to real-passage tier.

---

*V2 skeleton — 2026-06-24. Pool counts from 200-item blind-solve audit (2026-06-23). All TO-CONFIRM cells must be resolved before course certify_pipeline.py can run green. Do not invent numbers for TO-CONFIRM cells — source them from the actual pool tagging run.*
