# G5 GENERATOR — Anti-Leak Grade-5 Reading Item Harness

A reusable, prompt-only harness for generating passage-dependent **Grade-5** reading items
that survive an independent, passage-blind leakage audit. It is the G5-parameterized port of
the G3 harness (`../GENERATOR.md`), retargeted to the Grade-5 course spec
(`../../GRADE5_COURSE_SPEC.md`).

It emulates the aptraining fine-tune goal (kb-0063) **by prompting**, with **no weight
training** and **no dependency on the blocked macmini grader** — and it is written so Abdul
can carry the *same* generator/grader/accepted-item structure from prompting into fine-tuning
(see (d)) without re-deriving the contract.

The harness has three parts: a **GENERATOR POLICY** prompt, a **GRADER** prompt, and the
**loop architecture** that wires them together. A fine-tuning mapping and an honesty section
follow.

**What changed from G3 → G5 (read this first):**
- **Lexile band** ~830–1010L (denser, longer sentences, more subordinate clauses than G3's
  ~520–820L). Passages run **~120–160 words** (G3 ran ~90–140; G5 carries more text load, but
  respect `edullm-ela`'s ~140-word soft cap by keeping the *median* near 140 and reserving
  150–160 for the hard band only).
- **Standards** are RL.5.x / RI.5.x / L.5.x (NOT RI.3.x). Mapping table in (a) rule 8.
- **Passages are COLD and machine-authored.** Mark `passage_source="machine-authored-cold"`,
  `humanApproved:false`. No real-provenance claim until real G5 passages land (see (e)).
- **Format constraints (from the team's `DESIGN.md`):** **EBSR only at the easy band** (no
  EBSR template above ~560L); **no drag-to-order template → use `match`** instead of `order`;
  **vocab is MCQ-only**.
- **Difficulty/format mix** follows the team's G3/G4 MAP-like blueprint, ported to G5
  (see (a) rule 9 and the MAP-equiv row in (c)).

---

## (a) GENERATOR POLICY PROMPT — the anti-leak generation prompt (G5)

> **Role.** You write **Grade-5** reading-comprehension items that a student CANNOT answer
> correctly without reading the supplied passage. Your only success condition is:
> *a smart reader who has NOT seen the passage must fail to recover full credit from
> general knowledge, distractor surface cues, or the structure of the options.*
>
> **Inputs.** One **cold, machine-authored** passage (~120–160 words, Grade-5 Lexile band
> ~830–1010L); a target skill (e.g. compare-contrast, cause-effect, theme/main-idea,
> inference, author's-purpose, figurative-language/vocabulary-in-context); a target item type
> (`mcq` | `msq` | `ebsr` | `hot-text` | `match`); the CCSS code to tag (RL.5.x / RI.5.x /
> L.5.x); a target difficulty (`easy` | `medium` | `hard`).
>
> **Hard rules (every item must satisfy ALL):**
> 1. **Passage-locked key.** The keyed answer must be fixed by a *passage-specific* fact that
>    a grade-5 reader cannot recover from world knowledge. At G5, prefer keys that hinge on a
>    **relationship the passage asserts** (a cause the text names, a contrast the text draws,
>    an inference the text licenses) rather than a lone retrievable noun — denser passages
>    make relational keys both natural and harder to leak.
> 2. **Verbatim grounding.** The key must be defensible from the passage text. Quote the
>    supporting sentence(s) in your rationale. For inference/theme items, quote the two-or-more
>    sentences whose combination licenses the inference (no single-sentence lift).
> 3. **Near-neighbour distractors.** Distractors are built from *real passage details*, with
>    the wrong actor / stage / effect / cause / claim swapped in. No distractor may be absurd
>    or eliminable by world knowledge alone. (Absurd distractors leak the key by elimination.)
>    At G5, a near-neighbour distractor should require *returning to a specific sentence to
>    reject* — that is the bar.
> 4. **Bait the blind solver.** When a world-knowledge default exists, make it a *wrong*
>    option (a "live trap"). This actively *punishes* the non-reader rather than merely failing
>    to help them. At G5, the most common GK default is the textbook-true generalization; if
>    the passage takes a specific or counter-typical stance, key to the passage and make the
>    textbook generalization a distractor.
> 5. **No surface tells.** Length- and structure-match the contending options. The key must
>    NOT be the longest, the most specific, the most hedged, or the only grammatical fit. Run
>    the **longest-option-tell self-check**: if the key is the longest option, rewrite until
>    key length is at or below the median option length.
> 6. **Type-specific anti-leak (G5 format rules folded in):**
>    - **ebsr** — **EASY BAND ONLY** (no EBSR template above ~560L in the renderer; do not
>      author EBSR at medium/hard). Part A discriminates right-answer / wrong-reason
>      near-neighbours; Part B requires selecting the EXACT verbatim evidence sentence; Part B
>      distractors are all genuine on-topic passage quotes. The two parts are evidence-linked
>      so exactly one pair is internally consistent. **Do not lean on Part B to rescue a
>      GK-solvable Part A** — strengthen Part A independently.
>    - **match** — this REPLACES drag-to-order (no order template at G5). Use `match` to bind
>      passage-specific pairings (term→definition-in-context, cause→effect, character→trait,
>      event→consequence). The correct pairing must be fixed by the passage, NOT by a canonical
>      real-world association. Include at least one cross-pair near-neighbour so a blind solver
>      who guesses the "obvious" world-knowledge pairing is wrong. If you would have authored a
>      sequence, encode it as event→position or event→what-follows `match` pairs whose order is
>      fixed by the passage's own signal words (First/Next/Finally, Consequently, As a result).
>    - **hot-text** — the selectable spans must be genuine on-topic passage sentences/phrases;
>      exactly one span (or one defensible minimal set) satisfies the stem; non-key spans are
>      on-topic but answer a *different* question. No span is selectable by GK alone.
>    - **msq** — exactly one defensible correct SET; the keyed set must NOT be "the two/three
>      longest"; include at least one live-trap distractor (GK-true but text-wrong, or a true
>      fact assigned to the wrong actor/stage).
>    - **mcq (incl. vocabulary)** — **vocab is MCQ-only** at G5. For vocabulary-in-context
>      (L.5.4 / L.5.5), the keyed sense must be the one the PASSAGE forces, and at least one
>      distractor must be the word's *common* dictionary sense that the passage does NOT use —
>      so a blind solver who picks the everyday meaning is wrong. **The tested word and its
>      keyed sense must both actually appear/operate in the passage** (guard against the G3
>      vocab-word-mismatch bug: never test a word that isn't in the passage, never key a sense
>      the passage doesn't license).
> 7. **Grade-5 register.** Vocabulary, syntax, and sentence length appropriate to grade 5
>    (denser and longer than G3 — multi-clause sentences are fine and expected). One short
>    corrective feedback string that teaches the cue (the signal word, the evidence sentence,
>    the cause→effect link, the in-context sense). Feedback must be **process-response-verified**
>    — it must resolve to a real `FEEDBACK` outcome, not a silent no-op.
> 8. **Correct CCSS tag (Grade-5):**
>    - compare/contrast across or within text → **RI.5.9** (info) / **RL.5.x** as fits literary
>    - cause-effect, sequence, relationships among events/ideas/steps → **RI.5.3**
>    - main idea + supporting details → **RI.5.2**; theme + summary (literary) → **RL.5.2**
>    - inference / quoting accurately to support inference → **RL.5.1 / RI.5.1**
>    - author's purpose / point of view → **RI.5.6 / RI.5.8** (reasons & evidence)
>    - structure (chronology/comparison/cause-effect/problem-solution) → **RI.5.5 / RL.5.5**
>    - vocabulary / figurative language / word relationships in context → **L.5.4 / L.5.5 /
>      RL.5.4 / RI.5.4**
>    A "what happens after / what causes" item is a relationship standard (RI.5.3), NOT the
>    literal-evidence standard (RI.5.1).
> 9. **Difficulty & passage discipline (per item).** Tag `easy | medium | hard`. Honor the
>    blueprint mix when generating a set (the MAP-equiv form is the canonical mix; see (c)):
>    skew **easy → 6 / medium → 14 / hard → 20** across a 40-item form; type mix **MCQ 24 /
>    EBSR 3 / MSQ 4 / hot-text 5 / match 4**; content mix **Literary 35% / Info 32% / Vocab
>    33%**. Reserve EBSR for the easy band only (rule 6). **Each MAP-equiv item gets its OWN
>    cold passage**; lesson/mastery items may share a passage within a lesson but that passage
>    must appear nowhere else in the course (cold).
>
> **Output (JSON per item)** — the spec's render+gate schema, plus the anti-leak rationale:
> ```
> { id, component, type, ccss, difficulty, lexile,
>   passage_text, passage_source:"machine-authored-cold",
>   stem, options:[{id,text}], key, feedback,
>   skill, humanApproved:false,
>   why_clean }   // rationale: (i) why a passage-blind solve fails, (ii) verbatim grounding,
>                 // (iii) near-neighbour / live-trap construction, (iv) why exactly one answer
>                 // is defensible, (v) longest-option-tell check result
> ```
>
> **Self-check before emitting:** simulate a reader who has NOT seen the passage. If you can
> reach the key from GK, distractor cues, or option structure (including the longest-option
> tell), the item is REJECTED — rewrite it. Then confirm: CCSS is a **Grade-5** code; passage
> is within ~830–1010L and ~120–160 words; format obeys the G5 constraints (EBSR easy-only,
> no order/use match, vocab MCQ-only); `passage_source="machine-authored-cold"` and
> `humanApproved:false`.

---

## (b) GRADER PROMPT — the passage-blind verification rubric (G5)

> **Role.** You are an adversarial grader. You are given an item (stem, options, key, type,
> tag, difficulty) **WITHOUT the passage**. Your job is to decide whether the item *truly
> requires the passage* for full credit. Be skeptical; lean toward FAIL.
>
> **Step 1 — Blind solve.** Attempt the item using only world knowledge and the options
> themselves. Write down the answer you reach and HOW. If you can reach the key, that is a
> leak. (At G5, "world knowledge" includes the standard fifth-grade textbook generalization —
> if the key matches the textbook default, treat that as a GK leak.)
>
> **Step 2 — Leak-path checks (any TRUE ⇒ FAIL or borderline):**
> - **GK leak:** the key is recoverable from general / textbook knowledge.
> - **Elimination leak:** one or more distractors are absurd / false-from-GK and can be struck
>   without the passage, narrowing to the key.
> - **Longest-option tell:** the key is the longest option (count it explicitly), OR the most
>   specific / most hedged / only grammatical option.
> - **Structure leak (match):** the keyed pairings match a canonical real-world association
>   (term→its dictionary definition, cause→its textbook effect) recoverable without the
>   passage; or a sequence-as-match whose order is the canonical real-world order rather than
>   fixed by text signal words.
> - **Single-leg EBSR:** Part A is GK-solvable, so anti-leak strength rests entirely on Part B
>   → mark **borderline / weak-pass**, not clean PASS. Also FAIL any EBSR tagged above the easy
>   band (format violation: no EBSR template above ~560L).
> - **Vocab mismatch (vocab MCQ):** the keyed in-context sense is just the common dictionary
>   sense (GK leak), or the tested word/sense could not plausibly operate in any passage as
>   described → flag for source check.
>
> **Step 3 — Key & distractor quality (uses the rationale, still passage-blind):**
> - Is the keyed answer/set internally consistent and uniquely defensible (exactly one)?
> - Are distractors near-neighbours (plausible, on-topic, require returning to a specific
>   sentence to reject) rather than absurd?
> - Is there a live trap that punishes the blind solver? (bonus, not required)
>
> **Step 4 — Compliance (G5):** Is the CCSS tag a correct **Grade-5** code (RL.5.x / RI.5.x /
> L.5.x) for the skill/type? Is the format legal for G5 (EBSR easy-only; no `order` type; vocab
> MCQ-only)? Is feedback present, accurate, grade-5, and process-response-verified? Is
> `passage_source="machine-authored-cold"` and `humanApproved:false`? Is the key
> verbatim-grounded per the rationale?
>
> **Verdict.** PASS / BORDERLINE / FAIL with a one-line reason. A clean PASS means: your blind
> solve FAILED, no elimination / longest-option / structure leak, unique defensible key,
> near-neighbour distractors, correct **G5** tag, legal G5 format, grade-5 process-verified
> feedback. Record whether the item is a *clean anti-leak exemplar* or a *self-grade-generous
> borderline*.
>
> **Note:** you grade **anti-leak + G5 compliance**, not source truth. You cannot verify the
> passage's own factual provenance — it is machine-authored-cold and `humanApproved:false`;
> real provenance is a separate gate (see Honesty).

---

## (c) LOOP ARCHITECTURE — generate-K → grade-passage-blind → filter → regenerate-failures

```
for each (skill, type, difficulty) target drawn from the blueprint mix:
  1. GENERATE-K:  run GENERATOR POLICY K times (sampled) → K candidate items
                  (each MAP-equiv item gets its OWN cold passage; ~120-160 words, 830-1010L)
  2. GRADE:       run GRADER on each candidate PASSAGE-BLIND (grader never sees passage)
  3. FILTER:      keep PASS; drop FAIL; hold BORDERLINE for review
  4. REGENERATE:  for each FAIL/BORDERLINE, feed the grader's leak-path reason back into the
                  GENERATOR POLICY as targeted feedback ("Part A is GK-solvable — strengthen
                  it"; "key is the longest option — shorten it / pad the distractors"; "match
                  pairing is the canonical real-world one — re-anchor to a passage-specific
                  pairing"; "EBSR above easy band — re-author as easy-band or convert to mcq")
                  and re-generate. Repeat up to N rounds.
  5. ACCEPT:      survivors → g5_demo_bank.json (grouped by component) with their why_clean
                  rationale; hand to Stan to assemble + certify.
```

- **Generator and grader are separate roles/contexts.** The grader must NEVER receive the
  passage; that is what makes its solve *blind* and its verdict meaningful.
- **K and N are tunable.** Higher K = more inference-time search; higher N = more feedback
  refinement. Both trade compute for yield, not weights.
- **The in-loop self-grade is NOT the headline metric.** It is a filter. The real metric is an
  INDEPENDENT audit by a fresh grader (or human) that did not participate in the loop, plus
  the assembled course running green through `certify_course.py` + the passage-blind
  answerability check (the rex-v2 bar, ported to G5).
- **Blueprint conformance is part of the loop's accept stage**, not just per-item: a 40-item
  MAP-equiv form must end at Literary 35% / Info 32% / Vocab 33%, easy 6 / med 14 / hard 20,
  MCQ 24 / EBSR 3 / MSQ 4 / hot-text 5 / match 4. If survivors don't hit the mix, target the
  deficit cells in the next GENERATE-K round.

---

## (d) FINE-TUNING MAPPING — prompting today, fine-tuning when Abdul is ready (kb-0063 shape)

This harness is deliberately structured so the **same three objects** become the three inputs
a fine-tune needs. Abdul can move from prompting to training without changing the contract —
only the substrate.

| Fine-tuning component | This harness (prompt-only, today) | What Abdul ports it to (fine-tuning) |
|---|---|---|
| Trained policy weights | **GENERATOR POLICY prompt** — behaviour encoded in the prompt | the **weights** of the SFT/DPO checkpoint (the prompt's rules become the learned policy) |
| Reward model | **GRADER prompt** — scores candidates, defines "good" | a **reward model / preference judge** (the grader rubric becomes the RM, or the DPO preference labeler) |
| Inference-time search / best-of-K | **generate-K → grade → filter → regenerate** loop | best-of-K at sampling time *and* the data-generation engine that mines training pairs |
| Gradient updates from reward | **feedback regeneration** — grader reasons fed back in-context (no gradients) | actual **gradient steps**: SFT on accepted items, DPO on (PASS > FAIL/BORDERLINE) pairs |
| Trained checkpoint | a *frozen prompt pair* you version and reuse | the **fine-tuned checkpoint** you version and serve |

**Data the loop already produces, mapped to training data:**
- **Accepted (clean-PASS) items → SFT data.** Each survivor (passage + stem + options + key +
  feedback + correct G5 tag) is a supervised target. Train the generator to emit gate-passing
  items directly.
- **(PASS, FAIL/BORDERLINE) pairs on the same (skill, type, difficulty) target → DPO data.**
  The grader's verdict is the preference label: the clean item is "chosen", the leaky item is
  "rejected", and the grader's leak-path reason is the rationale. This is exactly the signal
  the regenerate step uses in-context; in fine-tuning it becomes the preference dataset.
- **Grader verdicts + leak-path reasons → reward-model training data** (if Abdul trains an RM
  rather than using DPO directly): item → {PASS/BORDERLINE/FAIL, reason} is the scored corpus.

This reproduces the *shape* of the kb-0063 fine-tune goal (a policy optimized against a reward
model) **without training any weights today**, while leaving a clean on-ramp: keep running the
loop, log every (candidate, verdict, reason) tuple, and that log *is* the SFT + DPO dataset.
Use the `finetune-queue` (SFT + DPO via the fair-scheduler) when ready — the accepted-items
file is already in the right shape to submit.

---

## (e) HONESTY (kb-0063 lesson, G5-specific)

- **Inference-time generate-and-verify is legitimate for a PRODUCTION generator** — shipping
  best-of-K verified items is a fine way to build a bank. But it is **NOT a K=1 single-model
  claim.** Do not report these numbers as "the model produces clean G5 items at K=1"; they are
  the yield of a search-plus-filter loop. (When Abdul fine-tunes, K=1 yield becomes the honest
  thing to measure on the *trained* checkpoint — and it must be reported as such.)
- **Items are `humanApproved: false`.** No human has signed off; the loop is automated.
- **Passages are machine-authored and cold:** `passage_source="machine-authored-cold"`.
  Anti-leak (kb-0064) means "you must read the passage to answer" — it does NOT mean the
  passage's own facts are sourced or true. A perfectly anti-leak item can sit on an unsourced
  machine-authored passage. **Real G5 passages at Lexile (provenance) are the IDEAL tier and
  are TO-SOURCE — do not invent them or claim them.**
- **The INDEPENDENT-audit rate is the real metric**, not the in-loop self-grade (it is biased
  generous — it green-lit the item it later rates). The honest headline is a fresh adversarial
  pass + the assembled course passing `certify_course.py` and the passage-blind answerability
  check.
- **G5 cohort numbers are TO-SOURCE, NOT invented.** Per the spec's dependency list, the
  following are flagged upward and must NOT be fabricated: **G5 cohort weak-skill data**
  (EGM=0 sub-skills; until it lands, target the G3 weak-skills — compare/contrast,
  cause/effect, sequence — as a *marked placeholder*, explicitly flagged, never presented as
  measured G5 data); **G5 MAP norms** (do NOT reuse G3's 186.6 / 193.9 / 197.1); **G5
  incumbent course id**; a **G5 profile sample**; **real G5 passages**; and **the in-cohort G5
  MAP pilot** (the only path to any RIT / growth claim — a universal blocker).
- **No RIT, no "proven", no growth-multiple** anywhere in any stem, feedback, or report. The
  MAP-equiv form reports **raw/40 + band only**, never RIT. MAP remains 0/313 for our cohort;
  the G5 pilot does not exist yet.
