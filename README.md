# TimeBack Alpha Read Packager

Turn **QTI items** + a **course skeleton** into a complete, **contract-valid TimeBack Alpha Read course**
(OneRoster v1p2 + QTI 3.0). Offline, fail-closed (passes the offline validator; never yet POSTed) — the contract is
reverse-engineered from a live production `Alpha Read – Grade 3` course export (1077 items) and cross-checked
against Ilma's `incept-timeback-plugin` skill.

## Start here — the three docs, most important first
1. **`skill.md`** — the installable Claude skill + the hard rules. **Read this first.** Drop it into
   `~/.claude/skills/timeback-alpha-read-packager/` (or `claude plugin add`) and an agent can drive the
   whole packager. **Push** is via Ilma's `/timeback` skill, never hand-rolled.
2. **`agent.qmd`** — the agent reference: the verified contract, the validator's reject list, the Ilma
   cross-check corrections, and the push plan. Read before changing anything.
3. **`README.md`** (this file) — the human quickstart, the contract in prose, and current status.

## Quickstart
```bash
python3 src/arpack.py --selftest                          # build + validate a sample (no network)
python3 src/arpack.py build skeleton.json out/

# ONE COMMAND: skeleton -> generate -> validate -> assemble -> a full course package
python3 src/course_orchestrator.py examples/sample_skeleton.json out/

bash tests/run_all.sh                                     # all 4 verification layers (206 tests)
```
The orchestrator fans out per lesson (generate → parse → stamp-ids → validate → collect), then assembles
+ emits a package that passes `arpack.validate`. Generator backend is **pluggable**: `stub` (default —
serves the real incept-qti-sdk fixture shapes, so it runs today) → `real` (one-line swap to the live
generator). Draft-safe (course title forced to `STAN-PROBE-DELETEME…`), idempotent, fail-closed (a lesson
that won't validate is reported + excluded, never silently shipped). **Scope: it emits the package; the
*push* to TimeBack is the separate back-half** (Ilma's `/timeback` pipeline + a `POST /validate` server-accept check).

## Feed it your native output
| Hand over | The packager… |
|---|---|
| raw QTI item XMLs (as the incept-qti-sdk emits), grouped per lesson, + passages | `from_qti_xml` parses them; guiding/quiz **auto-detected** from the stimulus-ref |
| an expedition CSV (`examples/expeditions.csv`) | `skeleton_adapter.from_skeleton_table` builds the units (band→Lexile, genre, coverage) |

Then `arpack` assembles the OneRoster+QTI graph, runs a **fail-closed validator**, and emits the package.

## The contract (the validator enforces all of it)
- Per lesson: **3–6 guiding** (1 passage + 1 question each) **+ exactly 4 quiz** — the counts are enforced; the items we've sampled are four-option MCQs, but the validator accepts any of the 7 formats and a ≥2-option floor, not MCQ-ness or a fixed count of 4.
- **All 7 r2 item formats end-to-end**, split by Ilma's RULE 1 *per item*: JSON-safe
  (`choice`/`order`/`extended-text`/single-blank `text-entry`) emit JSON; the rest
  (`hot-text`/`match`/`ebsr`/… **and multi-blank fill-in**) carry the **raw item XML verbatim**
  (`{"format":"xml","xml":…}`), so the API's lossy JSON→XML converter never corrupts their scoring.
  Answer key from `qti-correct-response`. Passage HTML ⊆ `div/p/h1/h2/strong/em/br/blockquote` + MathML;
  images must be **S3 URLs** (no other media).
- Every JSON item carries its **question stem** (`interaction.questionStructure.prompt`) — a stemless item is rejected.
- Course ownership: **root** `primaryApp:"alpha_read"` is the one authoritative setter (Ramish breaking
  change ≥2026-06-30; null/empty/alias→422); `metadata.primaryApp` is mirrored but **inert** (forward-safe
  to drop). Plus `isAlphaRead`; visibility `publishStatus:published` + `timebackVisible`.
- **Standards don't serialise** (the live course stores none) — they drive generator targeting + coverage only.

## Verified vs open
- **Verified (offline):** ingests the real `incept-qti-sdk` output with no hand-edits — both the 4-item sample and the
  13-item all-7 set (mcq/msq, drag-to-order, single + multi-blank fill-in, hot-text, match, EBSR); routes
  every non-JSON-safe item to byte-verbatim raw XML so the API's lossy converter can't touch its scoring;
  parses every item of a live course export we pulled (~1077) cleanly (no wrong keys, no blanks); emits a graph whose
  contract-invariant fields match that export (checked by the parity tests on the course header + one
  round-tripped lesson); the one-command orchestrator (stub generator) builds a package that passes the
  fail-closed validator; cross-checked against Ilma's skill (her corrections adopted where we differed);
  the full test suite + `run_all.sh`'s four layers pass.
- **Server-validated (demo tenant):** the QTI for all 6 sample formats (incl. raw-XML hot-text/match/EBSR)
  imports QC-trusted to a **TimeBack Content surface** — [platform3 content-alpha](https://platform3-andymontgomery-9773s-projects.vercel.app/content/alpha/skill_pack/pack/SKILL.md),
  `demo` tenant — via its `qti-package` import: `trust_status: "trusted"` (`problem_code: null`), items
  `published`, student-view with answer keys hidden. Confirmed for **both** the bridge-generated QTI
  (`examples/g3v2_demo_bridge.py`) **and the production `incept-qti-sdk` package** (6 items, real ELA sample),
  which our packager also parses clean. Real TimeBack QC, sandbox tenant — **not** the live Alpha Read renderer.
- **Live push + render (verified 2026-06-17):** the production `incept-qti-sdk` package (6 items + 6 stimuli)
  was pushed to **live Alpha Read** (`qti.alpha-1edtech.ai` + `api.alpha-1edtech.ai`) as a `STAN-PROBE-DELETEME`
  draft — 6 items (verbatim XML POST) + test + a full OneRoster course/unit/lesson/resource/link, all 201. It
  **renders in AlphaBuild**: all 6 formats appear (Choice/Match/Order/Composite-EBSR/HotText), the QTI panel
  shows **✅ Valid**, and the **"Preview (from Timeback) LIVE"** renders the real two-pane reading view
  (passage + question + selectable options).
- **Student-app render confirmed (2026-06-17):** the real ELA article renders **end-to-end in the live Alpha
  Read student app** — `https://alpharead.alpha-1edtech.ai/articles?articleId=<N>&crsid=article_<N>` shows the
  passage → guiding-question unlock flow (a 25-step reading session whose step types match the live article).
  A test student (own profile, `student` role) is enrolled via term→class→enrollment
  (`push_to_timeback.py --enroll-student <userId>`). Only the student **login** is non-automatable.
- **Open:** a full multi-lesson course end-to-end awaits the live skeleton + full generator.
  *Gotchas baked into the tool:* `vendorResourceId` must be the bare number (test at `article_<N>`); the
  student URL needs both `articleId` + `crsid`; a draft must land in an org the viewer belongs to; a class's
  `terms` must share the class's `org`.

## Upload — two real targets
- **Demo (proven):** build the QTI from real generated content with `examples/g3v2_demo_bridge.py` (Anirudh's
  `grade3-reading-v2` sample → QTI → package), then import it to the [platform3 content-alpha](https://platform3-andymontgomery-9773s-projects.vercel.app/content/alpha/implementation/api)
  `demo` tenant — `POST /dev/mint?tenantId=demo` for a token, then `POST …/imports/qti-package` with
  `Content-Type: application/xml`, an `Idempotency-Key` header, and the raw item XML as the body (the server
  parses — don't parse locally). Read back `…/trust` (expect `trusted`) and `…/student-view`. Sandbox tenant,
  no real creds, throwaway data — real TimeBack QC, but **not** the live Alpha Read app.
- **Live Alpha Read (production):** automated by `examples/push_to_timeback.py` (implements Ilma's
  [incept-timeback-plugin](https://github.com/ilmych/incept-timeback-plugin) push order — her `/timeback`
  skill stays the canonical surface): `python3 examples/push_to_timeback.py --package qti_package/ --org
  <viewer-org-sourcedId> --verify`. Creds from a gitignored `.env`; idempotent + checkpointed + 409=success;
  pushes only a `STAN-PROBE-DELETEME` draft. **Org gotcha:** the draft must land in an org the viewer belongs
  to (a foreign org → AlphaBuild "Access denied"). Verified 2026-06-17: renders in AlphaBuild, QTI **Valid**.

## Layout
```
src/        all 8 Python modules — run with `python3 src/<name>.py`
examples/   sample skeleton + materialized JSON + the expedition CSV
fixtures/   real incept-qti-sdk build output (the stub's source of truth)
tests/      pytest suite + run_all.sh (all 4 verification layers)
skill.md · agent.qmd · README.md   the three docs (most important first)
```
CLI path args (e.g. `examples/sample_skeleton.json`) stay relative to the repo root.

## Decided up front
The reviewer questions are already answered from the live export + Ilma's skill: the canonical owner string,
whether the pre-cutover `metadata.primaryApp` is still needed (it isn't), the `vendorResourceId` form, where
the resource `url` lives, who owns the push order/auth (Ilma's `/timeback`), and that standards never
serialise. Each is enforced in `validate()` and locked by a test — see `agent.qmd` for the specifics.

---
*Thanks to **Mayank Dave** (incept-qti-sdk generator + the real fixture output) and **Praveen Koka**
(Alpha Read delivery app + API guidance) for their help.*
