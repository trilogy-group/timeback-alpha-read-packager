# G5 anti-leak generator — hand-off for Abdul

## What this is
A **working** G5 anti-leak item generator + an **executable** acceptance test + **11 Grade-5 seed items**.
You are adapting a gated pipeline, not building from a blank spec.

## The bar, in one line
Every item must be solvable **only by reading the passage**. That is stricter than InceptBench — InceptBench
passes leaky items; this gate does not.

## Run it (3 things, in order)
1. **Generate** — `G5_GENERATOR.md` is the harness that produces gate-passing items.
2. **Grade** — `anti_leak_grader.py` is your definition of done. Run your edullm-ela output through it.
3. **Reference** — `seed_bank.json` = 11 deterministic-clean seed items: reference examples + fine-tune data.

## Your path (3 parts; you are at part 3 — the own-LLM)
1. **Orient** with edullm-ela.
2. **Grade** its output through `anti_leak_grader.py`.
3. **Where it fails — tailor / agentify / fine-tune.** The reward signal is the grader's **accept/reject**,
   NOT "match Gemini." Gemini leaks; InceptBench passes the leaks. Do not chase them.
4. **Deliverable** = reliable regeneration of grader-passing items.

## The division
- **You own the model.** **Stan owns the gate.**
- "Done" = your output runs **green** through the grader.

## Honest caveats (do not paper over these)
- G5 cohort weak-skill data, norms, and incumbent-id are **TO-SOURCE** — don't invent them.
- Passages here are **machine-authored-cold** (`humanApproved: false`).
- **No RIT claim** until a real in-cohort G5 pilot exists.
- Current seed coverage is narrow: RI.5.9 x5, RI.5.3 x4, RL.5.1 x2; types are mcq x6, msq x2,
  ebsr x1, hottext x2. Match/sequence and main-idea coverage still need generator work.
- `anti_leak_grader.py` deterministically checks structure and grade-family only. Passage-blind
  solvability still requires a separate LLM/human adjudication step.

## Files
- Full spec: `/Users/stanhus/Documents/grade3-reading/artifacts/alpha-read-packager/GRADE5_COURSE_SPEC.md`
- Generator harness: `G5_GENERATOR.md`
- The gate: `anti_leak_grader.py`
- Seed items: `seed_bank.json`
