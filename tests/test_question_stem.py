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


def test_ebsr_decomposes_into_two_choice_items_with_stems():
    """An EBSR is DECOMPOSED on assemble() into two single-select choice items (Part A claim, Part B
    evidence) — Alpha Read's reading renderer flattens a composite (2-interaction) item into one
    ~8-option question (confirmed live); two linked single-select CHOICE items render correctly. Each
    decomposed part MUST carry a real, non-blank stem in interaction.questionStructure.prompt — that is
    this test's contract: the per-part <qti-prompt> ("Part A. …" / "Part B. …") survives onto the
    emitted item, never dropped."""
    xml = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "fixtures", "qti_all7_2026-06-16", "items", "sample-ebsr.xml")).read()
    parsed = arpack.from_qti_xml(xml)
    assert parsed["format"] == "ebsr"
    spec = arpack.adapt_qti_item(parsed)
    emitted = arpack._emit_items("sample-ebsr", spec, stimulus_id="stim_308fa4b211dd")
    assert [rid for rid, _ in emitted] == ["sample-ebsr-partA", "sample-ebsr-partB"]
    for rid, item in emitted:
        assert item["type"] == "choice"
        assert item.get("format") != "xml", "a decomposed EBSR part is a JSON choice item, not an envelope"
        assert item["interaction"]["maxChoices"] == 1, "each part is single-select"
        stem = _qs(item["interaction"]).get("prompt", "")
        assert stem.strip(), f"{rid}: decomposed EBSR part emitted with NO stem"
        assert "stimulusRef" in item, "each part is a guiding item carrying the stimulus-ref"
    # the two part prompts are distinct (Part A vs Part B) and non-cross-contaminated
    pa = _qs(emitted[0][1]["interaction"])["prompt"]
    pb = _qs(emitted[1][1]["interaction"])["prompt"]
    assert "Part A" in pa and "Part B" in pb


def test_ebsr_assembled_package_has_no_composite_envelope():
    """After assemble(), an EBSR guiding item yields TWO `-partA`/`-partB` choice items appearing as
    two separate "Guiding …" sections, and NO composite/raw-XML envelope item remains in the package.
    Each part has a resolvable correctResponse + stimulusRef; validate() returns []."""
    fx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "fixtures", "qti_all7_2026-06-16", "items", "sample-ebsr.xml")
    spec = arpack.adapt_qti_item(arpack.from_qti_xml(open(fx).read()))
    base = copy.deepcopy(arpack.SAMPLE)
    base["units"][0]["lessons"][0]["guiding"][0]["item"] = spec
    pkg = arpack.assemble(base)
    assert arpack.validate(pkg) == []
    items = {i["identifier"]: i for i in pkg["qti"]["items"]}
    assert "sample-ebsr-partA" in items and "sample-ebsr-partB" in items
    assert "sample-ebsr" not in items, "the composite EBSR item must NOT survive into the package"
    assert not any(i.get("format") == "xml" for i in pkg["qti"]["items"]), \
        "no XML-envelope/composite item may remain after EBSR decomposition"
    for pid in ("sample-ebsr-partA", "sample-ebsr-partB"):
        assert items[pid]["type"] == "choice"
        assert items[pid]["responseDeclarations"][0]["correctResponse"]["value"], \
            f"{pid}: must have a resolvable correctResponse"
        assert "stimulusRef" in items[pid]
    secs = pkg["qti"]["tests"][0]["qti-test-part"][0]["qti-assessment-section"]
    guiding = [s for s in secs if s["title"].startswith("Guiding")]
    part_secs = [s for s in guiding
                 if s["qti-assessment-item-ref"][0]["identifier"].startswith("sample-ebsr-part")]
    assert len(part_secs) == 2, "the two EBSR parts appear as two separate Guiding sections"


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
