# MSQ Regeneration Guide — Grade 5 Reading

**Status:** MSQ pool is 100% leaked (0 of 1,346 structural-pass items usable). Full regeneration required using the rules and system prompt additions below.

---

## Why MSQ is Harder to Fix Than MCQ

MCQ fails when the correct answer is recoverable from world knowledge. MSQ fails for that reason AND three additional structural reasons:

**Reason 1: Options are evaluated independently.**
In MCQ a student must pick the best single answer. In MSQ each option is judged true/false independently. This means a student evaluating option A does not need the passage to eliminate options B, C, D, or E — they just need to decide whether option A is true in the world. Because any given option is either a known fact or a known non-fact, world knowledge reaches further.

**Reason 2: Partial credit from partial knowledge.**
If a student knows one of the two correct answers from school (say, that salmon swim upstream to spawn), they have a 50% chance of recovering the full key by guessing the second correct answer from the remaining options. MCQ has no analogous shortcut — guessing wrong forfeits the item entirely. MSQ partial-knowledge guessing is a structural leak that passage-independent options make catastrophically worse.

**Reason 3: The elimination path is wider.**
With 5-6 options and 2 correct answers, a student who can eliminate even 2 wrong options using world knowledge (both make absolute claims, or both describe things that are never true) is now choosing 2 from 3 — essentially a coin flip. In Abdul's current corpus, 100% of MSQ items had at least 2 eliminatable-without-the-passage wrong options, which means every item collapsed to a 2-choice selection on a passage-blind basis.

**Why MCQ partial fixes do not transfer to MSQ:**
The option-quality rules from GENERATOR_REPAIR_KIT.md (no absolute language, no generic topic truths, length parity) are necessary but not sufficient for MSQ. Even after those fixes, if any individual option describes a general true/false claim about the topic, a student can make that judgment independently. The passage must be the ONLY arbitrator of each option's truth value — and that requires each option to reference a specific, passage-bound detail, not a verifiable claim about the world.

---

## What Makes MSQ Passage-Dependent

Each option must satisfy ALL of the following:

**1. Options reference specific passage-bound details, not world-knowledge claims.**
A wrong option that says "Salmon navigate by sensing magnetic fields" is eliminatable — a student either knows that or doesn't, independently of the passage. A wrong option that says "The biologist in the passage concluded salmon navigate primarily by magnetic cues after the 1998 radio-tagging study" can only be evaluated by reading whether the passage says that.

**2. Options use passage-specific language and framing, not generic descriptions.**
Good options lift phrasing from the passage and modify one element. A student who reads "The author argues X led to Y" sees the passage's specific causal claim. An option that says "X did not cause Y" is a near-neighbor that requires locating the passage's causal sentence to verify.

**3. Wrong options are plausible misreadings, not known falsehoods.**
Wrong options should describe things that could have been true in a different passage on the same topic, or that are true in the world but not what THIS passage claims. They should attract students who read too fast or misremember a detail — not students who know the wrong option is a known falsehood.

**4. The selection criteria must be evident only from the passage.**
The stem must invoke a passage-specific standard: "Which TWO details does the author use to support the specific claim that..." rather than "Which TWO facts are true about salmon." The first stem forces reading the passage's argumentative structure; the second is a biology trivia game.

**5. Knowing one correct answer must not help you find the other.**
Correct answers must not be thematically paired in a way that signals "these two go together." A student who gets one correct answer should not be able to infer the second from the first using world knowledge or thematic grouping. Each correct answer must be independently grounded in the passage.

---

## Before/After Examples (5 pairs)

### Example 1: Main Idea / Supporting Details

**BEFORE (leaked — 100% of Abdul's current MSQ)**

*Passage summary: Standard description of how monarch butterflies migrate from Canada to Mexico.*

Stem: Which TWO statements describe monarch butterflies?

A. Monarch butterflies travel thousands of miles each year to reach warmer climates.
B. Monarch butterflies are the only insects that migrate long distances.
C. Monarch butterflies navigate using the position of the sun.
D. Monarch butterflies are classified as endangered by most governments.
E. Monarch butterflies spend winters in Mexico.

Key: A, E

Why it leaks: A blind solver who studied butterflies in 4th grade knows both A and E. Options B and D are eliminatable by world knowledge (other insects migrate; butterflies are not universally classified endangered). The passage is not needed.

---

**AFTER (passage-dependent)**

*Passage: Author argues that the monarch decline since the 1990s is attributable specifically to herbicide-resistant crop expansion in the Midwest, not to climate change as previously reported. Uses the Michoacan overwintering count (27.5M in strong year, down from 682M in 1990s).*

Stem: Which TWO pieces of evidence does the author use to argue that crop expansion — not climate change — caused the decline?

A. The decline in overwintering numbers began a decade before climate models showed significant regional warming in the Midwest.
B. Monarch populations have declined globally, including in regions where no herbicide-resistant crops are planted.
C. Milkweed coverage in the Corn Belt dropped 58% between 1999 and 2012, matching the decade of peak herbicide adoption.
D. Scientists who study climate change agree that the monarch populations should be recovering under current temperature trends.
E. The author's own field counts showed zero overwintering clusters at two traditionally occupied sites.

Key: A, C

Why it works: Both correct options cite passage-specific evidence the author presents. Option B is a near-neighbor that sounds like it complicates the argument (it describes a real problem with crop-expansion theories) but is not in the passage. Option D misattributes a position — the passage does not say climate scientists claim recovery. Option E describes a detail that sounds like it would appear in this passage but doesn't. Every option requires checking the passage.

---

### Example 2: Author's Purpose / Argumentative Structure

**BEFORE (leaked)**

*Passage summary: Standard account of how the Panama Canal was built and why it was important for trade.*

Stem: Which TWO statements are TRUE about the Panama Canal?

A. The Panama Canal connects the Atlantic and Pacific Oceans.
B. The canal was built entirely by American workers.
C. The canal shortened trade routes for ships traveling between the coasts.
D. The Panama Canal is still in use today.
E. Building the canal required moving millions of tons of earth.

Key: A, C

Why it leaks: The entire key is textbook knowledge. No student needs the passage.

---

**AFTER (passage-dependent)**

*Passage: From the perspective of a Panamanian historian, arguing that U.S. accounts of the canal's construction systematically undercount the death toll among West Indian workers by using a filing system that reported only "American" worker deaths (meaning white U.S. citizens) and classified Caribbean laborers separately.*

Stem: Which TWO arguments does the author use to challenge the accuracy of official U.S. construction records?

A. The mortality records used a two-category filing system that counted white U.S. citizens separately from Caribbean contract workers, producing a misleadingly low "American" death total.
B. The U.S. government deliberately falsified the records before they were transferred to the Smithsonian Institution.
C. Cross-referencing pension claims and hospital intake logs from Barbadian recruitment offices produces a worker-death estimate nearly four times the official figure.
D. European engineers refused to work alongside Caribbean workers, which led to underreporting in team-level records.
E. The official records have been destroyed by water damage and are no longer verifiable.

Key: A, C

Why it works: Both correct answers cite evidence the author uses (filing system structure; cross-referencing methodology). Option B distorts the claim (the author argues for a records-design flaw, not deliberate falsification). Option D is a plausible historical detail that is not what the passage argues. Option E is directly contradicted by the passage (the records are being cross-referenced, so they exist).

---

### Example 3: Text Structure / Cause-Effect

**BEFORE (leaked)**

*Passage summary: Standard description of how zebra mussels spread through the Great Lakes.*

Stem: Which TWO effects of zebra mussels are described in the passage?

A. Zebra mussels filter large amounts of water.
B. Zebra mussels have eliminated all native fish species.
C. Zebra mussels clog water intake pipes.
D. Zebra mussels were brought to the U.S. deliberately for scientific study.
E. Zebra mussels prefer cold water.

Key: A, C

Why it leaks: A and C are documented facts about zebra mussels that appear in dozens of textbooks. B and D are eliminatable by world knowledge (not all fish are gone; mussels arrived via ballast water, not deliberate import). The passage is decorative.

---

**AFTER (passage-dependent)**

*Passage: Presents a causal chain specific to the passage's argument: zebra mussels filter water → clearer water → more sunlight penetrates → denser aquatic plant growth → native fish nursery habitat crowded out. The passage specifies that step two (water clarity, not the mussels directly) is the operative cause of fish habitat loss — a counter-intuitive structure.*

Stem: According to the passage's causal chain, which TWO links are essential for understanding why the mussels harmed native fish nurseries?

A. The mussels' filtration increased water clarity to depths where sunlight had not previously reached.
B. The mussels directly consumed the eggs of native fish species during the spawning season.
C. The increased plant density at depth created competition that crowded out the low-lying vegetation native fish use as nursery cover.
D. Water treatment plants downstream experienced higher costs because of increased plant debris.
E. The mussels' shells created physical barriers that blocked fish migration routes in shallow water.

Key: A, C

Why it works: The passage's causal chain makes A and C the correct links (clarity → sunlight → plants → habitat loss). Option B describes direct predation — plausible for an invasive mussel story but explicitly not the passage's mechanism. Option D introduces a downstream consequence not in the passage. Option E introduces a physical barrier mechanism that is a near-neighbor to the passage's habitat-crowding mechanism but wrong.

---

### Example 4: Character / Point of View (Literary)

**BEFORE (leaked)**

*Passage summary: Maya Angelou was a famous poet and civil rights activist.*

Stem: Which TWO statements describe Maya Angelou?

A. Maya Angelou was an African American author.
B. Maya Angelou was born in the 19th century.
C. Maya Angelou wrote the poem "I Know Why the Caged Bird Sings."
D. Maya Angelou spoke at a presidential inauguration.
E. Maya Angelou won multiple literary awards.

Key: A, D

Why it leaks: A, C, D, and E are all curriculum-level facts. Option B is a known falsehood. No passage is needed.

---

**AFTER (passage-dependent)**

*Passage (literary): A scene in which a 12-year-old character named Rosa reads a collection of Angelou's poems for the first time at her grandmother's house. The passage focuses on Rosa's specific reaction to the poem "Still I Rise" — she doesn't understand the historical context initially, finds the imagery "too dramatic," and only connects with the poem after her grandmother explains the specific lines about "oil wells pumping in my living room." Rosa's changed response is the passage's pivot.*

Stem: Which TWO details show that Rosa's reaction to the poem changed over the course of the scene?

A. Rosa's initial description of the poem as "too dramatic" contrasts with her decision to re-read it after her grandmother's explanation.
B. Rosa recognized the poem immediately because she had studied Maya Angelou in school the previous year.
C. After her grandmother explained the "oil wells" image, Rosa noticed the poem's repeated phrase — something she had read past the first time.
D. Rosa's grandmother read the poem aloud in a way that helped Rosa hear the rhythm she had missed when she read silently.
E. Rosa borrowed the book to take home, suggesting she wanted to return to poems she had not yet understood.

Key: A, C

Why it works: Both A and C are grounded in specific passage moments (her "too dramatic" response; the re-reading triggered by the oil wells explanation). Option B invents prior knowledge Rosa doesn't have in the passage. Option D describes a grandmother-reads-aloud event that is not in the passage. Option E is a plausible inference for this kind of story but is not in the passage.

---

### Example 5: Vocabulary in Context (L.5 — NOT a valid MSQ use case)

**Note:** MSQ is NOT the correct format for vocabulary items at Grade 5. L.5.4 / L.5.5 / RI.5.4 are MCQ-only in the V2 skeleton. Do not generate MSQ for vocabulary. This example shows a WRONG item type to flag — if you see MSQ vocabulary items in Abdul's output, they are format errors.

**WRONG format (do not generate):**

Stem: Which TWO words in the passage are examples of figurative language?

This is a hot-text or MCQ item at Grade 5, not MSQ.

---

## System Prompt Additions for Abdul's Generator

Paste the block below into your Gemini prompt, immediately after the passage-necessity rules.

---

```
=== MSQ-SPECIFIC GENERATION RULES (NON-NEGOTIABLE) ===

MSQ is the format most vulnerable to passage-leak because each option is evaluated
independently. A student who can answer "is option A true in the world?" without the
passage has already solved half the item. These rules override MCQ rules when
generating MSQ items.

--- MSQ RULE 1: EVERY OPTION MUST BE EVALUABLE ONLY BY READING THE PASSAGE ---

Each option must reference a specific, passage-bound claim:
  - A named character's specific action or stated belief (from THIS passage)
  - A specific piece of evidence the author uses (not "evidence that could appear in
    a passage on this topic")
  - A specific link in the passage's causal chain
  - A specific comparison the passage draws using criteria it defines

BANNED option constructions:
  - "X is true of [topic]" → a world-knowledge verdict, not a passage verdict
  - "The passage describes [general fact about topic]" → the general fact is already
    known; evaluating it doesn't require reading
  - "[Famous person] was known for [well-documented achievement]" → curriculum knowledge

--- MSQ RULE 2: STEM MUST INVOKE A PASSAGE-SPECIFIC SELECTION CRITERION ---

The stem must name a standard ONLY visible in the passage:
  GOOD: "Which TWO pieces of evidence does the author use to support the specific
        claim that crop expansion — not climate change — caused the decline?"
  GOOD: "Which TWO events in the passage directly cause the water clarity increase?"
  GOOD: "Which TWO details show that the character's opinion changed?"

  BAD: "Which TWO facts about [topic] are described in the passage?"
  BAD: "Which TWO statements are TRUE about [topic]?"

"Which TWO facts are true" is always passage-independent because facts are true or false
in the world, not just in one passage.

--- MSQ RULE 3: EACH CORRECT ANSWER MUST BE INDEPENDENTLY GROUNDED ---

Do not design correct answers that are thematically paired in a way a student can
infer from world knowledge. Test this: if a student picks correct answer A because
it sounds right, can they infer that correct answer B must also be right? If yes,
the pair is leaking the key.

Each correct answer should be independently verifiable ONLY by locating a specific
passage sentence.

--- MSQ RULE 4: WRONG OPTIONS MUST BE NEAR-NEIGHBORS, NOT KNOWN FALSEHOODS ---

Every wrong option must describe something that:
  (a) could plausibly have been in this passage but is not, OR
  (b) is true in the world but is NOT what this passage argues/describes

NEVER use a wrong option that is:
  - A known falsehood a 5th grader would recognize immediately
  - An absolute claim (see DISTRACTOR QUALITY RULE 1)
  - A paraphrase of a correct answer with a single word changed to a wrong word

--- MSQ RULE 5: THE "BLIND FLIP" TEST ---

Before finalizing any MSQ item:
  1. Simulate a student who has NOT read the passage.
  2. For each option, ask: can this student decide whether this option is "probably
     true" or "probably false" using only general knowledge about the topic?
  3. If >= 2 options can be resolved this way, the item is leaked — rewrite.
  4. The only acceptable resolution for every option is "I'd need to read the passage
     to be sure."

--- MSQ RULE 6: MINIMUM VIABLE OPTION STRUCTURE ---

A Grade-5 MSQ must have:
  - 5 or 6 options total
  - Exactly 2 correct answers (the keyed set)
  - At least 3 wrong options
  - NO option that is the logical complement of another option (contradictory pair)
  - All options within 20% of the same character length

=== END MSQ-SPECIFIC GENERATION RULES ===
```

---

## Checkpoint: Is Your MSQ Item Passage-Dependent?

Run this 3-question test before accepting any MSQ item:

**Q1:** Strip the passage. Give a smart 5th grader only the stem + options. Can they pick the correct TWO options with confidence above chance?
- If YES at >= 60% confidence → reject and rewrite the passage or options.

**Q2:** For each wrong option: what specific passage sentence would a student need to read to reject it?
- If you cannot name a specific sentence → the wrong option is not a near-neighbor, it is a known falsehood. Replace it.

**Q3:** Does the stem name a selection criterion that is visible ONLY in this passage?
- If the criterion is "which are true facts about X" → replace the stem.

All three questions must pass before the item is submitted.

---

*MSQ pool audit finding: 0 of 1,346 structural-pass items survived the passage-blind gate (100% leak rate). Root cause: all options describe verifiable world-knowledge claims rather than passage-specific details. The passage was not required to evaluate any option. These rules directly address that failure mode.*
