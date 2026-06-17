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
- **Open / unverified:** whether Alpha Read **renders** the tech-enhanced formats — the renderer probe
  (needs a test-student account); a full multi-lesson course end-to-end (awaiting the live skeleton + full
  generator); the package has **never been POSTed to a server** (shape-match, not server-accept — closed by
  `POST /validate` + the Ilma push).

## Push (manual, by design)
Safety rail: only a course titled `STAN-PROBE-DELETEME…`, and `POST /validate` first. Paths: admin
**Manage Courses** import · **AlphaBuild** "Sync All Lesson Plans" · direct QTI/OneRoster API. (No
package-import endpoint exists, so QTI leaves get POSTed regardless.)

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
