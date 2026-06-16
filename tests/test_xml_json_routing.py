"""Stream B2 — EMIT / XML-POST ROUTING (Ilma CRITICAL RULE 1).

The API's JSON->XML converter is LOSSY. JSON POST is safe for EXACTLY 4 types
(choice, extended-text, order, text-entry). Everything else (hottext, match, associate,
ebsr, inline-choice, gap-match, select-point) MUST be emitted as the raw-XML envelope
{"format":"xml","xml":<rawXml>} carried verbatim from the parsed item, or it renders broken
and scores wrong. These tests are the SHIP-BLOCKER gate for that split.

Verified against Mayank's REAL all-7 fixture (fixtures/qti_all7_2026-06-16, 13 items).
"""
import copy
import json
import os

import pytest

import arpack

FX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "qti_all7_2026-06-16", "items",
)


def _adapt(fn):
    return arpack.adapt_qti_item(arpack.from_qti_xml(open(os.path.join(FX, fn)).read()))


# ───────────────────────── the JSON-safe / XML-only partition is exactly RULE 1 ─────────────────
def test_json_safe_set_is_exactly_the_four():
    assert arpack.JSON_SAFE_TYPES == {"choice", "extended-text", "order", "text-entry"}


def test_xml_only_set_is_the_complement():
    assert arpack.XML_ONLY_TYPES == (arpack.ACCEPTED_ITEM_TYPES - arpack.JSON_SAFE_TYPES)
    # the non-JSON-safe families the brief enumerates are ALL xml-only
    for t in ("hottext", "match", "associate", "ebsr", "inline-choice",
              "gap-match", "select-point"):
        assert t in arpack.XML_ONLY_TYPES, f"{t} must be XML-only (RULE 1)"
    # ...and none of the 4 json-safe families leak into xml-only
    assert arpack.XML_ONLY_TYPES.isdisjoint(arpack.JSON_SAFE_TYPES)


# ───────────────────────── JSON-safe types emit the JSON dict (as today) ────────────────────────
@pytest.mark.parametrize("fn,fmt,card", [
    ("sample-mcq-no-stimulus.xml", "choice", "single"),
    ("sample-msq-no-stimulus.xml", "choice", "multiple"),
    ("sample-order-summative.xml", "order", "ordered"),
    ("sample-fill-in-single.xml", "text-entry", "single"),
])
def test_json_safe_emit_json_dict(fn, fmt, card):
    it = arpack._item(fn, _adapt(fn), stimulus_id=None)
    assert it["type"] == fmt
    assert it.get("format") != "xml", f"{fmt} must NOT be an XML envelope (it is JSON-safe)"
    assert "xml" not in it
    assert it["responseDeclarations"][0]["cardinality"] == card
    # JSON-safe items carry the modelled interaction + questionStructure
    if fmt == "text-entry":
        assert "questionStructure" in it["interaction"]
    else:
        assert "questionStructure" in it["interaction"]
        assert it["interaction"]["questionStructure"]["choices"]


# ───────────────────────── NON-JSON-safe types emit the raw-XML envelope ────────────────────────
@pytest.mark.parametrize("fn,fmt", [
    ("sample-hot-text-single.xml", "hottext"),
    ("sample-hot-text-multi-feedback.xml", "hottext"),
    ("sample-match-drag-drop.xml", "match"),
    ("sample-ebsr.xml", "ebsr"),
])
def test_xml_only_emit_envelope_verbatim(fn, fmt):
    raw = open(os.path.join(FX, fn)).read()
    it = arpack._item(fn, _adapt(fn), stimulus_id=None)
    assert it["type"] == fmt
    assert it["format"] == "xml", f"{fmt} MUST be the XML envelope (RULE 1)"
    assert it["xml"] == raw, "rawXml must ride through VERBATIM (no reshaping)"
    # it must NOT be JSON-modelled — that is the corruption RULE 1 forbids
    assert "interaction" not in it and "interactions" not in it
    assert "responseDeclarations" not in it
    assert "responseProcessing" not in it


def test_match_directed_pair_survives_in_envelope():
    """JSON POST would split 'france paris' into 'france'/'paris' and mangle scoring. The envelope
    keeps the verbatim directedPair value."""
    it = arpack._item("sample-match-drag-drop",
                      _adapt("sample-match-drag-drop.xml"), stimulus_id=None)
    assert 'base-type="directedPair"' in it["xml"]
    assert "<qti-value>france paris</qti-value>" in it["xml"]


def test_ebsr_two_response_decls_survive_in_envelope():
    it = arpack._item("sample-ebsr", _adapt("sample-ebsr.xml"), stimulus_id=None)
    assert 'identifier="RESPONSE_1"' in it["xml"]
    assert 'identifier="RESPONSE_2"' in it["xml"]


# ───────────────────────── map_response template is DROPPED everywhere ───────────────────────────
def test_no_map_response_template_anywhere():
    for fn in os.listdir(FX):
        it = arpack._item(fn, _adapt(fn), stimulus_id=None)
        assert "map_response" not in json.dumps(it), f"{fn}: map_response must be dropped"


# ───────────────────────── validate() ACCEPTS the envelope, fail-closed on a broken one ─────────
def test_validate_accepts_well_formed_envelope():
    for fn in ("sample-hot-text-single.xml", "sample-match-drag-drop.xml", "sample-ebsr.xml"):
        a = _adapt(fn)
        it = arpack._item(a["identifier"], a, stimulus_id=None)   # iid == the XML's own identifier
        assert arpack._validate_item(it) == [], f"{fn}: well-formed envelope must validate clean"


def test_validate_rejects_envelope_without_xml():
    it = arpack._item("sample-hot-text-single",
                      _adapt("sample-hot-text-single.xml"), stimulus_id=None)
    bad = copy.deepcopy(it)
    bad["xml"] = ""
    assert any("empty" in e or "rawXml" in e for e in arpack._validate_item(bad))


def test_validate_rejects_malformed_envelope_xml():
    it = arpack._item("sample-match-drag-drop",
                      _adapt("sample-match-drag-drop.xml"), stimulus_id=None)
    bad = copy.deepcopy(it)
    bad["xml"] = "<qti-assessment-item identifier='x'><unclosed>"
    assert any("well-formed" in e for e in arpack._validate_item(bad))


def test_validate_rejects_envelope_id_mismatch():
    it = arpack._item("sample-match-drag-drop",
                      _adapt("sample-match-drag-drop.xml"), stimulus_id=None)
    bad = copy.deepcopy(it)
    bad["identifier"] = "a-different-id"
    assert any("mismatch" in e for e in arpack._validate_item(bad))


def test_validate_rejects_envelope_missing_format():
    it = arpack._item("sample-ebsr", _adapt("sample-ebsr.xml"), stimulus_id=None)
    bad = copy.deepcopy(it)
    bad.pop("format")
    assert any("XML-only" in e or "format" in e for e in arpack._validate_item(bad))


# ───────────────────────── the brief's headline proof: a MIXED lesson validates clean ───────────
def test_mixed_lesson_choice_order_hottext_match_validates_clean():
    """Assemble one lesson mixing choice + order + hottext + match: the JSON-safe pair emit JSON,
    the non-JSON-safe pair emit XML envelopes, and validate() returns clean."""
    choice = _adapt("sample-mcq-no-stimulus.xml")
    order = _adapt("sample-order-summative.xml")
    hottext = _adapt("sample-hot-text-single.xml")
    match = _adapt("sample-match-drag-drop.xml")

    def guiding(n):
        return {"stimulus": {"title": f"P{n}", "html": f"<div><p>Passage {n}.</p></div>"},
                "item": {"title": f"G{n}", "prompt": f"Q{n}?",
                         "choices": ["A", "B", "C", "D"], "correct_index": 0}}

    skel = {
        "course": {"title": "STAN-PROBE-DELETEME Mixed B2", "courseCode": "ALPHAREAD-PROBE",
                   "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
        "units": [{"title": "Mixed", "sortOrder": 1, "lessons": [
            {"vendorId": 9100001, "title": "Mixed", "xp": 12,
             "guiding": [guiding(1), guiding(2), guiding(3)],
             "quiz": [choice, order, hottext, match]}]}]}

    pkg = arpack.assemble(skel)
    assert arpack.validate(pkg) == []
    items = {i["identifier"]: i for i in pkg["qti"]["items"]}
    assert items[choice["identifier"]].get("format") != "xml"
    assert items[order["identifier"]].get("format") != "xml"
    assert items[hottext["identifier"]]["format"] == "xml"
    assert items[match["identifier"]]["format"] == "xml"


# ───────────────────────── adapt_qti_item: XML-only requires rawXml ──────────────────────────────
def test_adapt_xml_only_requires_rawxml():
    parsed = arpack.from_qti_xml(open(os.path.join(FX, "sample-hot-text-single.xml")).read())
    parsed["rawXml"] = ""                                # simulate a parser that dropped it
    with pytest.raises(ValueError, match="XML-only"):
        arpack.adapt_qti_item(parsed)
