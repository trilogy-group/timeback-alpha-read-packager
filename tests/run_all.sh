#!/usr/bin/env bash
# run_all.sh — the QUADRUPLE verification gate for the Alpha Read Packager.
#
#   Layer 1: every module's built-in self-test (arpack/skeleton_adapter/output_dir_ingester/
#            generator_client) — proves each unit in isolation, no network.
#   Layer 2: the pytest suite (tests/) — contract, parsing, adapters, sanitizer, pipeline,
#            forward-compat (Ramish primaryApp gate), idempotency, fail-closed.
#   Layer 3: live-production parity (skipped cleanly if the export isn't on disk) — parses all
#            1077 live items, confirms canonical 'alpha_read', round-trips a real lesson.
#   Layer 4: a clean one-command end-to-end build from the example skeleton + CSV.
#
# Run from anywhere: `bash tests/run_all.sh`. Exits non-zero on the first failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/src"
cd "$ROOT"

echo "════════ Layer 1: module self-tests ════════"
python3 "$SRC/arpack.py" --selftest
python3 "$SRC/skeleton_adapter.py" >/dev/null && echo "skeleton_adapter: PASS"
python3 "$SRC/output_dir_ingester.py" >/dev/null && echo "output_dir_ingester: PASS"
python3 "$SRC/generator_client.py" >/dev/null && echo "generator_client: PASS"

echo ""
echo "════════ Layers 2+3: pytest suite (incl. live-parity) ════════"
python3 -m pytest "$ROOT/tests" -q

echo ""
echo "════════ Layer 4: clean end-to-end build ════════"
TMP="$(mktemp -d)"
python3 "$SRC/course_orchestrator.py" "$ROOT/examples/sample_skeleton.json" "$TMP/skel_out"
python3 "$SRC/course_orchestrator.py" "$ROOT/examples/expeditions.csv" "$TMP/csv_out"
rm -rf "$TMP"

echo ""
echo "✅ ALL FOUR LAYERS PASSED"
