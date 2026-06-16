"""G3 question-stem contract tests — the fix for the ship-blocker where the parsed prompt was
dropped on emit and items rendered as naked choices with no question.

The stem MUST land in `interaction.questionStructure.prompt` (Ilma's authoritative JSON template,
create-mcq.md / create-frq.md), with options nested in `questionStructure.choices`. A stemless item
is fail-closed by the validator. Verified against Mayank's real incept-qti-sdk fixture XML.
"""
import copy
import json
import os

import pytest

import arpack


def _qs(interaction):
    return (interaction or {}).get("questionStructure") or {}


# ───────────────────────── emission: every sample item carries a real stem ─────────────────────
def test_every_sample_item_emits_a_stem(sample_pkg):
    for it in sample_pkg["qti"]["items"]:
        inters = [it.get("interaction", {})] + (it.get("interactions") or [])
        stems = [_qs(x).get("prompt", "") for x in inters if x]
        assert any(s.strip() for s in stems), f"{it['identifier']} emitted with NO question stem"


def test_choice_options_live_in_questionstructure(sample_pkg):
    """Options must be nested in questionStructure.choices (Ilma's JSON shape), not bare."""
    it = sample_pkg["qti"]["items"][0]
    qs = _qs(it["interaction"])
    assert "prompt" in qs and "choices" in qs
    assert len(qs["choices"]) == 4
    assert all(c.get("identifier") and "content" in c for c in qs["choices"])


def test_stem_is_block_wrapped_xhtml(sample_pkg):
    """A bare-text stem is wrapped in <p class="stem_paragraph"> (live production convention)."""
    it = sample_pkg["qti"]["items"][0]
    prompt = _qs(it["interaction"])["prompt"]
    assert prompt.startswith("<p") and prompt.rstrip().endswith("</p>")
    assert "stem_paragraph" in prompt


# ───────────────────────── roundtrip: Mayank's REAL stem survives parse→adapt→emit ─────────────
def test_real_mayank_stem_roundtrips(fixture_dir):
    xml = open(os.path.join(fixture_dir, "items", "sample-mcq-with-stimulus.xml")).read()
    parsed = arpack.from_qti_xml(xml)
    assert "ocean acidification" in parsed["prompt"]          # parsed correctly from <div class="stem">
    item = arpack._item("t", arpack.adapt_qti_item(parsed), stimulus_id=None)
    emitted = _qs(item["interaction"]).get("prompt", "")
    assert "ocean acidification" in emitted, "Mayank's real stem was dropped on emit"


# ───────────────────────── fail-closed: a stemless item is REJECTED ────────────────────────────
def test_missing_choice_stem_fails_closed(sample_pkg):
    pkg = copy.deepcopy(sample_pkg)
    # surgically strip the prompt from one emitted choice item
    pkg["qti"]["items"][0]["interaction"]["questionStructure"]["prompt"] = ""
    errs = [e for e in arpack.validate(pkg) if "stem" in e]
    assert errs, "a choice item with an empty stem must be rejected"


def test_skeleton_without_prompt_fails_closed():
    base = copy.deepcopy(arpack.SAMPLE)
    del base["units"][0]["lessons"][0]["guiding"][0]["item"]["prompt"]
    errs = [e for e in arpack.validate(arpack.assemble(base)) if "stem" in e]
    assert errs, "dropping a skeleton prompt must surface as a stem error"


def test_text_entry_requires_stem():
    base = copy.deepcopy(arpack.SAMPLE)
    base["units"][0]["lessons"][0]["quiz"][0] = {
        "title": "fill", "format": "text-entry", "answers": ["Paris"],
        "correct_ids": ["Paris"], "choices": [],          # no prompt
    }
    errs = [e for e in arpack.validate(arpack.assemble(base)) if "stem" in e]
    assert errs, "a fill-in with no stem must be rejected"


def test_ebsr_is_xml_only_requires_rawxml():
    """Ilma RULE 1: EBSR is composite (two response-decls) -> NON-JSON-safe -> emitted as the raw-XML
    envelope, NOT JSON-modelled into questionStructure.prompt. An EBSR spec that carries NO rawXml is
    un-emittable and must fail closed (the stem now lives inside the verbatim XML, not a JSON field)."""
    base = copy.deepcopy(arpack.SAMPLE)
    base["units"][0]["lessons"][0]["guiding"][0]["item"] = {
        "title": "EBSR", "format": "ebsr", "choices": [], "choice_ids": [],
        "correct_ids": ["B"], "correct_index": 0,
        # no rawXml -> XML-only emit cannot produce a valid envelope
    }
    with pytest.raises(ValueError, match="XML-only"):
        arpack.assemble(base)


def test_ebsr_emits_xml_envelope_not_json():
    """A real EBSR item (carries rawXml) emits the {"format":"xml","xml":...} envelope and validates
    clean — it must NOT carry the JSON interactions/responseDeclarations model (RULE 1)."""
    xml = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "fixtures", "qti_all7_2026-06-16", "items", "sample-ebsr.xml")).read()
    parsed = arpack.from_qti_xml(xml)
    assert parsed["format"] == "ebsr"
    item = arpack._item("sample-ebsr", arpack.adapt_qti_item(parsed), stimulus_id=None)
    assert item["format"] == "xml" and item["xml"] == xml
    assert "interactions" not in item and "responseDeclarations" not in item
    assert arpack._validate_item(item) == []


# ───────────────────────── the stem is HTML: G1 well-formedness + S3 img gates apply ───────────
def test_malformed_stem_html_fails_closed():
    base = copy.deepcopy(arpack.SAMPLE)
    # already-HTML prompt that is NOT well-formed (unclosed tag) — bypasses the <p> wrap
    base["units"][0]["lessons"][0]["guiding"][0]["item"]["prompt"] = "<p>bad <b>unclosed</p>"
    errs = [e for e in arpack.validate(arpack.assemble(base)) if "well-formed" in e and "prompt" in e]
    assert errs, "a malformed-XHTML stem must be rejected by the G1 gate"


def test_non_s3_image_in_stem_fails_closed():
    base = copy.deepcopy(arpack.SAMPLE)
    base["units"][0]["lessons"][0]["guiding"][0]["item"]["prompt"] = (
        '<p>Look: <img src="http://evil.example/x.png"/></p>'
    )
    errs = [e for e in arpack.validate(arpack.assemble(base)) if "img src" in e and "prompt" in e]
    assert errs, "a non-S3 image in the stem must be rejected"


def test_s3_image_in_stem_passes():
    base = copy.deepcopy(arpack.SAMPLE)
    base["units"][0]["lessons"][0]["guiding"][0]["item"]["prompt"] = (
        '<p>Look: <img src="https://ai-first-incept-media.s3.amazonaws.com/x.png"/></p>'
    )
    assert arpack.validate(arpack.assemble(base)) == [], "an S3 image in the stem must pass"


# ───────────────────────── the emitted package is JSON-serializable end-to-end ─────────────────
def test_emitted_items_json_roundtrip(sample_pkg):
    for it in sample_pkg["qti"]["items"]:
        assert json.loads(json.dumps(it)) == it
