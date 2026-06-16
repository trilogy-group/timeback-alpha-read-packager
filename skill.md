---
name: timeback-alpha-read-packager
description: Package QTI items + a course skeleton into a complete, contract-valid TimeBack Alpha Read course (OneRoster v1p2 + QTI 3.0), or one-command-build a whole course from a skeleton. Use when assembling, validating, or preparing Grade-3 Alpha Read content for upload, or ingesting an incept-qti-sdk output_dir. Reverse-engineered from a live production Alpha Read course export (1077 items) and cross-checked against Ilma's timeback skill.
---

# TimeBack Alpha Read Packager — skill

Turn QTI items (`incept-qti-sdk` output) + a course skeleton (an expedition table) into a
complete, **contract-valid** Alpha Read course (OneRoster v1p2 + QTI 3.0).

## Invoke when
- assembling or validating a Grade-3 reading course for AlphaRead
- ingesting an `incept-qti-sdk` `output_dir` (manifest + items + stimuli)
- one-command-building a whole course from a skeleton

## Use it
```bash
python3 src/arpack.py --selftest                       # build + validate a sample (no network)
python3 src/course_orchestrator.py skeleton.json out/  # ONE COMMAND: skeleton → generate → validate → assemble → full package
bash tests/run_all.sh                                  # 4 verification layers (self-tests + 206 pytests + live-parity + e2e)
```
- `output_dir_ingester.from_timeback_build_output(dir)` — ingests Mayank's output verbatim (no reshaping).
- `skeleton_adapter.from_skeleton_table(csv)` — reads Anirudh's expedition table.
- All 8 modules live in `src/`; CLI path args stay relative to the repo root.

## Before changing anything
Read **`agent.qmd`** (contract, invariants, the applied cross-check corrections, the push plan) and
**`README.md`** (human quickstart + status).

## Hard rules
- Emit only what passes the fail-closed `validate()` — **root** `primaryApp:"alpha_read"` (the one ownership
  setter, Ramish ≥2026-06-30; null/empty/alias→422) with `metadata.primaryApp` mirrored-but-inert (forward-safe
  to drop), `isAlphaRead`, publish flags (`publishStatus:published` + `timebackVisible`), 3–6 guiding + exactly
  4 quiz per lesson, every item's **question stem** in `interaction.questionStructure.prompt`, **sanitized XHTML**
  content/stem (`sanitize_html.full_sanitize`), **S3-only** images, resolvable answer key.
- **PUSH via Ilma's `/timeback` skill — do NOT hand-roll a pusher.** She owns auth, push-order, the
  JSON-vs-XML branching, and the gotchas (200 OK ≠ rendered). Push only to a `STAN-PROBE-DELETEME…` draft,
  and run `POST /validate` first.
