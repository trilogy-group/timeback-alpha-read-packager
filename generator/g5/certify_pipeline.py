#!/usr/bin/env python3
"""
certify_pipeline.py — end-to-end certification pipeline for G5 course items.

Runs a candidate item set through all certification stages and writes a
verified, annotated item set ready for course assembly.

Usage:
  python3 certify_pipeline.py <input.jsonl> [--schema abdul|adapted]
                               [--sample N] [--output-dir DIR]

Arguments:
  input.jsonl        One item per line. If --schema=abdul (default), each line
                     is a wrapper record with a nested 'item' object (Abdul's
                     grade5-reading-v2 format). If --schema=adapted, each line
                     is already in anti_leak_grader.py input format.

Options:
  --schema SCHEMA    Input schema: 'abdul' (default) or 'adapted'.
  --sample N         Process only the first N items (useful for spot-checks).
  --output-dir DIR   Directory for output files (default: ./certify_output/).

Stages:
  1. ADAPT            (abdul schema only) Convert to grader format via
                      adapt_abdul.py.
  2. STRUCTURAL GATE  Run anti_leak_grader.py deterministic checks (7 checks).
  3. STANDARD VERIFY  Confirm every item's CCSS code is in the Grade-5 family
                      (RL.5 / RI.5 / L.5 / RF.5).
  4. COVERAGE REPORT  Breakdown by type, by CCSS standard, and by KCT tag.
  5. SUMMARY          PASS/FAIL per item, aggregate stats, top fail reasons.

Output files (in output-dir):
  passing.jsonl      Items that cleared all gates (with _certify_* annotations).
  failing.jsonl      Items that failed one or more gates (with fail reasons).
  certify_report.json  Full machine-readable report.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADAPT_SCRIPT = os.path.join(SCRIPT_DIR, "adapt_abdul.py")
GRADER_SCRIPT = os.path.join(SCRIPT_DIR, "anti_leak_grader.py")

GRADE5_FAMILIES = ("RL.5", "RI.5", "L.5", "RF.5")


# ---------------------------------------------------------------------------
# Stage 1: Adapt (Abdul schema → grader format)
# ---------------------------------------------------------------------------

def run_adapt(input_path, adapted_jsonl_path):
    """
    Run adapt_abdul.py as a subprocess.
    Returns (ok_count, skip_count, error_count).
    Raises RuntimeError if the subprocess fails with no output.
    """
    result = subprocess.run(
        [sys.executable, ADAPT_SCRIPT, input_path, adapted_jsonl_path],
        capture_output=True,
        text=True,
    )
    stderr = result.stderr.strip()
    ok = skip = err = 0
    m = re.search(r"Adapted:\s*(\d+).*skipped:\s*(\d+).*errors:\s*(\d+)", stderr)
    if m:
        ok, skip, err = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if result.returncode not in (0, 1) and ok == 0:
        raise RuntimeError(
            f"adapt_abdul.py failed (rc={result.returncode}):\n{stderr}"
        )
    return ok, skip, err


def load_adapted_jsonl(jsonl_path, sample_n=None):
    """
    Load already-adapted JSONL (one item per line).
    Returns a list of dicts.
    """
    items = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
            if sample_n is not None and len(items) >= sample_n:
                break
    return items


def load_raw_jsonl_and_adapt(input_path, sample_n=None):
    """
    Load Abdul-schema JSONL and adapt in-process using adapt_abdul.adapt_item.
    Returns (adapted_items, skip_count, error_count).
    """
    # Import adapt_item from adapt_abdul.py
    import importlib.util
    spec = importlib.util.spec_from_file_location("adapt_abdul", ADAPT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    adapt_item = mod.adapt_item

    items = []
    skip = err = 0
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            if sample_n is not None and len(items) >= sample_n:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                raw_item = rec.get("item", rec)
                adapted = adapt_item(raw_item)
                if adapted:
                    items.append(adapted)
                else:
                    skip += 1
            except Exception:
                err += 1
    return items, skip, err


# ---------------------------------------------------------------------------
# Stage 2: Structural gate
# ---------------------------------------------------------------------------

def jsonl_to_json_tempfile(items, tmpdir):
    """Write items list to a temp JSON file for anti_leak_grader.py."""
    json_path = os.path.join(tmpdir, "grader_input.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(items, f)
    return json_path


def run_grader(json_path):
    """
    Run anti_leak_grader.py on a JSON file.
    Returns (stdout_text, returncode).
    --no-llm-prompt keeps output compact; prompts are available via direct
    grader invocation if needed.
    """
    result = subprocess.run(
        [sys.executable, GRADER_SCRIPT, json_path, "--no-llm-prompt", "--no-notes"],
        capture_output=True,
        text=True,
    )
    return result.stdout, result.returncode


# Grader output line patterns:
#   [#N] FAIL  (fmt) | stem_preview
#        - reason1
#   [#N] PASS (deterministic) -> NEEDS_LLM_GRADE (fmt) | stem_preview
#
# For PASS lines the format name is in the LAST parenthesised group before '|'.
# For FAIL lines it is in the FIRST (and only) parenthesised group.
# Capture them with two alternative patterns.

_ITEM_PASS_RE = re.compile(
    r"^\[#(\d+)\]\s+PASS\b.*?\bNEEDS_LLM_GRADE\s+\((\w[\w-]*)\)\s*\|?\s*(.*)?$"
)
_ITEM_FAIL_RE = re.compile(
    r"^\[#(\d+)\]\s+FAIL\b\s+\((\w[\w-]*)\)\s*\|?\s*(.*)?$"
)
_REASON_LINE_RE = re.compile(r"^\s+-\s+(.+)$")


def parse_grader_output(stdout_text):
    """
    Parse anti_leak_grader.py stdout into per-item dicts:
      {idx, verdict, fmt, stem_preview, reasons}
    verdict: 'STRUCTURAL_PASS' or 'STRUCTURAL_FAIL'
    """
    results = []
    current = None

    for line in stdout_text.splitlines():
        mp = _ITEM_PASS_RE.match(line)
        mf = _ITEM_FAIL_RE.match(line)
        m = mp or mf
        if m:
            if current is not None:
                results.append(current)
            idx = int(m.group(1))
            fmt = m.group(2)
            stem_preview = (m.group(3) or "").strip()
            verdict = "STRUCTURAL_PASS" if mp else "STRUCTURAL_FAIL"
            current = {
                "idx": idx,
                "verdict": verdict,
                "fmt": fmt,
                "stem_preview": stem_preview,
                "reasons": [],
            }
            continue

        if current is not None:
            rm = _REASON_LINE_RE.match(line)
            if rm:
                current["reasons"].append(rm.group(1).strip())

    if current is not None:
        results.append(current)

    return results


# ---------------------------------------------------------------------------
# Stage 3: Standard verification — CCSS Grade-5 family
# ---------------------------------------------------------------------------

def _ccss_codes(ccss_field):
    """Normalize a ccss field value to a list of strings."""
    if ccss_field is None:
        return []
    if isinstance(ccss_field, str):
        return [c.strip() for c in ccss_field.replace(",", " ").split() if c.strip()]
    if isinstance(ccss_field, (list, tuple)):
        return [c.strip() for c in ccss_field if isinstance(c, str) and c.strip()]
    return []


def verify_ccss_standard(item):
    """
    Return (passes, reason_or_None).
    Passes if at least one CCSS code is in the Grade-5 reading family.
    """
    codes = _ccss_codes(item.get("ccss"))
    if not codes:
        return False, "standard-verify: no CCSS code present"
    for code in codes:
        if any(code.startswith(fam) for fam in GRADE5_FAMILIES):
            return True, None
    return False, (
        "standard-verify: CCSS code(s) %s not in Grade-5 family "
        "(%s)" % (", ".join(codes), "/".join(GRADE5_FAMILIES))
    )


# ---------------------------------------------------------------------------
# Stage 4: Coverage report
# ---------------------------------------------------------------------------

def build_coverage_report(passing_items):
    """
    Return a coverage dict for the passing item set:
      by_type:     {type: count}
      by_ccss:     {ccss_standard: count}  (e.g. "RL.5.1": 42)
      by_kct:      {kct_tag: count}
    """
    by_type = defaultdict(int)
    by_ccss = defaultdict(int)
    by_kct = defaultdict(int)

    for item in passing_items:
        by_type[item.get("type", "unknown")] += 1
        for code in _ccss_codes(item.get("ccss")):
            by_ccss[code] += 1
        kct = item.get("kct", "")
        if kct:
            by_kct[kct] += 1

    return {
        "by_type": dict(sorted(by_type.items())),
        "by_ccss": dict(sorted(by_ccss.items())),
        "by_kct": dict(sorted(by_kct.items())),
    }


# ---------------------------------------------------------------------------
# Stage 5: Merge verdicts and write output files
# ---------------------------------------------------------------------------

def merge_and_write(adapted_items, grader_results, output_dir):
    """
    Merge structural and standard-verification verdicts onto each item.
    Write passing.jsonl, failing.jsonl, and certify_report.json.
    Returns certify_report dict.
    """
    os.makedirs(output_dir, exist_ok=True)

    pass_path = os.path.join(output_dir, "passing.jsonl")
    fail_path = os.path.join(output_dir, "failing.jsonl")
    report_path = os.path.join(output_dir, "certify_report.json")

    idx_to_grader = {r["idx"]: r for r in grader_results}

    passing = []
    failing = []
    per_type = defaultdict(lambda: {"pass": 0, "fail": 0})
    fail_reason_counts = defaultdict(int)

    for idx, item in enumerate(adapted_items):
        grader = idx_to_grader.get(idx)
        if grader is None:
            grader = {
                "idx": idx,
                "verdict": "STRUCTURAL_FAIL",
                "fmt": item.get("type", "unknown"),
                "reasons": ["item-not-graded: item missing from grader output"],
            }

        fmt = grader.get("fmt", item.get("type", "unknown"))
        structural_pass = grader["verdict"] == "STRUCTURAL_PASS"
        structural_reasons = list(grader["reasons"])

        # Stage 3: CCSS standard verification
        std_pass, std_reason = verify_ccss_standard(item)

        all_reasons = list(structural_reasons)
        if not std_pass and std_reason:
            all_reasons.append(std_reason)

        item_passes = structural_pass and std_pass

        annotated = dict(item)
        annotated["_certify_verdict"] = "PASS" if item_passes else "FAIL"
        annotated["_certify_structural"] = grader["verdict"]
        annotated["_certify_standard_verify"] = "PASS" if std_pass else "FAIL"
        annotated["_certify_fail_reasons"] = all_reasons

        if item_passes:
            passing.append(annotated)
            per_type[fmt]["pass"] += 1
        else:
            failing.append(annotated)
            per_type[fmt]["fail"] += 1
            for reason in all_reasons:
                reason_key = reason.split(":")[0].strip()
                fail_reason_counts[reason_key] += 1

    # Stage 4: coverage report on passing items
    coverage = build_coverage_report(passing)

    # Write output JSONL
    with open(pass_path, "w", encoding="utf-8") as f:
        for item in passing:
            f.write(json.dumps(item) + "\n")

    with open(fail_path, "w", encoding="utf-8") as f:
        for item in failing:
            f.write(json.dumps(item) + "\n")

    total = len(adapted_items)
    n_pass = len(passing)
    n_fail = len(failing)
    top_fail_reasons = sorted(
        fail_reason_counts.items(), key=lambda x: x[1], reverse=True
    )[:15]

    certify_report = {
        "pipeline": "certify_pipeline.py — G5 certification",
        "stages": [
            "1. ADAPT",
            "2. STRUCTURAL GATE (anti_leak_grader.py)",
            "3. STANDARD VERIFY (CCSS Grade-5 family)",
            "4. COVERAGE REPORT",
            "5. SUMMARY",
        ],
        "total_input": total,
        "total_passing": n_pass,
        "total_failing": n_fail,
        "pass_rate_pct": round(n_pass / total * 100, 1) if total else 0.0,
        "per_type": {
            fmt: {
                "pass": counts["pass"],
                "fail": counts["fail"],
                "total": counts["pass"] + counts["fail"],
                "pass_pct": round(
                    counts["pass"] / (counts["pass"] + counts["fail"]) * 100, 1
                ) if (counts["pass"] + counts["fail"]) else 0.0,
            }
            for fmt, counts in sorted(per_type.items())
        },
        "top_fail_reasons": [
            {"reason": r, "count": c} for r, c in top_fail_reasons
        ],
        "coverage": coverage,
        "output_files": {
            "passing": pass_path,
            "failing": fail_path,
            "certify_report": report_path,
        },
        "next_step": (
            "Run passage-blind LLM check on passing.jsonl. "
            "Use anti_leak_grader.py directly (without --no-llm-prompt) "
            "or pipe each item's blind-solve prompt to a cross-family model."
        ),
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(certify_report, f, indent=2)

    return certify_report, pass_path, fail_path


# ---------------------------------------------------------------------------
# Terminal summary printer
# ---------------------------------------------------------------------------

def print_summary(certify_report, sample_n=None):
    total = certify_report["total_input"]
    n_pass = certify_report["total_passing"]
    n_fail = certify_report["total_failing"]
    rate = certify_report["pass_rate_pct"]
    per_type = certify_report["per_type"]
    top_reasons = certify_report["top_fail_reasons"]
    coverage = certify_report["coverage"]

    print()
    print("=" * 72)
    print("CERTIFY PIPELINE — G5 RESULTS")
    if sample_n is not None:
        print(f"  (sample mode: first {sample_n} items)")
    print("=" * 72)
    print()

    # Stage 2+3 gate results
    print(f"  Stage 2+3 gate: {n_pass}/{total} passed ({rate}%)")
    print()

    # Per-type breakdown
    print("  By type:")
    type_order = ["mcq", "msq", "hot-text", "match", "sequence", "ebsr"]
    printed = set()
    for fmt in type_order:
        if fmt in per_type:
            c = per_type[fmt]
            print(f"    {fmt:<12} {c['pass']}/{c['total']} ({c['pass_pct']}%)")
            printed.add(fmt)
    for fmt, c in per_type.items():
        if fmt not in printed:
            print(f"    {fmt:<12} {c['pass']}/{c['total']} ({c['pass_pct']}%)")
    print()

    # Stage 4: coverage
    if coverage["by_ccss"]:
        print("  Coverage by CCSS standard (passing items):")
        # Sort by count descending, then alphabetically
        ccss_sorted = sorted(coverage["by_ccss"].items(), key=lambda x: (-x[1], x[0]))
        for code, cnt in ccss_sorted[:20]:
            print(f"    {code:<18} {cnt:>5} items")
        if len(ccss_sorted) > 20:
            print(f"    ... ({len(ccss_sorted) - 20} more standards)")
        print()

    if coverage["by_kct"]:
        print("  Coverage by KCT tag (passing items):")
        kct_sorted = sorted(coverage["by_kct"].items(), key=lambda x: (-x[1], x[0]))
        for kct, cnt in kct_sorted[:15]:
            print(f"    {kct:<30} {cnt:>5} items")
        if len(kct_sorted) > 15:
            print(f"    ... ({len(kct_sorted) - 15} more KCT tags)")
        print()

    # Top fail reasons
    if top_reasons:
        print("  Top fail reasons:")
        for r in top_reasons[:10]:
            print(f"    [{r['count']:>5}]  {r['reason']}")
        print()

    # Output locations
    out_files = certify_report["output_files"]
    print(f"  Output written to:")
    print(f"    passing.jsonl        ({n_pass} items)")
    print(f"    failing.jsonl        ({n_fail} items)")
    print(f"    certify_report.json")
    print()
    print(
        "  Next step: passage-blind LLM check on passing.jsonl\n"
        "    python3 anti_leak_grader.py <(python3 -c\n"
        "      \"import json,sys; print(json.dumps([json.loads(l)"
        " for l in open('passing.jsonl')]))\"\n"
        "    )"
    )
    print("=" * 72)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="certify_pipeline.py",
        description="End-to-end certification pipeline for G5 course items.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_jsonl", help="Input JSONL file (one item per line).")
    parser.add_argument(
        "--schema",
        choices=["abdul", "adapted"],
        default="abdul",
        help=(
            "Input schema: 'abdul' (default, raw generator output with nested 'item') "
            "or 'adapted' (already in grader format)."
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N items.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        dest="output_dir",
        help="Output directory (default: ./certify_output/ next to input file).",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])

    input_path = args.input_jsonl
    sample_n = args.sample
    schema = args.schema
    output_dir = args.output_dir or os.path.join(
        os.path.dirname(os.path.abspath(input_path)), "certify_output"
    )

    if not os.path.exists(input_path):
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(2)

    if not os.path.exists(GRADER_SCRIPT):
        print(f"ERROR: anti_leak_grader.py not found at {GRADER_SCRIPT}", file=sys.stderr)
        sys.exit(2)

    # ---- Stage 1: ADAPT -------------------------------------------------------
    if schema == "abdul":
        if not os.path.exists(ADAPT_SCRIPT):
            print(f"ERROR: adapt_abdul.py not found at {ADAPT_SCRIPT}", file=sys.stderr)
            sys.exit(2)
        print(f"[1/5] ADAPT  ({schema} schema)  {input_path}")
        adapted_items, skip, err = load_raw_jsonl_and_adapt(input_path, sample_n)
        print(f"      Adapted: {len(adapted_items)} items | skipped: {skip} | errors: {err}")
    else:
        print(f"[1/5] ADAPT  (schema=adapted — skipping conversion)  {input_path}")
        adapted_items = load_adapted_jsonl(input_path, sample_n)
        skip = err = 0
        print(f"      Loaded: {len(adapted_items)} items")

    if not adapted_items:
        print("ERROR: no items loaded — check input JSONL format.", file=sys.stderr)
        sys.exit(1)

    # ---- Stage 2: STRUCTURAL GATE ---------------------------------------------
    print(f"[2/5] STRUCTURAL GATE  ({len(adapted_items)} items)")
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = jsonl_to_json_tempfile(adapted_items, tmpdir)
        grader_stdout, grader_rc = run_grader(json_path)

    grader_results = parse_grader_output(grader_stdout)
    n_struct_pass = sum(1 for r in grader_results if r["verdict"] == "STRUCTURAL_PASS")
    n_struct_fail = len(grader_results) - n_struct_pass
    print(f"      Structural: {n_struct_pass} pass / {n_struct_fail} fail")

    # ---- Stage 3: STANDARD VERIFICATION (reported inside merge_and_write) ----
    print(f"[3/5] STANDARD VERIFY  (CCSS Grade-5 family: {'/'.join(GRADE5_FAMILIES)})")

    # ---- Stage 4 + 5: COVERAGE + MERGE + WRITE --------------------------------
    print(f"[4/5] COVERAGE REPORT  (by type / CCSS / KCT)")
    print(f"[5/5] SUMMARY  writing output to {output_dir}/")
    certify_report, pass_path, fail_path = merge_and_write(
        adapted_items, grader_results, output_dir
    )

    print_summary(certify_report, sample_n=sample_n)

    sys.exit(0 if certify_report["total_passing"] > 0 else 1)


if __name__ == "__main__":
    main()
