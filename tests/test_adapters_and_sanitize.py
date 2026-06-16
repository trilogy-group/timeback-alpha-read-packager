"""Tests for the input adapters (skeleton_adapter, output_dir_ingester, qti_dir_resolver)
and the sanitizer (sanitize_html) — the surfaces Mayank/Anirudh feed without reshaping."""
import os

import pytest

import arpack
import sanitize_html
import skeleton_adapter
import output_dir_ingester
import qti_dir_resolver


# ════════════════════════════ sanitize_html ════════════════════════════
def test_void_elements_self_closed():
    out = sanitize_html.full_sanitize("<p>line<br>next</p>")
    assert "<br/>" in out
    _assert_well_formed(out)


def test_bare_ampersand_escaped():
    out = sanitize_html.full_sanitize("<p>CO2 & H2O</p>")
    assert "&amp;" in out
    _assert_well_formed(out)


def test_existing_entities_not_double_escaped():
    out = sanitize_html.full_sanitize("<p>a &amp; b &lt; c</p>")
    assert "&amp;amp;" not in out
    _assert_well_formed(out)


def test_named_entity_to_unicode():
    out = sanitize_html.full_sanitize("<p>3 &mdash; 4 &deg;C</p>")
    assert "—" in out and "°" in out
    _assert_well_formed(out)


def test_bare_lt_in_math_escaped():
    out = sanitize_html.full_sanitize("<p>if x < 5 then</p>")
    _assert_well_formed(out)


def test_table_moved_out_of_p():
    out = sanitize_html.full_sanitize("<p>before<table><tr><td>x</td></tr></table>after</p>")
    _assert_well_formed(out)
    # the <table> must no longer be a child of <p>
    assert "<p><table" not in out.replace(" ", "")


def _assert_well_formed(html):
    import xml.etree.ElementTree as ET
    ET.fromstring(f"<_r>{html}</_r>")   # raises on malformed


# ════════════════════════════ skeleton_adapter ════════════════════════════
def test_skeleton_adapter_selftest():
    assert skeleton_adapter._selftest()


def test_csv_with_p_in_header_not_shredded():
    # the regression the comment warns about: csv.Sniffer would pick 'p' from 'expedition'.
    units = skeleton_adapter.from_skeleton_table(
        "expedition,band,genre\nSpace,A,Informational\n")
    assert len(units) == 1 and units[0]["title"] == "Space"


def test_band_order_drives_sortorder():
    units = skeleton_adapter.from_skeleton_table(
        "expedition,band\nC1,C\nA1,A\nB1,B\n")
    assert [u["band"] for u in units] == ["A", "B", "C"]
    assert [u["sortOrder"] for u in units] == [1, 2, 3]


def test_standards_stay_coverage_only():
    units = skeleton_adapter.from_skeleton_table(
        "expedition,band,standards\nX,A,\"RI.3.1;RI.3.2\"\n")
    u = units[0]
    assert "standards" not in u, "standards must NOT be a top-level serialized field"
    assert u["coverage"]["standards"] == ["RI.3.1", "RI.3.2"]


def test_real_expeditions_csv_adapts(examples_dir):
    csv_path = os.path.join(examples_dir, "expeditions.csv")
    units = skeleton_adapter.from_skeleton_table(csv_path)
    assert len(units) == 5
    vids = [l["vendorId"] for u in units for l in u["lessons"]]
    assert len(vids) == len(set(vids)), "vendorIds globally unique"
    assert min(vids) == skeleton_adapter.VENDOR_ID_BASE


# ════════════════════════════ output_dir_ingester (Mayank fixture) ════════════════════════════
def test_ingest_mayank_fixture_all_records(fixture_dir):
    res = output_dir_ingester.from_timeback_build_output(fixture_dir)
    assert len(res["records"]) == 4               # 4 items in the fixture
    sids = {r["stimulus_id"] for r in res["records"] if r["stimulus"]}
    assert len(sids) == 2                          # 2 distinct stimuli
    for r in res["records"]:
        it = r["item"]
        assert it["prompt"].strip(), f"{r['item_id']}: blank prompt"
        assert len(it["choices"]) >= 2
        assert it["correct_ids"]
        cids = {c["id"] for c in it["choices"]}
        assert all(c in cids for c in it["correct_ids"])


def test_ingest_fixture_prove_passes(fixture_dir):
    ok, _ = output_dir_ingester._prove(fixture_dir)
    assert ok


def test_ingest_missing_dir_raises():
    with pytest.raises(ValueError):
        output_dir_ingester.from_timeback_build_output("/tmp/__definitely_not_here__")


# ════════════════════════════ qti_dir_resolver (loose-XML grouping) ════════════════════════════
def _write_lesson_folder(tmp_path):
    """A minimal one-lesson loose-XML folder: 3 guiding (each w/ a passage) + 4 quiz."""
    QN = 'xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0"'
    d = tmp_path / "lesson"
    d.mkdir()

    def choice_item(ident, stim_ref=None):
        # live href convention is 'stimuli/<sid>' WITHOUT a .xml suffix (verified in the export).
        ref = (f'<qti-assessment-stimulus-ref identifier="{stim_ref}" '
               f'href="stimuli/{stim_ref}"/>') if stim_ref else ""
        return f'''<?xml version="1.0"?>
<qti-assessment-item {QN} identifier="{ident}" title="{ident}">
{ref}
<qti-response-declaration identifier="RESPONSE" cardinality="single" base-type="identifier">
<qti-correct-response><qti-value>A</qti-value></qti-correct-response></qti-response-declaration>
<qti-item-body><qti-choice-interaction response-identifier="RESPONSE" max-choices="1">
<qti-prompt>Q for {ident}?</qti-prompt>
<qti-simple-choice identifier="A">yes</qti-simple-choice>
<qti-simple-choice identifier="B">no</qti-simple-choice>
</qti-choice-interaction></qti-item-body></qti-assessment-item>'''

    def stim(ident):
        return f'''<?xml version="1.0"?>
<qti-assessment-stimulus {QN} identifier="{ident}" title="Passage {ident}">
<qti-stimulus-body><div><h1>Passage {ident}</h1><p>Some text.</p></div></qti-stimulus-body>
</qti-assessment-stimulus>'''

    # guiding ids: guiding_<A>_<B>; stimulus id == guiding_<A>
    for n in range(1, 4):
        sid = f"guiding_300000{n}"
        (d / f"{sid}_300000{n}.xml").write_text(choice_item(f"{sid}_300000{n}", sid))
        (d / f"{sid}.xml").write_text(stim(sid))
    for n in range(1, 5):
        (d / f"quiz_30000{n}.xml").write_text(choice_item(f"quiz_30000{n}"))
    return d


def test_qti_dir_resolver_one_lesson(tmp_path):
    folder = _write_lesson_folder(tmp_path)
    lesson = qti_dir_resolver.from_qti_lesson_folder(str(folder))
    assert len(lesson["guiding"]) == 3
    assert len(lesson["quiz"]) == 4


def test_qti_dir_resolver_assembles_and_validates(tmp_path):
    _write_lesson_folder(tmp_path)
    res = qti_dir_resolver.from_qti_dir(str(tmp_path))
    assert len(res["lessons"]) == 1
    skel = {
        "course": {"title": "STAN-PROBE-DELETEME T", "courseCode": "ALPHAREAD-PROBE",
                   "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
        "units": [{"title": "U", "sortOrder": 1, "lessons": res["lessons"]}],
    }
    pkg = arpack.assemble(skel)
    assert arpack.validate(pkg) == []


def test_qti_dir_resolver_fails_loud_on_short_lesson(tmp_path):
    # only 2 guiding + 4 quiz -> below the 3-guiding floor -> must raise.
    folder = _write_lesson_folder(tmp_path)
    # delete one guiding pair
    for f in folder.glob("guiding_3000003*"):
        f.unlink()
    with pytest.raises(ValueError):
        qti_dir_resolver.from_qti_lesson_folder(str(folder))
