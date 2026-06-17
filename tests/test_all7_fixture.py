"""STREAM B3 — ALL-7 contract tests, locked against Mayank's REAL all-7 build output.

Fixture: fixtures/qti_all7_2026-06-16 (incept-qti-sdk 0.5.7, BuildResult/output_dir shape:
manifest.json + items/*.xml + stimuli/*.xml). 13 items spanning every r2 family:
  mcq x3 (incl. one with an S3-style image stimulus), msq x2, fill-in text-entry (single + multi
  blank), hot-text (single + multi+feedback), match (drag-drop), order (summative + partial-credit),
  ebsr; + 4 stimuli (one carrying an <img>).

THE CONTRACT THESE TESTS LOCK (Ilma RULE 1 — /tmp/ilma_skill/skills/timeback/interaction-types.md):
the API's JSON->XML converter is LOSSY. JSON POST is safe for EXACTLY 4 types — choice, extended-text,
order, text-entry. Everything else (hottext/match/associate/ebsr/inline-choice/gap-match/select-point)
MUST be emitted as the raw-XML envelope {"format":"xml","xml":<rawXml verbatim>} or it renders broken
and scores wrong. So:
  * JSON-SAFE types  -> arpack._item() returns the JSON dict (interaction + responseDeclarations).
  * NON-JSON-SAFE    -> arpack._item() returns {"format":"xml","xml":<verbatim rawXml>}, with NO JSON
                        model and NO invented 'map_response' responseProcessing template.

WE adapt to HIS output; he changes nothing. Read-only against the checked-in fixture.
"""
import copy
import json
import os
import xml.etree.ElementTree as ET

import pytest

import arpack
import output_dir_ingester as odi


# ════════════════════════════ fixture wiring ════════════════════════════
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
ALL7_DIR = os.path.join(REPO_ROOT, "fixtures", "qti_all7_2026-06-16")
ITEMS_DIR = os.path.join(ALL7_DIR, "items")
STIMULI_DIR = os.path.join(ALL7_DIR, "stimuli")

# the 13 items, mapped to the format from_qti_xml MUST auto-detect and whether the emitter MUST
# ship them as the raw-XML envelope (Ilma RULE 1). Grounded in the actual fixture XML.
EXPECTED = {
    "sample-mcq-no-stimulus":         ("choice",     False),
    "sample-mcq-with-stimulus":       ("choice",     False),
    "sample-mcq-with-image-stimulus": ("choice",     False),
    "sample-msq-no-stimulus":         ("choice",     False),
    "sample-msq-with-stimulus":       ("choice",     False),
    "sample-order-summative":         ("order",      False),
    "sample-order-partial-credit":    ("order",      False),
    "sample-fill-in-single":          ("text-entry", False),
    # MULTI-blank text-entry is XML-only at the ITEM level: the documented single-interaction JSON
    # model cannot carry >1 inline interaction + >1 RESPONSE_BLANK_N decl — the converter merges the
    # blanks into one synonym pool AND drops the inline placeholders. Ilma RULE 1: ship verbatim XML.
    "sample-fill-in-multi":           ("text-entry", True),
    "sample-hot-text-single":         ("hottext",    True),
    "sample-hot-text-multi-feedback": ("hottext",    True),
    "sample-match-drag-drop":         ("match",      True),
    "sample-ebsr":                    ("ebsr",       True),
}


@pytest.fixture(scope="module")
def all7_dir():
    assert os.path.isdir(ALL7_DIR), f"all-7 fixture missing: {ALL7_DIR}"
    return ALL7_DIR


@pytest.fixture(scope="module")
def ingested(all7_dir):
    """Mayank's whole build output, ingested via the manifest-driven ingester (the real entry path)."""
    return odi.from_timeback_build_output(all7_dir)


def _raw(item_id):
    return open(os.path.join(ITEMS_DIR, item_id + ".xml")).read()


def _emit(item_id, *, stimulus_id=None):
    """Parse one fixture item the way the pipeline does and emit the assembled item dict."""
    parsed = arpack.from_qti_xml(_raw(item_id))
    return parsed, arpack._item(item_id, arpack.adapt_qti_item(parsed), stimulus_id=stimulus_id)


# ════════════════════════════ ingest: all 13 + 4 stimuli ════════════════════════════
def test_manifest_is_decoded_despite_utf16_bom(all7_dir):
    """Mayank's all-7 manifest is UTF-16-LE-with-BOM (the 4-item sample was UTF-8-BOM). The ingester
    must sniff the BOM and decode either — a utf-8-only read raises UnicodeDecodeError on 0xFF 0xFE."""
    res = odi.from_timeback_build_output(all7_dir)   # would raise if the BOM weren't handled
    assert len(res["records"]) == 13


def test_all_thirteen_items_ingest(ingested):
    assert len(ingested["records"]) == 13, "every manifest item must become a record"
    ids = {r["item_id"] for r in ingested["records"]}
    assert ids == set(EXPECTED), f"item id set mismatch: {ids ^ set(EXPECTED)}"
    assert ingested["warnings"] == [], f"clean fixture must ingest with no warnings: {ingested['warnings']}"
    # no lesson_id in this manifest -> ungrouped (grouping is the resolver's job, not Mayank's)
    assert ingested["groups"] is None


def test_four_distinct_stimuli_ingest(ingested):
    sids = {r["stimulus_id"] for r in ingested["records"] if r["stimulus"] is not None}
    # 4 stimulus files exist; 4 items reference one each (mcq-with-text, mcq-with-image, msq-with-text, ebsr)
    assert sids == {"stim_20c1a57c2496", "stim_65786e10081e", "stim_183862046711", "stim_308fa4b211dd"}


@pytest.mark.parametrize("item_id,expected", sorted(EXPECTED.items()))
def test_each_item_parses_with_resolvable_key(item_id, expected):
    """Every one of the 13 items parses to its correct auto-detected format AND carries a resolvable
    answer key (correct_ids non-empty). This is the 'each item parses with a resolvable key' gate."""
    fmt_expected, _ = expected
    parsed = arpack.from_qti_xml(_raw(item_id))
    assert parsed["format"] == fmt_expected, f"{item_id}: format {parsed['format']} != {fmt_expected}"
    assert parsed["correct_ids"], f"{item_id}: no resolvable answer key"
    # adapt_qti_item is the fail-closed bridge — it must NOT raise for any of the 13 real items.
    arpack.adapt_qti_item(parsed)


# ════════════════════════════ Ilma RULE 1: the JSON vs XML split ════════════════════════════
@pytest.mark.parametrize("item_id,expected", sorted(EXPECTED.items()))
def test_emit_format_matches_rule1_split(item_id, expected):
    """The headline contract: NON-JSON-safe types emit {"format":"xml"}; JSON-safe types emit JSON."""
    fmt_expected, is_envelope = expected
    _, item = _emit(item_id)
    if is_envelope:
        assert item.get("format") == "xml", f"{item_id} ({fmt_expected}) must emit the XML envelope"
    else:
        assert item.get("format") != "xml", f"{item_id} ({fmt_expected}) must emit JSON, not an XML envelope"


@pytest.mark.parametrize("item_id", [k for k, v in EXPECTED.items() if v[1]])
def test_xml_envelope_carries_verbatim_rawxml(item_id):
    """A NON-JSON-safe item ships Mayank's ORIGINAL item XML byte-for-byte. No re-derivation."""
    raw = _raw(item_id)
    parsed, item = _emit(item_id)
    assert item["format"] == "xml"
    assert item["xml"] == raw, f"{item_id}: envelope xml must be the verbatim rawXml"
    assert parsed["rawXml"] == raw, "from_qti_xml must RETAIN rawXml for XML-only types"
    # it must NOT smuggle the JSON model that RULE 1 forbids
    assert "interaction" not in item and "interactions" not in item
    assert "responseDeclarations" not in item
    # and it must NOT carry the invented (non-real) responseProcessing template
    assert "map_response" not in json.dumps(item), "the invented 'map_response' template must be dropped"


@pytest.mark.parametrize("item_id", [k for k, v in EXPECTED.items() if not v[1]])
def test_json_safe_items_emit_json_model(item_id):
    """JSON-safe types (choice/order/text-entry) emit the JSON model: a SCORE outcome decl, a RESPONSE
    response-declaration with a correctResponse, and a stem in interaction.questionStructure.prompt."""
    _, item = _emit(item_id)
    assert item.get("format") != "xml"
    assert any(d["identifier"] == "SCORE" for d in item["outcomeDeclarations"])
    rd = item["responseDeclarations"][0]
    assert rd["identifier"] == "RESPONSE" and rd["correctResponse"]["value"]
    stem = (item.get("interaction") or {}).get("questionStructure", {}).get("prompt", "")
    assert stem.strip(), f"{item_id}: JSON-safe item must carry a non-blank stem"


def test_json_safe_set_is_exactly_the_four(ingested):
    """Lock the constant itself: exactly the 4 lossless types are JSON-safe; everything else is XML-only."""
    assert arpack.JSON_SAFE_TYPES == {"choice", "extended-text", "order", "text-entry"}
    assert {"hottext", "match", "associate", "ebsr", "inline-choice", "gap-match", "select-point"} \
        <= arpack.XML_ONLY_TYPES
    assert arpack.JSON_SAFE_TYPES.isdisjoint(arpack.XML_ONLY_TYPES)


# ════════════════════════════ per-type answer-key shapes (from the real fixture) ════════════════════════════
def test_mcq_single_select_shape():
    parsed, item = _emit("sample-mcq-no-stimulus")
    rd = item["responseDeclarations"][0]
    assert rd["cardinality"] == "single" and rd["baseType"] == "identifier"
    assert rd["correctResponse"]["value"] == ["B"]               # choice id
    assert item["interaction"]["maxChoices"] == 1


def test_msq_multi_select_shape():
    parsed, item = _emit("sample-msq-no-stimulus")
    rd = item["responseDeclarations"][0]
    assert rd["cardinality"] == "multiple", "msq must be cardinality multiple"
    assert rd["correctResponse"]["value"] == ["A", "C"]          # two choice ids
    assert item["interaction"]["maxChoices"] == 0                # 0 == unlimited == multi-select


@pytest.mark.parametrize("item_id,full_order", [
    ("sample-order-summative",      ["magna_carta", "printing", "columbus", "declaration"]),
    ("sample-order-partial-credit", ["question", "hypothesis", "experiment", "analyze", "conclude"]),
])
def test_order_emits_full_ordering(item_id, full_order):
    """order is JSON-safe; its key is the FULL ordering of option ids (cardinality ordered), not a
    single index. Truncating to one value fails the validator's 'must rank ALL options' gate."""
    _, item = _emit(item_id)
    rd = item["responseDeclarations"][0]
    assert rd["cardinality"] == "ordered" and rd["baseType"] == "identifier"
    assert rd["correctResponse"]["value"] == full_order
    assert arpack._validate_item(item) == []


def test_fill_in_single_accepts_multiple_answer_strings():
    """text-entry: base-type string; the key is accepted answer STRINGS, not choice ids. The single
    fixture blank accepts two spellings (mitochondria / mitochondrion)."""
    parsed, item = _emit("sample-fill-in-single")
    assert parsed["answers"] == ["mitochondria", "mitochondrion"]
    rd = item["responseDeclarations"][0]
    assert rd["baseType"] == "string"
    assert rd["correctResponse"]["value"] == ["mitochondria", "mitochondrion"]


def test_fill_in_multi_blank_has_multiple_response_declarations_in_rawxml():
    """The multi-blank fill-in carries TWO <qti-response-declaration RESPONSE_BLANK_N> in the source
    XML (one per blank). The parser keeps per-blank fidelity (answers_by_blank) AND counts the blanks
    (text_blanks) so the emitter can route it correctly."""
    parsed = arpack.from_qti_xml(_raw("sample-fill-in-multi"))
    assert parsed["format"] == "text-entry"
    root = ET.fromstring(_raw("sample-fill-in-multi"))
    rd_ids = [rd.attrib.get("identifier")
              for rd in root.iter() if rd.tag.split('}', 1)[-1] == "qti-response-declaration"]
    assert rd_ids == ["RESPONSE_BLANK_1", "RESPONSE_BLANK_2"], "multi-blank must have per-blank decls"
    # flat key (back-compat) AND per-blank split (blank N never bleeds into blank M).
    assert parsed["answers"] == ["5", "5"]
    assert parsed["text_blanks"] == 2
    assert parsed["answers_by_blank"] == [["5"], ["5"]]


def test_fill_in_multi_blank_emits_xml_envelope_not_lossy_json():
    """REGRESSION GUARD for the real scoring-corruption bug: a MULTI-blank fill-in CANNOT be modelled
    by the documented single-interaction JSON shape. The in-tree JSON path used to collapse the two
    RESPONSE_BLANK_N declarations into ONE RESPONSE with value=['5','5'] (i.e. ONE blank accepting '5'
    OR '5' as synonyms) AND strip both inline qti-text-entry-interaction placeholders out of the stem —
    so a key like blank1='cat'/blank2='dog' would wrongly accept 'dog' in blank1. Ilma RULE 1: when the
    JSON model is lossy, ship the verbatim XML. So multi-blank text-entry MUST emit the XML envelope."""
    raw = _raw("sample-fill-in-multi")
    parsed, item = _emit("sample-fill-in-multi")
    # the parser still calls it text-entry (it IS), but _is_xml_only routes it to the envelope.
    assert parsed["format"] == "text-entry"
    assert arpack._is_xml_only(parsed) is True
    assert item["format"] == "xml", "multi-blank text-entry must emit the raw-XML envelope"
    assert item["type"] == "text-entry"
    # verbatim rawXml — BOTH per-blank declarations + BOTH inline interactions survive intact.
    assert item["xml"] == raw
    assert item["xml"].count("qti-text-entry-interaction") == 2
    assert 'identifier="RESPONSE_BLANK_1"' in item["xml"]
    assert 'identifier="RESPONSE_BLANK_2"' in item["xml"]
    # the lossy JSON model must NOT be present, and no invented template.
    assert "responseDeclarations" not in item and "interaction" not in item
    assert "map_response" not in json.dumps(item)
    # and it validates clean as an envelope.
    assert arpack._validate_item(item) == []


def test_fill_in_single_blank_stays_json_safe():
    """The SINGLE-blank fill-in is genuinely JSON-safe (one RESPONSE -> one input box) and MUST stay on
    the JSON path — only MULTI-blank text-entry is bumped to XML. Guards against over-routing."""
    parsed, item = _emit("sample-fill-in-single")
    assert parsed["text_blanks"] == 1
    assert parsed.get("answers_by_blank") is None
    assert arpack._is_xml_only(parsed) is False
    assert item.get("format") != "xml", "single-blank text-entry must stay JSON"
    assert item["responseDeclarations"][0]["baseType"] == "string"


def test_hottext_single_token_id_key():
    """hot-text: cardinality single, base-type identifier, value = a token id (t4). XML-only -> the
    answer key rides verbatim inside the rawXml (we assert against the parsed key + the envelope)."""
    parsed, item = _emit("sample-hot-text-single")
    assert parsed["format"] == "hottext"
    assert parsed["correct_ids"] == ["t4"]
    assert item["format"] == "xml"
    assert 'identifier="t4"' in item["xml"] and "<qti-hottext-interaction" in item["xml"]


def test_hottext_multi_token_ids_and_cardinality_multiple():
    """The multi+feedback hot-text selects two token ids (w2, w6), cardinality multiple — both survive
    in the verbatim XML envelope (no JSON modelling)."""
    parsed, item = _emit("sample-hot-text-multi-feedback")
    assert parsed["correct_ids"] == ["w2", "w6"]
    assert item["format"] == "xml"
    assert 'cardinality="multiple"' in item["xml"]
    assert "<qti-feedback-block" in item["xml"], "feedback blocks must survive verbatim, not be stripped"


def test_match_directedpair_pairs_survive_verbatim():
    """match (associate): cardinality multiple, base-type directedPair, value = 'left right' pairs.
    JSON POST mangles directedPair (splits on the space) -> MUST be the verbatim XML envelope."""
    parsed, item = _emit("sample-match-drag-drop")
    assert parsed["format"] == "match"
    assert parsed["correct_ids"] == ["france paris", "japan tokyo", "brazil brasilia", "egypt cairo"]
    assert item["format"] == "xml"
    assert 'base-type="directedPair"' in item["xml"]
    for pair in ("france paris", "japan tokyo", "brazil brasilia", "egypt cairo"):
        assert f"<qti-value>{pair}</qti-value>" in item["xml"], f"{pair} must survive intact"
    assert "<qti-match-interaction" in item["xml"]


def test_ebsr_parts_parse_with_per_part_prompts_and_keys():
    """ebsr parsing: TWO parts (Part A claim + Part B evidence), each coupled to its own
    response-declaration (RESPONSE_1 / RESPONSE_2) so the two answer keys never cross-contaminate.
    Each part now ALSO carries its own per-part prompt — the <qti-prompt> inside that interaction —
    which the decomposition needs so each emitted single-select item has a real stem."""
    parsed = arpack.from_qti_xml(_raw("sample-ebsr"))
    assert parsed["format"] == "ebsr"
    parts = parsed["ebsr_parts"]
    assert len(parts) == 2
    assert parts[0]["response_identifier"] == "RESPONSE_1"
    assert parts[1]["response_identifier"] == "RESPONSE_2"
    # both parts key to choice "B" in the fixture
    assert parts[0]["correct_indices"] == [1] and parts[1]["correct_indices"] == [1]
    # per-part prompts captured from each interaction's own <qti-prompt>
    assert "Part A" in parts[0]["prompt"] and "Part B" in parts[1]["prompt"]
    assert parts[0]["prompt"] != parts[1]["prompt"]


def test_ebsr_decomposes_into_two_choice_items_on_assemble():
    """The SHIPPED EBSR contract (replaces the old composite-envelope behavior): Alpha Read's reading
    renderer flattens a composite (two-interaction) item into one ~8-option question (confirmed live);
    the fix (also confirmed live to render) decomposes the EBSR into TWO linked single-select CHOICE
    items. After assemble(), an EBSR input yields items `sample-ebsr-partA` and `sample-ebsr-partB`,
    both choice + single-select (maxChoices==1), each with a non-empty stem + a resolvable
    correctResponse + a stimulusRef, appearing as two separate "Guiding …" sections — and NO
    composite/envelope item remains in the assembled package."""
    spec = arpack.adapt_qti_item(arpack.from_qti_xml(_raw("sample-ebsr")))
    skel = {"course": {"title": "STAN-PROBE-DELETEME ebsr-decomp", "courseCode": "ALPHAREAD-PROBE",
                       "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
            "units": [{"title": "U", "sortOrder": 1, "lessons": [{
                "vendorId": 9300001, "title": "L", "xp": 12,
                "guiding": [
                    {"stimulus": {"title": "P1", "html": "<div><p>Passage 1.</p></div>"}, "item": spec},
                    {"stimulus": {"title": "P2", "html": "<div><p>Passage 2.</p></div>"},
                     "item": {"title": "G2", "prompt": "Q2?", "choices": ["A", "B", "C", "D"], "correct_index": 0}},
                    {"stimulus": {"title": "P3", "html": "<div><p>Passage 3.</p></div>"},
                     "item": {"title": "G3", "prompt": "Q3?", "choices": ["A", "B", "C", "D"], "correct_index": 0}},
                ],
                "quiz": [{"title": f"Z{i}", "prompt": "Q?", "choices": ["A", "B", "C", "D"],
                          "correct_index": 0} for i in range(4)]}]}]}
    pkg = arpack.assemble(skel)
    assert arpack.validate(pkg) == []
    items = {i["identifier"]: i for i in pkg["qti"]["items"]}
    assert "sample-ebsr-partA" in items and "sample-ebsr-partB" in items
    assert "sample-ebsr" not in items, "the composite EBSR item must not survive"
    assert not any(i.get("format") == "xml" for i in pkg["qti"]["items"]), \
        "no composite/raw-XML envelope item may remain after decomposition"
    for pid in ("sample-ebsr-partA", "sample-ebsr-partB"):
        it = items[pid]
        assert it["type"] == "choice"
        assert it["interaction"]["maxChoices"] == 1
        assert it["interaction"]["questionStructure"]["prompt"].strip()
        assert it["responseDeclarations"][0]["correctResponse"]["value"]
        assert "stimulusRef" in it
    secs = pkg["qti"]["tests"][0]["qti-test-part"][0]["qti-assessment-section"]
    part_secs = [s for s in secs if s["title"].startswith("Guiding")
                 and s["qti-assessment-item-ref"][0]["identifier"].startswith("sample-ebsr-part")]
    assert len(part_secs) == 2, "the two EBSR parts appear as two separate Guiding sections"
    json.dumps(pkg)   # stays JSON-serializable for emit()


# ════════════════════════════ the S3 image gate ════════════════════════════
def test_image_stimulus_local_src_is_caught_by_s3_gate():
    """The mcq-with-image-stimulus references a LOCAL filename (water_cycle_diagram.png), NOT an S3
    URL. The S3 gate must FLAG it — that's the gate doing its job (local paths render as broken
    thumbnails in the student UI). Proves the gate actually fires on the real fixture image."""
    s = arpack.from_qti_stimulus_xml(open(os.path.join(STIMULI_DIR, "stim_65786e10081e.xml")).read())
    assert "<img" in s["html"]
    bad = arpack.validate_img_src(s["html"])
    assert bad == ["water_cycle_diagram.png"], \
        "the local (non-S3) image src must be flagged by the S3 gate"


def test_image_stimulus_passes_gate_once_rewritten_to_s3():
    """The SAME stimulus, with the img src rewritten to an S3 URL, passes the gate — confirming the
    gate keys on the URL shape (https S3 / CloudFront), not on the presence of an <img>."""
    s = arpack.from_qti_stimulus_xml(open(os.path.join(STIMULI_DIR, "stim_65786e10081e.xml")).read())
    s3_html = s["html"].replace(
        "water_cycle_diagram.png",
        "https://ai-first-incept-media.s3.amazonaws.com/water_cycle_diagram.png")
    assert arpack.validate_img_src(s3_html) == [], "an S3-hosted img must pass the gate"


def test_text_stimuli_have_no_images_and_pass_gate():
    """The three text passages (incl. the MathML one and the EBSR passage) carry no <img> and pass."""
    for sid in ("stim_20c1a57c2496", "stim_183862046711", "stim_308fa4b211dd"):
        s = arpack.from_qti_stimulus_xml(open(os.path.join(STIMULI_DIR, sid + ".xml")).read())
        assert arpack.validate_img_src(s["html"]) == []


# ════════════════════════════ end-to-end: all-7 ride into a valid package ════════════════════════════
def _all7_lesson(ingested):
    """Build one materialized lesson from the all-7 ingest: 3 S3-clean guiding (stimulus) items + the
    first 4 quiz (non-stimulus) items. Covers choice/order/text-entry/hottext/match/ebsr end-to-end."""
    guiding, quiz = [], []
    for r in ingested["records"]:
        item = arpack.adapt_qti_item(r["item"])
        if r["stimulus"] is not None:
            # skip the local-image stimulus for the clean-validate path (its src fails the S3 gate by design)
            if arpack.validate_img_src(r["stimulus"]["html"]):
                continue
            if len(guiding) < 6:
                guiding.append({"stimulus": {"title": r["stimulus"]["title"],
                                             "html": r["stimulus"]["html"]}, "item": item})
        elif len(quiz) < 4:
            quiz.append(item)
    return guiding[:3], quiz


def test_all7_assembles_and_validates_clean(ingested):
    guiding, quiz = _all7_lesson(ingested)
    assert len(guiding) == 3 and len(quiz) == 4
    skel = {"course": {"title": "STAN-PROBE-DELETEME all7", "courseCode": "ALPHAREAD-PROBE",
                       "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
            "units": [{"title": "All7", "sortOrder": 1,
                       "lessons": [{"vendorId": 9100001, "title": "All7 lesson", "xp": 12,
                                    "guiding": guiding, "quiz": quiz}]}]}
    pkg = arpack.assemble(skel)
    assert arpack.validate(pkg) == [], "an all-7 lesson must round-trip to a valid package"
    # envelope items survived into the package and stay JSON-serializable for emit()
    json.dumps(pkg)


def test_all7_package_keeps_envelope_items_as_xml(ingested):
    """Non-JSON-safe items that land in the package keep their {"format":"xml"} envelope through
    assemble() — assemble must NOT silently re-model them into the JSON shape."""
    guiding, quiz = _all7_lesson(ingested)
    # force at least one envelope item (the EBSR is a guiding item with a stimulus) into the quiz too
    # by appending a hottext envelope item as a quiz item (no stimulus).
    ht = arpack.adapt_qti_item(arpack.from_qti_xml(_raw("sample-hot-text-single")))
    quiz = (quiz[:3] + [ht])
    skel = {"course": {"title": "STAN-PROBE-DELETEME all7e", "courseCode": "ALPHAREAD-PROBE",
                       "grades": ["3"], "subjects": ["Reading"], "org_sourcedId": "powerpath-ui-org"},
            "units": [{"title": "All7e", "sortOrder": 1,
                       "lessons": [{"vendorId": 9100002, "title": "All7e lesson", "xp": 12,
                                    "guiding": guiding, "quiz": quiz}]}]}
    pkg = arpack.assemble(skel)
    assert arpack.validate(pkg) == []
    env = [i for i in pkg["qti"]["items"] if i.get("format") == "xml"]
    assert env, "at least one XML-envelope item must be present in the assembled package"
    for i in env:
        assert i["type"] in arpack.XML_ONLY_TYPES
        assert i["xml"].strip().startswith("<?xml") or "<qti-assessment-item" in i["xml"]


# ════════════════════════════ fail-closed: a corrupted envelope is rejected ════════════════════════════
def test_envelope_with_empty_rawxml_fails_closed():
    spec = {"identifier": "x", "title": "x", "format": "hottext", "rawXml": "   ", "correct_ids": ["t1"]}
    with pytest.raises(ValueError):
        arpack._item("x", spec, stimulus_id=None)


def test_envelope_validator_flags_malformed_xml():
    bad = {"identifier": "x", "type": "match", "format": "xml", "xml": "<qti-assessment-item><unclosed>"}
    errs = arpack._validate_item(bad)
    assert errs, "a malformed raw-XML envelope must be rejected by the validator"


def test_json_safe_type_must_not_use_envelope():
    """A 'choice' that tries to ride as an XML envelope is a contract violation (choice is JSON-safe).
    The validator must fail CLOSED with a message — not crash, and not silently accept it."""
    parsed = arpack.from_qti_xml(_raw("sample-mcq-no-stimulus"))
    forged = {"identifier": "x", "type": "choice", "format": "xml", "xml": parsed["rawXml"]}
    errs = arpack._validate_item(forged)
    assert errs and any("must NOT use the raw-XML envelope" in e for e in errs), \
        "a JSON-safe type wearing the XML envelope must be rejected (fail-closed, no crash)"


def test_malformed_json_item_fails_closed_not_crash():
    """A JSON-safe item missing its responseDeclarations is malformed — the validator must report it,
    not raise KeyError (a crash is not a fail-closed gate)."""
    errs = arpack._validate_item({"identifier": "x", "type": "choice",
                                  "interaction": {"questionStructure": {"prompt": "Q?"}}})
    assert errs and any("responseDeclarations" in e for e in errs)


def test_single_blank_text_entry_in_envelope_is_rejected():
    """The multi-blank envelope exception must be NARROW: a SINGLE-blank text-entry (genuinely
    JSON-safe) that tries to ride the raw-XML envelope is still a contract violation and must be
    rejected — only a real multi-blank (>1 RESPONSE_BLANK_N) text-entry is allowed in the envelope."""
    single_raw = _raw("sample-fill-in-single")
    forged = {"identifier": "sample-fill-in-single", "type": "text-entry",
              "format": "xml", "xml": single_raw}
    errs = arpack._validate_item(forged)
    assert errs and any("must NOT use the raw-XML envelope" in e for e in errs)


def test_multi_blank_text_entry_envelope_validates_clean():
    """The other side of the narrow exception: a genuine multi-blank (>1 RESPONSE_BLANK_N) text-entry
    riding the envelope validates clean (it is legitimately XML-only at the item level)."""
    multi_raw = _raw("sample-fill-in-multi")
    good = {"identifier": "sample-fill-in-multi", "type": "text-entry",
            "format": "xml", "xml": multi_raw}
    assert arpack._validate_item(good) == []
