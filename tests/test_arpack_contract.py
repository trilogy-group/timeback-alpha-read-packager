"""Contract + validator tests for arpack — the fail-closed gate that decides what ships.

Every invariant here was confirmed against the live production export (course 4c49bc61,
1077 items / 120 lessons) and/or Ilma's authoritative timeback skill. A regression in any
of these is a SHIP BLOCKER.
"""
import copy

import pytest

import arpack


# ───────────────────────── the canonical sample assembles + validates ─────────────────────────
def test_selftest_sample_validates_clean(sample_pkg):
    errs = arpack.validate(sample_pkg)
    assert errs == [], f"canonical sample must validate clean, got: {errs}"


def test_sample_counts(sample_pkg):
    assert len(sample_pkg["components"]) == 1          # 1 unit
    assert len(sample_pkg["resources"]) == 1           # 1 lesson
    assert len(sample_pkg["qti"]["tests"]) == 1
    assert len(sample_pkg["qti"]["stimuli"]) == 3      # 3 guiding stimuli
    assert len(sample_pkg["qti"]["items"]) == 7        # 3 guiding + 4 quiz


# ───────────────────────── Ramish breaking change (>=2026-06-30) forward-compat ────────────────
# ROOT course.primaryApp is the ONE authoritative ownership setter and MUST equal the exact
# active applications.sourcedId "alpha_read" (confirmed from the live export). metadata.primaryApp
# is INERT and must be forward-safe to DROP entirely.
def _pa_errs(pkg):
    return [e for e in arpack.validate(pkg) if "primaryApp" in e]


def test_root_primaryapp_canonical_passes(sample_pkg):
    assert _pa_errs(sample_pkg) == []


@pytest.mark.parametrize("bad", [None, "", "AlphaRead", "alpha-read", "ALPHA_READ", " alpha_read", 123, [], {}])
def test_root_primaryapp_non_canonical_fails_closed(sample_pkg, bad):
    pkg = copy.deepcopy(sample_pkg)
    pkg["course"]["primaryApp"] = bad
    assert _pa_errs(pkg), f"root primaryApp={bad!r} must be rejected (forward-compat hard gate)"


def test_root_primaryapp_missing_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    del pkg["course"]["primaryApp"]
    assert _pa_errs(pkg), "absent root primaryApp must fail (null clears ownership -> 422)"


def test_metadata_primaryapp_dropped_is_forward_safe(sample_pkg):
    """The CRUX of forward-compatibility: dropping inert metadata.primaryApp must NOT error."""
    pkg = copy.deepcopy(sample_pkg)
    pkg["course"]["metadata"].pop("primaryApp", None)
    assert arpack.validate(pkg) == [], "dropping inert metadata.primaryApp must stay valid"


def test_metadata_primaryapp_present_but_wrong_is_flagged(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["course"]["metadata"]["primaryApp"] = "stale_old_app"
    assert _pa_errs(pkg), "a present-and-wrong inert metadata.primaryApp should be flagged"


def test_we_emit_canonical_alpha_read(sample_pkg):
    # We must never emit null/empty; we must emit exactly "alpha_read" at root.
    assert sample_pkg["course"]["primaryApp"] == "alpha_read"
    assert sample_pkg["course"]["metadata"]["primaryApp"] == "alpha_read"


# ───────────────────────── course markers + publish flags ──────────────────────────────────────
@pytest.mark.parametrize("key,good", [
    ("isAlphaRead", True), ("publishStatus", "published"), ("timebackVisible", True),
])
def test_required_markers_fail_closed(sample_pkg, key, good):
    pkg = copy.deepcopy(sample_pkg)
    pkg["course"]["metadata"][key] = "WRONG"
    assert any(key in e for e in arpack.validate(pkg))
    pkg["course"]["metadata"][key] = good
    assert arpack.validate(pkg) == []


def test_metadata_metrics_must_not_be_authored(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["course"]["metadata"]["metrics"] = {"totalXp": 999}
    assert any("metrics" in e for e in arpack.validate(pkg)), \
        "metrics is server-derived; authoring it must be rejected"


# ───────────────────────── OneRoster resource shape (live-verified) ─────────────────────────────
def test_resources_wrapped_and_id_coupled(sample_pkg):
    for entry in sample_pkg["resources"]:
        assert "resource" in entry, "resource must be wrapped in {'resource': {...}}"
        r = entry["resource"]
        assert "roles" in r
        assert r["metadata"]["sourcedId"] == r["sourcedId"]
        assert r["metadata"]["lessonType"] == "alpha-read-article"
        assert r["metadata"]["url"].endswith(r["sourcedId"])
        # live-verified: vendorResourceId is the NUMBER ONLY (no article_ prefix)
        assert r["vendorResourceId"].isdigit(), "vendorResourceId must be the bare number"


def test_resource_unwrapped_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["resources"][0] = pkg["resources"][0]["resource"]   # unwrap it
    assert any("wrapped" in e or "resource" in e.lower() for e in arpack.validate(pkg))


def test_resource_lessontype_wrong_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["resources"][0]["resource"]["metadata"]["lessonType"] = "quiz"
    assert any("lessonType" in e for e in arpack.validate(pkg))


def test_resource_ids_equal_test_ids(sample_pkg):
    res_ids = {e["resource"]["sourcedId"] for e in sample_pkg["resources"]}
    test_ids = {t["identifier"] for t in sample_pkg["qti"]["tests"]}
    assert res_ids == test_ids


# ───────────────────────── stimulus tag vocab + media ban + S3 img ──────────────────────────────
def test_media_tag_banned(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["qti"]["stimuli"][0]["content"] = "<div><video src='x'></video></div>"
    assert any("media tag" in e for e in arpack.validate(pkg))


def test_unknown_tag_banned(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["qti"]["stimuli"][0]["content"] = "<div><marquee>hi</marquee></div>"
    assert any("outside allowed vocab" in e for e in arpack.validate(pkg))


def test_mathml_allowed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["qti"]["stimuli"][0]["content"] = (
        "<div><p>Water is <math><mrow><msub><mi>H</mi><mn>2</mn></msub>"
        "<mi>O</mi></mrow></math>.</p></div>"
    )
    assert arpack.validate(pkg) == [], "inline presentation MathML must be allowed"


@pytest.mark.parametrize("src,ok", [
    ("https://my-bucket.s3.amazonaws.com/img.png", True),
    ("https://my-bucket.s3.us-east-1.amazonaws.com/img.png", True),
    ("https://s3.amazonaws.com/my-bucket/img.png", True),
    ("https://d123.cloudfront.net/img.png", True),
    ("http://my-bucket.s3.amazonaws.com/img.png", False),   # not https
    ("data:image/png;base64,AAAA", False),
    ("/relative/img.png", False),
    ("https://evil.example.com/img.png", False),
])
def test_img_src_s3_only(src, ok):
    bad = arpack.validate_img_src(f'<img src="{src}"/>')
    assert (bad == []) == ok, f"{src!r} expected ok={ok}, got bad={bad}"


def test_malformed_xhtml_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["qti"]["stimuli"][0]["content"] = "<div><p>unclosed"
    assert any("well-formed" in e for e in arpack.validate(pkg))


# ───────────────────────── test section structure (3-6 guiding + exactly 4 quiz) ────────────────
def test_too_few_guiding_fails(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    secs = pkg["qti"]["tests"][0]["qti-test-part"][0]["qti-assessment-section"]
    guiding = [s for s in secs if s["title"].startswith("Guiding")]
    # drop guiding down to 2 (below the floor of 3)
    keep_quiz = [s for s in secs if s["title"] == "Quiz"]
    pkg["qti"]["tests"][0]["qti-test-part"][0]["qti-assessment-section"] = guiding[:2] + keep_quiz
    assert any("guiding" in e for e in arpack.validate(pkg))


def test_wrong_quiz_count_fails(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    for s in pkg["qti"]["tests"][0]["qti-test-part"][0]["qti-assessment-section"]:
        if s["title"] == "Quiz":
            s["qti-assessment-item-ref"] = s["qti-assessment-item-ref"][:3]   # 3 != 4
    assert any("quiz" in e.lower() for e in arpack.validate(pkg))


def test_item_ref_href_id_coupled(sample_pkg):
    # D4: bare {id}.xml hrefs — the id MUST appear in the href.
    for t in sample_pkg["qti"]["tests"]:
        for s in t["qti-test-part"][0]["qti-assessment-section"]:
            for ref in s["qti-assessment-item-ref"]:
                assert ref["identifier"] in ref["href"], "item-ref href must be id-coupled"


def test_quiz_item_must_not_have_stimulus_ref(sample_pkg):
    items = {i["identifier"]: i for i in sample_pkg["qti"]["items"]}
    for t in sample_pkg["qti"]["tests"]:
        for s in t["qti-test-part"][0]["qti-assessment-section"]:
            if s["title"] == "Quiz":
                for ref in s["qti-assessment-item-ref"]:
                    assert "stimulusRef" not in items[ref["identifier"]]


def test_guiding_item_must_have_stimulus_ref(sample_pkg):
    items = {i["identifier"]: i for i in sample_pkg["qti"]["items"]}
    for t in sample_pkg["qti"]["tests"]:
        for s in t["qti-test-part"][0]["qti-assessment-section"]:
            if s["title"].startswith("Guiding"):
                for ref in s["qti-assessment-item-ref"]:
                    assert "stimulusRef" in items[ref["identifier"]]


# ───────────────────────── question stem lives in interaction.questionStructure.prompt ─────────
# Ilma's authoritative JSON template (create-mcq.md) puts the stem + choices inside
# `questionStructure`; an item with a blank prompt renders as naked options. Fail-closed.
def test_every_choice_item_carries_a_stem(sample_pkg):
    for i in sample_pkg["qti"]["items"]:
        if i["type"] == "choice":
            qs = i["interaction"]["questionStructure"]
            assert qs.get("prompt", "").strip(), f"{i['identifier']}: empty stem"
            assert qs.get("choices"), f"{i['identifier']}: choices not in questionStructure"


def test_blank_stem_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    pkg["qti"]["items"][0]["interaction"]["questionStructure"]["prompt"] = ""
    assert any("stem" in e for e in arpack.validate(pkg)), \
        "a blank questionStructure.prompt must be rejected (renders stemless)"


def test_stem_is_sanitized_xhtml(sample_pkg):
    # the emitted stem must be well-formed XHTML (wrapped/escaped by _sani_prompt).
    import xml.etree.ElementTree as ET
    for i in sample_pkg["qti"]["items"]:
        if i["type"] == "choice":
            stem = i["interaction"]["questionStructure"]["prompt"]
            ET.fromstring(f"<_r>{stem}</_r>")   # raises if not well-formed


# ───────────────────────── G2: every test + item carries a SCORE outcome decl ──────────────────
def test_every_test_has_score_outcome_decl(sample_pkg):
    for t in sample_pkg["qti"]["tests"]:
        decls = t.get("qti-outcome-declaration", [])
        assert any(d["identifier"] == "SCORE" for d in decls), \
            f"{t['identifier']}: missing SCORE outcome decl (else score always 0)"


def test_every_item_has_score_outcome_decl(sample_pkg):
    for i in sample_pkg["qti"]["items"]:
        decls = i.get("outcomeDeclarations", [])
        assert any(d["identifier"] == "SCORE" for d in decls), \
            f"{i['identifier']}: missing SCORE outcome decl"
