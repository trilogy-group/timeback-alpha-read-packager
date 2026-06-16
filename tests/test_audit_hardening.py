"""Audit-hardening regression locks (A1 BLOCKER + SHOULDs).

Three defects the parallel audit surfaced, each now fixed and pinned here so they
cannot silently regress:

  1. [BLOCKER] course_orchestrator crashed with an uncaught KeyError on a nested
     skeleton whose lesson lacked `vendorId` (the fan-out futures key + the assembly
     rebuild both read l["vendorId"] OUTSIDE the per-lesson try/except). That violates
     the documented fail-closed guarantee. Now load_skeleton mints a deterministic
     vendorId so the run completes and the package is valid.

  2. [SHOULD] arpack.validate() did NOT detect DUPLICATE leaf ids — the only coupling
     check was a SET comparison that cannot see count collisions. A real OneRoster/QTI
     push rejects duplicate item/stimulus/test/resource ids. Now validate() fail-closes
     on them.

  3. [SHOULD] `arpack build <shell_skeleton>` threw a raw KeyError traceback instead of
     a clean message. A shell skeleton (guiding_count, no items) is the ORCHESTRATOR's
     input. Now the build branch emits a clear redirect and returns 1.
"""
import copy
import io
import json
import os
from contextlib import redirect_stdout

import arpack
import course_orchestrator


# ═══════════════ 1. [BLOCKER] missing vendorId must NOT crash the run ═══════════════
def test_load_skeleton_mints_vendorid_when_absent(tmp_path):
    skel = {
        "course": {"title": "x"},
        "units": [{"title": "U", "sortOrder": 1, "lessons": [
            {"title": "no-vendor-A", "guiding_count": 3},   # NO vendorId
            {"title": "no-vendor-B"},                        # NO vendorId
        ]}],
    }
    loaded = course_orchestrator.load_skeleton(skel)
    vids = [l["vendorId"] for u in loaded["units"] for l in u["lessons"]]
    assert all(vids), "every lesson must carry a vendorId after load_skeleton"
    assert len(vids) == len(set(vids)), "minted vendorIds must be unique"


def test_load_skeleton_minted_vendorid_is_deterministic():
    skel = {"course": {"title": "x"},
            "units": [{"title": "U", "sortOrder": 7, "lessons": [{"title": "L"}]}]}
    a = course_orchestrator.load_skeleton(copy.deepcopy(skel))
    b = course_orchestrator.load_skeleton(copy.deepcopy(skel))
    assert a["units"][0]["lessons"][0]["vendorId"] == b["units"][0]["lessons"][0]["vendorId"]


def test_orchestrator_run_does_not_crash_on_missing_vendorid(tmp_path):
    """The whole point of the BLOCKER fix: a vendorId-less nested skeleton RUNS to a
    valid package instead of crashing with KeyError: 'vendorId'."""
    skel = tmp_path / "novendor.json"
    skel.write_text(json.dumps({
        "course": {"title": "Reading G3"},
        "units": [{"title": "Animals", "sortOrder": 1, "band": "A", "lessons": [
            {"title": "Mammals", "guiding_count": 3},   # NO vendorId — would KeyError pre-fix
        ]}],
    }))
    report, pkg = course_orchestrator.run(str(skel), str(tmp_path / "out"))
    assert pkg is not None, f"run should produce a package, report={report.get('fatal')}"
    assert report["validate"]["ok"], report["validate"]["errors"]
    assert report["unique_ids"]["items"] and report["unique_ids"]["stimuli"]


# ═══════════════ 2. [SHOULD] validate() must reject DUPLICATE leaf ids ═══════════════
def test_duplicate_item_id_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    # force two items to share an identifier (a set-comparison cannot see this)
    pkg["qti"]["items"][1]["identifier"] = pkg["qti"]["items"][0]["identifier"]
    errs = arpack.validate(pkg)
    assert any("duplicate item id" in e for e in errs), errs


def test_duplicate_stimulus_id_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["qti"]["stimuli"][1]["identifier"] = pkg["qti"]["stimuli"][0]["identifier"]
    assert any("duplicate stimulus id" in e for e in arpack.validate(pkg))


def test_no_false_duplicate_on_clean_package(sample_pkg):
    # the canonical sample has all-unique ids: NO duplicate error may appear.
    assert not any("duplicate" in e for e in arpack.validate(sample_pkg))


def test_duplicate_resource_and_test_id_fails_closed():
    # two lessons sharing a vendorId -> duplicate resource id AND duplicate test id.
    skel = {
        "course": {"title": "STAN-PROBE-DELETEME Dup", "courseCode": "C",
                   "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "o"},
        "units": [{"title": "U", "sortOrder": 1, "lessons": [
            _materialized_lesson(7777), _materialized_lesson(7777),   # same vendorId twice
        ]}],
    }
    pkg = arpack.assemble(skel)
    errs = arpack.validate(pkg)
    assert any("duplicate resource id" in e for e in errs), errs
    assert any("duplicate test id" in e for e in errs), errs


def _materialized_lesson(vid):
    g = lambda n: {"stimulus": {"title": f"S{n}", "html": f"<div><p>passage {n}</p></div>"},
                   "item": {"title": f"Q{n}", "prompt": f"q{n}?",
                            "choices": ["a", "b", "c", "d"], "correct_index": 0}}
    q = lambda n: {"title": f"QZ{n}", "prompt": f"qz{n}?",
                   "choices": ["a", "b", "c", "d"], "correct_index": 0}
    return {"vendorId": vid, "title": f"L{vid}", "xp": 12,
            "guiding": [g(1), g(2), g(3)], "quiz": [q(1), q(2), q(3), q(4)]}


# ═══════════════ 3. [SHOULD] `arpack build` on a SHELL skeleton -> clean message ═══════════════
def test_arpack_build_shell_skeleton_clean_message(examples_dir, tmp_path):
    shell = os.path.join(examples_dir, "sample_skeleton.json")   # lesson shells, no items
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = arpack.main(["arpack.py", "build", shell, str(tmp_path / "out")])
    out = buf.getvalue()
    assert rc == 1, "a shell skeleton must fail the build branch cleanly"
    assert "UNMATERIALIZED" in out and "course_orchestrator.py" in out
    assert "Traceback" not in out and "KeyError" not in out
    # and it must NOT have emitted anything
    assert not os.path.isdir(os.path.join(str(tmp_path), "out", "oneroster"))


def test_assemble_shell_lesson_does_not_keyerror():
    """assemble() itself reads guiding/quiz defensively now (API callers, not just CLI)."""
    skel = {"course": {"title": "STAN-PROBE-DELETEME x", "courseCode": "C",
                       "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "o"},
            "units": [{"title": "U", "sortOrder": 1,
                       "lessons": [{"vendorId": 1, "title": "shell"}]}]}   # no guiding/quiz
    pkg = arpack.assemble(skel)        # must NOT raise KeyError
    # it produces a (degenerate) package; validate then fail-closes on the empty shape.
    errs = arpack.validate(pkg)
    assert errs, "a shell-only lesson must fail validation (degenerate, no items)"
