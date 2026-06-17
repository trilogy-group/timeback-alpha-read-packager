#!/usr/bin/env python3
"""
course_orchestrator — ONE-COMMAND autonomous Grade-3 Reading course builder.

Sits ON TOP of the packager (imports arpack, never edits it). One command, whole pipeline:

    python3 course_orchestrator.py <skeleton.json|table.csv> <out/>

PIPELINE
  1. read skeleton            -> skeleton_adapter handles Anirudh's CSV/table -> units[].lessons[];
                                 an already-nested arpack skeleton is passed through as-is.
  2. FAN OUT per lesson (parallel, threads — lessons are independent):
       build requests         -> gen_request.build_lesson_request(lesson, unit)
       generate               -> generator_client.generate(req, backend)  (Mayank-shaped QTI; stub
                                 by default — serves Mayank's REAL fixture, id-rewritten)
       parse via arpack       -> from_qti_xml / from_qti_stimulus_xml + adapt_qti_item (the single
                                 source of truth for parsing + the fail-closed answer-key bridge)
       RE-STAMP ids           -> the orchestrator owns FINAL, collision-free, deterministic ids
                                 (see _stamp_ids: the stub's id minting truncates and collides across
                                 sections/lessons; arpack.validate does NOT catch that, a real push
                                 would — so we fix it here, the only writer, without touching the
                                 generator). ids derive from (vendorId, role, index) -> idempotent.
       validate (hook)        -> InceptBench quality hook (stub, fail-open) + per-lesson shape gate
       collect                -> lesson {guiding[], quiz[]} in arpack.assemble's exact input shape
  3. arpack.assemble(skeleton+lessons) -> arpack.validate -> arpack.emit(out/)   (validate = hard gate)
  4. write out/RUN_REPORT.md  (per-lesson status, counts, final validate result)

PROPERTIES (all four, by construction)
  * fan-out per lesson (parallel)  — ThreadPoolExecutor.
  * idempotent                     — deterministic, collision-free ids end-to-end (request_ids ->
                                     re-stamped leaf ids), so a re-run converges to the same course.json
                                     + items byte-for-byte (asserted by test_orchestrator_idempotent_byte_for_byte).
  * fail-closed                    — a lesson that fails its per-lesson shape/parse gate is REPORTED
                                     and EXCLUDED from assembly, never silently shipped; the final
                                     arpack.validate is the hard gate — NOTHING emits if it fails.
  * draft-safe                     — the course title is force-prefixed STAN-PROBE-DELETEME (matches
                                     arpack.THROWAWAY_PREFIX) so any later push lands as a throwaway.

PLUGGABLE GENERATOR: generator_client.generate(req, backend) has two backends. The stub backend
  (default) runs the FULL pipeline on Mayank's real-shaped QTI today; the 'real' backend is a
  documented, not-yet-wired one-line swap (GEN_BACKEND=real or --backend real). The orchestrator never
  branches on backend internals — it just calls generate(); the return shape is identical, so the swap
  touches nothing here.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---- single import surface: arpack + its siblings (NEVER edited, only imported) ------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import arpack                       # noqa: E402  THE packager — do not edit, only import
import gen_request                  # noqa: E402  r2 request builder (Stream S1)
import generator_client            # noqa: E402  pluggable Mayank-shaped generator (Stream S2)

try:
    from skeleton_adapter import from_skeleton_table  # noqa: E402
except Exception:                                     # adapter optional; nested skeletons still work
    from_skeleton_table = None

DRAFT_PREFIX = arpack.THROWAWAY_PREFIX                 # "STAN-PROBE-DELETEME" — push safety rail
GEN_BACKEND = os.environ.get("GEN_BACKEND", "stub").lower()
MAX_WORKERS = int(os.environ.get("ORCH_WORKERS", "8"))


# ───────────────────────────── 1. read skeleton ──────────────────────────────────
def load_skeleton(path_or_obj):
    """Return a nested arpack skeleton {"course": {...}, "units": [...]}.

    Accepts (a) an already-nested arpack skeleton (units carry lessons) -> passed through;
    (b) Anirudh's expedition TABLE (CSV/JSON path, CSV string, or list[dict]) -> adapted via
    skeleton_adapter into unit shells, wrapped with a default course header. The course title is
    ALWAYS forced to start with the draft prefix (draft-safe)."""
    obj = path_or_obj
    if isinstance(path_or_obj, str) and os.path.isfile(path_or_obj):
        with open(path_or_obj, encoding="utf-8-sig") as fh:
            txt = fh.read()
        try:
            obj = json.loads(txt)
        except json.JSONDecodeError:
            obj = txt                                 # a raw CSV file -> let the adapter parse it

    if isinstance(obj, dict) and isinstance(obj.get("units"), list) \
            and obj["units"] and isinstance(obj["units"][0], dict) and "lessons" in obj["units"][0]:
        skel = {"course": obj.get("course") or {}, "units": obj["units"]}
    else:
        if from_skeleton_table is None:
            raise RuntimeError("skeleton_adapter unavailable and input is not a nested skeleton")
        units = from_skeleton_table(obj)
        course = (obj.get("course") if isinstance(obj, dict) else None) or {}
        skel = {"course": course, "units": units}

    skel["course"] = _draft_course_header(skel.get("course") or {})
    # normalise unit shells: every unit needs title + sortOrder + lessons[]
    norm_units = []
    for n, u in enumerate(skel["units"], 1):
        sort_order = u.get("sortOrder", n)
        lessons = u.get("lessons") or []
        # FAIL-CLOSED GUARANTEE: every lesson MUST carry a vendorId before fan-out. The fan-out
        # futures map and the assembly rebuild both key on l["vendorId"] OUTSIDE the per-lesson
        # try/except, so a hand-authored/partner nested skeleton missing vendorId would crash the
        # whole run instead of reporting+excluding one lesson. skeleton_adapter always assigns
        # vendorIds, so this only bites raw nested skeletons — we mint a deterministic, collision-free
        # one here (stable per (sortOrder, position)) so the rest of the pipeline's vendorId
        # assumptions hold and re-runs converge.
        for i, l in enumerate(lessons):
            if isinstance(l, dict) and not l.get("vendorId"):
                l["vendorId"] = f"auto_{sort_order}_{i}"
        norm_units.append({
            "title": u.get("title") or f"Unit {n}",
            "sortOrder": sort_order,
            "lessons": lessons,
            **{k: v for k, v in u.items() if k in ("band", "genre", "lexile_band", "coverage")},
        })
    skel["units"] = norm_units
    return skel


def _draft_course_header(course):
    """Fill a complete, draft-prefixed course header (arpack.assemble requires these keys)."""
    title = course.get("title") or "Reading G3"
    if not str(title).startswith(DRAFT_PREFIX):
        title = f"{DRAFT_PREFIX} {title}"
    header = {
        "title": title,
        "courseCode": course.get("courseCode", "ALPHAREAD-PROBE"),
        "grades": course.get("grades", ["3"]),
        "subjects": course.get("subjects", ["Reading"]),
        "org_sourcedId": course.get("org_sourcedId", "powerpath-ui-org"),
        "contentGrade": course.get("contentGrade", "3"),
    }
    if course.get("sourcedId"):
        header["sourcedId"] = course["sourcedId"]
    return header


# ───────────────────────── InceptBench validation hook (stub) ─────────────────────
def inceptbench_check(item, request):
    """STUB hook for InceptBench item-quality validation. Today: a no-op pass with a clear seam.
    REAL: POST the parsed item + r2 request to InceptBench, return its verdict. Wire here later.
    Returns (ok: bool, notes: list[str]). FAIL-OPEN on the stub (it's a quality gate, not the shape
    gate; the shape gate is arpack's and stays fail-closed)."""
    return True, []


# ───────────────────────── deterministic final ids (the integrator's job) ─────────
def _stamp_ids(vendor_id, role, idx, item, stim=None):
    """Assign FINAL, collision-free, deterministic ids and couple the item<->stimulus refs.

    WHY THE ORCHESTRATOR OWNS THIS: generator_client mints ids by truncating the request key to 16
    chars, so 'lesson_X_guiding1/2/3' all collapse to one id, and ids collide ACROSS lessons too.
    arpack.validate does NOT catch duplicate item identifiers (it dedupes by id and every ref still
    resolves) — but a real OneRoster/QTI push would reject the package. We are the only writer, so we
    re-stamp here from (vendorId, role, index): unique within AND across lessons, stable on re-run."""
    iid = f"art{vendor_id}_{ 'g' if role == 'guiding' else 'q'}{idx}"
    item["identifier"] = iid
    if stim is not None:
        sid = f"stim_{vendor_id}_{idx}"
        stim["identifier"] = sid
        item["stimulus_id"] = sid
    else:
        item["stimulus_id"] = None
    return item, stim


# ───────────────────────── 2. fan-out: one lesson end-to-end ──────────────────────
def _process_lesson(unit, lesson, backend):
    """Build requests -> generate -> parse(arpack) -> re-stamp ids -> collect into {guiding[], quiz[]}.

    Returns a per-lesson result dict. FAIL-CLOSED: any generation/parse/answer-key failure marks the
    lesson 'failed' with reasons and excludes it from assembly. A lesson is 'ok' only if it yields
    3-6 valid guiding (each with a passage) + EXACTLY 4 valid quiz items."""
    vid = lesson["vendorId"]
    res = {"vendorId": vid, "title": lesson.get("title"), "status": "ok",
           "guiding_built": 0, "quiz_built": 0, "errors": [], "incept_notes": []}
    try:
        # honour a per-lesson guiding_count when the skeleton asks for one (clamped by gen_request
        # to [GUIDING_MIN, GUIDING_MAX]); else gen_request's default. quiz is always 4 (the contract).
        g_want = lesson.get("guiding_count")
        bundle = (gen_request.build_lesson_request(lesson, unit, guiding_count=int(g_want))
                  if g_want else gen_request.build_lesson_request(lesson, unit))
    except Exception as e:
        res["status"] = "failed"
        res["errors"].append(f"build_lesson_request failed: {e}")
        return res

    guiding, quiz = [], []
    g_n = q_n = 0
    for req in bundle["items"]:
        role = req.get("role") or ("guiding" if (req.get("stimulus") or {}).get("ref") else "quiz")
        try:
            gen = generator_client.generate(req, backend=backend)   # Mayank-shaped BuildResult
        except Exception as e:
            res["errors"].append(f"{req.get('request_id')}: generate failed: {e}")
            continue
        try:
            parsed = arpack.from_qti_xml(gen["item_xml"])          # single source of truth for parsing
            item = arpack.adapt_qti_item(parsed)                   # fail-closed bridge: raises on bad key
        except Exception as e:
            res["errors"].append(f"{req.get('request_id')}: parse/adapt failed: {e}")
            continue

        ok, notes = inceptbench_check(item, req)                   # quality hook (fail-open stub)
        if notes:
            res["incept_notes"].extend(f"{req.get('request_id')}: {n}" for n in notes)

        if role == "guiding":
            g_n += 1
            stim_xml = gen.get("stimulus_xml")
            if not stim_xml:
                res["errors"].append(f"{req.get('request_id')}: guiding item has no stimulus (fail-closed)")
                continue
            try:
                stim = arpack.from_qti_stimulus_xml(stim_xml)
            except Exception as e:
                res["errors"].append(f"{req.get('request_id')}: stimulus parse failed: {e}")
                continue
            _stamp_ids(vid, "guiding", g_n, item, stim)            # final unique ids, coupled
            guiding.append({"stimulus": {"title": stim["title"], "html": stim["html"],
                                         "identifier": stim["identifier"]},
                            "item": item})
        else:
            q_n += 1
            _stamp_ids(vid, "quiz", q_n, item, None)               # quiz items carry NO stimulus-ref
            quiz.append(item)

    # fail-closed lesson-shape gate (mirrors arpack's validator BEFORE assembly)
    if not (arpack.GUIDING_MIN <= len(guiding) <= arpack.GUIDING_MAX):
        res["errors"].append(f"guiding count {len(guiding)} outside {arpack.GUIDING_MIN}-{arpack.GUIDING_MAX}")
    if len(quiz) != arpack.QUIZ_ITEMS:
        res["errors"].append(f"quiz count {len(quiz)} != {arpack.QUIZ_ITEMS}")

    res["guiding_built"], res["quiz_built"] = len(guiding), len(quiz)
    if res["errors"]:
        res["status"] = "failed"
        return res

    res["lesson"] = {
        "vendorId": vid,
        "title": lesson.get("title") or f"Lesson {vid}",
        "xp": lesson.get("xp", 12),
        "grade": lesson.get("grade", "3"),
        "measuredReadingGrade": lesson.get("measuredReadingGrade", lesson.get("grade", "3")),
        "guiding": guiding, "quiz": quiz,
    }
    if lesson.get("lexileLevel"):
        res["lesson"]["lexileLevel"] = lesson["lexileLevel"]
    return res


# ───────────────────────── orchestrate: fan out, assemble, emit ───────────────────
def run(skeleton, outdir, *, workers=MAX_WORKERS, backend=None, emit=True):
    """Full pipeline. Returns (report_dict, package|None). Emits ONLY if the FINAL arpack.validate
    passes (fail-closed); a failing validate emits nothing and the report says why."""
    backend = (backend or GEN_BACKEND).lower()
    skel = load_skeleton(skeleton)
    units = skel["units"]

    jobs = [(u, l) for u in units for l in u["lessons"]]
    lesson_results = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(_process_lesson, u, l, backend): (u["sortOrder"], l["vendorId"])
                for u, l in jobs}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                lesson_results[key] = fut.result()
            except Exception as e:                                # a worker blew up -> record, never crash the run
                lesson_results[key] = {"vendorId": key[1], "status": "failed",
                                       "errors": [f"worker crashed: {e}"], "title": None,
                                       "guiding_built": 0, "quiz_built": 0, "incept_notes": []}

    # rebuild the skeleton with ONLY the lessons that passed (fail-closed: failures dropped + reported)
    assembled_units, per_lesson = [], []
    for u in units:
        kept = []
        for l in u["lessons"]:
            r = lesson_results.get((u["sortOrder"], l["vendorId"]), {
                "status": "failed", "errors": ["no result"], "vendorId": l["vendorId"],
                "title": l.get("title"), "guiding_built": 0, "quiz_built": 0, "incept_notes": []})
            per_lesson.append({"unit": u["title"], "sortOrder": u["sortOrder"], **r})
            if r["status"] == "ok" and r.get("lesson"):
                kept.append(r["lesson"])
        if kept:
            assembled_units.append({"title": u["title"], "sortOrder": u["sortOrder"], "lessons": kept})

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "course_title": skel["course"]["title"],
        "backend": backend,
        "units_in": len(units), "lessons_in": len(jobs),
        "lessons_ok": sum(1 for r in per_lesson if r["status"] == "ok"),
        "lessons_failed": sum(1 for r in per_lesson if r["status"] != "ok"),
        "per_lesson": sorted(per_lesson, key=lambda r: (r["sortOrder"], r["vendorId"])),
        "assembled": None, "validate": None, "emitted": None, "outdir": outdir,
    }

    if not assembled_units:
        report["fatal"] = "no lesson passed validation — nothing to assemble (fail-closed)"
        return report, None

    pkg = arpack.assemble({"course": skel["course"], "units": assembled_units})
    errs = arpack.validate(pkg)                                   # THE hard gate
    report["assembled"] = {"units": len(pkg["components"]), "lessons": len(pkg["resources"]),
                           "stimuli": len(pkg["qti"]["stimuli"]), "items": len(pkg["qti"]["items"]),
                           "tests": len(pkg["qti"]["tests"])}
    report["validate"] = {"ok": not errs, "errors": errs}

    # belt-and-suspenders uniqueness audit (arpack.validate does NOT check this): every leaf id unique
    item_ids = [i["identifier"] for i in pkg["qti"]["items"]]
    stim_ids = [s["identifier"] for s in pkg["qti"]["stimuli"]]
    dupes = [x for x in set(item_ids) if item_ids.count(x) > 1] + \
            [x for x in set(stim_ids) if stim_ids.count(x) > 1]
    report["unique_ids"] = {"items": len(set(item_ids)) == len(item_ids),
                            "stimuli": len(set(stim_ids)) == len(stim_ids),
                            "duplicates": dupes}

    if errs:
        report["fatal"] = "final arpack.validate FAILED — nothing emitted (fail-closed)"
        return report, pkg

    if emit:
        report["emitted"] = arpack.emit(pkg, outdir)             # the integrator's write happens here
    return report, pkg


# ───────────────────────── 4. RUN_REPORT.md ──────────────────────────────────────
def render_run_report(report):
    """Render RUN_REPORT.md from a run() report dict (returned as a string; main() writes it)."""
    L = []
    A = L.append
    v = report.get("validate") or {}
    overall = "PASS" if (v.get("ok") and not report.get("fatal")) else "FAIL"
    A(f"# RUN_REPORT — {report['course_title']}")
    A("")
    A(f"- generated_at: `{report['generated_at']}`")
    A(f"- generator backend: `{report['backend']}`")
    A(f"- outdir: `{report['outdir']}`")
    A(f"- **overall: {overall}**" + (f"  (`{report['fatal']}`)" if report.get("fatal") else ""))
    A("")
    A("## Counts")
    A(f"- units in / lessons in: {report['units_in']} / {report['lessons_in']}")
    A(f"- lessons ok / failed: **{report['lessons_ok']} / {report['lessons_failed']}**")
    if report.get("assembled"):
        a = report["assembled"]
        A(f"- assembled: {a['units']} units · {a['lessons']} lessons · "
          f"{a['stimuli']} stimuli · {a['items']} items · {a['tests']} tests")
    if report.get("validate") is not None:
        A(f"- final arpack.validate: **{'PASS (0 errors)' if v.get('ok') else 'FAIL'}**"
          + ("" if v.get("ok") else f" ({len(v.get('errors', []))} errors)"))
    if report.get("unique_ids") is not None:
        uq = report["unique_ids"]
        A(f"- leaf-id uniqueness: items={'OK' if uq['items'] else 'DUPES'}, "
          f"stimuli={'OK' if uq['stimuli'] else 'DUPES'}"
          + (f" — duplicates: {uq['duplicates']}" if uq.get("duplicates") else ""))
    if report.get("emitted"):
        A(f"- emitted manifest: `{json.dumps(report['emitted'])}`")
    A("")
    A("## Per-lesson")
    A("")
    A("| unit | sortOrder | vendorId | title | status | guiding | quiz | notes |")
    A("|---|---|---|---|---|---|---|---|")
    for r in report["per_lesson"]:
        badge = "ok" if r["status"] == "ok" else "FAILED"
        notes = "; ".join(r.get("errors", []))[:120] or ("; ".join(r.get("incept_notes", []))[:120] or "—")
        A(f"| {r.get('unit', '')} | {r['sortOrder']} | {r['vendorId']} | "
          f"{(r.get('title') or '')[:40]} | {badge} | {r.get('guiding_built', 0)} | "
          f"{r.get('quiz_built', 0)} | {notes} |")
    A("")
    if not v.get("ok") and v.get("errors"):
        A("## Final validation errors (fail-closed — nothing emitted)")
        for e in v["errors"]:
            A(f"- {e}")
        A("")
    A("---")
    A(f"_pipeline: skeleton -> fan-out(build -> generate -> parse -> stamp-ids -> validate -> collect) "
      f"-> assemble -> validate -> emit. backend=`{report['backend']}` "
      f"(stub serves Mayank's real fixture; real backend is a one-line swap)._")
    return "\n".join(L) + "\n"


# ───────────────────────── CLI ───────────────────────────────────────────────────
def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print("usage: course_orchestrator.py <skeleton.json|table.csv> <out/> [--backend stub|real]")
        return 0
    skeleton = argv[1]
    outdir = "out"
    backend = None
    rest = argv[2:]
    i = 0
    while i < len(rest):
        if rest[i] == "--backend" and i + 1 < len(rest):
            backend = rest[i + 1]; i += 2
        else:
            outdir = rest[i]; i += 1

    report, _pkg = run(skeleton, outdir, backend=backend)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "RUN_REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write(render_run_report(report))
    ok = bool((report.get("validate") or {}).get("ok")) and not report.get("fatal")
    print(("BUILD PASS -> " + outdir) if ok else "BUILD FAILED (see RUN_REPORT.md)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
