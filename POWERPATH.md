# PowerPath path — render ALL question types (the working path, 2026-06-17)

> **Important correction to the "Render reality" in [`README.md`](README.md)/[`RULES.md`](RULES.md).**
> That narrow render set (single-select `choice` + `order` only; match / hot-text / text-entry blank) is
> **specific to the `alpha-read-article` lessonType on the AlphaRead app** (`alpharead.alpha-1edtech.ai`).
> It is **not** a platform limit. The **`powerpath-100` lessonType on the TimeBack UI**
> (`alpha.timeback.com`) uses the full renderer and draws **every** question type — match, hot-text, EBSR,
> sequence, MSQ, choice. If you need the rich types to render, ship `powerpath-100`, not `alpha-read-article`.

Verified by reverse-engineering Praveen's `reading-explorers-g3-allqtypes` (the "works really well" course)
and rebuilding our Grade-3 Reading content in the same shape: **`grade3-reading-ela-pp-9701`** — 10 units /
47 lessons / ~560 questions, all types rendering on the TimeBack UI.

## The shape a `powerpath-100` lesson needs
```
course
  unit component
    lesson component
      component-resource   metadata.lessonType = powerpath-100, resource.sourcedId = QTI test id
      QTI assessment-test  ONE test-part (linear/individual) -> ONE section -> N item-refs = the BANK
      QTI items            clean QTI 3.0 (adaptive=false), each with a <qti-assessment-stimulus-ref>
      stimulus             the passage the question was written against (see "per-item stimulus" below)
      parent ALI           gradebook assessmentLineItem, 0-100, linked to the component-resource
      child ALIs           one per item, 0-1, metadata.questionId = the QTI item id
```
Key invariants (full recipe: the powerpath-100 instructions doc):
- The selector pool **is the QTI assessment-test's item-refs** — child ALIs are tracking only, not the bank.
- Banks must be **deep (≥8 items)**. PowerPath scoring is incremental (one correct ≈ 14, not 100); a
  1-item bank loops (this is the "match re-renders on submit" bug — a course-shape issue, not the renderer).
- Don't model a single standalone item as `powerpath-100`.

## Per-item stimulus (the gotcha that cost us a re-deploy)
Each source question is authored against its **own** stimulus text, which drifts from the lesson's article
passage. If you attach one shared passage per lesson, hot-text/EBSR/MCQ reference sentences the student
never sees → "not answerable" everywhere. **Give each item its own stimulus** (the text it was written for).
An adversarial QA pass (per-question vs its passage) caught this: shared-stimulus = 279 issues, per-item = 19.

## Scripts (`examples/`)
| Script | What it does |
|---|---|
| `publish_powerpath.py` | Build the whole powerpath course from a raw bundle (Anirudh's `course_bundle.jsonl`). Emits stimuli + clean QTI items + bank tests + powerpath resources/component-resources + parent/child ALIs + enrollment. Idempotent. |
| `audit_powerpath.py` | Verify every lesson is powerpath-wired: cr+resource `lessonType=powerpath-100`, bank ≥ N, parent ALI present. |
| `dump_lesson.py` | Print one lesson's passage + every question (keys marked) — for content review/QA. |
| `prune_banks.py` | Re-PUT a lesson's test with flagged item-refs removed (drop bad questions without a full re-deploy). |

QTI item generators are the `adaptive=false` builders from the v2 bridge (same clean shape Praveen uses).

## Commands
```bash
# dry-run (offline plan + XML well-formedness)
python3 examples/publish_powerpath.py --bundle course_bundle.jsonl \
  --org <ORG> --prefix <course-id> --title "<title>" --dry-run

# deploy (idempotent; --skeleton-only / --only-unit N / --limit-lessons N for staged runs)
python3 examples/publish_powerpath.py --bundle course_bundle.jsonl \
  --org <ORG> --prefix <course-id> --title "<title>" --enroll-student <uid> --publish

# verify wiring
python3 examples/audit_powerpath.py --course <course-id> --min-bank 8
```

## Render check (admin-viewable; the course viewer itself is student-only)
```
https://alpha.timeback.com/app/activity/<component-resource-id>?courseId=<course-id>&kind=quiz&url=<urlencoded QTI test url>&title=<t>
```
Pointing this at an `alpha-read-article` resource hangs on "Loading exercise…" (no powerpath session). A
real `powerpath-100` cr renders: passage on the left, question on the right, POWERPATH SCORE gauge.

## API quirks
- `POST /assessment-tests` needs **structured JSON** (top-level `identifier` + `qti-test-part`); the
  `{format:xml,xml}` envelope is rejected for tests (it's fine for `/assessment-items`).
- This OneRoster API returns **HTTP 404 with "already exists"** for duplicates (not 409) —
  `push_to_timeback.post()` treats "already exists" as success so re-runs are idempotent.
