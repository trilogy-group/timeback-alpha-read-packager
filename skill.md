---
name: timeback-alpha-read-packager
description: Package QTI items + a course skeleton into a complete TimeBack Alpha Read course (OneRoster v1p2 + QTI 3.0) that passes the offline contract validator, or one-command-build a whole course from a skeleton. Use when assembling, validating, or preparing Grade-3 Alpha Read content for upload, or ingesting an incept-qti-sdk output_dir. Reverse-engineered from a live production Alpha Read course export (1077 items) and cross-checked against Ilma's timeback skill.
---

# TimeBack Alpha Read Packager — skill

Turn QTI items (`incept-qti-sdk` output) + a course skeleton (an expedition table) into a
complete Alpha Read course (OneRoster v1p2 + QTI 3.0) that passes the offline, fail-closed `validate()` — shape-match, never POSTed to a server.

## Invoke when
- assembling or validating a Grade-3 reading course for AlphaRead
- ingesting an `incept-qti-sdk` `output_dir` (manifest + items + stimuli)
- one-command-building a whole course from a skeleton

## Use it
```bash
python3 src/arpack.py --selftest                       # build + validate a sample (no network)
python3 src/course_orchestrator.py skeleton.json out/  # ONE COMMAND: skeleton → generate (stub) → validate → assemble → full package
bash tests/run_all.sh                                  # 4 verification layers (self-tests + pytest + live-parity + e2e)
```
- `output_dir_ingester.from_timeback_build_output(dir)` — parses + normalizes the incept-qti-sdk output (raw XML for XML-only items carried byte-verbatim).
- `skeleton_adapter.from_skeleton_table(csv)` — reads the expedition table.
- The modules live in `src/`; CLI path args stay relative to the repo root.

## Before changing anything
Read **`agent.qmd`** (contract, invariants, the applied cross-check corrections, the push plan) and
**`README.md`** (human quickstart + status).

## Hard rules (key gates — `validate()` enforces more)
- Emit only what passes the fail-closed `validate()`: **root** `primaryApp:"alpha_read"` (the one ownership
  setter, Ramish ≥2026-06-30; null/empty/alias→422) with `metadata.primaryApp` mirrored-but-inert (forward-safe
  to drop), `isAlphaRead`, publish flags (`publishStatus:published` + `timebackVisible`), 3–6 guiding + exactly
  4 quiz per lesson, **sanitized XHTML** content/stem (`sanitize_html.full_sanitize`), **S3-only** images.
  For **JSON-safe** items also: a **question stem** (`interaction.questionStructure.prompt`) and a resolvable
  answer key. **XML-only** items (hot-text/match/EBSR/…) are validated as a well-formed envelope — their key
  and stem live in the verbatim XML and are not inspected. (Also gated: duplicate-id, resource↔test
  id-coupling, no authored `metadata.metrics`.)
- **PUSH via Ilma's `/timeback` skill — do NOT hand-roll a pusher.** She owns auth, push-order, the
  JSON-vs-XML branching, and the gotchas (200 OK ≠ rendered). Push only to a `STAN-PROBE-DELETEME…` draft,
  and run `POST /validate` first.
