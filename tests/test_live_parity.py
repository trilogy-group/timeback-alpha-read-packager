"""Live-production parity tests — the strongest evidence we have.

These run against the REAL Alpha Read - Grade 3 export (course 4c49bc61, 1077 items /
120 lessons) when it is present on disk, and SKIP cleanly when it isn't (so the suite
stays self-contained). They are the ground truth behind every "confirmed from live"
claim in the docs: the canonical primaryApp value, the resource shape, and that arpack
parses every item in the live export we sampled with zero blank prompts / zero unresolvable answer keys.
"""
import glob
import json
import os
import shutil

import pytest

import arpack
import qti_dir_resolver


# ════════════════════════════ canonical course values ════════════════════════════
def _course(raw_path):
    d = json.load(open(raw_path))
    c = d["course"]
    if isinstance(c, dict) and "course" in c:
        c = c["course"]
    return c


def test_live_root_primaryapp_is_alpha_read(live_course_raw):
    """THE proactively-resolved team question: 'alpha_read' is the canonical applications.sourcedId."""
    c = _course(live_course_raw)
    assert c["primaryApp"] == "alpha_read"
    # and it's exactly what arpack emits at root
    assert arpack.COURSE_MARKERS["primaryApp"] == "alpha_read"


def test_live_metadata_markers_match_what_we_emit(live_course_raw):
    md = _course(live_course_raw)["metadata"]
    assert md["primaryApp"] == "alpha_read"
    assert md["isAlphaRead"] is True
    assert md["publishStatus"] == "published"
    assert md["timebackVisible"] is True
    # arpack's assembled sample mirrors all of these
    sample = arpack.assemble(arpack.SAMPLE)["course"]["metadata"]
    for k in ("primaryApp", "isAlphaRead", "publishStatus", "timebackVisible"):
        assert sample[k] == md[k]


def test_live_metrics_is_server_derived(live_course_raw):
    # live carries metrics{}; we must NEVER author it (validator rejects authored metrics).
    md = _course(live_course_raw)["metadata"]
    assert "metrics" in md, "live course has server-derived metrics"
    assert "metrics" not in arpack.assemble(arpack.SAMPLE)["course"]["metadata"]


# ════════════════════════════ live resource shape parity ════════════════════════════
def test_live_resource_shape(live_export):
    sample = glob.glob(os.path.join(live_export, "resources", "article_*.json"))
    if not sample:
        pytest.skip("no live resources on disk")
    r = json.load(open(sample[0]))["resource"]
    md = r["metadata"]
    # the invariants arpack reproduces
    assert md["lessonType"] == "alpha-read-article"
    assert md["type"] == "qti" and md["subType"] == "qti-test"
    assert md["sourcedId"] == r["sourcedId"]
    assert r["vendorResourceId"].isdigit(), "vendorResourceId is the bare number, live-confirmed"
    assert r["importance"] == "primary"
    assert "url" in md, "url lives INSIDE metadata (top-level url is silently dropped)"


# ════════════════════════════ full live-export parse (the headline check) ════════════════════════════
def test_parse_all_live_items_no_blanks_no_bad_keys(live_export):
    item_files = glob.glob(os.path.join(live_export, "items", "*.json"))
    if not item_files:
        pytest.skip("no live items on disk")
    assert len(item_files) >= 1000, f"expected ~1077 live items, found {len(item_files)}"
    blank_prompt, bad_key, parsed = [], [], 0
    for f in item_files:
        d = json.load(open(f))
        raw = d.get("rawXml")
        if not raw:
            continue
        p = arpack.from_qti_xml(raw)
        parsed += 1
        if not (p["prompt"] or "").strip():
            blank_prompt.append(os.path.basename(f))
        # answer key must resolve for choice/ebsr items
        try:
            arpack.adapt_qti_item(p)
        except ValueError:
            bad_key.append(os.path.basename(f))
    assert parsed >= 1000, f"only parsed {parsed} live items"
    assert blank_prompt == [], f"blank prompts in: {blank_prompt[:10]}"
    assert bad_key == [], f"unresolvable answer keys in: {bad_key[:10]}"


# ════════════════════════════ live loose-XML round-trip through qti_dir_resolver ════════════════
def test_live_lesson_roundtrips_to_valid_package(live_export, tmp_path):
    """Reconstruct one real lesson's loose XML from the export, group it via qti_dir_resolver,
    assemble, and require arpack.validate to PASS. Real data, full round-trip, zero edits."""
    test_path = os.path.join(live_export, "tests", "article_3000001.json")
    if not os.path.isfile(test_path):
        pytest.skip("live test article_3000001 not present")
    test = json.load(open(test_path))
    item_ids = [r["identifier"]
                for s in test["qti-test-part"][0]["qti-assessment-section"]
                for r in s["qti-assessment-item-ref"]]

    out = tmp_path / "loose"
    out.mkdir()
    stim_ids = set()
    import re
    for iid in item_ids:
        d = json.load(open(os.path.join(live_export, "items", iid + ".json")))
        (out / f"{iid}.xml").write_text(d["rawXml"])
        m = re.search(r'qti-assessment-stimulus-ref[^>]*href="([^"]*)"', d["rawXml"])
        if m:
            stim_ids.add(m.group(1).rsplit("/", 1)[-1].replace(".xml", ""))
    for sid in stim_ids:
        cand = os.path.join(live_export, "stimuli", sid + ".json")
        if os.path.isfile(cand):
            (out / f"{sid}.xml").write_text(json.load(open(cand))["rawXml"])

    res = qti_dir_resolver.from_qti_dir(str(out))
    assert len(res["lessons"]) == 1
    lesson = res["lessons"][0]
    assert 3 <= len(lesson["guiding"]) <= 6
    assert len(lesson["quiz"]) == 4
    skel = {
        "course": {"title": "STAN-PROBE-DELETEME live", "courseCode": "ALPHAREAD-PROBE",
                   "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
        "units": [{"title": "Live lesson", "sortOrder": 1, "lessons": res["lessons"]}],
    }
    pkg = arpack.assemble(skel)
    assert arpack.validate(pkg) == [], "real live lesson must round-trip to a valid package"
