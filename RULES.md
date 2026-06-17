# RULES — Grade-3 Reading on Alpha Read

What actually renders, what to author, and how to publish. Every rule carries its evidence so nobody
has to re-guess. **Confidence tags:** `[LIVE]` walked in the student app myself · `[CENSUS]` exhaustive
content check of the real course · `[PROBE]` one live probe per format (decisive for draws/doesn't, not
edge cases) · `[CODE]` enforced in code + tests · `[OPEN]` not yet verified.

_Last verified 2026-06-17 against `alpharead.alpha-1edtech.ai` (DevFactory org) + `trilogy-group/alpha_courses`._

---

## RENDER RULES (the reading-article surface)

**R1 — The reading renderer draws ONLY single-select `choice` + `order`.** Author reading questions as
single-select MCQ or drag-to-order. Nothing else displays. `[PROBE each]` + `[CENSUS]` the live 1077-item
reading course is **1077/1077 single-select MCQ** (zero order/match/hot-text/text-entry/ebsr), so this
isn't a guess — the real course already lives inside this limit.

**R2 — MSQ does not work.** A `qti-choice-interaction` with `cardinality="multiple"` renders, but the
reader makes it **single-select** — selecting a second option deselects the first, so a multi-answer
question can't be answered. `[LIVE]` (clicked two, the first deselected). Never ship MSQ to reading; if a
question needs multiple correct answers, split it into per-row single-choice items.

**R3 — `match`, `hot-text`, `text-entry` render BLANK.** They push fine (HTTP 201, valid QTI, GET 200) but
the quiz body is empty — the reader has no component for them. `[PROBE each, LIVE]`. They must be
transformed to single-select choice (see Authoring) or they show nothing to the student.

**R4 — A composite item (≥2 interactions, e.g. EBSR) FLATTENS** into one combined ~8-option question.
`[LIVE]`. **Fix is automatic:** `arpack`/`push_to_timeback.py` decompose an EBSR into two linked
single-choice items (`<id>-partA`, `<id>-partB`) at build/push time. `[CODE]` (207 tests) + `[LIVE]`
(Part A renders isolated as "1 of 2", 4 options, no flatten). Never push a composite EBSR as one item.

**R5 — Scoring works.** Answer + Confirm grades correctly: a correct pick shows a green check and awards XP
(verified 100 XP on a correct answer), a SCORE outcome is required on every item (the packager emits it).
`[LIVE]` + `[CODE]`. `[OPEN]`: within a multi-question article I confirmed Part A renders+scores; the exact
Part-A-then-Part-B *screen* sequence inside the final-quiz step should be re-confirmed on the real
multi-question package.

**R6 — Two surfaces, two renderers — don't conflate.** The **reading** app does R1. The **assessment**
surface (`alpha_read_build`, MAP-proxy) is a *different* renderer that DOES draw match/hot-text/ebsr/order
(exhaustive census: 103 hot-text, 37 match, 100 ebsr, 42 sequence). `[CENSUS]`. "It renders in assessment"
and "AlphaBuild shows it Valid" do **not** mean it renders in reading — only a live student-app walk proves
reading render. `[CODE]`/`[LIVE]`.

---

## AUTHORING RULES (what to send for reading content)

**A1 — Reading questions = single-select MCQ or drag-order. Full stop.** (R1)
**A2 — EBSR is fine to author** — it auto-decomposes to two single-choice items. (R4)
**A3 — Transform the blanks** (only if reading content uses them): hot-text → single-choice (options = the
candidate sentences; verified `[LIVE]`); match → **one single-choice MCQ per row** (NOT one MSQ — R2);
text-entry → single-choice MCQ (correct term + near-neighbor distractors). These are content transforms
(semantic), not auto-applied by the tool — author them as MCQ upstream, or run the transform pass.
**A4 — One article = one passage + its questions.** Items are grouped into articles by their
`<qti-assessment-stimulus-ref>`; every item must carry it, or it lands in the wrong article. `[CODE]`/`[LIVE]`.
**A5 — Skeleton coordinates live in the manifest LOM** (`timeback-extended-attributes` taxonPath):
`cell_key = standard|format|lexile`, `lexile`→band, `lesson_phase`→i-do/we-do/you-do, `template_id`.
Group units with `--unit-by cell_key`. `[CODE]` (dry-run verified).

---

## PUBLISH RULES (the wiring + the command)

**P1 — ID coupling (or it 404s / won't render):** per article the QTI test id == OneRoster resource id ==
component-resource id == `article_<N>`, with `vendorResourceId = <N>` (a bare number). `[LIVE]`/`[CODE]`.
**P2 — Student URL needs BOTH params:** `…/articles?articleId=<N>&crsid=article_<N>`. `[LIVE]`.
**P3 — Org:** a course must live in an org the viewer belongs to. Pilot target = DevFactory
`3bf28231-08de-45c3-a9d1-40b1defc9fd5`. Real student-facing school = a different org. `[LIVE]`.
**P4 — `publishStatus: published` behaves the same as draft for render+score** — verified a published
course renders + scores identically. `[LIVE]`. Use `--publish` for a real course (loud banner, lifts the
DELETEME guard).
**P5 — Always `--dry-run` first**, eyeball the unit→article→item tree, then swap for `--publish --verify`.
**P6 — Drafts/tests use a `STAN-PROBE-DELETEME-*` prefix** so teardown (filter-delete) can find them. `[LIVE]`.

```bash
set -a; source /tmp/timeback.env; set +a
# dry-run (offline):
python3 examples/push_to_timeback.py --package <pkg> --org 3bf28231-08de-45c3-a9d1-40b1defc9fd5 \
  --prefix grade3-reading-ela-9100 --title "Grade 3 Reading (ELA pilot)" --unit-by cell_key --dry-run
# publish (after eyeballing the tree):  (swap --dry-run -> --publish --verify [--enroll-student <id>])
```

---

## CONFIDENCE LEDGER

| Claim | Confidence | Basis |
|---|---|---|
| Reading = single-select choice + order only | **High** | n=1 probe each + exhaustive 1077-item census agree |
| match/hot-text/text-entry blank | **High** | live probe each (decisive for draw/no-draw) |
| MSQ renders single-select | **High** | live (deselect observed) |
| Composite EBSR flattens; decompose fixes it | **High** | live both ways + 207 tests |
| Scoring (correct → XP) | **High** | live (green check + 100 XP) |
| Multi-question Part-A→Part-B screen sequence | **Open** | Part A verified; confirm on real package |
| text-entry via JSON-modeled push | **Open** | only raw-XML path tested (blank); JSON path untested |
| Reading renderer parity (match/hot-text) | **Escalation** | renderer-side fix; not on our side |
