"""QTI 3.0 parsing tests for arpack — the single source of truth for ingesting Mayank's items.

Covers: format auto-detection for the families exercised here (choice/msq/ebsr/text-entry); see
test_all7_fixture.py for the wider format set. Plus the fail-closed answer-key bridge,
and the hardened prompt/choice extraction edge cases (feedback-in-choice, div.stem stems,
multi-paragraph/MathML choices, namespace quirks).
"""
import pytest

import arpack

QN = 'xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0"'


def _item(body, *, ident="it1", title="T", extra_decl="", stim=""):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<qti-assessment-item {QN} identifier="{ident}" title="{title}">
  {extra_decl}
  {stim}
  <qti-item-body>{body}</qti-item-body>
</qti-assessment-item>'''


# ───────────────────────── single-select MCQ (the live-export shape) ─────────────────────────
def test_mcq_single_select():
    xml = _item(
        '<qti-choice-interaction response-identifier="RESPONSE" max-choices="1">'
        '<qti-prompt>What is 2+2?</qti-prompt>'
        '<qti-simple-choice identifier="A">3</qti-simple-choice>'
        '<qti-simple-choice identifier="B">4</qti-simple-choice>'
        '<qti-simple-choice identifier="C">5</qti-simple-choice>'
        '<qti-simple-choice identifier="D">6</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>B</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    assert p["format"] == "choice"
    assert p["prompt"] == "What is 2+2?"
    assert [c["text"] for c in p["choices"]] == ["3", "4", "5", "6"]
    assert p["correct_id"] == "B"
    assert p["max_choices"] == 1
    adapted = arpack.adapt_qti_item(p)
    assert adapted["correct_index"] == 1


# ───────────────────────── multi-select MSQ (Mayank's fixture proves this) ──────────────────────
def test_msq_multi_select():
    xml = _item(
        '<qti-choice-interaction response-identifier="RESPONSE" max-choices="0">'
        '<qti-prompt>Pick the primes.</qti-prompt>'
        '<qti-simple-choice identifier="A">2</qti-simple-choice>'
        '<qti-simple-choice identifier="B">4</qti-simple-choice>'
        '<qti-simple-choice identifier="C">7</qti-simple-choice>'
        '<qti-simple-choice identifier="D">9</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="multiple" '
                   'base-type="identifier"><qti-correct-response>'
                   '<qti-value>A</qti-value><qti-value>C</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    assert p["correct_ids"] == ["A", "C"]
    assert p["max_choices"] == 0   # unlimited == multi
    adapted = arpack.adapt_qti_item(p)
    assert adapted["correct_indices"] == [0, 2]


# ───────────────────────── Mayank's div.stem stem (no qti-prompt) ───────────────────────────────
def test_div_stem_prompt_extraction():
    xml = _item(
        '<div class="stem"><p>Using the passage, what is the main idea?</p></div>'
        '<qti-choice-interaction response-identifier="RESPONSE" max-choices="1">'
        '<qti-simple-choice identifier="A">Cats</qti-simple-choice>'
        '<qti-simple-choice identifier="B">Dogs</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>A</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    assert p["prompt"] == "Using the passage, what is the main idea?"
    # the option text must NOT leak into the prompt
    assert "Cats" not in p["prompt"] and "Dogs" not in p["prompt"]


# ───────────────────────── feedback nested in a choice (answer split around it) ─────────────────
def test_feedback_in_choice_is_excised():
    xml = _item(
        '<qti-choice-interaction response-identifier="RESPONSE" max-choices="1">'
        '<qti-prompt>Q?</qti-prompt>'
        '<qti-simple-choice identifier="A">Milk'
        '<qti-feedback-inline>Correct! great job</qti-feedback-inline>'
        ' is the answer</qti-simple-choice>'
        '<qti-simple-choice identifier="B">Rocks</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>A</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    a = p["choices"][0]["text"]
    assert "Milk" in a and "is the answer" in a
    assert "Correct" not in a, "feedback body must be excised from choice text"


# ───────────────────────── fail-closed answer key: correct id not among choices ─────────────────
def test_adapt_raises_when_key_not_in_choices():
    xml = _item(
        '<qti-choice-interaction response-identifier="RESPONSE" max-choices="1">'
        '<qti-prompt>Q?</qti-prompt>'
        '<qti-simple-choice identifier="A">x</qti-simple-choice>'
        '<qti-simple-choice identifier="B">y</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>ZZZ</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    with pytest.raises(ValueError):
        arpack.adapt_qti_item(p)


# ───────────────────────── EBSR (two choice interactions == 2-part) ─────────────────────────────
def test_ebsr_detected_and_parsed():
    xml = _item(
        '<qti-choice-interaction response-identifier="RESP_A" max-choices="1">'
        '<qti-prompt>Part A claim</qti-prompt>'
        '<qti-simple-choice identifier="A1">claim1</qti-simple-choice>'
        '<qti-simple-choice identifier="A2">claim2</qti-simple-choice>'
        '</qti-choice-interaction>'
        '<qti-choice-interaction response-identifier="RESP_B" max-choices="1">'
        '<qti-prompt>Part B evidence</qti-prompt>'
        '<qti-simple-choice identifier="B1">evid1</qti-simple-choice>'
        '<qti-simple-choice identifier="B2">evid2</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESP_A" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>A1</qti-value>'
                   '</qti-correct-response></qti-response-declaration>'
                   '<qti-response-declaration identifier="RESP_B" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>B2</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    assert p["format"] == "ebsr"
    assert len(p["ebsr_parts"]) == 2
    assert p["ebsr_parts"][0]["correct_indices"] == [0]
    assert p["ebsr_parts"][1]["correct_indices"] == [1]


# ───────────────────────── text-entry (fill-in): literal answers, no choice ids ─────────────────
def test_text_entry_format():
    xml = _item(
        '<p>The capital of France is <qti-text-entry-interaction '
        'response-identifier="RESPONSE"/>.</p>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="single" '
                   'base-type="string"><qti-correct-response><qti-value>Paris</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    assert p["format"] == "text-entry"
    assert p["answers"] == ["Paris"]
    adapted = arpack.adapt_qti_item(p)
    assert adapted["format"] == "text-entry"


# ───────────────────────── stimulus parsing: inner HTML of qti-stimulus-body ────────────────────
def test_stimulus_html_extraction_preserves_https():
    xml = f'''<?xml version="1.0"?>
<qti-assessment-stimulus {QN} identifier="stim1" title="Leaves">
  <qti-stimulus-body><div><h1>Leaves</h1>
  <p>See <a href="https://example.com/x">link</a>.</p></div></qti-stimulus-body>
</qti-assessment-stimulus>'''
    s = arpack.from_qti_stimulus_xml(xml)
    assert s["identifier"] == "stim1"
    assert s["title"] == "Leaves"
    # the colon-bearing scheme must survive the namespace scrub
    assert "https://example.com/x" in s["html"]
    assert "<h1>Leaves</h1>" in s["html"]


# ───────────────────────── role auto-inference from a stimulus-ref ─────────────────────────────
def test_role_inferred_guiding_when_stimulus_ref_present():
    xml = _item(
        '<qti-choice-interaction response-identifier="RESPONSE" max-choices="1">'
        '<qti-prompt>Q?</qti-prompt>'
        '<qti-simple-choice identifier="A">x</qti-simple-choice>'
        '<qti-simple-choice identifier="B">y</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>A</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
        stim='<qti-assessment-stimulus-ref identifier="stimX" href="stimuli/stimX.xml"/>',
    )
    p = arpack.from_qti_xml(xml)
    assert p["role"] == "guiding"
    assert p["stimulus_id"] == "stimX"


def test_role_inferred_quiz_when_no_stimulus_ref():
    xml = _item(
        '<qti-choice-interaction response-identifier="RESPONSE" max-choices="1">'
        '<qti-prompt>Q?</qti-prompt>'
        '<qti-simple-choice identifier="A">x</qti-simple-choice>'
        '<qti-simple-choice identifier="B">y</qti-simple-choice>'
        '</qti-choice-interaction>',
        extra_decl='<qti-response-declaration identifier="RESPONSE" cardinality="single" '
                   'base-type="identifier"><qti-correct-response><qti-value>A</qti-value>'
                   '</qti-correct-response></qti-response-declaration>',
    )
    p = arpack.from_qti_xml(xml)
    assert p["role"] == "quiz"


# ───────────────────────── per-format validator: bad items rejected ────────────────────────────
def test_validate_item_rejects_unknown_type():
    errs = arpack._validate_item({"identifier": "x", "type": "not-a-real-format"})
    assert errs and "not an accepted" in errs[0]


def test_validate_item_mcq_needs_resolvable_key():
    item = {
        "identifier": "x", "type": "choice",
        "interaction": {"choices": [{"identifier": "A"}, {"identifier": "B"}]},
        "responseDeclarations": [{"cardinality": "single",
                                  "correctResponse": {"value": ["NOPE"]}}],
    }
    errs = arpack._validate_item(item)
    assert any("not among its options" in e for e in errs)
